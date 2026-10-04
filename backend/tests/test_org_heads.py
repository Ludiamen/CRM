"""T-2103: руководитель и подчинённые в карточке, все ветви FR-115 (FR-115…117). Сценарий 3 спеки."""
from html.parser import HTMLParser

import pytest

from tests import factories, support, support_org
from tests.support import model
from tests.support_org import make_member, make_tree, root_unit

pytestmark = pytest.mark.django_db


# --- помощники файла ----------------------------------------------------------------------------

class _FieldReader(HTMLParser):
    """Собирает `data-field="<имя>"`: текст и значение `data-empty` (вложенные теги того же имени учитываются)."""

    def __init__(self):
        super().__init__()
        self.fields: dict[str, dict] = {}
        self._open: list[list] = []  # [имя поля, тег, глубина]

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        for entry in self._open:
            if entry[1] == tag:
                entry[2] += 1
        if "data-field" in attrs:
            name = attrs["data-field"]
            self.fields[name] = {"text": "", "empty": attrs.get("data-empty")}
            self._open.append([name, tag, 1])

    def handle_endtag(self, tag):
        for entry in list(self._open):
            if entry[1] == tag:
                entry[2] -= 1
                if entry[2] == 0:
                    self._open.remove(entry)

    def handle_data(self, data):
        for entry in self._open:
            self.fields[entry[0]]["text"] += data


def card_fields(viewer, target) -> dict[str, dict]:
    """Поля карточки `/staff/<id>/` глазами `viewer`: имя -> {"text": без лишних пробелов, "empty": "true"/"false"}."""
    response = viewer.get(f"/staff/{target.pk}/")
    assert response.status_code == 200, response.status_code
    reader = _FieldReader()
    reader.feed(response.content.decode())
    return {name: {"text": " ".join(f["text"].split()), "empty": f["empty"]} for name, f in reader.fields.items()}


class _LabelReader(HTMLParser):
    """Подписи полей: `data-field-label="<имя>"` -> текст элемента (п. 20 дополнения контракта)."""

    def __init__(self):
        super().__init__()
        self.labels: dict[str, str] = {}
        self.fields: set[str] = set()
        self._name, self._tag, self._depth = None, None, 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "data-field" in attrs:
            self.fields.add(attrs["data-field"])
        if self._name is not None and tag == self._tag:
            self._depth += 1
        if "data-field-label" in attrs and self._name is None:
            self._name, self._tag, self._depth = attrs["data-field-label"], tag, 1
            self.labels[self._name] = ""

    def handle_endtag(self, tag):
        if self._name is not None and tag == self._tag:
            self._depth -= 1
            if self._depth == 0:
                self._name = None

    def handle_data(self, data):
        if self._name is not None:
            self.labels[self._name] += data


def card_labels(viewer, target) -> tuple[dict[str, str], set[str]]:
    reader = _LabelReader()
    reader.feed(viewer.get(f"/staff/{target.pk}/").content.decode())
    return {k: " ".join(v.split()) for k, v in reader.labels.items()}, reader.fields


def person(name: str, **extra):
    return support.make_employee(full_name=name, **extra)


def heads_by_unit(user) -> dict[int, tuple[list[str], int | None]]:
    """`heads_of(user)` как «id узла -> (имена руководителей, id узла-источника)»."""
    from apps.org.services import structure
    return {item.unit.id: ([p.full_name for p in item.heads], item.source.id if item.source else None)
            for item in structure.heads_of(user)}


# --- ветви FR-115 -------------------------------------------------------------------------------

def test_heads_of_own_unit_when_not_head():
    """FR-115 (сценарий 3.1): не руководитель узла и у узла есть руководители — это они; источник — сам узел; заместитель не руководитель."""
    from apps.org.services import structure
    units = make_tree({"Отдел ИТ": {"Сеть": {}}})
    net, it = units["Сеть"], units["Отдел ИТ"]
    boss = person("Орлов Олег")
    second = person("Белов Борис")
    deputy = person("Яшин Ян")
    employee = person("Сидоров Сидор")
    make_member(boss, it, mark="head")  # у ИТ-отдела свой руководитель: он не должен подменить руководителей «Сети»
    for user, mark in ((second, "head"), (boss, "head"), (deputy, "deputy"), (employee, "")):
        make_member(user, net, mark=mark)
    result = structure.heads_of(employee)
    assert len(result) == 1
    assert result[0].unit.id == net.id and result[0].source.id == net.id
    assert [p.full_name for p in result[0].heads] == ["Белов Борис", "Орлов Олег"]
    assert [p.id for p in result[0].heads] == [second.id, boss.id]
    viewer = support.logged_in(support.make_admin())
    assert card_fields(viewer, employee)["head"]["text"] == "Белов Борис, Орлов Олег"
    # обычный сотрудник с `staff.view` (не администратор) видит те же поля (FR-116, сценарий 4.5)
    colleague = support.logged_in(support.make_employee(
        roles=[factories.make_role(permissions=("staff.view",))]))
    colleague_fields = card_fields(colleague, employee)
    assert colleague_fields["head"]["text"] == "Белов Борис, Орлов Олег"
    assert colleague_fields["units"]["text"] == "Сеть"


