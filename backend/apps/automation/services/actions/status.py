"""Действие «сменить статус» (PLAN-013, T-13033; SPEC-013, FR-803)."""
from . import ActionSkip


def run(row, params, obj, subject, rule) -> None:
    handler = subject.change_status
    if handler is None:
        raise ActionSkip("статус недоступен")
    error = handler(rule.author, obj, params.get("status"))
    if error:
        raise ActionSkip(error)
