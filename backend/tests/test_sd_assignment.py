"""T-3112: ответственный, передача в очередь и смена категории (FR-237, FR-238, FR-239, FR-240, FR-255).

Сценарии 3, 4 и 8 спеки среза 003. Взять себе и назначить (только участник очереди, даже прямым запросом),
подсказки кандидатов, ответственный по умолчанию категории, письмо «взята в работу» один раз, снятие
ответственного, передача в другую очередь (причина, ответственный не из новой очереди, переход на список),
смена категории с подтверждением смены очереди. Код среза на уровне модуля не импортируется: имена берутся
внутри тестов (CONTRACT-003, шапка).
"""
import importlib
import re
import secrets
from html.parser import HTMLParser

import pytest

from tests import factories, support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import HX, model

pytestmark = pytest.mark.django_db


# --- помощники только этого файла -------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.servicedesk.services.{name}")


def _error_type():
    return importlib.import_module("apps.servicedesk.services").ServiceDeskError


def _queue(name: str | None = None):
    """Отмеченный очередью узел с уникальным названием."""
    return sd.make_queue(org.make_unit(name or f"Очередь {secrets.token_hex(3)}"))


def _member(unit, name: str | None = None, *, mark: str = ""):
    """Сотрудник, состоящий в узле."""
    user = support.make_employee(full_name=name) if name else support.make_employee()
    org.make_member(user, unit, mark=mark)
    return user


def _fresh(obj):
    obj.refresh_from_db()
    return obj


def _ticket(queue, **over):
    return sd.make_ticket(queue=queue, **over)


def _worked_ticket(queue, assignee, **over):
    """Заявка, у которой ответственный уже был: вид «в работе», `assigned_once` истинно."""
    return sd.make_ticket(queue=queue, kind="in_progress", assignee=assignee, assigned_once=True, **over)


def _feed(ticket, event: str) -> list:
    return list(ticket.entries.filter(kind="event", event=event).order_by("id"))


def _journal(action: str, ticket) -> list:
    return list(model("core.AuditEvent").objects.filter(
        action=action, object_type="ticket", object_id=str(ticket.number)).order_by("id"))


def _assigned_mails(ticket) -> list:
    return [m for m in sd.ticket_mails(ticket) if m.template == "ticket.assigned"]


def _post(client, ticket, action: str, data: dict | None = None, *, hx: bool = False):
    return client.post(f"/tickets/{ticket.number}/{action}/", data or {}, **(HX if hx else {}))


def _html(response) -> str:
    return response.content.decode("utf-8", "replace")


def _alert_codes(response) -> list[str]:
    """Значения `data-code` у всех `[role=alert]` ответа (CONTRACT-003 § 13.1)."""
    codes = []
    for tag in re.findall(r'<[^>]*\brole="alert"[^>]*>', _html(response)):
        found = re.search(r'\bdata-code="([^"]*)"', tag)
        codes.append(found.group(1) if found else "")
    return codes


def _has_form(response, name: str) -> bool:
    return re.search(rf'<form\b[^>]*\bdata-form="{re.escape(name)}"', _html(response)) is not None


def _candidate_ids(response) -> set[int]:
    """`data-user-id` у `[data-candidate]` (`label`, § 12.4)."""
    ids = set()
    for tag in re.findall(r"<[^>]*(?<![\w-])data-candidate(?![\w-])[^>]*>", _html(response)):
        found = re.search(r'\bdata-user-id="(\d+)"', tag)
        if found:
            ids.add(int(found.group(1)))
    return ids


def _select_values(response, field: str) -> set[int]:
    """Числовые значения `option` у `select[name=<field>]`."""
    found = re.search(rf'<select\b[^>]*\bname="{field}"[^>]*>(.*?)</select>', _html(response), re.S)
    assert found, f"в ответе нет select[name={field}]"
    return {int(v) for v in re.findall(r'<option\b[^>]*\bvalue="(\d+)"', found.group(1))}


def _element_html(response, attr: str, value: str) -> str:
    """Разметка элемента с `attr="value"` (от открывающего тега до закрывающего `</li>` или `</div>`)."""
    html = _html(response)
    start = re.search(rf'<(li|div)\b[^>]*\b{re.escape(attr)}="{re.escape(value)}"', html)
    assert start, f"в ответе нет элемента [{attr}=\"{value}\"]"
    end = html.find(f"</{start.group(1)}>", start.start())
    return html[start.start(): end if end != -1 else len(html)]


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _El:
    """Узел разбора разметки (с учётом вложенности)."""

    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.kids = tag, attrs, parent, []

    def walk(self):
        yield self
        for kid in self.kids:
            if isinstance(kid, _El):
                yield from kid.walk()

    def text(self) -> str:
        return " ".join(" ".join(k if isinstance(k, str) else k.text() for k in self.kids).split())

    def find_all(self, tag=None, **want):
        wanted = {key.replace("_", "-"): value for key, value in want.items()}
        return [el for el in self.walk()
                if (tag is None or el.tag == tag)
                and all(n in el.attrs and (v is True or el.attrs[n] == str(v)) for n, v in wanted.items())]


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
        el = self.cur
        while el is not None and el.tag != tag:
            el = el.parent
        if el is not None and el.parent is not None:
            self.cur = el.parent

    def handle_data(self, data):
        self.cur.kids.append(data)


def _tree(response) -> _El:
    builder = _Builder()
    builder.feed(_html(response))
    return builder.root


