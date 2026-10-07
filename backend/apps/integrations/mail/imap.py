"""IMAP-адаптер ящика заявок сервис-деска (T-3207, PLAN-003, «Опрос ящика»; CONTRACT-003, 5.1).

`connect()` — фабрика соединения и точка подмены в тестах: служба опроса зовёт её как `imap.connect()`.
Ящик открывается только для чтения (`EXAMINE`): адаптер не помечает и не удаляет письма, методов `store`,
`copy`, `expunge`, `append` у соединения нет. Настройки `IMAP_*` читаются при каждом `connect()`.
Ошибки `imaplib`, сокета и TLS становятся `MailboxUnavailable` с текстом без пароля (`tasks.safe_error`).
"""
import datetime
import email.utils
import imaplib
import re
import ssl
from email.parser import BytesHeaderParser
from typing import NamedTuple

from django.conf import settings

MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

_SIZE = re.compile(rb"RFC822\.SIZE\s+(\d+)", re.IGNORECASE)
_INTERNALDATE = re.compile(rb'INTERNALDATE\s+"\s*(\d{1,2})-([A-Za-z]{3})-(\d{4}\s+\d{2}:\d{2}:\d{2}\s+[+-]\d{4})\s*"',
                           re.IGNORECASE)

_ERRORS = (imaplib.IMAP4.error, OSError, ssl.SSLError)


class MailboxUnavailable(Exception):
    """Ящик недоступен; `str(exc)` — текст после `tasks.safe_error` (без пароля)."""


class FetchedMail(NamedTuple):
    uid: int
    size: int                        # RFC822.SIZE
    internal_date: datetime.datetime  # с часовым поясом, UTC
    raw: bytes                       # BODY.PEEK[] целиком


class MailHead(NamedTuple):
    uid: int
    internal_date: datetime.datetime  # с часовым поясом, UTC
    message_id: str                  # "" — заголовка нет
    size: int                        # RFC822.SIZE


def _unavailable(exc: BaseException) -> MailboxUnavailable:
    """Оборачивает исключение; `tasks` импортируется лениво: он при загрузке может вызвать `django.setup()`."""
    from apps.integrations.mail import tasks

    return MailboxUnavailable(tasks.safe_error(exc))


def _to_int(value) -> int | None:
    if isinstance(value, (list, tuple)):
        value = value[0] if value else None
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def connect() -> "MailboxConnection":
    """Соединяется с ящиком по `IMAP_SECURITY`, входит и открывает папку только для чтения."""
    host, port = settings.IMAP_HOST, settings.IMAP_PORT
    security, timeout = settings.IMAP_SECURITY, settings.IMAP_TIMEOUT
    if security not in ("ssl", "starttls", "none"):
        raise MailboxUnavailable(f"MailboxUnavailable: неизвестный режим IMAP_SECURITY: {security!r}")

    client = None
    try:
        if security == "ssl":
            client = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=timeout)
        else:
            client = imaplib.IMAP4(host, port, timeout=timeout)
            if security == "starttls":
                client.starttls(ssl_context=ssl.create_default_context())
        client.login(settings.IMAP_USER, settings.IMAP_PASSWORD)
        status, _data = client.select(settings.IMAP_FOLDER, readonly=True)
        if status != "OK":
            raise MailboxUnavailable("MailboxUnavailable: папка не открылась")
        uidvalidity = _to_int(client.response("UIDVALIDITY")[1])
        uidnext = _to_int(client.response("UIDNEXT")[1])
        if uidvalidity is None or uidnext is None:
            raise MailboxUnavailable("MailboxUnavailable: сервер не сообщил UIDVALIDITY или UIDNEXT")
    except MailboxUnavailable:
        _quiet_logout(client)
        raise
    except _ERRORS as exc:
        _quiet_logout(client)
        raise _unavailable(exc) from exc
    return MailboxConnection(client, uidvalidity, uidnext)


