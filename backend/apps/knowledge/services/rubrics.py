"""Рубрики: дерево до трёх уровней (PLAN-005, «Рубрики, теги, главная»; FR-418, FR-419, FR-438).

Все записи дерева идут в одной транзакции под замком `pg_advisory_xact_lock(hashtextextended('knowledge.rubrics', 0))`:
глубина и потомки считаются под ним, поэтому два встречных переноса не дают цикла. Дерево — сотни строк, обход в
памяти. Ключ замка — параметр запроса.
"""
from typing import NamedTuple

from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.db.models import Value
from django.db.models.functions import Lower
from django.http import Http404

from apps.core.services import audit, permissions

from ..models import Article, Rubric
from . import RubricError

LOCK_KEY = "knowledge.rubrics"
MAX_DEPTH = 3
MAX_NAME = 100
OBJECT_TYPE = "knowledge.rubric"


class RubricNode(NamedTuple):
    """Узел дерева рубрик: рубрика и её подрубрики (по названию без учёта регистра)."""

    rubric: Rubric
    children: list


def _require_manage(user) -> None:
    if not permissions.has_permission(user, "knowledge.manage"):
        raise PermissionDenied


def _lock() -> None:
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [LOCK_KEY])


def _load() -> dict[int, Rubric]:
    """Все рубрики одним запросом (под замком)."""
    return {r.pk: r for r in Rubric.objects.all()}


def _path(all_rubrics: dict[int, Rubric], pk: int) -> str:
    """Названия от корня до рубрики через « / »."""
    names = []
    node = all_rubrics.get(pk)
    while node is not None:
        names.append(node.name)
        node = all_rubrics.get(node.parent_id) if node.parent_id else None
    return " / ".join(reversed(names))


def _snapshot(all_rubrics: dict[int, Rubric], pk: int) -> dict:
    return {"name": all_rubrics[pk].name, "path": _path(all_rubrics, pk)}


def _clean_name(name) -> str:
    name = (name or "").strip()
    if not name:
        raise RubricError("name_empty", "name")
    if len(name) > MAX_NAME:
        raise RubricError("name_too_long", "name")
    return name


def _check_unique(name: str, parent_id, exclude_pk=None) -> None:
    """Сосед с тем же названием без учёта регистра (сравнение — как у ограничения базы, `Lower` на стороне базы)."""
    clash = Rubric.objects.annotate(lname=Lower("name")).filter(parent_id=parent_id, lname=Lower(Value(name)))
    if exclude_pk is not None:
        clash = clash.exclude(pk=exclude_pk)
    if clash.exists():
        raise RubricError("name_duplicate", "name")


def create(user, name: str, parent_id: int | None) -> Rubric:
    """Создаёт рубрику (право `knowledge.manage`); журнал `knowledge.rubric_created`."""
    _require_manage(user)
    with transaction.atomic():
        _lock()
        name = _clean_name(name)
        all_rubrics = _load()
        depth = 1
        if parent_id is not None:
            parent = all_rubrics.get(parent_id)
            if parent is None:
                raise RubricError("parent_missing", "parent")
            if parent.depth >= MAX_DEPTH:
                raise RubricError("too_deep", "parent")
            depth = parent.depth + 1
        _check_unique(name, parent_id)
        rubric = Rubric.objects.create(name=name, parent_id=parent_id, depth=depth)
        all_rubrics[rubric.pk] = rubric
        audit.record("knowledge.rubric_created", actor=user, object_type=OBJECT_TYPE, object_id=rubric.pk,
                     after=_snapshot(all_rubrics, rubric.pk))
    return rubric


def rename(user, rubric_id: int, name: str) -> Rubric:
    """Переименовывает рубрику («Общее» — тоже); журнал `knowledge.rubric_renamed` (было / стало, путь)."""
    _require_manage(user)
    with transaction.atomic():
        _lock()
        all_rubrics = _load()
        rubric = all_rubrics.get(rubric_id)
        if rubric is None:
            raise Http404("Рубрики нет")
        name = _clean_name(name)
        _check_unique(name, rubric.parent_id, exclude_pk=rubric.pk)
        before = _snapshot(all_rubrics, rubric.pk)
        rubric.name = name
        rubric.save(update_fields=["name"])
        audit.record("knowledge.rubric_renamed", actor=user, object_type=OBJECT_TYPE, object_id=rubric.pk,
                     before=before, after=_snapshot(all_rubrics, rubric.pk))
    return rubric


