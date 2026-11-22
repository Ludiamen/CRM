"""Задачи для нагрузочного прогона среза 009 (NFR-710, NFR-719; PLAN-009, «Нагрузка»; CONTRACT-009, 13.2).

Добавляет задачи до LOAD_TASKS (по умолчанию 1 000) на LOAD_PEOPLE (100) действующих сотрудников: статусы по
распределению, сроки от −5 до +14 дней, категории, личные колонки, соисполнители и наблюдатели, комментарии у
трети задач и автоматические напоминания у задач со сроком. Тексты — из словаря русских ИТ-слов (без ПДн).

Повторный запуск добирает до цели и не дублирует уже созданные строки (задача узнаётся по названию-маркеру).
Работает ТОЛЬКО при E2E_STAND=1; данные убирает следующий сброс приёмки:

    docker compose -f deploy/docker-compose.yml --profile dev exec -T -e LOAD_TASKS=1000 \
        standtools python manage.py shell --no-imports < backend/tests/load/fill_tasks.py

Вывод: `fill_tasks: tasks=<число> comments=<число> reminders=<число>`.
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

from apps.tasks.models import (PlanColumn, Task, TaskCategory, TaskComment, TaskMember, TaskReminder,  # noqa: E402
                               TaskSettings)

TASKS_TARGET = min(int(os.environ.get("LOAD_TASKS", "1000")), 20_000)
PEOPLE_TARGET = min(int(os.environ.get("LOAD_PEOPLE", "100")), 2_000)
CHUNK = 250
STATUSES = (("new", 30), ("in_progress", 40), ("waiting", 15), ("done", 15))
CATEGORIES = ("Работа", "Личное", "Срочное", "Проекты", "Обучение")
WORDS = (
    "задача срок исполнитель постановщик проверка обновление установка настройка принтер картридж монитор "
    "ноутбук сервер сеть кабель почта доступ права папка документ диск резервная копия восстановление "
    "программа лицензия антивирус защита сертификат телефон гарнитура камера собрание календарь проектор "
    "питание драйвер система профиль сотрудник отдел заявка согласование закупка инвентаризация отчёт"
).split()


def _choice(pairs):
    total = sum(weight for _value, weight in pairs)
    point = random.uniform(0, total)
    upto = 0
    for value, weight in pairs:
        upto += weight
        if point <= upto:
            return value
    return pairs[-1][0]


def _text(size=6):
    return " ".join(random.choice(WORDS) for _ in range(size))


def main() -> None:
    User = get_user_model()
    people = list(User.objects.filter(state="active").order_by("pk")[:PEOPLE_TARGET])
    if not people:
        print("fill_tasks: tasks=0 comments=0 reminders=0")
        return
    TaskSettings.objects.get_or_create(pk=1, defaults={"retention_years": 3})
    categories = [TaskCategory.objects.get_or_create(title=title, defaults={"position": index})[0]
                  for index, title in enumerate(CATEGORIES)]
    for person in people:
        for position, title in enumerate(("Сегодня", "На этой неделе", "Потом")):
            PlanColumn.objects.get_or_create(user=person, title=title, defaults={"position": position})

    today = timezone.localdate()
    created = Task.objects.filter(title__startswith="Нагрузка ").count()
    while created < TASKS_TARGET:
        batch = []
        for _index in range(min(CHUNK, TASKS_TARGET - created)):
            author = random.choice(people)
            assignee = random.choice(people)
            deadline = today + timedelta(days=random.randint(-5, 14)) if random.random() < 0.85 else None
            batch.append(Task(
                title=f"Нагрузка {created + len(batch) + 1}: {_text(5)}",
                description=_text(25),
                author=author, assignee=assignee,
                status=_choice(STATUSES),
                deadline=deadline,
                category=random.choice(categories + [None]),
                created_at=timezone.now() - timedelta(days=random.randint(0, 120)),
                updated_at=timezone.now() - timedelta(days=random.randint(0, 30)),
            ))
        with transaction.atomic():
            Task.objects.bulk_create(batch, batch_size=CHUNK)
        created += len(batch)
        if not batch:
            break

    tasks = list(Task.objects.filter(title__startswith="Нагрузка ").order_by("pk")[:TASKS_TARGET])
    comments = 0
    with transaction.atomic():
        for task in tasks:
            for offset in range(3 if random.random() < 0.3 else 0):
                TaskComment.objects.create(task=task, author=random.choice(people), text=_text(12),
                                           created_at=task.created_at + timedelta(minutes=offset * 10))
                comments += 1
            if random.random() < 0.3:
                member = random.choice([person for person in people if person.pk != task.assignee_id])
                TaskMember.objects.get_or_create(task=task, user=member,
                                                 defaults={"role": random.choice(("coexecutor", "observer"))})
            if task.deadline is not None and random.random() < 0.25:
                TaskReminder.objects.get_or_create(
                    task=task, user=task.assignee, kind="auto_due",
                    defaults={"moment": timezone.now() + timedelta(minutes=random.randint(5, 600))})

    reminders = TaskReminder.objects.filter(task__in=tasks, kind="auto_due").count()
    print(f"fill_tasks: tasks={len(tasks)} comments={comments} reminders={reminders}")


main()