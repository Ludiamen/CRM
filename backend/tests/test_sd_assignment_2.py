"""T-3113: поля заявки, участники, закрытая заявка и групповые действия (FR-217, FR-237, FR-239, FR-240, FR-241, FR-246).

Сценарии 3 и 4 спеки среза 003. Правка критичности, сложности, подразделения и ФИО заявителя (`tickets.update_fields`,
`/tickets/<номер>/fields/`), снятие участника (`tickets.remove_participant`), отказы на закрытой заявке (`ticket_closed`,
ответ 200 с `[role=alert]`) и групповые действия (`assignment.bulk`, `/tickets/bulk/`). Имена кода среза 003
берутся внутри тестов: сбор проходит до появления кода (CONTRACT-003, шапка; разделы 6.1, 6.7, 6.8, 12.2, 12.4, 13, 16).
"""
import email
import json
import re
from email import policy
from html.parser import HTMLParser

import pytest

from tests import support, support_servicedesk as sd
from tests import support_org as org
from tests.support import HX, model

pytestmark = pytest.mark.django_db

CLOSED_TEXT = "Заявка закрыта: сначала откройте её"
DOMAIN = "corp.test"
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- разбор разметки (помощник только этого файла) --------------------------------------------------

class _El:
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
    builder.feed(response.content.decode("utf-8", "replace"))
    return builder.root


def _alerts(response) -> list[tuple[str, str]]:
    """`[role=alert]`: пары (`data-code`, текст)."""
    return [(el.attrs.get("data-code", ""), el.text()) for el in _tree(response).find_all(role="alert")]


def _options(root, form: str, select: str) -> list[str]:
    """Значения `option` у `form[data-form=<form>] select[name=<select>]`."""
    values = []
    for form_el in root.find_all("form", data_form=form):
        for sel in form_el.find_all("select", name=select):
            values += [o.attrs.get("value", "") for o in sel.find_all("option")]
    return values


# --- данные теста -----------------------------------------------------------------------------------

def _member(unit, **extra):
    user = support.make_employee(**extra)
    org.make_member(user, unit)
    return user


def _world(**ticket_over):
    """Очередь, участник очереди (исполнитель), его заявка и клиент с входом. Возвращает (очередь, пользователь, заявка, клиент)."""
    queue = sd.make_queue()
    user = _member(queue.unit)
    ticket = sd.make_ticket(queue=queue, requester=sd.make_requester(), **ticket_over)
    return queue, user, ticket, support.logged_in(user)


def _fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


def _priority(name):
    return model("servicedesk.Priority").objects.get(name_key=org.name_key(name))


def _complexity(name):
    return model("servicedesk.Complexity").objects.get(name_key=org.name_key(name))


def _archived(kind: str, name: str):
    return model(f"servicedesk.{kind}").objects.create(name=name, name_key=org.name_key(name), order=90, archived=True)


def _client_unit(name: str):
    return model("servicedesk.ClientUnit").objects.create(name=name, name_key=org.name_key(name))


def _events(ticket, event=None):
    rows = model("servicedesk.TicketEntry").objects.filter(ticket=ticket, kind="event")
    return list(rows.filter(event=event).order_by("id") if event else rows.order_by("id"))


def _journal(action, ticket=None, object_id=None):
    object_id = str(ticket.number) if ticket is not None else object_id
    return list(model("core.AuditEvent").objects.filter(action=action, object_id=object_id).order_by("id"))


def _entry_count(ticket) -> int:
    return model("servicedesk.TicketEntry").objects.filter(ticket=ticket).count()


def _closed_world():
    """Закрытая заявка очереди, участник очереди и клиент; ещё один участник очереди (кандидат в ответственные)."""
    queue, user, ticket, client = _world(kind="closed")
    candidate = _member(queue.unit)
    return queue, user, ticket, client, candidate


def _page(client, ticket):
    response = client.get(f"/tickets/{ticket.number}/")
    assert response.status_code == 200
    return _tree(response)


def _assert_closed_refusal(response, ticket, *, what: str):
    assert response.status_code == 200, f"{what}: отказ сервиса — всегда 200, получили {response.status_code}"
    alerts = _alerts(response)
    assert [code for code, _ in alerts] == ["ticket_closed"], f"{what}: ждали один [role=alert] с кодом ticket_closed, {alerts}"
    assert CLOSED_TEXT in alerts[0][1], f"{what}: текст отказа — {alerts[0][1]!r}"


# --- поля заявки: критичность, сложность, подразделение, ФИО, тема -------------------------------------

def test_criticality_and_complexity_edit_write_event_per_field():
    """FR-246: правка критичности и сложности из карточки — по одному событию ленты на поле (`before`/`after`, `*_id`),
    журнал `ticket.updated` с названиями до и после, неизменённое поле событий не даёт; повтор тех же значений ничего не пишет."""
    from apps.servicedesk.services import tickets

    queue, user, ticket, client = _world()
    high, hard = _priority("Высокая"), _complexity("Высокий")
    medium = _priority("Средняя")

    response = client.post(f"/tickets/{ticket.number}/fields/", {"priority": high.pk, "complexity": hard.pk}, **HX)
    assert response.status_code == 200
    ticket = _fresh(ticket)
    assert ticket.priority_id == high.pk and ticket.complexity_id == hard.pk

    by_event = {e.event: e for e in _events(ticket)}
    assert sorted(by_event) == ["complexity_changed", "priority_changed"], "ровно по одному событию на изменённое поле"
    assert len(_events(ticket)) == 2
    priority_event, complexity_event = by_event["priority_changed"], by_event["complexity_changed"]
    assert priority_event.data == {"before": "Средняя", "after": "Высокая", "before_id": medium.pk, "after_id": high.pk}
    assert complexity_event.data == {"before": "", "after": "Высокий", "before_id": None, "after_id": hard.pk}
    assert priority_event.author_id == user.pk and complexity_event.author_id == user.pk

    journal = _journal("ticket.updated", ticket)
    assert len(journal) == 1, "дополнение 21: один вызов — одно событие ticket.updated на все изменённые поля"
    assert journal[0].actor_id == user.pk
    assert journal[0].before == {"priority": "Средняя", "complexity": ""}
    assert journal[0].after == {"priority": "Высокая", "complexity": "Высокий"}

    entries_before, journal_before = _entry_count(ticket), len(journal)
    assert tickets.update_fields(ticket, actor=user, priority=high, complexity=hard) == []
    assert _entry_count(ticket) == entries_before and len(_journal("ticket.updated", ticket)) == journal_before
    assert tickets.update_fields(ticket, actor=user, priority=medium, complexity=None) == ["priority", "complexity"]


