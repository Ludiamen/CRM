"""Получатели уведомлений задач (срез 009, T-9212; FR-691, FR-692; CONTRACT-009, 9.2).

`assigned`/`due_soon`/`due` — исполнитель и соисполнители; `overdue` — они же и постановщик; `subordinate_overdue`
и `digest` — руководители и заместители всей цепочки вышестоящих узлов исполнителя; `comment` — все участники
(включая наблюдателей) и автор задачи; `reminder` — поставивший. `recipients` отдаёт `{номер: код вида}`,
`targets` — объекты пользователей для рассылки.
"""
from apps.tasks.models import TaskMember

KIND_OF_EVENT = {
    "assigned": "tasks.assigned",
    "due_soon": "tasks.due_soon",
    "due": "tasks.due",
    "overdue": "tasks.overdue",
    "subordinate_overdue": "tasks.subordinate_overdue",
    "reminder": "tasks.reminder",
    "comment": "tasks.comment",
    "digest": "tasks.subordinate_digest",
}
TITLES = {
    "tasks.assigned": "Назначена задача",
    "tasks.due_soon": "Задача скоро просрочена",
    "tasks.due": "Срок наступил",
    "tasks.overdue": "Задача просрочена",
    "tasks.subordinate_overdue": "Задача подчинённого просрочена",
    "tasks.reminder": "Вы просили напомнить",
    "tasks.comment": "Новый комментарий",
    "tasks.subordinate_digest": "Сводка по задачам подчинённых",
}


def _users(task, *, observers: bool = False) -> list:
    people = {task.assignee_id: task.assignee}
    roles = [TaskMember.Role.COEXECUTOR, TaskMember.Role.OBSERVER] if observers else [TaskMember.Role.COEXECUTOR]
    for row in task.members.filter(role__in=roles).select_related("user"):
        people[row.user_id] = row.user
    return list(people.values())


def managers(task) -> list:
    """Руководители и заместители всей цепочки вышестоящих узлов исполнителя."""
    from apps.org.services import structure

    return structure.managers_of(task.assignee)


def targets(task, event) -> list:
    """Сотрудники-получатели события (объекты `User`)."""
    if event == "comment":
        people = _users(task, observers=True) + [task.author]
        return list({user.pk: user for user in people}.values())
    if event == "reminder":
        return [task.assignee]
    if event in ("subordinate_overdue", "digest"):
        return managers(task)
    people = _users(task)
    if event == "overdue":
        people.append(task.author)
    return list({user.pk: user for user in people}.values())


def recipients(task, event) -> dict[int, str]:
    """Получатели события: `{номер: код вида}`; при совмещении ролей в просрочке — `subordinate_overdue`."""
    kind = KIND_OF_EVENT[event]
    result = {user.pk: kind for user in targets(task, event)}
    if event == "overdue":
        for manager in managers(task):
            if manager.pk in result and manager.pk != task.author_id:
                result[manager.pk] = KIND_OF_EVENT["subordinate_overdue"]
        from apps.org.services import structure

        if set(structure.managed_units(task.assignee)) & {unit.id for unit in structure.units_of(task.assignee)}:
            result[task.assignee_id] = KIND_OF_EVENT["subordinate_overdue"]
    return result


def managers_for(person) -> set[int]:
    """Сотрудники, которыми управляет `person`: участники его узлов-отметок и вложенных, без него."""
    from apps.org.services import structure

    units = sorted(structure.managed_units(person))
    if not units:
        return set()
    return set(structure.subtree_member_ids(units)) - {person.pk}


def still_relevant(user_id: int, object_ref: str) -> bool:
    """Задача жива, видна получателю и (для просрочки) не «Готово»."""
    from apps.core.models import User
    from apps.tasks.models import Task
    from apps.tasks.services import access

    if not object_ref.startswith("tasks.task:"):
        return False
    try:
        task = Task.objects.get(pk=int(object_ref.split(":", 1)[1]))
        user = User.objects.get(pk=user_id)
    except (Task.DoesNotExist, ValueError, User.DoesNotExist):
        return False
    return access.visible(user, task) and task.status != Task.Status.DONE