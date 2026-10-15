"""Общие помощники тестов среза 004 (T-4100, вторая половина).

Имена и поведение — `tests/CONTRACT-004.md` (шапка, разделы 1.1, 2.3, 3.1, 5.1, 5.3, 6.x, 7.3, 11.3, 11.4).
Кода среза 004 ещё нет, поэтому на уровне модуля здесь нет импортов из `apps.notify`, `apps.integrations.*`,
`channels`, `config.asgi`: модели берутся лениво (`support.model("notify.Delivery")`), остальное — внутри
функций. Сбор тестов (`pytest --collect-only`) проходит до появления кода; вызов того, чего ещё нет,
падает понятной ошибкой.

Секреты (решение 23 задач): токены ботов и ключи VAPID создаются на месте, в именах переменных нет слов
`secret`, `token`, `key`, `password`; значения в сообщения об ошибках не попадают. Константы RFC 8291 —
публичные векторы приложения A.

Фикстуры `bots_on`, `webpush_on` подключены в `tests/conftest.py`.
"""
import asyncio
import base64
import contextlib
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from typing import NamedTuple

import pytest
from asgiref.sync import async_to_sync, sync_to_async
from django.conf import settings as django_settings

from tests import support

# --- права, названия и точки расширения среза 004 (контракт 2.3) ---------------------------------------

PERMISSIONS_004 = ("notify.manage",)
TITLES_004 = {"notify.manage": "Настройка уведомлений"}
POINTS_004 = ("notification_kinds", "top_bar_items")

# значение `WEBPUSH_ALLOWED_HOSTS` по умолчанию (контракт 1.3)
_ALLOWED_HOSTS_DEFAULT = ["fcm.googleapis.com", "jmt17.google.com", "*.notify.windows.com",
                          "updates.push.services.mozilla.com"]


# --- векторы RFC 8291, приложение A (https://www.rfc-editor.org/rfc/rfc8291.txt) ------------------------

def _b64(text: str) -> bytes:
    text = "".join(text.split())
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


RFC8291_PLAINTEXT = bytes.fromhex("5768656e20492067726f772075702c20492077616e7420746f20626520612077617465726d656c6f6e")  # «When I grow up, I want to be a watermelon»
RFC8291_SENDER_PRIV = _b64("yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw")
RFC8291_SENDER_PUB = _b64("BP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A8")
RFC8291_RECEIVER_PRIV = _b64("q1dXpw3UpT5VOmu_cf_v6ih07Aems3njxI-JWgLcM94")
RFC8291_RECEIVER_PUB = _b64("BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4")
RFC8291_AUTH = _b64("BTBZMqHH6r4Tts7J_aSIgg")
RFC8291_SALT = _b64("DGv6ra1nlYgDCS1FRnbzlw")
RFC8291_ECDH = _b64("kyrL1jIIOHEzg3sM2ZWRHDRB62YACZhhSlknJ672kSs")
RFC8291_IKM = _b64("S4lYMb_L0FxCeq0WhDx813KgSYqU26kOyzWUdsXYyrg")
RFC8291_CEK = _b64("oIhVW04MRdy2XN9CiKLxTg")
RFC8291_NONCE = _b64("4h_95klXJ5E_qnoN")
# тело запроса из раздела 5 RFC (144 байта: заголовок 86 ‖ шифртекст 58; «Content-Length: 145» в тексте RFC — неточность)
RFC8291_BODY = _b64("DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27ml"
                    "mlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPT"
                    "pK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN")


# --- ленивые классы адаптеров (`apps.integrations.channel`, контракт 5.1) ----------------------------------

class _FallbackResponse(NamedTuple):
    """ЗАГЛУШКА формы `apps.integrations.channel.Response`, пока кода нет."""
    status: int
    headers: dict
    body: bytes


