"""Публичный интерфейс сервис-деска: ответы по заявке (PLAN-003, «Где живёт код»)."""
from django.db import transaction

from ..models import TicketEntry


def add_event(ticket, event, *, actor=None, data=None):
    """Дописать в ленту событие (6.10): единственная точка записи событий для всех модулей.

    `actor=None` — событие системы. Время — «сейчас» (по умолчанию модели), `last_message_*`
    заявки не меняются, журнал пишет вызывающая служба. Код события не проверяется.
    """
    with transaction.atomic():
        return TicketEntry.objects.create(
            ticket=ticket, kind=TicketEntry.Kind.EVENT, event=event, author=actor, data=data or {},
        )


def on_files_checked(entry_id):
    """Проверен последний файл ответа: решить, отправлять ли его. Тело — T-3219 (6.10)."""
