"""Состаривание записей ленты (только при E2E_STAND=1; CONTRACT-007, 14.2).

`e2e_feed_retention --age-days N [--posts <номера через запятую>]`: сдвигает `published_at`
выбранных записей (без `--posts` — всех записей стенда) и копии `Recipient.published_at` на N
суток в прошлое прямой записью (`update(F() − delta)` без `save()`); затем выполняет ночное
задание `retention.run(now)` в процессе команды, «сейчас» берётся из `timezone.now()` один раз
(решение 59 задач). Вывод — одна строка `feed_retention: aged=<состарено> deleted=<удалено>`.
"""
import argparse
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F
from django.utils import timezone

from apps.feed.models import Post, Recipient
from apps.feed.services import retention
from apps.feed.stand import require_stand

MAX_DAYS = 4000


def _number(text: str) -> int:
    """Тип аргумента: целое число (со знаком); не число — ошибка разбора. Пределы проверяет `handle` после
    проверки стенда: без `E2E_STAND=1` отказ стенда главнее ошибки значения."""
    digits = text[1:] if text[:1] in "+-" else text
    if not (digits.isascii() and digits.isdigit()):
        raise argparse.ArgumentTypeError(f"Нужно целое число от 1 до {MAX_DAYS}: {text}")
    return int(text)


def _post_ids(text: str) -> list[int]:
    """Номера записей через запятую без пробелов; не целые — отказ (К40) до любого изменения."""
    ids = []
    for part in text.split(","):
        if not (part.isascii() and part.isdigit()):
            raise CommandError(f"Неверный список записей: {text}")
        ids.append(int(part))
    return ids


class Command(BaseCommand):
    help = "Состаривает записи ленты и запускает ночное задание срока хранения (только при E2E_STAND=1)."

    def add_arguments(self, parser):
        parser.add_argument("--age-days", type=_number, required=True,
                            help="сутки: на сколько состарить записи")
        parser.add_argument("--posts", default=None,
                            help="номера записей через запятую без пробелов (без ключа — все записи стенда)")

    def handle(self, *args, **options):
        require_stand()
        days = options["age_days"]
        if not 1 <= days <= MAX_DAYS:
            raise CommandError(f"Число вне пределов от 1 до {MAX_DAYS}: {days}")
        ids = _post_ids(options["posts"]) if options["posts"] is not None else None
        delta = timedelta(days=days)
        posts = Post.objects.all() if ids is None else Post.objects.filter(pk__in=ids)
        aged = posts.update(published_at=F("published_at") - delta)
        Recipient.objects.filter(post__in=posts).update(published_at=F("published_at") - delta)
        now = timezone.now()
        deleted = retention.run(now)
        self.stdout.write(f"feed_retention: aged={aged} deleted={deleted}")
