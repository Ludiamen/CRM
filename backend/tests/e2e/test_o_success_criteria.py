"""T-2150: критерии успеха спеки среза 002, измеряемые временем (FR-101…105, FR-110, FR-130, FR-139, FR-145).

Каждый тест проходит путь интерфейсом и сравнивает `time.monotonic()` с пределом критерия (plan.md, «Критерии
успеха спеки и чем они проверяются»). Подготовка (заведение людей, узлов-целей) в замер не входит; в замер входят
только шаги самого критерия. Человеческое время (10 минут на структуру) — ручной проход владельца: здесь проверяется,
что путь есть и не медленный. Нагрузка (500 мс при 100 пользователях) — locust, не e2e.
"""
import re
import secrets
import time

from playwright.sync_api import expect

from tests import factories, support_org
from tests.e2e import helpers, helpers_org
from tests.e2e.helpers_org import (add_members, audit_rows, create_unit, descendant_li, member_row, open_structure,
                                   root_id, transfer_member, unique_name, unit_li)

IMPORT_ID_URL = re.compile(r"/structure/import/(\d+)/$")
CALENDAR_YEAR = 2027  # год файла tests/fixtures/calendar/cal2027.csv
CALENDAR_DAY = "2027-03-17"  # обычная среда: после загрузки года день без особого вида


def test_five_departments_three_teams_path_timed(admin_page):
    """Критерий 1, FR-101…105: администратор строит структуру из 5 отделов и 3 команд интерфейсом «Создать» —
    путь есть и не медленный (предел машинного прохода — 10 минут); все узлы видны в дереве под своими
    родителями, команды отмечены как команды, журнал знает о создании каждого узла."""
    page = admin_page
    open_structure(page)
    rid = root_id(page)

    started = time.monotonic()
    departments = [create_unit(page, unique_name(f"Отдел{i}"), kind="department", parent_id=rid) for i in range(5)]
    teams = [
        create_unit(page, unique_name("Команда1"), kind="team", parent_id=departments[0]),
        create_unit(page, unique_name("Команда2"), kind="team", parent_id=departments[1]),
        create_unit(page, unique_name("Команда3"), kind="team", parent_id=departments[1]),
    ]
    elapsed = time.monotonic() - started
    assert elapsed < 600, f"структура из 5 отделов и 3 команд собрана за {elapsed:.0f} с (предел 600 с)"

    # результат виден пользователю: дерево, вид узла, вложенность
    open_structure(page)
    for unit_id in departments:
        expect(descendant_li(page, rid, unit_id)).to_have_count(1)
        expect(unit_li(page, unit_id)).to_have_attribute("data-kind", "department")
    for unit_id, parent in zip(teams, (departments[0], departments[1], departments[1])):
        expect(descendant_li(page, parent, unit_id)).to_have_count(1)
        expect(unit_li(page, unit_id)).to_have_attribute("data-kind", "team")
    # журнал: по событию создания на каждый из восьми узлов
    for unit_id in departments + teams:
        assert len(audit_rows(page, "unit.created", unit_id)) == 1, f"нет записи о создании узла {unit_id}"


