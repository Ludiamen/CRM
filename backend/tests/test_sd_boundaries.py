"""T-3132: шина событий, точки расширения ядра и границы модулей (FR-292). Сценарии спеки — через шину и точки: срез 003
подключается к ядру и `org` только через `apps/core/events.py` и `apps/core/extensions.py` (CONTRACT-003 § 3.1–3.3, § 4,
6.13; дополнения 7 и 22 раздела 16). Имена кода среза 003 импортируются внутри тестов."""
import ast
import dataclasses
import importlib
import logging
import re
import secrets
from collections import defaultdict

import pytest
from django.db import transaction
from django.db.models import ProtectedError

from tests import factories, support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

POINTS_15 = ("menu_items", "role_sources", "role_usage", "audit_labels", "staff_directory", "card_sections",
             "day_marks", "home_notices", "stand_reset", "unit_usage", "file_purposes", "mail_renderers", "login_links",
             "notification_kinds", "top_bar_items")
SERVICEDESK_POINTS = ("menu_items", "unit_usage", "file_purposes", "mail_renderers", "login_links", "audit_labels",
                      "card_sections", "stand_reset", "home_notices", "notification_kinds")
CORE_MENU_TITLES = ["Сотрудники", "Роли и права", "Журнал событий", "Настройки портала", "Безопасность и политика"]
FOUR = ("servicedesk.ticket_created", "servicedesk.assignee_changed", "servicedesk.reply_received",
        "servicedesk.ticket_closed")
EVENT_KEYS = {"number", "queue_id", "assignee_before_id", "assignee_after_id"}


# --- помощники только этого файла -------------------------------------------------------------------

def _events():
    return importlib.import_module("apps.core.events")


def _svc(name: str):
    return importlib.import_module(f"apps.servicedesk.services.{name}")


def _role_names(prefix: str) -> list[str]:
    return list(model("core.Role").objects.filter(name__startswith=prefix).values_list("name", flat=True))


def _member(unit, *, mark: str = "", name: str | None = None):
    user = support.make_employee(full_name=name) if name else support.make_employee()
    org.make_member(user, unit, mark=mark)
    return user


def _is_docstring(node, parent) -> bool:
    body = getattr(parent, "body", None)
    return bool(body) and body[0] is node


