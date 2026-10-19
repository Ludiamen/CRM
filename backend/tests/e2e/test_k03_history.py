"""T-5142: сценарий 3 — правка, история, сравнение, восстановление, одновременная правка (FR-406, FR-407, FR-408,
FR-409, FR-410, FR-411, FR-412, FR-413, FR-414, FR-416, FR-438, FR-449, NFR-411).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-005.md):
- каждый тест заводит своих сотрудников (редактор — «Сотрудник ИТ», читатель — «Руководитель», управляющий —
  администратор круга `admin_page`), свои рубрики и статьи; названия уникальны; у сотрудников свои ФИО (по ним
  проверяются автор версии и сообщение об одновременной правке); общих настроек тесты не меняют, сброса стенда нет;
- версии создаются через интерфейс: первое сохранение (версия 1), правки черновика и опубликованной статьи
  (по версии за правку), публикация без изменений версии не даёт (план, «Публикация»);
- «две одновременные правки» — два контекста браузера (фикстура `employee` даёт каждому свой): оба открыли форму
  на одной версии, первый сохранил, второй нажимает «Сохранить» (раздел 16 контракта, поправка к решению 18 —
  о серверных тестах, приёмка идёт настоящими двумя контекстами);
- подтверждения `hx-confirm` (корзина, удаление навсегда, удаление версии и рубрики) принимает обработчик окна `dialog`;
- время — по Москве (UTC+3, как показывает портал); тексты и зацепки — разделы 11, 12, 17 контракта.
"""
import re
import secrets
from datetime import datetime, timedelta, timezone

from playwright.sync_api import expect

from tests.e2e import helpers_kb, helpers_org
from tests.e2e.helpers_kb import (
    article_form, create_draft, create_rubric, fill_article_form, history_versions, open_article, open_edit,
    open_history, press_save, publish_from_article_page, unique_title, unique_word)

MSK = timezone(timedelta(hours=3))
CYRILLIC = "абвгдежзийклмнопрстуфхцчшщэюя"
MISSING_ARTICLE = 2_000_000_000  # номер, которого на стенде нет (в пределах целого PostgreSQL)
MARKS = {1: "альфа", 2: "бета", 3: "гамма", 4: "дельта", 5: "эпсилон"}
AT_TEXT = re.compile(r"^\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}$")
MINUS = "−"


# --- Общие помощники файла ---------------------------------------------------------------------------------

def _person(employee, role_maker) -> object:
    """Сотрудник с уникальным ФИО (по нему узнаются автор версии и сообщение об одновременной правке)."""
    surname = "Тестов" + "".join(secrets.choice(CYRILLIC) for _ in range(6))
    return role_maker(employee, full_name=f"{surname} Иван Иванович")


def _editor(employee):
    return _person(employee, helpers_kb.make_editor)


def _reader(employee):
    return _person(employee, helpers_kb.make_reader)


def _rubric(admin_page) -> str:
    """Своя рубрика круга (создаёт управляющий); возвращает название. Названия не содержатся друг в друге."""
    name = f"Раздел {unique_word()}"
    create_rubric(admin_page, name)
    return name


def _text(number: int) -> str:
    """Текст версии `number`: общая строка и метка, по которой версию узнают."""
    return f"Общая строка.\nМетка {MARKS[number]}."


def _comment(number: int) -> str:
    return f"правка {MARKS[number]}"


def _save_edit(page, article_id, *, text=None, title=None, rubric=None, tags=None, comment=None) -> None:
    """Правка статьи через форму: открывает `/kb/<id>/edit/`, заполняет переданное, «Сохранить», ждёт возврат на
    `/kb/<id>/` и страницу статьи (успех правки, раздел 10.2)."""
    open_edit(page, article_id)
    fill_article_form(page, title=title, text=text, rubric=rubric, tags=tags, comment=comment)
    press_save(page)
    page.wait_for_url(re.compile(rf"/kb/{article_id}/$"))
    expect(page.locator(f'article[data-article-id="{article_id}"]')).to_be_visible()


def _article(page, rubric, *, versions=3, publish=True, title=None, tags="") -> tuple:
    """Статья с `versions` версиями (1 — создание, остальные — правки черновика), затем публикация без новой версии.
    Метки версий — `MARKS`; комментарии — `_comment`. Возвращает (номер статьи, заголовок)."""
    title = title or unique_title()
    article_id = create_draft(page, title=title, text=_text(1), rubric=rubric, tags=tags, comment=_comment(1))
    for number in range(2, versions + 1):
        _save_edit(page, article_id, text=_text(number), comment=_comment(number))
    if publish:
        publish_from_article_page(page, article_id)
    return article_id, title


def _version_page(page, article_id, number) -> None:
    """Открывает просмотр версии и ждёт его корень."""
    page.goto(f"/kb/{article_id}/versions/{number}/")
    expect(page.locator('[data-kb-page="version"]')).to_be_visible()


def _compare_selected(page, article_id, numbers) -> None:
    """В истории отмечает версии `numbers`, нажимает «Сравнить выбранные версии» и ждёт страницу сравнения."""
    open_history(page, article_id)
    for number in numbers:
        page.locator(f'tr[data-version="{number}"] input[type=checkbox][name="v"]').check()
    page.locator('button[data-action="kb-compare"]').click()
    page.wait_for_url(re.compile(rf"/kb/{article_id}/compare/\?"))
    expect(page.locator('[data-kb-page="compare"]')).to_be_visible()


def _lift_comment_limit(page) -> None:
    """Снимает `maxlength` с поля комментария: проверка предела — дело сервера (обход браузера)."""
    article_form(page).locator("input[name=comment]").evaluate("el => el.removeAttribute('maxlength')")


