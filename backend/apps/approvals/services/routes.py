"""Запуск, решения, отмена и выбывание участников (PLAN-014, T-14012…T-14022)."""
from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.services import permissions

from ..extensions import subjects
from ..models import (ApprovalAssignment, ApprovalEvent, ApprovalRoute, ApprovalStageRun,
                      ApprovalTemplate)
from . import access, events, journal, stages
from .errors import ApprovalError
from .templates import resolve_participants, validate

COMMENT_MAX = 4000


def _now():
    return timezone.now()


def _normalize_comment(comment) -> str:
    return (comment or "").strip()


def start(actor, *, subject_type: str, subject_id: int, template_id: int):
    """Запустить маршрут; возвращает `ApprovalRoute`."""
    adapter = subjects().get(subject_type)
    if adapter is None:
        raise ApprovalError("subject_mismatch", "Субъект согласования не найден")
    try:
        with transaction.atomic():
            subject = adapter.lock(subject_id)
            if subject is None:
                raise ApprovalError("subject_closed", "Субъект не найден")
            brief = adapter.brief(subject)
            if brief.get("closed"):
                raise ApprovalError("subject_closed", "Субъект закрыт")
            if not adapter.can_work(actor, subject):
                raise ApprovalError("forbidden", "Нет права запускать согласование")
            template = ApprovalTemplate.objects.filter(pk=template_id).first()
            if template is None:
                raise ApprovalError("template_absent", "Шаблон не найден")
            if template.subject_type != subject_type:
                raise ApprovalError("subject_mismatch", "Шаблон для другого субъекта")
            if not template.enabled:
                raise ApprovalError("template_disabled", "Шаблон выключен")
            validate(template)
            stage_data = []
            for stage in template.stages.order_by("order", "pk"):
                users = resolve_participants(stage, subject_type, subject)
                if not users:
                    raise ApprovalError("no_participants", "В этапе нет доступных участников")
                stage_data.append((stage, list(users.values())))
            route = ApprovalRoute.objects.create(
                template=template, template_name=template.name, subject_type=subject_type,
                subject_id=subject.pk, subject_number=brief.get("number") or subject.pk,
                initiator=actor)
            now = _now()
            for order, (stage, users) in enumerate(stage_data, start=1):
                run = ApprovalStageRun.objects.create(
                    route=route, order=order, title=stage.title, mode=stage.mode, rule=stage.rule,
                    deadline_hours=stage.deadline_hours,
                    status=ApprovalStageRun.Status.RUNNING if order == 1 else ApprovalStageRun.Status.WAITING,
                    started_at=now if order == 1 else None,
                    due_at=(now + timedelta(hours=stage.deadline_hours))
                    if order == 1 and stage.deadline_hours else None)
                for index, user in enumerate(users, start=1):
                    ApprovalAssignment.objects.create(
                        stage_run=run, user=user, order=index, due_at=run.due_at)
                if order == 1:
                    for assignment in stages.current_assignments(run):
                        _notify_assignment(route, assignment)
            journal.route_started(route, actor=actor)
            ApprovalEvent.objects.create(route=route, kind=ApprovalEvent.Kind.STARTED, actor=actor,
                                         data={"template_id": template.pk})
            events.started(route, actor=actor)
            return route
    except IntegrityError as error:
        if "approval_route_one_running" not in str(error):
            raise
        raise ApprovalError("route_exists", "Маршрут уже идёт")


def _locked(assignment_id: int):
    route = (ApprovalRoute.objects.select_for_update(of=("self",))
             .filter(stages__assignments__pk=assignment_id).first())
    if route is None:
        raise ApprovalError("assignment_not_found", "Задание не найдено")
    assignment = (ApprovalAssignment.objects.select_for_update(of=("self",))
                  .select_related("stage_run__route", "user").filter(pk=assignment_id).first())
    if assignment is None:
        raise ApprovalError("assignment_not_found", "Задание не найдено")
    return route, assignment


