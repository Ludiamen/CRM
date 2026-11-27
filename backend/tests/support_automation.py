"""Синтетические правила и запуски автоматизации для тестов среза 013."""
from tests import support


def make_rule(author=None, **fields):
    from apps.automation.models import Rule

    values = {
        "name": fields.pop("name", "Правило"),
        "subject_type": fields.pop("subject_type", Rule.Subject.TICKET),
        "scope": fields.pop("scope", Rule.Scope.GLOBAL),
        "author": author or support.make_employee(),
        "trigger": fields.pop("trigger", "ticket_created"),
        "conditions": fields.pop("conditions", []),
        "priority": fields.pop("priority", 100),
        "enabled": fields.pop("enabled", False),
    }
    values.update(fields)
    return Rule.objects.create(**values)


def make_action(rule, order, kind, params=None, delay_seconds=0):
    from apps.automation.models import RuleAction

    return RuleAction.objects.create(rule=rule, order=order, kind=kind, params=params or {},
                                     delay_seconds=delay_seconds)


def make_run(rule, subject_type="ticket", subject_id=1, event="ticket_created", event_id="created:1", **fields):
    from apps.automation.models import RuleRun

    values = {"rule": rule, "subject_type": subject_type, "subject_id": subject_id, "event": event,
              "event_id": event_id}
    values.update(fields)
    return RuleRun.objects.create(**values)