def _find_one(response, **want) -> _El:
    """Единственный элемент любого тега с заданными атрибутами (например `data_dialog="ticket-category"`)."""
    found = _tree(response).find_all(**want)
    assert len(found) == 1, f"в ответе элементов {want}: {len(found)}"
    return found[0]


def _text(fragment: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", fragment).replace("&laquo;", "«").replace("&raquo;", "»")
                    .replace("&quot;", '"').split())


def _status_messages(response) -> list[str]:
    """Тексты `[role=status]` страницы (без вложенной разметки)."""
    html = _html(response)
    texts = []
    for start in re.finditer(r'<(\w+)\b[^>]*\brole="status"[^>]*>', html):
        end = html.find(f"</{start.group(1)}>", start.end())
        texts.append(_text(html[start.end(): end if end != -1 else len(html)]))
    return texts


def _hidden_inputs(fragment: str) -> dict[str, str]:
    values = {}
    for tag in re.findall(r"<input\b[^>]*>", fragment):
        if 'type="hidden"' in tag:
            name = re.search(r'\bname="([^"]*)"', tag)
            value = re.search(r'\bvalue="([^"]*)"', tag)
            if name:
                values[name.group(1)] = value.group(1) if value else ""
    return values


def _setup_desk():
    queue = sd.make_queue()
    sd.configure_servicedesk(domains=["corp.test"], default_queue=queue)
    return queue


def _create_mail(**kw):
    tickets = _svc("tickets")
    kw.setdefault("subject", "Не печатает принтер")
    kw.setdefault("text", "Принтер на втором этаже не печатает")
    kw.setdefault("requester_email", factories.new_email("req").lower())
    kw.setdefault("inbound_id", sd.make_inbound().pk)
    return tickets.create(channel=tickets.MAIL, **kw)


# --- FR-237: взять себе и назначить ------------------------------------------------------------------

def test_take_for_self_by_queue_member_sets_assignee_and_in_work(django_capture_on_commit_callbacks):
    """FR-237: участник очереди берёт заявку себе: он ответственный, статус «в работе», событие ленты и журнала."""
    queue = _queue()
    member = _member(queue.unit, "Орлов Олег Игоревич")
    ticket = _ticket(queue)
    client = support.logged_in(member)
    assert _has_form(client.get(f"/tickets/{ticket.number}/"), "ticket-take")
    with django_capture_on_commit_callbacks(execute=True):
        response = _post(client, ticket, "take")
    assert response.status_code == 302 and response["Location"].endswith(f"/tickets/{ticket.number}/")
    _fresh(ticket)
    assert ticket.assignee_id == member.pk and ticket.assigned_once is True
    assert ticket.kind == "in_progress"
    assert ticket.status_id == model("servicedesk.Status").objects.get(kind="in_progress", is_default=True).pk
    events = _feed(ticket, "assignee_changed")
    assert len(events) == 1
    assert (events[0].data["before"], events[0].data["after"]) == ("", member.full_name)
    assert (events[0].data["before_id"], events[0].data["after_id"]) == (None, member.pk)
    journal = _journal("ticket.assigned", ticket)
    assert len(journal) == 1 and journal[0].actor_id == member.pk
    assert journal[0].before == {"assignee": "", "assignee_id": None}
    assert journal[0].after == {"assignee": member.full_name, "assignee_id": member.pk}
    assert not _has_form(client.get(f"/tickets/{ticket.number}/"), "ticket-take")


def test_take_for_self_by_non_member_refused_even_direct_request(django_capture_on_commit_callbacks):
    """FR-237: не участник очереди (ответственный по заявке чужой очереди) не берёт заявку; невидимая — 404."""
    assignment, error = _svc("assignment"), _error_type()
    queue, foreign = _queue(), _queue()
    stranger = _member(foreign.unit)
    visible = _worked_ticket(queue, stranger)  # чужая очередь, но ответственный — он: заявку видит, участником нет
    hidden = _ticket(queue)
    client = support.logged_in(stranger)
    with django_capture_on_commit_callbacks(execute=True):
        response = _post(client, visible, "take")
        hidden_response = _post(client, hidden, "take")
    assert response.status_code == 200 and "not_participant" in _alert_codes(response)
    assert hidden_response.status_code == 404
    with pytest.raises(error) as refused:
        assignment.take(_fresh(visible), actor=stranger)
    assert refused.value.code == "not_participant"
    with pytest.raises(error) as invisible:
        assignment.take(_fresh(hidden), actor=stranger)
    assert invisible.value.code == "no_access"
    assert _fresh(visible).assignee_id == stranger.pk and _fresh(hidden).assignee_id is None
    for ticket in (visible, hidden):
        assert _feed(ticket, "assignee_changed") == [] and _journal("ticket.assigned", ticket) == []
        assert _assigned_mails(ticket) == []


def test_assign_non_member_of_queue_refused_even_direct_request(django_capture_on_commit_callbacks):
    """FR-237: назначить можно только участника очереди заявки; чужой очереди, без членства и уволенный — отказ."""
    assignment, error = _svc("assignment"), _error_type()
    queue, foreign = _queue(), _queue()
    actor = _member(queue.unit)
    outsider = support.make_employee()
    other_queue_member = _member(foreign.unit)
    dismissed = _member(queue.unit)
    model("core.User").objects.filter(pk=dismissed.pk).update(state="dismissed")
    ticket = _ticket(queue)
    client = support.logged_in(actor)
    for candidate in (outsider, other_queue_member, dismissed):
        with django_capture_on_commit_callbacks(execute=True):
            response = _post(client, ticket, "assign", {"assignee": str(candidate.pk)})
        assert response.status_code == 200 and "not_participant" in _alert_codes(response), candidate.pk
        with pytest.raises(error) as refused:
            assignment.assign(_fresh(ticket), _fresh(candidate), actor=actor)
        assert refused.value.code == "not_participant"
    _fresh(ticket)
    assert ticket.assignee_id is None and ticket.assigned_once is False and ticket.kind == "new"
    assert _feed(ticket, "assignee_changed") == [] and _journal("ticket.assigned", ticket) == []
    assert _assigned_mails(ticket) == []


