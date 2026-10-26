"""T-6146: сценарий 7 — связь записей списков с заявками (FR-523, FR-524, FR-528).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-006.md, разделы 10.2, 11.5, 11.8, 15.4):
- управляющий — администратор круга `admin_page`: он управляет списками (читает и правит любой) и видит все заявки;
  читающий — `helpers_lists.make_list_reader` плюс участник очереди по умолчанию (участник очереди видит её заявки,
  прав сервис-деска не нужно); сотрудник, не читающий ни одного списка, — новая роль без прав плюс участник очереди;
- заявки заводятся письмом в ящик заявок (стандартная библиотека и `helpers_sd.deliver`), как в срезе 005; слово темы —
  латинские буквы без цифр (поиск не принимает его за номер);
- каждый тест заводит свои списки с уникальными названиями, записи и заявки; шесть стартовых списков не трогает;
- общая настройка «очередь по умолчанию» меняется только в тесте п. 4 и возвращается в `finally`;
- подготовка вне интерфейса — только команды стенда: `e2e_poll_mailbox` (через `deliver`), `e2e_backdate`,
  `e2e_run_job anonymize_tickets`; `stand_shell` в файле нет;
- раздел заявки — `[data-card-part="lists-records"] [data-lists-ticket-section]`; подбор — `input[data-lists-picker="ticket"]`,
  `ul[data-lists-pick] li[data-pick-id]` внутри раздела; нажатие на строку подбора только выбирает, привязку делает
  `button[data-action="ticket-link"]` (CONTRACT-006, 15.5 п. 4); «Отвязать» — без подтверждения.
"""
import re
import secrets
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formataddr, formatdate, make_msgid

from playwright.sync_api import expect

from tests.e2e import helpers_lists, helpers_org, helpers_sd
from tests.e2e.helpers_kb import unique_word
from tests.e2e.helpers_sd import MAILBOX

PART = '[data-card-part="lists-records"]'
SECTION = PART + " [data-lists-ticket-section]"
INV_NAME = "Инвентарный номер"


# --- Свои помощники файла ---------------------------------------------------------------------------------

def _norm(text: str) -> str:
    return " ".join(text.split())


def _raw_mail(sender: str, subject: str, body: str) -> bytes:
    """Письмо заявителя (RFC 822) на стандартной библиотеке: тема — через `Header` (не теряет пробелов)."""
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = formataddr(("", sender))
    msg["To"] = MAILBOX
    msg["Subject"] = Header(subject, "utf-8")
    msg["Date"] = formatdate()
    msg["Message-ID"] = make_msgid(domain="client.test")
    return msg.as_bytes()


def _new_ticket(admin_page) -> tuple:
    """Заявка письмом корпоративного заявителя в очередь по умолчанию; возвращает `(номер, тема)`."""
    word = unique_word("tk")
    subject = f"Не работает принтер {word}"
    helpers_sd.deliver(_raw_mail(helpers_sd.requester_email(), subject, f"Описание сбоя {word}"))
    return helpers_sd.ticket_number_by_subject(admin_page, word), subject


def _add_to_queue(admin_page, queue_id, account, mark: str) -> None:
    note = helpers_sd.add_queue_member(admin_page, queue_id, [account.id], q=f"Тест{mark}")
    assert "уже участник" not in note, note


def _reader(admin_page, employee, queue_id, list_id, *, member: bool = True):
    """Читающий список `list_id`; `member` — участник очереди по умолчанию (видит её заявки)."""
    mark = secrets.token_hex(3)
    account = helpers_lists.make_list_reader(employee, admin_page, list_id, full_name=f"Тест{mark} Иванов Иван")
    if member:
        _add_to_queue(admin_page, queue_id, account, mark)
    return account


def _no_list_employee(admin_page, employee, queue_id):
    """Сотрудник с ролью без прав, не читающий ни одного списка; участник очереди по умолчанию."""
    mark = secrets.token_hex(3)
    _, role_name = helpers_lists.make_list_role(admin_page)
    account = employee(role=role_name, full_name=f"Тест{mark} Петров Пётр")
    _add_to_queue(admin_page, queue_id, account, mark)
    return account


