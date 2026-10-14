"""T-4149: сценарий 10 — страница «Уведомления»: прочитать, прочитать все, хранение (FR-307, FR-318, FR-319, FR-338,
FR-342).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-004.md):
- «много уведомлений» заводит команда стенда `e2e_notify_fill` (§ 8.2, помощник `helpers_notify.fill`): текст
  «Тестовое уведомление <i>», вид ядра, ссылка `/notifications/`; больший номер — новее, поэтому порядок «новые сверху»
  задан номерами в тексте. Каждый тест берёт своего только что активированного сотрудника: список его уведомлений
  задаёт сам тест (по контракту § 3.3 вход при активации и первое устройство уведомлений безопасности не создают);
- строки списка ищутся по тексту «Тестовое уведомление <i>» или по слову темы заявки, а не «первая строка страницы»:
  если у сотрудника есть другие уведомления, тесты на них не опираются (кроме теста пустого списка, где сотрудник
  свежий);
- тест хранения (7) сдвигает сроки по всему стенду (`e2e_notify_tick --age-days … --retention`, § 8.2) и поэтому
  проверяет только свои уведомления и историю своей заявки; срок хранения читается со страницы администратора;
- заявки заводятся письмом заявителя (`helpers_sd.deliver`), очередь по умолчанию на время теста — своя и возвращается
  в `finally`; участники очередей — `helpers_org`.
"""
import contextlib
import re
import secrets
from datetime import datetime, timedelta, timezone

from playwright.sync_api import expect

from tests.e2e import helpers_notify, helpers_org, helpers_sd
from tests.e2e.helpers_sd import MAILBOX
from tests.support_servicedesk import build_mail

MOSCOW = timezone(timedelta(hours=3))  # Москва без перехода на летнее время (UTC+3)
FILL_TEXT = "Тестовое уведомление"  # текст, который создаёт `e2e_notify_fill` (§ 8.2)
FILL_RE = re.compile(rf"{FILL_TEXT} (\d+)")
TIME_RE = re.compile(r"\d\d\.\d\d\.\d{4} \d\d:\d\d")  # ДД.ММ.ГГГГ ЧЧ:ММ (§ 14)
KIND_NAME = "Пароль изменён"  # название вида `core.password_changed` у уведомлений `e2e_notify_fill` (§ 3.2, § 8.2)
NO_NOTIFICATIONS = "У вас нет уведомлений"  # § 15.5
NO_UNREAD = "Непрочитанных уведомлений нет"  # § 15.5, фильтр «Непрочитанные»
LIVE_WAIT_MS = 5_000  # число по соединению там, где срок 2 с (NFR-301) не проверяется


# --- Общие помощники файла ----------------------------------------------------------------------------

def _word() -> str:
    """Уникальное слово темы: буква и шесть шестнадцатеричных знаков (не из одних цифр: поиск списка принял бы его
    за номер заявки; CONTRACT-003, доп. 41 (в))."""
    return f"t{secrets.token_hex(3)}"


def _tag() -> str:
    """Общее начало фамилий сотрудников теста: по нему «Добавить сотрудников» находит всех сразу."""
    return "Список" + secrets.token_hex(3)


def _norm(text: str) -> str:
    return " ".join(text.split())


def _staff(employee, tag: str, index: int):
    return employee(full_name=f"{tag}{index} Петр Петрович")


def _queue(page, prefix: str = "Поддержка") -> tuple:
    """Новый узел `org`, отмеченный очередью: `(номер, название)`."""
    name = helpers_org.unique_name(prefix)
    unit_id = helpers_org.create_unit(page, name, kind="department")
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
    """Очередь по умолчанию на время теста — своя (письмо попадает в неё); прежняя возвращается в `finally`."""
    helpers_sd.set_default_queue(page, queue_id)
    try:
        yield
    finally:
        helpers_sd.set_default_queue(page, old_id)


def _mail_ticket(title: str = "Не работает принтер") -> tuple:
    """Письмо заявителя в ящик заявок и сразу разбор: заявка в очереди по умолчанию, без ответственного.
    Возвращает `(слово, тема, адрес заявителя)`; номер заявки — `helpers_sd.ticket_number_by_subject`."""
    word = _word()
    subject = f"{title} {word}"
    sender = helpers_sd.requester_email()
    helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=subject, text=f"Нужна помощь {word}",
                                  message_id=f"<{secrets.token_hex(8)}@client.test>"))
    return word, subject, sender


