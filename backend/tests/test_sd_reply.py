"""T-3115: ответ исполнителя, повторная отправка и недоставка (FR-244, FR-245, FR-247, NFR-202). Сценарии 3 и 12 спеки.

Ответ без вложений и с вложениями (ожидание проверки, чистые файлы, карантин, архив с паролем, закрытие во время
проверки), «Отправить заново», внутренний комментарий, доставка письма заданием `mail` с повторами и недоставка
после последней неудачи (событие ленты и журнал). Код среза на уровне модуля не импортируется: имена берутся
внутри тестов (CONTRACT-003, шапка). Почта и очереди настоящие (Mailpit, Valkey); подменяется только проверка
файла на вирусы (CONTRACT-003, 3.5).
"""
import importlib
from datetime import datetime, timedelta, timezone as dt_timezone
from html.parser import HTMLParser
from itertools import count

import pytest
from django.utils import timezone

from tests import support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model
from tests.support_mail import break_smtp, deliver, mail_jobs, mail_queue

pytestmark = pytest.mark.django_db

SECOND = timedelta(seconds=1)
CLOSED_TEXT = "Заявка закрыта: сначала откройте её"
RETRY_INTERVALS = [60, 300, 900, 3600] + [10800] * 7
_ips = count(210)
_VOID = {"input", "br", "img", "hr", "meta", "link", "area", "base", "col", "source", "wbr"}


# --- помощники только этого файла ------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.servicedesk.services.{name}")


def _errors():
    return importlib.import_module("apps.servicedesk.services").ServiceDeskError


def _actor():
    """Сотрудник с правом `servicedesk.all`: видит все заявки и участник любой очереди."""
    return support.make_with_permissions("servicedesk.all")


def _ticket(kind: str = "in_progress", **over):
    return sd.make_ticket(queue=sd.make_queue(), kind=kind, **over)


def _fresh(obj):
    obj.refresh_from_db()
    return obj


def _part(name: str = "справка.txt", data: bytes = b"clean data"):
    return _svc("attachments").Part(name=name, data=data)


def _reply(ticket, actor, capture, *, text: str = "Ответ исполнителя", wait: bool = False, parts=()):
    with capture(execute=True):
        return _svc("replies").reply(ticket, text=text, wait_flag=wait, parts=list(parts), actor=actor)


def _refuse(code: str, call):
    """Вызывает `call`; ждёт `ServiceDeskError` с кодом `code`, возвращает ошибку."""
    with pytest.raises(_errors()) as caught:
        call()
    assert caught.value.code == code, f"ждали {code}, получили {caught.value.code}: {caught.value}"
    return caught.value


def _closed(ticket) -> None:
    """Закрывает заявку напрямую в базе (как будто её закрыли между ответом и проверкой файлов)."""
    status = model("servicedesk.Status").objects.get(kind="closed", is_default=True)
    model("servicedesk.Ticket").objects.filter(pk=ticket.pk).update(
        status=status, kind="closed", closed_at=timezone.now())


def _events(ticket, code: str) -> list:
    entries = model("servicedesk.TicketEntry").objects.filter(ticket=ticket, kind="event", event=code)
    return list(entries.order_by("id"))


def _stored_of(entry) -> list:
    return [a.file for a in entry.attachments.order_by("id")]


def _run_jobs(capture, monkeypatch, jobs) -> None:
    """Исполняет перечисленные задания очереди `files` по одному, каждое внутри фиксации."""
    for job in jobs:
        with capture(execute=True):
            job.perform()


def _file_jobs() -> list:
    return list(org.files_queue().jobs)


def _job_of(stored) -> object:
    (job,) = [j for j in _file_jobs() if str(j.args[0]) == str(stored.pk)]
    return job


def _mail_dates_close(left, right) -> bool:
    return abs(left - right) <= 5 * SECOND


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
        """Элементы с тегом `tag` и атрибутами `want` (`data_x` -> `data-x`; True — любое значение)."""
        wanted = {key.replace("_", "-"): value for key, value in want.items()}
        found = []
        for el in self.walk():
            if tag is not None and el.tag != tag:
                continue
            if all(name in el.attrs and (value is True or el.attrs[name] == str(value)) for name, value in wanted.items()):
                found.append(el)
        return found

    def inside(self, **want) -> bool:
        """Есть ли среди предков элемент с такими атрибутами."""
        wanted = {key.replace("_", "-"): value for key, value in want.items()}
        el = self.parent
        while el is not None:
            if all(name in el.attrs and (value is True or el.attrs[name] == str(value)) for name, value in wanted.items()):
                return True
            el = el.parent
        return False


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


