"""T-3118: письма заявителю (FR-210, FR-247, FR-253…259, NFR-202). Сценарии 1, 3, 5, 6 спеки SPEC-003.

Имена кода среза 003 (`apps.servicedesk…`) импортируются внутри тестов: сбор проходит до появления кода.
Правила — tests/CONTRACT-003.md (§ 5.3, 6.17, 10, дополнения 5, 6, 7, 8, 18 раздела 16). Доставку выполняет
`SimpleWorker` (tests/support_mail.py) на настоящем Valkey и SMTP Mailpit; тексты читает `mail_text`.
"""
import importlib
import os
import re
from datetime import timedelta

import pytest
from django.utils import timezone

from tests import factories, support, support_org as org, support_servicedesk as sd
from tests.support import model
from tests.support_mail import break_smtp, deliver

pytestmark = pytest.mark.django_db

PORTAL_NAME = "Портал для заявок"
CLOSE_TEXT = "Заменили картридж"


# --- помощники файла ----------------------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.servicedesk.services.{name}")


def _norm(text: str) -> str:
    """Текст без различий в пробелах и переносах строк."""
    return " ".join(text.split())


def _staff(unit, name: str | None = None):
    user = support.make_employee(full_name=name) if name else support.make_employee()
    org.make_member(user, unit)
    return user


def _ticket(*, requester_name: str = "Иванова Анна", text: str = "Не печатает принтер", **over):
    """Заявка в новой очереди с первым элементом `incoming`; возвращает (заявка, элемент, очередь)."""
    queue = over.pop("queue", None) or sd.make_queue()
    requester = sd.make_requester(full_name=requester_name)
    ticket = sd.make_ticket(queue=queue, requester=requester, **over)
    entry = sd.make_entry(ticket, "incoming", text=text)
    return ticket, entry, queue


def _send(capture, ticket, template, *, entry=None, extra=None):
    """`letters.send` внутри фиксации; возвращает новое письмо заявки."""
    letters = _svc("letters")
    before = len(sd.ticket_mails(ticket))
    with capture(execute=True):
        letters.send(ticket, template, entry=entry, extra=extra)
    mails = sd.ticket_mails(ticket)
    assert len(mails) == before + 1, f"письмо {template} не создано"
    return mails[-1]


def _job_of(message):
    import django_rq

    jobs = [j for j in django_rq.get_queue("mail").jobs if j.args == (message.pk,)]
    assert len(jobs) == 1, "задание deliver_message для письма не поставлено"
    return jobs[0]


def _ctx(message) -> dict:
    """Контекст письма так, как он лежит в задании."""
    return _job_of(message).meta["context"]


def _text(message) -> str:
    return sd.mail_text(message, _ctx(message))


def _mails_to(mailpit, email: str) -> list[dict]:
    """Все письма Mailpit на адрес: полное письмо плюс `_headers` (имена строчными, значения — списки)."""
    found = []
    for short in mailpit.messages():
        if any(a["Address"].lower() == email.lower() for a in short["To"]):
            full = mailpit.message(short["ID"])
            raw = mailpit._request("GET", f"/api/v1/message/{short['ID']}/headers")
            full["_headers"] = {k.lower(): v for k, v in raw.items()}
            found.append(full)
    return found


def _delivered(mailpit, email: str, template: str | None = None) -> dict:
    """Доставляет очередь и возвращает письмо на адрес (с нужным `X-Portal-Template`, если он назван)."""
    deliver()
    mails = _mails_to(mailpit, email)
    if template is not None:
        mails = [m for m in mails if m["_headers"].get("x-portal-template") == [template]]
    assert len(mails) == 1, f"в Mailpit {len(mails)} писем вместо одного"
    return mails[0]


def _cc_of(message) -> set[str]:
    return {a.strip() for a in message.cc.split(",") if a.strip()}


def _mails_of(ticket, template: str) -> list:
    return [m for m in sd.ticket_mails(ticket) if m.template == template]


def _closed_status():
    return model("servicedesk.Status").objects.get(kind="closed", is_default=True)


# --- send_rendered и задание -------------------------------------------------------------------------

