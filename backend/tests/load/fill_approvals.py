"""Синтетические согласования для нагрузочного прогона NFR-746/747 (срез 014).

Создаёт 300 шаблонов, 5 000 маршрутов (1 000 активных, 4 000 завершённых), 25 000 заданий
(10 000 ожидающих). Заявки берутся из `fill_tickets.py`, сотрудники — из `prepare_users.py`.
Повторный запуск не дублирует данные: маршруты узнаются по `template_name`-маркеру.
Работает только при E2E_STAND=1; данные убирает следующий сброс приёмки.

    docker compose -f deploy/docker-compose.yml --profile dev exec -T -e E2E_STAND=1 \
        standtools python manage.py shell --no-imports < backend/tests/load/fill_approvals.py
"""
import os
import random
import sys
from datetime import timedelta

if os.environ.get("E2E_STAND") != "1":
    sys.exit("Скрипт работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено.")

from django.db import transaction  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.approvals.models import (ApprovalAssignment, ApprovalRoute, ApprovalStage, ApprovalStageParticipant,  # noqa: E402
                                   ApprovalStageRun, ApprovalTemplate)
from apps.core.models import Role, User  # noqa: E402
from apps.servicedesk.models import Ticket  # noqa: E402

TEMPLATES = 300
ROUTES = 5_000
RUNNING = 1_000
ASSIGNMENTS = 25_000

admin = (User.objects.filter(roles__name="Администратор портала").order_by("pk").first()
         or User.objects.order_by("pk").first())
users = list(User.objects.filter(state="active", email__startswith="load-").order_by("pk")[:2000])
tickets = list(Ticket.objects.order_by("pk").values_list("pk", "number")[:ROUTES])
if not users or not tickets:
    print("fill_approvals: нет load-пользователей или заявок")
    raise SystemExit(1)

with transaction.atomic():
    templates = list(ApprovalTemplate.objects.filter(name__startswith="Нагрузка 014").order_by("pk"))
    if len(templates) < TEMPLATES:
        templates.extend(ApprovalTemplate.objects.bulk_create([
            ApprovalTemplate(name=f"Нагрузка 014 {index:03d}", subject_type="ticket", author=admin, enabled=True)
            for index in range(len(templates), TEMPLATES)
        ], batch_size=100))
    templates = templates[:TEMPLATES]

    existing = ApprovalRoute.objects.filter(template_name__startswith="Нагрузка 014").count()
    if existing < ROUTES:
        now = timezone.now()
        routes = []
        for index in range(existing, ROUTES):
            ticket_pk, number = tickets[index % len(tickets)]
            running = index < RUNNING
            routes.append(ApprovalRoute(
                template=random.choice(templates), template_name=f"Нагрузка 014 {index:05d}",
                subject_type="ticket", subject_id=ticket_pk, subject_number=number,
                initiator=random.choice(users),
                status=ApprovalRoute.Status.RUNNING if running else ApprovalRoute.Status.APPROVED,
                started_at=now - timedelta(hours=random.randint(1, 72)),
                finished_at=None if running else now - timedelta(hours=random.randint(1, 24))))
        routes = ApprovalRoute.objects.bulk_create(routes, batch_size=500)
        stages = []
        for route in routes:
            stages.append(ApprovalStageRun(
                route=route, order=1, title="Согласование", mode="parallel", rule="all",
                status=ApprovalStageRun.Status.RUNNING if route.status == "running" else ApprovalStageRun.Status.DONE,
                started_at=route.started_at,
                finished_at=route.finished_at,
                due_at=route.started_at + timedelta(hours=48)))
        stages = ApprovalStageRun.objects.bulk_create(stages, batch_size=500)
        assignments = []
        for index, stage in enumerate(stages):
            route = stage.route
            running = route.status == "running"
            count = 10 if running else 4
            for offset in range(count):
                user = users[(index * 10 + offset) % len(users)]
                assignments.append(ApprovalAssignment(
                    stage_run=stage, user=user, order=offset + 1,
                    status=ApprovalAssignment.Status.PENDING if running else ApprovalAssignment.Status.APPROVED,
                    decision=None if running else ApprovalAssignment.Decision.APPROVED,
                    decided_at=None if running else route.finished_at,
                    created_at=route.started_at, due_at=stage.due_at,
                    comment="" if running else "Согласовано"))
        ApprovalAssignment.objects.bulk_create(assignments, batch_size=1000)

print(f"fill_approvals: templates={ApprovalTemplate.objects.filter(name__startswith='Нагрузка 014').count()} "
      f"routes={ApprovalRoute.objects.filter(template_name__startswith='Нагрузка 014').count()} "
      f"assignments={ApprovalAssignment.objects.filter(stage_run__route__template_name__startswith='Нагрузка 014').count()}")