def _make_list(admin_page, *, with_inventory: bool = False) -> tuple:
    """Новый список; с `with_inventory` — уникальное поле «Инвентарный номер». Возвращает `(номер, название, код поля)`."""
    name = helpers_lists.unique_list_name("Техника")
    list_id = helpers_lists.create_list(admin_page, name)
    code = ""
    if with_inventory:
        code = helpers_lists.add_field(admin_page, list_id, INV_NAME, "string", unique=True)
    return list_id, name, code


def _record(admin_page, list_id, title: str, values: dict | None = None) -> int:
    return helpers_lists.create_record(admin_page, list_id, title, values)


def _section(page):
    return page.locator(SECTION)


def _rows(page):
    return _section(page).locator("li[data-ticket-link-id]")


def _row(page, title: str):
    return _rows(page).filter(has_text=title)


def _open(page, number: int):
    """Карточка заявки страницей целиком (сотрудник её видит: корень карточки ждёт `open_ticket`)."""
    return helpers_sd.open_ticket(page, number)


def _search(page, query: str) -> None:
    """Вводит запрос в поле подбора раздела заявки; ответ ждёт вызывающий по зацепке нужной строки подбора."""
    field = _section(page).locator('input[data-lists-picker="ticket"]')
    expect(field).to_be_visible()
    field.fill(query)
    field.press("End")


def _offers(page, title: str):
    """Строки подбора (`ul[data-lists-pick] li[data-pick-id]` раздела) с названием `title`."""
    return _section(page).locator("ul[data-lists-pick] li[data-pick-id]").filter(has_text=title)


def _link(page, title: str) -> None:
    """Выбирает в подборе запись `title` (нажатие на строку только выбирает) и нажимает «Привязать запись»
    (`button[data-action="ticket-link"]`, 15.5 п. 4); ждёт строку раздела."""
    offer = _offers(page, title)
    expect(offer).to_have_count(1)
    offer.click()
    _section(page).locator('button[data-action="ticket-link"]').click()
    expect(_row(page, title)).to_have_count(1)


def _link_from_ticket(page, number: int, word: str, title: str) -> None:
    """Открывает заявку, ищет по слову и привязывает запись `title`."""
    _open(page, number)
    _search(page, word)
    _link(page, title)


def _close_ticket(page, number: int, resolution: str) -> None:
    """Закрытие заявки диалогом `ticket-close` с текстом решения; ждёт вид «закрыта»."""
    _open(page, number)
    page.locator('a[data-action="ticket-close"]').click()
    dialog = page.locator('[data-dialog="ticket-close"]')
    expect(dialog).to_be_visible()
    dialog.locator("textarea[name=resolution]").fill(resolution)
    dialog.locator("button[type=submit]").click()
    expect(page.locator(f'[data-ticket-card][data-number="{number}"]')).to_have_attribute("data-kind", "closed")


# --- Тесты ------------------------------------------------------------------------------------------------

