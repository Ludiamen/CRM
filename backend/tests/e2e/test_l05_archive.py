"""T-6144: сценарий 5 — архив, возврат, удаление навсегда (FR-513, FR-516, FR-523, FR-524, FR-530, FR-538, FR-542).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-006.md, разделы 10–12 и 15.3–15.4):
- управляющий — администратор круга `admin_page`; правящий и читающий — `helpers_lists.make_list_editor` /
  `make_list_reader` (своя роль без прав в наборе списка); заявки заводятся письмом в ящик заявок (стандартная
  библиотека и `helpers_sd.deliver`), сотрудники видят их как участники очереди по умолчанию;
- каждый тест заводит свои списки с уникальными названиями, свои записи и свою заявку; шесть стартовых списков и общие
  настройки не меняются; `stand_shell` в файле нет; единственная команда стенда — `helpers_lists.shift` (тест срока);
- «В архив» и «Удалить навсегда» подтверждаются диалогом `dialog[data-lists-confirm]` (план: «подтверждение»;
  15.4 п. 2: `[data-action="confirm"]`); «Вернуть из архива» подтверждения не требует (в плане о нём не сказано);
- наличие записи в «Все», в поиске, в выборе поля-ссылки и в подборе заявки читается по ответу сервера: тест
  сравнивает «до» и «после» одним набором проверок (`_presence`), поэтому пустая выдача не принимается за успех;
- даты — по Москве (`ZoneInfo("Europe/Moscow")`).
"""
import re
import secrets
from datetime import datetime, timedelta
from email.header import Header
from email.mime.text import MIMEText
from email.utils import formatdate, make_msgid
from types import SimpleNamespace
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

from playwright.sync_api import expect

from tests.e2e import helpers_lists, helpers_org, helpers_sd
from tests.e2e.helpers_lists import (
    add_field, confirm_dialog, create_list, create_record, fill_record, grant_role, open_add_record, open_record,
    open_edit_record, pick, post_status, record_form, status_of, submit_record, unique_list_name, unique_word)

PART = '[data-card-part="lists-records"]'
ARCHIVED_TEXT = "Запись в архиве"
MARK = '[data-lists-page="record"] [data-lists-archived]'


# --- Свои помощники файла ---------------------------------------------------------------------------------

def _archive(page, list_id, number) -> None:
    """«В архив» на карточке с подтверждением в диалоге; ждёт кнопку «Вернуть из архива» и пометку «в архиве»."""
    open_record(page, list_id, number)
    page.locator('button[data-action="record-archive"]').click()
    confirm_dialog(page)
    expect(page.locator('button[data-action="record-restore"]')).to_be_visible()
    expect(page.locator(MARK).first).to_be_visible()


def _restore(page, list_id, number) -> None:
    """«Вернуть из архива» на карточке; ждёт кнопку «В архив»."""
    open_record(page, list_id, number)
    page.locator('button[data-action="record-restore"]').click()
    expect(page.locator('button[data-action="record-archive"]')).to_be_visible()


def _raw_mail(sender: str, subject: str, body: str) -> bytes:
    msg = MIMEText(body, "plain", "utf-8")
    msg["From"] = sender
    msg["To"] = helpers_sd.MAILBOX
    msg["Subject"] = Header(subject, "utf-8")
    msg["Date"] = formatdate()
    msg["Message-ID"] = make_msgid(domain="client.test")
    return msg.as_bytes()


def _new_ticket(admin_page) -> int:
    """Заявка письмом корпоративного заявителя; возвращает номер."""
    word = unique_word("tk")
    helpers_sd.deliver(_raw_mail(helpers_sd.requester_email(), f"Не работает принтер {word}", f"Описание {word}"))
    return helpers_sd.ticket_number_by_subject(admin_page, word)