def _list(page) -> None:
    """Открывает «Уведомления» и ждёт корень страницы (список только читается, ничего не отмечает)."""
    page.goto("/notifications/")
    expect(page.locator("[data-notify-list]")).to_be_visible()


def _all_rows(page):
    return page.locator("ul[data-notifications] li[data-notification]")


def _rows(page, word: str):
    """Строки списка, в тексте которых есть слово темы заявки."""
    return _all_rows(page).filter(has_text=word)


def _fill_row(page, number: int):
    """Строка «Тестовое уведомление <number>» (число — целиком: «3» не находит «30»)."""
    text = page.locator('[data-field="text"]', has_text=re.compile(rf"^\s*{FILL_TEXT} {number}\s*$"))
    return _all_rows(page).filter(has=text)


def _texts(rows) -> list:
    """Тексты уведомлений строк `[data-field="text"]` в порядке страницы."""
    return [_norm(t) for t in rows.locator('[data-field="text"]').all_inner_texts()]


def _fill_numbers(texts) -> list:
    """Номера «Тестовое уведомление <i>» из текстов, в порядке страницы (прочие уведомления пропускаются)."""
    found = (FILL_RE.search(t) for t in texts)
    return [int(m.group(1)) for m in found if m]


def _assert_newest_first(numbers: list, top: int) -> None:
    """Номера идут подряд вниз от `top`: новые сверху (больший номер создан позже, § 8.2)."""
    assert numbers == list(range(top, top - len(numbers), -1)), numbers


def _ready(page) -> int:
    """Число колокольчика при готовом соединении (решение E21): отсчёт «до события»."""
    helpers_notify.wait_ws_open(page)
    return helpers_notify.bell_count(page)


def _retention_days(admin_page) -> int:
    """Срок хранения уведомлений, как он стоит на странице администратора (по умолчанию 90)."""
    admin_page.goto("/settings/notifications/")
    field = admin_page.locator('[data-notify-settings] input[name="retention_days"]')
    expect(field).to_have_count(1)
    return int(field.input_value())


# --- Тесты --------------------------------------------------------------------------------------------------

def test_e10_page_with_120_notifications_shows_first_50_newest_first_with_kind_text_time_and_unread_mark(employee):
    """Сценарий 10, п. 1: у сотрудника 120 уведомлений — страница «Уведомления» показывает первые 50, новые сверху,
    у каждого вид, текст, время по Москве и отметку «не прочитано» (FR-319)."""
    member = employee()
    page = member.page
    _list(page)
    before = _all_rows(page).count()  # уведомления, которые были до команды (по контракту их нет)
    # дано: 120 непрочитанных уведомлений
    helpers_notify.fill(member.email, 120)
    # когда: сотрудник открывает страницу
    _list(page)
    rows = _all_rows(page)
    # п. 1: видны первые 50 (на странице больше нет), остальное — на следующей странице
    expect(rows).to_have_count(50)
    pager = page.locator("nav[data-pager]")
    expect(pager.locator("a[data-page-next]")).to_have_count(1)
    expect(pager.locator("a[data-page-prev]")).to_have_count(0)
    expect(pager.locator("[data-page-current]")).to_have_text("1")
    # п. 1: новые сверху — номера подряд вниз от 120; все 50 мест заняты новыми (прежние уведомления, если были,
    # старше и могут вытеснить только последние места)
    numbers = _fill_numbers(_texts(rows))
    _assert_newest_first(numbers, 120)
    assert len(numbers) >= 50 - before, f"в первых 50 строках только {len(numbers)} новых уведомлений"
    # п. 1: у каждой строки — вид, текст, время и отметка «не прочитано»
    expect(page.locator('ul[data-notifications] li[data-notification][data-unread="1"]')).to_have_count(50)
    expect(rows.locator("[data-unread-mark]")).to_have_count(50)
    kinds = rows.locator('[data-field="kind"]')
    expect(kinds).to_have_count(50)
    expect(kinds).to_have_text([KIND_NAME] * 50)  # вид `core.password_changed` (§ 8.2, § 3.2)
    links = rows.locator('[data-field="text"] a[data-open]')
    expect(links).to_have_count(50)
    for text in links.all_inner_texts():
        assert text.strip()
    for mark in rows.locator("[data-unread-mark]").all_inner_texts():
        assert mark.strip() == "новое", mark
    # п. 1: время — «ДД.ММ.ГГГГ ЧЧ:ММ» по Москве, как в атрибуте data-at
    stamps = rows.locator("time[data-at]").evaluate_all("els => els.map(e => [e.getAttribute('data-at'), "
                                                        "e.textContent.trim()])")
    assert len(stamps) == 50, stamps
    for iso, shown in stamps:
        assert TIME_RE.fullmatch(shown), shown
        assert shown == datetime.fromisoformat(iso).astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M"), (iso, shown)
    # п. 1: остальное — на следующей странице: по ссылке 50 строк с номерами 70…21 подряд
    pager.locator("a[data-page-next]").click()
    expect(pager.locator("[data-page-current]")).to_have_text("2")
    expect(_all_rows(page)).to_have_count(50)
    second = _fill_numbers(_texts(_all_rows(page)))
    assert second == list(range(70, 20, -1)), second


