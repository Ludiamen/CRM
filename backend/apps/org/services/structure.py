"""Структура: отделы и дерево (PLAN-002, «Дерево»; CONTRACT-002, § 4.1).

Все изменения структуры идут в транзакции и берут замок строки корня (`lock_root`) до первой записи.
Службы прав не проверяют: это делают представления.
"""
from django.db import transaction
from django.db.models import F, Q, Value
from django.db.models.functions import Concat, Substr

from apps.core import events, extensions
from apps.core.services import audit
from apps.core.services.permissions import forget_users
from apps.org.models import Membership, Unit
from apps.org.services.errors import OrgError
from apps.org.services.refs import HeadsOf, PersonRef, UnitRef

NAME_MAX = 150
_NAME_TAKEN = "У этого родителя уже есть узел с таким названием: названия узлов под одним родителем не повторяются."


def name_key(text: str) -> str:
    """`Unit.name_key`: без крайних и повторных пробелов, в нижнем регистре, «ё» -> «е»."""
    return " ".join(text.split()).lower().replace("ё", "е")


def _chain_ids(path: str) -> list[int]:
    """Номера узлов цепочки по `path`, от корня к узлу."""
    return [int(part) for part in path.split("/") if part]


def lock_root() -> Unit:
    """Замок строки корня: берут все функции, меняющие структуру, членства и состояние людей."""
    return Unit.objects.select_for_update().get(is_root=True)


def root() -> Unit:
    return Unit.objects.get(is_root=True)


def _check_name(name: str) -> str:
    name = (name or "").strip()
    if not name:
        raise OrgError("name_required", "Название узла не может быть пустым.")
    if len(name) > NAME_MAX:
        raise OrgError("name_too_long", f"Название узла не длиннее {NAME_MAX} знаков.")
    return name


def _check_kind(kind: str, parent: Unit | None) -> None:
    """Отдел — только под отделом; команда — под отделом или командой; корень создаёт только миграция."""
    if kind not in (Unit.Kind.DEPARTMENT, Unit.Kind.TEAM):
        raise OrgError("kind_rules", "Неизвестный вид узла: нужен отдел или команда.")
    if parent is None:
        raise OrgError("kind_rules", "Узел должен лежать под другим узлом: корень один и уже создан.")
    if kind == Unit.Kind.DEPARTMENT and parent.kind != Unit.Kind.DEPARTMENT:
        raise OrgError("kind_rules", "Отдел подчиняется только отделу.")


def _check_free_name(parent: Unit | None, key: str, exclude_pk=None) -> None:
    if parent is None:
        return
    taken = Unit.objects.filter(parent=parent, name_key=key)
    if exclude_pk is not None:
        taken = taken.exclude(pk=exclude_pk)
    if taken.exists():
        raise OrgError("name_taken", _NAME_TAKEN)


def create_unit(*, kind, name, parent, description="", actor, ip=None) -> Unit:
    with transaction.atomic():
        lock_root()
        name = _check_name(name)
        if parent is not None:
            parent = Unit.objects.get(pk=parent.pk)
        _check_kind(kind, parent)
        key = name_key(name)
        _check_free_name(parent, key)
        unit = Unit.objects.create(
            kind=kind, name=name, name_key=key, description=description or "", parent=parent,
            depth=parent.depth + 1, path="")
        unit.path = f"{parent.path}{unit.pk}/"
        unit.save(update_fields=["path"])
        audit.record(
            "unit.created", actor=actor, object_type="unit", object_id=unit.pk, ip=ip,
            after={"kind": unit.kind, "name": unit.name, "description": unit.description, "parent": parent.name})
    return unit


def update_unit(unit, *, name, description, actor, ip=None) -> Unit:
    with transaction.atomic():
        lock_root()
        unit = Unit.objects.get(pk=unit.pk)
        name = _check_name(name)
        key = name_key(name)
        description = description or ""
        _check_free_name(unit.parent, key, exclude_pk=unit.pk)
        before, after = {}, {}
        if name != unit.name:
            before["name"], after["name"] = unit.name, name
        if description != unit.description:
            before["description"], after["description"] = unit.description, description
        if after:
            unit.name, unit.name_key, unit.description = name, key, description
            unit.save(update_fields=["name", "name_key", "description"])
            audit.record(
                "unit.updated", actor=actor, object_type="unit", object_id=unit.pk, ip=ip, before=before, after=after)
        elif unit.name_key != key:
            unit.name_key = key
            unit.save(update_fields=["name_key"])
    return unit


