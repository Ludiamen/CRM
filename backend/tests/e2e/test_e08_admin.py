"""T-4147: сценарий 8 — администратор включает каналы и задаёт значения: страница «Настройки уведомлений», ключи в
окружении, выключение канала, значения по умолчанию, срок письма и хранения, право, журнал
(FR-322, FR-327, FR-334, FR-335, FR-336, FR-337, FR-338, FR-341, NFR-312).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-004.md):
- всё, что тест меняет на странице администратора (переключатели каналов, значения по умолчанию, срок письма и
  хранения), читается со страницы до изменения и возвращается в `finally` теми же значениями;
- ключей и токенов тест не читает и не печатает: «страница не показывает ключи» (NFR-312) и ветка «ключи не заданы»
  (дополнение 24 раздела 17) проверяются отдельным процессом `standtools` (`_probe`): он входит на страницу сессией
  браузера теста через `django.test.Client`, сверяет тело ответа со значениями настроек внутри себя и печатает
  одну строку JSON — только имена совпавших настроек, состояния `[data-keys]`, коды отказов и их тексты;
- отдельный процесс — единственная подготовка вне интерфейса: команда `docker compose … exec -T -e ИМЯ= standtools
  python manage.py shell -c <код>` (префикс — `helpers_sd._stand_prefix()`); `helpers.stand_shell` не используется;
- уведомления и письма проверяются так же, как в тесте сценария 1: уникальные имена, срок письма —
  `helpers_notify.tick(...)`, письма — поиском Mailpit по адресу получателя, сообщения бота — по своему `chat_id`.
"""
import contextlib
import json
import os
import secrets
import subprocess

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_notify, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_servicedesk import build_mail

SETTINGS_URL = "/settings/notifications/"
CHANNELS = ("webpush", "telegram", "max")  # порядок блоков страницы (§ 14.4)
CHANNEL_TITLE = {"webpush": "Web Push", "telegram": "Telegram", "max": "MAX"}  # § 15.5
ENV_NAME = {"webpush": "VAPID_PRIVATE_KEY", "telegram": "TELEGRAM_BOT_TOKEN", "max": "MAX_BOT_TOKEN"}  # доп. 24
NEW_IN_QUEUE = "servicedesk.new_in_queue"
SD_KINDS = ("servicedesk.new_in_queue", "servicedesk.assigned", "servicedesk.requester_replied",
            "servicedesk.reply_failed")  # виды сервис-деска: не mandatory, значит в таблице умолчаний (§ 3.2, § 14.4)
MANDATORY_KINDS = ("core.new_device", "core.password_changed", "core.second_factor_reset", "notify.channel_unbound")
EXTERNAL_SUBJECT = "Новая заявка в вашей очереди"  # внешний текст вида (§ 15.2): Telegram, Web Push, тема письма
MARK_SET_TEXT, MARK_UNSET_TEXT = "ключи заданы", "ключи не заданы"  # § 15.5
MARK_MISSING_TEXT = "ключи задаются в окружении установки"  # § 15.4, код `keys_missing`
DELAY_RANGE_TEXT, RETENTION_RANGE_TEXT = "от 5 до 120", "от 30 до 365"  # § 15.4, код `out_of_range`
SETTINGS_ACTION = "notify.settings_changed"  # § 9.2
ACTION_TITLE = "Настройки уведомлений изменены"  # § 9.2 (`ACTIONS`)
DELAY_LABEL, RETENTION_LABEL = "срок до письма, минут", "срок хранения уведомлений, дней"  # § 9.2 (`FIELDS`)


# --- Общие помощники файла ----------------------------------------------------------------------------

def _norm(text: str) -> str:
    return " ".join(text.split())


def _word() -> str:
    """Уникальное слово темы: буква и шесть шестнадцатеричных знаков (не из одних цифр, иначе поиск списка принял бы
    его за номер заявки)."""
    return f"t{secrets.token_hex(3)}"


def _tag() -> str:
    """Общее начало фамилий сотрудников теста: по нему «Добавить сотрудников» находит всех сразу."""
    return "Очередь" + secrets.token_hex(3)


def _chat_id() -> int:
    """Уникальный номер чата `fakebots` для теста: служба одна на круг, сообщения выбираются по своему чату."""
    return secrets.randbelow(900_000_000) + 100_000_000


# --- Страница администратора: чтение и сохранение (§ 13.3, § 14.4) ------------------------------------------

def _open(page):
    """Открывает `/settings/notifications/` и возвращает форму `notify-settings`."""
    page.goto(SETTINGS_URL)
    expect(page.locator("[data-notify-settings]")).to_be_visible()
    form = page.locator('form[data-form="notify-settings"]')
    expect(form).to_be_visible()
    return form


def _switches(page) -> dict:
    """Значения переключателей каналов страницы: `{канал: включён}`."""
    form = _open(page)
    return {c: form.locator(f'input[type=checkbox][name="{c}_enabled"]').is_checked() for c in CHANNELS}


