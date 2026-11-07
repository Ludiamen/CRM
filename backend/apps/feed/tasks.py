"""Задания очереди и расписания ленты (срез 007)."""
from django.utils import timezone

from apps.feed.services import reminders, retention
from apps.feed.services.reminders import RunResult


def remind_events(now=None) -> RunResult:
    """Разослать напоминания о событиях, срок напоминания которых наступил.

    Задание cron: «сейчас» берётся из ``timezone.now()`` один раз и передаётся
    службе параметром (решение 59 задач), поэтому ``Clock`` и ручной вызов
    ``run_reminders(now)`` сдвигают время. Сам обход — ``reminders.run``.
    """
    return reminders.run(now or timezone.now())


def retention_night(now=None) -> int:
    """Ночное задание срока хранения: показы, записи старше срока, файлы.

    Задание cron: «сейчас» берётся из ``timezone.now()`` один раз и передаётся
    службе параметром (решение 59 задач), поэтому ``Clock`` и ручной вызов
    ``run_retention(now)`` задают время. Сам обход — ``retention.run``.
    """
    return retention.run(now or timezone.now())
