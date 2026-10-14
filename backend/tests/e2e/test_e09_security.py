"""T-4148: сценарий 9 — безопасность, вход с нового устройства: письма ядра остаются, а на портале появляются записи
«Вход с нового устройства», «Пароль изменён», «Второй фактор сброшен»; выключить их нельзя (FR-305, FR-313, FR-321,
FR-330).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-004.md):
- каждый тест заводит своего сотрудника (`employee()` — активирован, сессия в `account.page`) и сверяет число и строки
  списка с тем, что было до события: у других тестов круга свои сотрудники, у нового сотрудника уведомлений нет, но
  отсчёт всё равно берётся перед событием;
- «новое устройство» — вход в новом контексте браузера (признаки среза 001: другая кука устройства); письма ядра —
  `helpers.wait_mail` по заголовку `X-Portal-Template` (`new_device`, `password_changed`, `second_factor_reset`,
  `account_locked`, `invitation`, `password_reset`);
- тексты уведомлений — § 15.1, браузер в тексте «Вход с нового устройства» сверяется с устройством на странице
  `/me/security/devices/` (его туда записал `devices.parse_user_agent` — решение E27), время — по Москве;
- число колокольчика читается `helpers_notify.bell_count` после готовности соединения (решение E21);
- общих настроек стенда тест не меняет: тихие часы и режим — настройки самого сотрудника теста; блокировка записи
  снимается у администратора в `finally`.
"""
import re
import secrets
from datetime import datetime, timedelta, timezone

from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers, helpers_notify, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_servicedesk import build_mail

MSK = timezone(timedelta(hours=3), "MSK")  # Москва без перехода на летнее время (NFR-307)
NEW_IN_QUEUE = "servicedesk.new_in_queue"
TEXT_NEW_DEVICE = "Вход с нового устройства"  # § 15.1: «Вход с нового устройства (<браузер>, <ДД.ММ.ГГГГ ЧЧ:ММ>)»
TEXT_PW_CHANGED = "Пароль изменён"
TEXT_SECOND_FACTOR = "Второй фактор сброшен"
NEW_DEVICE_RE = re.compile(r"^Вход с нового устройства \((?P<browser>.+), (?P<at>\d{2}\.\d{2}\.\d{4} \d{2}:\d{2})\)$")
SECURITY_URL = "/me/security/"  # Notification.url видов безопасности (§ 3.5, решение A1)
FIXED_SECURITY = "Безопасность: всегда"  # § 15.5
FIXED_UNBOUND = "Канал отвязан: всегда, только на портале"  # § 15.5
BELL_WAIT_MS = 15_000  # ожидание числа там, где срок 2 с (NFR-301) не проверяется
MAIL_WAIT = 60.0  # письма ядра уходят за секунды; предел — минута (SPEC-001 FR-052)


# --- Общие помощники файла ----------------------------------------------------------------------------

def _now() -> datetime:
    return datetime.now(MSK)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _minutes(start: datetime, end: datetime) -> set:
    """Все минуты от `start` до `end` (по Москве) в виде `ДД.ММ.ГГГГ ЧЧ:ММ`: событие произошло между этими отметками."""
    moment = start.replace(second=0, microsecond=0)
    found = set()
    while moment <= end:
        found.add(moment.strftime("%d.%m.%Y %H:%M"))
        moment += timedelta(minutes=1)
    return found


def _has_russian(mail: dict) -> bool:
    return re.search(r"[А-Яа-я]", mail["Subject"] + mail["Text"]) is not None


def _change_password(page, current: str, new: str) -> None:
    """Смена своего пароля на `/me/security/password/` (образец — test_s16): ждёт перехода после отправки."""
    page.goto("/me/security/password/")
    page.fill("input[name=current_password]", current)
    page.fill("input[name=password1]", new)
    page.fill("input[name=password2]", new)
    with page.expect_navigation():
        page.locator("form:has(input[name=current_password]) button[type=submit]").click()
    page.wait_for_load_state()
    assert not helpers.alert_text(page), f"пароль не сменён: {helpers.alert_text(page)}"


def _reset_second_factor(admin_page, account) -> None:
    """Администратор сбрасывает второй фактор на карточке сотрудника (вкладка «Безопасность», образец — test_s07)."""
    admin_page.goto(f"/staff/{account.id}/")
    helpers.open_security_tab(admin_page)
    helpers.submit(admin_page.locator('form[action$="/reset-2fa/"]'))


