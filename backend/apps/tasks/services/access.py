"""Права и видимость задач (срез 009, T-9202; FR-676…678, FR-695; CONTRACT-009, раздел 4).

Правило структуры — `org.services.structure.managed_units`: узлы с отметкой руководителя или заместителя и
вложенные, без обычных членств. `manages` — пересечение управляемых узлов с узлами человека на момент просмотра.
Права полей считаются по узлу **исполнителя** (ADR-0018 п. 10), личная колонка плана — только владельцу.
"""
from apps.org.services import structure
from apps.tasks.models import TaskMember


def managed_units(viewer) -> frozenset[int]:
    """Узлы зрителя, которыми он управляет (переэкспорт правила `org`)."""
    return structure.managed_units(viewer)


def units_of(person) -> frozenset[int]:
    """Узлы человека на момент просмотра."""
    return frozenset(unit.id for unit in structure.units_of(person))


def manages(viewer, person) -> bool:
    """Ведёт ли `viewer` `person` по структуре: есть общий узел среди управляемых и узлов человека."""
    if viewer is None or person is None:
        return False
    return bool(managed_units(viewer) & units_of(person))


def _can_assign(viewer) -> bool:
    from apps.core.services import permissions

    return permissions.has_permission(viewer, "tasks.assign")


def can_set_task(viewer, assignee) -> bool:
    """Поставить задачу: себе — всем с `tasks.use`; другому — с `tasks.assign` в управляемых узлах."""
    if viewer.pk == assignee.pk:
        return True
    return _can_assign(viewer) and manages(viewer, assignee)


def _is_member(viewer, task) -> bool:
    return TaskMember.objects.filter(task=task, user=viewer).exists()


def visible(viewer, task) -> bool:
    """Видимость: автор, участник, либо руководитель/заместитель автора или исполнителя по цепочке.

    Удалённая задача (`deleted_at IS NOT NULL`) не видна никому; администратор портала чужих не видит.
    """
    if task.deleted_at is not None:
        return False
    if viewer.pk in (task.author_id, task.assignee_id):
        return True
    if _is_member(viewer, task):
        return True
    return manages(viewer, task.author) or manages(viewer, task.assignee)


def can_edit_fields(viewer, task) -> bool:
    """Поля задачи: автор или руководитель/заместитель узла исполнителя (не узла автора)."""
    if task.deleted_at is not None:
        return False
    return viewer.pk == task.author_id or manages(viewer, task.assignee)


def can_change_status(viewer, task) -> bool:
    """Статус: исполнитель, соисполнитель, иначе — права полей."""
    if task.deleted_at is not None:
        return False
    if viewer.pk == task.assignee_id:
        return True
    if TaskMember.objects.filter(task=task, user=viewer, role=TaskMember.Role.COEXECUTOR).exists():
        return True
    return can_edit_fields(viewer, task)


def can_delete(viewer, task) -> bool:
    """Удаление: автор или руководитель/заместитель узла исполнителя."""
    if task.deleted_at is not None:
        return False
    return viewer.pk == task.author_id or manages(viewer, task.assignee)


def can_comment(viewer, task) -> bool:
    """Комментарии пишут все, кто видит задачу."""
    return visible(viewer, task)


def can_edit_comment(viewer, comment) -> bool:
    """Правка и удаление комментария — только автор и пока комментарий не удалён."""
    return comment.deleted_at is None and comment.author_id == viewer.pk


def can_move(viewer, task, board, *, owner=None) -> bool:
    """Перенос карточки по полю: статус, срок и категория — права поля; план — только владелец плана."""
    if task.deleted_at is not None:
        return False
    if board == "status":
        return can_change_status(viewer, task)
    if board in ("deadline", "category"):
        return can_edit_fields(viewer, task)
    if board == "plan":
        plan_owner = owner.pk if owner is not None else (
            task.plan_column.user_id if task.plan_column_id is not None else None)
        return plan_owner is None or plan_owner == viewer.pk
    return False