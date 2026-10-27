"""Сдвиг сроков списков (только при E2E_STAND=1; CONTRACT-006, 13.1).

`e2e_lists_shift --days N`: сдвигает значения всех полей-сроков (`type="date"`, `settings.deadline`, в том числе скрытых)
всех записей (в том числе в архиве) и `ReminderSent.due_date` на N суток назад прямой записью `update` без `save()`:
`version`, `updated_at`, история и журнал не меняются. Затем в процессе команды выполняет обход сроков
`reminders.run(moscow_today())`. Вывод — одна строка `lists_shift: days=N shifted=<записей> notified=<уведомлений>`.
"""
import argparse
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db.models import F

from apps.core.widgets import moscow_today
from apps.lists.models import Field, Record, ReminderSent
from apps.lists.services import reminders
from apps.lists.stand import require_stand

MAX_DAYS = 3650
CHUNK = 500


def _number(text: str) -> int:
    """Тип аргумента: целое число (со знаком); не число — ошибка разбора (код 2). Пределы проверяет `handle` после
    проверки стенда: без `E2E_STAND=1` отказ стенда главнее ошибки значения."""
    digits = text[1:] if text[:1] in "+-" else text
    if not (digits.isascii() and digits.isdigit()):
        raise argparse.ArgumentTypeError(f"Нужно целое число от 1 до {MAX_DAYS}: {text}")
    return int(text)


def _moved(value, delta: timedelta):
    """Значение срока, сдвинутое назад; `None` — значение не дата в форме хранения (не трогается)."""
    if isinstance(value, str):
        try:
            return (date.fromisoformat(value) - delta).isoformat()
        except ValueError:
            return None
    return None


def _shift_records(delta: timedelta) -> int:
    """Сдвигает значения полей-сроков; возвращает число записей, у которых изменено хотя бы одно значение."""
    codes: dict[int, list[str]] = {}
    for field in Field.objects.filter(type=Field.Type.DATE).only("list_id", "code", "settings"):
        if (field.settings or {}).get("deadline"):
            codes.setdefault(field.list_id, []).append(field.code)
    shifted = 0
    for list_id, field_codes in codes.items():
        queryset = Record.objects.filter(list_id=list_id).only("id", "values").order_by("id")
        pending = []
        for record in queryset.iterator(chunk_size=CHUNK):
            changed = False
            for code in field_codes:
                new = _moved((record.values or {}).get(code), delta)
                if new is not None:
                    record.values[code] = new
                    changed = True
            if changed:
                pending.append(record)
            if len(pending) >= CHUNK:
                Record.objects.bulk_update(pending, ["values"])
                shifted += len(pending)
                pending = []
        if pending:
            Record.objects.bulk_update(pending, ["values"])
            shifted += len(pending)
    return shifted


class Command(BaseCommand):
    help = "Сдвигает сроки записей списков назад и запускает обход напоминаний (только при E2E_STAND=1)."

    def add_arguments(self, parser):
        parser.add_argument("--days", type=_number, required=True, help="сутки: на сколько сдвинуть сроки записей")

    def handle(self, *args, **options):
        require_stand()
        days = options["days"]
        if not 1 <= days <= MAX_DAYS:
            raise CommandError(f"Число вне пределов от 1 до {MAX_DAYS}: {days}")
        delta = timedelta(days=days)
        shifted = _shift_records(delta)
        ReminderSent.objects.update(due_date=F("due_date") - delta)
        result = reminders.run(moscow_today())
        self.stdout.write(f"lists_shift: days={days} shifted={shifted} notified={result.notified}")
