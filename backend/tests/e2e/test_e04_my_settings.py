"""T-4143: сценарий 4 — сотрудник настраивает свои уведомления на странице «Мои уведомления»: таблица «вид × канал»,
недоступные столбцы, сводные строки безопасности, значения администратора по умолчанию, тихие часы («Свои часы»,
«Без тихих часов», ночной график), отказы, ширина 360 px, журнал «было / стало»
(FR-303, FR-305, FR-321, FR-322, FR-323, FR-324, FR-325, FR-327, FR-329, FR-330, FR-341, FR-344, NFR-308).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-004.md):
- таблица «вид × канал» показывает только виды, доступные сотруднику (§ 4.3, `available`; доп. 18 (а)): у сотрудника
  без очереди строк видов нет, остаются две сводные строки. Поэтому сотрудник, у которого проверяется таблица или
  письма, делается прямым участником своей очереди (`ensure_ready`, `_queue`, `_members`); очередь по умолчанию на
  время теста меняется на свою и возвращается в `finally` (письмо заявителя попадает в неё);
- тихие часы: у каждого, чьё письмо проверяется, режим задан явно («Без тихих часов» или «Свои часы» вокруг текущего
  московского времени, `datetime.now(ZoneInfo("Europe/Moscow"))`): стенд не подменяет часы, а «рабочее время по
  календарю» зависит от времени суток; окно «вне текущего времени» — со сдвигом на 3 часа вперёд (час длиной), «внутри» —
  от двух часов назад до двух часов вперёд; дни — все семь (день недели из заботы выпадает);
- срок письма — `helpers_notify.tick(shift=PAST_ANY_TERM)`: 121 минута больше верхней границы срока письма (120 минут,
  § 6.5), письмо просрочено при любом сроке на стенде; доставки вне рабочего времени (`held`) сдвиг не трогает (§ 8.2);
  сдвиг идёт по всему стенду, поэтому письма ищутся поиском Mailpit по адресу получателя и шаблону;
- каналы Telegram, MAX и Web Push, которые тест включает на странице администратора, возвращаются в `finally`
  (`helpers_notify.channels_on`); значения по умолчанию администратора (тест 5) тоже возвращаются в `finally`.
"""
import re
import secrets
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_notify, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_feed import FEED_KINDS, FEED_MODULE
from tests.support_servicedesk import build_mail

NEW_IN_QUEUE = "servicedesk.new_in_queue"
ASSIGNED = "servicedesk.assigned"
REPLIED = "servicedesk.requester_replied"
REPLY_FAILED = "servicedesk.reply_failed"
KINDS = (  # § 3.2: код, название, порядок каталога; модуль у всех четырёх — «Сервис-деск»
    (NEW_IN_QUEUE, "Новая заявка в моей очереди"),
    (ASSIGNED, "Мне назначили заявку"),
    (REPLIED, "Заявитель ответил"),
    (REPLY_FAILED, "Ответ заявителю не ушёл"),
)
MODULE = "Сервис-деск"
RUBRIC = "knowledge.rubric_subscription"
# срез 005: сотрудник из приёмки заведён с ролью «Сотрудник ИТ» (`knowledge.edit`, CONTRACT-005 3.6), поэтому в таблице
# у участника очереди ещё три строки модуля «База знаний» (7.2: два вида — по `knowledge.edit`/`manage` или автору, «по подписке» — всем)
KB_KINDS = (
    ("knowledge.comment_on_my_article", "Новый комментарий к моей статье"),
    ("knowledge.my_article_changed", "Мою статью изменили"),
    (RUBRIC, "Статья в рубрике по подписке"),
)
KB_MODULE = "База знаний"
# срез 006: вид «Срок в записи списка» доступен всем (CONTRACT-006, раздел 7.3) — строка у каждого сотрудника, после
# видов базы знаний
LISTS_KINDS = (("lists.deadline", "Срок в записи списка"),)
LISTS_MODULE = "Списки"
# срез 007: восемь видов «Ленты» доступны всем (CONTRACT-007, раздел 15.3) — строки у каждого сотрудника, после видов списков
FEED_KINDS_E2E = tuple((row[0], row[1]) for row in FEED_KINDS)
ROWS = KINDS + KB_KINDS + LISTS_KINDS + FEED_KINDS_E2E  # строки таблицы участника очереди в порядке каталога
COLUMNS = ("На портале", "Почта", "Push в браузере", "Telegram", "MAX")  # § 15.5
CHANNEL_ORDER = ["portal", "email", "push", "telegram", "max"]  # § 14.3
SAVED = "Настройки уведомлений сохранены."  # § 15.4
EXTERNAL_TEXT = "Новая заявка в вашей очереди"  # внешний текст вида (§ 3.2, FR-317)
PAST_ANY_TERM = 121  # минут: больше верхней границы срока письма (120 минут, § 6.5)
MOSCOW = ZoneInfo("Europe/Moscow")
ALL_DAYS = range(7)
CYRILLIC = re.compile(r"[А-Яа-яЁё]")
LONG_WAIT_MS = 15_000


# --- Общие помощники файла ---------------------------------------------------------------------------------

