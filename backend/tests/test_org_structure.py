"""T-2101: дерево и страница «Структура» (FR-101…109, FR-112, FR-123, FR-150).

Сценарии 1, 4, 6 спеки SPEC-002. Имена кода среза 002 импортируются внутри тестов: сбор проходит до кода.
"""
import re
from html.parser import HTMLParser
from urllib.parse import quote

import pytest
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test.utils import CaptureQueriesContext

from tests import factories, support, support_org
from tests.support import model

pytestmark = pytest.mark.django_db

HX = support.HX
VIEW = ("staff.view",)
MANAGE = ("staff.view", "org.manage")


# --- помощники этого файла ------------------------------------------------------------------------

def structure():
    from apps.org.services import structure as module
    return module


def expect_code(code, func, *args, **kwargs):
    """Служба отказывает `OrgError` с нужным кодом; возвращает ошибку (текст — `str(error)`)."""
    from apps.org.services import OrgError

    with pytest.raises(OrgError) as raised:
        func(*args, **kwargs)
    assert raised.value.code == code, f"ожидали код {code!r}, получили {raised.value.code!r}"
    return raised.value


def admin():
    return support.make_with_permissions(*MANAGE, full_name="Админов Админ")


def viewer(**extra):
    return support.make_with_permissions(*VIEW, **extra)


def snapshot():
    """Состояние дерева: по узлам — родитель, путь, глубина, вид, название."""
    return list(model("org.Unit").objects.order_by("pk").values_list(
        "pk", "name", "parent_id", "path", "depth", "kind"))


def events(action, **filters):
    return list(model("core.AuditEvent").objects.filter(action=action, **filters).order_by("id"))


def unit_url(unit):
    return f"/structure/{unit.pk}/"


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.content = tag, attrs, parent, []

    def walk(self):
        for item in self.content:
            if isinstance(item, Node):
                yield item
                yield from item.walk()

    def text(self):
        parts = []

        def collect(node):
            for item in node.content:
                collect(item) if isinstance(item, Node) else parts.append(item)

        collect(self)
        return " ".join(" ".join(parts).split())

    def select(self, tag=None, cls=None, **want):
        """Потомки по тегу и атрибутам; `data_x_y=` -> `data-x-y`; `True` — атрибут есть, `False` — нет."""
        found = []
        for node in self.walk():
            if tag and node.tag != tag:
                continue
            if cls and cls not in node.attrs.get("class", "").split():
                continue
            ok = True
            for key, value in want.items():
                name = key.replace("_", "-")
                if value is True:
                    ok = name in node.attrs
                elif value is False:
                    ok = name not in node.attrs
                else:
                    ok = node.attrs.get(name) == str(value)
                if not ok:
                    break
            if ok:
                found.append(node)
        return found

    def inside(self, other):
        node = self.parent
        while node is not None:
            if node is other:
                return True
            node = node.parent
        return False


class _Parser(HTMLParser):
    VOID = {"input", "img", "br", "hr", "meta", "link", "area", "base", "col", "source", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {}, None)
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v or "") for k, v in attrs}, self.stack[-1])
        self.stack[-1].content.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, {k: (v or "") for k, v in attrs}, self.stack[-1])
        self.stack[-1].content.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].content.append(data)


def doc(response) -> Node:
    parser = _Parser()
    parser.feed(response.content.decode("utf-8"))
    return parser.root


def alert_text(response) -> str:
    alerts = doc(response).select(role="alert")
    assert alerts, "в ответе нет [role=alert]"
    return " ".join(a.text() for a in alerts)


def card_of(response) -> Node:
    cards = doc(response).select(data_unit_card=True)
    assert len(cards) == 1, f"карточек узла в ответе: {len(cards)}"
    return cards[0]


def member_ids(response) -> set:
    """Участники из раздела `members` карточки."""
    sections = doc(response).select(data_section="members")
    if not sections:  # при пустом поиске раздел может заменяться [data-empty-state="search"] (CONTRACT-002 § 9.1)
        return set()
    return {int(r.attrs["data-user-id"]) for r in sections[0].select(data_member=True)}


def person(full_name, position="Инженер", **extra):
    return support.make_employee(full_name=full_name, position=position, **extra)


def sqls_of(call) -> list:
    with CaptureQueriesContext(connection) as ctx:
        call()
    return [q["sql"] for q in ctx.captured_queries]


def assert_root_locked_before_writes(sqls):
    locks = [i for i, s in enumerate(sqls)
             if "FOR UPDATE" in s and '"org_unit"' in s and 'WHERE "org_unit"."is_root"' in s]  # CONTRACT-002, доп. 16
    writes = [i for i, s in enumerate(sqls) if re.match(r'\s*(INSERT INTO|UPDATE|DELETE FROM) "org_unit\w*"', s)]
    assert locks, "нет запроса FOR UPDATE по org_unit (замок строки корня)"
    assert writes, "в вызове нет записи в org_unit — тест не проверяет порядок"
    assert min(locks) < min(writes), "замок строки корня взят позже первой записи"


# --- модель и правила дерева -----------------------------------------------------------------------