def test_no_route_or_service_to_add_participant():
    """FR-217: участников добавляет только копия входящих писем — ни функции в `tickets`, `assignment`, `replies`,
    ни маршрута: POST на `…/participants/` и `…/participants/add/` — 404, форм добавления в карточке нет."""
    from apps.servicedesk.services import assignment, replies, tickets

    for module in (tickets, assignment, replies):
        names = [n for n in dir(module) if re.fullmatch(r"(add|append|create)_?participants?|participants?_?(add|append|create)", n.lower())]
        assert names == [], f"{module.__name__}: функции добавления участника быть не должно, нашли {names}"
    assert not hasattr(tickets, "add_participant")

    queue, user, ticket, client = _world()
    sd.make_participant(ticket, f"cc@{DOMAIN}")
    root = _page(client, ticket)
    assert [el for el in root.walk() if "data-ticket-card" in el.attrs], "карточка открывается (заявка видна)"
    forbidden_forms = [f.attrs.get("data-form", "") for f in root.find_all("form") if "participant" in f.attrs.get("data-form", "")]
    assert forbidden_forms == [], f"формы работы с участниками в карточке: {forbidden_forms}"
    for path in (f"/tickets/{ticket.number}/participants/", f"/tickets/{ticket.number}/participants/add/"):
        for data in ({}, {"email": f"new@{DOMAIN}", "name": "Новый"}):
            assert client.post(path, data, **HX).status_code == 404, path
    assert model("servicedesk.TicketParticipant").objects.filter(ticket=ticket).count() == 1


def test_archived_criticality_and_complexity_not_offered():
    """FR-246: архивные критичность и сложность в выборе формы полей не предлагаются, а присланные напрямую отказывают
    `archived_value` (200 с `[role=alert]`, ничего не меняется, в том числе соседнее поле того же запроса)."""
    from apps.servicedesk.services import ServiceDeskError, tickets

    queue, user, ticket, client = _world()
    old_priority, old_complexity = _archived("Priority", "Архивная критичность"), _archived("Complexity", "Архивный уровень")
    medium, easy = _priority("Средняя"), _complexity("Лёгкий")

    root = _page(client, ticket)
    priorities, complexities = _options(root, "ticket-fields", "priority"), _options(root, "ticket-fields", "complexity")
    assert str(medium.pk) in priorities and str(old_priority.pk) not in priorities
    assert str(easy.pk) in complexities and str(old_complexity.pk) not in complexities

    for field, value in (("priority", old_priority.pk), ("complexity", old_complexity.pk)):
        data = {field: value, ("complexity" if field == "priority" else "priority"): (
            easy.pk if field == "priority" else _priority("Высокая").pk)}
        response = client.post(f"/tickets/{ticket.number}/fields/", data, **HX)
        assert response.status_code == 200
        assert [code for code, _ in _alerts(response)] == ["archived_value"], field
        stored = _fresh(ticket)
        assert stored.priority_id == medium.pk and stored.complexity_id is None, f"{field}: ничего не меняется"
    assert _events(ticket) == [] and _journal("ticket.updated", ticket) == []

    with pytest.raises(ServiceDeskError) as caught:
        tickets.update_fields(ticket, actor=user, complexity=easy, priority=old_priority)
    assert caught.value.code == "archived_value"
    assert _fresh(ticket).complexity_id is None


def test_department_edit_writes_to_ticket_and_requester_record_always():
    """FR-246: подразделение, которое правит исполнитель, пишется в заявку и в запись заявителя всегда — и поверх другого
    значения записи; пустое значение стирает оба; событие ленты и журнал названия, журнал заявителя `requester.updated`."""
    queue = sd.make_queue()
    user = _member(queue.unit)
    old_unit, new_unit = _client_unit("Бухгалтерия"), _client_unit("Склад")
    requester = sd.make_requester(client_unit=old_unit)
    ticket = sd.make_ticket(queue=queue, requester=requester, client_unit=None)
    client = support.logged_in(user)

    response = client.post(f"/tickets/{ticket.number}/fields/", {"client_unit": new_unit.pk}, **HX)
    assert response.status_code == 200
    assert _fresh(ticket).client_unit_id == new_unit.pk
    assert _fresh(requester).client_unit_id == new_unit.pk, "в запись заявителя — всегда, даже если там было другое"
    events = _events(ticket, "client_unit_changed")
    assert len(events) == 1
    assert events[0].data == {"before": "", "after": "Склад", "before_id": None, "after_id": new_unit.pk}
    journal = _journal("ticket.updated", ticket)
    assert journal and journal[-1].after["client_unit"] == "Склад" and journal[-1].before["client_unit"] == ""
    record_journal = _journal("requester.updated", object_id=str(requester.pk))
    assert record_journal and record_journal[-1].actor_id == user.pk
    assert record_journal[-1].before["client_unit"] == "Бухгалтерия" and record_journal[-1].after["client_unit"] == "Склад"

    response = client.post(f"/tickets/{ticket.number}/fields/", {"client_unit": ""}, **HX)
    assert response.status_code == 200
    assert _fresh(ticket).client_unit_id is None and _fresh(requester).client_unit_id is None, "пусто стирает оба"
    cleared = _events(ticket, "client_unit_changed")
    assert len(cleared) == 2 and cleared[-1].data == {"before": "Склад", "after": "", "before_id": new_unit.pk, "after_id": None}


