"""Сброс данных среза 014 на стенде (PLAN-014, T-14042)."""


def stand_reset() -> None:
    """Заготовка: заполняется на этапе 5; чистит маршруты, задания, шаблоны и события."""
    from .models import (ApprovalAssignment, ApprovalEvent, ApprovalNotice, ApprovalRoute,
                         ApprovalStage, ApprovalStageParticipant, ApprovalStageRun, ApprovalTemplate)

    ApprovalNotice.objects.all().delete()
    ApprovalEvent.objects.all().delete()
    ApprovalAssignment.objects.all().delete()
    ApprovalStageRun.objects.all().delete()
    ApprovalRoute.objects.all().delete()
    ApprovalStageParticipant.objects.all().delete()
    ApprovalStage.objects.all().delete()
    ApprovalTemplate.objects.all().delete()