def move_unit(unit, new_parent, *, actor, ip=None) -> Unit:
    with transaction.atomic():
        lock_root()
        unit = Unit.objects.get(pk=unit.pk)
        new_parent = Unit.objects.get(pk=new_parent.pk)
        if unit.is_root:
            raise OrgError("root_protected", "Корневой отдел нельзя перенести.")
        if new_parent.path.startswith(unit.path):
            raise OrgError("cycle", "Так получится цикл в подчинении: узел нельзя перенести в самого себя или в его вложенный узел.")
        if unit.parent_id == new_parent.pk:
            return unit
        _check_kind(unit.kind, new_parent)
        _check_free_name(new_parent, unit.name_key, exclude_pk=unit.pk)
        old_parent = unit.parent
        old_path = unit.path
        new_path = f"{new_parent.path}{unit.pk}/"
        delta = (new_parent.depth + 1) - unit.depth
        # Все чтения для состава события `access.changed` — до записи путей: после неё цепочки уже новые.
        subtree_ids = set(
            Membership.objects.filter(unit__path__startswith=old_path).values_list("user_id", flat=True).distinct())
        user_ids = list(subtree_ids)
        marked = [Membership.Mark.HEAD, Membership.Mark.DEPUTY]
        old_chain = _chain_ids(old_parent.path)
        new_chain = _chain_ids(new_parent.path)
        former_heads = set(
            Membership.objects.filter(unit_id__in=old_chain, mark__in=marked).values_list("user_id", flat=True))
        kept_heads = set(
            Membership.objects.filter(unit_id__in=new_chain, mark__in=marked, user_id__in=former_heads)
            .values_list("user_id", flat=True)) if former_heads else set()
        event_ids = sorted(subtree_ids | (former_heads - kept_heads))
        Unit.objects.filter(path__startswith=old_path).update(
            path=Concat(Value(new_path), Substr("path", len(old_path) + 1)), depth=F("depth") + delta)
        Unit.objects.filter(pk=unit.pk).update(parent=new_parent)
        forget_users(user_ids, publish=False)
        if event_ids:
            events.publish("access.changed", user_ids=event_ids)
        audit.record(
            "unit.moved", actor=actor, object_type="unit", object_id=unit.pk, ip=ip,
            before={"parent": old_parent.name, "parent_id": old_parent.pk},
            after={"parent": new_parent.name, "parent_id": new_parent.pk})
        unit.refresh_from_db()
    return unit


def delete_unit(unit, *, actor, ip=None) -> None:
    with transaction.atomic():
        lock_root()
        unit = Unit.objects.get(pk=unit.pk)
        if unit.is_root:
            raise OrgError("root_protected", "Корневой отдел нельзя удалить.")
        if unit.memberships.exists() or unit.children.exists():
            raise OrgError("not_empty", "Узел не пуст: в нём есть участники или вложенные узлы.")  # дополнение 52
        for func in extensions.registered("unit_usage"):
            reason = func(unit.pk)
            if reason:
                raise OrgError("in_use", f"Узел нельзя удалить: {reason}.")
        roles = sorted(unit.unit_roles.values_list("role__name", flat=True))
        before = {"kind": unit.kind, "name": unit.name, "parent": unit.parent.name, "roles": roles}
        pk = unit.pk
        unit.delete()
        audit.record("unit.deleted", actor=actor, object_type="unit", object_id=pk, ip=ip, before=before)


def descendants(unit, *, include_self=True):
    """Узлы поддерева по началу `path`, порядок по `path` (байтовый, поле с `db_collation="C"`)."""
    found = Unit.objects.filter(path__startswith=unit.path)
    if not include_self:
        found = found.exclude(pk=unit.pk)
    return found.order_by("path")


def units_of(user) -> list[UnitRef]:
    """Узлы, где `user` состоит, по возрастанию `path`; уволенный и не участник — `[]`."""
    if getattr(user, "state", None) == "dismissed":
        return []
    units = Unit.objects.filter(memberships__user=user).order_by("path")
    return [UnitRef(id=u.pk, name=u.name, kind=u.kind, path=u.path) for u in units]


def _unit_ref(unit: Unit) -> UnitRef:
    return UnitRef(id=unit.pk, name=unit.name, kind=unit.kind, path=unit.path)


def unit_chain_ids(user) -> frozenset[int]:
    """Узлы, где `user` состоит, и все их предки по `Unit.path`, включая корень; без членства — `frozenset()`.

    Права подразделений в `lists` действуют по цепочке: право узла покрывает вложенные узлы. Два запроса.
    """
    paths = list(Unit.objects.filter(memberships__user=user).values_list("path", flat=True).distinct())
    result: set[int] = set()
    for path in paths:
        result.update(_chain_ids(path))
    return frozenset(result)


def all_units() -> list[UnitRef]:
    """Все узлы по возрастанию `path` (байтовый порядок, поле с `db_collation="C"`): для выбора и загрузки."""
    return [_unit_ref(u) for u in Unit.objects.order_by("path")]


def unit_refs(ids) -> dict[int, UnitRef]:
    """Узлы по номерам: `id` -> `UnitRef`; несуществующих номеров в словаре нет. Один запрос."""
    wanted = {int(i) for i in ids}
    if not wanted:
        return {}
    return {u.pk: _unit_ref(u) for u in Unit.objects.filter(pk__in=wanted)}


def _person_ref(person) -> PersonRef:
    return PersonRef(id=person.pk, full_name=person.full_name, position=person.position)


