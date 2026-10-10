"""T-4103: события сервис-деска — поле `actor_id` и событие `reply_received` (FR-313). Сценарии 2, 3, 4 и 7 спеки среза 004.

Событие шины должно нести достаточно данных, чтобы решить, кому и о чём уведомлять (CONTRACT-004 § 4.2): кто сделал
(`actor_id`), по какому каналу создана заявка (`channel`), как и от кого пришло письмо (`via`, `author_kind`,
`entry_id`). Действия выполняют настоящие службы сервис-деска (`tickets`, `assignment`, `transfer`, `closing`,
`reconcile`, `intake`), события ловит фикстура `bus_spy`; подписчики шины идут после фиксации, поэтому действие —
внутри `django_capture_on_commit_callbacks(execute=True)`. Имена кода среза 004 внутри тестов импортируются: сбор
проходит до появления кода.
"""
import secrets

import pytest
from django.utils import timezone

from tests import support, support_org as org, support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

CREATED = "servicedesk.ticket_created"
CHANGED = "servicedesk.assignee_changed"
REPLY = "servicedesk.reply_received"
CLOSED = "servicedesk.ticket_closed"
DOMAIN = "corp.test"
MAILBOX = "tickets@stand.test"
OLD_FIELDS = ("number", "queue_id", "assignee_before_id", "assignee_after_id")


# --- помощники только этого файла ------------------------------------------------------------------

def _tickets():
    from apps.servicedesk.services import tickets
    return tickets


def _svc(name: str):
    import importlib
    return importlib.import_module(f"apps.servicedesk.services.{name}")


def _spy(bus_spy) -> None:
    bus_spy.listen(CREATED, CHANGED, REPLY, CLOSED)


def _setup_desk():
    """Очередь по умолчанию и домен: приём открыт."""
    queue = sd.make_queue()
    sd.configure_servicedesk(domains=[DOMAIN], default_queue=queue)
    return queue


def _member(unit, **extra):
    user = support.make_employee(**extra)
    org.make_member(user, unit)
    return user


def _fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


def _of(bus_spy, name: str, ticket) -> list:
    """Вызовы события `name` по заявке `ticket` (по номеру) в порядке публикации."""
    return [c for c in bus_spy.calls(name) if c["number"] == ticket.number]


def _one(bus_spy, name: str, ticket) -> dict:
    calls = _of(bus_spy, name, ticket)
    assert len(calls) == 1, f"ожидали одно событие {name} по заявке {ticket.number}, получили {len(calls)}"
    return calls[0]


def _expect(call: dict, **want) -> None:
    for field, value in want.items():
        assert field in call, f"в данных события нет поля {field}: {sorted(call)}"
        assert call[field] == value, f"{field}: ожидали {value!r}, получили {call[field]!r}"


def _manual_source():
    return model("servicedesk.Source").objects.filter(system_code="").order_by("id").first()


def _create(channel: str, **kw):
    """`tickets.create` с обязательными аргументами; для письма — со строкой входящего письма."""
    tickets = _tickets()
    kw.setdefault("subject", "Не печатает принтер")
    kw.setdefault("text", "Принтер на втором этаже не печатает")
    kw.setdefault("requester_email", f"req-{secrets.token_hex(3)}@{DOMAIN}")
    if channel == tickets.MAIL:
        kw.setdefault("inbound_id", sd.make_inbound().pk)
    if channel == tickets.FORM:
        kw.setdefault("consent_at", timezone.now())
    if channel == tickets.STAFF:
        kw.setdefault("source", _manual_source())
    return tickets.create(channel=channel, **kw)


def _work_ticket(queue, assignee, **over):
    """Заявка в работе, у которой ответственный уже был."""
    return sd.make_ticket(queue=queue, kind="in_progress", assignee=assignee, assigned_once=True, **over)


def _closed_ticket(queue, *, days: int, requester, assignee=None):
    ticket = sd.make_ticket(queue=queue, requester=requester, kind="closed", closed_at=timezone.now(), closed_by=assignee,
                            resolution="Готово", assignee=assignee, assigned_once=assignee is not None)
    sd.make_entry(ticket, "incoming", text="Первое письмо")
    sd.backdate(ticket, "closed_at", days=days)
    return _fresh(ticket)


# --- создание заявки: ticket_created ---------------------------------------------------------------

