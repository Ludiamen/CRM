"""T-2142: сценарий 4 — сотрудник смотрит структуру и находит коллегу (FR-108, FR-118, FR-119, FR-123, FR-130,
FR-131, FR-134, FR-135, NFR-104)."""
import re
import secrets

from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers
from tests.e2e.helpers_org import (add_members, create_unit, direct_get, direct_post, open_structure, root_id, role_id,
                                   set_marks, unique_name, unit_card, unit_li, unit_link)


def _people(admin_page, prefix: str, count: int, *, position: str) -> list:
    """Заводит `count` приглашённых сотрудников с ФИО `<prefix> Имя<i>` и должностью `position` (интерфейс
    «Добавить сотрудника», письма не читаются); возвращает номера записей."""
    return [helpers.create_employee(admin_page, factories.new_email("col"), full_name=f"{prefix} Имя{i:02d}",
                                    position=position) for i in range(count)]


def _only_rows(page, emails_present, emails_absent=()) -> None:
    """В списке «Сотрудники» ровно перечисленные строки есть, указанных нет (`tr[data-user-email]`)."""
    for email in emails_present:
        expect(helpers.staff_row(page, email)).to_have_count(1)
    for email in emails_absent:
        expect(helpers.staff_row(page, email)).to_have_count(0)


def test_o04_tree_own_units_highlighted_and_search_in_unit(admin_page, employee):
    """Сценарий 4, п. 1-2: сотрудник с правом просмотра открывает «Структуру» — виден корневой отдел и все
    вложенные узлы, его собственные узлы выделены; в карточке узла с 30 участниками поиск по части должности
    оставляет только подходящих, без учёта регистра и разницы «е/ё» (FR-108)."""
    tag = secrets.token_hex(3)
    viewer = employee(full_name=f"Единый{tag} Сотрудник Первый")
    page = viewer.page

    # подготовка администратором через интерфейс: отдел A, команда T под ним, отдел C рядом; 30 участников в A
    open_structure(admin_page)
    rid = root_id(admin_page)
    dept_a = create_unit(admin_page, unique_name("Сеть"), kind="department", parent_id=rid)
    team_t = create_unit(admin_page, unique_name("Группа"), kind="team", parent_id=dept_a)
    dept_c = create_unit(admin_page, unique_name("Чужой"), kind="department", parent_id=rid)
    add_members(admin_page, team_t, [viewer.id], q=f"Единый{tag}")
    add_members(admin_page, dept_a, [viewer.id], q=f"Единый{tag}", mode="concurrent")
    engineers = _people(admin_page, f"Инж{tag}a", 15, position="Инженер-сетевик") \
        + _people(admin_page, f"Инж{tag}b", 10, position="Инженер-сетевик")
    receivers = _people(admin_page, f"Прм{tag}a", 4, position="Приёмщик заявок")
    # кандидатов за один запрос не больше 20: три пачки, каждая находит своих по общей части ФИО
    add_members(admin_page, dept_a, engineers[:15], q=f"Инж{tag}a", mode="concurrent")
    add_members(admin_page, dept_a, engineers[15:], q=f"Инж{tag}b", mode="concurrent")
    add_members(admin_page, dept_a, receivers, q=f"Прм{tag}a", mode="concurrent")

    # п. 1: «Структура» открывается на первом своём узле (по path), в дереве корень и все вложенные узлы
    page.goto("/structure/")
    expect(page.locator("[data-unit-tree]")).to_be_visible()
    expect(page.locator(f'#unit-card [data-unit-card][data-unit-id="{dept_a}"]')).to_be_visible()
    expect(unit_link(page, dept_a)).to_have_attribute("aria-current", "true")
    for unit_id in (rid, dept_a, team_t, dept_c):
        expect(unit_li(page, unit_id)).to_have_count(1)  # узел есть в разметке (свёрнутые узлы могут быть скрыты)
    # п. 1: собственные узлы выделены, чужие и корень — нет
    expect(unit_li(page, dept_a)).to_have_attribute("data-own", "true")
    expect(unit_li(page, team_t)).to_have_attribute("data-own", "true")
    expect(unit_li(page, dept_c)).to_have_attribute("data-own", "false")
    expect(unit_li(page, rid)).to_have_attribute("data-own", "false")

    # п. 2: в карточке 30 участников (1 + 25 + 4), поиск по части должности
    members = unit_card(page).locator("[data-member]")
    expect(members).to_have_count(30)

    def search_in_card(text: str) -> None:
        """Вводит запрос в поле карточки и ждёт ответ именно на него (карточка подменяется целиком)."""
        with page.expect_response(lambda r: "/structure/" in r.url and "q=" in r.url):
            unit_card(page).locator("input[name=q]").fill(text)

    search_in_card("ПРИЕМЩИК")  # другой регистр и «е» вместо «ё»
    expect(members).to_have_count(4)
    for position in unit_card(page).locator("[data-member] [data-member-position]").all_inner_texts():
        assert "приёмщик" in position.lower(), position
    search_in_card("приёмщик")  # то же слово с «ё»
    expect(members).to_have_count(4)
    search_in_card("ИНЖЕНЕР")
    expect(members).to_have_count(26)  # 25 сетевиков и сам наблюдатель (должность «Инженер»)
    search_in_card(f"нет-такой-должности-{tag}")
    expect(members).to_have_count(0)
    expect(page.locator('[data-empty-state="search"]')).to_be_visible()


