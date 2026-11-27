"""Сброс данных среза 014 на стенде (PLAN-014, T-14042)."""
from django.db import connections


def stand_reset() -> None:
    """Чистит маршруты, задания, шаблоны и события; на стенде — под владельцем схемы (`migrate`)."""
    from .models import (ApprovalAssignment, ApprovalEvent, ApprovalNotice, ApprovalRoute,
                         ApprovalStage, ApprovalStageParticipant, ApprovalStageRun, ApprovalTemplate)

    db = "migrate" if "migrate" in connections.databases else "default"
    for model in (ApprovalNotice, ApprovalEvent, ApprovalAssignment, ApprovalStageRun,
                  ApprovalRoute, ApprovalStageParticipant, ApprovalStage, ApprovalTemplate):
        model.objects.using(db).all().delete()
