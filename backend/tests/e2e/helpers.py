"""Помощники приёмки Playwright (T-140…T-151).

Всё, что ходит в стенд: вход с кодом TOTP без повтора кода, мастер активации,
создание сотрудника администратором, чтение писем Mailpit и несколько команд
в контейнере web (состарить ссылку, поменять порог бездействия).

Правила:
- пароли только из `factories.new_password()`; коды ссылок, ключи TOTP и
  резервные коды в сообщения проверок и в вывод не попадают;
- коды TOTP не повторяются в одном 30-секундном шаге (устройство отклоняет
  повтор), поэтому `totp_for` при необходимости ждёт следующего шага;
- разметка — по tests/CONTRACT.md («Дополнения исполнителя T-140…T-151»).
"""
import re
import subprocess
import time
import urllib.request
import json
import os
from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import expect

from tests import factories
from tests.e2e.conftest import COMPOSE_FILE, totp_from_base32

STAFF_ROLE = "Сотрудник ИТ"
ADMIN_ROLE = "Администратор портала"
DEFAULT_ROLES = ("Администратор портала", "Руководитель", "Сотрудник ИТ")

ADMINS: dict = {}  # браузер → Account администратора круга


@dataclass
class Account:
    email: str
    password: str
    full_name: str = "Тест Тестов"
    totp_secret: str = ""
    backup_codes: list = field(default_factory=list)
    id: str = ""
    link: str = ""            # ссылка приглашения (содержит код — не печатать)
    page: object = None       # страница в контексте активации (там сессия открыта)
    storage_state: dict | None = None


# --- Коды TOTP -------------------------------------------------------------------

_LAST_STEP: dict = {}


