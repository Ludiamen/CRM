"""T-9113: виды и получатели уведомлений задач, цепочка вышестоящих, приоритет, свои действия, внешний текст,
письмо через 15 минут (FR-691, FR-692, NFR-714).

Источники: PLAN-009 «Уведомления и сводка» (восемь видов `tasks.*`; получатели: `assigned` — исполнитель и
соисполнители без автора; `due_soon`/`due` — исполнитель и соисполнители; `overdue` — они же и постановщик;
`subordinate_overdue` — руководители и заместители всей цепочки вышестоящих узлов исполнителя; при совмещении —
одно сообщение с приоритетом `subordinate_overdue`; `reminder` — сам поставивший; `comment` — участники без автора;
о собственных действиях уведомлений нет; внешний текст постоянный, без названия и описания; письмо — через 15 минут,
если не прочитано); CONTRACT-009: 5.1 (`notify_rules.recipients`, `is_own_action`), 5.3, 9.1 (коды, названия,
`order` 210–217, каналы, внешний текст), 9.2 (получатели и «свои действия»), 12.2 (тексты интерфейса).

Код среза импортируется внутри тестов, модели — через `support.model`; сбор проходит до появления кода. Шина
событий срезом не используется: уведомления создают службы задач, поэтому проверки идут настоящим путём служб, а
результат читается из `notify.Notification`/`notify.Delivery`. Секретов и ПДн нет: ФИО вымышленные.
"""
import importlib
from datetime import date, timedelta

import pytest

from tests import support
from tests import support_org
from tests import support_tasks as tasks_helpers

pytestmark = pytest.mark.django_db

MODULE = "Задачи"
KINDS = (
    ("tasks.assigned", "Назначена задача", 210, "Вам назначена задача"),
    ("tasks.due_soon", "Задача скоро просрочена", 211, "Срок задачи приближается"),
    ("tasks.due", "Срок наступил", 212, "Срок задачи наступил"),
    ("tasks.overdue", "Задача просрочена", 213, "Задача просрочена"),
    ("tasks.subordinate_overdue", "Задача подчинённого просрочена", 214, "Задача подчинённого просрочена"),
    ("tasks.reminder", "Вы просили напомнить", 215, "Напоминание о задаче"),
    ("tasks.comment", "Новый комментарий", 216, "Новый комментарий к задаче"),
    ("tasks.subordinate_digest", "Сводка по задачам подчинённых", 217, "Сводка по задачам подчинённых"),
)
CODES = tuple(item[0] for item in KINDS)
CHANNELS = ("portal", "email")


# --- помощники файла ---------------------------------------------------------------------------------------------

def _rules():
    return importlib.import_module("apps.tasks.services.notify_rules")


def _tasks():
    return importlib.import_module("apps.tasks.services.tasks")


def _comments():
    return importlib.import_module("apps.tasks.services.comments")


def _catalog():
    from apps.notify.services import kinds as notify_kinds

    return notify_kinds.catalog()


def _kind(code: str):
    from apps.notify.services import kinds as notify_kinds

    return notify_kinds.get(code)


def _notes(user=None, kind: str | None = None):
    rows = support.model("notify.Notification").objects.filter(kind__startswith="tasks.")
    if user is not None:
        rows = rows.filter(user=getattr(user, "user", user))
    if kind is not None:
        rows = rows.filter(kind=kind)
    return rows


def _kinds_of(user) -> list[str]:
    return list(_notes(user=user).order_by("pk").values_list("kind", flat=True))


def _pair():
    """Постановщик — руководитель узла, исполнитель — его подчинённый: служба разрешает поставить задачу."""
    unit = support_org.make_tree({"Узел пары уведомлений": {}})["Узел пары уведомлений"]
    author = tasks_helpers.head_of(unit, full_name="Постановщик Уведомлений")
    assignee = tasks_helpers.staff_user(full_name="Исполнитель Уведомлений")
    support_org.make_member(assignee, unit)
    return author, assignee