def _reconnect(page, account) -> None:
    """Вход после сброса: пароль ведёт только на подключение второго фактора (ограниченная сессия — у неё нет
    колокольчика, § 14.1), затем новый ключ и новые резервные коды; в конце сотрудник вошёл полностью."""
    helpers.fill_login(page, account.email, account.password)
    page.wait_for_url(re.compile(r"/me/security/totp/"))
    expect(page.locator("#notify-bell")).to_have_count(0)
    seed = page.locator("#totp-secret").inner_text().strip()
    page.fill("input[name=code]", helpers.totp_for(seed))
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/me/security/backup-codes/"))
    codes = [c.strip() for c in page.locator("code.backup-code").all_inner_texts()]
    page.locator("input[name=confirm]").check()
    page.click("button[type=submit]")
    expect(page.locator("#top-bar")).to_be_visible()
    account.totp_secret, account.backup_codes = seed, codes


def _list(page) -> list:
    """Строки `/notifications/` (первая страница, новые сверху) как словари: `id`, `unread`, `text` (нормализованный),
    `href` (адрес открытия), `at` (значение `time[data-at]`), `shown` (видимый текст времени). Страница только читается."""
    page.goto("/notifications/")
    expect(page.locator("[data-notify-list]")).to_be_visible()
    rows = []
    for item in page.locator("ul[data-notifications] li[data-notification]").all():
        link = item.locator('[data-field="text"] a[data-open]')
        stamp = item.locator("time[data-at]")
        rows.append({
            "id": item.get_attribute("data-notification"),
            "unread": item.get_attribute("data-unread"),
            "text": _norm(item.locator('[data-field="text"]').inner_text()),
            "href": link.get_attribute("href") if link.count() else "",
            "at": stamp.first.get_attribute("data-at") if stamp.count() else "",
            "shown": _norm(stamp.first.inner_text()) if stamp.count() else "",
        })
    return rows


def _with_text(rows: list, text: str) -> list:
    """Строки, чей текст равен `text` (для «Вход с нового устройства» — начинается с него)."""
    if text == TEXT_NEW_DEVICE:
        return [r for r in rows if NEW_DEVICE_RE.match(r["text"])]
    return [r for r in rows if r["text"] == text]


def _count_now(page) -> int:
    """Число колокольчика при готовом соединении (решение E21)."""
    helpers_notify.wait_ws_open(page)
    return helpers_notify.bell_count(page)


def _quiet_form(page):
    page.goto("/me/notifications/")
    form = page.locator('form[data-form="notify-prefs"]')
    expect(form).to_be_visible()
    return form


def _save_prefs(page, form, mode: str) -> None:
    """Отправляет форму «Мои уведомления» и проверяет, что режим тихих часов сохранён."""
    with page.expect_navigation():
        form.locator('button[type=submit][data-action="save-prefs"]').click()
    page.wait_for_load_state()
    assert not helpers.alert_text(page), f"настройки не сохранены: {helpers.alert_text(page)}"
    expect(page.locator("[role=status]").first).to_be_visible()
    expect(page.locator(f'fieldset[data-quiet] input[name="quiet_mode"][value="{mode}"]')).to_be_checked()


def _own_hours_not_now(page) -> None:
    """Включает «Почту» вида «Новая заявка в моей очереди» и «Свои часы», которые начинаются через час и кончаются через
    два (все семь дней): сейчас — нерабочее (тихое) время сотрудника при любом часе суток (§ 6.6: рабочее — внутри
    интервала, «с» позже «до» — через полночь)."""
    form = _quiet_form(page)
    cell = form.locator(f'tr[data-notify-kind="{NEW_IN_QUEUE}"] td[data-channel="email"] '
                        f'input[type=checkbox][name="cell"][value="{NEW_IN_QUEUE}:email"]')
    expect(cell).to_have_count(1)
    cell.set_checked(True)
    quiet = form.locator("fieldset[data-quiet]")
    quiet.locator('input[type=radio][name="quiet_mode"][value="own"]').check()
    for day in range(7):
        quiet.locator(f'input[type=checkbox][name="own_days"][value="{day}"]').set_checked(True)
    now = _now()
    quiet.locator('input[type=time][name="own_start"]').fill((now + timedelta(hours=1)).strftime("%H:%M"))
    quiet.locator('input[type=time][name="own_end"]').fill((now + timedelta(hours=2)).strftime("%H:%M"))
    _save_prefs(page, form, "own")
    expect(cell).to_be_checked()