def _word() -> str:
    """Уникальное слово темы: буква и шесть шестнадцатеричных знаков (не из одних цифр, иначе поиск списка принял бы
    его за номер заявки)."""
    return f"t{secrets.token_hex(3)}"


def _tag() -> str:
    """Общее начало фамилий сотрудников теста: по нему «Добавить сотрудников» находит всех сразу."""
    return "Свои" + secrets.token_hex(3)


def _chat_id() -> int:
    """Уникальный номер чата `fakebots` для теста: служба одна на круг, сообщения выбираются по своему чату."""
    return secrets.randbelow(900_000_000) + 100_000_000


def _staff(employee, tag: str, index: int):
    return employee(full_name=f"{tag}{index} Петр Петрович")


def _queue(page, prefix: str = "Поддержка") -> tuple:
    """Новый узел `org`, отмеченный очередью: `(номер, название)`."""
    name = helpers_org.unique_name(prefix)
    unit_id = helpers_org.create_unit(page, name)
    helpers_sd.mark_queue(page, unit_id)
    return unit_id, name


def _members(page, queue_id, accounts, tag: str) -> None:
    """Прямые участники узла-очереди (у отдела — режим «параллельно»: человек может состоять в нескольких узлах)."""
    page.goto(f"/structure/{queue_id}/")
    mode = "concurrent" if page.locator("#unit-card select[name=mode]").count() else None
    note = helpers_org.add_members(page, queue_id, [a.id for a in accounts], q=tag, mode=mode)
    assert "уже участник" not in note, note
    helpers_org.open_structure(page, queue_id)
    for account in accounts:
        expect(helpers_org.member_row(page, account.id)).to_have_count(1)


class _DefaultQueue:
    """Очередь по умолчанию на время блока — своя (письмо заявителя попадает в неё); прежняя возвращается в `finally`."""

    def __init__(self, page, old_id, queue_id):
        self.page, self.old_id, self.queue_id = page, old_id, queue_id

    def __enter__(self):
        helpers_sd.set_default_queue(self.page, self.queue_id)
        return self

    def __exit__(self, *exc):
        helpers_sd.set_default_queue(self.page, self.old_id)
        return False


def _new_mail() -> str:
    """Письмом заявителя создаёт заявку в очереди по умолчанию (разбор ящика сразу); возвращает слово темы."""
    word = _word()
    helpers_sd.deliver(build_mail(from_addr=helpers_sd.requester_email(), to=[MAILBOX],
                                  subject=f"Не работает принтер {word}", text=f"Нужна помощь {word}",
                                  message_id=f"<{secrets.token_hex(8)}@client.test>"))
    return word


def _event(watchers) -> str:
    """Новая заявка в очереди: вкладки наблюдателей уже ждут соединения; ждёт, пока число колокольчика у каждого вырастет
    на 1 (уведомление на портале создано, значит доставки поставлены); возвращает слово темы."""
    bases = [helpers_notify.bell_count(w) for w in watchers]
    word = _new_mail()
    for watcher, base in zip(watchers, bases):
        helpers_notify.wait_bell_count(watcher, base + 1, timeout_ms=LONG_WAIT_MS)
    return word


def _tick() -> None:
    """Срок письма прошёл: ожидающие доставки стенда сдвинуты, обход выполнен (`shifted >= 1`: хотя бы у получателя с
    положительным контролем доставка ожидает)."""
    result = helpers_notify.tick(shift=PAST_ANY_TERM)
    assert result["shifted"] >= 1, result


def _portal_rows(page, word: str):
    """Строки списка `/notifications/`, в тексте которых есть слово темы (список только читает)."""
    page.goto("/notifications/")
    expect(page.locator("[data-notify-list]")).to_be_visible()
    return page.locator("ul[data-notifications] li[data-notification]").filter(has_text=word)


def _hours(start_offset: int, end_offset: int) -> tuple:
    """Часы «ЧЧ:ММ» (московское время) на `start_offset` и `end_offset` часов от текущего момента; начало позже конца
    (переход через полночь) допустимо (§ 6.6)."""
    now = datetime.now(MOSCOW)
    return ((now + timedelta(hours=start_offset)).strftime("%H:%M"),
            (now + timedelta(hours=end_offset)).strftime("%H:%M"))


def _cell(page, kind: str, channel: str):
    """Флажок ячейки таблицы `/me/notifications/` (§ 14.3)."""
    return page.locator(f'table[data-notify-table] tr[data-notify-kind="{kind}"] td[data-channel="{channel}"] '
                        f'input[type=checkbox][name="cell"][value="{kind}:{channel}"]')


def _fill_prefs(page, *, cells=None, quiet=None, days=(), start=None, end=None):
    """Открывает «Мои уведомления» и заполняет основную форму (таблица и тихие часы); возвращает форму. `cells` —
    `{(код вида, канал): состояние}`; `quiet` — `calendar`, `own` или `none`; для `own` — дни, начало и конец."""
    page.goto("/me/notifications/")
    form = page.locator('form[data-form="notify-prefs"]')
    expect(form).to_be_visible()
    for (kind, channel), state in (cells or {}).items():
        _cell(page, kind, channel).set_checked(state)
    if quiet is not None:
        form.locator(f'fieldset[data-quiet] input[type=radio][name="quiet_mode"][value="{quiet}"]').check()
    if quiet == "own":
        for day in ALL_DAYS:
            form.locator(f'fieldset[data-quiet] input[type=checkbox][name="own_days"][value="{day}"]'
                         ).set_checked(day in days)
        if start is not None:
            form.locator('fieldset[data-quiet] input[type=time][name="own_start"]').fill(start)
        if end is not None:
            form.locator('fieldset[data-quiet] input[type=time][name="own_end"]').fill(end)
    return form


