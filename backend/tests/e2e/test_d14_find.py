"""T-3151: сценарий 14 — исполнитель находит заявку: пресеты, поиск, фильтр, сортировки, счётчик меню, пустой
пресет, узкое окно, ссылка в карточке сотрудника, «последнее сообщение», колонки сетки (FR-248, FR-276…FR-282,
NFR-208)."""
import re
import secrets
import urllib.parse
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_servicedesk import build_mail

MSK = ZoneInfo("Europe/Moscow")
CONSONANTS = "бвгджзклмнпрстфхцчш"  # суффикс без гласных: основа слова не меняется стеммером поиска
GRID_ROWS = "#tickets-grid tr[data-ticket]"


# --- Свои помощники файла ------------------------------------------------------------------------

def _word() -> str:
    """Уникальное слово темы по доп. 41 (в): буква и шесть шестнадцатеричных знаков, не из одних цифр."""
    return f"t{secrets.token_hex(3)}"


def _cyr(size: int = 6) -> str:
    """Случайная строка из согласных кириллицы: уникальный «хвост» слова с «ё»/«е» для поиска (6.21)."""
    return "".join(secrets.choice(CONSONANTS) for _ in range(size))


def _lat(size: int = 6) -> str:
    """Случайная строка латинских букв (начало местной части адреса — не из цифр, доп. 41 (в))."""
    return "".join(secrets.choice("bcdfghklmnpqrtvwxz") for _ in range(size))


def _mail(sender: str, subject: str, text: str = "Обычный текст заявки") -> bytes:
    return build_mail(from_addr=sender, to=[MAILBOX], subject=subject, text=text,
                      message_id=f"<{secrets.token_hex(8)}@client.test>")


def _deliver_all(raws: list) -> None:
    """Кладёт все письма в ящик и разбирает их одним `poll_now()` (одна команда стенда вместо нескольких)."""
    for raw in raws:
        helpers_sd.append_mail(raw)
    helpers_sd.poll_now()


def _numbers(page) -> list:
    """Номера строк сетки в порядке на странице."""
    return [int(v) for v in page.locator(GRID_ROWS).evaluate_all("els => els.map(e => e.dataset.ticket)")]


def _open_list(page, **params) -> None:
    page.goto("/tickets/?" + urllib.parse.urlencode(params))
    expect(page.locator("[data-tickets-list]")).to_be_visible()


def _list(page, count: int, **params) -> list:
    """Список `/tickets/` с параметрами; ждёт ровно `count` строк (0 — пустое состояние), возвращает номера."""
    _open_list(page, **params)
    if count == 0:
        expect(page.locator('[data-empty-state="tickets"]')).to_be_visible()
        expect(page.locator(GRID_ROWS)).to_have_count(0)
        return []
    expect(page.locator(GRID_ROWS)).to_have_count(count)
    return _numbers(page)


def _found(page, query: str) -> list:
    """Номера заявок первой страницы по поиску `q` (пресет «Все»); без ожидания числа строк."""
    _open_list(page, preset="all", q=query)
    return _numbers(page)


def _pick(select, text: str) -> str:
    """Выбирает пункт `select`, текст которого равен `text` (иначе содержит его, без учёта регистра); возвращает
    значение пункта. Подписи могут нести метки («по умолчанию», «в архиве»), поэтому точное `label=` не берём."""
    options = [(o.get_attribute("value"), (o.text_content() or "").strip()) for o in select.locator("option").all()]
    for value, label in options:
        if label.lower() == text.lower():
            select.select_option(value=value)
            return value
    for value, label in options:
        if text.lower() in label.lower():
            select.select_option(value=value)
            return value
    raise AssertionError(f"в выборе нет пункта «{text}»: {[label for _, label in options]}")


def _option_value(page, name: str, text: str) -> str:
    """Значение пункта выбора фильтра `#tickets-filter select[name=<name>]` (страница списка уже открыта)."""
    for option in page.locator(f'#tickets-filter select[name="{name}"] option').all():
        label = (option.text_content() or "").strip()
        if label.lower() == text.lower() or text.lower() in label.lower():
            return option.get_attribute("value")
    raise AssertionError(f"в фильтре «{name}» нет пункта «{text}»")


def _at(locator) -> datetime:
    """Время элемента из `time[data-at]` (13.4: `date:'c'`, ISO 8601 по Москве)."""
    return datetime.fromisoformat(locator.get_attribute("data-at"))


def _date(day) -> str:
    """Дата для параметров `created_from`/`created_to` — `ДД.ММ.ГГГГ` (12.2)."""
    return day.strftime("%d.%m.%Y")


def _take(page, number: int):
    """Нажимает «Взять себе» в карточке и ждёт, пока у поля ответственного исчезнет «не назначен»."""
    card = helpers_sd.open_ticket(page, number)
    card.locator('form[data-form="ticket-take"] button[data-action="ticket-take"]').click()
    expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "false")
    return card