def _response(status: int, headers: dict | None = None, body: bytes = b""):
    try:
        from apps.integrations import channel
        cls = channel.Response
    except (ImportError, AttributeError):
        cls = _FallbackResponse
    return cls(status, {str(k).lower(): v for k, v in (headers or {}).items()}, body)


def _client_module(channel: str):
    import importlib
    if channel not in ("telegram", "max"):
        raise ValueError(f"канал должен быть telegram или max, получено {channel!r}")
    try:
        return importlib.import_module(f"apps.integrations.{channel}.client")
    except ImportError:
        pytest.fail(f"нет apps.integrations.{channel}.client: помощник ждёт код среза 004 (CONTRACT-004 § 5)")


def _transport_owner(module):
    if not hasattr(module, "transport"):
        pytest.fail(f"в {module.__name__} нет функции transport: помощник ждёт код среза 004 (CONTRACT-004 § 5.1)")
    return module


def _notify_settings_update(**fields) -> None:
    support.model("notify.NotifySettings").objects.update_or_create(pk=1, defaults=fields)


# --- ключи браузера и расшифровка Web Push (контракт 5.3) ------------------------------------------------

class BrowserKeys(NamedTuple):
    p256dh: str      # base64url без дополнения, 65 байт открытой точки P-256
    auth: str        # base64url без дополнения, 16 байт
    private: bytes   # 32 байта закрытого скаляра P-256
    auth_raw: bytes  # те же 16 байт


def _b64_text(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def browser_keys() -> BrowserKeys:
    """Новая пара ключей браузера на каждый вызов (решение E15)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    pair = ec.generate_private_key(ec.SECP256R1())
    scalar = pair.private_numbers().private_value.to_bytes(32, "big")
    point = pair.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    raw_auth = secrets.token_bytes(16)
    return BrowserKeys(_b64_text(point), _b64_text(raw_auth), scalar, raw_auth)


def _decrypt_body(body: bytes, keys: BrowserKeys) -> bytes:
    """Открытый текст из тела aes128gcm (RFC 8188, RFC 8291): одна запись, разделитель 0x02 убирается."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
    from cryptography.hazmat.primitives.kdf.hkdf import HKDF

    salt, id_len = body[:16], body[20]
    sender_point = body[21:21 + id_len]
    cipher_text = body[21 + id_len:]
    receiver_point = _b64(keys.p256dh)
    receiver = ec.derive_private_key(int.from_bytes(keys.private, "big"), ec.SECP256R1())
    sender = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), sender_point)
    shared = receiver.exchange(ec.ECDH(), sender)
    ikm = HKDF(hashes.SHA256(), 32, keys.auth_raw, b"WebPush: info\x00" + receiver_point + sender_point).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    plain = AESGCM(cek).decrypt(nonce, cipher_text, None).rstrip(b"\x00")
    if not plain or plain[-1] != 2:
        raise ValueError("в расшифрованной записи нет разделителя последней записи 0x02 (CONTRACT-004 § 5.3)")
    return plain[:-1]


class _WebpushRequest:
    """Перехваченный запрос Web Push: `.url`, `.method`, `.headers` (ключи в нижнем регистре), `.body`, `.timeout`."""

    def __init__(self, request, timeout):
        self.url = request.full_url
        self.method = request.get_method()
        self.headers = {name.lower(): value for name, value in request.header_items()}
        self.body = request.data
        self.timeout = timeout