def _limits(page) -> tuple:
    """Срок письма (минут) и срок хранения (дней) со страницы."""
    form = _open(page)
    return (int(form.locator('input[name="email_delay_minutes"]').input_value()),
            int(form.locator('input[name="retention_days"]').input_value()))


def _cells(page) -> dict:
    """Значения по умолчанию «вид × канал» со страницы: `{"<код вида>:<канал>": отмечена}`."""
    form = _open(page)
    boxes = form.locator('table[data-defaults-table] input[type=checkbox][name="cell"]')
    expect(boxes.first).to_be_visible()
    return {box.get_attribute("value"): box.is_checked() for box in boxes.all()}


def _errors(page) -> list:
    """Отказы страницы: `[(поле, код, текст)]` по `[data-error][data-code]` (§ 13)."""
    return [(e.get_attribute("data-error"), e.get_attribute("data-code"), _norm(e.inner_text()))
            for e in page.locator("[data-error][data-code]").all()]


def _fill_form(form, *, switches=None, limits=None, cells=None) -> None:
    for channel, state in (switches or {}).items():
        form.locator(f'input[type=checkbox][name="{channel}_enabled"]').set_checked(state)
    if limits is not None:
        form.locator('input[name="email_delay_minutes"]').fill(str(limits[0]))
        form.locator('input[name="retention_days"]').fill(str(limits[1]))
    for value, state in (cells or {}).items():
        form.locator(f'table[data-defaults-table] input[type=checkbox][name="cell"][value="{value}"]').set_checked(state)


def _submit(page, form) -> None:
    with page.expect_navigation():
        form.locator('button[type=submit][data-action="save-settings"]').click()
    page.wait_for_load_state()


def _save(page, *, switches=None, limits=None, cells=None) -> None:
    """Сохраняет страницу администратора: указанные переключатели, сроки `(минут, дней)` и ячейки умолчаний
    (остальное форма отправляет как есть). Успех — «Настройки уведомлений сохранены.» без отказов."""
    form = _open(page)
    _fill_form(form, switches=switches, limits=limits, cells=cells)
    _submit(page, form)
    assert not _errors(page), f"настройки не сохранены: {_errors(page)}"
    expect(page.locator("[role=status]").filter(has_text=helpers_notify.SETTINGS_SAVED).first).to_be_visible()


def _try_save(page, *, limits) -> list:
    """Отправка сроков, которую портал вправе отклонить: возвращает отказы страницы (200 с `[data-error]`)."""
    form = _open(page)
    _fill_form(form, limits=limits)
    _submit(page, form)
    return _errors(page)


# --- Отдельный процесс стенда: сессия браузера теста, значения настроек внутри процесса (доп. 24) -----------

_PROBE = r'''
def main():
    import json
    import re
    from urllib.parse import urlsplit
    from django.conf import settings
    from django.test import Client

    spec = json.loads(__SPEC__)
    client = Client()
    for name, value in spec["cookies"].items():
        client.cookies[name] = value
    kw = {"secure": True, "HTTP_HOST": urlsplit(settings.PORTAL_URL).netloc, "HTTP_USER_AGENT": spec["ua"]}
    page_path = "/settings/notifications/"

    def body_of(response):
        return response.content.decode("utf-8", "replace")

    def plain(text):
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", text)).strip()

    def leaks(body):
        names = ("TELEGRAM_BOT_TOKEN", "MAX_BOT_TOKEN", "VAPID_PRIVATE_KEY", "VAPID_PUBLIC_KEY")
        return [n for n in names if getattr(settings, n, "") and str(getattr(settings, n)) in body]

    def blocks(body):
        marks = [(m.start(), m.group(1)) for m in re.finditer(r'data-channel-block="(webpush|telegram|max)"', body)]
        out = {}
        for i, (pos, name) in enumerate(marks):
            seg = body[pos:marks[i + 1][0] if i + 1 < len(marks) else len(body)]
            found = re.search(r'<[^>]*data-keys="(set|unset)"[^>]*>', seg)
            out[name] = {"keys": found.group(1) if found else "",
                         "text": plain(seg[found.end():found.end() + 120]) if found else ""}
        return out

    def errors(body):
        out = []
        for m in re.finditer(r'<[^>]*data-error="([^"]+)"[^>]*>', body):
            code = re.search(r'data-code="([^"]+)"', m.group(0))
            if code:
                out.append({"field": m.group(1), "code": code.group(1), "text": plain(body[m.end():m.end() + 300])})
        return out

    def switch_states(body):
        out = {}
        for name in ("webpush", "telegram", "max"):
            tag = re.search(r'<input[^>]*name="%s_enabled"[^>]*>' % name, body)
            out[name] = bool(tag and re.search(r"\bchecked\b", tag.group(0)))
        return out

    result = {}
    if spec["action"] == "get":
        response = client.get(spec["path"], **kw)
        body = body_of(response)
        result = {"status": response.status_code, "leaks": leaks(body), "blocks": blocks(body),
                  "errors": errors(body)}
        if spec.get("leaks_only"):
            result = {"status": response.status_code, "leaks": leaks(body)}
    else:
        channel = spec["channel"]
        first = body_of(client.get(page_path, **kw))
        data = {"channels": "1", channel + "_enabled": "1"}
        for name, state in switch_states(first).items():
            if state:
                data[name + "_enabled"] = "1"
        response = client.post(page_path, data, **kw)
        body = body_of(response)
        after = switch_states(body_of(client.get(page_path, **kw)))
        result = {"status": response.status_code, "leaks": leaks(first) + leaks(body), "blocks": blocks(first),
                  "errors": errors(body), "after_enabled": after[channel]}
    print("PROBE " + json.dumps(result))


main()
'''