def test_root_department_created_by_migration_without_members():
    """FR-103, FR-112 (сценарий 1.7): после установки один корневой отдел «ИТ-отдел» без участников; первый администратор в него не помещается."""
    Unit = model("org.Unit")
    assert Unit.objects.count() == 1
    root = Unit.objects.get()
    assert root.is_root and root.kind == "department" and root.name == "ИТ-отдел"
    assert root.parent is None and root.depth == 0 and root.path == f"/{root.pk}/"
    assert root.name_key == support_org.name_key("ИТ-отдел")
    assert structure().root() == root
    support.make_admin()
    assert not model("org.Membership").objects.exists()
    assert not root.memberships.exists()


def test_unit_kinds_department_under_department_team_under_any():
    """FR-101, FR-102 (сценарий 1.1–1.3): отдел только под отделом, команда под отделом или командой; нарушение — `kind_rules` с текстом спеки."""
    Unit = model("org.Unit")
    actor, root = support.make_admin(), support_org.root_unit()
    net = structure().create_unit(kind="department", name="Сеть", parent=root, actor=actor)
    team = structure().create_unit(kind="team", name="Группа филиала", parent=net, actor=actor)
    sub_team = structure().create_unit(kind="team", name="Дежурные", parent=team, actor=actor)
    assert (net.kind, team.kind, sub_team.kind) == ("department", "team", "team")
    assert (net.parent, team.parent, sub_team.parent) == (root, net, team)
    before = snapshot()
    error = expect_code("kind_rules", structure().create_unit, kind="department", name="Отдел", parent=team, actor=actor)
    assert "отдел подчиняется только отделу" in str(error).lower()
    expect_code("kind_rules", structure().create_unit, kind="department", name="Отдел2", parent=sub_team, actor=actor)
    expect_code("kind_rules", structure().create_unit, kind="team", name="Корневая", parent=None, actor=actor)
    expect_code("kind_rules", structure().create_unit, kind="department", name="Корневой", parent=None, actor=actor)
    assert snapshot() == before and Unit.objects.count() == 4
    # то же через форму: отказ — 200 с [role=alert], база не меняется
    client = support.logged_in(admin())
    response = client.post("/structure/new/", {"kind": "department", "name": "Отдел3", "description": "", "parent": team.pk})
    assert response.status_code == 200 and "отдел подчиняется только отделу" in alert_text(response).lower()
    assert snapshot() == before


def test_unit_fields_name_description_parent_and_marks():
    """FR-104: у узла название, описание, «Подчиняется», руководители и заместители (ноль или несколько); связь `children`."""
    actor, root = support.make_admin(), support_org.root_unit()
    net = structure().create_unit(kind="department", name="Сеть", parent=root, description="Сетевая инфраструктура", actor=actor)
    assert net.name == "Сеть" and net.description == "Сетевая инфраструктура" and net.parent == root
    assert not net.is_root and net.depth == 1 and net.path == f"{root.path}{net.pk}/" and net.created_at
    assert list(root.children.all()) == [net]
    empty = support_org.make_unit("Без людей")
    assert not empty.memberships.exists()
    heads = [person("Иванов Иван"), person("Яковлев Яков")]
    deputy = person("Петров Пётр")
    for user in heads:
        support_org.make_member(user, net, mark="head")
    support_org.make_member(deputy, net, mark="deputy")
    support_org.make_member(person("Сидоров Семён"), net)
    marks = net.memberships.values_list("user_id", "mark")
    assert {u for u, m in marks if m == "head"} == {u.pk for u in heads}
    assert {u for u, m in marks if m == "deputy"} == {deputy.pk}
    assert net.memberships.count() == 4


def test_unit_name_required_and_unique_per_parent_case_and_yo_insensitive():
    """FR-105 (сценарий 1.4): название непустое, до 150 знаков, у родителя не повторяется без учёта регистра, пробелов и «е/ё»; в другом родителе можно; ограничение есть и в базе."""
    Unit = model("org.Unit")
    actor, root = support.make_admin(), support_org.root_unit()
    create = lambda name, parent=root, kind="department": structure().create_unit(  # noqa: E731
        kind=kind, name=name, parent=parent, actor=actor)
    expect_code("name_required", create, "")
    expect_code("name_required", create, "   ")
    expect_code("name_too_long", create, "я" * 151)
    assert create("я" * 150).name == "я" * 150
    net = create("Сеть")
    for dup in ("сеть", "  СЕТЬ  ", "Сеть "):
        error = expect_code("name_taken", create, dup)
        assert "названия узлов под одним родителем не повторяются" in str(error).lower()
    yolka = create("  Ёлка   Тест ")
    assert yolka.name_key == "елка тест" == support_org.name_key("Ёлка Тест")
    expect_code("name_taken", create, "елка тест")
    assert create("Сеть", parent=yolka).parent == yolka, "то же название под другим родителем допустимо"
    # порядок проверок: название раньше видов, виды раньше занятого названия
    team = create("Команда", kind="team")
    expect_code("name_required", create, "", team)
    support_org.make_unit("Занято", kind="department", parent=team)  # через ORM: отдел под командой
    expect_code("kind_rules", create, "занято", team)
    # правка: занятое название отказывается, смена регистра у самого узла — нет, name_key обновляется
    other = create("Поддержка")
    expect_code("name_taken", structure().update_unit, other, name="сеть", description="", actor=actor)
    renamed = structure().update_unit(net, name="СЕТЬ", description="", actor=actor)
    assert renamed.name == "СЕТЬ" and Unit.objects.get(pk=net.pk).name_key == "сеть"
    # смена только «ё» на «е» тоже допустима (дополнение 6): узел не конфликтует сам с собой по name_key
    renamed = structure().update_unit(yolka, name="Елка Тест", description="", actor=actor)
    assert renamed.name == "Елка Тест" and Unit.objects.get(pk=yolka.pk).name_key == "елка тест"
    renamed = structure().update_unit(yolka, name="Ёлка Тест", description="", actor=actor)
    assert renamed.name == "Ёлка Тест" and Unit.objects.get(pk=yolka.pk).name_key == "елка тест"
    # ограничение базы: одно имя под одним родителем
    with pytest.raises(IntegrityError), transaction.atomic():
        support_org.make_unit("Поддержка")
    # форма: отказ — 200 с текстом спеки
    response = support.logged_in(admin()).post(
        "/structure/new/", {"kind": "department", "name": "поддержка", "description": "", "parent": root.pk})
    assert response.status_code == 200 and "названия узлов под одним родителем не повторяются" in alert_text(response).lower()