def _accept_dialogs(page) -> None:
    """Принимает окна подтверждения `hx-confirm` этой страницы (вызывать один раз на страницу)."""
    page.on("dialog", lambda dialog: dialog.accept())


def _pick_option(select, text: str) -> str:
    """Выбирает пункт `<select>`, подпись которого (без отступа) содержит `text`; возвращает `value`."""
    value = select.evaluate(
        "(el, text) => { const o = Array.from(el.options).find(o => o.text.trim().includes(text)); "
        "return o ? o.value : null; }", text)
    assert value is not None, f"в списке нет пункта «{text}»"
    select.select_option(value=value)
    return value


def _rubric_row(page, rubric_id):
    """Строка рубрики на `/kb/rubrics/` (страница должна быть открыта)."""
    return page.locator(f'[data-kb-rubrics] li[data-rubric-id="{rubric_id}"]')


def _moscow(text: str) -> datetime:
    """Время из «ДД.ММ.ГГГГ ЧЧ:ММ» (московское)."""
    return datetime.strptime(text.strip(), "%d.%m.%Y %H:%M").replace(tzinfo=MSK)


def _minutes(text: str) -> int:
    """Минуты суток из «ЧЧ:ММ» в конце строки."""
    hours, minutes = re.findall(r"(\d{2}):(\d{2})", text)[-1]
    return int(hours) * 60 + int(minutes)


# --- Тесты -------------------------------------------------------------------------------------------------

def test_k03_edit_with_edit_comment_creates_version_2_with_author_time_and_comment_visible_at_once(
        admin_page, employee):
    """Сценарий 3, п. 1: правка опубликованной статьи сотрудником с правом «Редактирование базы знаний» с комментарием
    «поправил команду» создаёт версию 2 с его именем, временем и комментарием, правка видна всем сразу
    (FR-408, FR-410)."""
    rubric = _rubric(admin_page)
    author = _editor(employee)
    editor = _editor(employee)
    reader = _reader(employee)
    article_id, _ = _article(author.page, rubric, versions=1)
    assert history_versions(editor.page, article_id) == [1]
    # п. 1: правит текст, пишет «поправил команду» и нажимает «Сохранить»
    new_text = f"Новая команда {unique_word()}"
    _save_edit(editor.page, article_id, text=new_text, comment="поправил команду")
    # п. 1: создана версия 2 с его именем, временем и комментарием
    assert history_versions(editor.page, article_id) == [2, 1]
    row = editor.page.locator('tr[data-version="2"]')
    expect(row.locator('[data-field="author"]')).to_contain_text(editor.full_name)
    expect(row.locator('[data-field="comment"]')).to_contain_text("поправил команду")
    moment = row.locator("time[data-at]")
    expect(moment).to_have_text(AT_TEXT)
    assert moment.get_attribute("datetime").endswith("+03:00"), "время версии не по Москве"
    delta = abs(datetime.now(MSK) - _moscow(moment.inner_text()))
    assert delta < timedelta(minutes=15), f"время версии {moment.inner_text()} далеко от текущего московского"
    assert author.full_name not in row.inner_text(), "версию 2 приписали прежнему автору"
    # п. 1: правка видна всем сразу — читателю без права правки
    seen = reader.page
    open_article(seen, article_id)
    expect(seen.locator("[data-field=body]")).to_contain_text(new_text)
    expect(seen.locator("[data-field=body]")).not_to_contain_text("Метка альфа")
    expect(seen.locator("[data-field=updated]")).to_contain_text(editor.full_name)


def test_k03_history_lists_number_author_time_comment_with_checkboxes_and_opens_any_version_view(
        admin_page, employee):
    """Сценарий 3, п. 2: у статьи с тремя версиями «История» показывает номер, автора, время и комментарий к правке с
    флажками у версий; у любой версии открывается просмотр (FR-411)."""
    rubric = _rubric(admin_page)
    author = _editor(employee)
    second = _editor(employee)
    page = author.page
    article_id, title = _article(page, rubric, versions=2)
    _save_edit(second.page, article_id, text=_text(3), comment=_comment(3))
    # п. 2: открыта «История»
    open_history(page, article_id)
    assert [int(r.get_attribute("data-version")) for r in page.locator("tr[data-version]").all()] == [3, 2, 1]
    expected_author = {1: author, 2: author, 3: second}
    for number in (3, 2, 1):
        row = page.locator(f'tr[data-version="{number}"]')
        # п. 2: список «Номер, Автор, Время, Комментарий к правке» с флажком у версии
        expect(row.locator('input[type=checkbox][name="v"]')).to_have_count(1)
        expect(row.locator('input[type=checkbox][name="v"]')).to_have_attribute("value", str(number))
        expect(row.locator('[data-field="author"]')).to_contain_text(expected_author[number].full_name)
        expect(row.locator("time[data-at]")).to_have_text(AT_TEXT)
        expect(row.locator('[data-field="comment"]')).to_contain_text(_comment(number))
    expect(page.locator('button[data-action="kb-compare"]')).to_have_text("Сравнить выбранные версии")
    # п. 2: у любой версии можно открыть просмотр
    for number in (1, 2, 3):
        open_history(page, article_id)
        page.locator(f'tr[data-version="{number}"] a[data-action="kb-version-open"]').click()
        page.wait_for_url(re.compile(rf"/kb/{article_id}/versions/{number}/$"))
        expect(page.locator('[data-kb-page="version"]')).to_be_visible()
        expect(page.locator('[data-kb-page="version"] [data-field="title"]')).to_contain_text(title)
        body = page.locator('[data-kb-page="version"] [data-field="body"]')
        expect(body).to_contain_text(f"Метка {MARKS[number]}")
        for other in (1, 2, 3):
            if other != number:
                expect(body).not_to_contain_text(f"Метка {MARKS[other]}")


