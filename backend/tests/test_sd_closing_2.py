"""T-3117: открытие заново и продолжение заявки (FR-205, FR-251, FR-252, FR-256).

Сценарии 5 и 6 спеки среза 003. Письмо к закрытой заявке кладётся строкой `InboundMail` и файлом
`protected/inbound/<id>.eml` (помощники этого файла) и разбирается настоящим `intake.process(id)` внутри
`django_capture_on_commit_callbacks(execute=True)`; ручное открытие — `closing.reopen` и маршрут
`/tickets/<номер>/reopen/`. Срок — `backdate(ticket, "closed_at", days=…)` с запасом по обе стороны границы.
Имена кода среза 003 импортируются внутри тестов: сбор проходит до появления кода.
Правила — tests/CONTRACT-003.md (§ 3.5, 6.2, 6.11, 6.16, 9.2, 9.3, 12.4, 13.3, 14.5, 16: дополнения 9, 16).
"""
import re
import secrets
from html.parser import HTMLParser

import pytest
from django.utils import timezone

from tests import support, support_org as org, support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

DOMAIN = "corp.test"
MAILBOX = "tickets@stand.test"
SMTP_FROM = "portal@corp.test"
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- помощники только этого файла ------------------------------------------------------------------

def _addr(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(3)}@{DOMAIN}"


def _prepare(settings):
    """Ящик, адрес отправки портала, домен и очередь по умолчанию; возвращает её `Queue`."""
    settings.SERVICEDESK_MAILBOX = MAILBOX
    settings.DEFAULT_FROM_EMAIL = SMTP_FROM
    default = sd.make_queue()
    sd.configure_servicedesk(domains=[DOMAIN], default_queue=default)
    return default


def _member(unit, name: str = "Участников Иван"):
    user = support.make_employee(full_name=name)
    org.make_member(user, unit)
    return user


def _closed(queue_row, *, days: int, requester=None, assignee=None, status=None, resolution="Готово",
            closed_by=None, **over):
    """Закрытая заявка с первым письмом заявителя; `closed_at` сдвинут назад на `days` суток."""
    requester = requester or sd.make_requester(_addr("req"))
    fields = {"queue": queue_row, "requester": requester, "kind": "closed", "closed_at": timezone.now(),
              "closed_by": closed_by, "resolution": resolution, "assignee": assignee,
              "assigned_once": assignee is not None}
    if status is not None:
        fields["status"] = status
    fields.update(over)
    ticket = sd.make_ticket(**fields)
    sd.make_entry(ticket, "incoming", text="Первое письмо")
    if days:
        sd.backdate(ticket, "closed_at", days=days)
    ticket.refresh_from_db()
    return ticket


def _store(raw: bytes, protected_root, **over):
    """Строка `InboundMail` и файл письма: `make_inbound` файла не создаёт."""
    inbound = sd.make_inbound(size=len(raw), **over)
    folder = protected_root / "inbound"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{inbound.pk}.eml").write_bytes(raw)
    return inbound


def _letter(ticket, sender, protected_root, capture, *, text="Не помогло"):
    """Письмо `sender` с `[#N]` в теме разбирается настоящим `intake`; (итог, свежая строка `InboundMail`)."""
    from apps.servicedesk.services import intake

    raw = sd.build_mail(from_addr=sender, to=[MAILBOX], subject=f"[#{ticket.number}] Ответ", text=text)
    inbound = _store(raw, protected_root, from_email=sender)
    with capture(execute=True):
        result = intake.process(inbound.pk)
    inbound.refresh_from_db()
    return result, inbound


def _fresh(ticket):
    return model("servicedesk.Ticket").objects.get(pk=ticket.pk)


def _tickets_pks() -> set:
    return set(model("servicedesk.Ticket").objects.values_list("pk", flat=True))


def _events(ticket, code):
    return list(model("servicedesk.TicketEntry").objects.filter(ticket=ticket, kind="event", event=code)
                .order_by("id"))


def _incoming(ticket):
    return list(ticket.entries.filter(kind="incoming").order_by("at", "id"))


def _audit(action, ticket):
    return list(model("core.AuditEvent").objects.filter(action=action, object_type="ticket", object_id=str(ticket.number))
                .order_by("id"))


def _mails(ticket, template):
    return [m for m in sd.ticket_mails(ticket) if m.template == template]


def _copies(message) -> set:
    return {a.strip() for a in message.cc.split(",") if a.strip()}


