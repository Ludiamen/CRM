"""Публичный интерфейс сервис-деска: письма заявителю (PLAN-003, «Где живёт код»; CONTRACT-003, 6.17 и раздел 10).

Письмо ставит `send` (после фиксации, через `send_rendered` почтового модуля); текст собирает `render` в момент
отправки из базы: в `MailMessage` и в задание очереди тело и адреса не попадают. В ленту и журнал модуль ничего
не пишет: это дело вызывающей службы. Исполнителям писем о заявках нет (FR-259).
"""
from email.utils import make_msgid, parseaddr

from django.conf import settings
from django.db import transaction
from django.template import Context, loader

from apps.core.extensions import MailRenderer, Rendered
from apps.core.services import files
from apps.integrations.mail import services as mail_services

from . import mail_parse

TEMPLATES = ("ticket.confirmation", "ticket.assigned", "ticket.closed", "ticket.autoclosed", "ticket.reopened",
             "ticket.reply")


def _check(template: str) -> None:
    if template not in TEMPLATES:
        raise ValueError(f"неизвестный шаблон письма заявки: {template}")


def short_name(full_name: str) -> str:
    """«Имя Фамилия» из «Фамилия Имя Отчество»: слов два и больше — второе, пробел, первое; одно слово — как есть."""
    words = (full_name or "").split()
    if len(words) >= 2:
        return f"{words[1]} {words[0]}"
    return words[0] if words else ""


def recipients(ticket, template: str) -> tuple[str, list[str]]:
    """Пара (адрес заявителя, копия): подтверждение — без копии, остальные — неснятые участники без адреса заявителя."""
    to = ticket.requester_email
    if template == "ticket.confirmation":
        return to, []
    emails = ticket.participants.filter(removed_at__isnull=True).order_by("id").values_list("email", flat=True)
    return to, [email for email in emails if email.lower() != to.lower()]


def auto_submitted(ticket, template: str) -> str:
    """Значение `Auto-Submitted`: подтверждение заявки из письма — `auto-replied`, ответ исполнителя — пусто."""
    if template == "ticket.reply":
        return ""
    if template == "ticket.confirmation" and ticket.source.system_code == "mail":
        return "auto-replied"
    return "auto-generated"


def subject_of(ticket) -> str:
    """Тема письма: `[#<номер>] <тема заявки без управляющих знаков>`; пустая тема — `[#<номер>]`."""
    subject = mail_parse.clean_subject(ticket.subject)
    return f"[#{ticket.number}] {subject}" if subject else f"[#{ticket.number}]"


def new_message_id() -> str:
    """Свой `Message-ID` с доменом ящика заявок (без ящика — домен адреса `SMTP_FROM`)."""
    address = settings.SERVICEDESK_MAILBOX or parseaddr(settings.DEFAULT_FROM_EMAIL)[1]
    domain = address.rpartition("@")[2] if "@" in address else None
    return make_msgid(domain=domain or None)


def references_of(ticket) -> list[str]:
    """Идентификатор первого элемента `incoming` (его письма) заявителя и предыдущего письма портала по заявке, по порядку, без повторов."""
    from apps.integrations.mail.models import MailMessage

    from ..models import TicketEntry

    found = []
    first = (TicketEntry.objects.filter(ticket=ticket, kind=TicketEntry.Kind.INCOMING)
             .order_by("at", "id").select_related("inbound").first())
    if first is not None and first.inbound is not None and first.inbound.message_id:
        found.append(first.inbound.message_id)
    last = (MailMessage.objects.filter(related_ref=f"ticket:{ticket.pk}").exclude(message_id="")
            .order_by("-id").values_list("message_id", flat=True).first())
    if last and last not in found:
        found.append(last)
    return found


def attachment_ids(entry) -> list[str]:
    """`str(StoredFile.id)` принятых и проверенных (`clean`) вложений элемента `reply`; у прочих элементов — пусто."""
    from ..models import Attachment, TicketEntry

    if entry is None or entry.kind != TicketEntry.Kind.REPLY:
        return []
    ids = (Attachment.objects.filter(entry=entry, file__isnull=False, file__status="clean")
           .order_by("id").values_list("file_id", flat=True))
    return [str(pk) for pk in ids]


