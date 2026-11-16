"""Задания очереди и расписания ленты (срез 007)."""
from django.utils import timezone

from apps.feed.services import reminders, retention
from apps.feed.services.reminders import RunResult


def publish_event(post_id, action, comment_id=None, recipients=None, owner_id=None):
    """Задание очереди `notify`: фан-аут живых обновлений `live.publish_event`.

    Рассылка уходит из запроса действия в worker-notify (план «Риски»: при p95 публикации
    выше 500 мс уведомления и рассылка уходят заданием очереди `notify`). Порядок и семантика
    личных групп/ООB/счётчиков сохраняются — задание зовёт ту же `live.publish_event`.
    `recipients` передаётся списком (сериализация RQ) и снимается готовым множеством только
    для удаления записи, когда адресатов в базе уже нет.
    """
    from apps.feed.services import live

    return live.publish_event(
        post_id,
        action,
        comment_id=comment_id,
        recipients=frozenset(recipients) if recipients is not None else None,
        owner_id=owner_id,
    )


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
