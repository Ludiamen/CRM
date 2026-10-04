"""T-2140: сценарий 1 — администратор строит структуру: отделы и команда (FR-101…105, FR-108, FR-123, FR-150)."""
import secrets

from playwright.sync_api import expect

from tests.e2e import helpers_org
from tests.e2e.helpers_org import (ROOT_NAME, card_text, create_unit, descendant_li, direct_post, has_alert,
                                   open_structure, root_id, try_create_unit, unique_name, unit_card, unit_li,
                                   unit_link)


def test_o01_root_department_and_new_department_and_team(admin_page):
    """Сценарий 1, п. 7, 1-4 (первый структурный тест круга, стенд после сброса — E2E_RESET_CMD, stand_reset,
    T-2242): в дереве корневой отдел «ИТ-отдел»; отдел «Сеть» под ним и команда под «Сетью» видны
    в дереве (команда отмечена видом), карточка нового узла открывается сама, журнал пишет создание «было / стало»;
    отдел под командой и повтор названия под одним родителем отклонены с названной причиной (FR-101…105, FR-150)."""
    page = admin_page
    open_structure(page)
    rid = root_id(page)

    # п. 7: на новой установке в дереве один корень без участников, видно пустое состояние дерева
    expect(page.locator("[data-unit-tree] li[data-unit-id]")).to_have_count(1)
    open_structure(page, rid)
    expect(unit_card(page).locator("[data-member]")).to_have_count(0)
    expect(page.locator('[data-empty-state="tree"]')).to_be_visible()

    # п. 7: корневой отдел «ИТ-отдел» — отдел, на новой установке один
    expect(unit_li(page, rid)).to_have_attribute("data-kind", "department")
    expect(unit_link(page, rid)).to_contain_text(ROOT_NAME)
    expect(page.locator('[data-action="unit-new"]').first).to_be_visible()  # кнопка шапки (доп. 50)

    # п. 1: отдел «Сеть» под «ИТ-отделом»
    net_name = unique_name("Сеть")
    net_id = create_unit(page, net_name, kind="department", parent_id=rid, description="Сетевое оборудование")
    expect(page.locator(f'#unit-card [data-unit-card][data-unit-id="{net_id}"]')).to_be_visible()  # карточка сама
    assert net_name in card_text(page, "name")
    expect(descendant_li(page, rid, net_id)).to_have_count(1)
    expect(unit_li(page, net_id)).to_have_attribute("data-kind", "department")
    assert card_text(page, "parent"), "в карточке не показано «Подчиняется»"

    # п. 2: команда «Группа филиала» под «Сетью», отмечена как команда
    team_name = unique_name("Группа")
    team_id = create_unit(page, team_name, kind="team", parent_id=net_id)
    expect(descendant_li(page, net_id, team_id)).to_have_count(1)
    expect(unit_li(page, team_id)).to_have_attribute("data-kind", "team")
    expect(page.locator(f'#unit-card [data-unit-card][data-unit-id="{team_id}"]')).to_have_attribute("data-kind", "team")
    assert net_name in card_text(page, "parent")

    # п. 3: отдел под командой — отказ «отдел подчиняется только отделу»
    bad_name = unique_name("Отдел")
    message = try_create_unit(page, bad_name, kind="department", parent_id=team_id)
    assert "отдел подчиняется только отделу" in message.lower(), message
    open_structure(page)
    expect(page.locator("[data-unit-tree] a[data-unit-link]", has_text=bad_name)).to_have_count(0)

    # п. 4: тот же родитель, то же название — отказ; регистр букв значения не имеет (FR-105)
    message = try_create_unit(page, team_name, kind="team", parent_id=net_id)
    assert "названия узлов под одним родителем не повторяются" in message.lower(), message
    message = try_create_unit(page, team_name.upper(), kind="team", parent_id=net_id)
    assert "названия узлов под одним родителем не повторяются" in message.lower(), message
    open_structure(page, net_id)
    expect(page.locator("[data-unit-tree] a[data-unit-link]", has_text=team_name)).to_have_count(1)

    # п. 1 (журнал) и FR-150: создание узла записано «было / стало» по-русски, с названием узла
    rows = helpers_org.audit_rows(page, "unit.created", net_id)
    assert len(rows) == 1, rows
    assert net_name in rows[0] and "стало" in rows[0].lower(), rows[0]


