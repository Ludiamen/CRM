"""T-2141: сценарий 3 — руководители и заместители узла; карточка показывает руководителя (FR-114…117)."""
import secrets

from playwright.sync_api import expect

from tests.e2e import helpers_org
from tests.e2e.helpers_org import (create_unit, direct_post, has_alert, member_row, open_structure, root_id,
                                   unique_name, unit_card)

ONLY_MEMBER = "руководителем и заместителем может быть только участник узла"
HEAD_OR_DEPUTY = "в одном узле человек либо руководитель, либо заместитель"


def _field(page, user_id, name):
    """Поле `[data-field="<name>"]` карточки `/staff/<id>/` (локатор; страница открывается заново)."""
    page.goto(f"/staff/{user_id}/")
    expect(page.locator(f'[data-card][data-user-id="{user_id}"]')).to_be_visible()
    return page.locator(f'[data-card][data-user-id="{user_id}"] [data-field="{name}"]')


def _head_line(page, user_id) -> str:
    """Текст строки «Руководитель» карточки сотрудника."""
    field = _field(page, user_id, "head")
    expect(field).to_be_visible()
    return field.inner_text().strip()


def _root_heads(page, rid) -> list:
    """Номера людей, отмеченных руководителями корня (раздел `heads` карточки корня)."""
    open_structure(page, rid)
    return [r.get_attribute("data-user-id") for r in unit_card(page).locator('[data-section="heads"] [data-member]').all()]


def _marks_events(page, unit_id) -> int:
    """Сколько событий `unit.marks_changed` в журнале у узла."""
    return len(helpers_org.audit_rows(page, "unit.marks_changed", unit_id))


