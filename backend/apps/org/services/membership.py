"""Членство сотрудников в отделах и командах (PLAN-002, «Членство»; CONTRACT-002, § 4.2).

Каждая функция — одна транзакция, которая берёт замок строки корня (`structure.lock_root`) до первой записи.
Службы прав не проверяют: это делают представления. Отметки руководителя и заместителя — поле членства,
поэтому уходят вместе с ним при переводе, удалении и увольнении.
"""
from dataclasses import dataclass, field

from django.db import transaction

from apps.core import events
from apps.core.models import User
from apps.core.services import audit
from apps.core.services.permissions import forget_users
from apps.org.models import Membership, Unit
from apps.org.services import structure
from apps.org.services.errors import OrgError

TRANSFER = "transfer"
CONCURRENT = "concurrent"


@dataclass
class AddResult:
    """Итог `add_members`: кто добавлен и кто уже был участником."""

    added: list = field(default_factory=list)
    already: list = field(default_factory=list)


def _unique(users) -> list:
    seen, result = set(), []
    for user in users:
        if user.pk not in seen:
            seen.add(user.pk)
            result.append(user)
    return result


def _unit_names(user) -> list[str]:
    """Названия всех узлов человека по возрастанию `path`."""
    return list(Unit.objects.filter(memberships__user=user).order_by("path").values_list("name", flat=True))


def _dismissed(users) -> bool:
    return User.objects.filter(pk__in=[u.pk for u in users], state="dismissed").exists()


def _record_removed(user, member: Membership, reason: str, actor, ip) -> None:
    audit.record(
        "membership.removed", actor=actor, object_type="user", object_id=user.pk, ip=ip,
        before={"unit": member.unit.name, "unit_id": member.unit_id, "mark": member.mark, "reason": reason})


def _add(user, unit: Unit, mode: str, actor, ip) -> None:
    Membership.objects.create(user=user, unit=unit, mark="", created_by=actor)
    audit.record(
        "membership.added", actor=actor, object_type="user", object_id=user.pk, ip=ip,
        after={"unit": unit.name, "unit_id": unit.pk, "mode": mode, "mark": ""})


def _record_transferred(user, before_units, actor, ip) -> None:
    audit.record(
        "membership.transferred", actor=actor, object_type="user", object_id=user.pk, ip=ip,
        before={"units": before_units}, after={"units": _unit_names(user)})


def add_members(unit, users, *, mode=None, actor, ip=None) -> AddResult:
    """Добавляет людей в узел. Отдел: режим `TRANSFER` или `CONCURRENT`; команда: режим игнорируется."""
    users = _unique(users)
    with transaction.atomic():
        structure.lock_root()
        unit = Unit.objects.get(pk=unit.pk)
        is_department = unit.kind == Unit.Kind.DEPARTMENT
        if is_department and mode not in (TRANSFER, CONCURRENT):
            raise OrgError("bad_mode", "Для отдела нужно выбрать режим: перевести или добавить как совместителя.")
        if _dismissed(users):
            raise OrgError("dismissed_user", "Уволенного сотрудника нельзя добавить в узел: никто из набора не добавлен.")
        result = AddResult()
        for user in users:
            if Membership.objects.filter(user=user, unit=unit).exists():
                result.already.append(user)
                continue
            result.added.append(user)
            if not is_department:
                _add(user, unit, "", actor, ip)
            elif mode == CONCURRENT:
                _add(user, unit, CONCURRENT, actor, ip)
            else:
                before_units = _unit_names(user)
                others = list(
                    Membership.objects.filter(user=user, unit__kind=Unit.Kind.DEPARTMENT)
                    .select_related("unit").order_by("unit__path"))
                for member in others:
                    _record_removed(user, member, "transfer", actor, ip)
                    member.delete()
                _add(user, unit, TRANSFER, actor, ip)
                if others:
                    _record_transferred(user, before_units, actor, ip)
        forget_users([u.pk for u in result.added])
    return result