def _no_quiet_hours(page) -> None:
    """Режим «Без тихих часов» (накопленное за тихие часы уходит сводкой сразу — решение C1)."""
    form = _quiet_form(page)
    form.locator('fieldset[data-quiet] input[type=radio][name="quiet_mode"][value="none"]').check()
    _save_prefs(page, form, "none")


def _send_mail(subject: str, word: str) -> None:
    """Письмо заявителя в ящик заявок и сразу разбор: заявка создана в очереди по умолчанию."""
    helpers_sd.deliver(build_mail(from_addr=helpers_sd.requester_email(), to=[MAILBOX], subject=subject,
                                  text=f"Нужна помощь {word}", message_id=f"<{secrets.token_hex(8)}@client.test>"))


def _forgot(page, email: str) -> None:
    """Просит ссылку восстановления пароля (образец — test_s18); ждёт ответ портала."""
    page.goto("/login/")
    page.get_by_text("Забыли пароль?").first.click()
    page.wait_for_url(re.compile(r"/password/forgot/"))
    page.fill("input[name=email]", email)
    page.click("button[type=submit]")
    page.locator("[role=status], [role=alert]").first.wait_for()


def _lock_account(page, email: str) -> None:
    """Пять неверных паролей подряд: запись блокируется (образец — test_s09)."""
    for _ in range(5):
        helpers.fill_login(page, email, factories.new_password())
        expect(page.locator("[role=alert]").first).to_be_visible()


def _unlock(admin_page, account) -> None:
    """Снимает блокировку входа записи и адреса (`/staff/locks/`, CONTRACT.md): прочие тесты идут с того же адреса."""
    admin_page.goto("/staff/locks/")
    rows = admin_page.locator(f'[data-lock-kind="account"][data-lock-target="{account.id}"]')
    if rows.count():
        helpers.submit(rows.first.locator("form"))
    admin_page.goto("/staff/locks/")
    for _ in range(admin_page.locator('[data-lock-kind="ip"]').count()):
        helpers.submit(admin_page.locator('[data-lock-kind="ip"]').first.locator("form"))
        admin_page.goto("/staff/locks/")


def _enable_queue_mail(page) -> None:
    """Включает «Почту» вида «Новая заявка в моей очереди» и режим «Без тихих часов»: письмо уведомления по заявке уходит
    после обхода `tick(shift=…)` в любое время суток (нужно для положительного контроля «письма notify.item»)."""
    form = _quiet_form(page)
    cell = form.locator(f'tr[data-notify-kind="{NEW_IN_QUEUE}"] td[data-channel="email"] '
                        f'input[type=checkbox][name="cell"][value="{NEW_IN_QUEUE}:email"]')
    expect(cell).to_have_count(1)
    cell.set_checked(True)
    form.locator('fieldset[data-quiet] input[type=radio][name="quiet_mode"][value="none"]').check()
    _save_prefs(page, form, "none")
    expect(cell).to_be_checked()


def _queue_with_member(admin_page, member, tag: str) -> tuple:
    """Очередь с одним участником (`member`, его полное имя начинается с уникальной метки `tag`), у которого включена
    «Почта» вида «Новая заявка…»: (id очереди, id очереди по умолчанию до теста). Очередью по умолчанию её делает
    `_mail_control`."""
    old_id, _ = helpers_sd.ensure_ready(admin_page)
    queue_name = helpers_org.unique_name("Поддержка")
    queue_id = helpers_org.create_unit(admin_page, queue_name)
    helpers_sd.mark_queue(admin_page, queue_id)
    admin_page.goto(f"/structure/{queue_id}/")
    mode = "concurrent" if admin_page.locator("#unit-card select[name=mode]").count() else None
    note = helpers_org.add_members(admin_page, queue_id, [member.id], q=tag, mode=mode)
    assert "уже участник" not in note, note
    _enable_queue_mail(member.page)
    return queue_id, old_id


def _mail_control(admin_page, member, mailpit, queue_id, old_id) -> None:
    """Положительный контроль «письма notify.item нет»: у того же сотрудника событие вида с включённой почтой («Новая
    заявка в моей очереди») после того же `tick(shift=121)` даёт письмо. Без него проверка прошла бы и на реализации,
    у которой письмо уведомлений для сотрудника не включено или обход его не поднял."""
    try:
        helpers_sd.set_default_queue(admin_page, queue_id)
        seen = helpers.mail_ids(mailpit, member.email)
        word = "k" + secrets.token_hex(3)
        _send_mail(f"Не работает принтер {word}", word)
        helpers_notify.tick(shift=121)
        helpers_notify.wait_item_mail(mailpit, member.email, seen=seen)
    finally:
        helpers_sd.set_default_queue(admin_page, old_id)


