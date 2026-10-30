"""T-7141: сценарий 2 — важная запись, «Прочитано», кто прочитал (FR-602, FR-605, FR-606, FR-613, FR-614, FR-615,
FR-620, FR-629, FR-630, FR-642, NFR-606).

Общее для файла (шаблон e2e/template.md, CONTRACT-007.md, разделы 10, 12, 13, 14.4):
- люди и узлы круга — `helpers_feed.feed_cast` (один раз на круг браузера; сессии сохранены в
  `Account.storage_state`); «40 адресатов» (п. 4, 11) — отдельные большие узлы: приглашённые без активации остаются
  адресатами (план: «действующий» — не заблокирован и не уволен), активированы только те, кто нажимает «Прочитано»;
  узел больше 20 человек добавляется пачками по ≤ 20 с разными частями ФИО (в подсказке структуры предел 20);
- конец срока на стенде — `helpers_feed.shift(2900)`: срок «День» кончается не позже чем через 48 часов, а команда
  сдвигает назад и `important_until` ВСЕХ важных записей стенда (решение 54 задач), поэтому тесты не опираются на
  чужие записи; точный конец срока по Москве (12.10 00:00) проверяет серверный T-7112;
- уведомления — по строкам «Мои уведомления» (`helpers_feed.my_notifications`), в тексте — уникальное слово теста;
- локальные помощники файла: `_edit` (правка записи `/feed/<id>/edit/`, поля раздела 10.2), `_dismiss`, `_block`,
  `_wait_note`; кнопки правки и сохранения контракт называет не полностью — форма берётся как первая форма
  `[data-feed-page="edit"]`, кнопка — первая `button[type=submit]`;
- локаторы — раздел 12 контракта, тексты — раздел 13; время и даты — по Москве.
"""
import re
import secrets
import types
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers, helpers_feed, helpers_org

_CASTS: dict = {}
_CROWDS: dict = {}
EXPIRE = 2900  # минут: больше 48 часов — срок «День» гарантированно истёк


# --- Общие помощники файла -----------------------------------------------------------------------------------------

def _today() -> date:
    return datetime.now(ZoneInfo("Europe/Moscow")).date()


def _plus_year(day: date) -> date:
    try:
        return day.replace(year=day.year + 1)
    except ValueError:  # 29 февраля
        return day.replace(year=day.year + 1, day=28)


def _word() -> str:
    return "".join(secrets.choice("абвгдежзиклмнопрстуф") for _ in range(12))


def _token() -> str:
    return helpers_org.unique_name("к")[2:]


def _unit_name(page, unit_id) -> str:
    helpers_org.open_structure(page, unit_id)
    return helpers_org.unit_link(page, unit_id).inner_text().strip().splitlines()[0].strip()


def _dismiss(page, user_id) -> None:
    """Увольнение из карточки (образец — test_o07_dismiss)."""
    page.goto(f"/staff/{user_id}/")
    page.locator('[data-action="dismiss"]').first.click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(page.locator("[data-dismissed-badge]").first).to_be_visible()


def _block(page, user_id) -> None:
    """Блокировка из вкладки «Безопасность» карточки (образец — test_l13_rights)."""
    page.goto(f"/staff/{user_id}/")
    helpers.open_security_tab(page)
    form = page.locator('form[action$="/block/"]')
    form.locator("[name=reason]").fill("проверка ленты")
    helpers.submit(form)


def _open(new_context, account):
    return helpers_feed.open_feed(new_context(), account)


def _wait_note(page, *markers, timeout: int = 30_000) -> list:
    """Ждёт в «Моих уведомлениях» строку(и) со всеми `markers`; возвращает такие строки."""
    deadline = datetime.now().timestamp() + timeout / 1000
    while True:
        found = [t for t in helpers_feed.my_notifications(page) if all(m in t for m in markers)]
        if found or datetime.now().timestamp() > deadline:
            assert found, f"в «Моих уведомлениях» нет строки с {markers}"
            return found
        page.wait_for_timeout(1_000)


