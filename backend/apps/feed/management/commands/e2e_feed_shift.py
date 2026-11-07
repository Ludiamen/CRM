"""Сдвиг событий и важных записей ленты назад (только при E2E_STAND=1; CONTRACT-007, 14.1).

`e2e_feed_shift --minutes N`: сдвигает `event_start`, `event_end`, `remind_at` и
`reminded_for_start` всех событий и `important_until` всех важных записей на N минут раньше
прямой записью (`update(F() − delta)` без `save()`); затем выполняет задание напоминаний
`reminders.run(now)` в процессе команды (не через очередь — ловушка сна ноутбука и RQ),
«сейчас» берётся из `timezone.now()` один раз (решение 59 задач). Вывод — одна строка
`feed_shift: shifted=<события> reminded=<напоминания> important=<важные>`.
"""
import argparse
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F
from django.utils import timezone

from apps.feed.models import Post
from apps.feed.services import reminders
from apps.feed.stand import require_stand

MAX_MINUTES = 10080


def _number(text: str) -> int:
    """Тип аргумента: целое число (со знаком); не число — ошибка разбора. Пределы проверяет `handle` после
    проверки стенда: без `E2E_STAND=1` отказ стенда главнее ошибки значения."""
    digits = text[1:] if text[:1] in "+-" else text
    if not (digits.isascii() and digits.isdigit()):
        raise argparse.ArgumentTypeError(f"Нужно целое число от 1 до {MAX_MINUTES}: {text}")
    return int(text)


class Command(BaseCommand):
    help = "Сдвигает события и важные записи ленты назад и запускает напоминания (только при E2E_STAND=1)."

    def add_arguments(self, parser):
        parser.add_argument("--minutes", type=_number, required=True,
                            help="минуты: на сколько сдвинуть события и важные записи назад")

    def handle(self, *args, **options):
        require_stand()
        minutes = options["minutes"]
        if not 1 <= minutes <= MAX_MINUTES:
            raise CommandError(f"Число вне пределов от 1 до {MAX_MINUTES}: {minutes}")
        delta = timedelta(minutes=minutes)
        shifted = Post.objects.filter(kind=Post.Kind.EVENT).update(
            event_start=F("event_start") - delta,
            event_end=F("event_end") - delta,
            remind_at=F("remind_at") - delta,
            reminded_for_start=F("reminded_for_start") - delta,
        )
        important = Post.objects.filter(kind=Post.Kind.IMPORTANT).update(
            important_until=F("important_until") - delta,
        )
        now = timezone.now()
        result = reminders.run(now)
        self.stdout.write(
            f"feed_shift: shifted={shifted} reminded={result.reminded} important={important}"
        )
