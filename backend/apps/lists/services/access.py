"""Сервис: права на чтение, правку и управление (срез 006).

Единственное место решений о правах `lists` (план, «Права и видимость»; FR-501, FR-512…FR-514) и единственная функция
замка списка `lock_list` (CONTRACT-006, 5.2)."""
from typing import NamedTuple

from django.apps import apps
from django.db import connection
from django.db.models import Q
from django.http import Http404

from apps.core.models import UserState
from apps.core.services import permissions
from apps.lists.models import Access, List, ListProcess, ProcessStage, ProcessStageAccess, Record

MANAGE_PERMISSION = "lists.manage"


class Scope(NamedTuple):
    """Права сотрудника на время запроса: `manage` — право управляющего, `readable` и `editable` — номера списков."""

    manage: bool
    readable: frozenset
    editable: frozenset


_EMPTY = Scope(False, frozenset(), frozenset())


class StageScope(NamedTuple):
    """Права на стадии списка: номера стадий, которые сотрудник читает и правит."""

    read: frozenset
    edit: frozenset


def lock_list(list_id: int, *, shared: bool) -> None:
    """Замок списка на время транзакции (И1): разделяемый — правка записей, исключительный — схема и права.

    Вызывается только внутри транзакции; ключ — `hashtext('lists.list')` и номер списка по модулю 2^31."""
    with connection.cursor() as cursor:
        if shared:
            cursor.execute("SELECT pg_advisory_xact_lock_shared(hashtext('lists.list'), %s)", [list_id % 2147483648])
        else:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtext('lists.list'), %s)", [list_id % 2147483648])


def scope(user) -> Scope:
    """Права сотрудника; считаются один раз на запрос и хранятся в `user._lists_scope`.

    Не `active` (уволен, заблокирован, приглашён) — пустой `Scope`, до обращения к ролям и узлам. «Правят» входят в
    `readable`. Право подразделения действует по цепочке узлов сотрудника (предки включены)."""
    cached = getattr(user, "_lists_scope", None)
    if cached is not None:
        return cached
    result = _count(user)
    try:
        user._lists_scope = result
    except AttributeError:
        pass
    return result


def _count(user) -> Scope:
    if not getattr(user, "is_authenticated", False) or getattr(user, "state", None) != UserState.ACTIVE:
        return _EMPTY
    manage = permissions.has_permission(user, MANAGE_PERMISSION)
    role_ids = permissions.role_ids(user)
    units: frozenset = frozenset()
    if apps.is_installed("apps.org"):
        from apps.org.services import structure

        units = structure.unit_chain_ids(user)
    readable: set[int] = set()
    editable: set[int] = set()
    if role_ids or units:
        rows = Access.objects.filter(Q(role_id__in=role_ids) | Q(unit_id__in=units)).values_list("list_id", "level")
        for list_id, level in rows:
            readable.add(list_id)
            if level == Access.Level.EDIT:
                editable.add(list_id)
    return Scope(manage, frozenset(readable), frozenset(editable))


def can_manage(user) -> bool:
    """Право управляющего (`lists.manage`) у действующего сотрудника."""
    return scope(user).manage


def can_read(user, lst) -> bool:
    """Читает список: управляющий — любой, остальные — по наборам «Читают» и «Правят»."""
    current = scope(user)
    return current.manage or lst.pk in current.readable


def can_edit(user, lst) -> bool:
    """Правит записи списка: управляющий — любого, остальные — по набору «Правят»."""
    current = scope(user)
    return current.manage or lst.pk in current.editable


def in_edit_set(user, lst) -> bool:
    """Только по набору «Правят», без права управляющего (получатели напоминаний, FR-530)."""
    return lst.pk in scope(user).editable


def edits_any(user) -> bool:
    """Правит хотя бы один список или управляет: для подсказок людей и узлов."""
    current = scope(user)
    return current.manage or bool(current.editable)


def sees_section(user) -> bool:
    """Раздел «Списки» виден: управляющему или тому, кому открыт хоть один список (FR-501).

    Зовётся пунктом меню на каждой странице портала: управляющему ответ даёт право из кэша прав, без расчёта наборов
    (иначе +3–4 запроса на любую страницу, NFR-002 среза 001 — `test_capacity`)."""
    cached = getattr(user, "_lists_scope", None)
    if cached is None and getattr(user, "is_authenticated", False) \
            and getattr(user, "state", None) == UserState.ACTIVE \
            and permissions.has_permission(user, MANAGE_PERMISSION):
        return True
    current = scope(user)
    return current.manage or bool(current.readable)