def _dom(response) -> _El:
    builder = _Builder()
    builder.feed(response.content.decode("utf-8", "replace"))
    return builder.root


def _card(actor, ticket) -> _El:
    client = support.logged_in(actor, ip=f"198.51.100.{next(_ips)}")
    response = client.get(f"/tickets/{ticket.number}/")
    assert response.status_code == 200
    return _dom(response)


def _item(dom: _El, entry) -> _El:
    (li,) = dom.find_all("li", data_entry_id=entry.pk)
    return li


# --- ответ: письмо, текст, вложения (FR-244) -------------------------------------------------------

def test_reply_without_attachments_goes_to_queue_at_once(django_capture_on_commit_callbacks, settings):
    """FR-244: ответ без файлов сразу идёт письмом в очередь: `queued`, `MailMessage`, задание, журнал, `last_message_from`."""
    settings.SERVICEDESK_MAILBOX = "tickets@stand.test"
    actor = _actor()
    ticket = _ticket("new")
    entry = _reply(ticket, actor, django_capture_on_commit_callbacks)
    _fresh(entry)
    _fresh(ticket)
    assert entry.kind == "reply" and entry.send_state == "queued"
    (message,) = sd.ticket_mails(ticket)
    assert entry.mail_id == message.pk
    assert message.template == "ticket.reply" and message.status == "queued"
    assert len(mail_jobs()) == 1
    assert ticket.last_message_from == "staff" and ticket.kind == "in_progress"
    audit = model("core.AuditEvent").objects.get(action="ticket.reply_sent", object_id=str(ticket.number))
    assert audit.actor_id == actor.pk and audit.object_type == "ticket"
    assert audit.before == {} and audit.after == {"entry_id": entry.pk}


def test_reply_letter_to_requester_cc_participants_with_subject_and_reply_to_mailbox(
        django_capture_on_commit_callbacks, settings):
    """FR-244: письмо — заявителю, в копию неснятые участники (без адреса заявителя), тема `[#N] Тема`, Reply-To — ящик заявок."""
    settings.SERVICEDESK_MAILBOX = "tickets@stand.test"
    actor = _actor()
    ticket = _ticket("in_progress")
    kept = sd.make_participant(ticket, "kept@client.test")
    sd.make_participant(ticket, "gone@client.test", removed_by=actor)
    sd.make_participant(ticket, ticket.requester_email)
    _reply(ticket, actor, django_capture_on_commit_callbacks)
    (message,) = sd.ticket_mails(ticket)
    assert message.to == ticket.requester_email
    assert {a.strip() for a in message.cc.split(",") if a.strip()} == {kept.email}
    assert message.subject == f"[#{ticket.number}] {ticket.subject}"
    assert message.reply_to == "tickets@stand.test"
    assert message.auto_submitted == ""
    assert message.related_ref == f"ticket:{ticket.pk}"


def test_reply_text_required_plain_up_to_50_thousand(django_capture_on_commit_callbacks):
    """FR-244: текст обязателен после обрезки пробелов (`text_required`), до 50 000 знаков (`text_too_long`); отказ ничего не пишет."""
    replies = _svc("replies")
    actor = _actor()
    ticket = _ticket("in_progress")
    Entry = model("servicedesk.TicketEntry")
    for text in ("", "   \n\t "):
        _refuse("text_required", lambda text=text: replies.reply(ticket, text=text, actor=actor))
    _refuse("text_too_long", lambda: replies.reply(ticket, text="я" * 50_001, actor=actor))
    assert not Entry.objects.filter(ticket=ticket, kind="reply").exists() and sd.ticket_mails(ticket) == []
    entry = _reply(ticket, actor, django_capture_on_commit_callbacks, text="  " + "я" * 50_000 + "\n")
    assert _fresh(entry).text == "я" * 50_000
    assert _fresh(entry).send_state == "queued"


def test_reply_limits_ten_files_and_fifty_megabytes(monkeypatch, protected_root):
    """FR-244: больше 10 файлов — `too_many_files`; сумма больше 50 МБ — `total_too_big`; ничего не записано (по правилам вложений)."""
    replies = _svc("replies")
    actor = _actor()
    ticket = _ticket("in_progress")
    Entry, Stored = model("servicedesk.TicketEntry"), model("core.StoredFile")
    sd.scan_clean(monkeypatch)
    eleven = [_part(f"файл{i}.txt") for i in range(11)]
    _refuse("too_many_files", lambda: replies.reply(ticket, text="Ответ", parts=eleven, actor=actor))
    heavy = [_part(f"большой{i}.bin", b"0" * (17 * 1024 * 1024)) for i in range(3)]
    _refuse("total_too_big", lambda: replies.reply(ticket, text="Ответ", parts=heavy, actor=actor))
    assert not Entry.objects.filter(ticket=ticket, kind="reply").exists()
    assert not Stored.objects.filter(purpose="attachment").exists()
    assert sd.ticket_mails(ticket) == [] and org.files_queue().jobs == []


