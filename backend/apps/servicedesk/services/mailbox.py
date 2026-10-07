"""Публичный интерфейс сервис-деска: опрос почтового ящика (PLAN-003, «Где живёт код»; CONTRACT-003, 6.15).

`poll` — один запуск задания `poll_mailbox`: замок в Valkey, соединение только через `imap.connect()` (имя модуля, чтобы
работала подмена), первое подключение, пересоздание ящика или обычный порядок; не больше `PER_RUN` скачиваний за запуск.
`store` пишет строку письма, файл и `last_uid` одной транзакцией; разбор ставится после фиксации (`intake.enqueue`).
Портал письма не помечает и не удаляет: ящик открыт только для чтения.
"""
import datetime
import logging
import os
import pathlib
import secrets
from dataclasses import dataclass

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.services import audit, valkey
from apps.integrations.mail import imap
from apps.integrations.mail import tasks as mail_tasks

from ..models import InboundMail, MailboxState
from . import intake, mail_parse

logger = logging.getLogger(__name__)

LOCK_KEY = "servicedesk:poll"
LOCK_TTL = 120
PER_RUN = 20
RECREATE_WINDOW_MINUTES = 10
REQUEUE_AFTER_MINUTES = 3

# Продление и снятие замка — только со своим значением, одной операцией на стороне Valkey.
_EXTEND_SCRIPT = ("if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('expire', KEYS[1], ARGV[2]) "
                  "else return 0 end")
_RELEASE_SCRIPT = ("if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) "
                   "else return 0 end")


@dataclass(frozen=True)
class PollResult:
    """Итог запуска: `ok`, `disabled` (`IMAP_HOST` пуст), `locked` (замок занят) или `unavailable` (ошибка ящика)."""

    state: str
    fetched: int = 0
    known: int = 0


@dataclass(frozen=True)
class MailboxStatus:
    """Состояние ящика для верха страницы «Входящие письма»."""

    address: str
    last_ok_at: object
    last_poll_at: object
    last_error: str
    configured: bool
    connected: bool


class _Counters:
    """Счётчики запуска: нужны и при ошибке посреди запуска."""

    def __init__(self):
        self.fetched = 0
        self.known = 0


def _extend_lock(token: str) -> None:
    valkey.conn().eval(_EXTEND_SCRIPT, 1, LOCK_KEY, token, LOCK_TTL)


def _release_lock(token: str) -> None:
    valkey.conn().eval(_RELEASE_SCRIPT, 1, LOCK_KEY, token)


def poll() -> PollResult:
    """Один запуск опроса (6.15); ошибки ящика наружу не идут: они попадают в `last_error` и в итог."""
    if not settings.IMAP_HOST:
        return PollResult("disabled")
    token = secrets.token_urlsafe()
    if not valkey.conn().set(LOCK_KEY, token, nx=True, ex=LOCK_TTL):
        return PollResult("locked")
    counters = _Counters()
    try:
        try:
            return _run(token, counters)
        except (imap.MailboxUnavailable, OSError) as exc:
            text = mail_tasks.safe_error(exc)
            logger.warning("Опрос ящика заявок: %s", text)
            _record_error(text)
            return PollResult("unavailable", fetched=counters.fetched, known=counters.known)
    finally:
        _release_lock(token)


def _record_error(text: str) -> None:
    """Ошибка опроса: строка состояния создаётся при первой же ошибке (`uidvalidity` и `last_uid` пусты)."""
    MailboxState.objects.update_or_create(pk=1, defaults={"last_error": text, "last_poll_at": timezone.now()})


def _run(token: str, counters: _Counters) -> PollResult:
    state = MailboxState.objects.filter(pk=1).first()
    last_ok_before = state.last_ok_at if state is not None else None
    with imap.connect() as conn:
        if state is None or state.uidvalidity is None:
            _first_connect(conn)
            return PollResult("ok")
        last_uid = state.last_uid or 0
        if state.uidvalidity != conn.uidvalidity:
            last_uid = _recreated(conn, state, last_ok_before)
        _take_new(conn, last_uid, token, counters)
    now = timezone.now()
    MailboxState.objects.filter(pk=1).update(last_poll_at=now, last_ok_at=now, last_error="")
    return PollResult("ok", fetched=counters.fetched, known=counters.known)


def _first_connect(conn) -> None:
    """Первое подключение: запомнить UIDVALIDITY и `UIDNEXT − 1`; письма, лежащие в ящике, не разбираются (FR-211)."""
    now = timezone.now()
    last_uid = int(conn.uidnext) - 1
    with transaction.atomic():
        MailboxState.objects.update_or_create(pk=1, defaults={
            "uidvalidity": int(conn.uidvalidity), "last_uid": last_uid, "connected_at": now,
            "last_poll_at": now, "last_ok_at": now, "last_error": ""})
        audit.record("mailbox.connected", object_type="mailbox", object_id="1", before={},
                     after={"uidvalidity": int(conn.uidvalidity), "last_uid": last_uid})