def test_requester_name_edit_event_has_no_values():
    """FR-246: правка ФИО заявителя в заявке пишет событие `requester_name_changed` с пустым `data` и журнал только с
    фактом «изменено»; ни старого, ни нового ФИО нет ни в ленте, ни в журнале; запись заявителя без кнопки не меняется."""
    queue = sd.make_queue()
    user = _member(queue.unit)
    requester = sd.make_requester(full_name="Прежний Заявитель")
    ticket = sd.make_ticket(queue=queue, requester=requester)
    client = support.logged_in(user)

    response = client.post(f"/tickets/{ticket.number}/fields/", {"requester_name": "Новый Заявитель"}, **HX)
    assert response.status_code == 200
    assert _fresh(ticket).requester_name == "Новый Заявитель"
    assert _fresh(requester).full_name == "Прежний Заявитель"

    events = _events(ticket)
    assert [e.event for e in events] == ["requester_name_changed"] and events[0].data == {}
    journal = _journal("ticket.updated", ticket)
    assert len(journal) == 1, "дополнение 21: ровно одно событие ticket.updated"
    assert journal[0].before == {} and journal[0].after == {"requester_name_changed": True}
    dump = json.dumps([e.data for e in events] + [[r.before, r.after] for r in journal], ensure_ascii=False)
    assert "Прежний" not in dump and "Новый" not in dump


def test_requester_name_save_also_in_record_button():
    """FR-246: у формы полей есть кнопка «Сохранить и в записи заявителя» (`button[name=save_to_record][value="1"]`);
    с ней ФИО пишется и в запись заявителя, без неё — только в заявку."""
    queue = sd.make_queue()
    user = _member(queue.unit)
    requester = sd.make_requester(full_name="Прежнее Имя")
    ticket = sd.make_ticket(queue=queue, requester=requester)
    client = support.logged_in(user)

    root = _page(client, ticket)
    forms = root.find_all("form", data_form="ticket-fields")
    assert len(forms) == 1
    buttons = forms[0].find_all("button", name="save_to_record")
    assert len(buttons) == 1 and buttons[0].attrs.get("value") == "1"
    assert "Сохранить и в записи заявителя" in buttons[0].text()
    assert forms[0].find_all("input", name="requester_name")

    client.post(f"/tickets/{ticket.number}/fields/", {"requester_name": "Только в заявке"}, **HX)
    assert _fresh(ticket).requester_name == "Только в заявке" and _fresh(requester).full_name == "Прежнее Имя"

    response = client.post(f"/tickets/{ticket.number}/fields/",
                           {"requester_name": "И в записи", "save_to_record": "1"}, **HX)
    assert response.status_code == 200
    assert _fresh(ticket).requester_name == "И в записи"
    assert _fresh(requester).full_name == "И в записи"
    record_journal = _journal("requester.updated", object_id=str(requester.pk))
    assert record_journal and record_journal[-1].after.get("name_changed") is True
    assert "И в записи" not in json.dumps([[r.before, r.after] for r in record_journal], ensure_ascii=False)


def test_subject_not_editable():
    """FR-246: тема заявки не правится — в форме полей нет поля темы, присланный `subject` игнорируется, а
    `update_fields(subject=…)` — `TypeError`."""
    from apps.servicedesk.services import tickets

    queue, user, ticket, client = _world(subject="Исходная тема")
    root = _page(client, ticket)
    assert root.find_all("form", data_form="ticket-fields")
    assert not [el for form in root.find_all("form", data_form="ticket-fields")
                for el in form.walk() if el.attrs.get("name") == "subject"]

    high = _priority("Высокая")
    response = client.post(f"/tickets/{ticket.number}/fields/", {"subject": "Подмена темы", "priority": high.pk}, **HX)
    assert response.status_code == 200
    stored = _fresh(ticket)
    assert stored.subject == "Исходная тема" and stored.priority_id == high.pk
    assert [e.event for e in _events(ticket)] == ["priority_changed"]

    client.post(f"/tickets/{ticket.number}/fields/", {"subject": "Только тема"}, **HX)
    assert _fresh(ticket).subject == "Исходная тема"
    assert [e.event for e in _events(ticket)] == ["priority_changed"]
    with pytest.raises(TypeError):
        tickets.update_fields(ticket, actor=user, subject="Подмена темы")
    assert _fresh(ticket).subject == "Исходная тема"


# --- участники: снятие -------------------------------------------------------------------------------