def _admin_unblock(admin_page, account) -> None:
    """Снимает блокировку администратора (`/staff/<id>/unblock/`), если она стоит."""
    admin_page.goto(f"/staff/{account.id}/")
    helpers.open_security_tab(admin_page)
    form = admin_page.locator('form[action$="/unblock/"]')
    if form.count():
        helpers.submit(form)


def _open_and_check(page, row: dict) -> None:
    """Открытие записи из списка ведёт на `/me/security/` (ссылка записи, § 3.5, § 15.1) и отмечает её прочитанной."""
    assert row["href"] == f"/notifications/{row['id']}/open/", row
    before = _count_now(page)
    page.goto(row["href"])
    page.wait_for_url(re.compile(r"/me/security/$"))
    helpers_notify.wait_ws_open(page)
    helpers_notify.wait_bell_count(page, before - 1, timeout_ms=BELL_WAIT_MS)


# --- Тесты ------------------------------------------------------------------------------------------

def test_e09_login_from_new_device_sends_core_mail_and_portal_notification_with_browser_and_time(
        employee, mailpit, new_context):
    """Сценарий 9, п. 1: вход с нового устройства (новый контекст браузера) — письмо ядра «вход с нового устройства» и
    на портале у сотрудника непрочитанное уведомление «Вход с нового устройства (браузер, время)»: браузер тот, что
    записан за устройством, время — московское, число колокольчика выросло на 1 (FR-305)."""
    acc = employee()
    watcher = acc.page
    watcher.goto("/")
    base = _count_now(watcher)
    seen = helpers.mail_ids(mailpit, acc.email)
    # когда: вход из нового контекста
    other = new_context().new_page()
    started = _now()
    helpers.sign_in(other, acc)
    # п. 1: письмо ядра
    mail = helpers.wait_mail(mailpit, acc.email, "new_device", seen=seen, timeout=MAIL_WAIT)
    assert _has_russian(mail)
    # п. 1: колокольчик открытой вкладки сотрудника вырос на 1 по соединению, без перезагрузки
    helpers_notify.wait_bell_count(watcher, base + 1, timeout_ms=BELL_WAIT_MS)
    finished = _now()
    # п. 1: в списке — одна непрочитанная запись «Вход с нового устройства (<браузер>, <время>)»
    rows = _with_text(_list(other), TEXT_NEW_DEVICE)
    assert len(rows) == 1, rows
    row = rows[0]
    assert row["unread"] == "1"
    found = NEW_DEVICE_RE.match(row["text"])
    # п. 1: браузер — тот, что записан за новым устройством (решение E27), а не буквальное «Chrome»
    other.goto("/me/security/devices/")
    current = other.locator('[data-device-id][data-current="true"]')
    expect(current).to_have_count(1)
    assert found["browser"].strip() and found["browser"] in current.inner_text(), (found["browser"], current.inner_text())
    # п. 1: время — по Москве, между началом входа и появлением записи; время в списке то же
    assert found["at"] in _minutes(started - timedelta(minutes=1), finished + timedelta(minutes=1)), found["at"]
    moment = datetime.fromisoformat(row["at"])
    assert moment.utcoffset() == timedelta(hours=3), row["at"]
    assert started - timedelta(minutes=1) <= moment <= finished + timedelta(minutes=1), row["at"]
    assert row["shown"] == moment.astimezone(MSK).strftime("%d.%m.%Y %H:%M"), row
    # то же уведомление видно и в первой вкладке сотрудника (одна учётная запись)
    assert _with_text(_list(watcher), TEXT_NEW_DEVICE)[0]["id"] == row["id"]


