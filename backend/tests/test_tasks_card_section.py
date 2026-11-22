"""T-9120: раздел «Задачи» в карточке сотрудника (FR-698; CONTRACT-009, 11).

План «Поиск, карточка сотрудника»: раздел точки `card_sections` — задачи, где сотрудник автор, исполнитель,
соисполнитель или наблюдатель и которые видит смотрящий; никакого сужения сверх видимости; пусто — раздела нет
или пустой список по правилу ядра (как «Заявки»). Контракт: 3 (`card_sections` —
`CardSection("tasks", "profile", 75, "tasks/_card_section.html", {"url": …})`, К4), 4 (`visible`), 6.3
(`[data-tasks-page="card"]`), 11.

Код среза на уровне модуля не импортируется: модели — `support.model(...)`, точка и шаблон — внутри тестов, поэтому
`pytest --collect-only` проходит до появления кода. Секретов и ПДн нет: ФИО вымышленные.
"""
import pytest
from django.template.loader import render_to_string

from tests import support
from tests import support_org
from tests import support_tasks

pytestmark = pytest.mark.django_db

KEY = "tasks"
TEMPLATE = "tasks/_card_section.html"
ORDER = 75


# --- помощники файла --------------------------------------------------------------------------------------

def _registered_sections(viewer, person) -> list:
    """Разделы карточки, которые отдаёт точка `card_sections` (только записи `apps.tasks`)."""
    from apps.core import extensions

    found = []
    for func in extensions.registered("card_sections"):
        if getattr(func, "__module__", "").startswith("apps.tasks"):
            found += func(viewer, person)
    return found


def _section_html(section) -> str:
    """Разметка раздела по его шаблону и контексту (как ядро: `{% include section.template with ctx=section.context %}`)."""
    return render_to_string(section.template, section.context)


def _all_html(viewer, person) -> str:
    return "\n".join(_section_html(section) for section in _registered_sections(viewer, person))


def _titles(*names: str) -> dict[str, object]:
    return {name: support_tasks.make_task(name) for name in names}


# --- 1. запись точки --------------------------------------------------------------------------------------

def test_card_section_registered_with_key_profile_order_75_and_template():
    """FR-698: `apps.tasks` регистрирует в `card_sections` одну функцию; для сотрудника с видимой задачей она
    отдаёт ровно `CardSection("tasks", "profile", 75, "tasks/_card_section.html", {"url": …})` (К4): вкладка
    `profile`, порядок 75 — после «Заявок» 60 и мессенджера 70; в контексте есть адрес раздела `/tasks/…`."""
    from apps.tasks import extensions

    owner = support_tasks.staff_user(full_name="Смотрящий Раздела")
    support_tasks.make_task("Задача раздела", author=owner, assignee=owner)
    sections = _registered_sections(owner, owner)
    assert len(sections) == 1, f"разделов задач: {len(sections)}"
    section = sections[0]
    assert (section.key, section.tab, section.order, section.template) == (KEY, "profile", ORDER, TEMPLATE)
    assert isinstance(section.context, dict)
    url = section.context.get("url")
    assert isinstance(url, str) and url.startswith("/tasks/"), f"адрес раздела: {url!r}"

    from apps.core.views import me

    core_sections = me.card_sections(owner, owner)["profile"]
    assert section in core_sections
    orders = [item.order for item in core_sections]
    assert orders == sorted(orders), f"ядро не отсортировало разделы: {orders}"
    assert section in core_sections


# --- 2. четыре роли участника ----------------------------------------------------------------------------

def test_card_section_lists_tasks_of_author_assignee_coexecutor_and_observer():
    """FR-698: в своей карточке сотрудник видит все четыре свои роли — задачу, где он автор, где исполнитель, где
    соисполнитель и где наблюдатель; раздел отдаёт их списком/разметкой с ссылками `/tasks/<id>/`."""
    person = support_tasks.staff_user(full_name="Участник Четырёх Ролей")
    colleague = support_tasks.staff_user(full_name="Коллега Ролей")
    authored = support_tasks.make_task("Авторская задача карточки", author=person, assignee=colleague)
    assigned = support_tasks.make_task("Исполнительная задача карточки", author=colleague, assignee=person)
    coexecuted = support_tasks.make_task("Соисполнительская задача карточки", author=colleague, assignee=colleague)
    support_tasks.add_member(coexecuted, person, role="coexecutor")
    observed = support_tasks.make_task("Наблюдательская задача карточки", author=colleague, assignee=colleague)
    support_tasks.add_member(observed, person, role="observer")

    html = _all_html(person, person)
    for task in (authored, assigned, coexecuted, observed):
        assert f"/tasks/{task.pk}/" in html, f"в разделе нет задачи {task.pk}"
        assert task.title in html, f"в разделе нет названия задачи {task.pk}"


