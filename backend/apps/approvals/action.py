"""Действие правила `start_approval` (PLAN-014, T-14033)."""
from apps.automation.extensions import Action
from apps.automation.services.actions import ActionSkip

from .services import routes
from .services.errors import ApprovalError


def actions() -> list:
    return [Action("start_approval", "Запустить согласование",
                   {"required": ["template"], "optional": []}, _run)]


def _run(row, params: dict, obj, subject, rule) -> None:
    template_id = params.get("template")
    try:
        template_id = int(template_id)
    except (TypeError, ValueError):
        raise ActionSkip("не выбран шаблон")
    try:
        routes.start(rule.author, subject_type=subject.type, subject_id=obj.pk, template_id=template_id)
    except ApprovalError as error:
        raise ActionSkip(error.message)
