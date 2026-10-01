"""Ссылки, второй фактор, известные устройства (PLAN-001, «Модель данных»)."""
import hmac
import time

from django.db import models, transaction
from django_otp.models import Device
from django_otp.oath import TOTP

from apps.core.services import crypto

from ._util import now


class LinkPurpose(models.TextChoices):
    ACTIVATION = "activation", "активация"
    RESET = "reset", "восстановление пароля"


class OneTimeLink(models.Model):
    """Одноразовая ссылка. В базе: SHA-256 кода (поиск) и Fernet-токен (показ и отправка)."""

    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="links")
    purpose = models.CharField(max_length=16, choices=LinkPurpose.choices)
    token_hash = models.CharField(max_length=64, unique=True)
    # пусто после использования, гашения и истечения срока
    code_encrypted = models.TextField(blank=True)
    created_at = models.DateTimeField(default=now)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey("core.User", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        default_permissions = ()
        indexes = [models.Index(fields=["user", "purpose"], name="core_link_user_purpose")]


class EncryptedTOTPDevice(Device):
    """Устройство TOTP с ключом под Fernet.

    Встроенный ThrottlingMixin не подмешивается: пауза django-otp после неверных
    кодов отвергала бы верный код поверх нашей блокировки (PLAN-001).
    """

    key_encrypted = models.TextField()
    step = models.PositiveSmallIntegerField(default=30)
    digits = models.PositiveSmallIntegerField(default=6)
    tolerance = models.PositiveSmallIntegerField(default=1)
    last_t = models.BigIntegerField(default=-1, help_text="шаг последнего принятого кода (защита от повтора)")

    class Meta(Device.Meta):
        default_permissions = ()

    @property
    def key(self) -> bytes:
        return crypto.decrypt(self.key_encrypted)

    def verify_token(self, token):
        """Код принимается с допуском ±tolerance шагов, один раз и только вперёд по времени."""
        token = str(token).strip().replace(" ", "")
        if not (token.isascii() and token.isdigit() and len(token) == self.digits):
            return False
        with transaction.atomic():
            locked = type(self).objects.select_for_update().get(pk=self.pk)
            totp = TOTP(locked.key, step=locked.step, digits=locked.digits)
            totp.time = time.time()
            if not totp.verify(int(token), tolerance=locked.tolerance, min_t=locked.last_t + 1):
                return False
            locked.last_t = totp.t()
            locked.save(update_fields=["last_t"])
        self.last_t = locked.last_t
        return True


class BackupCodeDevice(Device):
    """Набор резервных кодов; сами коды — строки BackupCode с HMAC."""

    class Meta(Device.Meta):
        default_permissions = ()

    def verify_token(self, token):
        """Резервный код срабатывает один раз; проверка под select_for_update."""
        digest = crypto.backup_code_hash(crypto.normalize_backup_code(token))
        if not digest:
            return False
        with transaction.atomic():
            code = (BackupCode.objects.select_for_update()
                    .filter(device_id=self.pk, used_at__isnull=True).filter(code_hash=digest).first())
            if code is None or not hmac.compare_digest(code.code_hash, digest):
                return False
            code.used_at = now()
            code.save(update_fields=["used_at"])
        return True

    def remaining(self) -> int:
        return BackupCode.objects.filter(device_id=self.pk, used_at__isnull=True).count()


class BackupCode(models.Model):
    device = models.ForeignKey(BackupCodeDevice, on_delete=models.CASCADE, related_name="codes")
    # hex от HMAC-SHA256(BACKUP_CODE_PEPPER, код); сам код не хранится
    code_hash = models.CharField(max_length=64, db_index=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        default_permissions = ()


class KnownDevice(models.Model):
    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="known_devices")
    # SHA-256 случайного идентификатора из долгоживущей куки; значение куки в базе не лежит
    device_key_hash = models.CharField(max_length=64)
    browser = models.CharField(max_length=128, blank=True)
    platform = models.CharField(max_length=128, blank=True)
    first_seen = models.DateTimeField(default=now)
    last_seen = models.DateTimeField(default=now)

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["user", "device_key_hash"], name="core_knowndevice_uniq")]

    def __str__(self):
        return f"{self.browser} / {self.platform}"
