"""Сессии: запись по каждой, бездействие, ограниченная сессия (T-219, FR-021, FR-028…030).

Сессии Django лежат в базе; рядом с каждой — строка `UserSession`, по ней сессии
закрываются по одной. Время бездействия запоминается в сессии при её создании:
изменённая политика действует для новых сессий (сценарий 10.2).
"""
from datetime import timedelta

from django.contrib.auth import login, logout
from django.contrib.sessions.models import Session
from django.utils import timezone

from apps.core.models import UserSession

from . import audit, security_settings

BACKEND = "django.contrib.auth.backends.ModelBackend"
IDLE_KEY = "idle_timeout_minutes"
LIMITED_KEY = "limited"


def start(request, user, *, device=None, ip=None, limited: bool = False) -> UserSession:
    """Открывает сессию Django, запоминает порог бездействия и заводит `UserSession`."""
    login(request, user, backend=BACKEND)
    request.session[IDLE_KEY] = security_settings.get().idle_timeout_minutes
    if limited:
        request.session[LIMITED_KEY] = True
    else:
        request.session.pop(LIMITED_KEY, None)
    request.session.save()
    now = timezone.now()
    return UserSession.objects.create(
        user=user, session_key=request.session.session_key, device=device, ip=ip or None,
        created_at=now, last_activity=now)


def is_limited(request) -> bool:
    return bool(request.session.get(LIMITED_KEY))


def finish_limited(request) -> None:
    """Второй фактор подключён и коды подтверждены: ограничение снимается."""
    request.session.pop(LIMITED_KEY, None)


def idle_expired(session_row: UserSession, request) -> bool:
    minutes = request.session.get(IDLE_KEY) or security_settings.get().idle_timeout_minutes
    return timezone.now() - session_row.last_activity > timedelta(minutes=minutes)


def touch(session_row: UserSession) -> None:
    session_row.last_activity = timezone.now()
    session_row.save(update_fields=["last_activity"])


def end(request) -> None:
    """Выход: запись и сессия Django удаляются."""
    key = request.session.session_key
    if key:
        UserSession.objects.filter(session_key=key).delete()
    logout(request)


def close(qs) -> int:
    """Закрывает сессии из выборки `UserSession`: удаляет сессии Django и сами записи."""
    keys = list(qs.values_list("session_key", flat=True))
    if not keys:
        return 0
    Session.objects.filter(session_key__in=keys).delete()
    return UserSession.objects.filter(session_key__in=keys).delete()[0]


def close_all(user, *, except_key: str | None = None) -> int:
    """Закрывает все сессии записи, кроме указанной (выход со всех устройств, смена пароля, блокировка)."""
    qs = UserSession.objects.filter(user=user)
    if except_key:
        qs = qs.exclude(session_key=except_key)
    return close(qs)


def keep_after_password_change(request, user) -> None:
    """Смена пароля меняет хеш сессии Django: текущая сессия остаётся действующей."""
    from django.contrib.auth import update_session_auth_hash

    old_key = request.session.session_key
    update_session_auth_hash(request, user)  # меняет и ключ сессии (cycle_key)
    new_key = request.session.session_key
    if old_key and new_key and old_key != new_key:
        UserSession.objects.filter(session_key=old_key).update(session_key=new_key)



def logout_everywhere(request, user, *, ip=None) -> int:
    """«Выйти со всех устройств»: остальные сессии закрываются, текущая остаётся; событие — в журнал (FR-030)."""
    closed = close_all(user, except_key=request.session.session_key)
    audit.record("sessions.logout_everywhere", actor=user, object_type="user", object_id=user.pk,
                 after={"closed": closed}, ip=ip)
    return closed
