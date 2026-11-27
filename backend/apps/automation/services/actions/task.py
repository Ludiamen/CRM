"""Действие «поставить задачу» (PLAN-013, T-13032; SPEC-013, FR-802)."""
from . import ActionSkip


def run(row, params, obj, subject, rule) -> None:
    handler = subject.create_task
    if handler is None:
        raise ActionSkip("задача недоступна")
    error = handler(rule.author, obj, params)
    if error:
        raise ActionSkip(error)