def test_e09_password_change_sends_core_mail_and_password_changed_notification(
        admin_page, employee, mailpit, new_context):
    """Сценарий 9, п. 2: сотрудник сменил пароль — письмо ядра «пароль изменён» и на портале одно новое уведомление
    «Пароль изменён»; отдельного письма от уведомлений нет (у видов безопасности доставок нет, FR-305);
    контроль — у того же сотрудника событие вида с включённой почтой после того же обхода даёт письмо уведомления."""
    tag = "Смена" + secrets.token_hex(3)
    acc = employee(full_name=f"{tag} Петр Петрович")
    page = acc.page
    queue_id, old_id = _queue_with_member(admin_page, acc, tag)
    before_rows = _with_text(_list(page), TEXT_PW_CHANGED)
    base = _count_now(page)
    seen = helpers.mail_ids(mailpit, acc.email)
    fresh_pw = factories.new_password()
    # когда: смена пароля
    _change_password(page, acc.password, fresh_pw)
    acc.password = fresh_pw
    # п. 2: письмо ядра
    mail = helpers.wait_mail(mailpit, acc.email, "password_changed", seen=seen, timeout=MAIL_WAIT)
    assert _has_russian(mail)
    assert fresh_pw not in mail["Text"]
    # п. 2: уведомление «Пароль изменён» — одно новое, непрочитанное; число колокольчика выросло на 1
    page.goto("/notifications/")
    helpers_notify.wait_ws_open(page)
    helpers_notify.wait_bell_count(page, base + 1, timeout_ms=BELL_WAIT_MS)
    rows = _with_text(_list(page), TEXT_PW_CHANGED)
    assert len(rows) == len(before_rows) + 1, rows
    assert [r for r in rows if r["id"] not in {b["id"] for b in before_rows}][0]["unread"] == "1"
    # п. 2: у видов безопасности доставок нет — после срока письма уведомление отдельным письмом не уходит
    helpers_notify.tick(shift=121)
    assert helpers_notify.no_item_mail(mailpit, acc.email, wait=4)
    # контроль: тот же обход поднимает письмо уведомления вида с включённой почтой («Новая заявка в моей очереди»)
    _mail_control(admin_page, acc, mailpit, queue_id, old_id)
    # п. 2: новый пароль работает (смена прошла по-настоящему)
    helpers.sign_in(new_context().new_page(), acc)


def test_e09_second_factor_reset_by_admin_sends_mail_at_once_and_notification_appears_after_employee_login(
        admin_page, employee, mailpit, new_context):
    """Сценарий 9, п. 3: администратор сбросил второй фактор — письмо ядра уходит сразу; уведомление «Второй фактор
    сброшен» появляется на портале, когда сотрудник после повторного подключения фактора вошёл (FR-305)."""
    acc = employee()
    seen = helpers.mail_ids(mailpit, acc.email)
    # когда: администратор сбрасывает второй фактор
    _reset_second_factor(admin_page, acc)
    # п. 3: письмо ядра уходит сразу
    mail = helpers.wait_mail(mailpit, acc.email, "second_factor_reset", seen=seen, timeout=MAIL_WAIT)
    assert _has_russian(mail)
    # прежняя сессия сотрудника закрыта сбросом: портал просит войти
    acc.page.goto("/notifications/")
    assert "/login/" in acc.page.url, acc.page.url
    # п. 3: вход ведёт только на подключение фактора — колокольчика и списка уведомлений ещё нет (ограниченная сессия)
    page = new_context().new_page()
    _reconnect(page, acc)
    # п. 3: после повторного подключения и входа запись есть: одна, непрочитанная, число колокольчика не нулевое
    rows = _with_text(_list(page), TEXT_SECOND_FACTOR)
    assert len(rows) == 1 and rows[0]["unread"] == "1", rows
    helpers_notify.wait_ws_open(page)
    assert helpers_notify.bell_count(page) == 1
    # п. 3: запись ведёт на страницу безопасности и открытие отмечает её прочитанной
    _open_and_check(page, rows[0])


