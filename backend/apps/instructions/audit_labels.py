"""Подписи журнала поручений (срез 010, T-10212; CONTRACT-010, 10.2)."""

ACTIONS = {
    "instructions.created": "Поручение создано",
    "instructions.changed": "Поручение изменено",
    "instructions.report_submitted": "Отчёт отправлен",
    "instructions.report_accepted": "Отчёт принят",
    "instructions.report_returned": "Отчёт возвращён",
    "instructions.part_added": "Добавлена часть отчёта",
    "instructions.transfer_requested": "Запрошен перенос срока",
    "instructions.transfer_decided": "Решение по переносу",
    "instructions.closed": "Поручение снято с контроля",
    "instructions.reassigned": "Сменён контролёр или исполнитель",
    "instructions.retention_changed": "Срок хранения поручений изменён",
    "instructions.retention_purged": "Поручения удалены по сроку",
    "instructions.reminder_failed": "Напоминание не создано",
}

FIELDS = {
    "title": "название", "text": "текст", "basis": "основание", "deadline": "срок",
    "controller": "контролёр", "assignee": "исполнитель", "members": "соисполнители",
    "periodicity": "периодичность", "years": "срок хранения, лет",
    "instructions": "Удалено по сроку, поручений",
}

OBJECT_TYPES = {
    "instructions.instruction": "поручение",
    "instructions.report": "отчёт по поручению",
    "instructions.transfer": "перенос срока",
    "instructions.settings": "настройки поручений",
    "instructions.basis": "вид основания",
}


def audit_labels() -> dict:
    """Словарь подписей для точки `audit_labels`."""
    return {"actions": dict(ACTIONS), "fields": dict(FIELDS), "object_types": dict(OBJECT_TYPES), "values": {}}
