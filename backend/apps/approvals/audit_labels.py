"""Русские подписи журнала согласований (PLAN-014, T-14034)."""

LABELS = {
    "approvals.template_created": "Шаблон согласования создан",
    "approvals.template_updated": "Шаблон согласования изменён",
    "approvals.template_enabled": "Шаблон согласования включён",
    "approvals.template_disabled": "Шаблон согласования выключен",
    "approvals.route_started": "Маршрут согласования запущен",
    "approvals.route_completed": "Маршрут согласования согласован",
    "approvals.stage_completed": "Этап согласования завершён",
    "approvals.decision": "Решение по согласованию",
    "approvals.route_rejected": "Маршрут согласования отклонён",
    "approvals.route_returned": "Маршрут согласования возвращён",
    "approvals.route_cancelled": "Маршрут согласования отменён",
    "approvals.assignment_cancelled": "Задание согласования отменено",
}
FIELDS = {
    "name": "название",
    "subject_type": "субъект",
    "subject_id": "номер субъекта",
    "enabled": "включено",
    "status": "состояние",
    "decision": "решение",
    "assignment": "задание",
    "stage_run": "этап маршрута",
    "order": "порядок",
    "template": "шаблон",
    "reason": "причина",
    "stages": "этапы",
}
OBJECT_TYPES = {"approvals.template": "шаблон согласования", "approvals.route": "маршрут согласования"}


def audit_labels() -> dict:
    return {"actions": dict(LABELS), "fields": dict(FIELDS), "object_types": dict(OBJECT_TYPES), "values": {}}