class _WebpushCapture:
    """Результат `webpush_capture`: контекстный менеджер; `.requests`, `.decrypt(request, keys)`."""

    def __init__(self, status, headers, error, by_endpoint, on_request):
        self.requests: list[_WebpushRequest] = []
        self._status, self._headers, self._error = status, headers, error
        self._by_endpoint, self._on_request = by_endpoint or {}, on_request
        self._module = None
        self._saved = None

    def _transport(self, request, timeout):
        record = _WebpushRequest(request, timeout)
        self.requests.append(record)
        if self._on_request is not None:
            self._on_request(record)
        outcome = self._by_endpoint.get(record.url, self._error)
        if outcome is not None and not isinstance(outcome, str) and hasattr(outcome, "status"):
            return outcome
        if outcome == "timeout":
            raise TimeoutError("timeout")
        if outcome == "network":
            raise OSError("network")
        return _response(self._status, self._headers)

    def decrypt(self, request, keys: BrowserKeys) -> dict:
        """Расшифровывает тело запроса ключами браузера; нагрузка — JSON `{"title", "url", "tag"}`."""
        return json.loads(_decrypt_body(request.body, keys).decode("utf-8"))

    def __enter__(self):
        import importlib
        try:
            self._module = importlib.import_module("apps.integrations.webpush.client")
        except ImportError:
            pytest.fail("нет apps.integrations.webpush.client: помощник ждёт код среза 004 (CONTRACT-004 § 5.3)")
        _transport_owner(self._module)
        self._saved = self._module.transport
        self._module.transport = self._transport
        return self

    def __exit__(self, *exc):
        self._module.transport = self._saved
        return False


def webpush_capture(status=201, headers=None, error=None, *, by_endpoint=None, on_request=None):
    """Подмена `apps.integrations.webpush.client.transport` без сети (контракт 5.3, решение 5 задач).

    `error` — `"timeout"` (поднимает `TimeoutError`) или `"network"` (`OSError`); `by_endpoint` — адрес подписки →
    `Response`, `"timeout"` или `"network"`, главнее общего ответа; `on_request(request)` зовётся перед ответом.
    """
    return _WebpushCapture(status, headers, error, by_endpoint, on_request)


class _BotRequest:
    """Перехваченный запрос бота: `.url`, `.method`, `.headers` (нижний регистр), `.body`, `.json`, `.params`, `.timeout`."""

    def __init__(self, request, timeout):
        self.url = request.full_url
        self.method = request.get_method()
        self.headers = {name.lower(): value for name, value in request.header_items()}
        self.body = request.data
        self.timeout = timeout
        try:
            self.json = json.loads(self.body.decode("utf-8")) if self.body else None
        except (ValueError, UnicodeDecodeError):
            self.json = None
        merged = {name: values[-1] for name, values in
                  urllib.parse.parse_qs(urllib.parse.urlsplit(self.url).query, keep_blank_values=True).items()}
        if isinstance(self.json, dict):
            merged.update(self.json)
        self.params = merged


class _BotsCapture:
    """Результат `bots_capture`: контекстный менеджер над `module.transport`; `.requests`."""

    def __init__(self, module, passthrough, responses):
        self.requests: list[_BotRequest] = []
        self._module, self._passthrough = module, passthrough
        many = isinstance(responses, (list, tuple)) and not hasattr(responses, "status")  # Response — тоже кортеж
        self._queue = list(responses) if many else ([] if responses is None else [responses])
        self._single = responses is not None and not many
        self._real = None

    def _transport(self, request, timeout):
        self.requests.append(_BotRequest(request, timeout))
        if self._passthrough:
            return self._real(request, timeout)
        if self._single:
            return self._queue[0]
        if not self._queue:
            raise AssertionError("bots_capture: ответы из responses закончились, а запрос пришёл ещё")
        return self._queue.pop(0)

    def __enter__(self):
        _transport_owner(self._module)
        self._real = self._module.transport
        self._module.transport = self._transport
        return self

    def __exit__(self, *exc):
        self._module.transport = self._real
        return False


def bots_capture(module, *, passthrough=True, responses=None):
    """Перехват запросов ботов (контракт 5.1, решение E15): `passthrough=True` — запрос уходит настоящей функцией
    на `fakebots`; иначе ответ из `responses` (один `Response` или список по порядку). Адрес Telegram содержит
    токен: тест не печатает `.url` целиком."""
    return _BotsCapture(module, passthrough, responses)