def test_send_rendered_queues_deliver_job_and_rejects_unregistered_prefix(django_capture_on_commit_callbacks):
    """FR-247, FR-257, NFR-202: письмо заявки — `MailMessage` `queued` и задание `deliver_message` с повторами; чужой префикс — `ValueError`."""
    import django_rq

    from apps.integrations.mail import services

    MailMessage = model("mail.MailMessage")
    context = {"ticket_id": 1, "entry_id": None, "after_hours": None}
    with django_capture_on_commit_callbacks(execute=True):
        message = services.send_rendered(
            "ticket.confirmation", "req@client.test", subject="[#1] Тема", cc=["a@corp.test", "b@corp.test"],
            reply_to="desk@desk.test", message_id="<one@desk.test>", references="<first@client.test>",
            auto_submitted="auto-replied", related_ref="ticket:1", attachments=[], context=context)
    message.refresh_from_db()
    assert (message.status, message.template, message.to) == ("queued", "ticket.confirmation", "req@client.test")
    assert message.subject == "[#1] Тема" and _cc_of(message) == {"a@corp.test", "b@corp.test"}
    assert (message.reply_to, message.message_id, message.references) == (
        "desk@desk.test", "<one@desk.test>", "<first@client.test>")
    assert (message.auto_submitted, message.related_ref, message.attachments) == ("auto-replied", "ticket:1", [])
    jobs = [j for j in django_rq.get_queue("mail").jobs if j.func_name == "apps.integrations.mail.tasks.deliver_message"]
    assert len(jobs) == 1
    job = jobs[0]
    assert (job.args, job.kwargs) == ((message.pk,), {})
    assert job.retries_left == 11 and list(job.retry_intervals) == [60, 300, 900, 3600] + [10800] * 7
    assert job.failure_callback is not None and job.get_status() == "queued"
    assert job.meta == {"context": context}
    count = MailMessage.objects.count()
    for foreign in ("other.letter", "invitation", "ticketing"):
        with pytest.raises(ValueError):
            services.send_rendered(foreign, "req@client.test", subject="[#1] Тема", cc=[], reply_to="",
                                   message_id="<two@desk.test>", references="", auto_submitted="",
                                   related_ref="ticket:1", attachments=[], context=context)
    assert MailMessage.objects.count() == count, "письмо с чужим префиксом создано"


def test_mail_body_not_stored_and_job_meta_has_no_texts_or_addresses(django_capture_on_commit_callbacks):
    """FR-257, FR-258: тела письма в базе нет; в `job.meta` только `ticket_id`, `entry_id`, `after_hours` — без адресов и текстов."""
    secret_text = f"Секретный текст заявки {factories.new_password()}"
    ticket, entry, _ = _ticket(text=secret_text)
    participant = sd.make_participant(ticket, "copy@corp.test", name="Копиев Копий")
    message = _send(django_capture_on_commit_callbacks, ticket, "ticket.confirmation", entry=entry,
                    extra={"after_hours": "07.10.2026 09:00", "junk": "someone@client.test", "text": secret_text})
    job = _job_of(message)
    assert job.meta == {"context": {"ticket_id": ticket.pk, "entry_id": entry.pk, "after_hours": "07.10.2026 09:00"}}
    dump = repr(job.__dict__)
    for private in (secret_text, ticket.requester_email, participant.email, ticket.requester_name, ticket.subject):
        leaked = private in dump
        assert not leaked, "в задании очереди лежат данные заявки"
    field_names = {f.name for f in type(message)._meta.get_fields()}
    assert not field_names & {"body", "text", "content"}, "у MailMessage появилось поле для тела письма"
    stored = repr([getattr(message, f.name) for f in type(message)._meta.concrete_fields])
    assert secret_text not in stored


def test_deliver_renders_body_from_database_at_send_time(protected_root, mailpit, django_capture_on_commit_callbacks):
    """FR-258: тело собирается в момент отправки из базы; прикладываются только чистые и доступные вложения."""
    letters, files = _svc("letters"), importlib.import_module("apps.core.services.files")
    StoredFile, Attachment = model("core.StoredFile"), model("servicedesk.Attachment")
    ticket, _, queue = _ticket()
    author = _staff(queue.unit, "Петров Пётр Сергеевич")
    entry = sd.make_entry(ticket, "reply", author=author, text="Старый текст ответа", send_state="queued")

    def attach(name, status, *, on_disk=True, file=True):
        stored = None
        if file:
            stored = StoredFile.objects.create(purpose="attachment", owner=None, size=5, sha256="0" * 64,
                                               content_type="text/plain", status=status)
            if on_disk:
                path = files.attachment_path(stored)
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"12345")
        Attachment.objects.create(ticket=ticket, entry=entry, file=stored, name=name, size=5,
                                  rejected="" if file else "too_big", created_at=timezone.now())
        return stored

    good = attach("отчёт.txt", "clean")
    attach("пропал.txt", "clean", on_disk=False)
    bad = attach("вирус.txt", "quarantine")
    attach("огромный.zip", "clean", file=False)
    assert str(good.pk) in letters.attachment_ids(entry)
    assert "огромный.zip" not in repr(letters.attachment_ids(entry))
    assert letters.attachment_ids(sd.make_entry(ticket, "comment", text="x")) == []
    message = _send(django_capture_on_commit_callbacks, ticket, "ticket.reply", entry=entry)
    assert str(good.pk) in message.attachments
    assert str(bad.pk) not in letters.attachment_ids(entry), "файл в карантине попал в attachment_ids"
    assert str(bad.pk) not in message.attachments, "файл в карантине попал во вложения письма"
    entry.refresh_from_db()
    assert entry.mail_id == message.pk, "letters.send не поставил entry.mail у ответа"
    model("servicedesk.TicketEntry").objects.filter(pk=entry.pk).update(text="Новый текст ответа")
    rendered = letters.render(message, {"ticket_id": ticket.pk, "entry_id": entry.pk, "after_hours": None})
    assert [(name, str(path)) for name, path in rendered.attachments] == [("отчёт.txt", str(files.attachment_path(good)))]
    delivered = _delivered(mailpit, ticket.requester_email, "ticket.reply")
    assert "Новый текст ответа" in delivered["Text"] and "Старый текст ответа" not in delivered["Text"]
    assert [a["FileName"] for a in delivered["Attachments"]] == ["отчёт.txt"]


