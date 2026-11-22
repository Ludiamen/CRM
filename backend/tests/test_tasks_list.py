"""Срез 009 «Задачи»: список, пресеты и фильтры (T-9107; FR-685, FR-686, NFR-712).

`tasks.services.list.rows(viewer, *, preset, filters, sort, page, per_page)` — один SQL с видимостью и
`deleted_at IS NULL`; пресеты `mine`, `authored`, `subordinate`, `work`, `overdue`; фильтры и сортировки из
белого списка; страницы 20/50 (CONTRACT-009, 5.1, 6.2).
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from tests import support, support_org
from tests import support_tasks

pytestmark = pytest.mark.django_db


def listing():
    from apps.tasks.services import list as module
    return module


def _member(unit, **extra):
    user = support.make_employee(**extra)
    support_org.make_member(user, unit)
    return user


def _marked(unit, mark, **extra):
    user = support.make_employee(**extra)
    support_org.make_member(user, unit, mark=mark)
    return user


def _titles(result) -> list[str]:
    return [row.title for row in result["rows"]]


def test_mine_authored_work_and_overdue_presets():
    """FR-685: «Мои» — задачи, где я исполнитель; «Поставленные мной» — автор; «В работе» — статус
    `in_progress`; «Просрочены» — дата срока раньше сегодняшней и статус не «Готово» (сценарий 3)."""
    viewer = support_tasks.staff_user()
    other = support.make_employee()
    today = timezone.localdate()
    support_tasks.make_task(title="Моя", author=other, assignee=viewer)
    support_tasks.make_task(title="Поставленная", author=viewer, assignee=other)
    support_tasks.make_task(title="В работе", author=other, assignee=viewer, status="in_progress")
    support_tasks.make_task(title="Просрочена", author=other, assignee=viewer,
                            deadline=today - timedelta(days=5), status="waiting")
    support_tasks.make_task(title="Просрочена, но готова", author=other, assignee=viewer,
                            deadline=today - timedelta(days=5), status="done")
    support_tasks.make_task(title="Сегодня", author=other, assignee=viewer, deadline=today)

    assert {"Моя", "В работе", "Просрочена", "Сегодня"} <= set(_titles(listing().rows(viewer, preset="mine")))
    assert "Поставленная" not in _titles(listing().rows(viewer, preset="mine"))
    assert "Поставленная" in _titles(listing().rows(viewer, preset="authored"))
    assert _titles(listing().rows(viewer, preset="work")) == ["В работе"]
    assert _titles(listing().rows(viewer, preset="overdue")) == ["Просрочена"]


def test_subordinate_preset_uses_current_structure():
    """FR-686: «Задачи подчинённых» — задачи сотрудников управляемых узлов на момент просмотра; после перевода
    сотрудник пропадает у прежнего руководителя и появляется у нового."""
    tree = support_org.make_tree({"Первый": {}, "Второй": {}})
    employee = _member(tree["Первый"])
    first_head = _marked(tree["Первый"], "head")
    second_head = _marked(tree["Второй"], "head")
    support_tasks.make_task(title="Подчинённому", author=first_head, assignee=employee)
    assert _titles(listing().rows(first_head, preset="subordinate")) == ["Подчинённому"]
    assert _titles(listing().rows(second_head, preset="subordinate")) == []

    from apps.org.services import membership

    membership.transfer_member(employee, tree["Первый"], tree["Второй"], actor=first_head)
    assert _titles(listing().rows(first_head, preset="subordinate")) == []
    assert _titles(listing().rows(second_head, preset="subordinate")) == ["Подчинённому"]


def test_filters_status_deadline_assignee_and_category():
    """FR-685: фильтры по статусу, сроку (`today`/`week`/`overdue`/`none`), исполнителю и категории — только
    подходящие задачи; чужие ключи отбрасываются."""
    viewer = support_tasks.staff_user()
    peer = support.make_employee()
    category = support_tasks.make_category("Работа")
    today = timezone.localdate()
    support_tasks.make_task(title="Сегодня", author=viewer, assignee=viewer, deadline=today)
    support_tasks.make_task(title="На неделе", author=viewer, assignee=peer, deadline=today + timedelta(days=3),
                            category=category)
    support_tasks.make_task(title="Без срока", author=viewer, assignee=viewer)

    assert _titles(listing().rows(viewer, preset="mine", filters={"deadline": "today"})) == ["Сегодня"]
    assert _titles(listing().rows(viewer, preset="authored", filters={"deadline": "week"})) == ["На неделе"]
    assert _titles(listing().rows(viewer, preset="authored", filters={"deadline": "none"})) == ["Без срока"]
    assert _titles(listing().rows(viewer, preset="authored", filters={"assignee": peer.pk})) == ["На неделе"]
    assert _titles(listing().rows(viewer, preset="authored", filters={"category": category.pk})) == ["На неделе"]
    assert _titles(listing().rows(viewer, preset="authored", filters={"category": "none"})) == [
        "Сегодня", "Без срока"]
    assert _titles(listing().rows(viewer, preset="mine", filters={"status": "in_progress"})) == []


def test_default_order_is_deadline_then_updated():
    """FR-685: по умолчанию — по сроку (пустой срок последним), затем по изменению; сортировки `deadline` и
    `updated` из белого списка."""
    viewer = support_tasks.staff_user()
    today = timezone.localdate()
    late = support_tasks.make_task(title="Позже", author=viewer, assignee=viewer, deadline=today + timedelta(days=5))
    soon = support_tasks.make_task(title="Скоро", author=viewer, assignee=viewer, deadline=today + timedelta(days=1))
    none = support_tasks.make_task(title="Без срока", author=viewer, assignee=viewer)
    assert _titles(listing().rows(viewer)) == ["Скоро", "Позже", "Без срока"]
    assert _titles(listing().rows(viewer, sort="updated"))[0] == none.title
    assert _titles(listing().rows(viewer, sort="deadline")) == [soon.title, late.title, none.title]


def test_pages_20_and_50_and_unknown_values_fall_back():
    """FR-685: страницы по 20 или 50; иное число — 20; неверный пресет — «Мои»; в ответе есть `total`, `pages`,
    `page`, `per_page`."""
    viewer = support_tasks.staff_user()
    for index in range(25):
        support_tasks.make_task(title=f"Задача {index:02d}", author=viewer, assignee=viewer)
    first = listing().rows(viewer, page=1)
    assert (first["per_page"], len(first["rows"]), first["total"], first["pages"]) == (20, 20, 25, 2)
    assert len(listing().rows(viewer, page=2)["rows"]) == 5
    assert listing().rows(viewer, per_page=50)["per_page"] == 50
    assert listing().rows(viewer, per_page=7)["per_page"] == 20
    assert listing().rows(viewer, preset="unknown")["total"] == 25


def test_deleted_tasks_are_excluded():
    """FR-695: мягко удалённая задача не входит ни в один пресет и не считается в `total`."""
    viewer = support_tasks.staff_user()
    task = support_tasks.make_task(title="Удалённая", author=viewer, assignee=viewer)
    from apps.tasks.services import tasks as service

    service.soft_delete(viewer, task)
    assert listing().rows(viewer)["total"] == 0


def test_query_count_is_constant_and_values_are_parameters():
    """NFR-712: число SQL не зависит от количества строк (20 и 50), значения фильтров — параметрами, а не в тексте
    SQL (CONTRACT-009, правила тестов)."""
    viewer = support_tasks.staff_user()
    for index in range(30):
        support_tasks.make_task(title=f"Строка {index}", author=viewer, assignee=viewer)
    short = support_tasks.queries_with_params(lambda: listing().rows(viewer, per_page=20))
    long = support_tasks.queries_with_params(lambda: listing().rows(viewer, per_page=50))
    assert len(short) == len(long)
    string = support_tasks.staff_user(full_name="Фильтров Фильтр")
    support_tasks.make_task(title="С фильтром", author=viewer, assignee=string)
    queries = support_tasks.queries_with_params(
        lambda: listing().rows(viewer, preset="authored", filters={"assignee": string.pk}))
    assert any(str(string.pk) in str(params) for _sql, params in queries), "номер исполнителя не ушёл параметром"