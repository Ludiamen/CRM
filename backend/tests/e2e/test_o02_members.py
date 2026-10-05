"""T-2141: сценарий 2 — участники узла: перевод, совместительство, меню «…», уволенные не предлагаются
(FR-110…113, FR-123, FR-125, FR-127)."""
import re
import secrets

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_org
from tests.e2e.helpers_org import (create_unit, direct_get, direct_post, has_alert, member_menu, member_row,
                                   open_structure, root_id, unique_name)


def _field(page, user_id, name) -> str:
    """Текст поля `[data-field="<name>"]` карточки сотрудника `/staff/<id>/` (профиль открыт по умолчанию)."""
    page.goto(f"/staff/{user_id}/")
    field = page.locator(f'[data-card][data-user-id="{user_id}"] [data-field="{name}"]')
    expect(field).to_be_visible()
    return field.inner_text().strip()


def _units_line(page, user_id) -> str:
    """Строка «Подразделение» карточки сотрудника."""
    return _field(page, user_id, "units")


def _by_path(*pairs) -> list:
    """Названия узлов в порядке `path` (байтовом, как `sorted()`; доп. 1, 18): `pairs` — (path, название)."""
    return [name for _, name in sorted(pairs)]


def _members_in(page, unit_id, user_id) -> int:
    """Сколько строк участника `user_id` в карточке узла `unit_id` (0 — не участник)."""
    open_structure(page, unit_id)
    return member_row(page, user_id).count()


def test_o02_transfer_concurrent_remove_and_repeated_add(admin_page, employee):
    """Сценарий 2, п. 1, 2, 3, 7: «перевести» оставляет человека только в новом отделе (команда на месте), журнал
    пишет перевод с прежним и новым подразделением; «добавить как совместителя» оставляет прежний отдел, и
    «Подразделение» перечисляет оба через запятую; повторное добавление не дублирует и сообщает «уже участник»;
    «Удалить из отдела» оставляет человека в портале без подразделения, он находится по фильтру
    «Без подразделения» (FR-110, FR-111, FR-112, FR-113)."""
    page = admin_page
    token = secrets.token_hex(3)
    person = employee(activate=False, full_name=f"Совмест{token} Иван Петрович")
    lone = employee(activate=False, full_name=f"Единств{token} Олег Иванович")
    open_structure(page)
    rid = root_id(page)
    net_name, support_name, team_name = unique_name("Сеть"), unique_name("Поддержка"), unique_name("Группа")
    net_id = create_unit(page, net_name, kind="department", parent_id=rid)
    support_id = create_unit(page, support_name, kind="department", parent_id=rid)
    team_id = create_unit(page, team_name, kind="team", parent_id=net_id)
    path = {net_id: f"/{rid}/{net_id}/", support_id: f"/{rid}/{support_id}/", team_id: f"/{rid}/{net_id}/{team_id}/"}

    # дано: человек в отделе «Сеть» и в команде «Группа» (у команды выбора режима нет)
    helpers_org.add_members(page, net_id, [person.id], q=token, mode="concurrent")
    helpers_org.add_members(page, team_id, [person.id], q=token)
    open_structure(page, team_id)
    expect(page.locator('#unit-card select[name=mode]')).to_have_count(0)
    assert _units_line(page, person.id) == ", ".join(_by_path((path[net_id], net_name), (path[team_id], team_name)))

    # п. 1: добавляем в «Поддержку» в режиме «перевести»
    helpers_org.add_members(page, support_id, [person.id], q=token, mode="transfer")
    assert _members_in(page, net_id, person.id) == 0, "после перевода человек остался в прежнем отделе"
    assert _members_in(page, support_id, person.id) == 1
    assert _members_in(page, team_id, person.id) == 1, "команда при переводе не затрагивается"
    assert _units_line(page, person.id) == ", ".join(
        _by_path((path[support_id], support_name), (path[team_id], team_name)))
    rows = helpers_org.audit_rows(page, "membership.transferred", person.id)
    assert len(rows) == 1, rows
    assert net_name in rows[0] and support_name in rows[0], rows[0]  # прежнее и новое подразделение

    # п. 2: возвращаем в «Сеть» как совместителя — остаётся и в «Поддержке»
    helpers_org.add_members(page, net_id, [person.id], q=token, mode="concurrent")
    assert _members_in(page, net_id, person.id) == 1
    assert _members_in(page, support_id, person.id) == 1
    assert _units_line(page, person.id) == ", ".join(_by_path(
        (path[net_id], net_name), (path[support_id], support_name), (path[team_id], team_name)))
    assert len(helpers_org.audit_rows(page, "membership.transferred", person.id)) == 1  # перевода не было

    # п. 7: повторное добавление в тот же отдел — второго членства нет, портал сообщает «уже участник»
    message = helpers_org.add_members(page, support_id, [person.id], q=token, mode="concurrent")
    assert "уже участник" in message.lower(), message
    open_structure(page, support_id)
    expect(member_row(page, person.id)).to_have_count(1)
    assert _units_line(page, person.id).count(support_name) == 1

    # п. 3: единственный отдел «Сеть» — «Удалить из отдела»; человек остаётся в портале без подразделения
    helpers_org.add_members(page, net_id, [lone.id], q=token, mode="concurrent")
    open_structure(page, net_id)
    expect(member_row(page, lone.id).locator('[data-menu-item="remove"]')).to_contain_text("Удалить из отдела")
    helpers_org.remove_member(page, lone.id)
    expect(member_row(page, lone.id)).to_have_count(0)
    page.goto(f"/staff/?state=no_unit&q={token}")
    expect(page.locator('a[data-preset="no_unit"]')).to_have_attribute("aria-current", "true")
    expect(page.locator(f'tr[data-user-id="{lone.id}"]')).to_have_count(1)  # он в портале и найден без подразделения
    expect(page.locator(f'tr[data-user-id="{person.id}"]')).to_have_count(0)  # у «Совместителя» подразделения есть
    assert _field(page, lone.id, "units") == "не заполнено"
    assert helpers_org.audit_rows(page, "membership.removed", lone.id)


