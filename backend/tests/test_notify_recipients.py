"""T-4106: получатели видов заявок — очередь и назначение (FR-306, FR-308, FR-309, FR-310, FR-314, FR-315).

Сценарии 1-3 спеки среза 004. Настоящие действия сервис-деска (создание тремя каналами, передача, смена
категории, назначение, групповое назначение, открытие заново) идут внутри `django_capture_on_commit_callbacks(
execute=True)`: подписчики `notify` работают после фиксации и читают заявку из базы (CONTRACT-004 § 4.3, решение
E9). Проверяются записи `Notification` (`kind`, `user`, `object_ref`, `url`); доставки здесь не проверяются (T-4109).
Имена кода среза 004 внутри тестов (шапка CONTRACT-004): модели — через `support.model`.
"""
import importlib
import logging
import secrets

import pytest
from django.utils import timezone

from tests import factories, support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

NEW_IN_QUEUE = "servicedesk.new_in_queue"
ASSIGNED = "servicedesk.assigned"


# --- помощники только этого файла -------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.servicedesk.services.{name}")


def _queue(name: str | None = None, *, parent=None):
    """Отмеченный очередью узел с уникальным названием."""
    return sd.make_queue(org.make_unit(name or f"Очередь {secrets.token_hex(3)}", parent=parent))


def _desk(settings):
    """Приём заявок открыт, очередь по умолчанию задана; возвращает её `Queue`."""
    settings.SERVICEDESK_MAILBOX = "tickets@stand.test"
    settings.DEFAULT_FROM_EMAIL = "portal@corp.test"
    default = _queue()
    sd.configure_servicedesk(domains=["corp.test"], default_queue=default)
    return default


def _member(unit, name: str | None = None, *, mark: str = ""):
    """Сотрудник, состоящий в узле (`mark` — `""`, `"head"`, `"deputy"`)."""
    user = support.make_employee(full_name=name) if name else support.make_employee()
    org.make_member(user, unit, mark=mark)
    return user


def _fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


def _ref(ticket) -> str:
    return f"servicedesk.ticket:{ticket.pk}"


def _notes(ticket=None, kind: str | None = None):
    """Записи `Notification`: по заявке (`object_ref`) и виду."""
    notes = model("notify.Notification").objects.all()
    if ticket is not None:
        notes = notes.filter(object_ref=_ref(ticket))
    if kind is not None:
        notes = notes.filter(kind=kind)
    return notes


def _users(ticket, kind: str) -> list:
    """Номера получателей вида по заявке, по возрастанию; повтор у одного получателя виден как повтор номера."""
    return sorted(_notes(ticket, kind).values_list("user_id", flat=True))


def _ids(*users) -> list:
    return sorted(user.pk for user in users)


def _no_bus_errors(caplog) -> None:
    """Решение 24 задач: сбоев подписчиков шины в журнале приложения нет."""
    bad = [r for r in caplog.records if r.name == "apps.core.events" and r.levelno >= logging.ERROR]
    assert not bad, [r.getMessage() for r in bad]


def _manual_source():
    return model("servicedesk.Source").objects.filter(system_code="").order_by("order", "id").first()


def _create_mail(**kw):
    tickets = _svc("tickets")
    kw.setdefault("subject", "Не печатает принтер")
    kw.setdefault("text", "Принтер на втором этаже не печатает")
    kw.setdefault("requester_email", factories.new_email("req").lower())
    kw.setdefault("inbound_id", sd.make_inbound().pk)
    return tickets.create(channel=tickets.MAIL, **kw).ticket


def _create_staff(queue, creator, *, take: bool = False, category=None):
    tickets = _svc("tickets")
    return tickets.create(
        channel=tickets.STAFF, subject="Заявка по звонку", text="Звонили", requester_email=factories.new_email("req"),
        queue_id=queue.unit_id, source=_manual_source(), created_by=creator, take_by=creator if take else None,
        category=category).ticket