def test_remove_participant_marks_removed_and_writes_feed_and_journal_without_address():
    """FR-217: снятие участника (диалог с `confirm=1`) ставит `removed_at` и `removed_by`, пишет событие ленты и журнал
    `ticket.participant_removed` только с номером участника, без адреса; повтор тихий; чужой участник — 404."""
    from apps.servicedesk.services import tickets

    queue, user, ticket, client = _world()
    keep = sd.make_participant(ticket, f"keep@{DOMAIN}", name="Остающийся")
    gone = sd.make_participant(ticket, f"gone@{DOMAIN}", name="Уходящий")
    other = sd.make_participant(sd.make_ticket(queue=queue, requester=sd.make_requester()), f"x@{DOMAIN}")
    url = f"/tickets/{ticket.number}/participants/{gone.pk}/remove/"

    root = _page(client, ticket)
    section = root.find_all(data_section="participants")
    assert section
    links = [a for a in section[0].find_all("a", data_action="participant-remove")]
    assert sorted(a.attrs.get("hx-get", "") for a in links) == sorted(
        f"/tickets/{ticket.number}/participants/{p.pk}/remove/" for p in (keep, gone))

    dialog = client.get(url, **HX)
    assert dialog.status_code == 200
    dialog_el = _tree(dialog).find_all(data_dialog="participant-remove")
    assert len(dialog_el) == 1 and dialog_el[0].attrs.get("role") == "dialog" and dialog_el[0].attrs.get("aria-modal") == "true"
    assert len(dialog_el[0].find_all("form")) == 1
    assert [i.attrs.get("value") for i in dialog_el[0].find_all("input", name="confirm", type="hidden")] == ["1"]
    assert dialog_el[0].find_all("button", data_dialog_cancel=True)

    refused = client.post(url, {}, **HX)
    assert refused.status_code == 200 and any("Подтвердите действие" in text for _, text in _alerts(refused)), \
        "без confirm=1 — [role=alert] «Подтвердите действие»"
    assert _fresh(gone).removed_at is None and _events(ticket) == []
    assert client.post(f"/tickets/{ticket.number}/participants/{other.pk}/remove/", {"confirm": "1"}, **HX).status_code == 404
    assert _fresh(other).removed_at is None

    response = client.post(url, {"confirm": "1"}, **HX)
    assert response.status_code == 200
    stored = _fresh(gone)
    assert stored.removed_at is not None and stored.removed_by_id == user.pk
    assert _fresh(keep).removed_at is None

    events = _events(ticket)
    assert [e.event for e in events] == ["participant_removed"]
    assert events[0].data == {"participant_id": gone.pk} and events[0].author_id == user.pk
    journal = _journal("ticket.participant_removed", ticket)
    assert len(journal) == 1 and journal[0].actor_id == user.pk and journal[0].object_type == "ticket"
    assert journal[0].before == {} and journal[0].after == {"participant_id": gone.pk}
    dump = json.dumps([events[0].data, events[0].text, journal[0].before, journal[0].after], ensure_ascii=False)
    assert gone.email not in dump and "Уходящий" not in dump

    card = _tree(response)
    marked = [el for el in card.find_all(data_participant=True) if el.attrs.get("data-participant-id") == str(gone.pk)]
    assert marked and marked[0].attrs.get("data-removed") == "true"
    assert not [a for a in card.find_all("a", data_action="participant-remove")
                if a.attrs.get("hx-get") == f"/tickets/{ticket.number}/participants/{gone.pk}/remove/"]

    removed_at = stored.removed_at
    assert tickets.remove_participant(ticket, gone.pk, actor=user) is None
    assert _fresh(gone).removed_at == removed_at and len(_events(ticket)) == 1
    with pytest.raises(model("servicedesk.TicketParticipant").DoesNotExist):
        tickets.remove_participant(ticket, other.pk, actor=user)


def test_removed_participant_gets_no_letters(django_capture_on_commit_callbacks):
    """FR-217: снятый участник не получает писем заявки — ни в списке `letters.recipients`, ни в копии
    настоящего письма «взята в работу»; неснятый получает."""
    from apps.servicedesk.services import assignment, letters, tickets

    queue, user, ticket, _client = _world()
    keep = sd.make_participant(ticket, f"keep@{DOMAIN}")
    gone = sd.make_participant(ticket, f"gone@{DOMAIN}")
    tickets.remove_participant(ticket, gone.pk, actor=user)
    assignee = _member(queue.unit)

    for template in ("ticket.assigned", "ticket.closed", "ticket.reply", "ticket.reopened", "ticket.autoclosed"):
        to, cc = letters.recipients(_fresh(ticket), template)
        assert to == ticket.requester_email and list(cc) == [keep.email], template
    assert letters.recipients(_fresh(ticket), "ticket.confirmation") == (ticket.requester_email, [])

    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.assign(_fresh(ticket), assignee, actor=user) is True
    mails = [m for m in sd.ticket_mails(ticket) if m.template == "ticket.assigned"]
    assert len(mails) == 1 and mails[0].to == ticket.requester_email
    copy = [a.strip().lower() for a in mails[0].cc.split(",") if a.strip()]
    assert copy == [keep.email] and gone.email not in copy