def _chain_tree():
    """Два узла вложенно: руководители и заместители обоих — «вся цепочка вышестоящих» исполнителя."""
    units = support_org.make_tree({"Отдел уведомлений": {"Группа уведомлений": {}}})
    top, nested = units["Отдел уведомлений"], units["Группа уведомлений"]
    return {
        "top": top,
        "nested": nested,
        "head_top": tasks_helpers.head_of(top, full_name="Руководитель Отдела"),
        "deputy_top": tasks_helpers.deputy_of(top, full_name="Заместитель Отдела"),
        "head_nested": tasks_helpers.head_of(nested, full_name="Руководитель Группы"),
        "deputy_nested": tasks_helpers.deputy_of(nested, full_name="Заместитель Группы"),
    }


# --- 9.1: виды уведомлений -------------------------------------------------------------------------------------

def test_eight_kinds_titles_orders_channels_and_external_text():
    """FR-691, NFR-714 (CONTRACT-009, 9.1): в каталоге восемь видов «Задачи» с кодами `tasks.*`, названиями,
    `order` 210–217 подряд, каналами по умолчанию «портал» и «почта», постоянным внешним текстом; подписок на шину
    событий у среза нет, `still_relevant` — правило `notify_rules`, вид доступен сотруднику с `tasks.use`."""
    catalog = _catalog()
    module_kinds = [kind for kind in catalog if kind.module == MODULE]
    assert [kind.code for kind in module_kinds] == list(CODES), (
        f"виды задач в каталоге: {[kind.code for kind in module_kinds]}")
    assert [kind.order for kind in module_kinds] == list(range(210, 218))

    previous_orders = [kind.order for kind in catalog if kind.order < 210]  # прежние модули до задач
    assert min(kind.order for kind in module_kinds) > max(previous_orders), "виды задач не после прежних модулей"
    assert min(kind.order for kind in module_kinds) < max(
        kind.order for kind in catalog if kind.module == "Поручения"), "поручения должны идти после задач"

    user = tasks_helpers.staff_user(full_name="Читатель Видов")
    for code, title, order, external in KINDS:
        kind = _kind(code)
        assert kind.title == title, code
        assert kind.order == order, code
        assert tuple(kind.default_channels) == CHANNELS, code
        assert kind.external_text == external, code
        assert tuple(kind.events) == (), f"{code}: у среза не должно быть подписок на шину"
        assert kind.available(user) is True, f"{code}: вид закрыт сотруднику с tasks.use"

    rules = _rules()
    still_relevant = getattr(rules, "still_relevant", None)
    assert callable(still_relevant), "у notify_rules нет still_relevant"
    for kind in module_kinds:
        assert kind.still_relevant is still_relevant, f"{kind.code}: проверка перед письмом не из notify_rules"


# --- 9.2: получатели по видам -----------------------------------------------------------------------------------

def test_assigned_goes_to_assignee_and_coexecutors_not_author():
    """FR-691 (CONTRACT-009, 9.2): «Назначена задача» — исполнителю и соисполнителям, автору — нет; наблюдателю —
    нет; у каждого получателя ровно одно уведомление вида `tasks.assigned`."""
    author, assignee = _pair()
    coexecutor = tasks_helpers.staff_user(full_name="Соисполнитель Назначения")
    observer = tasks_helpers.staff_user(full_name="Наблюдатель Назначения")
    task = tasks_helpers.make_task(author=author, assignee=assignee, deadline=None, title="Назначение")
    tasks_helpers.add_member(task, coexecutor)
    tasks_helpers.add_member(task, observer, role="observer")

    got = _rules().recipients(task, "assigned")

    assert got == {assignee.pk: "tasks.assigned", coexecutor.pk: "tasks.assigned"}, f"получатели: {got}"
    assert author.pk not in got and observer.pk not in got


def test_due_soon_due_and_overdue_recipients():
    """FR-691 (CONTRACT-009, 9.2): «скоро» и «срок наступил» — исполнителю и соисполнителям; «просрочена» — им же и
    постановщику; наблюдатель не получает ни одного из трёх."""
    author, assignee = _pair()
    coexecutor = tasks_helpers.staff_user(full_name="Соисполнитель Сроков")
    observer = tasks_helpers.staff_user(full_name="Наблюдатель Сроков")
    task = tasks_helpers.make_task(author=author, assignee=assignee, deadline=None)
    tasks_helpers.add_member(task, coexecutor)
    tasks_helpers.add_member(task, observer, role="observer")
    rules = _rules()

    for event, kind in (("due_soon", "tasks.due_soon"), ("due", "tasks.due")):
        got = rules.recipients(task, event)
        assert got == {assignee.pk: kind, coexecutor.pk: kind}, f"{event}: {got}"
        assert author.pk not in got

    overdue = rules.recipients(task, "overdue")
    assert overdue == {assignee.pk: "tasks.overdue", coexecutor.pk: "tasks.overdue", author.pk: "tasks.overdue"}
    assert observer.pk not in overdue