def test_assignee_suggestions_only_queue_members_by_name_start_case_and_yo_insensitive():
    """FR-237: в подсказках — участники очереди и держатели «Все заявки» по началу ФИО, без регистра и «ё»."""
    access = _svc("access")
    queue, foreign = _queue(), _queue()
    actor = _member(queue.unit, "Яковлев Яков Яковлевич")
    yolkin = _member(queue.unit, "Ёлкин Пётр Иванович")
    elisey = _member(queue.unit, "Елисеев Иван Петрович")
    _member(queue.unit, "Еремин Олег Игоревич")  # начинается с «Ер», не с «Ел»
    elizarov = _member(queue.unit, "Елизаров Егор Егорович")
    dismissed = _member(queue.unit, "Еловой Евгений Андреевич")
    model("core.User").objects.filter(pk=dismissed.pk).update(state="dismissed")
    _member(foreign.unit, "Елагин Ефим Ефимович")  # из другой очереди
    holder = support.make_with_permissions("servicedesk.all", full_name="Елецкий Елисей Еремеевич")
    ticket = _ticket(queue)
    expected_ids = {yolkin.pk, elisey.pk, holder.pk, elizarov.pk}
    for prefix in ("ел", "ЕЛ", "ёл", "Ёл"):
        assert {p.id for p in access.suggest_assignees(queue.unit_id, prefix)} == expected_ids, prefix
        response = support.logged_in(actor).get(f"/tickets/{ticket.number}/assignees/", {"q": prefix})
        assert response.status_code == 200
        assert _candidate_ids(response) == expected_ids, prefix
    nothing = support.logged_in(actor).get(f"/tickets/{ticket.number}/assignees/", {"q": "Ел-нет"})
    assert nothing.status_code == 200 and _candidate_ids(nothing) == set()


# --- FR-238: ответственный по умолчанию категории -----------------------------------------------------

def test_ticket_without_category_default_assignee_has_no_assignee(django_capture_on_commit_callbacks):
    """FR-237, FR-238: у заявки без категории и у категории без ответственного по умолчанию его не назначают."""
    assignment = _svc("assignment")
    queue = _queue()
    _member(queue.unit)
    plain = sd.make_category(queue=queue)  # ответственного по умолчанию нет
    without_category = _ticket(queue)
    with_category = _ticket(queue, category=plain)
    for ticket in (without_category, with_category):
        with django_capture_on_commit_callbacks(execute=True):
            assert assignment.apply_default_assignee(_fresh(ticket)) is False
        _fresh(ticket)
        assert ticket.assignee_id is None and ticket.assigned_once is False and ticket.kind == "new"
        assert _feed(ticket, "assignee_changed") == [] and _journal("ticket.assigned", ticket) == []
        assert _assigned_mails(ticket) == []


def test_category_default_assignee_assigned_on_creation_when_still_queue_member(
        django_capture_on_commit_callbacks, bus):
    """FR-238: при создании ответственным становится участник очереди — ответственный по умолчанию категории.

    Лента и журнал пишутся, события шины `assignee_changed` нет, письма «взята в работу» нет (дополнение 7)."""
    _setup_desk()
    queue = _queue()
    default = _member(queue.unit, "Белов Борис Борисович")
    category = sd.make_category(queue=queue, default_assignee=default)
    bus.listen("servicedesk.ticket_created", "servicedesk.assignee_changed")
    with django_capture_on_commit_callbacks(execute=True):
        created = _create_mail(category=category)
    ticket = _fresh(created.ticket)
    assert ticket.queue_id == queue.unit_id
    assert ticket.assignee_id == default.pk and ticket.assigned_once is True and ticket.kind == "in_progress"
    events = _feed(ticket, "assignee_changed")
    assert len(events) == 1
    assert (events[0].data["before"], events[0].data["after"]) == ("", default.full_name)
    assert (events[0].data["before_id"], events[0].data["after_id"]) == (None, default.pk)
    journal = _journal("ticket.assigned", ticket)
    assert len(journal) == 1 and journal[0].actor_id is None
    assert journal[0].before == {"assignee": "", "assignee_id": None}
    assert journal[0].after == {"assignee": default.full_name, "assignee_id": default.pk}
    assert _assigned_mails(ticket) == []
    assert bus.calls("servicedesk.assignee_changed") == []
    published = bus.calls("servicedesk.ticket_created")
    assert len(published) == 1 and published[0]["assignee_after_id"] == default.pk


def test_category_default_assignee_not_member_any_more_leaves_ticket_unassigned(django_capture_on_commit_callbacks):
    """FR-238: ответственный по умолчанию перестал быть участником очереди — заявка остаётся без ответственного."""
    assignment = _svc("assignment")
    _setup_desk()
    queue = _queue()
    default = _member(queue.unit)
    category = sd.make_category(queue=queue, default_assignee=default)
    model("org.Membership").objects.filter(user=default).delete()
    with django_capture_on_commit_callbacks(execute=True):
        created = _create_mail(category=category)
    ticket = _fresh(created.ticket)
    assert ticket.assignee_id is None and ticket.assigned_once is False and ticket.kind == "new"
    existing = _ticket(queue, category=category)
    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.apply_default_assignee(_fresh(existing)) is False
    for item in (ticket, existing):
        _fresh(item)
        assert item.assignee_id is None and item.assigned_once is False
        assert _feed(item, "assignee_changed") == [] and _journal("ticket.assigned", item) == []
        assert _assigned_mails(item) == []


