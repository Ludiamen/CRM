"""T-4146: сценарий 7 — «Ночь и выходные»: тихие часы и утренняя сводка — события в нерабочее время видны на портале
сразу, а письма, push, Telegram и MAX копятся и уходят одной сводкой с началом рабочего времени
(FR-305, FR-323, FR-327, FR-329, FR-330, FR-333, FR-345).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-004.md):
- часов стенда не подменить: тихие часы сотрудника — «Свои часы» вокруг текущего московского времени
  (`datetime.now(ZoneInfo("Europe/Moscow"))`): окно «вне текущего времени» — со сдвигом на 3 часа вперёд (час длиной),
  «внутри» — от двух часов назад до двух вперёд; дни — все семь. «Начало рабочего времени» наступает сменой режима на
  «Без тихих часов» (`replan_digest` ставит срок сводки «сейчас», § 6.7) или своих часов, включающих текущее время,
  затем обходом `helpers_notify.tick()`; сводку собирает и шлёт `worker-notify` стенда, тест ждёт письмо в Mailpit и
  сообщение в `fakebots` (решение C1 контракта, § 8.2). Срок сводки `digest_due_at` читается из базы
  (`helpers.stand_shell`, `_due`: решения C1, E23);
- письмо уведомления в тихие часы становится «отложенным» не при создании, а в обходе после срока письма
  (§ 6.10 `send_due`): поэтому сначала `tick(shift=121)` (121 минута больше верхней границы срока письма, 120 минут,
  § 6.5), и только потом — смена режима; доставки Telegram, MAX и Web Push в тихие часы откладываются сразу при создании
  (§ 6.7 `create`);
- каналы Telegram, MAX и Web Push, которые тест включает на странице администратора, возвращаются в `finally`
  (`helpers_notify.channels_on`); очередь по умолчанию на время теста — своя (`_DefaultQueue`);
- тесты, где среди проверяемых каналов Web Push (в том числе «push не пришёл»), — с меткой `webpush_only` и устройством
  из `webpush_context()` (дополнение 23): вкладки сотрудника закрыты (открытая вкладка пропускает Web Push, FR-331),
  push читается со страницы `/sw.js` контекста; каждое «нет push / сообщения / письма» — после ожидания
  положительного контроля того же пути.
"""
import contextlib
import json
import re
import secrets
import time
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_notify, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_servicedesk import build_mail

NEW_IN_QUEUE = "servicedesk.new_in_queue"
ASSIGNED = "servicedesk.assigned"
EXTERNAL_NEW = "Новая заявка в вашей очереди"  # внешний текст вида (§ 15.2)
EXTERNAL_ASSIGNED = "Вам назначена заявка"  # § 15.2
NEW_DEVICE_TEXT = "Вход с нового устройства"  # § 15.1
PAST_ANY_TERM = 121  # минут: больше верхней границы срока письма (120 минут, § 6.5)
MOSCOW = ZoneInfo("Europe/Moscow")
ALL_DAYS = range(7)
SAVED = "Настройки уведомлений сохранены."  # § 15.4
MAIL_WAIT = 90.0
LONG_WAIT_MS = 15_000


# --- Общие помощники файла ---------------------------------------------------------------------------------

def _word() -> str:
    """Уникальное слово темы: буква и шесть шестнадцатеричных знаков (не из одних цифр, иначе поиск списка принял бы
    его за номер заявки)."""
    return f"t{secrets.token_hex(3)}"


def _tag() -> str:
    """Общее начало фамилий сотрудников теста: по нему «Добавить сотрудников» находит всех сразу."""
    return "Ночь" + secrets.token_hex(3)


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