def _step() -> int:
    return int(time.time() // 30)


def wait_fresh_step(secret: str) -> None:
    """Ждёт шага, в котором код этого ключа ещё не использовался."""
    key = secret.replace(" ", "").upper()
    last = _LAST_STEP.get(key)
    while last is not None and _step() <= last:
        time.sleep(0.5)


def totp_for(secret: str) -> str:
    """Свежий верный код: тот же шаг дважды не используется."""
    wait_fresh_step(secret)
    _LAST_STEP[secret.replace(" ", "").upper()] = _step()
    return totp_from_base32(secret)


def wrong_code(secret: str) -> str:
    """Шестизначный код, заведомо не совпадающий с кодами соседних шагов."""
    valid = {totp_from_base32(secret, at=time.time() + 30 * d) for d in range(-3, 4)}
    n = 123456
    while f"{n:06d}" in valid:
        n += 1
    return f"{n:06d}"


# --- Почта -----------------------------------------------------------------------

def _mailpit_get(mailpit, path: str):
    with urllib.request.urlopen(mailpit.base_url + path, timeout=10) as r:
        return json.loads(r.read())


def mail_ids(mailpit, to: str) -> set:
    return {m["ID"] for m in mailpit.messages() if any(a["Address"].lower() == to.lower() for a in m["To"])}


def template_of(mailpit, message_id: str) -> str:
    """Шаблон письма — заголовок X-Portal-Template (CONTRACT.md)."""
    headers = _mailpit_get(mailpit, f"/api/v1/message/{message_id}/headers")
    value = next((v for k, v in headers.items() if k.lower() == "x-portal-template"), [""])
    return (value[0] if isinstance(value, list) else value).strip()


def wait_mail(mailpit, to: str, template: str, *, seen=(), timeout: float = 60.0) -> dict:
    """Новое (не из `seen`) письмо на адрес с заданным шаблоном; полный текст."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for short in mailpit.messages():
            if short["ID"] in seen or not any(a["Address"].lower() == to.lower() for a in short["To"]):
                continue
            if template_of(mailpit, short["ID"]) == template:
                return mailpit.message(short["ID"])
        time.sleep(0.5)
    raise AssertionError(f"письмо «{template}» на {to} не пришло за {timeout:.0f} с")


def no_mail(mailpit, to: str, template: str, *, seen=(), wait: float = 4.0) -> bool:
    """True, если за `wait` секунд нового письма с шаблоном нет (письма уходят за секунды)."""
    time.sleep(wait)
    return not [m for m in mailpit.messages()
                if m["ID"] not in seen and any(a["Address"].lower() == to.lower() for a in m["To"])
                and template_of(mailpit, m["ID"]) == template]


def link_in(message: dict, path: str) -> str:
    """Ссылка `…/<path>#<код>` из текста письма."""
    found = re.search(r"https?://[^\s\"'<>]+" + re.escape(path) + r"#[^\s\"'<>]+", message["Text"])
    assert found, f"в письме нет ссылки {path}#…"
    return found.group(0)


def code_of(link: str) -> str:
    return link.split("#", 1)[1]


# --- Команды в контейнере web ------------------------------------------------------

def stand_shell(code: str) -> str:
    """`manage.py shell -c` в контейнере web (E2E_SHELL_CMD — свой префикс команды)."""
    custom = os.environ.get("E2E_SHELL_CMD")
    if custom:
        cmd = custom.split() + [code]
    else:
        cmd = ["docker", "compose", "-f", str(COMPOSE_FILE), "--profile", "dev", "exec", "-T", "web",
               "python", "manage.py", "shell", "-c", code]
    return subprocess.run(cmd, capture_output=True, text=True, check=True, timeout=120).stdout.strip()


def reset_counters() -> None:
    """Обнуляет счётчики адреса и запросов восстановления (ключи — CONTRACT.md): все проходы идут с одного
    адреса, и без этого неудачи соседних тестов за 15 минут заблокировали бы адрес посреди прохода."""
    stand_shell("import redis; from django.conf import settings; "
                "r = redis.Redis.from_url(settings.VALKEY_URL); "
                "print(sum(r.delete(k) for p in ('*fail:ip:*', '*accts:ip:*', '*lock:ip:*', '*forgot:*') "
                "for k in r.scan_iter(p)))")


def age_activation_link(email: str) -> None:
    """Состарить ссылку активации записи: срок вышел час назад (в e2e 72 часа не подождать)."""
    out = stand_shell(
        "from datetime import timedelta; from django.apps import apps; from django.utils import timezone; "
        f"print(apps.get_model('core.OneTimeLink').objects.filter(user__email='{email}', purpose='activation')"
        ".update(expires_at=timezone.now() - timedelta(hours=1)))")
    assert out.splitlines()[-1].strip() != "0", "у записи нет ссылки активации"


def set_idle_minutes(minutes: int) -> None:
    """Порог бездействия прямо в базе (форма не даёт меньше 5 минут, ждать их незачем)."""
    stand_shell("from django.apps import apps; "
                f"apps.get_model('core.SecuritySettings').objects.update(idle_timeout_minutes={int(minutes)})")


# --- Страницы ---------------------------------------------------------------------

def submit(form) -> None:
    """Нажимает `button[type=submit]` формы (`form` — локатор); флажок `confirm`, если он есть, отмечается."""
    box = form.locator("input[name=confirm]")
    if box.count() and box.first.is_visible() and not box.first.is_checked():
        box.first.check()
    form.locator("button[type=submit]").first.click()


def alert_text(page) -> str:
    return " ".join(page.locator("[role=alert]").all_inner_texts()).strip()


def status_text(page) -> str:
    return " ".join(page.locator("[role=status]").all_inner_texts()).strip()


def open_security_tab(page) -> None:
    """Карточка сотрудника открывается на вкладке «Профиль»: переключает на «Безопасность» (§ 9.3 контракта,
    FR-119, FR-135) перед работой с приглашением, блокировкой, сбросом второго фактора и входами."""
    page.locator('[data-tab-button="security"]').click()
    expect(page.locator('[data-tab-panel="security"]')).to_be_visible()


def no_horizontal_scroll(page) -> bool:
    return page.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def fill_login(page, email: str, password: str) -> None:
    page.goto("/login/")
    page.fill("input[name=email]", email)
    page.fill("input[name=password]", password)
    page.click("button[type=submit]")


def sign_in(page, account: Account, *, next_url: str | None = None) -> None:
    """Полный вход: почта, пароль, код TOTP. Ждёт верхнюю панель."""
    page.goto("/login/" + (f"?next={next_url}" if next_url else ""))
    page.fill("input[name=email]", account.email)
    page.fill("input[name=password]", account.password)
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/login/code/"))
    page.fill("input[name=code]", totp_for(account.totp_secret))
    page.click("button[type=submit]")
    expect(page.locator("#top-bar")).to_be_visible()


def sign_in_backup(page, account: Account, backup_code: str) -> None:
    fill_login(page, account.email, account.password)
    page.wait_for_url(re.compile(r"/login/code/"))
    use_backup_code(page, backup_code)


def use_backup_code(page, backup_code: str) -> None:
    field_ = page.locator("input[name=backup_code]")
    if not field_.is_visible():
        page.get_by_text("Войти по резервному коду").first.click()
    field_.fill(backup_code)
    field_.locator("xpath=ancestor::form").locator("button[type=submit]").click()


def sign_out(page) -> None:
    page.locator('#top-bar form[action="/logout/"] button').click()
    page.wait_for_url(re.compile(r"/login/"))


# --- Активация ---------------------------------------------------------------------

def open_activation_link(page, link: str) -> None:
    """Открывает ссылку приглашения и ждёт первый шаг мастера: адрес уже без кода."""
    page.goto(link)
    page.wait_for_url(re.compile(r"/activate/profile/"))


def walk_activation(page, link: str, password: str, *, phone: str = "+7 900 000-00-00") -> tuple:
    """Проходит мастер из четырёх шагов; возвращает (ключ TOTP, список резервных кодов)."""
    open_activation_link(page, link)
    page.fill("[name=phone]", phone)
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/activate/password/"))
    page.fill("input[name=password1]", password)
    page.fill("input[name=password2]", password)
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/activate/totp/"))
    secret = page.locator("#totp-secret").inner_text().strip()
    page.fill("input[name=code]", totp_for(secret))
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/activate/codes/"))
    codes = [c.strip() for c in page.locator("code.backup-code").all_inner_texts()]
    page.locator("input[name=confirm]").check()
    page.click("button[type=submit]")
    page.wait_for_url(lambda url: "/activate/" not in url)
    return secret, codes


def bootstrap_admin(browser, context_args, first_admin) -> Account:
    """Создаёт и активирует первого администратора круга (если s01 этого не сделал)."""
    account = Account(email=factories.new_email("admin"), password=factories.new_password(),
                      full_name="Администратор Стенда")
    link = first_admin(account.email)
    context = browser.new_context(**context_args)
    try:
        page = context.new_page()
        account.totp_secret, account.backup_codes = walk_activation(page, link, account.password)
        account.storage_state = context.storage_state()
    finally:
        context.close()
    ADMINS[browser.e2e_project] = account
    return account


# --- Сотрудники --------------------------------------------------------------------

def create_employee(admin_page, email: str, *, full_name: str = "Иванов Иван Иванович",
                    position: str = "Инженер", phone: str = "", role: str = STAFF_ROLE) -> str:
    """Форма `/staff/new/` — «Создать и пригласить»; возвращает номер записи."""
    admin_page.goto("/staff/new/")
    form = admin_page.locator('form[action="/staff/new/"]')
    form.locator("[name=email]").fill(email)
    form.locator("[name=full_name]").fill(full_name)
    form.locator("[name=position]").fill(position)
    if phone:
        form.locator("[name=phone]").fill(phone)
    form.get_by_label(role, exact=True).check()
    form.locator("button[type=submit]").click()
    admin_page.wait_for_url(re.compile(r"/staff/\d+/"))
    return re.search(r"/staff/(\d+)/", admin_page.url).group(1)


def make_employee(admin_page, mailpit, new_context, *, activate: bool = True, role: str = STAFF_ROLE,
                  full_name: str = "Иванов Иван Иванович") -> Account:
    """Сотрудник: заведён администратором, письмо прочитано, мастер пройден (если activate)."""
    account = Account(email=factories.new_email("emp"), password=factories.new_password(), full_name=full_name)
    account.id = create_employee(admin_page, account.email, full_name=full_name, role=role)
    mail = wait_mail(mailpit, account.email, "invitation")
    account.link = link_in(mail, "/activate/")
    if activate:
        context = new_context()
        account.page = context.new_page()
        account.totp_secret, account.backup_codes = walk_activation(account.page, account.link, account.password)
    return account


def staff_row(page, email: str):
    return page.locator(f'tr[data-user-email="{email}"]')


# --- Журнал ------------------------------------------------------------------------

def audit_actions(admin_page, query: str = "") -> list:
    """Коды событий, показанные на первой странице журнала с параметрами `query`."""
    admin_page.goto("/audit/" + (f"?{query}" if query else ""))
    return [r.get_attribute("data-action") for r in admin_page.locator("tr[data-event-id]").all()]


def audit_text(admin_page) -> str:
    admin_page.goto("/audit/")
    return admin_page.locator("body").inner_text()


# --- Картинки ----------------------------------------------------------------------

def make_png(width: int, height: int, *, noise: bool = False) -> bytes:
    """Настоящий PNG заданного размера (noise=True — несжимаемый, тяжёлый файл)."""
    import secrets
    import struct
    import zlib

    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)

    rows = b"".join(b"\x00" + (secrets.token_bytes(width * 3) if noise else bytes((30, 120, 200)) * width)
                    for _ in range(height))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


# --- Журнал nginx ------------------------------------------------------------------

def nginx_access_log() -> str:
    """Журнал доступа nginx: файл из E2E_NGINX_LOG_FILE или `docker compose logs nginx`."""
    path = os.environ.get("E2E_NGINX_LOG_FILE")
    if path:
        return Path(path).read_text(encoding="utf-8", errors="replace")
    return subprocess.run(
        ["docker", "compose", "-f", str(COMPOSE_FILE), "--profile", "dev", "logs", "--no-color", "--no-log-prefix",
         "nginx"], capture_output=True, text=True, check=True, timeout=120).stdout