def test_letter_without_category_gets_no_default_assignee(django_capture_on_commit_callbacks):
    """FR-238: письмо без категории идёт в очередь по умолчанию без ответственного."""
    assignment = _svc("assignment")
    default_queue = _setup_desk()
    _member(default_queue.unit)
    with django_capture_on_commit_callbacks(execute=True):
        created = _create_mail()
    ticket = _fresh(created.ticket)
    assert ticket.category_id is None and ticket.queue_id == default_queue.unit_id
    assert ticket.assignee_id is None and ticket.assigned_once is False and ticket.kind == "new"
    assert _feed(ticket, "assignee_changed") == [] and _journal("ticket.assigned", ticket) == []
    assert _assigned_mails(ticket) == []
    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.apply_default_assignee(ticket) is False
    assert _fresh(ticket).assignee_id is None


# --- FR-255: письмо «взята в работу» -----------------------------------------------------------------

def test_first_assignee_sends_taken_into_work_letter_once_with_name_and_surname(django_capture_on_commit_callbacks):
    """FR-255: первое появление ответственного — одно письмо заявителю «взята в работу» с именем и фамилией."""
    assignment = _svc("assignment")
    queue = _queue()
    actor = _member(queue.unit, "Сидоров Сидор Сидорович")
    first = _member(queue.unit, "Петров Пётр Сергеевич")
    ticket = _ticket(queue, requester=sd.make_requester(full_name="Иванова Анна"))
    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.assign(_fresh(ticket), first, actor=actor) is True
    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.assign(_fresh(ticket), first, actor=actor) is False  # тот же — ничего не меняется
    mails = _assigned_mails(ticket)
    assert len(mails) == 1
    assert mails[0].to == ticket.requester_email and mails[0].auto_submitted == "auto-generated"
    text = sd.mail_text(mails[0])
    assert "Ответственный: Пётр Петров" in text and str(ticket.number) in text
    assert "Сергеевич" not in text


def test_taken_letter_not_sent_on_creation_with_assignee(django_capture_on_commit_callbacks):
    """FR-255: ответственный при создании (по умолчанию категории или `take_by`) — отдельного письма нет, только подтверждение."""
    tickets = _svc("tickets")
    _setup_desk()
    queue = _queue()
    default = _member(queue.unit)
    taker = _member(queue.unit)
    category = sd.make_category(queue=queue, default_assignee=default)
    with django_capture_on_commit_callbacks(execute=True):
        by_default = _create_mail(category=category).ticket
    manual = model("servicedesk.Source").objects.filter(system_code="").order_by("order", "id").first()
    with django_capture_on_commit_callbacks(execute=True):
        by_taker = tickets.create(
            channel=tickets.STAFF, subject="Заявка по звонку", text="Звонили", requester_email=factories.new_email("req"),
            queue_id=queue.unit_id, source=manual, created_by=taker, take_by=taker).ticket
    for ticket, assignee in ((by_default, default), (by_taker, taker)):
        _fresh(ticket)
        assert ticket.assignee_id == assignee.pk and ticket.assigned_once is True
        assert [m.template for m in sd.ticket_mails(ticket)] == ["ticket.confirmation"]
    assert _journal("ticket.assigned", by_default)[0].actor_id is None
    assert _journal("ticket.assigned", by_taker)[0].actor_id == taker.pk


def test_taken_letter_not_repeated_on_reassign_or_after_unassign(django_capture_on_commit_callbacks):
    """FR-255: смена ответственного и повторное назначение после снятия новых писем не дают; `assigned_once` остаётся."""
    assignment = _svc("assignment")
    queue = _queue()
    actor = _member(queue.unit)
    first, second = _member(queue.unit), _member(queue.unit)
    ticket = _ticket(queue)
    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.assign(_fresh(ticket), first, actor=actor) is True
    assert len(_assigned_mails(ticket)) == 1
    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.assign(_fresh(ticket), second, actor=actor) is True
    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.unassign(_fresh(ticket), actor=actor) is True
    _fresh(ticket)
    assert ticket.assignee_id is None and ticket.assigned_once is True and ticket.kind == "in_progress"
    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.take(_fresh(ticket), actor=first) is True
    assert _fresh(ticket).assignee_id == first.pk
    assert len(_assigned_mails(ticket)) == 1
    already = _worked_ticket(queue, first)  # ответственный у заявки уже был (`assigned_once`): письма нет и сейчас
    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.assign(_fresh(already), second, actor=actor) is True
    assert _assigned_mails(already) == []


