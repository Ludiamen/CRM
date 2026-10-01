"""Подключение и проверка TOTP (T-214, FR-021, FR-025, NFR-004, NFR-011).

Свои устройства django-otp без `ThrottlingMixin`: защита от перебора — наш сервис
блокировки. Ключ хранится только Fernet-токеном. Неверный код при подключении
считает вызывающий (`login.register_other_failure`, сценарий 3.4).
"""
import base64
import io
import os
from urllib.parse import quote, urlencode

import qrcode
from django.db import transaction

from apps.core.models import EncryptedTOTPDevice

from . import audit, crypto, portal_settings

KEY_BYTES = 20


def confirmed_device(user) -> EncryptedTOTPDevice | None:
    return EncryptedTOTPDevice.objects.filter(user=user, confirmed=True).order_by("-id").first()


def has_confirmed(user) -> bool:
    return EncryptedTOTPDevice.objects.filter(user=user, confirmed=True).exists()


def begin_enrollment(user) -> EncryptedTOTPDevice:
    """Устройство для подключения: создаётся при открытии страницы, повторное открытие даёт то же."""
    with transaction.atomic():
        device = EncryptedTOTPDevice.objects.filter(user=user, confirmed=False).order_by("-id").first()
        if device is None:
            device = EncryptedTOTPDevice.objects.create(
                user=user, name="default", confirmed=False,
                key_encrypted=crypto.encrypt(os.urandom(KEY_BYTES)), step=30, digits=6, tolerance=1, last_t=-1)
    return device


def secret_base32(device: EncryptedTOTPDevice) -> str:
    """Ключ для ручного ввода в приложение: base32 без выравнивания."""
    return base64.b32encode(device.key).decode().rstrip("=")


def provisioning_uri(device: EncryptedTOTPDevice) -> str:
    issuer = portal_settings.get().name
    label = quote(f"{issuer}:{device.user.email}")
    # otpauth:// — формат приложений-генераторов, а не адрес страницы: ключ в нём обязателен
    # и уходит только в QR-код и на экран подключения
    query = urlencode({"secret": secret_base32(device), "issuer": issuer, "digits": device.digits, "period": device.step})
    return f"otpauth://totp/{label}?{query}"


def qr_data_uri(device: EncryptedTOTPDevice) -> str:
    """QR-код в виде data: URI (CSP разрешает `img-src data:`)."""
    buffer = io.BytesIO()
    qrcode.make(provisioning_uri(device), box_size=6, border=2).save(buffer, format="PNG")
    return "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode()


def confirm_enrollment(user, code: str, *, ip=None) -> bool:
    """Подтверждает устройство верным кодом; другие устройства записи заменяются."""
    with transaction.atomic():
        device = EncryptedTOTPDevice.objects.select_for_update().filter(user=user, confirmed=False).order_by("-id").first()
        if device is None or not device.verify_token(code):
            return False
        EncryptedTOTPDevice.objects.filter(user=user, confirmed=True).exclude(pk=device.pk).delete()
        device.confirmed = True
        device.save(update_fields=["confirmed"])
        audit.record("totp.enrolled", actor=user, object_type="user", object_id=user.pk,
                     after={"confirmed": True}, ip=ip)
    return True


def verify(user, code: str) -> bool:
    device = confirmed_device(user)
    return bool(device and device.verify_token(code))