def test_ticket_created_by_mail_has_channel_mail_and_no_actor(bus_spy, django_capture_on_commit_callbacks):
    """FR-313: заявка из письма — `ticket_created` с `channel="mail"`, `actor_id=None`, прежними полями; ответственного нет."""
    _spy(bus_spy)
    queue = _setup_desk()
    tickets = _tickets()
    with django_capture_on_commit_callbacks(execute=True):
        ticket = _create(tickets.MAIL).ticket
    call = _one(bus_spy, CREATED, ticket)
    _expect(call, queue_id=queue.unit_id, assignee_before_id=None, assignee_after_id=None, actor_id=None,
            channel="mail")
    assert not _of(bus_spy, CHANGED, ticket), "при создании отдельного assignee_changed нет"


def test_ticket_created_by_open_form_has_channel_form_and_no_actor(bus_spy, django_capture_on_commit_callbacks):
    """FR-313: заявка с открытой формы — `ticket_created` с `channel="form"`, `actor_id=None`; очередь — очередь категории."""
    _spy(bus_spy)
    _setup_desk()
    tickets = _tickets()
    category_queue = sd.make_queue()
    category = sd.make_category(queue=category_queue, on_form=True)
    with django_capture_on_commit_callbacks(execute=True):
        ticket = _create(tickets.FORM, category=category).ticket
    call = _one(bus_spy, CREATED, ticket)
    _expect(call, queue_id=category_queue.unit_id, assignee_before_id=None, assignee_after_id=None, actor_id=None,
            channel="form")


def test_ticket_created_by_staff_has_channel_staff_and_creator_actor(bus_spy, django_capture_on_commit_callbacks):
    """FR-313: заявка от исполнителя — `ticket_created` с `channel="staff"` и `actor_id` равным номеру создателя."""
    _spy(bus_spy)
    _setup_desk()
    tickets = _tickets()
    queue = sd.make_queue()
    creator = _member(queue.unit)
    category = sd.make_category(queue=queue)
    with django_capture_on_commit_callbacks(execute=True):
        ticket = _create(tickets.STAFF, category=category, created_by=creator).ticket
    call = _one(bus_spy, CREATED, ticket)
    _expect(call, queue_id=queue.unit_id, assignee_before_id=None, assignee_after_id=None, actor_id=creator.pk,
            channel="staff")


# --- ответственный: assignee_changed ---------------------------------------------------------------

def test_assignee_changed_by_other_employee_carries_that_actor(bus_spy, django_capture_on_commit_callbacks):
    """FR-313: назначение другим сотрудником — `actor_id` этого сотрудника, `assignee_after_id` — назначенный; повторное
    назначение — `assignee_before_id` прежний ответственный."""
    _spy(bus_spy)
    assignment = _svc("assignment")
    queue = sd.make_queue()
    actor, first, second = _member(queue.unit), _member(queue.unit), _member(queue.unit)
    ticket = sd.make_ticket(queue=queue)
    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.assign(ticket, first, actor=actor) is True
    call = _one(bus_spy, CHANGED, ticket)
    _expect(call, queue_id=queue.unit_id, assignee_before_id=None, assignee_after_id=first.pk, actor_id=actor.pk)
    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.assign(_fresh(ticket), second, actor=actor) is True
    calls = _of(bus_spy, CHANGED, ticket)
    assert len(calls) == 2
    _expect(calls[1], assignee_before_id=first.pk, assignee_after_id=second.pk, actor_id=actor.pk)


def test_take_to_self_event_has_actor_equal_to_new_assignee(bus_spy, django_capture_on_commit_callbacks):
    """FR-313: «Взять себе» — `actor_id` равен `assignee_after_id` (взявший); у заявки с другим ответственным
    `assignee_before_id` — прежний."""
    _spy(bus_spy)
    assignment = _svc("assignment")
    queue = sd.make_queue()
    me, other = _member(queue.unit), _member(queue.unit)
    free = sd.make_ticket(queue=queue)
    busy = _work_ticket(queue, other)
    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.take(free, actor=me) is True
        assert assignment.take(busy, actor=me) is True
    first = _one(bus_spy, CHANGED, free)
    _expect(first, assignee_before_id=None, assignee_after_id=me.pk, actor_id=me.pk)
    second = _one(bus_spy, CHANGED, busy)
    _expect(second, assignee_before_id=other.pk, assignee_after_id=me.pk, actor_id=me.pk)


