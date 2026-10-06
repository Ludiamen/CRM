"""Помощники приёмки среза 003 «Сервис-деск» (T-3140, CONTRACT-003.md, дополнение 40).

Что здесь есть:
- команды стенда `e2e_poll_mailbox`, `e2e_backdate`, `e2e_run_job` (8.1–8.2): `poll_now`, `backdate`, `run_job`;
- письма в ящик стенда по IMAP `APPEND` (раздел 1): `append_mail`, `deliver`;
- адреса приёмки: `MAILBOX`, `CORP_DOMAIN`, `FOREIGN_DOMAIN`, `requester_email`;
- сброс стенда посреди круга: `reset_stand_and_relogin`, порог формы — `reset_form_counters` (7.4);
- исходящие письма в Mailpit по номеру заявки: `ticket_letters`, `wait_letter`, `no_letter`, `letter_headers`;
- таблицы для загрузки: `make_table`;
- настройка через интерфейс (12.6, 13.7): домены, очереди, готовность сервис-деска;
- заявка по слову темы, карточка заявки, «Входящие письма» (12.2, 13.2, 13.3, 13.8).

Правила: пароль ящика — только `os.environ["IMAP_PASSWORD"]` и только при вызове; в сообщениях об ошибках его
нет (подстановка `***`). Код приложения (`apps.*`, `django`) не импортируется. Зацепки и маршруты — только из
контракта. Файл правит только T-3140.
"""
import csv
import dataclasses
import imaplib
import io
import os
import re
import secrets
import subprocess
import time
import urllib.parse

import openpyxl
from playwright.sync_api import expect

from tests.e2e import conftest, helpers, helpers_org

# --- Адреса приёмки (доп. 40 (в)) -------------------------------------------------------------

MAILBOX = os.environ.get("SERVICEDESK_MAILBOX", "tickets@stand.test")
CORP_DOMAIN = MAILBOX.rsplit("@", 1)[-1]  # корпоративный домен приёмки — домен ящика (FR-216, FR-217)
FOREIGN_DOMAIN = "foreign.test"

STAND_KINDS = ("ticket", "mail", "mailbox")  # виды e2e_backdate (8.2)


def requester_email(prefix: str = "req") -> str:
    """Уникальный адрес заявителя корпоративного домена: `<prefix>-<8 hex>@CORP_DOMAIN`."""
    return f"{prefix}-{secrets.token_hex(4)}@{CORP_DOMAIN}"


# --- Команды стенда (доп. 40 (а); 8.1, 8.2) ---------------------------------------------------

def _stand_prefix() -> list:
    """Префикс команд стенда: `E2E_STAND_CMD` (до `manage.py` включительно) или служба `standtools` (E2E_STAND=1)."""
    custom = os.environ.get("E2E_STAND_CMD")
    if custom:
        return custom.split()
    return ["docker", "compose", "-f", str(conftest.COMPOSE_FILE), "--profile", "dev", "exec", "-T", "standtools",
            "python", "manage.py"]


def _stand_command(*args: str) -> str:
    """Запускает `<префикс> <args>` (тайм-аут 120 с); возвращает последнюю непустую строку `stdout`.
    Код выхода не 0 или тайм-аут — `AssertionError` с текстом `stderr` (паролей в нём нет, 8.1)."""
    cmd = _stand_prefix() + [str(a) for a in args]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired as e:
        raise AssertionError(f"команда стенда {' '.join(args)} не уложилась в 120 с") from e
    if done.returncode != 0:
        raise AssertionError(f"команда стенда {' '.join(args)} завершилась с кодом {done.returncode}: "
                             f"{done.stderr.strip()}")
    lines = [line for line in done.stdout.splitlines() if line.strip()]
    return lines[-1].strip() if lines else ""


def poll_now() -> str:
    """`e2e_poll_mailbox` (8.2): опрос ящика и разбор писем сразу, без ожидания рабочего процесса. Возвращает строку
    вывода `poll_mailbox: state=… fetched=… parsed=… errors=…`; числа тест не проверяет — результат смотрит в
    интерфейсе."""
    return _stand_command("e2e_poll_mailbox")