def transfer_member(user, unit, target, *, actor, ip=None) -> bool:
    """Переводит человека из `unit` в `target` того же вида; `False` — он уже участник цели."""
    with transaction.atomic():
        structure.lock_root()
        unit = Unit.objects.get(pk=unit.pk)
        target = Unit.objects.get(pk=target.pk)
        member = Membership.objects.select_related("unit").filter(user=user, unit=unit).first()
        if member is None:
            raise OrgError("not_member", "Сотрудник не состоит в этом узле.")
        if unit.kind != target.kind:
            raise OrgError("kind_mismatch", "Перевести можно только в узел того же вида: из отдела в отдел, из команды в команду.")
        if Membership.objects.filter(user=user, unit=target).exists():
            return False
        before_units = _unit_names(user)
        _record_removed(user, member, "transfer", actor, ip)
        member.delete()
        _add(user, target, TRANSFER, actor, ip)
        _record_transferred(user, before_units, actor, ip)
        forget_users([user.pk])
    return True


def remove_member(user, unit, *, actor, ip=None) -> None:
    """Удаляет членство; отметка уходит вместе с ним."""
    with transaction.atomic():
        structure.lock_root()
        member = Membership.objects.select_related("unit").filter(user=user, unit_id=unit.pk).first()
        if member is None:
            raise OrgError("not_member", "Сотрудник не состоит в этом узле.")
        _record_removed(user, member, "manual", actor, ip)
        member.delete()
        forget_users([user.pk])


def _marks_state(unit: Unit) -> dict:
    """Текущие отметки узла: {'head': [User…], 'deputy': [User…]}."""
    state = {Membership.Mark.HEAD: [], Membership.Mark.DEPUTY: []}
    for member in Membership.objects.filter(unit=unit).exclude(mark="").select_related("user"):
        state[member.mark].append(member.user)
    return state


def _names(users) -> list[str]:
    return sorted(u.full_name for u in users)


def set_marks(unit, *, heads=None, deputies=None, actor, ip=None) -> None:
    """Заменяет набор руководителей и/или заместителей; `None` — набор не меняется."""
    head, deputy = Membership.Mark.HEAD, Membership.Mark.DEPUTY
    with transaction.atomic():
        structure.lock_root()
        unit = Unit.objects.get(pk=unit.pk)
        current = _marks_state(unit)
        current_ids = {head: {u.pk for u in current[head]}, deputy: {u.pk for u in current[deputy]}}
        new = {head: None if heads is None else _unique(heads), deputy: None if deputies is None else _unique(deputies)}
        asked = [*(new[head] or []), *(new[deputy] or [])]
        if _dismissed(asked):
            raise OrgError("dismissed_user", "Уволенному сотруднику нельзя поставить отметку.")
        member_ids = set(Membership.objects.filter(unit=unit, user__in=[u.pk for u in asked]).values_list("user_id", flat=True))
        if any(u.pk not in member_ids for u in asked):
            raise OrgError("not_member", "Руководителем и заместителем может быть только участник узла.")
        final = {mark: ({u.pk for u in new[mark]} if new[mark] is not None else current_ids[mark]) for mark in (head, deputy)}
        clash = (
            final[head] & final[deputy]
            or {u.pk for u in (new[head] or [])} & current_ids[deputy]
            or {u.pk for u in (new[deputy] or [])} & current_ids[head])
        if clash:
            raise OrgError("head_and_deputy", "В одном узле человек либо руководитель, либо заместитель: заменить отметку молча нельзя, сначала снимите прежнюю.")
        if final[head] == current_ids[head] and final[deputy] == current_ids[deputy]:
            return
        had_mark = current_ids[head] | current_ids[deputy]
        before = {"heads": _names(current[head]), "deputies": _names(current[deputy])}
        members = Membership.objects.filter(unit=unit)
        members.filter(user_id__in=final[head] - current_ids[head]).update(mark=head)
        members.filter(user_id__in=final[deputy] - current_ids[deputy]).update(mark=deputy)
        members.filter(mark=head).exclude(user_id__in=final[head]).update(mark="")
        members.filter(mark=deputy).exclude(user_id__in=final[deputy]).update(mark="")
        after_state = _marks_state(unit)
        audit.record(
            "unit.marks_changed", actor=actor, object_type="unit", object_id=unit.pk, ip=ip, before=before,
            after={"heads": _names(after_state[head]), "deputies": _names(after_state[deputy])})
        ids = sorted(had_mark ^ (final[head] | final[deputy]))
        if ids:
            events.publish("access.changed", user_ids=ids)
