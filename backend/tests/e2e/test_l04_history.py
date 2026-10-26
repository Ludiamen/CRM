"""T-6143: сценарий 4 — история изменений записи: создание, правка, файлы, архив, загрузка таблицей, скрытое поле,
неизменяемость, уволенный автор, отказ не читающему (FR-509, FR-514, FR-522, FR-524, FR-534).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-006.md):
- управляющий — администратор круга `admin_page`; правящий — `helpers_lists.make_list_editor`; читающий —
  `make_list_reader`; сотрудник без прав на списки — сотрудник с новой ролью без прав (`make_list_role`);
- каждый тест заводит свои списки с уникальными названиями и шесть стартовых не трогает (решение 56); общих настроек
  тесты файла не меняют; сброса стенда, команд стенда и `stand_shell` в файле нет;
- история — `[data-lists-history]` карточки: строки `li[data-change-kind]` новыми сверху (5.4, 11.6), изменения —
  `[data-change-field]` с `[data-field="before"]` и `[data-field="after"]`; тексты — раздел 12.4 («Создана»,
  «Перенесена в архив», «Возвращена из архива», «Изменено загрузкой», «Добавлен файл», «Удалён файл»);
- время показа — по Москве (UTC+3 без перехода на летнее время), хостовой пояс не используется;
- подтверждения (CONTRACT-006, 15.5 п. 1): «В архив» — с диалогом `dialog[data-lists-confirm][open]`; «Вернуть из архива»
  и «Удалить» у файла — без подтверждения.
"""
import re
from datetime import datetime, timedelta, timezone

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_lists, helpers_org
from tests.e2e.helpers_lists import (
    add_field, attach_file, confirm_dialog, create_list, create_record, files_block, open_edit_record, open_record,
    open_settings, pick, status_of, submit_record, unique_list_name, unique_word, wait_file_clean)

MOSCOW = timezone(timedelta(hours=3))
SHOWN_TIME = re.compile(r"(\d{2})\.(\d{2})\.(\d{4}) (\d{2}):(\d{2})")
_HISTORY = "[data-lists-history]"


# --- Помощники файла --------------------------------------------------------------------------------------------

def _rows(page):
    """Строки истории карточки по порядку показа (новые сверху)."""
    return page.locator(f"{_HISTORY} li[data-change-kind]")


def _kinds(page, count: int) -> list:
    """Виды строк истории по порядку; сначала ждёт, что строк ровно `count` (ожидание, не разовое чтение)."""
    expect(_rows(page)).to_have_count(count)
    return [row.get_attribute("data-change-kind") for row in _rows(page).all()]


def _change(row, code: str):
    """Изменение поля `code` внутри строки истории."""
    return row.locator(f'[data-change-field="{code}"]')


def _now_moscow() -> datetime:
    return datetime.now(MOSCOW).replace(tzinfo=None)


def _shown_time(row) -> datetime:
    """Время строки истории `time[data-at]` (текст «ДД.ММ.ГГГГ ЧЧ:ММ» по Москве) как наивное время Москвы."""
    stamp = row.locator("time[data-at]")
    expect(stamp).to_have_count(1)
    found = SHOWN_TIME.fullmatch(stamp.inner_text().strip())
    assert found, f"время строки истории не в виде «ДД.ММ.ГГГГ ЧЧ:ММ»: {stamp.inner_text()!r}"
    day, month, year, hour, minute = (int(x) for x in found.groups())
    return datetime(year, month, day, hour, minute)


def _archive(page, list_id, number) -> None:
    """«В архив» на карточке с подтверждением в диалоге (15.5 п. 1); ждёт «Вернуть» и пометку «в архиве»."""
    open_record(page, list_id, number)
    restore = page.locator('button[data-action="record-restore"]')
    page.locator('button[data-action="record-archive"]').click()
    confirm_dialog(page)
    expect(restore).to_be_visible()
    expect(page.locator('[data-lists-page="record"] [data-lists-archived]').first).to_be_visible()