def test_unassign_without_letter_writes_feed_event(django_capture_on_commit_callbacks):
    """FR-237, FR-255: «Снять ответственного» — без письма, статус не меняется, событие ленты и журнала."""
    queue = _queue()
    actor = _member(queue.unit)
    assignee = _member(queue.unit, "Крылов Кирилл Павлович")
    ticket = _worked_ticket(queue, assignee)
    client = support.logged_in(actor)
    assert _has_form(client.get(f"/tickets/{ticket.number}/"), "ticket-unassign")
    with django_capture_on_commit_callbacks(execute=True):
        response = _post(client, ticket, "assign", {"assignee": ""})
    assert response.status_code == 302 and response["Location"].endswith(f"/tickets/{ticket.number}/")
    _fresh(ticket)
    assert ticket.assignee_id is None and ticket.assigned_once is True and ticket.kind == "in_progress"
    assert _assigned_mails(ticket) == []
    events = _feed(ticket, "assignee_changed")
    assert len(events) == 1
    assert (events[0].data["before"], events[0].data["after"]) == (assignee.full_name, "")
    assert (events[0].data["before_id"], events[0].data["after_id"]) == (assignee.pk, None)
    journal = _journal("ticket.assignee_removed", ticket)
    assert len(journal) == 1 and journal[0].actor_id == actor.pk
    assert journal[0].before == {"assignee": assignee.full_name, "assignee_id": assignee.pk}
    assert journal[0].after == {"assignee": "", "assignee_id": None, "reason": "manual"}
    assert not _has_form(client.get(f"/tickets/{ticket.number}/"), "ticket-unassign")


def test_assignee_changes_write_feed_event_was_became(django_capture_on_commit_callbacks):
    """FR-237: каждое назначение, смена и снятие — событие ленты «ответственный: было → стало»."""
    assignment = _svc("assignment")
    queue = _queue()
    actor = _member(queue.unit)
    first = _member(queue.unit, "Андреев Андрей Андреевич")
    second = _member(queue.unit, "Борисов Борис Борисович")
    ticket = _ticket(queue)
    with django_capture_on_commit_callbacks(execute=True):
        assignment.take(_fresh(ticket), actor=first)
    with django_capture_on_commit_callbacks(execute=True):
        assignment.assign(_fresh(ticket), second, actor=actor)
    with django_capture_on_commit_callbacks(execute=True):
        assignment.unassign(_fresh(ticket), actor=actor)
    changes = [(e.data["before"], e.data["after"], e.data["before_id"], e.data["after_id"])
               for e in _feed(ticket, "assignee_changed")]
    assert changes == [("", first.full_name, None, first.pk),
                       (first.full_name, second.full_name, first.pk, second.pk),
                       (second.full_name, "", second.pk, None)]
    card = support.logged_in(actor).get(f"/tickets/{ticket.number}/")
    assert card.status_code == 200
    assert "ответственный" in _text(_element_html(card, "data-event", "assignee_changed"))


# --- FR-239: передача в очередь -----------------------------------------------------------------------

def test_transfer_requires_queue_among_marked_nodes_except_current(django_capture_on_commit_callbacks):
    """FR-239: очередь обязательна и выбирается среди отмеченных узлов, кроме текущей; иное — отказ."""
    transfer, error = _svc("transfer"), _error_type()
    current, second, third = _queue(), _queue(), _queue()
    unmarked = org.make_unit(f"Не очередь {secrets.token_hex(3)}")
    actor = _member(current.unit)
    ticket = _ticket(current)
    expected = {second.unit_id, third.unit_id}
    assert {u.id for u in transfer.target_queues(ticket)} == expected
    client = support.logged_in(actor)
    dialog = client.get(f"/tickets/{ticket.number}/transfer/")
    assert dialog.status_code == 200 and 'data-dialog="ticket-transfer"' in _html(dialog)
    assert _select_values(dialog, "queue") == expected
    assert re.search(r"<textarea\b[^>]*\bname=\"reason\"", _html(dialog))
    for queue_id, code in ((None, "queue_required"), (unmarked.pk, "not_queue"), (current.unit_id, "same_queue")):
        with pytest.raises(error) as refused:
            transfer.transfer(_fresh(ticket), queue_id, actor=actor)
        assert refused.value.code == code
    for value, code in (("", "queue_required"), (str(unmarked.pk), "not_queue"), (str(current.unit_id), "same_queue")):
        response = _post(client, ticket, "transfer", {"queue": value, "reason": ""})
        assert response.status_code == 200 and code in _alert_codes(response), code
    assert _fresh(ticket).queue_id == current.unit_id
    assert _feed(ticket, "transferred") == [] and _journal("ticket.transferred", ticket) == []
    with django_capture_on_commit_callbacks(execute=True):
        result = transfer.transfer(_fresh(ticket), second.unit_id, actor=actor)
    assert result.queue_changed is True
    assert _fresh(ticket).queue_id == second.unit_id


def test_transfer_reason_optional_up_to_500_characters(django_capture_on_commit_callbacks):
    """FR-239: причина необязательна, до 500 знаков; 501 — отказ `reason_too_long`, заявка не меняется."""
    transfer, error = _svc("transfer"), _error_type()
    current, target = _queue(), _queue()
    actor = _member(current.unit)
    texts = ["", "  Нужна другая линия  ", "я" * 500]
    saved = []
    for text in texts:
        ticket = _ticket(current)
        with django_capture_on_commit_callbacks(execute=True):
            transfer.transfer(ticket, target.unit_id, reason=text, actor=actor)
        saved.append(_feed(_fresh(ticket), "transferred")[0].data["reason_text"])
        assert ticket.queue_id == target.unit_id
    assert saved == ["", "Нужна другая линия", "я" * 500]
    too_long = _ticket(current)
    with pytest.raises(error) as refused:
        transfer.transfer(too_long, target.unit_id, reason="я" * 501, actor=actor)
    assert refused.value.code == "reason_too_long"
    response = _post(support.logged_in(actor), too_long, "transfer", {"queue": str(target.unit_id), "reason": "я" * 501})
    assert response.status_code == 200 and "reason_too_long" in _alert_codes(response)
    assert _fresh(too_long).queue_id == current.unit_id and _feed(too_long, "transferred") == []


