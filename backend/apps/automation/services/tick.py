"""Отложенные действия: очередь и минутное задание (PLAN-013, T-13034; SPEC-013, FR-807/808)."""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from ..extensions import subjects
from ..models import RuleActionRun
from . import actions, chain

logger = logging.getLogger(__name__)
STALE = timedelta(minutes=10)


def pending_count(*, rule=None) -> int:
    queryset = RuleActionRun.objects.filter(status=RuleActionRun.Status.PENDING)
    if rule is not None:
        queryset = queryset.filter(run__rule=rule)
    return queryset.count()


def cancel_rule(rule) -> int:
    return RuleActionRun.objects.filter(run__rule=rule, status=RuleActionRun.Status.PENDING).update(
        status=RuleActionRun.Status.SKIPPED, reason="правило выключено", finished_at=timezone.now())


def run_due(now=None) -> int:
    """Выполнить созревшие отложенные действия; вернуть число обработанных."""
    now = now or timezone.now()
    done = 0
    rows = RuleActionRun.objects.filter(status=RuleActionRun.Status.PENDING, due_at__lte=now).order_by(
        "due_at", "pk")[:50]
    for row in rows:
        with transaction.atomic():
            claimed = RuleActionRun.objects.select_for_update(skip_locked=True).filter(
                pk=row.pk, status=RuleActionRun.Status.PENDING).first()
            if claimed is None:
                continue
            claimed.status = RuleActionRun.Status.RUNNING
            claimed.started_at = now
            claimed.save(update_fields=["status", "started_at"])
        subject = subjects().get(claimed.run.subject_type)
        obj = subject.load(claimed.run.subject_id) if subject is not None else None
        if subject is None or obj is None:
            _finish(claimed, RuleActionRun.Status.SKIPPED, "субъект недоступен")
        elif claimed.run.rule.enabled is False:
            _finish(claimed, RuleActionRun.Status.SKIPPED, "правило выключено")
        else:
            token = chain.start(claimed.run.subject_type, claimed.run.subject_id,
                                root_run_id=claimed.run.root_run_id or claimed.run.chain_id)
            try:
                actions.execute(claimed, subject, obj, claimed.run.rule)
            finally:
                chain.reset(token)
        done += 1
    _stale(now)
    return done


def _stale(now) -> None:
    edge = now - STALE
    RuleActionRun.objects.filter(status=RuleActionRun.Status.RUNNING, started_at__lt=edge).update(
        status=RuleActionRun.Status.FAILED, reason="зависло", finished_at=now)
    from ..models import RuleRun

    RuleRun.objects.filter(status=RuleRun.Status.RUNNING, created_at__lt=edge).update(
        status=RuleRun.Status.FAILED, reason="зависло", finished_at=now)


def _finish(row, status: str, reason: str) -> None:
    row.status = status
    row.reason = reason
    row.finished_at = timezone.now()
    row.save(update_fields=["status", "reason", "finished_at"])