def backdate(kind: str, ref, field: str, days: int) -> str:
    """`e2e_backdate <kind> <ref> <field> <days>` (8.2): сдвигает отметку назад на `days` суток (от 1).
    `kind`: `ticket` (`ref` — номер заявки; поля `waiting_since`, `closed_at`, `created_at`, `last_message_at`),
    `mail` (`ref` — `Message-ID` с `<` `>`; поле `received_at`), `mailbox` (`ref` — `"-"`; поле `last_ok_at`).
    Возвращает строку вывода `backdate: …`."""
    if kind not in STAND_KINDS:
        raise ValueError(f"вид {kind!r}: нужен один из {STAND_KINDS}")
    if int(days) < 1:
        raise ValueError("days должно быть целым от 1")
    return _stand_command("e2e_backdate", kind, ref, field, int(days))


def run_job(job: str) -> str:
    """`e2e_run_job <job>` (8.2): периодическое задание целиком в процессе команды; `job` — `autoclose`,
    `anonymize_tickets` или `purge_inbound`. Возвращает строку `run_job: <job> done=… batches=…`."""
    return _stand_command("e2e_run_job", job)


# --- Письма в ящик стенда (доп. 40 (б); раздел 1, «Вход в Dovecot у приёмки») ------------------

def _imap_connect() -> imaplib.IMAP4:
    """Соединение с Dovecot стенда без TLS и вход: `E2E_IMAP_HOST` (127.0.0.1), `E2E_IMAP_PORT` (31143, `int`),
    `E2E_IMAP_USER` (tickets), пароль — `os.environ["IMAP_PASSWORD"]` (читается здесь, при вызове)."""
    host = os.environ.get("E2E_IMAP_HOST", "127.0.0.1")
    port = int(os.environ.get("E2E_IMAP_PORT", "31143"))
    user = os.environ.get("E2E_IMAP_USER", "tickets")
    password = os.environ.get("IMAP_PASSWORD")
    if not password:
        raise AssertionError("нужна переменная окружения IMAP_PASSWORD (пароль ящика заявок)")
    conn = None
    try:
        conn = imaplib.IMAP4(host, port, timeout=30)
        conn.login(user, password)
    except (imaplib.IMAP4.error, OSError) as e:
        if conn is not None:
            try:
                conn.logout()
            except (imaplib.IMAP4.error, OSError):
                pass
        raise AssertionError(f"вход в Dovecot {host}:{port} как {user} не удался: "
                             f"{str(e).replace(password, '***')}") from None
    return conn


def append_mail(raw: bytes, *, seen: bool = False) -> None:
    """Кладёт письмо `raw` (байты, обычно `support_servicedesk.build_mail(...)`) в `INBOX` ящика стенда командой
    `APPEND`; `seen=True` — с флагом `\\Seen` (FR-211: письмо уже «прочитано» другим клиентом). Своё соединение на
    каждый вызов (вход, `APPEND`, выход). Ошибка, в том числе ответ `APPEND` не `OK`, — `AssertionError` без пароля.
    Разбор письма сам не запускает (для этого `poll_now()` или `deliver`)."""
    password = os.environ.get("IMAP_PASSWORD") or ""
    conn = _imap_connect()
    try:
        status, data = conn.append("INBOX", r"(\Seen)" if seen else None, None, raw)
        if status != "OK":
            detail = " ".join(d.decode("utf-8", "replace") if isinstance(d, bytes) else str(d) for d in (data or []))
            raise AssertionError(f"APPEND в INBOX: ответ {status}: {detail.replace(password, '***')}")
    except (imaplib.IMAP4.error, OSError) as e:
        raise AssertionError(f"APPEND в INBOX не удался: {str(e).replace(password, '***')}") from None
    finally:
        try:
            conn.logout()
        except (imaplib.IMAP4.error, OSError):
            pass


def deliver(raw: bytes, *, seen: bool = False) -> str:
    """`append_mail(raw, seen=seen)`, затем `poll_now()`: письмо в ящике и сразу разобрано. Возвращает строку
    вывода `poll_now()`; результат тест проверяет в интерфейсе."""
    append_mail(raw, seen=seen)
    return poll_now()


# --- Сброс стенда посреди круга (доп. 40 (г), (д); 8.3, 7.4) -----------------------------------