def test_removed_participant_letter_not_appended_to_ticket(settings, protected_root, django_capture_on_commit_callbacks):
    """FR-217: письмо снятого участника в заявку не дописывается — создаётся новая заявка, старая остаётся с прежним
    числом писем; письмо заявителя в ту же заявку дописывается (письмо принимается, дело в снятии)."""
    from apps.servicedesk.services import intake, tickets

    settings.SERVICEDESK_MAILBOX = "tickets@stand.test"
    settings.DEFAULT_FROM_EMAIL = "portal@corp.test"
    queue = sd.make_queue()
    sd.configure_servicedesk(domains=[DOMAIN], default_queue=queue)
    staff = _member(queue.unit)
    requester = sd.make_requester(f"req@{DOMAIN}")
    ticket = sd.make_ticket(queue=queue, requester=requester)
    sd.make_entry(ticket, "incoming", text="Первое письмо")
    gone = sd.make_participant(ticket, f"gone@{DOMAIN}")
    tickets.remove_participant(ticket, gone.pk, actor=staff)

    def deliver(sender):
        raw = sd.build_mail(from_addr=sender, subject=f"[#{ticket.number}] Продолжение", text="Текст письма")
        message = email.message_from_bytes(raw, policy=policy.default)
        inbound = sd.make_inbound(size=len(raw), from_email=sender, subject="", message_id=str(message["Message-ID"] or ""))
        folder = protected_root / "inbound"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{inbound.pk}.eml").write_bytes(raw)
        with django_capture_on_commit_callbacks(execute=True):
            result = intake.process(inbound.pk)
        inbound.refresh_from_db()
        return result, inbound

    incoming = lambda: model("servicedesk.TicketEntry").objects.filter(ticket=ticket, kind="incoming").count()
    result, inbound = deliver(requester.email)
    assert result == "appended" and inbound.ticket_id == ticket.pk and incoming() == 2, "письмо заявителя дописано"

    result, inbound = deliver(gone.email)
    assert result == "created", "письмо снятого участника — новая заявка"
    assert inbound.ticket_id != ticket.pk and inbound.ticket.requester_email == gone.email
    assert incoming() == 2, "в старую заявку ничего не дописано"
    assert _fresh(gone).removed_at is not None


# --- закрытая заявка: отказ 200 с сообщением ---------------------------------------------------------

def test_closed_ticket_assign_and_transfer_refused_with_200_and_message():
    """FR-237, FR-239: на закрытой заявке назначение, взятие и передача отказывают `ticket_closed` — 200 с `[role=alert]`
    и текстом «Заявка закрыта: сначала откройте её», в том числе на GET диалога передачи и на прямой POST; в карточке
    нет форм назначения, передачи, ответа, полей и статуса, остаются «Открыть заново» и комментарий; сервис — `ticket_closed`."""
    from apps.servicedesk.services import ServiceDeskError, assignment, transfer

    queue, user, ticket, client, candidate = _closed_world()
    target = sd.make_queue()

    cases = [
        (f"/tickets/{ticket.number}/assign/", {"assignee": candidate.pk}),
        (f"/tickets/{ticket.number}/take/", {}),
        (f"/tickets/{ticket.number}/transfer/", {"queue": target.unit_id, "reason": "нужна другая очередь"}),
    ]
    for path, data in cases:
        _assert_closed_refusal(client.post(path, data, **HX), ticket, what=f"POST {path}")
        _assert_closed_refusal(client.post(path, data), ticket, what=f"POST без HTMX {path}")
    _assert_closed_refusal(client.get(f"/tickets/{ticket.number}/transfer/", **HX), ticket, what="GET диалога передачи")
    stored = _fresh(ticket)
    assert stored.assignee_id is None and stored.queue_id == queue.unit_id and stored.kind == "closed"
    assert _events(ticket) == [] and _journal("ticket.assigned", ticket) == [] and _journal("ticket.transferred", ticket) == []

    root = _page(client, ticket)
    card = root.find_all("div", data_ticket_card=True) or [el for el in root.walk() if "data-ticket-card" in el.attrs]
    assert card and card[0].attrs.get("data-kind") == "closed"
    for name in ("ticket-take", "ticket-assign", "ticket-unassign", "ticket-category", "ticket-fields", "ticket-status", "ticket-reply"):
        assert not root.find_all("form", data_form=name), f"на закрытой заявке нет формы {name}"
    assert not root.find_all("a", data_action="ticket-transfer") and not root.find_all("a", data_action="ticket-close")
    assert root.find_all("form", data_form="ticket-reopen") and root.find_all("form", data_form="ticket-comment")

    for call in (lambda: assignment.assign(ticket, candidate, actor=user), lambda: assignment.take(ticket, actor=user),
                 lambda: transfer.transfer(ticket, target.unit_id, actor=user)):
        with pytest.raises(ServiceDeskError) as caught:
            call()
        assert caught.value.code == "ticket_closed"
    assert _fresh(ticket).assignee_id is None


def test_closed_ticket_category_and_fields_change_refused_with_200_and_message():
    """FR-240, FR-246: на закрытой заявке смена категории и правка полей отказывают `ticket_closed` — 200 с `[role=alert]`
    и текстом «Заявка закрыта: сначала откройте её»; категория, критичность, подразделение, ФИО не меняются, событий нет."""
    from apps.servicedesk.services import ServiceDeskError, tickets, transfer

    queue, user, ticket, client, _candidate = _closed_world()
    other_category = sd.make_category(queue=sd.make_queue())
    own_category = sd.make_category(queue=queue)
    ticket.category = own_category
    ticket.save(update_fields=["category"])
    unit = _client_unit("Отдел продаж")
    high = _priority("Высокая")

    posts = [
        ("category", {"category": other_category.pk, "confirm": "1"}),
        ("category (та же очередь)", {"category": sd.make_category(queue=queue).pk, "confirm": "1"}),
        ("fields", {"priority": high.pk, "client_unit": unit.pk, "requester_name": "Новое Имя", "save_to_record": "1"}),
    ]
    for label, data in posts:
        path = f"/tickets/{ticket.number}/{label.split()[0]}/"
        _assert_closed_refusal(client.post(path, data, **HX), ticket, what=label)
    stored = _fresh(ticket)
    assert stored.category_id == own_category.pk and stored.priority_id == _priority("Средняя").pk
    assert stored.client_unit_id is None and stored.requester_name == ticket.requester_name
    assert stored.queue_id == queue.unit_id
    assert _events(ticket) == [] and _journal("ticket.updated", ticket) == []

    with pytest.raises(ServiceDeskError) as caught:
        tickets.update_fields(ticket, actor=user, priority=high)
    assert caught.value.code == "ticket_closed"
    with pytest.raises(ServiceDeskError) as caught:
        transfer.change_category(ticket, other_category, confirmed=True, actor=user)
    assert caught.value.code == "ticket_closed"


