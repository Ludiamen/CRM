"""Выполнение фонового задания целиком, прямо в процессе команды (только при E2E_STAND=1; CONTRACT-003, 8.2).

`e2e_run_job <job>`: `autoclose`, `anonymize_tickets`, `purge_inbound`. Служба вызывается порциями по 50 с курсором
`after=batch.last` до конца цепочки; задания RQ и очередь `maintenance` не используются.
Вывод: `run_job: <job> done=<обработано> batches=<порций>`.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from apps.servicedesk.services import closing, retention

SIZE = 50
NIGHTLY_LIMIT = 2000  # как у задания `anonymize_tickets`: за запуск не больше 2000 заявок


def _autoclose(done_total, after):
    return closing.autoclose_batch(limit=SIZE, after=after)


def _anonymize_tickets(done_total, after):
    return retention.anonymize_batch(size=SIZE, done_total=done_total, nightly_limit=NIGHTLY_LIMIT, after=after)


def _purge_inbound(done_total, after):
    return retention.purge_inbound(size=SIZE, after=after)


JOBS = {"autoclose": _autoclose, "anonymize_tickets": _anonymize_tickets, "purge_inbound": _purge_inbound}

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."


def require_stand() -> None:
    """Отказ без `E2E_STAND=1`; вызывается раньше любого чтения базы, Valkey и ящика."""
    if os.environ.get("E2E_STAND") != "1":
        raise CommandError(REFUSAL)


class Command(BaseCommand):
    help = "Выполняет фоновое задание целиком в процессе команды (только при E2E_STAND=1)."

    def add_arguments(self, parser):
        parser.add_argument("job", choices=sorted(JOBS))

    def handle(self, *args, **options):
        require_stand()
        step = JOBS[options["job"]]
        done_total, batches, after = 0, 0, None
        while True:
            batch = step(done_total, after)
            batches += 1
            done_total += batch.done
            if not batch.more:
                break
            after = batch.last
        self.stdout.write(f"run_job: {options['job']} done={done_total} batches={batches}")
