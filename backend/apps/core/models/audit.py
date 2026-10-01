"""Сессии, история входов и журнал событий (PLAN-001, «Модель данных»)."""
from django.db import models

from ._util import now


class UserSession(models.Model):
    """Сессия сотрудника: по ней сессии закрываются по одной (FR-030, FR-040)."""

    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="user_sessions")
    session_key = models.CharField(max_length=40, unique=True)
    device = models.ForeignKey("core.KnownDevice", null=True, blank=True, on_delete=models.SET_NULL, related_name="sessions")
    created_at = models.DateTimeField(default=now)
    last_activity = models.DateTimeField(default=now)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        default_permissions = ()


class LoginResult(models.TextChoices):
    SUCCESS = "success", "успешно"
    BAD_PASSWORD = ("bad_password", "неверный пароль")
    BAD_CODE = "bad_code", "неверный код"
    LOCKED = "locked", "блокировка записи"
    IP_LOCKED = "ip_locked", "блокировка адреса"
    BACKUP_CODE = "backup_code", "вход по резервному коду"


class LoginAttempt(models.Model):
    """История входов. Геопозиция по адресу не определяется и не хранится (FR-043)."""

    user = models.ForeignKey("core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="login_attempts")
    at = models.DateTimeField(default=now)
    ip = models.GenericIPAddressField(null=True, blank=True)
    browser = models.CharField(max_length=128, blank=True)
    platform = models.CharField(max_length=128, blank=True)
    device = models.ForeignKey("core.KnownDevice", null=True, blank=True, on_delete=models.SET_NULL, related_name="attempts")
    result = models.CharField(max_length=16, choices=LoginResult.choices)

    class Meta:
        default_permissions = ()
        indexes = [
            models.Index(fields=["-at"], name="core_login_at"),
            models.Index(fields=["user", "-at"], name="core_login_user_at"),
        ]


class AuditEvent(models.Model):
    """Журнал событий: только дописывается.

    У роли приложения в базе нет UPDATE и DELETE на эту таблицу (миграция прав);
    внешний ключ `actor` — PROTECT, потому что SET_NULL был бы UPDATE журнала.
    """

    at = models.DateTimeField(default=now)
    actor = models.ForeignKey("core.User", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    action = models.CharField(max_length=64)
    object_type = models.CharField(max_length=64, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    before = models.JSONField(default=dict, blank=True)
    after = models.JSONField(default=dict, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        default_permissions = ()
        indexes = [
            models.Index(fields=["-at"], name="core_audit_at"),
            models.Index(fields=["actor", "-at"], name="core_audit_actor_at"),
            models.Index(fields=["action", "-at"], name="core_audit_action_at"),
            models.Index(fields=["object_type", "object_id"], name="core_audit_object"),
        ]
