"""Публичный интерфейс уведомлений: подписки Web Push (PLAN-004, «Web Push» — «Подписка», «Выход из портала»;
CONTRACT-004, 6.12). Службы журнала пишут `notify.push_subscribed` и `notify.push_removed` (9.2): ни адреса подписки,
ни ключей в журнал не попадает."""
import re
from urllib.parse import urlsplit

from django.conf import settings
from django.db import transaction
from django.http import Http404

from apps.core.services import audit, devices

from ..models import PushSubscription
from .errors import NotifyError

MAX_ENDPOINT = 1000
MAX_SUBSCRIPTIONS = 10

_BASE64URL = re.compile(r"^[A-Za-z0-9_-]+={0,2}$")


def _host_allowed(host: str) -> bool:
    """Имя хоста сверяется целиком; шаблон `*.<хост>` — хост оканчивается на `.<хост>`, без учёта регистра."""
    for entry in settings.WEBPUSH_ALLOWED_HOSTS:
        entry = str(entry).strip().lower()
        if not entry:
            continue
        if entry.startswith("*."):
            if host.endswith(entry[1:]):
                return True
        elif host == entry:
            return True
    return False


def check_endpoint(endpoint: str) -> None:
    """Проверяет адрес подписки: длина, разбор, `https`, логин, порт, хост (порядок — 6.2)."""
    endpoint = endpoint if isinstance(endpoint, str) else ""
    if len(endpoint) > MAX_ENDPOINT:
        raise NotifyError("too_long", "Адрес подписки слишком длинный.", field="endpoint")
    if not endpoint.strip():
        raise NotifyError("bad_endpoint", "Адрес подписки не указан.", field="endpoint")
    try:
        parts = urlsplit(endpoint)
        host = parts.hostname
        port = parts.port
    except ValueError:
        raise NotifyError("bad_endpoint", "Адрес подписки не разобрать.", field="endpoint") from None
    if not host:
        raise NotifyError("bad_endpoint", "Адрес подписки не разобрать.", field="endpoint")
    if parts.scheme.lower() != "https":
        raise NotifyError("bad_scheme", "Адрес подписки должен начинаться с https.", field="endpoint")
    if parts.username is not None or parts.password is not None:
        raise NotifyError("has_credentials", "В адресе подписки не должно быть логина и пароля.", field="endpoint")
    if port not in (None, 443):
        raise NotifyError("bad_port", "Адрес подписки указывает на недопустимый порт.", field="endpoint")
    if not _host_allowed(host.lower()):
        raise NotifyError("bad_host", "Этот push-сервис не разрешён администратором.", field="endpoint")


def _check_key(value, field: str, limit: int) -> None:
    if not isinstance(value, str) or not value or len(value) > limit or not _BASE64URL.match(value):
        raise NotifyError("bad_keys", "Ключи подписки неверны.", field=field)


def _remove(subscription: PushSubscription, *, actor=None, ip=None, reason: str = "") -> None:
    """Удаляет подписку и пишет `notify.push_removed`: объект — владелец; у системы в «стало» `reason`."""
    audit.record("notify.push_removed", actor=actor, object_type="user", object_id=subscription.user_id,
                 before={"browser": subscription.browser, "platform": subscription.platform},
                 after={"reason": reason} if reason else {}, ip=ip)
    subscription.delete()


def save(user, *, endpoint, p256dh, auth, device_id=None, user_agent="", ip=None) -> PushSubscription:
    """Сохраняет подписку: адрес с другой учётной записи переносится (`moved`), лишняя сверх 10 уходит (`limit`)."""
    check_endpoint(endpoint)
    _check_key(p256dh, "p256dh", 128)
    _check_key(auth, "auth", 64)
    browser, platform = devices.parse_user_agent(user_agent)
    with transaction.atomic():
        for other in PushSubscription.objects.select_for_update().filter(endpoint=endpoint).exclude(user=user):
            _remove(other, reason="moved")
        existing = PushSubscription.objects.select_for_update().filter(endpoint=endpoint, user=user).first()
        if existing is not None:
            existing.p256dh, existing.auth, existing.device_id = p256dh, auth, device_id
            existing.browser, existing.platform = browser, platform
            existing.save(update_fields=["p256dh", "auth", "device", "browser", "platform"])
            return existing
        subscription = PushSubscription.objects.create(
            user=user, endpoint=endpoint, p256dh=p256dh, auth=auth, device_id=device_id,
            browser=browser, platform=platform)
        audit.record("notify.push_subscribed", actor=user, object_type="user", object_id=user.pk,
                     after={"browser": browser, "platform": platform}, ip=ip)
        excess = PushSubscription.objects.filter(user=user).order_by("-created_at", "-pk")[MAX_SUBSCRIPTIONS:]
        for old in list(excess):
            _remove(old, reason="limit")
        return subscription


def list_for(user_id) -> list[PushSubscription]:
    """Подписки сотрудника, новые первыми."""
    return list(PushSubscription.objects.filter(user_id=user_id).order_by("-created_at", "-pk"))


def delete(user, subscription_id, *, ip=None) -> None:
    """Сотрудник удаляет свою подписку; чужая или несуществующая — `Http404`."""
    with transaction.atomic():
        subscription = PushSubscription.objects.select_for_update().filter(pk=subscription_id, user=user).first()
        if subscription is None:
            raise Http404("Подписка не найдена.")
        _remove(subscription, actor=user, ip=ip)


def drop(subscription_id, *, reason: str) -> None:
    """Система удаляет подписку (`gone`, `logout`, `dismissed`, `moved`, `limit`); нет подписки — ничего."""
    with transaction.atomic():
        subscription = PushSubscription.objects.select_for_update().filter(pk=subscription_id).first()
        if subscription is not None:
            _remove(subscription, reason=reason)


def on_logged_out(*, user_id, device_ids, reason) -> None:
    """Подписчик `core.logged_out`: удаляет подписки сотрудника устройств из события; без устройства — остаются."""
    device_ids = [d for d in (device_ids or []) if d]
    if not device_ids:
        return
    with transaction.atomic():
        for subscription in list(PushSubscription.objects.select_for_update()
                                 .filter(user_id=user_id, device_id__in=device_ids)):
            _remove(subscription, reason="logout")