def test_transfer_removes_assignee_not_in_new_queue_keeps_member(django_capture_on_commit_callbacks, bus):
    """FR-239: при передаче ответственный снимается, если не участник новой очереди; участник остаётся."""
    transfer = _svc("transfer")
    current, target = _queue(), _queue()
    actor = _member(current.unit)
    only_old = _member(current.unit)
    both = _member(current.unit)
    org.make_member(both, target.unit)
    removed_ticket, kept_ticket = _worked_ticket(current, only_old), _worked_ticket(current, both)
    bus.listen("servicedesk.assignee_changed")
    with django_capture_on_commit_callbacks(execute=True):
        removed = transfer.transfer(removed_ticket, target.unit_id, actor=actor)
    with django_capture_on_commit_callbacks(execute=True):
        kept = transfer.transfer(kept_ticket, target.unit_id, actor=actor)
    assert (removed.assignee_removed, kept.assignee_removed) == (True, False)
    assert _fresh(removed_ticket).assignee_id is None and _fresh(removed_ticket).queue_id == target.unit_id
    assert _fresh(kept_ticket).assignee_id == both.pk and _fresh(kept_ticket).queue_id == target.unit_id
    journal = _journal("ticket.assignee_removed", removed_ticket)
    assert len(journal) == 1 and journal[0].actor_id == actor.pk
    assert journal[0].before == {"assignee": only_old.full_name, "assignee_id": only_old.pk}
    assert journal[0].after == {"assignee": "", "assignee_id": None, "reason": "queue_changed"}
    assert _journal("ticket.assignee_removed", kept_ticket) == []
    changed = bus.calls("servicedesk.assignee_changed")
    assert [(c["number"], c["assignee_before_id"], c["assignee_after_id"]) for c in changed] == [
        (removed_ticket.number, only_old.pk, None)]
    events = _feed(removed_ticket, "assignee_changed")
    assert len(events) == 1
    assert (events[0].data["before"], events[0].data["after"], events[0].data["before_id"],
            events[0].data["after_id"]) == (only_old.full_name, "", only_old.pk, None)
    assert _feed(kept_ticket, "assignee_changed") == []


def test_transfer_event_who_from_to_reason_and_journal_without_reason(django_capture_on_commit_callbacks):
    """FR-239: событие ленты «кто, откуда, куда, причина»; журнал знает только, указана ли причина."""
    transfer = _svc("transfer")
    current = _queue("Линия первая")
    target = _queue("Линия вторая")
    actor = _member(current.unit, "Лебедев Лев Львович")
    ticket = _ticket(current)
    reason = "Нужен специалист по принтерам"
    with django_capture_on_commit_callbacks(execute=True):
        transfer.transfer(ticket, target.unit_id, reason=reason, actor=actor)
    plain = _ticket(current)
    with django_capture_on_commit_callbacks(execute=True):
        transfer.transfer(plain, target.unit_id, actor=actor)
    events = _feed(_fresh(ticket), "transferred")
    assert len(events) == 1 and events[0].author_id == actor.pk
    assert events[0].data["from"] == "Линия первая" and events[0].data["to"] == "Линия вторая"
    assert (events[0].data["from_id"], events[0].data["to_id"]) == (current.unit_id, target.unit_id)
    assert events[0].data["reason_text"] == reason
    journal = _journal("ticket.transferred", ticket)
    assert len(journal) == 1 and journal[0].actor_id == actor.pk
    assert journal[0].before == {"queue": "Линия первая", "queue_id": current.unit_id}
    assert journal[0].after == {"queue": "Линия вторая", "queue_id": target.unit_id, "reason_given": True}
    assert reason not in str(journal[0].before) + str(journal[0].after)
    assert _journal("ticket.transferred", plain)[0].after["reason_given"] is False
    assert _feed(_fresh(plain), "transferred")[0].data["reason_text"] == ""
    # после передачи актёр (участник только прежней очереди) заявку не видит (12.4) — карточку смотрит участник новой
    viewer = _member(target.unit, "Смотрова Вера Петровна")
    card = support.logged_in(viewer).get(f"/tickets/{ticket.number}/")
    element = _element_html(card, "data-event", "transferred")
    authors = _find_one(card, data_event="transferred").find_all(data_author=True)
    assert len(authors) == 1 and actor.full_name in authors[0].text()
    text = _text(element)
    assert "Линия первая" in text and "Линия вторая" in text and reason in text
    assert "причина" not in _text(_element_html(support.logged_in(viewer).get(f"/tickets/{plain.number}/"),
                                                "data-event", "transferred"))


def test_transfer_to_unavailable_ticket_returns_hx_redirect_with_message():
    """FR-239: заявка после передачи актёру не видна — HX-Redirect на список (или на главную) с сообщением."""
    current, target = _queue("Исходная очередь"), _queue("Целевая очередь")
    actor = _member(current.unit)
    hx_ticket, plain_ticket = _ticket(current), _ticket(current)
    client = support.logged_in(actor)
    response = _post(client, hx_ticket, "transfer", {"queue": str(target.unit_id), "reason": ""}, hx=True)
    assert response.status_code == 200 and response["HX-Redirect"] == "/tickets/"
    assert _fresh(hx_ticket).queue_id == target.unit_id
    page = client.get("/tickets/")
    assert page.status_code == 200
    hx_message = f"Заявка #{hx_ticket.number} передана в очередь «Целевая очередь»"
    assert any(hx_message in m for m in _status_messages(page))
    plain = _post(client, plain_ticket, "transfer", {"queue": str(target.unit_id), "reason": ""})
    assert plain.status_code == 302 and plain["Location"] == "/tickets/"
    plain_message = f"Заявка #{plain_ticket.number} передана в очередь «Целевая очередь»"
    assert any(plain_message in m for m in _status_messages(client.get("/tickets/")))
    # у ответственного по заявке чужой очереди после передачи нет ни заявок, ни очереди: переход на главную
    holder = support.make_employee()
    last = _worked_ticket(current, holder)
    away = _post(support.logged_in(holder), last, "transfer", {"queue": str(target.unit_id), "reason": ""}, hx=True)
    assert away.status_code == 200 and away["HX-Redirect"] == "/"
    assert _fresh(last).assignee_id is None and _fresh(last).queue_id == target.unit_id