def test_subordinate_overdue_goes_to_heads_and_deputies_of_whole_chain():
    """FR-691 (CONTRACT-009, 9.2): «Задача подчинённого просрочена» — руководителям и заместителям **всей цепочки**
    вышестоящих узлов исполнителя (оба узла дерева), самому исполнителю и постановщику — нет."""
    cast = _chain_tree()
    author = tasks_helpers.staff_user(full_name="Постановщик Цепочки")
    worker = tasks_helpers.staff_user(full_name="Исполнитель Цепочки")
    support_org.make_member(worker, cast["nested"])
    task = tasks_helpers.make_task(author=author, assignee=worker, deadline=None)

    got = _rules().recipients(task, "subordinate_overdue")

    managers = {cast["head_top"].pk, cast["deputy_top"].pk, cast["head_nested"].pk, cast["deputy_nested"].pk}
    assert set(got) == managers, f"получатели цепочки: {got}"
    assert set(got.values()) == {"tasks.subordinate_overdue"}


def test_combined_roles_give_one_message_with_subordinate_overdue_priority():
    """FR-691, CONTRACT-009 9.2, К15: если сотрудник одновременно исполнитель и руководитель своего узла, он получает
    одно уведомление, и его вид — `tasks.subordinate_overdue` (приоритет выше `tasks.overdue`)."""
    unit = support_org.make_tree({"Свой узел": {}})["Свой узел"]
    chief = tasks_helpers.head_of(unit, full_name="Руководитель Исполнитель")
    author = tasks_helpers.staff_user(full_name="Постановщик Совмещения")
    task = tasks_helpers.make_task(author=author, assignee=chief, deadline=None)

    got = _rules().recipients(task, "overdue")

    assert got.get(chief.pk) == "tasks.subordinate_overdue", f"вид при совмещении: {got.get(chief.pk)!r}"
    assert list(got.values()).count("tasks.subordinate_overdue") == 1
    assert got.get(author.pk) == "tasks.overdue"


# --- 9.2: свои действия ----------------------------------------------------------------------------------------

def test_self_assignment_and_self_comment_create_no_notifications():
    """FR-691 (CONTRACT-009, 9.2): назначил себе — уведомления нет; собственный комментарий уведомлений не создаёт
    (другим участникам — создаёт). Просрочка постановщику по своей задаче — есть (проверяется ниже по видам)."""
    user = tasks_helpers.staff_user(full_name="Сам Себе Задачу")
    task = _tasks().create(user, title="Задача себе", assignee=user)
    assert not _notes(user=user).exists(), f"назначение себе дало уведомления: {_kinds_of(user)}"

    colleague = tasks_helpers.staff_user(full_name="Коллега Комментария")
    tasks_helpers.add_member(task, colleague)
    _comments().add(user, task, "Комментарий себе")
    assert not _notes(user=user).exists(), "свой комментарий дал уведомление автору"
    assert _kinds_of(colleague) == ["tasks.comment"], f"коллеге: {_kinds_of(colleague)}"


def test_comment_goes_to_every_participant_except_comment_author():
    """FR-691 (CONTRACT-009, 9.2): «Новый комментарий» — автору задачи, исполнителю, соисполнителям и наблюдателям,
    кроме автора комментария; посторонний не получает; на один комментарий — одно уведомление каждому."""
    author, assignee = _pair()
    coexecutor = tasks_helpers.staff_user(full_name="Соисполнитель Комментария")
    observer = tasks_helpers.staff_user(full_name="Наблюдатель Комментария")
    outsider = tasks_helpers.staff_user(full_name="Посторонний Комментария")
    task = tasks_helpers.make_task(author=author, assignee=assignee, deadline=None)
    tasks_helpers.add_member(task, coexecutor)
    tasks_helpers.add_member(task, observer, role="observer")

    _comments().add(coexecutor, task, "Смотрите сюда")

    assert set(_kinds_of(author)) == {"tasks.comment"}
    assert set(_kinds_of(assignee)) == {"tasks.comment"}
    assert set(_kinds_of(observer)) == {"tasks.comment"}
    assert _notes(user=coexecutor).count() == 0, "автору комментария ушло уведомление"
    assert _notes(user=outsider).count() == 0, "постороннему ушло уведомление"
    assert _notes(kind="tasks.comment").count() == 3