def test_reply_with_unacceptable_file_refused_as_a_whole(monkeypatch, protected_root):
    """FR-244: один недопустимый файл (исполняемый) — отказ всему ответу `file_rejected`; элемента, файлов и письма нет."""
    replies = _svc("replies")
    actor = _actor()
    ticket = _ticket("new")
    sd.scan_clean(monkeypatch)
    parts = [_part("справка.txt"), _part("setup.exe", b"MZ" + b"\x00" * 64)]
    error = _refuse("file_rejected", lambda: replies.reply(ticket, text="Ответ", parts=parts, actor=actor))
    assert error.message == "файл «setup.exe» не принят: исполняемый файл"
    assert not model("servicedesk.TicketEntry").objects.filter(ticket=ticket, kind="reply").exists()
    assert not model("core.StoredFile").objects.filter(purpose="attachment").exists()
    assert not model("servicedesk.Attachment").objects.filter(ticket=ticket).exists()
    assert sd.ticket_mails(ticket) == [] and org.files_queue().jobs == []
    assert _fresh(ticket).kind == "new", "статус не меняется при отказе"
    assert not list(protected_root.glob("incoming/*"))


def test_reply_with_attachments_waits_in_waiting_files(django_capture_on_commit_callbacks, monkeypatch, protected_root):
    """FR-244: ответ с файлами ждёт проверки: `waiting_files`, письма нет, файл `pending` в `incoming`, задание проверки поставлено."""
    attachments = _svc("attachments")
    actor = _actor()
    ticket = _ticket("in_progress")
    sd.scan_clean(monkeypatch)
    entry = _reply(ticket, actor, django_capture_on_commit_callbacks, parts=[_part()])
    _fresh(entry)
    assert entry.send_state == "waiting_files" and entry.mail_id is None
    assert sd.ticket_mails(ticket) == [] and mail_jobs() == []
    assert attachments.pending_for(entry) is True
    (stored,) = _stored_of(entry)
    assert stored.purpose == "attachment" and stored.status == "pending"
    assert (protected_root / "incoming" / str(stored.pk)).is_file()
    assert [str(job.args[0]) for job in _file_jobs()] == [str(stored.pk)]


def test_reply_waits_while_files_are_checked_then_goes_when_all_clean(
        django_capture_on_commit_callbacks, monkeypatch, protected_root):
    """FR-244: пока проверен не последний файл — `waiting_files` и письма нет; проверен последний чистый — `queued` и письмо."""
    actor = _actor()
    ticket = _ticket("in_progress")
    sd.scan_clean(monkeypatch)
    entry = _reply(ticket, actor, django_capture_on_commit_callbacks,
                   parts=[_part("первый.txt", b"one"), _part("второй.txt", b"two")])
    first, second = _stored_of(entry)
    _run_jobs(django_capture_on_commit_callbacks, monkeypatch, [_job_of(first)])
    assert _fresh(first).status == "clean" and _fresh(second).status == "pending"
    assert _fresh(entry).send_state == "waiting_files" and sd.ticket_mails(ticket) == []
    _run_jobs(django_capture_on_commit_callbacks, monkeypatch, [_job_of(second)])
    assert _fresh(second).status == "clean"
    assert _fresh(entry).send_state == "queued"
    (message,) = sd.ticket_mails(ticket)
    assert _fresh(entry).mail_id == message.pk
    assert message.attachments == [str(first.pk), str(second.pk)]
    assert (protected_root / "attachments" / str(first.pk)).is_file()