def test_e10_opening_unread_notification_link_marks_it_read_and_bell_counter_drops_at_once(employee, new_context):
    """Сценарий 10, п. 2: уведомление не прочитано — сотрудник открывает его ссылку, уведомление становится
    прочитанным, счётчик колокольчика уменьшается сразу, в том числе во второй открытой вкладке (FR-307, FR-318)."""
    member = employee()
    page = member.page
    helpers_notify.fill(member.email, 5)
    watcher = helpers_notify.open_watcher(new_context, member)  # вторая вкладка той же учётной записи
    _list(page)
    base = _ready(page)
    assert base >= 5
    target = _fill_row(page, 3)
    expect(target).to_have_count(1)
    notification_id = target.get_attribute("data-notification")
    expect(target).to_have_attribute("data-unread", "1")
    link = target.locator('[data-field="text"] a[data-open]')
    expect(link).to_have_attribute("href", f"/notifications/{notification_id}/open/")
    # когда: сотрудник открывает ссылку уведомления
    with page.expect_navigation():
        link.click()
    expect(page.locator("[data-notify-list]")).to_be_visible()
    # п. 2: уведомление прочитано, остальные нет
    row = page.locator(f'ul[data-notifications] li[data-notification="{notification_id}"]')
    expect(row).to_have_attribute("data-unread", "0")
    expect(row.locator("[data-unread-mark]")).to_have_count(0)
    expect(_fill_row(page, 4)).to_have_attribute("data-unread", "1")
    # п. 2: счётчик уменьшился на 1 сразу — на открытой странице и во второй вкладке (во второй вкладке — кадром соединения)
    helpers_notify.wait_bell_count(page, base - 1, timeout_ms=LIVE_WAIT_MS)
    helpers_notify.wait_bell_count(watcher, base - 1, timeout_ms=LIVE_WAIT_MS)


def test_e10_mark_read_button_marks_notification_read_without_navigation(employee):
    """Сценарий 10, п. 3: сотрудник нажимает «Прочитать» у уведомления — оно прочитано без перехода: страница не
    перезагружается, строка остаётся в списке, счётчик на 1 меньше (FR-307)."""
    member = employee()
    page = member.page
    helpers_notify.fill(member.email, 3)
    _list(page)
    base = _ready(page)
    assert base >= 3
    target = _fill_row(page, 3)
    expect(target).to_have_count(1)
    notification_id = target.get_attribute("data-notification")
    url_before = page.url
    page.evaluate("window.__e2eNoReload = 'same page'")  # метка пропадёт, если страница перезагрузится
    # когда: нажатие «Прочитать» в строке
    read_button = target.locator('form[data-form="read"] button[data-action="read"]')
    expect(read_button).to_have_text("Прочитать")  # точное совпадение: «Прочитать все» — другая кнопка
    read_button.click()
    # п. 3: строка заменена на прочитанную на месте — отметки и кнопки нет, остальные строки не тронуты
    row = page.locator(f'ul[data-notifications] li[data-notification="{notification_id}"]')
    expect(row).to_have_attribute("data-unread", "0")
    expect(row.locator("[data-unread-mark]")).to_have_count(0)
    expect(row.locator('button[data-action="read"]')).to_have_count(0)
    expect(_fill_row(page, 2)).to_have_attribute("data-unread", "1")
    expect(_fill_row(page, 1)).to_have_attribute("data-unread", "1")
    # п. 3: без перехода — тот же адрес, та же страница (метка жива), строка осталась в списке
    assert page.url == url_before
    assert page.evaluate("window.__e2eNoReload") == "same page", "страница перезагрузилась"
    expect(_fill_row(page, 3)).to_have_count(1)
    # п. 3: число на колокольчике приходит по соединению
    helpers_notify.wait_bell_count(page, base - 1, timeout_ms=LIVE_WAIT_MS)