def _restore(page, list_id, number) -> None:
    """«Вернуть» на карточке записи в архиве (без подтверждения, 15.5 п. 1); ждёт «В архив» и исчезновение пометки
    «в архиве»."""
    open_record(page, list_id, number)
    archive = page.locator('button[data-action="record-archive"]')
    page.locator('button[data-action="record-restore"]').click()
    expect(archive).to_be_visible()
    expect(page.locator('[data-lists-page="record"] [data-lists-archived]')).to_have_count(0)


def _dismiss(page, user_id) -> None:
    """Увольняет сотрудника в его карточке `/staff/<id>/` (образец test_o07): диалог, подтверждение, отметка."""
    page.goto(f"/staff/{user_id}/")
    card = page.locator(f'[data-card][data-user-id="{user_id}"]')
    card.locator('[data-action="dismiss"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(card.locator("[data-dismissed-badge]")).to_be_visible()


def _employee_name(tag: str, surname: str) -> str:
    """ФИО с уникальным латинским словом `tag` (по нему сотрудника находит подсказка выбора)."""
    return f"{surname} {tag} Иванович"


def _write(page, method: str, path: str) -> int:
    """Прямой запрос `method` с токеном CSRF и заголовками портала, без переходов; код ответа."""
    origin = helpers_org.PORTAL_URL.split("/", 3)
    origin = "/".join(origin[:3])
    return page.request.fetch(path, method=method, max_redirects=0, headers={
        "X-CSRFToken": helpers_org.csrf_token(page), "Referer": origin + "/", "Origin": origin}).status


def _import_csv(page, list_id, content: bytes, name: str, codes: list) -> None:
    """Загрузка таблицы через интерфейс до итога: «Загрузить из таблицы» → файл → сопоставление (столбец N — код из
    `codes`, `title` — «Название») → «Проверить» → «Загрузить»; ждёт страницу итога."""
    page.goto(f"/lists/{list_id}/")
    page.locator('[data-lists-page="grid"] a[data-action="import"]').first.click()  # кнопка бывает и в пустом состоянии
    page.wait_for_url(re.compile(rf"/lists/{list_id}/import/$"))
    expect(page.locator('[data-lists-page="import"]')).to_be_visible()
    form = page.locator('[data-lists-page="import"] form:has(input[type=file][name="file"])')
    form.locator('input[type=file][name="file"]').set_input_files({"name": name, "mimeType": "text/csv",
                                                                   "buffer": content})
    form.locator("button[type=submit]:not([data-action])").click()
    expect(page.locator('[data-lists-page="mapping"]')).to_be_visible()
    for index, code in enumerate(codes):
        page.locator(f'select[name="map.{index}"][data-lists-map-column="{index}"]').select_option(value=code)
    page.locator('[data-lists-page="mapping"] form button[type=submit]:not([data-action])').click()
    expect(page.locator('[data-lists-page="preview"]')).to_be_visible()


# --- Тесты ---------------------------------------------------------------------------------------------------

def test_l04_history_first_row_is_created_with_author_name_and_time(admin_page, employee):
    """Сценарий 4, п. 1: запись создана — в истории первая (и единственная) строка «создана» с именем автора и временем
    по Москве, без отметки «уволен» и «создана загрузкой»; тот же ответ даёт фрагмент `…/history/` (FR-522)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Ноутбуки"))
    editor = helpers_lists.make_list_editor(employee, page, list_id, full_name=_employee_name(unique_word("aut"), "Автор"))
    title = f"Ноутбук {unique_word('nb')}"
    before = _now_moscow().replace(second=0, microsecond=0)
    number = create_record(editor.page, list_id, title)
    after = _now_moscow()
    # п. 1: история открыта в карточке — одна строка «создана»
    open_record(editor.page, list_id, number)
    assert _kinds(editor.page, 1) == ["created"]
    row = _rows(editor.page).first
    expect(row).to_contain_text("Создана")
    expect(row.locator("[data-via-import]")).to_have_count(0)
    # п. 1: имя автора — ФИО правящего, без отметки «уволен»
    expect(row).to_contain_text(editor.full_name)
    expect(row.locator('[data-dismissed="true"]')).to_have_count(0)
    # п. 1: время — московское, в пределах нескольких минут вокруг создания (минутная точность показа)
    shown = _shown_time(row)
    assert before - timedelta(minutes=3) <= shown <= after + timedelta(minutes=3), \
        f"время создания {shown} вне окна {before}…{after} по Москве"
    # п. 1: адрес фрагмента истории отвечает 200 и называет ту же строку
    assert status_of(editor.page, f"/lists/{list_id}/{number}/history/") == 200
    response = editor.page.request.get(f"/lists/{list_id}/{number}/history/")
    assert "Создана" in response.text() and editor.full_name in response.text()


def test_l04_assignee_and_state_change_is_one_entry_with_author_time_and_two_was_became_rows_with_full_names(
        admin_page, employee):
    """Сценарий 4, п. 2: «За кем закреплено» с Иванова на Петрова и «Состояние» с «На складе» на «В работе» одним
    сохранением — одна запись «изменена» с автором и временем и двумя строками «поле: было → стало»; сотрудники
    показаны ФИО (FR-522)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Ноутбуки"))
    assignee = add_field(page, list_id, "За кем закреплено", "person")
    state = add_field(page, list_id, "Состояние", "choice")
    helpers_lists.set_choices(page, list_id, state, ["На складе", "В работе"])
    editor = helpers_lists.make_list_editor(employee, page, list_id, full_name=_employee_name(unique_word("aut"), "Автор"))
    ivanov_tag, petrov_tag = unique_word("ivn"), unique_word("ptr")
    ivanov = employee(full_name=_employee_name(ivanov_tag, "Иванов"))
    petrov = employee(full_name=_employee_name(petrov_tag, "Петров"))
    ep = editor.page
    # исходное состояние: записан Иванов, «На складе»
    helpers_lists.open_add_record(ep, list_id)
    helpers_lists.fill_record(ep, {"title": f"Ноутбук {unique_word('nb')}"})
    pick(ep, assignee, ivanov_tag)
    helpers_lists.choose(ep, state, "На складе")
    number = submit_record(ep)
    assert number
    # п. 2: одно сохранение меняет оба поля
    open_edit_record(ep, list_id, number)
    box = ep.locator(f'[data-lists-selected="{assignee}"]')
    box.locator('button[data-action="pick-remove"]').click()
    expect(box.locator("li[data-selected-id]")).to_have_count(0)
    pick(ep, assignee, petrov_tag)
    helpers_lists.choose(ep, state, "В работе")
    before = _now_moscow().replace(second=0, microsecond=0)
    assert submit_record(ep) == number
    after = _now_moscow()
    # п. 2: одна запись «изменена» над строкой «создана», новые сверху
    open_record(ep, list_id, number)
    assert _kinds(ep, 2) == ["changed", "created"]
    row = _rows(ep).first
    expect(row).to_contain_text("Изменена")
    expect(row).to_contain_text(editor.full_name)
    shown = _shown_time(row)
    assert before - timedelta(minutes=3) <= shown <= after + timedelta(minutes=3), f"время правки {shown}"
    # п. 2: ровно две строки «поле: было → стало»
    expect(row.locator("[data-change-field]")).to_have_count(2)
    who = _change(row, assignee)
    expect(who).to_contain_text("За кем закреплено")
    expect(who.locator('[data-field="before"]')).to_contain_text(ivanov.full_name)
    expect(who.locator('[data-field="after"]')).to_contain_text(petrov.full_name)
    expect(who.locator('[data-field="before"]')).not_to_contain_text(petrov.full_name)
    expect(who.locator('[data-field="after"]')).not_to_contain_text(ivanov.full_name)
    how = _change(row, state)
    expect(how).to_contain_text("Состояние")
    expect(how.locator('[data-field="before"]')).to_contain_text("На складе")
    expect(how.locator('[data-field="after"]')).to_contain_text("В работе")


def test_l04_added_and_removed_file_give_file_added_and_file_removed_rows(admin_page):
    """Сценарий 4, п. 3: файл добавлен и удалён — строки «добавлен файл …» и «удалён файл …» с именем файла и названием
    поля (FR-522)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Ноутбуки"))
    code = add_field(page, list_id, "Документ", "file")
    number = create_record(page, list_id, f"Ноутбук {unique_word('nb')}")
    file_name = f"akt-{unique_word('f')}.txt"
    # п. 3: файл добавлен
    file_id, _ = attach_file(page, list_id, number, code, b"history acceptance file", file_name, mime="text/plain")
    assert wait_file_clean(page, list_id, number, file_id) == "clean"
    assert _kinds(page, 2) == ["file_added", "created"]
    added = _rows(page).first
    expect(added).to_contain_text("Добавлен файл")
    expect(added).to_contain_text(file_name)
    expect(added).to_contain_text("Документ")
    # п. 3: файл удалён — новая строка над прежними
    block = files_block(page, code)
    row = page.locator(f'li[data-file-id="{file_id}"]')
    block.locator('button[data-action="file-delete"]').click()  # без подтверждения (15.5 п. 1)
    expect(row).to_have_count(0)
    open_record(page, list_id, number)
    assert _kinds(page, 3) == ["file_removed", "file_added", "created"]
    removed = _rows(page).first
    expect(removed).to_contain_text("Удалён файл")
    expect(removed).to_contain_text(file_name)
    expect(removed).to_contain_text("Документ")
    # п. 3: прежняя строка «добавлен файл» не исчезла и не изменилась
    expect(_rows(page).nth(1)).to_contain_text("Добавлен файл")
    expect(_rows(page).nth(1)).to_contain_text(file_name)


def test_l04_archive_restore_and_browser_table_import_give_archived_restored_and_changed_by_import_rows(admin_page):
    """Сценарий 4, п. 4: запись отправлена в архив и возвращена, затем загружена таблицей (то же уникальное значение,
    другое значение поля) — строки «в архив», «возвращена», «изменено загрузкой» (FR-522, FR-534)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Ноутбуки"))
    inventory = add_field(page, list_id, "Инвентарный номер", "string", unique=True)
    model = add_field(page, list_id, "Модель", "string")
    tag = unique_word("inv")
    title = f"Ноутбук {unique_word('nb')}"
    number = create_record(page, list_id, title, {inventory: tag, model: "Модель А"})
    # п. 4: «в архив» и «возвращена»
    _archive(page, list_id, number)
    _restore(page, list_id, number)
    # п. 4: загрузка таблицей — запись с тем же инвентарным номером получает другую модель
    content = f"Название,Инвентарный номер,Модель\n{title},{tag},Модель Б\n".encode()
    _import_csv(page, list_id, content, f"update-{tag}.csv", ["title", inventory, model])
    preview = page.locator('tr[data-import-row="2"][data-result="will_update"]')
    expect(preview).to_have_count(1)
    expect(preview.locator('[data-field="number"]')).to_contain_text(str(number))
    page.locator('button[data-action="import-confirm"]').click()
    expect(page.locator('[data-lists-page="summary"]')).to_be_visible()
    expect(page.locator('[data-import-summary="updated"]')).to_contain_text("1")
    # п. 4: история — «изменено загрузкой», «возвращена», «в архив», «создана» (новые сверху)
    open_record(page, list_id, number)
    assert _kinds(page, 4) == ["imported", "restored", "archived", "created"]
    rows = _rows(page)
    expect(rows.nth(0)).to_contain_text("Изменено загрузкой")
    expect(rows.nth(1)).to_contain_text("Возвращена из архива")
    expect(rows.nth(2)).to_contain_text("Перенесена в архив")
    expect(rows.nth(3)).to_contain_text("Создана")
    changed = _change(rows.nth(0), model)
    expect(changed.locator('[data-field="before"]')).to_contain_text("Модель А")
    expect(changed.locator('[data-field="after"]')).to_contain_text("Модель Б")


def test_l04_hidden_field_rows_stay_in_history_and_field_shown_again_after_show(admin_page):
    """Сценарий 4, п. 5: поле скрыто — прежние строки истории по нему остаются (с прежними «было → стало»), значения
    в карточке нет; после «Показать» поле снова видно в карточке (FR-509, FR-522)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Ноутбуки"))
    code = add_field(page, list_id, "Модель", "string")
    number = create_record(page, list_id, f"Ноутбук {unique_word('nb')}", {code: "Старая модель"})
    open_edit_record(page, list_id, number)
    helpers_lists.fill_record(page, {code: "Новая модель"})
    assert submit_record(page) == number
    row_in_grid = page.locator(f'[data-lists-fields-grid] tr[data-field-code="{code}"]')
    # до скрытия: значение в карточке и строка истории
    open_record(page, list_id, number)
    expect(page.locator(f'[data-lists-value="{code}"]')).to_contain_text("Новая модель")
    # п. 5: «Скрыть» — вместо неё «Показать»
    open_settings(page, list_id, "fields")
    row_in_grid.locator('button[data-action="field-hide"]').click()
    expect(row_in_grid.locator('button[data-action="field-show"]')).to_be_visible()
    # п. 5: в карточке поля нет, строки истории по нему остаются с прежними значениями
    open_record(page, list_id, number)
    expect(page.locator(f'[data-lists-value="{code}"]')).to_have_count(0)
    assert _kinds(page, 2) == ["changed", "created"]
    kept = _change(_rows(page).first, code)
    expect(kept).to_have_count(1)
    expect(kept.locator('[data-field="before"]')).to_contain_text("Старая модель")
    expect(kept.locator('[data-field="after"]')).to_contain_text("Новая модель")
    # п. 5: «Показать» — поле снова видно в карточке со своим значением, история прежняя
    open_settings(page, list_id, "fields")
    row_in_grid.locator('button[data-action="field-show"]').click()
    expect(row_in_grid.locator('button[data-action="field-hide"]')).to_be_visible()
    open_record(page, list_id, number)
    expect(page.locator(f'[data-lists-value="{code}"]')).to_contain_text("Новая модель")
    assert _kinds(page, 2) == ["changed", "created"]
    expect(_change(_rows(page).first, code)).to_have_count(1)


def test_l04_history_has_no_edit_or_delete_action_and_disappears_only_with_purged_record(admin_page):
    """Сценарий 4, п. 6: в истории нет кнопок и ссылок правки и удаления; прямые изменяющие обращения отклонены, строки
    на месте; история исчезает только вместе с записью при «Удалить навсегда», у соседней записи остаётся (FR-522,
    FR-524)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Ноутбуки"))
    number = create_record(page, list_id, f"Ноутбук {unique_word('nb')}")
    neighbour = create_record(page, list_id, f"Ноутбук {unique_word('nb')}")
    _archive(page, list_id, number)
    assert _kinds(page, 2) == ["archived", "created"]
    history = page.locator(_HISTORY)
    # п. 6: в истории нет действий, кроме «Показать ещё»
    expect(history.locator("form, input, textarea, select")).to_have_count(0)
    expect(history.locator('button:not([data-action="more"])')).to_have_count(0)
    expect(history.locator('a[data-action], a[href*="edit"], a[href*="delete"], a[href*="remove"]')).to_have_count(0)
    # п. 6: прямые изменяющие обращения к истории отклонены (не успех и не переход), строки не изменились
    base = f"/lists/{list_id}/{number}/history/"
    for method in ("POST", "PUT", "PATCH", "DELETE"):
        assert _write(page, method, base) >= 400, f"{method} {base} принят"
    for tail in ("1/", "1/edit/", "1/delete/"):
        for method in ("POST", "DELETE"):
            assert _write(page, method, base + tail) >= 400, f"{method} {base + tail} принят"
    open_record(page, list_id, number)
    assert _kinds(page, 2) == ["archived", "created"]
    # п. 6: «Удалить навсегда» (запись в архиве, управляющий) — запись и история исчезли
    page.locator('button[data-action="record-purge"]').click()
    confirm_dialog(page)
    page.wait_for_url(re.compile(rf"/lists/{list_id}/\?preset=archive"))
    assert status_of(page, f"/lists/{list_id}/{number}/") == 404
    assert status_of(page, base) == 404
    # п. 6: история соседней записи на месте
    open_record(page, list_id, neighbour)
    assert _kinds(page, 1) == ["created"]


def test_l04_dismissed_author_signed_with_full_name_and_dismissed_mark(admin_page, employee):
    """Сценарий 4, п. 7: автор правки уволен — в истории он подписан ФИО с пометкой «уволен» (во всех своих строках);
    у строки действующего автора пометки нет (FR-522; SPEC-002 FR-127)."""
    page = admin_page
    list_id = create_list(page, unique_list_name("Ноутбуки"))
    editor = helpers_lists.make_list_editor(employee, page, list_id, full_name=_employee_name(unique_word("aut"), "Бывший"))
    ep = editor.page
    number = create_record(ep, list_id, f"Ноутбук {unique_word('nb')}")
    open_edit_record(ep, list_id, number)
    helpers_lists.fill_record(ep, {"title": f"Ноутбук {unique_word('nb')}"})
    assert submit_record(ep) == number
    # правка действующего администратора над правкой будущего уволенного
    open_edit_record(page, list_id, number)
    helpers_lists.fill_record(page, {"title": f"Ноутбук {unique_word('nb')}"})
    assert submit_record(page) == number
    _dismiss(page, editor.id)
    # п. 7: строки уволенного — с ФИО и пометкой, строка действующего администратора — без неё
    open_record(page, list_id, number)
    assert _kinds(page, 3) == ["changed", "changed", "created"]
    rows = _rows(page)
    expect(rows.nth(0).locator('[data-dismissed="true"]')).to_have_count(0)
    expect(rows.nth(0)).not_to_contain_text(editor.full_name)
    for index in (1, 2):
        mark = rows.nth(index).locator('[data-dismissed="true"]')
        expect(mark).to_have_count(1)
        expect(mark).to_contain_text(editor.full_name)
        expect(mark).to_contain_text("уволен")


def test_l04_non_reader_opening_history_by_direct_link_gets_same_answer_as_missing_record(admin_page, employee):
    """Сценарий 4, п. 8: сотрудник, не читающий список, открывает историю записи по прямой ссылке — отказ 404, как у
    несуществующей записи и несуществующего списка, без данных записи; читающий тот же адрес открывает (FR-514)."""
    page = admin_page
    list_name = unique_list_name("Секретный")
    list_id = create_list(page, list_name)
    title = f"Запись {unique_word('sec')}"
    number = create_record(page, list_id, title)
    reader = helpers_lists.make_list_reader(employee, page, list_id)
    no_rights = employee(role=helpers_lists.make_list_role(page)[1])
    staff = employee()                                    # «Сотрудник ИТ»: читает стартовые списки, наш — нет
    history = f"/lists/{list_id}/{number}/history/"
    # контроль: читающий тот же адрес открывает и видит строку «создана»
    assert status_of(reader.page, history) == 200
    assert "Создана" in reader.page.request.get(history).text()
    missing_record = f"/lists/{list_id}/{number + 500}/history/"
    missing_list = f"/lists/{int(list_id) + 100000}/{number}/history/"
    for person in (no_rights, staff):
        # п. 8: отказ тот же, что у несуществующей записи и несуществующего списка: 404 и тот же текст области
        # содержимого одним клиентом (15.5 п. 11)
        helpers_lists.same_404(person.page, history, missing_record)
        helpers_lists.same_404(person.page, history, missing_list)
        # п. 8: в теле отказа нет ни названия записи, ни названия списка, ни строки истории
        body = helpers_org.direct_get(person.page, history).text()
        assert title not in body and list_name not in body and "Создана" not in body
        # п. 8: в браузере — страница отказа 404 без данных записи
        response = person.page.goto(history)
        assert response is not None and response.status == 404
        expect(person.page.locator("body")).not_to_contain_text(title)
        expect(person.page.locator(f"{_HISTORY} li[data-change-kind]")).to_have_count(0)