def test_clean_files_with_flag_set_waiting_since_when_still_waiting_kind(
        django_capture_on_commit_callbacks, monkeypatch, protected_root):
    """FR-244, FR-250: с флажком отсчёт начинается при постановке письма, если заявка ещё в виде «ждёт»; иначе `waiting_since` пуст."""
    tickets = _svc("tickets")
    actor = _actor()
    still_waiting, moved_away = _ticket("in_progress"), _ticket("in_progress")
    sd.scan_clean(monkeypatch)
    first = _reply(still_waiting, actor, django_capture_on_commit_callbacks, wait=True, parts=[_part()])
    second = _reply(moved_away, actor, django_capture_on_commit_callbacks, wait=True, parts=[_part()])
    for ticket in (still_waiting, moved_away):
        assert _fresh(ticket).kind == "waiting" and ticket.waiting_since is None, "до проверки отсчёта нет"
    in_work = model("servicedesk.Status").objects.get(kind="in_progress", is_default=True)
    with django_capture_on_commit_callbacks(execute=True):
        tickets.set_status_manual(moved_away, in_work, actor=actor)
    assert _fresh(moved_away).kind == "in_progress"
    with django_capture_on_commit_callbacks(execute=True):
        org.run_files_worker()
    assert _fresh(first).send_state == "queued" and _fresh(second).send_state == "queued"
    (mail,) = sd.ticket_mails(_fresh(still_waiting))
    assert still_waiting.kind == "waiting" and still_waiting.waiting_since is not None
    assert _mail_dates_close(still_waiting.waiting_since, mail.created_at)
    assert _fresh(moved_away).kind == "in_progress" and moved_away.waiting_since is None


def test_reply_without_flag_sets_no_waiting_since(django_capture_on_commit_callbacks):
    """FR-244, FR-250: ответ без флажка статус «ждёт» не ставит и `waiting_since` не задаёт; из «новой» — в работу."""
    actor = _actor()
    ticket = _ticket("new")
    entry = _reply(ticket, actor, django_capture_on_commit_callbacks, wait=False)
    _fresh(ticket)
    assert ticket.kind == "in_progress" and ticket.waiting_since is None
    assert _fresh(entry).send_state == "queued" and entry.wait_flag is False
    assert len(sd.ticket_mails(ticket)) == 1


# --- карантин, архив с паролем, закрытие во время проверки (FR-244) ---------------------------------

def test_reply_with_quarantined_file_not_sent_with_event(django_capture_on_commit_callbacks, monkeypatch, protected_root):
    """FR-244: файл в карантине — ответ `not_sent`, событие ленты «ответ не отправлен: вложение «…» в карантине», кнопка заново."""
    actor = _actor()
    ticket = _ticket("in_progress")
    sd.scan_found(monkeypatch, "Eicar-Signature")
    name = "заметка.txt"
    entry = _reply(ticket, actor, django_capture_on_commit_callbacks, parts=[_part(name, org.eicar_bytes())])
    (stored,) = _stored_of(entry)
    with django_capture_on_commit_callbacks(execute=True):
        org.run_files_worker()
    assert _fresh(entry).send_state == "not_sent" and entry.mail_id is None
    assert _fresh(stored).status == "quarantine"
    assert sd.ticket_mails(ticket) == []
    (event,) = _events(ticket, "reply_not_sent")
    assert event.data == {"reason": "quarantine", "entry_id": entry.pk, "name": name}
    dom = _card(actor, ticket)
    assert "ответ не отправлен: вложение «заметка.txt» в карантине" in _item_event(dom, "reply_not_sent").text()
    assert _item(dom, entry).find_all(data_send_state="not_sent")


def _item_event(dom: _El, code: str) -> _El:
    (li,) = dom.find_all("li", data_kind="event", data_event=code)
    return li


def test_reply_with_quarantine_sends_no_letter_and_starts_no_countdown(
        django_capture_on_commit_callbacks, monkeypatch, protected_root):
    """FR-244, FR-250: при карантине письма и задания отправки нет, с флажком `waiting_since` остаётся пустым."""
    actor = _actor()
    ticket = _ticket("in_progress")
    sd.scan_found(monkeypatch, "Eicar-Signature")
    entry = _reply(ticket, actor, django_capture_on_commit_callbacks, wait=True,
                   parts=[_part("заметка.txt", org.eicar_bytes())])
    with django_capture_on_commit_callbacks(execute=True):
        org.run_files_worker()
    assert _fresh(entry).send_state == "not_sent" and entry.wait_flag is True
    assert sd.ticket_mails(ticket) == [] and mail_jobs() == []
    assert _fresh(ticket).kind == "waiting" and ticket.waiting_since is None


