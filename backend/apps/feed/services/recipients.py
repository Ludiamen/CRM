"""Строка адресатов записи ленты."""
from typing import NamedTuple

from django.apps import apps
from apps.core.models import User
from apps.feed.models import Recipient
from apps.feed.services.errors import FeedError


class Line(NamedTuple):
    items: list[str]
    more: int


class Targets(NamedTuple):
    to_all: bool
    unit_ids: tuple[int, ...]
    user_ids: tuple[int, ...]


def _values(values):
    if hasattr(values, "getlist"):
        return values.getlist("to")
    if isinstance(values, dict):
        raw = values.get("to", ())
    else:
        raw = values
    if raw is None:
        return []
    if isinstance(raw, (str, bytes)):
        return [raw]
    return list(raw)


def _target_parts(values):
    unit_ids: list[int] = []
    user_ids: list[int] = []
    to_all = False
    for value in _values(values):
        if value == "all":
            to_all = True
        elif isinstance(value, str) and value.startswith("u") and value[1:].isdigit():
            unit_ids.append(int(value[1:]))
        elif isinstance(value, str) and value.startswith("p") and value[1:].isdigit():
            user_ids.append(int(value[1:]))
        else:
            raise FeedError("recipient_invalid", "to")
    return to_all, list(dict.fromkeys(unit_ids)), list(dict.fromkeys(user_ids))


def parse(viewer, values, *, saved=None) -> Targets:
    """Разобрать адресатов; при правке проверять наличие/состояние только у добавленных."""
    to_all, unit_ids, user_ids = _target_parts(values)
    saved_all = False
    saved_units: list[int] = []
    saved_users: list[int] = []
    if saved is not None:
        if isinstance(saved, Targets):
            saved_all, saved_units, saved_users = saved
        else:
            saved_all, saved_units, saved_users = _target_parts(saved)
        if (not to_all and saved_all
                or not set(unit_ids).issuperset(saved_units)
                or not set(user_ids).issuperset(saved_users)):
            raise FeedError("only_add_recipients", "to")

    to_all = to_all or saved_all
    if not saved_all and to_all and not viewer.post_all:
        raise FeedError("post_all_denied", "to")
    new_units = set(unit_ids) - set(saved_units)
    new_users = set(user_ids) - set(saved_users)

    if len(unit_ids) + len(user_ids) + int(to_all) > 50:
        raise FeedError("too_many_recipients", "to")

    if new_units:
        if not apps.is_installed("apps.org"):
            raise FeedError("recipient_invalid", "to")
        from apps.org.services import structure

        if set(structure.unit_refs(new_units)) != new_units:
            raise FeedError("recipient_invalid", "to")

    if new_users:
        found = set(User.objects.exclude(state__in=("blocked", "dismissed"))
                    .filter(pk__in=new_users).values_list("pk", flat=True))
        if found != new_users:
            raise FeedError("recipient_invalid", "to")

    if not to_all and not unit_ids and not user_ids:
        raise FeedError("no_recipients", "to")

    return Targets(to_all, tuple(unit_ids), tuple(user_ids))


def _rows(post):
    return list(Recipient.objects.filter(post_id=post.pk).select_related("user").order_by("pk"))


def _unit_refs(unit_ids):
    if not unit_ids or not apps.is_installed("apps.org"):
        return {}
    from apps.org.services import structure

    return structure.unit_refs(unit_ids)


def _short_name(full_name: str) -> str:
    """Краткая форма персонального адресата для строки записи: «Фамилия И. О.» (FR-603, сценарий 5).

    Инициалы берутся от всех слов после фамилии; одно слово не меняется, уже краткая
    форма («Петров И. И.») остаётся как есть.
    """
    parts = (full_name or "").split()
    if len(parts) < 2:
        return full_name or ""
    initials = " ".join(f"{part[:1].upper()}." for part in parts[1:])
    return f"{parts[0]} {initials}"


def full(post, *, rows=None, users=None, units=None, short=False) -> list[str]:
    """Все адресаты в контрактном порядке; аргументы — уже загруженные данные страницы.

    `short=True` — персональные адресаты краткой формой «Фамилия И. О.» (строка записи);
    полный список `/feed/<id>/to/` остаётся с полными ФИО (FR-603: «полный список по нажатию»).
    """
    rows = _rows(post) if rows is None else list(rows)
    users = users or {}
    unit_ids = list(dict.fromkeys(row.unit_id for row in rows if row.unit_id is not None))
    units = _unit_refs(unit_ids) if units is None else units

    items = ["Всем"] if post.to_all else []
    for unit_id in unit_ids:
        unit = units.get(unit_id)
        items.append(unit.name if unit is not None else "Подразделение удалено")

    seen = set()
    for row in rows:
        if row.user_id is None or row.user_id in seen:
            continue
        seen.add(row.user_id)
        person = users.get(row.user_id)
        if person is None:
            person = row.user
        name = _short_name(person.full_name) if short else person.full_name
        if person.state == "dismissed":
            name += " (уволен)"
        items.append(name)
    return items


def line(post, *, rows=None, users=None, units=None) -> Line:
    """Первые пять адресатов и число остальных; люди — краткой формой «Фамилия И. О.»."""
    items = full(post, rows=rows, users=users, units=units, short=True)
    return Line(items[:5], max(0, len(items) - 5))