def _notes_with(page, *markers) -> list:
    return [t for t in helpers_feed.my_notifications(page) if all(m in t for m in markers)]


def _pick_to(page, form, label: str) -> None:
    field = form.locator('input[data-feed-picker="to"]')
    pills = form.locator("[data-to-pill]")
    before = pills.count()
    field.fill("")
    field.press_sequentially(label.split()[0], delay=30)
    option = page.locator(f'[data-feed-pick-list] [data-pick-label="{label}"]').first
    expect(option).to_be_visible(timeout=10_000)
    option.click()
    expect(pills).to_have_count(before + 1)


def _edit(page, post_id, *, text=None, to=(), mention=None, term=None, until=None) -> None:
    """Правка записи автором: `/feed/<id>/edit/`, форма правки (поля раздела 10.2), «Сохранить» (первая кнопка отправки)."""
    page.goto(f"/feed/{post_id}/edit/")
    page.wait_for_load_state()
    expect(page.locator('[data-feed-page="edit"]')).to_be_visible()
    form = page.locator('[data-feed-page="edit"] form').first
    body = form.locator('textarea[name="text"]')
    if text is not None:
        body.fill(text)
    for label in to:
        _pick_to(page, form, label)
    if mention:
        body.click()
        body.press("End")
        helpers_feed.pick_mention(page, body, mention.split()[0], mention)
    if term:
        helpers_org.set_choice(form, "term", term)
        if until:
            form.locator('input[name="until"]').fill(str(until))
    with page.expect_response(lambda r: r.request.method == "POST" and f"/feed/{post_id}/edit/" in r.url):
        form.locator("button[type=submit]").first.click()
    page.wait_for_load_state()


def _novalidate(page) -> None:
    """Проверку полей форм браузером отключаем: нужен ответ сервера с причиной у поля, а не подсказка браузера."""
    page.evaluate("() => { document.querySelectorAll('form#feed-form').forEach(f => { f.noValidate = true; }); }")


def _imp(page, post_id):
    return page.locator(f"#feed-post-{post_id}-imp")


def _open_reads(page, post_id):
    """Автор или модератор нажимает «Прочитали N из M»: открываются списки отметивших."""
    counter = _imp(page, post_id).locator("[data-feed-reads-count]").first
    counter.click()
    lists = page.locator('[data-feed-list="reads"]')
    expect(lists).to_be_visible()
    return lists


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


def _crowd_unit(admin_page, name_prefix: str, groups: list) -> tuple:
    """Узел с участниками из `groups` — списков `(фамилия, число)`; приглашённые без активации. Возвращает
    `(название узла, список ФИО, номера)`; в каждой пачке ≤ 20 человек (предел подсказки структуры)."""
    token = _token()
    helpers_org.open_structure(admin_page)
    unit_name = helpers_org.unique_name(name_prefix)
    unit = helpers_org.create_unit(admin_page, unit_name, kind="department", parent_id=helpers_org.root_id(admin_page))
    names, ids = [], []
    for index, (surname, count) in enumerate(groups):
        batch = []
        for n in range(count):
            full = f"{surname}{token}{chr(97 + index)}{n:02d} Иван Иванович"
            batch.append(helpers.create_employee(admin_page, factories.new_email("emp"), full_name=full))
            names.append(full)
        helpers_org.add_members(admin_page, unit, batch, q=f"{surname}{token}{chr(97 + index)}", mode="concurrent")
        ids += batch
    return unit_name, names, ids