def _probe(page, spec: dict, *, unset: str | None = None) -> dict:
    """Запускает `_PROBE` в службе `standtools` (доп. 24): сессия — куки контекста страницы, `unset` — имя переменной
    окружения, которая в этом процессе пуста (`-e ИМЯ=`). Значения кук и настроек не печатаются ни процессом, ни
    сообщением об ошибке. Возвращает словарь, напечатанный процессом."""
    if os.environ.get("E2E_STAND_CMD"):
        raise AssertionError("нужен стандартный префикс standtools (E2E_STAND_CMD не задавать)")
    cookies = {c["name"]: c["value"] for c in page.context.cookies()}
    agent = page.evaluate("() => navigator.userAgent")  # устройство сессии узнаётся по признакам среза 001, в том числе по User-Agent
    code = _PROBE.replace("__SPEC__", repr(json.dumps({**spec, "cookies": cookies, "ua": agent})))
    prefix = helpers_sd._stand_prefix()
    at = prefix.index("standtools")
    cmd = prefix[:at] + (["-e", f"{unset}="] if unset else []) + prefix[at:] + ["shell", "-c", code]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        raise AssertionError("процесс standtools не уложился в 120 с") from None
    if done.returncode != 0:
        tail = done.stderr.strip()[-300:]
        for value in cookies.values():
            tail = tail.replace(value, "***")
        raise AssertionError(f"процесс standtools завершился с кодом {done.returncode}: {tail}")
    lines = [line for line in done.stdout.splitlines() if line.startswith("PROBE ")]
    if not lines:
        raise AssertionError("процесс standtools не напечатал строку PROBE")
    return json.loads(lines[-1][len("PROBE "):])


# --- Заявки, очереди и «Мои уведомления» (как в приёмке сценария 1) -----------------------------------------

def _queue(page, prefix: str = "Поддержка") -> tuple:
    """Новый узел `org`, отмеченный очередью: `(номер, название)`."""
    name = helpers_org.unique_name(prefix)
    unit_id = helpers_org.create_unit(page, name)
    helpers_sd.mark_queue(page, unit_id)
    return unit_id, name


def _members(page, queue_id, accounts, tag: str) -> None:
    """Прямые участники узла-очереди (у отдела — режим «параллельно»)."""
    page.goto(f"/structure/{queue_id}/")
    mode = "concurrent" if page.locator("#unit-card select[name=mode]").count() else None
    note = helpers_org.add_members(page, queue_id, [a.id for a in accounts], q=tag, mode=mode)
    assert "уже участник" not in note, note
    helpers_org.open_structure(page, queue_id)
    for account in accounts:
        expect(helpers_org.member_row(page, account.id)).to_have_count(1)


@contextlib.contextmanager
def _default_queue(page, old_id, queue_id):
    """Очередь по умолчанию на время теста — своя (письмо заявителя попадает в неё); прежняя возвращается в `finally`."""
    helpers_sd.set_default_queue(page, queue_id)
    try:
        yield
    finally:
        helpers_sd.set_default_queue(page, old_id)


def _team(page, employee, size: int = 1) -> tuple:
    """Сотрудники-участники своей очереди: `(список, номер очереди)`."""
    tag = _tag()
    people = [employee(full_name=f"{tag}{i} Петр Петрович") for i in range(1, size + 1)]
    queue_id, _name = _queue(page)
    _members(page, queue_id, people, tag)
    return people, queue_id


def _own_cell(page, kind: str, channel: str):
    return page.locator(f'form[data-form="notify-prefs"] tr[data-notify-kind="{kind}"] td[data-channel="{channel}"] '
                        f'input[type=checkbox][name="cell"][value="{kind}:{channel}"]')