def _quiet_logout(client) -> None:
    if client is None:
        return
    try:
        client.logout()
    except Exception:  # соединение и так сломано
        pass


class MailboxConnection:
    """Соединение с ящиком; контекстный менеджер. Только чтение."""

    def __init__(self, client, uidvalidity: int, uidnext: int):
        self._client = client
        self.uidvalidity = uidvalidity
        self.uidnext = uidnext

    def __enter__(self) -> "MailboxConnection":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()

    def _uid(self, command: str, *args):
        if self._client is None:
            raise MailboxUnavailable("MailboxUnavailable: соединение закрыто")
        try:
            status, data = self._client.uid(command, *args)
        except _ERRORS as exc:
            raise _unavailable(exc) from exc
        if status != "OK":
            raise MailboxUnavailable(f"MailboxUnavailable: команда UID {command} отклонена ({status})")
        return data

    @staticmethod
    def _numbers(data) -> list[int]:
        raw = b" ".join(item for item in data if isinstance(item, bytes))
        return sorted(int(n) for n in raw.split())

    def search_uids(self, first_uid: int) -> list[int]:
        """`UID SEARCH UID <first>:*` как отвечает сервер, без фильтрации; по возрастанию."""
        return self._numbers(self._uid("SEARCH", "UID", f"{int(first_uid)}:*"))

    def search_since(self, day: datetime.date) -> list[int]:
        """`UID SEARCH SINCE дд-Мес-гггг`; месяц — английское сокращение независимо от языка системы."""
        text = f"{day.day:02d}-{MONTHS[day.month - 1]}-{day.year:04d}"
        return self._numbers(self._uid("SEARCH", "SINCE", text))

    @staticmethod
    def _parse(data, uid: int) -> tuple[int, datetime.datetime, bytes]:
        """Размер, дата и литерал из ответа `FETCH`: атрибуты — по именам, а не по позициям."""
        meta = b""
        literal = b""
        for item in data or []:
            if isinstance(item, tuple):
                meta += item[0] + b" "
                if len(item) > 1 and isinstance(item[1], bytes):
                    literal = item[1]
            elif isinstance(item, bytes):
                meta += item + b" "
        size, date = _SIZE.search(meta), _INTERNALDATE.search(meta)
        if not size or not date:
            raise MailboxUnavailable(f"MailboxUnavailable: письма с UID {uid} нет в ящике")
        text = f"{date.group(1).decode()} {date.group(2).decode()} {date.group(3).decode()}"
        try:
            when = email.utils.parsedate_to_datetime(text).astimezone(datetime.timezone.utc)
        except (ValueError, TypeError):
            raise MailboxUnavailable(f"MailboxUnavailable: у письма с UID {uid} не разобрана дата INTERNALDATE") from None
        return int(size.group(1)), when, literal

    def fetch(self, uid: int) -> FetchedMail:
        """Письмо целиком (`BODY.PEEK[]`: признак «прочитано» не ставится)."""
        data = self._uid("FETCH", str(int(uid)), "(RFC822.SIZE INTERNALDATE BODY.PEEK[])")
        size, when, raw = self._parse(data, uid)
        return FetchedMail(uid=int(uid), size=size, internal_date=when, raw=raw)

    def head(self, uid: int) -> MailHead:
        """Дата, размер и `Message-ID` письма; тело не скачивается."""
        data = self._uid("FETCH", str(int(uid)),
                         "(INTERNALDATE RFC822.SIZE BODY.PEEK[HEADER.FIELDS (MESSAGE-ID)])")
        size, when, literal = self._parse(data, uid)
        value = BytesHeaderParser().parsebytes(literal).get("Message-ID")
        return MailHead(uid=int(uid), internal_date=when, message_id=" ".join(str(value or "").split()), size=size)

    def close(self) -> None:
        """Выход из соединения; повторный вызов безвреден."""
        client, self._client = self._client, None
        _quiet_logout(client)