def _reply(page, number: int, text: str, *, wait: bool = False):
    card = helpers_sd.open_ticket(page, number)
    form = card.locator('form[data-form="ticket-reply"]')
    form.locator("textarea[name=text]").fill(text)
    if wait:
        form.locator("input[name=wait]").check()
    form.locator("button[type=submit]").click()
    expect(card.locator('ol[data-feed] li[data-kind="reply"]')).to_have_count(1)
    return card


def _close(page, number: int):
    card = helpers_sd.open_ticket(page, number)
    card.locator('a[data-action="ticket-close"]').click()
    dialog = page.locator('#dialog-root [data-dialog="ticket-close"]')
    expect(dialog).to_be_visible()
    dialog.locator("textarea[name=resolution]").fill("Решено, проверено")
    dialog.locator("button[type=submit]").click()
    expect(card).to_have_attribute("data-kind", "closed")
    return card


def _set_fields(page, number: int, *, priority: str | None = None, client_unit: str | None = None) -> None:
    """Правка критичности и подразделения заявки формой `ticket-fields` (13.3, доп. 41 (г))."""
    card = helpers_sd.open_ticket(page, number)
    form = card.locator('form[data-form="ticket-fields"]')
    if priority is not None:
        _pick(form.locator("select[name=priority]"), priority)
    if client_unit is not None:
        _pick(form.locator("select[name=client_unit]"), client_unit)
    form.locator('button[type=submit]:not([name="save_to_record"])').click()
    if priority is not None:
        expect(card.locator('[data-field="priority"]')).to_contain_text(priority)
    if client_unit is not None:
        expect(card.locator('[data-field="client-unit"]')).to_contain_text(client_unit)


def _set_status(page, number: int, status: str, kind: str) -> None:
    card = helpers_sd.open_ticket(page, number)
    form = card.locator('form[data-form="ticket-status"]')
    _pick(form.locator("select[name=status]"), status)
    form.locator("button[type=submit]").click()
    expect(card).to_have_attribute("data-kind", kind)


def _change_category(page, number: int, category: str, queue_name: str) -> None:
    """Смена категории на категорию другой очереди: подтверждение в диалоге (13.3), затем очередь заявки меняется."""
    card = helpers_sd.open_ticket(page, number)
    form = card.locator('form[data-form="ticket-category"]')
    _pick(form.locator("select[name=category]"), category)
    form.locator("button[type=submit]").click()
    dialog = page.locator('#dialog-root [data-dialog="ticket-category"]')
    expect(dialog).to_be_visible()
    dialog.locator("button[type=submit]").click()
    expect(card.locator('[data-field="queue"]')).to_contain_text(queue_name)
    expect(card.locator('[data-field="category"]')).to_contain_text(category)


def _transfer(page, number: int, queue_id: str, queue_name: str) -> None:
    card = helpers_sd.open_ticket(page, number)
    card.locator('a[data-action="ticket-transfer"]').click()
    dialog = page.locator('#dialog-root [data-dialog="ticket-transfer"]')
    expect(dialog).to_be_visible()
    dialog.locator("select[name=queue]").select_option(value=str(queue_id))
    dialog.locator("button[type=submit]").click()
    expect(card.locator('[data-field="queue"]')).to_contain_text(queue_name)


def _create_value(page, kind: str, name: str, *, queue_id=None) -> None:
    """Новое значение справочника формой `/servicedesk/dictionaries/<вид>/new/` (12.6): категория или подразделение."""
    page.goto(f"/servicedesk/dictionaries/{kind}/new/")
    form = page.locator('form[data-form="dictionary"]')
    expect(form).to_be_visible()
    form.locator("input[name=name]").fill(name)
    order = form.locator("input[name=order]")  # у подразделений поля нет; у категорий — целое (доп. 42 (г))
    if order.count() and not order.input_value():
        order.fill("50")
    if queue_id is not None:
        form.locator("select[name=queue]").select_option(value=str(queue_id))
    form.locator("button[type=submit]").click()
    expect(page).to_have_url(re.compile(rf"/servicedesk/dictionaries/{kind}/$"))


def _executor_ticket(page, *, queue_id: str, subject: str, priority: str, source: str) -> int:
    """Заявка от исполнителя (12.3, 13.6): `/tickets/new/`, категория «Другое» (очередь по умолчанию), без «Взять
    себе» (флажок включён по умолчанию — снимаем). Возвращает номер из адреса карточки (302 на `/tickets/<N>/`)."""
    page.goto("/tickets/new/")
    form = page.locator('form[data-form="ticket-new"]')
    expect(form).to_be_visible()
    with page.expect_response(lambda r: "/tickets/new/requester/" in r.url):  # подстановка по `change` (доп. 26)
        form.locator("input[name=email]").fill(helpers_sd.requester_email())
        form.locator("input[name=email]").press("Tab")
    with page.expect_response(lambda r: "/tickets/new/queue/" in r.url):
        _pick(form.locator("select[name=category]"), "Другое")
    expect(form.locator("[data-queue-fields] select[name=queue]")).to_have_value(str(queue_id))
    _pick(form.locator("select[name=priority]"), priority)
    _pick(form.locator("select[name=source]"), source)
    form.locator("input[name=subject]").fill(subject)
    form.locator("textarea[name=text]").fill("Звонок: обращение принято по телефону")
    form.locator("input[name=take]").uncheck()
    form.locator("button[type=submit]").click()
    expect(page).to_have_url(re.compile(r"/tickets/\d+/$"))
    return int(re.search(r"/tickets/(\d+)/", page.url).group(1))