def _team(page, employee, size: int) -> tuple:
    """Сотрудники-участники своей очереди: `(список, номер очереди)`."""
    tag = _tag()
    people = [_staff(employee, tag, i) for i in range(1, size + 1)]
    queue_id, _name = _queue(page)
    _members(page, queue_id, people, tag)
    return people, queue_id


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
    на 1 (уведомление на портале создано сразу, FR-329); возвращает слово темы."""
    bases = [helpers_notify.bell_count(w) for w in watchers]
    word = _new_mail()
    for watcher, base in zip(watchers, bases):
        helpers_notify.wait_bell_count(watcher, base + 1, timeout_ms=LONG_WAIT_MS)
    return word


def _tick() -> None:
    """Срок письма прошёл: ожидающие доставки стенда сдвинуты, обход выполнен (`shifted >= 1`: хотя бы у кого-то из
    получателей доставка ожидает; письма тихих часов становятся отложенными)."""
    result = helpers_notify.tick(shift=PAST_ANY_TERM)
    assert result["shifted"] >= 1, result


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


def _save_prefs(page, *, cells=None, quiet=None, days=(), start=None, end=None) -> None:
    """Открывает «Мои уведомления», заполняет основную форму (таблица и тихие часы: `quiet` — `calendar`, `own` или
    `none`; для `own` — дни, начало и конец) и сохраняет; успех — «Настройки уведомлений сохранены.» без отказов."""
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
    with page.expect_navigation():
        form.locator('button[type=submit][data-action="save-prefs"]').click()
    page.wait_for_load_state()
    assert not helpers.alert_text(page), f"настройки не сохранены: {helpers.alert_text(page)}"
    expect(page.locator('form[data-form="notify-prefs"] [data-error]')).to_have_count(0)
    expect(page.locator("[role=status]").filter(has_text=SAVED).first).to_be_visible()


def _quiet(page, *, offsets=(3, 4), cells=None) -> None:
    """Тихие часы: «Свои часы» в окне, не включающем текущее время (по умолчанию с +3 до +4 часов), все дни."""
    start, end = _hours(*offsets)
    _save_prefs(page, quiet="own", days=ALL_DAYS, start=start, end=end, cells=cells)


def _working(page) -> None:
    """«Свои часы» от двух часов назад до двух вперёд: сейчас рабочее время сотрудника."""
    start, end = _hours(-2, 2)
    _save_prefs(page, quiet="own", days=ALL_DAYS, start=start, end=end)


def _no_quiet(page) -> None:
    """Режим «Без тихих часов»: накопленное уходит сводкой сразу (п. 12)."""
    _save_prefs(page, quiet="none")


def _poll(page, check, what: str, *, timeout: float = 30.0):
    """Опрос с пределом: `check()` вернул истину — вернуть её; иначе по истечении `timeout` — `AssertionError`."""
    deadline = time.monotonic() + timeout
    while True:
        value = check()
        if value:
            return value
        if time.monotonic() >= deadline:
            raise AssertionError(f"не дождались: {what} ({timeout:.0f} с)")
        page.wait_for_timeout(500)


def _due(email: str):
    """Срок сводки `digest_due_at` сотрудника (московское время) или `None`. Чтение базы через `helpers.stand_shell`
    (решения C1, E23); адрес в вывод не попадает."""
    out = helpers.stand_shell(
        "from zoneinfo import ZoneInfo; from django.apps import apps; "
        "row = apps.get_model('notify', 'UserNotifySettings').objects.filter(user__email=" + repr(email) + ").first(); "
        "value = row.digest_due_at if row else None; "
        "print('NONE' if value is None else value.astimezone(ZoneInfo('Europe/Moscow')).isoformat())")
    last = out.splitlines()[-1].strip()
    return None if last == "NONE" else datetime.fromisoformat(last)


def _wait_due(page, email: str, *, timeout: float = 30.0):
    """Ждёт, пока у сотрудника появится срок сводки (отложенная доставка поставлена), и возвращает его."""
    return _poll(page, lambda: _due(email), "срок сводки digest_due_at", timeout=timeout)


def _assert_due_in(due, low: timedelta, high: timedelta) -> None:
    """Срок сводки `due` лежит от `low` до `high` после текущего момента (допуск на длительность теста)."""
    delta = due - datetime.now(MOSCOW)
    assert low < delta < high, f"срок сводки через {delta}, ожидалось между {low} и {high}"


def _delivery(email: str, channel: str):
    """`(состояние, число попыток)` последней доставки сводки сотрудника в канал или `None` (чтение базы через
    `helpers.stand_shell`: журнал попыток на портале не виден; адрес в вывод не попадает)."""
    out = helpers.stand_shell(
        "from django.apps import apps; model = apps.get_model('notify', 'Delivery'); "
        "row = model.objects.filter(digest__user__email=" + repr(email) + ", channel=" + repr(channel) + ").order_by('-pk').first(); "
        "print('NONE' if row is None else row.state + ' ' + str(row.attempts))")
    last = out.splitlines()[-1].strip()
    if last == "NONE":
        return None
    state, attempts = last.split()
    return state, int(attempts)


@contextlib.contextmanager
def _tab(context, url: str = "/me/notifications/"):
    """Короткая вкладка в контексте сотрудника (закрывается): пока она открыта, сотрудник «в сети»."""
    page = context.new_page()
    page.goto(url)
    try:
        yield page
    finally:
        page.close()


def _push_member(webpush_context, member, bots, channels=("telegram", "max")) -> tuple:
    """Устройство сотрудника: постоянный профиль `webpush_context()` с его сессией, разрешением и подпиской на Web Push
    (Web Push включён администратором), затем привязка ботов `channels` (уникальные `chat_id`). Все вкладки сотрудника
    закрыты (в том числе страница фикстуры `employee`): открытая вкладка пропускает Web Push (FR-331). Возвращает
    `(контекст, {канал: chat_id})`. Подписка идёт первой: привязка ботов занимает время, и первый push не уходит в
    первые секунды профиля (дополнение 23 (г))."""
    context = webpush_context()
    helpers_notify.adopt_session(context, member)
    helpers_notify.grant_notifications(context)
    with _tab(context) as tab:
        helpers_notify.enable_push_on_device(tab)
    member.page.close()
    chats = {}
    for channel in channels:
        chats[channel] = _chat_id()
        with _tab(context) as tab:
            helpers_notify.bind_channel(tab, bots, channel, chats[channel])
    return context, chats


def _count(bots, channel: str, chat, text: str) -> int:
    """Сколько сообщений бота `channel` в чат `chat` с текстом ровно `text`."""
    return len([m for m in helpers_notify.sent_to(bots, channel, chat) if (m.get("text") or "") == text])


def _digest_message(count: int) -> str:
    """Текст сообщения сводки (§ 15.2, § 15.6)."""
    if count % 100 not in range(11, 15) and count % 10 == 1:
        return f"У вас {count} новое уведомление"
    if count % 100 not in range(11, 15) and count % 10 in (2, 3, 4):
        return f"У вас {count} новых уведомления"
    return f"У вас {count} новых уведомлений"


def _digest_subject(count: int) -> str:
    """Тема письма сводки (§ 10.1, § 15.6)."""
    if count % 100 not in range(11, 15) and count % 10 == 1:
        return f"За нерабочее время: {count} уведомление"
    if count % 100 not in range(11, 15) and count % 10 in (2, 3, 4):
        return f"За нерабочее время: {count} уведомления"
    return f"За нерабочее время: {count} уведомлений"


def _push_subscriptions(email: str) -> int:
    """Число подписок Web Push сотрудника (`notify.PushSubscription`, § 2) — чтение базы через `helpers.stand_shell`;
    адрес подписки и ключи в вывод не попадают."""
    out = helpers.stand_shell(
        "from django.apps import apps; "
        "print(apps.get_model('notify', 'PushSubscription').objects.filter(user__email=" + repr(email) + ").count())")
    return int(out.splitlines()[-1].strip())


def _hours_in_minutes(start_minutes: int, end_minutes: int) -> tuple:
    """Часы «ЧЧ:ММ» (московское время) на `start_minutes` и `end_minutes` минут от текущего момента."""
    now = datetime.now(MOSCOW)
    return ((now + timedelta(minutes=start_minutes)).strftime("%H:%M"),
            (now + timedelta(minutes=end_minutes)).strftime("%H:%M"))


def _digest_items(mail: dict) -> list:
    """Строки списка сводки «текст — ссылка» (§ 10.2): строки тела со ссылкой `…/notifications/<id>/open/`."""
    return [line for line in mail["Text"].splitlines() if "/notifications/" in line and "/open/" in line]


def _assert_notifications_button(message: dict) -> None:
    """Сообщение сводки Telegram несёт ту же кнопку, что обычное сообщение бота (доп. 29 (б), § 6.9): первая кнопка
    `reply_markup.inline_keyboard[0][0]` — «Открыть уведомления» с адресом, оканчивающимся на `/notifications/`."""
    markup = message["reply_markup"]
    markup = json.loads(markup) if isinstance(markup, str) else markup
    button = markup["inline_keyboard"][0][0]
    assert button["text"] == "Открыть уведомления", button
    assert button["url"].endswith("/notifications/"), "адрес кнопки сводки"


def _digests_of(mailpit, email: str) -> list:
    return helpers_notify.find_mails(mailpit, email, helpers_notify.TEMPLATE_DIGEST)


def _portal_rows(page, word: str):
    """Строки списка `/notifications/`, в тексте которых есть `word` (список только читает)."""
    page.goto("/notifications/")
    expect(page.locator("[data-notify-list]")).to_be_visible()
    return page.locator("ul[data-notifications] li[data-notification]").filter(has_text=word)


def _wait_rows(page, word: str, *, count: int = 1, timeout: float = 15.0):
    """Список уведомлений с `count` строками о `word`: перезагружает страницу до предела (уведомление создаётся
    событием, а не в момент загрузки). Возвращает строки; не появились — `AssertionError`."""
    deadline = time.monotonic() + timeout
    while True:
        rows = _portal_rows(page, word)
        if rows.count() >= count:
            return rows
        if time.monotonic() >= deadline:
            raise AssertionError(f"на портале нет {count} уведомлений со словом темы за {timeout:.0f} с")
        page.wait_for_timeout(500)


def _mark_read(page, word: str) -> None:
    """Сотрудник открывает список и отмечает прочитанным уведомление о `word` кнопкой «Прочитать»."""
    row = _portal_rows(page, word)
    expect(row).to_have_count(1)
    row.locator('form[data-form="read"] button[data-action="read"]').click()
    expect(row).to_have_attribute("data-unread", "0")


def _control_all_channels(bots, chats: dict, context, title: str = EXTERNAL_NEW) -> None:
    """Положительный контроль обычного дня для сотрудника в режиме «Без тихих часов»: новая заявка — и сообщение в
    каждый привязанный мессенджер, и push на закрытую вкладку устройства (настоящий push-сервис, до 90 с)."""
    _new_mail()
    for channel, chat in chats.items():
        helpers_notify.wait_sent(bots, channel, chat_id=chat, text_has=title, timeout=MAIL_WAIT)
    shown = helpers_notify.wait_service_worker_notifications(context, count=1, timeout=MAIL_WAIT)
    assert any(n["title"] == title for n in shown), [n["title"] for n in shown]


def _candidates_for(card, query: str) -> None:
    box = card.locator('form[data-form="ticket-assign"] input[name=q]')
    with card.page.expect_response(lambda r: "/assignees/" in r.url) as info:
        box.fill(query)
    assert info.value.ok, f"подсказки назначения: ответ {info.value.status}"
    expect(card.locator('form[data-form="ticket-assign"] [data-candidates] label[data-candidate]').first).to_be_visible()


def _assign(page, number: int, user) -> None:
    """Назначить ответственного через карточку: подсказки → выбор → кнопка (CONTRACT-003, 13.3)."""
    card = helpers_sd.open_ticket(page, number)
    _candidates_for(card, user.full_name.split()[0])
    label = card.locator(f'label[data-candidate][data-user-id="{user.id}"]')
    expect(label).to_have_count(1)
    label.click()
    expect(label.locator("input[type=radio][name=assignee]")).to_be_checked()
    helpers.submit(card.locator('form[data-form="ticket-assign"]'))
    expect(card.locator('[data-field="assignee"]')).to_contain_text(user.full_name.split()[0])


def _midnight_guard(page) -> None:
    """Не начинать за 15 минут до полуночи по Москве (до события проходят создание сотрудников, очереди, загрузка
    календаря и вкладки — минуты): ждёт новой даты (предел ~17 минут) и ещё 15 секунд."""
    start = datetime.now(MOSCOW)
    if not (start.hour == 23 and start.minute >= 45):
        return
    deadline = time.monotonic() + 1020
    while datetime.now(MOSCOW).date() == start.date() and time.monotonic() < deadline:
        page.wait_for_timeout(2000)
    page.wait_for_timeout(15_000)


# --- Календарь среза 002: особый день «сегодня» (тест 6; доп. 29 (в) CONTRACT-004) --------------------------------
# Рабочую неделю и часы компании тест не трогает. Год загружен — меняется и возвращается только вид сегодняшнего дня;
# не загружен — тест загружает год и в `finally` удаляет только его (`_unload_calendar_year`).

DAY_FORM_KINDS = ("holiday", "day_off", "workday", "short")  # значения `select[name=kind]`; прочее — обычный день ("")


def _calendar_state(page, day) -> tuple:
    """Читает `/calendar/?year=<год дня>`: `(загружен ли год, вид дня `data-day-kind` или None)` — до всяких правок."""
    page.goto(f"/calendar/?year={day.year}")
    holder = page.locator(f'[data-calendar-year][data-year="{day.year}"]')
    expect(holder).to_be_visible()
    loaded = holder.get_attribute("data-loaded") == "true"
    cell = page.locator(f'td[data-date="{day.isoformat()}"]')
    kind = cell.get_attribute("data-day-kind") if cell.count() else None
    return loaded, kind


def _calendar_file(year: int):
    """Файл года: настоящий из `tests/fixtures/calendar/` (2024–2027); для других лет — файл формата открытых данных,
    собранный `support_org.calendar_csv` (как `test_o11_calendar._year_file_or_synthetic`): `(содержимое, имя, тип)`."""
    try:
        return helpers_org.calendar_fixture(f"cal{year}.csv"), "upload.bin", "application/octet-stream"
    except FileNotFoundError:
        from tests.support_org import calendar_csv
        return calendar_csv(year, {1: "1,2,3,4,5,6,7,8", 5: "1,9"}), f"cal{year}.csv", "text/csv"


def _load_calendar_year(page, year: int, state: dict) -> None:
    """Администратор загружает производственный календарь года (форма `calendar-upload`, предпросмотр и подтверждение;
    срез 002); номер загрузки из адреса `/calendar/upload/<id>/` кладёт в `state["upload"]` для `finally`."""
    page.goto("/calendar/upload/")
    form = page.locator('form[data-form="calendar-upload"]')
    expect(form).to_be_visible()
    form.locator("input[name=year]").fill(str(year))
    file, name, mime = _calendar_file(year)
    helpers_org.upload_file(form, file, name=name, mime=mime)
    page.wait_for_url(re.compile(r"/calendar/upload/\d+/"))
    state["upload"] = int(re.search(r"/calendar/upload/(\d+)/", page.url).group(1))
    preview = page.locator("[data-calendar-preview]")
    expect(preview).to_be_visible()
    helpers.submit(preview.locator("form").filter(has=page.locator('input[name=confirm][value="1"]')))
    page.wait_for_url(re.compile(rf"/calendar/\?year={year}$"))
    expect(page.locator("[role=status]:not([data-notice])").first).not_to_have_text("")


def _unload_calendar_year(year: int, upload) -> None:
    """Возврат «год не загружен» точечно через `helpers.stand_shell` (как `_stand_reset_years` теста сценария 11 среза
    002, но без `WorkCalendar.update`): удалены особые дни и отметка «загружен» этого года и своя загрузка `upload`
    (если известна), сброшен кэш отметок месяцев, поднят номер версии календаря."""
    helpers.stand_shell(
        "import redis\n"
        "from django.apps import apps\n"
        "from django.conf import settings\n"
        f"year = {int(year)}\n"
        f"upload = {upload!r}\n"
        "apps.get_model('org.SpecialDay').objects.filter(date__year=year).delete()\n"
        "apps.get_model('org.CalendarYear').objects.filter(year=year).delete()\n"
        "if upload is not None:\n"
        "    apps.get_model('org.CalendarUpload').objects.filter(pk=upload).delete()\n"
        "r = redis.Redis.from_url(settings.VALKEY_URL)\n"
        "for k in list(r.scan_iter('*calendar:marks:*')):\n"
        "    r.delete(k)\n"
        "for k in list(r.scan_iter('*calendar:version')):\n"
        "    r.incr(k)\n"
        "print('ok')\n")


def _set_day_kind(page, day, kind: str, expected_attr: str) -> None:
    """Правка вида дня в загруженном году формой дня (`/calendar/days/<ГГГГ-ММ-ДД>/`, срез 002): `kind` — значение
    `select[name=kind]` (пустая строка — обычный день); после сохранения `data-day-kind` ячейки равен `expected_attr`."""
    page.goto(f"/calendar/days/{day.isoformat()}/")
    form = page.locator('form[data-form="calendar-day"]')
    expect(form).to_be_visible()
    form.locator("select[name=kind]").select_option(kind)
    form.locator("button[type=submit]").click()
    page.wait_for_url(re.compile(rf"/calendar/\?year={day.year}$"))
    expect(page.locator(f'td[data-date="{day.isoformat()}"]')).to_have_attribute("data-day-kind", expected_attr)


def _expected_digest_due() -> datetime:
    """Срок сводки по календарю компании: `apps.org.services.calendar.next_working_start(сейчас)` через
    `helpers.stand_shell` (функция среза 002 — источник правды режима `calendar`, § 6.6; доп. 29 (в)). Московское время."""
    out = helpers.stand_shell(
        "import datetime; from zoneinfo import ZoneInfo; "
        "from apps.org.services.calendar import next_working_start; "
        "value = next_working_start(datetime.datetime.now(ZoneInfo('Europe/Moscow'))); "
        "print('NONE' if value is None else value.astimezone(ZoneInfo('Europe/Moscow')).isoformat())")
    last = out.splitlines()[-1].strip()
    assert last != "NONE", "next_working_start не нашла рабочего дня"
    return datetime.fromisoformat(last)


# --- Тесты --------------------------------------------------------------------------------------------------

@helpers_notify.webpush_only
def test_e07_event_in_quiet_hours_shows_on_portal_at_once_and_sends_no_mail_push_telegram_max(
        admin_page, employee, mailpit, webpush_context):
    """Сценарий 7, п. 1: нерабочее время сотрудника по его тихим часам, наступает событие (новая заявка в очереди) —
    уведомление на портале есть сразу, письмо, push, Telegram и MAX не отправляются, а копятся (срок сводки поставлен)
    (FR-329). Контроль: второй участник очереди с часами, включающими текущее время, получает то же событие письмом
    (по сроку), push, Telegram и MAX. Web Push — постоянные профили `webpush_context()` (метка webpush)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (quiet, control), queue_id = _team(page, employee, 2)
    bots = helpers_notify.fakebots()
    with _DefaultQueue(page, old_id, queue_id), helpers_notify.channels_on(page, "telegram", "max", "webpush"):
        ctx_q, chats_q = _push_member(webpush_context, quiet, bots)
        ctx_c, chats_c = _push_member(webpush_context, control, bots)
        with _tab(ctx_q) as tab:
            _quiet(tab)  # п. 1: сейчас нерабочее время сотрудника
        with _tab(ctx_c) as tab:
            _working(tab)  # контроль: сейчас рабочее время
        base = {channel: len(helpers_notify.sent_to(bots, channel, chats_q[channel])) for channel in chats_q}
        # когда: наступает событие
        word = _new_mail()
        # п. 1: на портале уведомление есть сразу
        with _tab(ctx_q, "/notifications/") as tab:
            rows = _wait_rows(tab, word)
            expect(rows).to_have_count(1)
            expect(rows).to_have_attribute("data-unread", "1")
        # контроль: рабочему сотруднику пришли сообщения в оба мессенджера и push на закрытую вкладку устройства
        for channel in ("telegram", "max"):
            found = helpers_notify.wait_sent(bots, channel, chat_id=chats_c[channel], text_has=EXTERNAL_NEW,
                                             timeout=MAIL_WAIT)
            assert found[-1]["text"] == EXTERNAL_NEW
        shown = helpers_notify.wait_service_worker_notifications(ctx_c, count=1, timeout=MAIL_WAIT)
        assert any(n["title"] == EXTERNAL_NEW for n in shown), [n["title"] for n in shown]
        # когда: проходит срок письма
        _tick()
        helpers_notify.wait_item_mail(mailpit, control.email, timeout=MAIL_WAIT)  # контроль: письмо у рабочего
        # п. 1: у сотрудника в тихие часы нет ни письма, ни сообщений мессенджеров, ни push
        assert helpers_notify.no_item_mail(mailpit, quiet.email, wait=10), "письмо в тихие часы"
        for channel in ("telegram", "max"):
            assert len(helpers_notify.sent_to(bots, channel, chats_q[channel])) == base[channel], \
                f"сообщение в {channel} в тихие часы"
        assert helpers_notify.no_service_worker_notifications(ctx_q, observe=10), "push в тихие часы"
        # п. 1: копятся — срок сводки поставлен на начало его рабочего времени (с +3 часов)
        due = _wait_due(page, quiet.email)
        _assert_due_in(due, timedelta(hours=2), timedelta(hours=3, minutes=5))
        assert _due(control.email) is None, "у рабочего сотрудника сводка поставлена"