# --- заголовки -----------------------------------------------------------------------------------------

def test_from_header_has_portal_name_and_smtp_from(settings, mailpit, django_capture_on_commit_callbacks):
    """FR-257: `From` — название портала из настроек и адрес `SMTP_FROM` (`settings.DEFAULT_FROM_EMAIL`)."""
    model("core.PortalSettings").objects.update(name=PORTAL_NAME)
    settings.DEFAULT_FROM_EMAIL = "portal@mail.test"
    ticket, entry, _ = _ticket()
    _send(django_capture_on_commit_callbacks, ticket, "ticket.confirmation", entry=entry)
    delivered = _delivered(mailpit, ticket.requester_email)
    assert delivered["From"]["Name"] == PORTAL_NAME and delivered["From"]["Address"] == "portal@mail.test"
    assert delivered["_headers"]["x-portal-template"] == ["ticket.confirmation"]


def test_to_requester_cc_unremoved_participants_and_no_cc_for_confirmation(
        mailpit, django_capture_on_commit_callbacks):
    """FR-253, FR-256, FR-257: `To` — заявитель; `Cc` — неснятые участники без адреса заявителя; у подтверждения копии нет."""
    letters = _svc("letters")
    ticket, entry, queue = _ticket()
    author = _staff(queue.unit)
    sd.make_participant(ticket, "alive@corp.test")
    sd.make_participant(ticket, "gone@corp.test", removed_by=author)
    sd.make_participant(ticket, ticket.requester_email)
    reply = sd.make_entry(ticket, "reply", author=author, text="Ответ", send_state="queued")
    first = _send(django_capture_on_commit_callbacks, ticket, "ticket.confirmation", entry=entry)
    assert first.to == ticket.requester_email and first.cc == ""
    entry.refresh_from_db()
    assert entry.mail_id is None, "подтверждение не должно ставить entry.mail"
    assert letters.recipients(ticket, "ticket.confirmation") == (ticket.requester_email, [])
    for template in ("ticket.assigned", "ticket.closed", "ticket.autoclosed", "ticket.reopened", "ticket.reply"):
        message = _send(django_capture_on_commit_callbacks, ticket, template,
                        entry=reply if template == "ticket.reply" else None)
        assert message.to == ticket.requester_email, template
        assert _cc_of(message) == {"alive@corp.test"}, template
        to, cc = letters.recipients(ticket, template)
        assert to == ticket.requester_email and list(cc) == ["alive@corp.test"], template
    deliver()
    sent = [m for m in _mails_to(mailpit, ticket.requester_email)
            if m["_headers"].get("x-portal-template") == ["ticket.reopened"]]
    assert len(sent) == 1
    assert [a["Address"] for a in sent[0]["Cc"]] == ["alive@corp.test"]
    confirmation = [m for m in _mails_to(mailpit, ticket.requester_email)
                    if m["_headers"].get("x-portal-template") == ["ticket.confirmation"]]
    assert len(confirmation) == 1 and not confirmation[0]["Cc"]


def test_reply_to_is_servicedesk_mailbox(settings, mailpit, django_capture_on_commit_callbacks):
    """FR-257: `Reply-To` — адрес ящика заявок; при пустом адресе заголовка нет, а домен `Message-ID` — из `SMTP_FROM`."""
    settings.DEFAULT_FROM_EMAIL = "portal@from.test"
    settings.SERVICEDESK_MAILBOX = "desk@desk.test"
    ticket, entry, _ = _ticket()
    message = _send(django_capture_on_commit_callbacks, ticket, "ticket.confirmation", entry=entry)
    assert message.reply_to == "desk@desk.test"
    delivered = _delivered(mailpit, ticket.requester_email)
    assert [a["Address"] for a in delivered["ReplyTo"]] == ["desk@desk.test"]
    mailpit.clear()
    settings.SERVICEDESK_MAILBOX = ""
    other, other_entry, _ = _ticket()
    empty = _send(django_capture_on_commit_callbacks, other, "ticket.confirmation", entry=other_entry)
    assert empty.reply_to == "" and re.fullmatch(r"<[^<>@\s]+@from\.test>", empty.message_id)
    delivered = _delivered(mailpit, other.requester_email)
    assert not delivered["ReplyTo"] and "reply-to" not in delivered["_headers"]


def test_own_message_id_with_mailbox_domain_saved_before_send(settings, mailpit, django_capture_on_commit_callbacks):
    """FR-257: свой `Message-ID` с доменом ящика заявок сохраняется в `MailMessage` до отправки и уходит в заголовок."""
    letters = _svc("letters")
    settings.SERVICEDESK_MAILBOX = "desk@desk.test"
    ticket, entry, _ = _ticket()
    message = _send(django_capture_on_commit_callbacks, ticket, "ticket.confirmation", entry=entry)
    assert message.status == "queued" and message.attempts == 0
    assert re.fullmatch(r"<[^<>@\s]+@desk\.test>", message.message_id), "идентификатор не с доменом ящика"
    one, two = letters.new_message_id(), letters.new_message_id()
    assert one != two and re.fullmatch(r"<[^<>@\s]+@desk\.test>", one)
    delivered = _delivered(mailpit, ticket.requester_email)
    assert delivered["_headers"]["message-id"] == [message.message_id]