def test_k03_compare_two_versions_shows_line_diff_with_plus_minus_marks_and_title_rubric_tags_rows(
        admin_page, employee):
    """Сценарий 3, п. 3: версии 1 и 3 — построчное сравнение: добавленное и удалённое подсвечены по-разному и помечены
    «+» и «−», смена заголовка, рубрики и тегов — отдельными строками (FR-411)."""
    first_rubric = _rubric(admin_page)
    second_rubric = _rubric(admin_page)
    author = _editor(employee)
    page = author.page
    old_title = unique_title("Старый заголовок")
    new_title = unique_title("Новый заголовок")
    old_tag, new_tag = unique_word("т").lower(), unique_word("н").lower()
    article_id = create_draft(
        page, title=old_title, rubric=first_rubric, tags=old_tag, comment="первая",
        text="Общая строка.\nУдаляемая строка уникум.\nКонец текста.")
    _save_edit(page, article_id, text="Общая строка.\nУдаляемая строка уникум.\nДобавлено во второй.\nКонец текста.",
               comment="вторая")
    _save_edit(page, article_id, title=new_title, rubric=second_rubric, tags=new_tag, comment="третья",
               text="Общая строка.\nДобавленная строка уникум.\nКонец текста.")
    publish_from_article_page(page, article_id)
    # п. 3: отмечены версии 1 и 3, «Сравнить выбранные версии»
    _compare_selected(page, article_id, (1, 3))
    diff = page.locator("[data-kb-diff]")
    expect(diff).to_be_visible()
    removed = diff.locator("div.kb-diff-del").filter(has_text="Удаляемая строка уникум.")
    added = diff.locator("div.kb-diff-add").filter(has_text="Добавленная строка уникум.")
    expect(removed).to_have_count(1)
    expect(added).to_have_count(1)
    # п. 3: пометки «+» и «−», не только цвет
    expect(removed).to_contain_text(MINUS)
    expect(added).to_contain_text("+")
    # п. 3: добавленное и удалённое подсвечены по-разному
    colors = [loc.evaluate("el => { const s = getComputedStyle(el); return s.backgroundColor + '|' + s.color; }")
              for loc in (removed, added)]
    assert colors[0] != colors[1], f"добавленное и удалённое окрашены одинаково: {colors}"
    # неизменённые строки не помечены
    expect(diff.locator("div.kb-diff-add, div.kb-diff-del").filter(has_text="Общая строка.")).to_have_count(0)
    # п. 3: смена заголовка, рубрики и тегов — отдельными строками «было / стало»
    for field, before, after in (("title", old_title, new_title), ("rubric", first_rubric, second_rubric),
                                 ("tags", old_tag, new_tag)):
        row = diff.locator(f'[data-kb-diff-field="{field}"]')
        expect(row).to_have_count(1)
        expect(row.locator('[data-side="before"]')).to_contain_text(before)
        expect(row.locator('[data-side="after"]')).to_contain_text(after)
    # старший номер — «стало» при любом порядке `v`
    page.goto(f"/kb/{article_id}/compare/?v=3&v=1")
    expect(page.locator('[data-kb-diff-field="title"] [data-side="after"]')).to_contain_text(new_title)
    page.goto(f"/kb/{article_id}/compare/?v=1&v=3")
    expect(page.locator('[data-kb-diff-field="title"] [data-side="after"]')).to_contain_text(new_title)
    # строки полей — только изменённые: версии 1 и 2 различаются лишь текстом
    _compare_selected(page, article_id, (1, 2))
    expect(page.locator("[data-kb-diff]")).to_be_visible()
    expect(page.locator("[data-kb-diff] [data-kb-diff-field]")).to_have_count(0)
    expect(page.locator("[data-kb-diff] div.kb-diff-add").filter(has_text="Добавлено во второй.")).to_have_count(1)


def test_k03_compare_with_one_or_four_versions_selected_shows_select_two_hint_and_no_diff(admin_page, employee):
    """Сценарий 3, п. 4: отмечена одна версия или четыре — подсказка «Отметьте две версии», сравнения нет
    (FR-411)."""
    rubric = _rubric(admin_page)
    author = _editor(employee)
    page = author.page
    article_id, _ = _article(page, rubric, versions=4)
    for numbers in ((2,), (1, 2, 3, 4)):
        # п. 4: отмечена одна версия / четыре, «Сравнить выбранные версии»
        _compare_selected(page, article_id, numbers)
        hint = page.locator('[data-kb-hint="pick-two"]')
        expect(hint).to_be_visible()
        expect(hint).to_contain_text("Отметьте две версии")
        expect(page.locator("[data-kb-diff]")).to_have_count(0)
        expect(page.locator("div.kb-diff-add, div.kb-diff-del")).to_have_count(0)