def test_o03_heads_deputies_marks_and_card_head_line(admin_page, employee):
    """Сценарий 3, п. 1, 4, 5, 6: администратор отмечает участника руководителем — рядом с именем метка
    «Руководитель», а в карточках участников отдела в строке «Руководитель» его имя; совместитель в двух отделах
    с разными руководителями видит «Сеть: …; Поддержка: …»; если во всей цепочке до корня руководителей нет,
    написано «не назначен»; из двух заместителей убрать одного — второй остаётся, журнал пишет «было / стало»
    (FR-114, FR-115, FR-116)."""
    page = admin_page
    token = secrets.token_hex(3)
    head_net = employee(activate=False, full_name=f"Начальник{token} Иван Петрович")
    head_support = employee(activate=False, full_name=f"Глава{token} Пётр Иванович")
    member = employee(activate=False, full_name=f"Рядовой{token} Олег Олегович")
    dep1 = employee(activate=False, full_name=f"Зам{token}а Анна Андреевна")
    dep2 = employee(activate=False, full_name=f"Зам{token}б Борис Борисович")
    both = employee(activate=False, full_name=f"Совмест{token} Сергей Сергеевич")
    open_structure(page)
    rid = root_id(page)
    saved_root_heads = _root_heads(page, rid)  # другие тесты круга могли назначить руководителя корня
    try:
        net_name, support_name = unique_name("Сеть"), unique_name("Поддержка")
        net_id = create_unit(page, net_name, kind="department", parent_id=rid)
        support_id = create_unit(page, support_name, kind="department", parent_id=rid)
        helpers_org.add_members(page, net_id, [head_net.id, member.id, dep1.id, dep2.id, both.id], q=token,
                                mode="concurrent")
        helpers_org.add_members(page, support_id, [head_support.id, both.id], q=token, mode="concurrent")

        # п. 5: во всей цепочке до корня руководителей нет — «не назначен»
        if saved_root_heads:
            helpers_org.set_marks(page, rid, "heads", [])
        assert _root_heads(page, rid) == []
        expect(_field(page, member.id, "head")).to_have_attribute("data-empty", "true")
        assert "не назначен" in _head_line(page, member.id)
        expect(page.locator(f'[data-card][data-user-id="{member.id}"] [data-field-label="head"]')).to_contain_text(
            "Руководитель")

        # п. 1: отмечаем руководителя отдела «Сеть»
        message = helpers_org.set_marks(page, net_id, "heads", [head_net.id])
        assert message, "после отметки портал ничего не сообщил"
        open_structure(page, net_id)
        expect(member_row(page, head_net.id, "heads")).to_have_count(1)
        expect(member_row(page, head_net.id).first).to_have_attribute("data-mark", "head")
        expect(member_row(page, head_net.id).first.locator("[data-mark-label]").first).to_contain_text("Руководитель")
        expect(member_row(page, member.id).first).to_have_attribute("data-mark", "")
        expect(member_row(page, member.id).first.locator("[data-mark-label]")).to_have_count(0)
        for person in (member, dep1, dep2):  # в карточках участников «Сети» — его имя
            assert head_net.full_name in _head_line(page, person.id), person.full_name

        # п. 6: два заместителя; убираем одного — второй остаётся, журнал пишет «было / стало»
        helpers_org.set_marks(page, net_id, "deputies", [dep1.id, dep2.id])
        open_structure(page, net_id)
        for deputy in (dep1, dep2):
            expect(member_row(page, deputy.id).first).to_have_attribute("data-mark", "deputy")
            expect(member_row(page, deputy.id).first.locator("[data-mark-label]").first).to_contain_text("Заместитель")
        before = _marks_events(page, net_id)
        helpers_org.set_marks(page, net_id, "deputies", [dep1.id])
        open_structure(page, net_id)
        expect(member_row(page, dep1.id).first).to_have_attribute("data-mark", "deputy")
        expect(member_row(page, dep2.id).first).to_have_attribute("data-mark", "")
        expect(member_row(page, dep2.id).first.locator("[data-mark-label]")).to_have_count(0)
        expect(member_row(page, dep2.id, "deputies")).to_have_count(0)
        expect(member_row(page, head_net.id).first).to_have_attribute("data-mark", "head")  # руководитель не тронут
        sides = helpers_org.audit_sides(page, "unit.marks_changed", net_id)
        assert len(sides) == before + 1, sides
        was, became = sides[0]  # новое событие сверху: было — оба заместителя, стало — только оставшийся
        assert dep1.full_name in was and dep2.full_name in was, was
        assert dep1.full_name in became and dep2.full_name not in became, became

        # п. 4: совместитель в двух отделах с разными руководителями — руководитель по каждому узлу
        helpers_org.set_marks(page, support_id, "heads", [head_support.id])
        expected = {net_id: f"{net_name}: {head_net.full_name}", support_id: f"{support_name}: {head_support.full_name}"}
        paths = [(f"/{rid}/{uid}/", expected[uid]) for uid in (net_id, support_id)]
        line = _head_line(page, both.id)
        assert line == "; ".join(text for _, text in sorted(paths)), line
        # участник только «Сети» руководителя «Поддержки» в своей строке не видит
        assert head_support.full_name not in _head_line(page, member.id)
    finally:
        if saved_root_heads:
            helpers_org.set_marks(page, rid, "heads", saved_root_heads)


