"""Журнал автоматизации: изменения правил без ПДн (PLAN-013, T-13043; SPEC-013, FR-809/810/817)."""
from apps.core.services import audit

RULE_ACTIONS = {
    "automation.rule_created": "Правило создано",
    "automation.rule_updated": "Правило изменено",
    "automation.rule_enabled": "Правило включено",
    "automation.rule_disabled": "Правило выключено",
}


def rule_changed(rule, action: str, *, actor=None) -> None:
    """Записать изменение правила: только идентификаторы и служебные поля."""
    audit.record(action, actor=actor, object_type="automation.rule", object_id=rule.pk,
                 after={"name": rule.name, "subject_type": rule.subject_type, "scope": rule.scope,
                        "enabled": rule.enabled, "priority": rule.priority})