def test_e10_read_all_with_30_unread_marks_all_read_and_counter_zero(employee):
    """Сценарий 10, п. 4: 30 непрочитанных — «Прочитать все» отмечает все прочитанными, счётчик 0; уведомления другого
    сотрудника не затронуты (FR-307, FR-319)."""
    member, other = employee(), employee()
    page = member.page
    _list(other.page)
    other_before = _ready(other.page)  # у второго сотрудника до команды (по контракту 0)
    helpers_notify.fill(member.email, 30)
    helpers_notify.fill(other.email, 2)
    _list(page)
    base = _ready(page)
    assert base >= 30
    expect(page.locator('ul[data-notifications] li[data-notification][data-unread="1"]')).to_have_count(base)
    # когда: «Прочитать все»
    form = page.locator('form[data-form="read-all"]')
    expect(form).to_have_count(1)
    read_all = form.locator('button[data-action="read-all"]')
    expect(read_all).to_have_text("Прочитать все")
    read_all.click()
    # п. 4: на странице нет непрочитанных, счётчик 0
    expect(page.locator('ul[data-notifications] li[data-notification][data-unread="1"]')).to_have_count(0)
    expect(page.locator("[data-unread-mark]")).to_have_count(0)
    helpers_notify.wait_bell_count(page, 0, timeout_ms=LIVE_WAIT_MS)
    _list(page)  # и после перезагрузки
    expect(page.locator('ul[data-notifications] li[data-notification][data-unread="1"]')).to_have_count(0)
    assert helpers_notify.bell_count(page) == 0
    # п. 4: чужие уведомления не затронуты — у второго сотрудника по-прежнему 2 непрочитанных
    _list(other.page)
    assert helpers_notify.bell_count(other.page) == other_before + 2
    expect(other.page.locator('ul[data-notifications] li[data-notification][data-unread="1"]').filter(
        has_text=FILL_TEXT)).to_have_count(2)


def test_e10_unread_filter_shows_only_unread_and_all_filter_shows_all(employee):
    """Сценарий 10, п. 5: фильтр «Непрочитанные» показывает только непрочитанные, «Все» — все (FR-319)."""
    member = employee()
    page = member.page
    helpers_notify.fill(member.email, 8, read=3)  # прочитаны три самых старых (1…3), непрочитаны 4…8
    _list(page)
    filter_nav = page.locator("nav[data-notify-filter]")
    # дано: по умолчанию активен фильтр «Все», видны все восемь
    expect(filter_nav.locator('a[data-filter="all"]')).to_have_attribute("aria-current", "true")
    _assert_newest_first(_fill_numbers(_texts(_all_rows(page))), 8)
    assert sorted(_fill_numbers(_texts(_all_rows(page)))) == list(range(1, 9))
    # когда: сотрудник выбирает «Непрочитанные»
    expect(filter_nav.locator('a[data-filter="all"]')).to_have_text("Все")
    expect(filter_nav.locator('a[data-filter="unread"]')).to_have_text("Непрочитанные")
    filter_nav.locator('a[data-filter="unread"]').click()
    page.wait_for_url(re.compile(r"[?&]f=unread"))
    expect(page.locator("[data-notify-list]")).to_be_visible()
    # п. 5: только непрочитанные — 4…8; ни одной прочитанной строки
    expect(page.locator("nav[data-notify-filter] a[data-filter=\"unread\"]")).to_have_attribute("aria-current", "true")
    expect(page.locator('ul[data-notifications] li[data-notification][data-unread="0"]')).to_have_count(0)
    unread_numbers = _fill_numbers(_texts(_all_rows(page)))
    assert unread_numbers == [8, 7, 6, 5, 4], unread_numbers
    # когда: сотрудник выбирает «Все»
    page.locator('nav[data-notify-filter] a[data-filter="all"]').click()
    page.wait_for_url(re.compile(r"/notifications/$"))
    expect(page.locator("[data-notify-list]")).to_be_visible()
    # п. 5: видны все — прочитанные 3…1 и непрочитанные 8…4
    expect(page.locator('nav[data-notify-filter] a[data-filter="all"]')).to_have_attribute("aria-current", "true")
    numbers = _fill_numbers(_texts(_all_rows(page)))
    assert numbers == [8, 7, 6, 5, 4, 3, 2, 1], numbers
    for number in (3, 2, 1):
        expect(_fill_row(page, number)).to_have_attribute("data-unread", "0")
    for number in (8, 7, 6, 5, 4):
        expect(_fill_row(page, number)).to_have_attribute("data-unread", "1")


