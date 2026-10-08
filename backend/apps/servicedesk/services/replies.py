"""Публичный интерфейс сервис-деска: ответы по заявке (PLAN-003, «Где живёт код»)."""
from dataclasses import dataclass

from django.db import transaction
from django.db.models import Exists, OuterRef
from django.utils import timezone

from apps.core.services import audit
from apps.integrations.mail.models import MailMessage

from ..models import Attachment, Status, Ticket, TicketEntry, TicketParticipant
from . import access, attachments, dictionaries, letters, search, tickets
from .errors import ServiceDeskError

MAX_TEXT = 50_000
CLOSED_TEXT = "Заявка закрыта: сначала откройте её"


@dataclass(frozen=True)
class FeedItem:
    """Элемент ленты с подготовленным автором (6.10): `author_kind` — `staff`, `requester`, `participant`, `system`."""

    entry: TicketEntry
    author_name: str
    author_kind: str
    author_dismissed: bool
    author_address: str
    mail_status: str
    resent: bool = False


def add_event(ticket, event, *, actor=None, data=None):
    """Дописать в ленту событие (6.10): единственная точка записи событий для всех модулей.

    `actor=None` — событие системы. Время — «сейчас» (по умолчанию модели), `last_message_*`
    заявки не меняются, журнал пишет вызывающая служба. Код события не проверяется.
    """
    with transaction.atomic():
        return TicketEntry.objects.create(
            ticket=ticket, kind=TicketEntry.Kind.EVENT, event=event, author=actor, data=data or {},
        )


def _error(code: str, message: str) -> ServiceDeskError:
    return ServiceDeskError(code, message)


def _lock(ticket) -> None:
    """Блокирует строку заявки и перечитывает состояние объекта (6.1)."""
    Ticket.objects.select_for_update().filter(pk=ticket.pk).first()
    ticket.refresh_from_db()


def _guard(ticket, actor, *, closed_ok: bool = False) -> None:
    """Порядок проверок 6.1: `no_access`, затем `ticket_closed` (у комментария закрытая заявка допустима)."""
    if not access.can_work(actor, ticket):
        raise _error("no_access", "нет доступа")
    if not closed_ok and ticket.kind == Status.Kind.CLOSED:
        raise _error("ticket_closed", CLOSED_TEXT)


def _check_text(text: str) -> None:
    """Текст после обрезки: не пустой и не длиннее 50 000 знаков (дополнение 29)."""
    if not text:
        raise _error("text_required", "Введите текст")
    if len(text) > MAX_TEXT:
        raise _error("text_too_long", "Текст ответа не длиннее 50 000 знаков")


def _move_status(ticket, wait_flag: bool, actor, ip) -> None:
    """Смена статуса ответом по FR-208: с флажком — «ждёт» по умолчанию, без — «новая» и «ждёт» уходят «в работу»."""
    if wait_flag:
        tickets.set_status(ticket, dictionaries.default_status(Status.Kind.WAITING), actor=actor, reason="reply",
                           ip=ip, start_countdown=False)
    elif ticket.kind in (Status.Kind.NEW, Status.Kind.WAITING):
        tickets.set_status(ticket, dictionaries.default_status(Status.Kind.IN_PROGRESS), actor=actor, reason="reply",
                           ip=ip)


def _queue_letter(ticket, entry) -> None:
    """Ответ уходит: `queued`, отсчёт ожидания (флажок и вид «ждёт»), письмо после фиксации."""
    entry.send_state = TicketEntry.SendState.QUEUED
    entry.save(update_fields=["send_state"])
    if entry.wait_flag and ticket.kind == Status.Kind.WAITING:
        ticket.waiting_since = timezone.now()
        ticket.save(update_fields=["waiting_since", "updated_at"])
    letters.send(ticket, "ticket.reply", entry=entry)


def _dispatch(ticket, entry, actor, ip, *, parts=()) -> None:
    """Общий конец `reply` и `resend`: вложения, статус, последнее сообщение, отправка или ожидание файлов, журнал."""
    attachments.accept(entry, parts)
    _move_status(ticket, entry.wait_flag, actor, ip)
    ticket.last_message_at = entry.at
    ticket.last_message_from = Ticket.MessageFrom.STAFF
    ticket.save(update_fields=["last_message_at", "last_message_from", "updated_at"])
    if attachments.pending_for(entry):
        entry.send_state = TicketEntry.SendState.WAITING_FILES
        entry.save(update_fields=["send_state"])
    else:
        _queue_letter(ticket, entry)
    audit.record("ticket.reply_sent", actor=actor, object_type="ticket", object_id=ticket.number, before={},
                 after={"entry_id": entry.pk}, ip=ip)
    search.index(ticket, entry)


def reply(ticket, *, text, parts=(), wait_flag=False, actor, ip=None):
    """Ответ исполнителя заявителю (6.10): одна транзакция; письмо уходит после фиксации и проверки файлов."""
    text = (text or "").strip()
    with transaction.atomic():
        _lock(ticket)
        _guard(ticket, actor)
        _check_text(text)
        entry = TicketEntry.objects.create(ticket=ticket, kind=TicketEntry.Kind.REPLY, author=actor, text=text,
                                           wait_flag=bool(wait_flag))
        _dispatch(ticket, entry, actor, ip, parts=list(parts))
    return entry


