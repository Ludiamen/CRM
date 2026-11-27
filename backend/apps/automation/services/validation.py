"""Проверка правила до сохранения и при запуске (PLAN-013, T-13020; SPEC-013, FR-794/797/798)."""
from . import conditions

TICKET_FIELDS = {"queue", "category", "priority", "status", "status_kind", "assignee", "source",
                 "changed_field", "sla_deadline"}
TASK_FIELDS = {"status", "category", "assignee", "author", "has_deadline", "changed_field"}
TRIGGERS = {
    "ticket": {"ticket_created", "reply_received", "ticket_field_changed", "ticket_status_changed",
               "ticket_transferred", "ticket_closed", "sla_threshold"},
    "task": {"task_created", "task_field_changed", "task_status_changed", "task_threshold"},
}
SCOPES = {"ticket": {"global", "queue"}, "task": {"global", "task_author"}}
ACTION_SCHEMAS = {
    "notify": ({"recipients", "text"}, {"recipients", "text", "employee"}),
    "assign": ({"mode"}, {"mode", "employee"}),
    "create_task": ({"title"}, {"title", "description", "assignee", "due_days"}),
    "change_status": ({"status"}, {"status"}),
    "comment": ({"text"}, {"text"}),
}
DELAY_MAX = 2_592_000
PRIORITY_MIN, PRIORITY_MAX = 1, 999


class RuleError(Exception):
    """Ошибка правила: код и русский текст."""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def _active(user) -> bool:
    return user is not None and getattr(user, "state", "") != "dismissed"


def validate_rule(rule, *, actions: dict | None = None) -> None:
    """Проверить правило, условия и действия; ошибка — `RuleError`."""
    from ..extensions import actions as registered_actions
    from ..extensions import subjects

    name = (rule.name or "").strip()
    if not 1 <= len(name) <= 150:
        raise RuleError("rule_invalid", "Название правила — от 1 до 150 знаков")
    if rule.subject_type not in TRIGGERS:
        raise RuleError("rule_invalid", "Неизвестный субъект правила")
    if rule.scope not in SCOPES[rule.subject_type]:
        raise RuleError("rule_invalid", "Область не подходит субъекту")
    if rule.scope == "queue" and rule.queue_id is None:
        raise RuleError("rule_invalid", "Выберите очередь")
    if rule.scope != "queue" and rule.queue_id is not None:
        raise RuleError("rule_invalid", "Очередь указывается только для области «Очередь»")
    if rule.trigger not in TRIGGERS[rule.subject_type]:
        raise RuleError("rule_invalid", "Событие не подходит субъекту")
    if not _active(rule.author):
        raise RuleError("rule_invalid", "Автор правила уволен")
    if not PRIORITY_MIN <= rule.priority <= PRIORITY_MAX:
        raise RuleError("priority_range", "Приоритет — от 1 до 999")
    subject = subjects().get(rule.subject_type)
    if subject is not None and subject.validate_scope is not None:
        error = subject.validate_scope(rule)
        if error:
            raise RuleError("rule_invalid", error)
    fields = TICKET_FIELDS if rule.subject_type == "ticket" else TASK_FIELDS
    if not isinstance(rule.conditions, list):
        raise RuleError("rule_invalid", "Условия должны быть списком")
    for condition in rule.conditions:
        _validate_condition(condition, rule, fields, subject)
    registered = registered_actions() if actions is None else actions
    for action in rule.actions.all() if hasattr(rule, "actions") else ():
        _validate_action(action, registered)


def _validate_condition(condition, rule, fields, subject) -> None:
    if not isinstance(condition, dict) or set(condition) != {"field", "op", "value"}:
        raise RuleError("rule_invalid", "Условие должно содержать field, op и value")
    field, op, value = condition["field"], condition["op"], condition["value"]
    if field not in fields:
        raise RuleError("rule_invalid", "Поле условия не подходит субъекту")
    if field == "changed_field" and rule.trigger not in ("ticket_field_changed", "task_field_changed"):
        raise RuleError("rule_invalid", "Поле «изменено поле» доступно только событию изменения")
    if field == "sla_deadline" and rule.trigger != "sla_threshold":
        raise RuleError("rule_invalid", "Срок SLA доступен только событию порога")
    if op not in conditions.OPERATORS:
        raise RuleError("rule_invalid", "Неизвестный оператор условия")
    if op in ("пусто", "не пусто"):
        return
    if field == "changed_field":
        allowed = {"priority", "category", "queue", "assignee", "complexity", "client_unit"} if rule.subject_type == "ticket" \
            else {"deadline", "assignee", "category", "status", "title"}
        values = value if isinstance(value, (list, tuple, set)) else (value,)
        if not values or any(item not in allowed for item in values):
            raise RuleError("rule_invalid", "Неизвестное изменяемое поле")
        return
    if field == "sla_deadline":
        values = value if isinstance(value, (list, tuple, set)) else (value,)
        if any(item not in ("reaction", "solution") for item in values):
            raise RuleError("rule_invalid", "Срок SLA — «реакция» или «решение»")
        return
    if subject is not None and subject.validate_condition is not None:
        error = subject.validate_condition(field, op, value)
        if error:
            raise RuleError("archived_value", error)


def _validate_action(action, registered: dict) -> None:
    if action.kind not in ACTION_SCHEMAS:
        raise RuleError("unknown_action", "Неизвестное действие")
    if registered and action.kind not in registered:
        raise RuleError("unknown_action", "Действие недоступно: приложение не установлено")
    required, allowed = ACTION_SCHEMAS[action.kind]
    params = action.params if isinstance(action.params, dict) else {}
    if not required <= set(params):
        raise RuleError("rule_invalid", "У действия не хватает параметров")
    if set(params) - allowed:
        raise RuleError("rule_invalid", "У действия лишние параметры")
    if not 0 <= action.delay_seconds <= DELAY_MAX:
        raise RuleError("delay_range", "Задержка — от 0 до 30 дней")
    if action.order < 1:
        raise RuleError("rule_invalid", "Порядок действия — с 1")
    if action.kind == "notify":
        if not 1 <= len(params.get("recipients") or []) <= 5:
            raise RuleError("rule_invalid", "Выберите от 1 до 5 получателей")
        if not 1 <= len(str(params.get("text") or "")) <= 500:
            raise RuleError("rule_invalid", "Текст уведомления — от 1 до 500 знаков")
        _validate_placeholders(str(params.get("text") or ""))
    if action.kind == "comment" and not 1 <= len(str(params.get("text") or "")) <= 2000:
        raise RuleError("rule_invalid", "Текст комментария — от 1 до 2000 знаков")
    if action.kind == "create_task" and not 1 <= len(str(params.get("title") or "")) <= 300:
        raise RuleError("rule_invalid", "Название задачи — от 1 до 300 знаков")
    if action.kind == "create_task":
        _validate_placeholders(str(params.get("title") or ""))
        description = str(params.get("description") or "")
        if len(description) > 10_000:
            raise RuleError("rule_invalid", "Описание задачи — не длиннее 10 000 знаков")
        _validate_placeholders(description)
        due = params.get("due_days", 0)
        if not isinstance(due, int) or not 0 <= due <= 365:
            raise RuleError("rule_invalid", "Срок задачи — от 0 до 365 дней")


PLACEHOLDERS = {"number", "status", "queue", "assignee", "priority", "url"}


def _validate_placeholders(text: str) -> None:
    import re

    for found in re.findall(r"\{([^{}]+)\}", text):
        if found not in PLACEHOLDERS:
            raise RuleError("unknown_placeholder", "Неизвестная подстановка в тексте")