def test_root_rename_allowed_delete_and_move_refused_even_direct():
    """FR-103 (сценарий 1.5): корень переименовывается; удалить и перенести его нельзя ни службой, ни прямым запросом; в базе один корень, у корня нет родителя."""
    Unit = model("org.Unit")
    actor, root = support.make_admin(), support_org.root_unit()
    net = support_org.make_unit("Сеть")
    child = support_org.make_unit("Серверы", parent=net)
    renamed = structure().update_unit(root, name="Служба ИТ", description="Главная", actor=actor)
    assert renamed.is_root and Unit.objects.get(pk=root.pk).name == "Служба ИТ"
    assert Unit.objects.get(pk=root.pk).name_key == "служба ит" and Unit.objects.get(pk=root.pk).path == f"/{root.pk}/"
    before = snapshot()
    expect_code("root_protected", structure().delete_unit, root, actor=actor)
    expect_code("root_protected", structure().move_unit, root, net, actor=actor)
    expect_code("root_protected", structure().move_unit, root, child, actor=actor)  # root_protected раньше cycle
    assert snapshot() == before
    # страница и формы
    client = support.logged_in(admin())
    page = client.get(unit_url(root))
    assert page.status_code == 200
    assert not doc(page).select(data_action="unit-delete"), "у корня нет «Удалить»"
    assert doc(page).select(data_action="unit-edit")
    form = client.get(f"/structure/{root.pk}/edit/")
    assert form.status_code == 200 and not doc(form).select(name="parent"), "у корня нет поля «Подчиняется»"
    moved = client.post(f"/structure/{root.pk}/edit/", {"name": "Служба ИТ", "description": "", "parent": net.pk})
    assert moved.status_code == 200 and alert_text(moved)
    deleted = client.post(f"/structure/{root.pk}/delete/", {"confirm": "1"})
    assert deleted.status_code == 200 and alert_text(deleted)
    assert snapshot() == before
    ok = client.post(f"/structure/{root.pk}/edit/", {"name": "ИТ-служба", "description": ""})
    assert ok.status_code == 302 and ok["Location"] == unit_url(root)
    assert Unit.objects.get(pk=root.pk).name == "ИТ-служба"
    # ограничения базы: второй корень, корень с родителем, не корень без родителя
    with pytest.raises(IntegrityError), transaction.atomic():
        Unit.objects.create(name="Второй", name_key="второй", kind="department", is_root=True, depth=0, path="/x/")
    with pytest.raises(IntegrityError), transaction.atomic():
        Unit.objects.create(name="Сирота", name_key="сирота", kind="department", is_root=False, parent=None, depth=1, path="/y/")
    with pytest.raises(IntegrityError), transaction.atomic():
        Unit.objects.create(name="Корень2", name_key="корень2", kind="department", is_root=True, parent=net, depth=2, path="/z/")


# --- перенос ---------------------------------------------------------------------------------------

def test_move_subtree_paths_depths_members_and_heads_kept():
    """FR-106 (сценарий 6.1): перенос меняет пути и глубины всего поддерева (одним UPDATE), участники и отметки сохраняются."""
    Membership = model("org.Membership")
    actor, root = support.make_admin(), support_org.root_unit()
    tree = support_org.make_tree({"Сеть": {"Серверы": {"team:Дежурные": {}}}, "Поддержка": {}})
    net, servers, duty, sup = tree["Сеть"], tree["Серверы"], tree["Дежурные"], tree["Поддержка"]
    head, deputy, plain = person("Иванов Иван"), person("Петров Пётр"), person("Сидоров Семён")
    support_org.make_member(head, servers, mark="head")
    support_org.make_member(deputy, servers, mark="deputy")
    support_org.make_member(plain, duty)
    support_org.make_member(plain, net)
    members_before = set(Membership.objects.values_list("user_id", "unit_id", "mark"))
    assert (net.depth, servers.depth, duty.depth) == (1, 2, 3)
    queries = sqls_of(lambda: structure().move_unit(net, sup, actor=actor))
    updates = [s for s in queries if s.lstrip().startswith('UPDATE "org_unit"')]
    assert 0 < len(updates) <= 2, f"перенос поддерева из 3 узлов — не по UPDATE на узел: {len(updates)}"
    Unit = model("org.Unit")
    net, servers, duty, sup = (Unit.objects.get(pk=u.pk) for u in (net, servers, duty, sup))
    assert net.parent == sup and net.path == f"{sup.path}{net.pk}/" and net.depth == sup.depth + 1 == 2
    assert servers.parent == net and servers.path == f"{net.path}{servers.pk}/" and servers.depth == 3
    assert duty.parent == servers and duty.path == f"{servers.path}{duty.pk}/" and duty.depth == 4
    assert Unit.objects.get(pk=root.pk).path == f"/{root.pk}/" and sup.path == f"{root.path}{sup.pk}/"
    assert set(Membership.objects.values_list("user_id", "unit_id", "mark")) == members_before
    assert {u.pk for u in structure().descendants(sup)} == {sup.pk, net.pk, servers.pk, duty.pk}
    assert {u.pk for u in structure().descendants(sup, include_self=False)} == {net.pk, servers.pk, duty.pk}
    assert len(events("unit.moved", object_id=str(net.pk))) == 1
    # тот же родитель — тихо ничего
    structure().move_unit(net, sup, actor=actor)
    assert len(events("unit.moved")) == 1


