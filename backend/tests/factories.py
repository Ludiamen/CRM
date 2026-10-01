"""Общие помощники и фабрики тестов (T-010).

Пароли создаются только через `new_password()` (secrets.token_urlsafe), а не
литералом — решение владельца 2026-09-29, инвариант «секреты-вне-кода».

Фабрики пользователей, ролей и ссылок берут модели через `apps.get_model` и
работают, когда модели Этапа 3 появятся (поля — по таблице «Модель данных»
PLAN-001); до этого вызов даёт понятную ошибку.
"""
import hashlib
import json
import os
import secrets
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from unittest import mock

from django.apps import apps
from django.conf import settings
from django.utils import timezone


def new_password() -> str:
    """Случайный пароль для теста: 22 знака, проходит политику длины 12."""
    return secrets.token_urlsafe(16)


def new_email(prefix: str = "user") -> str:
    return f"{prefix}-{secrets.token_hex(4)}@example.com"


# --- Коды TOTP ----------------------------------------------------------------

def totp_code(key: bytes, *, at: float | None = None, step: int = 30,
              digits: int = 6, drift: int = 0) -> str:
    """Код TOTP на django_otp.oath (как у устройства: шаг 30 с, 6 знаков).

    `at` — момент в секундах Unix (по умолчанию сейчас), `drift` — сдвиг в шагах
    (±1 — допуск устройства).
    """
    from django_otp.oath import TOTP

    totp = TOTP(key, step=step, digits=digits, drift=drift)
    if at is not None:
        totp.time = at
    return str(totp.token()).zfill(digits)


# --- Время --------------------------------------------------------------------

class Clock:
    """Задаёт «сейчас» для сроков ссылок и блокировок.

    Подменяет `django.utils.timezone.now`, поэтому код под тестом обязан
    звать `timezone.now()` (а не `datetime.now()`). Valkey и RQ живут по
    настоящему времени.
    """

    def __init__(self):
        self._now = timezone.now()
        self._patch = mock.patch("django.utils.timezone.now", side_effect=lambda: self._now)

    def start(self):
        self._patch.start()
        return self

    def stop(self):
        self._patch.stop()

    def set(self, moment: datetime) -> None:
        if timezone.is_naive(moment):
            moment = timezone.make_aware(moment)
        self._now = moment

    def advance(self, **kwargs) -> None:
        self._now += timedelta(**kwargs)


# --- Почта: Mailpit по API ------------------------------------------------------

def mailpit_url() -> str:
    """Адрес API Mailpit: из E2E_MAILPIT_URL, иначе http://<SMTP_HOST>:8025.

    С хоста (проход Playwright) задайте E2E_MAILPIT_URL=http://127.0.0.1:8025.
    """
    if os.environ.get("E2E_MAILPIT_URL"):
        return os.environ["E2E_MAILPIT_URL"]
    return f"http://{settings.EMAIL_HOST}:8025"


class MailpitClient:
    def __init__(self, base_url: str | None = None):
        self.base_url = (base_url or mailpit_url()).rstrip("/")

    def _request(self, method: str, path: str):
        req = urllib.request.Request(self.base_url + path, method=method)
        with urllib.request.urlopen(req, timeout=10) as r:
            body = r.read()
        return json.loads(body) if body.startswith((b"{", b"[")) else body.decode()

    def clear(self) -> None:
        self._request("DELETE", "/api/v1/messages")

    def messages(self) -> list[dict]:
        return self._request("GET", "/api/v1/messages")["messages"]

    def message(self, message_id: str) -> dict:
        """Полное письмо: поля Text, HTML, Subject, To."""
        return self._request("GET", f"/api/v1/message/{message_id}")

    def wait_for(self, to: str, *, timeout: float = 15.0) -> dict:
        """Ждёт письмо на адрес и возвращает его полностью."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            for short in self.messages():
                if any(a["Address"].lower() == to.lower() for a in short["To"]):
                    return self.message(short["ID"])
            time.sleep(0.3)
        raise AssertionError(f"письмо на {to} не пришло за {timeout} с")


# --- Фабрики моделей Этапа 3 ----------------------------------------------------

def _model(label: str):
    try:
        return apps.get_model(label)
    except LookupError as e:
        raise RuntimeError(f"модель {label} ещё не реализована (Этап 3)") from e


def make_role(name: str | None = None, permissions: tuple[str, ...] = (), **extra):
    Role, Permission = _model("core.Role"), _model("core.Permission")
    role = Role.objects.create(name=name or f"role-{secrets.token_hex(3)}", **extra)
    role.permissions.set(Permission.objects.filter(code__in=permissions))
    return role


def make_user(email: str | None = None, password: str | None = None, *,
              state: str = "active", roles=(), **extra):
    """Пользователь с паролем; пароль — `user.test_password`."""
    User = _model("core.User")
    password = password or new_password()
    user = User(email=email or new_email(), full_name=extra.pop("full_name", "Тест Тестов"),
                state=state, **extra)
    user.set_password(password)
    user.save()
    if roles:
        user.roles.set(roles)
    user.test_password = password
    return user


def make_link(user, purpose: str = "activation", *, ttl: timedelta | None = None, created_by=None):
    """Одноразовая ссылка по таблице `OneTimeLink`; возвращает (ссылка, код)."""
    from cryptography.fernet import Fernet, MultiFernet

    OneTimeLink = _model("core.OneTimeLink")
    code = secrets.token_urlsafe(32)
    fernet = MultiFernet([Fernet(k) for k in settings.FIELD_ENCRYPTION_KEYS])
    ttl = ttl or (timedelta(hours=72) if purpose == "activation" else timedelta(hours=1))
    link = OneTimeLink.objects.create(
        user=user, purpose=purpose,
        token_hash=hashlib.sha256(code.encode()).hexdigest(),
        code_encrypted=fernet.encrypt(code.encode()).decode(),
        expires_at=timezone.now() + ttl, created_by=created_by,
    )
    return link, code