def test_nearest_ancestor_heads_when_unit_has_none():
    """FR-115 (сценарий 3.2): у узла нет руководителей — берутся руководители ближайшего вышестоящего узла, где они есть; карточка показывает их имена."""
    units = make_tree({"Отдел ИТ": {"Сеть": {"Серверы": {}}}})
    top, net, servers = units["Отдел ИТ"], units["Сеть"], units["Серверы"]
    far, near, employee = person("Дальний Даниил"), person("Ближний Борис"), person("Сидоров Сидор")
    make_member(far, top, mark="head")
    make_member(near, net, mark="deputy")  # заместитель руководителем не считается: «Сеть» без руководителей
    make_member(employee, servers)
    assert heads_by_unit(employee) == {servers.id: (["Дальний Даниил"], top.id)}
    near_head = person("Средний Семён")
    make_member(near_head, net, mark="head")
    assert heads_by_unit(employee) == {servers.id: (["Средний Семён"], net.id)}
    viewer = support.logged_in(support.make_admin())
    field = card_fields(viewer, employee)["head"]
    assert field["text"] == "Средний Семён" and field["empty"] == "false"


def test_head_sees_nearest_ancestor_heads_even_one_of_several():
    """FR-115 (сценарий 3.3): сам руководитель узла (даже один из нескольких) видит руководителей ближайшего вышестоящего узла, а не коллегу по узлу."""
    units = make_tree({"Отдел ИТ": {"Сеть": {}}})
    top, net = units["Отдел ИТ"], units["Сеть"]
    boss, first, second = person("Орлов Олег"), person("Антонов Антон"), person("Борисов Борис")
    make_member(boss, top, mark="head")
    make_member(first, net, mark="head")
    make_member(second, net, mark="head")
    assert heads_by_unit(first) == {net.id: (["Орлов Олег"], top.id)}
    assert heads_by_unit(second) == {net.id: (["Орлов Олег"], top.id)}
    viewer = support.logged_in(support.make_admin())
    assert card_fields(viewer, first)["head"]["text"] == "Орлов Олег"


def test_self_excluded_above_first_level_empty_set_goes_higher():
    """FR-115: выше первого уровня из набора исключается сам сотрудник; пустой набор ведёт ещё выше; если остался кто-то, он и руководитель."""
    units = make_tree({"Отдел ИТ": {"Сеть": {}}, "Бухгалтерия": {"Касса": {}}})
    top, net, acc, cash = units["Отдел ИТ"], units["Сеть"], units["Бухгалтерия"], units["Касса"]
    root = root_unit()
    director, solo, pair_a, pair_b = person("Директоров Дмитрий"), person("Одинцов Олег"), person("Андреев Андрей"), person("Борин Борис")
    make_member(director, root, mark="head")
    # solo — руководитель «Сети» и «Отдела ИТ»: набор «Отдела ИТ» после исключения себя пуст, поиск идёт к корню
    make_member(solo, top, mark="head")
    make_member(solo, net, mark="head")
    assert heads_by_unit(solo) == {top.id: (["Директоров Дмитрий"], root.id), net.id: (["Директоров Дмитрий"], root.id)}
    # pair_a — руководитель «Кассы» и вместе с pair_b руководитель «Бухгалтерии»: остаётся pair_b
    make_member(pair_a, acc, mark="head")
    make_member(pair_b, acc, mark="head")
    make_member(pair_a, cash, mark="head")
    assert heads_by_unit(pair_a) == {acc.id: (["Директоров Дмитрий"], root.id), cash.id: (["Борин Борис"], acc.id)}