def resend(entry, *, actor, ip=None):
    """«Отправить заново без заражённых вложений»: новый `reply` с тем же текстом и чистыми файлами (6.10)."""
    with transaction.atomic():
        old = TicketEntry.objects.select_related("ticket").get(pk=entry.pk)
        ticket = old.ticket
        _lock(ticket)
        _guard(ticket, actor)
        old = TicketEntry.objects.select_for_update().get(pk=old.pk)
        if (old.kind != TicketEntry.Kind.REPLY or old.send_state != TicketEntry.SendState.NOT_SENT
                or old.resends.exists()):
            raise _error("not_resendable", "Отправить заново можно только неотправленный ответ")
        new = TicketEntry.objects.create(ticket=ticket, kind=TicketEntry.Kind.REPLY, author=actor, text=old.text,
                                         wait_flag=old.wait_flag, resent_from=old)
        for item in Attachment.objects.filter(entry=old, file__status="clean").order_by("id"):
            Attachment.objects.create(ticket=ticket, entry=new, file=item.file, name=item.name, size=item.size,
                                      inline=item.inline)
        _dispatch(ticket, new, actor, ip)
    return new


def comment(ticket, *, text, actor, ip=None):
    """Внутренний комментарий (6.10): без письма и вложений, работает и на закрытой заявке."""
    text = (text or "").strip()
    with transaction.atomic():
        _lock(ticket)
        _guard(ticket, actor, closed_ok=True)
        _check_text(text)
        entry = TicketEntry.objects.create(ticket=ticket, kind=TicketEntry.Kind.COMMENT, author=actor, text=text)
        audit.record("ticket.comment_added", actor=actor, object_type="ticket", object_id=ticket.number, before={},
                     after={"entry_id": entry.pk}, ip=ip)
        search.index(ticket, entry)
    return entry


def _not_sent(entry, ticket, reason: str, **extra) -> None:
    entry.send_state = TicketEntry.SendState.NOT_SENT
    entry.save(update_fields=["send_state"])
    add_event(ticket, "reply_not_sent", data={"reason": reason, "entry_id": entry.pk, **extra})


def on_files_checked(entry_id):
    """Проверен последний файл ответа: отправить его или пометить `not_sent` с событием ленты (6.10)."""
    with transaction.atomic():
        ticket_id = (TicketEntry.objects.filter(pk=entry_id, kind=TicketEntry.Kind.REPLY)
                     .values_list("ticket_id", flat=True).first())
        if ticket_id is None:
            return
        ticket = Ticket.objects.select_for_update().get(pk=ticket_id)
        entry = TicketEntry.objects.select_for_update().filter(pk=entry_id, kind=TicketEntry.Kind.REPLY).first()
        if entry is None or entry.send_state != TicketEntry.SendState.WAITING_FILES:
            return
        if ticket.kind == Status.Kind.CLOSED:
            _not_sent(entry, ticket, "ticket_closed")
            return
        bad = (Attachment.objects.filter(entry=entry).select_related("file").order_by("id"))
        for item in bad:
            if item.rejected == Attachment.Rejected.ENCRYPTED:
                _not_sent(entry, ticket, "encrypted", name=item.name)
                return
            if item.file is not None and item.file.status == "quarantine":
                _not_sent(entry, ticket, "quarantine", name=item.name)
                return
        _queue_letter(ticket, entry)


def on_mail_failed(*, mail_id, related_ref):
    """Недоставка письма заявки после последней попытки: событие ленты и журнал (подписчик `mail.failed`)."""
    kind, _, number = (related_ref or "").partition(":")
    if kind != "ticket" or not number.isdigit():
        return
    ticket = Ticket.objects.filter(pk=int(number)).first()
    message = MailMessage.objects.filter(pk=mail_id).first()
    if ticket is None or message is None:
        return
    mail_kind = message.template.partition(".")[2]
    data = {"mail_kind": mail_kind}
    with transaction.atomic():
        entry = TicketEntry.objects.filter(ticket=ticket, mail_id=mail_id).first()
        if entry is not None:
            data["entry_id"] = entry.pk
        add_event(ticket, "mail_failed", data=data)
        audit.record("ticket.mail_failed", actor=None, object_type="ticket", object_id=ticket.number, before={},
                     after={"mail_kind": mail_kind})


def feed(ticket) -> list[FeedItem]:
    """Лента заявки по `(at, id)`: не больше двух запросов (записи с автором, письмом и признаком участника; вложения)."""
    is_participant = TicketParticipant.objects.filter(ticket_id=OuterRef("ticket_id"),
                                                      email__iexact=OuterRef("author_email"))
    rows = (TicketEntry.objects.filter(ticket=ticket).select_related("author", "mail")
            .prefetch_related("attachments").annotate(from_participant=Exists(is_participant),
                                          was_resent=Exists(TicketEntry.objects.filter(resent_from_id=OuterRef("pk"))))
            .order_by("at", "id"))
    items = []
    for entry in rows:
        dismissed = False
        address = ""
        if entry.author is not None:
            kind, name, dismissed = "staff", entry.author.full_name, entry.author.state == "dismissed"
        elif entry.kind == TicketEntry.Kind.INCOMING:
            kind = "participant" if entry.from_participant else "requester"
            name, address = entry.author_name, entry.author_email
        else:
            kind, name = "system", ""
        status = entry.mail.status if entry.kind == TicketEntry.Kind.REPLY and entry.mail is not None else ""
        items.append(FeedItem(entry=entry, author_name=name, author_kind=kind, author_dismissed=dismissed,
                              author_address=address, mail_status=status, resent=entry.was_resent))
    return items