def test_e09_security_kinds_in_my_notifications_have_no_checkboxes_and_cannot_be_switched_off(employee, mailpit):
    """Сценарий 9, п. 4: в «Моих уведомлениях» виды безопасности — отдельной сводной строкой «Безопасность: всегда»
    без галочек; ни одной ячейки с их кодом нет, подделанная отправка с такой ячейкой не отключает виды безопасности, и событие
    безопасности всё равно даёт уведомление (FR-305, FR-321)."""
    acc = employee()
    page = acc.page
    page.goto("/me/notifications/")
    root = page.locator("#notify-prefs-root[data-notify-prefs]")
    expect(root).to_be_visible()
    # п. 4: сводные строки «Безопасность: всегда» и «Канал отвязан: …» — без полей ввода
    fixed = root.locator("tbody[data-fixed-rows]")
    security = fixed.locator('tr[data-notify-fixed="security"]')
    expect(security).to_have_count(1)
    assert FIXED_SECURITY in _norm(security.inner_text())
    expect(security.locator("input")).to_have_count(0)
    unbound = fixed.locator('tr[data-notify-fixed="channel_unbound"]')
    expect(unbound).to_have_count(1)
    assert FIXED_UNBOUND in _norm(unbound.inner_text())
    expect(unbound.locator("input")).to_have_count(0)
    expect(fixed.locator("input")).to_have_count(0)
    # п. 4: строк и ячеек с кодами видов безопасности в таблице видов нет — выключить нечем
    expect(root.locator('table[data-notify-table] tr[data-notify-kind^="core."]')).to_have_count(0)
    expect(root.locator('input[name="cell"][value^="core."]')).to_have_count(0)
    # п. 4: подделанная отправка с ячейкой вида безопасности: сервис отбрасывает такие коды, виды `core.*` остаются без
    # ячеек и всегда включены (прочие виды такой POST выключает по § 13.2 — здесь это не проверяется)
    response = helpers_org.direct_post(page, "/me/notifications/",
                                       {"table": "1", "cell": "core.password_changed:email"})
    assert response.status in (200, 302), response.status
    page.goto("/me/notifications/")
    expect(page.locator('#notify-prefs-root input[name="cell"][value^="core."]')).to_have_count(0)
    expect(page.locator('#notify-prefs-root tr[data-notify-fixed="security"]')).to_have_count(1)
    # п. 4: событие безопасности всё равно создаёт уведомление
    before = len(_with_text(_list(page), TEXT_PW_CHANGED))
    seen = helpers.mail_ids(mailpit, acc.email)
    fresh_pw = factories.new_password()
    _change_password(page, acc.password, fresh_pw)
    acc.password = fresh_pw
    helpers.wait_mail(mailpit, acc.email, "password_changed", seen=seen, timeout=MAIL_WAIT)
    assert len(_with_text(_list(page), TEXT_PW_CHANGED)) == before + 1


def test_e09_block_invite_and_password_recovery_give_only_core_mails_and_no_portal_notifications(
        admin_page, employee, mailpit, new_context):
    """Сценарий 9, п. 5: блокировка записи (пять неверных паролей и блокировка администратором), приглашение и запрос
    восстановления пароля — только письма ядра (у блокировки администратором письма может не быть — это не проверяется);
    число колокольчика и список уведомлений не изменились. Контроли того же теста: смена пароля — событие безопасности —
    число и список меняет, а событие вида с включённой почтой даёт письмо уведомления (FR-305)."""
    tag = "Блок" + secrets.token_hex(3)
    victim = employee(full_name=f"{tag} Петр Петрович")
    invited = employee(activate=False)
    queue_id, old_id = _queue_with_member(admin_page, victim, tag)
    page = victim.page
    base_rows = _list(page)
    base = _count_now(page)
    guest = new_context().new_page()
    try:
        # п. 5: восстановление пароля — только письмо ядра
        _forgot(guest, victim.email)
        helpers.wait_mail(mailpit, victim.email, "password_reset", timeout=MAIL_WAIT)
        # п. 5: приглашение (повторное) — только письмо ядра; приглашённый, активировавшись, видит пустой список
        seen = helpers.mail_ids(mailpit, invited.email)
        admin_page.goto(f"/staff/{invited.id}/")
        helpers.open_security_tab(admin_page)
        helpers.submit(admin_page.locator('form[action$="/invite/"]'))
        second = helpers.wait_mail(mailpit, invited.email, "invitation", seen=seen, timeout=MAIL_WAIT)
        guest_page = new_context().new_page()
        helpers.walk_activation(guest_page, helpers.link_in(second, "/activate/"), invited.password)
        guest_page.goto("/notifications/")
        expect(guest_page.locator('[data-empty-state="notifications"]')).to_be_visible()
        assert _count_now(guest_page) == 0
        # п. 5: блокировка записи — только письмо ядра о блокировке
        seen = helpers.mail_ids(mailpit, victim.email)
        _lock_account(guest, victim.email)
        helpers.wait_mail(mailpit, victim.email, "account_locked", seen=seen, timeout=MAIL_WAIT)
        # п. 5: блокировка администратором (`/staff/<id>/block/`, причина) — портального уведомления нет; письма — какие даёт
        # ядро (их отсутствие не проверяется)
        _unlock(admin_page, victim)
        admin_page.goto(f"/staff/{victim.id}/")
        helpers.open_security_tab(admin_page)
        block = admin_page.locator('form[action$="/block/"]')
        block.locator("[name=reason]").fill("Проверка приёмки: блокировка администратором")
        helpers.submit(block)
        admin_page.goto("/staff/?state=blocked")
        expect(admin_page.locator(f'tr[data-user-id="{victim.id}"][data-state="blocked"]')).to_have_count(1)
    finally:
        try:
            _admin_unblock(admin_page, victim)
        finally:
            _unlock(admin_page, victim)
    # после снятия блокировки сотрудник входит с того же устройства (сессия могла остаться)
    page.goto("/notifications/")
    if "/login/" in page.url:
        helpers.sign_in(page, victim)
    # п. 5: список и число колокольчика не изменились
    after_rows = _list(page)
    assert [r["id"] for r in after_rows] == [r["id"] for r in base_rows], (base_rows, after_rows)
    assert _count_now(page) == base
    # п. 5: письмо уведомлений не приходило ни по одному из событий
    helpers_notify.tick(shift=121)
    assert helpers_notify.no_item_mail(mailpit, victim.email, wait=4)
    # контроль: событие безопасности на том же сотруднике даёт запись и число
    fresh_pw = factories.new_password()
    _change_password(page, victim.password, fresh_pw)
    victim.password = fresh_pw
    helpers_notify.wait_bell_count(page, base + 1, timeout_ms=BELL_WAIT_MS)
    assert len(_list(page)) == len(base_rows) + 1
    # контроль: тот же обход поднимает письмо уведомления вида с включённой почтой («Новая заявка в моей очереди»)
    _mail_control(admin_page, victim, mailpit, queue_id, old_id)