def test_o04_list_search_and_unit_filter_with_nested(admin_page, employee):
    """Сценарий 4, п. 3-4: в списке «Сотрудники» часть фамилии, внутренний телефон и название подразделения
    находят подходящих сотрудников; фильтр «Подразделение: Сеть» показывает участников «Сети» и всех вложенных
    узлов, участников других узлов и людей без узла — нет (FR-130, FR-131)."""
    tag = secrets.token_hex(3)
    viewer = employee()
    page = viewer.page

    open_structure(admin_page)
    rid = root_id(admin_page)
    net_name = unique_name("Сеть")
    net = create_unit(admin_page, net_name, kind="department", parent_id=rid)
    support = create_unit(admin_page, unique_name("Поддержка"), kind="department", parent_id=net)
    team = create_unit(admin_page, unique_name("Группа"), kind="team", parent_id=support)
    other = create_unit(admin_page, unique_name("Иной"), kind="department", parent_id=rid)
    plan = (("Ларин", net), ("Мартынов", support), ("Орлов", team), ("Седов", other), ("Тихонов", None))
    emails, ids = {}, {}
    for surname, unit_id in plan:
        emails[surname] = factories.new_email("col")
        ids[surname] = helpers.create_employee(admin_page, emails[surname], full_name=f"{surname}{tag} Иван Петрович",
                                               position="Инженер")
        if unit_id is not None:
            add_members(admin_page, unit_id, [ids[surname]], q=f"{surname}{tag}",
                        mode=None if unit_id == team else "concurrent")
    phone = "9" + "".join(secrets.choice("0123456789") for _ in range(5))
    # внутренний телефон администратор правит прямым запросом формы карточки (в форме «Создать» этого поля нет)
    response = direct_post(admin_page, f"/staff/{ids['Ларин']}/edit/", {
        "full_name": f"Ларин{tag} Иван Петрович", "position": "Инженер", "phone": "", "email": emails["Ларин"],
        "contacts": "", "internal_phone": phone, "workplace": "Кабинет 12"})
    assert response.status == 302, response.status

    def search(text: str) -> None:
        page.goto("/staff/")
        field = page.locator("input[name=q]")
        field.fill(text)
        field.press("Enter")

    # п. 3: часть фамилии (другой регистр)
    search(f"арин{tag}".upper())
    _only_rows(page, [emails["Ларин"]], [emails["Мартынов"], emails["Седов"], emails["Тихонов"]])
    # п. 3: внутренний телефон
    search(phone)
    _only_rows(page, [emails["Ларин"]], [emails["Мартынов"], emails["Седов"]])
    # п. 3: название подразделения — находятся его участники, не участники других узлов
    search(net_name)
    _only_rows(page, [emails["Ларин"]], [emails["Седов"], emails["Тихонов"]])

    # п. 4: фильтр «Подразделение: Сеть» (вместе с вложенными) на выборке по метке теста
    page.goto("/staff/")
    field = page.locator("input[name=q]")
    field.fill(tag)
    field.press("Enter")
    _only_rows(page, [emails[s] for s, _ in plan])
    page.locator("select[name=unit]").select_option(net)
    _only_rows(page, [emails["Ларин"], emails["Мартынов"], emails["Орлов"]], [emails["Седов"], emails["Тихонов"]])
    page.locator("select[name=unit]").select_option(support)  # середина: сам узел и команда под ним
    _only_rows(page, [emails["Мартынов"], emails["Орлов"]], [emails["Ларин"], emails["Седов"], emails["Тихонов"]])
    page.locator("select[name=unit]").select_option("")  # «Все подразделения»
    _only_rows(page, [emails[s] for s, _ in plan])