@pytest.fixture
def crowd_post(admin_page, mailpit, new_context, stand_admin, cast):
    """Важная запись узлу из 40 человек: 12 активированных нажали «Прочитано», 28 приглашённых не читали (п. 4);
    один набор на круг браузера."""
    found = _CROWDS.get(stand_admin.email)
    if found is None:
        token = _token()
        readers = [helpers.make_employee(admin_page, mailpit, new_context, full_name=f"Читатель{token}{n:02d} Иван Иванович")
                   for n in range(12)]
        helpers_org.open_structure(admin_page)
        unit_name = helpers_org.unique_name("Большой отдел")
        unit = helpers_org.create_unit(admin_page, unit_name, kind="department",
                                       parent_id=helpers_org.root_id(admin_page))
        helpers_org.add_members(admin_page, unit, [r.id for r in readers], q=f"Читатель{token}", mode="concurrent")
        silent = []
        for index in range(2):
            batch = []
            for n in range(14):
                full = f"Молчунов{token}{chr(97 + index)}{n:02d} Иван Иванович"
                batch.append(helpers.create_employee(admin_page, factories.new_email("emp"), full_name=full))
                silent.append(full)
            helpers_org.add_members(admin_page, unit, batch, q=f"Молчунов{token}{chr(97 + index)}", mode="concurrent")
        page = _open(new_context, cast.writer)
        text = "Важное большому отделу " + _word()
        post_id = helpers_feed.publish(page, text, kind="important", term="week", to=[("unit", unit_name)])
        for reader in readers:
            tab = _open(new_context, reader)
            helpers_feed.mark_read(tab, post_id)
            expect(tab.locator(f'#feed-post-{post_id}-imp button[data-action="read"]')).to_have_count(0)
        for account in readers:
            account.storage_state = account.page.context.storage_state()
            account.page = None
        found = types.SimpleNamespace(post_id=post_id, readers=readers, silent=silent, unit_name=unit_name)
        _CROWDS[stand_admin.email] = found
    return found


# --- Тесты ---------------------------------------------------------------------------------------------------------

def test_f02_important_kind_offers_day_week_month_and_until_date_terms(new_context, cast):
    """П. 1: у вида «Важное» доступны сроки «День», «Неделя», «Месяц», «До даты» (FR-613)."""
    page = _open(new_context, cast.writer)
    form = page.locator("form#feed-form")
    form.locator('label:has(input[name="kind"][value="important"])').click()
    block = form.locator('[data-kind-fields="important"]')
    expect(block).to_be_visible()
    for value, label in (("day", "День"), ("week", "Неделя"), ("month", "Месяц"), ("date", "До даты")):
        expect(block.locator(f'input[type=radio][name="term"][value="{value}"]')).to_have_count(1)
        expect(block).to_contain_text(label)
    assert block.locator('input[name="term"]').count() == 4


def test_f02_until_date_field_allows_choice_only_from_tomorrow_to_one_year_ahead(new_context, cast):
    """П. 1: дата срока — не раньше завтрашнего дня и не позже чем через год: поле даты принимает только такие
    значения (граничные значения проверяет `validity` поля, FR-613)."""
    page = _open(new_context, cast.writer)
    form = page.locator("form#feed-form")
    form.locator('label:has(input[name="kind"][value="important"])').click()
    helpers_org.set_choice(form, "term", "date")
    until = form.locator('input[name="until"]')
    expect(until).to_be_visible()
    today = _today()
    last = _plus_year(today)

    def valid(value: date) -> bool:
        return until.evaluate("(el, v) => { el.value = v; return el.validity.valid; }", value.isoformat())

    assert not valid(today), "сегодняшняя дата допустима"
    assert valid(today + timedelta(days=1)), "завтрашняя дата недопустима"
    assert valid(last), "дата через год недопустима"
    assert not valid(last + timedelta(days=1)), "дата позже чем через год допустима"