# --- Сценарий 14 ----------------------------------------------------------------------------------

def test_d14_preset_switch_updates_only_grid_filter_panel_stays(admin_page):
    """Сценарий 14, п. 1: пресеты «Мои», «Без ответственного», «Мои очереди», «Ждут ответа заявителя», «Закрытые»,
    «Все» — переключение запрашивает только сетку (`HX-Target: tickets-grid`), адрес получает `preset=…`, панель
    фильтра остаётся тем же элементом, а в сетке — заявки именно этого пресета (FR-276)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    words = {key: _word() for key in "abcd"}
    _deliver_all([_mail(helpers_sd.requester_email(), f"Пресет {key} {word}") for key, word in words.items()])
    number = {key: helpers_sd.ticket_number_by_subject(page, word) for key, word in words.items()}
    # дано: a — без ответственного (новая); b — взята мной; c — ответ с «ждём ответа»; d — закрыта
    _take(page, number["b"])
    card = _reply(page, number["c"], "Уточните, пожалуйста, модель принтера", wait=True)
    expect(card).to_have_attribute("data-kind", "waiting")
    _close(page, number["d"])
    a, b, c, d = (number[key] for key in "abcd")
    # пресет → (свои заявки, которые в нём есть; свои, которых нет): «Мои» — открытые, где я ответственный;
    # «Без ответственного» и «Мои очереди» — открытые очередей (ждущая тоже открыта); «Закрытые» — вид closed
    expected = {
        "mine": ({b}, {a, c, d}),
        "unassigned": ({a, c}, {b, d}),
        "my_queues": ({a, b, c}, {d}),
        "waiting": ({c}, {a, b, d}),
        "closed": ({d}, {a, b, c}),
        "all": ({a, b, c, d}, set()),
    }
    # когда: пользователь открывает список и переключает пресеты ссылками панели
    page.goto("/tickets/?preset=all")
    expect(page.locator("[data-tickets-list]")).to_be_visible()
    panel = page.locator("details[data-filter-panel]")
    if panel.get_attribute("open") is None:  # панель свёрнута — раскрываем, чтобы набрать текст
        panel.locator("summary").first.click()
    filter_input = page.locator("#tickets-filter input[name=q]")
    filter_input.fill("несохранённый текст")  # набранное в панели не должно пропасть при смене сетки
    panel_before = panel.element_handle()
    page.evaluate("window.__d14_marker = 'alive'")  # полная перезагрузка страницы сбросила бы метку
    for code, (present, absent) in expected.items():
        link = page.locator(f'nav[data-presets] a[data-preset="{code}"]')
        with page.expect_response(lambda r, c=code: "/tickets/" in r.url and f"preset={c}" in r.url) as info:
            link.click()
        # тогда: запрос НХ с целью сетки, адрес с пресетом, панель — тот же элемент, страница не перезагружалась
        assert info.value.request.header_value("hx-target") == "tickets-grid", code
        expect(page).to_have_url(re.compile(rf"preset={code}(&|$)"))
        for n in present:
            expect(page.locator(f'#tickets-grid tr[data-ticket="{n}"]')).to_have_count(1)
        for n in absent:
            expect(page.locator(f'#tickets-grid tr[data-ticket="{n}"]')).to_have_count(0)
        assert page.evaluate("([a, b]) => a === b", [panel_before, panel.element_handle()]), code
        assert page.evaluate("window.__d14_marker") == "alive", code
        assert filter_input.input_value() == "несохранённый текст", code
    # прямой адрес пресета: страница целиком, выбранный пресет отмечен `aria-current`
    page.goto("/tickets/?preset=waiting")
    expect(page.locator('nav[data-presets] a[data-preset="waiting"]')).to_have_attribute("aria-current", "true")


def test_d14_search_ye_and_yo_find_same_tickets_by_number_subject_text_address_and_name_ignoring_case(admin_page):
    """Сценарий 14, п. 2: поиск «еж…» и «ёж…» находит одни и те же заявки; находит по номеру, теме, тексту
    сообщения, адресу и ФИО заявителя, регистр не важен (FR-278)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    s_shared, s_name = _cyr(), _cyr()
    address_head = "ezh" + _lat()
    sender_addr = helpers_sd.requester_email(prefix=address_head)
    words = [_word() for _ in range(4)]
    # дано: одно слово у двух заявок — «Ёж…» в теме одной и «еж…» в тексте другой; ФИО с «Ёж…»; адрес с уникальным началом
    _deliver_all([
        _mail(helpers_sd.requester_email(), f"Ёж{s_shared} на сервере {words[0]}"),
        _mail(helpers_sd.requester_email(), f"Тема без слова {words[1]}", f"Нашли еж{s_shared} под столом"),
        _mail(f"Ёж{s_name} Тестов <{helpers_sd.requester_email()}>", f"Письмо с именем {words[2]}"),
        _mail(sender_addr, f"Письмо с адресом {words[3]}"),
    ])
    t_subject, t_text, t_name, t_addr = (helpers_sd.ticket_number_by_subject(page, w) for w in words)
    # когда ищем «ёж…» и «еж…» (в разном регистре) — тогда одни и те же заявки: и по теме, и по тексту
    found_yo = _found(page, f"ёж{s_shared}")
    found_ye = _found(page, f"еж{s_shared}")
    found_upper = _found(page, f"ЕЖ{s_shared}".upper())
    assert {t_subject, t_text} <= set(found_yo), found_yo
    assert set(found_yo) == set(found_ye) == set(found_upper) == {t_subject, t_text}
    # ФИО заявителя, без учёта регистра и «ё»/«е»
    for query in (f"ёж{s_name}", f"еж{s_name}", f"ЁЖ{s_name}".upper(), f"Еж{s_name}"):
        assert _found(page, query) == [t_name], query
    # адрес: начало местной части в разном регистре и адрес целиком
    for query in (address_head, address_head.upper(), sender_addr, sender_addr.upper()):
        assert _found(page, query) == [t_addr], query
    # тема: слово в разном регистре; текст сообщения — слово из тела письма
    assert _found(page, words[0].upper()) == [t_subject]
    assert _found(page, words[1]) == [t_text]
    # номер: «N» и «#N» находят заявку с этим номером
    assert t_name in _found(page, str(t_name))
    assert t_name in _found(page, f"#{t_name}")
    # чужого слова нет: пояснение «ничего не найдено» вместо пустого поля
    _open_list(page, preset="all", q=f"ёж{_cyr()}")
    expect(page.locator('[data-empty-state="tickets"]')).to_be_visible()
    expect(page.locator(GRID_ROWS)).to_have_count(0)