def _save_prefs(page, **kwargs) -> None:
    """Заполняет и сохраняет форму; успех — переход на `/me/notifications/` с сообщением «Настройки уведомлений
    сохранены.» и без отказов поля (§ 13.2)."""
    form = _fill_prefs(page, **kwargs)
    with page.expect_navigation():
        form.locator('button[type=submit][data-action="save-prefs"]').click()
    page.wait_for_load_state()
    assert not helpers.alert_text(page), f"настройки не сохранены: {helpers.alert_text(page)}"
    expect(page.locator('form[data-form="notify-prefs"] [data-error]')).to_have_count(0)
    expect(page.locator("[role=status]").filter(has_text=SAVED).first).to_be_visible()


def _own_table(page) -> dict:
    """Состояние ячеек «Почта» и «Push в браузере» четырёх видов сервис-деска на странице сотрудника."""
    page.goto("/me/notifications/")
    expect(page.locator("table[data-notify-table]")).to_be_visible()
    table = {}
    for kind, _title in KINDS:
        for channel in ("email", "push"):
            cell = _cell(page, kind, channel)
            expect(cell).to_have_count(1)
            table[(kind, channel)] = cell.is_checked()
    return table


def _admin_cell(page, kind: str, channel: str):
    """Флажок таблицы значений по умолчанию на странице администратора (§ 14.4)."""
    return page.locator(f'table[data-defaults-table] tr[data-notify-kind="{kind}"] td[data-channel="{channel}"] '
                        f'input[type=checkbox][name="cell"][value="{kind}:{channel}"]')


def _admin_defaults(page) -> dict:
    """Значения по умолчанию, прочитанные со страницы `/settings/notifications/` (почта и push четырёх видов)."""
    page.goto("/settings/notifications/")
    expect(page.locator('form[data-form="notify-settings"]')).to_be_visible()
    values = {}
    for kind, _title in KINDS:
        for channel in ("email", "push"):
            cell = _admin_cell(page, kind, channel)
            expect(cell).to_have_count(1)
            values[(kind, channel)] = cell.is_checked()
    return values


def _admin_save(page, values: dict) -> None:
    """Администратор ставит ячейки таблицы по умолчанию и сохраняет страницу (§ 13.3, § 14.4)."""
    page.goto("/settings/notifications/")
    form = page.locator('form[data-form="notify-settings"]')
    expect(form).to_be_visible()
    for (kind, channel), state in values.items():
        _admin_cell(page, kind, channel).set_checked(state)
    with page.expect_navigation():
        form.locator('button[type=submit][data-action="save-settings"]').click()
    page.wait_for_load_state()
    refusals = page.locator("[data-error][data-code]")
    assert not refusals.count(), f"значения по умолчанию не сохранены: {refusals.first.get_attribute('data-code')}"
    expect(page.locator("[role=status]").filter(has_text=SAVED).first).to_be_visible()


# --- Тесты --------------------------------------------------------------------------------------------------