def test_o03_head_of_unit_sees_upper_heads_and_subordinates(admin_page, employee):
    """Сценарий 3, п. 2, 3, 9: у отдела без руководителя в строке «Руководитель» — руководители ближайшего
    вышестоящего узла; руководитель отдела видит там не себя, а вышестоящих, и у него есть строка «Подчинённые» —
    участники отдела и вложенных узлов без него самого и без повторов; обычный участник строки «Подчинённые» не
    имеет; перевод руководителя в другой отдел снимает отметку вместе с членством, у отдела руководителя нет, журнал
    записал оба изменения, а строка «Руководитель» участников снова указывает на вышестоящего (FR-115, FR-116)."""
    page = admin_page
    token = secrets.token_hex(3)
    top_head = employee(activate=False, full_name=f"Верхний{token} Игорь Игоревич")
    net_head = employee(activate=False, full_name=f"Сетевой{token} Роман Романович")
    sub1 = employee(activate=False, full_name=f"Подчин{token}а Дарья Дмитриевна")
    sub2 = employee(activate=False, full_name=f"Подчин{token}б Елена Егоровна")
    open_structure(page)
    rid = root_id(page)
    top_name, net_name, group_name, support_name = (unique_name("Верх"), unique_name("Сеть"), unique_name("Группа"),
                                                    unique_name("Поддержка"))
    top_id = create_unit(page, top_name, kind="department", parent_id=rid)
    net_id = create_unit(page, net_name, kind="department", parent_id=top_id)
    group_id = create_unit(page, group_name, kind="team", parent_id=net_id)
    support_id = create_unit(page, support_name, kind="department", parent_id=rid)
    helpers_org.add_members(page, top_id, [top_head.id], q=token, mode="concurrent")
    helpers_org.add_members(page, net_id, [net_head.id, sub1.id], q=token, mode="concurrent")
    helpers_org.add_members(page, group_id, [sub2.id], q=token)
    helpers_org.set_marks(page, top_id, "heads", [top_head.id])

    # п. 2: у «Сети» руководителя нет, у вышестоящего есть — в карточках участников он
    assert _head_line(page, sub1.id) == top_head.full_name
    assert _head_line(page, sub2.id) == top_head.full_name  # и у команды внутри «Сети»

    # п. 3: «Сеть» получает руководителя; он сам видит вышестоящего, а подчинённые — его
    helpers_org.set_marks(page, net_id, "heads", [net_head.id])
    assert _head_line(page, net_head.id) == top_head.full_name  # «а не он сам»
    assert _head_line(page, sub1.id) == net_head.full_name
    assert _head_line(page, sub2.id) == net_head.full_name
    subordinates = _field(page, net_head.id, "subordinates")
    expect(subordinates).to_be_visible()
    expect(page.locator(f'[data-card][data-user-id="{net_head.id}"] [data-field-label="subordinates"]')
           ).to_contain_text("Подчинённые")
    text = subordinates.inner_text()
    assert sub1.full_name in text and sub2.full_name in text, text  # участники «Сети» и вложенной команды
    assert net_head.full_name not in text, text  # кроме него самого
    expect(_field(page, sub1.id, "subordinates")).to_have_count(0)  # у обычного участника строки нет
    top_text = _field(page, top_head.id, "subordinates").inner_text()
    for person in (net_head, sub1, sub2):  # руководитель верхнего узла: вложенные узлы, каждый один раз
        assert top_text.count(person.full_name) == 1, (person.full_name, top_text)
    assert top_head.full_name not in top_text

    # п. 9: руководителя «Сети» переводим в «Поддержку»
    marks_before = _marks_events(page, net_id)
    helpers_org.add_members(page, support_id, [net_head.id], q=token, mode="transfer")
    open_structure(page, net_id)
    expect(member_row(page, net_head.id)).to_have_count(0)  # отметка ушла вместе с членством
    expect(unit_card(page).locator('[data-section="heads"] [data-member]')).to_have_count(0)  # у «Сети» руководителя нет
    open_structure(page, support_id)
    expect(member_row(page, net_head.id).first).to_have_attribute("data-mark", "")  # в новом узле отметки нет
    assert _head_line(page, sub1.id) == top_head.full_name  # участники «Сети» снова у вышестоящего
    removed = helpers_org.audit_rows(page, "membership.removed", net_head.id)
    assert removed and net_name in removed[0], removed  # снятие членства (отметка видна в «было»)
    moved = helpers_org.audit_rows(page, "membership.transferred", net_head.id)
    assert len(moved) == 1 and net_name in moved[0] and support_name in moved[0], moved  # и сам перевод
    assert _marks_events(page, net_id) == marks_before  # отдельного события отметок нет, отметка видна в «было»