def test_k03_restore_version_1_creates_version_4_with_restored_comment_and_keeps_versions_1_to_3(
        admin_page, employee):
    """Сценарий 3, п. 5: на открытой версии 1 «Восстановить эту версию» создаёт версию 4 с текстом версии 1 и
    комментарием «Восстановлено из версии 1»; версии 1–3 остаются как были (FR-412)."""
    rubric = _rubric(admin_page)
    author = _editor(employee)
    page = author.page
    article_id, _ = _article(page, rubric, versions=3)
    # п. 5: открыта версия 1
    open_history(page, article_id)
    page.locator('tr[data-version="1"] a[data-action="kb-version-open"]').click()
    page.wait_for_url(re.compile(rf"/kb/{article_id}/versions/1/$"))
    expect(page.locator('form[data-form="kb-version-restore"] button[data-action="kb-restore-version"]')
           ).to_have_text("Восстановить эту версию")
    # п. 5: нажимает «Восстановить эту версию»
    page.locator('form[data-form="kb-version-restore"] button[data-action="kb-restore-version"]').click()
    page.wait_for_url(re.compile(rf"/kb/{article_id}/$"))
    # п. 5: создана версия 4 с текстом версии 1 и комментарием «Восстановлено из версии 1»
    expect(page.locator("[data-field=body]")).to_contain_text(f"Метка {MARKS[1]}")
    expect(page.locator("[data-field=body]")).not_to_contain_text(f"Метка {MARKS[3]}")
    assert history_versions(page, article_id) == [4, 3, 2, 1]
    expect(page.locator('tr[data-version="4"] [data-field="comment"]')).to_contain_text("Восстановлено из версии 1")
    _version_page(page, article_id, 4)
    expect(page.locator('[data-kb-page="version"] [data-field="body"]')).to_contain_text(f"Метка {MARKS[1]}")
    # п. 5: версии 1–3 остались как были — тексты и комментарии
    for number in (1, 2, 3):
        _version_page(page, article_id, number)
        body = page.locator('[data-kb-page="version"] [data-field="body"]')
        expect(body).to_contain_text(f"Метка {MARKS[number]}")
        for other in (1, 2, 3):
            if other != number:
                expect(body).not_to_contain_text(f"Метка {MARKS[other]}")
        open_history(page, article_id)
        expect(page.locator(f'tr[data-version="{number}"] [data-field="comment"]')).to_contain_text(
            _comment(number))


def test_k03_reader_without_edit_right_sees_history_and_compare_but_no_restore_or_edit_and_direct_call_is_denied(
        admin_page, employee):
    """Сценарий 3, п. 6: сотрудник без права «Редактирование базы знаний» видит историю и сравнение, но кнопок
    «Восстановить эту версию» и «Править» нет, прямое обращение — отказ (FR-406, FR-411, FR-412)."""
    rubric = _rubric(admin_page)
    author = _editor(employee)
    reader = _reader(employee)
    article_id, _ = _article(author.page, rubric, versions=3)
    page = reader.page
    # п. 6: смотрит историю — виден список
    open_history(page, article_id)
    assert [int(r.get_attribute("data-version")) for r in page.locator("tr[data-version]").all()] == [3, 2, 1]
    expect(page.locator('tr[data-version="2"] [data-field="comment"]')).to_contain_text(_comment(2))
    # п. 6: видит сравнение
    _compare_selected(page, article_id, (1, 3))
    expect(page.locator("[data-kb-diff]")).to_be_visible()
    expect(page.locator("[data-kb-diff] div.kb-diff-add").filter(has_text=f"Метка {MARKS[3]}")).to_have_count(1)
    # п. 6: кнопок «Восстановить эту версию» и «Править» нет
    _version_page(page, article_id, 1)
    expect(page.locator('[data-kb-page="version"] [data-field="body"]')).to_contain_text(f"Метка {MARKS[1]}")
    expect(page.locator('form[data-form="kb-version-restore"]')).to_have_count(0)
    expect(page.locator('button[data-action="kb-restore-version"]')).to_have_count(0)
    open_article(page, article_id)
    expect(page.locator('a[data-action="kb-edit"]')).to_have_count(0)
    # п. 6: прямое обращение — отказ
    assert helpers_org.direct_get(page, f"/kb/{article_id}/edit/").status == 403, "форма правки читателю не отказана"
    restore = helpers_org.direct_post(page, f"/kb/{article_id}/versions/1/restore/")
    assert restore.status == 403, f"восстановление версии читателем: {restore.status}"
    edit = helpers_org.direct_post(page, f"/kb/{article_id}/edit/", {
        "title": "чужая правка", "text": "чужой текст", "base_version": "3", "action": "save"})
    assert edit.status == 403, f"правка читателем: {edit.status}"
    assert history_versions(author.page, article_id) == [3, 2, 1], "отказанное действие создало версию"


def test_k03_second_editor_save_after_first_saved_is_rejected_with_author_time_compare_link_text_kept_version_4_intact(
        admin_page, employee):
    """Сценарий 3, п. 7: двое открыли статью на версии 3, первый сохранил (версия 4); второй нажимает «Сохранить» —
    отказ «Статью уже изменил <имя> в <время>» со ссылкой «Сравнить версии», введённый текст остался в форме,
    версия 4 не затёрта (FR-413, NFR-411)."""
    first, second, article_id, rubric_name = _conflict_pair(admin_page, employee)
    del rubric_name
    # п. 7: двое открыли статью на версии 3; первый сохранил — версия 4
    second_text = f"Текст второго {unique_word()}"
    _save_edit(first.page, article_id, text=_text(4), comment=_comment(4))
    assert history_versions(first.page, article_id) == [4, 3, 2, 1]
    # п. 7: второй нажимает «Сохранить»
    page = second.page
    fill_article_form(page, text=second_text, comment="правка второго")
    press_save(page)
    alert = page.locator('[role=alert][data-code="stale_version"]')
    # п. 7: сохранение отклонено, показано «Статью уже изменил <имя> в <время>»
    expect(alert).to_be_visible()
    expect(alert).to_contain_text("Статью уже изменил")
    expect(alert).to_contain_text(first.full_name)
    assert re.search(r"в \d{2}:\d{2}", alert.inner_text()), f"в отказе нет времени: {alert.inner_text()}"
    # время в отказе — время версии 4 (по Москве), а не дата хоста
    open_tab = page.context.new_page()
    try:
        open_history(open_tab, article_id)
        version_time = open_tab.locator('tr[data-version="4"] time[data-at]').inner_text()
    finally:
        open_tab.close()
    assert abs(_minutes(alert.inner_text()) - _minutes(version_time)) <= 1, (
        f"время в отказе {alert.inner_text()!r} не совпало со временем версии 4 {version_time!r}")
    # п. 7: ссылка «Сравнить версии» на сравнение версий 3 и 4
    link = page.locator('a[data-action="kb-compare-link"]')
    expect(link).to_have_text("Сравнить версии")
    assert re.search(rf"/kb/{article_id}/compare/\?v=3&v=4$", link.get_attribute("href")), link.get_attribute("href")
    # п. 7: введённый текст остался в форме, скрытое поле получило номер версии 4
    form = article_form(page)
    expect(form.locator("textarea[name=text]")).to_have_value(second_text)
    expect(form.locator("input[name=comment]")).to_have_value("правка второго")
    expect(form.locator("input[name=base_version]")).to_have_value("4")
    assert re.search(rf"/kb/{article_id}/edit/$", page.url), "после отказа адрес сменился"
    # п. 7: версия 4 не затёрта, новой версии нет
    assert history_versions(first.page, article_id) == [4, 3, 2, 1]
    _version_page(first.page, article_id, 4)
    expect(first.page.locator('[data-kb-page="version"] [data-field="body"]')).to_contain_text(f"Метка {MARKS[4]}")
    expect(first.page.locator('[data-kb-page="version"] [data-field="body"]')).not_to_contain_text(second_text)
    open_article(first.page, article_id)
    expect(first.page.locator("[data-field=body]")).to_contain_text(f"Метка {MARKS[4]}")