def test_move_into_self_or_descendant_refused():
    """FR-106 (сценарий 6.2): нельзя подчинить узел самому себе или потомку — `cycle` с текстом спеки, ничего не меняется; цикл проверяется раньше правил видов."""
    actor = support.make_admin()
    tree = support_org.make_tree({"Сеть": {"Серверы": {"team:Дежурные": {}}}})
    net, servers, duty = tree["Сеть"], tree["Серверы"], tree["Дежурные"]
    before = snapshot()
    error = expect_code("cycle", structure().move_unit, net, net, actor=actor)
    assert "цикл в подчинении" in str(error).lower()
    expect_code("cycle", structure().move_unit, net, servers, actor=actor)
    expect_code("cycle", structure().move_unit, net, duty, actor=actor)  # потомок-команда: и cycle, и kind_rules — первым cycle
    assert snapshot() == before and not events("unit.moved")
    client = support.logged_in(admin())
    response = client.post(f"/structure/{net.pk}/edit/", {"name": "Сеть", "description": "", "parent": servers.pk})
    assert response.status_code == 200 and "цикл в подчинении" in alert_text(response).lower()
    assert snapshot() == before


def test_move_checks_kind_rules_and_free_name_at_new_parent():
    """FR-102, FR-105, FR-106: перенос проверяет виды и свободное название у нового родителя до записи; порядок — виды, затем название."""
    actor = support.make_admin()
    sup, net = support_org.make_unit("Поддержка"), support_org.make_unit("Сеть")
    ext = support_org.make_unit("Внешние", kind="team", parent=sup)
    support_org.make_unit("Общий", parent=sup)
    other = support_org.make_unit("общий", parent=net)  # то же имя под другим родителем — можно
    before = snapshot()
    expect_code("kind_rules", structure().move_unit, net, ext, actor=actor)
    expect_code("name_taken", structure().move_unit, other, sup, actor=actor)
    added = support_org.make_unit("Общий", parent=ext)  # через ORM: отдел под командой
    expect_code("kind_rules", structure().move_unit, other, ext, actor=actor)  # виды раньше названия
    assert [row for row in snapshot() if row[0] != added.pk] == before and not events("unit.moved")  # включая узел `other`
    # допустимое: переименовать и перенести; команда — под отдел и под команду
    other = structure().update_unit(other, name="Другой", description="", actor=actor)
    other = structure().move_unit(other, sup, actor=actor)
    assert other.parent == sup
    team = support_org.make_unit("Т2", kind="team", parent=net)
    team = structure().move_unit(team, ext, actor=actor)
    assert team.parent == ext
    ext = structure().move_unit(ext, net, actor=actor)
    assert ext.parent == net
    assert len(events("unit.moved")) == 3


def test_structure_changes_lock_root_row():
    """FR-106: создание, правка, перенос и удаление берут `FOR UPDATE` по строке корня до первой записи (службой и через запрос)."""
    actor = support.make_admin()
    root = support_org.root_unit()
    a, b = support_org.make_unit("А"), support_org.make_unit("Б")
    empty = support_org.make_unit("Пустой")
    assert_root_locked_before_writes(sqls_of(lambda: structure().create_unit(kind="department", name="Новый", parent=root, actor=actor)))
    assert_root_locked_before_writes(sqls_of(lambda: structure().update_unit(a, name="А2", description="", actor=actor)))
    assert_root_locked_before_writes(sqls_of(lambda: structure().move_unit(a, b, actor=actor)))
    assert_root_locked_before_writes(sqls_of(lambda: structure().delete_unit(empty, actor=actor)))
    # запрос через клиент: журнал запросов сбрасывается сигналом, поэтому — execute_wrapper
    client = support.logged_in(admin())
    log = []

    def wrapper(execute, sql, params, many, context):
        log.append(sql)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(wrapper):
        response = client.post("/structure/new/", {"kind": "department", "name": "Через форму", "description": "", "parent": root.pk})
    assert response.status_code == 302
    assert_root_locked_before_writes(log)