def test_e07_term_expiring_in_quiet_hours_sends_no_separate_mail_and_goes_to_morning_digest(
        admin_page, employee, new_context, mailpit):
    """Сценарий 7, п. 2: уведомление создано в рабочее время и не прочитано, а срок письма истекает в тихие часы —
    отдельное письмо не уходит, уведомление попадает в утреннюю сводку (FR-327, FR-329). Порядок решения 7 задач: часы
    включают «сейчас» → событие → часы меняются на исключающие → срок письма → режим «Без тихих часов» → сводка.
    Контроль: второй участник в рабочих часах получает отдельное письмо после того же обхода."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (subject, control), queue_id = _team(page, employee, 2)
    _working(subject.page)  # п. 2: в рабочее время
    _working(control.page)
    with _DefaultQueue(page, old_id, queue_id):
        tab_s, tab_c = helpers_notify.open_watchers(new_context, [subject, control])
        word = _event([tab_s, tab_c])  # п. 2: уведомление создано в рабочее время, не прочитано
        _quiet(subject.page)  # п. 2: срок письма истекает в тихие часы
        # когда: срок проходит
        _tick()
        helpers_notify.wait_item_mail(mailpit, control.email, timeout=MAIL_WAIT)  # контроль: письмо рабочему
        # п. 2: отдельного письма нет; срок сводки поставлен
        assert helpers_notify.no_item_mail(mailpit, subject.email, wait=10), "отдельное письмо в тихие часы"
        _assert_due_in(_wait_due(page, subject.email), timedelta(hours=2), timedelta(hours=3, minutes=5))
        assert helpers_notify.no_digest_mail(mailpit, subject.email, wait=2)  # рабочее время ещё не наступило
        # «утро»: режим «Без тихих часов» → сводка сразу
        _no_quiet(subject.page)
        helpers_notify.tick()
        mail = helpers_notify.wait_digest_mail(mailpit, subject.email, timeout=MAIL_WAIT)
        # п. 2: уведомление — в сводке (текст и ссылка), тема по склонению
        assert mail["Subject"] == _digest_subject(1), mail["Subject"]
        items = _digest_items(mail)
        assert len(items) == 1 and word in items[0], items
        # «ровно одно» и отдельного письма так и нет — повторная проверка в конце
        assert helpers_notify.no_item_mail(mailpit, subject.email, wait=5)
        assert len(_digests_of(mailpit, subject.email)) == 1
        expect(_wait_rows(subject.page, word)).to_have_count(1)


@helpers_notify.webpush_only
def test_e07_seven_accumulated_three_read_gives_one_mail_for_four_and_one_telegram_message_only(
        admin_page, employee, mailpit, webpush_context):
    """Сценарий 7, п. 3: за ночь накопилось 7 уведомлений, 3 из них прочитаны на портале, у остальных включены «Почта»
    и Telegram (MAX и Web Push у сотрудника тоже привязаны и включены) — с началом рабочего времени приходит одно
    письмо «За нерабочее время: 4 уведомления» со списком «текст — ссылка» (без трёх прочитанных) и одно сообщение
    «У вас 4 новых уведомления» в Telegram; в MAX и Web Push сводки нет (FR-330; решение владельца 2026-10-10,
    ADR-0011, п. 6, 11). Контроль: обычная заявка в режиме «Без тихих часов» приходит и в MAX, и push-уведомлением."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (member,), queue_id = _team(page, employee, 1)
    bots = helpers_notify.fakebots()
    with _DefaultQueue(page, old_id, queue_id), helpers_notify.channels_on(page, "telegram", "max", "webpush"):
        context, chats = _push_member(webpush_context, member, bots)
        with _tab(context) as tab:
            _quiet(tab)  # п. 3: ночь
        base = {channel: len(helpers_notify.sent_to(bots, channel, chats[channel])) for channel in chats}
        words = [_new_mail() for _ in range(7)]  # п. 3: за ночь накопилось 7 уведомлений
        with _tab(context, "/notifications/") as tab:
            _wait_rows(tab, words[-1])
            for word in words:
                expect(_portal_rows(tab, word)).to_have_count(1)
            for word in words[:3]:  # п. 3: три прочитаны на портале
                _mark_read(tab, word)
        _tick()  # письма тихих часов отложены (4 непрочитанных; прочитанные пропущены)
        _wait_due(page, member.email)
        # когда: начинается рабочее время (режим «Без тихих часов»)
        with _tab(context) as tab:
            _no_quiet(tab)
        helpers_notify.tick()
        # п. 3: одно письмо на четыре уведомления со списком текст + ссылка
        mail = helpers_notify.wait_digest_mail(mailpit, member.email, timeout=MAIL_WAIT)
        assert mail["Subject"] == "За нерабочее время: 4 уведомления", mail["Subject"]
        assert "За нерабочее время: 4 уведомления:" in mail["Text"]
        items = _digest_items(mail)
        assert len(items) == 4, items
        for word in words[3:]:
            assert any(word in line for line in items), word
        for word in words[:3]:
            assert word not in mail["Text"], "в сводке прочитанное уведомление"
        # п. 3: одно сообщение в Telegram
        message = _digest_message(4)
        assert message == "У вас 4 новых уведомления"
        sent = helpers_notify.wait_sent(bots, "telegram", chat_id=chats["telegram"], text_has=message, timeout=MAIL_WAIT)
        _assert_notifications_button(sent[0])  # п. 3: сообщение + ссылка (кнопка «Открыть уведомления», доп. 29 (б))
        # п. 3: в MAX и Web Push сообщений сводки нет
        assert _count(bots, "max", chats["max"], message) == 0
        assert len(helpers_notify.sent_to(bots, "max", chats["max"])) == base["max"], "сообщение в MAX"
        assert helpers_notify.no_service_worker_notifications(context, observe=10), "push сводки"
        # контроль: тот же сотрудник днём — и MAX, и push
        _control_all_channels(bots, chats, context)
        # «ровно одно» — повторная проверка в конце
        assert len(_digests_of(mailpit, member.email)) == 1
        assert _count(bots, "telegram", chats["telegram"], message) == 1


