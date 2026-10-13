"""T-3116: закрытие заявки (FR-206, FR-245, FR-249, FR-251, FR-256). Сценарии 5 (пп. 1, 2, 8) и 3 спеки.

Закрытие с решением: отказы `resolution_required`, `resolution_too_long`, `ticket_closed`, `bad_status`, `no_access`,
выбор статуса на форме закрытия, поля закрытой заявки, события ленты и журнала, шина, письмо «закрыта с решением»
и ответ на него. Код среза на уровне модуля не импортируется: имена берутся внутри тестов (CONTRACT-003, шапка).
"""
import email
import importlib
import re
import uuid
from email import policy
from html.parser import HTMLParser

import pytest
from django.utils import timezone

from tests import support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

MAILBOX = "tickets@portal.example"
SMTP_FROM = "noreply@portal.example"
DOMAIN = "corp.example"
CLOSED_TEXT = "Заявка закрыта: сначала откройте её"
HX = {"HTTP_HX_REQUEST": "true"}


# --- помощники только этого файла ------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.servicedesk.services.{name}")


def _errors():
    return importlib.import_module("apps.servicedesk.services").ServiceDeskError


def _member(unit, **extra):
    """Сотрудник — участник узла (рядовой, без права «Все заявки»)."""
    user = support.make_employee(**extra)
    org.make_member(user, unit)
    return user


def _default_closed():
    return model("servicedesk.Status").objects.get(kind="closed", is_default=True)


def _status(kind: str, name: str, *, archived: bool = False):
    return model("servicedesk.Status").objects.create(name=name, name_key=org.name_key(name), kind=kind,
                                                      archived=archived)


def _setup(kind: str = "in_progress", **over):
    """(очередь, участник очереди, заявка вида `kind`)."""
    queue = sd.make_queue()
    user = _member(queue.unit)
    ticket = sd.make_ticket(queue=queue, kind=kind, **over)
    return queue, user, ticket


def _close(ticket, status, resolution, actor, capture):
    with capture(execute=True):
        return _svc("closing").close(ticket, status, resolution, actor=actor)


def _refused(code: str, ticket, status, resolution, actor, capture):
    with pytest.raises(_errors()) as caught:
        _close(ticket, status, resolution, actor, capture)
    assert caught.value.code == code, f"ожидали код {code}, получили {caught.value.code}"
    return caught.value


def _untouched(ticket):
    """Заявка после отказа: не закрыта, поля закрытия пусты, писем и событий закрытия нет."""
    ticket.refresh_from_db()
    assert ticket.kind != "closed" and ticket.closed_at is None and ticket.closed_by_id is None
    assert ticket.resolution == ""
    assert not ticket.entries.filter(kind="event", event__in=["closed", "status_changed"]).exists()
    assert sd.ticket_mails(ticket) == []


def _closed_ticket(queue, user, **over):
    status = _default_closed()
    fields = {"kind": "closed", "status": status, "closed_at": timezone.now(), "closed_by": user,
              "resolution": "Готово"}
    fields.update(over)
    return sd.make_ticket(queue=queue, **fields)


class _Dom(HTMLParser):
    """Список элементов страницы: тег, атрибуты, весь текст внутри (с вложенным)."""
    VOID = {"input", "br", "img", "hr", "meta", "link"}

    def __init__(self, html: str):
        super().__init__()
        self.items: list[dict] = []
        self._stack: list[dict] = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        item = {"tag": tag, "attrs": dict(attrs), "text": []}
        self.items.append(item)
        if tag not in self.VOID:
            self._stack.append(item)

    def handle_endtag(self, tag):
        for index in range(len(self._stack) - 1, -1, -1):
            if self._stack[index]["tag"] == tag:
                del self._stack[index:]
                return

    def handle_data(self, data):
        for item in self._stack:
            item["text"].append(data)

    def find(self, tag: str | None = None, **attrs) -> list[dict]:
        found = []
        for item in self.items:
            if tag and item["tag"] != tag:
                continue
            if all((key.replace("_", "-") in item["attrs"]) if value is True
                   else item["attrs"].get(key.replace("_", "-")) == value for key, value in attrs.items()):
                found.append(item)
        return found

    @staticmethod
    def text(item: dict) -> str:
        return " ".join("".join(item["text"]).split())


def _alerts(response) -> list[str]:
    dom = _Dom(response.content.decode())
    return [dom.text(item) for item in dom.items if item["attrs"].get("role") == "alert"]


def _journal(action: str, ticket) -> list:
    return list(model("core.AuditEvent").objects.filter(action=action, object_type="ticket",
                                                         object_id=str(ticket.number)).order_by("id"))