def test_e10_bell_click_shows_last_10_notifications_and_all_notifications_link(employee):
    """Сценарий 10, п. 6: сотрудник нажимает на колокольчик — видны последние 10 уведомлений (новые сверху) и ссылка
    «Все уведомления» (и «Настройки») (FR-318)."""
    member = employee()
    page = member.page
    helpers_notify.fill(member.email, 15)
    page.goto("/")
    _ready(page)
    panel = page.locator("#notify-bell-panel")
    # дано: до нажатия панель пуста
    expect(panel.locator("[data-bell-list]")).to_have_count(0)
    # когда: нажатие на колокольчик
    page.locator("button[data-bell-toggle]").click()
    expect(panel.locator("[data-bell-list]")).to_be_visible()
    # п. 6: последние 10 — «Тестовое уведомление 15» … «6», новые сверху
    rows = panel.locator("[data-bell-list] li[data-notification]")
    expect(rows).to_have_count(10)
    numbers = _fill_numbers(_texts(rows))
    assert numbers, "в панели нет тестовых уведомлений"
    _assert_newest_first(numbers, 15)
    # п. 6: ссылки «Все уведомления» и «Настройки» — всегда
    all_link = panel.locator("a[data-bell-all]")
    expect(all_link).to_have_count(1)
    expect(all_link).to_have_attribute("href", "/notifications/")
    expect(all_link).to_contain_text("Все уведомления")
    settings_link = panel.locator("a[data-bell-settings]")
    expect(settings_link).to_have_attribute("href", "/me/notifications/")
    expect(settings_link).to_contain_text("Настройки")
    # п. 6: «Все уведомления» ведёт на страницу со списком
    with page.expect_navigation():
        all_link.click()
    expect(page.locator("[data-notify-list]")).to_be_visible()
    assert page.url.split("?")[0].endswith("/notifications/"), page.url


