"""Отправка Web Push (PLAN-004, «Где живёт код»): запрос к push-сервису через `urllib` без перенаправлений.

`transport` — заменяемая на уровне модуля точка (CONTRACT-004 § 5.1): тест подставляет свою функцию. Перенаправления не
выполняются: ответ 3xx возвращается как есть и считается неудачной попыткой без повторов (решение плана: адрес вводит
браузер, и портал не должен ходить по адресам, которые подсунул push-сервис). Исключения клиентов ботов здесь не
поднимаются: итог — `Sent` либо `SendError`. Адрес подписки и ключи в тексты ошибок не попадают (NFR-312).
"""
import urllib.error
import urllib.request
from email.utils import parsedate_to_datetime
from typing import NamedTuple

from django.conf import settings
from django.utils import timezone

from . import crypto

DEFAULT_TTL = 43200
DEFAULT_TIMEOUT = 10


class Sent(NamedTuple):
    """Ответ push-сервиса: код и секунды до повтора из `Retry-After` (или `None`)."""
    status: int
    retry_after: int | None


class SendError(Exception):
    """Запрос не получил ответа: `reason` — `"network"` или `"timeout"`."""

    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Перенаправление не исполняется: `urllib` отдаёт ответ 3xx как `HTTPError`, а `transport` — как `Response`."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def transport(request: urllib.request.Request, timeout: float):
    """Выполнить запрос; вернуть `apps.integrations.channel.Response`.

    `HTTPError` (в том числе 3xx) превращается в ответ, таймаут — в `TimeoutError`, прочие сбои сети — в `OSError`.
    """
    from apps.integrations.channel import Response

    opener = urllib.request.build_opener(_NoRedirect)
    try:
        with opener.open(request, timeout=timeout) as answer:
            return Response(answer.status, {name.lower(): value for name, value in answer.headers.items()},
                            answer.read())
    except urllib.error.HTTPError as error:
        try:
            body = error.read()
        except OSError:
            body = b""
        return Response(error.code, {name.lower(): value for name, value in error.headers.items()}, body)
    except TimeoutError:
        raise TimeoutError from None
    except urllib.error.URLError as error:
        if isinstance(error.reason, TimeoutError):
            raise TimeoutError from None
        raise OSError("network") from None
    except OSError:
        raise OSError("network") from None


def _retry_after(value: str | None) -> int | None:
    """Секунды из `Retry-After`: целое число или дата HTTP (от «сейчас» до даты, не меньше 0); иначе `None`."""
    if value is None:
        return None
    value = value.strip()
    if value.isascii() and value.isdigit():
        return int(value)
    try:
        moment = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return max(0, int((moment - timezone.now()).total_seconds()))


def send(subscription, payload: bytes, ttl: int = DEFAULT_TTL, urgency: str = "normal", topic: str | None = None,
         timeout: float = DEFAULT_TIMEOUT) -> Sent:
    """Зашифровать `payload` ключами подписки и отправить POST на её адрес.

    Ответ любого кода — `Sent`; сеть — `SendError("network")`, таймаут — `SendError("timeout")`; плохие ключи —
    `crypto.CryptoError`.
    """
    endpoint = subscription.endpoint
    body = crypto.encrypt(payload, subscription.p256dh, subscription.auth)
    headers = {
        "Authorization": crypto.vapid(endpoint, settings.VAPID_PRIVATE_KEY, settings.VAPID_SUBJECT),
        "TTL": str(ttl),
        "Urgency": urgency,
        "Content-Encoding": "aes128gcm",
        "Content-Type": "application/octet-stream",
    }
    if topic is not None:
        headers["Topic"] = topic
    request = urllib.request.Request(endpoint, data=body, headers=headers, method="POST")
    try:
        response = transport(request, timeout)
    except TimeoutError:
        raise SendError("timeout") from None
    except OSError:
        raise SendError("network") from None
    return Sent(response.status, _retry_after(response.headers.get("retry-after")))
