"""T-7148: сценарий 9 — уведомления ленты по каналам (FR-626, FR-629, FR-630, FR-631, FR-632, NFR-609).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-007.md разделы 7, 10, 12, 13, 14; решения 8, 14, 23, 54
задач; образцы — test_k09_notify.py, test_e06_bots.py, test_e07_quiet_digest.py):
- помощники ленты — только из `helpers_feed.py` (`publish`, `open_feed`, `feed_mail`, `tick_mail`, `age`, `badge`,
  `bell`…); правка и удаление записи в этом файле — свои короткие помощники `_edit_post`, `_delete_post` по зацепкам
  раздела 12.3 (в `helpers_feed.py` их нет — вопрос Opus в итоге);
- у каждого получателя, чьё письмо или сообщение проверяется, режим «Без тихих часов» (иначе ночью всё ушло бы в
  сводку); тихие часы — только в тесте про тихие часы;
- Telegram включает администратор на время теста (`helpers_notify.channels_on`), привязка — `bind_channel` (до 120 с);
  `fakebots` одна на круг, сообщения выбираются по своему `chat_id`;
- письмо «через 15 минут» — `tick_mail()` (решение 14 задач); «письма нет» проверяется только после положительного
  контроля другого получателя или другой записи;
- ПДн и секретов в данных нет; имена и слова собираются с уникальной частью (`_uid`).
"""
import json
import re
import secrets
import time
from datetime import datetime, timedelta
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_feed, helpers_notify, helpers_org
from tests.e2e.helpers_feed import POST_ALL, MODERATE

MOSCOW = ZoneInfo("Europe/Moscow")
SAVED = "Настройки уведомлений сохранены."  # прежний текст «Мои уведомления» (CONTRACT-004, 15.4)
FOR_YOU, MENTION, COMMENT = "feed.for_you", "feed.mention", "feed.comment"
IMPORTANT, INVITE, EVENT_CHANGED = "feed.important", "feed.invite", "feed.event_changed"
REMINDER, LIKE = "feed.event_reminder", "feed.like"
FEED_KINDS = (FOR_YOU, MENTION, COMMENT, IMPORTANT, INVITE, EVENT_CHANGED, REMINDER, LIKE)  # порядок `order` 70…77
EXTERNAL_MENTION = "Вас упомянули в ленте"        # CONTRACT-007, 7.1
EXTERNAL_INVITE = "Приглашение на событие в ленте"
EXTERNAL_CHANGED = "Событие в ленте изменено"
ALL_DAYS = range(7)
MAIL_WAIT = 90.0


# --- Общие помощники файла ---------------------------------------------------------------------------------------

def _uid() -> str:
    """Уникальная часть имён и слов теста: шесть шестнадцатеричных знаков."""
    return secrets.token_hex(3)


def _chat_id() -> int:
    """Уникальный номер чата `fakebots` для роли теста (служба одна на круг)."""
    return secrets.randbelow(900_000_000) + 100_000_000


def _norm(text: str) -> str:
    return " ".join(text.split())


def _words(prefix: str, length: int) -> str:
    """Строка из слов `<prefix>NNN` ровно `length` знаков (слова по восемь-девять знаков, обрезка по границе знака)."""
    text = " ".join(f"{prefix}{i:03d}" for i in range(80))
    return text[:length]


def _writer(admin_page, employee):
    """Сотрудник с правом «Писать всем» (роль только с этим правом)."""
    role = helpers_feed.make_role(admin_page, [POST_ALL])
    return employee(role=role, full_name=f"Писарев{_uid()} Иван Иванович")


def _moderator(admin_page, employee):
    role = helpers_feed.make_role(admin_page, [MODERATE])
    return employee(role=role, full_name=f"Модераторов{_uid()} Иван Иванович")


def _person(employee, surname: str, mark: str = ""):
    return employee(full_name=f"{surname}{mark or _uid()} Пётр Петрович")


def _unit(admin_page, prefix: str, members, mark: str) -> tuple:
    """Новый отдел под корнем с участниками `members` (в их ФИО общая часть `mark`): `(номер, название)`."""
    helpers_org.open_structure(admin_page)
    root = helpers_org.root_id(admin_page)
    name = helpers_org.unique_name(prefix)
    unit_id = helpers_org.create_unit(admin_page, name, kind="department", parent_id=root)
    helpers_org.add_members(admin_page, unit_id, [a.id for a in members], q=mark, mode="concurrent")
    return unit_id, name


def _cell(page, kind: str, channel: str):
    """Флажок ячейки таблицы `/me/notifications/`."""
    return page.locator(f'table[data-notify-table] tr[data-notify-kind="{kind}"] td[data-channel="{channel}"] '
                        f'input[type=checkbox][name="cell"][value="{kind}:{channel}"]')