def reset_stand_and_relogin(browser, browser_context_args, stand_admin, admin_page=None) -> None:
    """Всё на стенде — с нуля: `E2E_RESET_CMD` (`e2e_reset_stand`), новый администратор круга, вход без второго кода.
    Аргументы — фикстуры теста (`browser`, `browser_context_args`, `stand_admin`, `admin_page`). Объект
    `stand_admin` остаётся тем же (поля переписываются), `helpers.ADMINS[browser.e2e_project]` указывает на него;
    куки `admin_page` заменяются куками нового `storage_state`. Без `E2E_RESET_CMD` — `AssertionError`.
    Звать первой строкой теста: всё заведённое раньше стирается."""
    reset = os.environ.get("E2E_RESET_CMD")
    if not reset:
        raise AssertionError("нужен E2E_RESET_CMD")
    subprocess.run(reset.split(), check=True, timeout=300)
    fresh = helpers.bootstrap_admin(browser, browser_context_args, conftest.create_first_admin)
    for item in dataclasses.fields(helpers.Account):
        setattr(stand_admin, item.name, getattr(fresh, item.name))
    helpers.ADMINS[browser.e2e_project] = stand_admin
    if admin_page is not None:
        context = admin_page.context
        context.clear_cookies()
        context.add_cookies(stand_admin.storage_state["cookies"])
        admin_page.goto("/")
        if "/login/" in admin_page.url:
            raise AssertionError("после сброса стенда администратор не вошёл: страница ведёт на /login/")


def reset_form_counters() -> None:
    """Стирает ключи порога формы `servicedesk:form:*` (7.4) в Valkey стенда через `helpers.stand_shell`: как
    `helpers.reset_counters`, прочие ключи не трогает."""
    helpers.stand_shell("import redis; from django.conf import settings; "
                        "r = redis.Redis.from_url(settings.VALKEY_URL); "
                        "print(sum(r.delete(k) for k in r.scan_iter(match='servicedesk:form:*')))")


# --- Письма в Mailpit по номеру заявки (доп. 40 (е); 10.1, 10.2) -------------------------------

def _addresses(short: dict, *keys: str) -> list:
    return [a["Address"].lower() for key in keys for a in (short.get(key) or [])]


def ticket_letters(mailpit, number: int, *, template: str | None = None, to: str | None = None,
                   recipient: str | None = None) -> list:
    """Краткие записи писем Mailpit, в теме которых есть `[#<number>]` целиком (`[#1]` не находит `[#12]`).
    Фильтры, если заданы: `template` — заголовок `X-Portal-Template` (10.2), `to` — адрес в `To`, `recipient` —
    адрес среди `To`, `Cc` и `Bcc`. «Адресу писем нет» проверяй по `recipient`: участник попадает в `Cc`.
    Смотрит последние 50 писем Mailpit (`MailpitClient.messages`); ящик чистится перед каждым тестом."""
    mark = f"[#{int(number)}]"
    found = []
    for short in mailpit.messages():
        if mark not in (short.get("Subject") or ""):
            continue
        if to is not None and to.lower() not in _addresses(short, "To"):
            continue
        if recipient is not None and recipient.lower() not in _addresses(short, "To", "Cc", "Bcc"):
            continue
        if template is not None and helpers.template_of(mailpit, short["ID"]) != template:
            continue
        found.append(short)
    return found


def wait_letter(mailpit, number: int, template: str, *, to: str | None = None, timeout: float = 60.0) -> dict:
    """Ждёт (до `timeout` с) письмо по заявке `number` с шаблоном `template` (10.1: например `ticket.reply`) и, если
    задан, адресом `to` в `To`; возвращает полное письмо (`mailpit.message`). Не пришло — `AssertionError`."""
    deadline = time.monotonic() + timeout
    while True:
        found = ticket_letters(mailpit, number, template=template, to=to)
        if found:
            return mailpit.message(found[0]["ID"])
        if time.monotonic() >= deadline:
            raise AssertionError(f"письмо «{template}» по заявке #{number} не пришло за {timeout:.0f} с")
        time.sleep(0.5)


def letter_headers(mailpit, message_id: str) -> dict:
    """Заголовки письма Mailpit (`/api/v1/message/<id>/headers`): ключи как в ответе, значения — списки
    (например, `Auto-Submitted`, 10.2)."""
    return helpers._mailpit_get(mailpit, f"/api/v1/message/{message_id}/headers")


