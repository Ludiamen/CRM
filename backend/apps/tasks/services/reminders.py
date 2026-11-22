"""Напоминания задач: моменты, личные тихие часы, ручные и «Отложить» (срез 009, T-9211; FR-687…690, NFR-715).

Момент срока — конец рабочего дня даты срока (нерабочая дата — первый рабочий день после неё). «Скоро» — начало
предыдущего рабочего дня, «срок наступил» — начало рабочего дня даты срока, «просрочена» — начало следующего
рабочего дня после момента. Каждый момент сдвигается `notify.services.quiet.next_start` по личным настройкам
получателя. Автоматические напоминания пересоздаются при смене срока и состава; ручные — «на дату» и «за N
рабочих дней»; «Отложить» — на следующий рабочий день от момента срабатывания.
"""
import datetime

from django.utils import timezone

from apps.core.services import audit
from apps.notify.services import dispatch, quiet
from apps.org.services import calendar
from apps.tasks.models import TaskMember, TaskReminder
from apps.tasks.services.errors import TasksError

AUTO_KINDS = ("auto_soon", "auto_due", "auto_overdue")
MSK = datetime.timezone(datetime.timedelta(hours=3))
LIMIT = 10
DAYS_MIN, DAYS_MAX = 1, 30


def _settings():
    return calendar._settings()


def _working(day: datetime.date) -> bool:
    return calendar.day_kind(day) not in calendar.OFF_KINDS


def _next_working(day: datetime.date) -> datetime.date:
    for offset in range(0, 401):
        found = day + datetime.timedelta(days=offset)
        if _working(found):
            return found
    return day


def _previous_working(day: datetime.date) -> datetime.date:
    for offset in range(1, 401):
        found = day - datetime.timedelta(days=offset)
        if _working(found):
            return found
    return day


def _start(day: datetime.date) -> datetime.datetime:
    return datetime.datetime.combine(_next_working(day), _settings().day_start, tzinfo=MSK)


def deadline_moment(day: datetime.date) -> datetime.datetime:
    """Конец рабочего дня даты срока (нерабочая дата — первый рабочий день после)."""
    return datetime.datetime.combine(_next_working(day), _settings().day_end, tzinfo=MSK)


def moments(deadline: datetime.date) -> dict[str, datetime.datetime]:
    """Три автоматических момента по сроку."""
    due_day = _next_working(deadline)
    return {
        "auto_soon": _start(_previous_working(due_day)),
        "auto_due": _start(due_day),
        "auto_overdue": _start(due_day + datetime.timedelta(days=1)),
    }


def _recipients(task) -> list:
    people = {task.assignee_id: task.assignee}
    for row in task.members.filter(role=TaskMember.Role.COEXECUTOR).select_related("user"):
        people[row.user_id] = row.user
    return list(people.values())


def _shift(user, moment: datetime.datetime) -> datetime.datetime | None:
    return quiet.next_start(dispatch.user_prefs(user.pk), moment)


def plan(task) -> list[TaskReminder]:
    """Пересчитать автоматические и ручные «за N рабочих дней»; без срока — снять их."""
    TaskReminder.objects.filter(task=task, kind__in=AUTO_KINDS).delete()
    manual = list(TaskReminder.objects.filter(task=task, kind=TaskReminder.Kind.MANUAL, days__isnull=False))
    if task.deadline is None:
        for row in manual:
            row.delete()
        return []
    for row in manual:
        day = task.deadline
        for _ in range(row.days):
            day = _previous_working(day)
        row.moment = _start(day)
        row.save(update_fields=["moment"])
    result = []
    for kind, moment in moments(task.deadline).items():
        for user in _recipients(task):
            shifted = _shift(user, moment)
            if shifted is None:
                continue
            result.append(TaskReminder.objects.create(task=task, user=user, kind=kind, moment=shifted))
    return result


def set_manual(actor, task, *, days=None, on=None) -> TaskReminder:
    """Поставить ручное напоминание себе: «за N рабочих дней» или «на дату»."""
    if actor.pk != task.assignee_id and not TaskMember.objects.filter(task=task, user=actor).exists():
        raise TasksError("reminder_forbidden_other", "reminder")
    if days not in (None, ""):
        if task.deadline is None:
            raise TasksError("reminder_deadline_required", "reminder")
        try:
            days = int(days)
        except (TypeError, ValueError):
            raise TasksError("reminder_days_range", "reminder") from None
        if not DAYS_MIN <= days <= DAYS_MAX:
            raise TasksError("reminder_days_range", "reminder")
        day = task.deadline
        for _ in range(days):
            day = _previous_working(day)
        moment = _start(day)
    elif on not in (None, ""):
        try:
            day = datetime.date.fromisoformat(str(on))
        except ValueError:
            raise TasksError("reminder_date_invalid", "reminder") from None
        moment = _start(day)
    else:
        raise TasksError("reminder_days_range", "reminder")
    if TaskReminder.objects.filter(task=task, kind=TaskReminder.Kind.MANUAL).count() >= LIMIT:
        raise TasksError("reminders_limit", "reminder")
    shifted = _shift(actor, moment) or moment
    reminder = TaskReminder.objects.create(task=task, user=actor, kind=TaskReminder.Kind.MANUAL, moment=shifted,
                                           days=days if days not in (None, "") else None)
    audit.record("tasks.reminder_set", actor=actor, object_type="tasks.task", object_id=task.pk,
                 after={"reminder": reminder.pk, "moment": shifted.isoformat()})
    return reminder


def postpone(actor, reminder) -> TaskReminder:
    """Отложить пришедшее напоминание на следующий рабочий день от текущего момента."""
    if reminder.user_id != actor.pk:
        raise TasksError("reminder_forbidden_other", "reminder")
    base = reminder.postponed_to or reminder.moment
    target = _start(_next_working(timezone.localtime(base).date() + datetime.timedelta(days=1)))
    reminder.postponed_to = target
    reminder.state = TaskReminder.State.PENDING
    reminder.save(update_fields=["postponed_to", "state"])
    return reminder


def cancel_all(task, *, reason: str = "") -> int:
    """Снять все напоминания задачи."""
    deleted, _ = TaskReminder.objects.filter(task=task).delete()
    return deleted


def due(now=None) -> list[TaskReminder]:
    """Созревшие напоминания: `pending` и момент (или отложенный) не позже `now`."""
    now = now or timezone.now()
    from django.db.models import Q

    return list(TaskReminder.objects.filter(state=TaskReminder.State.PENDING)
                .filter(Q(postponed_to__lte=now) | Q(postponed_to__isnull=True, moment__lte=now))
                .select_related("task", "user").order_by("moment", "pk")[:1000])


def replan(task) -> list[TaskReminder]:
    """Псевдоним `plan` для службы задач."""
    return plan(task)