def _save_prefs(page, *, cells=None, quiet=None, start=None, end=None) -> None:
    """«Мои уведомления»: ячейки `{(вид, канал): состояние}`, режим тихих часов (`none`, `own`; для `own` — все дни,
    начало и конец), сохранение; успех — «Настройки уведомлений сохранены.» без отказов."""
    page.goto("/me/notifications/")
    form = page.locator('form[data-form="notify-prefs"]')
    expect(form).to_be_visible()
    for (kind, channel), state in (cells or {}).items():
        _cell(page, kind, channel).set_checked(state)
    if quiet is not None:
        form.locator(f'fieldset[data-quiet] input[type=radio][name="quiet_mode"][value="{quiet}"]').check()
    if quiet == "own":
        for day in ALL_DAYS:
            form.locator(f'fieldset[data-quiet] input[type=checkbox][name="own_days"][value="{day}"]').set_checked(True)
        form.locator('fieldset[data-quiet] input[type=time][name="own_start"]').fill(start)
        form.locator('fieldset[data-quiet] input[type=time][name="own_end"]').fill(end)
    with page.expect_navigation():
        form.locator('button[type=submit][data-action="save-prefs"]').click()
    page.wait_for_load_state()
    assert not helpers.alert_text(page), f"настройки не сохранены: {helpers.alert_text(page)}"
    expect(page.locator("[role=status]").filter(has_text=SAVED).first).to_be_visible()


def _hours(start_offset: int, end_offset: int) -> tuple:
    """Часы «ЧЧ:ММ» (Москва) на `start_offset` и `end_offset` часов от текущего момента."""
    now = datetime.now(MOSCOW)
    return ((now + timedelta(hours=start_offset)).strftime("%H:%M"),
            (now + timedelta(hours=end_offset)).strftime("%H:%M"))


def _mail_ids(mailpit, to: str) -> set:
    """Номера уже имеющихся писем `notify.item` на адрес (ждать только новое)."""
    return {short["ID"] for short in helpers_notify.find_mails(mailpit, to, helpers_notify.TEMPLATE_ITEM)}


def _rows(page, word: str):
    """Строки списка `/notifications/` со словом `word` (список только читает)."""
    page.goto("/notifications/")
    expect(page.locator("[data-notify-list]")).to_be_visible()
    return page.locator("ul[data-notifications] li[data-notification]").filter(has_text=word)


def _wait_rows(page, word: str, count: int = 1, timeout: float = 20.0):
    """Перезагружает список до предела, пока строк со словом не меньше `count`; возвращает строки."""
    deadline = time.monotonic() + timeout
    while True:
        rows = _rows(page, word)
        if rows.count() >= count:
            return rows
        if time.monotonic() >= deadline:
            raise AssertionError(f"уведомлений со словом {word!r}: {rows.count()}, ждали {count} за {timeout:.0f} с")
        page.wait_for_timeout(500)


def _row_text(row) -> str:
    return _norm(row.locator('[data-field="text"]').first.inner_text())


def _link(row) -> str:
    """Адрес ссылки уведомления `/notifications/<id>/open/`."""
    return row.locator('[data-field="text"] a[data-open]').first.get_attribute("href")


def _status_of(page, href: str) -> int:
    """Код ответа после перехода по адресу (редиректы пройдены)."""
    return page.goto(href).status


def _button_url(message: dict) -> str:
    """Адрес кнопки сообщения Telegram: `reply_markup.inline_keyboard[0][0].url`."""
    markup = message["reply_markup"]
    markup = json.loads(markup) if isinstance(markup, str) else markup
    return markup["inline_keyboard"][0][0]["url"]


def _future(days: int) -> datetime:
    """Время события через `days` суток по Москве, без часового пояса (так его принимают поля формы)."""
    return (datetime.now(MOSCOW) + timedelta(days=days)).replace(tzinfo=None, second=0, microsecond=0)


def _edit_post(page, post_id, **fields) -> None:
    """Правка записи формой `/feed/<id>/edit/`: поля `text`, `event_title`, `event_place` (раздел 10.2, 12.3);
    ждёт переход на карточку. Помощника правки в `helpers_feed.py` нет."""
    page.goto(f"/feed/{post_id}/edit/")
    expect(page.locator('[data-feed-page="edit"]')).to_be_visible()
    form = page.locator('[data-feed-page="edit"] form:has(textarea[name="text"])').first
    for name, value in fields.items():
        form.locator(f'[name="{name}"]').fill(value)
    with page.expect_navigation():
        form.locator("button[type=submit]").first.click()
    page.wait_for_load_state()
    expect(page.locator('[data-feed-page="card"]')).to_be_visible()


