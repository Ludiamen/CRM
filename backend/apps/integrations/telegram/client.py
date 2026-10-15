"""Адаптер Telegram: getMe, getUpdates, sendMessage, deleteWebhook (PLAN-004, «Telegram и MAX» → «Адаптеры»).

Адрес и токен берутся из `settings.TELEGRAM_*` при каждом вызове. Токен стоит в пути запроса, поэтому адрес в тексты
исключений и в журнал не попадает (NFR-312). Текст в `send_message` не экранируется: `html.escape` делает вызывающая
служба доставки. Доверие TLS — системное хранилище.
"""
import json
import ssl
import urllib.request

from django.conf import settings

from apps.integrations import channel
from apps.integrations.channel import BadRequest, BadToken, ChannelError, ChannelGone, Response, RetryLater  # noqa: F401

POLL_SOCKET_TIMEOUT = 40   # опрос: ожидание на стороне Telegram 25 с плюс запас
SEND_SOCKET_TIMEOUT = 15   # отправка и прочие методы
POLL_WAIT = 25
MAX_TEXT = 4096
ALLOWED_UPDATES = ["message", "my_chat_member"]


def ssl_context() -> ssl.SSLContext:
    """Проверяющий контекст TLS с системным хранилищем сертификатов (корня Минцифры в нём нет)."""
    return ssl.create_default_context()


def transport(request: urllib.request.Request, timeout: float) -> Response:
    """Отправка запроса без перенаправлений; для адресов `https` — со своим контекстом TLS (подменяется в тестах)."""
    context = ssl_context() if request.full_url.lower().startswith("https:") else None
    return channel.send(request, timeout, context)


def _call(method: str, payload: dict | None, timeout: float, *, post: bool = True):
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        raise BadToken(method, 401)
    url = f"{settings.TELEGRAM_API_BASE.rstrip('/')}/bot{token}/{method}"
    if post:
        request = urllib.request.Request(url, data=json.dumps(payload or {}).encode("utf-8"), method="POST",
                                         headers={"Content-Type": "application/json"})
    else:
        request = urllib.request.Request(url, method="GET")
    answer = channel.call(method, transport, request, timeout)
    data = _json(answer)
    if 200 <= answer.status < 300:
        if not isinstance(data, dict) or data.get("ok") is not True:
            raise BadRequest(method, reason="bad_response")
        return data.get("result")
    after = None
    if answer.status == 429:
        params = data.get("parameters") if isinstance(data, dict) else None
        after = channel.retry_after(params.get("retry_after") if isinstance(params, dict) else None)
        if after is None:
            after = channel.retry_after(answer.headers.get("retry-after"))
    if answer.status == 409:
        raise RetryLater(method, 409)
    raise channel.error_for(method, answer.status, after=after)


def _json(answer: Response):
    try:
        return json.loads(answer.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None


def get_me() -> dict:
    """Описание бота (`username`); ссылка на бота — `https://t.me/<username>`."""
    return _call("getMe", None, SEND_SOCKET_TIMEOUT, post=False)


def get_updates(offset: int | None, *, timeout: int = POLL_WAIT) -> list[dict]:
    """События: `offset` — только при курсоре; ожидание на стороне Telegram `timeout` секунд."""
    payload = {"timeout": timeout, "allowed_updates": list(ALLOWED_UPDATES)}
    if offset is not None:
        payload["offset"] = offset
    return _call("getUpdates", payload, POLL_SOCKET_TIMEOUT)


def send_message(chat_id: str, text: str, *, button: tuple[str, str] | None = None) -> str:
    """Отправляет текст в чат (HTML, без предпросмотра ссылок), при `button=(подпись, адрес)` — с кнопкой-ссылкой."""
    payload = {"chat_id": chat_id, "text": text[:MAX_TEXT], "parse_mode": "HTML",
               "link_preview_options": {"is_disabled": True}}
    if button is not None:
        payload["reply_markup"] = {"inline_keyboard": [[{"text": button[0], "url": button[1]}]]}
    result = _call("sendMessage", payload, SEND_SOCKET_TIMEOUT)
    try:
        return str(result["message_id"])
    except (TypeError, KeyError):
        raise BadRequest("sendMessage", reason="bad_response") from None


def delete_webhook() -> None:
    """Снимает webhook (опрос не работает при заданном), ожидающие события не удаляет."""
    _call("deleteWebhook", {"drop_pending_updates": False}, SEND_SOCKET_TIMEOUT)