def test_e04_my_notifications_table_shows_kinds_with_module_five_channel_columns_and_fixed_portal_column(
        admin_page, employee):
    """Сценарий 4, п. 1: сотрудник открыл «Мои уведомления» — видна таблица: строки — виды (название, модуль), столбцы —
    «На портале», «Почта», «Push в браузере», «Telegram», «MAX»; столбец «На портале» отмечен у всех видов и не
    меняется (FR-321, FR-303)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [member], tag)  # без очереди строк видов в таблице нет (§ 4.3, доп. 18 (а))
    # п. 1: страница загружена
    tab = member.page
    tab.goto("/me/notifications/")
    expect(tab).to_have_title(re.compile("Мои уведомления"))  # h1 и title — «Мои уведомления» (§ 15.5)
    table = tab.locator("table[data-notify-table]")
    expect(table).to_be_visible()
    # п. 1: пять столбцов в порядке контракта, подписи § 15.5
    expect(table.locator("th[data-channel]")).to_have_text(list(COLUMNS))
    heads = table.locator("th[data-channel]").evaluate_all("els => els.map(e => e.dataset.channel)")
    assert heads == CHANNEL_ORDER, heads
    # п. 1: строки — четыре вида сервис-деска, три вида базы знаний и вид списков в порядке каталога, у каждой название
    # и модуль (CONTRACT-006, раздел 7.3)
    rows = table.locator("tr[data-notify-kind]")
    expect(rows).to_have_count(len(ROWS))
    codes = rows.evaluate_all("els => els.map(e => e.dataset.notifyKind)")
    assert codes == [code for code, _title in ROWS], codes
    for code, title in ROWS:
        row = table.locator(f'tr[data-notify-kind="{code}"]')
        expect(row.locator('[data-field="title"]')).to_have_text(title)
        module = (KB_MODULE if code.startswith("knowledge.") else LISTS_MODULE if code.startswith("lists.")
                  else FEED_MODULE if code.startswith("feed.") else MODULE)
        expect(row.locator('[data-field="module"]')).to_have_text(module)
        cells = row.locator("td[data-channel]")
        expect(cells).to_have_count(5)
        assert cells.evaluate_all("els => els.map(e => e.dataset.channel)") == CHANNEL_ORDER
        # п. 1: «На портале» отмечен у всех видов и не меняется: отмечен, недоступен, имени поля нет
        portal = row.locator('td[data-channel="portal"]')
        expect(portal).to_have_attribute("data-locked", "1")
        box = portal.locator("input[type=checkbox]")
        expect(box).to_have_count(1)
        expect(box).to_be_checked()
        expect(box).to_be_disabled()
        assert box.get_attribute("name") is None, "у ячейки «На портале» не должно быть имени поля"
        # «Почта» доступна всегда и стоит отмеченной (по умолчанию у видов включены все внешние каналы, § 3.2);
        # у `feed.like` внешних каналов нет (CONTRACT-007, раздел 7.1: `channels=("portal",)`) — флажка «Почты» нет
        if code == "feed.like":
            expect(row.locator('td[data-channel="email"] input[type=checkbox]')).to_have_count(0)
            continue
        expect(_cell(tab, code, "email")).to_be_checked()
        expect(_cell(tab, code, "email")).to_be_enabled()


def test_e04_unchecking_email_and_saving_stops_email_for_kind_and_keeps_portal_notification(
        admin_page, employee, new_context, mailpit):
    """Сценарий 4, п. 2: вид отмечен — сотрудник снимает галочку «Почта» и сохраняет, и уведомления этого вида письмом
    больше не приходят, а на портале остаются (FR-321, FR-327). Контроль: второй участник очереди с включённой
    «Почтой» то же письмо получает."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    muted, control = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [muted, control], tag)
    # п. 2: вид отмечен
    muted.page.goto("/me/notifications/")
    expect(_cell(muted.page, NEW_IN_QUEUE, "email")).to_be_checked()
    # п. 2: снимает «Почту» у вида «Новая заявка в моей очереди» и сохраняет (тихих часов нет: письмо уходит в любое время)
    _save_prefs(muted.page, cells={(NEW_IN_QUEUE, "email"): False}, quiet="none")
    expect(_cell(muted.page, NEW_IN_QUEUE, "email")).not_to_be_checked()
    expect(_cell(muted.page, ASSIGNED, "email")).to_be_checked()  # другие виды не тронуты
    expect(muted.page.locator(f'tr[data-notify-kind="{NEW_IN_QUEUE}"] td[data-channel="portal"] input')).to_be_checked()
    _save_prefs(control.page, quiet="none")  # контроль: «Почта» включена
    with _DefaultQueue(page, old_id, queue_id):
        tab_muted, tab_control = helpers_notify.open_watchers(new_context, [muted, control])
        word = _event([tab_muted, tab_control])
        # когда: проходит срок письма
        _tick()
        # п. 2: письмо получил только тот, у кого «Почта» включена
        helpers_notify.wait_item_mail(mailpit, control.email)
        assert helpers_notify.no_item_mail(mailpit, muted.email, wait=10), "письмо при снятой «Почте»"
        # п. 2: на портале уведомление осталось (непрочитанное)
        rows = _portal_rows(tab_muted, word)
        expect(rows).to_have_count(1)
        expect(rows).to_have_attribute("data-unread", "1")


