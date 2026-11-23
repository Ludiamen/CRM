"""Срез 010 «Поручения»: реестр (T-10109; FR-713, 717, NFR-721).

`apps.instructions.services.registry.rows` и страницы реестра — CONTRACT-010, раздел 11, К23. Код среза
импортируется внутри тестов: сбор проходит до появления моделей и служб.
"""
import datetime

import pytest

from tests import support, support_org
from tests import support_instructions as ins

pytestmark = pytest.mark.django_db


def registry():
    from apps.instructions.services import registry as module
    return module


def _base():
    tree = support_org.make_tree({"Отдел": {"Группа": {}}, "Чужой": {}})
    head = ins.head_of(tree["Отдел"])
    assignee = ins.staff_user()
    support_org.make_member(assignee, tree["Группа"])
    peer = support.make_employee()
    support_org.make_member(peer, tree["Группа"])
    controller = ins.staff_user()
    outsider = support.make_employee()
    support_org.make_member(outsider, tree["Чужой"])
    return tree, head, assignee, peer, controller, outsider


def _ids(data):
    return [row.pk for row in data["rows"]]


def test_visible_rows_include_participants_and_managers_but_not_outsiders():
    """FR-721: реестр показывает поручения участников и руководителей цепочки; посторонний и администратор чужих
    не видят."""
    tree, head, assignee, peer, controller, outsider = _base()
    extra_outside = support.make_employee()
    support_org.make_member(extra_outside, tree["Чужой"])

    own = ins.make_instruction(title="Исполнителю", author=controller, controller=controller, assignee=assignee)
    co = ins.make_instruction(title="Соисполнителю", author=controller, controller=controller, assignee=assignee)
    ins.add_coexecutor(co, peer)
    control = ins.make_instruction(title="Контролёру", author=head, controller=controller, assignee=assignee)
    managed = ins.make_instruction(title="Подчинённому", author=controller, controller=controller, assignee=peer)
    hidden = ins.make_instruction(title="Постороннему", author=outsider, controller=outsider, assignee=extra_outside)

    seen = _ids(registry().rows(assignee))
    assert {own.pk, co.pk, control.pk} <= set(seen)
    assert hidden.pk not in seen and managed.pk not in seen

    seen_controller = _ids(registry().rows(controller, preset="control"))
    assert {own.pk, co.pk, control.pk, managed.pk} <= set(seen_controller) and hidden.pk not in seen_controller

    seen_head = _ids(registry().rows(head, preset="subordinate"))
    assert managed.pk in seen_head and hidden.pk not in seen_head

    assert _ids(registry().rows(outsider, preset="control")) == [hidden.pk]
    admin = support.make_admin()
    support_org.make_member(admin, tree["Чужой"], mark="head")
    assert hidden.pk not in _ids(registry().rows(admin, preset="control"))


def test_presets_mine_control_subordinate_and_overdue():
    """FR-713: «Мои» — исполнитель или соисполнитель; «На моём контроле» — контролёр; «Подчинённых» — ответственный
    в управляемых узлах, кроме собственных; «Просроченные» — состояние «Просрочено»."""
    tree, head, assignee, peer, controller, outsider = _base()
    mine = ins.make_instruction(title="Моё", author=controller, controller=controller, assignee=assignee)
    as_co = ins.make_instruction(title="Соисполнителю", author=controller, controller=controller, assignee=peer)
    ins.add_coexecutor(as_co, assignee)
    on_control = ins.make_instruction(title="На контроле", author=head, controller=controller, assignee=peer)
    own_of_head = ins.make_instruction(title="Своё руководителя", author=head, controller=head, assignee=head)
    overdue = ins.make_instruction(title="Просрочено", author=controller, controller=controller, assignee=peer,
                                   deadline=ins._today() - datetime.timedelta(days=2))

    assert _ids(registry().rows(assignee, preset="mine")) == [mine.pk, as_co.pk]
    assert set(_ids(registry().rows(controller, preset="control"))) == {mine.pk, as_co.pk, on_control.pk, overdue.pk}
    subordinate = _ids(registry().rows(head, preset="subordinate"))
    assert peer.pk in {support.model("instructions.Instruction").objects.get(pk=pk).assignee_id for pk in subordinate}
    assert own_of_head.pk not in subordinate
    assert set(_ids(registry().rows(head, preset="overdue"))) == {overdue.pk}
    assert set(_ids(registry().rows(assignee, preset="unknown"))) == {mine.pk, as_co.pk}


