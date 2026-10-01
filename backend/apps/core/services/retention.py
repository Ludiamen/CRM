"""Ночные очистки (T-222, FR-039, FR-045): регистрируются в `config/cron.py` для `rq cron`.

Журнал событий не трогает ни одна из них: срок его хранения — не меньше 3 лет,
а удаления по сроку нет вовсе.
"""
from datetime import timedelta

from django.contrib.sessions.models import Session
from django.utils import timezone

from apps.core.models import LoginAttempt, OneTimeLink, UserSession

from . import security_settings

# Просроченные ссылки удаляются после этого срока (коды стираются сразу по истечении)
LINK_KEEP = timedelta(days=30)


def purge_login_history() -> int:
    """Удаляет записи истории входов старше `login_history_days`; возвращает их число."""
    cutoff = timezone.now() - timedelta(days=security_settings.get().login_history_days)
    return LoginAttempt.objects.filter(at__lt=cutoff).delete()[0]


def purge_expired_links() -> int:
    """Стирает коды просроченных ссылок и удаляет давно просроченные; возвращает число затронутых."""
    now = timezone.now()
    erased = OneTimeLink.objects.filter(expires_at__lte=now).exclude(code_encrypted="").update(code_encrypted="")
    deleted = OneTimeLink.objects.filter(expires_at__lt=now - LINK_KEEP).delete()[0]
    return erased + deleted


def purge_expired_sessions() -> int:
    """Удаляет просроченные сессии Django и записи `UserSession`, у которых сессии больше нет."""
    expired = Session.objects.filter(expire_date__lt=timezone.now()).delete()[0]
    live = Session.objects.values_list("session_key", flat=True)
    orphans = UserSession.objects.exclude(session_key__in=live).delete()[0]
    return expired + orphans
