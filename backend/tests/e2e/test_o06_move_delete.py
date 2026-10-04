"""T-2140: сценарий 6 — перенос отдела и удаление пустого узла (FR-106, FR-107, FR-115)."""
import re
import secrets

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org
from tests.e2e.helpers_org import (card_text, create_unit, descendant_li, direct_get, direct_post, has_alert,
                                   member_row, open_structure, root_id, unique_name, unit_card, unit_li, unit_link)


def _head_text(page, user_id) -> str:
    """Текст строки «Руководитель» (`[data-field="head"]`) карточки сотрудника `/staff/<id>/`."""
    page.goto(f"/staff/{user_id}/")
    field = page.locator(f'[data-card][data-user-id="{user_id}"] [data-field="head"]')
    expect(field).to_be_visible()
    return field.inner_text()


def _refuse_parent(page, unit_id, parent_id) -> str:
    """Просит у формы узла «Подчиняется» = `parent_id`. Если пункт есть в списке формы — выбирает его в форме
    `unit-edit`; если форма такого пункта не предлагает — шлёт тот же POST напрямую. Возвращает текст отказа
    (ответ 200 с `[role=alert]`)."""
    page.goto(f"/structure/{unit_id}/edit/")
    form = page.locator('form[data-form="unit-edit"]')
    expect(form).to_be_visible()
    name = form.locator("[name=name]").input_value()
    description = form.locator("[name=description]").input_value()
    if form.locator(f'select[name=parent] option[value="{parent_id}"]').count():
        return helpers_org.try_edit_unit(page, unit_id, parent_id=parent_id)
    response = direct_post(page, f"/structure/{unit_id}/edit/", {"name": name, "description": description,
                                                                 "parent": parent_id})
    assert response.status == 200 and has_alert(response), response.status
    return response.text()


def test_o06_move_subtree_with_members_and_heads(admin_page, employee):
    """Сценарий 6, п. 1, 4, 6: отдел «Сеть» с вложенными командами и участниками переносится полем «Подчиняется»
    под «Поддержку» и виден под ней вместе с поддеревом; руководитель команды, заместитель отдела и участники
    сохранены; журнал пишет «было / стало» с прежним и новым вышестоящим узлом; строка «Руководитель» участника
    после переноса определяется по новому положению (FR-106, FR-115)."""
    page = admin_page
    token = secrets.token_hex(3)
    open_structure(page)
    rid = root_id(page)
    open_structure(page, rid)
    old_parent_name = card_text(page, "name")  # прежний вышестоящий узел «Сети» — корень

    # люди: руководитель «Поддержки», заместитель «Сети», руководитель команды, участник команды без руководителей
    head_support = employee(activate=False, full_name=f"Поддерж{token} Пётр Петрович")
    deputy_net = employee(activate=False, full_name=f"Замест{token} Олег Олегович")
    head_team = employee(activate=False, full_name=f"Командир{token} Иван Иванович")
    plain = employee(activate=False, full_name=f"Участник{token} Анна Андреевна")

    # структура: «Сеть» -> команды «Группа» и «Участок»; рядом «Поддержка» — тоже под корнем
    net_name, support_name = unique_name("Сеть"), unique_name("Поддержка")
    net_id = create_unit(page, net_name, kind="department", parent_id=rid)
    group_id = create_unit(page, unique_name("Группа"), kind="team", parent_id=net_id)
    site_id = create_unit(page, unique_name("Участок"), kind="team", parent_id=net_id)
    support_id = create_unit(page, support_name, kind="department", parent_id=rid)

    helpers_org.add_members(page, net_id, [deputy_net.id], q=token, mode="concurrent")
    helpers_org.add_members(page, group_id, [head_team.id], q=token)
    helpers_org.add_members(page, site_id, [plain.id], q=token)
    helpers_org.add_members(page, support_id, [head_support.id], q=token, mode="concurrent")
    helpers_org.set_marks(page, net_id, "deputies", [deputy_net.id])
    helpers_org.set_marks(page, group_id, "heads", [head_team.id])
    helpers_org.set_marks(page, support_id, "heads", [head_support.id])

    # до переноса: у участника «Участка» руководителем не назван руководитель «Поддержки» (узлы «Участок» и «Сеть» без руководителей)
    assert head_support.full_name.split()[0] not in _head_text(page, plain.id)

    # п. 1: меняем «Подчиняется» у «Сети» на «Поддержку»
    helpers_org.edit_unit(page, net_id, parent_id=support_id)
    assert support_name in card_text(page, "parent")
    open_structure(page, net_id)
    expect(descendant_li(page, support_id, net_id)).to_have_count(1)   # «Сеть» под «Поддержкой»
    expect(descendant_li(page, support_id, group_id)).to_have_count(1)  # вместе с командами
    expect(descendant_li(page, support_id, site_id)).to_have_count(1)
    expect(descendant_li(page, net_id, group_id)).to_have_count(1)

    # руководители и участники сохранены: заместитель отдела, руководитель команды, участник второй команды
    expect(member_row(page, deputy_net.id).first).to_have_attribute("data-mark", "deputy")
    open_structure(page, group_id)
    expect(member_row(page, head_team.id).first).to_have_attribute("data-mark", "head")
    open_structure(page, site_id)
    expect(member_row(page, plain.id).first).to_be_visible()
    open_structure(page, support_id)
    expect(member_row(page, head_support.id).first).to_have_attribute("data-mark", "head")

    # п. 6: строка «Руководитель» участника «Участка» — уже руководитель «Поддержки» (новое положение)
    assert head_support.full_name.split()[0] in _head_text(page, plain.id)

    # п. 4: журнал — «было / стало» с прежним и новым вышестоящим узлом
    sides = helpers_org.audit_sides(page, "unit.moved", net_id)
    assert len(sides) == 1, sides
    was, became = sides[0]
    assert old_parent_name in was and support_name not in was, was
    assert support_name in became and old_parent_name not in became, became


