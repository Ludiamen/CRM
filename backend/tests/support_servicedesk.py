"""Общие помощники тестов среза 003 (T-3100, вторая половина).

Имена и поведение — `tests/CONTRACT-003.md` (разделы 1, 3.1, 3.4, 3.5, 5.2, 10). Кода среза 003
ещё нет, поэтому на уровне модуля здесь нет импортов из `apps.servicedesk`, `apps.core.events`
и `apps.integrations.mail.imap`: модели берутся лениво (`support.model("servicedesk.Ticket")`),
остальное — внутри функций. Сбор тестов (`pytest --collect-only`) проходит до появления кода;
вызов того, чего ещё нет, падает понятной ошибкой.

Пароли — только `secrets.token_urlsafe()` или из окружения (`IMAP_PASSWORD`); в текстах ошибок
пароль заменяется на `***`. EICAR берётся из `support_org` (собирается из частей).

Фикстуры `bus`, `bus_spy`, `fake_mailbox`, `live_mailbox` подключены в `tests/conftest.py`.
"""
import email
import email.policy
import imaplib
import importlib
import io
import os
import secrets
import ssl
import time
import zipfile
from collections.abc import Callable, Sequence
from datetime import date, datetime, timedelta, timezone as dt_timezone
from email.headerregistry import AddressHeader, HeaderRegistry
from email.message import EmailMessage
from email.utils import format_datetime, make_msgid
from pathlib import Path
from types import MappingProxyType
from typing import NamedTuple

import pytest
from django.conf import settings as django_settings
from django.utils import timezone

from tests import factories, support, support_org
from tests.support_org import eicar_bytes  # noqa: F401  (контракт 3.4: `eicar_bytes` берётся из support_org)

SAMPLES_DIR = Path(__file__).resolve().parent / "fixtures" / "servicedesk"

# Три права среза 003 (контракт 3.3); `support.PERMISSIONS` и `support.PERMISSIONS_002` не меняются.
PERMISSIONS_003 = ("servicedesk.all", "servicedesk.manage")


# --- классы адаптера IMAP: настоящие, если код уже есть, иначе заглушки той же формы -----------------

class _FallbackMailboxUnavailable(Exception):
    """ЗАГЛУШКА: настоящего `apps.integrations.mail.imap.MailboxUnavailable` ещё нет.

    Тест, который ловит именно настоящий класс, упадёт красным, пока кода нет, — это нормально."""


class _FallbackMailHead(NamedTuple):
    uid: int
    internal_date: datetime
    message_id: str
    size: int


class _FallbackFetchedMail(NamedTuple):
    uid: int
    size: int
    internal_date: datetime
    raw: bytes


_FALLBACKS = {
    "MailboxUnavailable": _FallbackMailboxUnavailable,
    "MailHead": _FallbackMailHead,
    "FetchedMail": _FallbackFetchedMail,
}


def _imap_attr(name: str):
    try:
        module = importlib.import_module("apps.integrations.mail.imap")
    except ImportError:
        return _FALLBACKS[name]
    return getattr(module, name, _FALLBACKS[name])