def test_in_reply_to_and_references_chain_first_requester_letter_and_previous_portal_letter(
        mailpit, django_capture_on_commit_callbacks):
    """FR-257: `References` — идентификатор первого письма заявителя и предыдущего письма портала; `In-Reply-To` — последний; без них заголовков нет."""
    letters = _svc("letters")
    ticket, first_entry, queue = _ticket()
    first_id = "<first-letter@client.test>"
    lonely = letters.references_of(ticket)
    assert lonely == [], "у заявки без письма заявителя и без писем портала цепочка пуста"
    inbound = sd.make_inbound(message_id=first_id, from_email=ticket.requester_email)
    model("servicedesk.TicketEntry").objects.filter(pk=first_entry.pk).update(inbound=inbound)
    first = _send(django_capture_on_commit_callbacks, ticket, "ticket.confirmation")
    assert first.references == first_id and letters.references_of(ticket) == [first_id, first.message_id]
    second = _send(django_capture_on_commit_callbacks, ticket, "ticket.reopened")
    assert second.references.split() == [first_id, first.message_id]
    third = _send(django_capture_on_commit_callbacks, ticket, "ticket.assigned")
    assert third.references.split() == [first_id, second.message_id], "предыдущее письмо портала — последнее"
    deliver()
    got = {m["_headers"]["x-portal-template"][0]: m for m in _mails_to(mailpit, ticket.requester_email)}
    assert got["ticket.confirmation"]["_headers"]["in-reply-to"] == [first_id]
    assert got["ticket.confirmation"]["_headers"]["references"][0].split() == [first_id]
    assert got["ticket.reopened"]["_headers"]["in-reply-to"] == [first.message_id]
    assert got["ticket.reopened"]["_headers"]["references"][0].split() == [first_id, first.message_id]
    assert got["ticket.assigned"]["_headers"]["in-reply-to"] == [second.message_id]
    mailpit.clear()
    lone, lone_entry, _ = _ticket()
    assert letters.references_of(lone) == []
    message = _send(django_capture_on_commit_callbacks, lone, "ticket.confirmation", entry=lone_entry)
    assert message.references == ""
    delivered = _delivered(mailpit, lone.requester_email)
    assert "references" not in delivered["_headers"] and "in-reply-to" not in delivered["_headers"]


# --- Auto-Submitted ------------------------------------------------------------------------------------

def test_auto_submitted_auto_replied_for_confirmation_of_email_ticket(mailpit, django_capture_on_commit_callbacks):
    """FR-253, FR-257: подтверждение заявки из письма помечено `Auto-Submitted: auto-replied`."""
    letters = _svc("letters")
    ticket, entry, _ = _ticket()
    assert ticket.source.system_code == "mail"
    message = _send(django_capture_on_commit_callbacks, ticket, "ticket.confirmation", entry=entry)
    assert message.auto_submitted == "auto-replied" and letters.auto_submitted(ticket, "ticket.confirmation") == "auto-replied"
    delivered = _delivered(mailpit, ticket.requester_email)
    assert delivered["_headers"]["auto-submitted"] == ["auto-replied"]


def test_auto_submitted_auto_generated_for_form_and_executor_confirmation(django_capture_on_commit_callbacks):
    """FR-253, FR-257: подтверждение заявки с формы и от исполнителя — `auto-generated`."""
    letters = _svc("letters")
    Source = model("servicedesk.Source")
    for source in (Source.objects.get(system_code="form"), Source.objects.filter(system_code="").order_by("id").first()):
        ticket, entry, _ = _ticket(source=source)
        message = _send(django_capture_on_commit_callbacks, ticket, "ticket.confirmation", entry=entry)
        assert message.auto_submitted == "auto-generated", source.name
        assert letters.auto_submitted(ticket, "ticket.confirmation") == "auto-generated"


def test_auto_submitted_auto_generated_for_assigned_closed_autoclosed_reopened(
        mailpit, django_capture_on_commit_callbacks):
    """FR-255, FR-256, FR-257: письма о ходе заявки — `Auto-Submitted: auto-generated` (и в `MailMessage`, и в заголовке)."""
    letters = _svc("letters")
    ticket, _, queue = _ticket(resolution=CLOSE_TEXT)
    ticket.assignee = _staff(queue.unit, "Петров Пётр Сергеевич")
    ticket.save(update_fields=["assignee"])
    templates = ("ticket.assigned", "ticket.closed", "ticket.autoclosed", "ticket.reopened")
    for template in templates:
        message = _send(django_capture_on_commit_callbacks, ticket, template)
        assert message.auto_submitted == "auto-generated", template
        assert letters.auto_submitted(ticket, template) == "auto-generated"
    deliver()
    got = {m["_headers"]["x-portal-template"][0]: m for m in _mails_to(mailpit, ticket.requester_email)}
    assert set(got) == set(templates)
    for template in templates:
        assert got[template]["_headers"]["auto-submitted"] == ["auto-generated"], template


