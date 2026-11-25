"""Заполнение стенда данными SLA среза 011 (T-11005).

Команда работает только при `E2E_STAND=1`, создаёт два уровня, привязки,
шаблоны и три заявки с разными состояниями сроков. Повторный запуск не
дублирует записи.
"""
import os
from datetime import time, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from apps.servicedesk.models import (AnswerTemplate, Category, Priority, SlaBinding, SlaCycle, SlaLevel, Source,
                                     Ticket)
from apps.servicedesk.services import dictionaries, tickets


REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."
LEVELS = (("Критичный", 30, 240, 10), ("Обычный", 240, 1440, 20))
TICKET_TITLES = ("E2E SLA: в срок", "E2E SLA: просроченная реакция", "E2E SLA: просроченное решение")


def require_stand() -> None:
    """Отказывает без `E2E_STAND=1` до чтения базы."""
    if os.environ.get("E2E_STAND") != "1":
        raise CommandError(REFUSAL)


class Command(BaseCommand):
    help = "Стенд: два уровня SLA, шаблоны и три заявки для приёмки среза 011."

    def handle(self, *args, **options):
        require_stand()
        from django.contrib.auth import get_user_model

        people = list(get_user_model().objects.filter(state="active").order_by("pk")[:2])
        if not people:
            self.stdout.write("e2e_sla_seed: levels=0 bindings=0 answers=0 tickets=0")
            return
        actor = people[0]
        queue = self._queue()
        if queue is None:
            self.stdout.write("e2e_sla_seed: levels=0 bindings=0 answers=0 tickets=0")
            return
        self._stand_access(actor, queue)
        with transaction.atomic():
            priorities = [self._priority(name, actor) for name in ("Высокая", "Средняя")]
            category = self._category(actor, queue.pk)
            levels = self._levels()
            self._bindings(levels, priorities, category)
            self._answers(actor, category)
            self._tickets(actor, queue, category, priorities, levels)
        self.stdout.write("e2e_sla_seed: levels=2 bindings=3 answers=3 tickets=3")

    @staticmethod
    def _stand_access(actor, queue):
        """Стенд: администратор становится руководителем очереди и получает право отчёта.

        В данных установки `servicedesk.reports` выдан только роли «Руководитель» (SPEC-011, решение 10),
        а администратору он не нужен; для приёмки отчёта в браузере даём право администратору стенда и
        делаем его руководителем очереди — так у него появляется область `managed_units`.
        """
        from apps.core.models import Permission, Role
        from apps.org.services import membership

        reports = Permission.objects.filter(code="servicedesk.reports").first()
        admin_role = Role.objects.filter(name="Администратор портала").first()
        if reports and admin_role:
            admin_role.permissions.add(reports)
        membership.set_marks(queue.unit, heads=[actor], actor=actor)

    @staticmethod
    def _queue():
        from apps.servicedesk.models import Queue

        return Queue.objects.select_related("unit").order_by("pk").first()

    @staticmethod
    def _priority(name, actor):
        value = Priority.objects.filter(name=name).first()
        if value is None:
            value = dictionaries.create("priority", name=name, actor=actor)
        return value

    @staticmethod
    def _category(actor, queue_id):
        category = Category.objects.filter(name="E2E SLA").first()
        if category is None:
            category = dictionaries.create("category", name="E2E SLA", queue_id=queue_id, actor=actor)
        return category

    @staticmethod
    def _levels():
        levels = []
        for title, reaction, solution, priority in LEVELS:
            level, _ = SlaLevel.objects.update_or_create(
                title=title,
                defaults={"priority": priority, "reaction_minutes": reaction, "solution_minutes": solution,
                          "workdays": [0, 1, 2, 3, 4], "day_start": time(9), "day_end": time(18),
                          "all_day": False, "archived": False},
            )
            levels.append(level)
        return levels

    @staticmethod
    def _bindings(levels, priorities, category):
        critical, normal = levels
        SlaBinding.objects.update_or_create(priority=priorities[0], defaults={"level": critical, "kind": "priority",
                                                                              "category": None})
        SlaBinding.objects.update_or_create(priority=priorities[1], defaults={"level": normal, "kind": "priority",
                                                                              "category": None})
        SlaBinding.objects.update_or_create(category=category, defaults={"level": normal, "kind": "category",
                                                                         "priority": None})

    @staticmethod
    def _answers(actor, category):
        values = (
            ("E2E SLA: общий", "Здравствуйте. Заявка принята в работу.", None),
            ("E2E SLA: общий по категории", "Здравствуйте. Заявка категории принята в работу.", category),
            ("E2E SLA: личный", "Сообщение сотруднику стенда.", None),
        )
        for index, (title, text, answer_category) in enumerate(values):
            AnswerTemplate.objects.update_or_create(
                title=title,
                defaults={"owner": actor if index == 2 else None, "text": text,
                          "category": answer_category, "archived": False},
            )

    @staticmethod
    def _tickets(actor, queue, category, priorities, levels):
        source = Source.objects.filter(name="Лично").first() or Source.objects.filter(system_code="").first()
        now = timezone.now()
        for index, title in enumerate(TICKET_TITLES):
            ticket = Ticket.objects.filter(subject=title).first()
            if ticket is None:
                ticket = tickets.create(
                    channel=tickets.STAFF, subject=title, text="Сценарий приёмки SLA.",
                    requester_email=f"e2e-sla-{index}@example.invalid", requester_name="Стенд SLA",
                    category=category, queue_id=queue.unit_id, priority=priorities[index == 0],
                    source=source, created_by=actor, at=now - timedelta(minutes=10),
                ).ticket
            level = levels[0] if index == 0 else levels[1]
            reaction_due = now + timedelta(hours=2) if index == 0 else now - timedelta(minutes=30)
            solution_due = now + timedelta(hours=8) if index == 0 else now - timedelta(minutes=10)
            SlaCycle.objects.update_or_create(
                ticket=ticket, number=1,
                defaults={"is_current": True, "level": level, "level_title": level.title, "queue": queue.unit,
                          "queue_name": queue.unit.name, "category": category, "category_name": category.name,
                          "assignee": actor, "assignee_name": actor.full_name, "schedule": {
                              "workdays": [0, 1, 2, 3, 4], "day_start": "09:00", "day_end": "18:00",
                              "all_day": False, "days": {}, "extended": False},
                          "cycle_started_at": now - timedelta(minutes=10), "reaction_due": reaction_due,
                          "solution_due": solution_due},
            )
            Ticket.objects.filter(pk=ticket.pk).update(
                sla=level, sla_cycle_started_at=now - timedelta(minutes=10),
                sla_reaction_due=reaction_due, sla_solution_due=solution_due,
            )
