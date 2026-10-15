"""Общее для адаптеров Telegram, MAX и Web Push: ответ, исключения, транспорт (PLAN-004, CONTRACT-004 § 5.1).

Исключения несут метод и код ответа, но не адрес запроса и не заголовки: у Telegram в адресе токен бота (NFR-312).
Транспорт — на `urllib`, без обработчика перенаправлений: ответ 3xx возвращается как `Response`, а не исполняется.
"""
import http.client
import socket
import ssl
import urllib.error
import urllib.request
from typing import NamedTuple


class Response(NamedTuple):
    """Ответ внешнего сервиса: код, заголовки (ключи в нижнем регистре) и тело."""
    status: int
    headers: dict
    body: bytes


class ChannelError(Exception):
    """Сбой отправки через канал; `str` — «<метод> <код>» или «<метод> <причина>», без адреса запроса."""

    def __init__(self, method: str, code: int | None = None, *, reason: str = ""):
        super().__init__(method, code, reason)
        self.method = method
        self.code = code
        self.reason = reason

    def __str__(self) -> str:
        return f"{self.method} {self.code if self.code is not None else self.reason}".rstrip()


class ChannelGone(ChannelError):
    """Ответ 403: бот заблокирован, пользователь удалён или остановил бота."""


class RetryLater(ChannelError):
    """429, 5xx, сеть, таймаут (и 409 у Telegram): повторить позже; `after` — секунды до повтора, если сервис назвал."""

    def __init__(self, method: str, code: int | None = None, *, reason: str = "", after: int | None = None):
        super().__init__(method, code, reason=reason)
        self.after = after


class BadRequest(ChannelError):
    """Ответ 400 и любой другой неповторяемый ответ."""


class BadToken(ChannelError):
    """Ответ 401: токен не принят — ошибка настройки, не пользователя."""


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Перенаправление не исполняется: `urllib` превращает такой ответ в `HTTPError`, а мы — в `Response`."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _lower(headers) -> dict:
    return {str(name).lower(): value for name, value in headers.items()}


def send(request: urllib.request.Request, timeout: float, context: ssl.SSLContext | None = None) -> Response:
    """Настоящая отправка: ответ любого кода — `Response`; таймаут — `TimeoutError`, прочие сбои сети — `OSError`.

    `context` (проверка TLS) применяется к адресам `https`; для `http` его передавать не нужно."""
    handlers: list = [_NoRedirect()]
    if context is not None:
        handlers.append(urllib.request.HTTPSHandler(context=context))
    opener = urllib.request.build_opener(*handlers)
    try:
        with opener.open(request, timeout=timeout) as answer:
            return Response(answer.status, _lower(answer.headers), answer.read())
    except urllib.error.HTTPError as exc:
        try:
            body = exc.read()
        except (OSError, http.client.HTTPException):
            body = b""
        return Response(exc.code, _lower(exc.headers), body)
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (TimeoutError, socket.timeout)):
            raise TimeoutError("timeout") from None
        raise OSError("network") from None
    except TimeoutError:
        raise TimeoutError("timeout") from None
    except (OSError, http.client.HTTPException):
        raise OSError("network") from None


def call(method: str, transport, request: urllib.request.Request, timeout: float) -> Response:
    """Запрос через `transport` клиента; таймаут и сбой сети — `RetryLater` с причиной, без текста исходного сбоя."""
    try:
        return transport(request, timeout)
    except TimeoutError:
        raise RetryLater(method, reason="timeout") from None
    except OSError:
        raise RetryLater(method, reason="network") from None


def retry_after(value) -> int | None:
    """Секунды из заголовка `Retry-After` или поля `retry_after`; непонятное значение — `None`."""
    try:
        seconds = int(str(value).strip())
    except (TypeError, ValueError):
        return None
    return seconds if seconds >= 0 else None


def error_for(method: str, status: int, *, after: int | None = None) -> ChannelError:
    """Исключение по коду ответа (401 BadToken, 403 ChannelGone, 400 BadRequest, 429 и 5xx RetryLater, иное BadRequest)."""
    if status == 401:
        return BadToken(method, status)
    if status == 403:
        return ChannelGone(method, status)
    if status == 429 or status >= 500:
        return RetryLater(method, status, after=after if status == 429 else None)
    return BadRequest(method, status)
