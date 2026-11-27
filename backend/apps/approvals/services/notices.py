"""Напоминания о сроке заданий (PLAN-014, T-14031)."""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from ..models import ApprovalAssignment, ApprovalNotice, ApprovalRoute
from . import notify

logger = logging.getLogger(__name__)


def run_due(now=None) -> int:
    now = now or timezone.now()
    # Напоминание нужно, когда до срока осталось не больше 24 часов; прошедший срок — отдельный вид.
    rows = (ApprovalAssignment.objects.filter(
        status=ApprovalAssignment.Status.PENDING, due_at__isnull=False,
        due_at__lte=now + timedelta(hours=24),
        stage_run__route__status=ApprovalRoute.Status.RUNNING)
        .select_related("stage_run__route", "user").order_by("due_at", "pk")[:50])
    done = 0
    for row in rows:
        with transaction.atomic():
            claimed = (ApprovalAssignment.objects.select_for_update(skip_locked=True)
                       .select_related("stage_run__route", "user")
                       .filter(pk=row.pk, status=ApprovalAssignment.Status.PENDING).first())
            if claimed is None:
                continue
            kind = ApprovalNotice.Kind.OVERDUE if claimed.due_at <= now else ApprovalNotice.Kind.REMINDER
            if kind == ApprovalNotice.Kind.REMINDER and claimed.due_at - timedelta(hours=24) <= claimed.created_at:
                continue
            marker, created = ApprovalNotice.objects.get_or_create(assignment=claimed, kind=kind)
            if not created:
                continue
            try:
                if kind == ApprovalNotice.Kind.OVERDUE:
                    notify.overdue(claimed)
                else:
                    notify.reminder(claimed)
            except Exception:  # noqa: BLE001
                logger.exception("Уведомление о сроке задания %s не создано", claimed.pk)
                marker.delete()
                continue
            done += 1
    return done