def test_reply_with_password_archive_not_sent_with_event(django_capture_on_commit_callbacks, monkeypatch, protected_root):
    """FR-244: «архив с паролем» (сигнатура `Heuristics.Encrypted.*`) — файл стёрт, `rejected="encrypted"`, ответ `not_sent`, причина в событии."""
    actor = _actor()
    ticket = _ticket("in_progress")
    sd.scan_found(monkeypatch, "Heuristics.Encrypted.Zip")
    name = "секрет.zip"
    entry = _reply(ticket, actor, django_capture_on_commit_callbacks, parts=[_part(name, b"plain bytes")])
    (stored,) = _stored_of(entry)
    with django_capture_on_commit_callbacks(execute=True):
        org.run_files_worker()
    assert _fresh(entry).send_state == "not_sent" and entry.mail_id is None
    (attachment,) = entry.attachments.all()
    assert attachment.rejected == "encrypted" and attachment.file_id is None
    assert not model("core.StoredFile").objects.filter(pk=stored.pk).exists()
    assert not list(protected_root.glob(f"*/{stored.pk}"))
    assert sd.ticket_mails(ticket) == []
    (event,) = _events(ticket, "reply_not_sent")
    assert event.data == {"reason": "encrypted", "entry_id": entry.pk, "name": name}
    assert [e.data["name"] for e in _events(ticket, "attachment_rejected")] == [name]
    assert "ответ не отправлен: вложение «секрет.zip» — архив с паролем" in _item_event(
        _card(actor, ticket), "reply_not_sent").text()


def test_reply_with_ticket_closed_during_check_not_sent_ticket_closed(
        django_capture_on_commit_callbacks, monkeypatch, protected_root):
    """FR-244, FR-252: заявку закрыли за время проверки — ответ `not_sent`, событие «ответ не отправлен: заявка закрыта», письма нет."""
    actor = _actor()
    ticket = _ticket("in_progress")
    sd.scan_clean(monkeypatch)
    entry = _reply(ticket, actor, django_capture_on_commit_callbacks, parts=[_part()])
    assert _fresh(entry).send_state == "waiting_files"
    _closed(ticket)
    with django_capture_on_commit_callbacks(execute=True):
        org.run_files_worker()
    assert _fresh(entry).send_state == "not_sent" and entry.mail_id is None
    assert sd.ticket_mails(ticket) == [] and mail_jobs() == []
    (event,) = _events(ticket, "reply_not_sent")
    assert event.data == {"reason": "ticket_closed", "entry_id": entry.pk}
    assert "ответ не отправлен: заявка закрыта" in _item_event(_card(actor, ticket), "reply_not_sent").text()


# --- повторная отправка (FR-244) -------------------------------------------------------------------

def _infected_reply(capture, monkeypatch, actor, ticket, *, wait: bool = False):
    """Ответ с заражённым и чистым файлом: чистый проверен, заражённый — в карантине. Возвращает (ответ, чистый файл)."""
    entry = _reply(ticket, actor, capture, wait=wait,
                   parts=[_part("плохой.txt", org.eicar_bytes()), _part("хороший.txt", b"good")])
    bad, good = _stored_of(entry)
    sd.scan_clean(monkeypatch)
    _run_jobs(capture, monkeypatch, [_job_of(good)])
    sd.scan_found(monkeypatch, "Eicar-Signature")
    _run_jobs(capture, monkeypatch, [_job_of(bad)])
    assert _fresh(entry).send_state == "not_sent" and _fresh(good).status == "clean"
    assert _fresh(bad).status == "quarantine"
    return entry, good


def test_resend_without_infected_creates_new_item_with_clean_files_only(
        django_capture_on_commit_callbacks, monkeypatch, protected_root):
    """FR-244: «Отправить заново» — новый элемент `reply` только с чистыми файлами (те же `StoredFile`), сразу `queued`, письмо одно."""
    actor = _actor()
    ticket = _ticket("in_progress")
    old, good = _infected_reply(django_capture_on_commit_callbacks, monkeypatch, actor, ticket)
    with django_capture_on_commit_callbacks(execute=True):
        new = _svc("replies").resend(old, actor=actor)
    assert new.pk != old.pk and new.kind == "reply"
    assert _fresh(new).send_state == "queued"
    assert [a.file_id for a in new.attachments.all()] == [good.pk]
    assert _fresh(old).send_state == "not_sent"
    (message,) = sd.ticket_mails(ticket)
    assert new.mail_id == message.pk and message.attachments == [str(good.pk)]