def test_transfer_or_concurrent_within_30_seconds(admin_page):
    """Критерий 2, FR-110: администратор ставит сотрудника в отдел — режим «перевести», режим «добавить как
    совместителя» и пункт меню «…» «Перевести в другой отдел» — каждое действие не дольше 30 секунд (от открытия
    карточки узла до готового результата в ней)."""
    page = admin_page
    tag = secrets.token_hex(3)
    open_structure(page)
    rid = root_id(page)
    dept_a = create_unit(page, unique_name("Сеть"), kind="department", parent_id=rid)
    dept_b = create_unit(page, unique_name("Поддержка"), kind="department", parent_id=rid)
    dept_c = create_unit(page, unique_name("Разработка"), kind="department", parent_id=rid)
    user_id = helpers.create_employee(page, factories.new_email("mv"), full_name=f"Перев{tag} Пётр Петрович")
    add_members(page, dept_a, [user_id], q=f"Перев{tag}", mode="transfer")  # исходное положение: только в «Сети»

    # режим «перевести»: из «Сети» в «Поддержку»
    started = time.monotonic()
    add_members(page, dept_b, [user_id], q=f"Перев{tag}", mode="transfer")
    expect(member_row(page, user_id)).to_have_count(1)
    elapsed = time.monotonic() - started
    assert elapsed < 30, f"перевод режимом «перевести» занял {elapsed:.0f} с"
    open_structure(page, dept_a)
    expect(member_row(page, user_id)).to_have_count(0)

    # режим «добавить как совместителя»: «Разработка» к «Поддержке»
    started = time.monotonic()
    add_members(page, dept_c, [user_id], q=f"Перев{tag}", mode="concurrent")
    expect(member_row(page, user_id)).to_have_count(1)
    elapsed = time.monotonic() - started
    assert elapsed < 30, f"совместительство заняло {elapsed:.0f} с"
    open_structure(page, dept_b)
    expect(member_row(page, user_id)).to_have_count(1)  # из «Поддержки» не ушёл

    # меню «…» → «Перевести в другой отдел»: из «Разработки» в «Сеть»
    open_structure(page, dept_c)
    started = time.monotonic()
    transfer_member(page, user_id, dept_a)
    expect(member_row(page, user_id)).to_have_count(0)  # после 302 карточка исходного узла без него
    elapsed = time.monotonic() - started
    assert elapsed < 30, f"перевод через меню занял {elapsed:.0f} с"
    open_structure(page, dept_a)
    expect(member_row(page, user_id)).to_have_count(1)
    open_structure(page, dept_b)
    expect(member_row(page, user_id)).to_have_count(1)  # во втором узле остался


def test_file_100_rows_to_result_within_5_minutes(admin_page):
    """Критерий 3, FR-139: файл на 100 сотрудников — от открытия страницы загрузки и выбора файла до итога («создано
    100, пропущено 0, с ошибками 0») не дольше 5 минут. Приглашения не отправляются (замер файла, не почты):
    письма уходят после фиксации и в критерий «до итога» не входят (plan.md:399, 488)."""
    page = admin_page
    token = secrets.token_hex(3)
    emails = [factories.new_email("ok") for _ in range(100)]
    content = support_org.staff_csv(
        [support_org.staff_row(email=e, last_name=f"Срок{token}{i}", position=f"Инженер {token}")
         for i, e in enumerate(emails)])

    started = time.monotonic()
    page.goto("/structure/import/")
    form = page.locator('form[data-form="import-upload"]')
    expect(form).to_be_visible()
    helpers_org.upload_file(form, content, name=f"people-{token}.csv", mime="text/csv")
    page.wait_for_url(IMPORT_ID_URL)
    expect(page.locator("[data-import-preview]")).to_be_visible()
    confirm = page.locator('form[data-form="import-confirm"]')
    box = confirm.locator('input[type=checkbox][name=send_invites][value="1"]')
    expect(box).to_be_visible()
    box.uncheck()
    confirm.locator("button[type=submit]").click()
    summary = page.locator("[data-result-summary]")
    expect(summary).to_be_visible()
    elapsed = time.monotonic() - started
    assert elapsed < 300, f"загрузка 100 сотрудников заняла {elapsed:.0f} с (предел 300 с)"

    text = " ".join(summary.inner_text().split())
    assert "создано 100, пропущено 0, с ошибками 0" in text, text
    for email in (emails[0], emails[-1]):  # записи действительно созданы
        page.goto(f"/staff/?q={email}&state=all")
        expect(helpers.staff_row(page, email)).to_have_count(1)