def _assert_assignee_removed(ticket, user, reason, bus_spy) -> None:
    """Снятие ответственного открытием (дополнение 22): событие ленты, журнал с причиной и событие шины."""
    removed = _events(ticket, "assignee_changed")
    assert len(removed) == 1
    assert (removed[0].data["before"], removed[0].data["after"]) == (user.full_name, "")
    assert (removed[0].data["before_id"], removed[0].data["after_id"]) == (user.pk, None)
    journal = _audit("ticket.assignee_removed", ticket)
    assert len(journal) == 1 and journal[0].object_type == "ticket"
    assert journal[0].before == {"assignee": user.full_name, "assignee_id": user.pk}
    assert journal[0].after == {"assignee": "", "assignee_id": None, "reason": reason}
    published = [c for c in bus_spy.calls("servicedesk.assignee_changed") if c["number"] == ticket.number]
    assert [(c["assignee_before_id"], c["assignee_after_id"]) for c in published] == [(user.pk, None)]


def _dismiss(user) -> None:
    model("core.User").objects.filter(pk=user.pk).update(state="dismissed")


def _status(kind: str, **filters):
    return model("servicedesk.Status").objects.get(kind=kind, **filters)


class _Page(HTMLParser):
    """Все элементы страницы: тег, атрибуты, текст (с вложенными); `text` — весь текст страницы."""

    def __init__(self):
        super().__init__()
        self.elements = []
        self._stack = []
        self._all = []

    def handle_starttag(self, tag, attrs):
        element = {"tag": tag, "attrs": {k: (v if v is not None else "") for k, v in attrs}, "parts": []}
        self.elements.append(element)
        if tag not in _VOID:
            self._stack.append(element)

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        while self._stack:
            if self._stack.pop()["tag"] == tag:
                break

    def handle_data(self, data):
        self._all.append(data)
        for element in self._stack:
            element["parts"].append(data)

    @property
    def text(self) -> str:
        return " ".join(" ".join(self._all).split())


def _parse(response) -> _Page:
    page = _Page()
    page.feed(response.content.decode("utf-8", "replace"))
    return page