def test_unit_with_only_deputies_goes_higher():
    """FR-115: у узла только заместители — руководителей нет, поиск идёт выше; сам заместитель тоже получает руководителей выше."""
    units = make_tree({"Отдел ИТ": {"Сеть": {}}})
    top, net = units["Отдел ИТ"], units["Сеть"]
    boss, deputy, employee = person("Орлов Олег"), person("Заместов Захар"), person("Сидоров Сидор")
    make_member(boss, top, mark="head")
    make_member(deputy, net, mark="deputy")
    make_member(employee, net)
    assert heads_by_unit(employee) == {net.id: (["Орлов Олег"], top.id)}
    assert heads_by_unit(deputy) == {net.id: (["Орлов Олег"], top.id)}


def test_not_assigned_when_no_heads_up_to_root():
    """FR-115 (сценарий 3.5): руководителей нет до самого корня — пустой набор и источник `None`; в карточке «не назначен»; у руководителя корня — тоже."""
    units = make_tree({"Отдел ИТ": {"Сеть": {}}})
    top, net = units["Отдел ИТ"], units["Сеть"]
    employee, deputy, lone = person("Сидоров Сидор"), person("Заместов Захар"), person("Одинцов Олег")
    make_member(employee, net)
    make_member(deputy, top, mark="deputy")
    assert heads_by_unit(employee) == {net.id: ([], None)}
    viewer = support.logged_in(support.make_admin())
    field = card_fields(viewer, employee)["head"]
    assert field["text"] == "не назначен" and field["empty"] == "true"
    root = root_unit()
    make_member(lone, root, mark="head")
    assert heads_by_unit(lone) == {root.id: ([], None)}
    assert card_fields(viewer, lone)["head"]["text"] == "не назначен"
    no_units = person("Безузлов Борис")
    assert card_fields(viewer, no_units)["head"]["empty"] == "true"


def test_concurrent_employee_heads_shown_per_unit():
    """FR-115, FR-116 (сценарий 3.4): совместителю руководители показаны по каждому узлу: «Сеть: …; Поддержка: …»."""
    units = make_tree({"Отдел ИТ": {"Сеть": {}, "Поддержка": {}}})
    net, support_unit = units["Сеть"], units["Поддержка"]
    ivanov, petrov, concurrent = person("Иванов Иван"), person("Петров Пётр"), person("Сидоров Сидор")
    make_member(ivanov, net, mark="head")
    make_member(petrov, support_unit, mark="head")
    make_member(concurrent, net)
    make_member(concurrent, support_unit)
    result = heads_by_unit(concurrent)
    assert result == {net.id: (["Иванов Иван"], net.id), support_unit.id: (["Петров Пётр"], support_unit.id)}
    from apps.org.services import structure
    ordered = sorted((net, support_unit), key=lambda u: u.path)  # байтовый порядок path, а не порядок создания (CONTRACT-002, доп. 1, 18)
    assert [item.unit.id for item in structure.heads_of(concurrent)] == [u.id for u in ordered]
    viewer = support.logged_in(support.make_admin())
    by_name = {net.id: "Сеть: Иванов Иван", support_unit.id: "Поддержка: Петров Пётр"}
    assert card_fields(viewer, concurrent)["head"]["text"] == "; ".join(by_name[u.id] for u in ordered)