def test_no_drag_and_drop_route_move_only_by_parent_field():
    """FR-106 (сценарий 6.5): перетаскивания нет — ни в разметке, ни маршрута `/structure/<id>/move/`; перенос — полем «Подчиняется»."""
    client = support.logged_in(admin())
    tree = support_org.make_tree({"Сеть": {"Серверы": {}}, "Поддержка": {}})
    net, sup = tree["Сеть"], tree["Поддержка"]
    page = client.get("/structure/")
    assert page.status_code == 200 and doc(page).select(data_unit_tree=True)
    html = page.content.decode().lower()
    assert "draggable" not in html and "data-drag" not in html and "ondrag" not in html
    assert not any(re.search(r"(^|/)move/", str(route)) for route, _ in support.all_routes() if "structure" in str(route))
    assert client.get(f"/structure/{net.pk}/move/").status_code == 404
    assert client.post(f"/structure/{net.pk}/move/", {"parent": sup.pk}).status_code == 404
    form = client.get(f"/structure/{net.pk}/edit/")
    assert form.status_code == 200 and doc(form).select(name="parent")
    moved = client.post(f"/structure/{net.pk}/edit/", {"name": "Сеть", "description": "", "parent": sup.pk})
    assert moved.status_code == 302 and moved["Location"] == unit_url(net)
    net.refresh_from_db()
    assert net.parent == sup and net.path == f"{sup.path}{net.pk}/"


# --- удаление --------------------------------------------------------------------------------------

def test_delete_only_empty_unit_with_confirmation_roles_removed_and_audited():
    """FR-107, FR-150 (сценарий 6.3): удалить можно только пустой узел и после подтверждения; роли узла уходят с ним, журнал записывает снятые роли."""
    Unit, UnitRole = model("org.Unit"), model("org.UnitRole")
    actor, root = support.make_admin(), support_org.root_unit()
    busy, parent_unit = support_org.make_unit("С людьми"), support_org.make_unit("С детьми")
    support_org.make_unit("Вложенный", parent=parent_unit)
    support_org.make_member(person("Иванов Иван"), busy)
    empty = support_org.make_unit("Пустой")
    role_a, role_b = factories.make_role(name="Б роль"), factories.make_role(name="А роль")
    support_org.make_unit_role(empty, role_a)
    support_org.make_unit_role(empty, role_b)
    expect_code("not_empty", structure().delete_unit, busy, actor=actor)
    expect_code("not_empty", structure().delete_unit, parent_unit, actor=actor)
    with pytest.raises(ProtectedError), transaction.atomic():
        busy.delete()
    client = support.logged_in(admin())
    # диалог ничего не меняет
    dialog = client.get(f"/structure/{empty.pk}/delete/")
    assert dialog.status_code == 200
    node = doc(dialog).select(data_dialog="unit-delete", role="dialog", aria_modal="true")
    assert node and node[0].select("button", type="submit") and node[0].select("button", data_dialog_cancel=True)
    assert Unit.objects.filter(pk=empty.pk).exists() and not events("unit.deleted")
    # отказы по существу — 200 с [role=alert]
    for blocked in (busy, parent_unit):
        refused = client.post(f"/structure/{blocked.pk}/delete/", {"confirm": "1"})
        assert refused.status_code == 200 and alert_text(refused)
        assert Unit.objects.filter(pk=blocked.pk).exists()
    # без подтверждения (confirm=1 нет) — 200 с [role=alert], узел цел, событий нет (п. 21 дополнения)
    for data in ({}, {"confirm": ""}):
        unconfirmed = client.post(f"/structure/{empty.pk}/delete/", data)
        assert unconfirmed.status_code == 200 and alert_text(unconfirmed)
        assert Unit.objects.filter(pk=empty.pk).exists() and UnitRole.objects.filter(unit=empty).count() == 2
        assert not events("unit.deleted")
    done = client.post(f"/structure/{empty.pk}/delete/", {"confirm": "1"})
    assert done.status_code == 302 and done["Location"] == "/structure/"
    assert not Unit.objects.filter(pk=empty.pk).exists() and not UnitRole.objects.filter(role__in=[role_a, role_b]).exists()
    assert model("core.Role").objects.filter(pk__in=[role_a.pk, role_b.pk]).count() == 2, "сами роли остаются"
    (event,) = events("unit.deleted", object_id=str(empty.pk))
    assert event.before["roles"] == ["А роль", "Б роль"] and event.before["name"] == "Пустой"


# --- страница ---------------------------------------------------------------------------------------

