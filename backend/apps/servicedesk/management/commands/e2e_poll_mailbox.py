"""Опрос ящика заявок и разбор писем сразу, без рабочего процесса (только при E2E_STAND=1; CONTRACT-003, 8.2).

Повторяет `mailbox.poll()` до нуля скачанных писем (при замке — до 10 попыток раз в секунду), затем в порядке `id` разбирает
письма в состоянии `received`. Вывод: `poll_mailbox: state=ok fetched=<n> parsed=<n> errors=<n>`.
"""
import os
import time

from django.core.management.base import BaseCommand, CommandError

from apps.servicedesk.models import InboundMail, MailboxState
from apps.servicedesk.services import intake, mailbox

LOCK_TRIES = 10
MAX_ROUNDS = 500  # защита от бесконечного опроса: за круг скачивается не больше 20 писем

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."


def require_stand() -> None:
    """Отказ без `E2E_STAND=1`; вызывается раньше любого чтения базы, Valkey и ящика."""
    if os.environ.get("E2E_STAND") != "1":
        raise CommandError(REFUSAL)


class Command(BaseCommand):
    help = "Опрашивает ящик заявок и разбирает письма сразу (только при E2E_STAND=1)."

    def _poll_all(self) -> int:
        fetched, locked = 0, 0
        drained = False
        for _ in range(MAX_ROUNDS):
            result = mailbox.poll()
            if result.state == "disabled":
                raise CommandError("Ящик заявок не настроен: IMAP_HOST пуст.")
            if result.state == "unavailable":
                error = MailboxState.objects.filter(pk=1).values_list("last_error", flat=True).first() or ""
                raise CommandError(f"Ящик заявок недоступен: {error}" if error else "Ящик заявок недоступен.")
            if result.state == "locked":
                locked += 1
                if locked >= LOCK_TRIES:
                    raise CommandError("Опрос ящика занят другим процессом.")
                time.sleep(1)
                continue
            locked = 0
            fetched += result.fetched
            if result.fetched == 0:
                drained = True
                break
        if not drained:
            self.stderr.write(f"Предупреждение: достигнут предел кругов опроса ({MAX_ROUNDS}); ящик мог быть выбран не до конца.")
        return fetched

    def handle(self, *args, **options):
        require_stand()
        fetched = self._poll_all()
        parsed = errors = 0
        for inbound_id in list(InboundMail.objects.filter(status=InboundMail.Status.RECEIVED)
                               .order_by("id").values_list("id", flat=True)):
            try:
                if intake.process(inbound_id) is not None:
                    parsed += 1
            except Exception:  # строка уже получила status="error"; команду ошибка разбора не останавливает
                errors += 1
        self.stdout.write(f"poll_mailbox: state=ok fetched={fetched} parsed={parsed} errors={errors}")