def _save_own(page, changes: dict, *, quiet_none: bool = False) -> None:
    """«Мои уведомления» сотрудника: ячейки `{(вид, канал): отмечена}` и, если нужно, режим «Без тихих часов» (в тихие
    часы внешние сообщения ушли бы в сводку); ждёт сообщение страницы и проверяет сохранённое (§ 13.2, § 14.3)."""
    page.goto("/me/notifications/")
    form = page.locator('form[data-form="notify-prefs"]')
    expect(form).to_be_visible()
    for (kind, channel), state in changes.items():
        cell = _own_cell(page, kind, channel)
        expect(cell).to_have_count(1)
        cell.set_checked(state)
    if quiet_none:
        form.locator('fieldset[data-quiet] input[type=radio][name="quiet_mode"][value="none"]').check()
    with page.expect_navigation():
        form.locator('button[type=submit][data-action="save-prefs"]').click()
    page.wait_for_load_state()
    assert not helpers.alert_text(page), f"настройки не сохранены: {helpers.alert_text(page)}"
    expect(page.locator("[role=status]").first).to_be_visible()
    for (kind, channel), state in changes.items():
        expect(_own_cell(page, kind, channel)).to_be_checked(checked=state)
    if quiet_none:
        expect(page.locator('fieldset[data-quiet] input[name="quiet_mode"][value="none"]')).to_be_checked()


def _new_mail(title: str = "Не работает принтер") -> tuple:
    """Письмо заявителя в ящик заявок и сразу разбор: заявка создана в очереди по умолчанию, без ответственного.
    Возвращает `(слово, тема)`."""
    word = _word()
    subject = f"{title} {word}"
    helpers_sd.deliver(build_mail(from_addr=helpers_sd.requester_email(), to=[MAILBOX], subject=subject,
                                  text=f"Нужна помощь {word}", message_id=f"<{secrets.token_hex(8)}@client.test>"))
    return word, subject


def _mail_and_wait(tab, title: str = "Не работает принтер") -> str:
    """Письмо заявителя создаёт заявку в очереди по умолчанию; ждёт, пока число колокольчика вкладки `tab` вырастет на
    1 (уведомление создано). Возвращает слово темы."""
    helpers_notify.wait_ws_open(tab)
    base = helpers_notify.bell_count(tab)
    word, _subject = _new_mail(title)
    helpers_notify.wait_bell_count(tab, base + 1, timeout_ms=15_000)
    return word


def _notification_rows(page, word: str):
    """Открывает `/notifications/` и возвращает строки списка со словом темы (список только читает)."""
    page.goto("/notifications/")
    expect(page.locator("[data-notify-list]")).to_be_visible()
    return page.locator("ul[data-notifications] li[data-notification]").filter(has_text=word)


# --- Тесты --------------------------------------------------------------------------------------------------

def test_e08_notification_settings_page_shows_channels_with_switch_keys_set_mark_and_defaults_but_no_keys_or_tokens(
        admin_page):
    """Сценарий 8, п. 1: у сотрудника есть право «Настройка уведомлений» — на странице «Настройки уведомлений» три
    канала (Web Push, Telegram, MAX) с переключателем и отметкой «ключи заданы», таблица значений по умолчанию, сроки;
    самих ключей и токенов страница не показывает: отдельный процесс стенда сверяет тело ответа со значениями
    настроек и находит совпадений (FR-334, FR-335, FR-336, NFR-312)."""
    page = admin_page
    page.goto(SETTINGS_URL)
    # п. 1: страница и пункт меню «Уведомления» (право есть)
    expect(page.locator("[data-notify-settings]")).to_be_visible()
    expect(page.locator("h1").first).to_contain_text("Настройки уведомлений")
    assert "Настройки уведомлений" in page.title()
    menu = page.locator('#main-menu a.menu-item[href="/settings/notifications/"]')
    expect(menu).to_have_count(1)
    expect(menu).to_contain_text("Уведомления")
    # п. 1: три канала по порядку, у каждого переключатель и отметка ключей (на стенде ключи всех трёх каналов заданы)
    names = [b.get_attribute("data-channel-block") for b in page.locator("section[data-channel-block]").all()]
    assert names == list(CHANNELS), names
    for channel in CHANNELS:
        block = page.locator(f'section[data-channel-block="{channel}"]')
        expect(block).to_contain_text(CHANNEL_TITLE[channel])
        switch = block.locator(f'input[type=checkbox][name="{channel}_enabled"]')
        expect(switch).to_have_count(1)
        expect(switch).to_be_enabled()
        mark = block.locator("[data-keys]")
        expect(mark).to_have_count(1)
        expect(mark).to_have_attribute("data-keys", "set")
        expect(mark).to_contain_text(MARK_SET_TEXT)
    # п. 1: значения по умолчанию — виды сервис-деска по четырём внешним каналам, видов `mandatory` и столбца
    # «На портале» нет (§ 14.4)
    table = page.locator("table[data-defaults-table]")
    expect(table).to_have_count(1)
    expect(table.locator("[data-channel=portal]")).to_have_count(0)
    kinds = [r.get_attribute("data-notify-kind") for r in table.locator("tr[data-notify-kind]").all()]
    for kind in SD_KINDS:
        assert kind in kinds, f"в таблице умолчаний нет вида {kind}"
    for kind in MANDATORY_KINDS:
        assert kind not in kinds, f"в таблице умолчаний вид {kind} (обязательные виды в ней не показываются)"
    for kind in kinds:
        row = table.locator(f'tr[data-notify-kind="{kind}"]')
        for channel in ("email", "push", "telegram", "max"):
            cell = row.locator(f'td[data-channel="{channel}"]')
            expect(cell).to_have_count(1)
            expect(cell.locator(f'input[type=checkbox][name="cell"][value="{kind}:{channel}"]')).to_have_count(1)
    # п. 1: по умолчанию «Новая заявка…» отмечена по почте (default_channels, § 3.2)
    expect(table.locator('input[name="cell"][value="servicedesk.new_in_queue:email"]')).to_be_checked()
    # п. 1: сроки — числа в допустимых пределах; одна кнопка сохранения
    delay, days = _limits(page)
    assert 5 <= delay <= 120 and 30 <= days <= 365, (delay, days)
    expect(page.locator('button[type=submit][data-action="save-settings"]')).to_have_count(1)
    # п. 1 (NFR-312): ни токенов ботов, ни ключей VAPID в теле страницы (сверка идёт внутри процесса стенда)
    result = _probe(page, {"action": "get", "path": SETTINGS_URL, "leaks_only": True})
    assert result["status"] == 200, result["status"]
    assert result["leaks"] == [], f"в теле страницы значения настроек: {result['leaks']}"