def _link_ticket(page, number, word) -> None:
    """Привязка записи к заявке в разделе «Записи списков»: подсказка по слову названия, выбор строки, «Привязать
    запись»; ждёт строку связи с этим словом."""
    helpers_sd.open_ticket(page, number)
    field = page.locator(f'{PART} input[data-lists-picker="ticket"]')
    expect(field).to_be_visible()
    with page.expect_response(lambda r: "/lists/ticket-pick/" in r.url):
        field.fill(word)
    option = page.locator(f"{PART} ul[data-lists-pick] li[data-pick-id]").filter(has_text=word)
    expect(option).to_have_count(1)
    option.click()
    row = page.locator(f"{PART} li[data-ticket-link-id]").filter(has_text=word)
    button = page.locator(f'{PART} button[data-action="ticket-link"]')
    # контракт не говорит, уходит ли связь сразу по выбору строки или по кнопке: нажимаем кнопку, если связи ещё нет
    try:
        expect(row).to_have_count(1, timeout=1500)
    except AssertionError:
        button.click()
    expect(row).to_have_count(1)


def _suggest(page, field, url_part: str, query: str) -> str:
    """Вводит `query` в поле подсказки и возвращает тело ответа сервера на запрос, адрес которого содержит `url_part`."""
    with page.expect_response(lambda r: url_part in r.url and r.request.method == "GET") as info:
        field.fill(query)
    response = info.value
    assert response.status == 200, f"подсказка {url_part}: код {response.status}"
    return response.text()


def _world(admin_page, employee, *, editor: bool = True, referrer: bool = False, ticket: bool = False,
           title_prefix: str = "Принтер") -> SimpleNamespace:
    """Список «Оборудование» с записью; по флагам — правящий сотрудник (в наборе «Правят» и, при `referrer`, второго
    списка), второй список «Картриджи» с полем «Принтер» (запись другого списка) и записью-ссылкой, заявка.
    Правящий, если нужен заявке, — участник очереди по умолчанию."""
    mark = secrets.token_hex(3)
    word = unique_word("eq")
    world = SimpleNamespace(word=word, title=f"{title_prefix} {word}", a=create_list(admin_page, unique_list_name("Оборудование")),
                            b=None, ref_code=None, ref_number=None, ref_title=None, editor=None, ticket=None)
    world.number = create_record(admin_page, world.a, world.title)
    if referrer:
        world.b = create_list(admin_page, unique_list_name("Картриджи"))
        world.ref_code = add_field(admin_page, world.b, "Принтер", "record", target=world.a)
        world.ref_title = f"Картридж {unique_word('cr')}"
        open_add_record(admin_page, world.b)
        fill_record(admin_page, {"title": world.ref_title})
        pick(admin_page, world.ref_code, word)
        world.ref_number = submit_record(admin_page)
        assert world.ref_number, "запись-ссылка не создана"
    if editor:
        world.editor = helpers_lists.make_list_editor(employee, admin_page, world.a, full_name=f"Тест{mark} Иванов Иван")
        if referrer:
            grant_role(admin_page, world.b, "edit", world.editor.list_role_id)
        if ticket:
            queue_id, _ = helpers_sd.ensure_ready(admin_page)
            note = helpers_sd.add_queue_member(admin_page, queue_id, [world.editor.id], q=f"Тест{mark}")
            assert "уже участник" not in note, note
    if ticket:
        world.ticket = _new_ticket(admin_page)
        _link_ticket(admin_page, world.ticket, word)
    return world


def _presence(world, page) -> dict:
    """Где запись видна смотрящему `page` (правящему оба списка и видящему заявку): отбор «Все», «Все» с поиском по
    слову, отбор «Архив», сквозной поиск, выбор в поле-ссылке второго списка, подбор для привязки к заявке.
    Каждое место читается ответом сервера на этот же запрос; значение — истина, если запись показана."""
    found = {}
    row = f'#lists-grid tr[data-record-number="{world.number}"]'
    for place, query in (("all", ""), ("all_search", f"?q={world.word}"), ("archive", "?preset=archive")):
        page.goto(f"/lists/{world.a}/{query}")
        expect(page.locator('[data-lists-page="grid"]')).to_be_visible()
        found[place] = page.locator(row).count() == 1
    page.goto(f"/search/?q={world.word}")
    expect(page.locator("[data-search-page]")).to_be_visible()
    found["search"] = page.locator(f'[data-search-page] a[href="/lists/{world.a}/{world.number}/"]').count() == 1
    page.goto(f"/lists/{world.b}/add/")
    expect(page.locator('[data-lists-page="add"]')).to_be_visible()
    field = page.locator(f'[data-lists-field="{world.ref_code}"] input[data-lists-picker="record"]')
    expect(field).to_be_visible()
    found["record_pick"] = world.title in _suggest(page, field, "/pick/", world.word)
    helpers_sd.open_ticket(page, world.ticket)
    field = page.locator(f'{PART} input[data-lists-picker="ticket"]')
    expect(field).to_be_visible()
    found["ticket_pick"] = world.title in _suggest(page, field, "/lists/ticket-pick/", world.word)
    return found


