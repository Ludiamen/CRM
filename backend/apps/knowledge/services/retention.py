"""Ночная очистка корзины (PLAN-005, «Корзина и ночная очистка»; FR-417, NFR-410).

Других заданий хранения у базы знаний нет (FR-448): статьи, версии, комментарии и вложения сроком не чистятся.
"""
import logging
from datetime import datetime, timedelta
from typing import NamedTuple

from django.db import connection, transaction
from django.utils import timezone

from ..models import Article, Tag
from . import articles
from . import settings as kb_settings

logger = logging.getLogger(__name__)

BATCH = 100
TAGS_LOCK_KEY = "knowledge.tags"


class PurgeResult(NamedTuple):
    """Итог обхода: удалено, пропущено (вернули, срок не вышел, строка занята) и номера статей со сбоем."""

    purged: int
    skipped: int
    failed: list


class PurgeFailed(RuntimeError):
    """Задание завершается ошибкой после обхода, если у каких-то статей был сбой; `numbers` — их номера."""

    def __init__(self, numbers):
        self.numbers = list(numbers)
        super().__init__("Сбой удаления статей из корзины: " + ", ".join(str(n) for n in self.numbers))


def next_batch(after_id: int, cutoff: datetime) -> list[int]:
    """До 100 номеров статей в корзине со сроком, вышедшим раньше `cutoff`, с номером больше `after_id`, по возрастанию."""
    return list(Article.objects.filter(state=Article.State.TRASH, deleted_at__lt=cutoff, pk__gt=after_id)
                .order_by("pk").values_list("pk", flat=True)[:BATCH])


def _purge_one(number: int, cutoff: datetime) -> bool:
    """Удаляет одну статью в своей транзакции; `False` — пропущена (повторная проверка под замком строки)."""
    with transaction.atomic():
        article = (Article.objects.select_for_update(skip_locked=True)
                   .filter(pk=number, state=Article.State.TRASH, deleted_at__lt=cutoff).first())
        if article is None:
            return False
        articles.purge(article, None, by_term=True)
    return True


def _delete_unused_tags() -> None:
    """Теги без единой статьи — под исключительным замком: тег, который сейчас привязывается (разделяемый замок
    сохранения статьи), не исчезнет."""
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [TAGS_LOCK_KEY])
        Tag.objects.filter(article__isnull=True).delete()


def purge_trash(now: datetime | None = None) -> PurgeResult:
    """Удаляет навсегда статьи, пробывшие в корзине дольше срока; порции по 100, каждая статья — своя транзакция.

    Сбой одной статьи пишется в журнал приложения (номер и класс исключения, без текста), обход продолжается.
    """
    now = now or timezone.now()
    cutoff = now - timedelta(days=kb_settings.get().trash_days)
    purged = skipped = 0
    failed: list[int] = []
    after = 0
    while True:
        batch = next_batch(after, cutoff)
        if not batch:
            break
        for number in batch:
            try:
                if _purge_one(number, cutoff):
                    purged += 1
                else:
                    skipped += 1
            except Exception as exc:
                failed.append(number)
                logger.error("Статья %s: сбой удаления по сроку (%s)", number, type(exc).__name__)
        after = batch[-1]
    _delete_unused_tags()
    return PurgeResult(purged, skipped, failed)