def _addresses(value: str) -> set[str]:
    return {part.strip() for part in value.split(",") if part.strip()}


# --- отказы ----------------------------------------------------------------------------------------

def test_close_without_resolution_refused(django_capture_on_commit_callbacks):
    """FR-249: без текста решения (пусто и только пробелы) заявка не закрывается: `resolution_required`;
    маршрут отвечает 200 с диалогом и `[role=alert]`, слово «решение» в сообщении (сценарий 5, п. 1)."""
    _queue, user, ticket = _setup()
    status = _default_closed()
    for empty in ("", "   ", " \n\t "):
        _refused("resolution_required", ticket, status, empty, user, django_capture_on_commit_callbacks)
        _untouched(ticket)

    other = sd.make_ticket(queue=_queue, kind="in_progress")
    response = support.logged_in(user).post(f"/tickets/{other.number}/close/",
                                            {"status": status.pk, "resolution": "  "}, **HX)
    assert response.status_code == 200
    alerts = _alerts(response)
    assert alerts and "решение" in alerts[0].lower(), f"в сообщении нет слова «решение»: {alerts}"
    assert _Dom(response.content.decode()).find(None, data_dialog="ticket-close"), "ответ без диалога закрытия"
    _untouched(other)


def test_close_resolution_up_to_10_thousand(django_capture_on_commit_callbacks):
    """FR-249: решение до 10 000 знаков принимается (пробелы по краям не считаются и обрезаются),
    10 001 знак — `resolution_too_long`, заявка остаётся открытой; то же из формы (200 с `[role=alert]`)."""
    queue, user, ticket = _setup()
    status = _default_closed()
    exact = "я" * 10000
    _close(ticket, status, f"  {exact}  ", user, django_capture_on_commit_callbacks)
    ticket.refresh_from_db()
    assert ticket.kind == "closed" and ticket.resolution == exact and len(ticket.resolution) == 10000

    long_ticket = sd.make_ticket(queue=queue, kind="in_progress")
    _refused("resolution_too_long", long_ticket, status, "я" * 10001, user, django_capture_on_commit_callbacks)
    _untouched(long_ticket)

    response = support.logged_in(user).post(f"/tickets/{long_ticket.number}/close/",
                                            {"status": status.pk, "resolution": "я" * 10001}, **HX)
    assert response.status_code == 200 and _alerts(response)
    _untouched(long_ticket)


def test_close_of_already_closed_ticket_refused_with_message(django_capture_on_commit_callbacks):
    """FR-249: закрытие закрытой заявки — `ticket_closed` с текстом «Заявка закрыта: сначала откройте её»;
    данные закрытия не меняются; прямой POST — 200 и `[role=alert]` с тем же текстом (6.2, 12.4)."""
    queue, user, _ = _setup()
    ticket = _closed_ticket(queue, user, resolution="Первое решение")
    before = (ticket.closed_at, ticket.closed_by_id, ticket.resolution, ticket.status_id)
    error = _refused("ticket_closed", ticket, _default_closed(), "Второе решение", user,
                     django_capture_on_commit_callbacks)
    assert str(error) == error.message == CLOSED_TEXT
    ticket.refresh_from_db()
    assert (ticket.closed_at, ticket.closed_by_id, ticket.resolution, ticket.status_id) == before

    response = support.logged_in(user).post(f"/tickets/{ticket.number}/close/",
                                            {"status": _default_closed().pk, "resolution": "Третье"})
    assert response.status_code == 200
    assert any(CLOSED_TEXT in text for text in _alerts(response)), _alerts(response)
    ticket.refresh_from_db()
    assert ticket.resolution == "Первое решение"
    assert sd.ticket_mails(ticket) == []


def test_internal_comment_on_closed_ticket_allowed_and_changes_nothing_else(django_capture_on_commit_callbacks):
    """FR-245, FR-249: на закрытой заявке внутренний комментарий разрешён (сервис и маршрут), письма нет даже при
    участниках, статус, поля закрытия и `last_message_*` не меняются; новых событий ленты нет."""
    queue, user, _ = _setup()
    ticket = _closed_ticket(queue, user, last_message_from="requester")
    sd.make_participant(ticket)
    ticket.refresh_from_db()
    before = {name: getattr(ticket, name) for name in
              ("status_id", "kind", "closed_at", "closed_by_id", "resolution", "waiting_since",
               "last_message_at", "last_message_from", "assignee_id")}
    entries_before = ticket.entries.count()

    with django_capture_on_commit_callbacks(execute=True):
        entry = _svc("replies").comment(ticket, text="Заметка для своих", actor=user)
    assert entry.kind == "comment" and entry.text == "Заметка для своих" and entry.author_id == user.pk

    response = support.logged_in(user).post(f"/tickets/{ticket.number}/comment/", {"text": "Ещё заметка"})
    assert response.status_code in (200, 302)

    ticket.refresh_from_db()
    assert {name: getattr(ticket, name) for name in before} == before
    assert ticket.entries.count() == entries_before + 2
    assert list(ticket.entries.order_by("id")[entries_before:].values_list("kind", flat=True)) == ["comment", "comment"]
    assert sd.ticket_mails(ticket) == []