def test_card_units_by_comma_and_subordinates_without_self_or_repeats():
    """FR-116 (сценарий 3): «Подразделение» — узлы через запятую; «Подчинённые» только у руководителя: участники узла и вложенных, без него и без повторов."""
    from apps.org.services import structure
    units = make_tree({"Отдел ИТ": {"Сеть": {"Серверы": {}}}, "Бухгалтерия": {}})
    top, net, servers, acc = units["Отдел ИТ"], units["Сеть"], units["Серверы"], units["Бухгалтерия"]
    boss, ann, vova, both, outsider, leaf_head = (
        person("Орлов Олег"), person("Анна Яковлева"), person("Владимир Вавилов"), person("Борис Совместов"),
        person("Чужой Человек"), person("Лист Леонид"))
    make_member(boss, top, mark="head")
    make_member(boss, net, mark="head")  # руководитель двух узлов: сам себе не подчинённый
    make_member(ann, top)
    make_member(vova, net)
    make_member(both, net)
    make_member(both, servers)  # в двух вложенных узлах — один раз
    make_member(outsider, acc)
    make_member(leaf_head, servers, mark="head")
    subs = structure.subordinates_of(boss)
    assert [(p.full_name, p.id) for p in subs] == sorted(
        [("Анна Яковлева", ann.id), ("Владимир Вавилов", vova.id), ("Борис Совместов", both.id), ("Лист Леонид", leaf_head.id)])
    assert all(hasattr(p, "position") for p in subs)
    viewer = support.logged_in(support.make_admin())
    fields = card_fields(viewer, boss)
    labels, field_names = card_labels(viewer, boss)
    for name, label in (("units", "Подразделение"), ("head", "Руководитель"), ("subordinates", "Подчинённые")):
        assert name in field_names and labels.get(name) == label, (name, labels)
    assert fields["units"]["text"] == "Отдел ИТ, Сеть"
    text = fields["subordinates"]["text"]
    assert all(name in text for name in ("Анна Яковлева", "Владимир Вавилов", "Борис Совместов", "Лист Леонид"))
    assert "Чужой Человек" not in text and "Орлов Олег" not in text and text.count("Борис Совместов") == 1
    assert fields["subordinates"]["empty"] == "false"
    # обычный участник и руководитель узла без подчинённых
    assert "subordinates" not in card_fields(viewer, ann)
    assert structure.subordinates_of(ann) == []
    empty = card_fields(viewer, person_in_empty_unit_head())["subordinates"]
    assert empty["text"] == "нет" and empty["empty"] == "true"
    deputy = person("Заместов Захар")
    make_member(deputy, acc, mark="deputy")
    assert "subordinates" not in card_fields(viewer, deputy)


def person_in_empty_unit_head():
    """Руководитель узла, где больше никого нет."""
    unit = support_org.make_unit("Одиночный отдел")
    user = person("Одинцов Олег")
    make_member(user, unit, mark="head")
    return user


def test_heads_follow_new_position_after_move(django_capture_on_commit_callbacks):
    """FR-115: руководители читаются по текущему положению — после перевода участника и после переноса узла карточка показывает новых."""
    from apps.org.services import membership, structure
    actor = support.make_admin()
    units = make_tree({"Отдел ИТ": {"Сеть": {}, "Поддержка": {}}, "Бухгалтерия": {}})
    top, net, helpdesk, acc = units["Отдел ИТ"], units["Сеть"], units["Поддержка"], units["Бухгалтерия"]
    net_head, help_head, acc_head, employee = (
        person("Сетевой Сергей"), person("Помощников Павел"), person("Бухов Борис"), person("Сидоров Сидор"))
    make_member(net_head, net, mark="head")
    make_member(help_head, helpdesk, mark="head")
    make_member(acc_head, acc, mark="head")
    make_member(employee, net)
    viewer = support.logged_in(support.make_admin())
    assert card_fields(viewer, employee)["head"]["text"] == "Сетевой Сергей"
    with django_capture_on_commit_callbacks(execute=True):
        assert membership.transfer_member(employee, net, helpdesk, actor=actor) is True
    assert heads_by_unit(employee) == {helpdesk.id: (["Помощников Павел"], helpdesk.id)}
    assert card_fields(viewer, employee)["head"]["text"] == "Помощников Павел"
    # узел без руководителей переезжает: руководители берутся из нового вышестоящего узла
    lone = support_org.make_unit("Склад", parent=top)
    member = person("Складов Семён")
    make_member(member, lone)
    top_head = person("Орлов Олег")
    make_member(top_head, top, mark="head")
    assert heads_by_unit(member) == {lone.id: (["Орлов Олег"], top.id)}
    with django_capture_on_commit_callbacks(execute=True):
        structure.move_unit(lone, acc, actor=actor)
    assert heads_by_unit(member) == {lone.id: (["Бухов Борис"], acc.id)}
    assert card_fields(viewer, member)["head"]["text"] == "Бухов Борис"


# --- FR-117 -------------------------------------------------------------------------------------