def _delete_post(page, post_id) -> None:
    """Удаление записи с карточки: «Удалить» → подтверждение `dialog[data-feed-confirm]` → запись исчезла.
    Помощника удаления в `helpers_feed.py` нет."""
    page.goto(f"/feed/{post_id}/")
    post = page.locator(f"#feed-post-{post_id}")
    post.locator('button[data-action="post-delete"]').first.click()
    dialog = page.locator("dialog[data-feed-confirm][open]")
    expect(dialog).to_be_visible()
    with page.expect_response(lambda r: r.request.method == "POST" and f"/feed/{post_id}/delete/" in r.url):
        dialog.locator("button[type=submit]").click()
    expect(post).to_have_count(0)


# --- Тесты -------------------------------------------------------------------------------------------------------

def test_f09_personal_addressee_gets_record_for_you_on_bell_with_author_and_snippet_up_to_100_chars(
        admin_page, employee, new_context):
    """Сценарий 9, п. 1: запись адресована Петрову лично — на портале «Запись для вас» с автором и отрывком текста до 100
    знаков (FR-629, FR-631)."""
    mark = _uid()
    writer, petrov = _writer(admin_page, employee), _person(employee, "Петров", mark)
    head = f"заявка{mark}"
    tail = "хвостовоеслово"
    text = f"{head} {_words('слово', 260)} {tail}"
    watcher = helpers_notify.open_watcher(new_context, petrov, spy=False)
    base = helpers_feed.bell(watcher)
    page = helpers_feed.open_feed(new_context(), writer)
    # п. 1: публикация лично Петрову
    helpers_feed.publish(page, text, to=[("person", petrov.full_name)])
    helpers_feed.wait_bell(watcher, base + 1, timeout=15_000)
    rows = _wait_rows(watcher, head)
    expect(rows).to_have_count(1)
    expect(rows.first.locator('[data-field="kind"]')).to_have_text("Запись для вас")
    row_text = _row_text(rows.first)
    # п. 1: автор и отрывок до 100 знаков (по шаблону «<ФИО>: запись для вас — «<отрывок>»»)
    assert row_text.startswith(f"{writer.full_name}: запись для вас — «"), row_text
    snippet = row_text.split("«", 1)[1].rsplit("»", 1)[0]
    assert head in snippet and tail not in row_text, row_text
    assert len(snippet) <= 100, f"отрывок {len(snippet)} знаков (предел 100, «…» входит)"
    assert snippet.endswith("…"), "длинный текст обрезан без «…»"
    assert _norm(text) not in row_text


def test_f09_plain_post_to_all_or_unit_without_mentions_gives_no_notification_and_raises_feed_menu_count(
        admin_page, employee, new_context):
    """Сценарий 9, п. 2: обычная запись «Всем» или подразделению без упоминаний — уведомлений нет, новое видно по числу у
    пункта «Лента» (FR-626, FR-629)."""
    mark = _uid()
    writer, member = _writer(admin_page, employee), _person(employee, "Итов", mark)
    _unit_id, unit_name = _unit(admin_page, "Отдел ИТ", [member], mark)
    tab = helpers_feed.open_feed(new_context(), member)
    bell_base, badge_base = helpers_feed.bell(tab), helpers_feed.badge(tab)
    page = helpers_feed.open_feed(new_context(), writer)
    all_word, unit_word = f"всем{mark}", f"узлу{mark}"
    # п. 2: запись «Всем» и запись подразделению
    helpers_feed.publish(page, f"Объявление {all_word}")
    helpers_feed.publish(page, f"Объявление {unit_word}", to=[("unit", unit_name)])
    # п. 2: новое видно по числу у «Ленты»
    helpers_feed.wait_badge(tab, badge_base + 2, timeout=15_000)
    # п. 2: уведомлений нет — ни на колокольчике, ни в списке
    assert helpers_feed.bell(tab) == bell_base
    texts = " ".join(helpers_feed.my_notifications(tab))
    assert all_word not in texts and unit_word not in texts, "об обычной записи пришло уведомление"


