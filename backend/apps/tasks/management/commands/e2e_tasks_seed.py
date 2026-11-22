"""Заполнение стенда задачами (срез 009, T-9010; CONTRACT-009, 13.1).

`e2e_tasks_seed`: проверка стенда первой строкой, затем две категории и три задачи (своя, подчинённому, с
соисполнителем и наблюдателем) — данные для сценариев приёмки. Повторный запуск ничего не дублирует: категории
ищутся по названию, задачи — по названию. Вывод — одна строка
`e2e_tasks_seed: tasks=3 categories=2`.
"""
import datetime

from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from apps.tasks.stand import require_stand

CATEGORIES = ("Работа", "Личное")
TASKS = (
    ("Проверить резервные копии", "Сегодня — проверить отчёты и восстановление одной копии."),
    ("Обновить парк ноутбуков", "Сверить инвентарь и отправить список на обновление."),
    ("Согласовать закупку картриджей", "Уточнить остатки и подготовить заявку."),
)


class Command(BaseCommand):
    help = "Стенд: категории и три задачи для сценариев приёмки среза 009."

    def handle(self, *args, **options):
        require_stand()
        from django.contrib.auth import get_user_model

        from apps.tasks.models import PlanColumn, Task, TaskCategory, TaskMember

        User = get_user_model()
        people = list(User.objects.filter(state="active").order_by("pk")[:4])
        if not people:
            self.stdout.write("e2e_tasks_seed: tasks=0 categories=0")
            return
        author = people[0]
        assignee = people[1] if len(people) > 1 else author
        coexecutor = people[2] if len(people) > 2 else None
        observer = people[3] if len(people) > 3 else None
        today = timezone.localdate()

        with transaction.atomic():
            categories = [TaskCategory.objects.get_or_create(title=title, defaults={"position": index})[0]
                          for index, title in enumerate(CATEGORIES)]
            for index, (title, description) in enumerate(TASKS):
                Task.objects.get_or_create(
                    title=title,
                    defaults={"description": description, "author": author,
                              "assignee": assignee if index == 1 else author,
                              "deadline": today + datetime.timedelta(days=index + 1),
                              "category": categories[index % len(categories)]})
            if len(people) > 1:
                main = Task.objects.filter(title=TASKS[2][0]).first()
                if main is not None and coexecutor is not None:
                    TaskMember.objects.get_or_create(task=main, user=coexecutor, defaults={"role": "coexecutor"})
                if main is not None and observer is not None:
                    TaskMember.objects.get_or_create(task=main, user=observer, defaults={"role": "observer"})
            # Три личные колонки лениво — как при первом открытии «Моего плана».
            for position, title in enumerate(("Сегодня", "На этой неделе", "Потом")):
                PlanColumn.objects.get_or_create(user=author, title=title, defaults={"position": position})
        total = Task.objects.filter(title__in=[title for title, _ in TASKS]).count()
        self.stdout.write(f"e2e_tasks_seed: tasks={total} categories={len(categories)}")