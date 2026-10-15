"""Сдвиг сроков и обход уведомлений (только при E2E_STAND=1; CONTRACT-004, 8.1, 8.2).

`e2e_notify_tick [--shift N] [--age-codes M] [--age-days D] [--retention]`: сначала сдвиги (`--age-days`, `--age-codes`,
`--shift`) прямой записью `update` без `save()`, затем всегда обход `tasks.notify_tick()`, затем при `--retention` —
`tasks.notify_retention()`. Вывод — одна строка `notify_tick: shifted=… aged_codes=… aged_rows=… emails=… released=…
requeued=… digests=… codes=…` (при `--retention` дописываются `retention_*`).
"""
import argparse
import datetime
import os

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F

from apps.notify import tasks
from apps.notify.models import BindCode, Delivery, Digest, Notification

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."
MAX_MINUTES = 525600
MAX_DAYS = 36500


def require_stand() -> None:
    """Отказ без `E2E_STAND=1`; вызывается раньше любого чтения базы, Valkey и `fakebots`."""
    if os.environ.get("E2E_STAND") != "1":
        raise CommandError(REFUSAL)


def _bounded(limit: int):
    """Тип аргумента: целое от 1 до `limit`; иное — `CommandError`."""
    def parse(text: str) -> int:
        try:
            value = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"Нужно целое число от 1 до {limit}: {text}") from None  # не число — ошибка разбора, код 2 (§ 8.1)
        if not 1 <= value <= limit:
            raise CommandError(f"Число вне пределов от 1 до {limit}: {value}")
        return value
    return parse


class Command(BaseCommand):
    help = "Сдвигает сроки уведомлений назад и выполняет обход (только при E2E_STAND=1)."

    def add_arguments(self, parser):
        parser.add_argument("--shift", type=_bounded(MAX_MINUTES), default=0, help="минуты: срок ожидающих доставок назад")
        parser.add_argument("--age-codes", type=_bounded(MAX_MINUTES), default=0, help="минуты: срок кодов привязки назад")
        parser.add_argument("--age-days", type=_bounded(MAX_DAYS), default=0, help="сутки: возраст уведомлений и сводок")
        parser.add_argument("--retention", action="store_true", help="после обхода выполнить ночное удаление")

    def handle(self, *args, **options):
        require_stand()
        days, codes_minutes, shift = options["age_days"], options["age_codes"], options["shift"]
        aged_rows = 0
        if days:
            delta = datetime.timedelta(days=days)
            aged_rows = (Notification.objects.update(created_at=F("created_at") - delta)
                         + Digest.objects.update(created_at=F("created_at") - delta))
            for field in ("due_at", "enqueued_at", "lease_until"):
                Delivery.objects.filter(**{f"{field}__isnull": False}).update(**{field: F(field) - delta})
        aged_codes = 0
        if codes_minutes:
            aged_codes = BindCode.objects.update(expires_at=F("expires_at") - datetime.timedelta(minutes=codes_minutes))
        shifted = 0
        if shift:
            shifted = Delivery.objects.filter(state=Delivery.State.WAITING, due_at__isnull=False).update(
                due_at=F("due_at") - datetime.timedelta(minutes=shift), enqueued_at=None)
        tick = tasks.notify_tick()
        line = (f"notify_tick: shifted={shifted} aged_codes={aged_codes} aged_rows={aged_rows} emails={tick['emails']} "
                f"released={tick['released']} requeued={tick['requeued']} digests={tick['digests']} codes={tick['codes']}")
        if options["retention"]:
            kept = tasks.notify_retention()
            line += (f" retention_notifications={kept['notifications']} retention_digests={kept['digests']} "
                     f"retention_codes={kept['codes']} retention_botchats={kept['botchats']}")
        self.stdout.write(line)