VISIBLE = {"all": True, "all_search": True, "archive": False, "search": True, "record_pick": True, "ticket_pick": True}
HIDDEN = {"all": False, "all_search": False, "archive": True, "search": False, "record_pick": False,
          "ticket_pick": False}


def _history_kinds(page) -> list:
    return [li.get_attribute("data-change-kind") for li in page.locator("[data-lists-history] li[data-change-kind]").all()]


# --- Тесты ---------------------------------------------------------------------------------------------------

def test_l05_archive_after_confirm_dialog_removes_record_from_all_preset_search_record_field_choice_and_ticket_pick(
        admin_page, employee):
    """Сценарий 5, п. 1: правящий нажимает «В архив» и подтверждает — записи нет в отборе «Все», в поиске, в выборе
    поля-ссылки и в подборе заявки; она есть в отборе «Архив» (FR-523)."""
    world = _world(admin_page, employee, referrer=True, ticket=True)
    page = world.editor.page
    # п. 1: до архива запись показана во всех местах (контроль: пустая выдача не принимается за успех), в «Архиве» нет
    assert _presence(world, page) == VISIBLE
    # п. 1: «В архив», подтверждение в диалоге
    open_record(page, world.a, world.number)
    page.locator('button[data-action="record-archive"]').click()
    expect(page.locator("dialog[data-lists-confirm]")).to_be_visible()
    confirm_dialog(page)
    expect(page.locator('button[data-action="record-restore"]')).to_be_visible()
    # п. 1: записи нет в «Все», в поиске, в выборе поля-ссылки и в подборе заявки; в «Архиве» она есть
    assert _presence(world, page) == HIDDEN


def test_l05_archived_record_in_archive_preset_keeps_history_and_links(admin_page, employee):
    """Сценарий 5, п. 1 (вторая половина): запись в отборе «Архив»; её история, ссылки других записей и связь с заявкой
    сохранены (FR-523)."""
    world = _world(admin_page, employee, referrer=True, ticket=True)
    page = world.editor.page
    _archive(page, world.a, world.number)
    # п. 1: в отборе «Архив» запись со ссылкой на карточку
    page.goto(f"/lists/{world.a}/?preset=archive")
    link = page.locator(f'#lists-grid tr[data-record-number="{world.number}"] a[data-field="title"]')
    expect(link).to_have_attribute("href", f"/lists/{world.a}/{world.number}/")
    expect(link).to_contain_text(world.title)
    # п. 1: история сохранена — «Создана» и «Перенесена в архив»
    open_record(page, world.a, world.number)
    expect(page.locator('[data-lists-history] li[data-change-kind="archived"]')).to_have_count(1)
    assert "created" in _history_kinds(page)
    expect(page.locator('[data-lists-history] li[data-change-kind="archived"]')).to_contain_text("Перенесена в архив")
    # п. 1: связи сохранены — «Ссылаются на эту запись» и «Связанные заявки»
    expect(page.locator(f'[data-lists-referrers] li[data-record-ref="{world.b}:{world.ref_number}"]')).to_have_count(1)
    expect(page.locator(f'[data-lists-related-tickets] li[data-ticket-number="{world.ticket}"]')).to_have_count(1)
    # п. 1: у значения-ссылки в записи другого списка — ссылка и пометка «в архиве»
    open_record(page, world.b, world.ref_number)
    value = page.locator(f'[data-lists-value="{world.ref_code}"]')
    expect(value.locator(f'a[href="/lists/{world.a}/{world.number}/"]')).to_have_count(1)
    expect(value.locator("[data-lists-archived]")).to_have_count(1)
    # п. 1: в карточке заявки связь осталась, строка с пометкой «в архиве»
    helpers_sd.open_ticket(admin_page, world.ticket)
    row = admin_page.locator(f"{PART} li[data-ticket-link-id]").filter(has_text=world.word)
    expect(row).to_have_count(1)
    expect(row.locator("[data-lists-archived]")).to_have_count(1)