def test_group_assign_publishes_event_with_actor_for_each_ticket(bus_spy, django_capture_on_commit_callbacks):
    """FR-313: групповое назначение — событие `assignee_changed` на каждую заявку, у всех `actor_id` исполнителя,
    `assignee_after_id` кандидата."""
    _spy(bus_spy)
    assignment = _svc("assignment")
    queue = sd.make_queue()
    actor, candidate = _member(queue.unit), _member(queue.unit)
    group = [sd.make_ticket(queue=queue, requester=sd.make_requester()) for _ in range(3)]
    numbers = [t.number for t in group]
    with django_capture_on_commit_callbacks(execute=True):
        result = assignment.bulk(numbers, "assign", actor=actor, user=candidate)
    assert result.done == numbers and result.skipped == []
    for ticket in group:
        call = _one(bus_spy, CHANGED, ticket)
        _expect(call, queue_id=queue.unit_id, assignee_before_id=None, assignee_after_id=candidate.pk,
                actor_id=actor.pk)


def test_default_assignee_on_create_and_on_category_change_carry_actor_of_the_action(
        bus_spy, django_capture_on_commit_callbacks):
    """FR-313 (решение E9): при создании ответственный по умолчанию виден только в `assignee_after_id` события
    `ticket_created` (с `actor_id` создателя, отдельного `assignee_changed` нет); при смене категории ответственного
    по умолчанию ставит `assignee_changed` с `actor_id` действующего сотрудника."""
    _spy(bus_spy)
    _setup_desk()
    tickets, transfer = _tickets(), _svc("transfer")
    # создание
    queue = sd.make_queue()
    creator, default = _member(queue.unit), _member(queue.unit)
    category = sd.make_category(queue=queue, default_assignee=default)
    with django_capture_on_commit_callbacks(execute=True):
        created = _create(tickets.STAFF, category=category, created_by=creator).ticket
    call = _one(bus_spy, CREATED, created)
    _expect(call, assignee_before_id=None, assignee_after_id=default.pk, actor_id=creator.pk, channel="staff")
    assert not _of(bus_spy, CHANGED, created), "при создании ответственный по умолчанию отдельного события не даёт"
    # смена категории
    first, second = sd.make_queue(), sd.make_queue()
    new_default = _member(second.unit)
    old = sd.make_category(queue=first)
    new = sd.make_category(queue=second, default_assignee=new_default)
    actor = support.make_with_permissions("servicedesk.all")
    ticket = sd.make_ticket(queue=first, category=old)
    with django_capture_on_commit_callbacks(execute=True):
        result = transfer.change_category(ticket, new, confirmed=True, actor=actor)
    assert result.applied is True and result.assignee_set is True
    call = _one(bus_spy, CHANGED, ticket)
    _expect(call, queue_id=second.unit_id, assignee_before_id=None, assignee_after_id=new_default.pk,
            actor_id=actor.pk)


def test_clear_assignee_event_carries_actor(bus_spy, django_capture_on_commit_callbacks):
    """FR-313: снятие ответственного вручную — `assignee_changed` с `assignee_after_id=None`, прежним
    `assignee_before_id` и `actor_id` снявшего."""
    _spy(bus_spy)
    assignment = _svc("assignment")
    queue = sd.make_queue()
    actor, holder = _member(queue.unit), _member(queue.unit)
    ticket = _work_ticket(queue, holder)
    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.unassign(ticket, actor=actor) is True
    call = _one(bus_spy, CHANGED, ticket)
    _expect(call, queue_id=queue.unit_id, assignee_before_id=holder.pk, assignee_after_id=None, actor_id=actor.pk)


def test_reconcile_assignee_change_has_actor_none(bus_spy, django_capture_on_commit_callbacks):
    """FR-313: сверка (человек потерял доступ к очереди) снимает ответственного событием `assignee_changed` с
    `actor_id=None`; ключ есть."""
    from apps.org.services import membership
    _spy(bus_spy)
    queue = sd.make_queue()
    admin = support.make_admin()
    user = _member(queue.unit)
    ticket = _work_ticket(queue, user)
    with django_capture_on_commit_callbacks(execute=True):
        membership.remove_member(user, queue.unit, actor=admin)
    assert _fresh(ticket).assignee_id is None
    call = _one(bus_spy, CHANGED, ticket)
    _expect(call, queue_id=queue.unit_id, assignee_before_id=user.pk, assignee_after_id=None, actor_id=None)


# --- закрытие: ticket_closed -----------------------------------------------------------------------

