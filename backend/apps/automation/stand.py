"""Сброс данных автоматизации на стенде (PLAN-013, T-13045)."""
from django.db import connections

from apps.automation.models import Rule, RuleAction, RuleActionRun, RuleRun


def stand_reset() -> int:
    """Удалить запуски, действия и правила; вернуть число удалённых правил."""
    db = "migrate" if "migrate" in connections.databases else "default"
    RuleActionRun.objects.using(db).all().delete()
    RuleRun.objects.using(db).all().delete()
    RuleAction.objects.using(db).all().delete()
    count, _ = Rule.objects.using(db).all().delete()
    return count
