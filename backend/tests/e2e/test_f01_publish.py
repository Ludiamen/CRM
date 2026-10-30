"""T-7140b: сценарий 1 — публикация всем, подразделению и людям; кто видит, кто нет (FR-601…FR-610, FR-642,
NFR-605, NFR-606).

Общее для файла (шаблон e2e/template.md, CONTRACT-007.md, разделы 10, 12, 13, 14.4):
- люди и узлы круга — `helpers_feed.feed_cast` (один раз на круг браузера; сессии людей сохранены в
  `Account.storage_state`, потому что контекст активации закрывается вместе с тестом-создателем); тесты, которые
  переводят, увольняют или удаляют, заводят своих людей и свои узлы и общий круг не меняют;
- каждый тест публикует свои записи с уникальным словом; записи «Всем» видят все сотрудники круга, поэтому тесты,
  которым нужна пустая или точно известная лента, чистят записи стенда `helpers_feed.age(4000)` (решение 54 задач:
  без `posts` — все записи стенда; ночное задание удаляет всё старше срока хранения);
- локаторы — только из раздела 12 контракта; тексты отказов — литералы раздела 13; ПДн в данных собираются из частей;
- локальные помощники файла (правка записи здесь не нужна): `_dismiss` (образец test_o07_dismiss), `_unit_name`.
"""
import re
import secrets
import types

import pytest
from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers, helpers_feed, helpers_org

_CASTS: dict = {}
_DATE = re.compile(r"\d{2}\.\d{2}\.\d{4} \d{2}:\d{2}")


# --- Общие помощники файла -----------------------------------------------------------------------------------------

def _unit_name(page, unit_id) -> str:
    """Название узла по его номеру (первая строка ссылки узла в дереве структуры)."""
    helpers_org.open_structure(page, unit_id)
    return helpers_org.unit_link(page, unit_id).inner_text().strip().splitlines()[0].strip()


def _dismiss(page, user_id) -> None:
    """Увольняет из карточки сотрудника (образец — test_o07_dismiss): диалог → подтверждение → отметка «уволен»."""
    page.goto(f"/staff/{user_id}/")
    page.locator('[data-action="dismiss"]').first.click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(page.locator("[data-dismissed-badge]").first).to_be_visible()


def _word() -> str:
    """Уникальное слово из русских букв (поиск ленты работает по словам)."""
    return "".join(secrets.choice("абвгдежзиклмнопрстуф") for _ in range(12))


def _person(admin_page, surname: str, token: str) -> tuple:
    """Приглашённый (без активации) сотрудник: `(номер, ФИО)`; приглашённый остаётся адресатом (план: «действующий»)."""
    name = f"{surname}{token} Иван Иванович"
    return helpers.create_employee(admin_page, factories.new_email("emp"), full_name=name), name


def _token() -> str:
    return helpers_org.unique_name("к")[2:]


def _open(new_context, account):
    return helpers_feed.open_feed(new_context(), account)


def _see(new_context, account, post_id):
    """Лента сотрудника, в которой запись видна."""
    page = _open(new_context, account)
    expect(page.locator(f"#feed-post-{post_id}")).to_be_visible()
    return page


def _not_see(new_context, account, post_id):
    page = _open(new_context, account)
    expect(page.locator(f"#feed-post-{post_id}")).to_have_count(0)
    assert post_id not in helpers_feed.post_ids(page)
    return page


def _choose_kind(form, kind: str) -> None:
    radio = form.locator(f'input[name="kind"][value="{kind}"]')
    try:
        radio.check(timeout=3_000)
    except PlaywrightTimeoutError:
        form.locator(f'label:has(input[name="kind"][value="{kind}"])').click()
    expect(radio).to_be_checked()


@pytest.fixture
def cast(admin_page, mailpit, new_context, stand_admin):
    """Круг людей и узлов сценариев (`feed_cast`), один на круг браузера."""
    found = _CASTS.get(stand_admin.email)
    if found is None:
        base = helpers_feed.feed_cast(admin_page, mailpit, new_context)
        for account in (base.writer, base.moderator, base.plain, base.it_member, base.net_member, base.part_timer,
                        base.accountant, base.petrov, base.sidorov):
            account.storage_state = account.page.context.storage_state()
            account.page = None
        found = types.SimpleNamespace(**base._asdict())
        found.it_name = _unit_name(admin_page, base.it_unit)
        found.net_name = _unit_name(admin_page, base.net_unit)
        found.acc_name = _unit_name(admin_page, base.accounting_unit)
        _CASTS[stand_admin.email] = found
    return found