def test_d14_combined_filters_narrow_list_by_all_conditions(admin_page, stand_admin):
    """Сценарий 14, п. 3: фильтр по очереди, категории, критичности, статусу, виду статуса, ответственному,
    подразделению, источнику и периоду создания — каждое условие сужает список, вместе они сужают до одной заявки
    (FR-278)."""
    page = admin_page
    queue_id, queue_name = helpers_sd.ensure_ready(page)
    tag = secrets.token_hex(3)
    word = _word()
    queue2_name, category_name, unit_name = f"Очередь2 {tag}", f"Категория {tag}", f"Подразделение {tag}"
    queue2_id = helpers_org.create_unit(page, queue2_name)
    helpers_sd.mark_queue(page, queue2_id)
    _create_value(page, "categories", category_name, queue_id=queue2_id)
    _create_value(page, "client-units", unit_name)
    # дано четыре заявки с общим словом темы:
    # t1 — очередь по умолчанию, «Другое», «Высокая», «Телефон», подразделение, «Новая», без ответственного;
    # t3 и t4 пришли письмом — у них категории нет (письмо приходит без категории в очередь по умолчанию);
    # t2 — очередь 2, своя категория, «Средняя», «Почта», подразделение, создана 10 суток назад;
    # t3 — очередь по умолчанию, «Высокая», «Почта», «В работе» (вручную), без подразделения;
    # t4 — очередь по умолчанию, «Почта», подразделение, взята администратором
    t1 = _executor_ticket(page, queue_id=queue_id, subject=f"Условие один {word}", priority="Высокая", source="Телефон")
    words = [_word() for _ in range(3)]
    _deliver_all([_mail(helpers_sd.requester_email(), f"Условие {i + 2} {word} {w}") for i, w in enumerate(words)])
    t2, t3, t4 = (helpers_sd.ticket_number_by_subject(page, w) for w in words)
    _set_fields(page, t1, client_unit=unit_name)
    _change_category(page, t2, category_name, queue2_name)
    _set_fields(page, t2, priority="Средняя", client_unit=unit_name)
    helpers_sd.backdate("ticket", t2, "created_at", 10)
    _set_fields(page, t3, priority="Высокая")
    _set_status(page, t3, "В работе", "in_progress")
    _set_fields(page, t4, priority="Средняя", client_unit=unit_name)
    _take(page, t4)
    today = datetime.now(MSK).date()
    # значения выбора фильтра — со страницы списка
    _open_list(page, preset="all", q=word)
    value = {
        "queue": _option_value(page, "queue", queue_name), "queue2": _option_value(page, "queue", queue2_name),
        "category": _option_value(page, "category", "Другое"), "category2": _option_value(page, "category", category_name),
        "high": _option_value(page, "priority", "Высокая"), "phone": _option_value(page, "source", "Телефон"),
        "mail": _option_value(page, "source", "Почта"), "unit": _option_value(page, "client_unit", unit_name),
        "new": _option_value(page, "status", "Новая"), "admin": _option_value(page, "assignee", stand_admin.full_name),
    }
    base = dict(preset="all", q=word)

    def numbers(count: int, **params) -> set:
        return set(_list(page, count, **{**base, **params}))

    # когда: каждое условие отдельно — тогда список сужается именно по нему
    assert numbers(4) == {t1, t2, t3, t4}
    assert numbers(1, queue=value["queue2"]) == {t2}
    assert numbers(3, queue=value["queue"]) == {t1, t3, t4}
    assert numbers(1, category=value["category2"]) == {t2}
    assert numbers(1, category=value["category"]) == {t1}  # t3, t4 — письма без категории
    assert numbers(2, priority=value["high"]) == {t1, t3}
    assert numbers(1, source=value["phone"]) == {t1}
    assert numbers(3, source=value["mail"]) == {t2, t3, t4}
    assert numbers(3, client_unit=value["unit"]) == {t1, t2, t4}
    assert numbers(3, assignee="none") == {t1, t2, t3}
    assert numbers(1, assignee=value["admin"]) == {t4}
    assert numbers(2, status=value["new"], assignee="none") == {t1, t2}  # «Новая» и без ответственного
    assert numbers(1, kind="in_progress", assignee="none") == {t3}  # вид «в работе», без ответственного
    assert numbers(1, created_from=_date(today - timedelta(days=12)), created_to=_date(today - timedelta(days=8))) == {t2}
    assert numbers(3, created_from=_date(today - timedelta(days=3))) == {t1, t3, t4}
    assert numbers(1, created_to=_date(today - timedelta(days=5))) == {t2}
    # сочетания: условия складываются через «и»
    assert numbers(1, priority=value["high"], source=value["phone"]) == {t1}
    assert numbers(1, queue=value["queue"], category=value["category"], priority=value["high"]) == {t1}
    assert numbers(2, source=value["mail"], client_unit=value["unit"]) == {t2, t4}
    assert numbers(1, source=value["mail"], client_unit=value["unit"], assignee="none") == {t2}
    assert numbers(1, source=value["mail"], client_unit=value["unit"], assignee="none",
                   created_from=_date(today - timedelta(days=12)), created_to=_date(today - timedelta(days=8))) == {t2}
    assert numbers(0, priority=value["high"], source=value["mail"], client_unit=value["unit"]) == set()
    assert numbers(0, queue=value["queue2"], priority=value["high"]) == set()
    # все десять условий сразу — ровно заявка t1
    everything = dict(queue=value["queue"], category=value["category"], priority=value["high"], status=value["new"],
                      kind="new", assignee="none", client_unit=value["unit"], source=value["phone"],
                      created_from=_date(today - timedelta(days=1)), created_to=_date(today))
    assert numbers(1, **everything) == {t1}
    # любое одно условие, заменённое чужим значением, оставляет список пустым
    assert numbers(0, **{**everything, "source": value["mail"]}) == set()
    assert numbers(0, **{**everything, "queue": value["queue2"]}) == set()
    # заданный фильтр показан в форме: значения выбраны
    _open_list(page, **{**base, **everything})
    form = page.locator("#tickets-filter")
    expect(form.locator('[name="created_from"]')).not_to_have_value("")
    expect(form.locator('[name="created_to"]')).not_to_have_value("")
    for name in ("queue", "category", "priority", "status", "kind", "assignee", "client_unit", "source"):
        expect(form.locator(f'select[name="{name}"]')).to_have_value(everything[name])
    expect(form.locator("input[name=q]")).to_have_value(word)


