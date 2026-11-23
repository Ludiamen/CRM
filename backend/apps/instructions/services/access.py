"""Права и видимость поручений (срез 010, T-10202; FR-702, 703, 719, 721, 722; CONTRACT-010, раздел 4).

Видимость по структуре дополнительна к праву `instructions.use`. Администратор портала чужих поручений не видит
(он видит только те, где участник). Блокировка лишает действий, но не видимости.
"""
from apps.core.services import permissions, roles
from apps.instructions.models import InstructionMember, InstructionReport, InstructionTransfer
from apps.org.services import structure


def managed_units(viewer) -> frozenset[int]:
    """Узлы, которыми управляет сотрудник (руководитель/заместитель и вложенные)."""
    return structure.managed_units(viewer)


def units_of(person) -> frozenset[int]:
    """Узлы, где состоит сотрудник."""
    return frozenset(item.id for item in structure.units_of(person))


def manages(viewer, person) -> bool:
    """Управляет ли `viewer` сотрудником `person` по структуре."""
    if viewer is None or person is None:
        return False
    return bool(managed_units(viewer) & units_of(person))


def _active(viewer) -> bool:
    return getattr(viewer, "state", "") == "active"


def _participant(viewer, instruction) -> bool:
    if viewer.pk in (instruction.author_id, instruction.controller_id, instruction.assignee_id):
        return True
    return InstructionMember.objects.filter(instruction=instruction, user=viewer).exists()


def visible(viewer, instruction) -> bool:
    """Видно ли поручение: участник или руководитель цепочки; администратор чужих не видит."""
    if viewer is None or instruction.deleted_at is not None:
        return False
    if _participant(viewer, instruction):
        return True
    if roles.is_active_admin(viewer):
        return False
    return manages(viewer, instruction.assignee) or manages(viewer, instruction.author)


def can_assign(viewer, assignee) -> bool:
    """Ставить поручение: право `instructions.assign` и управление узлом исполнителя."""
    return bool(_active(viewer) and assignee is not None
                and permissions.has_permission(viewer, "instructions.assign")
                and manages(viewer, assignee))


def can_edit_fields(viewer, instruction) -> bool:
    """Поля меняет автор, пока поручение не снято с контроля."""
    return bool(_active(viewer) and instruction.closed_at is None and viewer.pk == instruction.author_id)


def can_edit_ladder(viewer, instruction) -> bool:
    """Лестницу правит автор или контролёр до снятия с контроля."""
    return bool(_active(viewer) and instruction.closed_at is None
                and viewer.pk in (instruction.author_id, instruction.controller_id))


def can_decide(viewer, instruction) -> bool:
    """Принимает и возвращает отчёт только контролёр."""
    return bool(_active(viewer) and instruction.closed_at is None and viewer.pk == instruction.controller_id)


def _date_open(date) -> bool:
    return date is None or date.state in ("waiting", "returned")


def can_report(viewer, instruction, date=None) -> bool:
    """Сводный отчёт отправляет ответственный, пока поручение не снято и дата открыта."""
    return bool(_active(viewer) and instruction.closed_at is None and viewer.pk == instruction.assignee_id
                and _date_open(date))


def can_add_part(viewer, instruction, date) -> bool:
    """Часть добавляет соисполнитель или ответственный до сводного отчёта к дате."""
    if not (_active(viewer) and instruction.closed_at is None and date is not None and _date_open(date)):
        return False
    if viewer.pk != instruction.assignee_id and not InstructionMember.objects.filter(
            instruction=instruction, user=viewer).exists():
        return False
    return not InstructionReport.objects.filter(instruction=instruction, date=date).exists()


def can_request_transfer(viewer, instruction) -> bool:
    """Перенос просит ответственный, если нет другого запроса."""
    return bool(_active(viewer) and instruction.closed_at is None and viewer.pk == instruction.assignee_id
                and not InstructionTransfer.objects.filter(instruction=instruction, state="pending").exists())


def can_decide_transfer(viewer, instruction) -> bool:
    """Решение по переносу — автор или контролёр."""
    return bool(_active(viewer) and instruction.closed_at is None
                and viewer.pk in (instruction.author_id, instruction.controller_id))


def can_close(viewer, instruction) -> bool:
    """Снять с контроля может контролёр при принятом итоговом отчёте и без pending-переноса."""
    if not (_active(viewer) and instruction.closed_at is None and viewer.pk == instruction.controller_id):
        return False
    if InstructionTransfer.objects.filter(instruction=instruction, state="pending").exists():
        return False
    return InstructionReport.objects.filter(instruction=instruction, date__isnull=True,
                                            decision="accepted").exists()


def can_view_discipline(viewer) -> bool:
    """Отчёт по дисциплине — руководителю/заместителю с правом поручений; администратор его не получает."""
    if not _active(viewer) or roles.is_active_admin(viewer):
        return False
    return permissions.has_permission(viewer, "instructions.use") and bool(managed_units(viewer))