def test_l07_ticket_card_has_list_records_section_with_link_button_for_list_reader_and_none_for_employee_reading_no_list(
        admin_page, employee):
    """Сценарий 7, п. 1: в карточке видимой заявки у читающего список — раздел «Записи списков» и кнопка «Привязать
    запись»; у сотрудника, не читающего ни одного списка, раздела нет (FR-528)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    list_id, _, _ = _make_list(admin_page)
    reader = _reader(admin_page, employee, queue_id, list_id)
    stranger = _no_list_employee(admin_page, employee, queue_id)
    number, _ = _new_ticket(admin_page)
    # п. 1: у читающего есть раздел с заголовком и кнопкой
    _open(reader.page, number)
    expect(reader.page.locator(PART)).to_have_count(1)
    expect(_section(reader.page)).to_have_count(1)
    expect(reader.page.locator(PART)).to_contain_text("Записи списков")
    expect(_section(reader.page).locator("button", has_text="Привязать запись")).not_to_have_count(0)
    expect(_section(reader.page).locator('button[data-action="ticket-link"]')).to_have_count(1)
    # контроль: сотрудник, не читающий списков, заявку видит (карточка открыта), раздела в ней нет
    card = _open(stranger.page, number)
    expect(card).to_be_visible()
    expect(stranger.page.locator(PART)).to_have_count(0)
    expect(stranger.page.locator("[data-lists-ticket-section]")).to_have_count(0)
    assert "Записи списков" not in card.inner_text()
    assert "Привязать запись" not in stranger.page.locator("body").inner_text()


def test_l07_link_search_by_title_part_or_inventory_number_finds_non_archived_records_of_read_lists_and_links_chosen(
        admin_page, employee):
    """Сценарий 7, п. 2: поиск по части названия и по инвентарному номеру находит записи не в архиве из читаемых
    списков, записи нечитаемого списка не предлагаются; выбранная запись привязана (FR-528)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    list_id, list_name, inv_code = _make_list(admin_page, with_inventory=True)
    other_id, _, _ = _make_list(admin_page)
    reader = _reader(admin_page, employee, queue_id, list_id)
    word_a, word_b = unique_word("prn"), unique_word("scn")
    inv_b = unique_word("inv")
    title_a, title_b = f"Принтер {word_a} первый", f"Сканер {word_b} второй"
    title_hidden = f"Принтер {word_a} скрытый"
    number_a = _record(admin_page, list_id, title_a, {inv_code: unique_word("inv")})
    number_b = _record(admin_page, list_id, title_b, {inv_code: inv_b})
    _record(admin_page, other_id, title_hidden)
    ticket, _ = _new_ticket(admin_page)
    _open(reader.page, ticket)
    # п. 2: часть названия (начало слова) — найдена запись читаемого списка, записи нечитаемого списка нет
    _search(reader.page, word_a[:8])
    expect(_offers(reader.page, title_a)).to_have_count(1)
    expect(_offers(reader.page, title_hidden)).to_have_count(0)
    expect(_offers(reader.page, title_b)).to_have_count(0)
    # инвентарный номер целиком — найдена запись с этим номером, прежняя выдача заменена
    _search(reader.page, inv_b)
    expect(_offers(reader.page, title_b)).to_have_count(1)
    expect(_offers(reader.page, title_a)).to_have_count(0)
    # выбранная привязана: строка ведёт на карточку записи
    _link(reader.page, title_b)
    link = _row(reader.page, title_b).locator(f'a[href="/lists/{list_id}/{number_b}/"]')
    expect(link).to_have_count(1)
    assert _norm(_row(reader.page, title_b).inner_text()).startswith(f"{title_b} — {list_name}")
    expect(_row(reader.page, title_a)).to_have_count(0)
    assert number_a != number_b
    # привязка сохранена: после перезагрузки строка на месте
    _open(reader.page, ticket)
    expect(_row(reader.page, title_b)).to_have_count(1)