def _find(page, tag=None, **attrs) -> list:
    """Элементы с этими атрибутами (`data_field="previous"` — `data-field`); у каждого `el["text"]`."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for element in page.elements:
        if tag is not None and element["tag"] != tag:
            continue
        if all(element["attrs"].get(name) == value for name, value in wanted.items()):
            element["text"] = " ".join(" ".join(element["parts"]).split())
            found.append(element)
    return found


def _card(user, ticket):
    response = support.logged_in(user).get(f"/tickets/{ticket.number}/")
    assert response.status_code == 200, response.status_code
    return _parse(response)


def _has_number(text: str, number: int) -> bool:
    return re.search(rf"#{number}(?!\d)", text) is not None


# --- открытие письмом ------------------------------------------------------------------------------

def test_requester_letter_within_term_reopens_in_work_same_queue_assignee_kept(
        settings, protected_root, django_capture_on_commit_callbacks):
    """FR-251, сценарий 5.3: письмо заявителя с номером закрытой 3 дня назад заявки открывает её: «В работе» (статус
    по умолчанию вида), своя очередь, прежний ответственный; письмо дописано в ту же заявку, новой заявки нет."""
    default = _prepare(settings)
    queue_row = sd.make_queue()
    assignee = _member(queue_row.unit)
    ticket = _closed(queue_row, days=3, assignee=assignee, closed_by=assignee)
    count = model("servicedesk.Ticket").objects.count()

    result, inbound = _letter(ticket, ticket.requester_email, protected_root, django_capture_on_commit_callbacks)

    assert result == "reopened"
    assert (inbound.outcome, inbound.status, inbound.ticket_id) == ("reopened", "processed", ticket.pk)
    assert model("servicedesk.Ticket").objects.count() == count
    ticket = _fresh(ticket)
    assert ticket.kind == "in_progress" and ticket.status.kind == "in_progress" and ticket.status.is_default
    assert ticket.queue_id == queue_row.unit_id != default.unit_id
    assert ticket.assignee_id == assignee.pk
    assert ticket.closed_at is None and ticket.closed_by_id is None
    assert len(_incoming(ticket)) == 2 and inbound.entries.get().ticket_id == ticket.pk
    assert ticket.last_message_from == "requester"


def test_participant_letter_within_term_reopens_ticket(settings, protected_root, django_capture_on_commit_callbacks):
    """FR-251: письмо неснятого участника из копии с номером закрытой заявки (в срок) тоже открывает её и
    дописывается: автор элемента — адрес участника."""
    _prepare(settings)
    queue_row = sd.make_queue()
    ticket = _closed(queue_row, days=2)
    participant = sd.make_participant(ticket, _addr("partner"), name="Партнёр")

    result, inbound = _letter(ticket, participant.email, protected_root, django_capture_on_commit_callbacks)

    assert result == "reopened"
    assert (inbound.outcome, inbound.ticket_id) == ("reopened", ticket.pk)
    ticket = _fresh(ticket)
    assert ticket.kind == "in_progress" and ticket.closed_at is None
    entry = inbound.entries.get()
    assert entry.kind == "incoming" and entry.author_email == participant.email
    assert ticket.last_message_from == "requester"


def test_reopen_by_letter_sends_reopened_letter(settings, protected_root, django_capture_on_commit_callbacks):
    """FR-251, FR-256, сценарий 5.3: после открытия письмом уходит одно письмо «открыта заново» (`ticket.reopened`)
    заявителю, в копию — неснятые участники; текст «Заявка № N снова в работе.»; подтверждения нет."""
    _prepare(settings)
    queue_row = sd.make_queue()
    ticket = _closed(queue_row, days=3)
    active = sd.make_participant(ticket, _addr("active"))
    sd.make_participant(ticket, _addr("removed"), removed_by=_member(queue_row.unit))

    result, _ = _letter(ticket, ticket.requester_email, protected_root, django_capture_on_commit_callbacks)

    assert result == "reopened"
    letters = _mails(ticket, "ticket.reopened")
    assert len(letters) == 1
    letter = letters[0]
    assert letter.to == ticket.requester_email
    assert _copies(letter) == {active.email}
    assert letter.auto_submitted == "auto-generated"
    assert f"Заявка № {ticket.number} снова в работе." in sd.mail_text(letter)
    assert _mails(ticket, "ticket.confirmation") == []


# --- письмо после срока, продолжение ---------------------------------------------------------------

def _continuation_world(settings, protected_root, capture):
    """Закрытая 10 дней назад заявка и письмо заявителя; возвращает (прежняя, новая, письмо, очередь по умолчанию,
    очередь прежней заявки)."""
    default = _prepare(settings)
    queue_row = sd.make_queue()
    old = _closed(queue_row, days=10, closed_by=_member(queue_row.unit, "Закрывалов Пётр"))
    before = _tickets_pks()
    result, inbound = _letter(old, old.requester_email, protected_root, capture)
    assert result == "created"
    new = model("servicedesk.Ticket").objects.exclude(pk__in=before).get()
    return old, new, inbound, default, queue_row


def test_letter_after_term_creates_new_ticket_with_previous_and_confirmation(
        settings, protected_root, django_capture_on_commit_callbacks):
    """FR-251, FR-205, сценарий 5.4: письмо к закрытой 10 дней назад заявке при сроке 7 дней создаёт новую заявку с
    `previous`, в очереди по умолчанию, с обычным подтверждением; на карточке — «продолжение заявки #N»."""
    old, new, inbound, default, queue_row = _continuation_world(settings, protected_root,
                                                                django_capture_on_commit_callbacks)

    assert (inbound.outcome, inbound.status, inbound.ticket_id) == ("created", "processed", new.pk)
    assert new.previous_id == old.pk
    assert new.queue_id == default.unit_id and new.kind == "new"
    assert new.requester_email == old.requester_email
    assert inbound.entries.get().ticket_id == new.pk
    confirmations = _mails(new, "ticket.confirmation")
    assert len(confirmations) == 1 and confirmations[0].to == old.requester_email
    assert f"под номером {new.number}" in sd.mail_text(confirmations[0])
    assert _mails(new, "ticket.reopened") == [] and _mails(old, "ticket.reopened") == []
    viewer = _member(default.unit)
    org.make_member(viewer, queue_row.unit)
    links = _find(_card(viewer, new), "a", data_field="previous")
    assert len(links) == 1 and links[0]["attrs"]["href"] == f"/tickets/{old.number}/"
    assert "продолжение заявки" in links[0]["text"] and _has_number(links[0]["text"], old.number)


