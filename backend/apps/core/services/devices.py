"""Известные устройства и история входов (T-222, FR-039…043).

Устройство узнаётся по долгоживущей куке `HttpOnly` со случайным значением; в базе
лежит только SHA-256 значения. Браузер и платформа — из User-Agent (`ua-parser`).
Геопозиция по адресу IP не определяется и не хранится (FR-043).
"""
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone
from ua_parser import parse as parse_user_agent_string

from apps.core.models import KnownDevice, LoginAttempt, LoginResult, UserSession

from . import crypto

COOKIE_NAME = "portal_device"
COOKIE_MAX_AGE = 400 * 24 * 3600  # около 13 месяцев


@dataclass(frozen=True)
class Touched:
    device: KnownDevice
    raw_key: str       # значение куки, которое нужно выставить клиенту
    is_new: bool


def parse_user_agent(user_agent: str) -> tuple[str, str]:
    """Возвращает (браузер, платформа); для неопознанного — пустые строки."""
    result = parse_user_agent_string(user_agent or "")
    browser = platform = ""
    if result.user_agent is not None and result.user_agent.family and result.user_agent.family != "Other":
        browser = result.user_agent.family
        if result.user_agent.major:
            browser = f"{browser} {result.user_agent.major}"
    if result.os is not None and result.os.family and result.os.family != "Other":
        platform = result.os.family
    return browser[:128], platform[:128]


def has_history(user) -> bool:
    """Был ли у записи хоть один вход или устройство (иначе это первый вход после активации)."""
    return (KnownDevice.objects.filter(user=user).exists()
            or LoginAttempt.objects.filter(user=user, result__in=[LoginResult.SUCCESS, LoginResult.BACKUP_CODE]).exists())


def touch(user, raw_key: str | None, user_agent: str) -> Touched:
    """Узнаёт устройство по значению куки или заводит новое."""
    browser, platform = parse_user_agent(user_agent)
    raw_key = raw_key or crypto.new_device_key()
    digest = crypto.sha256_hex(raw_key)
    now = timezone.now()
    with transaction.atomic():
        device, created = KnownDevice.objects.get_or_create(
            user=user, device_key_hash=digest,
            defaults={"browser": browser, "platform": platform, "first_seen": now, "last_seen": now})
        if not created:
            device.browser, device.platform, device.last_seen = browser or device.browser, platform or device.platform, now
            device.save(update_fields=["browser", "platform", "last_seen"])
    return Touched(device, raw_key, created)


def known_devices(user):
    return KnownDevice.objects.filter(user=user).order_by("-last_seen", "-id")


def _own(user, device_id) -> KnownDevice | None:
    try:
        return KnownDevice.objects.filter(user=user, pk=int(device_id)).first()
    except (TypeError, ValueError):
        return None


def close_sessions(user, device_id) -> bool:
    """«Закрыть сессию» устройства: сессии завершаются, следующий вход с него — снова новое устройство."""
    from . import sessions

    device = _own(user, device_id)
    if device is None:
        return False
    with transaction.atomic():
        sessions.close(UserSession.objects.filter(user=user, device=device))
        device.delete()
    return True


def forget(user, device_id) -> bool:
    """«Забыть» устройство: оно исчезает из списка, следующий вход с него — новое устройство."""
    device = _own(user, device_id)
    if device is None:
        return False
    device.delete()
    return True


def history(user):
    """История входов записи по убыванию времени (неудачи тоже)."""
    return LoginAttempt.objects.filter(user=user).select_related("device").order_by("-at", "-id")