def __getattr__(name: str):
    """`support_servicedesk.MailHead`, `FetchedMail`, `MailboxUnavailable` — настоящие, если код уже есть."""
    if name in _FALLBACKS:
        return _imap_attr(name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# --- время (контракт 3.4) -----------------------------------------------------------------------------

def backdate(obj, field: str, days: int = 0, *, hours: int = 0, minutes: int = 0) -> None:
    """Сдвигает сохранённое значение поля даты назад на этот срок (решение 5 задач).

    Пустое значение — отсчёт от `timezone.now()`. Пишет `type(obj).objects.filter(pk=...).update(...)` без
    `save()` (поля `auto_now` и сигналы не трогаются) и обновляет значение в `obj`. Работает с любой моделью.
    """
    value = getattr(obj, field) or timezone.now()
    shifted = value - timedelta(days=days, hours=hours, minutes=minutes)
    type(obj).objects.filter(pk=obj.pk).update(**{field: shifted})
    setattr(obj, field, shifted)


# --- подмена антивируса (контракт 3.4, 3.5): та же цель, что у фото в support_org ----------------------

def scan_clean(monkeypatch) -> list:
    """`scan` отвечает «чисто». Возвращает список путей, с которыми его вызвали."""
    return support_org.scan_clean(monkeypatch)


def scan_found(monkeypatch, signature: str = "Eicar-Signature") -> list:
    """`scan` находит сигнатуру (например `"Heuristics.Encrypted.Zip"`)."""
    return support_org.scan_found(monkeypatch, signature)


def scan_unavailable(monkeypatch) -> list:
    """`scan` поднимает `ScanUnavailable`."""
    return support_org.scan_unavailable(monkeypatch)


# --- образцы T-3002 -----------------------------------------------------------------------------------

def sample(name: str) -> bytes:
    """Файл образца из `tests/fixtures/servicedesk/` по имени; неизвестное имя — `FileNotFoundError`.

    Имя должно быть простым именем файла и упоминаться в `SOURCE.md` (там описаны все образцы).
    """
    if not name or Path(name).name != name:
        raise FileNotFoundError(f"образец {name!r}: нужно простое имя файла из SOURCE.md")
    source = SAMPLES_DIR / "SOURCE.md"
    if name not in source.read_text(encoding="utf-8"):
        raise FileNotFoundError(f"образца {name!r} нет в {source}")
    path = SAMPLES_DIR / name
    if not path.is_file():
        raise FileNotFoundError(f"образец {name!r} описан в SOURCE.md, но файла нет: {path}")
    return path.read_bytes()


def big_zip(megabytes: int = 20) -> bytes:
    """ZIP без сжатия (`ZIP_STORED`) с одним элементом из `os.urandom` указанного размера."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("data.bin", os.urandom(megabytes * 1024 * 1024))
    return buffer.getvalue()


# --- build_mail (контракт 5.2) ------------------------------------------------------------------------

class _RepeatableHeaders(HeaderRegistry):
    """Реестр заголовков, где адресные заголовки можно повторять (`AddressHeader.max_count` не ограничен)."""

    def __init__(self):
        super().__init__()
        for name in ("cc", "to", "reply-to", "bcc"):
            self.map_to_type(name, AddressHeader)


_POLICY = email.policy.EmailPolicy(header_factory=_RepeatableHeaders())


class MailPart(NamedTuple):
    name: str
    data: bytes
    content_type: str = "application/octet-stream"
    content_id: str | None = None


def build_mail(*, from_addr: str, to: Sequence[str] = (), cc: Sequence[str] = (), subject: str = "",
               text: str | None = "", html: str | None = None, message_id: str | None = None,
               in_reply_to: str | None = None, references: str | None = None,
               headers: dict[str, str | Sequence[str]] | None = None,
               attachments: Sequence[MailPart] = (), date: datetime | None = None,
               charset: str = "utf-8") -> bytes:
    """Байты письма (RFC 822) на `email.message.EmailMessage`.

    `message_id=None` — генерируется `make_msgid(domain="client.test")`, `""` — заголовок не пишется.
    `headers` дописываются как есть; значение-список пишет заголовок несколько раз (например, несколько `Cc`;
    повтор разрешён у `To`, `Cc`, `Reply-To`, `Bcc`). Переводы строк — CRLF.
    Часть с `content_id` — `Content-Disposition: inline`. Если нет ни `text`, ни `html`, но есть вложения,
    тело — пустой `text/plain` (без него у письма нет основной части).
    """
    msg = EmailMessage(policy=_POLICY)
    msg["From"] = from_addr
    if to:
        msg["To"] = ", ".join(to)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg["Subject"] = subject
    msg["Date"] = format_datetime(date if date is not None else datetime.now(dt_timezone.utc))
    if message_id is None:
        message_id = make_msgid(domain="client.test")
    if message_id:
        msg["Message-ID"] = message_id
    if in_reply_to is not None:
        msg["In-Reply-To"] = in_reply_to
    if references is not None:
        msg["References"] = references
    # повторные заголовки (несколько `Cc`): политика `_POLICY` разрешает повтор адресных заголовков
    for name, value in (headers or {}).items():
        for item in ([value] if isinstance(value, str) else list(value)):
            msg[name] = item

    if text is not None:
        msg.set_content(text, charset=charset)
        if html is not None:
            msg.add_alternative(html, subtype="html", charset=charset)
    elif html is not None:
        msg.set_content(html, subtype="html", charset=charset)
    elif attachments:
        msg.set_content("", charset=charset)
    for part in attachments:
        maintype, _, subtype = part.content_type.partition("/")
        extra = {"disposition": "inline", "cid": part.content_id if part.content_id.startswith("<")
                 else f"<{part.content_id}>"} if part.content_id else {}
        msg.add_attachment(part.data, maintype=maintype, subtype=subtype or "octet-stream",
                           filename=part.name, **extra)
    # переводы строк CRLF, как письмо хранит и отдаёт Dovecot (длина байтов = `RFC822.SIZE`)
    return msg.as_bytes(policy=_POLICY.clone(linesep="\r\n"))


# --- FakeMailbox (контракт 5.2) -----------------------------------------------------------------------

class FakeMessage(NamedTuple):
    raw: bytes
    internal_date: datetime
    seen: bool


def _utc(value: datetime) -> datetime:
    if timezone.is_naive(value):
        return value.replace(tzinfo=dt_timezone.utc)
    return value.astimezone(dt_timezone.utc)


class FakeMailbox:
    """Один ящик в памяти; повторяет интерфейс `MailboxConnection` и сам является своим соединением.

    Подмена: `monkeypatch.setattr(imap, "connect", fake.connect)` (или `install_fake_mailbox`).
    Воспроизводит UIDVALIDITY и UIDNEXT, UID по возрастанию без повторов, `UID SEARCH N:*` с ответом
    «последнее письмо» на пустой диапазон, `INTERNALDATE`, байты письма, признак «прочитано» (его `fetch`
    не меняет), пересоздание ящика. Папок, других флагов, удаления и SMTP нет.
    """

    def __init__(self, *, uidvalidity: int = 1000, uidnext: int = 1):
        self.uidvalidity = uidvalidity
        self.uidnext = uidnext
        self._messages: dict[int, FakeMessage] = {}
        self.on_fetch: Callable[[int], None] | None = None
        self.connects = 0
        self.closes = 0
        self.folder: str | None = None
        self.fetched: list[int] = []
        self.peeked: list[int] = []
        self.searches: list[tuple[str, object]] = []
        self._unavailable: str | None = None
        self._fail_fetch: dict[int, str] = {}

    # тест-часть интерфейса
    @property
    def messages(self) -> MappingProxyType:
        """UID → `FakeMessage(raw, internal_date, seen)`; только чтение."""
        return MappingProxyType(self._messages)

    def append(self, raw: bytes, *, internal_date: datetime | None = None, seen: bool = False) -> int:
        uid = self.uidnext
        self.uidnext += 1
        self._messages[uid] = FakeMessage(raw, _utc(internal_date or timezone.now()).replace(microsecond=0), seen)
        return uid

    def recreate(self, *, uidvalidity: int | None = None) -> None:
        self._messages = {}
        self.uidnext = 1
        self.uidvalidity = uidvalidity if uidvalidity is not None else self.uidvalidity + 1

    def mark_seen(self, uid: int) -> None:
        self._messages[uid] = self._messages[uid]._replace(seen=True)

    def seen(self, uid: int) -> bool:
        return self._messages[uid].seen

    def set_unavailable(self, error: str | None) -> None:
        self._unavailable = error

    def fail_fetch(self, uid: int, error: str) -> None:
        self._fail_fetch[uid] = error

    # интерфейс соединения
    def connect(self) -> "FakeMailbox":
        self.connects += 1
        self.folder = django_settings.IMAP_FOLDER
        if self._unavailable is not None:
            raise _imap_attr("MailboxUnavailable")(self._unavailable)
        return self

    def search_uids(self, first_uid: int) -> list[int]:
        self.searches.append(("uid", first_uid))
        found = sorted(uid for uid in self._messages if uid >= first_uid)
        if not found and self._messages:
            return [max(self._messages)]
        return found

    def search_since(self, day: date) -> list[int]:
        self.searches.append(("since", day))
        return sorted(uid for uid, message in self._messages.items() if message.internal_date.date() >= day)

    def _get(self, uid: int) -> FakeMessage:
        if uid not in self._messages:
            raise _imap_attr("MailboxUnavailable")(f"нет письма с UID {uid}")
        return self._messages[uid]

    def head(self, uid: int):
        message = self._get(uid)
        self.peeked.append(uid)
        parsed = email.message_from_bytes(message.raw, policy=email.policy.default)
        message_id = str(parsed["Message-ID"] or "").strip()
        return _imap_attr("MailHead")(uid, message.internal_date, message_id, len(message.raw))

    def fetch(self, uid: int):
        if uid in self._fail_fetch:
            raise _imap_attr("MailboxUnavailable")(self._fail_fetch[uid])
        message = self._get(uid)
        self.fetched.append(uid)
        result = _imap_attr("FetchedMail")(uid, len(message.raw), message.internal_date, message.raw)
        if self.on_fetch is not None:
            self.on_fetch(uid)
        return result

    def close(self) -> None:
        self.closes += 1

    def __enter__(self) -> "FakeMailbox":
        return self

    def __exit__(self, *exc_info) -> None:
        self.close()


def install_fake_mailbox(monkeypatch, settings, fake: FakeMailbox | None = None) -> FakeMailbox:
    """Подменяет `apps.integrations.mail.imap.connect` и ставит `IMAP_*` и `SERVICEDESK_MAILBOX`.

    `IMAP_PASSWORD` — случайный `secrets.token_urlsafe()`. Тест «пустой `IMAP_HOST`» после этого
    ставит `settings.IMAP_HOST = ""`.
    """
    fake = fake if fake is not None else FakeMailbox()
    try:
        imap = importlib.import_module("apps.integrations.mail.imap")
    except ImportError as exc:
        raise AssertionError("нет apps.integrations.mail.imap: фальшивый ящик ждёт код среза 003 "
                             "(CONTRACT-003 § 5.1)") from exc
    monkeypatch.setattr(imap, "connect", fake.connect)
    settings.IMAP_HOST = "imap.test"
    settings.IMAP_PORT = 993
    settings.IMAP_SECURITY = "ssl"
    settings.IMAP_USER = "tickets"
    settings.IMAP_PASSWORD = secrets.token_urlsafe()
    settings.IMAP_FOLDER = "INBOX"
    settings.SERVICEDESK_MAILBOX = "tickets@stand.test"
    return fake


@pytest.fixture
def fake_mailbox(monkeypatch, settings) -> FakeMailbox:
    return install_fake_mailbox(monkeypatch, settings)


# --- FakeImap (контракт 5.2): двойник imaplib для тестов адаптера -----------------------------------

class FakeImap:
    """Двойник `imaplib.IMAP4` / `IMAP4_SSL`. Состояние лежит в атрибутах класса (тест адаптера видит его через
    `FakeImap`, а не через экземпляр, которого у него нет): `FakeImap.factory(...)` обнуляет их.

    `ctor` — `(имя класса, позиционные, ключевые)` каждого создания; имя класса определяется по ключу
    `ssl_context` (только у `IMAP4_SSL`); `ssl_context` — что передано в конструктор или `starttls`;
    `calls` — `(команда, аргументы)`; `readonly` — что передано в `select`.
    """

    ctor: list[tuple[str, tuple, dict]] = []
    ssl_context = None
    calls: list[tuple[str, tuple]] = []
    readonly = None
    instances: list["FakeImap"] = []
    _uidvalidity = 0
    _uidnext = 0
    _status_uidvalidity = 0
    _select_result = "OK"

    def __init__(self, host: str = "", port: int | None = None, *, ssl_context=None, timeout=None):
        cls = type(self)
        kwargs = {}
        if ssl_context is not None:
            kwargs["ssl_context"] = ssl_context
        if timeout is not None:
            kwargs["timeout"] = timeout
        positional = (host,) if port is None else (host, port)
        cls.ctor.append(("IMAP4_SSL" if "ssl_context" in kwargs else "IMAP4", positional, kwargs))
        if ssl_context is not None:
            cls.ssl_context = ssl_context
        cls.instances.append(self)

    @classmethod
    def factory(cls, *, uidvalidity: int, uidnext: int, status_uidvalidity: int,
                select_result: str = "OK") -> Callable[..., "FakeImap"]:
        """Фабрика с сигнатурой `imaplib` (`(host, port=…, *, ssl_context=None, timeout=None)`).

        `status_uidvalidity` — заведомо другое значение, которое отдаёт `STATUS`."""
        cls.ctor = []
        cls.ssl_context = None
        cls.calls = []
        cls.readonly = None
        cls.instances = []
        cls._uidvalidity = uidvalidity
        cls._uidnext = uidnext
        cls._status_uidvalidity = status_uidvalidity
        cls._select_result = select_result

        def make(host: str = "", port: int | None = None, *, ssl_context=None, timeout=None) -> "FakeImap":
            return cls(host, port, ssl_context=ssl_context, timeout=timeout)

        return make

    def login(self, user, password):
        type(self).calls.append(("login", (user, "***")))   # пароль не запоминается
        return "OK", [b"Logged in"]

    def starttls(self, ssl_context=None):
        cls = type(self)
        cls.calls.append(("starttls", (ssl_context,)))
        cls.ssl_context = ssl_context
        return "OK", [b"Begin TLS negotiation now"]

    def select(self, folder="INBOX", readonly=False):
        cls = type(self)
        cls.calls.append(("select", (folder, readonly)))
        cls.readonly = readonly
        return cls._select_result, [b"1"]

    def response(self, code):
        cls = type(self)
        cls.calls.append(("response", (code,)))
        if cls._select_result != "OK":
            return code, [None]
        value = {"UIDVALIDITY": cls._uidvalidity, "UIDNEXT": cls._uidnext}.get(code)
        return code, [None if value is None else str(value).encode()]

    def status(self, folder, names):
        cls = type(self)
        cls.calls.append(("status", (folder, names)))
        line = f'"{folder}" (UIDVALIDITY {cls._status_uidvalidity} UIDNEXT {cls._uidnext + 100})'
        return "OK", [line.encode()]

    def uid(self, command, *args):
        type(self).calls.append(("uid", (command, *args)))
        return "OK", [b""]

    def logout(self):
        type(self).calls.append(("logout", ()))
        return "BYE", [b"Logging out"]


# --- шина событий: фикстуры `bus` и `bus_spy` (контракт 3.1) ---------------------------------------

class Bus:
    """Записывающий подписчик шины: `.listen(*names)`, `.calls(name)`, `.all()`."""

    def __init__(self, events):
        self._events = events
        self._all: list[tuple[str, dict]] = []
        self._handlers: list[tuple[str, Callable]] = []

    def listen(self, *names: str) -> None:
        for name in names:
            def handler(_name=name, **data):
                self._all.append((_name, data))

            self._events.subscribe(name, handler)
            self._handlers.append((name, handler))

    def calls(self, name: str) -> list[dict]:
        return [data for event, data in self._all if event == name]

    def all(self) -> list[tuple[str, dict]]:
        return list(self._all)

    def detach(self) -> None:
        for name, handler in self._handlers:
            self._events.unsubscribe(name, handler)
        self._handlers = []


def _events_module():
    try:
        return importlib.import_module("apps.core.events")
    except ImportError:
        pytest.fail("нет apps.core.events: фикстуры bus и bus_spy ждут код среза 003 (CONTRACT-003 § 3.1)")


@pytest.fixture
def bus():
    """Тело теста идёт внутри `events.empty()` (подписчиков нет); `Bus` записывает вызовы."""
    events = _events_module()
    with events.empty():
        yield Bus(events)


@pytest.fixture
def bus_spy():
    """Прежние подписки остаются; записывающие обработчики снимаются при выходе из теста."""
    events = _events_module()
    spy = Bus(events)
    try:
        yield spy
    finally:
        spy.detach()


# --- вход в Dovecot для живых тестов (контракт, раздел 1) -------------------------------------------

def _scrub(text: str, password: str) -> str:
    return text.replace(password, "***") if password else text


def _imap_login(timeout: float = 5.0):
    """Новое соединение `imaplib` по `settings.IMAP_*` и паролю из окружения (без шифрования, `starttls`, `ssl`)."""
    host, port = django_settings.IMAP_HOST, int(django_settings.IMAP_PORT)
    mode = django_settings.IMAP_SECURITY
    if mode == "ssl":
        conn = imaplib.IMAP4_SSL(host, port, ssl_context=ssl.create_default_context(), timeout=timeout)
    else:
        conn = imaplib.IMAP4(host, port, timeout=timeout)
        if mode == "starttls":
            conn.starttls(ssl_context=ssl.create_default_context())
    conn.login(django_settings.IMAP_USER, os.environ["IMAP_PASSWORD"])
    return conn


def live_mailbox_ready(timeout: float = 30.0) -> None:
    """Повторяет вход в Dovecot раз в секунду до `timeout` с; при неудаче — `AssertionError` без пароля."""
    password = os.environ.get("IMAP_PASSWORD", "")
    deadline = time.monotonic() + timeout
    last = "нет попыток"
    while True:
        try:
            conn = _imap_login()
        except Exception as exc:
            last = _scrub(f"{type(exc).__name__}: {exc}", password)
        else:
            conn.logout()
            return
        if time.monotonic() >= deadline:
            raise AssertionError(f"Dovecot ({django_settings.IMAP_HOST}:{django_settings.IMAP_PORT}) не принял вход "
                                 f"за {timeout:g} с: {last}")
        time.sleep(1.0)


class LiveMailbox:
    """Своя папка `live-<токен>` на настоящем Dovecot: `.folder`, `.append`, `.recreate`, `.uidvalidity`."""

    def __init__(self, folder: str):
        self.folder = folder

    def _run(self, action):
        conn = _imap_login()
        try:
            return action(conn)
        finally:
            try:
                conn.logout()
            except Exception:
                pass

    @staticmethod
    def _ok(result, what: str):
        status, data = result
        assert status == "OK", f"Dovecot: {what} не выполнено ({status})"
        return data

    def create(self) -> None:
        self._run(lambda conn: self._ok(conn.create(self.folder), "CREATE"))

    def delete(self) -> str:
        """`DELETE` папки; возвращает статус ответа (`"OK"` или `"NO"`)."""
        return self._run(lambda conn: conn.delete(self.folder)[0])

    def append(self, raw: bytes, *, flags=()) -> int:
        """`APPEND` и UID по `UID SEARCH` (`APPENDUID` у Dovecot для первого письма неверен по UIDVALIDITY)."""
        def action(conn):
            flag_text = f"({' '.join(flags)})" if flags else None
            self._ok(conn.append(self.folder, flag_text, None, raw), "APPEND")
            self._ok(conn.select(self.folder, readonly=True), "EXAMINE")
            data = self._ok(conn.uid("SEARCH", None, "ALL"), "UID SEARCH")
            uids = [int(item) for item in (data[0] or b"").split()]
            assert uids, "после APPEND в папке нет писем"
            return max(uids)

        return self._run(action)

    def recreate(self) -> None:
        """Закрыть соединения, `DELETE` и `CREATE` папки: UIDVALIDITY меняется."""
        self.delete()
        self.create()

    def uidvalidity(self) -> int:
        def action(conn):
            self._ok(conn.select(self.folder, readonly=True), "EXAMINE")
            data = conn.response("UIDVALIDITY")[1]
            return int(data[0])

        return self._run(action)


@pytest.fixture
def live_mailbox(settings):
    """Своя папка на Dovecot на время теста; `settings.IMAP_FOLDER` — её имя; `INBOX` стенда не трогается."""
    live_mailbox_ready()
    box = LiveMailbox(f"live-{secrets.token_urlsafe(6)}")
    box.create()
    settings.IMAP_FOLDER = box.folder
    try:
        yield box
    finally:
        if box.delete() != "OK":
            print(f"live_mailbox: папка {box.folder} не удалена на стенде")


# --- последовательность номеров заявок (контракт 2.2, через соединение `migrate`) --------------------

def sequence_state() -> tuple[int, bool]:
    """`(last_value, is_called)` последовательности `servicedesk_ticket_number`."""
    from django.db import connections

    with connections["migrate"].cursor() as cur:
        cur.execute("SELECT last_value, is_called FROM servicedesk_ticket_number")
        last_value, is_called = cur.fetchone()
    return int(last_value), bool(is_called)


def set_sequence(value: int, *, is_called: bool = True) -> None:
    """`SELECT setval('servicedesk_ticket_number', value, is_called)` через соединение `migrate`."""
    from django.db import connections

    with connections["migrate"].cursor() as cur:
        cur.execute("SELECT setval('servicedesk_ticket_number', %s, %s)", [value, is_called])


# --- настройка сервис-деска и фабрики (имена выбрал исполнитель: в контракте их нет, см. дополнение 3.4) ---
# Все фабрики принимают `using` (имя соединения, по умолчанию "default"; "migrate" — контракт 8.4).
# При `using != "default"` фабрики сами создают узел на том же соединении (`_unit_on`) и пользователя не создают:
# тест передаёт его (`created_by`, `queue`), иначе `ValueError`. Тесты команд через `migrate` (T-3136) создают данные
# только этими фабриками с `using="migrate"`, без `support_org.make_unit` и `support.make_employee`: иначе проверка
# внешних ключей в конце теста на соединении `migrate` не увидит узлов и пользователей из транзакции `default`.

def _unit_of(value):
    """Узел `org.Unit` из узла, `Queue` или `None`."""
    return getattr(value, "unit", value)


def _db(model, using: str):
    """Менеджер модели на нужном соединении."""
    return model.objects.db_manager(using)


def _unit_on(using: str, name: str | None = None, *, parent=None):
    """Узел на соединении `using` по правилам `support_org.make_unit` (`path`, `depth`, `name_key`).

    Корень — строка миграции (`parent=None`), она видна обоим соединениям."""
    Unit = support.model("org.Unit")
    manager = _db(Unit, using)
    parent = parent or manager.get(parent=None)
    name = name or f"Узел {next(support_org._unit_counter)}-{secrets.token_hex(3)}"
    unit = manager.create(name=name, name_key=support_org.name_key(name), kind="department", parent=parent,
                          depth=parent.depth + 1, path="")
    unit.path = f"{parent.path}{unit.pk}/"
    unit.save(using=using, update_fields=["path"])
    return unit


def _require(using: str, value, field: str):
    """При `using != "default"` обязательное значение передаёт тест: создавать его через `migrate` нельзя."""
    if value is None and using != "default":
        raise ValueError(f"при using={using!r} через {using} передайте {field}")
    return value


def make_queue(unit=None, *, created_by=None, using: str = "default"):
    """Очередь (отметка узла). Без `unit` создаётся новый узел (`support_org.make_unit()`; при `using` не по
    умолчанию — `_unit_on`). При `using` не по умолчанию `created_by` обязателен."""
    Queue = support.model("servicedesk.Queue")
    unit = _unit_of(unit) or (support_org.make_unit() if using == "default" else _unit_on(using))
    if using != "default":
        existing = _db(Queue, using).filter(unit=unit).first()
        if existing is not None:
            return existing
        _require(using, created_by, "created_by")
    queue, _ = _db(Queue, using).get_or_create(
        unit=unit, defaults={"created_by": created_by or _any_user(using), "created_at": timezone.now()})
    return queue


def _any_user(using: str = "default"):
    User = support.model("core.User")
    return _db(User, using).order_by("id").first() or support.make_employee()


def configure_servicedesk(*, domains: Sequence[str] | None = None, default_queue=None, using: str = "default",
                          **fields):
    """Строка настроек (`pk=1`): домены, очередь по умолчанию (узел или `Queue`; `None` — не менять), прочие поля."""
    Settings = support.model("servicedesk.ServiceDeskSettings")
    obj, _ = _db(Settings, using).get_or_create(pk=1)
    if domains is not None:
        obj.domains = [d.lower() for d in domains]
    if default_queue is not None:
        obj.default_queue = _unit_of(default_queue)
    for name, value in fields.items():
        setattr(obj, name, value)
    obj.save(using=using)
    return obj


def make_category(name: str | None = None, *, queue=None, default_assignee=None, on_form: bool = False,
                  order: int = 0, archived: bool = False, using: str = "default"):
    """Категория (не системная); `queue` — узел или `Queue`, без него создаётся очередь."""
    Category = support.model("servicedesk.Category")
    name = name or f"Категория {secrets.token_hex(3)}"
    _require(using, queue, "queue")
    unit = _unit_of(queue) if queue is not None else make_queue(using=using).unit
    return _db(Category, using).create(name=name, name_key=support_org.name_key(name), queue=unit,
                                       default_assignee=default_assignee, on_form=on_form, order=order,
                                       archived=archived)


def make_requester(email: str | None = None, *, full_name: str = "", client_unit=None, origin: str = "ticket",
                   using: str = "default"):
    """Заявитель; адрес хранится строчными."""
    Requester = support.model("servicedesk.Requester")
    return _db(Requester, using).create(email=(email or factories.new_email("req")).lower(), full_name=full_name,
                                        client_unit=client_unit, origin=origin, created_at=timezone.now())


def make_ticket(*, queue=None, requester=None, kind: str = "new", number: int | None = None,
                using: str = "default", **over):
    """Заявка через ORM (не через сервис): номер — из последовательности `servicedesk_ticket_number` (как у
    `tickets.create`: иначе первая заявка службы в том же тесте получит уже занятый номер), справочники — начальные строки.

    `last_message_at` и `created_at` ставятся в «сейчас» (тест сдвигает их `backdate`). `status` без `kind` в
    `over` — вид берётся из статуса."""
    from django.db import connections

    Ticket = support.model("servicedesk.Ticket")
    Status, Priority, Source = (support.model(f"servicedesk.{n}") for n in ("Status", "Priority", "Source"))
    requester = requester or make_requester(using=using)
    _require(using, queue, "queue")
    unit = _unit_of(queue) if queue is not None else make_queue(using=using).unit
    if number is None:
        with connections[using].cursor() as cur:
            cur.execute("SELECT nextval('servicedesk_ticket_number')")
            number = cur.fetchone()[0]
    now = timezone.now()
    fields = {
        "number": number, "subject": f"Тема {number}", "requester": requester,
        "requester_email": requester.email, "requester_name": requester.full_name, "queue": unit,
        "priority": _db(Priority, using).get(name_key=support_org.name_key("Средняя")),
        "status": _db(Status, using).get(kind=kind, is_default=True), "kind": kind,
        "source": _db(Source, using).get(system_code="mail"),
        "created_at": now, "last_message_at": now,
    }
    fields.update(over)
    if "status" in over and "kind" not in over:
        fields["kind"] = fields["status"].kind
    return _db(Ticket, using).create(**fields)


def make_entry(ticket, kind: str = "comment", *, author=None, text: str = "", using: str = "default", **over):
    """Элемент ленты через ORM; для `kind="incoming"` без автора ставятся адрес и имя заявителя; `at` — «сейчас»."""
    Entry = support.model("servicedesk.TicketEntry")
    fields = {"ticket": ticket, "kind": kind, "text": text, "author": author, "at": timezone.now()}
    if kind == "incoming" and author is None:
        fields.update(author_email=ticket.requester_email, author_name=ticket.requester_name)
    fields.update(over)
    return _db(Entry, using).create(**fields)


def make_participant(ticket, email: str | None = None, *, name: str = "", removed_by=None, removed_at=None,
                     using: str = "default"):
    """Участник из копии; снятый — с `removed_at` (и `removed_by`)."""
    Participant = support.model("servicedesk.TicketParticipant")
    if removed_by is not None and removed_at is None:
        removed_at = timezone.now()
    return _db(Participant, using).create(
        ticket=ticket, email=(email or factories.new_email("cc")).lower(), name=name, added_at=timezone.now(),
        removed_at=removed_at, removed_by=removed_by)


_inbound_uid = iter(range(1, 10 ** 9))


def make_inbound(*, uidvalidity: int = 1000, uid: int | None = None, from_email: str | None = None,
                 using: str = "default", **over):
    """Входящее письмо (строка `InboundMail`) через ORM; файла письма на диске не создаёт; `received_at` — «сейчас»."""
    Inbound = support.model("servicedesk.InboundMail")
    fields = {
        "uidvalidity": uidvalidity, "uid": uid if uid is not None else next(_inbound_uid),
        "message_id": make_msgid(domain="client.test"), "internal_date": timezone.now(), "size": 0,
        "from_email": from_email or factories.new_email("sender"), "subject": "", "received_at": timezone.now(),
    }
    fields.update(over)
    return _db(Inbound, using).create(**fields)


# --- чтение писем заявки (контракт 10) --------------------------------------------------------------

def ticket_mails(ticket) -> list:
    """`MailMessage` заявки по `related_ref == "ticket:<Ticket.id>"`, по возрастанию номера."""
    MailMessage = support.model("mail.MailMessage")
    return list(MailMessage.objects.filter(related_ref=f"ticket:{ticket.pk}").order_by("id"))


def mail_text(message, context: dict | None = None) -> str:
    """Текст письма заявки: тело, которое отдаёт рендерер `letters.render(message, context)`.

    Контекст по умолчанию — как в `job.meta["context"]`: `ticket_id` (из `related_ref`), `entry_id=None`,
    `after_hours=None`."""
    try:
        letters = importlib.import_module("apps.servicedesk.services.letters")
    except ImportError as exc:
        raise AssertionError("нет apps.servicedesk.services.letters: чтение текста письма ждёт код среза 003 "
                             "(CONTRACT-003 § 6.17)") from exc
    if context is None:
        ticket_id = int(message.related_ref.partition(":")[2])
        context = {"ticket_id": ticket_id, "entry_id": None, "after_hours": None}
    return letters.render(message, context).body