def heads_of(user) -> list[HeadsOf]:
    """Руководители `user` по правилу FR-115: по элементу на каждое членство, по возрастанию `path` узла.

    Первый уровень — собственный узел: руководители берутся от него, если `user` там не руководитель и они есть.
    Выше из набора исключается сам `user`; пустой набор ведёт ещё выше. Заместители руководителями не считаются,
    уволенные руководители не берутся. Читается двумя запросами: узлы и членства (отметки руководителей и
    членства `user`), дальше всё в памяти.
    """
    units = {u.pk: u for u in Unit.objects.all()}
    memberships = list(
        Membership.objects.filter(Q(mark=Membership.Mark.HEAD) | Q(user=user)).select_related("user"))
    heads_by_unit: dict[int, list] = {}
    own_units = []
    for m in memberships:
        if m.mark == Membership.Mark.HEAD and m.user.state != "dismissed":
            heads_by_unit.setdefault(m.unit_id, []).append(m.user)
        if m.user_id == user.pk:
            own_units.append(units[m.unit_id])
    result = []
    for unit in sorted(own_units, key=lambda u: u.path):
        chain = [int(part) for part in unit.path.split("/") if part]  # от корня к узлу
        found, source = [], None
        own = heads_by_unit.get(unit.pk, [])
        if own and all(h.pk != user.pk for h in own):
            found, source = own, unit
        else:
            for unit_id in reversed(chain[:-1]):
                above = [h for h in heads_by_unit.get(unit_id, []) if h.pk != user.pk]
                if above:
                    found, source = above, units[unit_id]
                    break
        people = sorted({h.pk: h for h in found}.values(), key=lambda h: (h.full_name, h.pk))
        result.append(HeadsOf(
            unit=_unit_ref(unit), heads=[_person_ref(h) for h in people],
            source=_unit_ref(source) if source else None))
    return result


def subordinates_of(user) -> list[PersonRef]:
    """Участники узлов, где `user` руководитель, и всех вложенных, без `user` и без повторов; по `full_name`, `id`."""
    paths = list(
        Unit.objects.filter(memberships__user=user, memberships__mark=Membership.Mark.HEAD)
        .values_list("path", flat=True))
    if not paths:
        return []
    condition = Q()
    for path in paths:
        condition |= Q(unit__path__startswith=path)
    people = {
        m.user_id: m.user for m in Membership.objects.filter(condition).exclude(user=user).select_related("user")
        if m.user.state != "dismissed"}
    ordered = sorted(people.values(), key=lambda p: (p.full_name, p.pk))
    return [_person_ref(p) for p in ordered]


def work_units_of(user) -> frozenset[int]:
    """Узлы работы `user`: где он состоит, и все узлы, вложенные в узлы, где он руководитель или заместитель.

    Родитель узла участника не входит; уволенный и не участник — `frozenset()`. Два запроса (узлы и членства
    человека), дальше всё в памяти; по текущей структуре, без кэша.
    """
    if getattr(user, "state", None) == "dismissed":
        return frozenset()
    memberships = list(Membership.objects.filter(user=user).values_list("unit_id", "mark"))
    if not memberships:
        return frozenset()
    units = list(Unit.objects.values_list("pk", "path"))
    result = {unit_id for unit_id, _ in memberships}
    marked_ids = {unit_id for unit_id, mark in memberships if mark}
    paths = [path for pk, path in units if pk in marked_ids]
    for pk, path in units:
        if any(path.startswith(top) for top in paths):
            result.add(pk)
    return frozenset(result)


def queue_people(unit_id: int) -> list[PersonRef]:
    """Участники очереди узла: его прямые участники и руководители и заместители всех вышестоящих узлов.

    Без повторов и без уволенных, по `full_name`, затем `id`; несуществующий узел — `[]`. Два запроса.
    """
    path = Unit.objects.filter(pk=unit_id).values_list("path", flat=True).first()
    if path is None:
        return []
    upper = _chain_ids(path)[:-1]
    found = Membership.objects.filter(
        Q(unit_id=unit_id) | Q(unit_id__in=upper, mark__in=[Membership.Mark.HEAD, Membership.Mark.DEPUTY])
    ).exclude(user__state="dismissed").select_related("user")
    people = {m.user_id: m.user for m in found}
    return [_person_ref(p) for p in sorted(people.values(), key=lambda p: (p.full_name, p.pk))]


def direct_members(unit_id: int) -> list[PersonRef]:
    """Прямые участники узла: члены самого узла, без вложенных и вышестоящих (получатели уведомлений).

    Руководитель и заместитель узла входят своим членством. Входят активные и заблокированные; уволенные и
    приглашённые, кто ещё не вошёл, исключены. Без повторов, по `full_name`, затем `id`; несуществующий узел — `[]`.
    Один запрос.
    """
    found = Membership.objects.filter(unit_id=unit_id).exclude(
        user__state__in=["dismissed", "invited"]
    ).select_related("user")
    people = {m.user_id: m.user for m in found}
    return [_person_ref(p) for p in sorted(people.values(), key=lambda p: (p.full_name, p.pk))]