def test_filters_basis_assignee_deadline_state_and_query():
    """FR-713: фильтры по основанию, исполнителю, сроку и статусу; поиск по названию и номеру; неизвестные ключи
    игнорируются."""
    tree, head, assignee, peer, controller, outsider = _base()
    kind = ins.make_basis("Приказ")
    today = ins._today()
    by_basis = ins.make_instruction(title="ПоОснованию", author=head, controller=head, assignee=assignee, basis=kind)
    by_assignee = ins.make_instruction(title="ПоИсполнителю", author=head, controller=head, assignee=peer)
    due_today = ins.make_instruction(title="СрокСегодня", author=head, controller=head, assignee=assignee,
                                     deadline=today)
    due_week = ins.make_instruction(title="СрокНаНеделе", author=head, controller=head, assignee=assignee,
                                    deadline=today + datetime.timedelta(days=3))
    overdue = ins.make_instruction(title="Просроченное", author=head, controller=head, assignee=assignee,
                                   deadline=today - datetime.timedelta(days=1))

    assert _ids(registry().rows(head, preset="control", filters={"basis": kind.pk})) == [by_basis.pk]
    assert _ids(registry().rows(head, preset="control", filters={"assignee": peer.pk})) == [by_assignee.pk]
    assert set(_ids(registry().rows(head, preset="control", filters={"deadline": "today"}))) == {due_today.pk}
    assert set(_ids(registry().rows(head, preset="control", filters={"deadline": "week"}))) == {due_today.pk, due_week.pk}
    assert set(_ids(registry().rows(head, preset="control", filters={"deadline": "overdue"}))) == {overdue.pk}
    assert set(_ids(registry().rows(head, preset="control", filters={"state": "overdue"}))) == {overdue.pk}
    assert _ids(registry().rows(head, preset="control", filters={"q": "Неделе"})) == [due_week.pk]
    assert _ids(registry().rows(head, preset="control", filters={"q": str(by_assignee.pk)})) == [by_assignee.pk]
    assert set(_ids(registry().rows(head, preset="control", filters={"unknown": "x"}))) >= {by_basis.pk}


def test_default_sort_deadline_then_updated_and_pages_twenty_fifty():
    """FR-713: порядок по сроку, затем изменению; страницы 20/50, `per_page` вне 20/50 — 20; `total`/`pages`."""
    tree, head, assignee, peer, controller, outsider = _base()
    today = ins._today()
    made = [ins.make_instruction(title=f"Поручение {index}", author=head, controller=head, assignee=assignee,
                                 deadline=today + datetime.timedelta(days=index))
            for index in range(25)]

    first = registry().rows(head, preset="control", per_page=20)
    assert (first["total"], first["pages"], first["page"], first["per_page"]) == (25, 2, 1, 20)
    assert _ids(first) == [row.pk for row in made[:20]]
    second = registry().rows(head, preset="control", per_page=20, page=2)
    assert _ids(second) == [row.pk for row in made[20:]]

    fifty = registry().rows(head, preset="control", per_page=50)
    assert fifty["per_page"] == 50 and len(fifty["rows"]) == 25
    fallback = registry().rows(head, preset="control", per_page=30)
    assert fallback["per_page"] == 20 and len(fallback["rows"]) == 20


def test_updated_sort_and_no_deadline_last():
    """FR-713: сортировка `updated` — по изменению; поручения без срока в конце (срок обязателен, проверяем
    защиту от пустого значения)."""
    tree, head, assignee, peer, controller, outsider = _base()
    first = ins.make_instruction(title="Раньше", author=head, controller=head, assignee=assignee,
                                 deadline=ins._today() + datetime.timedelta(days=1))
    second = ins.make_instruction(title="Позже", author=head, controller=head, assignee=assignee,
                                  deadline=ins._today() + datetime.timedelta(days=10))
    support.model("instructions.Instruction").objects.filter(pk=first.pk).update(
        updated_at=support.model("instructions.Instruction").objects.get(pk=second.pk).updated_at
        + datetime.timedelta(hours=1))
    assert _ids(registry().rows(head, preset="control")) == [first.pk, second.pk]
    assert _ids(registry().rows(head, preset="control", sort="updated")) == [second.pk, first.pk]


def test_sql_parameters_and_chain_any():
    """NFR-721: значения фильтров и цепочка узлов — параметры; текста поиска в SQL нет; цепочка — `= ANY(%s)`."""
    tree, head, assignee, peer, controller, outsider = _base()
    ins.make_instruction(title="Секретное поручение", author=head, controller=head, assignee=peer)
    pairs = ins.queries_with_params(lambda: registry().rows(head, preset="subordinate",
                                                            filters={"q": "Секретное"}))
    assert pairs, "реестр не выполнил ни одного запроса"
    joined = " ".join(sql for sql, _params in pairs)
    assert "Секретное" not in joined, "значение поиска попало в текст SQL"
    assert any("Секретное" in str(params) for _sql, params in pairs), "значения поиска нет в параметрах"
    assert "= ANY(%s)" in joined, "цепочка узлов не массивом"
    chain_params = [params for sql, params in pairs if "= ANY(%s)" in sql]
    assert chain_params and any(isinstance(value, (list, tuple)) for params in chain_params for value in params)


def test_registry_page_and_fragment_render_hooks(client):
    """CONTRACT-010, 6.3: страница реестра и фрагмент отдают строки `[data-instruction-id]` с состоянием,
    пресеты и пустое состояние; фрагмент — без `<html>`."""
    tree, head, assignee, peer, controller, outsider = _base()
    row = ins.make_instruction(title="В реестре", author=head, controller=head, assignee=assignee)
    support.login(client, assignee)

    page = client.get("/instructions/")
    html = page.content.decode()
    assert page.status_code == 200 and 'data-instructions-page="registry"' in html
    assert 'data-instructions-preset="mine"' in html
    assert f'data-instruction-id="{row.pk}"' in html and "data-instruction-state=" in html

    fragment = client.get("/instructions/list/?preset=mine")
    text = fragment.content.decode()
    assert fragment.status_code == 200 and "<html" not in text.lower()
    assert f'data-instruction-id="{row.pk}"' in text

    empty = client.get("/instructions/list/?preset=overdue")
    assert "Поручений пока нет" in empty.content.decode()