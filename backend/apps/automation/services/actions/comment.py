"""Действие «добавить комментарий» (PLAN-013, T-13033; SPEC-013, FR-804)."""
from . import ActionSkip


def run(row, params, obj, subject, rule) -> None:
    handler = subject.comment
    if handler is None:
        raise ActionSkip("комментарий недоступен")
    error = handler(rule.author, obj, params.get("text") or "")
    if error:
        raise ActionSkip(error)