def test_structure_page_tree_details_and_card_with_own_url_and_fragment():
    """FR-108 (сценарий 4.1): дерево вложенными списками с `<details>`; карточка выбранного узла со своим адресом — фрагмент для HTMX и страница целиком без него."""
    tree = support_org.make_tree({"Сеть": {"Серверы": {"team:Дежурные": {}}}, "Поддержка": {"Линия": {}}})
    root, net, servers, duty, sup = support_org.root_unit(), tree["Сеть"], tree["Серверы"], tree["Дежурные"], tree["Поддержка"]
    servers.description = "Серверная группа"
    servers.save(update_fields=["description"])
    me = viewer(full_name="Смотров Сергей")
    support_org.make_member(me, servers)
    client = support.logged_in(me)
    page = client.get("/structure/")
    assert page.status_code == 200
    d = doc(page)
    (ul,) = d.select("ul", data_unit_tree=True)
    items = {int(li.attrs["data-unit-id"]): li for li in ul.select("li", data_unit_id=True)}
    assert set(items) == {root.pk, net.pk, servers.pk, duty.pk, sup.pk, tree["Линия"].pk}
    assert items[duty.pk].attrs["data-kind"] == "team" and items[net.pk].attrs["data-kind"] == "department"
    assert items[servers.pk].inside(items[net.pk]) and items[net.pk].inside(items[root.pk]) and not items[sup.pk].inside(items[net.pk])
    first_details = {pk: li.select("details")[0] for pk, li in items.items() if li.select("details")}
    assert {root.pk, net.pk, servers.pk, sup.pk} <= set(first_details)
    assert "open" in first_details[root.pk].attrs and "open" in first_details[net.pk].attrs, "корень и предки выбранного узла раскрыты"
    assert "open" not in first_details[sup.pk].attrs, "остальные закрыты"
    # карточка: свой узел выбран сам
    assert d.select(data_structure_layout=True)
    (holder,) = d.select(id="unit-card")
    (card,) = holder.select(data_unit_card=True)
    assert card.attrs["data-unit-id"] == str(servers.pk) and card.attrs["data-kind"] == "department"
    assert card.select(data_unit_name=True)[0].text() == "Серверы"
    assert card.select(data_unit_description=True)[0].text() == "Серверная группа"
    assert "Сеть" in card.select(data_unit_parent=True)[0].text()
    links = {int(a.attrs["href"].strip("/").split("/")[1]): a for a in ul.select("a", data_unit_link=True)}
    assert set(links) == set(items)
    link = links[net.pk]
    assert link.attrs["href"] == unit_url(net) and link.attrs["hx-get"] == unit_url(net)
    assert link.attrs["hx-target"] == "#unit-card" and link.attrs["hx-push-url"] == "true"
    assert links[servers.pk].attrs.get("aria-current") == "true" and links[net.pk].attrs.get("aria-current") != "true"
    # фрагмент и страница целиком по тому же адресу
    fragment = client.get(unit_url(net), **HX)
    assert fragment.status_code == 200 and "<html" not in fragment.content.decode().lower()
    assert card_of(fragment).attrs["data-unit-id"] == str(net.pk) and not doc(fragment).select(data_unit_tree=True)
    full = client.get(unit_url(net))
    assert full.status_code == 200 and "<html" in full.content.decode().lower() and doc(full).select(data_unit_tree=True)
    assert card_of(full).attrs["data-unit-id"] == str(net.pk)
    current = [a for a in doc(full).select("a", data_unit_link=True) if a.attrs.get("aria-current") == "true"]
    assert [a.attrs["href"] for a in current] == [unit_url(net)]
    # нет своих узлов — открывается корень; неизвестный и неверный адрес — 404; без входа — вход
    stranger = support.logged_in(viewer())
    assert card_of(stranger.get("/structure/")).attrs["data-unit-id"] == str(root.pk)
    assert client.get("/structure/99999999/").status_code == 404 and client.get("/structure/abc/").status_code == 404
    anonymous = support.make_client().get("/structure/")
    assert anonymous.status_code == 302 and anonymous["Location"].startswith("/login/")


def test_own_units_highlighted_and_search_in_unit_case_and_yo_insensitive():
    """FR-108 (сценарии 4.1, 4.2): свои узлы выделены (`data-own`, `unit-own`); поиск в узле по ФИО и должности без учёта регистра и «е/ё»."""
    tree = support_org.make_tree({"Сеть": {"Серверы": {}}, "Поддержка": {"Линия": {}}, "Инженеры": {}})
    root, net, servers, line, eng = (support_org.root_unit(), tree["Сеть"], tree["Серверы"], tree["Линия"], tree["Инженеры"])
    me = viewer(full_name="Смотров Сергей")
    support_org.make_member(me, servers)
    support_org.make_member(me, line)
    client = support.logged_in(me)
    d = doc(client.get("/structure/"))
    lis = {int(li.attrs["data-unit-id"]): li for li in d.select("li", data_unit_id=True)}
    own = {pk for pk, li in lis.items() if li.attrs["data-own"] == "true"}
    assert own == {servers.pk, line.pk}
    assert all(lis[pk].attrs["data-own"] in ("true", "false") for pk in lis)
    assert all(("unit-own" in lis[pk].attrs.get("class", "").split()) == (pk in own) for pk in lis)
    # поиск
    elkin, belov = person("Ёлкин Пётр", "Старший Инженер"), person("Белов Олег", "Бухгалтер")
    ezhova, orlov = person("Ежова Анна", "Инженер-электрик"), person("Орлов Игорь", "Бухгалтер")
    for user in (elkin, belov, ezhova, orlov):
        support_org.make_member(user, eng)
    url = unit_url(eng)
    everyone = {elkin.pk, belov.pk, ezhova.pk, orlov.pk}
    assert member_ids(client.get(url)) == everyone
    cases = {"ЕЛКИН": {elkin.pk}, "петр": {elkin.pk}, "ёж": {ezhova.pk}, "ИНЖЕНЕР": {elkin.pk, ezhova.pk},
             "бухг": {belov.pk, orlov.pk}, "старшии": set()}
    for text, expected in cases.items():
        assert member_ids(client.get(f"{url}?q={quote(text)}", **HX)) == expected, text
        assert member_ids(client.get(f"{url}?q={quote(text)}")) == expected, text
    # `/structure/` открывает первый свой узел по path (CONTRACT-002 § 8.3)
    first_own = min((servers, line), key=lambda u: u.path)
    assert card_of(client.get("/structure/")).attrs["data-unit-id"] == str(first_own.pk)
    (search,) = card_of(client.get(url)).select("input", name="q")
    assert search.attrs["hx-get"] == url and search.attrs["hx-target"] == "#unit-card"
    assert search.attrs["hx-trigger"] == "input changed delay:300ms"