def _closed(queue, *, assignee=None):
    """Закрытая заявка с первым письмом заявителя."""
    ticket = sd.make_ticket(queue=queue, kind="closed", closed_at=timezone.now(), resolution="Готово",
                            assignee=assignee, assigned_once=assignee is not None)
    sd.make_entry(ticket, "incoming", text="Первое письмо")
    return ticket


def _can_work(user, ticket) -> bool:
    """Заявка видна сотруднику по доступу среза 003 (кэш доступа не берётся: объект пользователя перечитан)."""
    access = _svc("access")
    return access.can_work(_fresh(user), _fresh(ticket))


# --- прямые участники узла-очереди (план, «События и получатели»; § 4.1) ------------------------------

def test_ticket_created_by_mail_without_assignee_notifies_direct_members_of_queue(
        settings, django_capture_on_commit_callbacks, caplog):
    """FR-308: заявка из письма без ответственного — «Новая заявка в моей очереди» каждому прямому участнику
    очереди по одной записи (вид, ссылка `/tickets/<номер>/`, `object_ref`); участник чужой очереди, сотрудник вне
    очередей и заявитель ничего не получают; «Мне назначили» нет."""
    queue = _desk(settings)
    first, second = _member(queue.unit), _member(queue.unit)
    foreign = _member(_queue().unit)
    outsider = support.make_employee()

    with django_capture_on_commit_callbacks(execute=True):
        ticket = _create_mail()

    assert _fresh(ticket).queue_id == queue.unit_id and _fresh(ticket).assignee_id is None
    assert _users(ticket, NEW_IN_QUEUE) == _ids(first, second)
    for note in _notes(ticket, NEW_IN_QUEUE):
        assert note.url == f"/tickets/{ticket.number}/" and note.object_ref == _ref(ticket)
    assert _users(ticket, ASSIGNED) == []
    assert not _notes().filter(user__in=[foreign, outsider]).exists()
    _no_bus_errors(caplog)


def test_direct_members_include_concurrent_head_and_deputy_of_queue_node():
    """FR-308: `direct_members(узел)` — члены самого узла: совместитель, руководитель и заместитель этого узла входят
    своим членством; порядок `(full_name, id)`, без повторов."""
    structure = importlib.import_module("apps.org.services.structure")
    unit = _queue().unit
    other = org.make_unit()
    concurrent = _member(unit, "Вторников Вадим")
    org.make_member(concurrent, other)
    head = _member(unit, "Главов Глеб", mark="head")
    deputy = _member(unit, "Аркадьев Аркадий", mark="deputy")
    plain = _member(unit, "Простов Павел")

    people = structure.direct_members(unit.pk)

    assert [person.id for person in people] == [deputy.pk, concurrent.pk, head.pk, plain.pk]
    assert [person.full_name for person in people] == sorted(person.full_name for person in people)
    assert [person.id for person in structure.direct_members(other.pk)] == [concurrent.pk]


def test_direct_members_exclude_upper_node_head_and_all_tickets_holder_without_membership():
    """FR-308: руководитель и заместитель вышестоящего узла, держатель «Все заявки» без членства и участник вложенного
    узла в `direct_members` не входят; несуществующий узел — пустой список."""
    structure = importlib.import_module("apps.org.services.structure")
    upper = org.make_unit()
    queue = _queue(parent=upper)
    nested = org.make_unit(parent=queue.unit)
    member = _member(queue.unit)
    upper_head = _member(upper, mark="head")
    upper_deputy = _member(upper, mark="deputy")
    holder = support.make_with_permissions("servicedesk.all")
    nested_member = _member(nested)

    ids = [person.id for person in structure.direct_members(queue.unit.pk)]

    assert ids == [member.pk]
    assert not {upper_head.pk, upper_deputy.pk, holder.pk, nested_member.pk} & set(ids)
    missing = model("org.Unit").objects.order_by("-id").values_list("id", flat=True).first() + 1000
    assert structure.direct_members(missing) == []