def test_e07_all_accumulated_read_before_work_start_gives_no_digest(admin_page, employee, new_context, mailpit):
    """Сценарий 7, п. 4: всё накопленное прочитано до начала рабочего времени — сводки нет: ни письма, ни сообщения
    в Telegram (FR-330). Контроль: второй участник с непрочитанным накопленным в тот же обход получает и письмо
    сводки, и сообщение."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (reader, control), queue_id = _team(page, employee, 2)
    bots = helpers_notify.fakebots()
    chat_r, chat_c = _chat_id(), _chat_id()
    with _DefaultQueue(page, old_id, queue_id), helpers_notify.channels_on(page, "telegram"):
        helpers_notify.bind_channel(reader.page, bots, "telegram", chat_r)
        helpers_notify.bind_channel(control.page, bots, "telegram", chat_c)
        _quiet(reader.page)
        _quiet(control.page)
        tab_r, tab_c = helpers_notify.open_watchers(new_context, [reader, control])
        base_r = len(helpers_notify.sent_to(bots, "telegram", chat_r))
        words = [_event([tab_r, tab_c]) for _ in range(2)]
        _tick()
        for word in words:  # п. 4: накопленное прочитано до начала рабочего времени
            _mark_read(tab_r, word)
        # когда: начинается рабочее время (оба переходят на «Без тихих часов»)
        _no_quiet(reader.page)
        _no_quiet(control.page)
        helpers_notify.tick()
        # контроль: непрочитанное накопленное даёт письмо и сообщение
        helpers_notify.wait_digest_mail(mailpit, control.email, timeout=MAIL_WAIT)
        helpers_notify.wait_sent(bots, "telegram", chat_id=chat_c, text_has=_digest_message(2), timeout=MAIL_WAIT)
        # п. 4: у прочитавшего сводки нет ни письмом, ни в Telegram; срока сводки нет
        assert helpers_notify.no_digest_mail(mailpit, reader.email, wait=10), "письмо сводки при прочитанном"
        assert len(helpers_notify.sent_to(bots, "telegram", chat_r)) == base_r, "сообщение сводки при прочитанном"
        assert _due(reader.email) is None


@helpers_notify.webpush_only
def test_e07_no_quiet_hours_mode_sends_mail_by_term_push_and_messengers_at_night_as_by_day(
        admin_page, employee, mailpit, webpush_context):
    """Сценарий 7, п. 5: сотрудник выбрал «Без тихих часов», наступает событие «ночью» — почта (по сроку), push и
    мессенджеры работают как днём, сводки нет (FR-323). «Ночь» не зависит от времени суток стенда: контроль — второй
    участник со «Своими часами» вне текущего времени, у которого в это же время нет ни письма, ни сообщения Telegram.
    Web Push — постоянный профиль `webpush_context()` (метка webpush)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (duty, night), queue_id = _team(page, employee, 2)
    bots = helpers_notify.fakebots()
    chat_night = _chat_id()
    with _DefaultQueue(page, old_id, queue_id), helpers_notify.channels_on(page, "telegram", "max", "webpush"):
        ctx_d, chats_d = _push_member(webpush_context, duty, bots)
        helpers_notify.bind_channel(night.page, bots, "telegram", chat_night)
        with _tab(ctx_d) as tab:
            _quiet(tab)  # сначала «Свои часы» вне текущего времени (поля остаются), затем «Без тихих часов»
            _no_quiet(tab)
        _quiet(night.page)  # «ночной» сотрудник
        base_night = len(helpers_notify.sent_to(bots, "telegram", chat_night))
        # когда: наступает событие
        _new_mail()
        # п. 5: мессенджеры и push работают как днём
        for channel in ("telegram", "max"):
            helpers_notify.wait_sent(bots, channel, chat_id=chats_d[channel], text_has=EXTERNAL_NEW, timeout=MAIL_WAIT)
        shown = helpers_notify.wait_service_worker_notifications(ctx_d, count=1, timeout=MAIL_WAIT)
        assert any(n["title"] == EXTERNAL_NEW for n in shown), [n["title"] for n in shown]
        # п. 5: почта — по сроку
        _tick()
        helpers_notify.wait_item_mail(mailpit, duty.email, timeout=MAIL_WAIT)
        # контроль: «ночному» сотруднику в это же время ни письма, ни сообщения
        assert helpers_notify.no_item_mail(mailpit, night.email, wait=10), "письмо вне часов"
        assert len(helpers_notify.sent_to(bots, "telegram", chat_night)) == base_night, "сообщение вне часов"
        # п. 5: сводки у дежурного нет — ни письма, ни срока
        assert helpers_notify.no_digest_mail(mailpit, duty.email, wait=4)
        assert _due(duty.email) is None
        assert _due(night.email) is not None  # контроль: у «ночного» накопленное ждёт сводки