def test_card_lists_heads_deputies_members_with_position_and_photo():
    """FR-108: карточка узла показывает руководителей, заместителей и участников с должностью и фото (картинка или инициалы)."""
    StoredFile = model("core.StoredFile")
    unit = support_org.make_unit("Сеть")
    head = person("Иванов Иван", "Начальник отдела")
    deputy = person("Петров Пётр", "Заместитель начальника")
    member = person("Сидорова Анна", "Сетевой инженер")
    support_org.make_member(head, unit, mark="head")
    support_org.make_member(deputy, unit, mark="deputy")
    support_org.make_member(member, unit)
    photo = StoredFile.objects.create(
        owner=member, purpose="photo", status="clean", size=1, sha256="0" * 64, content_type="image/jpeg")
    member.photo = photo
    member.save()
    client = support.logged_in(viewer())
    response = client.get(unit_url(unit))
    card = card_of(response)
    rows = {int(r.attrs["data-user-id"]): r for r in card.select(data_member=True)}
    assert {head.pk, deputy.pk, member.pk} <= set(rows)
    assert rows[head.pk].attrs["data-mark"] == "head" and rows[deputy.pk].attrs["data-mark"] == "deputy"
    assert rows[member.pk].attrs["data-mark"] == ""
    assert head.pk in {int(r.attrs["data-user-id"]) for r in card.select(data_section="heads")[0].select(data_member=True)}
    assert deputy.pk in {int(r.attrs["data-user-id"]) for r in card.select(data_section="deputies")[0].select(data_member=True)}
    assert member.pk in member_ids(response)
    for user in (head, deputy, member):
        row = rows[user.pk]
        assert row.select(data_member_name=True)[0].text() == user.full_name
        assert row.select(data_member_position=True)[0].text() == user.position
        assert row.select(data_photo=True), "у каждого участника есть [data-photo]"
    assert rows[head.pk].select(data_mark_label=True)[0].text() == "Руководитель"
    assert rows[deputy.pk].select(data_mark_label=True)[0].text() == "Заместитель"
    assert not rows[member.pk].select(data_mark_label=True)
    placeholder = rows[head.pk].select("span", data_photo_placeholder=True)
    assert placeholder and placeholder[0].attrs["data-initials"] == "ИИ" == placeholder[0].text()
    (image,) = rows[member.pk].select("img", data_photo_img=True)
    assert image.attrs["src"] == f"/staff/{member.pk}/photo/{photo.pk}/96/"
    assert not rows[member.pk].select(data_photo_placeholder=True)


def test_empty_tree_unit_and_search_explained():
    """FR-109: пустое дерево, пустой узел и пустой поиск — не пустое поле, а пояснение (`[data-empty-state]` с текстом)."""
    client = support.logged_in(viewer())
    page = client.get("/structure/")
    states = {n.attrs["data-empty-state"]: n for n in doc(page).select(data_empty_state=True)}
    assert {"tree", "unit"} <= set(states), "после установки: дерево из одного корня и пустой корень"
    assert all(n.text() for n in states.values())
    assert "search" not in states
    # у смотрящего без org.manage кнопок действий в пустых состояниях нет (дополнение 5)
    assert not states["tree"].select(data_action="unit-new") and not states["unit"].select(data_action="members-add")
    # у org.manage в пустом дереве — «unit-new», в пустом узле — «members-add»
    manager_states = {n.attrs["data-empty-state"]: n
                      for n in doc(support.logged_in(admin()).get("/structure/")).select(data_empty_state=True)}
    assert {"tree", "unit"} <= set(manager_states)
    assert manager_states["tree"].select(data_action="unit-new"), "пустое дерево: кнопка «unit-new»"
    assert manager_states["unit"].select(data_action="members-add"), "пустой узел: кнопка «members-add»"
    assert all(n.text() for n in manager_states.values())
    # дерево перестаёт быть пустым, пока есть вложенные узлы
    unit = support_org.make_unit("Сеть")
    states = {n.attrs["data-empty-state"] for n in doc(client.get(unit_url(unit))).select(data_empty_state=True)}
    assert "tree" not in states and "unit" in states
    # узел с людьми: ни «пустого узла», ни «пустого поиска»; поиск без совпадений — «search»
    support_org.make_member(person("Иванов Иван", "Инженер"), unit)
    full = {n.attrs["data-empty-state"] for n in doc(client.get(unit_url(unit))).select(data_empty_state=True)}
    assert full == set()
    miss = client.get(f"{unit_url(unit)}?q={quote('нет такого')}", **HX)
    found = {n.attrs["data-empty-state"]: n for n in doc(miss).select(data_empty_state=True)}
    assert set(found) == {"search"} and found["search"].text()
    assert not doc(miss).select(data_member=True)


# --- права -----------------------------------------------------------------------------------------