def test_e09_security_event_in_quiet_hours_core_mail_not_delayed_and_not_in_digest(
        admin_page, employee, mailpit, new_context):
    """Сценарий 9, п. 6: у сотрудника сейчас тихие часы («Свои часы» не включают текущее время) — письма ядра о входе с
    нового устройства и о смене пароля приходят сразу, запись на портале есть; в сводку за нерабочее время они не
    попадают: сводка при смене режима на «Без тихих часов» содержит только заявку из очереди (контроль) (FR-305, FR-330)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = "Тихие" + secrets.token_hex(3)
    member = employee(full_name=f"{tag}1 Петр Петрович")
    queue_name = helpers_org.unique_name("Поддержка")
    queue_id = helpers_org.create_unit(page, queue_name)
    helpers_sd.mark_queue(page, queue_id)
    page.goto(f"/structure/{queue_id}/")
    mode = "concurrent" if page.locator("#unit-card select[name=mode]").count() else None
    note = helpers_org.add_members(page, queue_id, [member.id], q=tag, mode=mode)
    assert "уже участник" not in note, note
    try:
        helpers_sd.set_default_queue(page, queue_id)
        # дано: тихие часы сейчас, «Почта» вида «Новая заявка в моей очереди» включена
        _own_hours_not_now(member.page)
        # когда: вход с нового устройства и смена пароля в тихие часы
        seen = helpers.mail_ids(mailpit, member.email)
        other = new_context().new_page()
        helpers.sign_in(other, member)
        helpers.wait_mail(mailpit, member.email, "new_device", seen=seen, timeout=MAIL_WAIT)
        seen = helpers.mail_ids(mailpit, member.email)
        fresh_pw = factories.new_password()
        _change_password(other, member.password, fresh_pw)
        member.password = fresh_pw
        helpers.wait_mail(mailpit, member.email, "password_changed", seen=seen, timeout=MAIL_WAIT)
        # п. 6: письма ядра пришли сразу (за минуту, а не к началу рабочего времени)
        # п. 6: записи на портале есть
        rows = _list(other)
        assert len(_with_text(rows, TEXT_NEW_DEVICE)) == 1 and len(_with_text(rows, TEXT_PW_CHANGED)) == 1, rows
        # контроль: заявка в очереди в тихие часы копится для сводки (письмо уведомления не уходит)
        word = "t" + secrets.token_hex(3)
        subject = f"Не работает принтер {word}"
        base = _count_now(other)
        _send_mail(subject, word)
        helpers_notify.wait_bell_count(other, base + 1, timeout_ms=BELL_WAIT_MS)
        number = helpers_sd.ticket_number_by_subject(page, word)
        text = f"Новая заявка #{number} в очереди «{queue_name}»: {subject}"
        assert any(_norm(text) == r["text"] for r in _list(other)), text
        assert helpers_notify.no_item_mail(mailpit, member.email, wait=3)
        # когда: начало рабочего времени — режим «Без тихих часов»; накопленное уходит сводкой сразу
        _no_quiet_hours(other)
        helpers_notify.tick()
        digest = helpers_notify.wait_digest_mail(mailpit, member.email)
        # п. 6: в сводке одно уведомление — заявка; записей безопасности нет ни в теме, ни в теле
        assert digest["Subject"] == "За нерабочее время: 1 уведомление", digest["Subject"]
        assert _norm(text) in _norm(digest["Text"])
        assert TEXT_NEW_DEVICE not in digest["Text"] and TEXT_PW_CHANGED not in digest["Text"], digest["Text"]
        # и после сводки отдельного письма по записям безопасности нет
        assert helpers_notify.no_item_mail(mailpit, member.email, wait=4)
    finally:
        helpers_sd.set_default_queue(page, old_id)


def test_e09_new_device_password_change_and_second_factor_reset_create_notifications_from_bus_events(
        admin_page, employee, mailpit, new_context):
    """Сценарий 9, п. 8: вход с нового устройства, смена пароля и сброс второго фактора — по каждому событию ядра на
    портале создаётся уведомление: три записи, новые сверху, со ссылкой на страницу безопасности; число колокольчика
    открытой вкладки растёт сразу по соединению. Шина из браузера не видна — проверяется её следствие (FR-313, FR-305)."""
    acc = employee()
    watcher = acc.page
    watcher.goto("/")
    helpers_notify.wait_ws_open(watcher)
    # событие 1: смена пароля — запись «Пароль изменён», число выросло
    seen = helpers.mail_ids(mailpit, acc.email)
    fresh_pw = factories.new_password()
    _change_password(watcher, acc.password, fresh_pw)
    acc.password = fresh_pw
    helpers.wait_mail(mailpit, acc.email, "password_changed", seen=seen, timeout=MAIL_WAIT)
    watcher.goto("/notifications/")
    base = _count_now(watcher)
    assert base >= 1 and len(_with_text(_list(watcher), TEXT_PW_CHANGED)) == 1
    # событие 2: вход с нового устройства — запись, число открытой вкладки выросло по соединению без перезагрузки
    watcher.goto("/")
    helpers_notify.wait_ws_open(watcher)
    seen = helpers.mail_ids(mailpit, acc.email)
    other = new_context().new_page()
    helpers.sign_in(other, acc)
    helpers.wait_mail(mailpit, acc.email, "new_device", seen=seen, timeout=MAIL_WAIT)
    helpers_notify.wait_bell_count(watcher, base + 1, timeout_ms=BELL_WAIT_MS)
    # событие 3: сброс второго фактора — запись появляется после повторного подключения и входа
    seen = helpers.mail_ids(mailpit, acc.email)
    _reset_second_factor(admin_page, acc)
    helpers.wait_mail(mailpit, acc.email, "second_factor_reset", seen=seen, timeout=MAIL_WAIT)
    page = new_context().new_page()
    _reconnect(page, acc)
    # п. 8: по записи на каждое событие; новые сверху: сброс, затем вход с нового устройства (из шага 2), затем пароль
    # (повторное подключение фактора записи о входе не даёт: `complete(limited=True)` устройство не запоминает, письма нет)
    rows = _list(page)
    resets = _with_text(rows, TEXT_SECOND_FACTOR)
    devices = _with_text(rows, TEXT_NEW_DEVICE)
    changes = _with_text(rows, TEXT_PW_CHANGED)
    assert len(resets) == 1 and len(changes) == 1 and len(devices) == 1, [r["text"] for r in rows]
    order = [r["id"] for r in rows]
    assert order.index(resets[0]["id"]) < order.index(devices[0]["id"]) < order.index(changes[0]["id"]), order
    # п. 8: все три непрочитанные; каждая открывается на странице безопасности и уменьшает число на 1
    for row in (resets[0], devices[0], changes[0]):
        assert row["unread"] == "1", row
    unread = _count_now(page)
    _open_and_check(page, resets[0])
    _open_and_check(page, _with_text(_list(page), TEXT_NEW_DEVICE)[0])
    _open_and_check(page, _with_text(_list(page), TEXT_PW_CHANGED)[0])
    assert _count_now(page) == unread - 3
