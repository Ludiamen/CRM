"""Настройки безопасности и портала, история паролей (PLAN-001, «Модель данных»)."""
from django.db import models

from ._util import now


class SecuritySettings(models.Model):
    """Одна строка; значения по умолчанию задаёт миграция данных (NFR-005, ADR-0006).

    Читается из базы при каждом запросе, без кэша.
    """

    password_min_length = models.PositiveIntegerField(default=12)
    password_history = models.PositiveIntegerField(default=5)
    password_max_age_days = models.PositiveIntegerField(null=True, blank=True, default=None)
    idle_timeout_minutes = models.PositiveIntegerField(default=60)
    account_lock_limit = models.PositiveIntegerField(default=5)
    account_lock_minutes = models.PositiveIntegerField(default=15)
    ip_lock_limit = models.PositiveIntegerField(default=20)
    ip_lock_min_accounts = models.PositiveIntegerField(default=3)
    ip_lock_window_minutes = models.PositiveIntegerField(default=15)
    ip_lock_minutes = models.PositiveIntegerField(default=15)
    login_history_days = models.PositiveIntegerField(default=365)

    class Meta:
        default_permissions = ()


class PasswordHistory(models.Model):
    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="password_history")
    password_hash = models.CharField(max_length=255)
    created_at = models.DateTimeField(default=now)

    class Meta:
        default_permissions = ()
        indexes = [models.Index(fields=["user", "-created_at"], name="core_pwdhist_user_at")]


class PortalSettings(models.Model):
    """Одна строка: название и логотип (только PNG и JPEG, FR-049)."""

    name = models.CharField(max_length=100)
    logo = models.ImageField(upload_to="logo/", blank=True)
    updated_at = models.DateTimeField(default=now)

    class Meta:
        default_permissions = ()
