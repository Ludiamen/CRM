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

Стенд недоступен — тест падает (ошибка подключения или 404), а не пропускается:
пропуск есть только у Edge без установки. Firefox не установлен — браузер падает
с ошибкой запуска (`playwright install firefox`), это не пропуск.

Первый администратор: `create_first_admin` отказывает при любой уже существующей
записи, поэтому проход идёт «кругом» на браузер: в начале круга стенд должен быть
пуст (команду очистки задаёт E2E_RESET_CMD, выполняется перед первым тестом
круга), а первым в круге идёт test_s01_first_admin.py. Без E2E_RESET_CMD второй и
третий круг (firefox, Edge) начнутся на стенде с уже заведённым администратором и
test_s01 в них упадёт с пояснением — это сигнал сбросить данные, не дефект.

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
from playwright.sync_api import expect

from tests import factories

PORTAL_URL = os.environ.get("E2E_PORTAL_URL", "https://127.0.0.1:8031/")
COMPOSE_FILE = Path(__file__).resolve().parents[3] / "deploy" / "docker-compose.yml"
PROJECTS = ["chromium", "firefox", "edge"]

os.environ.setdefault("DJANGO_ALLOW_ASYNC_UNSAFE", "true")  # sync API Playwright + ORM в одном процессе


expect.set_options(timeout=15_000)


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(items):
    for item in items:
        if "/tests/e2e/" in str(item.fspath).replace("\\", "/"):
            item.add_marker(pytest.mark.e2e)

    def rank(item):
        spec = getattr(item, "callspec", None)
        name = spec.params.get("browser") if spec else None
        return PROJECTS.index(name) if name in PROJECTS else 0

    # круг по браузерам; внутри круга первым идёт test_s01 (свежий стенд)
    items.sort(key=lambda it: (rank(it), "test_s01_first_admin" not in str(it.fspath)))


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
    instance.e2e_project = name
    reset = os.environ.get("E2E_RESET_CMD")
    if reset:
        subprocess.run(reset.split(), check=True, timeout=300)
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
               "python", "manage.py", "create_first_admin", "--email", email, "--full-name", "Администратор Стенда"]
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


# --- Общие фикстуры приёмки (T-140…T-151) ---------------------------------------------


@pytest.fixture(scope="session")
def stand_admin(browser, browser_context_args):
    """Администратор круга: создан и активирован один раз на браузер (см. шапку файла)."""
    from tests.e2e import helpers

    found = helpers.ADMINS.get(browser.e2e_project)
    return found or helpers.bootstrap_admin(browser, browser_context_args, create_first_admin)


@pytest.fixture
def admin_page(stand_admin, new_context):
    """Страница администратора с сохранённой сессией (при её потере — вход заново)."""
    from tests.e2e import helpers

    context = new_context(storage_state=stand_admin.storage_state)
    page = context.new_page()
    page.goto("/")
    if "/login/" in page.url:
        helpers.sign_in(page, stand_admin)
        stand_admin.storage_state = context.storage_state()
    return page


@pytest.fixture
def employee(admin_page, mailpit, new_context):
    """Фабрика сотрудников: админ заводит, письмо читается в Mailpit, активация в своём контексте."""
    from tests.e2e import helpers

    def make(**kwargs):
        return helpers.make_employee(admin_page, mailpit, new_context, **kwargs)

    return make


@pytest.fixture(autouse=True)
def fresh_counters():
    """Счётчики блокировки адреса и восстановления пароля — с нуля перед каждым тестом.

    Все тесты идут с одного адреса, и суммарные неудачи заблокировали бы его посреди прохода. Если команду
    в контейнере выполнить нельзя (стенда нет) — не шумим: сам тест упадёт на подключении к стенду."""
    from tests.e2e import helpers

    try:
        helpers.reset_counters()
    except (subprocess.SubprocessError, OSError) as e:
        print(f"счётчики не сброшены: {type(e).__name__}")
    yield


@pytest.fixture(autouse=True)
def fresh_form_counters(request):
    """Порог формы заявок `servicedesk:form:*` (7.4) — с нуля перед каждым тестом файлов `test_d*.py`.

    Все тесты идут с одного адреса: заявки сверх часового порога с формы заблокировали бы соседние тесты.
    У остальных файлов — сразу `yield`. Ошибки команды стенда печатаются, не поднимаются."""
    if request.node.path.name.startswith("test_d"):
        from tests.e2e import helpers_sd

        try:
            helpers_sd.reset_form_counters()
        except (subprocess.SubprocessError, OSError) as e:
            print(f"счётчики порога формы не сброшены: {type(e).__name__}")
    yield