def test_executor_reply_has_no_auto_submitted_header(mailpit, django_capture_on_commit_callbacks):
    """FR-257: ответ исполнителя пишет человек — заголовка `Auto-Submitted` нет; других служебных заголовков, кроме `X-Portal-Template`, тоже."""
    letters = _svc("letters")
    ticket, _, queue = _ticket()
    reply = sd.make_entry(ticket, "reply", author=_staff(queue.unit), text="Перезагрузите принтер", send_state="queued")
    message = _send(django_capture_on_commit_callbacks, ticket, "ticket.reply", entry=reply)
    assert message.auto_submitted == "" and letters.auto_submitted(ticket, "ticket.reply") == ""
    delivered = _delivered(mailpit, ticket.requester_email)
    headers = delivered["_headers"]
    assert "auto-submitted" not in headers
    assert headers["x-portal-template"] == ["ticket.reply"]
    for absent in ("precedence", "x-auto-response-suppress", "list-id", "x-autoreply"):
        assert absent not in headers, absent


# --- тема ----------------------------------------------------------------------------------------------

def test_subject_is_number_and_ticket_subject_with_control_chars_cleaned(
        mailpit, django_capture_on_commit_callbacks):
    """FR-257: тема письма — `[#N] тема`; переводы строк, табуляции и управляющие знаки — пробел; пустая тема — `[#N]`; при создании заявки тема чистится так же."""
    letters, tickets = _svc("letters"), _svc("tickets")
    ticket, entry, _ = _ticket(subject="Сломался\r\nпринтер\tна\x07 втором", number=77)
    assert letters.subject_of(ticket) == "[#77] Сломался принтер на втором"
    message = _send(django_capture_on_commit_callbacks, ticket, "ticket.confirmation", entry=entry)
    assert message.subject == "[#77] Сломался принтер на втором"
    delivered = _delivered(mailpit, ticket.requester_email)
    assert delivered["Subject"] == "[#77] Сломался принтер на втором"
    empty, _, _ = _ticket(subject="", number=78)
    assert letters.subject_of(empty) == "[#78]"
    # тема заявки в базе не длиннее 255 (plan.md:347, `Ticket.subject`); 300 знаков база не примет, поэтому
    # проверяется, что тема предельной длины уходит в письмо целиком, без лишней обрезки
    long_one, _, _ = _ticket(subject="а" * 255, number=79)
    assert letters.subject_of(long_one) == "[#79] " + "а" * 255
    category = sd.make_category(on_form=True)
    with django_capture_on_commit_callbacks(execute=True):
        created = tickets.create(channel=tickets.FORM, subject="Тема\r\nс\tпереносом\x07 строки", text="Текст",
                                 requester_email=factories.new_email("req"), category=category,
                                 consent_at=timezone.now())
    assert created.ticket.subject == "Тема с переносом строки"
    assert sd.ticket_mails(created.ticket)[0].subject == f"[#{created.ticket.number}] Тема с переносом строки"


# --- тексты --------------------------------------------------------------------------------------------

CONSENT = ("Чтобы дополнить заявку, ответьте на это письмо, не меняя тему. "
           "Отправляя заявку, вы согласны на обработку ваших персональных данных (адрес, ФИО, подразделение и "
           "текст заявки) для работы ИТ-отдела.")


def test_confirmation_text_matches_spec(django_capture_on_commit_callbacks):
    """FR-253, FR-258: подтверждение — дословно по § 10.4 без необязательных строк; без ФИО в приветствии адрес; текст — первого письма заявки; без экранирования."""
    text = "Принтер & сканер <не работают>\nВторая строка"
    ticket, entry, _ = _ticket(subject="Не печатает <принтер>", text=text, number=1234)
    sd.make_entry(ticket, "incoming", text="Второе письмо заявителя")
    message = _send(django_capture_on_commit_callbacks, ticket, "ticket.confirmation", entry=entry)
    body = sd.mail_text(message, {"ticket_id": ticket.pk, "entry_id": entry.pk, "after_hours": None})
    expected = ("Здравствуйте, Иванова Анна! Ваша заявка принята под номером 1234. Тема: Не печатает <принтер> "
                "Текст заявки: Принтер & сканер <не работают> Вторая строка " + CONSENT)
    assert _norm(body) == expected
    nameless, nameless_entry, _ = _ticket(requester_name="", text="Текст", subject="Тема", number=1235)
    message = _send(django_capture_on_commit_callbacks, nameless, "ticket.confirmation", entry=nameless_entry)
    body = sd.mail_text(message, {"ticket_id": nameless.pk, "entry_id": nameless_entry.pk, "after_hours": None})
    assert _norm(body).startswith(f"Здравствуйте, {nameless.requester_email}! Ваша заявка принята под номером 1235.")