def test_closed_ticket_participant_removal_refused_with_200_and_message():
    """FR-217: на закрытой заявке снятие участника отказывает `ticket_closed` — 200 с `[role=alert]` и текстом
    «Заявка закрыта: сначала откройте её» (и на GET диалога); `removed_at` не ставится, событий нет; сервис — `ticket_closed`."""
    from apps.servicedesk.services import ServiceDeskError, tickets

    queue, user, ticket, client, _candidate = _closed_world()
    participant = sd.make_participant(ticket, f"cc@{DOMAIN}")
    url = f"/tickets/{ticket.number}/participants/{participant.pk}/remove/"

    _assert_closed_refusal(client.post(url, {"confirm": "1"}, **HX), ticket, what="POST снятия")
    _assert_closed_refusal(client.get(url, **HX), ticket, what="GET диалога снятия")
    assert _fresh(participant).removed_at is None and _fresh(participant).removed_by_id is None
    assert _events(ticket) == [] and _journal("ticket.participant_removed", ticket) == []
    with pytest.raises(ServiceDeskError) as caught:
        tickets.remove_participant(ticket, participant.pk, actor=user)
    assert caught.value.code == "ticket_closed"
    root = _page(client, ticket)
    assert not root.find_all("a", data_action="participant-remove"), "у закрытой заявки кнопок снятия нет"


# --- групповые действия ------------------------------------------------------------------------------

def _group_world(count: int = 3):
    """Очередь, исполнитель с входом, кандидат — участник той же очереди и `count` заявок очереди."""
    queue = sd.make_queue()
    actor = _member(queue.unit)
    candidate = _member(queue.unit)
    tickets_ = [sd.make_ticket(queue=queue, requester=sd.make_requester()) for _ in range(count)]
    return queue, actor, candidate, tickets_


def test_group_assign_applies_to_all_when_candidate_is_queue_member():
    """FR-241: групповое «Назначить ответственного» применяется ко всем заявкам, где кандидат — участник очереди:
    ответственный, статус «в работе», событие ленты и журнал на каждую; повторы номеров убираются, порядок входа сохранён."""
    from apps.servicedesk.services import assignment

    queue, actor, candidate, group = _group_world(3)
    numbers = [t.number for t in group]

    result = assignment.bulk(numbers + [numbers[0]], "assign", actor=actor, user=candidate)
    assert result.done == numbers and result.skipped == []
    for ticket in group:
        stored = _fresh(ticket)
        assert stored.assignee_id == candidate.pk and stored.assigned_once is True and stored.kind == "in_progress"
        events = _events(ticket, "assignee_changed")
        assert len(events) == 1
        assert events[0].data == {"before": "", "after": candidate.full_name, "before_id": None, "after_id": candidate.pk}
        journal = _journal("ticket.assigned", ticket)
        assert len(journal) == 1 and journal[0].actor_id == actor.pk
        assert journal[0].after == {"assignee": candidate.full_name, "assignee_id": candidate.pk}


def test_group_transfer_unassigns_non_member_of_new_queue():
    """FR-239, FR-241: групповая передача в очередь переносит все заявки; ответственный, не участник новой очереди,
    снимается (журнал `ticket.assignee_removed`, причина «смена очереди»), участник — остаётся; событие `transferred` на каждую."""
    from apps.servicedesk.services import assignment

    old, new = sd.make_queue(), sd.make_queue()
    actor = _member(old.unit)
    stays, leaves = _member(old.unit), _member(old.unit)
    org.make_member(stays, new.unit)
    kept = sd.make_ticket(queue=old, requester=sd.make_requester(), assignee=stays, assigned_once=True, kind="in_progress",
                          status=model("servicedesk.Status").objects.get(kind="in_progress", is_default=True))
    dropped = sd.make_ticket(queue=old, requester=sd.make_requester(), assignee=leaves, assigned_once=True, kind="in_progress",
                             status=model("servicedesk.Status").objects.get(kind="in_progress", is_default=True))

    result = assignment.bulk([kept.number, dropped.number], "transfer", actor=actor, queue_id=new.unit_id, reason="")
    assert result.done == [kept.number, dropped.number] and result.skipped == []
    assert _fresh(kept).queue_id == new.unit_id and _fresh(kept).assignee_id == stays.pk
    assert _fresh(dropped).queue_id == new.unit_id and _fresh(dropped).assignee_id is None
    for ticket in (kept, dropped):
        events = _events(ticket, "transferred")
        assert len(events) == 1 and events[0].data["from_id"] == old.unit_id and events[0].data["to_id"] == new.unit_id
        assert len(_journal("ticket.transferred", ticket)) == 1
    removed = _journal("ticket.assignee_removed", dropped)
    assert len(removed) == 1 and removed[0].after["reason"] == "queue_changed"
    assert removed[0].before["assignee_id"] == leaves.pk
    assert _journal("ticket.assignee_removed", kept) == []
    # дополнение 22: снятие ответственного — отдельное событие ленты assignee_changed
    removal = _events(dropped, "assignee_changed")
    assert len(removal) == 1
    assert removal[0].data == {"before": leaves.full_name, "after": "", "before_id": leaves.pk, "after_id": None}
    assert _events(kept, "assignee_changed") == []