def test_e08_enabling_channel_without_environment_keys_refused_with_explanation(admin_page):
    """Сценарий 8, п. 2: для канала в окружении ключи не заданы — администратор пытается его включить, портал не
    включает и объясняет, что ключи задаются в окружении установки. На стенде ключи заданы, поэтому ветка идёт по
    дополнению 24: отдельный процесс `standtools` без ключа канала (по очереди VAPID, токен Telegram, токен MAX)
    открывает страницу и отправляет форму с сессией браузера; в браузере проверяется вторая половина — переключатель
    на странице стенда не изменился (FR-336, FR-337, NFR-312)."""
    page = admin_page
    before = _switches(page)
    try:
        for channel in CHANNELS:
            # дано: канал выключен (включать будет процесс без ключа)
            _save(page, switches={channel: False})
            result = _probe(page, {"action": "enable", "path": SETTINGS_URL, "channel": channel},
                            unset=ENV_NAME[channel])
            # п. 2: отметка «ключи не заданы» у этого канала, у остальных — «ключи заданы»
            assert result["blocks"][channel]["keys"] == "unset", result["blocks"]
            assert MARK_UNSET_TEXT in result["blocks"][channel]["text"], result["blocks"][channel]
            for other in CHANNELS:
                if other != channel:
                    assert result["blocks"][other]["keys"] == "set", result["blocks"]
            # п. 2: страница не включила канал и ответила отказом `keys_missing` у его переключателя с пояснением
            assert result["status"] == 200, result["status"]
            refusals = [e for e in result["errors"] if e["field"] == f"{channel}_enabled"]
            assert refusals, f"нет отказа у переключателя {channel}_enabled: {result['errors']}"
            assert refusals[0]["code"] == "keys_missing", refusals
            assert MARK_MISSING_TEXT in refusals[0]["text"], refusals[0]["text"]
            assert result["after_enabled"] is False, "канал без ключей включён"
            assert result["leaks"] == [], f"в ответе значения настроек: {result['leaks']}"
            # п. 2: на странице стенда ничего не изменилось
            current = _switches(page)
            assert current[channel] is False, f"переключатель {channel} изменился после отказа"
            expect(page.locator(f'section[data-channel-block="{channel}"] [data-keys="set"]')).to_have_count(1)
    finally:
        _save(page, switches=before)