def test_k03_second_editor_resave_after_compare_on_version_4_creates_version_5(admin_page, employee):
    """Сценарий 3, п. 8: после того же отказа второй открывает сравнение и сохраняет повторно с учётом версии 4 —
    создаётся версия 5 (FR-413)."""
    first, second, article_id, _ = _conflict_pair(admin_page, employee)
    second_text = f"Текст второго {unique_word()}"
    _save_edit(first.page, article_id, text=_text(4), comment=_comment(4))
    page = second.page
    # п. 8: то же отклонение
    fill_article_form(page, text=second_text, comment="правка второго")
    press_save(page)
    expect(page.locator('[role=alert][data-code="stale_version"]')).to_be_visible()
    # п. 8: второй открывает сравнение (в соседней вкладке: введённое в форме остаётся)
    href = page.locator('a[data-action="kb-compare-link"]').get_attribute("href")
    tab = page.context.new_page()
    try:
        tab.goto(href)
        expect(tab.locator('[data-kb-page="compare"]')).to_be_visible()
        expect(tab.locator("[data-kb-diff]")).to_be_visible()
        expect(tab.locator("[data-kb-diff] div.kb-diff-add").filter(has_text=f"Метка {MARKS[4]}")).to_have_count(1)
    finally:
        tab.close()
    # п. 8: сохраняет повторно с учётом версии 4
    expect(article_form(page).locator("input[name=base_version]")).to_have_value("4")
    press_save(page)
    page.wait_for_url(re.compile(rf"/kb/{article_id}/$"))
    # п. 8: создаётся версия 5, версия 4 цела
    assert history_versions(page, article_id) == [5, 4, 3, 2, 1]
    row = page.locator('tr[data-version="5"]')
    expect(row.locator('[data-field="author"]')).to_contain_text(second.full_name)
    expect(row.locator('[data-field="comment"]')).to_contain_text("правка второго")
    expect(page.locator('tr[data-version="4"] [data-field="comment"]')).to_contain_text(_comment(4))
    open_article(page, article_id)
    expect(page.locator("[data-field=body]")).to_contain_text(second_text)
    _version_page(page, article_id, 4)
    expect(page.locator('[data-kb-page="version"] [data-field="body"]')).to_contain_text(f"Метка {MARKS[4]}")


def test_k03_save_of_published_article_without_changes_creates_no_version(admin_page, employee):
    """Сценарий 3, п. 9: опубликованная статья правится без изменений, «Сохранить» — новой версии нет
    (FR-410)."""
    rubric = _rubric(admin_page)
    author = _editor(employee)
    page = author.page
    article_id, _ = _article(page, rubric, versions=2)
    # п. 9: открывает правку и нажимает «Сохранить» без изменений
    open_edit(page, article_id)
    press_save(page)
    notice = page.locator('[data-kb-notice="no-changes"]')
    expect(notice).to_be_visible()
    expect(notice).to_contain_text("Изменений нет")
    assert re.search(rf"/kb/{article_id}/edit/$", page.url), "без изменений форма закрылась"
    # п. 9: новой версии нет
    assert history_versions(page, article_id) == [2, 1]


def test_k03_editor_who_is_not_manager_editing_foreign_draft_is_denied_like_missing_article(admin_page, employee):
    """Сценарий 3, п. 10: чужой черновик пытается править сотрудник с правом «Редактирование базы знаний», но не
    управляющий — отказ, как у несуществующей статьи (FR-407, FR-409)."""
    rubric = _rubric(admin_page)
    rubric_id = helpers_kb.rubric_id_by_name(admin_page, rubric)
    author = _editor(employee)
    other = _editor(employee)
    article_id, title = _article(author.page, rubric, versions=2, publish=False)
    page = other.page
    page.goto("/kb/")
    # п. 10: сотрудник без управления пытается править чужой черновик — как несуществующую статью
    missing = helpers_org.direct_get(page, f"/kb/{MISSING_ARTICLE}/edit/")
    assert missing.status == 404
    for path in ("edit/", "", "history/", "versions/1/", "compare/?v=1&v=2"):
        response = helpers_org.direct_get(page, f"/kb/{article_id}/{path}")
        assert response.status == missing.status, f"/kb/{article_id}/{path}: {response.status}, ждали 404"
        assert title not in response.text(), f"в ответе /kb/{article_id}/{path} есть заголовок чужого черновика"
    posted = helpers_org.direct_post(page, f"/kb/{article_id}/edit/", {
        "title": "чужая правка", "text": "чужой текст", "rubric": rubric_id, "base_version": "2", "action": "save"})
    assert posted.status == 404, f"POST правки чужого черновика: {posted.status}"
    assert history_versions(author.page, article_id) == [2, 1], "отказанная правка создала версию"
    # управляющий черновик видит и правит
    open_edit(admin_page, article_id)
    expect(article_form(admin_page).locator("input[name=title]")).to_have_value(title)