def test_confirmation_optional_lines_rejected_attachments_and_executor(django_capture_on_commit_callbacks):
    """FR-253, FR-255, FR-258: строки «Вложения, которые не приняты» и «Исполнитель» — только когда есть что сказать; имя — «Имя Фамилия»."""
    Attachment = model("servicedesk.Attachment")
    ticket, entry, queue = _ticket(subject="Тема", text="Текст")
    plain = _send(django_capture_on_commit_callbacks, ticket, "ticket.confirmation", entry=entry)
    context = {"ticket_id": ticket.pk, "entry_id": entry.pk, "after_hours": None}
    body = _norm(sd.mail_text(plain, context))
    assert "Вложения, которые не приняты" not in body and "Исполнитель" not in body
    for code, name in (("too_big", "большой.zip"), ("encrypted", "шифр.zip")):
        Attachment.objects.create(ticket=ticket, entry=entry, file=None, name=name, size=30, rejected=code,
                                  created_at=timezone.now())
    ticket.assignee = _staff(queue.unit, "Петров Пётр Сергеевич")
    ticket.assigned_once = True
    ticket.save(update_fields=["assignee", "assigned_once"])
    body = _norm(sd.mail_text(plain, context))
    titles = Attachment.REJECT_TITLES
    for name, code in (("большой.zip", "too_big"), ("шифр.zip", "encrypted")):
        assert f"{name} — {titles[code]}" in body, name
    line = re.search(r"Вложения, которые не приняты: (.+?)\. Исполнитель", body)
    assert line and "; " in line.group(1), "перечень не принятых вложений идёт через «; »"
    assert "Исполнитель: Пётр Петров." in body and "Сергеевич" not in body
    assert body.index("Вложения, которые не приняты") < body.index("Исполнитель: ") < body.index("Чтобы дополнить заявку")


def test_confirmation_off_hours_line_only_when_given(django_capture_on_commit_callbacks):
    """FR-254, FR-258: фраза о нерабочем времени — только по `after_hours`; с датой — «с <дата>», без даты — «в ближайшее рабочее время»."""
    ticket, entry, _ = _ticket(subject="Тема", text="Текст")
    cases = {
        None: None,
        "07.10.2026 09:00": "Заявка поступила в нерабочее время, мы рассмотрим её с 07.10.2026 09:00.",
        "": "Заявка поступила в нерабочее время, мы рассмотрим её в ближайшее рабочее время.",
    }
    for after_hours, phrase in cases.items():
        message = _send(django_capture_on_commit_callbacks, ticket, "ticket.confirmation", entry=entry,
                        extra={"after_hours": after_hours})
        context = _ctx(message)
        assert context["after_hours"] == after_hours
        body = _norm(sd.mail_text(message, context))
        if phrase is None:
            assert "нерабочее время" not in body
        else:
            assert phrase in body
            assert body.index(phrase) < body.index("Чтобы дополнить заявку")


def test_assigned_letter_text_and_sent_once_on_first_assignment(django_capture_on_commit_callbacks):
    """FR-255, FR-258: первое появление ответственного — одно письмо «взята в работу» с «Имя Фамилия»; повторные назначения письма не дают."""
    assignment = _svc("assignment")
    ticket, _, queue = _ticket(number=412)
    actor = _staff(queue.unit)
    first = _staff(queue.unit, "Петров Пётр Сергеевич")
    second = _staff(queue.unit, "Сидоров Сидор Сидорович")
    sd.make_participant(ticket, "alive@corp.test")
    sd.make_participant(ticket, "gone@corp.test", removed_by=actor)
    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.assign(ticket, first, actor=actor) is True
    letters = _mails_of(ticket, "ticket.assigned")
    assert len(letters) == 1
    assert letters[0].to == ticket.requester_email and _cc_of(letters[0]) == {"alive@corp.test"}
    assert letters[0].auto_submitted == "auto-generated"
    assert _norm(_text(letters[0])) == "Ваша заявка № 412 взята в работу. Ответственный: Пётр Петров."
    ticket.refresh_from_db()
    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.assign(ticket, second, actor=actor) is True
    ticket.refresh_from_db()
    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.take(ticket, actor=actor) is True
    assert len(_mails_of(ticket, "ticket.assigned")) == 1, "повторные назначения письма не дают"


def test_no_assigned_letter_when_assignee_set_at_creation(django_capture_on_commit_callbacks):
    """FR-255: ответственный при создании (по умолчанию категории или «взять себе») — отдельного письма нет, подтверждение называет его."""
    tickets = _svc("tickets")
    queue = sd.make_queue()
    sd.configure_servicedesk(domains=["corp.test"], default_queue=queue)
    default = _staff(queue.unit, "Сидоров Сидор Сидорович")
    taker = _staff(queue.unit, "Петров Пётр Сергеевич")
    category = sd.make_category(queue=queue, default_assignee=default, on_form=True)
    manual = model("servicedesk.Source").objects.filter(system_code="").order_by("id").first()
    with django_capture_on_commit_callbacks(execute=True):
        by_default = tickets.create(
            channel=tickets.FORM, subject="Тема", text="Текст", requester_email=factories.new_email("req"),
            category=category, consent_at=timezone.now()).ticket
    with django_capture_on_commit_callbacks(execute=True):
        by_taker = tickets.create(
            channel=tickets.STAFF, subject="Звонок", text="Звонили", requester_email=factories.new_email("req"),
            source=manual, take_by=taker, created_by=taker, queue_id=queue.unit_id).ticket
    for ticket, name in ((by_default, "Сидор Сидоров"), (by_taker, "Пётр Петров")):
        assert ticket.assignee_id is not None and ticket.assigned_once is True
        assert [m.template for m in sd.ticket_mails(ticket)] == ["ticket.confirmation"]
        assert f"Исполнитель: {name}." in _norm(_text(sd.ticket_mails(ticket)[0]))