def test_f09_mention_sends_telegram_only_mentioned_in_feed_text_and_link_without_name_title_or_snippet(
        admin_page, employee, new_context):
    """Сценарий 9, п. 3 (Telegram): упомянутому в Telegram уходит только «Вас упомянули в ленте» и ссылка, без ФИО, названий
    и текста (FR-631, NFR-609)."""
    mark = _uid()
    writer, petrov = _writer(admin_page, employee), _person(employee, "Петров", mark)
    bots, chat = helpers_feed.fakebots(), _chat_id()
    word = f"совещание{mark}"
    with helpers_notify.channels_on(admin_page, "telegram"):
        # дано: Telegram привязан, ячейка «Вас упомянули» включена, тихих часов нет
        helpers_notify.bind_channel(petrov.page, bots, "telegram", chat)
        _save_prefs(petrov.page, cells={(MENTION, "telegram"): True}, quiet="none")
        page = helpers_feed.open_feed(new_context(), writer)
        # когда: Петрова упомянули
        helpers_feed.publish(page, f"Просьба прийти на {word}", mentions=[petrov.full_name])
        found = helpers_notify.wait_sent(bots, "telegram", chat_id=chat, text_has=EXTERNAL_MENTION)
    assert len(found) == 1, f"сообщений «{EXTERNAL_MENTION}» в свой чат: {len(found)}"
    message = found[0]
    assert message["text"] == EXTERNAL_MENTION
    # п. 3: ни ФИО, ни текста записи нигде в сообщении (ни в тексте, ни в кнопке)
    dump = json.dumps(message, ensure_ascii=False)
    for forbidden in (writer.full_name, petrov.full_name, word, "Просьба", writer.email, petrov.email):
        assert forbidden not in dump, "во внешнем сообщении есть данные записи"
    # п. 3: ссылка — страница уведомлений портала
    assert urlsplit(_button_url(message)).path == "/notifications/"


def test_f09_mention_mail_comes_after_unread_term_with_author_and_snippet_and_not_if_read_before_term(
        admin_page, employee, new_context, mailpit):
    """Сценарий 9, п. 3 (почта): письмо об упоминании уходит, только если уведомление не прочитано за срок (SPEC-004
    FR-327), и в нём автор и отрывок; прочитавшему до срока письма нет (FR-631)."""
    mark = _uid()
    writer = _writer(admin_page, employee)
    unread, reader = _person(employee, "Петров", mark), _person(employee, "Сидоров", mark)
    word = f"отчёт{mark}"
    for account in (unread, reader):
        _save_prefs(account.page, cells={(MENTION, "email"): True}, quiet="none")
    seen_unread, seen_reader = _mail_ids(mailpit, unread.email), _mail_ids(mailpit, reader.email)
    page = helpers_feed.open_feed(new_context(), writer)
    helpers_feed.publish(page, f"Прошу подготовить {word}", mentions=[unread.full_name, reader.full_name])
    # п. 3: оба получили уведомление на портале; второй прочитал его до срока
    _wait_rows(unread.page, word)
    rows = _wait_rows(reader.page, word)
    rows.first.locator('form[data-form="read"] button[data-action="read"]').click()
    expect(rows.first).to_have_attribute("data-unread", "0")
    # до срока письма нет
    assert helpers_feed.no_feed_mail(mailpit, unread.email, seen=seen_unread, wait=3), "письмо ушло до срока"
    # когда: срок прошёл
    helpers_feed.tick_mail()
    mail = helpers_feed.feed_mail(mailpit, unread.email, seen=seen_unread, timeout=MAIL_WAIT)
    # п. 3: в письме автор и отрывок
    assert writer.full_name in mail["Text"] and word in mail["Text"], "в письме нет автора или отрывка"
    # п. 3: прочитавшему до срока письма нет (после положительного контроля выше)
    assert helpers_feed.no_feed_mail(mailpit, reader.email, seen=seen_reader, wait=6), "письмо прочитавшему"


def test_f09_event_invite_and_event_changed_telegram_messages_have_no_event_title_place_or_name(
        admin_page, employee, new_context):
    """Сценарий 9, п. 3 (события): «Приглашение на событие» и «Событие изменено» в Telegram — только внешний текст и ссылка,
    без названия, места и ФИО (FR-631, NFR-609)."""
    mark = _uid()
    writer, petrov = _writer(admin_page, employee), _person(employee, "Петров", mark)
    bots, chat = helpers_feed.fakebots(), _chat_id()
    title, place = f"Учения{mark}", f"Корпус{mark}"
    with helpers_notify.channels_on(admin_page, "telegram"):
        helpers_notify.bind_channel(petrov.page, bots, "telegram", chat)
        _save_prefs(petrov.page, cells={(INVITE, "telegram"): True, (EVENT_CHANGED, "telegram"): True}, quiet="none")
        page = helpers_feed.open_feed(new_context(), writer)
        start = _future(2)
        post_id = helpers_feed.publish(
            page, "", kind="event", to=[("person", petrov.full_name)],
            event={"title": title, "place": place, "start": start, "end": start + timedelta(hours=2)})
        invite = helpers_notify.wait_sent(bots, "telegram", chat_id=chat, text_has=EXTERNAL_INVITE)
        # когда: автор меняет место события
        _edit_post(page, post_id, event_place=f"Зал{mark}")
        changed = helpers_notify.wait_sent(bots, "telegram", chat_id=chat, text_has=EXTERNAL_CHANGED)
    assert len(invite) == 1 and len(changed) == 1
    for message, text in ((invite[0], EXTERNAL_INVITE), (changed[0], EXTERNAL_CHANGED)):
        assert message["text"] == text
        dump = json.dumps(message, ensure_ascii=False)
        for forbidden in (title, place, f"Зал{mark}", writer.full_name, petrov.full_name):
            assert forbidden not in dump, f"в сообщении «{text}» есть данные события"
        assert urlsplit(_button_url(message)).path == "/notifications/"