def test_k03_edit_comment_over_200_chars_is_refused_with_limit_shown(admin_page, employee):
    """Сценарий 3, п. 11: комментарий к правке длиннее 200 знаков, «Сохранить» — сохранения нет, показан предел
    (FR-410)."""
    rubric = _rubric(admin_page)
    author = _editor(employee)
    page = author.page
    article_id, _ = _article(page, rubric, versions=1)
    # п. 11: комментарий из 201 знака и изменённый текст, «Сохранить»
    open_edit(page, article_id)
    _lift_comment_limit(page)
    new_text = f"Текст с длинным комментарием {unique_word()}"
    fill_article_form(page, text=new_text, comment="ж" * 201)
    press_save(page)
    error = page.locator('[data-error="comment"][data-code="comment_too_long"]')
    expect(error).to_be_visible()
    # п. 11: показан предел
    expect(error).to_contain_text("200")
    expect(error).to_contain_text("Комментарий к правке не длиннее 200 знаков")
    # п. 11: сохранения нет, введённое осталось
    assert re.search(rf"/kb/{article_id}/edit/$", page.url), "после отказа адрес сменился"
    expect(article_form(page).locator("textarea[name=text]")).to_have_value(new_text)
    assert history_versions(page, article_id) == [1]
    open_article(page, article_id)
    expect(page.locator("[data-field=body]")).not_to_contain_text("длинным комментарием")


def test_k03_no_action_changes_version_content_and_versions_vanish_only_with_article_or_manager_delete(
        admin_page, employee):
    """Сценарий 3, п. 12: способа изменить содержимое версии нет; версия исчезает либо вместе со статьёй при
    удалении навсегда, либо удалением управляющего (кроме текущей) (FR-414, FR-416, FR-449)."""
    rubric = _rubric(admin_page)
    author = _editor(employee)
    page = author.page
    _accept_dialogs(admin_page)
    article_id, _ = _article(page, rubric, versions=3)
    # п. 12: ищем способ изменить версию — в просмотре версии нет формы правки
    _version_page(page, article_id, 2)
    expect(page.locator('[data-kb-page="version"] textarea, [data-kb-page="version"] input[name=title], '
                        '[data-kb-page="version"] input[name=text]')).to_have_count(0)
    expect(page.locator('form[data-form="kb-article"]')).to_have_count(0)
    # п. 12: изменение методом, которого у версии нет, — отказ по методу
    assert helpers_org.direct_post(page, f"/kb/{article_id}/versions/2/").status == 405
    # п. 12: правка статьи и восстановление добавляют версии, прежние остаются как были
    _save_edit(page, article_id, text=_text(4), comment=_comment(4))
    _version_page(page, article_id, 1)
    page.locator('form[data-form="kb-version-restore"] button[data-action="kb-restore-version"]').click()
    page.wait_for_url(re.compile(rf"/kb/{article_id}/$"))
    assert history_versions(page, article_id) == [5, 4, 3, 2, 1]
    for number in (1, 2, 3, 4):
        _version_page(page, article_id, number)
        expect(page.locator('[data-kb-page="version"] [data-field="body"]')).to_contain_text(
            f"Метка {MARKS[number]}")
    # п. 12: сотрудник без управления версию не удаляет
    assert helpers_org.direct_post(page, f"/kb/{article_id}/versions/2/delete/").status == 403
    assert history_versions(page, article_id) == [5, 4, 3, 2, 1]
    # п. 12: управляющий удаляет не текущую версию — она исчезает
    _version_page(admin_page, article_id, 2)
    admin_page.locator('form[data-form="kb-version-delete"] button[data-action="kb-delete-version"]').click()
    admin_page.wait_for_url(re.compile(rf"/kb/{article_id}/history/$"))
    assert history_versions(admin_page, article_id) == [5, 4, 3, 1]
    assert helpers_org.direct_get(admin_page, f"/kb/{article_id}/versions/2/").status == 404
    # п. 12: при удалении навсегда исчезают все версии вместе со статьёй
    open_article(admin_page, article_id)
    admin_page.locator('form[data-form="kb-trash"] button').first.click()
    expect(admin_page.locator(f'article[data-article-id="{article_id}"][data-article-state="trash"]')).to_be_visible()
    admin_page.locator('form[data-form="kb-purge"] button').first.click()
    admin_page.wait_for_url(re.compile(r"/kb/trash/$"))
    for path in ("", "history/", "versions/1/", "versions/5/", "compare/?v=1&v=5"):
        status = helpers_org.direct_get(admin_page, f"/kb/{article_id}/{path}").status
        assert status == 404, f"/kb/{article_id}/{path} после удаления навсегда: {status}"