def test_e07_holiday_by_company_calendar_is_quiet_all_day_and_digest_comes_first_working_hour_of_next_working_day(
        admin_page, employee, new_context, mailpit):
    """Сценарий 7, п. 6: у сотрудника тихие часы «По рабочему календарю компании», по календарю среза 002 сегодня
    праздничный день — наступает событие: весь день тихие часы (отдельного письма нет, портал показывает сразу), а срок
    сводки — первый рабочий час следующего рабочего дня по Москве, рассчитанный по календарю (FR-323, FR-330).
    Контроль: второй участник со «Своими часами», включающими текущее время, получает письмо. Календарь текущего года
    загружается файлом (если не загружен), сегодняшний день делается праздником; в `finally` день возвращается к прежнему
    виду либо год удаляется (неделя и часы компании не трогаются)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    _midnight_guard(page)
    today = datetime.now(MOSCOW).date()
    (subject, control), queue_id = _team(page, employee, 2)
    loaded, prior_kind = _calendar_state(page, today)  # прежнее состояние читается до правок; неделю и часы не трогаем
    state = {"upload": None}
    try:
        if not loaded:
            _load_calendar_year(page, today.year, state)
        _set_day_kind(page, today, "holiday", "holiday")  # п. 6: праздничный день по календарю
        subject.page.goto("/me/notifications/")  # п. 6: «По рабочему календарю компании» — режим по умолчанию (без сохранения:
        expect(subject.page.locator('fieldset[data-quiet] input[name="quiet_mode"][value="calendar"]')).to_be_checked()  # доп. 21 (д)
        _working(control.page)
        expected = _expected_digest_due()  # next_working_start по календарю стенда (доп. 29 (в))
        with _DefaultQueue(page, old_id, queue_id):
            tab_s, tab_c = helpers_notify.open_watchers(new_context, [subject, control])
            word = _event([tab_s, tab_c])  # п. 6: портал показывает сразу
            _tick()
            helpers_notify.wait_item_mail(mailpit, control.email, timeout=MAIL_WAIT)  # контроль
            # п. 6: весь день тихие часы — отдельного письма нет
            assert helpers_notify.no_item_mail(mailpit, subject.email, wait=10), "письмо в праздничный день"
            # п. 6: сводка — в первый рабочий час следующего рабочего дня
            due = _wait_due(page, subject.email)
            assert due == expected, f"срок сводки {due.isoformat()}, по календарю ожидался {expected.isoformat()}"
            assert due.date() > today
            helpers_notify.tick()
            assert helpers_notify.no_digest_mail(mailpit, subject.email, wait=6), "сводка в праздничный день"
            expect(_wait_rows(subject.page, word)).to_have_count(1)
    finally:
        if loaded:  # год был загружен: возвращается прежний вид только этого дня
            if prior_kind is not None:
                back = prior_kind if prior_kind in DAY_FORM_KINDS else ""
                _set_day_kind(page, today, back, prior_kind)
        else:  # год не был загружен: удаляется только он (и своя загрузка)
            _unload_calendar_year(today.year, state["upload"])


def test_e07_security_kind_at_night_sends_core_mail_at_once_and_is_not_in_digest(
        admin_page, employee, new_context, mailpit):
    """Сценарий 7, п. 7: вид безопасности («Вход с нового устройства»), событие в тихие часы — письмо ядра уходит сразу,
    тихие часы его не задерживают; уведомление есть на портале, а в сводку оно не входит (FR-305). Контроль: заявка в
    те же тихие часы копится и приходит сводкой — в ней нет входа с нового устройства."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (member,), queue_id = _team(page, employee, 1)
    _quiet(member.page)  # п. 7: сейчас тихие часы сотрудника
    seen = helpers.mail_ids(mailpit, member.email)
    # когда: вход с нового устройства (новый контекст браузера)
    other = new_context().new_page()
    helpers.sign_in(other, member)
    # п. 7: письмо ядра ушло сразу (без обхода и срока)
    helpers.wait_mail(mailpit, member.email, "new_device", seen=seen, timeout=MAIL_WAIT)
    # п. 7: уведомление на портале есть, у вида нет доставок — срок сводки не поставлен
    expect(_wait_rows(other, NEW_DEVICE_TEXT)).to_have_count(1)
    assert _due(member.email) is None, "вид безопасности поставил срок сводки"
    with _DefaultQueue(page, old_id, queue_id):
        word = _new_mail()  # контроль: обычное событие в те же тихие часы
        _tick()
        assert helpers_notify.no_item_mail(mailpit, member.email, wait=10), "письмо заявки в тихие часы"
        _wait_due(page, member.email)
        # «начало рабочего времени» → сводка
        _no_quiet(member.page)
        helpers_notify.tick()
        mail = helpers_notify.wait_digest_mail(mailpit, member.email, timeout=MAIL_WAIT)
        # п. 7: в сводке только заявка, входа с нового устройства нет
        assert mail["Subject"] == _digest_subject(1), mail["Subject"]
        items = _digest_items(mail)
        assert len(items) == 1 and word in items[0], items
        assert NEW_DEVICE_TEXT not in mail["Text"], "вид безопасности попал в сводку"
        assert len(_digests_of(mailpit, member.email)) == 1