def test_l07_linked_row_shows_title_and_list_opens_record_card_and_unlink_removes_link(admin_page, employee):
    """Сценарий 7, п. 3: строка «Название — Список», по нажатию — карточка записи; «Отвязать» убирает связь
    (FR-528)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    list_id, list_name, _ = _make_list(admin_page)
    reader = _reader(admin_page, employee, queue_id, list_id)
    word = unique_word("prn")
    title = f"Принтер {word} бухгалтерия"
    number = _record(admin_page, list_id, title)
    ticket, _ = _new_ticket(admin_page)
    page = reader.page
    _link_from_ticket(page, ticket, word, title)
    # п. 3: «Название — Список»
    assert f"{title} — {list_name}" in _norm(_row(page, title).inner_text())
    # нажатие открывает карточку записи
    link = _row(page, title).locator("a")
    expect(link).to_have_count(1)
    link.click()
    page.wait_for_url(re.compile(rf"/lists/{list_id}/{number}/$"))
    expect(page.locator("[data-lists-record]")).to_be_visible()
    # «Отвязать» убирает связь (раздел заменяется целиком — строки ищутся заново)
    _open(page, ticket)
    expect(_row(page, title)).to_have_count(1)
    _row(page, title).locator('button[data-action="ticket-unlink"]').click()
    expect(_rows(page)).to_have_count(0)
    _open(page, ticket)
    expect(_rows(page)).to_have_count(0)
    # запись осталась: карточка открывается
    helpers_lists.open_record(page, list_id, number)


def test_l07_record_card_related_tickets_show_number_subject_state_only_for_tickets_viewer_sees(admin_page, employee):
    """Сценарий 7, п. 4: «Связанные заявки» в карточке записи — «#N Тема, состояние» только по заявкам, которые
    смотрящий видит сам (FR-528)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    list_id, _, _ = _make_list(admin_page)
    viewer = _reader(admin_page, employee, queue_id, list_id)
    word = unique_word("prn")
    title = f"Принтер {word} склад"
    number = _record(admin_page, list_id, title)
    # видимая заявка — в очереди по умолчанию, где viewer участник
    visible, visible_subject = _new_ticket(admin_page)
    # невидимая заявка — в другой очереди, где viewer не участник (очередь по умолчанию меняется на время письма)
    other_queue = helpers_org.create_unit(admin_page, helpers_org.unique_name("queue"))
    helpers_sd.mark_queue(admin_page, other_queue)
    helpers_sd.set_default_queue(admin_page, other_queue)
    try:
        hidden, hidden_subject = _new_ticket(admin_page)
    finally:
        helpers_sd.set_default_queue(admin_page, queue_id)
    # контроль видимости: viewer открывает видимую заявку, а невидимой не видит
    _open(viewer.page, visible)
    assert helpers_lists.status_of(viewer.page, f"/tickets/{hidden}/") == 404
    # управляющий привязывает обе заявки к записи
    for ticket in (visible, hidden):
        _link_from_ticket(admin_page, ticket, word, title)
    # контроль: управляющему в карточке записи видны обе
    helpers_lists.open_record(admin_page, list_id, number)
    related = admin_page.locator("[data-lists-related-tickets]")
    expect(related.locator("li[data-ticket-number]")).to_have_count(2)
    # п. 4: viewer видит одну — «#N Тема, состояние»
    helpers_lists.open_record(viewer.page, list_id, number)
    related = viewer.page.locator("[data-lists-related-tickets]")
    expect(related).to_be_visible()
    line = related.locator(f'li[data-ticket-number="{visible}"]')
    expect(line).to_have_count(1)
    assert re.fullmatch(rf"#{visible} {re.escape(_norm(visible_subject))}, \S.*", _norm(line.inner_text())), \
        _norm(line.inner_text())
    expect(related.locator(f'li[data-ticket-number="{hidden}"]')).to_have_count(0)
    expect(related.locator("li[data-ticket-number]")).to_have_count(1)
    assert hidden_subject not in related.inner_text()