# --- форма закрытия --------------------------------------------------------------------------------

def _close_form_options(user, ticket):
    response = support.logged_in(user).get(f"/tickets/{ticket.number}/close/", **HX)
    assert response.status_code == 200
    dom = _Dom(response.content.decode())
    assert dom.find(None, data_dialog="ticket-close"), "нет диалога [data-dialog=ticket-close]"
    assert dom.find("textarea", name="resolution"), "нет textarea[name=resolution]"
    assert dom.find("button", data_dialog_cancel=True), "нет кнопки button[data-dialog-cancel]"
    (select,) = dom.find("select", name="status")
    # варианты — элементы option внутри select: берём по порядку после select до следующего select/textarea
    index = dom.items.index(select)
    options = []
    for item in dom.items[index + 1:]:
        if item["tag"] in ("select", "textarea"):
            break
        if item["tag"] == "option":
            options.append((int(item["attrs"]["value"]), dom.text(item)))
    return options


def test_close_form_offers_closed_kind_statuses_default_resolved():
    """FR-206, FR-249: форма закрытия (GET `/tickets/<N>/close/`) предлагает неархивные статусы вида «закрыта»
    без системного, первым — статус по умолчанию вида «Решена»; список равен `dictionaries.closing_statuses()`
    (сценарий 5, п. 8)."""
    _queue, user, ticket = _setup()
    own = _status("closed", "Отклонена по просьбе")
    options = _close_form_options(user, ticket)
    expected = list(_svc("dictionaries").closing_statuses())
    assert [pk for pk, _ in options] == [status.pk for status in expected]
    default = _default_closed()
    assert default.name == "Решена" and options[0] == (default.pk, "Решена")
    names = [name for _, name in options]
    assert {"Решена", "Не может быть решена", own.name} <= set(names)
    assert all(status.kind == "closed" and not status.archived and status.system_code == "" for status in expected)


def test_close_form_excludes_system_autoclosed_and_archived_statuses(django_capture_on_commit_callbacks):
    """FR-206, FR-249: в форме нет системного «Закрыта автоматически» и архивных статусов вида «закрыта»;
    закрытие ими (и статусом не вида «закрыта») — `bad_status`, заявка не меняется; маршрут — 200 с alert."""
    queue, user, ticket = _setup()
    archived = _status("closed", "Архивная причина", archived=True)
    auto = model("servicedesk.Status").objects.get(system_code="autoclosed")
    in_work = model("servicedesk.Status").objects.get(kind="in_progress", is_default=True)
    options = _close_form_options(user, ticket)
    ids = {pk for pk, _ in options}
    assert auto.pk not in ids and archived.pk not in ids and in_work.pk not in ids
    assert "Закрыта автоматически" not in {name for _, name in options}
    assert archived.pk not in {s.pk for s in _svc("dictionaries").closing_statuses()}
    assert auto.pk not in {s.pk for s in _svc("dictionaries").closing_statuses()}

    for bad in (auto, archived, in_work):
        _refused("bad_status", ticket, bad, "Решение", user, django_capture_on_commit_callbacks)
        _untouched(ticket)
        response = support.logged_in(user).post(f"/tickets/{ticket.number}/close/",
                                                {"status": bad.pk, "resolution": "Решение"}, **HX)
        assert response.status_code == 200 and _alerts(response), f"статус {bad.name}: нет [role=alert]"
        _untouched(ticket)


# --- кто закрывает ---------------------------------------------------------------------------------