def test_resend_item_keeps_text_and_link_to_original(django_capture_on_commit_callbacks, monkeypatch, protected_root):
    """FR-244: новый элемент несёт тот же текст, `resent_from` на исходный и флажок; журнал `ticket.reply_sent` с номером нового."""
    actor = _actor()
    ticket = _ticket("in_progress")
    old = _reply(ticket, actor, django_capture_on_commit_callbacks, text="Текст ответа", wait=True,
                 parts=[_part("плохой.txt", org.eicar_bytes())])
    sd.scan_found(monkeypatch, "Eicar-Signature")
    with django_capture_on_commit_callbacks(execute=True):
        org.run_files_worker()
    assert _fresh(old).send_state == "not_sent"
    events_before = model("servicedesk.TicketEntry").objects.filter(ticket=ticket, kind="event").count()
    with django_capture_on_commit_callbacks(execute=True):
        new = _svc("replies").resend(old, actor=actor)
    assert new.text == old.text == "Текст ответа"
    assert new.resent_from_id == old.pk and list(old.resends.all()) == [new]
    assert _fresh(new).wait_flag is True
    audit = model("core.AuditEvent").objects.filter(action="ticket.reply_sent", object_id=str(ticket.number))
    assert new.pk in [event.after.get("entry_id") for event in audit]
    assert model("servicedesk.TicketEntry").objects.filter(ticket=ticket, kind="event").count() == events_before, (
        "повторная отправка событий ленты не пишет")


def test_resend_starts_countdown_from_this_sending(django_capture_on_commit_callbacks, monkeypatch, protected_root):
    """FR-244, FR-250: отсчёт автозакрытия идёт от этой отправки, а не от исходного ответа."""
    actor = _actor()
    ticket = _ticket("in_progress")
    old = _reply(ticket, actor, django_capture_on_commit_callbacks, wait=True,
                 parts=[_part("плохой.txt", org.eicar_bytes())])
    sd.scan_found(monkeypatch, "Eicar-Signature")
    with django_capture_on_commit_callbacks(execute=True):
        org.run_files_worker()
    assert _fresh(ticket).waiting_since is None
    sd.backdate(old, "at", hours=1)
    with django_capture_on_commit_callbacks(execute=True):
        new = _svc("replies").resend(old, actor=actor)
    _fresh(ticket)
    (message,) = sd.ticket_mails(ticket)
    assert _fresh(new).send_state == "queued"
    assert ticket.kind == "waiting" and ticket.waiting_since is not None
    assert _mail_dates_close(ticket.waiting_since, message.created_at)
    assert ticket.waiting_since > old.at + timedelta(minutes=50)


def test_resend_button_only_on_not_sent_reply(django_capture_on_commit_callbacks, monkeypatch, protected_root):
    """FR-244: кнопка «Отправить заново…» — только у `not_sent` ответа открытой заявки; `resend` других отказывает `not_resendable`."""
    replies = _svc("replies")
    actor = _actor()
    ticket = _ticket("in_progress")
    queued = _reply(ticket, actor, django_capture_on_commit_callbacks)
    comment = replies.comment(ticket, text="Комментарий", actor=actor)
    other = _ticket("in_progress")
    foreign = _reply(other, actor, django_capture_on_commit_callbacks)
    not_sent = _reply(ticket, actor, django_capture_on_commit_callbacks, parts=[_part("плохой.txt", org.eicar_bytes())])
    sd.scan_found(monkeypatch, "Eicar-Signature")
    with django_capture_on_commit_callbacks(execute=True):
        org.run_files_worker()
    assert _fresh(not_sent).send_state == "not_sent" and _fresh(queued).send_state == "queued"

    dom = _card(actor, ticket)
    forms = dom.find_all("form", data_form="reply-resend")
    assert len(forms) == 1 and forms[0].inside(data_entry_id=not_sent.pk)
    (button,) = forms[0].find_all("button", data_action="reply-resend")
    assert "Отправить заново без заражённых вложений" in button.text()
    for entry in (queued, comment):
        assert not _item(dom, entry).find_all("form", data_form="reply-resend")

    for entry in (queued, comment):
        _refuse("not_resendable", lambda entry=entry: replies.resend(entry, actor=actor))
    client = support.logged_in(actor, ip=f"198.51.100.{next(_ips)}")
    response = client.post(f"/tickets/{ticket.number}/reply/{queued.pk}/resend/")
    assert response.status_code == 200
    (alert,) = _dom(response).find_all(role="alert")
    assert alert.attrs.get("data-code") == "not_resendable"
    assert client.post(f"/tickets/{ticket.number}/reply/{foreign.pk}/resend/").status_code == 404

    _closed(ticket)
    assert not _card(actor, ticket).find_all("form", data_form="reply-resend"), "на закрытой заявке кнопки нет"


