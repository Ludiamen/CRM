"""Запуск правил по событию (PLAN-013, T-13021; SPEC-013, FR-794/805/809/815)."""
import logging
import uuid

from django.db import IntegrityError, transaction
from django.utils import timezone

from ..extensions import subjects
from ..models import Rule, RuleActionRun, RuleRun
from . import chain, conditions, validation

logger = logging.getLogger(__name__)


def _subject(subject_type: str):
    return subjects().get(subject_type)


def matching_rules(subject, event: str, obj):
    """Включённые правила субъекта, события и доступной области по приоритету."""
    found = Rule.objects.filter(enabled=True, subject_type=subject.type, trigger=event)
    queue_id = subject.queue_id(obj) if callable(subject.queue_id) else None
    author_id = subject.author_id(obj) if callable(subject.author_id) else None
    result = []
    for rule in found.select_related("queue", "author").prefetch_related("actions"):
        if rule.scope == Rule.Scope.QUEUE and (queue_id is None or rule.queue_id != queue_id):
            continue
        if rule.scope == Rule.Scope.TASK_AUTHOR and (author_id is None or rule.author_id != author_id):
            continue
        result.append(rule)
    return sorted(result, key=lambda rule: (rule.priority, rule.pk))


def on_event(subject_type: str, subject_id: int, event: str, event_id: str, data: dict | None = None) -> int:
    """Выполнить подходящие правила; вернуть число запусков (не действий)."""
    subject = _subject(subject_type)
    if subject is None:
        return 0
    obj = subject.load(subject_id)
    if obj is None:
        return 0
    token = None
    if chain.current() is None:
        token = chain.start(subject_type, subject_id)
    try:
        values = subject.values(obj)
        if data:
            values = {**values, **data}
        count = 0
        skipped = []
        current = chain.current()
        root = (current.root_run_id or current.id) if current is not None else None
        for rule in matching_rules(subject, event, obj):
            if not chain.can_run(rule.pk):
                continue
            if not conditions.match(values, rule.conditions):
                skipped.append(RuleRun(
                    rule=rule, subject_type=subject_type, subject_id=subject_id, event=event,
                    event_id=event_id, chain_id=chain.chain_id() or uuid.uuid4(), root_run_id=root,
                    depth=max(chain.depth(), 1), status=RuleRun.Status.SKIPPED,
                    reason="условия не совпали", finished_at=timezone.now()))
                continue
            run = _claim(rule, subject_type, subject_id, event, event_id)
            if run is None:
                continue
            chain.mark(rule.pk)
            from . import actions as action_service

            try:
                with chain.child(rule.pk), transaction.atomic():
                    action_service.run_rule(run, rule, obj, subject)
            except Exception:
                logger.exception("Ошибка правила %s", rule.pk)
                _finish(run, RuleRun.Status.FAILED, "ошибка выполнения")
                continue
            _finish(run, RuleRun.Status.DONE, "")
            count += 1
        if skipped:
            try:
                RuleRun.objects.bulk_create(skipped)
            except IntegrityError:
                pass
        return count
    finally:
        if token is not None:
            chain.reset(token)


def _claim(rule, subject_type, subject_id, event, event_id):
    """Создать запуск; повторная доставка и уникальность — пропуск."""
    current = chain.current()
    root = (current.root_run_id or current.id) if current is not None else None
    try:
        with transaction.atomic():
            return RuleRun.objects.create(
                rule=rule, subject_type=subject_type, subject_id=subject_id, event=event, event_id=event_id,
                chain_id=chain.chain_id() or uuid.uuid4(), root_run_id=root, depth=max(chain.depth(), 1))
    except IntegrityError:
        return None


def _finish(run, status: str, reason: str) -> None:
    run.status = status
    run.reason = reason[:255]
    run.finished_at = timezone.now()
    run.save(update_fields=["status", "reason", "finished_at"])