def test_f02_week_important_post_for_unit_stands_in_block_above_feed_with_important_until_date_and_read_button(
        new_context, cast):
    """П. 2: важная запись отделу на неделю у адресата стоит в блоке важных над лентой с датой «важно до» и кнопкой
    «Прочитано» (FR-602, FR-614)."""
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "Важное на неделю " + _word(), kind="important", term="week",
                                   to=[("unit", cast.it_name)])
    tab = _open(new_context, cast.it_member)
    assert post_id in helpers_feed.important_ids(tab)
    assert post_id not in helpers_feed.post_ids(tab), "запись повторена в основной ленте"
    block_top = tab.locator("#feed-important").bounding_box()["y"]
    feed_top = tab.locator("#feed-list").bounding_box()["y"]
    assert block_top < feed_top, "блок важных не над лентой"
    imp = _imp(tab, post_id)
    expect(imp).to_contain_text(re.compile(r"Важное, важно до \d{2}\.\d{2}\.\d{4}"))
    shown = re.search(r"важно до (\d{2})\.(\d{2})\.(\d{4})", imp.inner_text()).groups()
    until = date(int(shown[2]), int(shown[1]), int(shown[0]))
    assert _today() + timedelta(days=6) <= until <= _today() + timedelta(days=8), until
    expect(imp.locator('button[data-action="read"]')).to_be_visible()
    expect(imp.locator('button[data-action="read"]')).to_have_text("Прочитано")


def test_f02_read_click_moves_card_from_block_into_feed_by_publish_time_without_reload_and_removes_read_button(
        new_context, cast):
    """П. 3: после «Прочитано» запись уходит из блока важных и встаёт в ленту по времени публикации без перезагрузки;
    кнопки «Прочитано» больше нет (FR-614)."""
    page = _open(new_context, cast.writer)
    important = helpers_feed.publish(page, "Важное для чтения " + _word(), kind="important", term="week",
                                     to=[("unit", cast.it_name)])
    ordinary = helpers_feed.publish(page, "Обычная после важной " + _word(), to=[("unit", cast.it_name)])
    tab = _open(new_context, cast.it_member)
    tab.evaluate("() => { window.__no_reload = 1; }")
    assert important in helpers_feed.important_ids(tab) and ordinary in helpers_feed.post_ids(tab)
    helpers_feed.mark_read(tab, important)
    expect(tab.locator(f"#feed-important #feed-post-{important}")).to_have_count(0)
    expect(tab.locator(f"#feed-list #feed-post-{important}")).to_be_visible()
    order = helpers_feed.post_ids(tab)
    assert order.index(ordinary) < order.index(important), "прочитанная запись встала не по времени публикации"
    expect(_imp(tab, important).locator('button[data-action="read"]')).to_have_count(0)
    assert tab.evaluate("() => window.__no_reload") == 1, "страница перезагружалась"


def test_f02_after_reload_read_post_stays_in_feed_out_of_block_and_read_cannot_be_undone(new_context, cast):
    """После перезагрузки прочитанная запись остаётся в ленте, не возвращается в блок важных, отмены «Прочитано»
    нет (FR-614)."""
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "Важное без отмены " + _word(), kind="important", term="week",
                                   to=[("unit", cast.it_name)])
    tab = _open(new_context, cast.it_member)
    helpers_feed.mark_read(tab, post_id)
    tab.reload()
    tab.wait_for_load_state()
    assert post_id in helpers_feed.post_ids(tab)
    assert post_id not in helpers_feed.important_ids(tab)
    imp = _imp(tab, post_id)
    expect(imp.locator('button[data-action="read"]')).to_have_count(0)
    expect(imp.locator('button[data-action="unread"], [data-action="unread"]')).to_have_count(0)
    assert helpers_feed.badge(tab) >= 0


def test_f02_author_sees_read_12_of_40_and_on_click_readers_with_time_and_non_readers(cast, crowd_post, new_context):
    """П. 4: из 40 адресатов прочитали 12 — автор видит «Прочитали 12 из 40» и по нажатию списки прочитавших (со
    временем) и не прочитавших (FR-615)."""
    page = helpers_feed.open_card(new_context(), cast.writer, crowd_post.post_id)
    imp = _imp(page, crowd_post.post_id)
    expect(imp.locator("[data-feed-reads-count]")).to_contain_text("Прочитали 12 из 40")
    lists = _open_reads(page, crowd_post.post_id)
    read, unread = lists.locator('[data-feed-reads="read"]'), lists.locator('[data-feed-reads="unread"]')
    for reader in crowd_post.readers:
        expect(read).to_contain_text(reader.full_name)
    expect(read.locator("time[data-at]")).to_have_count(12)
    for name in crowd_post.silent:
        expect(unread).to_contain_text(name)
    for reader in crowd_post.readers:
        expect(unread).not_to_contain_text(reader.full_name)