def test_l05_restore_returns_record_to_all_preset_search_and_choices(admin_page, employee):
    """Сценарий 5, п. 2: правящий нажимает «Вернуть» у записи в архиве — запись снова в «Все», в поиске и в выборе;
    из «Архива» ушла (FR-523)."""
    world = _world(admin_page, employee, referrer=True, ticket=True)
    page = world.editor.page
    _archive(page, world.a, world.number)
    # п. 2: контроль — в архиве запись нигде, кроме «Архива»
    assert _presence(world, page) == HIDDEN
    # п. 2: «Вернуть»
    _restore(page, world.a, world.number)
    # п. 2: пометки «в архиве» на карточке нет, в истории — «Возвращена из архива»
    expect(page.locator(MARK)).to_have_count(0)
    expect(page.locator('[data-lists-history] li[data-change-kind="restored"]')).to_contain_text("Возвращена из архива")
    # п. 2: запись снова в «Все», в поиске, в выборе поля-ссылки и в подборе заявки
    assert _presence(world, page) == VISIBLE


def test_l05_archived_record_card_shows_archived_mark_and_cannot_be_edited_until_restored(admin_page, employee):
    """Сценарий 5, п. 3: открытая запись в архиве — пометка «в архиве», «Изменить» нет, правка по прямой ссылке и
    прямой POST — отказ «Запись в архиве»; после «Вернуть» правка работает (FR-516, FR-523)."""
    world = _world(admin_page, employee)
    page = world.editor.page
    open_edit_record(page, world.a, world.number)
    version = record_form(page).locator('input[name="base_version"]').get_attribute("value")
    _archive(page, world.a, world.number)
    # п. 3: пометка «в архиве», кнопки «Изменить» нет
    expect(page.locator(MARK).first).to_contain_text("в архиве")
    expect(page.locator('a[data-action="record-edit"]')).to_have_count(0)
    # п. 3: правка по прямой ссылке — страница «Запись в архиве» без формы
    page.goto(f"/lists/{world.a}/{world.number}/edit/")
    expect(page.locator('[data-lists-page="archived-edit"]')).to_be_visible()
    expect(page.locator("body")).to_contain_text(ARCHIVED_TEXT)
    expect(record_form(page)).to_have_count(0)
    # п. 3: прямой POST правки — отказ «Запись в архиве», название не изменилось
    response = helpers_org.direct_post(page, f"/lists/{world.a}/{world.number}/edit/",
                                       {"title": f"Другое {world.word}", "base_version": version})
    assert response.status == 200
    body = response.text()
    assert 'data-code="record_archived"' in body and ARCHIVED_TEXT in body, "нет отказа «Запись в архиве»"
    open_record(page, world.a, world.number)
    expect(page.locator("[data-lists-record]")).to_contain_text(world.title)
    expect(page.locator("[data-lists-record]")).not_to_contain_text("Другое")
    # п. 3: после «Вернуть» кнопка «Изменить» есть, правка сохраняется
    _restore(page, world.a, world.number)
    expect(page.locator('a[data-action="record-edit"]')).to_have_count(1)
    open_edit_record(page, world.a, world.number)
    new_title = f"Новое {world.word}"
    fill_record(page, {"title": new_title})
    assert submit_record(page) == world.number
    expect(page.locator("[data-lists-record]")).to_contain_text(new_title)