@helpers_notify.webpush_only
def test_e08_disabled_channel_stops_messages_keeps_bindings_and_subscriptions_and_they_work_after_reenabling(
        admin_page, employee, webpush_context):
    """Сценарий 8, п. 3: администратор выключил Telegram и Web Push и сохранил — сообщения не уходят (новая заявка в
    очереди сотрудника есть на портале, но ни в чат Telegram, ни push на закрытую вкладку устройства не пришли),
    страница сотрудника показывает «Канал отключён администратором»; привязка и подписка не удалены: после повторного
    включения следующая заявка приходит и в тот же чат, и push-уведомлением, а на странице «Привязан» и то же
    устройство в списке. Telegram — учебная служба `fakebots`, подписка Web Push — постоянный профиль
    `webpush_context()` (метка webpush: круги chromium и edge) (FR-336)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (member,), queue_id = _team(page, employee)
    bots = helpers_notify.fakebots()  # без сброса: сообщения своего теста — по своему chat_id
    chat = _chat_id()
    before = _switches(page)
    try:
        with _default_queue(page, old_id, queue_id):
            # дано: каналы включены, Telegram привязан кодом, устройство подписано в постоянном профиле
            _save(page, switches={"telegram": True, "webpush": True})
            helpers_notify.bind_channel(member.page, bots, "telegram", chat)
            answers = len(helpers_notify.sent_to(bots, "telegram", chat))  # ответ бота «Telegram привязан …» уже есть
            _save_own(member.page, {(NEW_IN_QUEUE, "email"): False}, quiet_none=True)  # письма не мешают, тихих часов нет
            for channel in ("telegram", "push"):
                expect(_own_cell(member.page, NEW_IN_QUEUE, channel)).to_be_checked()
            context = webpush_context()
            helpers_notify.adopt_session(context, member)
            helpers_notify.grant_notifications(context)
            tab = context.new_page()
            device = helpers_notify.enable_push_on_device(tab)
            # все вкладки сотрудника закрыты: без открытой вкладки Web Push не пропускается (FR-331)
            tab.close()
            member.page.close()
            # когда: администратор выключает оба канала и сохраняет
            _save(page, switches={"telegram": False, "webpush": False})
            word_a, _subject_a = _new_mail("Не работает монитор")
            # п. 3: сообщения не уходят — ни в чат, ни push на устройство
            assert helpers_notify.no_service_worker_notifications(context, observe=10), "push при выключенном Web Push"
            assert len(helpers_notify.sent_to(bots, "telegram", chat)) == answers, "сообщение в чат при выключенном Telegram"
            # положительный контроль: заявка создала уведомление на портале; у сотрудника «Канал отключён администратором»
            view = context.new_page()
            expect(_notification_rows(view, word_a)).to_have_count(1)
            view.goto("/me/notifications/")
            binding = view.locator("#notify-binding-telegram")
            expect(binding).to_have_attribute("data-state", "disabled")
            expect(binding.locator("[data-disabled-text]")).to_contain_text("Канал отключён администратором")
            expect(view.locator('[data-section="push"]')).to_have_attribute("data-web-push", "off")
            expect(view.locator("[data-push-disabled-text]")).to_contain_text(
                "Push при закрытой вкладке отключён администратором")
            view.close()
            # когда: администратор включает оба канала снова
            _save(page, switches={"telegram": True, "webpush": True})
            word_b, _subject_b = _new_mail("Не работает клавиатура")
            # п. 3: привязка действует — сообщение о новой заявке пришло в тот же чат (только внешний текст, § 15.2)
            found = helpers_notify.wait_sent(bots, "telegram", chat_id=chat, text_has=EXTERNAL_SUBJECT, timeout=90)
            assert found[-1]["text"] == EXTERNAL_SUBJECT, found[-1]["text"]
            # у выключенного канала доставка по заявке A окончательно `skipped` (CONTRACT-004, send_delivery):
            # после включения приходит ровно одно сообщение, о заявке B
            assert len(helpers_notify.sent_to(bots, "telegram", chat)) == answers + 1, \
                "сообщение о заявке A ушло после включения"
            # п. 3: подписка действует — push на закрытую вкладку устройства (настоящий push-сервис, норма — минута, NFR-302; ждём с запасом)
            shown = helpers_notify.wait_service_worker_notifications(context, count=1, timeout=90)
            assert any(n["title"] == EXTERNAL_SUBJECT for n in shown), [n["title"] for n in shown]
            # п. 3: на странице «Привязан» и то же устройство в списке
            view = context.new_page()
            expect(_notification_rows(view, word_b)).to_have_count(1)
            view.goto("/me/notifications/")
            expect(view.locator("#notify-binding-telegram")).to_have_attribute("data-state", "bound")
            expect(view.locator('[data-section="push"]')).to_have_attribute("data-web-push", "on")
            expect(view.locator(f'ul[data-devices] li[data-device="{device}"]')).to_have_count(1)
            view.close()
    finally:
        _save(page, switches=before)


def test_e08_changed_defaults_apply_to_employees_who_did_not_change_table_and_not_to_those_who_did(
        admin_page, employee):
    """Сценарий 8, п. 4: администратор изменил значение «вид × канал» по умолчанию («Новая заявка в моей очереди» —
    «Почта») и сохранил — у сотрудника, который свою таблицу не менял, в «Моих уведомлениях» новое значение; у того,
    кто сохранил свою таблицу раньше, остаётся его собственное (FR-322)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    (untouched, changed), _queue_id = _team(page, employee, 2)
    original = _cells(page)
    value = f"{NEW_IN_QUEUE}:email"
    assert value in original, "в таблице умолчаний нет ячейки «Новая заявка в моей очереди» — «Почта»"
    was = original[value]
    try:
        # дано: второй сотрудник сам сохранил свою таблицу (снимок со значением «до»)
        _save_own(changed.page, {("servicedesk.assigned", "email"): False})
        expect(_own_cell(changed.page, NEW_IN_QUEUE, "email")).to_be_checked(checked=was)
        # контроль: первый видит значение по умолчанию «до»
        untouched.page.goto("/me/notifications/")
        expect(_own_cell(untouched.page, NEW_IN_QUEUE, "email")).to_be_checked(checked=was)
        # когда: администратор меняет значение по умолчанию и сохраняет
        _save(page, cells={value: not was})
        expect(page.locator(f'table[data-defaults-table] input[name="cell"][value="{value}"]')).to_be_checked(
            checked=not was)
        # п. 4: у сотрудника, не менявшего таблицу, — новое значение
        untouched.page.goto("/me/notifications/")
        expect(_own_cell(untouched.page, NEW_IN_QUEUE, "email")).to_be_checked(checked=not was)
        # п. 4: у менявшего остаётся собственное
        changed.page.goto("/me/notifications/")
        expect(_own_cell(changed.page, NEW_IN_QUEUE, "email")).to_be_checked(checked=was)
        expect(_own_cell(changed.page, "servicedesk.assigned", "email")).not_to_be_checked()
    finally:
        _save(page, cells=original)