def test_e07_zero_accumulated_at_work_start_sends_nothing(admin_page, employee, new_context, mailpit):
    """Сценарий 7, п. 8: за тихие часы накопилось 0 уведомлений — с началом рабочего времени ничего не приходит: ни
    письма сводки, ни сообщения в Telegram, срока сводки нет (FR-330). Контроль: участник очереди, у которого за те же
    тихие часы накопилось событие, в тот же обход получает и письмо, и сообщение."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (accumulating,), queue_id = _team(page, employee, 1)
    empty = _staff(employee, _tag(), 1)  # не участник очереди: событий для него нет
    bots = helpers_notify.fakebots()
    chat_e, chat_a = _chat_id(), _chat_id()
    with _DefaultQueue(page, old_id, queue_id), helpers_notify.channels_on(page, "telegram"):
        helpers_notify.bind_channel(empty.page, bots, "telegram", chat_e)
        helpers_notify.bind_channel(accumulating.page, bots, "telegram", chat_a)
        _quiet(empty.page)  # п. 8: тихие часы, ничего не накопилось
        _quiet(accumulating.page)
        tab = helpers_notify.open_watchers(new_context, [accumulating])[0]
        base_e = len(helpers_notify.sent_to(bots, "telegram", chat_e))
        _event([tab])
        _tick()
        # когда: начинается рабочее время
        _no_quiet(empty.page)
        _no_quiet(accumulating.page)
        helpers_notify.tick()
        # контроль: у накопившего сводка есть
        helpers_notify.wait_digest_mail(mailpit, accumulating.email, timeout=MAIL_WAIT)
        helpers_notify.wait_sent(bots, "telegram", chat_id=chat_a, text_has=_digest_message(1), timeout=MAIL_WAIT)
        # п. 8: у пустого — ничего
        assert helpers_notify.no_digest_mail(mailpit, empty.email, wait=10), "письмо сводки при нуле накопленного"
        assert len(helpers_notify.sent_to(bots, "telegram", chat_e)) == base_e, "сообщение сводки при нуле накопленного"
        assert _due(empty.email) is None


@helpers_notify.webpush_only
def test_e07_two_telegram_only_and_two_push_only_unread_give_one_message_for_two_in_telegram(
        admin_page, employee, mailpit, webpush_context):
    """Сценарий 7, п. 9: из накопленных четырёх непрочитанных у двух включён только Telegram («Новая заявка в моей
    очереди»), у двух только Web Push («Мне назначили заявку») — с началом рабочего времени одно сообщение «У вас 2
    новых уведомления» уходит в Telegram, N — число накопленных непрочитанных, у вида которых этот канал включён
    (FR-330; решение владельца 2026-10-10, ADR-0011, п. 11); push и MAX сводки не получают. «Новая заявка» двух
    назначенных заявок к сборке сводки уже получила ответственного (п. 13) и в расчёт не входит. Контроль: назначение
    в режиме «Без тихих часов» приходит push-уведомлением. Web Push — профиль `webpush_context()` (метка webpush)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (member,), queue_id = _team(page, employee, 1)
    bots = helpers_notify.fakebots()
    with _DefaultQueue(page, old_id, queue_id), helpers_notify.channels_on(page, "telegram", "max", "webpush"):
        context, chats = _push_member(webpush_context, member, bots)
        cells = {(NEW_IN_QUEUE, "email"): False, (NEW_IN_QUEUE, "push"): False, (NEW_IN_QUEUE, "max"): False,
                 (NEW_IN_QUEUE, "telegram"): True,
                 (ASSIGNED, "email"): False, (ASSIGNED, "telegram"): False, (ASSIGNED, "max"): False,
                 (ASSIGNED, "push"): True}
        with _tab(context) as tab:
            _quiet(tab, cells=cells)  # п. 9: у вида «Новая заявка» только Telegram, у вида «Назначили» только Web Push
            for (kind, channel), state in cells.items():
                expect(_cell(tab, kind, channel)).to_be_checked(checked=state)
        base = {channel: len(helpers_notify.sent_to(bots, channel, chats[channel])) for channel in chats}
        telegram_only = [_new_mail() for _ in range(2)]  # две заявки остаются без ответственного
        assigned = [_new_mail() for _ in range(2)]  # две другие назначаются сотруднику
        for word in assigned:
            _assign(page, helpers_sd.ticket_number_by_subject(page, word), member)
        with _tab(context, "/notifications/") as tab:
            for word in telegram_only:
                _wait_rows(tab, word)
            for word in assigned:
                expect(_wait_rows(tab, "Вам назначена заявка").filter(has_text=word)).to_have_count(1)
        # когда: начинается рабочее время
        with _tab(context) as tab:
            _no_quiet(tab)
        helpers_notify.tick()
        # п. 9: одно сообщение «У вас 2 новых уведомления» в Telegram
        message = _digest_message(2)
        assert message == "У вас 2 новых уведомления"
        helpers_notify.wait_sent(bots, "telegram", chat_id=chats["telegram"], text_has=message, timeout=MAIL_WAIT)
        # п. 9: в MAX и в Web Push сводки нет; письма сводки нет (почта выключена у обоих видов)
        assert len(helpers_notify.sent_to(bots, "max", chats["max"])) == base["max"], "сводка в MAX"
        assert helpers_notify.no_service_worker_notifications(context, observe=10), "сводка в Web Push"
        assert helpers_notify.no_digest_mail(mailpit, member.email, wait=4)
        # контроль: назначение днём приходит push-уведомлением на то же устройство
        word = _new_mail()
        _assign(page, helpers_sd.ticket_number_by_subject(page, word), member)
        shown = helpers_notify.wait_service_worker_notifications(context, count=1, timeout=MAIL_WAIT)
        assert any(n["title"] == EXTERNAL_ASSIGNED for n in shown), [n["title"] for n in shown]
        # «ровно одно» — повторная проверка в конце
        assert _count(bots, "telegram", chats["telegram"], message) == 1