@helpers_notify.webpush_only
def test_f09_my_notifications_shows_feed_section_with_eight_kinds_and_employee_toggles_mail_push_telegram_max(
        admin_page, employee, webpush_context):
    """Сценарий 9, п. 4: «Мои уведомления» — раздел «Лента» с восемью видами; почту, «Push в браузере», Telegram и MAX
    каждого вида, кроме «Нравится», сотрудник включает и выключает сам (FR-629, FR-631). Push — в постоянном профиле
    `webpush_context` по образцу test_e05_webpush (в кругах firefox и yandex тест снимается со сбора меткой `webpush`)."""
    member = employee(full_name=f"Простов{_uid()} Иван Иванович")
    bots = helpers_feed.fakebots()
    toggled = ("email", "push", "telegram", "max")
    with helpers_notify.channels_on(admin_page, "webpush", "telegram", "max"):
        context = webpush_context()
        helpers_notify.adopt_session(context, member)
        helpers_notify.grant_notifications(context)
        page = context.new_page()
        helpers_notify.enable_push_on_device(page)  # подписка устройства: столбец push становится доступным
        helpers_notify.bind_channel(page, bots, "telegram", _chat_id())
        helpers_notify.bind_channel(page, bots, "max", _chat_id())
        page.goto("/me/notifications/")
        table = page.locator("table[data-notify-table]")
        rows = table.locator('tr[data-notify-kind^="feed."]')
        # п. 4: восемь видов раздела «Лента» в порядке каталога
        expect(rows).to_have_count(8)
        assert rows.evaluate_all("els => els.map(e => e.dataset.notifyKind)") == list(FEED_KINDS)
        for code in FEED_KINDS:
            row = table.locator(f'tr[data-notify-kind="{code}"]')
            expect(row.locator('[data-field="module"]')).to_have_text("Лента")
            expect(row.locator("td[data-channel]")).to_have_count(5)
        # п. 4: сотрудник сам меняет «Почту», «Push в браузере», Telegram и MAX у каждого вида, кроме «Нравится»
        kinds = [code for code in FEED_KINDS if code != LIKE]
        before = {(code, ch): _cell(page, code, ch).is_checked() for code in kinds for ch in toggled}
        for flip in (True, False):
            wanted = {pair: (not state) if flip else state for pair, state in before.items()}
            _save_prefs(page, cells=wanted)
            page.goto("/me/notifications/")
            for (code, ch), state in wanted.items():
                expect(_cell(page, code, ch)).to_be_checked(checked=state)


def test_f09_like_kind_has_only_portal_channel_in_employee_table_and_in_admin_defaults(admin_page, employee):
    """Сценарий 9, п. 4 («Нравится»): единственный канал — «На портале»; других каналов нет ни в таблице сотрудника, ни в
    значениях по умолчанию у администратора (FR-629, FR-631)."""
    member = employee(full_name=f"Простов{_uid()} Иван Иванович")
    member.page.goto("/me/notifications/")
    row = member.page.locator(f'table[data-notify-table] tr[data-notify-kind="{LIKE}"]')
    expect(row).to_have_count(1)
    # п. 4: у сотрудника — «На портале» есть, внешних ячеек с флажком нет
    expect(row.locator('td[data-channel="portal"] input[type=checkbox]')).to_have_count(1)
    expect(row.locator('td[data-channel]:not([data-channel="portal"]) input[type=checkbox]')).to_have_count(0)
    # контроль: у вида «Вас упомянули» почта настраивается
    expect(_cell(member.page, MENTION, "email")).to_have_count(1)
    # п. 4: у администратора в значениях по умолчанию — внешних ячеек вида «Нравится» нет
    admin_page.goto("/settings/notifications/")
    defaults = admin_page.locator("table[data-defaults-table]")
    expect(defaults).to_be_visible()
    like = defaults.locator(f'tr[data-notify-kind="{LIKE}"]')
    expect(like).to_have_count(1)
    expect(like.locator("td[data-channel] input[type=checkbox]")).to_have_count(0)
    mention = defaults.locator(f'tr[data-notify-kind="{MENTION}"] td[data-channel="email"] input[type=checkbox]')
    expect(mention).to_have_count(1)