def test_d14_sorts_by_number_created_last_message_criticality_default_newest_first(admin_page):
    """Сценарий 14, п. 4: сортировка по номеру, дате создания, последнему сообщению и критичности в обе стороны;
    без выбора сортировки — новые сверху, то есть по номеру по убыванию (FR-279)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    word = _word()
    words = [_word() for _ in range(3)]
    _deliver_all([_mail(helpers_sd.requester_email(), f"Порядок {word} {w}") for w in words])
    n1, n2, n3 = sorted(helpers_sd.ticket_number_by_subject(page, w) for w in words)
    # дано: порядок по каждому признаку свой (n1 < n2 < n3 — порядок номеров)
    _set_fields(page, n1, priority="Низкая")
    _set_fields(page, n2, priority="Высокая")
    _set_fields(page, n3, priority="Средняя")
    helpers_sd.backdate("ticket", n2, "created_at", 5)
    helpers_sd.backdate("ticket", n3, "created_at", 3)
    helpers_sd.backdate("ticket", n2, "last_message_at", 4)
    helpers_sd.backdate("ticket", n1, "last_message_at", 2)
    # по убыванию: номер n3 n2 n1; создана n1 n3 n2; последнее сообщение n3 n1 n2; критичность (высшая первой) n2 n3 n1
    desc = {"number": [n3, n2, n1], "created": [n1, n3, n2], "last_message": [n3, n1, n2], "priority": [n2, n3, n1]}
    cell = {"created": "created", "last_message": "last-message"}
    base = dict(preset="all", q=word)
    # когда открываем список без выбора — тогда новые сверху
    assert _list(page, 3, **base) == desc["number"]
    expect(page.locator('th[data-sort="number"]')).to_have_attribute("aria-sort", "descending")
    # тогда по каждому признаку — в обе стороны
    for key, order in desc.items():
        assert _list(page, 3, **base, sort=key, dir="desc") == order, (key, "desc")
        expect(page.locator(f'th[data-sort="{key}"]')).to_have_attribute("aria-sort", "descending")
        assert _list(page, 3, **base, sort=key, dir="asc") == order[::-1], (key, "asc")
        expect(page.locator(f'th[data-sort="{key}"]')).to_have_attribute("aria-sort", "ascending")
        if key in cell:  # столбец показывает те же времена: по возрастанию они не убывают
            stamps = [_at(page.locator(f'#tickets-grid tr[data-ticket="{n}"] [data-cell="{cell[key]}"] time[data-at]'))
                      for n in order[::-1]]
            assert stamps == sorted(stamps), (key, stamps)
    # щелчок по заголовку сортирует сетку по HTMX; направление читаем по `aria-sort`
    _open_list(page, **base)
    for key in ("created", "last_message", "priority"):
        header = page.locator(f'th[data-sort="{key}"]')
        with page.expect_response(lambda r, k=key: "/tickets/" in r.url and f"sort={k}" in r.url) as info:
            header.locator("a").click()
        assert info.value.request.header_value("hx-target") == "tickets-grid", key
        expect(header).to_have_attribute("aria-sort", re.compile("^(ascending|descending)$"))
        expect(page).to_have_url(re.compile(rf"q={word}(&|$)"))  # сортировка сохраняет фильтр (доп. 43 (а))
        direction = header.get_attribute("aria-sort")
        expect(page.locator(GRID_ROWS)).to_have_count(3)
        assert _numbers(page) == (desc[key] if direction == "descending" else desc[key][::-1]), (key, direction)


def test_d14_menu_counter_shows_six_for_four_unassigned_plus_two_requester_last(
        browser, browser_context_args, stand_admin, admin_page, employee):
    """Сценарий 14, п. 5: у пункта «Заявки» число 6 — четыре открытые заявки очереди пользователя без
    ответственного плюс две его открытые заявки, где последним писал заявитель; ответ исполнителя убирает заявку
    из счёта (FR-280)."""
    helpers_sd.reset_stand_and_relogin(browser, browser_context_args, stand_admin, admin_page)
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    # дано: пользователь, у которого только своя очередь (она же очередь по умолчанию)
    tag = secrets.token_hex(3)
    user = employee(full_name=f"Тест{tag} Счётчиков Иван")
    helpers_sd.add_queue_member(page, queue_id, [user.id], q=f"Тест{tag}")
    words = [_word() for _ in range(6)]
    _deliver_all([_mail(helpers_sd.requester_email(), f"Счётчик {w}") for w in words])
    badge = user.page.locator('#main-menu a.menu-item[href="/tickets/"] span[data-menu-badge]')
    # когда страница загружена — тогда 6: все шесть открытые и без ответственного
    user.page.goto("/tickets/")
    expect(badge).to_have_text("6")
    # две заявки пользователь берёт себе (последним писал заявитель) — снова 6: четыре без ответственного + две свои
    taken = [helpers_sd.ticket_number_by_subject(user.page, w) for w in words[:2]]
    for number in taken:
        _take(user.page, number)
    user.page.goto("/tickets/")
    expect(badge).to_have_text("6")
    # ответ исполнителя по одной из своих заявок: последним пишет он — 4 + 1 = 5
    _reply(user.page, taken[0], "Принято в работу, приедем сегодня")
    user.page.goto("/tickets/")
    expect(badge).to_have_text("5")


def test_d14_empty_preset_shows_explanation(browser, browser_context_args, stand_admin, admin_page, employee):
    """Сценарий 14, п. 6: у пустого пресета вместо пустого поля — пояснение (разное у каждого пресета) и кнопка
    «Новая заявка»; у пустого результата поиска — своё пояснение без кнопки (FR-282)."""
    helpers_sd.reset_stand_and_relogin(browser, browser_context_args, stand_admin, admin_page)
    page = admin_page
    queue_id, _ = helpers_sd.ensure_ready(page)
    # дано: пользователь со своей очередью, заявок нет совсем
    tag = secrets.token_hex(3)
    user = employee(full_name=f"Тест{tag} Пустов Иван")
    helpers_sd.add_queue_member(page, queue_id, [user.id], q=f"Тест{tag}")
    texts = []
    for code in ("mine", "unassigned", "my_queues", "waiting", "closed", "all"):
        user.page.goto(f"/tickets/?preset={code}")
        empty = user.page.locator(f'[data-empty-state="tickets"][data-preset="{code}"]')
        # тогда: пояснение вместо пустого поля, кнопка «Новая заявка» (у участника очереди она есть), строк нет
        expect(empty).to_have_count(1)
        expect(empty).to_be_visible()
        text = " ".join(empty.inner_text().split())
        assert text, code
        texts.append(text)
        expect(empty.locator('a[data-action="ticket-new"]')).to_have_attribute("href", "/tickets/new/")
        expect(user.page.locator(GRID_ROWS)).to_have_count(0)
    assert len(set(texts)) == 6, texts  # у каждого пресета своё пояснение
    # пустой результат поиска: пояснение без кнопки
    user.page.goto("/tickets/?" + urllib.parse.urlencode({"preset": "all", "q": f"ёж{_cyr()}"}))
    nothing = user.page.locator('[data-empty-state="tickets"]')
    expect(nothing).to_have_count(1)
    expect(nothing).to_contain_text("По вашему запросу заявок нет")
    expect(nothing.locator('a[data-action="ticket-new"]')).to_have_count(0)


def test_d14_list_at_360px_no_horizontal_scroll(admin_page):
    """Сценарий 14, п. 7: на ширине окна 360 px список заявок — карточками и без горизонтальной прокрутки, в том
    числе с раскрытой панелью фильтра (NFR-208)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    word = _word()
    subject = f"Не работает доступ к общему сетевому каталогу бухгалтерии после обновления системы {word}"
    helpers_sd.deliver(_mail(helpers_sd.requester_email(prefix="longaddresshead"), subject))
    number = helpers_sd.ticket_number_by_subject(page, word)
    # дано: окно 360 px; когда открыт список (своя заявка и общий список) — тогда прокрутки по горизонтали нет
    page.set_viewport_size({"width": 360, "height": 800})
    _open_list(page, preset="all", q=word)
    expect(page.locator(f'#tickets-grid tr[data-ticket="{number}"]')).to_be_visible()
    expect(page.locator('#tickets-grid[data-narrow="cards"]')).to_have_count(1)
    assert helpers.no_horizontal_scroll(page)
    panel = page.locator("details[data-filter-panel]")
    if panel.get_attribute("open") is None:  # раскрыта ли панель при заданном фильтре, контракт не говорит
        panel.locator("summary").first.click()
    expect(page.locator("#tickets-filter")).to_be_visible()
    assert helpers.no_horizontal_scroll(page)
    _open_list(page, preset="all")
    expect(page.locator(GRID_ROWS).first).to_be_visible()
    assert helpers.no_horizontal_scroll(page)