def test_e04_unlinked_telegram_column_disabled_with_hint_and_push_column_disabled_until_device_allowed(
        admin_page, employee):
    """Сценарий 4, п. 3: Telegram не привязан — столбец «Telegram» недоступен с подсказкой «Привяжите Telegram» (у MAX —
    «Привяжите MAX»), а «Push в браузере» недоступен, пока push не разрешён на устройстве (FR-321, FR-324, FR-325).
    Каналы включает администратор (иначе причина — «отключён администратором»). Обратная сторона («устройство
    разрешено — столбец доступен») требует подписки и проходит в test_e05_webpush (T-4144)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [member], tag)
    with helpers_notify.channels_on(page, "telegram", "max", "webpush"):
        tab = member.page
        tab.goto("/me/notifications/")
        table = tab.locator("table[data-notify-table]")
        expect(table).to_be_visible()
        expect(table.locator("tr[data-notify-kind]")).to_have_count(len(ROWS))
        for code, _title in KINDS:
            row = table.locator(f'tr[data-notify-kind="{code}"]')
            # п. 3: Telegram и MAX не привязаны — ячейки недоступны, флажка нет, подсказка «Привяжите …»
            for channel, label in (("telegram", "Telegram"), ("max", "MAX")):
                cell = row.locator(f'td[data-channel="{channel}"]')
                expect(cell).to_have_attribute("data-available", "0")
                expect(cell).to_have_attribute("data-reason", "not_bound")
                expect(cell.locator("input")).to_have_count(0)
                expect(cell.locator("[data-hint]")).to_contain_text(f"Привяжите {label}")
            # п. 3: «Push в браузере» — нет подписки на этом устройстве
            push = row.locator('td[data-channel="push"]')
            expect(push).to_have_attribute("data-available", "0")
            expect(push).to_have_attribute("data-reason", "no_subscriptions")
            expect(push.locator("[data-hint]")).to_contain_text("Разрешите push на этом устройстве")
            box = push.locator('input[type=checkbox][name="cell"]')
            expect(box).to_have_count(1)
            expect(box).to_be_enabled()  # флажок есть всегда и не disabled (§ 14.3): значение уходит прежним
            # скрипт при недоступности ставит замок и отменяет щелчок (§ 14.3, notify-push.js)
            expect(push).to_have_attribute("data-locked", "1")
            before = box.is_checked()
            box.click(force=True)
            expect(box).to_be_checked(checked=before)
        # контроль: «Почта» и «На портале» доступны, подсказок у них нет
        email = table.locator(f'tr[data-notify-kind="{NEW_IN_QUEUE}"] td[data-channel="email"]')
        expect(email.locator("input")).to_be_enabled()
        expect(email.locator("[data-hint]")).to_have_count(0)


def test_e04_security_and_channel_unlinked_kinds_shown_as_separate_rows_without_checkboxes(admin_page, employee):
    """Сценарий 4, п. 4: виды безопасности показаны одной строкой «Безопасность: всегда», а вид «Канал отвязан» — строкой
    «Канал отвязан: всегда, только на портале», обе без галочек (FR-305, FR-321, FR-344)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [member], tag)
    tab = member.page
    tab.goto("/me/notifications/")
    expect(tab.locator("table[data-notify-table]")).to_be_visible()
    # п. 4: ровно две сводные строки в блоке неизменяемых строк
    fixed = tab.locator("tbody[data-fixed-rows] tr[data-notify-fixed]")
    expect(fixed).to_have_count(2)
    security = tab.locator('tbody[data-fixed-rows] tr[data-notify-fixed="security"]')
    expect(security).to_have_count(1)
    expect(security).to_contain_text("Безопасность: всегда")
    unbound = tab.locator('tbody[data-fixed-rows] tr[data-notify-fixed="channel_unbound"]')
    expect(unbound).to_have_count(1)
    expect(unbound).to_contain_text("Канал отвязан: всегда, только на портале")
    # п. 4: без галочек
    expect(fixed.locator("input")).to_have_count(0)
    # п. 4: отдельных строк с флажками у этих видов нет — они только в сводных строках
    expect(tab.locator('tr[data-notify-kind^="core."]')).to_have_count(0)
    expect(tab.locator('tr[data-notify-kind="notify.channel_unbound"]')).to_have_count(0)
    # сводные строки лежат после строк видов (§ 14.3)
    assert tab.evaluate(
        "() => { const rows = document.querySelectorAll('tr[data-notify-kind]'); "
        "const fixed = document.querySelector('tbody[data-fixed-rows]'); "
        "return rows.length > 0 && !!(rows[rows.length - 1].compareDocumentPosition(fixed) "
        "& Node.DOCUMENT_POSITION_FOLLOWING); }"), "сводные строки должны идти после строк видов"