def test_l05_reader_sees_no_archive_or_restore_buttons_and_direct_calls_are_denied(admin_page, employee):
    """Сценарий 5, п. 4: читающий не видит «В архив» и «Вернуть»; прямые POST — отказ 403, состояние записей не
    меняется (FR-513, FR-523)."""
    world = _world(admin_page, employee, editor=False)
    archived_title = f"Принтер {unique_word('ar')}"
    archived_number = create_record(admin_page, world.a, archived_title)
    _archive(admin_page, world.a, archived_number)
    reader = helpers_lists.make_list_reader(employee, admin_page, world.a)
    page = reader.page
    # п. 4: у записи не в архиве кнопки «В архив» нет (карточка открыта, видна «Этикетка»)
    open_record(page, world.a, world.number)
    expect(page.locator('a[data-action="record-label"]')).to_have_count(1)
    expect(page.locator('button[data-action="record-archive"]')).to_have_count(0)
    # п. 4: у записи в архиве кнопки «Вернуть из архива» нет (пометка видна)
    open_record(page, world.a, archived_number)
    expect(page.locator(MARK).first).to_be_visible()
    expect(page.locator('button[data-action="record-restore"]')).to_have_count(0)
    # п. 4: прямое обращение — отказ
    assert post_status(page, f"/lists/{world.a}/{world.number}/archive/") == 403
    assert post_status(page, f"/lists/{world.a}/{archived_number}/restore/") == 403
    # п. 4: состояние не изменилось
    page.goto(f"/lists/{world.a}/")
    expect(page.locator(f'#lists-grid tr[data-record-number="{world.number}"]')).to_have_count(1)
    expect(page.locator(f'#lists-grid tr[data-record-number="{archived_number}"]')).to_have_count(0)
    page.goto(f"/lists/{world.a}/?preset=archive")
    expect(page.locator(f'#lists-grid tr[data-record-number="{archived_number}"]')).to_have_count(1)
    expect(page.locator(f'#lists-grid tr[data-record-number="{world.number}"]')).to_have_count(0)


def test_l05_manager_sees_no_purge_button_for_non_archived_record_and_direct_purge_is_denied(admin_page, employee):
    """Сценарий 5, п. 5: у записи не в архиве управляющий не видит «Удалить навсегда», прямой POST — 403 (FR-524)."""
    world = _world(admin_page, employee, editor=False)
    archived_number = create_record(admin_page, world.a, f"Принтер {unique_word('ar')}")
    _archive(admin_page, world.a, archived_number)
    # п. 5: у записи не в архиве кнопки нет, прямой POST — отказ, запись на месте
    open_record(admin_page, world.a, world.number)
    expect(admin_page.locator('button[data-action="record-archive"]')).to_have_count(1)
    expect(admin_page.locator('button[data-action="record-purge"]')).to_have_count(0)
    assert post_status(admin_page, f"/lists/{world.a}/{world.number}/purge/") == 403
    assert status_of(admin_page, f"/lists/{world.a}/{world.number}/") == 200
    # п. 5: контроль — у записи в архиве та же кнопка есть
    open_record(admin_page, world.a, archived_number)
    expect(admin_page.locator('button[data-action="record-purge"]')).to_have_count(1)


def test_l05_purge_of_archived_record_referenced_by_other_list_is_refused_with_links_to_referring_records(
        admin_page, employee):
    """Сценарий 5, п. 6: «Удалить навсегда» у записи в архиве, на которую ссылается запись другого списка, — отказ
    «Нельзя удалить: на запись ссылаются записи: …» со ссылкой на ссылающуюся запись; запись остаётся (FR-524)."""
    world = _world(admin_page, employee, editor=False, referrer=True)
    _archive(admin_page, world.a, world.number)
    # п. 6: кнопка, подтверждение в диалоге
    admin_page.locator('button[data-action="record-purge"]').click()
    expect(admin_page.locator("dialog[data-lists-confirm]")).to_be_visible()
    confirm_dialog(admin_page)
    # п. 6: отказ с текстом и ссылкой на ссылающуюся запись «Название — №N»
    alert = admin_page.locator('[role=alert][data-code="record_referenced"]')
    expect(alert).to_be_visible()
    expect(alert).to_contain_text("Нельзя удалить: на запись ссылаются записи:")
    expect(alert).to_contain_text(f"{world.ref_title} — №{world.ref_number}")
    expect(alert.locator(f'a[href="/lists/{world.b}/{world.ref_number}/"]')).to_have_count(1)
    # п. 6: запись на месте, в архиве
    open_record(admin_page, world.a, world.number)
    expect(admin_page.locator(MARK).first).to_be_visible()
    expect(admin_page.locator("[data-lists-record]")).to_contain_text(world.title)


