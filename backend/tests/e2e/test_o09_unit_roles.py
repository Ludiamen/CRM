"""T-2145: сценарий 9 — роль узла: права вложенным участникам, группы по источникам, отказы (FR-120…122)."""
import secrets

from playwright.sync_api import expect

from tests.e2e import helpers
from tests.e2e.helpers_org import (add_members, audit_rows, audit_sides, create_unit, direct_post, member_row, open_structure,
                                   remove_member, role_id, root_id, set_unit_roles, unique_name, unit_card,
                                   unit_role_names)


def _create_role(page, name: str, permissions) -> str:
    """Роль портала формой `/roles/new/` (срез 001): название и флажки прав; возвращает номер роли."""
    page.goto("/roles/new/")
    form = page.locator('form[action="/roles/new/"]')
    form.locator("[name=name]").fill(name)
    for code in permissions:
        form.locator(f'input[name=permissions][value="{code}"]').check()
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    return role_id(page, name)


def _group_title(group) -> str:
    """Заголовок группы ролей: текст группы без текстов её ролей `[data-role-name]` (отдельной зацепки нет)."""
    title = group.inner_text()
    for name in group.locator("[data-role-name]").all_inner_texts():
        title = title.replace(name.strip(), "")
    return title.lower()


def _assign_personal_role(admin_page, user_id, extra_role_id) -> None:
    """Добавляет личную роль сотруднику формой ролей `/staff/<id>/` (прежние отметки остаются)."""
    admin_page.goto(f"/staff/{user_id}/")
    form = admin_page.locator('form[action$="/roles/"]')
    form.locator(f'input[name=roles][value="{extra_role_id}"]').check()
    with admin_page.expect_navigation():
        form.locator("button[type=submit]").click()


def test_o09_unit_role_applies_to_nested_team_and_gone_after_removal(admin_page, employee):
    """Сценарий 9, п. 1, 2, 6: роль, назначенная отделу, действует на участника вложенной команды (права
    появляются на следующем запросе, права ролей объединяются); после удаления из команды права пропадают сразу;
    назначение и снятие роли узла записаны в журнал с узлом и ролью (FR-120, FR-122)."""
    token = secrets.token_hex(3)
    acc = employee(full_name=f"Вложен{token} Иван Иванович")
    page = acc.page
    role_name = unique_name("Аудитор-узла")
    rid = _create_role(admin_page, role_name, ["audit.view"])
    open_structure(admin_page)
    dept_id = create_unit(admin_page, unique_name("Сеть"), kind="department", parent_id=root_id(admin_page))
    team_id = create_unit(admin_page, unique_name("Группа филиала"), kind="team", parent_id=dept_id)
    add_members(admin_page, team_id, [acc.id], q=token)

    # до назначения роли права от узла нет
    assert page.goto("/audit/").status == 403, "до назначения роли журнал уже открыт"
    expect(page.locator('#main-menu a[href="/audit/"]')).to_have_count(0)

    # п. 1: роль назначена отделу «Сеть» — участник вложенной команды получает её права вместе с личными
    set_unit_roles(admin_page, dept_id, [rid])
    open_structure(admin_page, dept_id)
    assert role_name in unit_role_names(admin_page)
    assert page.goto("/audit/").status == 200, "права роли отдела не дошли до участника вложенной команды"
    expect(page.locator('#main-menu a[href="/audit/"]')).to_have_count(1)
    assert page.goto("/me/").status == 200  # личные права на месте
    assert page.goto("/settings/portal/").status == 403  # лишних прав роль не даёт

    # п. 2: человека удаляют из команды — права от узла пропадают сразу, на следующем запросе
    open_structure(admin_page, team_id)
    remove_member(admin_page, acc.id)
    expect(member_row(admin_page, acc.id)).to_have_count(0)
    assert page.goto("/audit/").status == 403, "после удаления из узла права от узла остались"
    expect(page.locator('#main-menu a[href="/audit/"]')).to_have_count(0)
    assert page.goto("/me/").status == 200

    # п. 6: назначение — в журнале «было / стало» с узлом и ролью; снятие роли — вторая запись
    rows = audit_rows(admin_page, "unit.roles_changed", dept_id)
    assert len(rows) == 1 and role_name in rows[0], rows
    sides = audit_sides(admin_page, "unit.roles_changed", dept_id)
    assert len(sides) == 1 and role_name not in sides[0][0] and role_name in sides[0][1], sides
    set_unit_roles(admin_page, dept_id, [])
    open_structure(admin_page, dept_id)
    assert unit_role_names(admin_page) == []
    rows = audit_rows(admin_page, "unit.roles_changed", dept_id)
    assert len(rows) == 2, rows
    assert all(role_name in row for row in rows), "в записи «было / стало» нет названия роли"
    sides = audit_sides(admin_page, "unit.roles_changed", dept_id)
    assert len(sides) == 2, sides
    # новые события сверху: снятие — роль была и не стала; назначение — не было и стала
    assert role_name in sides[0][0] and role_name not in sides[0][1], sides
    assert role_name not in sides[1][0] and role_name in sides[1][1], sides