def test_ticket_closed_by_employee_carries_actor_and_autoclose_has_actor_key(
        bus_spy, django_capture_on_commit_callbacks):
    """FR-313 (решение 16 задач): закрытие сотрудником — `actor_id` его номер; автозакрытие — ключ `actor_id` есть и
    равен `None`; ответственный до и после — тот, кто был на момент закрытия."""
    _spy(bus_spy)
    closing = _svc("closing")
    queue = sd.make_queue()
    user = _member(queue.unit)
    ticket = _work_ticket(queue, user)
    status = model("servicedesk.Status").objects.get(kind="closed", is_default=True)
    with django_capture_on_commit_callbacks(execute=True):
        closing.close(ticket, status, "Решено", actor=user)
    call = _one(bus_spy, CLOSED, ticket)
    _expect(call, queue_id=queue.unit_id, assignee_before_id=user.pk, assignee_after_id=user.pk, actor_id=user.pk)

    waiting = sd.make_ticket(queue=queue, kind="waiting", waiting_since=timezone.now(), assignee=user,
                             assigned_once=True)
    sd.backdate(waiting, "waiting_since", days=8)
    with django_capture_on_commit_callbacks(execute=True):
        assert closing.autoclose_one(waiting.pk) is True
    auto = _one(bus_spy, CLOSED, waiting)
    assert "actor_id" in auto and auto["actor_id"] is None
    _expect(auto, queue_id=queue.unit_id, assignee_before_id=user.pk, assignee_after_id=user.pk)


# --- входящее письмо: reply_received ---------------------------------------------------------------

def test_reply_received_appended_from_requester_has_via_author_kind_and_entry_id(
        bus_spy, django_capture_on_commit_callbacks):
    """FR-313: письмо заявителя в открытую заявку — `reply_received` с `via="appended"`, `author_kind="requester"`,
    `entry_id` созданного элемента ленты; ответственный до и после — текущий."""
    _spy(bus_spy)
    tickets = _tickets()
    queue = sd.make_queue()
    user = _member(queue.unit)
    ticket = _work_ticket(queue, user)
    with django_capture_on_commit_callbacks(execute=True):
        entry = tickets.add_incoming(ticket, author_email=ticket.requester_email, text="Всё ещё не печатает")
    assert entry.kind == "incoming"
    call = _one(bus_spy, REPLY, ticket)
    _expect(call, queue_id=queue.unit_id, assignee_before_id=user.pk, assignee_after_id=user.pk,
            via="appended", author_kind="requester", entry_id=entry.pk)


def test_reply_received_from_copy_participant_has_author_kind_participant(
        bus_spy, django_capture_on_commit_callbacks):
    """FR-313: письмо участника из копии — `author_kind="participant"` (адрес автора не совпадает с адресом заявителя)."""
    _spy(bus_spy)
    tickets = _tickets()
    queue = sd.make_queue()
    ticket = sd.make_ticket(queue=queue)
    participant = sd.make_participant(ticket, f"partner-{secrets.token_hex(3)}@{DOMAIN}", name="Партнёр")
    assert participant.email != ticket.requester_email
    with django_capture_on_commit_callbacks(execute=True):
        entry = tickets.add_incoming(ticket, author_email=participant.email, author_name="Партнёр",
                                     text="Дополню от себя")
    call = _one(bus_spy, REPLY, ticket)
    _expect(call, via="appended", author_kind="participant", entry_id=entry.pk)


def test_reply_received_reopened_by_mail_has_via_reopened(
        settings, protected_root, bus_spy, django_capture_on_commit_callbacks):
    """FR-313: письмо заявителя к закрытой заявке в срок открывает её настоящим `intake`: `reply_received` с
    `via="reopened"`, `author_kind="requester"` и номером дописанного элемента."""
    from apps.servicedesk.services import intake
    _spy(bus_spy)
    settings.SERVICEDESK_MAILBOX = MAILBOX
    settings.DEFAULT_FROM_EMAIL = "portal@corp.test"
    sd.configure_servicedesk(domains=[DOMAIN], default_queue=sd.make_queue())
    queue = sd.make_queue()
    user = _member(queue.unit)
    requester = sd.make_requester(f"req-{secrets.token_hex(3)}@{DOMAIN}")
    ticket = _closed_ticket(queue, days=3, requester=requester, assignee=user)
    raw = sd.build_mail(from_addr=ticket.requester_email, to=[MAILBOX], subject=f"[#{ticket.number}] Ответ",
                        text="Не помогло")
    inbound = sd.make_inbound(size=len(raw), from_email=ticket.requester_email)
    folder = protected_root / "inbound"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{inbound.pk}.eml").write_bytes(raw)
    with django_capture_on_commit_callbacks(execute=True):
        assert intake.process(inbound.pk) == "reopened"
    entry = inbound.entries.get()
    call = _one(bus_spy, REPLY, ticket)
    _expect(call, queue_id=queue.unit_id, via="reopened", author_kind="requester", entry_id=entry.pk)