def test_d14_employee_card_tickets_link_filters_by_assignee_and_shows_only_accessible(admin_page, employee):
    """Сценарий 14, п. 8: в карточке сотрудника у смотрящего, вправе видящего заявки, есть ссылка «Заявки» на список
    с фильтром «Ответственный: этот сотрудник», и в нём только то, что смотрящему доступно; у смотрящего без права
    ссылки нет (FR-281)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    tag = secrets.token_hex(3)
    q1_name, q2_name = f"Очередь1 {tag}", f"Очередь2 {tag}"
    q1, q2 = helpers_org.create_unit(page, q1_name), helpers_org.create_unit(page, q2_name)
    helpers_sd.mark_queue(page, q1)
    helpers_sd.mark_queue(page, q2)
    # дано: E — участник обеих очередей, V — только первой, W — ни одной
    assignee = employee(full_name=f"Тест{tag} Ефимов Егор")
    viewer = employee(full_name=f"Тест{tag} Власов Виктор")
    outsider = employee(full_name=f"Тест{tag} Одинов Олег")
    helpers_sd.add_queue_member(page, q1, [assignee.id, viewer.id], q=f"Тест{tag}")
    helpers_sd.add_queue_member(page, q2, [assignee.id], q=f"Тест{tag}")
    words = [_word(), _word()]
    _deliver_all([_mail(helpers_sd.requester_email(), f"Карточка сотрудника {w}") for w in words])
    in_q1, in_q2 = (helpers_sd.ticket_number_by_subject(page, w) for w in words)
    _transfer(page, in_q1, q1, q1_name)
    _transfer(page, in_q2, q2, q2_name)
    _take(assignee.page, in_q1)
    _take(assignee.page, in_q2)
    link_href = f"/tickets/?preset=all&assignee={assignee.id}"
    # когда смотрящий V открывает карточку E — тогда есть раздел «Заявки» со ссылкой на список с фильтром
    viewer.page.goto(f"/staff/{assignee.id}/")
    link = viewer.page.locator('[data-section="tickets"] a[data-action="employee-tickets"]')
    expect(link).to_have_count(1)
    expect(link).to_have_attribute("href", link_href)
    expect(link).to_have_text("Заявки")
    link.click()
    expect(viewer.page).to_have_url(re.compile(rf"assignee={assignee.id}"))
    expect(viewer.page.locator(GRID_ROWS)).to_have_count(1)
    # тогда в списке только заявки E, доступные V: заявка второй очереди скрыта
    assert _numbers(viewer.page) == [in_q1]
    # администратор по той же ссылке видит обе заявки E
    page.goto(f"/staff/{assignee.id}/")
    expect(page.locator('[data-section="tickets"] a[data-action="employee-tickets"]')).to_have_attribute(
        "href", link_href)
    page.goto(link_href)
    expect(page.locator(GRID_ROWS)).to_have_count(2)
    assert sorted(_numbers(page)) == sorted([in_q1, in_q2])
    # смотрящий без очередей и без права: пункта «Заявки» нет, раздела со ссылкой тоже
    outsider.page.goto(f"/staff/{assignee.id}/")
    expect(outsider.page.locator("#main-menu")).to_be_visible()
    expect(outsider.page.locator('#main-menu a.menu-item[href="/tickets/"]')).to_have_count(0)
    expect(outsider.page.locator('[data-section="tickets"]')).to_have_count(0)


def test_d14_last_message_is_executor_reply_with_time_and_mark_comment_and_event_excluded(admin_page):
    """Сценарий 14, п. 9: после письма заявителя «последнее сообщение» в списке — «заявитель»; после ответа
    исполнителя — «исполнитель» со временем ответа; внутренний комментарий и событие в него не входят (FR-248, FR-277)."""
    page = admin_page
    helpers_sd.ensure_ready(page)
    word = _word()
    helpers_sd.deliver(_mail(helpers_sd.requester_email(), f"Последнее сообщение {word}"))
    number = helpers_sd.ticket_number_by_subject(page, word)
    row = page.locator(f'#tickets-grid tr[data-ticket="{number}"]')
    cell = row.locator('[data-cell="last-message"]')
    # дано: в заявке письмо заявителя — последнее сообщение от заявителя
    expect(cell.locator('[data-last-from="requester"]')).to_contain_text("заявитель")
    # затем ответ исполнителя
    card = _reply(page, number, "Здравствуйте, проверяем вашу заявку")
    feed = card.locator("ol[data-feed]")
    expect(feed.locator('li[data-kind="reply"] [data-reply-label]')).to_be_visible()
    reply_at = _at(feed.locator('li[data-kind="reply"] time[data-at]'))
    # когда смотрим список — тогда «последнее сообщение» — ответ исполнителя: отметка «исполнитель» и его время
    _open_list(page, preset="all", q=word)
    expect(cell.locator('[data-last-from="staff"]')).to_contain_text("исполнитель")
    assert abs((_at(cell.locator("time[data-at]")) - reply_at).total_seconds()) < 2
    # затем внутренний комментарий и событие (взять себе); время «последнего сообщения» отодвигаем на двое суток назад:
    # если бы комментарий или событие его обновляли, оно снова стало бы «сейчас»
    helpers_sd.backdate("ticket", number, "last_message_at", 2)
    card = helpers_sd.open_ticket(page, number)
    form = card.locator('form[data-form="ticket-comment"]')
    form.locator("textarea[name=text]").fill("Внутренняя заметка для коллег")
    form.locator("button[type=submit]").click()
    expect(card.locator('ol[data-feed] li[data-kind="comment"]')).to_have_count(1)
    card.locator('form[data-form="ticket-take"] button[data-action="ticket-take"]').click()
    expect(card.locator('[data-field="assignee"]')).to_have_attribute("data-empty", "false")
    expect(card.locator('ol[data-feed] li[data-kind="event"]').first).to_be_visible()
    _open_list(page, preset="all", q=word)
    expect(cell.locator('[data-last-from="staff"]')).to_contain_text("исполнитель")
    shifted = _at(cell.locator("time[data-at]"))
    assert abs((shifted - (reply_at - timedelta(days=2))).total_seconds()) < 180, shifted


def test_d14_grid_columns_are_exactly_the_specified_set(admin_page):
    """Сценарий 14, п. 10: колонки сетки — выбор строки, номер, тема, заявитель, подразделение, категория, очередь,
    критичность, статус, ответственный, создана, последнее сообщение (время и от кого), и никаких других (FR-277)."""
    page = admin_page
    _, queue_name = helpers_sd.ensure_ready(page)
    word = _word()
    sender = helpers_sd.requester_email()
    subject = f"Колонки сетки {word}"
    helpers_sd.deliver(_mail(sender, subject))
    number = helpers_sd.ticket_number_by_subject(page, word)
    # когда смотрим сетку — тогда в строке ровно эти ячейки и в этом порядке
    row = page.locator(f'#tickets-grid tr[data-ticket="{number}"]')
    cells = row.locator(":scope > [data-cell]").evaluate_all("els => els.map(e => e.dataset.cell)")
    assert cells == ["select", "number", "subject", "requester", "client-unit", "category", "queue", "priority",
                     "status", "assignee", "created", "last-message"], cells
    # значения: номер-ссылка, тема, заявитель (без ФИО — адрес), очередь, критичность, статус, ответственный, время
    expect(row.locator('[data-cell="number"] a')).to_have_attribute("href", f"/tickets/{number}/")
    expect(row.locator('[data-cell="subject"]')).to_contain_text(subject)
    expect(row.locator('[data-cell="requester"]')).to_contain_text(sender)
    expect(row.locator('[data-cell="queue"]')).to_contain_text(queue_name)
    expect(row.locator('[data-cell="status"]')).to_contain_text("Новая")
    expect(row.locator('[data-cell="assignee"]')).to_contain_text("не назначен")
    expect(row.locator('[data-cell="priority"]')).not_to_be_empty()
    expect(row.locator('[data-cell="created"] time[data-at]')).to_have_count(1)
    expect(row.locator('[data-cell="last-message"] time[data-at]')).to_have_count(1)
    expect(row.locator('[data-cell="last-message"] [data-last-from="requester"]')).to_contain_text("заявитель")
    # сортируемые столбцы — только номер, дата создания, последнее сообщение и критичность
    keys = page.locator("#tickets-grid thead th[data-sort]").evaluate_all("els => els.map(e => e.dataset.sort)")
    assert sorted(keys) == ["created", "last_message", "number", "priority"], keys
