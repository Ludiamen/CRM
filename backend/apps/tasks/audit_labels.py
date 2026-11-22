"""Подписи журнала задач (срез 009, T-9213; CONTRACT-009, 10.2).

Точка `audit_labels`: действия и типы объектов `tasks.*`, ключи «было/стало». `values` пуст — службы пишут значения
по-русски сами.
"""


def audit_labels() -> dict:
    """Подписи действий, полей и видов объектов задач."""
    return {
        "actions": {
            "tasks.created": "Задача создана",
            "tasks.changed": "Задача изменена",
            "tasks.comment_changed": "Комментарий изменён или удалён",
            "tasks.deleted": "Задача удалена",
            "tasks.reminder_set": "Напоминание поставлено",
            "tasks.reminder_failed": "Напоминание не создано",
            "tasks.retention_changed": "Срок хранения задач изменён",
            "tasks.retention_purged": "Задачи удалены по сроку",
        },
        "fields": {
            "deadline": "срок",
            "members": "состав",
            "category": "категория",
            "plan_column": "колонка плана",
            "years": "срок хранения, лет",
            "tasks": "Удалено по сроку, задач",
            "comments": "Удалено по сроку, комментариев",
            "files": "Удалено по сроку, файлов",
            "reminder": "напоминание",
            "user": "сотрудник",
            "moment": "момент",
            "task": "задача",
        },
        "object_types": {
            "tasks.task": "задача",
            "tasks.comment": "комментарий задачи",
            "tasks.settings": "настройки задач",
        },
        "values": {},
    }