def test_view_needs_staff_view_changes_need_org_manage():
    """FR-123 (сценарий 1.6, 4.7): страница — по праву `staff.view`; кнопок изменений без `org.manage` нет, а прямые запросы отклоняются 403 до проверки объекта."""
    root = support_org.root_unit()
    dept, team = support_org.make_unit("Сеть"), support_org.make_unit("Дежурные", kind="team", parent=support_org.make_unit("Сеть2"))
    before = snapshot()
    nobody = support.logged_in(support.make_with_permissions())
    assert nobody.get("/structure/").status_code == 403 and nobody.get(unit_url(dept)).status_code == 403
    reader = support.logged_in(viewer())
    assert reader.get("/structure/").status_code == 200
    actions = ("unit-new", "unit-edit", "unit-delete", "members-add", "marks-heads", "marks-deputies", "unit-roles")
    for path in ("/structure/", unit_url(dept), unit_url(root)):
        d = doc(reader.get(path))
        assert not any(d.select(data_action=name) for name in actions), f"кнопки изменений у читателя на {path}"
    assert reader.get("/structure/new/").status_code == 403
    assert reader.post("/structure/new/", {"kind": "department", "name": "Взлом", "description": "", "parent": root.pk}).status_code == 403
    for path, data in ((f"/structure/{dept.pk}/edit/", {"name": "Взлом", "description": "", "parent": root.pk}),
                       (f"/structure/{dept.pk}/delete/", {"confirm": "1"}), ("/structure/999999/edit/", {})):
        assert reader.post(path, data).status_code == 403, path
    assert reader.get(f"/structure/{dept.pk}/edit/").status_code == 403 and reader.get(f"/structure/{dept.pk}/delete/").status_code == 403
    assert snapshot() == before
    anonymous = support.make_client()
    assert anonymous.post("/structure/new/", {}).status_code == 302
    # обладатель `org.manage` видит действия; у корня нет «Удалить»; «Роли узла» — по `roles.manage`
    manager = support.logged_in(admin())
    d = doc(manager.get(unit_url(dept)))
    for name in ("unit-new", "unit-edit", "unit-delete", "members-add", "marks-heads", "marks-deputies"):
        assert d.select(data_action=name), name
    assert not d.select(data_action="unit-roles")
    (add,) = d.select(data_action="members-add")
    assert {o.attrs.get("value") for o in add.select("select", name="mode")[0].select("option")} >= {"transfer", "concurrent"}
    team_page = doc(manager.get(unit_url(team)))
    assert team_page.select(data_action="members-add") and not team_page.select(data_action="members-add")[0].select("select", name="mode")
    root_page = doc(manager.get(unit_url(root)))
    assert root_page.select(data_action="unit-edit") and not root_page.select(data_action="unit-delete")
    with_roles = support.logged_in(support.make_with_permissions(*MANAGE, "roles.manage"))
    assert doc(with_roles.get(unit_url(dept))).select(data_action="unit-roles")
    created = manager.post("/structure/new/", {"kind": "department", "name": "Новый", "description": "О", "parent": root.pk})
    new = model("org.Unit").objects.get(name="Новый")
    assert created.status_code == 302 and created["Location"] == unit_url(new) and new.parent == root


# --- журнал ----------------------------------------------------------------------------------------

def test_unit_events_created_updated_moved_deleted_before_after():
    """FR-150 (сценарий 1.1, 6.3–6.4): `unit.created/updated/moved/deleted` пишут «было / стало» с ключами контракта; пустая правка событий не даёт."""
    actor, root = support.make_admin(), support_org.root_unit()
    sup = support_org.make_unit("Поддержка")
    unit = structure().create_unit(kind="department", name="Сеть", parent=root, description="Описание", actor=actor)
    (created,) = events("unit.created")
    assert (created.object_type, created.object_id, created.actor_id) == ("unit", str(unit.pk), actor.pk)
    assert {k: created.after[k] for k in ("kind", "name", "description", "parent")} == {
        "kind": "department", "name": "Сеть", "description": "Описание", "parent": root.name}
    expect_code("kind_rules", structure().create_unit, kind="team", name="Отказ", parent=None, actor=actor)
    assert len(events("unit.created")) == 1, "отказ события не пишет"
    # правка: только изменённые ключи
    unit = structure().update_unit(unit, name="Сеть2", description="Описание", actor=actor)
    (updated,) = events("unit.updated")
    assert (updated.object_type, updated.object_id, updated.actor_id) == ("unit", str(unit.pk), actor.pk)
    assert updated.before == {"name": "Сеть"} and updated.after == {"name": "Сеть2"}
    unit = structure().update_unit(unit, name="Сеть2", description="Описание", actor=actor)
    assert len(events("unit.updated")) == 1, "пустая правка событий не пишет"
    unit = structure().update_unit(unit, name="Сеть2", description="Другое", actor=actor)
    assert events("unit.updated")[-1].before == {"description": "Описание"} and events("unit.updated")[-1].after == {"description": "Другое"}
    # перенос
    unit = structure().move_unit(unit, sup, actor=actor)
    (moved,) = events("unit.moved")
    assert (moved.object_type, moved.object_id, moved.actor_id) == ("unit", str(unit.pk), actor.pk)
    assert moved.before["parent"] == root.name and moved.after["parent"] == "Поддержка"
    assert moved.before["parent_id"] == root.pk and moved.after["parent_id"] == sup.pk  # целые JSON (доп. 7)
    # удаление с ролями
    role = factories.make_role(name="Роль узла")
    support_org.make_unit_role(unit, role)
    structure().delete_unit(unit, actor=actor)
    (deleted,) = events("unit.deleted")
    assert (deleted.object_type, deleted.object_id, deleted.actor_id) == ("unit", str(unit.pk), actor.pk)
    assert {k: deleted.before[k] for k in ("kind", "name", "parent", "roles")} == {
        "kind": "department", "name": "Сеть2", "parent": "Поддержка", "roles": ["Роль узла"]}