def test_reply_to_closed_ticket_refused_with_message(django_capture_on_commit_callbacks):
    """FR-244, FR-252: закрытой заявке ответ не отправляется: `ticket_closed` с текстом контракта; маршрут — 200 и `[role=alert]`."""
    actor = _actor()
    ticket = _ticket("closed", closed_at=timezone.now())
    error = _refuse("ticket_closed", lambda: _svc("replies").reply(ticket, text="Ответ", actor=actor))
    assert error.message == CLOSED_TEXT
    client = support.logged_in(actor, ip=f"198.51.100.{next(_ips)}")
    with django_capture_on_commit_callbacks(execute=True):
        response = client.post(f"/tickets/{ticket.number}/reply/", {"text": "Ответ по закрытой"})
    assert response.status_code == 200
    (alert,) = _dom(response).find_all(role="alert")
    assert CLOSED_TEXT in alert.text() and alert.attrs.get("data-code") == "ticket_closed"
    assert not model("servicedesk.TicketEntry").objects.filter(ticket=ticket, kind="reply").exists()
    assert sd.ticket_mails(ticket) == []


# --- внутренний комментарий (FR-245) ---------------------------------------------------------------

def test_internal_comment_is_not_sent_as_reply(django_capture_on_commit_callbacks):
    """FR-245: комментарий — вид `comment`, без письма, задания и состояния отправки; статус, отсчёт и последнее сообщение целы."""
    actor = _actor()
    ticket = _ticket("waiting")
    sd.backdate(ticket, "waiting_since", hours=2)
    sd.backdate(ticket, "last_message_at", hours=1)
    before = (ticket.kind, ticket.waiting_since, ticket.last_message_at, ticket.last_message_from)
    with django_capture_on_commit_callbacks(execute=True):
        entry = _svc("replies").comment(ticket, text="Только для своих", actor=actor)
    assert entry.kind == "comment" and entry.send_state == "" and entry.mail_id is None
    assert sd.ticket_mails(ticket) == [] and mail_jobs() == []
    _fresh(ticket)
    assert (ticket.kind, ticket.waiting_since, ticket.last_message_at, ticket.last_message_from) == before
    audit = model("core.AuditEvent").objects.get(action="ticket.comment_added", object_id=str(ticket.number))
    assert audit.after == {"entry_id": entry.pk}


# --- доставка и недоставка письма ответа (FR-247, NFR-202) ------------------------------------------

def _queued_reply(actor, capture, settings, *, to_participant: bool = False):
    settings.SERVICEDESK_MAILBOX = "tickets@stand.test"
    ticket = _ticket("in_progress")
    if to_participant:
        sd.make_participant(ticket, "copy@client.test")
    entry = _reply(ticket, actor, capture, text="Текст ответа заявителю")
    (message,) = sd.ticket_mails(ticket)
    return ticket, entry, message


def test_reply_delivered_by_mail_job_on_first_attempt(django_capture_on_commit_callbacks, settings, mailpit):
    """FR-247, NFR-202: пока почта доступна, письмо уходит заданием `mail` с первой попытки; повторы заданы расписанием среза 001."""
    ticket, entry, message = _queued_reply(_actor(), django_capture_on_commit_callbacks, settings, to_participant=True)
    (job,) = mail_jobs()
    assert job.retries_left == 11 and list(job.retry_intervals) == RETRY_INTERVALS
    assert job.id not in mail_queue().scheduled_job_registry.get_job_ids()
    deliver()
    _fresh(message)
    assert message.status == "sent" and message.attempts == 1
    assert [a.ok for a in model("mail.MailAttempt").objects.filter(message=message).order_by("id")] == [True]
    letter = mailpit.wait_for(ticket.requester_email)
    assert letter["Subject"] == f"[#{ticket.number}] {ticket.subject}"
    assert [a["Address"] for a in letter["Cc"]] == ["copy@client.test"]
    assert [a["Address"] for a in letter["ReplyTo"]] == ["tickets@stand.test"]
    assert "Текст ответа заявителю" in letter["Text"]
    assert _fresh(entry).send_state == "queued"


def test_reply_retries_with_growing_pause_up_to_24_hours(django_capture_on_commit_callbacks, settings):
    """FR-247, NFR-202: паузы повторов растут (1, 5, 15, 60 мин, затем 3 ч), сумма — около 22 часов, в пределах 24; первая — около минуты."""
    from rq.job import Job

    ticket, entry, message = _queued_reply(_actor(), django_capture_on_commit_callbacks, settings)
    (job,) = mail_jobs()
    assert list(job.retry_intervals) == RETRY_INTERVALS and job.retries_left == 11
    break_smtp(settings)
    deliver()
    _fresh(message)
    assert message.status == "queued" and message.attempts == 1 and message.last_error
    fetched = Job.fetch(job.id, connection=mail_queue().connection)
    due = mail_queue().scheduled_job_registry.get_scheduled_time(fetched)
    assert 30 < (due - datetime.now(dt_timezone.utc)).total_seconds() <= 65, "первая пауза — около минуты"


