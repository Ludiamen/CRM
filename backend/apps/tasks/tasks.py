"""Задания задач (срез 009, T-9211/T-9212/T-9213; CONTRACT-009, 1.2, 8, 9).

`tasks_reminders` — каждые 5 минут: созревшие `pending` превращаются в уведомления и помечаются `sent`; повторный
`None` от `quiet.next_start` отменяет напоминание с записью `tasks.reminder_failed`. `tasks_digest` — раз в день на
сотрудника (атомарный `cache.add`). `tasks_retention` — ночная уборка. Все принимают время параметром.
"""
from django.core.cache import cache

from apps.core.extensions import Draft
from apps.notify.services import dispatch, quiet

KIND_OF = {"auto_soon": "tasks.due_soon", "auto_due": "tasks.due", "auto_overdue": "tasks.overdue",
           "manual": "tasks.reminder"}
TEXT_OF = {"tasks.due_soon": "Задача скоро просрочена", "tasks.due": "Срок наступил",
           "tasks.overdue": "Задача просрочена", "tasks.reminder": "Вы просили напомнить",
           "tasks.assigned": "Назначена задача", "tasks.comment": "Новый комментарий",
           "tasks.subordinate_overdue": "Задача подчинённого просрочена",
           "tasks.subordinate_digest": "Сводка по задачам подчинённых"}


def notify(task, code: str, users) -> list[int]:
    """Создать уведомления вида `code` перечисленным сотрудникам (без автора текущего действия)."""
    from apps.tasks.services import notify_rules

    drafts = [Draft(user_id=user.pk, text=f"{TEXT_OF.get(code, code)}: №{task.pk}",
                    url=f"/tasks/{task.pk}/", object_ref=f"tasks.task:{task.pk}")
              for user in users if user is not None]
    return dispatch.create(code, drafts) if drafts else []


def tasks_reminders(now=None) -> int:
    """Отправить созревшие напоминания; вернуть число отправленных."""
    from django.utils import timezone

    from apps.core.services import audit
    from apps.tasks.models import TaskReminder
    from apps.tasks.services import notify_rules, reminders

    now = now or timezone.now()
    sent = 0
    for reminder in reminders.due(now):
        prefs = dispatch.user_prefs(reminder.user_id)
        start = quiet.next_start(prefs, reminder.moment)
        key = f"tasks:reminder-none:{reminder.pk}"
        if start is None:
            if cache.add(key, 1, timeout=24 * 3600):
                reminder.moment = now
                reminder.save(update_fields=["moment"])
                continue
            reminder.state = TaskReminder.State.CANCELLED
            reminder.save(update_fields=["state"])
            audit.record("tasks.reminder_failed", object_type="tasks.task", object_id=reminder.task_id,
                         after={"reminder": reminder.pk, "user": reminder.user_id})
            continue
        if start > now:
            reminder.moment = start
            reminder.save(update_fields=["moment"])
            continue
        code = KIND_OF[reminder.kind]
        if code == "tasks.overdue":
            managers = {user.pk: user for user in notify_rules.managers(reminder.task)
                        if user.pk != reminder.task.author_id}
            for user in notify_rules.targets(reminder.task, "overdue"):
                if user.pk in managers:
                    continue
                notify(reminder.task, "tasks.overdue", [user])
            for manager in managers.values():
                notify(reminder.task, "tasks.subordinate_overdue", [manager])
        else:
            notify(reminder.task, code, [reminder.user])
        reminder.state = TaskReminder.State.SENT
        reminder.save(update_fields=["state"])
        cache.delete(key)
        sent += 1
    return sent


def tasks_digest(now=None) -> int:
    """Ежедневная сводка руководителям и заместителям (атомарный `cache.add`)."""
    from django.utils import timezone

    from apps.core.models import User
    from apps.org.services import calendar
    from apps.tasks.models import Task
    from apps.tasks.services import notify_rules
    from apps.core.widgets import moscow_today

    now = now or timezone.now()
    if not calendar.is_working_time(now):
        return 0
    today = moscow_today()
    sent = 0
    people = User.objects.filter(state="active")
    for person in people:
        key = f"tasks:digest:{today.isoformat()}:{person.pk}"
        if not cache.add(key, 1, timeout=24 * 3600):
            continue
        managed = notify_rules.managers_for(person)
        if not managed:
            continue
        hot = Task.objects.filter(deleted_at__isnull=True, assignee_id__in=managed,
                                  deadline__isnull=False, deadline__lte=today).exclude(status=Task.Status.DONE)
        if not hot.exists():
            cache.delete(key)
            continue
        draft = [Draft(user_id=person.pk, text="Сводка по задачам подчинённых", url="/tasks/?preset=subordinate",
                       object_ref=f"tasks.digest:{today.isoformat()}")]
        dispatch.create("tasks.subordinate_digest", draft)
        sent += 1
    return sent


def tasks_retention(now=None) -> dict:
    """Убрать задачи с истёкшим сроком хранения и старые непривязанные файлы."""
    from apps.tasks.services import retention

    return retention.purge(now)


def tasks_automation_tick(now=None):
    """Пороги задач для автоматизации: «скоро» и «просрочена» один раз на задачу, срок и порог."""
    import datetime

    from django.core.cache import cache
    from django.utils import timezone as dj_timezone

    from apps.tasks.models import Task
    from apps.tasks.services import events, reminders

    now = now or dj_timezone.now()
    today = now.date()
    horizon = today + datetime.timedelta(days=7)
    sent = 0
    queryset = Task.objects.filter(deleted_at__isnull=True, deadline__isnull=False, deadline__lte=horizon).exclude(
        status=Task.Status.DONE).select_related("assignee", "author")
    for task in queryset.iterator(chunk_size=500):
        moments = reminders.moments(task.deadline)
        if now >= moments["auto_overdue"]:
            if cache.add(f"automation:task:{task.pk}:overdue:{task.deadline}", 1, timeout=90 * 24 * 3600):
                events.task_threshold(task, deadline=task.deadline, kind="overdue")
                sent += 1
        elif now >= moments["auto_soon"]:
            if cache.add(f"automation:task:{task.pk}:soon:{task.deadline}", 1, timeout=90 * 24 * 3600):
                events.task_threshold(task, deadline=task.deadline, kind="soon")
                sent += 1
    return sent