def test_e04_untouched_table_shows_admin_defaults_and_after_first_save_own_values_apply(admin_page, employee):
    """Сценарий 4, п. 5: сотрудник, который сам ещё не менял таблицу, видит галочки по значениям администратора по
    умолчанию (прочитанным со страницы администратора); после его первого сохранения действуют его собственные
    значения, а новые значения администратора на него уже не влияют (FR-322). Контроль: второй сотрудник, не
    сохранявший таблицу, видит новые значения администратора. Значения администратора возвращаются в `finally`."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    tag = _tag()
    mine, untouched = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [mine, untouched], tag)
    original = _admin_defaults(page)  # значения администратора до теста
    try:
        # администратор меняет два значения по умолчанию
        first = dict(original)
        first[(REPLIED, "email")] = not original[(REPLIED, "email")]
        first[(ASSIGNED, "push")] = not original[(ASSIGNED, "push")]
        _admin_save(page, first)
        assert _admin_defaults(page) == first
        # п. 5: у обоих не менявших таблицу галочки стоят по значениям администратора
        assert _own_table(mine.page) == first
        assert _own_table(untouched.page) == first
        # п. 5: первое сохранение сотрудника — своё значение, отличное от значения администратора
        own = dict(first)
        own[(REPLY_FAILED, "email")] = not first[(REPLY_FAILED, "email")]
        _save_prefs(mine.page, cells={(REPLY_FAILED, "email"): own[(REPLY_FAILED, "email")]})
        assert _own_table(mine.page) == own
        # администратор меняет ещё одно значение по умолчанию
        second = dict(first)
        second[(NEW_IN_QUEUE, "email")] = not first[(NEW_IN_QUEUE, "email")]
        _admin_save(page, second)
        # п. 5: после первого сохранения действуют собственные значения, а не новые значения администратора
        assert _own_table(mine.page) == own
        # контроль: тот, кто таблицу не сохранял, видит новые значения администратора
        assert _own_table(untouched.page) == second
    finally:
        _admin_save(page, original)


def test_e04_own_hours_mode_stops_non_portal_channels_outside_set_hours(admin_page, employee, new_context, mailpit):
    """Сценарий 4, п. 6: тихие часы «По рабочему календарю компании» (по умолчанию) — сотрудник выбирает «Свои часы» и
    задаёт дни и часы, исключающие текущее московское время, и уведомления, кроме портала, вне заданных часов не
    шлются: письма нет, а на портале уведомление есть (FR-323, FR-329). Контроль: второй участник со «Своими часами»,
    включающими текущее время, то же письмо получает."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    outside, inside = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [outside, inside], tag)
    # п. 6: по умолчанию — «По рабочему календарю компании»
    outside.page.goto("/me/notifications/")
    expect(outside.page.locator('fieldset[data-quiet] input[name="quiet_mode"][value="calendar"]')).to_be_checked()
    # п. 6: «Свои часы» вне текущего времени (с +3 до +4 часов от сейчас), все дни
    start, end = _hours(3, 4)
    _save_prefs(outside.page, quiet="own", days=ALL_DAYS, start=start, end=end)
    outside.page.goto("/me/notifications/")
    expect(outside.page.locator('fieldset[data-quiet] input[name="quiet_mode"][value="own"]')).to_be_checked()
    expect(outside.page.locator('fieldset[data-quiet] input[name="own_start"]')).to_have_value(start)
    expect(outside.page.locator('fieldset[data-quiet] input[name="own_end"]')).to_have_value(end)
    # контроль: часы от двух часов назад до двух вперёд — сейчас рабочее время сотрудника
    in_start, in_end = _hours(-2, 2)
    _save_prefs(inside.page, quiet="own", days=ALL_DAYS, start=in_start, end=in_end)
    with _DefaultQueue(page, old_id, queue_id):
        tab_out, tab_in = helpers_notify.open_watchers(new_context, [outside, inside])
        word = _event([tab_out, tab_in])
        # когда: проходит срок письма
        _tick()
        # п. 6: контрольное письмо пришло; вне заданных часов письма нет и сводка не ушла
        helpers_notify.wait_item_mail(mailpit, inside.email)
        assert helpers_notify.no_item_mail(mailpit, outside.email, wait=10), "письмо вне заданных часов"
        assert helpers_notify.no_digest_mail(mailpit, outside.email, wait=2)
        # п. 6: на портале уведомление есть у обоих
        for tab in (tab_out, tab_in):
            expect(_portal_rows(tab, word)).to_have_count(1)