def test_add_incoming_via_parameter_defaults_to_appended(bus_spy, django_capture_on_commit_callbacks):
    """FR-313: параметр `via` у `tickets.add_incoming` по умолчанию `"appended"` (и явное значение работает); иное
    значение — `ValueError`."""
    _spy(bus_spy)
    tickets = _tickets()
    queue = sd.make_queue()
    ticket = sd.make_ticket(queue=queue)
    with django_capture_on_commit_callbacks(execute=True):
        tickets.add_incoming(ticket, author_email=ticket.requester_email, text="Без via")
        tickets.add_incoming(ticket, author_email=ticket.requester_email, text="Явный via", via="appended")
    calls = _of(bus_spy, REPLY, ticket)
    assert [c["via"] for c in calls] == ["appended", "appended"]
    with pytest.raises(ValueError):
        tickets.add_incoming(ticket, author_email=ticket.requester_email, text="Чужой via", via="bogus")


def test_reply_received_has_actor_none(bus_spy, django_capture_on_commit_callbacks):
    """FR-313 (решение 20 задач): у `reply_received` ключ `actor_id` есть и равен `None` (письмо — не действие
    сотрудника); `actor_id` не параметр помощника, а обязательные `via`, `author_kind`, `entry_id` — именованные."""
    _spy(bus_spy)
    tickets, events = _tickets(), _svc("events")
    ticket = sd.make_ticket(queue=sd.make_queue())
    with django_capture_on_commit_callbacks(execute=True):
        tickets.add_incoming(ticket, author_email=ticket.requester_email, text="Письмо")
    call = _one(bus_spy, REPLY, ticket)
    assert "actor_id" in call and call["actor_id"] is None
    with pytest.raises(TypeError):
        events.reply_received(ticket, via="appended", author_kind="requester", entry_id=1, actor_id=7)
    with pytest.raises(TypeError):
        events.reply_received(ticket)


# --- прежние поля ----------------------------------------------------------------------------------

def test_old_event_fields_are_kept_after_adding_new_ones(bus_spy, django_capture_on_commit_callbacks):
    """FR-313: у всех четырёх событий остаются прежние ключи `number`, `queue_id`, `assignee_before_id`,
    `assignee_after_id` с прежним смыслом; новые помощники без новых именованных параметров — `TypeError`
    (решение 20 задач)."""
    _spy(bus_spy)
    queue = _setup_desk()
    tickets, assignment, closing, events = _tickets(), _svc("assignment"), _svc("closing"), _svc("events")
    user = _member(queue.unit)
    status = model("servicedesk.Status").objects.get(kind="closed", is_default=True)
    with django_capture_on_commit_callbacks(execute=True):
        ticket = _create(tickets.MAIL).ticket
    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.take(_fresh(ticket), actor=user) is True
    with django_capture_on_commit_callbacks(execute=True):
        tickets.add_incoming(_fresh(ticket), author_email=ticket.requester_email, text="Ещё письмо")
    with django_capture_on_commit_callbacks(execute=True):
        closing.close(_fresh(ticket), status, "Решено", actor=user)

    created = _one(bus_spy, CREATED, ticket)
    changed = _one(bus_spy, CHANGED, ticket)
    reply = _one(bus_spy, REPLY, ticket)
    closed = _one(bus_spy, CLOSED, ticket)
    for call in (created, changed, reply, closed):
        for field in OLD_FIELDS:
            assert field in call, f"пропал прежний ключ {field}"
        _expect(call, number=ticket.number, queue_id=queue.unit_id)
    _expect(created, assignee_before_id=None, assignee_after_id=None)
    _expect(changed, assignee_before_id=None, assignee_after_id=user.pk)
    _expect(reply, assignee_before_id=user.pk, assignee_after_id=user.pk)
    _expect(closed, assignee_before_id=user.pk, assignee_after_id=user.pk)

    fresh = _fresh(ticket)
    with pytest.raises(TypeError):
        events.ticket_created(fresh)
    with pytest.raises(TypeError):
        events.assignee_changed(fresh, before_id=None, after_id=user.pk)
    with pytest.raises(TypeError):
        events.ticket_closed(fresh)