def test_continuation_links_both_ways_and_old_ticket_stays_closed(
        settings, protected_root, django_capture_on_commit_callbacks):
    """FR-205, FR-251: связь в обе стороны — у новой `previous`, у прежней событие ленты `continued` с номером новой
    и ссылка `continuation` на карточке; прежняя остаётся закрытой и не меняется; у заявок без связи элементов нет."""
    old, new, inbound, default, queue_row = _continuation_world(settings, protected_root,
                                                                django_capture_on_commit_callbacks)
    snapshot = _fresh(old)

    assert snapshot.kind == "closed" and snapshot.closed_at == old.closed_at
    assert snapshot.closed_by_id == old.closed_by_id and snapshot.resolution == old.resolution
    assert snapshot.status_id == old.status_id
    assert [t.pk for t in snapshot.continuations.all()] == [new.pk]
    continued = _events(old, "continued")
    assert len(continued) == 1 and continued[0].data["number"] == new.number
    assert _events(old, "reopened") == [] and len(_incoming(old)) == 1
    assert _mails(old, "ticket.reopened") == []

    viewer = _member(default.unit)
    org.make_member(viewer, queue_row.unit)
    old_page, new_page = _card(viewer, old), _card(viewer, new)
    links = _find(old_page, "a", data_field="continuation")
    assert len(links) == 1 and links[0]["attrs"]["href"] == f"/tickets/{new.number}/"
    assert "продолжение — заявка" in links[0]["text"] and _has_number(links[0]["text"], new.number)
    assert _find(old_page, data_field="previous") == []
    assert _find(new_page, data_field="continuation") == []


def test_continuation_link_opens_only_for_those_with_access_to_old_ticket(
        settings, protected_root, django_capture_on_commit_callbacks):
    """FR-205 (дополнение 9): тому, кому другая заявка не видна, остаётся элемент связи без `<a>` и без `href` с тем
    же текстом (номер целым числом); права на прежнюю заявку не расширяются; видящему обе — ссылки."""
    old, new, _, default, queue_row = _continuation_world(settings, protected_root,
                                                          django_capture_on_commit_callbacks)
    only_new = _member(default.unit, "Новиков Николай")
    only_old = _member(queue_row.unit, "Старов Сергей")
    both = _member(default.unit, "Обоев Олег")
    org.make_member(both, queue_row.unit)

    assert support.logged_in(only_new).get(f"/tickets/{old.number}/").status_code == 404
    plain = _find(_card(only_new, new), data_field="previous")
    assert len(plain) == 1 and plain[0]["tag"] != "a" and "href" not in plain[0]["attrs"]
    assert "продолжение заявки" in plain[0]["text"] and _has_number(plain[0]["text"], old.number)
    assert _find(_card(only_new, new), "a", data_field="previous") == []

    assert support.logged_in(only_old).get(f"/tickets/{new.number}/").status_code == 404
    plain = _find(_card(only_old, old), data_field="continuation")
    assert len(plain) == 1 and plain[0]["tag"] != "a" and "href" not in plain[0]["attrs"]
    assert "продолжение — заявка" in plain[0]["text"] and _has_number(plain[0]["text"], new.number)

    linked_new = _find(_card(both, new), "a", data_field="previous")
    linked_old = _find(_card(both, old), "a", data_field="continuation")
    assert [a["attrs"]["href"] for a in linked_new] == [f"/tickets/{old.number}/"]
    assert [a["attrs"]["href"] for a in linked_old] == [f"/tickets/{new.number}/"]


def test_reopen_term_read_from_settings_on_each_letter(settings, protected_root, django_capture_on_commit_callbacks):
    """FR-251, сценарий 5.7: срок открытия заново читается из настроек при каждом письме: заявка, закрытая 5 дней
    назад, открывается при сроке 7 и даёт новую заявку при сроке 3; смена срока записана в журнал."""
    from apps.servicedesk.services import closing, settings as sd_settings

    default = _prepare(settings)
    queue_row = sd.make_queue()
    admin = support.make_admin()
    first = _closed(queue_row, days=5)
    second = _closed(queue_row, days=5)
    third = _closed(queue_row, days=20)
    assert closing.within_reopen_term(first) is True and closing.within_reopen_term(third) is False

    result, _ = _letter(first, first.requester_email, protected_root, django_capture_on_commit_callbacks)
    assert result == "reopened" and _fresh(first).kind == "in_progress"

    sd_settings.update(actor=admin, reopen_days=3)
    assert closing.within_reopen_term(second) is False
    before = _tickets_pks()
    result, inbound = _letter(second, second.requester_email, protected_root, django_capture_on_commit_callbacks)
    assert result == "created"
    created = model("servicedesk.Ticket").objects.exclude(pk__in=before).get()
    assert created.previous_id == second.pk and created.queue_id == default.unit_id
    assert _fresh(second).kind == "closed"

    sd_settings.update(actor=admin, reopen_days=30)
    result, _ = _letter(third, third.requester_email, protected_root, django_capture_on_commit_callbacks)
    assert result == "reopened" and _fresh(third).kind == "in_progress"

    journal = list(model("core.AuditEvent").objects.filter(action="servicedesk.settings_changed").order_by("id"))
    assert [(e.before["reopen_days"], e.after["reopen_days"]) for e in journal] == [(7, 3), (3, 30)]