def test_head_mark_gives_no_permissions_and_no_manager_role(django_capture_on_commit_callbacks):
    """FR-117 (сценарий 3.8): отметка руководителя не даёт прав и не выдаёт роль «Руководитель»; роль «Руководитель» не делает человека руководителем узла."""
    from apps.core.services import permissions
    from apps.org.services import membership
    actor = support.make_admin()
    unit = support_org.make_unit("Сеть")
    head, manager_role_holder = person("Орлов Олег"), support.make_employee(
        full_name="Менеджеров Максим", roles=[support.role_by_name(support.MANAGER_ROLE)])
    make_member(head, unit)
    make_member(manager_role_holder, unit)
    roles_before = set(head.roles.values_list("name", flat=True))
    permissions_before = permissions.permissions_of(head)
    with django_capture_on_commit_callbacks(execute=True):
        membership.set_marks(unit, heads=[head], actor=actor)
    assert model("org.Membership").objects.get(user=head, unit=unit).mark == "head"
    assert set(head.roles.values_list("name", flat=True)) == roles_before == set()
    assert support.MANAGER_ROLE not in set(head.roles.values_list("name", flat=True))
    assert permissions.permissions_of(head) == permissions_before == frozenset()
    event = model("core.AuditEvent").objects.get(action="unit.marks_changed", object_id=str(unit.pk))
    assert event.before["heads"] == [] and event.after["heads"] == ["Орлов Олег"]
    client = support.logged_in(head)
    for path in ("/staff/", "/roles/", "/audit/", "/structure/"):
        assert client.get(path).status_code == 403, path
    assert client.get("/me/").status_code == 200
    # обратное направление: роль «Руководитель» без отметки не делает руководителем
    from apps.org.services import structure
    assert [p.full_name for item in structure.heads_of(head) for p in item.heads] == []
    assert [p.full_name for item in structure.heads_of(manager_role_holder) for p in item.heads] == ["Орлов Олег"]
    assert structure.subordinates_of(manager_role_holder) == []
    assert "subordinates" not in card_fields(support.logged_in(support.make_admin()), manager_role_holder)


# --- общие сервисы ------------------------------------------------------------------------------

def test_heads_and_units_public_services_for_other_slices(django_capture_on_commit_callbacks):
    """FR-115, FR-116: `units_of` и `heads_of` — общие сервисы: порядок по `path`, значения `PersonRef`/`UnitRef`/`HeadsOf`, заблокированный сохраняет узлы и руководителей, уволенный и не участник — пусто."""
    import dataclasses
    from apps.org import services
    from apps.org.services import people, structure
    units = make_tree({"Отдел ИТ": {"Сеть": {}}, "Бухгалтерия": {}})
    top, net, acc = units["Отдел ИТ"], units["Сеть"], units["Бухгалтерия"]
    blocked_head = person("Блокирован Борис", position="Старший инженер")
    blocked_head.state = "blocked"
    blocked_head.save(update_fields=["state"])
    employee = person("Сидоров Сидор")
    make_member(blocked_head, top, mark="head")
    make_member(employee, acc)
    make_member(employee, net)
    refs = structure.units_of(employee)
    assert [r.id for r in refs] == [u.id for u in sorted((net, acc), key=lambda u: u.path)]
    assert refs == sorted(refs, key=lambda r: r.path)
    ref = refs[0]
    assert isinstance(ref, services.UnitRef) and ref.name in {"Сеть", "Бухгалтерия"} and ref.kind == "department"
    assert ref.path == model("org.Unit").objects.get(pk=ref.id).path
    with pytest.raises(dataclasses.FrozenInstanceError):
        ref.name = "Другое"
    heads = structure.heads_of(employee)
    assert all(isinstance(item, services.HeadsOf) for item in heads)
    by_unit = {item.unit.id: item for item in heads}
    net_item = by_unit[net.id]
    assert net_item.source.id == top.id and [p.id for p in net_item.heads] == [blocked_head.id]
    head_ref = net_item.heads[0]
    assert isinstance(head_ref, services.PersonRef)
    assert (head_ref.id, head_ref.full_name, head_ref.position) == (blocked_head.id, "Блокирован Борис", "Старший инженер")
    assert by_unit[acc.id].heads == [] and by_unit[acc.id].source is None
    assert [r.id for r in structure.units_of(blocked_head)] == [top.id]  # блокировка членств не снимает
    assert structure.units_of(person("Без Узла")) == [] and structure.heads_of(person("Без Узла Второй")) == []
    gone = person("Уволенов Ульян")
    make_member(gone, acc)
    with django_capture_on_commit_callbacks(execute=True):
        people.dismiss(gone, actor=support.make_admin())  # служба снимает членства (FR-125)
    gone.refresh_from_db()
    assert gone.state == "dismissed"
    assert structure.units_of(gone) == []
