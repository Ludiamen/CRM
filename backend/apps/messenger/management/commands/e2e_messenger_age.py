"""Состаривание сообщений мессенджера (только при E2E_STAND=1; план 008, «Проверка» → «данные установки и стенд»).

`e2e_messenger_age --days N`: сдвигает `Message.created_at` всех сообщений на N суток в прошлое прямой
записью (`update(F("created_at") − delta)` без `save()`, одним `UPDATE`); службы мессенджера не вызываются,
другие таблицы не меняются (`Chat.last_message_at` не пересчитывается — стенд состаривает только отметки
времени). Вывод — одна строка `messenger_age: aged=<состариено>`.

Модель `Message` импортируется внутри `handle()`, как принято в срезах: сбор тестов и `manage.py help`
проходят до появления моделей. Здесь же проверка стенда (копия образца `feed`, не импорт): без `E2E_STAND=1`
отказ раньше любого чтения базы.
"""
import argparse
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F

from apps.messenger.stand import require_stand

MAX_DAYS = 3650


def _number(text: str) -> int:
    """Тип аргумента: целое число (со знаком); не число — ошибка разбора. Пределы проверяет `handle` после
    проверки стенда: без `E2E_STAND=1` отказ стенда главнее ошибки значения."""
    digits = text[1:] if text[:1] in "+-" else text
    if not (digits.isascii() and digits.isdigit()):
        raise argparse.ArgumentTypeError(f"Нужно целое число от 0 до {MAX_DAYS}: {text}")
    return int(text)


class Command(BaseCommand):
    help = "Состаривает сообщения мессенджера на N суток (только при E2E_STAND=1)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=_number, required=True,
                            help="сутки: на сколько состарить сообщения (от 0 до 3650)")

    def handle(self, *args, **options):
        require_stand()
        days = options["days"]
        if not 0 <= days <= MAX_DAYS:
            raise CommandError(f"Число вне пределов от 0 до {MAX_DAYS}: {days}")
        from apps.messenger.models import Message  # модель появляется в T-8200

        delta = timedelta(days=days)
        aged = Message.objects.update(created_at=F("created_at") - delta)
        self.stdout.write(f"messenger_age: aged={aged}")