def test_o03_mark_rules_and_no_manager_role(admin_page, employee):
    """Сценарий 3, п. 7, 8, 10: не участника узла нельзя отметить руководителем («только участник узла»);
    руководителей может быть несколько или ни одного; отметка руководителя не выдаёт роль «Руководитель»
    (SPEC-001) — в ролях сотрудника её нет; в одном узле человек либо руководитель, либо заместитель — отказ в обе
    стороны, отметки остаются прежними (FR-114, FR-117)."""
    page = admin_page
    token = secrets.token_hex(3)
    first = employee(activate=False, full_name=f"Первый{token} Иван Иванович")
    second = employee(activate=False, full_name=f"Второй{token} Пётр Петрович")
    deputy = employee(activate=False, full_name=f"Зам{token} Олег Олегович")
    outsider = employee(activate=False, full_name=f"Чужой{token} Анна Андреевна")
    open_structure(page)
    rid = root_id(page)
    unit_id = create_unit(page, unique_name("Сеть"), kind="department", parent_id=rid)
    helpers_org.add_members(page, unit_id, [first.id, second.id, deputy.id], q=token, mode="concurrent")

    # п. 7: человек вне узла — в форме отметок его нет, прямой запрос отклонён
    page.goto(f"/structure/{unit_id}/")
    page.locator('#unit-card details[data-action="marks-heads"] summary').first.click()
    form = page.locator('#unit-card form[data-form="marks-heads"]')
    expect(form.locator(f'input[name=users][value="{first.id}"]')).to_have_count(1)
    expect(form.locator(f'input[name=users][value="{outsider.id}"]')).to_have_count(0)
    events = _marks_events(page, unit_id)
    response = direct_post(page, f"/structure/{unit_id}/marks/", {"part": "heads", "users": outsider.id})
    assert response.status == 200 and has_alert(response), response.status
    assert ONLY_MEMBER in response.text().lower()
    open_structure(page, unit_id)
    expect(member_row(page, outsider.id)).to_have_count(0)
    expect(unit_card(page).locator('[data-section="heads"] [data-member]')).to_have_count(0)
    assert _marks_events(page, unit_id) == events

    # руководителей может быть несколько; п. 8: отметка не выдаёт роль «Руководитель»
    helpers_org.set_marks(page, unit_id, "heads", [first.id, second.id])
    open_structure(page, unit_id)
    for person in (first, second):
        expect(member_row(page, person.id, "heads")).to_have_count(1)
        expect(member_row(page, person.id).first.locator("[data-mark-label]").first).to_contain_text("Руководитель")
    page.goto(f"/staff/{first.id}/")
    roles = [t.strip() for t in page.locator(f'[data-card][data-user-id="{first.id}"] [data-role-name]').all_inner_texts()]
    assert "Сотрудник ИТ" in roles, roles  # роли карточки видны (проверка не пустая)
    assert "Руководитель" not in roles, roles  # отметка и роль не связаны
    helpers_org.set_marks(page, unit_id, "heads", [first.id])
    open_structure(page, unit_id)
    expect(member_row(page, second.id).first).to_have_attribute("data-mark", "")
    expect(member_row(page, first.id).first).to_have_attribute("data-mark", "head")

    # п. 10: руководитель не может стать заместителем того же узла — отказ, отметки прежние
    events = _marks_events(page, unit_id)
    message = helpers_org.set_marks(page, unit_id, "deputies", [first.id])
    assert HEAD_OR_DEPUTY in message.lower(), message
    open_structure(page, unit_id)
    expect(member_row(page, first.id).first).to_have_attribute("data-mark", "head")
    expect(unit_card(page).locator('[data-section="deputies"] [data-member]')).to_have_count(0)

    # и наоборот: заместитель не может стать руководителем
    helpers_org.set_marks(page, unit_id, "deputies", [deputy.id])
    events += 1
    message = helpers_org.set_marks(page, unit_id, "heads", [first.id, deputy.id])
    assert HEAD_OR_DEPUTY in message.lower(), message
    open_structure(page, unit_id)
    expect(member_row(page, deputy.id).first).to_have_attribute("data-mark", "deputy")
    expect(member_row(page, first.id).first).to_have_attribute("data-mark", "head")
    expect(unit_card(page).locator('[data-section="heads"] [data-member]')).to_have_count(1)
    assert _marks_events(page, unit_id) == events, "отказ записал событие в журнал"

    # ноль руководителей: набор очищается
    helpers_org.set_marks(page, unit_id, "heads", [])
    open_structure(page, unit_id)
    expect(unit_card(page).locator('[data-section="heads"] [data-member]')).to_have_count(0)