def unsent(entry) -> bool:
    """Письмо этого элемента `reply` в состоянии `failed` (маркер «не доставлено» в карточке)."""
    from ..models import TicketEntry

    if entry is None:
        return False
    return TicketEntry.objects.filter(pk=entry.pk, mail__status="failed").exists()


def send(ticket, template: str, *, entry=None, extra=None) -> None:
    """Ставит письмо заявителю после фиксации: получатели и заголовки считаются в момент фиксации.

    `extra` — только ключ `after_hours`; у `ticket.reply` письмо запоминается в `entry.mail` (недоставка находит по
    нему элемент). Неизвестный шаблон — `ValueError`."""
    _check(template)
    after_hours = (extra or {}).get("after_hours")

    def deliver() -> None:
        from ..models import TicketEntry

        to, cc = recipients(ticket, template)
        message = mail_services.send_rendered(
            template, to, subject=subject_of(ticket), cc=cc, reply_to=settings.SERVICEDESK_MAILBOX,
            message_id=new_message_id(), references=" ".join(references_of(ticket)),
            auto_submitted=auto_submitted(ticket, template), related_ref=f"ticket:{ticket.pk}",
            attachments=attachment_ids(entry) if template == "ticket.reply" else [],
            context={"ticket_id": ticket.pk, "entry_id": entry.pk if entry is not None else None,
                     "after_hours": after_hours})
        if template == "ticket.reply" and entry is not None:
            TicketEntry.objects.filter(pk=entry.pk).update(mail=message)

    transaction.on_commit(deliver)


def _text_of(template: str, values: dict) -> str:
    """Текст шаблона `templates/servicedesk/mail/ticket_<вид>.txt` без экранирования."""
    name = f"servicedesk/mail/ticket_{template.partition('.')[2]}.txt"
    return loader.get_template(name).template.render(Context(values, autoescape=False))


def _reply_files(entry) -> list[tuple[str, object]]:
    """Пары (имя, путь) проверенных вложений элемента; недоступные на диске не включаются."""
    from ..models import Attachment

    pairs = []
    rows = (Attachment.objects.filter(entry=entry, file__isnull=False, file__status="clean")
            .select_related("file").order_by("id"))
    for attachment in rows:
        path = files.attachment_path(attachment.file)
        if path.is_file():
            pairs.append((attachment.name, path))
    return pairs


def render(message, context: dict) -> Rendered:
    """Тело письма по `context` (`ticket_id`, `entry_id`, `after_hours`) из базы и вложения `reply` в момент отправки."""
    from ..models import Ticket, TicketEntry
    from . import attachments
    from . import settings as settings_service

    template = message.template
    _check(template)
    ticket = Ticket.objects.select_related("assignee").get(pk=context["ticket_id"])
    entry = TicketEntry.objects.select_related("author").filter(pk=context.get("entry_id")).first()
    values = {"number": ticket.number}
    pairs: list[tuple[str, object]] = []
    if template == "ticket.confirmation":
        first = (TicketEntry.objects.filter(ticket=ticket, kind=TicketEntry.Kind.INCOMING)
                 .order_by("at", "id").first())
        rejected = attachments.rejected_of(entry or first) if (entry or first) is not None else []
        values.update(
            greeting_name=ticket.requester_name or ticket.requester_email, subject=ticket.subject,
            text=first.text if first is not None else "",
            rejected=[(item.name, item.REJECT_TITLES[item.rejected]) for item in rejected],
            assignee_name=short_name(ticket.assignee.full_name) if ticket.assignee_id else "",
            after_hours=context.get("after_hours"))
    elif template == "ticket.assigned":
        values["assignee_name"] = short_name(ticket.assignee.full_name) if ticket.assignee_id else ""
    elif template in ("ticket.closed", "ticket.autoclosed"):
        configured = settings_service.get()
        values.update(resolution=ticket.resolution, autoclose_days=configured.autoclose_days,
                      reopen_days=configured.reopen_days)
    elif template == "ticket.reply":
        author = entry.author if entry is not None else None
        values.update(text=entry.text if entry is not None else "",
                      signature=short_name(author.full_name) if author is not None else "")
        if entry is not None:
            pairs = _reply_files(entry)
    return Rendered(body=_text_of(template, values), attachments=pairs)


def renderers() -> list[MailRenderer]:
    """Точка `mail_renderers`: один рендерер на префикс `ticket.`."""
    return [MailRenderer(prefix="ticket.", render=render)]