# --- Тесты ---------------------------------------------------------------------------------------------------------

def test_f01_form_of_post_all_holder_opens_with_message_kind_and_all_in_to(new_context, cast):
    """П. 1: у сотрудника с правом «Писать всем» форма открыта с видом «Сообщение», в «Кому» уже стоит «Всем»
    (FR-608, FR-610)."""
    page = _open(new_context, cast.writer)
    form = page.locator("form#feed-form")
    expect(form).to_be_visible()
    expect(form.locator('input[name="kind"][value="post"]')).to_be_checked()
    expect(form.locator('input[name="kind"][value="important"]')).not_to_be_checked()
    expect(form.locator('input[name="kind"][value="event"]')).not_to_be_checked()
    expect(form.locator('[data-to-pill="all"]')).to_have_count(1)
    expect(form.locator('[data-to-pill="all"]')).to_contain_text("Всем")
    expect(form.locator('input[name="to"][value="all"]')).to_have_count(1)
    for label in ("Сообщение", "Важное", "Событие"):
        expect(form).to_contain_text(label)


def test_f01_kind_switch_shows_term_field_for_important_and_event_fields_for_event_only(new_context, cast):
    """Переключатель вида: поля срока видны только у «Важное», поля события — только у «Событие» (FR-608)."""
    page = _open(new_context, cast.writer)
    form = page.locator("form#feed-form")
    important, event = form.locator('[data-kind-fields="important"]'), form.locator('[data-kind-fields="event"]')
    expect(important).to_be_hidden()
    expect(event).to_be_hidden()
    _choose_kind(form, "important")
    expect(important).to_be_visible()
    expect(event).to_be_hidden()
    expect(important.locator('input[name="term"]')).not_to_have_count(0)
    _choose_kind(form, "event")
    expect(event).to_be_visible()
    expect(important).to_be_hidden()
    for name in ("event_title", "event_start", "event_end", "event_place"):
        expect(event.locator(f'[name="{name}"]')).to_have_count(1)
    _choose_kind(form, "post")
    expect(important).to_be_hidden()
    expect(event).to_be_hidden()


def test_f01_employee_without_post_all_has_no_all_in_to_and_chosen_recipient_is_removed_by_cross_before_publish(
        new_context, cast):
    """Без права «Писать всем» в «Кому» нет «Всем»; выбранный адресат снимается крестиком до публикации, и запись без
    адресата не публикуется (FR-610)."""
    page = _open(new_context, cast.plain)
    form = page.locator("form#feed-form")
    expect(form.locator('[data-to-pill="all"]')).to_have_count(0)
    expect(form.locator('input[name="to"][value="all"]')).to_have_count(0)
    before = helpers_feed.post_ids(page)
    helpers_feed.pick_to(page, cast.it_member.full_name.split()[0], cast.it_member.full_name)
    pill = form.locator("[data-to-pill]")
    expect(pill).to_have_count(1)
    pill.locator('button[data-action="to-remove"]').click()
    expect(pill).to_have_count(0)
    codes = helpers_feed.try_publish(page, "Текст без адресата " + _word(), to=[])
    assert codes == [("to", "no_recipients")], codes
    expect(page.locator('[data-error="to"][data-code="no_recipients"]')).to_contain_text("Выберите, кому адресована запись")
    assert helpers_feed.post_ids(page) == before


