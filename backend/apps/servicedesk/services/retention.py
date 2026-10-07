"""Публичный интерфейс сервис-деска: сроки хранения (PLAN-003, «Хранение и обезличивание»; CONTRACT-003, 6.24).

Закрытые заявки обезличиваются по одной, каждая в своей транзакции; письма без заявки и файлы-сироты чистятся
порциями. Файлы стираются после фиксации (`on_commit`), отсутствующий файл не ошибка.
"""
import logging
import os
import pathlib
import time
from datetime import timedelta

from django.conf import settings as django_settings
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.core.services import audit, files
from apps.integrations.mail import services as mail_services

from ..models import Attachment, InboundMail, RequesterImport, Ticket, TicketEntry, TicketParticipant
from . import requesters, search
from . import settings as sd_settings
from .errors import Batch

logger = logging.getLogger(__name__)

ANONYMIZED = "обезличено"
ORPHAN_MIN_AGE = 3600  # файлы моложе часа не трогаем (опрос и чистка идут в разных процессах)
PREVIEW_TTL = timedelta(days=1)

# Ключи `data` событий ленты, которые несут тексты или имена файлов
EVENT_TEXT_KEYS = {
    "transferred": ("reason_text",),
    "attachment_rejected": ("name",),
    "attachment_quarantined": ("name",),
    "reply_not_sent": ("name",),
}


def _border(years: int):
    """Граница срока: «столько-то лет назад» от текущего времени; 29 февраля без такой даты — 28 февраля."""
    now = timezone.now()
    try:
        return now.replace(year=now.year - years)
    except ValueError:
        return now.replace(year=now.year - years, day=28)


def _selection(border):
    """Заявки, подлежащие обезличиванию."""
    return Ticket.objects.filter(kind="closed", anonymized_at__isnull=True, closed_at__lt=border)


def anonymize_batch(*, size=50, done_total=0, nightly_limit=2000, after=None) -> Batch:
    """Одна порция обезличивания: до `size` заявок по (`closed_at`, `id`) строго после курсора `after`."""
    border = _border(sd_settings.get().retention_years)
    queryset = _selection(border)
    if after is not None:
        closed_at, pk = after
        queryset = queryset.filter(Q(closed_at__gt=closed_at) | Q(closed_at=closed_at, pk__gt=pk))
    chosen = list(queryset.order_by("closed_at", "pk").values_list("pk", "closed_at")[:size])
    done = 0
    for pk, _closed_at in chosen:
        try:
            if anonymize_one(pk):
                done += 1
        except Exception:
            logger.exception("Обезличивание заявки %s не удалось", pk)
    last = (chosen[-1][1], chosen[-1][0]) if chosen else None
    more = len(chosen) == size and done_total + done < nightly_limit
    return Batch(done=done, more=more, last_id=chosen[-1][0] if chosen else None, last=last)