def test_new_in_queue_not_sent_to_upper_head_or_all_tickets_holder_but_ticket_visible_to_them(
        settings, django_capture_on_commit_callbacks, caplog):
    """FR-308, FR-314: руководитель вышестоящего узла и держатель «Все заявки» уведомления «Новая заявка» не получают
    (никакого уведомления о заявке), но заявка им видна по доступу среза 003 — `access.can_work` для них истинно."""
    _desk(settings)
    upper = org.make_unit()
    queue = _queue(parent=upper)
    member = _member(queue.unit)
    upper_head = _member(upper, mark="head")
    holder = support.make_with_permissions("servicedesk.all")
    sd.configure_servicedesk(default_queue=queue)

    with django_capture_on_commit_callbacks(execute=True):
        ticket = _create_mail()

    assert _fresh(ticket).queue_id == queue.unit_id
    assert _users(ticket, NEW_IN_QUEUE) == _ids(member)
    assert not _notes(ticket).filter(user__in=[upper_head, holder]).exists()
    assert _can_work(upper_head, ticket) and _can_work(holder, ticket)
    _no_bus_errors(caplog)


# --- создание заявки (FR-308, FR-310, FR-315) ----------------------------------------------------------

def test_ticket_created_by_form_notifies_direct_members(settings, django_capture_on_commit_callbacks, caplog):
    """FR-308: заявка с открытой формы (канал `form`, действующего сотрудника нет) без ответственного — «Новая заявка»
    всем прямым участникам очереди категории, руководителю и заместителю очереди тоже."""
    _desk(settings)
    queue = _queue()
    member = _member(queue.unit)
    head = _member(queue.unit, mark="head")
    deputy = _member(queue.unit, mark="deputy")
    foreign = _member(_queue().unit)
    category = sd.make_category(queue=queue, on_form=True)
    tickets = _svc("tickets")

    with django_capture_on_commit_callbacks(execute=True):
        ticket = tickets.create(
            channel=tickets.FORM, subject="Заявка с формы", text="Не работает вход", category=category,
            requester_email=factories.new_email("req").lower(), consent_at=timezone.now(), ip="198.51.100.7").ticket

    assert _fresh(ticket).queue_id == queue.unit_id and _fresh(ticket).assignee_id is None
    assert _users(ticket, NEW_IN_QUEUE) == _ids(member, head, deputy)
    assert _users(ticket, ASSIGNED) == []
    assert not _notes(ticket).filter(user=foreign).exists()
    _no_bus_errors(caplog)


def test_ticket_created_by_staff_without_take_notifies_other_direct_members_not_creator(
        settings, django_capture_on_commit_callbacks, caplog):
    """FR-308, FR-315: исполнитель завёл заявку без «Взять себе» — «Новая заявка» получают остальные прямые участники
    очереди, сам создатель (он тоже участник очереди) — нет."""
    _desk(settings)
    queue = _queue()
    creator = _member(queue.unit)
    colleague = _member(queue.unit)
    head = _member(queue.unit, mark="head")

    with django_capture_on_commit_callbacks(execute=True):
        ticket = _create_staff(queue, creator)

    assert _fresh(ticket).assignee_id is None
    assert _users(ticket, NEW_IN_QUEUE) == _ids(colleague, head)
    assert not _notes().filter(user=creator).exists()
    _no_bus_errors(caplog)


def test_ticket_created_by_staff_with_take_to_self_gives_nobody_assigned_or_new_in_queue(
        settings, django_capture_on_commit_callbacks, caplog):
    """FR-310, FR-315: «Взять себе» при создании — заявка с ответственным: «Новая заявка» не уходит (ответственный
    есть), «Мне назначили» создателю не уходит (назначил сам себе); других записей по заявке нет."""
    _desk(settings)
    queue = _queue()
    creator = _member(queue.unit)
    _member(queue.unit)

    with django_capture_on_commit_callbacks(execute=True):
        ticket = _create_staff(queue, creator, take=True)

    assert _fresh(ticket).assignee_id == creator.pk
    assert _users(ticket, NEW_IN_QUEUE) == [] and _users(ticket, ASSIGNED) == []
    assert not _notes(ticket).exists()
    _no_bus_errors(caplog)