# --- служба fakebots (контракт 1.1, 1.2) -----------------------------------------------------------------

class FakeBots:
    """Клиент учебной службы `fakebots`; адрес — `settings.TELEGRAM_API_BASE` без пути. Только серверные тесты."""

    def __init__(self):
        parts = urllib.parse.urlsplit(django_settings.TELEGRAM_API_BASE)
        if parts.hostname and parts.hostname.endswith("telegram.org"):
            raise RuntimeError("FakeBots: TELEGRAM_API_BASE указывает на настоящий Telegram, а не на fakebots")
        self.base = f"{parts.scheme}://{parts.netloc}"
        self._opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))

    def _call(self, method: str, path: str, body=None):
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(self.base + path, data=data, method=method,
                                         headers={"Content-Type": "application/json"} if data is not None else {})
        try:
            with self._opener.open(request, timeout=10) as answer:
                return json.loads(answer.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(f"fakebots {method} {path}: ответ {exc.code}") from None
        except OSError as exc:
            raise RuntimeError(f"fakebots {method} {path}: нет связи ({type(exc).__name__})") from None

    def health(self) -> dict:
        return self._call("GET", "/_test/health")

    def put_telegram(self, event_or_list) -> list[int]:
        """Кладёт события в очередь `getUpdates`; возвращает их `update_id` (с 1 по порядку)."""
        return self._call("POST", "/_test/telegram/updates", event_or_list)["update_ids"]

    def put_max(self, event_or_list) -> int:
        """Кладёт события в очередь MAX; возвращает номер следующего события (`marker`)."""
        return self._call("POST", "/_test/max/updates", event_or_list)["marker"]

    def sent(self, channel: str) -> list[dict]:
        return self._call("GET", "/_test/sent?" + urllib.parse.urlencode({"channel": channel}))["messages"]

    def fail(self, channel: str, status: int, *, method: str = "*", count: int = 1, retry_after: int = 1) -> None:
        self._call("POST", "/_test/fail", {"channel": channel, "status": status, "method": method,
                                           "count": count, "retry_after": retry_after})

    def reset(self) -> None:
        self._call("POST", "/_test/reset")


# --- фикстуры включения каналов (контракт 1.1) ------------------------------------------------------------

@pytest.fixture
def bots_on(settings, db):
    """Каналы ботов включены: сгенерированные токены, адреса из окружения службы `test`, `fakebots` очищен.

    Возвращает `FakeBots` (клиент службы)."""
    settings.TELEGRAM_BOT_TOKEN = "t-" + secrets.token_hex(8)
    settings.MAX_BOT_TOKEN = "t-" + secrets.token_hex(8)
    settings.TELEGRAM_API_BASE = os.environ.get("TELEGRAM_API_BASE", settings.TELEGRAM_API_BASE)
    settings.MAX_API_BASE = os.environ.get("MAX_API_BASE", settings.MAX_API_BASE)
    _notify_settings_update(telegram_enabled=True, max_enabled=True)
    fake = FakeBots()
    fake.reset()
    return fake


@pytest.fixture
def webpush_on(settings, db):
    """Web Push включён: пара VAPID создаётся на месте, тема и список хостов — по умолчанию."""
    try:
        from apps.integrations.webpush import crypto
        generate = crypto.generate_vapid_keys
    except (ImportError, AttributeError):
        pytest.fail("нет apps.integrations.webpush.crypto.generate_vapid_keys: фикстура webpush_on ждёт код среза 004")
    private, public = generate()
    settings.VAPID_PRIVATE_KEY = private
    settings.VAPID_PUBLIC_KEY = public
    settings.VAPID_SUBJECT = "mailto:noreply@example.test"
    settings.WEBPUSH_ALLOWED_HOSTS = list(_ALLOWED_HOSTS_DEFAULT)
    _notify_settings_update(webpush_enabled=True)


def subscribe(user, *, host: str = "fcm.googleapis.com", path: str | None = None, keys: BrowserKeys | None = None):
    """Подписка Web Push сотрудника через `push.save`; адрес — `https://<host>/<path или случайная строка>`."""
    try:
        from apps.notify.services import push
    except ImportError:
        pytest.fail("нет apps.notify.services.push: помощник subscribe ждёт код среза 004 (CONTRACT-004 § 6.12)")
    keys = keys or browser_keys()
    endpoint = f"https://{host}/{path if path is not None else secrets.token_urlsafe(16)}"
    return push.save(user, endpoint=endpoint, p256dh=keys.p256dh, auth=keys.auth)


class _FakeBotSend:
    """Результат `fake_bot_send`: контекстный менеджер; `.calls` — список `(chat_id, text, button)`."""

    def __init__(self, channel, raises, message_id):
        self.calls: list[tuple] = []
        self._channel, self._raises, self._message_id = channel, raises, message_id
        self._module = None
        self._saved = None

    def _send(self, chat_id, text, *, button=None):
        self.calls.append((chat_id, text, button))
        raises = self._raises
        if raises is not None:
            if isinstance(raises, type):
                codes = {"ChannelGone": 403, "RetryLater": 429, "BadRequest": 400, "BadToken": 401}
                method = "sendMessage" if self._channel == "telegram" else "POST /messages"
                raises = raises(method, codes.get(raises.__name__))
            raise raises
        return self._message_id

    def __enter__(self):
        self._module = _client_module(self._channel)
        if not hasattr(self._module, "send_message"):
            pytest.fail(f"в {self._module.__name__} нет send_message: помощник ждёт код среза 004 (CONTRACT-004 § 5.2)")
        self._saved = self._module.send_message
        self._module.send_message = self._send
        return self

    def __exit__(self, *exc):
        self._module.send_message = self._saved
        return False


def fake_bot_send(channel: str, *, raises=None, message_id: str = "1"):
    """Фальшивый адаптер бота (решение E16): подменяет `apps.integrations.<channel>.client.send_message`.

    `raises` — экземпляр или класс `ChannelGone`, `RetryLater`, `BadRequest`, `BadToken`."""
    return _FakeBotSend(channel, raises, message_id)


# --- виды, задания и очередь (контракт 3.1, 7.3) ---------------------------------------------------------

def register_kind(kind) -> None:
    """Регистрирует вид уведомлений и подписывает `dispatch` на его события (вызывать внутри `extensions.empty()`)."""
    try:
        from apps.core import events, extensions
        from apps.notify.services import dispatch
    except ImportError:
        pytest.fail("нет apps.notify.services.dispatch: помощник register_kind ждёт код среза 004 (CONTRACT-004 § 6.x)")
    extensions.register("notification_kinds", lambda: [kind])
    for name in kind.events:
        events.subscribe(name, dispatch.handler_for(name))


def run_jobs(queue_name: str = "notify") -> int:
    """Выполняет все задания очереди, стоящие к этому моменту, в этом же процессе и транзакции теста.

    Повторы по `due_at` не ждёт; возвращает число выполненных заданий."""
    import django_rq
    from rq.worker import SimpleWorker

    queue = django_rq.get_queue(queue_name)
    worker = SimpleWorker([queue], connection=queue.connection)
    worker.work(burst=True)
    worker.refresh()  # RQ 2.12: счётчики растут только в Valkey (hincrby)
    return worker.successful_job_count + worker.failed_job_count


def _tasks():
    try:
        from apps.notify import tasks
        return tasks
    except ImportError:
        pytest.fail("нет apps.notify.tasks: помощник ждёт код среза 004 (CONTRACT-004 § 7)")


def _commit_callbacks():
    """То же, что фикстура `django_capture_on_commit_callbacks(execute=True)`: исполняет и вложенные обработчики."""
    from django.db import DEFAULT_DB_ALIAS
    from django.test import TestCase

    return TestCase.captureOnCommitCallbacks(using=DEFAULT_DB_ALIAS, execute=True)


def run_tick() -> dict:
    """`tasks.notify_tick()` внутри `django_capture_on_commit_callbacks(execute=True)`; затем `run_jobs()`.

    Возвращает словарь `tick`."""
    tasks = _tasks()
    with _commit_callbacks():
        tick = tasks.notify_tick()
    run_jobs()
    return tick


def run_retention() -> dict:
    """`tasks.notify_retention()` напрямую; возвращает словарь `run`."""
    return _tasks().notify_retention()


def queued(function: str = "send_delivery", queue_name: str = "notify") -> list:
    """Задания очереди с `func_name == "apps.notify.tasks.<function>"`."""
    import django_rq

    return [job for job in django_rq.get_queue(queue_name).jobs if job.func_name == f"apps.notify.tasks.{function}"]


# --- разбор кадров /ws/notify/ (контракт 11.3) ------------------------------------------------------------

class Fragment(NamedTuple):
    tag: str
    attrs: dict
    text: str


_VOID_TAGS = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source",
                        "track", "wbr"})