def test_f09_post_deleted_by_author_or_moderator_after_notification_sends_no_delayed_mail_and_bell_link_gives_not_found(
        admin_page, employee, new_context, mailpit):
    """Сценарий 9, п. 5 (удаление автором и модератором): после удаления записи отложенное письмо не уходит; уведомление на
    портале остаётся, ссылка отвечает как на несуществующую запись (FR-630, FR-632)."""
    mark = _uid()
    writer, moderator = _writer(admin_page, employee), _moderator(admin_page, employee)
    petrov = _person(employee, "Петров", mark)
    _save_prefs(petrov.page, quiet="none")
    seen = _mail_ids(mailpit, petrov.email)
    page = helpers_feed.open_feed(new_context(), writer)
    by_author, by_moderator, kept = f"автор{mark}", f"модер{mark}", f"остаётся{mark}"
    first = helpers_feed.publish(page, f"Лично {by_author}", to=[("person", petrov.full_name)])
    second = helpers_feed.publish(page, f"Всем {by_moderator}", mentions=[petrov.full_name])
    helpers_feed.publish(page, f"Лично {kept}", to=[("person", petrov.full_name)])
    for word in (by_author, by_moderator, kept):
        _wait_rows(petrov.page, word)
    # когда: автор и модератор удаляют записи после создания уведомлений
    _delete_post(page, first)
    mod_page = helpers_feed.open_feed(new_context(), moderator)
    _delete_post(mod_page, second)
    helpers_feed.tick_mail()
    # контроль: письмо о неудалённой записи пришло, и оно единственное
    mail = helpers_feed.feed_mail(mailpit, petrov.email, seen=seen, timeout=MAIL_WAIT)
    assert kept in mail["Text"]
    assert helpers_feed.no_feed_mail(mailpit, petrov.email, seen=seen | {mail["ID"]}, wait=6), "письмо об удалённой"
    assert by_author not in mail["Text"] and by_moderator not in mail["Text"]
    # п. 5: уведомления на портале остались, ссылки — «не найдено»
    for word in (by_author, by_moderator):
        rows = _wait_rows(petrov.page, word)
        expect(rows).to_have_count(1)
        assert _status_of(petrov.page, _link(rows.first)) == 404, f"ссылка уведомления о {word}"


def test_f09_post_purged_by_retention_keeps_bell_notification_and_its_link_gives_not_found(
        admin_page, employee, new_context, mailpit):
    """Сценарий 9, п. 5 (срок хранения): запись удалена ночным заданием — уведомление на портале остаётся, ссылка отвечает
    как на несуществующую запись, письмо не уходит (FR-630, FR-632)."""
    mark = _uid()
    writer, petrov = _writer(admin_page, employee), _person(employee, "Петров", mark)
    _save_prefs(petrov.page, quiet="none")
    seen = _mail_ids(mailpit, petrov.email)
    page = helpers_feed.open_feed(new_context(), writer)
    word = f"срок{mark}"
    post_id = helpers_feed.publish(page, f"Лично {word}", to=[("person", petrov.full_name)])
    _wait_rows(petrov.page, word)
    # когда: запись состарена сверх срока хранения (по умолчанию 3 года) и ночное задание выполнено — только эта запись
    result = helpers_feed.age(1500, posts=[post_id])
    assert result["deleted"] >= 1, result
    helpers_feed.tick_mail()
    assert helpers_feed.no_feed_mail(mailpit, petrov.email, seen=seen, wait=8), "письмо о стёртой записи"
    rows = _wait_rows(petrov.page, word)
    expect(rows).to_have_count(1)
    assert _status_of(petrov.page, _link(rows.first)) == 404


def test_f09_link_from_already_sent_mail_of_deleted_post_gives_not_found(
        admin_page, employee, new_context, mailpit):
    """Сценарий 9, п. 5 (письмо уже ушло): ссылка из отправленного письма о позже удалённой записи отвечает как на
    несуществующую запись (FR-630, FR-632)."""
    mark = _uid()
    writer, petrov = _writer(admin_page, employee), _person(employee, "Петров", mark)
    _save_prefs(petrov.page, quiet="none")
    seen = _mail_ids(mailpit, petrov.email)
    page = helpers_feed.open_feed(new_context(), writer)
    word = f"письмо{mark}"
    post_id = helpers_feed.publish(page, f"Лично {word}", to=[("person", petrov.full_name)])
    _wait_rows(petrov.page, word)
    helpers_feed.tick_mail()
    mail = helpers_feed.feed_mail(mailpit, petrov.email, seen=seen, timeout=MAIL_WAIT)
    link = helpers_notify.open_link_in(mail)
    # контроль: пока запись есть, ссылка открывает её
    assert petrov.page.goto(link).status == 200
    expect(petrov.page.locator(f"#feed-post-{post_id}")).to_be_visible()
    # когда: запись удалена после отправки письма
    _delete_post(page, post_id)
    # п. 5: ссылка из письма — как на несуществующую запись
    assert _status_of(petrov.page, link) == 404


