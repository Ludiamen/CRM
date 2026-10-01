"""Резервные коды (T-215, FR-022, FR-023, FR-025, NFR-011).

Выпускается набор из 10 кодов (12 знаков случайного алфавита без похожих символов),
показывается один раз; в базе — только HMAC-SHA256 с секретом из окружения.
Новый набор гасит прежний.
"""
from django.db import transaction

from apps.core.models import BackupCode, BackupCodeDevice

from . import audit, crypto

SET_SIZE = 10


def device_of(user) -> BackupCodeDevice | None:
    return BackupCodeDevice.objects.filter(user=user).order_by("-id").first()


def remaining(user) -> int:
    device = device_of(user)
    return device.remaining() if device else 0


def issue(user, *, actor=None, ip=None) -> list[str]:
    """Выпускает новый набор из 10 кодов, прежний гасится; создаёт устройство при его отсутствии."""
    with transaction.atomic():
        device = BackupCodeDevice.objects.select_for_update().filter(user=user).order_by("-id").first()
        if device is None:
            device = BackupCodeDevice.objects.create(user=user, name="backup", confirmed=True)
        else:
            if not device.confirmed:
                device.confirmed = True
                device.save(update_fields=["confirmed"])
            device.codes.all().delete()
        codes = []
        while len(codes) < SET_SIZE:
            code = crypto.new_backup_code()
            if code not in codes:
                codes.append(code)
        BackupCode.objects.bulk_create([BackupCode(device=device, code_hash=crypto.backup_code_hash(c)) for c in codes])
        audit.record("backup_codes.issued", actor=actor or user, object_type="user", object_id=user.pk,
                     after={"count": len(codes)}, ip=ip)
    return codes


def verify(user, code: str) -> bool:
    """Проверяет и гасит резервный код; событие `backup_code.used` пишется при успехе."""
    for device in BackupCodeDevice.objects.filter(user=user):
        if device.verify_token(code):
            audit.record("backup_code.used", actor=user, object_type="user", object_id=user.pk,
                         after={"remaining": device.remaining()})
            return True
    return False