def test_o09_roles_grouped_by_source_in_card(admin_page, employee):
    """Сценарий 9, п. 3: совместитель состоит в двух отделах с разными ролями; в его карточке (у обладателя
    управления сотрудниками) роли сгруппированы по источникам: «лично», «от подразделения <первый отдел>»,
    «от подразделения <второй отдел>», роль каждого источника — только в своей группе (FR-122)."""
    token = secrets.token_hex(3)
    acc = employee(activate=False, full_name=f"Совмест{token} Пётр Петрович")
    open_structure(admin_page)
    rid_root = root_id(admin_page)
    net_name, support_name = unique_name("Сеть"), unique_name("Поддержка")
    net_id = create_unit(admin_page, net_name, kind="department", parent_id=rid_root)
    support_id = create_unit(admin_page, support_name, kind="department", parent_id=rid_root)
    net_role, support_role, personal_role = (unique_name("Роль-сети"), unique_name("Роль-поддержки"),
                                             unique_name("Роль-сама"))
    net_role_id = _create_role(admin_page, net_role, ["audit.view"])
    support_role_id = _create_role(admin_page, support_role, ["settings.portal"])
    personal_role_id = _create_role(admin_page, personal_role, ["settings.security"])
    add_members(admin_page, net_id, [acc.id], q=token, mode="concurrent")
    add_members(admin_page, support_id, [acc.id], q=token, mode="concurrent")
    set_unit_roles(admin_page, net_id, [net_role_id])
    set_unit_roles(admin_page, support_id, [support_role_id])
    _assign_personal_role(admin_page, acc.id, personal_role_id)

    admin_page.goto(f"/staff/{acc.id}/")
    card = admin_page.locator(f'[data-card][data-user-id="{acc.id}"]')
    personal = card.locator('[data-roles-group="personal"]')
    net_group = card.locator(f'[data-roles-group="unit"][data-source-unit="{net_name}"]')
    support_group = card.locator(f'[data-roles-group="unit"][data-source-unit="{support_name}"]')
    expect(personal).to_have_count(1)
    expect(net_group).to_have_count(1)
    expect(support_group).to_have_count(1)
    expect(card.locator('[data-roles-group="unit"]')).to_have_count(2)  # других источников нет
    assert "лично" in _group_title(personal), _group_title(personal)
    assert f"от подразделения {net_name}".lower() in _group_title(net_group), _group_title(net_group)
    assert f"от подразделения {support_name}".lower() in _group_title(support_group), _group_title(support_group)
    personal_names = [t.strip() for t in personal.locator("[data-role-name]").all_inner_texts()]
    assert personal_role in personal_names and helpers.STAFF_ROLE in personal_names, personal_names
    assert net_role not in personal_names and support_role not in personal_names
    assert [t.strip() for t in net_group.locator("[data-role-name]").all_inner_texts()] == [net_role]
    assert [t.strip() for t in support_group.locator("[data-role-name]").all_inner_texts()] == [support_role]


def test_o09_admin_role_refused_org_manage_alone_refused_assigned_role_not_deletable(admin_page, employee):
    """Сценарий 9, п. 4, 5, 7: роль «Администратор портала» узлу не назначается (отказ с причиной «администратор
    выдаётся только лично», набор не меняется, записи в журнале нет); сотрудник только с правом «Управление
    структурой» не видит действия «Роли узла», а прямой запрос назначить роль отвечает 403 (нужно «управлять
    ролями»), роли узла не меняются; роль, назначенная узлу, не удаляется (причина «роль назначена узлу»), а после
    снятия с узла удаляется (FR-120, FR-121)."""
    token = secrets.token_hex(3)
    manager = employee(full_name=f"Структур{token} Иван Иванович")
    open_structure(admin_page)
    unit_id = create_unit(admin_page, unique_name("Сеть"), kind="department", parent_id=root_id(admin_page))
    role_name = unique_name("Роль-узла")
    rid = _create_role(admin_page, role_name, ["audit.view"])
    admin_rid = role_id(admin_page, helpers.ADMIN_ROLE)

    # п. 4: администратор портала узлу — отказ, роль выдаётся только лично
    reason = set_unit_roles(admin_page, unit_id, [admin_rid])
    assert "администратор выдаётся только лично" in reason.lower(), reason
    open_structure(admin_page, unit_id)
    assert unit_role_names(admin_page) == []
    assert audit_rows(admin_page, "unit.roles_changed", unit_id) == []

    # п. 5: только «Управление структурой» — отказ: нужно право «управлять ролями»
    org_role_id = _create_role(admin_page, unique_name("Структура-только"), ["org.manage"])
    _assign_personal_role(admin_page, manager.id, org_role_id)
    set_unit_roles(admin_page, unit_id, [rid])  # у узла есть назначенная роль, которую сотрудник не должен тронуть
    page = manager.page
    open_structure(page, unit_id)
    expect(unit_card(page).locator('details[data-action="members-add"]')).to_have_count(1)  # право структуры есть
    expect(unit_card(page).locator('[data-action="unit-roles"]')).to_have_count(0)  # а «Роли узла» нет
    response = direct_post(page, f"/structure/{unit_id}/roles/", {"roles": ""})
    assert response.status == 403, response.status
    response = direct_post(page, f"/structure/{unit_id}/roles/", {"roles": admin_rid})
    assert response.status == 403, response.status
    open_structure(admin_page, unit_id)
    assert unit_role_names(admin_page) == [role_name], "роли узла изменились после отказа"

    # п. 7: роль назначена узлу — удалить нельзя, причина названа
    admin_page.goto(f"/roles/{rid}/")
    helpers.submit(admin_page.locator('form[action$="/delete/"]'))
    expect(admin_page.locator("[role=alert]").first).to_be_visible()
    assert "роль назначена узлу" in helpers.alert_text(admin_page).lower(), helpers.alert_text(admin_page)
    assert role_id(admin_page, role_name) == rid, "назначенная узлу роль удалена"

    # роль снята с узла — удаление проходит
    set_unit_roles(admin_page, unit_id, [])
    admin_page.goto(f"/roles/{rid}/")
    with admin_page.expect_navigation():
        helpers.submit(admin_page.locator('form[action$="/delete/"]'))
    admin_page.goto("/roles/")
    expect(admin_page.locator(f'[data-role-id][data-role-name="{role_name}"]')).to_have_count(0)
