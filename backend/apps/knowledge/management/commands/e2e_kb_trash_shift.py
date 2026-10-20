"""Сдвиг срока корзины базы знаний (только при E2E_STAND=1; CONTRACT-005, 13).

`e2e_kb_trash_shift --days N`: сдвигает `deleted_at` всех статей в корзине на N суток назад прямой записью `update` без
`save()` (журнал и события не затрагиваются). Вывод — одна строка `kb_trash_shift: days=N shifted=<число статей>`.
"""
import argparse
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F

from apps.knowledge.models import Article
from apps.knowledge.stand import require_stand

MAX_DAYS = 36500


def _days(text: str) -> int:
    """Тип аргумента: целое от 1 до 36500; вне пределов — `CommandError`, не число — ошибка разбора (код 2)."""
    try:
        value = int(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"Нужно целое число от 1 до {MAX_DAYS}: {text}") from None
    if not 1 <= value <= MAX_DAYS:
        raise CommandError(f"Число вне пределов от 1 до {MAX_DAYS}: {value}")
    return value


class Command(BaseCommand):
    help = "Сдвигает срок статей в корзине назад (только при E2E_STAND=1)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=_days, required=True, help="сутки: на сколько сдвинуть срок статей в корзине")

    def handle(self, *args, **options):
        require_stand()
        days = options["days"]
        shifted = Article.objects.filter(state=Article.State.TRASH).update(
            deleted_at=F("deleted_at") - timedelta(days=days))
        self.stdout.write(f"kb_trash_shift: days={days} shifted={shifted}")
