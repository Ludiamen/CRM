"""Доступ к правилам автоматизации (PLAN-013, T-13041; SPEC-013, FR-812–814)."""
from django.db.models import Q

from ..models import Rule


def _permission(user, code: str) -> bool:
    from apps.core.services import permissions

    return permissions.has_permission(user, code)


def can_manage(user, rule) -> bool:
    """Глобальные — `automation.manage`; очередь — руководитель очереди; задача — автор задачи."""
    if getattr(user, "state", "") == "dismissed":
        return False
    if _permission(user, "automation.manage"):
        return True
    if rule.scope == Rule.Scope.QUEUE:
        from apps.servicedesk.services import queues

        return rule.queue_id is not None and queues.can_manage(user, rule.queue_id)
    if rule.scope == Rule.Scope.TASK_AUTHOR:
        return rule.author_id == user.pk and _permission(user, "tasks.use")
    return False


def can_view_page(user) -> bool:
    """Страница правил: администратор, руководитель узла или сотрудник с правом задач."""
    if getattr(user, "state", "") == "dismissed":
        return False
    if _permission(user, "automation.manage") or _permission(user, "tasks.use"):
        return True
    from apps.org.services import structure

    return bool(structure.managed_units(user))


def visible_rules(user):
    """Правила, видимые пользователю: свои, своей очереди или все у администратора."""
    if getattr(user, "state", "") == "dismissed":
        return Rule.objects.none()
    if _permission(user, "automation.manage"):
        return Rule.objects.all()
    from apps.org.services import structure

    managed = structure.managed_units(user)
    condition = Q(subject_type=Rule.Subject.TASK, scope=Rule.Scope.TASK_AUTHOR, author=user)
    if managed:
        condition |= Q(scope=Rule.Scope.QUEUE, queue_id__in=managed)
    return Rule.objects.filter(condition)
