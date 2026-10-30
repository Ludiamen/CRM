"""T-7145: сценарий 6 — упоминания «@» в записи и комментарии (FR-605, FR-611, FR-629, FR-630, FR-642).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-007.md разделы 10.2, 12.2, 12.3, 13, К41; helpers_feed.py):
- каждый тест заводит своих сотрудников и свои подразделения с уникальными названиями и ФИО (общая часть ФИО теста —
  `tag`, по ней «Добавить сотрудников» находит всех сразу); автор — сотрудник с ролью «Писать всем» (своя роль,
  `helpers_feed.make_role`); сброса стенда и команд стенда в файле нет, общих настроек файл не меняет;
- подразделения создаёт администратор круга `admin_page` под корнем (`helpers_org.create_unit`, `add_members`);
- упоминание набирается «@» прямо в `textarea[name="text"]` (К41); выбранное показано в поле как `@ФИО`, в «Кому» —
  таблетка `[data-to-pill="m<id>"][data-mentioned]` «<ФИО> — упомянут» без крестика и без поля `to`; на сервер уходит
  маркер `@[<номер>]` (читается из тела запроса `/feed/posts/`);
- Петров, которому упоминание делает имя ссылкой на карточку, имеет роль с правом `staff.view` («Просмотр сотрудников и
  структуры», срез 002): план («Запись в ленте») даёт ссылку только тем, у кого карточки открываются;
- «уведомления нет» проверяется после положительного контроля: уведомления создаются в запросе действия;
- 21 упоминание набирается маркерами `@[<номер>]` в тексте (сервер доверяет только маркерам, план «Текст и
  упоминания»); номера — настоящие сотрудники теста, заведённые без активации (`activate=False`);
- ПДн в данных нет; ждать — `expect`, `expect_response`, опрос списка.
"""
import re
import secrets
import time
from urllib.parse import unquote_plus

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org
from tests.e2e.helpers_feed import (
    POST_ALL, add_comment, make_role, open_card, open_feed, pick_mention, publish)

STAFF_VIEW = "staff.view"
KIND_MENTION = "Вас упомянули"
LIMIT_TEXT = "Не больше 20 упоминаний"
FORM = "form#feed-form"
TEXT = f'{FORM} textarea[name="text"]'
OPTIONS = "[data-feed-pick-list] [data-pick-value]"
_POST_ID = re.compile(r'data-post-id="(\d+)"')


# --- Помощники файла ---------------------------------------------------------------------------------------------

def _tag() -> str:
    return secrets.token_hex(3)


def _fio(surname: str, tag: str) -> str:
    return f"{surname}{tag} Иван Иванович"


def _norm(text: str) -> str:
    return " ".join(text.split())


def _word() -> str:
    return "т" + secrets.token_hex(4)


def _writer(admin_page, employee, tag: str, surname: str = "Писарев"):
    """Сотрудник с правом «Писать всем» (своя роль)."""
    return employee(role=make_role(admin_page, [POST_ALL]), full_name=_fio(surname, tag))


def _staff(employee, tag: str, surname: str):
    return employee(full_name=_fio(surname, tag))


def _unit(admin_page, prefix: str, people, tag: str) -> tuple:
    """Подразделение под корнем с названием `<prefix>-<hex>` и участниками `people`; возвращает (номер, название)."""
    helpers_org.open_structure(admin_page)
    root = helpers_org.root_id(admin_page)
    name = helpers_org.unique_name(prefix)
    unit_id = helpers_org.create_unit(admin_page, name, kind="department", parent_id=root)
    helpers_org.add_members(admin_page, unit_id, [p.id for p in people], q=tag, mode="concurrent")
    return unit_id, name