def no_letter(mailpit, number: int, template: str, *, to=None, recipient=None, wait: float = 4.0) -> bool:
    """True, если за `wait` секунд писем по заявке `number` с шаблоном `template` (и `to`/`recipient`) нет."""
    time.sleep(wait)
    return not ticket_letters(mailpit, number, template=template, to=to, recipient=recipient)


# --- Таблицы для загрузки (доп. 40 (ж)) --------------------------------------------------------

def make_table(rows: list, fmt: str, delimiter: str = ";", *, bom: bool = False) -> bytes:
    """Таблица для загрузки заявителей (13.8): `rows` — строки, первая — заголовок. `fmt="csv"` — UTF-8 с
    разделителем `delimiter` (`bom=True` — с BOM), `fmt="xlsx"` — книга openpyxl, первый лист."""
    if fmt == "csv":
        out = io.StringIO()
        csv.writer(out, delimiter=delimiter, lineterminator="\r\n").writerows(rows)
        return out.getvalue().encode("utf-8-sig" if bom else "utf-8")
    if fmt == "xlsx":
        book = openpyxl.Workbook()
        sheet = book.active
        for row in rows:
            sheet.append(list(row))
        out = io.BytesIO()
        book.save(out)
        return out.getvalue()
    raise ValueError(f"формат {fmt!r}: нужен csv или xlsx")


# --- Настройка через интерфейс: домены (доп. 40 (з); 12.6, 13.7) ------------------------------

def _settings_form(page):
    page.goto("/servicedesk/")
    form = page.locator('form[data-form="servicedesk-settings"]')
    expect(form).to_be_visible()
    return form


def read_domains(page) -> list:
    """Список доменов со страницы `/servicedesk/` (`textarea[name=domains]` формы `servicedesk-settings`):
    строчные, без пустых."""
    value = _settings_form(page).locator("textarea[name=domains]").input_value()
    return [d.lower() for d in re.split(r"[,\s]+", value) if d]


def set_domains(page, domains: list) -> list:
    """Заменяет список доменов (форма `servicedesk-settings`, поле `domains`, по одному в строке; остальные поля
    формы остаются как есть). Ждёт 302 и `[role=status]`; отказ (`[data-error]` или `[role=alert][data-code]`, доп. 41 (б)) — `AssertionError` с `data-code`.
    Возвращает прежний список — тест вернёт его в `finally`."""
    form = _settings_form(page)
    before = [d.lower() for d in re.split(r"[,\s]+", form.locator("textarea[name=domains]").input_value()) if d]
    form.locator("textarea[name=domains]").fill("\n".join(domains))
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    alert = page.locator("[data-error], [role=alert][data-code]")  # доп. 41 (б): [data-warning] — не отказ
    if alert.count():
        raise AssertionError(f"список доменов не принят: {alert.first.get_attribute('data-code')} "
                             f"{alert.first.inner_text().strip()}")
    expect(page.locator("[role=status]").first).to_be_visible()
    return before


# --- Настройка через интерфейс: очереди (12.6, 13.7) -------------------------------------------

def _queue_form(page, kind: str, unit_id):
    """Форма `queue-mark` или `queue-default` узла: по скрытому полю `unit` (в дереве формы вложены в узлы)."""
    return page.locator(f'form[data-form="{kind}"]:has(input[name=unit][value="{unit_id}"])')


def open_queues(page) -> None:
    """Открывает `/servicedesk/queues/` и ждёт дерево `ul[data-unit-tree]`."""
    page.goto("/servicedesk/queues/")
    expect(page.locator("ul[data-unit-tree]")).to_be_visible()


def default_queue_id(page):
    """Номер очереди по умолчанию (`li[data-unit-id][data-default="true"]` на `/servicedesk/queues/`) или None."""
    open_queues(page)
    found = page.locator('ul[data-unit-tree] li[data-default="true"]')
    return found.first.get_attribute("data-unit-id") if found.count() else None


def default_queue_name(page) -> str:
    """Название очереди по умолчанию со страницы `/servicedesk/` (`[data-field="default-queue"]`); «не задана» —
    пустая строка. Метка `[data-field-label]` — рядом с полем, не внутри (доп. 41 (а)); вырезание метки ниже —
    страховка."""
    _settings_form(page)
    node = page.locator('[data-field="default-queue"]').first
    expect(node).to_be_visible()
    text = node.inner_text().strip()
    label = page.locator('[data-field-label="default-queue"]')
    if label.count():
        text = text.replace(label.first.inner_text().strip(), "", 1).strip()
    return "" if text == "не задана" else text