def test_f09_important_personal_post_with_mention_gives_single_mentioned_notification(
        admin_page, employee, new_context):
    """Сценарий 9, п. 6: важная запись с упоминанием Петрова, адресованная ему лично, — одно уведомление «Вас упомянули», а
    не три (FR-630)."""
    mark = _uid()
    writer, petrov = _writer(admin_page, employee), _person(employee, "Петров", mark)
    watcher = helpers_notify.open_watcher(new_context, petrov, spy=False)
    base = helpers_feed.bell(watcher)
    page = helpers_feed.open_feed(new_context(), writer)
    word, control = f"важное{mark}", f"контроль{mark}"
    helpers_feed.publish(page, f"Срочно {word}", kind="important", term="day", to=[("person", petrov.full_name)],
                         mentions=[petrov.full_name])
    # контроль того же пути: следующая запись лично Петрову приходит после первой (очередь одна)
    helpers_feed.publish(page, f"Лично {control}", to=[("person", petrov.full_name)])
    helpers_feed.wait_bell(watcher, base + 2, timeout=15_000)
    _wait_rows(watcher, control)
    rows = _rows(watcher, word)
    # п. 6: ровно одно уведомление, и оно — «Вас упомянули»
    expect(rows).to_have_count(1)
    expect(rows.first.locator('[data-field="kind"]')).to_have_text("Вас упомянули")
    assert helpers_feed.bell(watcher) == base + 2


def test_f09_author_mentioning_or_addressing_self_gets_no_notification(admin_page, employee, new_context):
    """Сценарий 9 (FR-630): автор, упомянувший или адресовавший запись самому себе, уведомления не получает."""
    mark = _uid()
    writer = _writer(admin_page, employee)
    petrov = _person(employee, "Петров", mark)
    own_tab = helpers_notify.open_watcher(new_context, writer, spy=False)
    base = helpers_feed.bell(own_tab)
    page = helpers_feed.open_feed(new_context(), writer)
    word = f"себе{mark}"
    # автор адресует запись себе и Петрову и упоминает себя
    helpers_feed.publish(page, f"Заметка {word}", to=[("person", writer.full_name), ("person", petrov.full_name)],
                         mentions=[writer.full_name])
    # контроль: Петров получил «Запись для вас»
    rows = _wait_rows(petrov.page, word)
    expect(rows).to_have_count(1)
    # автору уведомления нет
    assert helpers_feed.bell(own_tab) == base
    assert word not in " ".join(helpers_feed.my_notifications(own_tab)), "автор получил уведомление о своей записи"


def test_f09_mention_in_quiet_hours_shows_on_portal_at_once_and_mail_and_telegram_wait_for_digest(
        admin_page, employee, new_context, mailpit):
    """Сценарий 9, п. 7: тихие часы сотрудника — на портале уведомление видно сразу, письмо и сообщение в Telegram копятся
    до сводки (FR-631)."""
    mark = _uid()
    writer, petrov = _writer(admin_page, employee), _person(employee, "Петров", mark)
    bots, chat = helpers_feed.fakebots(), _chat_id()
    word = f"ночью{mark}"
    with helpers_notify.channels_on(admin_page, "telegram"):
        helpers_notify.bind_channel(petrov.page, bots, "telegram", chat)
        # дано: «Свои часы» в окне, не включающем текущее время; «Вас упомянули» — почта и Telegram
        start, end = _hours(3, 4)
        _save_prefs(petrov.page, cells={(MENTION, "email"): True, (MENTION, "telegram"): True},
                    quiet="own", start=start, end=end)
        seen = _mail_ids(mailpit, petrov.email)
        known = len(helpers_notify.sent_to(bots, "telegram", chat))
        watcher = helpers_notify.open_watcher(new_context, petrov, spy=False)
        base = helpers_feed.bell(watcher)
        page = helpers_feed.open_feed(new_context(), writer)
        helpers_feed.publish(page, f"Просьба {word}", mentions=[petrov.full_name])
        # п. 7: на портале видно сразу
        helpers_feed.wait_bell(watcher, base + 1, timeout=15_000)
        _wait_rows(watcher, word)
        # письма и сообщения нет, даже когда срок письма прошёл
        helpers_feed.tick_mail()
        assert helpers_feed.no_feed_mail(mailpit, petrov.email, seen=seen, wait=6), "письмо в тихие часы"
        assert len(helpers_notify.sent_to(bots, "telegram", chat)) == known, "сообщение в Telegram в тихие часы"
        # когда: рабочее время (режим «Без тихих часов») — сводка
        _save_prefs(petrov.page, quiet="none")
        helpers_notify.tick()
        mail = helpers_notify.wait_digest_mail(mailpit, petrov.email, timeout=MAIL_WAIT)
        assert mail["Subject"] == "За нерабочее время: 1 уведомление", mail["Subject"]
        helpers_notify.wait_sent(bots, "telegram", chat_id=chat, text_has="У вас 1 новое уведомление", timeout=MAIL_WAIT)