def test_mail_server_down_reply_kept_in_ticket(django_capture_on_commit_callbacks, settings, mailpit):
    """FR-247, NFR-202: почта недоступна — ответ остаётся в заявке, письмо ждёт повтора (`queued`), «не доставлено» ещё нет."""
    actor = _actor()
    ticket, entry, message = _queued_reply(actor, django_capture_on_commit_callbacks, settings)
    break_smtp(settings)
    with django_capture_on_commit_callbacks(execute=True):
        deliver()
    assert _fresh(message).status == "queued" and message.last_error
    assert not mailpit.messages()
    assert _fresh(entry).kind == "reply" and entry.text == "Текст ответа заявителю" and entry.mail_id == message.pk
    assert _events(ticket, "mail_failed") == []
    li = _item(_card(actor, ticket), entry)
    (state,) = li.find_all(data_mail_status=True)
    assert state.attrs["data-mail-status"] == "queued" and not li.find_all(data_undelivered=True)


def _fail_for_good(capture, settings, message):
    """Последняя неудача задания: повторов не осталось, почта недоступна, `on_failure` идёт после фиксации."""
    (job,) = mail_jobs()
    job.retries_left = 0
    job.save()
    break_smtp(settings)
    with capture(execute=True):
        deliver()
    assert _fresh(message).status == "failed"


def test_failure_after_last_retry_writes_not_delivered_event_in_feed(
        django_capture_on_commit_callbacks, settings, bus_spy):
    """FR-247: после последней неудачи — событие шины `mail.failed`, событие ленты «письмо не доставлено: …» и маркер в ответе."""
    actor = _actor()
    bus_spy.listen("mail.failed")
    ticket, entry, message = _queued_reply(actor, django_capture_on_commit_callbacks, settings)
    _fail_for_good(django_capture_on_commit_callbacks, settings, message)
    assert bus_spy.calls("mail.failed") == [{"mail_id": message.pk, "related_ref": f"ticket:{ticket.pk}"}]
    (event,) = _events(ticket, "mail_failed")
    assert event.data == {"mail_kind": "reply", "entry_id": entry.pk}
    assert _svc("letters").unsent(entry) is True
    dom = _card(actor, ticket)
    assert "письмо не доставлено" in _item_event(dom, "mail_failed").text()
    li = _item(dom, entry)
    (state,) = li.find_all(data_mail_status=True)
    assert state.attrs["data-mail-status"] == "failed" and li.find_all(data_undelivered=True)


def test_failure_after_last_retry_writes_journal_record(django_capture_on_commit_callbacks, settings):
    """FR-247: недоставка пишет журнал `ticket.mail_failed` с видом письма, без автора и без адресов и текста."""
    ticket, entry, message = _queued_reply(_actor(), django_capture_on_commit_callbacks, settings)
    _fail_for_good(django_capture_on_commit_callbacks, settings, message)
    audit = model("core.AuditEvent").objects.get(action="ticket.mail_failed", object_id=str(ticket.number))
    assert audit.object_type == "ticket" and audit.actor_id is None
    assert audit.before == {} and audit.after == {"mail_kind": "reply"}


def test_card_shows_mail_state_from_mail_message(django_capture_on_commit_callbacks, settings):
    """FR-244, FR-247: карточка берёт состояние письма ответа из `MailMessage.status`: «в очереди», «отправлено», «не доставлено»."""
    actor = _actor()
    settings.SERVICEDESK_MAILBOX = "tickets@stand.test"
    ticket = _ticket("in_progress")
    entries = [_reply(ticket, actor, django_capture_on_commit_callbacks, text=f"Ответ {i}") for i in range(3)]
    waiting = sd.make_entry(ticket, "reply", author=actor, text="Ждёт файлов", send_state="waiting_files")
    wanted = {"queued": "в очереди", "sent": "отправлено", "failed": "не доставлено"}
    for entry, status in zip(entries, wanted):
        model("mail.MailMessage").objects.filter(pk=_fresh(entry).mail_id).update(status=status)
    dom = _card(actor, ticket)
    for entry, (status, label) in zip(entries, wanted.items()):
        li = _item(dom, entry)
        (state,) = li.find_all(data_mail_status=True)
        assert state.attrs["data-mail-status"] == status and label in state.text()
        assert bool(li.find_all(data_undelivered=True)) is (status == "failed")
    li = _item(dom, waiting)
    assert not li.find_all(data_mail_status=True)
    assert li.find_all(data_send_state="waiting_files")