def test_autoclosed_ticket_reopened_by_requester_within_term(settings, protected_root,
                                                             django_capture_on_commit_callbacks):
    """FR-251, сценарий 6.5: закрытая автоматически заявка открывается письмом заявителя в пределах срока, как любая
    закрытая: «В работе», `closed_at` пусто."""
    from apps.servicedesk.services import closing

    _prepare(settings)
    queue_row = sd.make_queue()
    ticket = sd.make_ticket(queue=queue_row, kind="waiting")
    sd.make_entry(ticket, "incoming", text="Первое письмо")
    sd.backdate(ticket, "waiting_since", days=8)
    ticket = _fresh(ticket)
    with django_capture_on_commit_callbacks(execute=True):
        assert closing.autoclose_one(ticket.pk) is True
    ticket = _fresh(ticket)
    assert ticket.kind == "closed" and ticket.status.system_code == "autoclosed" and ticket.closed_by_id is None
    sd.backdate(ticket, "closed_at", days=3)
    assert closing.within_reopen_term(_fresh(ticket)) is True

    result, inbound = _letter(ticket, ticket.requester_email, protected_root, django_capture_on_commit_callbacks)

    assert result == "reopened" and inbound.ticket_id == ticket.pk
    ticket = _fresh(ticket)
    assert ticket.kind == "in_progress" and ticket.status.is_default and ticket.status.system_code == ""
    assert ticket.closed_at is None and ticket.closed_by_id is None
    assert len(_mails(ticket, "ticket.reopened")) == 1


def test_corporate_stranger_letter_to_closed_ticket_creates_new_ticket(
        settings, protected_root, django_capture_on_commit_callbacks):
    """FR-251, сценарий 5.5: письмо с номером закрытой заявки от корпоративного адреса, не заявителя и не участника,
    создаёт новую заявку без `previous`; закрытая не открывается и не меняется."""
    default = _prepare(settings)
    queue_row = sd.make_queue()
    ticket = _closed(queue_row, days=2)
    sd.make_participant(ticket, _addr("partner"))
    stranger = _addr("stranger")
    before = _tickets_pks()

    result, inbound = _letter(ticket, stranger, protected_root, django_capture_on_commit_callbacks)

    assert result == "created"
    new = model("servicedesk.Ticket").objects.exclude(pk__in=before).get()
    assert inbound.ticket_id == new.pk and (inbound.outcome, inbound.status) == ("created", "processed")
    assert new.requester_email == stranger and new.previous_id is None
    assert new.queue_id == default.unit_id and new.kind == "new"
    assert len(_mails(new, "ticket.confirmation")) == 1
    old = _fresh(ticket)
    assert old.kind == "closed" and old.closed_at == ticket.closed_at and old.resolution == ticket.resolution
    assert len(_incoming(old)) == 1 and _events(old, "reopened") == [] and _events(old, "continued") == []
    assert _mails(old, "ticket.reopened") == []


# --- открытие вручную ------------------------------------------------------------------------------

def test_manual_reopen_in_any_term_with_reopened_letter(settings, django_capture_on_commit_callbacks):
    """FR-252, FR-256, сценарий 5.6: закрытую год назад заявку участник очереди открывает кнопкой «Открыть заново»
    (форма на карточке, POST `…/reopen/`); заявитель и участники получают письмо «открыта заново»; у открытой
    заявки кнопки нет, повторное открытие — отказ `ticket_open` (200 с `[role=alert]`)."""
    _prepare(settings)
    queue_row = sd.make_queue()
    member = _member(queue_row.unit)
    ticket = _closed(queue_row, days=365)
    participant = sd.make_participant(ticket, _addr("partner"))
    path = f"/tickets/{ticket.number}/reopen/"

    page = _card(member, ticket)
    forms = _find(page, "form", data_form="ticket-reopen")
    assert len(forms) == 1 and forms[0]["attrs"].get("action", path) == path
    assert _find(page, "button", data_action="ticket-reopen", type="submit")

    client = support.logged_in(member)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(path)
    assert response.status_code == 302 and response["Location"] == f"/tickets/{ticket.number}/"
    ticket = _fresh(ticket)
    assert ticket.kind == "in_progress" and ticket.closed_at is None and ticket.queue_id == queue_row.unit_id
    letters = _mails(ticket, "ticket.reopened")
    assert len(letters) == 1 and letters[0].to == ticket.requester_email and _copies(letters[0]) == {participant.email}
    assert f"Заявка № {ticket.number} снова в работе." in sd.mail_text(letters[0])
    assert _find(_card(member, ticket), "form", data_form="ticket-reopen") == []

    with django_capture_on_commit_callbacks(execute=True):
        again = client.post(path)
    assert again.status_code == 200 and _find(_parse(again), role="alert")
    assert "Заявка не закрыта: открывать заново нечего" in _parse(again).text
    assert len(_mails(ticket, "ticket.reopened")) == 1

    # ответственный чужой очереди (не участник) открывает успешно (дополнение 27 (в))
    foreign = support.make_employee(full_name="Ответов Роман")
    owned = _closed(sd.make_queue(), days=200, assignee=foreign)
    with django_capture_on_commit_callbacks(execute=True):
        by_assignee = support.logged_in(foreign).post(f"/tickets/{owned.number}/reopen/")
    assert by_assignee.status_code == 302
    assert _fresh(owned).kind == "in_progress" and _fresh(owned).closed_at is None