def get_list(user, list_id: int) -> List:
    """Список или `Http404`, если его нет или он не читается (ответ тот же, FR-514)."""
    lst = List.objects.filter(pk=list_id).first()
    if lst is None or not can_read(user, lst):
        raise Http404("Список не найден")
    return lst


def get_record(user, list_id: int, number: int) -> Record:
    """Запись списка по номеру или `Http404`, если её нет или список не читается."""
    lst = get_list(user, list_id)
    record = Record.objects.filter(list=lst, number=number).first()
    if record is None:
        raise Http404("Запись не найдена")
    return record


# --- права стадий (срез 015) -----------------------------------------------------------------------------

def stage_scope(user, lst):
    """Права на стадии списка или `None`, если ограничений нет (управляющий, процесс выключен).

    Кэш на запрос: `user._lists_stage_scope` — словарь `id списка → StageScope | None`. Пустой набор прав
    стадии наследует права списка; явный набор только сужает. Считается по ролям и цепочке узлов, как `scope`.
    """
    cache = getattr(user, "_lists_stage_scope", None)
    if cache is None:
        cache = {}
        try:
            user._lists_stage_scope = cache
        except AttributeError:
            pass
    if lst.pk in cache:
        return cache[lst.pk]
    result = _stage_count(user, lst)
    cache[lst.pk] = result
    return result


def _stage_count(user, lst):
    current = scope(user)
    if current.manage:
        return None
    if not getattr(user, "is_authenticated", False) or getattr(user, "state", None) != UserState.ACTIVE:
        return StageScope(frozenset(), frozenset())
    if not ListProcess.objects.filter(list_id=lst.pk, enabled=True).exists():
        return None
    role_ids = permissions.role_ids(user)
    units: frozenset = frozenset()
    if apps.is_installed("apps.org"):
        from apps.org.services import structure

        units = structure.unit_chain_ids(user)
    stages = list(ProcessStage.objects.filter(process__list_id=lst.pk).values_list("pk", flat=True))
    rows = list(ProcessStageAccess.objects.filter(stage_id__in=stages).values_list("stage_id", "level", "role_id", "unit_id"))
    by_stage: dict[int, list] = {}
    for stage_id, level, role_id, unit_id in rows:
        by_stage.setdefault(stage_id, []).append((level, role_id, unit_id))
    readable: set[int] = set()
    editable: set[int] = set()
    for stage_id in stages:
        accesses = by_stage.get(stage_id, [])
        if not accesses:
            readable.add(stage_id)
            editable.add(stage_id)
            continue
        for level, role_id, unit_id in accesses:
            matches = (role_id is not None and role_id in role_ids) or (unit_id is not None and unit_id in units)
            if not matches:
                continue
            readable.add(stage_id)
            if level == ProcessStageAccess.Level.EDIT:
                editable.add(stage_id)
    return StageScope(frozenset(readable), frozenset(editable))


def can_read_record(user, record) -> bool:
    """Запись читается: список читается и стадия доступна (запись без стадии — по правам списка)."""
    lst = record.list
    if not can_read(user, lst):
        return False
    if record.stage_id is None:
        return True
    current = stage_scope(user, lst)
    return current is None or record.stage_id in current.read or record.stage_id in current.edit


def can_edit_record(user, record) -> bool:
    """Запись правится: список правится и стадия в наборе правки (запись без стадии — по правам списка)."""
    lst = record.list
    if not can_edit(user, lst):
        return False
    if record.stage_id is None:
        return True
    current = stage_scope(user, lst)
    return current is None or record.stage_id in current.edit


def global_record_condition(user):
    """Условие видимости записей по всем читаемым спискам: `None` — ограничений нет (управляющий)."""
    current = scope(user)
    if current.manage:
        return None
    condition = Q(pk__in=[])
    for lst in List.objects.filter(pk__in=current.readable).only("pk"):
        stage = stage_scope(user, lst)
        if stage is None:
            condition |= Q(list_id=lst.pk)
        else:
            condition |= (Q(list_id=lst.pk, stage__isnull=True)
                          | Q(list_id=lst.pk, stage_id__in=stage.read | stage.edit))
    return condition


def can_read_stage(user, lst, stage_id) -> bool:
    """Стадия видна: ограничений нет или она в наборе чтения/правки."""
    current = stage_scope(user, lst)
    return current is None or stage_id in current.read or stage_id in current.edit


def record_condition(user, lst):
    """Условие выборки записей по правам стадий: `None` — ограничений нет, иначе `Q` для фильтра."""
    current = stage_scope(user, lst)
    if current is None:
        return None
    return Q(stage__isnull=True) | Q(stage_id__in=current.read | current.edit)