def test_close_only_by_queue_member_or_assignee(django_capture_on_commit_callbacks):
    """FR-249: закрывает участник очереди и ответственный (в том числе по заявке чужой очереди);
    посторонний (не видит заявку) — `no_access` у сервиса и 404 у маршрута (допол. 2), заявка не меняется."""
    queue = sd.make_queue()
    member = _member(queue.unit)
    status = _default_closed()

    by_member = sd.make_ticket(queue=queue, kind="in_progress")
    _close(by_member, status, "Закрыл участник", member, django_capture_on_commit_callbacks)
    by_member.refresh_from_db()
    assert by_member.kind == "closed" and by_member.closed_by_id == member.pk

    assignee = _member(sd.make_queue().unit)  # член другой очереди: заявку видит только как ответственный
    foreign = sd.make_ticket(queue=queue, kind="in_progress", assignee=assignee)
    _close(foreign, status, "Закрыл ответственный", assignee, django_capture_on_commit_callbacks)
    foreign.refresh_from_db()
    assert foreign.kind == "closed" and foreign.closed_by_id == assignee.pk and foreign.resolution

    outsider = _member(sd.make_queue().unit)
    hidden = sd.make_ticket(queue=queue, kind="in_progress")
    _refused("no_access", hidden, status, "Чужое решение", outsider, django_capture_on_commit_callbacks)
    _untouched(hidden)
    response = support.logged_in(outsider).post(f"/tickets/{hidden.number}/close/",
                                                {"status": status.pk, "resolution": "Чужое решение"})
    assert response.status_code == 404
    _untouched(hidden)


# --- что записывает закрытие -----------------------------------------------------------------------

def test_close_sets_closed_at_closed_by_resolution_and_clears_waiting_since(django_capture_on_commit_callbacks):
    """FR-249: `closed_at` = сейчас, `closed_by` = закрывший, `resolution` без пробелов по краям, статус выбранный,
    вид `closed`, `waiting_since` снят (сценарий 5, п. 2)."""
    queue, user, ticket = _setup("waiting")
    sd.backdate(ticket, "waiting_since", hours=3)
    chosen = model("servicedesk.Status").objects.get(name="Не может быть решена")
    before = timezone.now()
    _close(ticket, chosen, "  Решение закрытия  ", user, django_capture_on_commit_callbacks)
    after = timezone.now()
    ticket.refresh_from_db()
    assert before <= ticket.closed_at <= after
    assert ticket.closed_by_id == user.pk
    assert ticket.resolution == "Решение закрытия"
    assert ticket.status_id == chosen.pk and ticket.kind == "closed"
    assert ticket.waiting_since is None

    card = support.logged_in(user).get(f"/tickets/{ticket.number}/")
    dom = _Dom(card.content.decode())
    assert dom.find(None, data_ticket_card=True, data_kind="closed"), "корень карточки без data-kind=closed"
    (field,) = dom.find(None, data_field="resolution")
    assert "Решение закрытия" in dom.text(field)


def test_close_event_has_status_and_resolution_text(django_capture_on_commit_callbacks):
    """FR-249: событие ленты `closed` с `data` — название, id статуса и текст решения (9.3, 14.5); сверх него
    событие «статус: было → стало» с причиной `close` (урок T-3100: решение C1 отменено)."""
    _queue, user, ticket = _setup()
    old = ticket.status
    chosen = _default_closed()
    _close(ticket, chosen, "Заменили кабель", user, django_capture_on_commit_callbacks)

    closed = list(ticket.entries.filter(kind="event", event="closed"))
    assert len(closed) == 1
    data = closed[0].data
    assert data["status"] == chosen.name and data["status_id"] == chosen.pk
    assert data["resolution"] == "Заменили кабель"

    changes = list(ticket.entries.filter(kind="event", event="status_changed"))
    assert len(changes) == 1
    assert changes[0].data["before"] == old.name and changes[0].data["after"] == chosen.name
    assert (changes[0].data["before_id"], changes[0].data["after_id"]) == (old.pk, chosen.pk)
    assert changes[0].data["reason"] == "close"


def test_close_publishes_ticket_closed_to_bus_and_writes_journal(bus_spy, django_capture_on_commit_callbacks):
    """FR-249: шина получает одно `servicedesk.ticket_closed` (номер, очередь, ответственный на момент закрытия, `actor_id` закрывшего);
    журнал — `ticket.closed` (исполнитель, `status` до и после, текста решения нет, 9.2)."""
    bus_spy.listen("servicedesk.ticket_closed")
    queue = sd.make_queue()
    user = _member(queue.unit)
    ticket = sd.make_ticket(queue=queue, kind="in_progress", assignee=user)
    old = ticket.status
    chosen = _default_closed()
    _close(ticket, chosen, "Уникальное решение 4711", user, django_capture_on_commit_callbacks)

    calls = bus_spy.calls("servicedesk.ticket_closed")
    assert calls == [{"number": ticket.number, "queue_id": queue.unit_id,
                      "assignee_before_id": user.pk, "assignee_after_id": user.pk, "actor_id": user.pk}]

    (row,) = _journal("ticket.closed", ticket)
    assert row.actor_id == user.pk
    assert row.before["status"] == old.name and row.after["status"] == chosen.name
    assert "4711" not in str(row.before) + str(row.after), "текст решения не должен попадать в журнал"
    assert _journal("ticket.updated", ticket) == [], "при закрытии `ticket.updated` не пишется (6.7)"