def test_e04_no_quiet_hours_mode_keeps_channels_round_the_clock_and_no_digest(
        admin_page, employee, new_context, mailpit):
    """Сценарий 4, п. 7: «Без тихих часов» (дежурный) — после сохранения почта и мессенджер работают круглосуточно, а
    сводки сотрудник не получает (FR-323, FR-330). Круглосуточность не зависит от времени суток стенда: контроль —
    второй участник с часами вне текущего времени, у которого письма и сообщения Telegram в это время нет."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    duty, other = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [duty, other], tag)
    bots = helpers_notify.fakebots()
    chat_duty, chat_other = _chat_id(), _chat_id()
    with _DefaultQueue(page, old_id, queue_id), helpers_notify.channels_on(page, "telegram"):
        helpers_notify.bind_channel(duty.page, bots, "telegram", chat_duty)
        helpers_notify.bind_channel(other.page, bots, "telegram", chat_other)
        # п. 7: сначала «Свои часы» вне текущего времени (поля own_* в строке остаются, § 14.3), затем «Без тихих часов»
        duty_start, duty_end = _hours(3, 4)
        _save_prefs(duty.page, quiet="own", days=ALL_DAYS, start=duty_start, end=duty_end)
        _save_prefs(duty.page, quiet="none")
        duty.page.goto("/me/notifications/")
        expect(duty.page.locator('fieldset[data-quiet] input[name="quiet_mode"][value="none"]')).to_be_checked()
        start, end = _hours(3, 4)
        _save_prefs(other.page, quiet="own", days=ALL_DAYS, start=start, end=end)
        tab_duty, tab_other = helpers_notify.open_watchers(new_context, [duty, other])
        _event([tab_duty, tab_other])
        # когда: проходит срок письма
        _tick()
        # п. 7: почта и Telegram у дежурного — в любое время суток
        helpers_notify.wait_item_mail(mailpit, duty.email)
        helpers_notify.wait_sent(bots, "telegram", chat_id=chat_duty, text_has=EXTERNAL_TEXT, timeout=60)
        # контроль: у второго вне его часов нет ни письма, ни сообщения (дежурный их получил)
        assert helpers_notify.no_item_mail(mailpit, other.email, wait=10), "письмо вне заданных часов"
        assert not [m for m in helpers_notify.sent_to(bots, "telegram", chat_other)
                    if EXTERNAL_TEXT in (m.get("text") or "")], "сообщение Telegram вне заданных часов"
        # п. 7: сводки у дежурного нет — письма нет и срок сводки не поставлен (чтение базы: решения C1, E23)
        assert helpers_notify.no_digest_mail(mailpit, duty.email, wait=4)
        planned = helpers.stand_shell(
            "from django.apps import apps; "
            "model = apps.get_model('notify', 'UserNotifySettings'); "
            f"print(model.objects.filter(user__email='{duty.email}', digest_due_at__isnull=False).count())")
        assert planned.splitlines()[-1].strip() == "0", f"у дежурного поставлена сводка: {planned!r}"


def test_e04_own_hours_with_start_equal_to_end_or_no_days_refused_with_explanation(admin_page, employee):
    """Сценарий 4, п. 8: «Свои часы» с началом, равным концу, или без отмеченных дней — портал отказывает с понятным
    объяснением у поля, введённые значения остаются, прежние настройки не меняются и в журнал ничего не пишется
    (FR-323)."""
    member = employee(full_name=f"{_tag()} Петр Петрович")
    tab = member.page
    # п. 8: начало равно концу (дни отмечены)
    form = _fill_prefs(tab, quiet="own", days=range(5), start="10:00", end="10:00")
    form.locator('button[type=submit][data-action="save-prefs"]').click()
    error = tab.locator('[data-error="own_end"][data-code="own_same_time"]')
    expect(error).to_be_visible()
    expect(error).to_have_text(CYRILLIC)  # объяснение по-русски (текст — § 15.4; тест сверяет код)
    expect(tab.locator('fieldset[data-quiet] input[name="own_start"]')).to_have_value("10:00")  # значения остались
    assert tab.url.rstrip("/").endswith("/me/notifications")
    # п. 8: ни одного отмеченного дня (время разное)
    form = _fill_prefs(tab, quiet="own", days=(), start="09:00", end="18:00")
    form.locator('button[type=submit][data-action="save-prefs"]').click()
    error = tab.locator('[data-error="own_days"][data-code="own_no_days"]')
    expect(error).to_be_visible()
    expect(error).to_have_text(CYRILLIC)
    expect(tab.locator('fieldset[data-quiet] input[name="own_start"]')).to_have_value("09:00")
    # п. 8: прежнее не изменилось — по-прежнему «По рабочему календарю компании»
    tab.goto("/me/notifications/")
    expect(tab.locator('fieldset[data-quiet] input[name="quiet_mode"][value="calendar"]')).to_be_checked()
    expect(tab.locator('form[data-form="notify-prefs"] [data-error]')).to_have_count(0)
    # п. 8: журнал не пополнился — отказ ничего не сохранил
    assert helpers_org.audit_rows(admin_page, "notify.user_settings_changed", member.id) == []
    # положительный контроль того же пути: верные «Свои часы» сохраняются и дают ровно одну запись журнала
    _save_prefs(tab, quiet="own", days=range(5), start="09:00", end="18:00")
    assert len(helpers_org.audit_rows(admin_page, "notify.user_settings_changed", member.id)) == 1


def test_e04_page_at_360px_width_has_no_horizontal_scroll(admin_page, employee, new_context):
    """Сценарий 4, п. 9: страница «Мои уведомления» на ширине 360 px — таблица складывается в карточки и горизонтальной
    прокрутки страницы нет (NFR-308)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [member], tag)  # таблица с семью строками (четыре вида сервис-деска и три вида базы знаний) — самый широкий случай
    context = new_context(viewport={"width": 360, "height": 800}, storage_state=helpers_notify.session_state(member))
    narrow = context.new_page()
    narrow.goto("/me/notifications/")
    # п. 9: таблица открыта
    expect(narrow.locator("[data-notify-prefs]")).to_be_visible()
    expect(narrow.locator('[data-section="push"]')).to_be_visible()
    narrow.wait_for_load_state("load")
    expect(narrow.locator('[data-narrow="cards"]').first).to_be_visible()
    expect(narrow.locator("tr[data-notify-kind]")).to_have_count(len(ROWS))
    # п. 9: горизонтальной прокрутки страницы нет
    assert helpers.no_horizontal_scroll(narrow), "на ширине 360 px появилась горизонтальная прокрутка"