def _descendants(all_rubrics: dict[int, Rubric]) -> dict[int | None, list[int]]:
    children: dict[int | None, list[int]] = {}
    for rubric in all_rubrics.values():
        children.setdefault(rubric.parent_id, []).append(rubric.pk)
    return children


def _height(children: dict, pk: int) -> int:
    """Число уровней поддерева, считая саму рубрику."""
    return 1 + max((_height(children, child) for child in children.get(pk, [])), default=0)


def move(user, rubric_id: int, parent_id: int | None) -> Rubric:
    """Переносит рубрику под другого родителя (`None` — в корень); `depth` поддерева пересчитывается здесь же.

    Порядок отказов (решение Opus 35): `parent_self`, `parent_descendant`, `default_immovable`, `depth_exceeded`
    (поле `parent`), затем `name_duplicate` (поле `name`). Журнал `knowledge.rubric_moved`.
    """
    _require_manage(user)
    with transaction.atomic():
        _lock()
        all_rubrics = _load()
        rubric = all_rubrics.get(rubric_id)
        if rubric is None:
            raise Http404("Рубрики нет")
        parent = None
        if parent_id is not None:
            parent = all_rubrics.get(parent_id)
            if parent is None:
                raise RubricError("parent_missing", "parent")
        children = _descendants(all_rubrics)
        if parent_id == rubric.pk:
            raise RubricError("parent_self", "parent")
        if parent is not None:
            node = parent
            while node is not None:
                if node.parent_id == rubric.pk:
                    raise RubricError("parent_descendant", "parent")
                node = all_rubrics.get(node.parent_id) if node.parent_id else None
            if rubric.is_default:
                raise RubricError("default_immovable", "parent")
        new_depth = parent.depth + 1 if parent is not None else 1
        if new_depth + _height(children, rubric.pk) - 1 > MAX_DEPTH:
            raise RubricError("depth_exceeded", "parent")
        _check_unique(rubric.name, parent_id, exclude_pk=rubric.pk)

        before = _snapshot(all_rubrics, rubric.pk)
        rubric.parent_id = parent_id
        rubric.depth = new_depth
        changed = [rubric]
        queue = [rubric]
        while queue:
            current = queue.pop()
            for child_pk in children.get(current.pk, []):
                child = all_rubrics[child_pk]
                child.depth = current.depth + 1
                changed.append(child)
                queue.append(child)
        Rubric.objects.bulk_update(changed, ["parent", "depth"])
        audit.record("knowledge.rubric_moved", actor=user, object_type=OBJECT_TYPE, object_id=rubric.pk,
                     before=before, after=_snapshot(all_rubrics, rubric.pk))
    return rubric


def delete(user, rubric_id: int) -> None:
    """Удаляет пустую рубрику; подписки уходят каскадом (FR-437).

    «Общее» — `default_undeletable`; подрубрики или статьи (в том числе в корзине) — `not_empty`. Журнал
    `knowledge.rubric_deleted` (название и путь — в `before`).
    """
    _require_manage(user)
    with transaction.atomic():
        _lock()
        all_rubrics = _load()
        rubric = all_rubrics.get(rubric_id)
        if rubric is None:
            raise Http404("Рубрики нет")
        if rubric.is_default:
            raise RubricError("default_undeletable")
        if any(r.parent_id == rubric.pk for r in all_rubrics.values()) \
                or Article.objects.filter(rubric_id=rubric.pk).exists():
            raise RubricError("not_empty")
        before = _snapshot(all_rubrics, rubric.pk)
        pk = rubric.pk
        rubric.delete()
        audit.record("knowledge.rubric_deleted", actor=user, object_type=OBJECT_TYPE, object_id=pk, before=before)


def tree() -> list[RubricNode]:
    """Дерево рубрик одним запросом, собирается в памяти; среди соседей — по названию без учёта регистра."""
    rows = list(Rubric.objects.order_by(Lower("name"), "id"))
    nodes = {r.pk: RubricNode(r, []) for r in rows}
    roots: list[RubricNode] = []
    for row in rows:
        (nodes[row.parent_id].children if row.parent_id in nodes else roots).append(nodes[row.pk])
    return roots