def _recreated(conn, state, last_ok_at) -> int:
    """Ящик пересоздан: отбор писем окна, новый `last_uid` и журнал; возвращает `last_uid` для обычного порядка."""
    selected: list[int] = []
    skipped = 0
    if last_ok_at is not None:
        day = (last_ok_at - datetime.timedelta(days=1)).astimezone(datetime.timezone.utc).date()
        border = last_ok_at - datetime.timedelta(minutes=RECREATE_WINDOW_MINUTES)
        for uid in conn.search_since(day):
            head = conn.head(uid)
            if head.internal_date < border:
                continue
            if head.message_id and InboundMail.objects.filter(message_id=head.message_id).exists():
                skipped += 1
                continue
            selected.append(uid)
    last_uid = min(selected) - 1 if selected else int(conn.uidnext) - 1
    with transaction.atomic():
        MailboxState.objects.filter(pk=1).update(uidvalidity=int(conn.uidvalidity), last_uid=last_uid)
        audit.record("mailbox.recreated", object_type="mailbox", object_id="1",
                     before={"uidvalidity": int(state.uidvalidity)},
                     after={"uidvalidity": int(conn.uidvalidity), "skipped": skipped})
    return last_uid


def _take_new(conn, last_uid: int, token: str, counters: _Counters) -> None:
    """Обычный порядок: `UID last_uid+1:*`, фильтр `uid > last_uid` — здесь; известные пары лишь двигают `last_uid`."""
    uidvalidity = int(conn.uidvalidity)
    for uid in sorted(u for u in conn.search_uids(last_uid + 1) if u > last_uid):
        if InboundMail.objects.filter(uidvalidity=uidvalidity, uid=uid).exists():
            MailboxState.objects.filter(pk=1).update(last_uid=uid)
            counters.known += 1
            continue
        if counters.fetched >= PER_RUN:
            break
        store(conn.fetch(uid), uidvalidity)
        counters.fetched += 1
        _extend_lock(token)


def store(fetched, uidvalidity) -> InboundMail:
    """Строка письма, файл и `last_uid` — одна транзакция; разбор — после фиксации. `OSError` откатывает всё."""
    with transaction.atomic():
        message_id, from_email, subject = headers_of(fetched.raw)
        row = InboundMail.objects.create(
            uidvalidity=uidvalidity, uid=fetched.uid, message_id=message_id, internal_date=fetched.internal_date,
            received_at=timezone.now(), size=fetched.size, from_email=from_email, subject=subject)
        write_raw(pathlib.Path(settings.PROTECTED_ROOT) / "inbound" / f"{row.pk}.eml", fetched.raw)
        MailboxState.objects.filter(pk=1).update(last_uid=fetched.uid)
        intake.enqueue(row.pk)
    return row


def write_raw(path, data) -> None:
    """Пишет байты письма во временный файл рядом и переименовывает; каталог создаётся (точка подмены в тестах)."""
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise


def headers_of(raw) -> tuple[str, str, str]:
    """(`Message-ID`, отправитель строчными, тема) из заголовков; любая ошибка — три пустые строки."""
    try:
        message = mail_parse.load(raw)
        message_id = " ".join(str(message.get("Message-ID") or "").split())[:255]
        from_email = mail_parse.sender_of(message)[0][:254]
        subject = mail_parse.clean_subject(message.get("Subject") or "")
        return message_id, from_email, subject
    except Exception:
        return "", "", ""


def status() -> MailboxStatus:
    """Состояние ящика; работает и без строки `MailboxState`."""
    state = MailboxState.objects.filter(pk=1).first()
    return MailboxStatus(
        address=settings.SERVICEDESK_MAILBOX,
        last_ok_at=state.last_ok_at if state else None,
        last_poll_at=state.last_poll_at if state else None,
        last_error=state.last_error if state else "",
        configured=bool(settings.IMAP_HOST),
        connected=state is not None and state.uidvalidity is not None)


def reparse(inbound_id, *, actor, ip=None) -> bool:
    """Письмо в `error` — ставит разбор и `True`; иное состояние — `False`, ничего не меняется. Права — у маршрута."""
    row = InboundMail.objects.get(pk=inbound_id)
    if row.status != InboundMail.Status.ERROR:
        return False
    intake.enqueue(row.pk)
    return True


def requeue_inbound() -> int:
    """Письма в `received` старше `REQUEUE_AFTER_MINUTES` без задания разбора получают его; возвращает их число."""
    border = timezone.now() - datetime.timedelta(minutes=REQUEUE_AFTER_MINUTES)
    count = 0
    for inbound_id in InboundMail.objects.filter(status=InboundMail.Status.RECEIVED, received_at__lt=border
                                                 ).order_by("id").values_list("id", flat=True):
        if not intake.has_job(inbound_id):
            intake.enqueue(inbound_id)
            count += 1
    return count
