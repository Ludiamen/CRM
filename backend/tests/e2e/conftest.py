"""Проход в браузере (Playwright, Python) против стенда (T-013, NFR-009).

Запуск с хоста, когда стенд поднят (`docker compose --profile dev up -d`):

    set -a; . ../deploy/.env; set +a
    E2E_MAILPIT_URL=http://127.0.0.1:8025 python -m pytest tests/e2e

Браузеры — chromium, firefox и Edge (`channel="msedge"`). Если Edge не
установлен, его проект пропускается с пометкой «Edge не установлен»: это
единственный допустимый skip. Яндекс.Браузер Playwright не ведёт — его
проходит человек (T-308). Снимки экрана и trace — в /playwright-report/
(параметры --output, --screenshot, --tracing в pytest.ini).

Адрес стенда — https://127.0.0.1:8031/ с тем же именем хоста, что в PORTAL_URL
(иначе ALLOWED_HOSTS откажет); сертификат самоподписанный, поэтому контекст
создаётся с ignore_https_errors=True.

Контракт с шаблонами Этапа 3 (T-24x): поля входа — `input[name=email]`,
`input[name=password]`, `input[name=code]`; кнопка шага — `button[type=submit]`.
"""
import base64
import os
import re
import subprocess
from pathlib import Path

import pytest
from playwright.sync_api import Error as PlaywrightError

from tests import factories

PORTAL_URL = os.environ.get("E2E_PORTAL_URL", "https://127.0.0.1:8031/")
COMPOSE_FILE = Path(__file__).resolve().parents[3] / "deploy" / "docker-compose.yml"
PROJECTS = ["chromium", "firefox", "edge"]

os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")  # sync API Playwright + ORM в одном процессе


def pytest_collection_modifyitems(items):
    for item in items:
        if "/tests/e2e/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.e2e)


@pytest.fixture(scope="session", params=PROJECTS)
def browser(playwright, request):
    """Браузер проекта: chromium, firefox или Edge (пропуск, если Edge не установлен)."""
    name = request.param
    try:
        if name == "edge":
            instance = playwright.chromium.launch(channel="msedge")
        else:
            instance = getattr(playwright, name).launch()
    except PlaywrightError as e:
        if name == "edge":
            pytest.skip("Edge не установлен")
        raise RuntimeError(f"не запускается {name}: {e}") from e
    yield instance
    instance.close()


@pytest.fixture(scope="session")
def portal_url() -> str:
    return PORTAL_URL


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args, portal_url):
    return {
        **browser_context_args,
        "base_url": portal_url,
        "ignore_https_errors": True,
        "locale": "ru-RU",
        "timezone_id": "Europe/Moscow",
    }


@pytest.fixture
def mailpit() -> factories.MailpitClient:
    """Mailpit по API; ящик очищается перед тестом. Адрес — E2E_MAILPIT_URL."""
    client = factories.MailpitClient(os.environ.get("E2E_MAILPIT_URL", "http://127.0.0.1:8025"))
    client.clear()
    return client


def create_first_admin(email: str) -> str:
    """Создаёт первого администратора командой create_first_admin в контейнере web.

    Команда печатает ссылку активации; она возвращается целиком (с кодом во
    фрагменте). Переопределить запуск можно переменной E2E_ADMIN_CMD
    (строка команды, `{email}` подставляется).
    """
    custom = os.environ.get("E2E_ADMIN_CMD")
    if custom:
        cmd = custom.format(email=email).split()
    else:
        cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), "--profile", "dev", "exec", "-T", "web",
               "python", "manage.py", "create_first_admin", "--email", email]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=120).stdout
    found = re.search(r"https?://\S+/activate/\S*", out)
    if not found:
        raise AssertionError("create_first_admin не напечатала ссылку активации")
    return found.group(0)


@pytest.fixture
def first_admin():
    return create_first_admin


def totp_from_base32(secret: str, **kwargs) -> str:
    """Текущий код TOTP по ключу в base32 (так ключ показан при подключении)."""
    padded = secret.replace(" ", "").upper()
    padded += "=" * (-len(padded) % 8)
    return factories.totp_code(base64.b32decode(padded), **kwargs)


def login(page, email: str, password: str, totp_secret: str | None = None) -> None:
    """Вход в два шага: почта и пароль, затем код TOTP (если ключ передан)."""
    page.goto("/login/")
    page.fill("input[name=email]", email)
    page.fill("input[name=password]", password)
    page.click("button[type=submit]")
    if totp_secret:
        page.wait_for_url(re.compile(r"/login/code/"))
        page.fill("input[name=code]", totp_from_base32(totp_secret))
        page.click("button[type=submit]")


@pytest.fixture
def portal_login():
    return login
