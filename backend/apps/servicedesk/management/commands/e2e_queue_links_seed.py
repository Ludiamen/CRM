"""Синтетическое наполнение стенда для среза 012.

Команда намеренно работает только с ``E2E_STAND=1``. Все имена и адреса
тестовые, а повторный запуск обновляет те же строки по устойчивым ключам.
"""
import hashlib
import os
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone

from apps.servicedesk.models import (Priority, Queue, QueueObserver, QueueRule, Requester, Source, Status, Ticket,
                                     TicketEntry, TicketRating)


REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."
QUEUE_NAMES = ("E2E 012 Равномерно", "E2E 012 По очереди", "E2E 012 Всем", "E2E 012 Выключен")
MODES = ("evenly", "strictly", "all", "off")


class Command(BaseCommand):
    help = "Стенд: очереди, режимы, наблюдатель, недоступный сотрудник, рейтинг и задача среза 012."

    def handle(self, *args, **options):
        if os.environ.get("E2E_STAND") != "1":
            raise CommandError(REFUSAL)
        from django.contrib.auth import get_user_model
        from apps.org.services import membership, structure

        people = list(get_user_model().objects.filter(state="active").order_by("pk")[:5])
        if not people:
            self.stdout.write("e2e_queue_links_seed: queues=0 rules=0 tickets=0 ratings=0 tasks=0")
            return
        actor = people[0]
        participants = people[1:4] or [actor]
        observer = people[4] if len(people) > 4 else participants[-1]
        with transaction.atomic():
            queues = []
            for name in QUEUE_NAMES:
                queue = Queue.objects.select_related("unit").filter(unit__name=name).first()
                if queue is None:
                    unit = structure.create_unit(kind="department", name=name, parent=structure.root(), actor=actor)
                    queue, _ = Queue.objects.get_or_create(
                        unit=unit, defaults={"created_by": actor, "created_at": timezone.now()})
                queues.append(queue)
                membership.add_members(queue.unit, participants, mode=membership.CONCURRENT, actor=actor)
            for queue, mode in zip(queues, MODES):
                QueueRule.objects.update_or_create(
                    queue=queue, defaults={"mode": mode, "updated_by": actor})
            QueueObserver.objects.update_or_create(
                queue=queues[2], user=observer, removed_at=None,
                defaults={"added_by": actor, "added_at": timezone.now()})
            unavailable = participants[-1]
            unavailable.unavailable_until = timezone.localdate() + timedelta(days=2)
            unavailable.unavailable_note = "E2E 012: недоступен"
            unavailable.unavailable_by = actor
            unavailable.unavailable_at = timezone.now()
            unavailable.save(update_fields=["unavailable_until", "unavailable_note", "unavailable_by", "unavailable_at"])
            ticket = self._ticket(queues[0], actor, participants[0])
            rating = self._rating(ticket)
            from apps.core import extensions
            creators = extensions.registered("ticket_task_create")
            task = (creators[0](participants[0], ticket.number, title="E2E 012: задача из заявки",
                                description=f"Связь с заявкой #{ticket.number}", assignee=participants[0])
                    if creators else None)
        self.stdout.write(
            f"e2e_queue_links_seed: queues={len(queues)} rules={QueueRule.objects.filter(queue__in=queues).count()} "
            f"tickets={1} ratings={1 if rating else 0} tasks={1 if task else 0}")

    @staticmethod
    def _ticket(queue, actor, assignee):
        requester, _ = Requester.objects.get_or_create(
            email="e2e-012-requester@example.invalid",
            defaults={"full_name": "Стенд 012", "origin": Requester.Origin.TICKET})
        priority = Priority.objects.filter(name_key="средняя").first() or Priority.objects.first()
        status = Status.objects.get(kind="closed", is_default=True)
        source = Source.objects.filter(system_code="mail").first() or Source.objects.order_by("pk").first()
        with connection.cursor() as cursor:
            cursor.execute("SELECT nextval('servicedesk_ticket_number')")
            number = cursor.fetchone()[0]
        ticket, _ = Ticket.objects.update_or_create(
            subject="E2E 012: заявка для оценки",
            defaults={"number": number, "requester": requester, "requester_email": requester.email,
                      "requester_name": requester.full_name,
                      "queue": queue.unit, "priority": priority, "status": status, "kind": "closed",
                      "source": source,
                      "assignee": assignee, "created_by": actor, "closed_at": timezone.now(),
                      "closed_by": actor, "last_message_at": timezone.now(), "resolution": "E2E 012"})
        TicketEntry.objects.get_or_create(ticket=ticket, kind="incoming", defaults={
            "text": "Синтетическая заявка E2E 012", "author_email": requester.email,
            "author_name": requester.full_name, "at": timezone.now()})
        return ticket

    @staticmethod
    def _rating(ticket):
        closed_at = ticket.closed_at or timezone.now()
        code = "012E2EDEM01"
        return TicketRating.objects.update_or_create(
            ticket=ticket, cycle_number=1,
            defaults={"closed_at_snapshot": closed_at,
                      "token_hash": hashlib.sha256(code.encode("ascii")).hexdigest(),
                      "score": 5, "expires_at": closed_at + timedelta(days=7), "is_current": True,
                      "rated_at": timezone.now(), "queue_id": ticket.queue_id,
                      "queue_name": ticket.queue.name, "assignee_id": ticket.assignee_id,
                      "assignee_name": ticket.assignee.full_name if ticket.assignee_id else ""})[0]