def test_e04_own_hours_night_20_to_08_on_workdays_accepted_as_interval_through_midnight(admin_page, employee):
    """Сценарий 4, п. 10: «Свои часы» с 20:00 до 08:00 по рабочим дням (ночной график) — портал принимает: начало
    позже конца означает интервал через полночь, значения сохранены, а толкование проверено на фиксированных
    московских моментах чтением `quiet.is_working` (FR-323)."""
    member = employee(full_name=f"{_tag()} Петр Петрович")
    tab = member.page
    member_email = member.email
    # п. 10: дни Пн–Пт, с 20:00 до 08:00
    _save_prefs(tab, quiet="own", days=range(5), start="20:00", end="08:00")
    # п. 10: принято — отказов нет, значения сохранены
    tab.goto("/me/notifications/")
    expect(tab.locator('form[data-form="notify-prefs"] [data-error]')).to_have_count(0)
    expect(tab.locator('fieldset[data-quiet] input[name="quiet_mode"][value="own"]')).to_be_checked()
    for day in ALL_DAYS:
        box = tab.locator(f'fieldset[data-quiet] input[name="own_days"][value="{day}"]')
        expect(box).to_be_checked(checked=day < 5)
    expect(tab.locator('fieldset[data-quiet] input[name="own_start"]')).to_have_value("20:00")
    expect(tab.locator('fieldset[data-quiet] input[name="own_end"]')).to_have_value("08:00")
    # п. 10: толкование — «начало позже конца» это интервал через полночь, относящийся ко дню начала (§ 6.6, решение 32,
    # доп. 25 (г)). Чтение, не подготовка: `quiet.is_working(строка сотрудника, момент)` на фиксированных московских
    # моментах (2026-10-12 — понедельник), одна строка вывода на момент; вызов `helpers.stand_shell` назван в отчёте.
    moments = [(12, 21, 0, True), (13, 3, 0, True), (12, 3, 0, False), (13, 12, 0, False),
               (17, 3, 0, True), (17, 21, 0, False), (13, 8, 0, False)]
    out = helpers.stand_shell(
        "import importlib; from datetime import datetime; from zoneinfo import ZoneInfo; "
        "from django.apps import apps; "
        "quiet = importlib.import_module('apps.notify.services.quiet'); "
        "row = apps.get_model('notify', 'UserNotifySettings').objects.get(user__email='%s'); "
        "moscow = ZoneInfo('Europe/Moscow'); "
        "[print(quiet.is_working(row, datetime(2026, 10, d, h, m, tzinfo=moscow))) for d, h, m in %r]"
        % (member_email, [(d, h, m) for d, h, m, _ in moments]))
    got = [line.strip() for line in out.splitlines()[-len(moments):]]
    expected = [str(ok) for *_, ok in moments]
    assert got == expected, f"толкование 20:00-08:00 по Пн-Пт неверно: {got!r}, ожидалось {expected!r} для {moments!r}"


@helpers_notify.webpush_only
def test_e04_journal_shows_was_became_entries_for_table_hours_telegram_link_and_push_subscription_without_chat_id_or_subscription_data(
        admin_page, employee, webpush_context):
    """Сценарий 4, п. 11: сотрудник изменил таблицу «вид × канал» и тихие часы, привязал Telegram и подписал устройство на
    Web Push — в журнале `/audit/` есть записи «было / стало» на русском, в них нет идентификатора чата и данных
    подписки (FR-341). Подписка устройства — только в постоянном профиле Chromium и Edge (метка `webpush`,
    дополнение 23)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [member], tag)
    bots = helpers_notify.fakebots()
    chat = _chat_id()
    with helpers_notify.channels_on(page, "telegram", "webpush"):
        context = webpush_context()
        tab = helpers_notify.open_tab(context, member, grant=True)
        # п. 11: таблица и тихие часы одним сохранением — «Почта» вида «Мне назначили заявку» снята, часы 20:00–08:00
        _save_prefs(tab, cells={(ASSIGNED, "email"): False}, quiet="own", days=range(5), start="20:00", end="08:00")
        # п. 11: привязка Telegram кодом и подписка устройства на Web Push
        helpers_notify.bind_channel(tab, bots, "telegram", chat)
        helpers_notify.enable_push_on_device(tab)
        subscription = tab.evaluate(
            "async () => { const reg = await navigator.serviceWorker.getRegistration(); "
            "const data = (await reg.pushManager.getSubscription()).toJSON(); "
            "return [data.endpoint, data.keys.p256dh, data.keys.auth]; }")
        device_values = [str(chat)] + [str(item) for item in subscription]
        # п. 11: журнал — записи этого сотрудника по трём кодам § 9.2
        who = member.id
        checks = {
            "notify.user_settings_changed": "Личные настройки уведомлений изменены",
            "notify.channel_bound": "Канал уведомлений привязан",
            "notify.push_subscribed": "Устройство подписано на push",
        }
        entries = {}
        for action, title in checks.items():
            rows = helpers_org.audit_rows(page, action, who)
            sides = helpers_org.audit_sides(page, action, who)
            assert len(rows) == 1 and len(sides) == 1, f"{action}: записей {len(rows)}, ожидалась одна"
            assert title in rows[0], f"{action}: нет названия «{title}» в строке журнала"
            was, became = (" ".join(side.split()) for side in sides[0])  # без переводов строк между парами
            assert became not in ("", "—"), f"{action}: пустое «стало»"
            # без идентификатора чата и данных подписки: ни в строке, ни в «было / стало»
            text = " ".join((rows[0], was, became))
            for value in device_values:
                assert value not in text, f"{action}: в записи журнала есть идентификатор чата или данные подписки"
            assert "http" not in text.lower(), f"{action}: в записи журнала есть адрес"
            entries[action] = (was, became)
        # п. 11: таблица и тихие часы — названия полей по-русски, вид по названию, старое и новое значение режима
        was, became = entries["notify.user_settings_changed"]
        for side in (was, became):
            assert "ячейки таблицы" in side and "Мне назначили заявку" in side, side
            assert "тихие часы" in side, side
        assert was != became
        assert "по рабочему календарю компании" in was, was
        assert "свои часы" in became and "20:00" in became and "08:00" in became, became
        # п. 11: привязка Telegram — было «не привязан», стало «Telegram, привязан»
        was, became = entries["notify.channel_bound"]
        assert "привязан: нет" in was, was
        assert "Telegram" in became and "привязан: да" in became, became
        # п. 11: подписка устройства — браузер и платформа
        was, became = entries["notify.push_subscribed"]
        assert "браузер" in became and "платформа" in became, became
