"""Пачка уведомлений сотруднику для приёмки (только при E2E_STAND=1; CONTRACT-004, 8.2).

`e2e_notify_fill ПОЧТА N [--read K]`: создаёт `N` уведомлений напрямую (`bulk_create`), без доставок, без событий шины и без
записи в журнал; `K` самых старых созданы прочитанными. Затем `live.push` — открытые вкладки получают новое число.
Вывод: `notify_fill: created=<N> read=<K> unread=<N-K>`.
"""
import argparse
import datetime

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.notify.management.commands.e2e_notify_tick import require_stand
from apps.notify.models import Notification
from apps.notify.services import live

MAX_COUNT = 1000
KIND = "core.password_changed"   # вид из каталога ядра (решение C2)


def _integer(low: int, high: int | None = None):
    """Тип аргумента: целое не меньше `low` (и не больше `high`, если задан); иное — `CommandError`."""
    def parse(text: str) -> int:
        try:
            value = int(text)
        except ValueError:
            raise argparse.ArgumentTypeError(f"Нужно целое число: {text}") from None  # не число — ошибка разбора, код 2 (§ 8.1)
        if value < low or (high is not None and value > high):
            raise CommandError(f"Число вне пределов: {value}")
        return value
    return parse


class Command(BaseCommand):
    help = "Создаёт сотруднику N уведомлений, K самых старых прочитаны (только при E2E_STAND=1)."

    def add_arguments(self, parser):
        parser.add_argument("email")
        parser.add_argument("count", type=_integer(1, MAX_COUNT))
        parser.add_argument("--read", type=_integer(0), default=0)

    def handle(self, *args, **options):
        require_stand()
        count, read = options["count"], options["read"]
        if read > count:
            raise CommandError(f"Прочитанных не может быть больше {count}: {read}")
        user = get_user_model().objects.filter(email__iexact=options["email"]).first()
        if user is None:
            raise CommandError("Сотрудник с таким адресом не найден.")
        now = timezone.now()
        rows = []
        for i in range(1, count + 1):
            created = now - datetime.timedelta(seconds=count - i)
            rows.append(Notification(user=user, kind=KIND, text=f"Тестовое уведомление {i}", url="/notifications/",
                                     object_ref="", created_at=created, read_at=created if i <= read else None))
        Notification.objects.bulk_create(rows)
        live.push([user.pk])
        self.stdout.write(f"notify_fill: created={count} read={read} unread={count - read}")