def test_k03_save_after_article_moved_to_trash_is_refused_with_deleted_message_and_form_text_kept(
        admin_page, employee):
    """Сценарий 3, п. 13: пока открыта форма правки, статью удалили в корзину; «Сохранить» — сохранения нет, показано
    «Статья удалена», введённый текст остался в форме (FR-413, NFR-411)."""
    rubric = _rubric(admin_page)
    author = _editor(employee)
    page = author.page
    _accept_dialogs(admin_page)
    article_id, _ = _article(page, rubric, versions=2)
    # п. 13: открыта форма правки, введён текст
    open_edit(page, article_id)
    typed = f"Введённый текст {unique_word()}"
    fill_article_form(page, text=typed, comment="правка при удалении")
    # п. 13: управляющий удалил статью в корзину
    open_article(admin_page, article_id)
    admin_page.locator('form[data-form="kb-trash"] button').first.click()
    expect(admin_page.locator(f'article[data-article-id="{article_id}"][data-article-state="trash"]')).to_be_visible()
    # п. 13: нажато «Сохранить» — сохранения нет, «Статья удалена»
    press_save(page)
    alert = page.locator('[role=alert][data-code="article_gone"]')
    expect(alert).to_be_visible()
    expect(alert).to_contain_text("Статья удалена")
    # п. 13: введённый текст остался в форме
    expect(article_form(page).locator("textarea[name=text]")).to_have_value(typed)
    # п. 13: новой версии нет (корзину видит управляющий)
    assert history_versions(admin_page, article_id) == [2, 1]


def test_k03_save_after_selected_rubric_deleted_is_refused_at_rubric_field_and_form_text_kept(
        admin_page, employee):
    """Сценарий 3, п. 14: пока открыта форма правки, управляющий удалил рубрику, выбранную в форме; «Сохранить» —
    сохранения нет, у поля рубрики отказ, текст формы остался (FR-413)."""
    own_rubric = _rubric(admin_page)
    doomed = f"Раздел {unique_word()}"
    doomed_id = create_rubric(admin_page, doomed)
    author = _editor(employee)
    page = author.page
    _accept_dialogs(admin_page)
    article_id, _ = _article(page, own_rubric, versions=1)
    # п. 14: открыта форма правки, в ней выбрана рубрика, которую удалят
    open_edit(page, article_id)
    typed = f"Введённый текст {unique_word()}"
    fill_article_form(page, text=typed, rubric=doomed, comment="правка при удалении рубрики")
    # п. 14: управляющий удалил выбранную в форме рубрику (она пуста)
    admin_page.goto("/kb/rubrics/")
    row = _rubric_row(admin_page, doomed_id)
    expect(row).to_have_count(1)
    row.locator('form[data-form="kb-rubric-delete"] button').first.click()
    expect(_rubric_row(admin_page, doomed_id)).to_have_count(0)
    # п. 14: нажато «Сохранить» — сохранения нет, у поля рубрики отказ
    press_save(page)
    error = page.locator('[data-error="rubric"][data-code="rubric_missing"]')
    expect(error).to_be_visible()
    expect(error).to_contain_text("Выберите рубрику")
    # п. 14: текст формы остался
    expect(article_form(page).locator("textarea[name=text]")).to_have_value(typed)
    expect(article_form(page).locator("input[name=comment]")).to_have_value("правка при удалении рубрики")
    assert re.search(rf"/kb/{article_id}/edit/$", page.url), "после отказа адрес сменился"
    assert history_versions(page, article_id) == [1]


def test_k03_save_after_manager_moved_article_rubric_succeeds(admin_page, employee):
    """Сценарий 3, п. 15: пока открыта форма правки, управляющий перенёс рубрику статьи; «Сохранить» — правка
    сохранена (FR-413)."""
    moved = f"Раздел {unique_word()}"
    moved_id = create_rubric(admin_page, moved)
    new_parent = _rubric(admin_page)
    author = _editor(employee)
    page = author.page
    article_id, _ = _article(page, moved, versions=1)
    # п. 15: открыта форма правки статьи рубрики `moved`
    open_edit(page, article_id)
    typed = f"Правка после переноса {unique_word()}"
    fill_article_form(page, text=typed, comment="правка при переносе")
    # п. 15: управляющий переносит рубрику статьи под другую
    admin_page.goto("/kb/rubrics/")
    expect(_rubric_row(admin_page, moved_id)).to_have_attribute("data-depth", "1")
    move = _rubric_row(admin_page, moved_id).locator('form[data-form="kb-rubric-move"]').first
    _pick_option(move.locator("select[name=parent]"), new_parent)
    move.locator("button").first.click()
    expect(_rubric_row(admin_page, moved_id)).to_have_attribute("data-depth", "2")
    # п. 15: нажато «Сохранить» — правка сохранена
    press_save(page)
    page.wait_for_url(re.compile(rf"/kb/{article_id}/$"))
    expect(page.locator("[data-field=body]")).to_contain_text(typed)
    expect(page.locator("[data-field=rubric]")).to_contain_text(moved)
    expect(page.locator("[data-field=rubric]")).to_contain_text(new_parent)
    assert history_versions(page, article_id) == [2, 1]
    expect(page.locator('tr[data-version="2"] [data-field="comment"]')).to_contain_text("правка при переносе")


def test_k03_history_of_published_article_shows_versions_created_during_draft_period(admin_page, employee):
    """Сценарий 3, п. 16: у опубликованной статьи с версиями периода черновика любой сотрудник в «Истории» видит все
    версии, включая созданные до публикации (FR-411)."""
    rubric = _rubric(admin_page)
    author = _editor(employee)
    reader = _reader(employee)
    # версии 1 и 2 — период черновика; публикация; версия 3 — после публикации
    article_id, _ = _article(author.page, rubric, versions=2)
    _save_edit(author.page, article_id, text=_text(3), comment=_comment(3))
    open_article(author.page, article_id)
    expect(author.page.locator(f'article[data-article-id="{article_id}"][data-article-state="published"]')
           ).to_be_visible()
    # п. 16: любой сотрудник (читатель) открывает «Историю»
    assert history_versions(reader.page, article_id) == [3, 2, 1]
    for number in (1, 2, 3):
        expect(reader.page.locator(f'tr[data-version="{number}"] [data-field="comment"]')).to_contain_text(
            _comment(number))
    # п. 16: версию периода черновика можно открыть
    reader.page.locator('tr[data-version="1"] a[data-action="kb-version-open"]').click()
    reader.page.wait_for_url(re.compile(rf"/kb/{article_id}/versions/1/$"))
    expect(reader.page.locator('[data-kb-page="version"] [data-field="body"]')).to_contain_text(f"Метка {MARKS[1]}")