def test_l07_link_keeps_number_and_subject_after_ticket_anonymized_by_term(admin_page, employee):
    """Сценарий 7, п. 5: заявка обезличена по сроку хранения — связь остаётся, в карточке записи видны номер и тема
    (FR-528; SPEC-003 FR-290)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    list_id, _, _ = _make_list(admin_page)
    reader = _reader(admin_page, employee, queue_id, list_id)
    word = unique_word("prn")
    title = f"Принтер {word} приёмная"
    number = _record(admin_page, list_id, title)
    ticket, subject = _new_ticket(admin_page)
    _link_from_ticket(reader.page, ticket, word, title)
    _close_ticket(admin_page, ticket, f"Решено {unique_word('res')}")
    admin_page.goto("/servicedesk/")
    form = admin_page.locator('form[data-form="servicedesk-settings"]')
    expect(form).to_be_visible()
    years = int(form.locator("input[name=retention_years]").input_value())
    # дано: срок хранения вышел, ночное обезличивание выполнено
    helpers_sd.backdate("ticket", ticket, "closed_at", years * 366 + 20)
    helpers_sd.run_job("anonymize_tickets")
    card = helpers_sd.open_ticket(admin_page, ticket)
    assert "обезличено" in helpers_sd.field_text(card, "requester-email")  # контроль: заявка обезличена
    # п. 5: связь на месте, номер и тема остались
    helpers_lists.open_record(reader.page, list_id, number)
    line = reader.page.locator(f'[data-lists-related-tickets] li[data-ticket-number="{ticket}"]')
    expect(line).to_have_count(1)
    text = _norm(line.inner_text())
    assert f"#{ticket}" in text and _norm(subject) in text, text


def test_l07_archived_record_not_offered_in_link_search_and_already_linked_shown_with_archived_mark(
        admin_page, employee):
    """Сценарий 7, п. 6: запись в архиве в подборе не предлагается; уже привязанная показана с пометкой «в архиве»
    (FR-523, FR-528)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    list_id, _, _ = _make_list(admin_page)
    reader = _reader(admin_page, employee, queue_id, list_id)
    word = unique_word("prn")
    linked_title = f"Принтер {word} старый"
    archived_title = f"Принтер {word} архивный"
    live_title = f"Принтер {word} живой"
    linked_no = _record(admin_page, list_id, linked_title)
    archived_no = _record(admin_page, list_id, archived_title)
    _record(admin_page, list_id, live_title)
    ticket, _ = _new_ticket(admin_page)
    page = reader.page
    # дано: запись привязана до архива (запись в архиве не привязывается), затем обе записи — в архиве
    _link_from_ticket(page, ticket, word, linked_title)
    helpers_lists.archive_record(admin_page, list_id, linked_no)
    helpers_lists.archive_record(admin_page, list_id, archived_no)
    # п. 6: уже привязанная показана с пометкой «в архиве»
    _open(page, ticket)
    row = _row(page, linked_title)
    expect(row).to_have_count(1)
    expect(row.locator("[data-lists-archived]")).to_contain_text("в архиве")
    # в подборе предложена только живая запись; записи в архиве нет
    _search(page, word)
    expect(_offers(page, live_title)).to_have_count(1)
    expect(_offers(page, archived_title)).to_have_count(0)
    expect(_offers(page, linked_title)).to_have_count(0)


def test_l07_purged_record_link_disappears_from_ticket_card(admin_page, employee):
    """Сценарий 7, п. 7: запись удалена навсегда — связь исчезла из карточки заявки (FR-524, FR-528)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    list_id, _, _ = _make_list(admin_page)
    word = unique_word("prn")
    title = f"Принтер {word} списанный"
    number = _record(admin_page, list_id, title)
    ticket, _ = _new_ticket(admin_page)
    _link_from_ticket(admin_page, ticket, word, title)
    # дано: запись в архиве и удалена навсегда управляющим
    helpers_lists.archive_record(admin_page, list_id, number)
    _open(admin_page, ticket)
    expect(_row(admin_page, title)).to_have_count(1)  # контроль: в архиве связь ещё есть
    helpers_lists.open_record(admin_page, list_id, number)
    admin_page.locator('button[data-action="record-purge"]').click()
    helpers_lists.confirm_dialog(admin_page)
    admin_page.wait_for_url(re.compile(rf"/lists/{list_id}/\?preset=archive"))
    # п. 7: строки связи в карточке заявки нет
    _open(admin_page, ticket)
    expect(_section(admin_page)).to_have_count(1)
    expect(_rows(admin_page)).to_have_count(0)
    assert title not in _section(admin_page).inner_text()
    assert helpers_lists.status_of(admin_page, f"/lists/{list_id}/{number}/") == 404


def test_l07_non_reader_of_list_does_not_see_linked_record_of_that_list_on_ticket_card(admin_page, employee):
    """Сценарий 7, п. 8: сотрудник, не читающий список, не видит в карточке заявки связанную запись этого списка
    (FR-528)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    read_id, _, _ = _make_list(admin_page)
    closed_id, _, _ = _make_list(admin_page)
    employee_page = _reader(admin_page, employee, queue_id, read_id).page
    word = unique_word("prn")
    title_read, title_closed = f"Принтер {word} открытый", f"Принтер {word} закрытый"
    number_read = _record(admin_page, read_id, title_read)
    _record(admin_page, closed_id, title_closed)
    ticket, _ = _new_ticket(admin_page)
    for title in (title_read, title_closed):
        _open(admin_page, ticket)
        _search(admin_page, word)
        _link(admin_page, title)
    # контроль: управляющему видны обе записи
    _open(admin_page, ticket)
    expect(_rows(admin_page)).to_have_count(2)
    # п. 8: сотруднику — только запись читаемого списка
    _open(employee_page, ticket)
    expect(_section(employee_page)).to_have_count(1)
    expect(_row(employee_page, title_read)).to_have_count(1)
    expect(_row(employee_page, title_read).locator(f'a[href="/lists/{read_id}/{number_read}/"]')).to_have_count(1)
    expect(_rows(employee_page)).to_have_count(1)
    expect(_section(employee_page).locator(f'a[href^="/lists/{closed_id}/"]')).to_have_count(0)
    assert title_closed not in employee_page.locator("body").inner_text()