def test_o06_cycle_refused_delete_only_empty_after_confirmation(admin_page, employee):
    """Сценарий 6, п. 2, 3, 4: подчинить отдел самому себе или его команде нельзя («цикл в подчинении») и ничего не
    меняется; «Удалить» узла с вложенным узлом или участником отказывает, называя причину; без подтверждения
    пустой узел не удаляется; «Отмена» диалога ничего не меняет; после подтверждения пустой узел с назначенной
    ролью исчезает, журнал пишет удаление с ролью (FR-106, FR-107)."""
    page = admin_page
    token = secrets.token_hex(3)
    open_structure(page)
    rid = root_id(page)

    # п. 2: цикл
    net_id = create_unit(page, unique_name("Сеть"), kind="department", parent_id=rid)
    group_id = create_unit(page, unique_name("Группа"), kind="team", parent_id=net_id)
    open_structure(page, net_id)
    parent_before = card_text(page, "parent")
    for target in (net_id, group_id):  # себе самому и своей вложенной команде
        message = _refuse_parent(page, net_id, target)
        assert "цикл в подчинении" in message.lower(), message
    open_structure(page, net_id)
    assert card_text(page, "parent") == parent_before
    expect(descendant_li(page, net_id, group_id)).to_have_count(1)

    # п. 3: узел с вложенным узлом не удаляется, причина названа
    dialog = helpers_org.open_delete_dialog(page, net_id)
    helpers_org.confirm_delete(page, dialog)
    expect(page.locator("[role=alert]").first).to_be_visible()
    assert "не пуст" in helpers.alert_text(page).lower(), helpers.alert_text(page)  # доп. 52
    open_structure(page)
    expect(unit_li(page, net_id)).to_have_count(1)

    # узел с участником не удаляется
    member = employee(activate=False, full_name=f"Участник{token} Игорь Игоревич")
    helpers_org.add_members(page, group_id, [member.id], q=token)
    dialog = helpers_org.open_delete_dialog(page, group_id)
    helpers_org.confirm_delete(page, dialog)
    expect(page.locator("[role=alert]").first).to_be_visible()
    assert "не пуст" in helpers.alert_text(page).lower(), helpers.alert_text(page)  # доп. 52
    open_structure(page, group_id)
    expect(member_row(page, member.id).first).to_be_visible()

    # пустой узел с ролью: «Отмена» диалога ничего не меняет
    empty_name = unique_name("Пустой")
    empty_id = create_unit(page, empty_name, kind="department", parent_id=rid)
    staff_role = helpers_org.role_id(page, helpers.STAFF_ROLE)
    helpers_org.set_unit_roles(page, empty_id, [staff_role])
    assert helpers.STAFF_ROLE in " ".join(helpers_org.unit_role_names(page))
    dialog = helpers_org.open_delete_dialog(page, empty_id)
    dialog.locator("button[data-dialog-cancel]").click()
    expect(page.locator('[data-dialog="unit-delete"]')).to_have_count(0)
    open_structure(page)
    expect(unit_li(page, empty_id)).to_have_count(1)

    # POST без подтверждения: отказ, узел на месте
    response = direct_post(page, f"/structure/{empty_id}/delete/", {})
    assert response.status == 200 and has_alert(response)
    assert "подтвердите удаление" in response.text().lower()
    open_structure(page)
    expect(unit_li(page, empty_id)).to_have_count(1)

    # п. 3: после подтверждения пустой узел удалён, роли ушли с ним
    dialog = helpers_org.open_delete_dialog(page, empty_id)
    helpers_org.confirm_delete(page, dialog)
    expect(page.locator('[data-dialog="unit-delete"]')).to_have_count(0)
    open_structure(page)
    expect(unit_li(page, empty_id)).to_have_count(0)
    expect(page.locator("[data-unit-tree] a[data-unit-link]", has_text=empty_name)).to_have_count(0)
    assert page.goto(f"/structure/{empty_id}/").status == 404

    # п. 3 (журнал): удаление записано, названа снятая роль
    rows = helpers_org.audit_rows(page, "unit.deleted", empty_id)
    assert len(rows) == 1, rows
    assert empty_name in rows[0] and helpers.STAFF_ROLE in rows[0], rows[0]