@helpers_notify.webpush_only
def test_e07_failed_digest_delivery_to_telegram_is_retried_there_and_not_moved_to_max_or_push(
        admin_page, employee, mailpit, webpush_context):
    """Сценарий 7, п. 10: доставка сводки в выбранный Telegram не удалась (учебная служба ответила 500 на отправку),
    сработали повторы по правилам FR-333 — сообщение остаётся в Telegram и приходит повтором туда же, в MAX и Web Push
    не переносится (FR-330, FR-333). Первая неудачная попытка видна в базе (`helpers.stand_shell`: доставка сводки
    ожидает, попыток 1). Контроль: обычная заявка в режиме «Без тихих часов» приходит и в MAX, и push-уведомлением.
    Web Push — профиль `webpush_context()` (метка webpush)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (member,), queue_id = _team(page, employee, 1)
    bots = helpers_notify.fakebots()
    with _DefaultQueue(page, old_id, queue_id), helpers_notify.channels_on(page, "telegram", "max", "webpush"):
        context, chats = _push_member(webpush_context, member, bots)
        with _tab(context) as tab:
            _quiet(tab)
        base_max = len(helpers_notify.sent_to(bots, "max", chats["max"]))
        words = [_new_mail() for _ in range(2)]
        with _tab(context, "/notifications/") as tab:
            _wait_rows(tab, words[-1])
        with _tab(context) as tab:
            _no_quiet(tab)
        # п. 10: служба откажет на следующую отправку сообщения Telegram
        bots.fail("telegram", 500, method="sendMessage", count=1)
        try:
            helpers_notify.tick()
            message = _digest_message(2)
            # п. 10: первая попытка не удалась — доставка сводки в Telegram ждёт повтора
            _poll(page, lambda: _delivery(member.email, "telegram") == ("waiting", 1), "неудачная первая попытка сводки",
                  timeout=MAIL_WAIT)
            assert _count(bots, "telegram", chats["telegram"], message) == 0
            # когда: срок повтора проходит
            helpers_notify.tick(shift=2)
            # п. 10: сообщение приходит повтором в тот же Telegram
            helpers_notify.wait_sent(bots, "telegram", chat_id=chats["telegram"], text_has=message, timeout=MAIL_WAIT)
            # п. 10: в MAX и Web Push не перенесено
            assert len(helpers_notify.sent_to(bots, "max", chats["max"])) == base_max, "сводка перенесена в MAX"
            assert helpers_notify.no_service_worker_notifications(context, observe=10), "сводка перенесена в Web Push"
            # контроль: те же каналы днём работают
            _control_all_channels(bots, chats, context)
            # «ровно одно» — повторная проверка в конце
            assert _count(bots, "telegram", chats["telegram"], message) == 1
            assert _delivery(member.email, "telegram")[0] == "sent"
        finally:
            bots.clear_fails("telegram")  # доп. 28 (а): остаток заказа не достаётся следующим тестам круга


def test_e07_all_accumulated_with_email_off_gives_no_digest_mail(admin_page, employee, new_context, mailpit):
    """Сценарий 7, п. 11: у всех накопленных непрочитанных «Почта» выключена — с началом рабочего времени письма сводки
    нет (сообщение в Telegram приходит) (FR-330; решение владельца 2026-10-10, ADR-0011, п. 6). Контроль: второй
    участник с включённой «Почтой» получает письмо сводки в тот же обход."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (no_mail, control), queue_id = _team(page, employee, 2)
    bots = helpers_notify.fakebots()
    chat = _chat_id()
    with _DefaultQueue(page, old_id, queue_id), helpers_notify.channels_on(page, "telegram"):
        helpers_notify.bind_channel(no_mail.page, bots, "telegram", chat)
        _quiet(no_mail.page, cells={(NEW_IN_QUEUE, "email"): False})  # п. 11: «Почта» выключена у вида
        expect(_cell(no_mail.page, NEW_IN_QUEUE, "email")).not_to_be_checked()
        _quiet(control.page)
        tab_n, tab_c = helpers_notify.open_watchers(new_context, [no_mail, control])
        _event([tab_n, tab_c])
        _tick()
        # когда: начинается рабочее время
        _no_quiet(no_mail.page)
        _no_quiet(control.page)
        helpers_notify.tick()
        # контроль: письмо сводки пришло тому, у кого «Почта» включена
        helpers_notify.wait_digest_mail(mailpit, control.email, timeout=MAIL_WAIT)
        # п. 11: сообщение в Telegram пришло, письма сводки нет
        helpers_notify.wait_sent(bots, "telegram", chat_id=chat, text_has=_digest_message(1), timeout=MAIL_WAIT)
        assert helpers_notify.no_digest_mail(mailpit, no_mail.email, wait=10), "письмо сводки при выключенной «Почте»"
        assert helpers_notify.no_item_mail(mailpit, no_mail.email, wait=2)


def test_e07_changing_quiet_hours_sends_digest_at_next_work_time_and_switch_to_no_quiet_hours_sends_it_at_once(
        admin_page, employee, new_context, mailpit):
    """Сценарий 7, п. 12: накопленные уведомления и смена тихих часов — срок сводки пересчитывается на ближайшее рабочее
    время по новым настройкам (было с +5 часов, стало с +3), а при переходе на «Без тихих часов» накопленное уходит
    сводкой сразу; «Свои часы», включающие текущее время, дают то же (FR-330; предложение, подтверждается подписью).
    Срок читается из базы (`helpers.stand_shell`), сам наступающий час ждать нельзя."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (to_none, to_hours), queue_id = _team(page, employee, 2)
    _quiet(to_none.page, offsets=(5, 6))
    _quiet(to_hours.page, offsets=(5, 6))
    with _DefaultQueue(page, old_id, queue_id):
        tab_n, tab_h = helpers_notify.open_watchers(new_context, [to_none, to_hours])
        word = _event([tab_n, tab_h])
        _tick()  # письма тихих часов отложены, срок сводки поставлен
        first = _wait_due(page, to_none.email)
        _assert_due_in(first, timedelta(hours=4), timedelta(hours=5, minutes=5))
        # когда: сотрудник меняет тихие часы на ближайшие (с +3 часов)
        _quiet(to_none.page, offsets=(3, 4))
        second = _poll(page, lambda: (lambda d: d if d and d < first else None)(_due(to_none.email)),
                       "пересчёт срока сводки")
        _assert_due_in(second, timedelta(hours=2), timedelta(hours=3, minutes=5))  # п. 12: по новым настройкам
        helpers_notify.tick()
        assert helpers_notify.no_digest_mail(mailpit, to_none.email, wait=6), "сводка до рабочего времени"
        # когда: переход на «Без тихих часов» — накопленное уходит сводкой сразу
        _no_quiet(to_none.page)
        helpers_notify.tick()
        mail = helpers_notify.wait_digest_mail(mailpit, to_none.email, timeout=MAIL_WAIT)
        assert mail["Subject"] == _digest_subject(1), mail["Subject"]
        assert word in "".join(_digest_items(mail))
        # «Свои часы», включающие текущее время: то же
        assert helpers_notify.no_digest_mail(mailpit, to_hours.email, wait=2)
        _working(to_hours.page)
        helpers_notify.tick()
        mail = helpers_notify.wait_digest_mail(mailpit, to_hours.email, timeout=MAIL_WAIT)
        assert word in "".join(_digest_items(mail))
        assert len(_digests_of(mailpit, to_none.email)) == 1 and len(_digests_of(mailpit, to_hours.email)) == 1


def test_e07_digest_skips_items_read_lost_access_or_already_assigned_by_build_time(
        admin_page, employee, new_context, mailpit):
    """Сценарий 7, п. 13: в сводку попало уведомление, которое к моменту сборки сотрудник прочитал, потерял доступ к
    заявке или «Новая заявка» которого уже получила ответственного, — в сводке строки о нём нет; остаётся только
    нетронутое (FR-330; предложение, подтверждается подписью). Четыре заявки: две очереди, сотрудник в обеих; письма
    уже отложены до изменений (проверки при сборке, а не при создании)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    subject, other = _staff(employee, tag, 1), _staff(employee, tag, 2)
    queue_a, _name_a = _queue(page, "ПоддержкаА")
    queue_b, _name_b = _queue(page, "ПоддержкаБ")
    _members(page, queue_a, [subject], tag)
    _members(page, queue_b, [subject, other], tag)
    _quiet(subject.page)
    with _DefaultQueue(page, old_id, queue_a):
        lost = _new_mail()  # заявка очереди А: доступ потеряется
    with _DefaultQueue(page, old_id, queue_b):
        kept, read, assigned = _new_mail(), _new_mail(), _new_mail()
    for word in (lost, kept, read, assigned):
        expect(_wait_rows(subject.page, word)).to_have_count(1)
    _tick()  # письма четырёх уведомлений отложены
    _wait_due(page, subject.email)
    # п. 13: к моменту сборки — прочитал на портале
    _mark_read(subject.page, read)
    # п. 13: «Новая заявка» получила ответственного (другого сотрудника)
    _assign(page, helpers_sd.ticket_number_by_subject(page, assigned), other)
    # п. 13: потерял доступ к заявке очереди А (убран из её участников)
    helpers_org.open_structure(page, queue_a)
    helpers_org.remove_member(page, subject.id)
    helpers_org.open_structure(page, queue_a)
    expect(helpers_org.member_row(page, subject.id)).to_have_count(0)
    # когда: начинается рабочее время
    _no_quiet(subject.page)
    helpers_notify.tick()
    mail = helpers_notify.wait_digest_mail(mailpit, subject.email, timeout=MAIL_WAIT)
    # п. 13: в сводке только нетронутая заявка
    assert mail["Subject"] == _digest_subject(1), mail["Subject"]
    items = _digest_items(mail)
    assert len(items) == 1 and kept in items[0], items
    for word in (lost, read, assigned):
        assert word not in mail["Text"], "в сводке уведомление, которое при сборке уже не нужно"
    assert len(_digests_of(mailpit, subject.email)) == 1