def test_l07_employee_not_seeing_ticket_gets_same_answer_as_missing_ticket_on_direct_link_request(
        admin_page, employee):
    """Сценарий 7, п. 9: сотрудник, не видящий заявку, по прямой ссылке привязки получает тот же отказ, что и для
    несуществующей заявки (FR-528; SPEC-003 FR-236)."""
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    list_id, _, _ = _make_list(admin_page)
    outsider = _reader(admin_page, employee, queue_id, list_id, member=False)
    insider = _reader(admin_page, employee, queue_id, list_id)
    word = unique_word("prn")
    title = f"Принтер {word} секретный"
    _record(admin_page, list_id, title)
    ticket, subject = _new_ticket(admin_page)
    missing = ticket + 1_000_000
    # номер записи в подборе (`li[data-pick-id]` — `Record.pk`, раздел 11.8) берётся у управляющего, привязка не делается
    _open(admin_page, ticket)
    _search(admin_page, word)
    offer = _offers(admin_page, title)
    expect(offer).to_have_count(1)
    record_pk = offer.get_attribute("data-pick-id")
    assert record_pk and record_pk.isdigit(), record_pk
    page = outsider.page
    page.goto("/lists/")  # страница с сессией и кукой для прямых запросов
    # контроль: заявку не видит ни карточка, ни подбор; участнику очереди подбор отвечает 200
    assert helpers_lists.status_of(page, f"/tickets/{ticket}/") == 404
    pick_path = "/lists/ticket-pick/?ticket={}&q=" + word
    assert helpers_lists.status_of(insider.page, pick_path.format(ticket)) == 200
    # п. 9: подбор и привязка по невидимой заявке — 404, как по несуществующей; данных заявки и записи в ответе нет
    seen = helpers_org.direct_get(page, pick_path.format(ticket))
    gone = helpers_org.direct_get(page, pick_path.format(missing))
    assert (seen.status, gone.status) == (404, 404), (seen.status, gone.status)
    linked = helpers_org.direct_post(page, "/lists/ticket-links/", {"ticket": ticket, "record": record_pk})
    absent = helpers_org.direct_post(page, "/lists/ticket-links/", {"ticket": missing, "record": record_pk})
    assert (linked.status, absent.status) == (404, 404), (linked.status, absent.status)
    for body in (seen.text(), gone.text(), linked.text(), absent.text()):
        assert subject not in body and title not in body
    # связь не создана: у управляющего в карточке заявки строк нет
    _open(admin_page, ticket)
    expect(_section(admin_page)).to_have_count(1)
    expect(_rows(admin_page)).to_have_count(0)
