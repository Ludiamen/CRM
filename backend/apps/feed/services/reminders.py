"""Сервис ленты: напоминания о событиях (срез 007; CONTRACT-007, 5.4).

Обход событий со сроком напоминания идёт по одной записи: выборка номера
SQL-литералом плана с ``FOR UPDATE SKIP LOCKED``, напоминание — в той же
транзакции. Сбойное событие исключается из выборки параметром ``id <> ALL(%s)``
до конца запуска и не останавливает обход (решение 12 задач); «сейчас» —
параметр из ``timezone.now()``, а не функция базы (решение 59 задач).
"""
import logging
from typing import NamedTuple

from django.apps import apps
from django.db import connection, transaction
from django.utils import timezone

from apps.core.extensions import Draft
from apps.feed.models import EventAnswer, Post
from apps.feed.services import text

# Логгер заданий контракта: запись о сбойном событии — ERROR логгера
# ``apps.feed.tasks`` (раздел 5.8, К59), независимо от того, где живёт обход.
logger = logging.getLogger("apps.feed.tasks")

RUN_LIMIT = 200

SELECT_DUE_SQL = """
    SELECT id FROM feed_post
    WHERE remind_at <= %s
      AND event_start > %s
      AND reminded_for_start IS DISTINCT FROM event_start
      AND id <> ALL(%s)
    ORDER BY remind_at
    LIMIT 1
    FOR UPDATE SKIP LOCKED
"""


class RunResult(NamedTuple):
    """Итог запуска: число отправленных напоминаний и номера сбойных записей."""

    reminded: int
    failed: list[int]


def _reminder_text(post: Post) -> str:
    """Текст «Напоминания о событии» (CONTRACT-007, 7.2): название и место — отрезки до 60 знаков,
    весь текст — не длиннее 300 (К26)."""
    title = text.snippet(post.event_title, 60)
    place = text.snippet(post.event_place, 60)
    return text.snippet(f"Через час: «{title}», {place}", 300)


def select_due(now, exclude) -> int | None:
    """Номер одного события, срок напоминания которого наступил (литерал плана).

    ``now`` и ``exclude`` — параметры запроса: ``Clock`` и ручной вызов задают
    «сейчас», сбойные записи исключаются до конца запуска. Замок строки берётся
    здесь и держится транзакцией вызывающего.
    """
    with connection.cursor() as cursor:
        cursor.execute(SELECT_DUE_SQL, [now, now, list(exclude)])
        row = cursor.fetchone()
    return row[0] if row else None


def remind_one(post_id: int, now) -> bool:
    """Напомнить об одном событии в транзакции выборки.

    Записи нет (удалена между выборкой и замком) — ``False`` без ошибки.
    Получатели — аудитория события минус ответившие «Не смогу» (автор приходит
    всегда); отметка «напомнено» ставится вместе с уведомлениями.
    """
    post = Post.objects.filter(pk=post_id).first()
    if post is None:
        return False

    from apps.feed.services import visibility

    audience = visibility.audience(post)
    no_answerers = set(
        EventAnswer.objects.filter(post=post, answer=EventAnswer.Answer.NO)
        .values_list("user_id", flat=True)
    )
    recipients = audience - no_answerers

    if apps.is_installed("apps.notify"):
        from apps.notify.services import dispatch

        dispatch.create(
            "feed.event_reminder",
            [
                Draft(
                    user_id=user_id,
                    text=_reminder_text(post),
                    url=f"/feed/{post.pk}/",
                    object_ref=f"feed.post:{post.pk}",
                )
                for user_id in recipients
            ],
        )

    Post.objects.filter(pk=post.pk).update(
        reminded_for_start=post.event_start, remind_at=None
    )
    return True


def run(now=None) -> RunResult:
    """Обойти события со сроком: не больше 200 за запуск, сбой не валит задание.

    Каждое событие — своя транзакция с перехватом исключения; сбойный номер
    пишется в журнал приложения (только номер) и в ``exclude`` до конца
    запуска, остальные события обходятся дальше.
    """
    if now is None:
        now = timezone.now()

    reminded = 0
    failed: list[int] = []
    exclude: list[int] = []
    handled = 0

    while handled < RUN_LIMIT:
        post_id = None
        try:
            with transaction.atomic():
                post_id = select_due(now, exclude)
                if post_id is None:
                    break
                if remind_one(post_id, now):
                    reminded += 1
        except Exception as error:  # noqa: BLE001 — сбой одного события не останавливает обход
            if post_id is None:
                logger.error("reminder selection failed: %s", type(error).__name__)
            else:
                logger.error("feed.event_reminder failed for post %s", post_id)
                failed.append(post_id)
                exclude.append(post_id)
        handled += 1

    return RunResult(reminded, failed)
