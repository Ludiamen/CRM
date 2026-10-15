"""Адаптер MAX: GET /me, GET /updates, POST /messages (PLAN-004, «Telegram и MAX» → «Адаптеры»).

Адрес и токен берутся из `settings.MAX_*` при каждом вызове; токен идёт в заголовке `Authorization` (без слова Bearer),
в адрес и тело не попадает. Доверие TLS — только корень Минцифры из `certs/` (системное хранилище не загружается).
Текст в `send_message` не экранируется: `html.escape` делает вызывающая служба доставки.
"""
import json
import pathlib
import ssl
import urllib.parse
import urllib.request

from django.conf import settings

from apps.integrations import channel
from apps.integrations.channel import BadRequest, BadToken, ChannelError, ChannelGone, Response, RetryLater  # noqa: F401

CA_FILE = pathlib.Path(__file__).parent / "certs" / "russian_trusted_root_ca.crt"
POLL_SOCKET_TIMEOUT = 40   # опрос: ожидание на стороне MAX 25 с плюс запас
SEND_SOCKET_TIMEOUT = 15   # отправка и прочие методы
POLL_WAIT = 25
MAX_TEXT = 4000
UPDATE_TYPES = "bot_started,bot_stopped,message_created"

GET_ME = "GET /me"
GET_UPDATES = "GET /updates"
POST_MESSAGES = "POST /messages"


def ssl_context() -> ssl.SSLContext:
    """Контекст TLS только с корнем Минцифры: `cafile` задан, системное хранилище не загружается."""
    return ssl.create_default_context(cafile=str(CA_FILE))


def transport(request: urllib.request.Request, timeout: float) -> Response:
    """Отправка запроса без перенаправлений; для адресов `https` — с контекстом MAX (подменяется в тестах)."""
    context = ssl_context() if request.full_url.lower().startswith("https:") else None
    return channel.send(request, timeout, context)


def _call(method: str, verb: str, path: str, query: dict, payload: dict | None, timeout: float) -> dict:
    token = settings.MAX_BOT_TOKEN
    if not token:
        raise BadToken(method, 401)
    url = settings.MAX_API_BASE.rstrip("/") + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    headers = {"Authorization": token}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=data, method=verb, headers=headers)
    answer = channel.call(method, transport, request, timeout)
    if 200 <= answer.status < 300:
        try:
            body = json.loads(answer.body.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            body = None
        if not isinstance(body, dict):
            raise BadRequest(method, reason="bad_response")
        return body
    raise channel.error_for(method, answer.status, after=channel.retry_after(answer.headers.get("retry-after")))


def get_me() -> dict:
    """Описание бота (`username`); ссылка на бота — `https://max.ru/<username>`."""
    return _call(GET_ME, "GET", "/me", {}, None, SEND_SOCKET_TIMEOUT)


def get_updates(marker: int | None, *, timeout: int = POLL_WAIT) -> tuple[list[dict], int | None]:
    """События и `marker` из ответа; `marker` в запрос идёт только при курсоре."""
    query = {"timeout": timeout, "types": UPDATE_TYPES}
    if marker is not None:
        query["marker"] = marker
    body = _call(GET_UPDATES, "GET", "/updates", query, None, POLL_SOCKET_TIMEOUT)
    updates = body.get("updates")
    return (updates if isinstance(updates, list) else []), body.get("marker")


def send_message(chat_id: str, text: str, *, button: tuple[str, str] | None = None) -> str:
    """Отправляет текст в чат (`format=html`), при `button=(подпись, адрес)` — с кнопкой-ссылкой; возвращает `mid`."""
    payload = {"text": text[:MAX_TEXT], "format": "html"}
    if button is not None:
        payload["attachments"] = [{"type": "inline_keyboard", "payload": {
            "buttons": [[{"type": "link", "text": button[0], "url": button[1]}]]}}]
    body = _call(POST_MESSAGES, "POST", "/messages", {"chat_id": chat_id}, payload, SEND_SOCKET_TIMEOUT)
    try:
        return str(body["message"]["body"]["mid"])
    except (TypeError, KeyError):
        raise BadRequest(POST_MESSAGES, reason="bad_response") from None
