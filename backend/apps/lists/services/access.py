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
from apps.lists.models import Access, List, Record

MANAGE_PERMISSION = "lists.manage"


class Scope(NamedTuple):
    """Права сотрудника на время запроса: `manage` — право управляющего, `readable` и `editable` — номера списков."""

    manage: bool
    readable: frozenset
    editable: frozenset


_EMPTY = Scope(False, frozenset(), frozenset())


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
    """Раздел «Списки» виден: управляющему или тому, кому открыт хоть один список (FR-501)."""
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