def test_f02_ordinary_recipient_sees_only_read_12_without_lists(cast, crowd_post, new_context):
    """П. 4: обычный адресат видит только «Прочитали 12»: ни числа адресатов, ни списков (FR-615)."""
    reader = crowd_post.readers[0]
    page = helpers_feed.open_card(new_context(), reader, crowd_post.post_id)
    counter = _imp(page, crowd_post.post_id).locator("[data-feed-reads-count]")
    expect(counter).to_contain_text("Прочитали 12")
    expect(counter).not_to_contain_text("из")
    expect(_imp(page, crowd_post.post_id).locator('a[href$="/reads/"], a[hx-get$="/reads/"]')).to_have_count(0)
    assert helpers_org.direct_get(page, f"/feed/{crowd_post.post_id}/reads/").status == 403


def test_f02_moderator_among_recipients_sees_author_lists_and_moderator_not_addressed_does_not_see_post(
        new_context, cast):
    """П. 5: модератор среди адресатов видит те же списки, что автор; модератору, которому запись не адресована, её не
    видно вовсе (FR-606, FR-615)."""
    page = _open(new_context, cast.writer)
    addressed = helpers_feed.publish(page, "Важное с модератором " + _word(), kind="important", term="week",
                                     to=[("person", cast.moderator.full_name), ("person", cast.it_member.full_name)])
    hidden = helpers_feed.publish(page, "Важное без модератора " + _word(), kind="important", term="week",
                                  to=[("person", cast.it_member.full_name)])
    tab = _open(new_context, cast.moderator)
    expect(_imp(tab, addressed).locator("[data-feed-reads-count]")).to_contain_text(re.compile(r"Прочитали \d+ из \d+"))
    lists = _open_reads(tab, addressed)
    expect(lists.locator('[data-feed-reads="unread"]')).to_contain_text(cast.it_member.full_name)
    expect(tab.locator(f"#feed-post-{hidden}")).to_have_count(0)
    assert helpers_org.direct_get(tab, f"/feed/{hidden}/").status == 404


def test_f02_after_term_expiry_unread_post_left_block_and_stands_in_feed_as_ordinary_without_reminders(
        new_context, cast):
    """П. 6: срок истёк — запись, которую адресат не прочитал, ушла из блока важных и стоит в ленте обычной; новых
    напоминаний о непрочитанном нет (FR-613, FR-614)."""
    word = _word()
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "Важное на день " + word, kind="important", term="day",
                                   to=[("person", cast.it_member.full_name)])
    tab = _open(new_context, cast.it_member)
    assert post_id in helpers_feed.important_ids(tab)
    before = _wait_note(tab, "Важная запись", word)
    helpers_feed.shift(EXPIRE)
    tab.reload()
    tab.wait_for_load_state()
    assert post_id not in helpers_feed.important_ids(tab), "истёкшая запись осталась в блоке важных"
    assert post_id in helpers_feed.post_ids(tab), "истёкшей записи нет в ленте"
    expect(_imp(tab, post_id).locator('button[data-action="read"]')).to_have_count(0)
    assert _notes_with(tab, word) == before, "после срока пришли новые уведомления о записи"