def test_f01_to_suggestion_finds_active_people_by_name_part_and_units_by_name_or_path_part_without_dismissed(
        admin_page, mailpit, new_context, cast):
    """Подсказка «Кому»: действующие сотрудники — по части ФИО, узлы — по части названия или пути; уволенного в
    подсказке нет (FR-610)."""
    token = _token()
    gone = helpers.make_employee(admin_page, mailpit, new_context, full_name=f"Ушедшев{token} Иван Иванович")
    _dismiss(admin_page, gone.id)
    page = _open(new_context, cast.plain)
    field = page.locator('form#feed-form input[data-feed-picker="to"]')
    options = page.locator("[data-feed-pick-list] [data-pick-value]")

    def type_query(query: str) -> None:
        field.fill("")
        field.press_sequentially(query, delay=30)

    type_query(cast.petrov.full_name.split()[0])  # часть ФИО
    expect(page.locator(f'[data-feed-pick-list] [data-pick-label="{cast.petrov.full_name}"]')).to_be_visible()
    type_query(cast.net_name)  # часть названия узла
    expect(page.locator(f'[data-feed-pick-list] [data-pick-label="{cast.net_name}"]')).to_be_visible()
    type_query(cast.it_name)  # часть пути: путь «Группы сети» содержит название «Отдела ИТ»
    expect(page.locator(f'[data-feed-pick-list] [data-pick-label="{cast.it_name}"]')).to_be_visible()
    expect(page.locator(f'[data-feed-pick-list] [data-pick-label="{cast.net_name}"]')).to_be_visible()
    type_query(f"Ушедшев{token}")  # уволенного нет
    page.wait_for_timeout(1_500)  # ответ подсказки приходит запросом; пустой список — это отсутствие строк
    expect(options).to_have_count(0)
    type_query(cast.accountant.full_name.split()[0])  # действующий находится тем же способом
    expect(page.locator(f'[data-feed-pick-list] [data-pick-label="{cast.accountant.full_name}"]')).to_be_visible()


def test_f01_post_to_all_appears_on_top_with_author_arrow_all_and_time_and_is_seen_by_other_active_employee(
        new_context, cast):
    """П. 2: запись «Всем» — наверху ленты автора с автором, «→ Всем» и временем; её видит другой действующий
    сотрудник (FR-603, FR-605, FR-608)."""
    page = _open(new_context, cast.writer)
    text = "Запись всем " + _word()
    post_id = helpers_feed.publish(page, text, to=["all"])
    assert helpers_feed.post_ids(page)[0] == post_id
    post = page.locator(f"#feed-post-{post_id}")
    expect(post.locator("[data-feed-author]")).to_contain_text(cast.writer.full_name)
    expect(post.locator(f"#feed-post-{post_id}-to")).to_contain_text("Всем")
    expect(post).to_contain_text("→")
    expect(post.locator("time[data-at]").first).to_have_text(_DATE)
    expect(post.locator(f"#feed-post-{post_id}-body")).to_contain_text(text)
    other = _see(new_context, cast.accountant, post_id)
    assert helpers_feed.post_ids(other)[0] == post_id


def test_f01_post_card_opens_at_permanent_address_for_recipient(new_context, cast):
    """Карточка записи открывается получателю по постоянному адресу `/feed/<id>/` (FR-604)."""
    page = _open(new_context, cast.writer)
    text = "Запись для карточки " + _word()
    post_id = helpers_feed.publish(page, text, to=[("person", cast.it_member.full_name)])
    card = helpers_feed.open_card(new_context(), cast.it_member, post_id)
    assert card.url.endswith(f"/feed/{post_id}/"), card.url
    expect(card.locator(f"#feed-post-{post_id}")).to_contain_text(text)
    card.reload()
    expect(card.locator(f"#feed-post-{post_id}")).to_contain_text(text)


def test_f01_unit_post_seen_by_nested_unit_member_and_part_timer_and_not_by_accounting_employee(new_context, cast):
    """П. 3: запись «Отделу ИТ» видят сотрудник вложенной «Группы сети» и совместитель, сотрудник бухгалтерии — нет
    (FR-605)."""
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "Запись отделу " + _word(), to=[("unit", cast.it_name)])
    _see(new_context, cast.net_member, post_id)
    _see(new_context, cast.part_timer, post_id)
    _see(new_context, cast.it_member, post_id)
    hidden = _not_see(new_context, cast.accountant, post_id)
    assert helpers_org.direct_get(hidden, f"/feed/{post_id}/").status == 404


