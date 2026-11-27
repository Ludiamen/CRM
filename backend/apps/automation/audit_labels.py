"""Русские подписи журнала автоматизации (PLAN-013, T-13043)."""
LABELS = {
    "automation.rule_created": "Правило автоматизации создано",
    "automation.rule_updated": "Правило автоматизации изменено",
    "automation.rule_enabled": "Правило автоматизации включено",
    "automation.rule_disabled": "Правило автоматизации выключено",
    "automation.run": "Запуск правила автоматизации",
    "automation.action": "Действие правила автоматизации",
    "automation.action_skipped": "Действие правила пропущено",
}
FIELDS = {
    "name": "название",
    "subject_type": "субъект",
    "scope": "область",
    "enabled": "включено",
    "priority": "критичность",
}
OBJECT_TYPES = {"automation.rule": "правило автоматизации"}


def audit_labels() -> dict:
    return {"actions": dict(LABELS), "fields": dict(FIELDS), "object_types": dict(OBJECT_TYPES), "values": {}}
