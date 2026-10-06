"""T-3104: сверка ответственных и шина событий (FR-235). Сценарий 15 спеки среза 003.

Имена кода среза 003 (`apps.servicedesk…`, `apps.core.events`, `permissions_of(fresh=…)`) импортируются
внутри тестов: сбор проходит до появления кода. Правила — tests/CONTRACT-003.md (§ 3.1, 3.3, 4, 6.3, 6.12,
6.13, 7.1, 9.2, 9.3, 13, 14.5). Изменения доступа делаются службами `org` и ядра (CONTRACT.md,
CONTRACT-002), а не правкой базы; обработчик шины идёт после фиксации, поэтому действия обёрнуты в
`django_capture_on_commit_callbacks(execute=True)`. Заявки заводит `support_servicedesk.make_ticket` (ORM):
до сверки ответственный может стоять где угодно.
"""
import logging
from html.parser import HTMLParser

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests import factories, support, support_org as org, support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

REASON_TEXT = "ответственный снят: больше не участник очереди"
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- разбор разметки (помощник только этого файла) ---------------------------------------------------

class _El:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.kids = tag, attrs, parent, []

    def walk(self):
        yield self
        for kid in self.kids:
            if isinstance(kid, _El):
                yield from kid.walk()

    def text(self) -> str:
        parts = [kid if isinstance(kid, str) else kid.text() for kid in self.kids]
        return " ".join(" ".join(parts).split())

    def find_all(self, tag=None, **want):
        """Элементы (в том числе сам) с тегом `tag` и атрибутами `want` (`data_x` -> `data-x`)."""
        wanted = {key.replace("_", "-"): str(value) for key, value in want.items()}
        return [el for el in self.walk()
                if (tag is None or el.tag == tag) and all(el.attrs.get(k) == v for k, v in wanted.items())]

    def has_attr(self, name: str) -> bool:
        return any(name in el.attrs for el in self.walk())


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _El("#root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        el = _El(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.kids.append(el)
        if tag not in _VOID:
            self.cur = el

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(_El(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        if data.strip():
            self.cur.kids.append(data)


def _dom(response) -> _El:
    assert response.status_code == 200
    builder = _Builder()
    builder.feed(response.content.decode())
    return builder.root


# --- данные и действия (помощники только этого файла) ------------------------------------------------

def _staff(name: str, *, roles=()):
    """Сотрудник без пароля и без второго фактора (в систему не входит). Имя — одно слово: «Имя Фамилия» не зависит от порядка."""
    user = model("core.User").objects.create(email=factories.new_email(), full_name=name, state="active")
    if roles:
        user.roles.set(roles)
    return user


def _all_role():
    return factories.make_role(permissions=("servicedesk.all",))


def _queue(unit=None):
    return sd.make_queue(unit).unit


def _open(user, unit, **over):
    return sd.make_ticket(queue=unit, assignee=user, **over)


def _closed(user, unit, **over):
    return sd.make_ticket(queue=unit, assignee=user, kind="closed", closed_by=user, closed_at=timezone.now(),
                          resolution="Готово", **over)


def _fresh(ticket):
    return model("servicedesk.Ticket").objects.get(pk=ticket.pk)


def _assignee_id(ticket):
    return _fresh(ticket).assignee_id


def _reconciled(ticket):
    return list(model("servicedesk.TicketEntry").objects.filter(
        ticket=ticket, kind="event", event="assignee_reconciled").order_by("id"))


def _transfer(user, source, target, admin):
    from apps.org.services import membership
    assert membership.transfer_member(user, source, target, actor=admin) is True


def _remove(user, unit, admin):
    from apps.org.services import membership
    membership.remove_member(user, unit, actor=admin)


def _jobs(queue_name="maintenance", func="reconcile_assignees"):
    import django_rq
    return [job for job in django_rq.get_queue(queue_name).jobs if job.func_name == f"apps.servicedesk.tasks.{func}"]


def _ticket_row(dom, ticket) -> _El:
    rows = dom.find_all("tr", data_ticket=ticket.number)
    assert len(rows) == 1, f"в списке нет строки заявки {ticket.number}"
    return rows[0]


# --- что вызывает сверку -----------------------------------------------------------------------------

def test_transfer_removes_assignee_from_open_and_closed_tickets_of_lost_queues(django_capture_on_commit_callbacks):
    """FR-235: перевод из узла в узел — открытые и закрытые заявки очереди прежнего узла остаются в очереди без ответственного (сценарий 15.1); заявка очереди нового узла остаётся за ним."""
    admin, user = support.make_admin(), _staff("Сидоров")
    old, new = org.make_unit(), org.make_unit()
    old_q, new_q = _queue(old), _queue(new)
    org.make_member(user, old)
    open_old, closed_old, open_new = _open(user, old_q), _closed(user, old_q), _open(user, new_q)

    with django_capture_on_commit_callbacks(execute=True):
        _transfer(user, old, new, admin)

    for ticket in (open_old, closed_old):
        fresh = _fresh(ticket)
        assert fresh.assignee_id is None and fresh.queue_id == old_q.pk and fresh.kind == ticket.kind
        assert len(_reconciled(ticket)) == 1
    assert _fresh(closed_old).closed_by_id == user.pk
    assert _assignee_id(open_new) == user.pk and _reconciled(open_new) == []


def test_dismissal_removes_assignee_from_open_and_closed_tickets(django_capture_on_commit_callbacks):
    """FR-235: увольнение — ответственный снят со всех заявок, открытых и закрытых, в том числе чужих очередей; закрывший остаётся в `closed_by`."""
    from apps.org.services import people
    admin, user = support.make_admin(), _staff("Петров")
    unit, foreign = org.make_unit(), org.make_unit()
    org.make_member(user, unit)
    own_open, own_closed = _open(user, _queue(unit)), _closed(user, _queue(unit))
    foreign_open = _open(user, _queue(foreign))

    with django_capture_on_commit_callbacks(execute=True):
        people.dismiss(user, actor=admin)

    for ticket in (own_open, own_closed, foreign_open):
        assert _assignee_id(ticket) is None
        assert len(_reconciled(ticket)) == 1
    assert _fresh(own_closed).closed_by_id == user.pk


def test_removal_from_unit_removes_assignee_of_that_queue(django_capture_on_commit_callbacks):
    """FR-235: удаление из узла — заявки очереди этого узла остаются без ответственного, заявки очереди другого узла, где он ещё участник, остаются за ним."""
    admin, user = support.make_admin(), _staff("Орлов")
    left, kept = org.make_unit(), org.make_unit()
    org.make_member(user, left)
    org.make_member(user, kept)
    lost_open, lost_closed, stays = _open(user, _queue(left)), _closed(user, _queue(left)), _open(user, _queue(kept))

    with django_capture_on_commit_callbacks(execute=True):
        _remove(user, left, admin)

    assert _assignee_id(lost_open) is None and _assignee_id(lost_closed) is None
    assert len(_reconciled(lost_open)) == 1 and len(_reconciled(lost_closed)) == 1
    assert _assignee_id(stays) == user.pk and _reconciled(stays) == []


def test_unit_move_removes_assignee_who_was_head_of_former_upper_units(django_capture_on_commit_callbacks):
    """FR-235 (FR-232): очередь перенесена под другой отдел — руководитель и заместитель прежнего вышестоящего узла теряют её заявки; руководитель узла, общего для обоих мест, сохраняет (сценарий 15.6)."""
    from apps.org.services import structure
    admin = support.make_admin()
    tree = org.make_tree({"Верх": {"Старый": {"Очередь": {}}, "Новый": {}}})
    head, deputy, top_head = _staff("Волков"), _staff("Зайцев"), _staff("Лисицын")
    org.make_member(head, tree["Старый"], mark="head")
    org.make_member(deputy, tree["Старый"], mark="deputy")
    org.make_member(top_head, tree["Верх"], mark="head")
    queue = _queue(tree["Очередь"])
    by_head, by_deputy, by_top = _open(head, queue), _closed(deputy, queue), _open(top_head, queue)

    with django_capture_on_commit_callbacks(execute=True):
        structure.move_unit(tree["Очередь"], tree["Новый"], actor=admin)

    assert _assignee_id(by_head) is None and _assignee_id(by_deputy) is None
    assert len(_reconciled(by_head)) == 1 and len(_reconciled(by_deputy)) == 1
    assert _assignee_id(by_top) == top_head.pk and _reconciled(by_top) == []


def test_marks_change_removes_assignee_who_lost_head_or_deputy_mark(django_capture_on_commit_callbacks):
    """FR-235: смена руководителя и заместителя — потерявшие отметку лишаются заявок вложенной очереди, оставшийся руководитель сохраняет их."""
    from apps.org.services import membership
    admin = support.make_admin()
    tree = org.make_tree({"Отдел": {"Очередь": {}}})
    head, deputy, kept_head = _staff("Белов"), _staff("Громов"), _staff("Ершов")
    for person, mark in ((head, "head"), (deputy, "deputy"), (kept_head, "head")):
        org.make_member(person, tree["Отдел"], mark=mark)
    queue = _queue(tree["Очередь"])
    by_head, by_deputy, by_kept = _open(head, queue), _open(deputy, queue), _open(kept_head, queue)

    with django_capture_on_commit_callbacks(execute=True):
        membership.set_marks(tree["Отдел"], heads=[kept_head], deputies=[], actor=admin)

    assert _assignee_id(by_head) is None and _assignee_id(by_deputy) is None
    assert len(_reconciled(by_head)) == 1 and len(_reconciled(by_deputy)) == 1
    assert _assignee_id(by_kept) == kept_head.pk


def test_unit_roles_change_triggers_reconcile(django_capture_on_commit_callbacks):
    """FR-235: роль узла с правом «Все заявки» снята — участник узла теряет заявки чужих очередей и сохраняет заявки очереди своего узла."""
    from apps.org.services import unit_roles
    from apps.servicedesk.services import access
    admin, user = support.make_admin(), _staff("Котов")
    role, unit, foreign = _all_role(), org.make_unit(), org.make_unit()
    org.make_member(user, unit)
    org.make_unit_role(unit, role)
    assert access.scope(user, fresh=True).has_all is True
    foreign_open, foreign_closed = _open(user, _queue(foreign)), _closed(user, _queue(foreign))
    own = _open(user, _queue(unit))

    with django_capture_on_commit_callbacks(execute=True):
        unit_roles.set_unit_roles(unit, [], actor=admin)

    assert _assignee_id(foreign_open) is None and _assignee_id(foreign_closed) is None
    assert _assignee_id(own) == user.pk


def test_personal_roles_change_triggers_reconcile(django_capture_on_commit_callbacks):
    """FR-235: личная роль с правом «Все заявки» снята — ответственный без узлов теряет все свои заявки."""
    from apps.core.services import roles
    admin, role = support.make_admin(), _all_role()
    user = _staff("Рысин", roles=[role])
    queue = _queue()
    open_ticket, closed_ticket = _open(user, queue), _closed(user, queue)

    with django_capture_on_commit_callbacks(execute=True):
        roles.set_user_roles(user, [], actor=admin)

    assert _assignee_id(open_ticket) is None and _assignee_id(closed_ticket) is None
    assert len(_reconciled(open_ticket)) == 1


def test_role_rights_change_triggers_reconcile_for_all_with_tickets(django_capture_on_commit_callbacks):
    """FR-235: у роли отозвано право «Все заявки» — сверяются все, у кого есть заявки: держатели личной роли и держатель роли через узел."""
    from apps.core.services import roles
    admin, role = support.make_admin(), _all_role()
    personal_a, personal_b, via_unit = _staff("Аистов", roles=[role]), _staff("Бобров", roles=[role]), _staff("Вепрев")
    unit = org.make_unit()
    org.make_member(via_unit, unit)
    org.make_unit_role(unit, role)
    foreign = _queue()
    lost = [_open(personal_a, foreign), _closed(personal_b, foreign), _open(via_unit, foreign)]
    own = _open(via_unit, _queue(unit))

    with django_capture_on_commit_callbacks(execute=True):
        roles.update_role(role, role.name, [], actor=admin)

    assert [_assignee_id(ticket) for ticket in lost] == [None, None, None]
    assert _assignee_id(own) == via_unit.pk


# --- что делает сверка -------------------------------------------------------------------------------

def test_removed_assignee_leaves_feed_event_journal_entry_and_bus_event(bus_spy, django_capture_on_commit_callbacks):
    """FR-235: на каждую снятую заявку — событие ленты `assignee_reconciled`, запись журнала `ticket.assignee_removed` без автора с причиной и событие шины `servicedesk.assignee_changed`."""
    admin, user = support.make_admin(), _staff("Тихонов")
    old, new = org.make_unit(), org.make_unit()
    org.make_member(user, old)
    queue = _queue(old)
    ticket = _open(user, queue)
    bus_spy.listen("servicedesk.assignee_changed")

    with django_capture_on_commit_callbacks(execute=True):
        _transfer(user, old, new, admin)

    entries = _reconciled(ticket)
    assert len(entries) == 1
    assert entries[0].author_id is None
    assert entries[0].data["before"] == user.full_name and entries[0].data["before_id"] == user.pk
    journal = list(model("core.AuditEvent").objects.filter(action="ticket.assignee_removed", object_id=str(ticket.number)))
    assert len(journal) == 1
    assert journal[0].actor_id is None and journal[0].object_type == "ticket"
    assert journal[0].before["assignee"] == user.full_name and journal[0].before["assignee_id"] == user.pk
    assert journal[0].after["assignee"] == "" and journal[0].after["assignee_id"] is None
    assert journal[0].after["reason"] == "not_participant"
    assert bus_spy.calls("servicedesk.assignee_changed") == [
        {"number": ticket.number, "queue_id": queue.pk, "assignee_before_id": user.pk, "assignee_after_id": None}]


# --- кто остаётся участником ---------------------------------------------------------------------------

def test_concurrent_member_keeps_tickets_after_transfer(django_capture_on_commit_callbacks):
    """FR-235: совместитель, переведённый из основного отдела, остаётся участником очереди второго отдела — его заявки там за ним (сценарий 15.2); заявки очереди прежнего отдела сняты."""
    admin, user = support.make_admin(), _staff("Мухин")
    main, concurrent, target = org.make_unit(), org.make_unit(), org.make_unit()
    org.make_member(user, main)
    org.make_member(user, concurrent)
    lost, kept = _open(user, _queue(main)), _open(user, _queue(concurrent))

    with django_capture_on_commit_callbacks(execute=True):
        _transfer(user, main, target, admin)

    assert _assignee_id(lost) is None
    assert _assignee_id(kept) == user.pk and _reconciled(kept) == []


def test_head_of_upper_unit_keeps_tickets(django_capture_on_commit_callbacks):
    """FR-235 (FR-232): руководитель вышестоящего узла остаётся участником вложенной очереди — при удалении из другого узла его заявки вложенной и собственной очередей остаются за ним."""
    admin, head = support.make_admin(), _staff("Соколов")
    tree = org.make_tree({"Верх": {"Вложенная": {}}, "Другой": {}})
    org.make_member(head, tree["Верх"], mark="head")
    org.make_member(head, tree["Другой"])
    nested, upper, other = _open(head, _queue(tree["Вложенная"])), _open(head, _queue(tree["Верх"])), _open(head, _queue(tree["Другой"]))

    with django_capture_on_commit_callbacks(execute=True):
        _remove(head, tree["Другой"], admin)

    assert _assignee_id(nested) == head.pk and _assignee_id(upper) == head.pk
    assert _assignee_id(other) is None


def test_all_tickets_holder_keeps_tickets_of_foreign_queues(django_capture_on_commit_callbacks):
    """FR-235: держатель «Все заявки» участник каждой очереди — после удаления из узла заявки чужих и прежней очередей остаются за ним."""
    admin, role = support.make_admin(), _all_role()
    user, unit = _staff("Дроздов", roles=[role]), org.make_unit()
    org.make_member(user, unit)
    own, foreign_open, foreign_closed = _open(user, _queue(unit)), _open(user, _queue()), _closed(user, _queue())

    with django_capture_on_commit_callbacks(execute=True):
        _remove(user, unit, admin)

    for ticket in (own, foreign_open, foreign_closed):
        assert _assignee_id(ticket) == user.pk and _reconciled(ticket) == []


def test_revoking_all_tickets_right_removes_assignee_from_queues_where_not_participant(django_capture_on_commit_callbacks):
    """FR-235 (FR-233): право «Все заявки» у роли снято — с заявок очередей, где он не участник, ответственный снят и в ленте событие (сценарий 15.8)."""
    from apps.core.services import roles
    admin, role = support.make_admin(), _all_role()
    user, unit = _staff("Чернов", roles=[role]), org.make_unit()
    org.make_member(user, unit)
    foreign = _queue()
    foreign_open, foreign_closed = _open(user, foreign), _closed(user, foreign)

    with django_capture_on_commit_callbacks(execute=True):
        roles.update_role(role, role.name, [], actor=admin)

    for ticket in (foreign_open, foreign_closed):
        assert _assignee_id(ticket) is None
        entries = _reconciled(ticket)
        assert len(entries) == 1 and entries[0].data["before_id"] == user.pk


def test_revoking_all_tickets_right_keeps_tickets_of_queues_where_still_participant(django_capture_on_commit_callbacks):
    """FR-235: после снятия права «Все заявки» заявки очередей, где он остался участником (свой узел, вложенный узел под его руководством), остаются за ним."""
    from apps.core.services import roles
    admin, role = support.make_admin(), _all_role()
    user = _staff("Щукин", roles=[role])
    tree = org.make_tree({"Свой": {}, "Руководимый": {"Вложенный": {}}})
    org.make_member(user, tree["Свой"])
    org.make_member(user, tree["Руководимый"], mark="head")
    own, headed, nested = (_open(user, _queue(tree[name])) for name in ("Свой", "Руководимый", "Вложенный"))
    foreign = _open(user, _queue())

    with django_capture_on_commit_callbacks(execute=True):
        roles.set_user_roles(user, [], actor=admin)

    for ticket in (own, headed, nested):
        assert _assignee_id(ticket) == user.pk
    assert _assignee_id(foreign) is None


# --- устройство сверки -----------------------------------------------------------------------------

def test_employee_without_assigned_tickets_exits_with_single_query():
    """FR-235: у человека без заявок с ответственным сверка делает один запрос (проверка наличия заявок), без транзакции и записей."""
    from apps.servicedesk.services import reconcile
    user = _staff("Пустов")
    sd.make_ticket(queue=_queue())  # чужая заявка без ответственного

    with CaptureQueriesContext(connection) as queries:
        removed = reconcile.for_users([user.pk])

    assert removed == 0
    assert len(queries.captured_queries) == 1
    assert model("servicedesk.Ticket")._meta.db_table in queries.captured_queries[0]["sql"]
    assert not model("core.AuditEvent").objects.filter(action="ticket.assignee_removed").exists()


def test_rights_read_without_cache_by_fresh_flag():
    """FR-235: `permissions_of(user, fresh=True)` считает права из базы мимо кэша `perms:<id>` и кэш не пишет; `access.scope(user, fresh=True)` видит те же права."""
    from django.core.cache import cache
    from apps.core.services import permissions
    from apps.servicedesk.services import access
    user = _staff("Кэшев")
    key = f"perms:{user.pk}"
    cache.delete(key)
    assert permissions.permissions_of(user) == frozenset()  # кэш теперь хранит «нет прав»
    cached = cache.get(key)  # значение кэша после первого расчёта: формат кэша тест не задаёт
    user.roles.add(_all_role())  # сброс кэша зарегистрирован на фиксацию и в тесте не выполняется

    assert permissions.permissions_of(user) == frozenset()  # без `fresh` — устаревшее из кэша
    assert "servicedesk.all" in permissions.permissions_of(user, fresh=True)
    assert cache.get(key) == cached  # свежий расчёт кэш не перезаписал
    assert access.scope(model("core.User").objects.get(pk=user.pk), fresh=True).has_all is True
    cache.delete(key)
    assert "servicedesk.all" in permissions.permissions_of(user, fresh=True)
    assert cache.get(key) is None  # и в пустой кэш не записал


def test_hourly_task_reconciles_all_users(django_capture_on_commit_callbacks):
    """FR-235: ежечасное задание `reconcile_assignees` сверяет всех, у кого есть заявки (страховка без события): нарушившие правило сняты, участники и держатель «Все заявки» нет."""
    from apps.servicedesk import tasks
    outsider, member, holder, closer = _staff("Первый"), _staff("Второй"), _staff("Третий", roles=[_all_role()]), _staff("Четвёртый")
    unit, foreign = org.make_unit(), _queue()
    org.make_member(member, unit)
    bad = [_open(outsider, foreign), _open(member, foreign), _closed(closer, foreign)]
    good = [_open(member, _queue(unit)), _open(holder, foreign)]

    with django_capture_on_commit_callbacks(execute=True):
        tasks.reconcile_assignees()

    assert [_assignee_id(ticket) for ticket in bad] == [None, None, None]
    assert [_assignee_id(ticket) for ticket in good] == [member.pk, holder.pk]
    journal = model("core.AuditEvent").objects.filter(action="ticket.assignee_removed")
    assert journal.count() == 3 and all(event.actor_id is None for event in journal)


def test_hourly_task_takes_fifty_people_per_batch_and_enqueues_next_batch(django_capture_on_commit_callbacks):
    """FR-235: задание берёт порцию в 50 человек по возрастанию `id`, ставит следующую в `maintenance` с `after_id` последнего (`job_timeout` 600); неполная порция следующей не ставит."""
    from apps.servicedesk import tasks
    User = model("core.User")
    users = [User.objects.create(email=factories.new_email(), full_name=f"Порционный {n}", state="active") for n in range(51)]
    users.sort(key=lambda person: person.pk)
    foreign = _queue()
    tickets = [_open(person, foreign) for person in users]

    with django_capture_on_commit_callbacks(execute=True):
        tasks.reconcile_assignees()

    assert all(_assignee_id(ticket) is None for ticket in tickets[:50])
    assert _assignee_id(tickets[50]) == users[50].pk
    jobs = _jobs()
    assert len(jobs) == 1
    assert jobs[0].kwargs == {"after_id": users[49].pk}
    assert jobs[0].timeout == 600

    with django_capture_on_commit_callbacks(execute=True):
        jobs[0].perform()

    assert _assignee_id(tickets[50]) is None
    assert len(_jobs()) == 1  # последняя порция неполная: новой нет


# --- имена и история после снятия -----------------------------------------------------------------------

def test_closed_by_name_kept_in_card_and_list_after_assignee_removed(django_capture_on_commit_callbacks):
    """FR-235: у закрытой заявки без ответственного карточка (`[data-field="closed-by"]`) и список («Закрыл: …») показывают закрывшего (сценарий 15.7)."""
    admin, user = support.make_admin(), _staff("Ледов")
    old, new = org.make_unit(), org.make_unit()
    org.make_member(user, old)
    ticket = _closed(user, _queue(old))
    with django_capture_on_commit_callbacks(execute=True):
        _transfer(user, old, new, admin)
    client = support.logged_in(admin)

    card = _dom(client.get(f"/tickets/{ticket.number}/"))
    assert card.find_all(data_field="assignee")[0].attrs.get("data-empty") == "true"
    closed_by = card.find_all(data_field="closed-by")
    assert len(closed_by) == 1 and f"Закрыл: {user.full_name}" in closed_by[0].text()
    listing = _dom(client.get("/tickets/?preset=closed"))
    cell = _ticket_row(listing, ticket).find_all(data_cell="assignee")[0]
    assert f"Закрыл: {user.full_name}" in cell.text()


def test_history_keeps_who_handled_ticket_after_removal(django_capture_on_commit_callbacks):
    """FR-235: после снятия в истории остаётся, кто вёл заявку: авторы комментариев, прежние события ответственного и закрывший; прибавляется событие сверки с текстом ленты."""
    admin, user = support.make_admin(), _staff("Мартынов")
    old, new = org.make_unit(), org.make_unit()
    org.make_member(user, old)
    ticket = _closed(user, _queue(old))
    comments = [sd.make_entry(ticket, "comment", author=user, text=f"Заметка {n}") for n in range(2)]
    taken = sd.make_entry(ticket, "event", event="assignee_changed",
                          data={"before": "", "after": user.full_name, "before_id": None, "after_id": user.pk})
    with django_capture_on_commit_callbacks(execute=True):
        _transfer(user, old, new, admin)

    Entry = model("servicedesk.TicketEntry")
    assert list(Entry.objects.filter(pk__in=[c.pk for c in comments]).values_list("author_id", flat=True)) == [user.pk, user.pk]
    assert Entry.objects.get(pk=taken.pk).data["after_id"] == user.pk
    assert _fresh(ticket).closed_by_id == user.pk
    feed = _dom(support.logged_in(admin).get(f"/tickets/{ticket.number}/"))
    for comment in comments:
        item = feed.find_all("li", data_entry_id=comment.pk)[0]
        assert any(user.full_name in el.text() for el in item.walk() if "data-author" in el.attrs)
    events = feed.find_all("li", data_kind="event", data_event="assignee_reconciled")
    assert len(events) == 1 and REASON_TEXT in events[0].text()


def test_dismissed_name_marked_in_messages_and_closed_tickets(django_capture_on_commit_callbacks):
    """FR-235 (SPEC-002 FR-127): имя уволенного в сообщениях ленты, в поле «закрыл» карточки и в списке закрытых помечено «(уволен)» (сценарий 15.3)."""
    from apps.org.services import people
    admin, user, unit = support.make_admin(), _staff("Уволенов"), org.make_unit()
    org.make_member(user, unit)
    ticket = _closed(user, _queue(unit))
    comment = sd.make_entry(ticket, "comment", author=user, text="Был здесь")
    with django_capture_on_commit_callbacks(execute=True):
        people.dismiss(user, actor=admin)
    client = support.logged_in(admin)

    card = _dom(client.get(f"/tickets/{ticket.number}/"))
    closed_by = card.find_all(data_field="closed-by")[0]
    assert user.full_name in closed_by.text() and "(уволен)" in closed_by.text()
    assert any(el.attrs.get("data-dismissed") == "true" or "data-dismissed-badge" in el.attrs for el in closed_by.walk())
    author = [el for el in card.find_all("li", data_entry_id=comment.pk)[0].walk() if "data-author" in el.attrs][0]
    assert author.attrs.get("data-dismissed") == "true" and f"{user.full_name} (уволен)" in author.text()
    cell = _ticket_row(_dom(client.get("/tickets/?preset=closed")), ticket).find_all(data_cell="assignee")[0]
    assert user.full_name in cell.text() and "Закрыл:" in cell.text() and cell.has_attr("data-dismissed-badge")


def test_removed_assignee_tickets_listed_in_preset_without_assignee(django_capture_on_commit_callbacks):
    """FR-235 (FR-276): заявки после снятия ответственного участник очереди видит в пресете «Без ответственного» (открытые; закрытая туда не попадает) (сценарий 15.4)."""
    admin, user, viewer = support.make_admin(), _staff("Снятов"), support.make_employee()
    old, new = org.make_unit(), org.make_unit()
    org.make_member(user, old)
    org.make_member(viewer, old)
    queue = _queue(old)
    open_ticket, closed_ticket = _open(user, queue), _closed(user, queue)
    client = support.logged_in(viewer)
    before = _dom(client.get("/tickets/?preset=unassigned"))
    assert before.find_all("tr", data_ticket=open_ticket.number) == []

    with django_capture_on_commit_callbacks(execute=True):
        _transfer(user, old, new, admin)

    after = _dom(client.get("/tickets/?preset=unassigned"))
    assert len(after.find_all("tr", data_ticket=open_ticket.number)) == 1
    assert after.find_all("tr", data_ticket=closed_ticket.number) == []


def test_reopened_ticket_of_removed_assignee_has_no_assignee(django_capture_on_commit_callbacks):
    """FR-235 (FR-251): закрытую заявку, с которой снят ответственный, открывают заново — ответственного нет, заявка в работе, закрытие очищено (сценарий 15.5)."""
    from apps.servicedesk.services import closing
    admin, user, worker = support.make_admin(), _staff("Закрытов"), _staff("Рабочев")
    old, new = org.make_unit(), org.make_unit()
    org.make_member(user, old)
    org.make_member(worker, old)
    ticket = _closed(user, _queue(old))
    with django_capture_on_commit_callbacks(execute=True):
        _transfer(user, old, new, admin)

    with django_capture_on_commit_callbacks(execute=True):
        closing.reopen(_fresh(ticket), actor=worker)

    fresh = _fresh(ticket)
    assert fresh.kind == "in_progress" and fresh.assignee_id is None
    assert fresh.closed_at is None and fresh.closed_by_id is None and fresh.resolution == ""


# --- шина событий -----------------------------------------------------------------------------------

def test_handler_runs_only_in_on_commit_callbacks(bus_spy, django_capture_on_commit_callbacks):
    """FR-235: обработчик `access.changed` работает только в обратных вызовах `on_commit`: до их выполнения заявка за прежним ответственным и события не записаны, после — снят."""
    admin, user = support.make_admin(), _staff("Коммитов")
    old, new = org.make_unit(), org.make_unit()
    org.make_member(user, old)
    ticket = _open(user, _queue(old))
    bus_spy.listen("access.changed")

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        _transfer(user, old, new, admin)
        assert _assignee_id(ticket) == user.pk
    assert callbacks
    assert _assignee_id(ticket) == user.pk and _reconciled(ticket) == []
    assert bus_spy.calls("access.changed") == []

    for callback in callbacks:
        callback()

    assert _assignee_id(ticket) is None and len(_reconciled(ticket)) == 1
    assert any(user.pk in (call["user_ids"] or []) for call in bus_spy.calls("access.changed"))


def test_handler_error_does_not_roll_back_publishing_action(caplog, django_capture_on_commit_callbacks):
    """FR-235: ошибка другого подписчика `access.changed` не откатывает действие, опубликовавшее событие, и не мешает сверке; запись об ошибке попадает в лог."""
    from apps.core import events
    admin, user = support.make_admin(), _staff("Сбойнов")
    old, new = org.make_unit(), org.make_unit()
    org.make_member(user, old)
    ticket = _open(user, _queue(old))

    def failing(**data):
        raise RuntimeError("сбой подписчика")

    events.subscribe("access.changed", failing)
    try:
        with caplog.at_level(logging.ERROR), django_capture_on_commit_callbacks(execute=True):
            _transfer(user, old, new, admin)
    finally:
        events.unsubscribe("access.changed", failing)

    Membership = model("org.Membership")
    assert not Membership.objects.filter(user=user, unit=old).exists()
    assert Membership.objects.filter(user=user, unit=new).exists()
    assert any(record.levelno >= logging.ERROR for record in caplog.records)
    assert _assignee_id(ticket) is None