def test_reminder_kind_goes_to_the_person_who_set_it():
    """FR-691 (CONTRACT-009, 9.2): «Вы просили напомнить» получает сам поставивший ручное напоминание, даже если он
    исполнитель своей же задачи; другим участникам это уведомление не уходит."""
    author, assignee = _pair()
    task = tasks_helpers.make_task(author=author, assignee=assignee, deadline=date(2026, 11, 18))
    service = importlib.import_module("apps.tasks.services.reminders")
    reminder = service.set_manual(assignee, task, days=1)

    from apps.tasks.tasks import tasks_reminders

    tasks_reminders(now=reminder.moment + timedelta(minutes=1))

    assert _kinds_of(assignee) == ["tasks.reminder"], f"исполнителю: {_kinds_of(assignee)}"
    assert _notes(user=author).count() == 0, "постановщику ушло «Вы просили напомнить»"


# --- FR-692, NFR-714: внешний текст и письмо -------------------------------------------------------------------

def test_external_text_has_no_task_title_description_or_names():
    """FR-692, NFR-714: во внешний текст попадает только постоянная фраза вида — без названия, описания, ФИО и
    адреса задачи; для каждого из восьми видов внешний текст совпадает с разделом 9.1."""
    title_marker, description_marker = "Секретное название задачи", "Секретное описание задачи"
    author, assignee = _pair()
    task = _tasks().create(author, title=title_marker, description=description_marker, assignee=assignee)
    note = _notes(user=assignee, kind="tasks.assigned").get()
    from apps.notify.services import kinds as notify_kinds

    text = notify_kinds.external_text(_kind("tasks.assigned"), note.object_ref)
    assert text == "Вам назначена задача", f"внешний текст: {text!r}"
    for marker in (title_marker, description_marker, author.full_name, assignee.full_name):
        assert marker not in text, f"во внешний текст попало: {marker!r}"
    assert note.url == f"/tasks/{task.pk}/"


def test_email_waits_fifteen_minutes_and_has_link_to_card():
    """FR-692 (CONTRACT-009, 9.2): у вида каналы «портал» и «почта»; после назначения письмо ждёт отправки
    `created_at + 15 минут` (срок из настроек уведомлений), уведомление в портале ведёт на карточку задачи."""
    author, assignee = _pair()
    task = _tasks().create(author, title="Письмо о задаче", assignee=assignee)

    note = _notes(user=assignee, kind="tasks.assigned").get()
    settings_row = support.model("notify.NotifySettings").objects.get(pk=1)
    assert settings_row.email_delay_minutes == 15, "задержка письма по умолчанию — 15 минут"
    delivery = note.deliveries.get(channel="email")
    assert delivery.state == "waiting", f"письмо не ждёт отправки: {delivery.state!r}"
    assert delivery.due_at == note.created_at + timedelta(minutes=15), "срок письма не через 15 минут"
    assert note.url == f"/tasks/{task.pk}/"


def test_kind_available_to_staff_and_still_relevant_follows_task():
    """FR-691, FR-692: вид доступен сотруднику с правом `tasks.use`; `still_relevant` вида — правило задач:
    собственная задача проходит, удалённая — нет (для просрочки ещё и статус ≠ «Готово»)."""
    allowed = tasks_helpers.staff_user(full_name="С Правом Задач")
    kind = _kind("tasks.assigned")
    assert kind.available(allowed) is True, "вид закрыт сотруднику с tasks.use"

    author, assignee = _pair()
    task = tasks_helpers.make_task(author=author, assignee=assignee, deadline=None)
    rules = _rules()
    ref = f"tasks.task:{task.pk}"
    assert rules.still_relevant(assignee.pk, ref) is True
    _tasks().soft_delete(author, task)
    assert rules.still_relevant(assignee.pk, ref) is False, "удалённая задача осталась актуальной для письма"