def test_l05_purge_of_archived_record_without_referrers_after_confirm_dialog_removes_record_history_files_and_ticket_links_and_journal_entry_has_no_field_values(
        admin_page, employee):
    """Сценарий 5, п. 7: подтверждённое удаление записи в архиве без ссылок — нет записи, истории, файлов и связи с
    заявкой; в журнале запись об удалении с названием и без значений полей (FR-524, FR-542)."""
    world = _world(admin_page, employee, editor=False, ticket=True)
    note_code = add_field(admin_page, world.a, "Заметка", "string")
    file_code = add_field(admin_page, world.a, "Скан", "file")
    marker = f"значение{unique_word('sv')}"
    open_edit_record(admin_page, world.a, world.number)
    fill_record(admin_page, {note_code: marker})
    assert submit_record(admin_page) == world.number
    file_id, _ = helpers_lists.attach_file(admin_page, world.a, world.number, file_code, b"pdf-data " + marker.encode(),
                                           "scan.txt", mime="text/plain")
    assert helpers_lists.wait_file_clean(admin_page, world.a, world.number, file_id) == "clean"
    href = admin_page.locator(f'li[data-file-id="{file_id}"] a[data-action="file-download"]').get_attribute("href")
    assert status_of(admin_page, href) == 200, "контроль: чистый файл скачивается"
    _archive(admin_page, world.a, world.number)
    # п. 7: «Удалить навсегда», подтверждение — переход на отбор «Архив» списка
    admin_page.locator('button[data-action="record-purge"]').click()
    expect(admin_page.locator("dialog[data-lists-confirm]")).to_be_visible()
    confirm_dialog(admin_page)
    admin_page.wait_for_url(re.compile(rf"/lists/{world.a}/\?preset=archive"))
    expect(admin_page.locator('[data-lists-page="grid"]')).to_be_visible()
    # п. 7: записи нет ни в «Архиве», ни в «Все»
    expect(admin_page.locator(f'#lists-grid tr[data-record-number="{world.number}"]')).to_have_count(0)
    admin_page.goto(f"/lists/{world.a}/")
    expect(admin_page.locator(f'#lists-grid tr[data-record-number="{world.number}"]')).to_have_count(0)
    # п. 7: карточка — 404 «Запись удалена», история — 404
    assert status_of(admin_page, f"/lists/{world.a}/{world.number}/") == 404
    admin_page.goto(f"/lists/{world.a}/{world.number}/")
    expect(admin_page.locator('[data-lists-page="gone"]')).to_contain_text("Запись удалена")
    assert status_of(admin_page, f"/lists/{world.a}/{world.number}/history/") == 404
    # п. 7: файл записи не скачивается
    assert status_of(admin_page, href) == 404
    # п. 7: связи с заявкой нет
    helpers_sd.open_ticket(admin_page, world.ticket)
    expect(admin_page.locator(f"{PART} li[data-ticket-link-id]").filter(has_text=world.word)).to_have_count(0)
    # п. 7: в журнале запись «lists.record_purged» с названием, без значений полей
    rows = helpers_lists.audit_rows(admin_page, "lists.record_purged")
    mine = [row for row in rows if world.title in row]
    assert len(mine) == 1, f"строки журнала об удалении записи: {rows}"
    assert not any(marker in row for row in rows), "в журнале значение поля записи"