class _FragmentParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.found: dict[str, Fragment] = {}
        self._depth = 0
        self._root = None   # (tag, attrs, [text])

    def handle_starttag(self, tag, attrs):
        if self._root is None:
            values = {name: ("" if value is None else value) for name, value in attrs}
            if tag in _VOID_TAGS:
                self._store(tag, values, "")
            else:
                self._root, self._depth = (tag, values, []), 1
        elif tag not in _VOID_TAGS:
            self._depth += 1

    def handle_startendtag(self, tag, attrs):
        if self._root is None:
            self._store(tag, {name: ("" if value is None else value) for name, value in attrs}, "")

    def handle_endtag(self, tag):
        if self._root is None or tag in _VOID_TAGS:
            return
        self._depth -= 1
        if self._depth == 0:
            root_tag, values, parts = self._root
            self._root = None
            self._store(root_tag, values, "".join(parts).strip())

    def handle_data(self, data):
        if self._root is not None:
            self._root[2].append(data)

    def _store(self, tag, values, text):
        self.found[values.get("id", "")] = Fragment(tag, values, text)


def ws_fragments(frame: str) -> dict[str, Fragment]:
    """Корневые элементы кадра: ключ — `id`, значение — `Fragment(tag, attrs, text)`; значения атрибутов
    разобраны (экранирование снято)."""
    parser = _FragmentParser()
    parser.feed(frame)
    parser.close()
    return parser.found