def test_o06_no_drag_and_drop(admin_page):
    """Сценарий 6, п. 5: способа перетащить узел мышью нет — в разметке дерева и карточки нет `draggable`,
    `data-drag*`, обработчиков перетаскивания, маршрут `/structure/<id>/move/` не существует, а перенос
    возможен только полем «Подчиняется» формы узла (FR-106)."""
    page = admin_page
    open_structure(page)
    rid = root_id(page)
    net_id = create_unit(page, unique_name("Сеть"), kind="department", parent_id=rid)
    group_id = create_unit(page, unique_name("Группа"), kind="team", parent_id=net_id)
    open_structure(page, group_id)

    expect(page.locator("[draggable]")).to_have_count(0)
    markup = page.evaluate("[document.querySelector('[data-unit-tree]').outerHTML, "
                           "document.querySelector('#unit-card').outerHTML].join('\\n')")
    found = re.findall(r"draggable|data-drag[\w-]*|ondrag\w*|ondrop|dropzone", markup, flags=re.IGNORECASE)
    assert not found, f"в разметке дерева и карточки есть признаки перетаскивания: {sorted(set(found))}"
    expect(unit_link(page, group_id)).to_have_count(1)

    # маршрута переноса нет ни для чтения, ни для записи (админ вошёл: 404, а не редирект на вход)
    assert direct_get(page, f"/structure/{group_id}/move/").status == 404
    assert direct_post(page, f"/structure/{group_id}/move/", {"parent": rid}).status == 404

    # перенос — только полем «Подчиняется» формы узла
    page.goto(f"/structure/{group_id}/edit/")
    expect(page.locator('form[data-form="unit-edit"] [name=parent]')).to_have_count(1)
    open_structure(page, group_id)
    assert card_text(page, "parent")
    expect(descendant_li(page, net_id, group_id)).to_have_count(1)
    expect(unit_card(page).locator("[data-unit-name]")).to_be_visible()