def test_closed_autoclosed_reopened_texts_and_recipients(django_capture_on_commit_callbacks):
    """FR-256, FR-258: «закрыта с решением», «закрыта автоматически», «открыта заново» — тексты § 10.4, сроки из настроек на момент отправки; заявителю и неснятым участникам."""
    closing = _svc("closing")
    sd.configure_servicedesk(autoclose_days=4, reopen_days=5)
    queue = sd.make_queue()
    actor = _staff(queue.unit)

    def prepared(**over):
        ticket, _, _ = _ticket(queue=queue, **over)
        sd.make_participant(ticket, "alive@corp.test")
        sd.make_participant(ticket, "gone@corp.test", removed_by=actor)
        return ticket

    def check(ticket, template, expected):
        letters = _mails_of(ticket, template)
        assert len(letters) == 1, template
        assert letters[0].to == ticket.requester_email and _cc_of(letters[0]) == {"alive@corp.test"}
        assert letters[0].auto_submitted == "auto-generated"
        assert _norm(_text(letters[0])) == expected, template

    closed = prepared(number=501)
    with django_capture_on_commit_callbacks(execute=True):
        closing.close(closed, _closed_status(), CLOSE_TEXT, actor=actor)
    check(closed, "ticket.closed", f"Ваша заявка № 501 закрыта. Решение: {CLOSE_TEXT}. "
          "Если проблема не решена, ответьте на это письмо в течение 5 дней — заявка откроется заново.")
    sd.configure_servicedesk(reopen_days=6)
    assert "в течение 6 дней" in _norm(_text(_mails_of(closed, "ticket.closed")[0])), "срок читается при отправке"
    sd.configure_servicedesk(reopen_days=5)
    waiting = prepared(number=502, kind="waiting", waiting_since=timezone.now())
    sd.backdate(waiting, "waiting_since", days=6)
    with django_capture_on_commit_callbacks(execute=True):
        assert closing.autoclose_one(waiting.pk) is True
    check(waiting, "ticket.autoclosed", "Заявка № 502 закрыта автоматически: мы ждали вашего ответа 4 дней. "
          "Если вопрос остался, ответьте на это письмо в течение 5 дней — заявка откроется заново.")
    done = prepared(number=503, kind="closed", closed_at=timezone.now(), resolution="Сделано")
    with django_capture_on_commit_callbacks(execute=True):
        closing.reopen(done, actor=actor)
    check(done, "ticket.reopened", "Заявка № 503 снова в работе.")


def test_executor_reply_text_without_additions_with_signature(django_capture_on_commit_callbacks):
    """FR-257, FR-258: ответ исполнителя — его текст без добавлений и отдельной строкой подпись «Имя Фамилия»."""
    ticket, _, queue = _ticket()
    author = _staff(queue.unit, "Петров Пётр Сергеевич")
    text = "Перезагрузите принтер & проверьте <кабель>.\nЕсли не поможет — напишите."
    reply = sd.make_entry(ticket, "reply", author=author, text=text, send_state="queued")
    message = _send(django_capture_on_commit_callbacks, ticket, "ticket.reply", entry=reply)
    body = _text(message).strip()
    assert body.startswith(text), "перед текстом ответа ничего нет"
    assert body.endswith("\nПётр Петров"), "подпись — отдельной строкой в конце"
    assert body[len(text):-len("Пётр Петров")].strip() == "", "между текстом и подписью ничего нет"
    assert "Сергеевич" not in body


def test_letters_have_no_passwords_or_login_links(settings, django_capture_on_commit_callbacks):
    """FR-257: в письмах всех шести видов нет паролей и ссылок для входа."""
    letters = _svc("letters")
    ticket, entry, queue = _ticket(resolution=CLOSE_TEXT)
    ticket.assignee = author = _staff(queue.unit, "Петров Пётр Сергеевич")
    ticket.save(update_fields=["assignee"])
    reply = sd.make_entry(ticket, "reply", author=author, text="Ответ исполнителя", send_state="queued")
    assert letters.TEMPLATES == ("ticket.confirmation", "ticket.assigned", "ticket.closed", "ticket.autoclosed",
                                 "ticket.reopened", "ticket.reply")
    for template in letters.TEMPLATES:
        message = _send(django_capture_on_commit_callbacks, ticket, template,
                        entry=reply if template == "ticket.reply" else entry if template == "ticket.confirmation" else None)
        body = _text(message)
        lowered = body.lower()
        for forbidden in ("://", "/activate", "/password/reset", "парол", "password", "войти в портал"):
            assert forbidden not in lowered, f"{template}: {forbidden}"
        assert settings.PORTAL_URL not in body, template