# --- 3. видимость смотрящего ------------------------------------------------------------------------------

def test_card_section_shows_only_tasks_visible_to_viewer():
    """FR-698, FR-677: руководитель узла видит в карточке подчинённого его задачи (видимость `visible`), а
    посторонний сотрудник — нет: раздел пуст или его нет, чужих названий и ссылок в разметке нет."""
    unit = support_org.make_unit("Отдел Карточки")
    head = support_tasks.head_of(unit, full_name="Руководитель Карточки")
    person = support.make_employee(full_name="Подчинённый Карточки")
    support_org.make_member(person, unit)
    colleague = support.make_employee(full_name="Коллега Подчинённого")
    support_org.make_member(colleague, unit)
    own = support_tasks.make_task("Задача подчинённого в узле", author=person, assignee=colleague)
    authored = support_tasks.make_task("Задача подчинённого коллеге", author=person, assignee=person)

    head_html = _all_html(head, person)
    assert f"/tasks/{own.pk}/" in head_html and f"/tasks/{authored.pk}/" in head_html, (
        "руководитель не видит задачи подчинённого в карточке")

    outsider = support.make_with_permissions("tasks.use", full_name="Посторонний Смотрящий")
    sections = _registered_sections(outsider, person)
    assert sections == [] or not any(task.title in _section_html(section)
                                     for section in sections for task in (own, authored)), (
        "посторонний видит задачи в чужой карточке")


# --- 4. удалённые и чужие ---------------------------------------------------------------------------------

def test_card_section_omits_deleted_tasks():
    """FR-698, FR-695: мягко удалённая задача (`deleted_at`) в раздел не попадает — ни названия, ни ссылки нет;
    живые задачи остаются."""
    person = support_tasks.staff_user(full_name="Владелец Удалённой")
    alive = support_tasks.make_task("Живая задача карточки", author=person, assignee=person)
    removed = support_tasks.make_task("Удалённая задача карточки", author=person, assignee=person)
    from django.utils import timezone

    support.model("tasks.Task").objects.filter(pk=removed.pk).update(deleted_at=timezone.now())
    html = _all_html(person, person)
    assert f"/tasks/{alive.pk}/" in html
    assert removed.title not in html and f"/tasks/{removed.pk}/" not in html, "удалённая задача в разделе"


# --- 5. страница карточки ---------------------------------------------------------------------------------

def test_staff_card_page_renders_tasks_section_and_links():
    """FR-698 (NFR-717): на странице карточки сотрудника (`/me/`) раздел «Задачи» отрисован по своему шаблону:
    видно название «Задачи» и ссылку на свою задачу `/tasks/<id>/`; страница отвечает 200."""
    viewer = support.make_with_permissions("tasks.use", "staff.view", full_name="Смотрящий Страницы Карточки")
    task = support_tasks.make_task("Задача на странице карточки", author=viewer, assignee=viewer)
    response = support.logged_in(viewer).get("/me/")
    assert response.status_code == 200, f"/me/: {response.status_code}"
    html = response.content.decode("utf-8")
    assert "Задачи" in html, "на странице карточки нет раздела «Задачи»"
    assert f"/tasks/{task.pk}/" in html, "в карточке нет ссылки на задачу"
    assert task.title in html, "в карточке нет названия задачи"


# --- 6. пустая карточка -----------------------------------------------------------------------------------

def test_card_section_is_empty_when_person_has_no_visible_tasks():
    """FR-698: у сотрудника без видимых смотрящему задач раздела нет или он пуст — ни одной ссылки `/tasks/` в его
    разметке; у сотрудника с задачей раздел возвращается."""
    viewer = support_tasks.viewer(full_name="Смотрящий Пустой Карточки")
    empty_person = support.make_employee(full_name="Сотрудник Без Задач")
    empty_html = _all_html(viewer, empty_person)
    assert "/tasks/" not in empty_html and "data-task-id" not in empty_html, (
        "у сотрудника без задач раздел не пуст")

    busy = support_tasks.staff_user(full_name="Сотрудник С Задачей")
    task = support_tasks.make_task("Единственная задача карточки", author=busy, assignee=busy)
    assert f"/tasks/{task.pk}/" in _all_html(busy, busy)