def test_manual_reopen_refused_for_outsider_even_direct_request(settings, django_capture_on_commit_callbacks):
    """FR-252: тот, кто не видит заявку, не открывает её ни маршрутом (404 как у несуществующей), ни прямым вызовом
    службы (`no_access`); `access.can_work` ложно; состояние и письма не меняются."""
    from apps.servicedesk.services import ServiceDeskError, access, closing

    _prepare(settings)
    queue_row = sd.make_queue()
    member = _member(queue_row.unit)
    outsider = _member(sd.make_queue().unit, "Чужаков Игорь")
    ticket = _closed(queue_row, days=4)
    assert access.can_work(member, ticket) is True and access.can_work(outsider, ticket) is False

    with django_capture_on_commit_callbacks(execute=True):
        response = support.logged_in(outsider).post(f"/tickets/{ticket.number}/reopen/")
        with pytest.raises(ServiceDeskError) as refused:
            closing.reopen(ticket, actor=outsider)
    assert response.status_code == 404
    assert refused.value.code == "no_access"
    unchanged = _fresh(ticket)
    assert unchanged.kind == "closed" and unchanged.closed_at == ticket.closed_at
    assert _events(unchanged, "reopened") == [] and _audit("ticket.reopened", unchanged) == []
    assert sd.ticket_mails(unchanged) == []


# --- очередь, ответственный, поля при открытии -----------------------------------------------------

def _unmark_world(settings):
    """Очередь, с которой снята отметка (в ней только закрытые заявки); возвращает (по умолчанию, снятая, админ)."""
    from apps.servicedesk.services import queues

    default = _prepare(settings)
    gone = sd.make_queue()
    admin = support.make_admin()
    return default, gone, admin, queues


def _assert_moved_to_default(ticket, gone, default):
    ticket = _fresh(ticket)
    assert ticket.queue_id == default.unit_id and ticket.kind == "in_progress"
    moved = _events(ticket, "queue_changed")
    assert len(moved) == 1
    data = moved[0].data
    assert (data["from_id"], data["to_id"], data["reason"]) == (gone.unit_id, default.unit_id, "queue_unmarked")
    assert data["from"] == gone.unit.name and data["to"] == default.unit.name
    return ticket


def test_reopen_by_letter_when_node_not_queue_goes_to_default_queue_with_event(
        settings, protected_root, bus_spy, django_capture_on_commit_callbacks):
    """FR-251, сценарий 5.9: узел закрытой заявки больше не очередь — письмо заявителя в срок открывает её в очереди
    по умолчанию, в ленте одно событие «очередь: было → стало» с причиной `queue_unmarked` (подпись «очередь
    снята»). Ответственный, участник только прежнего узла, в очереди по умолчанию снимается: событие ленты
    `assignee_changed`, журнал `ticket.assignee_removed` с причиной `queue_changed`, событие шины (дополнение 22)."""
    default, gone, admin, queues = _unmark_world(settings)
    bus_spy.listen("servicedesk.assignee_changed")
    former = _member(gone.unit, "Прежнев Павел")
    ticket = _closed(gone, days=3, assignee=former)
    queues.unmark(gone.unit_id, actor=admin)
    assert not model("servicedesk.Queue").objects.filter(unit_id=gone.unit_id).exists()

    result, inbound = _letter(ticket, ticket.requester_email, protected_root, django_capture_on_commit_callbacks)

    assert result == "reopened" and inbound.ticket_id == ticket.pk
    ticket = _assert_moved_to_default(ticket, gone, default)
    assert ticket.assignee_id is None
    _assert_assignee_removed(ticket, former, "queue_changed", bus_spy)
    assert len(_events(ticket, "reopened")) == 1
    text = _card(_member(default.unit), ticket).text
    assert "причина — очередь снята" in text