def anonymize_one(ticket_id) -> bool:
    """Обезличивает одну заявку по семи шагам плана; `False` — отбор уже не выполняется."""
    paths = []
    with transaction.atomic():
        ticket = Ticket.objects.select_for_update().filter(pk=ticket_id).first()
        border = _border(sd_settings.get().retention_years)
        if (ticket is None or ticket.kind != "closed" or ticket.anonymized_at is not None
                or ticket.closed_at is None or ticket.closed_at >= border):
            return False
        requester = ticket.requester
        # 1. тексты ленты, авторы-заявители, тексты и имена файлов в данных событий
        entries = TicketEntry.objects.filter(ticket=ticket)
        entries.filter(kind__in=["incoming", "reply", "comment"]).update(text="")
        entries.filter(kind="incoming").update(author_email=ANONYMIZED, author_name=ANONYMIZED)
        entries.filter(kind__in=["reply", "comment"], author__isnull=True).exclude(
            author_email="", author_name="").update(author_email=ANONYMIZED, author_name=ANONYMIZED)
        for entry in entries.filter(kind="event", event__in=list(EVENT_TEXT_KEYS)):
            keys = [key for key in EVENT_TEXT_KEYS[entry.event] if key in entry.data]
            if keys:
                entry.data = {key: value for key, value in entry.data.items() if key not in keys}
                entry.save(update_fields=["data"])
        # 2. вложения: пути — до удаления строк
        attachments = list(Attachment.objects.filter(ticket=ticket).select_related("file"))
        stored = {item.file_id: item.file for item in attachments if item.file is not None}
        paths.extend(files.attachment_path(item) for item in stored.values())
        Attachment.objects.filter(ticket=ticket).delete()
        for item in stored.values():
            item.delete()
        # 3. входящие письма заявки
        mails = InboundMail.objects.filter(ticket=ticket)
        root = pathlib.Path(django_settings.PROTECTED_ROOT) / "inbound"
        paths.extend(root / f"{pk}.eml" for pk in mails.values_list("pk", flat=True))
        mails.update(raw_deleted=True, from_email="", subject="", message_id="")
        # 4. журнал доставки
        mail_services.anonymize_related(f"ticket:{ticket.pk}")
        # 5. участники из копии
        TicketParticipant.objects.filter(ticket=ticket).delete()
        # 6. заявка; столбец `search` пересобирается отдельно, полным `save()` его не затираем
        now = timezone.now()
        Ticket.objects.filter(pk=ticket.pk).update(requester_email=ANONYMIZED, requester_name=ANONYMIZED,
                                                   requester=None, anonymized_at=now)
        ticket.refresh_from_db()
        search.rebuild(ticket, anonymized=True)
        audit.record("ticket.anonymized", actor=None, object_type="ticket", object_id=ticket.number,
                     before={}, after={"number": ticket.number})
        # 7. общая запись заявителя
        if requester is not None:
            requesters.delete_if_orphan(requester, reason="срок хранения")
        transaction.on_commit(lambda: files.remove_paths(paths))
    return True


def purge_inbound(*, size=50, after=None) -> Batch:
    """Чистит письма без заявки старше `inbound_retention_days`: файл, отправитель, тема, `message_id`."""
    border = timezone.now() - timedelta(days=sd_settings.get().inbound_retention_days)
    queryset = InboundMail.objects.filter(ticket__isnull=True, raw_deleted=False, received_at__lt=border)
    if after is not None:
        received_at, pk = after
        queryset = queryset.filter(Q(received_at__gt=received_at) | Q(received_at=received_at, pk__gt=pk))
    chosen = list(queryset.order_by("received_at", "pk").values_list("pk", "received_at")[:size])
    root = pathlib.Path(django_settings.PROTECTED_ROOT) / "inbound"
    done = 0
    for pk, _received_at in chosen:
        try:
            with transaction.atomic():
                updated = InboundMail.objects.filter(pk=pk, ticket__isnull=True, raw_deleted=False).update(
                    raw_deleted=True, from_email="", subject="", message_id="")
                if updated == 1:
                    transaction.on_commit(lambda path=root / f"{pk}.eml": files.remove_paths([path]))
            if updated == 1:
                done += 1
        except Exception:
            logger.exception("Чистка входящего письма %s не удалась", pk)
    last = (chosen[-1][1], chosen[-1][0]) if chosen else None
    return Batch(done=done, more=len(chosen) == size, last_id=chosen[-1][0] if chosen else None, last=last)


def purge_orphan_files(*, size=50, after="") -> Batch:
    """Стирает файлы `inbound/<id>.eml` без строки или со строкой `raw_deleted`; порция — до `size` имён каталога."""
    root = pathlib.Path(django_settings.PROTECTED_ROOT) / "inbound"
    try:
        names = sorted(name for name in os.listdir(root) if name > after)[:size]
    except FileNotFoundError:
        names = []
    done = 0
    for name in names:
        path = root / name
        stem, dot, extension = name.rpartition(".")
        if not dot or extension != "eml" or not (stem.isascii() and stem.isdigit()):
            continue
        try:
            if time.time() - path.stat().st_mtime < ORPHAN_MIN_AGE:
                continue
            if InboundMail.objects.filter(pk=int(stem), raw_deleted=False).exists():
                continue
            files.remove_paths([path])
            done += 1
        except FileNotFoundError:
            continue
        except Exception:
            logger.exception("Чистка файла %s не удалась", name)
    return Batch(done=done, more=len(names) == size, last=names[-1] if names else None)


def purge_requester_previews() -> int:
    """Удаляет неподтверждённые загрузки заявителей старше суток; возвращает число."""
    border = timezone.now() - PREVIEW_TTL
    deleted, _ = RequesterImport.objects.filter(state=RequesterImport.State.PREVIEW, created_at__lt=border).delete()
    return deleted