def test_ticket_created_with_default_assignee_gives_assigned_and_no_new_in_queue(
        settings, django_capture_on_commit_callbacks, caplog):
    """FR-308, FR-310: заявка из письма с категорией, у которой есть ответственный по умолчанию (участник очереди),
    даёт ему «Мне назначили заявку»; «Новая заявка в моей очереди» не уходит никому, остальным участникам тоже."""
    _desk(settings)
    queue = _queue()
    default = _member(queue.unit)
    other = _member(queue.unit)
    category = sd.make_category(queue=queue, default_assignee=default)

    with django_capture_on_commit_callbacks(execute=True):
        ticket = _create_mail(category=category)

    assert _fresh(ticket).assignee_id == default.pk
    assert _users(ticket, ASSIGNED) == _ids(default)
    assert _users(ticket, NEW_IN_QUEUE) == []
    assert not _notes(ticket).filter(user=other).exists()
    _no_bus_errors(caplog)


def test_ticket_created_with_default_assignee_equal_to_creator_gives_nothing(
        settings, django_capture_on_commit_callbacks, caplog):
    """FR-310, FR-315: исполнитель завёл заявку, а ответственный по умолчанию категории — он сам: назначил не другой,
    поэтому «Мне назначили» нет; ответственный есть, поэтому «Новая заявка» тоже нет; записей по заявке нет."""
    _desk(settings)
    queue = _queue()
    creator = _member(queue.unit)
    _member(queue.unit)
    category = sd.make_category(queue=queue, default_assignee=creator)

    with django_capture_on_commit_callbacks(execute=True):
        ticket = _create_staff(queue, creator, category=category)

    assert _fresh(ticket).assignee_id == creator.pk
    assert not _notes(ticket).exists()
    _no_bus_errors(caplog)


# --- передача в очередь и смена категории (FR-308, FR-310, FR-315) --------------------------------------

def test_ticket_transferred_without_assignee_notifies_new_queue_direct_members_except_actor(
        settings, django_capture_on_commit_callbacks, caplog):
    """FR-308, FR-315: заявка без ответственного передана в другую очередь — «Новая заявка» получают прямые участники
    новой очереди, кроме передавшего (он состоит и в новой очереди); участники прежней очереди ничего не получают."""
    _desk(settings)
    old, new = _queue(), _queue()
    actor = _member(old.unit)
    org.make_member(actor, new.unit)
    old_member = _member(old.unit)
    first, second = _member(new.unit), _member(new.unit, mark="head")
    ticket = sd.make_ticket(queue=old)
    transfer = _svc("transfer")

    with django_capture_on_commit_callbacks(execute=True):
        transfer.transfer(ticket, new.unit_id, actor=actor)

    assert _fresh(ticket).queue_id == new.unit_id
    assert _users(ticket, NEW_IN_QUEUE) == _ids(first, second)
    assert not _notes(ticket).filter(user__in=[actor, old_member]).exists()
    _no_bus_errors(caplog)


def test_ticket_transferred_with_remaining_assignee_gives_no_new_in_queue_and_no_assigned(
        settings, django_capture_on_commit_callbacks, caplog):
    """FR-308: ответственный — участник и новой очереди, при передаче он остался: ни «Новой заявки», ни «Мне
    назначили» нет (его никто не назначал); записей по заявке нет ни у кого."""
    _desk(settings)
    old, new = _queue(), _queue()
    actor = _member(old.unit)
    assignee = _member(old.unit)
    org.make_member(assignee, new.unit)
    _member(new.unit)
    ticket = sd.make_ticket(queue=old, kind="in_progress", assignee=assignee, assigned_once=True)
    transfer = _svc("transfer")

    with django_capture_on_commit_callbacks(execute=True):
        transfer.transfer(ticket, new.unit_id, actor=actor)

    moved = _fresh(ticket)
    assert moved.queue_id == new.unit_id and moved.assignee_id == assignee.pk
    assert not _notes(ticket).exists()
    _no_bus_errors(caplog)