def test_o04_colleague_card_profile_fields_without_service_fields(admin_page, employee):
    """Сценарий 4, п. 5: обычный сотрудник открывает карточку коллеги — видит ФИО, должность, почту, телефон,
    внутренний телефон, место работы, фото, подразделение, руководителя, день и месяц рождения (без года), но не
    роли, состояние записи, ссылку активации, устройства и историю входов; вкладки «Безопасность» нет (FR-119,
    FR-134, FR-135)."""
    tag = secrets.token_hex(3)
    colleague = employee(full_name=f"Фомин{tag} Пётр Иванович")
    viewer = employee(full_name=f"Зуев{tag} Олег Игоревич")
    head_name = f"Начальников{tag} Игорь Сергеевич"
    head_id = helpers.create_employee(admin_page, factories.new_email("head"), full_name=head_name,
                                      position="Руководитель сети")

    open_structure(admin_page)
    unit_name = unique_name("Сеть")
    unit_id = create_unit(admin_page, unit_name, kind="department", parent_id=root_id(admin_page))
    add_members(admin_page, unit_id, [colleague.id, head_id], q=tag, mode="concurrent")
    set_marks(admin_page, unit_id, "heads", [head_id])

    # коллега сам заполняет внутренний телефон, место работы и дату рождения (FR-134)
    own = colleague.page
    own.goto("/me/")
    form = own.locator('form:has(input[name="internal_phone"])')
    form.locator("input[name=internal_phone]").fill("4321")
    form.locator("[name=workplace]").fill("Кабинет 7")
    form.locator("input[data-datefield-input][name=birth_date]").fill("05.03.1961")
    with own.expect_navigation():
        form.locator("button[type=submit]").click()
    expect(own.locator("[role=status]").first).to_be_visible()

    # п. 5: карточка глазами обычного сотрудника
    page = viewer.page
    page.goto(f"/staff/{colleague.id}/")
    card = page.locator(f'[data-card][data-user-id="{colleague.id}"]').first
    expect(card).to_be_visible()
    expect(card).to_contain_text(f"Фомин{tag} Пётр Иванович")
    expect(card.locator('[data-field="position"]')).to_contain_text("Инженер")
    expect(card.locator('[data-field="email"]')).to_contain_text(colleague.email)
    expect(card.locator('[data-field="phone"]')).to_contain_text("900 000-00-00")
    expect(card.locator('[data-field="internal_phone"]')).to_contain_text("4321")
    expect(card.locator('[data-field="workplace"]')).to_contain_text("Кабинет 7")
    expect(card.locator('[data-field="units"]')).to_contain_text(unit_name)
    expect(card.locator('[data-field="head"]')).to_contain_text(head_name)
    expect(card.locator('[data-field="birth_date"]')).to_have_text(re.compile(r"^\s*5 марта\s*$"))  # день и месяц
    card_text = card.inner_text()
    assert "1961" not in card_text and "05.03" not in card_text, "чужая карточка показала год рождения"
    expect(card.locator("[data-photo]").first).to_be_visible()  # фото или заглушка с инициалами
    for name, label in (("units", "Подразделение"), ("head", "Руководитель"), ("workplace", "Место работы"),
                        ("internal_phone", "Внутренний телефон"), ("birth_date", "Дата рождения")):
        expect(card.locator(f'[data-field-label="{name}"]')).to_contain_text(label)

    # п. 5: служебного нет ни в разметке, ни по прямому адресу
    for hook in ('[data-tab-button="security"]', '[data-tab-panel="security"]', "[data-security-part]",
                 '[data-field="state"]', "[data-roles-group]", "[data-invitation-link]", "[data-mail-status]",
                 "[data-device-id]", "[data-history-row]", "[data-backup-remaining]",
                 f'form[action^="/staff/{colleague.id}/"]'):
        expect(page.locator(hook), hook).to_have_count(0)
    assert helpers.STAFF_ROLE not in card.inner_text(), "в чужой карточке показаны роли"
    assert direct_get(page, f"/staff/{colleague.id}/logins/").status == 403

    # контроль: у администратора та же карточка с вкладкой «Безопасность» и состоянием — разница не от пустой страницы
    admin_page.goto(f"/staff/{colleague.id}/")
    expect(admin_page.locator('[data-tab-button="security"]')).to_have_count(1)
    expect(admin_page.locator('[data-field="state"]')).to_have_count(1)


