"""Общие помощники тестов Этапа 2 (T-100…T-110).

Модули под тестом (`apps.core…`, `apps.integrations…`) здесь импортируются
только внутри функций: пока кода нет, сбор тестов проходит, а падения видны
поимённо. Имена, которых нет в PLAN-001, перечислены в tests/CONTRACT.md.
Пароли и секреты — только из factories (secrets), литералов нет.
"""
import hashlib
import os
import re
import secrets
import threading
import time
from datetime import timedelta
from pathlib import Path

import pytest
import redis
from django.apps import apps
from django.conf import settings
from django.test import Client
from django.utils import timezone

from tests import factories

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

PERMISSIONS = (
    "accounts.manage", "accounts.reset_2fa", "accounts.view_logins",
    "roles.manage", "audit.view", "settings.portal", "settings.security",
)
ADMIN_ROLE, MANAGER_ROLE, STAFF_ROLE = "Администратор портала", "Руководитель", "Сотрудник ИТ"

SECURITY_FIELDS = (
    "password_min_length", "password_history", "password_max_age_days", "idle_timeout_minutes",
    "account_lock_limit", "account_lock_minutes", "ip_lock_limit", "ip_lock_min_accounts",
    "ip_lock_window_minutes", "ip_lock_minutes", "login_history_days",
)

FIREFOX_UA = "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"
CHROME_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
             "(KHTML, like Gecko) Chrome/129.0.0.0 Safari/537.36")


def model(label: str):
    """Модель по метке `app.Model` (core.User, mail.MailMessage …)."""
    return factories._model(label)


def repo_file(*parts: str) -> Path:
    """Файл корня репозитория (deploy/, docs/): в контейнере тестов он должен быть смонтирован."""
    path = REPO_ROOT.joinpath(*parts)
    assert path.exists(), (
        f"{path} не найден: контейнеру тестов нужен корень репозитория "
        f"(смонтировать ../deploy в /app/deploy), см. tests/CONTRACT.md"
    )
    return path


# --- Valkey ------------------------------------------------------------------

def valkey() -> redis.Redis:
    return redis.Redis.from_url(settings.VALKEY_URL)


def valkey_keys(suffix: str) -> list[str]:
    """Ключи Valkey, оканчивающиеся на `suffix` (Django-кэш добавляет к ключу приставку)."""
    client = valkey()
    try:
        return [k.decode() for k in client.keys("*") if k.decode().endswith(suffix)]
    finally:
        client.close()


def valkey_key(suffix: str) -> str | None:
    found = valkey_keys(suffix)
    return found[0] if found else None


def valkey_int(suffix: str) -> int:
    key = valkey_key(suffix)
    if key is None:
        return 0
    client = valkey()
    try:
        return int(client.get(key) or 0)
    finally:
        client.close()


# --- Ключи шифрования и коды -----------------------------------------------------

def fernet():
    from cryptography.fernet import Fernet, MultiFernet

    return MultiFernet([Fernet(k) for k in settings.FIELD_ENCRYPTION_KEYS])


def link_code(link) -> str:
    """Код одноразовой ссылки из `code_encrypted` (то, что видит администратор)."""
    return fernet().decrypt(link.code_encrypted.encode()).decode()


def device_key(device) -> bytes:
    """Ключ TOTP из `key_encrypted` (в базе он лежит только зашифрованным)."""
    return fernet().decrypt(bytes(device.key_encrypted) if not isinstance(device.key_encrypted, str)
                            else device.key_encrypted.encode())