def test_no_ticket_letters_to_executors(django_capture_on_commit_callbacks):
    """FR-259: исполнителям писем о заявках нет — ни при создании, ни при ответе и закрытии; адреса исполнителей не попадают ни в `To`, ни в `Cc`."""
    tickets, replies, closing = _svc("tickets"), _svc("replies"), _svc("closing")
    queue = sd.make_queue()
    creator = _staff(queue.unit, "Сидоров Сидор Сидорович")
    assignee = _staff(queue.unit, "Петров Пётр Сергеевич")
    manual = model("servicedesk.Source").objects.filter(system_code="").order_by("id").first()
    with django_capture_on_commit_callbacks(execute=True):
        ticket = tickets.create(channel=tickets.STAFF, subject="Звонок", text="Звонили",
                                requester_email=factories.new_email("req"), source=manual, take_by=assignee,
                                created_by=creator, queue_id=queue.unit_id).ticket
    with django_capture_on_commit_callbacks(execute=True):
        replies.reply(ticket, text="Ответ", actor=assignee)
    ticket.refresh_from_db()
    with django_capture_on_commit_callbacks(execute=True):
        closing.close(ticket, _closed_status(), CLOSE_TEXT, actor=assignee)
    letters = sd.ticket_mails(ticket)
    assert {m.template for m in letters} >= {"ticket.confirmation", "ticket.reply", "ticket.closed"}
    staff_emails = {creator.email.lower(), assignee.email.lower()}
    for message in letters:
        assert message.to == ticket.requester_email, message.template
        assert not _cc_of(message) & staff_emails and message.to.lower() not in staff_emails
    everything = model("mail.MailMessage").objects.filter(template__startswith="ticket.")
    assert not [m for m in everything if m.to.lower() in staff_emails], "письмо о заявке ушло исполнителю"


# --- повторы и недоставка -----------------------------------------------------------------------------

def test_retry_schedule_about_22_hours_within_24(settings, django_capture_on_commit_callbacks):
    """FR-247, NFR-202: паузы 1, 5, 15, 60 минут и семь раз по 3 часа — около 22 часов, в пределах 24; первая попытка сразу, первая пауза — минута."""
    from datetime import datetime, timezone as dt_timezone

    from rq.job import Job

    from apps.integrations.mail import services
    from tests.support_mail import mail_queue

    pauses = [60, 300, 900, 3600] + [10800] * 7
    total = sum(pauses)
    assert total == 80460 and 22 * 3600 <= total < 23 * 3600 and total <= 24 * 3600
    assert services.RETRY_MAX == 11 and services.RETRY_INTERVALS == pauses
    ticket, entry, _ = _ticket()
    message = _send(django_capture_on_commit_callbacks, ticket, "ticket.confirmation", entry=entry)
    job = _job_of(message)
    assert job.retries_left == 11 and list(job.retry_intervals) == pauses
    assert job.get_status() == "queued", "первая попытка не отложена"
    break_smtp(settings)
    deliver()
    message.refresh_from_db()
    assert message.status == "queued" and message.attempts == 1 and message.last_error
    fetched = Job.fetch(job.id, connection=mail_queue().connection)
    due = mail_queue().scheduled_job_registry.get_scheduled_time(fetched)
    assert 30 < (due - datetime.now(dt_timezone.utc)).total_seconds() <= 65, "первая пауза — около минуты"


def test_last_failure_publishes_mail_failed_and_adds_feed_event_and_audit(
        settings, bus_spy, django_capture_on_commit_callbacks):
    """FR-247: после последней неудачи письмо `failed`, шина получает `mail.failed`, в ленте событие «письмо не доставлено», в журнале `ticket.mail_failed`."""
    bus_spy.listen("mail.failed")
    ticket, entry, _ = _ticket()
    message = _send(django_capture_on_commit_callbacks, ticket, "ticket.confirmation", entry=entry)
    job = _job_of(message)
    job.retries_left = 0
    job.save()
    break_smtp(settings)
    with django_capture_on_commit_callbacks(execute=True):
        deliver()
    message.refresh_from_db()
    assert message.status == "failed" and message.attempts == 1
    assert bus_spy.calls("mail.failed") == [{"mail_id": message.pk, "related_ref": f"ticket:{ticket.pk}"}]
    events = list(model("servicedesk.TicketEntry").objects.filter(ticket=ticket, kind="event", event="mail_failed"))
    assert len(events) == 1 and events[0].data == {"mail_kind": "confirmation"}, "ключа entry_id у письма без элемента нет"
    journal = list(model("core.AuditEvent").objects.filter(action="ticket.mail_failed"))
    assert len(journal) == 1
    assert (journal[0].object_type, journal[0].object_id) == ("ticket", str(ticket.number))
    assert journal[0].actor_id is None and journal[0].after == {"mail_kind": "confirmation"}
    assert not journal[0].before


def test_safe_error_hides_imap_password(settings, password):
    """FR-210: текст ошибки не содержит пароль ящика заявок (`IMAP_PASSWORD`) — он заменяется на `***`; пароль SMTP по-прежнему скрыт, длина — до 500 знаков."""
    from apps.integrations.mail import tasks

    imap_password = os.environ.get("IMAP_PASSWORD") or password
    smtp_password = factories.new_password()
    settings.IMAP_PASSWORD = imap_password
    settings.EMAIL_HOST_PASSWORD = smtp_password
    text = tasks.safe_error(ConnectionError(f"login failed: {imap_password}; smtp: {smtp_password}"))
    leaked = imap_password in text or smtp_password in text
    assert not leaked, "пароль попал в текст ошибки"
    assert text.startswith("ConnectionError: ") and text.count("***") == 2
    long_text = tasks.safe_error(ConnectionError("x" * 600 + imap_password))
    long_leak = imap_password in long_text
    assert len(long_text) <= 500 and not long_leak