def test_f02_until_date_13_months_ahead_or_yesterday_refused_with_reason_at_term_field(new_context, cast):
    """П. 7: «До даты» через 13 месяцев или вчерашняя — отказ с причиной у поля срока (FR-613, FR-642)."""
    page = _open(new_context, cast.writer)
    before = helpers_feed.post_ids(page)
    _novalidate(page)
    far = _today() + timedelta(days=396)
    codes = helpers_feed.try_publish(page, "Срок слишком далёкий " + _word(), kind="important", term="date", until=far)
    assert codes == [("term", "term_too_far")], codes
    expect(page.locator('[data-error="term"][data-code="term_too_far"]')).to_contain_text("Срок — не позже чем через год")
    _novalidate(page)
    past = _today() - timedelta(days=1)
    codes = helpers_feed.try_publish(page, "Срок уже прошёл " + _word(), kind="important", term="date", until=past)
    assert codes == [("term", "date_passed")], codes
    expect(page.locator('[data-error="term"][data-code="date_passed"]')).to_contain_text("Дата уже прошла")
    assert helpers_feed.post_ids(page) == before


def test_f02_author_sees_own_important_post_in_feed_by_time_not_in_block_and_unread_recipient_sees_it_only_in_block(
        new_context, cast):
    """П. 8: у автора важная запись — в ленте по времени, не в блоке; у адресата, не нажавшего «Прочитано», — в блоке
    и в основной ленте не повторяется (FR-602, FR-614)."""
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "Важное автору " + _word(), kind="important", term="week",
                                   to=[("unit", cast.it_name)])
    page.reload()
    page.wait_for_load_state()
    assert post_id in helpers_feed.post_ids(page)
    assert post_id not in helpers_feed.important_ids(page)
    expect(_imp(page, post_id).locator('button[data-action="read"]')).to_have_count(0)
    tab = _open(new_context, cast.it_member)
    assert post_id in helpers_feed.important_ids(tab)
    assert post_id not in helpers_feed.post_ids(tab)


def test_f02_expired_day_term_post_shows_was_important_mark_and_read_5(new_context, cast):
    """П. 9: запись со сроком «День» после срока — в ленте обычной с пометкой «было важным» и «Прочитали 5» (FR-613).
    Точное время конца срока (12.10 00:00 по Москве) проверяет серверный T-7112."""
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "Важное на день, пять прочли " + _word(), kind="important", term="day",
                                   to=[("unit", cast.it_name), ("unit", cast.acc_name)])
    for account in (cast.it_member, cast.net_member, cast.part_timer, cast.accountant, cast.petrov):
        tab = _open(new_context, account)
        helpers_feed.mark_read(tab, post_id)
    helpers_feed.shift(EXPIRE)
    viewer = _open(new_context, cast.sidorov)
    assert post_id in helpers_feed.post_ids(viewer) and post_id not in helpers_feed.important_ids(viewer)
    imp = _imp(viewer, post_id)
    expect(imp.locator("[data-feed-was-important]")).to_contain_text("было важным")
    counter = imp.locator("[data-feed-reads-count]")
    expect(counter).to_contain_text("Прочитали 5")
    expect(counter).not_to_contain_text("из")


def test_f02_author_edit_form_makes_expired_post_important_for_week_counted_from_edit_date_and_keeps_reads(
        new_context, cast):
    """П. 9: автор правкой снова делает истёкшую запись важной на «Неделю»; срок считается от даты правки, прочтения
    сохранены (FR-613, FR-620). Дату публикации сдвигает `age(2, posts=[…])`, чтобы отсчёт от правки отличался от отсчёта
    от публикации."""
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "Важное, потом снова важное " + _word(), kind="important", term="day",
                                   to=[("unit", cast.it_name)])
    helpers_feed.mark_read(_open(new_context, cast.it_member), post_id)
    helpers_feed.shift(EXPIRE)
    helpers_feed.age(2, posts=[post_id])
    _edit(page, post_id, term="week")
    card = helpers_feed.open_card(new_context(), cast.writer, post_id)
    imp = _imp(card, post_id)
    expect(imp).to_contain_text(re.compile(r"Важное, важно до \d{2}\.\d{2}\.\d{4}"))
    shown = re.search(r"важно до (\d{2})\.(\d{2})\.(\d{4})", imp.inner_text()).groups()
    until = date(int(shown[2]), int(shown[1]), int(shown[0]))
    assert _today() + timedelta(days=7) <= until <= _today() + timedelta(days=8), f"срок {until} не от даты правки"
    expect(imp.locator("[data-feed-reads-count]")).to_contain_text(re.compile(r"Прочитали 1 из \d+"))
    expect(imp.locator("[data-feed-was-important]")).to_have_count(0)