def _imported_names(source: str, package: list[str], *, with_strings: bool = False) -> set[str]:
    """Абсолютные имена, которые файл импортирует (разбор `ast`, не поиск по тексту): `import a.b`, `from a.b import c`
    (имена `a.b` и `a.b.c`), относительные импорты, вызовы `import_module("…")`/`__import__("…")`; при
    `with_strings` — ещё строковые константы вне докстрингов (контракт 3.2, «границы модулей»: «нет строки»)."""
    tree = ast.parse(source)
    found: set[str] = set()
    docstrings = set()
    for parent in ast.walk(tree):
        if isinstance(parent, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and parent.body:
            first = parent.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                module = ".".join(base + (node.module.split(".") if node.module else []))
            else:
                module = node.module or ""
            found.add(module)
            found.update(f"{module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in ("import_module", "__import__") and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                found.add(node.args[0].value)
        elif with_strings and isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings:
            found.add(node.value)
    return found


def _sd_dependency(name: str) -> bool:
    return name == "apps.servicedesk" or name.startswith("apps.servicedesk.")


def _org_models_dependency(name: str) -> bool:
    return name == "apps.org.models" or name.startswith("apps.org.models.")


def _scan_tree(*parts: str, bad) -> list[str]:
    root = support.BACKEND_DIR.joinpath(*parts)
    files = sorted(root.rglob("*.py"))
    assert files, f"нет исходников в {root}"
    offenders = []
    for path in files:
        rel = path.relative_to(support.BACKEND_DIR).with_suffix("")
        package = list(rel.parts[:-1]) if rel.parts[-1] != "__init__" else list(rel.parts[:-1])
        names = _imported_names(path.read_text(encoding="utf-8"), package, with_strings=bad is _sd_dependency)
        hits = sorted(n for n in names if bad(n))
        if hits:
            offenders.append(f"{path.relative_to(support.BACKEND_DIR)}: {hits}")
    return offenders


def _menu_anchor(html: str, href: str):
    match = re.search(rf'<a\s+class="menu-item[^"]*"\s+href="{re.escape(href)}"[^>]*>(.*?)</a>', html, re.S)
    return match.group(1) if match else None


def _badge_of(anchor: str):
    match = re.search(r"<span[^>]*\bdata-menu-badge\b[^>]*>\s*(\d+)\s*</span>", anchor)
    return int(match.group(1)) if match else None


def _item(url: str, title: str, perms=("probe.never",), order: int = 20, **extra) -> dict:
    return {"permissions": tuple(perms), "url": url, "title": title, "icon": "icons/people.html", "order": order, **extra}


# --- FR-292: публикация и подписчики (CONTRACT-003 § 3.1) ---------------------------------------------

def test_publish_runs_handlers_only_after_commit(bus, django_capture_on_commit_callbacks):
    """FR-292: обработчик не вызывается, пока действие не зафиксировано, и вызывается как `handler(**data)` один раз после
    фиксации; до фиксации в `bus.calls` пусто."""
    events = _events()
    bus.listen("probe.event")
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with transaction.atomic():
            events.publish("probe.event", number=7, user_ids=[1, 2])
        assert bus.calls("probe.event") == [], "обработчик ушёл до фиксации"
    assert len(callbacks) == 1
    assert bus.calls("probe.event") == [{"number": 7, "user_ids": [1, 2]}]


def test_publish_rolled_back_transaction_calls_no_handler(bus, django_capture_on_commit_callbacks):
    """FR-292: действие откатилось — события нет: обратных вызовов фиксации не осталось, обработчик не вызван."""
    events = _events()
    bus.listen("probe.event")
    with django_capture_on_commit_callbacks(execute=True) as callbacks:
        with pytest.raises(RuntimeError):
            with transaction.atomic():
                events.publish("probe.event", number=1)
                raise RuntimeError("действие не удалось")
    assert callbacks == []
    assert bus.calls("probe.event") == []


def test_publish_without_subscribers_does_nothing(bus, django_capture_on_commit_callbacks):
    """FR-292: без подписчиков `publish` ничего не регистрирует и не падает; заодно `subscribe` повтор игнорирует,
    `subscribers` отдаёт копию, `unsubscribe` повторно безвреден, `empty()` возвращает прежние подписки."""
    events = _events()
    with django_capture_on_commit_callbacks() as callbacks:
        events.publish("probe.nobody", anything=1)
    assert callbacks == []
    assert events.subscribers("probe.nobody") == []

    def handler(**data):
        pass

    events.subscribe("probe.nobody", handler)
    events.subscribe("probe.nobody", handler)
    assert events.subscribers("probe.nobody") == [handler], "та же функция второй раз игнорируется"
    events.subscribers("probe.nobody").clear()
    assert events.subscribers("probe.nobody") == [handler], "subscribers отдаёт копию"
    with events.empty():
        assert events.subscribers("probe.nobody") == []
    assert events.subscribers("probe.nobody") == [handler], "прежние подписки возвращаются при выходе"
    events.unsubscribe("probe.nobody", handler)
    events.unsubscribe("probe.nobody", handler)
    assert events.subscribers("probe.nobody") == []


def test_handler_error_is_logged_and_does_not_roll_back_action(bus, caplog, django_capture_on_commit_callbacks):
    """FR-292: исключение обработчика не откатывает действие, опубликовавшее событие; запись об ошибке — в логе
    (уровня ERROR); записи, сделанные упавшим обработчиком, откатываются."""
    events = _events()
    action, own = f"act-{secrets.token_hex(3)}", f"hnd-{secrets.token_hex(3)}"

    def failing(**data):
        factories.make_role(own)
        raise RuntimeError("сбой подписчика")

    events.subscribe("probe.event", failing)
    with caplog.at_level(logging.ERROR):
        with django_capture_on_commit_callbacks(execute=True):
            with transaction.atomic():
                factories.make_role(action)
                events.publish("probe.event")
    assert _role_names(action) == [action], "действие, опубликовавшее событие, осталось"
    assert _role_names(own) == [], "записи упавшего обработчика откатываются"
    assert any(record.levelno >= logging.ERROR for record in caplog.records), "в логе нет записи об ошибке"


def test_handler_error_does_not_block_other_handlers(bus, caplog, django_capture_on_commit_callbacks):
    """FR-292: упавший первый подписчик не мешает второму и третьему; все идут в порядке подписки."""
    events = _events()
    order = []

    def first(**data):
        order.append("first")
        raise RuntimeError("сбой первого")

    def second(**data):
        order.append(("second", data))

    def third(**data):
        order.append("third")

    for handler in (first, second, third):
        events.subscribe("probe.event", handler)
    with caplog.at_level(logging.ERROR):
        with django_capture_on_commit_callbacks(execute=True):
            events.publish("probe.event", n=5)
    assert order == ["first", ("second", {"n": 5}), "third"]


def test_each_handler_runs_in_own_transaction(bus, caplog, django_capture_on_commit_callbacks):
    """FR-292: у каждого обработчика своя транзакция: запись первого откатывается из-за его ошибки, запись второго
    остаётся; запись успешного обработчика не откатывается ошибкой следующего."""
    events = _events()
    names = {key: f"{key}-{secrets.token_hex(3)}" for key in ("a", "b", "c")}

    def writes_and_fails(**data):
        factories.make_role(names["a"])
        raise RuntimeError("сбой")

    def writes(**data):
        factories.make_role(names["b"])

    def writes_then_fails(**data):
        factories.make_role(names["c"])
        raise RuntimeError("сбой после записи")

    for handler in (writes_and_fails, writes, writes_then_fails):
        events.subscribe("probe.event", handler)
    with caplog.at_level(logging.ERROR):
        with django_capture_on_commit_callbacks(execute=True):
            events.publish("probe.event")
    assert _role_names(names["a"]) == [], "запись упавшего первого обработчика осталась"
    assert _role_names(names["b"]) == [names["b"]], "запись второго откатилась вместе с чужим сбоем"
    assert _role_names(names["c"]) == [], "запись упавшего третьего обработчика осталась"


# --- FR-292: событие access.changed (§ 3.1, § 4) --------------------------------------------------------

def test_forget_users_publishes_access_changed_with_user_ids(bus, django_capture_on_commit_callbacks):
    """FR-292: `forget_users` публикует `access.changed` с отсортированным списком без повторов; пустой список и
    `publish=False` события не дают."""
    from apps.core.services import permissions

    bus.listen("access.changed")
    first, second = support.make_employee(), support.make_employee()
    with django_capture_on_commit_callbacks(execute=True):
        permissions.forget_users([second.pk, first.pk, second.pk])
    assert bus.calls("access.changed") == [{"user_ids": sorted({first.pk, second.pk})}]
    with django_capture_on_commit_callbacks(execute=True):
        permissions.forget_users([])
        permissions.forget_users([first.pk], publish=False)
    assert len(bus.calls("access.changed")) == 1, "пустой список и publish=False события не публикуют"


def test_forget_all_publishes_access_changed_with_none(bus, django_capture_on_commit_callbacks):
    """FR-292: `forget_all` публикует `access.changed` с `user_ids=None` («все»), один раз."""
    from apps.core.services import permissions

    bus.listen("access.changed")
    support.make_employee()
    with django_capture_on_commit_callbacks(execute=True):
        permissions.forget_all()
    assert bus.calls("access.changed") == [{"user_ids": None}]


def test_access_changed_handler_sees_new_permissions_after_cache_reset(bus, django_capture_on_commit_callbacks):
    """FR-292: подписчик `access.changed` читает права уже после сброса кэша: событие публикуется после регистрации
    сброса (обратные вызовы фиксации идут в порядке регистрации)."""
    from apps.core.services import permissions

    events = _events()
    user = support.make_employee()
    role = factories.make_role(permissions=())
    user.roles.add(role)
    assert permissions.permissions_of(user) == frozenset(), "кэш прав прогрет пустым набором"
    seen = []

    def handler(user_ids=None, **data):
        seen.append(permissions.permissions_of(user))

    events.subscribe("access.changed", handler)
    role.permissions.add(model("core.Permission").objects.get(code="audit.view"))
    assert permissions.permissions_of(user) == frozenset(), "до сброса кэш прежний"
    with django_capture_on_commit_callbacks(execute=True):
        permissions.forget_users([user.pk])
    assert len(seen) == 1
    assert "audit.view" in seen[0], "подписчик увидел прежний кэш: событие ушло раньше сброса"


def test_set_marks_publishes_access_changed(bus, django_capture_on_commit_callbacks):
    """FR-292: `set_marks` публикует `access.changed` с теми, у кого отметка появилась или исчезла; повтор без изменений
    события не даёт (решение Opus A4). Обмен головы и заместителя одним вызовом запрещён правилом `head_and_deputy` среза
    002 (CONTRACT-002 § 4: сменить отметку можно только двумя вызовами), поэтому здесь не проверяется."""
    from apps.org.services import membership

    bus.listen("access.changed")
    admin = support.make_admin()
    unit = org.make_unit()
    lost = _member(unit, mark="head")
    gained_head, gained_deputy = _member(unit), _member(unit)
    with django_capture_on_commit_callbacks(execute=True):
        membership.set_marks(unit, heads=[gained_head], deputies=[gained_deputy], actor=admin)
    assert bus.calls("access.changed") == [{"user_ids": sorted([lost.pk, gained_head.pk, gained_deputy.pk])}]
    with django_capture_on_commit_callbacks(execute=True):
        membership.set_marks(unit, heads=[gained_head], deputies=[gained_deputy], actor=admin)
    assert len(bus.calls("access.changed")) == 1, "повтор без изменений не меняет состав очередей"


def test_move_unit_publishes_access_changed_with_former_upper_heads(bus, django_capture_on_commit_callbacks):
    """FR-292: `move_unit` публикует одно `access.changed`: участники поддерева и руководители прежних вышестоящих узлов,
    у которых нет отметки в вышестоящих узлах нового места; перенос к тому же родителю — без события (решение Opus A5)."""
    from apps.org.services import structure

    bus.listen("access.changed")
    admin = support.make_admin()
    root = org.root_unit()
    upper = org.make_unit("Верхний узел", parent=root)
    middle = org.make_unit("Средний узел", parent=upper)
    moved = org.make_unit("Переносимый узел", parent=middle)
    new_place = org.make_unit("Новое место", parent=root)
    still_head = _member(upper, mark="head")
    org.make_member(still_head, new_place, mark="deputy")
    former_head = _member(middle, mark="head")
    inside = _member(moved)
    with django_capture_on_commit_callbacks(execute=True):
        structure.move_unit(moved, new_place, actor=admin)
    assert bus.calls("access.changed") == [{"user_ids": sorted([inside.pk, former_head.pk])}], (
        "ждали участника поддерева и прежнего руководителя; руководитель, оставшийся над новым местом, не входит")
    with django_capture_on_commit_callbacks(execute=True):
        structure.move_unit(moved, new_place, actor=admin)
    assert len(bus.calls("access.changed")) == 1, "перенос к тому же родителю событие не публикует"


# --- FR-292: события servicedesk.* (§ 3.1, 6.13, дополнения 7 и 22) ---------------------------------------

def test_servicedesk_events_carry_ticket_number_queue_and_assignees(bus, django_capture_on_commit_callbacks):
    """FR-292, FR-313: четыре константы `events`; у каждого события прежние ключи данных (`number`, `queue_id`,
    `assignee_before_id`, `assignee_after_id`) и новые по событию (CONTRACT-004 § 4.2): `actor_id` и `channel` у
    `ticket_created`; `actor_id` у `assignee_changed` и `ticket_closed`; `actor_id` (всегда `None`), `via`, `author_kind`,
    `entry_id` у `reply_received`; у новой заявки `assignee_before_id` — `None`."""
    sd_events = _svc("events")
    assert (sd_events.TICKET_CREATED, sd_events.ASSIGNEE_CHANGED, sd_events.REPLY_RECEIVED, sd_events.TICKET_CLOSED) == FOUR
    bus.listen(*FOUR)
    queue = sd.make_queue()
    assignee, other = _member(queue.unit), _member(queue.unit)
    ticket = sd.make_ticket(queue=queue, kind="in_progress", assignee=assignee)
    base = {"number": ticket.number, "queue_id": ticket.queue_id}
    with django_capture_on_commit_callbacks(execute=True):
        sd_events.ticket_created(ticket, actor_id=other.pk, channel="staff")
        sd_events.assignee_changed(ticket, before_id=assignee.pk, after_id=other.pk, actor_id=other.pk)
        sd_events.reply_received(ticket, via="appended", author_kind="requester", entry_id=4711)
        sd_events.ticket_closed(ticket, actor_id=assignee.pk)
    assert bus.calls(FOUR[0]) == [{**base, "assignee_before_id": None, "assignee_after_id": assignee.pk,
                                   "actor_id": other.pk, "channel": "staff"}]
    assert bus.calls(FOUR[1]) == [{**base, "assignee_before_id": assignee.pk, "assignee_after_id": other.pk,
                                   "actor_id": other.pk}]
    assert bus.calls(FOUR[2]) == [{**base, "assignee_before_id": assignee.pk, "assignee_after_id": assignee.pk,
                                   "actor_id": None, "via": "appended", "author_kind": "requester", "entry_id": 4711}]
    assert bus.calls(FOUR[3]) == [{**base, "assignee_before_id": assignee.pk, "assignee_after_id": assignee.pk,
                                   "actor_id": assignee.pk}]
    new_keys = {FOUR[0]: {"actor_id", "channel"}, FOUR[1]: {"actor_id"},
                FOUR[2]: {"actor_id", "via", "author_kind", "entry_id"}, FOUR[3]: {"actor_id"}}
    assert all(set(data) == EVENT_KEYS | new_keys[name] for name, data in bus.all())
    assert base["queue_id"] == queue.unit_id


def test_four_servicedesk_events_are_published_by_ticket_services(bus_spy, django_capture_on_commit_callbacks):
    """FR-292: создание, назначение, письмо заявителя и закрытие публикуют ровно по одному своему событию; при создании с
    ответственным по умолчанию в шину уходит только `ticket_created` (дополнение 7), `assignee_changed` — при назначении."""
    bus_spy.listen(*FOUR)
    queue = sd.make_queue()
    sd.configure_servicedesk(domains=["corp.test"], default_queue=queue)
    first, second = _member(queue.unit), _member(queue.unit)
    category = sd.make_category(queue=queue, default_assignee=first)
    tickets, assignment, closing = _svc("tickets"), _svc("assignment"), _svc("closing")
    email = factories.new_email("req").lower()
    with django_capture_on_commit_callbacks(execute=True):
        created = tickets.create(channel=tickets.MAIL, subject="Не печатает принтер", text="Принтер не печатает",
                                 requester_email=email, category=category, inbound_id=sd.make_inbound().pk)
    ticket = model("servicedesk.Ticket").objects.get(pk=created.ticket.pk)
    base = {"number": ticket.number, "queue_id": queue.unit_id}
    assert bus_spy.calls(FOUR[0]) == [{**base, "assignee_before_id": None, "assignee_after_id": first.pk,
                                       "actor_id": None, "channel": "mail"}]
    assert bus_spy.calls(FOUR[1]) == [], "при создании шина получает только ticket_created (дополнение 7)"

    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.assign(ticket, second, actor=second) is True
    assert bus_spy.calls(FOUR[1]) == [{**base, "assignee_before_id": first.pk, "assignee_after_id": second.pk,
                                       "actor_id": second.pk}]

    ticket.refresh_from_db()
    with django_capture_on_commit_callbacks(execute=True):
        tickets.add_incoming(ticket, author_email=email, text="Добавляю подробности")
    entry = model("servicedesk.TicketEntry").objects.get(ticket=ticket, kind="incoming", text="Добавляю подробности")
    assert bus_spy.calls(FOUR[2]) == [{**base, "assignee_before_id": second.pk, "assignee_after_id": second.pk,
                                       "actor_id": None, "via": "appended", "author_kind": "requester",
                                       "entry_id": entry.pk}]

    ticket.refresh_from_db()
    closed = model("servicedesk.Status").objects.get(kind="closed", is_default=True)
    with django_capture_on_commit_callbacks(execute=True):
        closing.close(ticket, closed, "Заменили картридж", actor=second)
    assert bus_spy.calls(FOUR[3]) == [{**base, "assignee_before_id": second.pk, "assignee_after_id": second.pk,
                                       "actor_id": second.pk}]
    assert len(bus_spy.calls(FOUR[0])) == 1 and len(bus_spy.calls(FOUR[1])) == 1 and len(bus_spy.calls(FOUR[2])) == 1


# --- FR-292: точки расширения и меню (§ 3.2) ------------------------------------------------------------

def test_extension_points_include_unit_usage_file_purposes_mail_renderers_login_links():
    """FR-292: `POINTS` — пятнадцать имён в порядке контракта; `org` — только в девяти первых, `servicedesk` — в своих десяти
    точках (девять прежних и `notification_kinds`) функциями `apps.servicedesk…`; зарегистрированное отдаёт то, что описано
    в контракте, в том числе ровно четыре вида уведомлений с кодами CONTRACT-004 § 3.2."""
    from apps.core import extensions

    assert tuple(extensions.POINTS) == POINTS_15

    def owned(point, prefix):
        return [f for f in extensions.registered(point) if getattr(f, "__module__", "").startswith(prefix)]

    for point in POINTS_15[:9]:
        assert owned(point, "apps.org"), f"org не зарегистрирован в точке {point}"
    for point in POINTS_15[9:]:
        assert not owned(point, "apps.org"), f"org не должен регистрироваться в точке {point}"
    for point in POINTS_15:
        if point in SERVICEDESK_POINTS:
            assert owned(point, "apps.servicedesk"), f"servicedesk не зарегистрирован в точке {point}"
        else:
            assert not owned(point, "apps.servicedesk"), f"servicedesk не должен регистрироваться в точке {point}"

    def answers(point, *args):
        return [item for f in owned(point, "apps.servicedesk") for item in f(*args)]

    purposes = answers("file_purposes")
    assert [p.purpose for p in purposes] == ["attachment"]
    assert isinstance(purposes[0], extensions.FilePurpose)
    assert {f.name for f in dataclasses.fields(extensions.FilePurpose)} == {"purpose", "still_waiting", "clean", "found"}
    attachments = _svc("attachments")
    assert (purposes[0].still_waiting, purposes[0].clean, purposes[0].found) == (
        attachments.still_waiting, attachments.on_clean, attachments.on_found)

    renderers = answers("mail_renderers")
    assert [r.prefix for r in renderers] == ["ticket."]
    assert isinstance(renderers[0], extensions.MailRenderer)
    assert {f.name for f in dataclasses.fields(extensions.MailRenderer)} == {"prefix", "render"}
    assert renderers[0].render is _svc("letters").render
    assert tuple(extensions.Rendered._fields) == ("body", "attachments")

    assert answers("login_links") == [{"url": "/request/", "title": "Подать заявку в ИТ-отдел"}]

    kinds = answers("notification_kinds")
    assert len(kinds) == 4 and all(isinstance(kind, extensions.NotificationKind) for kind in kinds)
    assert sorted(kind.code for kind in kinds) == sorted((
        "servicedesk.new_in_queue", "servicedesk.assigned", "servicedesk.requester_replied", "servicedesk.reply_failed"))

    menu = {item["title"]: item for item in answers("menu_items")}
    assert set(menu) == {"Заявки", "Сервис-деск"}
    assert (menu["Заявки"]["url"], menu["Заявки"]["order"], tuple(menu["Заявки"]["permissions"])) == (
        "/tickets/", 5, ("servicedesk.all",))
    assert callable(menu["Заявки"]["visible"]) and callable(menu["Заявки"]["badge"])
    assert (menu["Сервис-деск"]["url"], menu["Сервис-деск"]["order"], tuple(menu["Сервис-деск"]["permissions"])) == (
        "/servicedesk/", 65, ("servicedesk.manage",))

    plain, with_tickets, queue_only = org.make_unit(), org.make_unit(), org.make_unit()
    sd.make_queue(with_tickets)
    sd.make_ticket(queue=with_tickets)
    sd.make_queue(queue_only)
    reasons = lambda unit: [r for f in owned("unit_usage", "apps.servicedesk") if (r := f(unit.pk))]  # noqa: E731
    assert reasons(plain) == []
    assert reasons(with_tickets)[0] == "к узлу привязаны заявки сервис-деска"
    assert reasons(queue_only) == ["узел — очередь сервис-деска: сначала снимите отметку"]


def test_menu_item_visible_shows_item_without_permissions():
    """FR-292: пункт с `visible` виден, если есть одно из прав ИЛИ `visible(user)` истинна; `visible` ложна, а права есть —
    пункт виден; `visible` ложна и прав нет — нет. На настоящей странице «Заявки» виден участнику очереди без прав среза,
    «Сервис-деск» ему не виден."""
    from apps.core import extensions
    from apps.core.services import permissions

    nobody = support.make_employee()
    holder = support.make_with_permissions("audit.view")
    with extensions.empty():
        extensions.register("menu_items", lambda: [
            _item("/probe-visible/", "Виден функцией", visible=lambda user: True),
            _item("/probe-hidden/", "Скрыт функцией", visible=lambda user: False),
            _item("/probe-rights/", "Виден правом", perms=("audit.view",), visible=lambda user: False),
        ])
        assert [item["title"] for item in permissions.menu_for(nobody)] == ["Виден функцией"]
        titles = {item["title"] for item in permissions.menu_for(holder)}
        assert {"Виден правом", "Виден функцией", "Журнал событий"} <= titles
        assert "Скрыт функцией" not in titles

    queue = sd.make_queue()
    member = _member(queue.unit)
    assert permissions.permissions_of(member) == frozenset(), "у участника очереди нет прав среза"
    html = support.logged_in(member).get("/").content.decode()
    assert _menu_anchor(html, "/tickets/") is not None, "«Заявки» виден участнику очереди по visible"
    assert "Заявки" in _menu_anchor(html, "/tickets/")
    assert _menu_anchor(html, "/servicedesk/") is None
    stranger = support.logged_in(support.make_employee()).get("/").content.decode()
    assert _menu_anchor(stranger, "/tickets/") is None


def test_menu_item_badge_called_only_for_visible_item_once_per_request(no_extensions):
    """FR-292: `badge` зовётся только у видимого пункта и один раз за запрос, `visible` — не больше одного; число видно
    в `span[data-menu-badge]` только при значении больше нуля, при `0` и `None` элемента нет."""
    from apps.core import extensions
    from apps.core.services import permissions

    counts = defaultdict(int)

    def counted(key, value):
        def func(user):
            counts[key] += 1
            return value
        return func

    extensions.register("menu_items", lambda: [
        _item("/probe-v/", "Пункт V", order=21, visible=counted("v.visible", True), badge=counted("v.badge", 3)),
        _item("/probe-h/", "Пункт H", order=22, visible=counted("h.visible", False), badge=counted("h.badge", 9)),
        _item("/probe-p/", "Пункт P", order=23, perms=("audit.view",), badge=counted("p.badge", 4)),
        _item("/probe-z/", "Пункт Z", order=24, visible=counted("z.visible", True), badge=counted("z.badge", 0)),
        _item("/probe-n/", "Пункт N", order=25, visible=counted("n.visible", True), badge=counted("n.badge", None)),
    ])
    user = support.make_with_permissions("audit.view")
    response = support.logged_in(user).get("/")
    assert response.status_code == 200
    assert counts["h.badge"] == 0, "badge скрытого пункта звать нельзя"
    for key in ("v.badge", "p.badge", "z.badge", "n.badge"):
        assert counts[key] == 1, f"{key}: ждали один вызов за запрос, было {counts[key]}"
    assert counts["v.visible"] == 1 and counts["h.visible"] <= 1
    html = response.content.decode()
    assert _menu_anchor(html, "/probe-h/") is None
    assert _badge_of(_menu_anchor(html, "/probe-v/")) == 3
    assert _badge_of(_menu_anchor(html, "/probe-p/")) == 4
    for href in ("/probe-z/", "/probe-n/"):
        anchor = _menu_anchor(html, href)
        assert anchor is not None, f"пункт {href} должен быть виден"
        assert "data-menu-badge" not in anchor, f"у {href} счётчика быть не должно (0 и None не выводятся)"
    counts.clear()
    entries = {item["url"]: item for item in permissions.menu_for(user)}
    assert entries["/probe-v/"]["badge"] == 3 and entries["/probe-z/"]["badge"] == 0 and entries["/probe-n/"]["badge"] is None
    assert "/probe-h/" not in entries
    assert counts["h.badge"] == 0 and counts["v.badge"] == 1 and counts["v.visible"] == 1


def test_menu_item_without_visible_and_badge_behaves_as_before(no_extensions):
    """FR-292: пункт без `visible` и `badge` виден только по праву и отдаётся ровно с ключами `url`, `title`, `icon`, `order`
    (без `badge`); ключ `badge` есть только у пункта с функцией `badge`, в том числе со значением `None`; разметка меню без
    `badge` прежняя."""
    from apps.core import extensions
    from apps.core.services import permissions

    extensions.register("menu_items", lambda: [
        _item("/probe-old/", "Прежний пункт", perms=("audit.view",), order=21),
        _item("/probe-new/", "Новый пункт", perms=("audit.view",), order=22, badge=lambda user: None),
        _item("/probe-locked/", "Закрытый пункт", order=23),
    ])
    holder = support.make_with_permissions("audit.view")
    menu = {item["url"]: item for item in permissions.menu_for(holder)}
    assert set(menu["/probe-old/"]) == {"url", "title", "icon", "order"}
    assert "badge" in menu["/probe-new/"] and menu["/probe-new/"]["badge"] is None
    assert "/probe-locked/" not in menu
    assert not permissions.menu_for(support.make_employee())
    html = support.logged_in(holder).get("/").content.decode()
    assert _menu_anchor(html, "/probe-old/") is not None and _menu_anchor(html, "/probe-new/") is not None
    assert "data-menu-badge" not in html
    assert _menu_anchor(html, "/probe-locked/") is None


# --- FR-292: границы модулей ----------------------------------------------------------------------------

def test_core_and_org_do_not_import_servicedesk():
    """FR-292: ни один файл `apps/core/**` и `apps/org/**` не импортирует `apps.servicedesk` (разбор импортов `ast`, а также
    `import_module` и строки вне докстрингов); сам разбор находит нарушения на образцах."""
    for sample_source in ("from apps.servicedesk.services import x", "import apps.servicedesk", "from apps import servicedesk",
                          "import importlib\nimportlib.import_module('apps.servicedesk.x')", "x = 'apps.servicedesk.y'"):
        names = _imported_names(sample_source, ["apps", "core"], with_strings=True)
        assert any(_sd_dependency(n) for n in names), f"разбор не нашёл зависимость в образце: {sample_source}"
    for clean_source in ('"""apps.servicedesk в докстринге"""\n# apps.servicedesk в комментарии\nimport os',
                         "from apps.core import extensions"):
        names = _imported_names(clean_source, ["apps", "core"], with_strings=True)
        assert not any(_sd_dependency(n) for n in names), f"ложное срабатывание: {clean_source}"
    assert _scan_tree("apps", "core", bad=_sd_dependency) == []
    assert _scan_tree("apps", "org", bad=_sd_dependency) == []


def test_servicedesk_does_not_import_org_models():
    """FR-292: `apps/servicedesk/**` не импортирует модели `org` (`from apps.org.models`, `import apps.org.models`,
    `from apps.org import models`); службы `apps.org.services` разрешены; сам разбор находит нарушения на образцах."""
    package = ["apps", "servicedesk", "services"]
    for sample_source in ("from apps.org.models import Unit", "import apps.org.models", "from apps.org import models",
                          "from apps.org.models.unit import Unit", "from ...org.models import Unit"):
        names = _imported_names(sample_source, package)
        assert any(_org_models_dependency(n) for n in names), f"разбор не нашёл зависимость в образце: {sample_source}"
    for clean_source in ("from apps.org.services import structure", "from apps.org import services",
                         "from apps.org.services.refs import UnitRef", "from ..models import Ticket"):
        names = _imported_names(clean_source, package)
        assert not any(_org_models_dependency(n) for n in names), f"ложное срабатывание: {clean_source}"
    assert _scan_tree("apps", "servicedesk", bad=_org_models_dependency) == []


def _check_core_and_org_slice_002(admin, monkeypatch, *, org_present: bool) -> None:
    """Поведение ядра и `org` без регистраций `servicedesk` (срез 002): меню, страница входа, удаление узла, проверка
    файла вложения, письма с префиксом `ticket.`."""
    from apps.core import tasks as core_tasks
    from apps.core.services import permissions
    from apps.integrations.mail import services as mail_services
    from apps.org.services import structure

    menu = permissions.menu_for(admin)
    assert all(set(item) == {"url", "title", "icon", "order"} for item in menu), "ключа badge быть не должно"
    urls = [item["url"] for item in menu]
    assert not [u for u in urls if u.startswith(("/tickets/", "/servicedesk/"))]
    assert bool([u for u in urls if u.startswith(("/structure/", "/calendar/"))]) is org_present
    if not org_present:
        assert [item["title"] for item in menu] == CORE_MENU_TITLES

    login = support.make_client().get("/login/")
    assert login.status_code == 200 and "data-login-link" not in login.content.decode()

    plain = org.make_unit()
    structure.delete_unit(plain, actor=admin)
    assert not model("org.Unit").objects.filter(pk=plain.pk).exists(), "пустой узел без заявок удаляется как в срезе 002"
    marked = sd.make_queue(org.make_unit())
    with pytest.raises(ProtectedError):
        structure.delete_unit(marked.unit, actor=admin)

    owner = support.make_employee()
    stored = model("core.StoredFile").objects.create(
        purpose="attachment", owner=owner, size=1, sha256="0" * 64, content_type="application/octet-stream", status="pending")
    ticket = sd.make_ticket(queue=marked)
    entry = sd.make_entry(ticket, "incoming")
    model("servicedesk.Attachment").objects.create(ticket=ticket, entry=entry, file=stored, name="a.bin", size=1)
    scans = sd.scan_clean(monkeypatch)
    core_tasks.scan_file(str(stored.pk))
    stored.refresh_from_db()
    assert scans == [] and stored.status == "pending", "без точки file_purposes назначение attachment ядро не знает"

    with pytest.raises(ValueError):
        mail_services.send_rendered("ticket.confirmation", factories.new_email("req"), subject="Тема", cc=[], reply_to="",
                                    message_id="", references="", auto_submitted="", related_ref="", attachments=[], context={})


def test_without_servicedesk_registrations_core_and_org_behave_as_slice_002(bus, monkeypatch):
    """FR-292: без регистраций и подписчиков `servicedesk` (реестры пусты, шина пуста) ядро и `org` ведут себя как в
    срезе 002: меню — пункты ядра (при `org` — и его пункты), без `badge`, ссылок на входе нет, узел удаляется, а у узла-очереди
    остаётся только защита `PROTECT`, назначение `attachment` ядро не знает, префикс `ticket.` отказывает `ValueError`."""
    from apps.core import extensions

    registered = {point: extensions.registered(point) for point in extensions.POINTS}
    admin = support.make_admin()
    with extensions.empty():
        _check_core_and_org_slice_002(admin, monkeypatch, org_present=False)
    with extensions.empty():
        for point, funcs in registered.items():
            for func in funcs:
                if not getattr(func, "__module__", "").startswith("apps.servicedesk"):
                    extensions.register(point, func)
        _check_core_and_org_slice_002(admin, monkeypatch, org_present=True)
