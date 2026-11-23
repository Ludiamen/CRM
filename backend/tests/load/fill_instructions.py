"""Поручения для нагрузочного прогона среза 010 (T-10150; NFR-720, NFR-728; CONTRACT-010, 13.2).

Добавляет поручения до LOAD_INSTRUCTIONS (по умолчанию 1 000) на LOAD_PEOPLE (100) действующих сотрудников:
виды основания, сроки от −10 до +180 дней, отчётные даты, отчёты, части и напоминания. Тексты — русские
ИТ-слова без ПДн. Повторный запуск добирает до цели по названию-маркеру «Нагрузка ».

Работает ТОЛЬКО при E2E_STAND=1; данные убирает следующий сброс приёмки:

    docker compose -f deploy/docker-compose.yml --profile dev exec -T -e LOAD_INSTRUCTIONS=1000 \\
        standtools python manage.py shell --no-imports < backend/tests/load/fill_instructions.py

Вывод: `fill_instructions: instructions=<число> reports=<число> parts=<число> reminders=<число>`.
"""
import os
import random
import sys

if os.environ.get("E2E_STAND") != "1":
    sys.exit("Скрипт работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено.")

from datetime import timedelta  # noqa: E402

from django.contrib.auth import get_user_model  # noqa: E402
from django.db import transaction  # noqa: E402
from django.utils import timezone  # noqa: E402

from apps.instructions.models import (Instruction, InstructionBasisKind, InstructionMember,  # noqa: E402
                                      InstructionReminder, InstructionReport, InstructionReportDate,
                                      InstructionReportPart, InstructionSettings, InstructionTransfer)

TARGET = min(int(os.environ.get("LOAD_INSTRUCTIONS", "1000")), 20_000)
PEOPLE_TARGET = min(int(os.environ.get("LOAD_PEOPLE", "100")), 2_000)
BASIS = ("Приказ", "Протокол совещания", "Письмо", "Устное указание")
LADDER = {"offsets": [30, 14, 7, 3, 1], "due": True, "overdue": True}
WORDS = (
    "поручение основание срок отчёт исполнитель контролёр подразделение проверка обновление установка "
    "настройка принтер картридж монитор ноутбук сервер сеть кабель почта доступ права папка документ диск "
    "резервная копия восстановление программа лицензия антивирус защита сертификат телефон гарнитура камера "
    "собрание календарь проектор питание драйвер система профиль сотрудник отдел заявка согласование закупка "
    "инвентаризация отчётность дисциплина перенос напоминание"
).split()
PERIODS = ("weekly", "monthly", "quarterly")


def _text(size=6):
    return " ".join(random.choice(WORDS) for _ in range(size))


def main() -> None:
    User = get_user_model()
    people = list(User.objects.filter(state="active").order_by("pk")[:PEOPLE_TARGET])
    if not people:
        print("fill_instructions: instructions=0 reports=0 parts=0 reminders=0")
        return
    InstructionSettings.objects.get_or_create(
        pk=1, defaults={"retention_years": 3, "default_ladder": dict(LADDER)})
    kinds = [InstructionBasisKind.objects.get_or_create(title=title, defaults={"position": index})[0]
             for index, title in enumerate(BASIS)]

    today = timezone.localdate()
    created = Instruction.objects.filter(title__startswith="Нагрузка ").count()
    while created < TARGET:
        batch = []
        for _index in range(min(200, TARGET - created)):
            deadline = today + timedelta(days=random.randint(-10, 180))
            batch.append(Instruction(
                title=f"Нагрузка {created + len(batch) + 1}: {_text(5)}",
                text=_text(30),
                basis_kind=random.choice(kinds),
                basis_number=str(random.randint(1, 999)),
                basis_date=today - timedelta(days=random.randint(0, 60)),
                author=random.choice(people),
                controller=random.choice(people),
                assignee=random.choice(people),
                deadline=deadline,
                original_deadline=deadline,
                ladder=dict(LADDER),
                created_at=timezone.now() - timedelta(days=random.randint(0, 90)),
                updated_at=timezone.now() - timedelta(days=random.randint(0, 30)),
            ))
        with transaction.atomic():
            Instruction.objects.bulk_create(batch, batch_size=200)
        created += len(batch)
        if not batch:
            break

    rows = list(Instruction.objects.filter(title__startswith="Нагрузка ").order_by("pk")[:TARGET])
    reports = parts = reminders = 0
    with transaction.atomic():
        for row in rows:
            if random.random() < 0.3:
                peer = random.choice([person for person in people if person.pk != row.assignee_id])
                InstructionMember.objects.get_or_create(instruction=row, user=peer, defaults={"role": "coexecutor"})
            dates = []
            for index in range(random.randint(0, 3)):
                due = today + timedelta(days=7 * (index + 1) + random.randint(0, 3))
                if due >= row.deadline or due <= today:
                    continue
                date_row, _ = InstructionReportDate.objects.get_or_create(
                    instruction=row, due_date=due, defaults={"position": index, "state": "waiting"})
                dates.append(date_row)
            for date_row in dates:
                if random.random() < 0.35:
                    InstructionReport.objects.create(
                        instruction=row, date=date_row, author=row.assignee, text=_text(20),
                        decision=random.choice(("pending", "accepted", "returned")),
                        decided_by=row.controller if random.random() < 0.5 else None,
                        decided_at=timezone.now() if random.random() < 0.5 else None)
                    reports += 1
                if random.random() < 0.25:
                    InstructionReportPart.objects.create(date=date_row, author=random.choice(people), text=_text(12))
                    parts += 1
            if dates and random.random() < 0.2:
                InstructionReport.objects.get_or_create(
                    instruction=row, date=None, author=row.assignee,
                    defaults={"text": _text(20), "decision": "pending"})
                reports += 1
            stage = random.choice(("d30", "d14", "d7", "d3", "d1", "due", "overdue"))
            InstructionReminder.objects.get_or_create(
                instruction=row, date=None, user=row.assignee, kind="deadline", stage=stage,
                defaults={"moment": timezone.now() + timedelta(minutes=random.randint(5, 600)),
                          "state": "pending"})
            reminders += 1
            if random.random() < 0.15:
                InstructionTransfer.objects.get_or_create(
                    instruction=row, state="approved",
                    defaults={"old_deadline": row.original_deadline,
                              "new_deadline": row.deadline + timedelta(days=7),
                              "reason": "Нагрузка: перенос срока", "requested_by": row.assignee,
                              "decided_by": row.controller, "decided_at": timezone.now()})

    print(f"fill_instructions: instructions={len(rows)} reports={reports} parts={parts} reminders={reminders}")


main()