"""Ночные задания `org` (T-2218, FR-141, FR-145; CONTRACT-002, § 3)."""
from datetime import timedelta

from django.utils import timezone

from apps.org.models import CalendarUpload, StaffImport

# Неподтверждённый предпросмотр живёт сутки
PREVIEW_KEEP = timedelta(days=1)


def purge_previews() -> int:
    """Удаляет неподтверждённые предпросмотры загрузки сотрудников и календаря старше суток; возвращает число строк."""
    border = timezone.now() - PREVIEW_KEEP
    total = 0
    for model in (StaffImport, CalendarUpload):
        total += model.objects.filter(state="preview", created_at__lt=border).delete()[0]
    return total