def test_category_change_with_default_assignee_gives_assigned_not_new_in_queue(
        settings, django_capture_on_commit_callbacks, caplog):
    """FR-308, FR-310 (решение E9): смена категории на категорию другой очереди с ответственным по умолчанию — заявка
    после действия в базе с ответственным, поэтому «Новая заявка» не уходит никому (участникам новой очереди тоже), а
    ответственный по умолчанию получает «Мне назначили заявку»."""
    _desk(settings)
    old, new = _queue(), _queue()
    actor = _member(old.unit)
    default = _member(new.unit)
    other = _member(new.unit)
    category = sd.make_category(queue=new, default_assignee=default)
    ticket = sd.make_ticket(queue=old)
    transfer = _svc("transfer")

    with django_capture_on_commit_callbacks(execute=True):
        transfer.change_category(ticket, category, confirmed=True, actor=actor)

    changed = _fresh(ticket)
    assert changed.queue_id == new.unit_id and changed.assignee_id == default.pk
    assert _users(ticket, ASSIGNED) == _ids(default)
    assert _users(ticket, NEW_IN_QUEUE) == []
    assert not _notes(ticket).filter(user__in=[actor, other]).exists()
    _no_bus_errors(caplog)


def test_category_change_with_non_member_assignee_and_no_default_gives_new_in_queue(
        settings, django_capture_on_commit_callbacks, caplog):
    """FR-308: смена категории на категорию другой очереди без ответственного по умолчанию — прежний ответственный не
    участник новой очереди и снят, заявка без ответственного: «Новая заявка» получают прямые участники новой очереди;
    «Мне назначили» (снятие ответственного) никому не уходит, снятому тоже."""
    _desk(settings)
    old, new = _queue(), _queue()
    actor = _member(old.unit)
    removed = _member(old.unit)
    first, second = _member(new.unit), _member(new.unit, mark="deputy")
    category = sd.make_category(queue=new)
    ticket = sd.make_ticket(queue=old, kind="in_progress", assignee=removed, assigned_once=True)
    transfer = _svc("transfer")

    with django_capture_on_commit_callbacks(execute=True):
        transfer.change_category(ticket, category, confirmed=True, actor=actor)

    changed = _fresh(ticket)
    assert changed.queue_id == new.unit_id and changed.assignee_id is None
    assert _users(ticket, NEW_IN_QUEUE) == _ids(first, second)
    assert _users(ticket, ASSIGNED) == []
    assert not _notes(ticket).filter(user__in=[actor, removed]).exists()
    _no_bus_errors(caplog)


# --- назначение (FR-306, FR-310, FR-315) ----------------------------------------------------------------

def test_assignee_changed_by_other_notifies_new_assignee(settings, django_capture_on_commit_callbacks, caplog):
    """FR-310: ответственного назначил другой сотрудник — «Мне назначили заявку» получает только новый ответственный
    (одна запись со ссылкой на заявку); назначивший и остальные участники очереди ничего не получают."""
    _desk(settings)
    queue = _queue()
    actor = _member(queue.unit)
    target = _member(queue.unit)
    bystander = _member(queue.unit)
    ticket = sd.make_ticket(queue=queue)
    assignment = _svc("assignment")

    with django_capture_on_commit_callbacks(execute=True):
        assignment.assign(ticket, target, actor=actor)

    assert _fresh(ticket).assignee_id == target.pk
    assert _users(ticket, ASSIGNED) == _ids(target)
    note = _notes(ticket, ASSIGNED).get()
    assert note.url == f"/tickets/{ticket.number}/" and note.object_ref == _ref(ticket)
    assert _users(ticket, NEW_IN_QUEUE) == []
    assert not _notes().filter(user__in=[actor, bystander]).exists()
    _no_bus_errors(caplog)