def test_group_change_criticality_applies_to_available_tickets():
    """FR-241: групповая смена критичности применяется к доступным заявкам (событие `priority_changed` на каждую),
    недоступная пропускается и не меняется."""
    from apps.servicedesk.services import assignment

    queue, actor, _candidate, group = _group_world(2)
    foreign = sd.make_ticket(queue=sd.make_queue(), requester=sd.make_requester())
    high = _priority("Высокая")
    numbers = [group[0].number, foreign.number, group[1].number]

    result = assignment.bulk(numbers, "priority", actor=actor, priority_id=high.pk)
    assert result.done == [group[0].number, group[1].number]
    assert [(s.number, s.code) for s in result.skipped] == [(None, "no_access")]
    for ticket in group:
        assert _fresh(ticket).priority_id == high.pk
        events = _events(ticket, "priority_changed")
        assert len(events) == 1 and events[0].data["after_id"] == high.pk and events[0].data["before"] == "Средняя"
    assert _fresh(foreign).priority_id == _priority("Средняя").pk and _events(foreign) == []


def test_group_over_hundred_tickets_refused():
    """FR-241: больше 100 номеров — отказ `bulk_limit` до всякой работы (ни одна заявка не тронута; на маршруте — 200 с
    `[role=alert]`); ровно 100 — принимается; неизвестное действие — `bad_action`."""
    from apps.servicedesk.services import ServiceDeskError, assignment

    queue, actor, candidate, group = _group_world(2)
    client = support.logged_in(actor)
    numbers = [t.number for t in group] + list(range(900000, 900099))
    assert len(set(numbers)) == 101

    with pytest.raises(ServiceDeskError) as caught:
        assignment.bulk(numbers, "assign", actor=actor, user=candidate)
    assert caught.value.code == "bulk_limit"
    assert all(_fresh(t).assignee_id is None for t in group)
    assert _events(group[0]) == [] and _journal("ticket.assigned", group[0]) == []

    response = client.post("/tickets/bulk/", {"action": "assign", "user": candidate.pk, "numbers": numbers}, **HX)
    assert response.status_code == 200
    assert "bulk_limit" in [code for code, _ in _alerts(response)]
    assert all(_fresh(t).assignee_id is None for t in group)

    result = assignment.bulk(numbers[:100], "assign", actor=actor, user=candidate)
    assert result.done == [group[0].number, group[1].number] and len(result.skipped) == 98
    # дополнение 28 (б): повторы убираются до проверки предела — 100 разных номеров с повторами не отказ
    again = assignment.bulk(numbers[:100] + numbers[:5], "assign", actor=actor, user=candidate)
    assert len(again.done) + len(again.skipped) == 100

    with pytest.raises(ServiceDeskError) as caught:
        assignment.bulk([group[0].number], "delete", actor=actor)
    assert caught.value.code == "bad_action"
    response = client.post("/tickets/bulk/", {"action": "delete", "numbers": [group[0].number]}, **HX)
    assert response.status_code == 200 and "bad_action" in [code for code, _ in _alerts(response)]


def test_group_skips_inaccessible_ticket_without_revealing_number():
    """FR-241: недоступная заявка пропускается как несуществующая — `Skipped(number=None, code="no_access")`, «нет доступа»;
    номера нет ни в результате службы, ни в блоке итога на маршруте; чужая заявка не меняется."""
    from apps.servicedesk.services import assignment

    queue, actor, candidate, group = _group_world(1)
    foreign = sd.make_ticket(queue=sd.make_queue(), requester=sd.make_requester(), number=4711)
    missing_number = 4812
    client = support.logged_in(actor)

    result = assignment.bulk([foreign.number, missing_number, group[0].number], "assign", actor=actor, user=candidate)
    assert result.done == [group[0].number]
    assert [(s.number, s.code, s.message) for s in result.skipped] == [(None, "no_access", "нет доступа")] * 2
    assert "4711" not in repr(result)
    assert _fresh(foreign).assignee_id is None

    other = sd.make_ticket(queue=queue, requester=sd.make_requester())
    response = client.post("/tickets/bulk/", {"action": "priority", "priority": _priority("Низкая").pk,
                                              "numbers": [foreign.number, missing_number, other.number]}, **HX)
    assert response.status_code == 200
    block = _tree(response).find_all(data_bulk_result=True)
    assert len(block) == 1
    skipped = block[0].find_all("li", data_skipped=True)
    assert len(skipped) == 2 and all("нет доступа" in li.text() for li in skipped)
    assert "4711" not in block[0].text() and "4812" not in block[0].text()
    assert re.search(r"Выполнено:\s*1\s*;\s*пропущено:\s*2", block[0].text())
    assert _fresh(foreign).priority_id == _priority("Средняя").pk


def test_group_skips_inapplicable_ticket_with_reason_and_applies_others():
    """FR-241: заявка, к которой действие неприменимо (кандидат не участник её очереди), пропускается с номером и
    причиной `not_participant`, остальные применяются; неизвестный id кандидата даёт ту же причину для каждой заявки."""
    from apps.servicedesk.services import assignment

    queue_a, queue_b = sd.make_queue(), sd.make_queue()
    actor = _member(queue_a.unit)
    org.make_member(actor, queue_b.unit)
    candidate = _member(queue_a.unit)
    fits = sd.make_ticket(queue=queue_a, requester=sd.make_requester())
    misfit = sd.make_ticket(queue=queue_b, requester=sd.make_requester())

    result = assignment.bulk([misfit.number, fits.number], "assign", actor=actor, user=candidate)
    assert result.done == [fits.number]
    assert [(s.number, s.code) for s in result.skipped] == [(misfit.number, "not_participant")]
    assert result.skipped[0].message
    assert _fresh(fits).assignee_id == candidate.pk and _fresh(misfit).assignee_id is None
    assert _events(misfit) == [] and _journal("ticket.assigned", misfit) == []

    client = support.logged_in(actor)
    response = client.post("/tickets/bulk/", {"action": "assign", "user": 99999999, "numbers": [fits.number, misfit.number]}, **HX)
    assert response.status_code == 200
    block = _tree(response).find_all(data_bulk_result=True)
    assert len(block) == 1 and len(block[0].find_all("li", data_skipped=True)) == 2
    assert re.search(r"Выполнено:\s*0\s*;\s*пропущено:\s*2", block[0].text())