def test_e10_nightly_job_deletes_notifications_older_than_retention_and_ticket_history_stays(
        admin_page, employee, new_context):
    """Сценарий 10, п. 7: уведомление старше срока хранения (по умолчанию 90 дней) — когда проходит ночное задание,
    оно удалено; уведомление младше срока остаётся; история самой заявки остаётся в заявке (FR-338)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [member], tag)
    days = _retention_days(page)  # срок хранения, как он стоит на стенде (по умолчанию 90)
    with _default_queue(page, old_id, queue_id):
        # дано: у участника очереди есть уведомление о новой заявке
        watcher = helpers_notify.open_watcher(new_context, member)
        base = helpers_notify.bell_count(watcher)
        word, _subject, _sender = _mail_ticket()
        helpers_notify.wait_bell_count(watcher, base + 1, timeout_ms=15_000)
        number = helpers_sd.ticket_number_by_subject(page, word)
        _list(member.page)
        expect(_rows(member.page, word)).to_have_count(1)
        # когда: уведомлению на сутки меньше срока хранения и проходит ночное задание (сдвиг идёт по всему стенду)
        helpers_notify.tick(age_days=days - 1, retention=True)  # days >= 30, сдвиг от 29 суток
        _list(member.page)
        expect(_rows(member.page, word)).to_have_count(1)  # младше срока — остаётся
        # когда: уведомлению стало больше срока хранения (итоговый возраст days + 1) и снова проходит ночное задание
        result = helpers_notify.tick(age_days=2, retention=True)
        assert result["aged_rows"] >= 1, result
        assert result["retention_notifications"] >= 1, result
        # п. 7: уведомление удалено — в списке его нет, число колокольчика вернулось к прежнему
        _list(member.page)
        expect(_rows(member.page, word)).to_have_count(0)
        assert helpers_notify.bell_count(member.page) == 0  # ночное удаление стёрло все уведомления сотрудника
        # п. 7: история самой заявки осталась — в ленте карточки письмо заявителя
        card = helpers_sd.open_ticket(page, number)
        incoming = card.locator('ol[data-feed] li[data-entry][data-kind="incoming"]')
        expect(incoming).to_have_count(1)
        expect(incoming.locator("[data-entry-text]")).to_contain_text(word)
        # п. 7: уведомление младше срока ночное задание не трогает
        helpers_notify.fill(member.email, 1)
        helpers_notify.tick(retention=True)
        _list(member.page)
        expect(_fill_row(member.page, 1)).to_have_count(1)
        expect(_rows(member.page, word)).to_have_count(0)
        assert helpers_notify.bell_count(member.page) == 1


def test_e10_other_employee_notifications_by_guessed_link_refused(employee):
    """Сценарий 10, п. 8: сотрудник подбирает ссылки на чужое уведомление — получает отказ (404), чужая запись не
    меняется; каждый видит только свои (FR-342)."""
    mine, other = employee(), employee()
    helpers_notify.fill(mine.email, 2)
    helpers_notify.fill(other.email, 1)
    _list(other.page)
    foreign = _fill_row(other.page, 1)
    expect(foreign).to_have_count(1)
    foreign_id = foreign.get_attribute("data-notification")
    other_base = helpers_notify.bell_count(other.page)
    page = mine.page
    _list(page)
    own_id = _fill_row(page, 2).get_attribute("data-notification")
    assert own_id != foreign_id
    # п. 8: чужого уведомления в своём списке нет
    expect(page.locator(f'li[data-notification="{foreign_id}"]')).to_have_count(0)
    # контроль: своё уведомление по такой же ссылке открывается (302 на его адрес), а не отказывает
    own = helpers_org.direct_get(page, f"/notifications/{own_id}/open/")
    assert own.status == 302, own.status
    # когда: сотрудник открывает чужое уведомление по подобранной ссылке
    response = helpers_org.direct_get(page, f"/notifications/{foreign_id}/open/")
    # п. 8: отказ — 404, без перенаправления
    assert response.status == 404, response.status
    # то же при отметке чужого прочитанным
    marked = helpers_org.direct_post(page, f"/notifications/{foreign_id}/read/")
    assert marked.status == 404, marked.status
    # и при открытии ссылки в браузере
    shown = page.goto(f"/notifications/{foreign_id}/open/")
    assert shown is not None and shown.status == 404, shown.status if shown else None
    expect(page.locator("body")).not_to_contain_text(FILL_TEXT)
    # п. 8: чужая запись не изменилась — у владельца по-прежнему не прочитана, число прежнее
    _list(other.page)
    expect(other.page.locator(f'li[data-notification="{foreign_id}"]')).to_have_attribute("data-unread", "1")
    assert helpers_notify.bell_count(other.page) == other_base


def test_e10_empty_list_shows_you_have_no_notifications(employee):
    """Сценарий 10, п. 9: в списке нет ни одного уведомления — страница показывает «У вас нет уведомлений» (FR-319)."""
    member = employee()  # свежий сотрудник: уведомлений у него нет (§ 3.3: активация уведомлений не создаёт)
    page = member.page
    # дано/когда: страница открыта у сотрудника без уведомлений
    _list(page)
    # п. 9: пустое состояние с текстом, строк нет
    empty = page.locator('[data-empty-state="notifications"]')
    expect(empty).to_have_count(1)
    expect(empty).to_contain_text(NO_NOTIFICATIONS)
    expect(_all_rows(page)).to_have_count(0)
    # п. 9: при фильтре «Непрочитанные» пустая выборка — свой текст
    page.goto("/notifications/?f=unread")
    expect(page.locator("[data-notify-list]")).to_be_visible()
    expect(page.locator('[data-empty-state="notifications"]')).to_contain_text(NO_UNREAD)
    # контроль: после появления уведомления пустого состояния нет, а строка есть
    helpers_notify.fill(member.email, 1)
    _list(page)
    expect(page.locator('[data-empty-state="notifications"]')).to_have_count(0)
    expect(_fill_row(page, 1)).to_have_count(1)


def test_e10_opening_ticket_card_from_list_marks_all_three_unread_notifications_about_it_read(
        admin_page, employee, new_context):
    """Сценарий 10, п. 10: три непрочитанных уведомления о заявке #N (новая в очереди, назначение, ответ заявителя) —
    сотрудник открывает карточку этой заявки из списка заявок, все три отмечены прочитанными, счётчик меньше на 3;
    уведомления о другой заявке остаются непрочитанными (FR-307; предложение, подтверждается подписью)."""
    page = admin_page
    old_id, _ = helpers_sd.ensure_ready(page)
    tag = _tag()
    member = _staff(employee, tag, 1)
    queue_id, _name = _queue(page)
    _members(page, queue_id, [member], tag)
    with _default_queue(page, old_id, queue_id):
        watcher = helpers_notify.open_watcher(new_context, member)
        base = _ready(watcher)
        # дано: заявка без ответственного — «Новая заявка в очереди» (1)
        word, subject, sender = _mail_ticket()
        helpers_notify.wait_bell_count(watcher, base + 1, timeout_ms=15_000)
        # контроль: другая заявка — её уведомление не должно отметиться при открытии первой
        word_other, _subject_other, _sender_other = _mail_ticket("Не включается монитор")
        helpers_notify.wait_bell_count(watcher, base + 2, timeout_ms=15_000)
        number = helpers_sd.ticket_number_by_subject(page, word)
        # дано: администратор назначает участника ответственным — «Вам назначена заявка» (2)
        answer = helpers_org.direct_post(page, f"/tickets/{number}/assign/", {"assignee": str(member.id)})
        assert answer.status == 302, f"назначение заявки #{number} не удалось: {answer.status}"
        helpers_notify.wait_bell_count(watcher, base + 3, timeout_ms=15_000)
        # дано: заявитель отвечает письмом — «Заявитель ответил в заявке» (3)
        helpers_sd.deliver(build_mail(from_addr=sender, to=[MAILBOX], subject=f"Re: [#{number}] {subject}",
                                      text=f"Ответ заявителя {word}",
                                      message_id=f"<{secrets.token_hex(8)}@client.test>"))
        helpers_notify.wait_bell_count(watcher, base + 4, timeout_ms=15_000)
        # дано: три непрочитанных об этой заявке и одно о другой
        _list(member.page)
        about = _rows(member.page, word)
        expect(about).to_have_count(3)
        expect(about.locator("[data-unread-mark]")).to_have_count(3)
        texts = _texts(about)
        assert any(t.startswith("Новая заявка") for t in texts), texts
        assert any(t.startswith("Вам назначена заявка") for t in texts), texts
        assert any(t.startswith("Заявитель ответил") for t in texts), texts
        expect(_rows(member.page, word_other)).to_have_attribute("data-unread", "1")
        # когда: участник открывает карточку этой заявки из списка заявок
        member.page.goto("/tickets/?preset=all&q=" + word)
        link = member.page.locator(f'#tickets-grid tr[data-ticket="{number}"] [data-cell="number"] a')
        expect(link).to_have_count(1)
        link.click()  # на широком экране карточка открывается слайдером поверх списка, на узком — страницей
        expect(member.page.locator(f'[data-ticket-card][data-number="{number}"]')).to_be_visible()
        # п. 10: счётчик в другой вкладке (по соединению) стал меньше на 3
        helpers_notify.wait_bell_count(watcher, base + 1, timeout_ms=LIVE_WAIT_MS)
        # п. 10: все три отмечены прочитанными, уведомление о другой заявке — нет
        _list(member.page)
        about = _rows(member.page, word)
        expect(about).to_have_count(3)
        expect(about.locator("[data-unread-mark]")).to_have_count(0)
        expect(member.page.locator('ul[data-notifications] li[data-notification][data-unread="0"]').filter(
            has_text=word)).to_have_count(3)
        expect(_rows(member.page, word_other)).to_have_attribute("data-unread", "1")
        assert helpers_notify.bell_count(member.page) == base + 1