def test_take_to_self_gives_no_assigned_notification(settings, django_capture_on_commit_callbacks, caplog):
    """FR-310, FR-315: «Взять себе» уведомления не даёт: событие несёт `actor_id`, равный новому ответственному;
    записей по заявке нет ни у взявшего, ни у остальных."""
    _desk(settings)
    queue = _queue()
    actor = _member(queue.unit)
    _member(queue.unit)
    ticket = sd.make_ticket(queue=queue)
    assignment = _svc("assignment")

    with django_capture_on_commit_callbacks(execute=True):
        assignment.take(ticket, actor=actor)

    assert _fresh(ticket).assignee_id == actor.pk
    assert not _notes(ticket).exists()
    _no_bus_errors(caplog)


def test_group_assign_five_tickets_gives_five_separate_records(settings, django_capture_on_commit_callbacks, caplog):
    """FR-310, FR-306: групповое назначение пяти заявок одному сотруднику — пять отдельных записей «Мне назначили
    заявку» (по одной на заявку, без группировки), у каждой своя ссылка и `object_ref`; назначивший ничего не получает."""
    _desk(settings)
    queue = _queue()
    actor = _member(queue.unit)
    target = _member(queue.unit)
    tickets = [sd.make_ticket(queue=queue) for _ in range(5)]
    assignment = _svc("assignment")

    with django_capture_on_commit_callbacks(execute=True):
        assignment.bulk([ticket.number for ticket in tickets], "assign", actor=actor, user=target)

    assert all(_fresh(ticket).assignee_id == target.pk for ticket in tickets)
    notes = list(_notes(kind=ASSIGNED).filter(user=target))
    assert len(notes) == 5
    assert sorted(note.object_ref for note in notes) == sorted(_ref(ticket) for ticket in tickets)
    assert sorted(note.url for note in notes) == sorted(f"/tickets/{ticket.number}/" for ticket in tickets)
    assert not _notes().filter(user=actor).exists()
    assert _notes().count() == 5
    _no_bus_errors(caplog)


def test_clearing_assignee_gives_no_notification(settings, django_capture_on_commit_callbacks, caplog):
    """FR-310: снятие ответственного без передачи уведомления не даёт: ни «Мне назначили» (нового ответственного
    нет), ни «Новая заявка»; записей нет ни у снятого, ни у остальных."""
    _desk(settings)
    queue = _queue()
    actor = _member(queue.unit)
    removed = _member(queue.unit)
    _member(queue.unit)
    ticket = sd.make_ticket(queue=queue, kind="in_progress", assignee=removed, assigned_once=True)
    assignment = _svc("assignment")

    with django_capture_on_commit_callbacks(execute=True):
        assignment.unassign(ticket, actor=actor)

    assert _fresh(ticket).assignee_id is None
    assert not _notes(ticket).exists()
    _no_bus_errors(caplog)


# --- открытие заявки заново (FR-309, FR-315) ------------------------------------------------------------

def test_ticket_reopened_by_mail_without_assignee_notifies_direct_members_only_of_queue_after_move_to_default(
        settings, django_capture_on_commit_callbacks, caplog):
    """FR-309: письмо заявителя открыло закрытую заявку без ответственного, а её узел больше не очередь — заявка ушла
    в очередь по умолчанию; «Новая заявка» получают прямые участники именно этой очереди (по состоянию в базе после
    действия), участники прежнего узла и руководитель вышестоящего узла — нет."""
    default = _desk(settings)
    gone = _queue()
    old_member = _member(gone.unit)
    first, head = _member(default.unit), _member(default.unit, mark="head")
    ticket = _closed(gone)
    admin = support.make_admin()
    _svc("queues").unmark(gone.unit_id, actor=admin)
    closing = _svc("closing")

    with django_capture_on_commit_callbacks(execute=True):
        closing.reopen(_fresh(ticket), actor=None, via="mail")

    reopened = _fresh(ticket)
    assert reopened.kind == "in_progress" and reopened.queue_id == default.unit_id and reopened.assignee_id is None
    assert _users(ticket, NEW_IN_QUEUE) == _ids(first, head)
    assert not _notes(ticket).filter(user=old_member).exists()
    _no_bus_errors(caplog)


