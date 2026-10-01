"""T-101: настройки читаются из окружения (FR-055, NFR-007, NFR-010, NFR-011).

Файл настроек импортируется в отдельном процессе с изменённым окружением, чтобы
проверить, что значения берутся из переменных, а не лежат в файле.
"""
import json
import os
import re
import subprocess
import sys

import pytest
from django.conf import settings

from tests import factories
from tests.support import BACKEND_DIR

PROBE = (
    "import json, config.settings as s;"
    "names = {names!r};"
    "print(json.dumps({{n: getattr(s, n) for n in names}}, default=list))"
)


def settings_in_subprocess(names: list[str], **env: str | None) -> subprocess.CompletedProcess:
    environment = dict(os.environ)
    for key, value in env.items():
        if value is None:
            environment.pop(key, None)
        else:
            environment[key] = value
    return subprocess.run([sys.executable, "-c", PROBE.format(names=names)], cwd=BACKEND_DIR, env=environment,
                          capture_output=True, text=True, timeout=60)


def loaded(names: list[str], **env: str | None) -> dict:
    done = settings_in_subprocess(names, **env)
    assert done.returncode == 0, done.stderr[-600:]
    return json.loads(done.stdout.strip().splitlines()[-1])


def test_settings_read_secrets_only_from_environment():
    """FR-055 / секреты-вне-кода: SECRET_KEY, ключи Fernet и секрет резервных кодов приходят из окружения."""
    from cryptography.fernet import Fernet

    secret, pepper = factories.new_password(), factories.new_password()
    keys = [Fernet.generate_key().decode(), Fernet.generate_key().decode()]
    got = loaded(["SECRET_KEY", "BACKUP_CODE_PEPPER", "FIELD_ENCRYPTION_KEYS"], DJANGO_SECRET_KEY=secret,
                 BACKUP_CODE_PEPPER=pepper, FIELD_ENCRYPTION_KEYS=",".join(keys))
    assert got == {"SECRET_KEY": secret, "BACKUP_CODE_PEPPER": pepper, "FIELD_ENCRYPTION_KEYS": keys}
    for name in ("DJANGO_SECRET_KEY", "FIELD_ENCRYPTION_KEYS", "BACKUP_CODE_PEPPER"):
        failed = settings_in_subprocess(["SECRET_KEY"], **{name: None})
        assert failed.returncode != 0, f"без {name} настройки не должны запускаться"
    source = (BACKEND_DIR / "config" / "settings.py").read_text(encoding="utf-8")
    assert not re.search(r"""(SECRET_KEY|PEPPER|PASSWORD|FIELD_ENCRYPTION_KEYS)\s*=\s*["'][^"']+["']""", source)
    # PORTAL_URL задаёт хосты сам, отдельно их не задают
    hosts = loaded(["ALLOWED_HOSTS", "CSRF_TRUSTED_ORIGINS"], PORTAL_URL="https://portal.example.org:8443")
    assert hosts == {"ALLOWED_HOSTS": ["portal.example.org"], "CSRF_TRUSTED_ORIGINS": ["https://portal.example.org:8443"]}


def test_smtp_settings_come_from_environment_only():
    """FR-055: адрес, порт, отправитель и учётные данные SMTP — только окружение; режимы starttls / ssl / none."""
    password = factories.new_password()
    environment = {"SMTP_HOST": "smtp.example.org", "SMTP_PORT": "2525", "SMTP_USER": "mailer",
                   "SMTP_PASSWORD": password, "SMTP_FROM": "portal@example.org", "SMTP_SECURITY": "starttls"}
    got = loaded(["EMAIL_HOST", "EMAIL_PORT", "EMAIL_HOST_USER", "EMAIL_HOST_PASSWORD", "DEFAULT_FROM_EMAIL",
                  "EMAIL_USE_TLS", "EMAIL_USE_SSL"], **environment)
    assert got == {"EMAIL_HOST": "smtp.example.org", "EMAIL_PORT": 2525, "EMAIL_HOST_USER": "mailer",
                   "EMAIL_HOST_PASSWORD": password, "DEFAULT_FROM_EMAIL": "portal@example.org",
                   "EMAIL_USE_TLS": True, "EMAIL_USE_SSL": False}
    assert loaded(["EMAIL_USE_TLS", "EMAIL_USE_SSL"], SMTP_SECURITY="ssl") == {"EMAIL_USE_TLS": False, "EMAIL_USE_SSL": True}
    assert loaded(["EMAIL_USE_TLS", "EMAIL_USE_SSL"], SMTP_SECURITY="none") == {"EMAIL_USE_TLS": False, "EMAIL_USE_SSL": False}
    assert settings_in_subprocess(["EMAIL_HOST"], SMTP_SECURITY="plain").returncode != 0
    for name in ("SMTP_HOST", "SMTP_PORT", "SMTP_FROM"):
        assert settings_in_subprocess(["EMAIL_HOST"], **{name: None}).returncode != 0, f"{name} обязателен"
    source = (BACKEND_DIR / "config" / "settings.py").read_text(encoding="utf-8")
    assert not re.search(r"EMAIL_HOST\w*\s*=\s*[\"']", source), "параметры SMTP не пишутся литералами"


def test_settings_language_and_timezone():
    """NFR-010: интерфейс по-русски, время в Europe/Moscow."""
    from datetime import datetime, timezone as tz

    from django.utils import formats, timezone, translation

    assert (settings.LANGUAGE_CODE, settings.TIME_ZONE, settings.USE_TZ) == ("ru", "Europe/Moscow", True)
    moment = datetime(2026, 10, 1, 21, 30, tzinfo=tz.utc)
    assert timezone.localtime(moment).hour == 0 and timezone.localtime(moment).day == 2  # UTC+3
    with translation.override("ru"):
        assert "октября" in formats.date_format(moment, "DATE_FORMAT")


def test_settings_cookie_flags():
    """NFR-007: куки сессии и CSRF — Secure, HttpOnly, SameSite=Lax."""
    assert settings.SESSION_COOKIE_SECURE is True
    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert settings.CSRF_COOKIE_SECURE is True
    assert settings.CSRF_COOKIE_HTTPONLY is True
    assert settings.CSRF_COOKIE_SAMESITE == "Lax"
    assert settings.SECURE_PROXY_SSL_HEADER == ("HTTP_X_FORWARDED_PROTO", "https")
    assert settings.SESSION_ENGINE == "django.contrib.sessions.backends.db"  # сессии закрываются по одной


def test_settings_argon2_first_hasher():
    """NFR-011: пароли хешируются argon2, он первым в списке хешеров."""
    from django.contrib.auth.hashers import make_password

    assert settings.PASSWORD_HASHERS[0].endswith("Argon2PasswordHasher")
    assert make_password(factories.new_password()).startswith("argon2$")