def test_f01_new_unit_member_sees_earlier_post_and_transferred_member_no_longer_sees_it(
        admin_page, mailpit, new_context, cast):
    """П. 4: принятый в подразделение позже видит и прежнюю запись; переведённый из подразделения её больше не видит
    (FR-605)."""
    token = _token()
    mover = helpers.make_employee(admin_page, mailpit, new_context, full_name=f"Переводов{token} Иван Иванович")
    newcomer = helpers.make_employee(admin_page, mailpit, new_context, full_name=f"Новичков{token} Иван Иванович")
    helpers_org.open_structure(admin_page)
    root = helpers_org.root_id(admin_page)
    name_a, name_b = helpers_org.unique_name("Отдел А"), helpers_org.unique_name("Отдел Б")
    unit_a = helpers_org.create_unit(admin_page, name_a, kind="department", parent_id=root)
    unit_b = helpers_org.create_unit(admin_page, name_b, kind="department", parent_id=root)
    helpers_org.add_members(admin_page, unit_a, [mover.id], q=token, mode="concurrent")
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "Запись отделу А " + _word(), to=[("unit", name_a)])
    _see(new_context, mover, post_id)
    _not_see(new_context, newcomer, post_id)
    helpers_org.add_members(admin_page, unit_a, [newcomer.id], q=token, mode="concurrent")
    _see(new_context, newcomer, post_id)  # принятый позже видит прежнюю запись
    helpers_org.open_structure(admin_page, unit_a)
    helpers_org.transfer_member(admin_page, mover.id, unit_b)
    expect(helpers_org.member_row(admin_page, mover.id)).to_have_count(0)
    _not_see(new_context, mover, post_id)  # переведённый записи больше не видит
    _see(new_context, newcomer, post_id)


def test_f01_post_to_unit_and_person_from_other_unit_seen_by_both_with_unit_and_short_name_in_recipients_line(
        new_context, cast):
    """П. 5: запись «Группе сети» и Петрову из другого отдела — видят оба; в строке адресатов — название группы и
    краткое имя «Фамилия И. О.» (FR-603, FR-605)."""
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "Группе и Петрову " + _word(),
                                   to=[("unit", cast.net_name), ("person", cast.petrov.full_name)])
    _see(new_context, cast.net_member, post_id)
    seen = _see(new_context, cast.petrov, post_id)
    line = seen.locator(f"#feed-post-{post_id}-to")
    expect(line).to_contain_text(cast.net_name)
    expect(line).to_contain_text(cast.petrov.full_name.split()[0] + " И. И.")
    _not_see(new_context, cast.plain, post_id)


def test_f01_invisible_post_link_search_and_file_link_answer_like_missing_and_post_absent_from_feed(
        new_context, cast, tmp_path):
    """П. 6: невидимую запись по прямой ссылке, в поиске и по ссылке на её файл не отличить от несуществующей; в ленте
    её нет (FR-604, FR-606)."""
    page = _open(new_context, cast.writer)
    word = _word()
    note = tmp_path / "note.txt"
    note.write_text("Файл записи " + word, encoding="utf-8")
    file_id = helpers_feed.upload(page, note)
    post_id = helpers_feed.publish(page, f"Только для одного {word}", to=[("person", cast.it_member.full_name)])
    other = _not_see(new_context, cast.plain, post_id)
    missing = 2_000_000_000
    for hidden_path, missing_path in ((f"/feed/{post_id}/", f"/feed/{missing}/"),
                                      (f"/feed/files/{file_id}/", f"/feed/files/{missing}/")):
        hidden = helpers_org.direct_get(other, hidden_path)
        absent = helpers_org.direct_get(other, missing_path)
        assert hidden.status == absent.status == 404, (hidden_path, hidden.status, absent.status)
        assert "Не найдено" in hidden.text() and "Не найдено" in absent.text(), hidden_path
    other.goto("/search/?q=" + word)
    other.wait_for_load_state()
    expect(other.locator(f'a[href="/feed/{post_id}/"]')).to_have_count(0)
    expect(other.locator('section[data-search-group="feed"] a')).to_have_count(0)
    owner = _open(new_context, cast.it_member)
    owner.goto("/search/?q=" + word)
    expect(owner.locator(f'section[data-search-group="feed"] a[href="/feed/{post_id}/"]').first).to_be_visible()


def test_f01_empty_blank_or_over_10000_text_refused_with_reason_at_field_and_input_kept(new_context, cast):
    """П. 7: пустой текст, из одних пробелов и длиннее 10 000 знаков не публикуются; у поля причина, введённое
    сохранено (FR-609, FR-642)."""
    page = _open(new_context, cast.writer)
    before = helpers_feed.post_ids(page)
    assert helpers_feed.try_publish(page, "") == [("text", "empty_text")]
    expect(page.locator('[data-error="text"][data-code="empty_text"]')).to_contain_text("Напишите текст")
    assert helpers_feed.try_publish(page, "   ") == [("text", "empty_text")]
    expect(page.locator('form#feed-form textarea[name="text"]')).to_have_value("   ")
    long_text = "а" * 10_001
    assert helpers_feed.try_publish(page, long_text) == [("text", "too_long")]
    expect(page.locator('[data-error="text"][data-code="too_long"]')).to_contain_text("Предел: 10 000 знаков")
    expect(page.locator('form#feed-form textarea[name="text"]')).to_have_value(long_text)
    assert helpers_feed.post_ids(page) == before