def test_ticket_reopened_manually_without_assignee_notifies_direct_members_except_opener(
        settings, django_capture_on_commit_callbacks, caplog):
    """FR-309, FR-315: сотрудник открыл закрытую заявку без ответственного вручную — «Новая заявка» получают прямые
    участники узла, кроме открывшего."""
    _desk(settings)
    queue = _queue()
    opener = _member(queue.unit)
    colleague = _member(queue.unit)
    head = _member(queue.unit, mark="head")
    ticket = _closed(queue)
    closing = _svc("closing")

    with django_capture_on_commit_callbacks(execute=True):
        closing.reopen(_fresh(ticket), actor=opener)

    reopened = _fresh(ticket)
    assert reopened.kind == "in_progress" and reopened.assignee_id is None
    assert _users(ticket, NEW_IN_QUEUE) == _ids(colleague, head)
    assert not _notes().filter(user=opener).exists()
    _no_bus_errors(caplog)


def test_ticket_reopened_with_assignee_gives_no_new_in_queue(settings, django_capture_on_commit_callbacks, caplog):
    """FR-309: открытая заново заявка сохранила ответственного (он участник очереди) — «Новой заявки» нет ни при письме
    заявителя, ни при ручном открытии; «Мне назначили» тоже нет (никто не назначал); записей по заявке нет."""
    _desk(settings)
    queue = _queue()
    assignee = _member(queue.unit)
    opener = _member(queue.unit)
    _member(queue.unit, mark="head")
    by_mail = _closed(queue, assignee=assignee)
    manual = _closed(queue, assignee=assignee)
    closing = _svc("closing")

    with django_capture_on_commit_callbacks(execute=True):
        closing.reopen(_fresh(by_mail), actor=None, via="mail")
    with django_capture_on_commit_callbacks(execute=True):
        closing.reopen(_fresh(manual), actor=opener)

    for ticket in (by_mail, manual):
        reopened = _fresh(ticket)
        assert reopened.kind == "in_progress" and reopened.assignee_id == assignee.pk
        assert not _notes(ticket).exists()
    _no_bus_errors(caplog)


# --- действующий сотрудник (FR-315) ---------------------------------------------------------------------

def test_actor_never_receives_notification_of_own_action(settings, django_capture_on_commit_callbacks, caplog):
    """FR-315: сотрудник, состоящий и в прежней, и в новой очереди и руководящий новой, сам завёл заявку, передал,
    сменил категорию, назначил и открыл заново — ни одной записи от своих действий у него нет, а другой участник тех же
    очередей получает «Новая заявка» по каждой из четырёх заявок без ответственного (создание, передача, смена
    категории, открытие)."""
    _desk(settings)
    old, new = _queue(), _queue()
    actor = _member(old.unit)
    org.make_member(actor, new.unit, mark="head")
    peer = _member(old.unit)
    org.make_member(peer, new.unit)
    target = _member(old.unit)
    category = sd.make_category(queue=new)
    transfer, assignment, closing = _svc("transfer"), _svc("assignment"), _svc("closing")
    moved = sd.make_ticket(queue=old)
    recategorized = sd.make_ticket(queue=old)
    assigned = sd.make_ticket(queue=old)
    closed = _closed(old)

    with django_capture_on_commit_callbacks(execute=True):
        created = _create_staff(old, actor)
    with django_capture_on_commit_callbacks(execute=True):
        transfer.transfer(moved, new.unit_id, actor=actor)
    with django_capture_on_commit_callbacks(execute=True):
        transfer.change_category(recategorized, category, confirmed=True, actor=actor)
    with django_capture_on_commit_callbacks(execute=True):
        assignment.assign(assigned, target, actor=actor)
    with django_capture_on_commit_callbacks(execute=True):
        closing.reopen(_fresh(closed), actor=actor)

    assert not _notes().filter(user=actor).exists()
    refs = {note.object_ref for note in _notes(kind=NEW_IN_QUEUE).filter(user=peer)}
    assert refs == {_ref(created), _ref(moved), _ref(recategorized), _ref(closed)}
    assert _users(assigned, ASSIGNED) == _ids(target)
    _no_bus_errors(caplog)