def test_manual_reopen_when_node_not_queue_goes_to_default_queue_with_event(
        settings, django_capture_on_commit_callbacks):
    """FR-252, сценарий 5.9: ручное открытие заявки узла, который больше не очередь, переводит её в очередь по
    умолчанию с тем же событием `queue_changed` и причиной `queue_unmarked`. Открывает участник узла без отметки
    очереди: видимость и право открыть от отметки не зависят."""
    default, gone, admin, queues = _unmark_world(settings)
    ticket = _closed(gone, days=30)
    queues.unmark(gone.unit_id, actor=admin)
    holder = _member(gone.unit, "Узлов Антон")

    client = support.logged_in(holder)
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(f"/tickets/{ticket.number}/reopen/")

    # заявка ушла в очередь по умолчанию и актёру больше не видна: переход на список, дополнение 27 (г);
    # сообщение `[role=status]` живёт в сессии того же клиента
    assert response.status_code == 302 and response["Location"] in ("/tickets/", "/")
    assert _find(_parse(client.get(response["Location"], follow=True)), role="status")
    ticket = _assert_moved_to_default(ticket, gone, default)
    reopened = _events(ticket, "reopened")
    assert len(reopened) == 1 and reopened[0].data["via"] == "manual"
    assert len(_mails(ticket, "ticket.reopened")) == 1


def test_reopen_keeps_assignee_who_is_member_of_final_queue(
        settings, protected_root, bus_spy, django_capture_on_commit_callbacks):
    """FR-251, FR-252: ответственный, участник итоговой очереди, остаётся — и в своей очереди, и когда заявка ушла в
    очередь по умолчанию; события шины `assignee_changed` и ленты о смене ответственного нет."""
    from apps.servicedesk.services import closing

    default, gone, admin, queues = _unmark_world(settings)
    bus_spy.listen("servicedesk.assignee_changed")
    queue_row = sd.make_queue()
    keeper = _member(queue_row.unit, "Хранитель Кирилл")
    own = _closed(queue_row, days=2, assignee=keeper)
    stays = _member(gone.unit, "Остапов Олег")
    org.make_member(stays, default.unit)
    moved = _closed(gone, days=2, assignee=stays)
    queues.unmark(gone.unit_id, actor=admin)

    result, _ = _letter(own, own.requester_email, protected_root, django_capture_on_commit_callbacks)
    with django_capture_on_commit_callbacks(execute=True):
        closing.reopen(moved, actor=admin)

    assert result == "reopened"
    own, moved = _fresh(own), _fresh(moved)
    assert (own.assignee_id, own.queue_id, own.kind) == (keeper.pk, queue_row.unit_id, "in_progress")
    assert (moved.assignee_id, moved.queue_id, moved.kind) == (stays.pk, default.unit_id, "in_progress")
    assert _events(own, "assignee_changed") == [] and _events(moved, "assignee_changed") == []
    assert bus_spy.calls("servicedesk.assignee_changed") == []


def test_reopen_without_assignee_when_assignee_dismissed(
        settings, protected_root, bus_spy, django_capture_on_commit_callbacks):
    """FR-251: ответственный, который больше не участник очереди (уволен, членство снято), при открытии
    не остаётся: письмом — заявка «В работе» без ответственного; вручную — то же. Снятие — событие ленты
    `assignee_changed`, журнал `ticket.assignee_removed` с причиной `not_participant` (очередь прежняя) и событие
    шины (дополнение 22)."""
    from apps.servicedesk.services import closing

    _prepare(settings)
    bus_spy.listen("servicedesk.assignee_changed")
    queue_row = sd.make_queue()
    actor = _member(queue_row.unit)
    gone_user = _member(queue_row.unit, "Уволенов Егор")
    ticket = _closed(queue_row, days=2, assignee=gone_user)
    _dismiss(gone_user)

    result, _ = _letter(ticket, ticket.requester_email, protected_root, django_capture_on_commit_callbacks)

    assert result == "reopened"
    ticket = _fresh(ticket)
    assert ticket.assignee_id is None and ticket.kind == "in_progress" and ticket.queue_id == queue_row.unit_id
    assert len(_events(ticket, "queue_changed")) == 0
    _assert_assignee_removed(ticket, gone_user, "not_participant", bus_spy)

    left = _member(queue_row.unit, "Ушедов Глеб")
    other = _closed(queue_row, days=2, assignee=left)
    model("org.Membership").objects.filter(user=left, unit=queue_row.unit).delete()
    with django_capture_on_commit_callbacks(execute=True):
        closing.reopen(other, actor=actor)
    other = _fresh(other)
    assert other.assignee_id is None and other.kind == "in_progress"
    _assert_assignee_removed(other, left, "not_participant", bus_spy)


