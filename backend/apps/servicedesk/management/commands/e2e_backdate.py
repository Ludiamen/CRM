"""Сдвиг сохранённой отметки назад на сутки (только при E2E_STAND=1; CONTRACT-003, 8.2).

`e2e_backdate <kind> <ref> <field> <days>`: `ticket` (ref — номер заявки), `mail` (ref — Message-ID вместе с `<` `>`),
`mailbox` (ref — `-`). Запись идёт через `update` без `save()`; пустое значение отсчитывается от «сейчас».
Вывод: `backdate: <kind> <ref> <field> -<days>d <было ISO UTC> -> <стало ISO UTC>`.
"""
import os
from datetime import timedelta, timezone as dt_timezone

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from apps.servicedesk.models import InboundMail, MailboxState, Ticket

FIELDS = {
    "ticket": ("waiting_since", "closed_at", "created_at", "last_message_at"),
    "mail": ("received_at",),
    "mailbox": ("last_ok_at",),
}


def _iso(value) -> str:
    return value.astimezone(dt_timezone.utc).isoformat()


MAX_DAYS = 36500  # больше — timedelta/вычитание дают OverflowError вместо отказа

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."


def require_stand() -> None:
    """Отказ без `E2E_STAND=1`; вызывается раньше любого чтения базы, Valkey и ящика."""
    if os.environ.get("E2E_STAND") != "1":
        raise CommandError(REFUSAL)


class Command(BaseCommand):
    help = "Сдвигает отметку времени заявки, письма или ящика назад на сутки (только при E2E_STAND=1)."

    def add_arguments(self, parser):
        parser.add_argument("kind")
        parser.add_argument("ref")
        parser.add_argument("field")
        parser.add_argument("days")

    def _find(self, kind: str, ref: str):
        """Запись по виду и ссылке; нет записи (или письмо не одно) — отказ."""
        if kind == "ticket":
            if not ref.isascii() or not ref.isdigit() or int(ref) > 2_147_483_647:
                raise CommandError(f"Номер заявки не число: {ref}")
            found = Ticket.objects.filter(number=int(ref))
        elif kind == "mail":
            found = InboundMail.objects.filter(message_id=ref)
        else:
            found = MailboxState.objects.filter(pk=1)
        rows = list(found[:2])
        if not rows:
            raise CommandError(f"Объект не найден: {kind} {ref}")
        if len(rows) > 1:
            raise CommandError(f"Найдено несколько писем с Message-ID {ref}")
        return rows[0]

    def handle(self, *args, **options):
        require_stand()
        kind, ref, field, raw_days = options["kind"], options["ref"], options["field"], options["days"]
        if kind not in FIELDS:
            raise CommandError(f"Неизвестный вид: {kind}; допустимы ticket, mail, mailbox")
        if field not in FIELDS[kind]:
            raise CommandError(f"Поле {field} не относится к виду {kind}; допустимы {', '.join(FIELDS[kind])}")
        if not raw_days.isascii() or not raw_days.isdigit() or int(raw_days) < 1 or int(raw_days) > MAX_DAYS:
            raise CommandError(f"Число суток — целое от 1 до 36500: {raw_days}")
        days = int(raw_days)
        row = self._find(kind, ref)
        was = getattr(row, field) or timezone.now()
        became = was - timedelta(days=days)
        type(row).objects.filter(pk=row.pk).update(**{field: became})  # без save(): auto_now и сигналы не трогаются
        self.stdout.write(f"backdate: {kind} {ref} {field} -{days}d {_iso(was)} -> {_iso(became)}")