def test_f01_no_recipient_or_over_50_recipients_refused_with_reason_at_field_and_input_kept(
        admin_page, new_context, cast):
    """П. 7: «Кому» без адресата и больше 50 адресатов — отказ с причиной у поля «Кому», введённое сохранено
    (FR-610, FR-642). 51 адресат — 51 приглашённый сотрудник, выбранный подсказкой."""
    token = _token()
    page = _open(new_context, cast.writer)
    text = "Без адресата " + _word()
    assert helpers_feed.try_publish(page, text, to=[]) == [("to", "no_recipients")]
    expect(page.locator('[data-error="to"][data-code="no_recipients"]')).to_contain_text("Выберите, кому адресована запись")
    expect(page.locator('form#feed-form textarea[name="text"]')).to_have_value(text)
    names = [_person(admin_page, "Массов", f"{token}{i:02d}")[1] for i in range(51)]
    many = [("person", name) for name in names]
    text = "Слишком много адресатов " + _word()
    assert helpers_feed.try_publish(page, text, to=many) == [("to", "too_many_recipients")]
    expect(page.locator('[data-error="to"][data-code="too_many_recipients"]')).to_contain_text("Не больше 50 адресатов")
    expect(page.locator('form#feed-form textarea[name="text"]')).to_have_value(text)


def test_f01_https_address_becomes_link_opening_in_new_tab_and_markup_shown_as_text(new_context, cast):
    """П. 8: адрес `https://example.org/docs` — ссылка, открывающаяся в новой вкладке; строка `<b>жирный</b>` показана
    как текст (FR-609)."""
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "Документы https://example.org/docs и <b>жирный</b> " + _word(), to=["all"])
    body = page.locator(f"#feed-post-{post_id}-body")
    link = body.locator('a[href="https://example.org/docs"]')
    expect(link).to_have_count(1)
    expect(link).to_have_attribute("target", "_blank")
    expect(body).to_contain_text("<b>жирный</b>")
    expect(body.locator("b")).to_have_count(0)


def test_f01_paragraphs_and_line_breaks_of_text_are_kept(new_context, cast):
    """Абзацы и переводы строк текста сохраняются при показе (FR-609)."""
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "Первый абзац\n\nВторой абзац\nстрока с переносом " + _word(), to=["all"])
    body = page.locator(f"#feed-post-{post_id}-body")
    expect(body.locator("p")).to_have_count(2)
    expect(body.locator("p").first).to_contain_text("Первый абзац")
    expect(body.locator("p").nth(1).locator("br")).to_have_count(1)
    expect(body.locator("p").nth(1)).to_contain_text("строка с переносом")


def test_f01_only_mailto_becomes_link_ftp_and_javascript_stay_text_and_links_have_noopener_noreferrer(
        new_context, cast):
    """П. 13: ссылкой становится только `mailto:`; `ftp://` и `javascript:` остаются текстом; у ссылок записи
    `rel="noopener noreferrer"` (FR-609, NFR-605). Адрес собран из частей."""
    mail = "mailto:" + "it" + "@" + "example.org"
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, f"Почта {mail} ftp://example.org/x javascript:alert(1) " + _word(),
                                   to=["all"], confirm_pdn=True)
    body = page.locator(f"#feed-post-{post_id}-body")
    links = body.locator("a")
    expect(links).to_have_count(1)
    expect(links.first).to_have_attribute("href", mail)
    expect(body.locator('a[href^="ftp"]')).to_have_count(0)
    expect(body.locator('a[href^="javascript"]')).to_have_count(0)
    expect(body).to_contain_text("ftp://example.org/x")
    expect(body).to_contain_text("javascript:alert(1)")
    rel = links.first.get_attribute("rel") or ""
    assert "noopener" in rel and "noreferrer" in rel, rel