def test_reopen_clears_closed_at_closed_by_resolution_and_close_event_keeps_resolution(
        settings, django_capture_on_commit_callbacks):
    """FR-251, FR-252: закрытие «Решена» с текстом, затем открытие очищают `closed_at`, `closed_by`, `resolution`;
    текст решения остаётся в событии ленты `closed` (статус и решение в `data`), событий закрытия не прибавилось."""
    from apps.servicedesk.services import closing

    _prepare(settings)
    queue_row = sd.make_queue()
    member = _member(queue_row.unit)
    ticket = sd.make_ticket(queue=queue_row, kind="in_progress", assignee=member, assigned_once=True)
    sd.make_entry(ticket, "incoming", text="Первое письмо")
    done = _status("closed", is_default=True)
    with django_capture_on_commit_callbacks(execute=True):
        closing.close(_fresh(ticket), done, "Заменили картридж", actor=member)
    closed = _fresh(ticket)
    assert closed.kind == "closed" and closed.closed_at is not None and closed.closed_by_id == member.pk
    assert closed.resolution == "Заменили картридж"

    with django_capture_on_commit_callbacks(execute=True):
        closing.reopen(closed, actor=member)

    ticket = _fresh(ticket)
    assert ticket.closed_at is None and ticket.closed_by_id is None and ticket.resolution == ""
    events = _events(ticket, "closed")
    assert len(events) == 1
    assert events[0].data["resolution"] == "Заменили картридж"
    assert events[0].data["status"] == done.name and events[0].data["status_id"] == done.pk


def test_reopen_sets_default_in_work_status_with_event_and_journal(
        settings, protected_root, django_capture_on_commit_callbacks):
    """FR-251, FR-252: открытие ставит статус по умолчанию вида «в работе» (а не другой статус вида), пишет события
    ленты `status_changed` (причина `reopen`) и `reopened`, журнал `ticket.reopened` (статус до и после, способ);
    отдельного `ticket.updated` для смены статуса нет."""
    from apps.servicedesk.services import closing

    _prepare(settings)
    queue_row = sd.make_queue()
    member = _member(queue_row.unit)
    other = model("servicedesk.Status").objects.create(
        name="Ждёт запчасть", name_key=org.name_key("Ждёт запчасть"), kind="in_progress", order=1)
    default_work = _status("in_progress", is_default=True)
    assert other.pk != default_work.pk
    closed_status = _status("closed", is_default=True)

    by_hand = _closed(queue_row, days=40, status=closed_status)
    with django_capture_on_commit_callbacks(execute=True):
        closing.reopen(by_hand, actor=member)
    by_hand = _fresh(by_hand)
    assert by_hand.status_id == default_work.pk and by_hand.kind == "in_progress" and by_hand.waiting_since is None
    changed = _events(by_hand, "status_changed")[-1]
    assert (changed.data["before"], changed.data["after"], changed.data["reason"]) == (
        closed_status.name, default_work.name, "reopen")
    assert (changed.data["before_id"], changed.data["after_id"]) == (closed_status.pk, default_work.pk)
    reopened = _events(by_hand, "reopened")
    assert len(reopened) == 1
    assert (reopened[0].data["via"], reopened[0].data["status"], reopened[0].data["status_id"]) == (
        "manual", default_work.name, default_work.pk)
    journal = _audit("ticket.reopened", by_hand)
    assert len(journal) == 1 and journal[0].actor_id == member.pk and journal[0].object_type == "ticket"
    assert journal[0].before["status"] == closed_status.name
    assert (journal[0].after["status"], journal[0].after["via"]) == (default_work.name, "manual")
    assert _audit("ticket.updated", by_hand) == []

    by_mail = _closed(queue_row, days=1, status=closed_status)
    result, _ = _letter(by_mail, by_mail.requester_email, protected_root, django_capture_on_commit_callbacks)
    assert result == "reopened"
    by_mail = _fresh(by_mail)
    assert by_mail.status_id == default_work.pk
    journal = _audit("ticket.reopened", by_mail)
    assert len(journal) == 1 and journal[0].actor_id is None
    assert (journal[0].after["status"], journal[0].after["via"]) == (default_work.name, "mail")
    assert _events(by_mail, "reopened")[0].data["via"] == "mail"