def test_colleague_found_within_10_seconds(admin_page, employee):
    """Критерий 5, FR-130: обычный сотрудник находит коллегу по части ФИО, по части должности и по внутреннему
    номеру — каждый поиск от открытия списка «Сотрудники» до открытой карточки не дольше 10 секунд; чужие
    записи в выдачу не попадают."""
    tag = secrets.token_hex(3)
    viewer = employee()
    page = viewer.page
    email, other_email = factories.new_email("col"), factories.new_email("col")
    position = f"Метролог{tag}"
    number = "".join(secrets.choice("0123456789") for _ in range(6))
    colleague = helpers.create_employee(admin_page, email, full_name=f"Волков{tag} Пётр Иванович", position=position)
    helpers.create_employee(admin_page, other_email, full_name=f"Зайцев{tag} Олег Петрович", position="Инженер")
    # внутренний телефон администратор правит формой карточки (в форме «Создать» этого поля нет), как в сценарии 4
    response = helpers_org.direct_post(admin_page, f"/staff/{colleague}/edit/", {
        "full_name": f"Волков{tag} Пётр Иванович", "position": position, "phone": "", "email": email,
        "contacts": "", "internal_phone": number, "workplace": "Кабинет 12"})
    assert response.status == 302, response.status

    for what, query in (("часть ФИО", f"олков{tag}"), ("часть должности", f"етролог{tag}"), ("номер", number)):
        started = time.monotonic()
        page.goto("/staff/")
        field = page.locator("input[name=q]")
        field.fill(query)
        field.press("Enter")
        page.wait_for_url(re.compile(r"[?&]q="))  # запрос поиска применился
        expect(helpers.staff_row(page, other_email)).to_have_count(0)  # фильтр применился, и только потом щелчок
        expect(helpers.staff_row(page, email)).to_have_count(1)
        helpers.staff_row(page, email).locator('[data-cell="name"] a').click()
        expect(page.locator(f'[data-card][data-user-id="{colleague}"]')).to_be_visible()
        elapsed = time.monotonic() - started
        assert elapsed < 10, f"поиск по признаку «{what}» занял {elapsed:.1f} с (предел 10 с)"
        expect(page.locator('[data-field="position"]')).to_contain_text(position)
        # чужой сотрудник под этот запрос не подходит
        page.goto(f"/staff/?q={query}")
        expect(helpers.staff_row(page, other_email)).to_have_count(0)


def test_calendar_year_and_day_edit_within_3_minutes(admin_page):
    """Критерий 8, FR-145: загрузка файла календаря на год (выбор года и файла, предпросмотр, подтверждение) и ручная
    правка одного дня вместе не дольше 3 минут; изменённый день виден в календаре. Правка дня возвращается в
    `finally` (вид «обычный день»), загруженный год остаётся: каждый круг начинается со сброса стенда
    (conftest.py, `E2E_RESET_CMD`, `stand_reset` — T-2242)."""
    page = admin_page
    try:
        started = time.monotonic()
        page.goto("/calendar/")
        page.locator('a[data-action="calendar-upload"]').click()
        form = page.locator('form[data-form="calendar-upload"]')
        expect(form).to_be_visible()
        form.locator("input[name=year]").fill(str(CALENDAR_YEAR))
        helpers_org.upload_file(form, helpers_org.calendar_fixture("cal2027.csv"))
        page.wait_for_url(re.compile(r"/calendar/upload/\d+/$"))
        expect(page.locator("[data-calendar-preview]")).to_be_visible()
        confirm = page.locator("[data-calendar-preview] input[name=confirm][value='1']")
        expect(confirm).to_have_count(1)
        page.locator("[data-calendar-preview]").locator("button[type=submit]").click()
        page.wait_for_url(re.compile(rf"/calendar/\?year={CALENDAR_YEAR}$"))
        expect(page.locator(f'[data-calendar-year][data-year="{CALENDAR_YEAR}"]')).to_have_attribute(
            "data-loaded", "true")

        # правка дня: ссылка в ячейке дня → форма → вид «праздник»
        day = page.locator(f'td[data-date="{CALENDAR_DAY}"]')
        day.locator("a[data-day-edit]").click()
        day_form = page.locator(f'form[data-form="calendar-day"][action="/calendar/days/{CALENDAR_DAY}/"]')
        expect(day_form).to_be_visible()
        day_form.locator("select[name=kind]").select_option("holiday")
        day_form.locator("button[type=submit]").click()
        page.wait_for_url(re.compile(rf"/calendar/\?year={CALENDAR_YEAR}$"))
        expect(page.locator(f'td[data-date="{CALENDAR_DAY}"]')).to_have_attribute("data-day-kind", "holiday")
        elapsed = time.monotonic() - started
        assert elapsed < 180, f"загрузка календаря и правка дня заняли {elapsed:.0f} с (предел 180 с)"
    finally:
        helpers_org.direct_post(page, f"/calendar/days/{CALENDAR_DAY}/", {"kind": ""})