def test_o02_member_menu_and_dismiss_dialog_from_unit(admin_page, employee):
    """Сценарий 2, п. 4, 5: у участника в карточке отдела меню «…» с пунктами «Перевести в другой отдел»,
    «Удалить из отдела», «Уволить» (в команде — «в другую команду», «из команды»); перевод предлагает только узлы
    того же вида; перевод из первого из двух отделов уходит из первого, входит в третий и оставляет второй;
    «Уволить» открывает диалог подтверждения увольнения с последствиями и «Отмена» ничего не меняет
    (FR-111, FR-125)."""
    page = admin_page
    token = secrets.token_hex(3)
    person = employee(activate=False, full_name=f"Меню{token} Пётр Иванович")
    open_structure(page)
    rid = root_id(page)
    net_name, support_name, third_name = unique_name("Сеть"), unique_name("Поддержка"), unique_name("Третий")
    net_id = create_unit(page, net_name, kind="department", parent_id=rid)
    support_id = create_unit(page, support_name, kind="department", parent_id=rid)
    third_id = create_unit(page, third_name, kind="department", parent_id=rid)
    team_id = create_unit(page, unique_name("Группа"), kind="team", parent_id=net_id)
    helpers_org.add_members(page, net_id, [person.id], q=token, mode="concurrent")
    helpers_org.add_members(page, support_id, [person.id], q=token, mode="concurrent")
    helpers_org.add_members(page, team_id, [person.id], q=token)

    # меню отдела: три пункта дословно; перевод предлагает отделы, а не команды
    open_structure(page, net_id)
    menu = member_menu(page, person.id)
    expect(menu.locator('[data-menu-item="transfer"]')).to_contain_text("Перевести в другой отдел")
    expect(menu.locator('[data-menu-item="remove"]')).to_contain_text("Удалить из отдела")
    expect(menu.locator('[data-menu-item="dismiss"]')).to_contain_text("Уволить")
    target = menu.locator('form[data-form="member-transfer"] select[name=target]')
    expect(target.locator(f'option[value="{third_id}"]')).to_have_count(1)
    expect(target.locator(f'option[value="{team_id}"]')).to_have_count(0)

    # меню команды: подписи команды
    open_structure(page, team_id)
    menu = member_menu(page, person.id)
    expect(menu.locator('[data-menu-item="transfer"]')).to_contain_text("Перевести в другую команду")
    expect(menu.locator('[data-menu-item="remove"]')).to_contain_text("Удалить из команды")
    expect(menu.locator('[data-menu-item="dismiss"]')).to_contain_text("Уволить")

    # п. 5: «Уволить» открывает диалог увольнения (сценарий 7); последствия названы, «Отмена» закрывает
    open_structure(page, support_id)
    member_menu(page, person.id).locator('[data-menu-item="dismiss"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    expect(dialog).to_have_attribute("role", "dialog")
    expect(dialog.locator("[data-consequence]").first).to_be_visible()
    consequences = " ".join(dialog.locator("[data-consequence]").all_inner_texts()).lower()
    for phrase in ("вход закрыт", "уйдёт из всех подразделений", "личные роли будут сняты"):
        assert phrase in consequences, (phrase, consequences)
    expect(dialog.locator("input[name=next]")).to_have_value(re.compile(rf"/structure/{support_id}/$"))
    dialog.locator("button[data-dialog-cancel]").click()
    expect(page.locator('[data-dialog="dismiss"]')).to_have_count(0)
    assert helpers_org.audit_rows(page, "user.dismissed", person.id) == []
    open_structure(page, support_id)  # журнал увёл страницу: вернуться в карточку узла (T-2260, разрешение владельца)
    expect(member_row(page, person.id)).to_have_count(1)  # увольнения не было

    # п. 4: два отдела — «Перевести в другой отдел» первого в третий: уходит из первого, входит в третий,
    # второй остаётся
    open_structure(page, net_id)
    helpers_org.transfer_member(page, person.id, third_id)
    expect(member_row(page, person.id)).to_have_count(0)
    assert _members_in(page, third_id, person.id) == 1
    assert _members_in(page, support_id, person.id) == 1
    assert _members_in(page, net_id, person.id) == 0
    assert _members_in(page, team_id, person.id) == 1, "команда при переводе отдела не затрагивается"
    line = _units_line(page, person.id)
    assert third_name in line and support_name in line and net_name not in line, line
    rows = helpers_org.audit_rows(page, "membership.transferred", person.id)
    assert len(rows) == 1 and net_name in rows[0] and third_name in rows[0], rows


def test_o02_no_menu_for_employee_dismissed_not_in_picker(admin_page, employee):
    """Сценарий 2, п. 6, 8: сотруднику без права «Управление структурой» карточка узла не показывает меню «…»,
    «Добавить сотрудников» и режимы, а прямые запросы отклоняются (403) и ничего не меняют; уволенного в выборе
    людей для добавления нет, а прямая попытка добавить его отклоняется (FR-123, FR-125, FR-127)."""
    page = admin_page
    token = secrets.token_hex(3)
    viewer = employee(full_name=f"Зритель{token} Иван Иванович")
    person = employee(activate=False, full_name=f"Участник{token} Олег Олегович")
    fired = employee(activate=False, full_name=f"Уволенный{token} Пётр Петрович")
    open_structure(page)
    rid = root_id(page)
    unit_id = create_unit(page, unique_name("Сеть"), kind="department", parent_id=rid)
    helpers_org.add_members(page, unit_id, [viewer.id, person.id, fired.id], q=token, mode="concurrent")

    # п. 6: сотрудник видит участников, но не меню, не «Добавить сотрудников» и не режимы
    employee_page = viewer.page
    open_structure(employee_page, unit_id)
    expect(member_row(employee_page, person.id).first).to_be_visible()
    expect(employee_page.locator("[data-member-menu]")).to_have_count(0)
    expect(employee_page.locator('[data-action="members-add"]')).to_have_count(0)
    expect(employee_page.locator("select[name=mode]")).to_have_count(0)
    expect(employee_page.locator('form[data-form="members-add"]')).to_have_count(0)
    assert direct_get(employee_page, f"/structure/{unit_id}/candidates/?q={token}").status == 403
    control = direct_post(employee_page, "/me/", {"phone": "+7 900 111-22-33", "contacts": "", "internal_phone": "",
                                                  "workplace": "", "birth_date": ""})
    assert control.status == 302, control.status  # токен CSRF принят: 403 ниже — отказ по праву
    for path, data in ((f"/structure/{unit_id}/members/", {"users": person.id, "mode": "transfer"}),
                       (f"/structure/{unit_id}/members/{person.id}/remove/", {}),
                       (f"/structure/{unit_id}/members/{person.id}/transfer/", {"target": rid}),
                       (f"/structure/people/{person.id}/dismiss/", {})):
        assert direct_post(employee_page, path, data).status == 403, path
    open_structure(page, unit_id)
    expect(member_row(page, person.id).first).to_be_visible()  # запросы ничего не изменили
    assert helpers_org.audit_rows(page, "user.dismissed", person.id) == []
    open_structure(page, unit_id)  # журнал увёл страницу: вернуться в карточку узла (T-2260, разрешение владельца)

    # увольняем третьего участника через меню «…» и диалог (сценарий 7)
    member_menu(page, fired.id).locator('[data-menu-item="dismiss"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(page.locator('[data-dialog="dismiss"]')).to_have_count(0)
    open_structure(page, unit_id)
    expect(member_row(page, fired.id)).to_have_count(0)  # уволенный ушёл из подразделения

    # п. 8: в выборе людей для добавления уволенного нет, живой с тем же запросом — есть
    other_id = create_unit(page, unique_name("Поддержка"), kind="department", parent_id=rid)
    page.goto(f"/structure/{other_id}/")
    details = page.locator('#unit-card details[data-action="members-add"]')
    details.locator("summary").first.click()
    form = details.locator('form[data-form="members-add"]')
    with page.expect_response(lambda r: "/candidates/" in r.url and r.status == 200):
        form.locator("input[name=q]").fill(token)
    expect(form.locator(f'label[data-candidate][data-user-id="{person.id}"]')).to_have_count(1)
    expect(form.locator(f'label[data-candidate][data-user-id="{fired.id}"]')).to_have_count(0)
    picker = direct_get(page, f"/structure/{other_id}/candidates/?q={token}")
    assert picker.status == 200 and f"Уволенный{token}" not in picker.text()
    assert f"Участник{token}" in picker.text()

    # прямая попытка добавить уволенного — отказ службы (200 с [role=alert]), членства нет
    response = direct_post(page, f"/structure/{other_id}/members/", {"users": fired.id, "mode": "concurrent"})
    assert response.status == 200 and has_alert(response), response.status
    assert _members_in(page, other_id, fired.id) == 0