# --- FR-240: смена категории -------------------------------------------------------------------------

def test_category_change_to_other_queue_asks_confirmation_first():
    """FR-240: смена категории на категорию другой очереди без подтверждения ничего не меняет, а просит его."""
    transfer = _svc("transfer")
    first, second = _queue("Очередь А"), _queue("Очередь Б")
    old = sd.make_category(queue=first)
    new = sd.make_category(queue=second)
    actor = support.make_with_permissions("servicedesk.all")
    ticket = _ticket(first, category=old)
    response = _post(support.logged_in(actor), ticket, "category", {"category": str(new.pk)}, hx=True)
    assert response.status_code == 200
    dialog = _find_one(response, data_dialog="ticket-category")
    assert "Заявка перейдёт в очередь «Очередь Б»" in dialog.text()
    hidden = {el.attrs.get("name"): el.attrs.get("value", "") for el in dialog.find_all("input", type="hidden")}
    assert hidden.get("category") == str(new.pk) and hidden.get("confirm") == "1"
    assert dialog.find_all(data_dialog_cancel=True)
    result = transfer.change_category(_fresh(ticket), new, actor=actor)
    assert result.needs_confirmation is True and result.applied is False and result.new_queue_id == second.unit_id
    _fresh(ticket)
    assert ticket.category_id == old.pk and ticket.queue_id == first.unit_id
    assert _feed(ticket, "category_changed") == [] and _feed(ticket, "queue_changed") == []
    assert _journal("ticket.updated", ticket) == [] and _journal("ticket.transferred", ticket) == []


def test_category_change_confirmed_changes_queue_with_two_events():
    """FR-240: с подтверждением меняются категория и очередь; два события ленты, журнал «изменена» и «передана»."""
    first, second = _queue("Очередь А"), _queue("Очередь Б")
    old = sd.make_category("Старая категория", queue=first)
    new = sd.make_category("Новая категория", queue=second)
    actor = support.make_with_permissions("servicedesk.all")
    ticket = _ticket(first, category=old)
    response = _post(support.logged_in(actor), ticket, "category", {"category": str(new.pk), "confirm": "1"})
    assert response.status_code == 302 and response["Location"].endswith(f"/tickets/{ticket.number}/")
    _fresh(ticket)
    assert ticket.category_id == new.pk and ticket.queue_id == second.unit_id
    category_events, queue_events = _feed(ticket, "category_changed"), _feed(ticket, "queue_changed")
    assert len(category_events) == 1 and len(queue_events) == 1
    assert (category_events[0].data["before"], category_events[0].data["after"]) == (
        "Старая категория", "Новая категория")
    assert (category_events[0].data["before_id"], category_events[0].data["after_id"]) == (old.pk, new.pk)
    assert (queue_events[0].data["from"], queue_events[0].data["to"]) == ("Очередь А", "Очередь Б")
    assert (queue_events[0].data["from_id"], queue_events[0].data["to_id"]) == (first.unit_id, second.unit_id)
    updated = _journal("ticket.updated", ticket)
    assert len(updated) == 1 and updated[0].before == {"category": "Старая категория"}
    assert updated[0].after == {"category": "Новая категория"}
    moved = _journal("ticket.transferred", ticket)
    assert len(moved) == 1 and moved[0].before == {"queue": "Очередь А", "queue_id": first.unit_id}
    assert moved[0].after["queue"] == "Очередь Б" and moved[0].after["queue_id"] == second.unit_id