def mark_queue(page, unit_id) -> str:
    """Отмечает узел очередью (`form[data-form="queue-mark"]`, `action=mark`); ждёт `[role=status]` и `li[data-queue=
    "true"]`. Возвращает текст `[role=status]`; отказ — `AssertionError` с `data-code`."""
    return _queue_action(page, "queue-mark", unit_id)


def set_default_queue(page, unit_id) -> str:
    """Назначает очередь по умолчанию (`form[data-form="queue-default"]`, `action=default`); ждёт `[role=status]`
    и `li[data-default="true"]` у узла. Возвращает текст `[role=status]`; отказ — `AssertionError`."""
    return _queue_action(page, "queue-default", unit_id)


def _queue_action(page, kind: str, unit_id) -> str:
    open_queues(page)
    form = _queue_form(page, kind, unit_id)
    expect(form).to_have_count(1)
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    alert = page.locator("[data-error], [role=alert][data-code]")  # доп. 41 (б): [data-warning] — не отказ
    if alert.count():
        raise AssertionError(f"очередь {unit_id}: {kind} отказано: {alert.first.get_attribute('data-code')} "
                             f"{alert.first.inner_text().strip()}")
    expect(page.locator("[role=status]").first).to_be_visible()
    mark = "data-default" if kind == "queue-default" else "data-queue"
    expect(helpers_org.unit_li(page, unit_id).first).to_have_attribute(mark, "true")
    return helpers.status_text(page)


def add_queue_member(page, queue_id, user_ids, *, q: str = "") -> str:
    """Делает сотрудников участниками очереди: очередь — узел `org`, участник — его член
    (`helpers_org.add_members`). Нужно сотруднику без права `servicedesk.all`: взять заявку может участник очереди
    или держатель права (6.1). `q` — общая часть ФИО добавляемых (см. `add_members`). Возвращает текст
    `[role=status]`/`[role=alert]`."""
    return helpers_org.add_members(page, queue_id, user_ids, q=q)


def ensure_ready(page) -> tuple:
    """Готовность сервис-деска, проверяется по страницам при каждом вызове (сброс круга и
    `reset_stand_and_relogin` стирают настройки): домен `CORP_DOMAIN` в списке доменов и очередь по умолчанию есть;
    чего нет — заводит (домен дописывается к существующим; очередь — новый узел под корнем с уникальным именем
    `helpers_org.create_unit`, отметка и назначение). Никого участником не делает. Возвращает
    `(id очереди по умолчанию, её название)`."""
    domains = read_domains(page)
    if CORP_DOMAIN not in domains:
        set_domains(page, domains + [CORP_DOMAIN])
    queue_id = default_queue_id(page)
    if queue_id is None:
        name = helpers_org.unique_name("queue")
        queue_id = helpers_org.create_unit(page, name)
        mark_queue(page, queue_id)
        set_default_queue(page, queue_id)
    return queue_id, default_queue_name(page)


# --- Заявки (12.2, 13.2, 13.3) ------------------------------------------------------------------

def _check_word(word: str) -> None:
    if re.fullmatch(r"#?\d+", word.strip()):
        raise ValueError("слово из одних цифр поиск считает номером заявки (6.21, доп. 41 (в)): "
                         "нужно f't{secrets.token_hex(3)}'")


def ticket_number_by_subject(page, word: str) -> int:
    """Номер заявки по уникальному слову темы: `/tickets/?preset=all&q=<слово>` (12.2; без `preset` у администратора
    `my_queues`, без закрытых); ждёт ровно одну строку `tr[data-ticket]` (13.2) и возвращает `int`. Слово —
    `f"t{secrets.token_hex(3)}"` в теме (доп. 41 (в): строку из одних цифр поиск считает номером заявки — `ValueError`;
    слово короче двух знаков или с дефисом и точкой не годится — `parse` делит по `\\w+`). Звать после `deliver` /
    `poll_now` или после ответа формы: страница грузится один раз. Ноль или несколько строк — падение `expect`."""
    _check_word(word)
    page.goto("/tickets/?" + urllib.parse.urlencode({"preset": "all", "q": word}))
    rows = page.locator("#tickets-grid tr[data-ticket]")
    expect(rows).to_have_count(1)
    return int(rows.get_attribute("data-ticket"))