def decide(actor, assignment_id: int, decision: str, comment: str = ""):
    """Принять решение по заданию; повтор с тем же ключом идемпотентен."""
    comment = _normalize_comment(comment)
    if decision not in (ApprovalAssignment.Decision.APPROVED, ApprovalAssignment.Decision.REJECTED,
                        ApprovalAssignment.Decision.RETURNED):
        raise ApprovalError("decision_invalid", "Неизвестное решение")
    if decision in (ApprovalAssignment.Decision.REJECTED, ApprovalAssignment.Decision.RETURNED) and not comment:
        raise ApprovalError("comment_required", "Комментарий обязателен")
    if len(comment) > COMMENT_MAX:
        raise ApprovalError("comment_too_long", "Комментарий — не длиннее 4 000 знаков")
    # Быстрый идемпотентный путь: повтор уже принятого решения не берёт блокировки и не пишет.
    replay = ApprovalAssignment.objects.filter(pk=assignment_id).values(
        "status", "decision", "comment", "user_id").first()
    if replay is not None and replay["status"] != ApprovalAssignment.Status.PENDING:
        if (replay["user_id"] == actor.pk and replay["decision"] == decision
                and (replay["comment"] or "").strip() == comment):
            return ApprovalAssignment.objects.get(pk=assignment_id)
        if replay["status"] == ApprovalAssignment.Status.CANCELLED:
            raise ApprovalError("assignment_cancelled", "Задание отменено")
        raise ApprovalError("already_decided", "Решение уже принято")
    with transaction.atomic():
        route, assignment = _locked(assignment_id)
        if assignment.status != ApprovalAssignment.Status.PENDING:
            if (assignment.user_id == actor.pk and assignment.decision == decision
                    and (assignment.comment or "").strip() == comment):
                return assignment
            if assignment.status == ApprovalAssignment.Status.CANCELLED:
                raise ApprovalError("assignment_cancelled", "Задание отменено")
            raise ApprovalError("already_decided", "Решение уже принято")
        if route.status != ApprovalRoute.Status.RUNNING:
            raise ApprovalError("route_finished", "Маршрут завершён")
        if assignment.user_id != actor.pk:
            raise ApprovalError("forbidden", "Решение принимает только назначенный участник")
        now = _now()
        assignment.status = decision
        assignment.decision = decision
        assignment.comment = comment
        assignment.decided_at = now
        assignment.save(update_fields=["status", "decision", "comment", "decided_at"])
        journal.decision(assignment, actor=actor)
        ApprovalEvent.objects.create(
            route=route, kind=ApprovalEvent.Kind.DECISION, actor=actor,
            data={"assignment_id": assignment.pk, "decision": decision})
        _notify_decision(route, assignment, actor)
        if decision == ApprovalAssignment.Decision.APPROVED:
            stages.approved(assignment.stage_run, assignment, actor=actor, now=now)
        else:
            stages.rejected(assignment.stage_run, assignment, actor=actor, decision=decision, now=now)
        return assignment


def cancel(actor, route_id: int):
    with transaction.atomic():
        route = ApprovalRoute.objects.select_for_update().filter(pk=route_id).first()
        if route is None:
            raise ApprovalError("route_not_found", "Маршрут не найден")
        if route.status == ApprovalRoute.Status.CANCELLED:
            if route.cancelled_by_id == actor.pk:
                return route
            raise ApprovalError("route_finished", "Маршрут уже отменён")
        if route.status != ApprovalRoute.Status.RUNNING:
            raise ApprovalError("route_finished", "Маршрут завершён")
        if not access.can_cancel(actor, route):
            raise ApprovalError("forbidden", "Отменить маршрут может инициатор или администратор")
        route.status = ApprovalRoute.Status.CANCELLED
        route.finished_at = _now()
        route.cancelled_by = actor
        route.save(update_fields=["status", "finished_at", "cancelled_by"])
        stages.cancel_route_pending(route)
        journal.route_finished(route, actor=actor, status=route.status)
        ApprovalEvent.objects.create(route=route, kind=ApprovalEvent.Kind.CANCELLED, actor=actor)
        events.route_finished(route, actor=actor, kind="cancelled")
        return route


def drop_inactive(now=None) -> int:
    """Отменить задания уволенных и заблокированных; пересчитать этапы."""
    now = now or _now()
    from django.contrib.auth import get_user_model

    inactive = get_user_model().objects.filter(state__in=("dismissed", "blocked")).values_list("pk", flat=True)
    route_ids = list(ApprovalAssignment.objects.filter(
        status=ApprovalAssignment.Status.PENDING, user_id__in=inactive
    ).values_list("stage_run__route_id", flat=True).distinct())
    done = 0
    for route_id in sorted(set(route_ids)):
        with transaction.atomic():
            route = ApprovalRoute.objects.select_for_update().filter(pk=route_id).first()
            if route is None or route.status != ApprovalRoute.Status.RUNNING:
                continue
            rows = list(ApprovalAssignment.objects.select_for_update().filter(
                stage_run__route_id=route.pk, status=ApprovalAssignment.Status.PENDING,
                user_id__in=inactive).select_related("stage_run"))
            for assignment in rows:
                assignment.status = ApprovalAssignment.Status.CANCELLED
                assignment.save(update_fields=["status"])
                journal.assignment_cancelled(assignment)
                done += 1
            for stage in route.stages.filter(status=ApprovalStageRun.Status.RUNNING):
                stages.recalculate(stage, now=now)
    return done


def start_for_rule(actor, *, subject_type: str, subject_id: int, template_id: int):
    from .errors import ApprovalError as Error

    try:
        return start(actor, subject_type=subject_type, subject_id=subject_id, template_id=template_id)
    except Error as error:
        from apps.automation.services.actions import ActionSkip

        raise ActionSkip(error.message)


def _notify_decision(route, assignment, actor) -> None:
    from . import notify

    try:
        notify.decision(route, assignment, actor)
    except Exception:  # noqa: BLE001 — уведомление не должно ломать решение
        import logging

        logging.getLogger(__name__).exception("Уведомление о решении %s не создано", assignment.pk)


def _notify_assignment(route, assignment) -> None:
    from . import notify

    try:
        notify.assignment(route, assignment)
    except Exception:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).exception("Уведомление о задании %s не создано", assignment.pk)