def test_e08_mail_term_30_minutes_delays_new_emails_and_retention_180_days_nightly_job_deletes_older(
        admin_page, employee, mailpit, new_context):
    """Сценарий 8, п. 5: срок письма 30 минут и срок хранения 180 дней — новое уведомление письмом уходит через 30
    минут (сдвиг на 29 минут письма ещё нет, ещё на 1 минуту — письмо есть), ночное удаление убирает уведомления
    старше 180 дней, а моложе срока остаются (сдвиг ночного удаления идёт на 100 и затем ещё на 81 сутки: 100 суток
    при прежнем сроке 90 уже удалены бы, при 180 остаются) (FR-327, FR-338)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (member,), queue_id = _team(page, employee)
    _save_own(member.page, {(NEW_IN_QUEUE, "email"): True}, quiet_none=True)  # письмо уходит в любое время суток
    was = _limits(page)
    try:
        # дано: администратор задал срок письма 30 минут и срок хранения 180 дней
        _save(page, limits=(30, 180))
        assert _limits(page) == (30, 180)
        with _default_queue(page, old_id, queue_id):
            tab = helpers_notify.open_watcher(new_context, member)
            # когда: новая заявка в очереди сотрудника
            word_1 = _mail_and_wait(tab)
            # п. 5: срок 30 минут — через 28 письма нет, ещё через 2 минуты (всего 30) есть
            assert helpers_notify.tick(shift=28)["shifted"] >= 1
            assert helpers_notify.no_item_mail(mailpit, member.email, wait=3), "письмо раньше срока 30 минут"
            assert helpers_notify.tick(shift=2)["shifted"] >= 1
            letter = helpers_notify.wait_item_mail(mailpit, member.email)
            assert letter["Subject"] == EXTERNAL_SUBJECT, letter["Subject"]
            # п. 5: хранение 180 дней — уведомлению 100 суток (при прежнем сроке 90 его бы удалили), оно остаётся
            helpers_notify.tick(age_days=100, retention=True)
            expect(_notification_rows(tab, word_1)).to_have_count(1)
            # новое уведомление моложе срока; затем первому исполняется 181 сутки, второму — 81
            tab.goto("/")
            word_2 = _mail_and_wait(tab, "Не работает сканер")
            result = helpers_notify.tick(age_days=81, retention=True)
            assert result["retention_notifications"] >= 1, result
            # п. 5: старше 180 дней — удалено; моложе срока — осталось
            expect(_notification_rows(tab, word_1)).to_have_count(0)
            expect(_notification_rows(tab, word_2)).to_have_count(1)
    finally:
        _save(page, limits=was)


def test_e08_mail_term_3_minutes_or_retention_10_days_refused_with_allowed_ranges(admin_page):
    """Сценарий 8, п. 6: срок письма 3 минуты (и 121) или хранения 10 дней (и 366) — портал отказывает и называет
    пределы: срок письма от 5 до 120 минут, хранения от 30 до 365 дней; ничего не сохранено, в том числе другое
    поле той же отправки (FR-335)."""
    page = admin_page
    delay, days = _limits(page)
    other_delay = delay + 1 if delay < 120 else delay - 1  # допустимое значение, отличное от действующего
    other_days = days + 1 if days < 365 else days - 1
    cases = [
        ((3, other_days), "email_delay_minutes", DELAY_RANGE_TEXT),
        ((121, other_days), "email_delay_minutes", DELAY_RANGE_TEXT),
        ((other_delay, 10), "retention_days", RETENTION_RANGE_TEXT),
        ((other_delay, 366), "retention_days", RETENTION_RANGE_TEXT),
    ]
    try:
        for sent, field, text in cases:
            refusals = [e for e in _try_save(page, limits=sent) if e[0] == field]
            # п. 6: отказ у поля со ссылкой на пределы
            assert refusals, f"{sent}: нет отказа у поля {field}"
            assert refusals[0][1] == "out_of_range", refusals
            assert text in refusals[0][2], refusals[0][2]
            assert not page.locator("[role=status]").filter(has_text=helpers_notify.SETTINGS_SAVED).count()
            # п. 6: ничего не сохранено — ни неверное значение, ни допустимое значение другого поля
            assert _limits(page) == (delay, days), f"{sent}: после отказа сохранено {_limits(page)}"
    finally:
        _save(page, limits=(delay, days))


def test_e08_user_without_notification_settings_right_gets_refusal_on_direct_link(admin_page, employee):
    """Сценарий 8, п. 7: у сотрудника нет права «Настройка уведомлений» — по прямой ссылке `/settings/notifications/`
    отказ 403 (и на просмотр, и на отправку формы), в меню пункта «Уведомления» нет, настройки не изменились; у
    администратора страница открыта и пункт меню есть (FR-334)."""
    page = admin_page
    plain = employee(full_name="Без права Настройки")
    delay, days = _limits(page)
    probe = (delay + 1 if delay < 120 else delay - 1, days + 1 if days < 365 else days - 1)
    # п. 7: просмотр по прямой ссылке — отказ, формы настроек на странице нет
    response = plain.page.goto(SETTINGS_URL)
    assert response.status == 403, response.status
    expect(plain.page.locator('form[data-form="notify-settings"]')).to_have_count(0)
    assert helpers_org.direct_get(plain.page, SETTINGS_URL).status == 403
    # п. 7: отправка формы — отказ раньше любой работы, настройки не изменились
    sent = helpers_org.direct_post(plain.page, SETTINGS_URL, {
        "limits": "1", "email_delay_minutes": str(probe[0]), "retention_days": str(probe[1])})
    assert sent.status == 403, sent.status
    assert _limits(page) == (delay, days)
    # п. 7: пункта меню у сотрудника нет, у администратора есть
    plain.page.goto("/")
    expect(plain.page.locator("#main-menu")).to_be_visible()
    expect(plain.page.locator('#main-menu a.menu-item[href="/settings/notifications/"]')).to_have_count(0)
    page.goto("/")
    expect(page.locator('#main-menu a.menu-item[href="/settings/notifications/"]')).to_have_count(1)


def test_e08_journal_shows_admin_changes_as_was_became_without_key_values(admin_page, stand_admin):
    """Сценарий 8, п. 8: администратор сохранил срок письма и срок хранения — в журнале `/audit/` запись «Настройки
    уведомлений изменены» с его именем и парами «было / стало» только по изменённым полям; значений ключей и токенов
    в журнале нет (сверка идёт внутри процесса стенда); сохранение без изменений новой записи не даёт (FR-341)."""
    page = admin_page
    old_delay, old_days = _limits(page)
    new_delay = 40 + secrets.randbelow(60)
    new_delay = new_delay + 1 if new_delay == old_delay else new_delay
    new_days = 200 + secrets.randbelow(100)
    new_days = new_days + 1 if new_days == old_days else new_days

    def events() -> list:
        """Строки журнала `notify.settings_changed` (первая страница, новые сверху): id, текст ячеек."""
        page.goto(f"/audit/?action={SETTINGS_ACTION}")
        rows = page.locator(f'tr[data-event-id][data-action="{SETTINGS_ACTION}"]').all()
        out = []
        for row in rows:
            cells = [_norm(c).lower() for c in row.locator("td").all_inner_texts()]
            out.append({"id": row.get_attribute("data-event-id"), "who": cells[1], "event": cells[2],
                        "before": cells[4], "after": cells[5], "text": " ".join(cells)})
        return out

    try:
        # когда: администратор сохранил изменённые сроки
        _save(page, limits=(new_delay, new_days))
        found = [e for e in events() if f"{DELAY_LABEL}: {new_delay}" in e["after"]]
        # п. 8: запись есть, одна, от имени администратора; название события русское
        assert len(found) == 1, f"записей журнала с новым сроком письма: {len(found)}"
        event = found[0]
        assert ACTION_TITLE.lower() in event["event"], event["event"]
        assert stand_admin.email.lower() in event["who"], "в записи нет администратора"
        # п. 8: «было / стало» по обоим изменённым полям, прежние значения слева, новые справа
        assert f"{DELAY_LABEL}: {old_delay}" in event["before"], event["before"]
        assert f"{RETENTION_LABEL}: {old_days}" in event["before"], event["before"]
        assert f"{RETENTION_LABEL}: {new_days}" in event["after"], event["after"]
        # п. 8: только изменившиеся поля — переключателей каналов в записи нет
        for label in ("web push включён", "telegram включён", "max включён"):
            assert label not in event["before"] and label not in event["after"], label
        # п. 8: значений ключей и токенов в журнале нет
        result = _probe(page, {"action": "get", "path": f"/audit/?action={SETTINGS_ACTION}", "leaks_only": True})
        assert result["status"] == 200 and result["leaks"] == [], result["leaks"]
        # сохранение без изменений записи не добавляет
        known = [e["id"] for e in events()]
        _save(page)
        assert [e["id"] for e in events()] == known, "сохранение без изменений добавило запись журнала"
    finally:
        _save(page, limits=(old_delay, old_days))
