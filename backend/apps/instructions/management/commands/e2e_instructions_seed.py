"""Заполнение стенда поручениями (срез 010, T-10008; CONTRACT-010, 13.1).

`e2e_instructions_seed`: проверка стенда первой строкой, затем четыре вида основания и три поручения (своё,
подчинённому с отчётной датой, с соисполнителем и запросом переноса) — данные для сценариев приёмки. Повторный
запуск ничего не дублирует: виды ищутся по названию, поручения — по названию. Вывод — одна строка
`e2e_instructions_seed: instructions=3 basis=4`.
"""
import datetime

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.instructions.stand import BASIS_KINDS, DEFAULT_LADDER, require_stand

INSTRUCTIONS = (
    ("Подготовить отчёт по резервным копиям", "Проверить восстановление одной копии и описать итог."),
    ("Обновить регламент обслуживания", "Сверить шаги регламента с текущей практикой."),
    ("Согласовать закупку оборудования", "Собрать список и передать на согласование."),
)


class Command(BaseCommand):
    help = "Стенд: виды основания и три поручения для сценариев приёмки среза 010."

    def handle(self, *args, **options):
        require_stand()
        from apps.core.widgets import moscow_today
        from apps.instructions.models import (Instruction, InstructionBasisKind, InstructionMember,
                                              InstructionReportDate, InstructionSettings, InstructionTransfer)

        today = moscow_today()
        InstructionSettings.objects.get_or_create(
            pk=1, defaults={"retention_years": 3, "default_ladder": dict(DEFAULT_LADDER)})
        with transaction.atomic():
            kinds = [InstructionBasisKind.objects.get_or_create(title=title, defaults={"position": index})[0]
                     for index, title in enumerate(BASIS_KINDS)]
            if not kinds:
                self.stdout.write("e2e_instructions_seed: instructions=0 basis=0")
                return
            author, assignee, coexecutor, controller = self._people()
            deadlines = (today + datetime.timedelta(days=14), today + datetime.timedelta(days=21),
                         today + datetime.timedelta(days=30))
            made = []
            for index, (title, text) in enumerate(INSTRUCTIONS):
                instruction, _ = Instruction.objects.get_or_create(
                    title=title,
                    defaults={"text": text, "basis_kind": kinds[index % len(kinds)], "basis_number": f"{index + 1}-01",
                              "basis_date": today, "author": author, "controller": controller,
                              "assignee": assignee if index else author,
                              "deadline": deadlines[index], "original_deadline": deadlines[index],
                              "ladder": dict(DEFAULT_LADDER)})
                made.append(instruction)
            if coexecutor is not None and len(made) > 1:
                InstructionMember.objects.get_or_create(instruction=made[1], user=coexecutor,
                                                        defaults={"role": "coexecutor"})
            if len(made) > 1:
                InstructionReportDate.objects.get_or_create(
                    instruction=made[1], due_date=today + datetime.timedelta(days=7),
                    defaults={"position": 0, "state": "waiting"})
            if len(made) > 2 and controller is not None:
                InstructionTransfer.objects.get_or_create(
                    instruction=made[2], state="pending",
                    defaults={"old_deadline": deadlines[2],
                              "new_deadline": deadlines[2] + datetime.timedelta(days=7),
                              "reason": "Нужно больше времени на сбор списка.",
                              "requested_by": assignee if assignee is not None else author})
        total = Instruction.objects.filter(title__in=[title for title, _ in INSTRUCTIONS]).count()
        self.stdout.write(f"e2e_instructions_seed: instructions={total} basis={len(kinds)}")

    def _people(self):
        """Автор, исполнитель, соисполнитель и контролёр — первые действующие сотрудники стенда."""
        from django.contrib.auth import get_user_model

        people = list(get_user_model().objects.filter(state="active").order_by("pk")[:4])
        if not people:
            return None, None, None, None
        author = people[0]
        assignee = people[1] if len(people) > 1 else author
        coexecutor = people[2] if len(people) > 2 else None
        controller = people[3] if len(people) > 3 else author
        return author, assignee, coexecutor, controller