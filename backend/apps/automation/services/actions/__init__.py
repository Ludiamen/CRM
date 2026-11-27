"""Выполнение действий правила (PLAN-013, T-13030…T-13036; SPEC-013, FR-799…804/818)."""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from ...models import RuleActionRun, RuleRun

logger = logging.getLogger(__name__)


class ActionSkip(Exception):
    """Действие пропущено: причина для журнала."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _handlers():
    from . import assign, comment, notify, status, task

    handlers = {"notify": notify.run, "assign": assign.run, "create_task": task.run,
                "change_status": status.run, "comment": comment.run}
    from ... import extensions

    for descriptor in extensions.actions().values():
        if descriptor.handler is not None:
            handlers[descriptor.code] = descriptor.handler
    return handlers


def run_rule(run: RuleRun, rule, obj, subject) -> None:
    """Создать строки действий и выполнить немедленные; отложенные ждут `tick`."""
    handlers = _handlers()
    now = timezone.now()
    for action in rule.actions.all():
        due = now + timedelta(seconds=action.delay_seconds) if action.delay_seconds else None
        row = RuleActionRun.objects.create(
            run=run, action=action, order=action.order, kind=action.kind,
            status=RuleActionRun.Status.PENDING if due else RuleActionRun.Status.RUNNING, due_at=due)
        if due:
            continue
        _execute(row, action.kind, action.params or {}, obj, subject, rule, handlers)


def execute(row: RuleActionRun, subject, obj, rule=None) -> None:
    """Выполнить отложенное действие из `tick`."""
    _execute(row, row.kind, (row.action.params if row.action else {}) or {}, obj, subject, rule, _handlers())


def _execute(row: RuleActionRun, kind: str, params: dict, obj, subject, rule, handlers: dict) -> None:
    row.status = RuleActionRun.Status.RUNNING
    row.started_at = timezone.now()
    row.save(update_fields=["status", "started_at"])
    handler = handlers.get(kind)
    if handler is None:
        _finish(row, RuleActionRun.Status.SKIPPED, "действие недоступно")
        return
    try:
        with transaction.atomic():
            handler(row, params, obj, subject, rule)
    except ActionSkip as exc:
        _finish(row, RuleActionRun.Status.SKIPPED, exc.reason)
    except Exception:
        logger.exception("Ошибка действия %s запуска %s", kind, row.run_id)
        _finish(row, RuleActionRun.Status.FAILED, "ошибка выполнения")
    else:
        _finish(row, RuleActionRun.Status.DONE, "")


def _finish(row: RuleActionRun, status: str, reason: str) -> None:
    row.status = status
    row.reason = reason[:255]
    row.finished_at = timezone.now()
    row.save(update_fields=["status", "reason", "finished_at"])
