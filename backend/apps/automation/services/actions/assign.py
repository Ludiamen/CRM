"""Действие «назначить» (PLAN-013, T-13031; SPEC-013, FR-801)."""
from . import ActionSkip


def run(row, params, obj, subject, rule) -> None:
    handler = subject.assign
    if handler is None:
        raise ActionSkip("назначение недоступно")
    mode = params.get("mode")
    employee_id = params.get("employee")
    error = handler(rule.author, obj, mode, employee_id)
    if error:
        raise ActionSkip(error)