def test_o01_root_cannot_be_deleted_or_moved(admin_page):
    """Сценарий 1, п. 5: у корня название правится (переименование видно в дереве), а «Удалить» и «Подчиняется»
    не предлагаются; прямые POST на удаление и перенос корня отвечают 200 с `[role=alert]`, корень остаётся первым
    узлом дерева и ни под кого не подчинён (FR-103)."""
    page = admin_page
    open_structure(page)
    rid = root_id(page)
    open_structure(page, rid)
    original = card_text(page, "name")
    other_id = create_unit(page, unique_name("Сеть"), kind="department", parent_id=rid)

    try:
        # п. 5: карточка корня — «Править» есть, «Удалить» нет
        open_structure(page, rid)
        card = unit_card(page)
        expect(card.locator('[data-action="unit-edit"]')).to_have_count(1)
        expect(card.locator('[data-action="unit-delete"]')).to_have_count(0)

        # форма корня: название есть, «Подчиняется» нет
        page.goto(f"/structure/{rid}/edit/")
        form = page.locator('form[data-form="unit-edit"]')
        expect(form.locator("[name=name]")).to_be_visible()
        expect(form.locator("[name=parent]")).to_have_count(0)

        # название корня править можно
        renamed = unique_name("Корень")
        helpers_org.edit_unit(page, rid, name=renamed)
        assert renamed in card_text(page, "name")
        expect(unit_link(page, rid)).to_contain_text(renamed)

        # прямой запрос на удаление корня (с подтверждением) — отказ, не 403 и не 302
        response = direct_post(page, f"/structure/{rid}/delete/", {"confirm": "1"})
        assert response.status == 200 and has_alert(response), (response.status, "нет [role=alert]")

        # прямой запрос на перенос корня под другой узел — отказ
        response = direct_post(page, f"/structure/{rid}/edit/", {"name": renamed, "description": "",
                                                                 "parent": other_id})
        assert response.status == 200 and has_alert(response), (response.status, "нет [role=alert]")

        # состояние не изменилось: корень на месте, верхний в дереве, под другим узлом его нет
        open_structure(page)
        assert root_id(page) == rid
        expect(unit_li(page, rid)).to_have_count(1)
        expect(descendant_li(page, other_id, rid)).to_have_count(0)
        assert page.goto(f"/structure/{rid}/").status == 200
    finally:
        helpers_org.edit_unit(page, rid, name=original)  # общее состояние стенда: корень с прежним названием


def test_o01_employee_sees_tree_without_change_buttons_direct_requests_refused(admin_page, employee):
    """Сценарий 1, п. 6: сотрудник без права «Управление структурой» видит дерево, карточки и свой выделенный узел,
    но не видит кнопок создания, правки, удаления, добавления, отметок и меню «…»; страницы форм и прямые POST на
    все изменения отвечают 403 (проверка CSRF пройдена: контрольный POST своего профиля — 302), структура не
    изменилась (FR-108, FR-123)."""
    token = secrets.token_hex(3)
    acc = employee(full_name=f"Сотр{token} Иван Иванович")
    page = acc.page
    unit_name = unique_name("Сеть")
    unit_id = helpers_org.create_unit(admin_page, unit_name, kind="department", parent_id=root_id(admin_page))
    helpers_org.add_members(admin_page, unit_id, [acc.id], q=token, mode="concurrent")

    # дерево и карточка видны, свой узел выделен, чужой (корень) — нет
    assert page.goto("/structure/").status == 200
    rid = root_id(page)
    expect(page.locator("[data-unit-tree]")).to_be_visible()
    expect(unit_link(page, unit_id)).to_have_count(1)
    expect(unit_li(page, unit_id)).to_have_attribute("data-own", "true")
    expect(unit_li(page, rid)).to_have_attribute("data-own", "false")
    for opened in (None, unit_id):
        open_structure(page, opened)
        for action in ("unit-new", "unit-edit", "unit-delete", "members-add", "marks-heads", "marks-deputies",
                       "unit-roles"):
            expect(page.locator(f'[data-action="{action}"]')).to_have_count(0)
        expect(page.locator("[data-member-menu]")).to_have_count(0)
    helpers_org.select_unit(page, unit_id)
    expect(helpers_org.member_row(page, acc.id).first).to_be_visible()  # участники в карточке видны, меню нет
    expect(page.locator("[data-member-menu]")).to_have_count(0)

    # страницы форм и диалога — 403
    for path in ("/structure/new/", f"/structure/{unit_id}/edit/", f"/structure/{unit_id}/delete/"):
        assert page.goto(path).status == 403, path

    # контрольный запрос: токен CSRF принят, 403 ниже — отказ по праву, а не по CSRF
    control = direct_post(page, "/me/", {"phone": "+7 900 111-22-33", "contacts": "", "internal_phone": "",
                                         "workplace": "", "birth_date": ""})
    assert control.status == 302, control.status

    # прямые POST на каждое изменение — 403
    evil = unique_name("Чужой")
    refused = {
        "/structure/new/": {"kind": "department", "name": evil, "parent": rid},
        f"/structure/{unit_id}/edit/": {"name": evil, "description": "", "parent": rid},
        f"/structure/{unit_id}/delete/": {"confirm": "1"},
        f"/structure/{unit_id}/members/": {"users": acc.id, "mode": "concurrent"},
        f"/structure/{unit_id}/members/{acc.id}/transfer/": {"target": rid},
        f"/structure/{unit_id}/members/{acc.id}/remove/": {},
        f"/structure/{unit_id}/marks/": {"part": "heads", "users": acc.id},
        f"/structure/{unit_id}/roles/": {"roles": "1"},
        f"/structure/people/{acc.id}/dismiss/": {},
    }
    for path, data in refused.items():
        response = direct_post(page, path, data)
        assert response.status == 403, (path, response.status)

    # ничего не изменилось: узел, название, участник, сотрудник работает
    open_structure(admin_page, unit_id)
    assert unit_name in card_text(admin_page, "name")
    expect(helpers_org.member_row(admin_page, acc.id).first).to_be_visible()
    expect(helpers_org.member_row(admin_page, acc.id).first).to_have_attribute("data-mark", "")  # отметки нет
    expect(helpers_org.member_row(admin_page, acc.id, section="heads")).to_have_count(0)
    assert helpers_org.unit_role_names(admin_page) == []  # роли узлу не назначены
    expect(admin_page.locator("[data-unit-tree] a[data-unit-link]", has_text=evil)).to_have_count(0)
    open_structure(admin_page, rid)
    expect(helpers_org.member_row(admin_page, acc.id)).to_have_count(0)  # в корень участника не переводили
    assert page.goto("/structure/").status == 200