def _dismiss(page, user_id) -> None:
    """Увольнение из карточки сотрудника (срез 002): `[data-action="dismiss"]`, диалог, подтверждение; ждёт отметку
    `[data-dismissed-badge]` рядом с ФИО."""
    page.goto(f"/staff/{user_id}/")
    card = page.locator(f'[data-card][data-user-id="{user_id}"]')
    card.locator('[data-action="dismiss"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(card.locator("[data-dismissed-badge]")).to_be_visible()


def _kind_rows(page, title: str):
    """Строки «Мои уведомления» вида `title` (страница открывается заново)."""
    page.goto("/notifications/")
    page.wait_for_load_state()
    return page.locator("ul[data-notifications] li[data-notification]").filter(
        has=page.locator('[data-field="kind"]', has_text=re.compile(rf"^\s*{re.escape(title)}\s*$")))


def _wait_kind_rows(page, title: str, count: int, timeout: float = 20.0):
    end = time.monotonic() + timeout
    while True:
        rows = _kind_rows(page, title)
        if rows.count() == count:
            return rows
        if time.monotonic() >= end:
            raise AssertionError(f"строк «{title}»: {rows.count()}, ожидалось {count}")
        page.wait_for_timeout(500)


def _row_text(row) -> str:
    return _norm(row.locator('[data-field="text"]').inner_text())


def _publish_button(page):
    return page.locator(FORM).get_by_role("button", name="Опубликовать", exact=True)


def _type_at(page, query: str) -> None:
    """Набирает «@» и `query` в конце текста формы записи (по символу, как человек)."""
    area = page.locator(TEXT)
    area.click()
    area.press("End")
    area.press_sequentially("@" + query, delay=30)


# --- Тесты -------------------------------------------------------------------------------------------------------

def test_f06_at_pet_opens_suggestion_of_active_employees_without_dismissed(admin_page, employee, new_context):
    """П. 1 (FR-611): сотрудник набирает «@Пет» в форме записи — открывается подсказка действующих сотрудников; в ней
    есть действующий Петров и нет уволенного Петровой с тем же началом фамилии."""
    tag = _tag()
    writer = _writer(admin_page, employee, tag)
    active = _staff(employee, tag, "Петров")
    gone = _staff(employee, tag, "Петрова")
    _dismiss(admin_page, gone.id)
    page = open_feed(new_context(), writer)
    _type_at(page, "Пет")
    options = page.locator(OPTIONS)
    expect(options.first).to_be_visible(timeout=10_000)
    values = options.evaluate_all("els => els.map(e => e.getAttribute('data-pick-value'))")
    assert values and all(re.fullmatch(r"p\d+", v) for v in values), f"в подсказке «@» не только люди: {values}"
    page.locator(TEXT).press_sequentially(f"ров{tag}", delay=30)
    expect(page.locator(f'[data-feed-pick-list] [data-pick-label="{active.full_name}"]').first).to_be_visible(
        timeout=10_000)
    expect(page.locator(f'[data-feed-pick-list] [data-pick-label="{gone.full_name}"]')).to_have_count(0)
    expect(page.locator(f'[data-feed-pick-list] [data-pick-value="p{gone.id}"]')).to_have_count(0)


def test_f06_chosen_employee_shown_in_text_as_at_full_name_and_in_to_as_mentioned_pill_without_cross(
        admin_page, employee, new_context):
    """П. 1 (FR-611): выбранный из подсказки Петров показан в поле текста как `@ФИО`, а в «Кому» — таблеткой «<ФИО> —
    упомянут» без крестика и без поля `to`."""
    tag = _tag()
    writer = _writer(admin_page, employee, tag)
    petrov = _staff(employee, tag, "Петров")
    page = open_feed(new_context(), writer)
    area = page.locator(TEXT)
    area.fill(f"Привет, коллеги {_word()} ")
    area.press("End")
    pick_mention(page, area, petrov.full_name.split()[0], petrov.full_name)
    expect(area).to_have_value(re.compile(re.escape("@" + petrov.full_name)))
    pill = page.locator(f'{FORM} [data-to-pill="m{petrov.id}"][data-mentioned]')
    expect(pill).to_have_count(1)
    expect(pill).to_contain_text(f"{petrov.full_name} — упомянут")
    expect(pill.locator('button[data-action="to-remove"]')).to_have_count(0)
    expect(page.locator(f'{FORM} input[name="to"][value="m{petrov.id}"]')).to_have_count(0)
    expect(pill.locator('input[name="to"]')).to_have_count(0)


def test_f06_publish_sends_at_id_marker_instead_of_chosen_full_name(admin_page, employee, new_context):
    """П. 1 (FR-611, план «Текст и упоминания»): при публикации на сервер уходит маркер `@[<номер>]` вместо выбранного
    ФИО; в опубликованной записи имя — упоминание с номером Петрова."""
    tag = _tag()
    writer = _writer(admin_page, employee, tag)
    petrov = _staff(employee, tag, "Петров")
    page = open_feed(new_context(), writer)
    area = page.locator(TEXT)
    area.fill(f"Запись с упоминанием {_word()} ")
    area.press("End")
    pick_mention(page, area, petrov.full_name.split()[0], petrov.full_name)
    with page.expect_response(lambda r: r.request.method == "POST" and "/feed/posts/" in r.url) as info:
        _publish_button(page).click()
    request = info.value.request
    body = unquote_plus((request.post_data_buffer or b"").decode("utf-8", "replace"))
    assert f"@[{petrov.id}]" in body, "на сервер не ушёл маркер упоминания"
    assert petrov.full_name not in body, "на сервер ушло выбранное ФИО вместо маркера"
    post_id = int(_POST_ID.search(info.value.text()).group(1))
    mention = page.locator(f'#feed-post-{post_id} [data-mention="{petrov.id}"]')
    expect(mention).to_have_count(1)
    expect(mention).to_contain_text(petrov.full_name)


def test_f06_mentioned_petrov_from_other_unit_sees_post_with_name_link_to_his_card_and_gets_you_were_mentioned(
        admin_page, employee, new_context):
    """П. 2 (FR-605, FR-611, FR-629): запись группе сети с упоминанием Петрова из другого отдела — Петров видит запись,
    имя в тексте — ссылка на его карточку, у него одно уведомление «Вас упомянули»."""
    tag = _tag()
    writer = _writer(admin_page, employee, tag)
    net_member = _staff(employee, tag, "Сетев")
    petrov = employee(role=make_role(admin_page, [STAFF_VIEW]), full_name=_fio("Петров", tag))
    _net_id, net_name = _unit(admin_page, "Отдел сети", [net_member], tag)
    _acc_id, _acc_name = _unit(admin_page, "Бухгалтерия", [petrov], tag)
    page_w = open_feed(new_context(), writer)
    text = f"Запись для сети {_word()} "
    post_id = publish(page_w, text, to=[("unit", net_name)], mentions=[petrov.full_name])
    expect(page_w.locator(f"#feed-post-{post_id}-to")).to_contain_text(petrov.full_name)
    page = open_feed(new_context(), petrov)
    expect(page.locator(f"#feed-post-{post_id}")).to_be_visible()
    link = page.locator(f'#feed-post-{post_id}-body a[data-mention="{petrov.id}"]')
    expect(link).to_have_count(1)
    expect(link).to_have_attribute("href", f"/staff/{petrov.id}/")
    expect(link).to_contain_text(petrov.full_name)
    rows = _wait_kind_rows(page, KIND_MENTION, 1)
    assert writer.full_name in _row_text(rows.first) and "упомянул(а) вас" in _row_text(rows.first)
    # контроль: член группы сети тоже видит запись
    expect(open_feed(new_context(), net_member).locator(f"#feed-post-{post_id}")).to_be_visible()


def test_f06_sidorov_mentioned_in_comment_becomes_recipient_sees_post_with_all_comments_and_gets_you_were_mentioned(
        admin_page, employee, new_context):
    """П. 3 (FR-605, FR-611): Сидоров запись не видит; в комментарии к ней его упомянули — он становится адресатом
    записи, видит её со всеми комментариями и получает «Вас упомянули»."""
    tag = _tag()
    writer = _writer(admin_page, employee, tag)
    net_member = _staff(employee, tag, "Сетев")
    sidorov = _staff(employee, tag, "Сидоров")
    _net_id, net_name = _unit(admin_page, "Отдел сети", [net_member], tag)
    _acc_id, _acc_name = _unit(admin_page, "Бухгалтерия", [sidorov], tag)
    page_w = open_feed(new_context(), writer)
    post_id = publish(page_w, f"Запись только для сети {_word()}", to=[("unit", net_name)])
    first = add_comment(page_w, post_id, f"комментарий автора {_word()}")
    assert helpers_org.direct_get(sidorov.page, f"/feed/{post_id}/").status == 404, "Сидоров видел запись до упоминания"
    page_n = open_feed(new_context(), net_member)
    second = add_comment(page_n, post_id, f"коллега, посмотрите {_word()} ", mentions=[sidorov.full_name])
    page = open_card(new_context(), sidorov, post_id)
    expect(page.locator(f"#feed-post-{post_id}")).to_be_visible()
    expect(page.locator(f"#c{first}")).to_be_visible()
    expect(page.locator(f"#c{second}")).to_be_visible()
    expect(page.locator(f'#c{second} [data-mention="{sidorov.id}"]')).to_have_count(1)
    feed = open_feed(new_context(), sidorov)
    expect(feed.locator(f"#feed-post-{post_id}")).to_be_visible()
    rows = _wait_kind_rows(feed, KIND_MENTION, 1)
    assert net_member.full_name in _row_text(rows.first), _row_text(rows.first)


def test_f06_self_mention_gives_no_notification(admin_page, employee, new_context):
    """П. 4 (FR-630): сотрудник упомянул самого себя и коллегу — запись опубликована; коллеге пришло «Вас упомянули»
    (контроль), самому автору уведомления нет."""
    tag = _tag()
    writer = _writer(admin_page, employee, tag)
    other = _staff(employee, tag, "Другов")
    page = open_feed(new_context(), writer)
    post_id = publish(page, f"Запись с упоминанием себя {_word()} ", mentions=[writer.full_name, other.full_name])
    expect(page.locator(f'#feed-post-{post_id}-body [data-mention="{writer.id}"]')).to_have_count(1)
    _wait_kind_rows(open_feed(new_context(), other), KIND_MENTION, 1)
    assert _kind_rows(page, KIND_MENTION).count() == 0, "автору пришло уведомление об упоминании самого себя"


def test_f06_unit_name_after_at_not_offered_in_suggestion(admin_page, employee, new_context):
    """П. 5 (FR-611): сотрудник набирает «@» и название подразделения — в подсказке подразделения нет (только люди);
    контроль: сотрудник с тем же началом фамилии в подсказке есть."""
    tag = _tag()
    writer = _writer(admin_page, employee, tag)
    unit_name = f"Звезда{tag}"
    helpers_org.open_structure(admin_page)
    helpers_org.create_unit(admin_page, unit_name, kind="department", parent_id=helpers_org.root_id(admin_page))
    person = employee(full_name=f"Звезда{tag}ев Иван Иванович")
    page = open_feed(new_context(), writer)
    _type_at(page, unit_name)
    expect(page.locator(f'[data-feed-pick-list] [data-pick-label="{person.full_name}"]').first).to_be_visible(
        timeout=10_000)
    expect(page.locator(f'[data-feed-pick-list] [data-pick-label="{unit_name}"]')).to_have_count(0)
    expect(page.locator('[data-feed-pick-list] [data-pick-value^="u"]')).to_have_count(0)


def test_f06_21_distinct_mentions_refused_with_reason_and_post_not_published(admin_page, employee, new_context):
    """П. 6 (FR-611, FR-642): в тексте упомянут 21 разный сотрудник — публикации нет, у текста причина «Не больше 20
    упоминаний», введённое остаётся; контроль: 20 разных упоминаний публикуются."""
    tag = _tag()
    writer = _writer(admin_page, employee, tag)
    people = [employee(activate=False, full_name=_fio(f"Упомянутов{i}", tag)) for i in range(1, 22)]
    markers = [f"@[{p.id}]" for p in people]
    page = open_feed(new_context(), writer)
    allowed = f"Двадцать упоминаний {_word()} " + " ".join(markers[:20])
    ok_id = publish(page, allowed)
    expect(page.locator(f"#feed-post-{ok_id}")).to_be_visible()
    word = _word()
    refused = f"Двадцать одно упоминание {word} " + " ".join(markers)
    area = page.locator(TEXT)
    area.fill(refused)
    with page.expect_response(lambda r: r.request.method == "POST" and "/feed/posts/" in r.url):
        _publish_button(page).click()
    error = page.locator(f'{FORM} [data-error="text"][data-code="too_many_mentions"]')
    expect(error).to_be_visible(timeout=10_000)
    expect(error).to_contain_text(LIMIT_TEXT)
    expect(area).to_have_value(refused)
    assert word not in page.locator("#feed-list").inner_text(), "запись с 21 упоминанием появилась в ленте"
    fresh = open_feed(new_context(), writer)
    expect(fresh.locator(f"#feed-post-{ok_id}")).to_be_visible()
    assert word not in fresh.locator("#feed-list").inner_text(), "запись с 21 упоминанием опубликована"
