"""Журнал исходящей почты (PLAN-001, «Модель данных»). Тело письма не хранится: в нём ссылка с кодом."""
from django.db import models
from django.utils import timezone


def now():
    """Время по умолчанию берётся при каждом обращении (подмена времени в тестах)."""
    return timezone.now()


class MailStatus(models.TextChoices):
    QUEUED = "queued", "в очереди"
    SENT = "sent", "отправлено"
    FAILED = "failed", "не доставлено"


class MailMessage(models.Model):
    to = models.CharField(max_length=254)
    template = models.CharField(max_length=64)
    subject = models.CharField(max_length=255, blank=True)
    status = models.CharField(max_length=16, choices=MailStatus.choices, default=MailStatus.QUEUED)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    created_at = models.DateTimeField(default=now)
    sent_at = models.DateTimeField(null=True, blank=True)
    related_user = models.ForeignKey("core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        default_permissions = ()
        indexes = [models.Index(fields=["related_user", "-created_at"], name="mail_msg_user_at")]


class MailAttempt(models.Model):
    """Результат каждой попытки доставки — журнал, видимый администратору (FR-053)."""

    message = models.ForeignKey(MailMessage, on_delete=models.CASCADE, related_name="attempt_log")
    at = models.DateTimeField(default=now)
    ok = models.BooleanField()
    error = models.TextField(blank=True)

    class Meta:
        default_permissions = ()