def test_f09_employee_moved_out_of_addressee_unit_gets_no_mail_and_notification_link_gives_not_found(
        admin_page, employee, new_context, mailpit):
    """Сценарий 9, п. 8: сотрудник ушёл из подразделения-адресата — письмо не уходит, ссылка уведомления отвечает как на
    несуществующую запись (FR-630)."""
    mark = _uid()
    writer = _writer(admin_page, employee)
    leaver, stayer = _person(employee, "Уходов", mark), _person(employee, "Остапов", mark)
    unit_id, unit_name = _unit(admin_page, "Отдел ИТ", [leaver, stayer], mark)
    _other_id, _other_name = _unit(admin_page, "Группа сети", [leaver], mark)
    for account in (leaver, stayer):
        _save_prefs(account.page, quiet="none")
    seen_leaver, seen_stayer = _mail_ids(mailpit, leaver.email), _mail_ids(mailpit, stayer.email)
    page = helpers_feed.open_feed(new_context(), writer)
    word = f"отдел{mark}"
    # видимость — только через подразделение (без упоминаний); «Важная запись» уведомляет адресатов, письмо включено по умолчанию
    helpers_feed.publish(page, f"Для отдела {word}", kind="important", term="week", to=[("unit", unit_name)])
    _wait_rows(stayer.page, word)
    rows = _wait_rows(leaver.page, word)
    link = _link(rows.first)
    # когда: сотрудник перестал состоять в подразделении-адресате (остаётся в другом узле)
    helpers_org.open_structure(admin_page, unit_id)
    helpers_org.remove_member(admin_page, leaver.id)
    expect(helpers_org.member_row(admin_page, leaver.id)).to_have_count(0)
    helpers_feed.tick_mail()
    # контроль: оставшийся сотрудник письмо получил
    mail = helpers_feed.feed_mail(mailpit, stayer.email, seen=seen_stayer, timeout=MAIL_WAIT)
    assert word in mail["Text"]
    # п. 8: ушедшему письма нет, ссылка — «не найдено»
    assert helpers_feed.no_feed_mail(mailpit, leaver.email, seen=seen_leaver, wait=6), "письмо ушедшему"
    assert _status_of(leaver.page, link) == 404


def test_f09_event_changed_notification_cuts_200_char_title_and_place_to_60_and_whole_text_to_300(
        admin_page, employee, new_context):
    """Сценарий 9, п. 9: событие с названием и местом по 200 знаков — в «Событие изменено» название и место обрезаны до 60
    знаков, весь текст не длиннее 300 знаков (FR-629, FR-631)."""
    mark = _uid()
    writer, petrov = _writer(admin_page, employee), _person(employee, "Петров", mark)
    watcher = helpers_notify.open_watcher(new_context, petrov, spy=False)
    page = helpers_feed.open_feed(new_context(), writer)
    title, place = _words("назв", 200), _words("мест", 200)
    new_place = _words("зал", 200)
    assert len(title) == len(place) == len(new_place) == 200
    start = _future(3)
    post_id = helpers_feed.publish(
        page, "", kind="event", to=[("person", petrov.full_name)],
        event={"title": title, "place": place, "start": start, "end": start + timedelta(hours=2)})
    _wait_rows(watcher, "приглашает")
    # когда: участникам уходит «Событие изменено» (новое место)
    _edit_post(page, post_id, event_place=new_place)
    rows = _wait_rows(watcher, "изменено")
    expect(rows).to_have_count(1)
    text = _row_text(rows.first)
    # п. 9: название и место обрезаны до 60 знаков, весь текст не длиннее 300
    assert text.startswith("Событие «") and " изменено: " in text, text
    assert title not in text and new_place not in text, "название или место не обрезаны"
    assert title[:30] in text and new_place[:30] in text, "в тексте нет начала названия или нового места"
    assert len(text) <= 300, f"текст уведомления {len(text)} знаков"
    quoted = re.search(r"«(.*)» изменено", text).group(1)
    assert len(quoted) <= 60, f"название в тексте {len(quoted)} знаков (предел 60, «…» входит)"