def test_k03_manager_deletes_non_current_version_numbers_stay_and_journal_records_article_and_version(
        admin_page, employee):
    """Сценарий 3, п. 17: управляющий на не текущей версии 2 нажимает «Удалить версию» и подтверждает: версии 2 нет
    в истории, номера остальных не изменились, в журнале запись с номером статьи и версии (FR-449, FR-438)."""
    rubric = _rubric(admin_page)
    author = _editor(employee)
    _accept_dialogs(admin_page)
    article_id, title = _article(author.page, rubric, versions=3)
    # п. 17: управляющий, не текущая версия 2 — «Удалить версию» и подтверждение
    _version_page(admin_page, article_id, 2)
    button = admin_page.locator('form[data-form="kb-version-delete"] button[data-action="kb-delete-version"]')
    expect(button).to_have_text("Удалить версию")
    button.click()
    admin_page.wait_for_url(re.compile(rf"/kb/{article_id}/history/$"))
    expect(admin_page.locator("[role=status]").filter(has_text="Версия удалена").first).to_be_visible()
    # п. 17: версии 2 нет, номера остальных не изменились
    assert history_versions(admin_page, article_id) == [3, 1]
    expect(admin_page.locator('tr[data-version="3"] [data-field="comment"]')).to_contain_text(_comment(3))
    expect(admin_page.locator('tr[data-version="1"] [data-field="comment"]')).to_contain_text(_comment(1))
    assert helpers_org.direct_get(admin_page, f"/kb/{article_id}/versions/2/").status == 404
    _compare_selected(admin_page, article_id, (1, 3))
    expect(admin_page.locator("[data-kb-diff]")).to_be_visible()
    admin_page.goto(f"/kb/{article_id}/compare/?v=2&v=3")
    expect(admin_page.locator('[data-kb-hint="deleted"]')).to_contain_text("Версия удалена")
    # п. 17: в журнале запись с номером статьи и версии
    sides = helpers_org.audit_sides(admin_page, "knowledge.version_deleted", article_id)
    assert len(sides) == 1, f"записей «Версия статьи удалена» по статье {article_id}: {len(sides)}"
    before, _ = sides[0]
    assert re.search(rf"(?<!\d){article_id}(?!\d)", before), f"в журнале нет номера статьи {article_id}: {before!r}"
    assert title in before, f"в журнале нет заголовка статьи: {before!r}"
    assert re.search(r"номер версии\D{0,12}2(?!\d)", before), f"в журнале нет номера версии 2: {before!r}"


def test_k03_delete_version_button_absent_for_current_version_and_non_manager_and_direct_call_is_denied(
        admin_page, employee):
    """Сценарий 3, п. 18: у текущей (последней) версии и у сотрудника без права «Управление базой знаний» кнопки
    «Удалить версию» нет, прямое обращение — отказ (FR-449, FR-409)."""
    rubric = _rubric(admin_page)
    author = _editor(employee)
    article_id, _ = _article(author.page, rubric, versions=3)
    # п. 18: управляющий — у не текущей версии кнопка есть, у текущей нет
    _version_page(admin_page, article_id, 2)
    expect(admin_page.locator('form[data-form="kb-version-delete"] button[data-action="kb-delete-version"]')
           ).to_have_count(1)
    _version_page(admin_page, article_id, 3)
    expect(admin_page.locator('[data-kb-page="version"] [data-field="body"]')).to_contain_text(f"Метка {MARKS[3]}")
    expect(admin_page.locator('form[data-form="kb-version-delete"]')).to_have_count(0)
    expect(admin_page.locator('button[data-action="kb-delete-version"]')).to_have_count(0)
    # п. 18: текущую версию прямым обращением удалить нельзя
    current = helpers_org.direct_post(admin_page, f"/kb/{article_id}/versions/3/delete/")
    assert current.status == 200, f"удаление текущей версии: {current.status}"
    assert 'data-code="current_version"' in current.text(), "нет отказа current_version"
    assert "Текущую версию удалить нельзя" in current.text()
    # п. 18: сотрудник без управления — кнопки нет даже у не текущей версии, прямое обращение — отказ
    _version_page(author.page, article_id, 2)
    expect(author.page.locator('[data-kb-page="version"] [data-field="body"]')).to_contain_text(f"Метка {MARKS[2]}")
    expect(author.page.locator('form[data-form="kb-version-delete"]')).to_have_count(0)
    expect(author.page.locator('button[data-action="kb-delete-version"]')).to_have_count(0)
    denied = helpers_org.direct_post(author.page, f"/kb/{article_id}/versions/2/delete/")
    assert denied.status == 403, f"удаление версии сотрудником без управления: {denied.status}"
    # п. 18: ничего не удалено
    assert history_versions(admin_page, article_id) == [3, 2, 1]


def _conflict_pair(admin_page, employee) -> tuple:
    """Два редактора и опубликованная статья с тремя версиями; второй открыл форму правки на версии 3 (его страница
    остаётся на `/kb/<id>/edit/`). Возвращает (первый, второй, номер статьи, название рубрики)."""
    rubric = _rubric(admin_page)
    first = _editor(employee)
    second = _editor(employee)
    article_id, _ = _article(first.page, rubric, versions=3)
    open_edit(second.page, article_id)
    expect(article_form(second.page).locator("input[name=base_version]")).to_have_value("3")
    return first, second, article_id, rubric