# --- соединение /ws/notify/ (контракт 11.4, решения 6 задач и C9) ----------------------------------------

def _application():
    """Приложение ASGI портала; закрытая функция, чтобы проба и тесты могли её подменить."""
    from config.asgi import application
    return application


class WsClient:
    """Одно соединение: `.accepted`, `.close_code`, `receive`, `wait_close`, `send`, `disconnect`."""

    def __init__(self, communicator):
        self._comm = communicator
        self.accepted: bool = False
        self.close_code: int | None = None
        self._finished = False

    def _raise_if_failed(self) -> None:
        future = self._comm.future
        if future.done() and not future.cancelled() and future.exception() is not None:
            raise future.exception()

    async def _next_output(self, timeout: float):
        """Следующий вывод приложения или `None` по тайм-ауту; приложение при тайм-ауте не отменяется
        (`receive_output` у `ApplicationCommunicator` отменило бы его)."""
        self._raise_if_failed()
        try:
            return await asyncio.wait_for(self._comm.output_queue.get(), timeout)
        except asyncio.TimeoutError:
            self._raise_if_failed()
            return None

    def _note_close(self, message) -> int:
        self.close_code = message.get("code", 1000)
        return self.close_code

    async def receive(self, timeout: float = 2.0) -> str | None:
        """Следующий текстовый кадр; `websocket.close` запоминается и даёт `None`; тайм-аут даёт `None`."""
        message = await self._next_output(timeout)
        if message is None:
            return None
        if message["type"] == "websocket.send":
            return message.get("text")
        if message["type"] == "websocket.close":
            self._note_close(message)
        return None

    async def wait_close(self, timeout: float = 2.0) -> int | None:
        """Читает выводы, пропуская текстовые кадры, до `websocket.close`; возвращает `code` или `None`."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            left = deadline - loop.time()
            if left <= 0:
                return None
            message = await self._next_output(left)
            if message is None:
                return None
            if message["type"] == "websocket.close":
                return self._note_close(message)

    async def send(self, text: str) -> None:
        await self._comm.send_input({"type": "websocket.receive", "text": text})

    async def disconnect(self) -> None:
        if self._finished:
            return
        self._finished = True
        await self._comm.send_input({"type": "websocket.disconnect", "code": 1000})
        await self._comm.wait(2)


class WsHub:
    """Открытые соединения одного сценария; создаётся `ws_run`."""

    def __init__(self):
        self._clients: list[WsClient] = []

    async def connect(self, client=None, *, origin: str | None = "http://testserver", cookie: str | None = None,
                      path: str = "/ws/notify/") -> WsClient:
        from asgiref.testing import ApplicationCommunicator

        headers = [(b"host", b"testserver")]
        if origin is not None:
            headers.append((b"origin", origin.encode("latin-1")))
        if cookie is None and client is not None:
            morsel = client.cookies.get(django_settings.SESSION_COOKIE_NAME)
            if morsel is not None:
                cookie = f"{django_settings.SESSION_COOKIE_NAME}={morsel.value}"
        if cookie:
            headers.append((b"cookie", cookie.encode("latin-1")))
        scope = {"type": "websocket", "path": path, "raw_path": path.encode("latin-1"), "query_string": b"",
                 "headers": headers, "client": ("127.0.0.1", 50000), "server": ("testserver", 80),
                 "scheme": "ws", "subprotocols": []}
        conn = WsClient(ApplicationCommunicator(_application(), scope))
        self._clients.append(conn)
        await conn._comm.send_input({"type": "websocket.connect"})
        message = await conn._next_output(2.0)
        if message is None:
            raise AssertionError(f"соединение {path}: нет ответа приложения за 2 с")
        if message["type"] == "websocket.accept":
            conn.accepted = True
        elif message["type"] == "websocket.close":
            conn.accepted = False
            conn._note_close(message)
            conn._finished = True
        else:
            raise AssertionError(f"соединение {path}: первый ответ — {message['type']}")
        return conn

    async def do(self, func, *args, **kwargs):
        """Вызов обычной функции в потоке теста (там же, где идут запросы к базе обработчика)."""
        return await sync_to_async(func)(*args, **kwargs)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(seconds)

    async def _close_all(self) -> None:
        for conn in self._clients:
            if conn._finished:
                continue
            with contextlib.suppress(Exception):
                await conn.disconnect()
            with contextlib.suppress(Exception):
                conn._comm.future.cancel()
        self._clients.clear()


def ws_run(scenario, *, timeout: float = 60.0):
    """Весь сценарий с соединениями — одним `async_to_sync(scenario)(hub)` (решение C9).

    По выходу, в том числе по исключению, все соединения отключаются и их приложения дожидаются.
    На время сценария `channels.db.close_old_connections` подменена пустой функцией: иначе
    `database_sync_to_async` закрыл бы соединение внутри транзакции теста; прежнее значение возвращается в `finally`."""
    import channels.db

    hub = WsHub()

    async def runner():
        try:
            return await asyncio.wait_for(scenario(hub), timeout)
        finally:
            await hub._close_all()

    saved = channels.db.close_old_connections
    channels.db.close_old_connections = lambda: None
    try:
        return async_to_sync(runner)()
    finally:
        channels.db.close_old_connections = saved