def sha256(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


# --- Сборка данных -------------------------------------------------------------------

def role_by_name(name: str):
    return model("core.Role").objects.get(name=name)


def make_totp_device(user, *, confirmed: bool = True, key: bytes | None = None):
    """Устройство TOTP; ключ хранится Fernet-ом, открытый вид — `user.test_totp_key`."""
    Device = model("core.EncryptedTOTPDevice")
    key = key or os.urandom(20)
    device = Device.objects.create(
        user=user, name="default", confirmed=confirmed,
        key_encrypted=fernet().encrypt(key).decode(), step=30, digits=6, tolerance=1, last_t=-1,
    )
    user.test_totp_key = key
    return device


def make_employee(*, roles=(), state="active", totp: bool = True, email: str | None = None, **extra):
    """Активный сотрудник с паролем (`user.test_password`) и подтверждённым TOTP (`user.test_totp_key`)."""
    extra.setdefault("activated_at", timezone.now() if state == "active" else None)
    user = factories.make_user(email=email, state=state, roles=roles, **extra)
    user.test_totp_key = None
    if totp:
        make_totp_device(user)
    return user


def make_admin(**extra):
    return make_employee(roles=[role_by_name(ADMIN_ROLE)], **extra)


def make_with_permissions(*codes: str, **extra):
    """Сотрудник, у которого ровно эти права (через свою роль)."""
    return make_employee(roles=[factories.make_role(permissions=codes)], **extra)


def set_password_history(user, passwords: list[str]) -> None:
    """Задаёт последовательность паролей: последний становится текущим, все — в `PasswordHistory`."""
    History = model("core.PasswordHistory")
    base = timezone.now() - timedelta(days=len(passwords))
    for i, pw in enumerate(passwords):
        user.set_password(pw)
        user.save()
        History.objects.create(user=user, password_hash=user.password, created_at=base + timedelta(days=i))
    user.test_password = passwords[-1]


# --- Клиент и вход ----------------------------------------------------------------------

def make_client(ip: str = "198.51.100.7", ua: str = FIREFOX_UA, **defaults) -> Client:
    return Client(REMOTE_ADDR=ip, HTTP_USER_AGENT=ua, **defaults)


HX = {"HTTP_HX_REQUEST": "true"}


def current_code(user) -> str:
    """Код TOTP на сейчас; защита от повтора сбрасывается, чтобы вход можно было повторять."""
    model("core.EncryptedTOTPDevice").objects.filter(user=user).update(last_t=-1)
    return factories.totp_code(user.test_totp_key)


def post_password(client, user_or_email, password: str | None = None, **extra):
    email = getattr(user_or_email, "email", user_or_email)
    password = password if password is not None else user_or_email.test_password
    return client.post("/login/", {"email": email, "password": password}, **extra)


def login(client, user, **extra):
    """Полный вход: пароль, затем код TOTP. Возвращает ответ второго шага."""
    first = post_password(client, user, **extra)
    assert first.status_code == 302 and first["Location"].endswith("/login/code/"), (
        f"шаг пароля: ожидали переход на /login/code/, получили {first.status_code} {first.get('Location')}")
    second = client.post("/login/code/", {"code": current_code(user)}, **extra)
    assert second.status_code == 302, f"шаг кода: {second.status_code}"
    return second


def logged_in(user, **client_kwargs) -> Client:
    client = make_client(**client_kwargs)
    login(client, user)
    return client


def same_failure(*responses) -> bool:
    """Ответы неотличимы: статус, адрес перехода и текст (без токена CSRF и пробелов)."""
    shapes = {normalized(r) for r in responses}
    return len(shapes) == 1


def normalized(response) -> tuple:
    body = response.content.decode("utf-8", "replace")
    body = re.sub(r'name="csrfmiddlewaretoken" value="[^"]*"', "", body)
    body = re.sub(r"\s+", " ", body)
    return response.status_code, response.get("Location", ""), body


def post_security_settings(client, **changes):
    """Форма политики безопасности: прежние значения плюс изменения."""
    current = model("core.SecuritySettings").objects.get()
    data = {name: getattr(current, name) for name in SECURITY_FIELDS}
    data.update(changes)
    data = {k: ("" if v is None else v) for k, v in data.items()}
    return client.post("/settings/security/", data)


def set_security(**changes) -> None:
    """Правка политики напрямую в базе (быстрая подготовка; значения читаются из базы при каждом запросе)."""
    model("core.SecuritySettings").objects.update(**changes)


def audit_actions(**filters) -> list[str]:
    return list(model("core.AuditEvent").objects.filter(**filters).order_by("id").values_list("action", flat=True))


def mails(**filters):
    return model("mail.MailMessage").objects.filter(**filters).order_by("id")


def run_threads(target, args_list) -> list:
    """Запускает target(*args) в потоках одновременно (барьером) и собирает результаты."""
    barrier = threading.Barrier(len(args_list))
    results = [None] * len(args_list)
    errors = []

    def worker(i, args):
        try:
            barrier.wait(timeout=10)
            results[i] = target(*args)
        except Exception as e:  # noqa: BLE001 — ошибку потока показываем в основном потоке
            errors.append(e)

    threads = [threading.Thread(target=worker, args=(i, a)) for i, a in enumerate(args_list)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    if errors:
        raise errors[0]
    return results


def backup_code_values(html: str) -> list[str]:
    """Резервные коды со страницы: каждый в `<code class="backup-code">…</code>`."""
    return re.findall(r'<code[^>]*class="[^"]*backup-code[^"]*"[^>]*>\s*([^<\s]+)\s*</code>', html)


def wait_until(predicate, timeout: float = 5.0, step: float = 0.1):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(step)
    return False





def sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def all_routes():
    """Все маршруты проекта как (шаблон пути, запись URLconf)."""
    from django.urls import get_resolver

    def walk(patterns, prefix=""):
        for entry in patterns:
            route = prefix + str(entry.pattern)
            if hasattr(entry, "url_patterns"):
                yield from walk(entry.url_patterns, route)
            else:
                yield route, entry

    yield from walk(get_resolver().url_patterns)


def pending_device_key(user) -> bytes:
    """Ключ ещё не подтверждённого устройства TOTP (создаётся при открытии страницы подключения)."""
    device = model("core.EncryptedTOTPDevice").objects.get(user=user, confirmed=False)
    return device_key(device)


def enroll_totp(client, user, *, totp_url: str, codes_url: str, finish: bool = True):
    """Подключение второго фактора через страницу: открыть, ввести верный код, сохранить коды.

    Возвращает (ключ TOTP, список резервных кодов). Для мастера активации —
    /activate/totp/ и /activate/codes/, для ограниченной сессии —
    /me/security/totp/ и /me/security/backup-codes/.
    """
    assert client.get(totp_url).status_code == 200
    key = pending_device_key(user)
    done = client.post(totp_url, {"code": factories.totp_code(key)})
    assert done.status_code == 302 and done["Location"].endswith(codes_url), (done.status_code, done.get("Location"))
    page = client.get(codes_url)
    assert page.status_code == 200
    codes = backup_code_values(page.content.decode())
    if finish:
        assert client.post(codes_url, {"confirm": "1"}).status_code == 302
    user.test_totp_key = key
    return key, codes