def test_f02_petrov_added_to_to_by_edit_gets_important_post_and_when_also_mentioned_gets_you_were_mentioned(
        new_context, cast):
    """П. 10: автор правкой добавляет в «Кому» Петрова — тот получает «Важная запись»; если Петрова при этом упомянули
    в тексте — «Вас упомянули» (FR-629, FR-630)."""
    page = _open(new_context, cast.writer)
    first, second = _word(), _word()
    only_to = helpers_feed.publish(page, "Важное, правка «Кому» " + first, kind="important", term="week",
                                   to=[("unit", cast.it_name)])
    both = helpers_feed.publish(page, "Важное, правка «Кому» и текста " + second, kind="important", term="week",
                                to=[("unit", cast.it_name)])
    tab = _open(new_context, cast.petrov)
    assert _notes_with(tab, first) == [] and _notes_with(tab, second) == []
    _edit(page, only_to, to=[cast.petrov.full_name])
    note = _wait_note(tab, "Важная запись", first)
    assert note, note
    _edit(page, both, to=[cast.petrov.full_name], mention=cast.petrov.full_name)
    mention = _wait_note(tab, "упомянул(а) вас", second)
    assert mention, mention


def test_f02_dismissed_and_blocked_recipients_excluded_from_m_37_and_from_both_lists(admin_page, new_context, cast):
    """П. 11: из 40 адресатов двое уволены и один заблокирован — M равно 37; их нет ни в списке прочитавших, ни в
    списке не прочитавших (FR-605, FR-615). Адресаты — приглашённые без активации (40 человек, затем 3 действия)."""
    unit_name, names, ids = _crowd_unit(admin_page, "Отдел сорока", [("Сорокин", 14), ("Сорокин", 13), ("Сорокин", 13)])
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "Важное сорока " + _word(), kind="important", term="week",
                                   to=[("unit", unit_name)])
    gone = [(ids[0], names[0]), (ids[1], names[1])]
    locked = (ids[2], names[2])
    for user_id, _ in gone:
        _dismiss(admin_page, user_id)
    _block(admin_page, locked[0])
    card = helpers_feed.open_card(new_context(), cast.writer, post_id)
    expect(_imp(card, post_id).locator("[data-feed-reads-count]")).to_contain_text("Прочитали 0 из 37")
    lists = _open_reads(card, post_id)
    unread = lists.locator('[data-feed-reads="unread"]')
    for user_id, name in gone + [locked]:
        expect(lists).not_to_contain_text(name)
    for name in names[3:]:
        expect(unread).to_contain_text(name)
    expect(lists.locator('[data-feed-reads="read"]')).not_to_contain_text("Сорокин")


def test_f02_important_block_and_readers_lists_have_no_horizontal_scroll_at_360px(new_context, cast):
    """Блок важных и списки прочитавших на ширине 360 px — без горизонтальной прокрутки (NFR-606)."""
    page = _open(new_context, cast.writer)
    post_id = helpers_feed.publish(page, "Важное, узкий экран " + "ж" * 80 + " " + _word(), kind="important",
                                   term="week", to=[("unit", cast.it_name), ("unit", cast.acc_name)])
    tab = _open(new_context, cast.it_member)
    assert post_id in helpers_feed.important_ids(tab)
    assert helpers_feed.check_360(tab)
    page.reload()
    page.wait_for_load_state()
    _open_reads(page, post_id)
    assert helpers_feed.check_360(page)