def test_group_skips_closed_ticket_with_reason():
    """FR-241: закрытая заявка пропускается с номером и причиной `ticket_closed` (сообщение «Заявка закрыта: сначала
    откройте её») и при назначении, и при передаче, и при смене критичности; открытая применяется, закрытая не меняется."""
    from apps.servicedesk.services import assignment

    queue, actor, candidate, group = _group_world(1)
    closed = sd.make_ticket(queue=queue, requester=sd.make_requester(), kind="closed")
    target = sd.make_queue()
    actions = (("assign", {"user": candidate}), ("transfer", {"queue_id": target.unit_id, "reason": ""}),
               ("priority", {"priority_id": _priority("Высокая").pk}))
    for action, params in actions:
        ticket = sd.make_ticket(queue=queue, requester=sd.make_requester())
        result = assignment.bulk([closed.number, ticket.number], action, actor=actor, **params)
        assert result.done == [ticket.number], action
        assert [(s.number, s.code, s.message) for s in result.skipped] == [(closed.number, "ticket_closed", CLOSED_TEXT)], action
    stored = _fresh(closed)
    assert stored.assignee_id is None and stored.queue_id == queue.unit_id and stored.priority_id == _priority("Средняя").pk
    assert _events(closed) == []


def test_group_each_ticket_in_own_savepoint(monkeypatch):
    """FR-241: каждая заявка группового действия — в своей точке сохранения: подменённая `assignment.assign` пишет часть
    данных второй заявки и поднимает `ServiceDeskError` — её изменения откатились, заявка пропущена с кодом ошибки,
    остальные заявки применены и остались."""
    from apps.servicedesk.services import ServiceDeskError, assignment

    queue, actor, candidate, group = _group_world(3)
    broken = group[1]
    original = assignment.assign

    def writes_then_raises(ticket, user, *, actor, ip=None):
        if ticket.number == broken.number:
            model("servicedesk.Ticket").objects.filter(pk=ticket.pk).update(assignee=user, assigned_once=True)
            sd.make_entry(ticket, "comment", text="часть данных")
            raise ServiceDeskError("not_participant", "сбой этой заявки")
        return original(ticket, user, actor=actor, ip=ip)

    monkeypatch.setattr(assignment, "assign", writes_then_raises)
    entries_before = _entry_count(broken)
    result = assignment.bulk([t.number for t in group], "assign", actor=actor, user=candidate)

    assert result.done == [group[0].number, group[2].number]
    assert [(s.number, s.code, s.message) for s in result.skipped] == [(broken.number, "not_participant", "сбой этой заявки")]
    stored = _fresh(broken)
    assert stored.assignee_id is None and stored.assigned_once is False, "частичная запись откатилась"
    assert _entry_count(broken) == entries_before
    for ticket in (group[0], group[2]):
        assert _fresh(ticket).assignee_id == candidate.pk, "остальные заявки остались применёнными"


def test_group_summary_fragment_done_n_skipped_m_with_list():
    """FR-241: итог группового действия — блок `[data-bulk-result]` «Выполнено: N; пропущено: M» и `li[data-skipped]` с
    «#номер — причина» на каждую пропущенную; у недоступной номера нет; на запрос HTMX — фрагмент без `<html>`, на обычный —
    страница списка с тем же блоком."""
    queue, actor, candidate, group = _group_world(2)
    closed = sd.make_ticket(queue=queue, requester=sd.make_requester(), kind="closed")
    foreign = sd.make_ticket(queue=sd.make_queue(), requester=sd.make_requester(), number=4711)
    numbers = [group[0].number, closed.number, foreign.number, group[1].number]
    client = support.logged_in(actor)

    response = client.post("/tickets/bulk/", {"action": "assign", "user": candidate.pk, "numbers": numbers}, **HX)
    assert response.status_code == 200
    assert "<html" not in response.content.decode("utf-8", "replace").lower()
    blocks = _tree(response).find_all(data_bulk_result=True)
    assert len(blocks) == 1
    assert re.search(r"Выполнено:\s*2\s*;\s*пропущено:\s*2", blocks[0].text())
    items = blocks[0].find_all("li", data_skipped=True)
    texts = sorted(li.text() for li in items)
    assert len(items) == 2
    closed_text = [t for t in texts if f"#{closed.number}" in t]
    assert len(closed_text) == 1 and CLOSED_TEXT in closed_text[0]
    hidden = [t for t in texts if "нет доступа" in t]
    assert len(hidden) == 1 and "4711" not in hidden[0]
    assert all(_fresh(t).assignee_id == candidate.pk for t in group)

    page = client.post("/tickets/bulk/", {"action": "priority", "priority": _priority("Высокая").pk, "numbers": numbers})
    assert page.status_code == 200
    assert "<html" in page.content.decode("utf-8", "replace").lower()
    blocks = _tree(page).find_all(data_bulk_result=True)
    assert len(blocks) == 1 and re.search(r"Выполнено:\s*2\s*;\s*пропущено:\s*2", blocks[0].text())