def test_f01_script_tag_and_attribute_breakout_in_text_shown_escaped_and_not_executed(new_context, cast):
    """Разметка `<script>` и выход из атрибута в тексте показаны как текст и не выполняются (NFR-605)."""
    page = _open(new_context, cast.writer)
    page.evaluate("() => { window.__feed_xss = 0; }")
    payload = '<script>window.__feed_xss = 1</script> "><img src=x onerror="window.__feed_xss = 2"> '
    post_id = helpers_feed.publish(page, payload + _word(), to=["all"])
    body = page.locator(f"#feed-post-{post_id}-body")
    expect(body).to_contain_text("<script>window.__feed_xss = 1</script>")
    expect(body).to_contain_text('"><img src=x onerror="window.__feed_xss = 2">')
    expect(body.locator("script, img")).to_have_count(0)
    other = _see(new_context, cast.accountant, post_id)
    expect(other.locator(f"#feed-post-{post_id}-body").locator("script, img")).to_have_count(0)
    for tab in (page, other):
        assert tab.evaluate("() => window.__feed_xss || 0") == 0, "разметка текста выполнилась"


def test_f01_feed_of_45_posts_shows_20_then_next_20_by_more_posts_without_reload_then_last_5(
        admin_page, mailpit, new_context, cast):
    """П. 9: в ленте 45 записей — сначала 20, по «Ещё записи» следующие 20 без перезагрузки, потом оставшиеся 5
    (FR-602). Записи стенда предварительно удалены `age(4000)` (иначе чужие «Всем» меняют счёт)."""
    helpers_feed.age(4000)
    reader = helpers.make_employee(admin_page, mailpit, new_context, full_name=f"Читателев{_token()} Иван Иванович")
    writer_page = _open(new_context, cast.writer)
    for i in range(45):
        helpers_feed.publish_request(writer_page, kind="post", text=f"Запись {i + 1} {_word()}", to=f"p{reader.id}")
    page = _open(new_context, reader)
    page.evaluate("() => { window.__no_reload = 1; }")
    assert len(helpers_feed.post_ids(page)) == 20
    more = page.locator("a[data-feed-more], button[data-feed-more]")
    expect(more).to_have_count(1)
    more.click()
    expect(page.locator("#feed-list [data-post-id]")).to_have_count(40)
    expect(more).to_have_count(1)
    more.click()
    expect(page.locator("#feed-list [data-post-id]")).to_have_count(45)
    expect(more).to_have_count(0)
    assert page.evaluate("() => window.__no_reload") == 1, "страница перезагружалась"
    assert len(set(helpers_feed.post_ids(page))) == 45


def test_f01_employee_without_addressed_posts_sees_no_posts_yet(admin_page, mailpit, new_context):
    """П. 9: у сотрудника, которому не адресовано ни одной записи, — «Записей пока нет» (FR-602). Записи «Всем»
    стенда предварительно удалены `age(4000)`."""
    helpers_feed.age(4000)
    lonely = helpers.make_employee(admin_page, mailpit, new_context, full_name=f"Одинцов{_token()} Иван Иванович")
    page = _open(new_context, lonely)
    expect(page.locator('[data-empty-state="feed"]')).to_contain_text("Записей пока нет")
    assert helpers_feed.post_ids(page) == []


def test_f01_anonymous_visitor_goes_to_login_and_user_without_second_factor_to_factor_setup_without_feed(
        admin_page, mailpit, new_context):
    """П. 10: не вошедшего ведёт на вход, вошедшего без второго фактора — на подключение фактора; ленты нет
    (FR-601)."""
    page = new_context().new_page()
    page.goto("/")
    expect(page).to_have_url(re.compile(r"/login/"))
    expect(page.locator('[data-feed-page="home"]')).to_have_count(0)
    expect(page.locator("form#feed-form")).to_have_count(0)
    email, password = factories.new_email("emp"), factories.new_password()
    helpers.create_employee(admin_page, email, full_name=f"Безфактров{_token()} Иван Иванович")
    link = helpers.link_in(helpers.wait_mail(mailpit, email, "invitation"), "/activate/")
    step = new_context().new_page()
    helpers.open_activation_link(step, link)
    step.click("button[type=submit]")
    step.wait_for_url(re.compile(r"/activate/password/"))
    step.fill("input[name=password1]", password)
    step.fill("input[name=password2]", password)
    step.click("button[type=submit]")
    step.wait_for_url(re.compile(r"/activate/totp/"))
    later = new_context().new_page()
    helpers.fill_login(later, email, password)
    later.wait_for_url(re.compile(r"/me/security/totp/"))
    later.goto("/")
    expect(later).to_have_url(re.compile(r"/me/security/totp/"))
    expect(later.locator('[data-feed-page="home"]')).to_have_count(0)
    expect(later.locator("#feed-list")).to_have_count(0)