def test_o04_structure_at_360px_tree_above_card(employee):
    """Сценарий 4, п. 6: на ширине окна 360 px страница «Структура» без горизонтальной прокрутки, дерево и карточка
    узла идут друг под другом; на широком окне дерево слева от карточки (NFR-104, FR-108)."""
    viewer = employee()
    page = viewer.page
    page.set_viewport_size({"width": 1280, "height": 800})
    open_structure(page)
    expect(page.locator("[data-structure-layout]")).to_be_visible()
    tree, card = page.locator("[data-unit-tree]").bounding_box(), page.locator("#unit-card").bounding_box()
    assert tree["x"] + tree["width"] <= card["x"] + 1, f"на широком окне дерево не слева от карточки: {tree} {card}"

    # п. 6: 360 px
    page.set_viewport_size({"width": 360, "height": 800})
    open_structure(page)
    assert helpers.no_horizontal_scroll(page), "на 360 px появилась горизонтальная прокрутка"
    tree, card = page.locator("[data-unit-tree]").bounding_box(), page.locator("#unit-card").bounding_box()
    assert tree["y"] + tree["height"] <= card["y"] + 1, f"на 360 px карточка не под деревом: {tree} {card}"
    assert card["x"] < tree["x"] + tree["width"], "карточка и дерево стоят рядом, а не друг под другом"
    # то же после выбора узла (карточка подменяется HTMX)
    first = page.locator("[data-unit-tree] a[data-unit-link]").first
    unit_id = first.get_attribute("data-unit-id") or re.search(r"/structure/(\d+)/", first.get_attribute("href")).group(1)
    with page.expect_response(lambda r: "/structure/" in r.url):
        first.click()
    expect(page.locator(f'#unit-card [data-unit-card][data-unit-id="{unit_id}"]')).to_be_visible()
    assert helpers.no_horizontal_scroll(page), "после выбора узла на 360 px появилась горизонтальная прокрутка"


def test_o04_without_staff_view_refused_and_hidden(admin_page, employee):
    """Сценарий 4, п. 7: у сотрудника, у которого нет права «Просмотр сотрудников и структуры», «Структура» и
    «Сотрудники» по прямому адресу отвечают отказом, а пункты скрыты из меню; обычному сотруднику открыты (FR-118,
    FR-123)."""
    normal = employee()
    # права среза 002 есть в форме роли (FR-118)
    admin_page.goto("/roles/new/")
    form = admin_page.locator('form[action="/roles/new/"]')
    for code in ("staff.view", "org.manage", "calendar.manage"):
        expect(form.locator(f'input[name=permissions][value="{code}"]')).to_have_count(1)
    # роль без staff.view (отдельная, роль «Сотрудник ИТ» общая для стенда и не меняется)
    role_name = f"БезСтруктуры-{secrets.token_hex(3)}"
    form.locator("[name=name]").fill(role_name)
    form.locator('input[name=permissions][value="audit.view"]').check()
    form.locator("button[type=submit]").click()
    assert role_id(admin_page, role_name)
    restricted = employee(role=role_name)

    open_structure(admin_page)
    rid = root_id(admin_page)
    admin_page.goto("/staff/")
    some_id = re.search(r"/staff/(\d+)/", admin_page.locator("tr[data-user-id] a[href^='/staff/']").first
                         .get_attribute("href")).group(1)

    # контроль: обычному сотруднику страницы открыты и пункты в меню есть
    page = normal.page
    assert page.goto("/structure/").status == 200
    expect(page.locator('#main-menu a[href="/structure/"]')).to_have_count(1)
    expect(page.locator('#main-menu a[href="/staff/"]')).to_have_count(1)
    assert page.goto("/staff/").status == 200

    # п. 7: без права — отказ по прямому адресу и нет пунктов меню
    blocked = restricted.page
    assert blocked.goto("/").status == 200
    expect(blocked.locator('#main-menu a[href="/structure/"]')).to_have_count(0)
    expect(blocked.locator('#main-menu a[href="/staff/"]')).to_have_count(0)
    for path in ("/structure/", f"/structure/{rid}/", "/staff/", f"/staff/{some_id}/"):
        assert blocked.goto(path).status == 403, path
        expect(blocked.locator("[data-unit-tree]")).to_have_count(0)
