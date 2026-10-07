"""Действия после восстановления из копии: сдвиг номеров заявок и разбор писем (FR-201, FR-211, NFR-210).

Команду запускает администратор по `deploy/RESTORE.md` от владельца схемы
(`docker compose run --rm migrate python manage.py servicedesk_after_restore`): у роли приложения на
последовательности только `USAGE`, а `setval` требует записи. Все чтения и записи идут через соединение `migrate`.
Команда не защищена флагом стенда.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction
from django.db.models import Max

from apps.servicedesk.models import InboundMail, Ticket
from apps.servicedesk.services import intake

SHIFT = 1000  # номера, выданные после копии (до 100 в день при RPO 24 часа), больше не выдаются


class Command(BaseCommand):
    help = "После восстановления из копии: сдвигает номера заявок на 1000 вперёд и ставит разбор полученным письмам."

    def handle(self, *args, **options):
        if "migrate" not in connections.databases:
            raise CommandError("Нужен DATABASE_MIGRATE_URL: команда работает под владельцем схемы.")
        with transaction.atomic(using="migrate"):
            with connections["migrate"].cursor() as cursor:
                cursor.execute("SELECT last_value, is_called FROM servicedesk_ticket_number")
                last_value, is_called = cursor.fetchone()
                current = int(last_value) if is_called else int(last_value) - 1
                top = Ticket.objects.using("migrate").aggregate(top=Max("number"))["top"] or 0
                new = max(current, top) + SHIFT
                cursor.execute("SELECT setval('servicedesk_ticket_number', %s, true)", [new])
            ids = list(InboundMail.objects.using("migrate").filter(status=InboundMail.Status.RECEIVED)
                       .order_by("id").values_list("id", flat=True))
        for inbound_id in ids:
            intake.enqueue(inbound_id)
        self.stdout.write(f"after_restore: sequence={new} max_number={top} requeued={len(ids)}")
