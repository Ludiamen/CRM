"""Описания действий автоматизации для формы и проверки (PLAN-013, T-13030)."""
from apps.automation.extensions import Action

ACTIONS = (
    ("notify", "Уведомить", {"required": ["recipients", "text"], "optional": ["employee"]}),
    ("assign", "Назначить", {"required": ["mode"], "optional": ["employee"]}),
    ("create_task", "Поставить задачу", {"required": ["title"], "optional": ["description", "assignee", "due_days"]}),
    ("change_status", "Сменить статус", {"required": ["status"], "optional": []}),
    ("comment", "Добавить комментарий", {"required": ["text"], "optional": []}),
)


def actions() -> list:
    return [Action(code, title, params, None) for code, title, params in ACTIONS]