def test_l05_archived_record_with_future_deadline_gives_no_notification_after_shift_to_reminder_day(
        admin_page, employee):
    """Сценарий 5, п. 8: у записи в архиве срок ещё не наступил; когда приходит время напоминания, уведомления нет
    (контроль: у такой же записи не в архиве уведомление есть) (FR-530)."""
    list_id = create_list(admin_page, unique_list_name("Договоры"))
    deadline_code = add_field(admin_page, list_id, "Срок", "date", deadline=True, thresholds=[3])
    editor = helpers_lists.make_list_editor(employee, admin_page, list_id)
    due = (datetime.now(ZoneInfo("Europe/Moscow")) + timedelta(days=5)).date().strftime("%d.%m.%Y")
    live_word, archived_word = unique_word("lv"), unique_word("ar")
    create_record(admin_page, list_id, f"Договор {live_word}", {deadline_code: due})
    archived = create_record(admin_page, list_id, f"Договор {archived_word}", {deadline_code: due})
    # п. 8: запись в архиве, срок через 5 дней, порог — за 3 дня
    _archive(admin_page, list_id, archived)
    # п. 8: до порога правящий уведомлений по записям не имеет
    page = editor.page

    def rows(word):
        page.goto("/notifications/")
        expect(page.locator("[data-notify-list]")).to_be_visible()
        return page.locator("ul[data-notifications] li[data-notification]").filter(has_text=word).all_inner_texts()

    assert rows(live_word) == [] and rows(archived_word) == []
    # п. 8: приходит время напоминания (срок через 3 дня) — задание работает
    result = helpers_lists.shift(2)
    assert result["days"] == 2 and result["notified"] >= 1, f"итог команды: {result}"
    # п. 8: по записи не в архиве уведомление есть, по записи в архиве — нет
    live_rows = rows(live_word)
    assert len(live_rows) == 1 and "Истекает срок" in live_rows[0], f"уведомления по живой записи: {live_rows}"
    assert rows(archived_word) == [], "уведомление по записи в архиве"


def test_l05_reader_opens_archived_record_from_label_qr_address_and_from_ticket_and_sees_archived_mark(
        admin_page, employee):
    """Сценарий 5, п. 9: читающий открывает запись в архиве по адресу из QR-кода этикетки и по ссылке из заявки —
    карточка открывается с пометкой «в архиве» (FR-523, FR-538)."""
    world = _world(admin_page, employee, editor=False, ticket=True)
    _archive(admin_page, world.a, world.number)
    mark = secrets.token_hex(3)
    reader = helpers_lists.make_list_reader(employee, admin_page, world.a, full_name=f"Тест{mark} Петров Пётр")
    queue_id, _ = helpers_sd.ensure_ready(admin_page)
    note = helpers_sd.add_queue_member(admin_page, queue_id, [reader.id], q=f"Тест{mark}")
    assert "уже участник" not in note, note
    page = reader.page
    card_path = f"/lists/{world.a}/{world.number}/"
    # п. 9: этикетка записи в архиве печатается; QR кодирует адрес карточки
    page.goto(f"{card_path}label/")
    expect(page.locator('[data-lists-page="label"]')).to_be_visible()
    img = page.locator("[data-lists-label] img[data-lists-qr]")
    expect(img).to_have_count(1)
    assert helpers_lists.qr_matches(img), "картинка QR не совпадает с генерацией для адреса из data-qr-url"
    url = img.get_attribute("data-qr-url")
    assert urlsplit(url).path == card_path, f"адрес QR: {url}"
    # п. 9: переход по адресу из QR — карточка с пометкой «в архиве»
    page.goto(urlsplit(url).path)
    expect(page.locator("[data-lists-record]")).to_contain_text(world.title)
    expect(page.locator(MARK).first).to_contain_text("в архиве")
    # п. 9: в карточке заявки строка записи с пометкой «в архиве», ссылка открывает ту же карточку
    helpers_sd.open_ticket(page, world.ticket)
    row = page.locator(f"{PART} li[data-ticket-link-id]").filter(has_text=world.word)
    expect(row).to_have_count(1)
    expect(row.locator("[data-lists-archived]")).to_have_count(1)
    row.locator(f'a[href="{card_path}"]').click()
    page.wait_for_url(re.compile(rf"{card_path}$"))
    expect(page.locator("[data-lists-record]")).to_contain_text(world.title)
    expect(page.locator(MARK).first).to_contain_text("в архиве")