def test_f01_post_of_deleted_unit_seen_by_person_and_author_with_unit_deleted_and_person_in_recipients_line(
        admin_page, new_context, cast):
    """П. 11: подразделение расформировано и удалено — запись видят Петров и автор; в строке адресатов «Подразделение
    удалено» и Петров (FR-607)."""
    helpers_org.open_structure(admin_page)
    root = helpers_org.root_id(admin_page)
    name = helpers_org.unique_name("Временная группа")
    unit = helpers_org.create_unit(admin_page, name, kind="team", parent_id=root)
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "Запись временной группе " + _word(),
                                   to=[("unit", name), ("person", cast.petrov.full_name)])
    dialog = helpers_org.open_delete_dialog(admin_page, unit)
    helpers_org.confirm_delete(admin_page, dialog)
    expect(dialog).to_have_count(0)
    short = cast.petrov.full_name.split()[0] + " И. И."
    for account in (cast.petrov, cast.writer):
        seen = _see(new_context, account, post_id)
        line = seen.locator(f"#feed-post-{post_id}-to")
        expect(line).to_contain_text("Подразделение удалено")
        expect(line).to_contain_text(short)
        expect(line).not_to_contain_text(name)


def test_f01_eight_recipients_line_shows_first_five_and_4_more_and_full_list_on_click_with_mentioned_and_dismissed_mark(
        admin_page, new_context, cast):
    """П. 12: запись восьми сотрудникам (один уволен), в комментарии упомянут Сидоров: в строке первые пять и «и ещё 4»,
    по нажатию — полный список с Сидоровым; уволенный — «ФИО (уволен)» (FR-603, FR-607)."""
    token = _token()
    leaver_id, leaver_name = _person(admin_page, "Уволенов", token)
    people = [cast.plain, cast.moderator, cast.it_member, cast.net_member, cast.part_timer, cast.accountant,
              cast.petrov]
    page = _open(new_context, cast.writer)
    to = [("person", account.full_name) for account in people] + [("person", leaver_name)]
    post_id = helpers_feed.publish(page, "Восьми сотрудникам " + _word(), to=to)
    _dismiss(admin_page, leaver_id)
    helpers_feed.add_comment(page, post_id, "Подключаем коллегу", mentions=[cast.sidorov.full_name])
    page.reload()
    line = page.locator(f"#feed-post-{post_id}-to")
    expect(line.locator("[data-to-item]")).to_have_count(5)
    more = line.locator("a[data-to-more]")
    expect(more).to_contain_text("и ещё 4")
    more.click()
    full = page.locator(f'#feed-post-{post_id} ul[data-feed-list="recipients"]')
    expect(full).to_be_visible()
    expect(full).to_contain_text(cast.sidorov.full_name)
    expect(full).to_contain_text(f"{leaver_name} (уволен)")
    for account in people:
        expect(full).to_contain_text(account.full_name)


def test_f01_feed_and_form_with_recipients_and_suggestions_have_no_horizontal_scroll_at_360px(new_context, cast):
    """Лента и форма с адресатами и подсказками на ширине 360 px — без горизонтальной прокрутки (NFR-606)."""
    page = _open(new_context, cast.writer)
    helpers_feed.publish(page, "Узкий экран, длинная строка без пробелов " + "ж" * 80 + " " + _word(),
                         to=[("unit", cast.it_name), ("unit", cast.net_name), ("person", cast.petrov.full_name),
                             ("person", cast.sidorov.full_name)])
    assert helpers_feed.check_360(page)
    field = page.locator('form#feed-form input[data-feed-picker="to"]')
    field.fill("")
    field.press_sequentially(cast.accountant.full_name.split()[0][:8], delay=30)
    expect(page.locator("[data-feed-pick-list] [data-pick-label]").first).to_be_visible()
    assert helpers_feed.check_360(page)