# --- письмо ----------------------------------------------------------------------------------------

def test_close_sends_closed_letter_with_resolution_to_requester_and_participants(django_capture_on_commit_callbacks):
    """FR-249, FR-256: письмо `ticket.closed` — заявителю (`To`), в `Cc` неснятые участники; в тексте номер и
    решение; `Auto-Submitted: auto-generated` (10.1, 10.2, 10.3); снятому участнику письма нет."""
    queue, user, ticket = _setup()
    first = sd.make_participant(ticket, "kollega@corp.example")
    second = sd.make_participant(ticket, "drugoj@corp.example")
    removed = sd.make_participant(ticket, "snyatyj@corp.example", removed_by=user)
    _close(ticket, _default_closed(), "Заменили маршрутизатор", user, django_capture_on_commit_callbacks)

    (mail,) = sd.ticket_mails(ticket)
    assert mail.template == "ticket.closed"
    assert mail.to == ticket.requester_email
    assert _addresses(mail.cc) == {first.email, second.email}
    assert removed.email not in mail.cc and ticket.requester_email not in mail.cc
    assert mail.auto_submitted == "auto-generated"
    body = sd.mail_text(mail)
    assert f"Ваша заявка № {ticket.number} закрыта. Решение: Заменили маршрутизатор." in body
    assert "в течение 7 дней" in body
    assert re.search(rf"(?<!\d){ticket.number}(?!\d)", body)


def test_closed_letter_can_be_answered_and_answer_reopens(settings, protected_root,
                                                          django_capture_on_commit_callbacks):
    """FR-256, FR-251: на письмо «закрыта с решением» можно ответить (`Reply-To` — ящик заявок, номер в теме);
    ответ заявителя в срок открывает заявку «в работе»: поля закрытия очищены, дописано письмо, итог `reopened`."""
    settings.SERVICEDESK_MAILBOX = MAILBOX
    settings.DEFAULT_FROM_EMAIL = SMTP_FROM
    queue = sd.make_queue()
    sd.configure_servicedesk(domains=[DOMAIN], default_queue=queue)
    user = _member(queue.unit)
    requester = sd.make_requester(f"zayavitel-{uuid.uuid4().hex[:8]}@{DOMAIN}")
    ticket = sd.make_ticket(queue=queue, requester=requester, kind="in_progress", subject="Не работает сеть")
    sd.make_entry(ticket, "incoming", text="Первое письмо")
    _close(ticket, _default_closed(), "Перезагрузили коммутатор", user, django_capture_on_commit_callbacks)
    (closed_mail,) = sd.ticket_mails(ticket)
    assert closed_mail.template == "ticket.closed" and closed_mail.reply_to == MAILBOX
    assert f"[#{ticket.number}]" in closed_mail.subject

    raw = sd.build_mail(from_addr=requester.email, to=[MAILBOX], subject=f"Re: {closed_mail.subject}",
                        text="Не помогло, сеть снова пропала", in_reply_to=closed_mail.message_id)
    message = email.message_from_bytes(raw, policy=policy.default)
    inbound = sd.make_inbound(size=len(raw), from_email=requester.email, subject=str(message["Subject"]),
                              message_id=str(message["Message-ID"]))
    folder = protected_root / "inbound"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{inbound.pk}.eml").write_bytes(raw)
    with django_capture_on_commit_callbacks(execute=True):
        outcome = _svc("intake").process(inbound.pk)

    assert outcome == "reopened"
    ticket.refresh_from_db()
    assert ticket.kind == "in_progress" and ticket.closed_at is None and ticket.closed_by_id is None
    assert ticket.resolution == ""
    assert model("servicedesk.Ticket").objects.count() == 1, "ответ в срок не должен создавать новую заявку"
    assert ticket.entries.filter(kind="incoming", text__contains="Не помогло").count() == 1
    assert ticket.entries.filter(kind="event", event="reopened", data__via="mail").count() == 1
    assert "ticket.reopened" in [m.template for m in sd.ticket_mails(ticket)]