def test_category_change_assigns_new_default_assignee_with_taken_letter(django_capture_on_commit_callbacks, bus):
    """FR-238, FR-240, FR-255: у заявки без ответственного назначается ответственный новой категории, письмо уходит."""
    transfer = _svc("transfer")
    first, second = _queue(), _queue()
    default = _member(second.unit, "Зайцев Зиновий Захарович")
    old = sd.make_category(queue=first)
    new = sd.make_category(queue=second, default_assignee=default)
    actor = support.make_with_permissions("servicedesk.all")
    ticket = _ticket(first, category=old)
    only_old = _member(first.unit)  # не участник новой очереди
    worked = _worked_ticket(first, only_old, category=old)
    bus.listen("servicedesk.assignee_changed")
    with django_capture_on_commit_callbacks(execute=True):
        result = transfer.change_category(ticket, new, confirmed=True, actor=actor)
    with django_capture_on_commit_callbacks(execute=True):
        replaced = transfer.change_category(worked, new, confirmed=True, actor=actor)
    assert result.applied is True and result.queue_changed is True and result.assignee_set is True
    assert replaced.applied is True and replaced.assignee_removed is True and replaced.assignee_set is True
    _fresh(ticket)
    assert ticket.assignee_id == default.pk and ticket.assigned_once is True and ticket.kind == "in_progress"
    mails = _assigned_mails(ticket)
    assert len(mails) == 1
    assert "Ответственный: Зиновий Зайцев" in sd.mail_text(mails[0])
    events = _feed(ticket, "assignee_changed")
    assert len(events) == 1 and (events[0].data["before"], events[0].data["after"]) == ("", default.full_name)
    assert _journal("ticket.assigned", ticket)[0].after == {"assignee": default.full_name, "assignee_id": default.pk}
    # у заявки, где ответственный не участник новой очереди: снятие, затем назначение по умолчанию (дополнение 22)
    _fresh(worked)
    assert worked.assignee_id == default.pk and worked.queue_id == second.unit_id
    pairs = {(e.data["before"], e.data["after"]) for e in _feed(worked, "assignee_changed")}
    assert len(_feed(worked, "assignee_changed")) == 2
    assert pairs == {(only_old.full_name, ""), ("", default.full_name)}
    removal = _journal("ticket.assignee_removed", worked)
    assert len(removal) == 1 and removal[0].after["reason"] == "queue_changed"
    assert len(_journal("ticket.assigned", worked)) == 1
    assert _assigned_mails(worked) == []  # assigned_once уже был истинным: письмо не уходит
    assert len(_assigned_mails(ticket)) == 1
    changed = bus.calls("servicedesk.assignee_changed")
    assert {(c["assignee_before_id"], c["assignee_after_id"]) for c in changed if c["number"] == worked.number} == {
        (only_old.pk, None), (None, default.pk)}
    assert len([c for c in changed if c["number"] == worked.number]) == 2
    assert len([c for c in changed if c["number"] == ticket.number]) == 1


def test_category_change_removes_assignee_not_in_new_queue(django_capture_on_commit_callbacks, bus):
    """FR-240: при смене очереди ответственный снимается, если он не участник новой очереди; участник остаётся."""
    transfer = _svc("transfer")
    first, second = _queue(), _queue()
    actor = support.make_with_permissions("servicedesk.all")
    only_old = _member(first.unit)
    both = _member(first.unit)
    org.make_member(both, second.unit)
    old = sd.make_category(queue=first)
    new = sd.make_category(queue=second)  # ответственного по умолчанию нет
    removed_ticket = _worked_ticket(first, only_old, category=old)
    kept_ticket = _worked_ticket(first, both, category=old)
    bus.listen("servicedesk.assignee_changed")
    with django_capture_on_commit_callbacks(execute=True):
        removed = transfer.change_category(removed_ticket, new, confirmed=True, actor=actor)
    with django_capture_on_commit_callbacks(execute=True):
        kept = transfer.change_category(kept_ticket, new, confirmed=True, actor=actor)
    assert (removed.queue_changed, removed.assignee_removed, removed.assignee_set) == (True, True, False)
    assert (kept.queue_changed, kept.assignee_removed) == (True, False)
    assert _fresh(removed_ticket).assignee_id is None and _fresh(removed_ticket).queue_id == second.unit_id
    assert _fresh(kept_ticket).assignee_id == both.pk and _fresh(kept_ticket).queue_id == second.unit_id
    journal = _journal("ticket.assignee_removed", removed_ticket)
    assert len(journal) == 1 and journal[0].actor_id == actor.pk
    assert journal[0].after == {"assignee": "", "assignee_id": None, "reason": "queue_changed"}
    assert _journal("ticket.assignee_removed", kept_ticket) == []
    events = _feed(removed_ticket, "assignee_changed")
    assert len(events) == 1
    assert (events[0].data["before"], events[0].data["after"], events[0].data["before_id"],
            events[0].data["after_id"]) == (only_old.full_name, "", only_old.pk, None)
    assert _feed(kept_ticket, "assignee_changed") == []
    for ticket in (removed_ticket, kept_ticket):
        assert len(_feed(ticket, "category_changed")) == 1 and len(_feed(ticket, "queue_changed")) == 1
    changed = bus.calls("servicedesk.assignee_changed")
    assert [(c["number"], c["assignee_before_id"], c["assignee_after_id"]) for c in changed] == [
        (removed_ticket.number, only_old.pk, None)]


def test_category_change_within_same_queue_needs_no_confirmation(django_capture_on_commit_callbacks):
    """FR-240: категория того же узла очереди меняется сразу: без подтверждения, без события очереди."""
    transfer = _svc("transfer")
    queue = _queue()
    actor = _member(queue.unit)
    old = sd.make_category("Принтеры", queue=queue)
    same = sd.make_category("Сканеры", queue=queue)
    via_service, via_route = _ticket(queue, category=old), _ticket(queue, category=old)
    with django_capture_on_commit_callbacks(execute=True):
        result = transfer.change_category(via_service, same, actor=actor)
    assert result.needs_confirmation is False and result.applied is True and result.queue_changed is False
    response = _post(support.logged_in(actor), via_route, "category", {"category": str(same.pk)})
    assert response.status_code == 302 and response["Location"].endswith(f"/tickets/{via_route.number}/")
    for ticket in (via_service, via_route):
        _fresh(ticket)
        assert ticket.category_id == same.pk and ticket.queue_id == queue.unit_id
        events = _feed(ticket, "category_changed")
        assert len(events) == 1 and (events[0].data["before"], events[0].data["after"]) == ("Принтеры", "Сканеры")
        assert _feed(ticket, "queue_changed") == [] and _journal("ticket.transferred", ticket) == []
        assert len(_journal("ticket.updated", ticket)) == 1