def tickets_by_subject(page, word: str) -> list:
    """Номера всех заявок, чья тема содержит слово `word` (`/tickets/?preset=all&q=<слово>`), по строкам первой
    страницы (до 50). Без ожидания числа строк: нужно для проверки «заявки нет» — смотри `expect` на
    `[data-empty-state="tickets"]` или пустой список после загрузки страницы. Слово — как у
    `ticket_number_by_subject` (доп. 41 (в))."""
    _check_word(word)
    page.goto("/tickets/?" + urllib.parse.urlencode({"preset": "all", "q": word}))
    page.wait_for_load_state()
    expect(page.locator("[data-tickets-list]")).to_be_visible()  # корень страницы есть и при пустом списке
    return [int(r.get_attribute("data-ticket")) for r in page.locator("#tickets-grid tr[data-ticket]").all()]


def open_ticket(page, number: int):
    """Открывает карточку `/tickets/<номер>/` страницей целиком и ждёт корень
    `[data-ticket-card][data-number="<номер>"]` (13.3). Возвращает локатор корня карточки."""
    page.goto(f"/tickets/{int(number)}/")
    card = page.locator(f'[data-ticket-card][data-number="{int(number)}"]')
    expect(card).to_be_visible()
    return card


def field_text(card, name: str) -> str:
    """Текст поля карточки `[data-field="<name>"]` (13.3: `status`, `queue`, `source`, `requester-name`,
    `requester-email`, `assignee` …): только значение — метка `[data-field-label]` стоит рядом с полем (доп. 41 (а));
    вырезание метки ниже — страховка. Пустое поле — «не заполнено» / «не назначен» и `data-empty="true"`."""
    node = card.locator(f'[data-field="{name}"]').first
    expect(node).to_be_visible()
    text = node.inner_text().strip()
    label = node.locator("[data-field-label]")
    if label.count():
        text = text.replace(label.first.inner_text().strip(), "", 1).strip()
    return text


# --- «Входящие письма» (12.6, 13.8) ---------------------------------------------------------------

def open_inbound(page) -> None:
    """Открывает `/servicedesk/inbound/` и ждёт блок состояния ящика `[data-mailbox-status]` (13.8)."""
    page.goto("/servicedesk/inbound/")
    expect(page.locator("[data-mailbox-status]")).to_be_visible()


def inbound_row(page, *, subject: str | None = None, sender: str | None = None):
    """Локатор строк `tr[data-inbound]` на открытой странице «Входящие письма»: с подстрокой в
    `[data-cell="subject"]` и/или `[data-cell="sender"]`. Не переходит на страницу (`open_inbound`); строк может
    быть несколько — тест ждёт `expect(...).to_have_count(1)`. Только первая страница (50 строк, новые сверху)."""
    rows = page.locator("tr[data-inbound]")
    if subject is not None:
        rows = rows.filter(has=page.locator('[data-cell="subject"]', has_text=subject))
    if sender is not None:
        rows = rows.filter(has=page.locator('[data-cell="sender"]', has_text=sender))
    return rows


def inbound_outcome(page, *, subject: str | None = None, sender: str | None = None) -> str:
    """Итог письма: открывает «Входящие письма», ждёт ровно одну строку по теме/отправителю и возвращает текст
    `[data-cell="outcome"]` (подписи итогов — § 14, например «отклонено: чужой домен»)."""
    open_inbound(page)
    row = inbound_row(page, subject=subject, sender=sender)
    expect(row).to_have_count(1)
    return row.locator('[data-cell="outcome"]').inner_text().strip()


def inbound_mail_id(page, *, subject: str | None = None, sender: str | None = None) -> int:
    """Номер письма (`tr[data-inbound][data-id]`) по теме/отправителю на странице «Входящие письма»
    (открывает её; нужен маршруту `/servicedesk/inbound/<id>/retry/`)."""
    open_inbound(page)
    row = inbound_row(page, subject=subject, sender=sender)
    expect(row).to_have_count(1)
    return int(row.get_attribute("data-id"))