@helpers_notify.webpush_only
def test_e07_blocked_account_gets_no_mail_push_messengers_or_digest_and_portal_notifications_accumulate(
        admin_page, employee, new_context, mailpit, webpush_context):
    """Сценарий 7, п. 14: учётная запись сотрудника заблокирована (не уволен) — письма уведомлений, push, Telegram, MAX
    и сводка не уходят, а уведомления на портале копятся; письма безопасности ядра — как в срезе 001 (их отсутствие не
    проверяется) (FR-345). Блокировка подписки Web Push не снимает (доп. 29 (а)). Контроль: до блокировки то же событие
    пришло этому сотруднику и в Telegram, и push-уведомлением; ветвь «сводка» — оба сотрудника в «Своих часах» с началом
    через две минуты (сейчас тихие часы), событие копится (`held`, срок сводки), блокируется один из них, начало часов
    наступает — сводку получает только участник-контроль, у заблокированного срок сводки очищен. Web Push — профиль
    `webpush_context()` (метка webpush)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    (blocked, control), queue_id = _team(page, employee, 2)
    bots = helpers_notify.fakebots()
    chat_c = _chat_id()
    with _DefaultQueue(page, old_id, queue_id), helpers_notify.channels_on(page, "telegram", "webpush"):
        ctx_b, chats_b = _push_member(webpush_context, blocked, bots, channels=("telegram",))
        helpers_notify.bind_channel(control.page, bots, "telegram", chat_c)
        with _tab(ctx_b) as tab:
            _no_quiet(tab)
        _no_quiet(control.page)
        # контроль до блокировки: Telegram и push доходят до этого сотрудника
        _new_mail()
        helpers_notify.wait_sent(bots, "telegram", chat_id=chats_b["telegram"], text_has=EXTERNAL_NEW, timeout=MAIL_WAIT)
        shown = helpers_notify.wait_service_worker_notifications(ctx_b, count=1, timeout=MAIL_WAIT)
        assert any(n["title"] == EXTERNAL_NEW for n in shown), [n["title"] for n in shown]
        helpers_notify.wait_sent(bots, "telegram", chat_id=chat_c, text_has=EXTERNAL_NEW, timeout=MAIL_WAIT)
        helpers_notify.close_service_worker_notifications(ctx_b)
        # ветвь «сводка»: «Свои часы» с началом через 3 минуты (запас на отброшенные секунды) и концом через час — сейчас тихие часы у обоих
        start, end = _hours_in_minutes(3, 63)
        with _tab(ctx_b) as tab:
            _save_prefs(tab, quiet="own", days=ALL_DAYS, start=start, end=end)
        _save_prefs(control.page, quiet="own", days=ALL_DAYS, start=start, end=end)
        base_b = len(helpers_notify.sent_to(bots, "telegram", chats_b["telegram"]))
        word_before = _new_mail()  # событие копится: доставки Telegram и Web Push — held, срок сводки поставлен
        due_b = _wait_due(page, blocked.email)
        _wait_due(page, control.email)
        _assert_due_in(due_b, timedelta(seconds=-30), timedelta(minutes=4))
        # п. 14: администратор блокирует учётную запись (не увольняет)
        page.goto(f"/staff/{blocked.id}/")
        helpers.open_security_tab(page)
        form = page.locator('form[action$="/block/"]')
        try:
            form.locator("[name=reason]").fill("Проверка приёмки: блокировка администратором")
            helpers.submit(form)
            page.goto("/staff/?state=blocked")
            expect(page.locator(f'tr[data-user-id="{blocked.id}"][data-state="blocked"]')).to_have_count(1)
            # доп. 29 (а): блокировка подписку устройства не снимает
            assert _push_subscriptions(blocked.email) == 1, "подписка Web Push после блокировки"
            # когда: наступает событие
            word = _new_mail()
            _tick()  # письма тихих часов: у контроля отложены, ожидающее письмо заблокированного отсекается
            # п. 14: ни письма, ни Telegram, ни push
            assert helpers_notify.no_item_mail(mailpit, blocked.email, wait=10), "письмо заблокированному"
            assert len(helpers_notify.sent_to(bots, "telegram", chats_b["telegram"])) == base_b, "Telegram заблокированному"
            assert helpers_notify.no_service_worker_notifications(ctx_b, observe=10), "push заблокированному"
            # ветвь «сводка»: ждём начала рабочих часов (срок сводки заблокированного), затем обход
            _poll(page, lambda: datetime.now(MOSCOW) >= due_b + timedelta(seconds=3), "начало рабочих часов",
                  timeout=300.0)
            helpers_notify.tick()
            # контроль: участник-контроль получает сводку (письмом и в Telegram)
            helpers_notify.wait_digest_mail(mailpit, control.email, timeout=MAIL_WAIT)
            helpers_notify.wait_sent(bots, "telegram", chat_id=chat_c, text_has=_digest_message(2), timeout=MAIL_WAIT)
            # п. 14: у заблокированного сводки нет, срок очищен (сборка прошла по ветви «заблокирован»)
            _poll(page, lambda: _due(blocked.email) is None, "срок сводки заблокированного очищен")
            assert helpers_notify.no_digest_mail(mailpit, blocked.email, wait=6), "сводка заблокированному"
            assert len(helpers_notify.sent_to(bots, "telegram", chats_b["telegram"])) == base_b, "сводка в Telegram"
            assert helpers_notify.no_service_worker_notifications(ctx_b, observe=5), "push сводки заблокированному"
        finally:
            page.goto(f"/staff/{blocked.id}/")
            helpers.open_security_tab(page)
            unblock = page.locator('form[action$="/unblock/"]')
            if unblock.count():
                helpers.submit(unblock)
        # п. 14: сводки нет и после снятия блокировки; уведомления на портале накопились
        helpers_notify.tick()
        assert helpers_notify.no_digest_mail(mailpit, blocked.email, wait=6), "сводка заблокированному"
        returned = new_context().new_page()
        helpers.sign_in(returned, blocked)
        expect(_wait_rows(returned, word_before)).to_have_count(1)
        expect(_wait_rows(returned, word)).to_have_count(1)
