"""Задания RQ сервис-деска, включая контроль сроков SLA."""

from datetime import datetime, timedelta

import django_rq
from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.extensions import Draft
from apps.notify.services import dispatch
from apps.org.models import WorkCalendar
from apps.org.services import calendar, structure

from .models import Queue, SlaCycle, SlaDigest, SlaNotice, Ticket
from .services import closing, intake, mailbox, reconcile, retention


def process_inbound(inbound_id):
    """Разбор входящего письма (7.2); исключение шага идёт наружу, повтор делает RQ."""
    return intake.process(inbound_id)


def autoclose(limit=50, after=None):
    """Порция автозакрытия (7.1); при остатке следующая порция уходит в `maintenance` (аргументы только по ключам)."""
    batch = closing.autoclose_batch(limit=limit, after=after)
    if batch.more:
        django_rq.get_queue("maintenance").enqueue(autoclose, limit=limit, after=batch.last, job_timeout=600)


def poll_mailbox():
    """Опрос ящика заявок (7.1): раз в минуту, очередь `inbox`; ошибки ящика поглощает `mailbox.poll`."""
    mailbox.poll()


def requeue_inbound():
    """Подбор зависших писем (7.1): `received` старше 3 минут без задания разбора."""
    mailbox.requeue_inbound()


def reconcile_assignees(after_id=0):
    """Сверка ответственных (7.1): порция в 50 человек; при остатке следующая уходит в `maintenance`."""
    batch = reconcile.batch(after_id=after_id, size=50)
    if batch.more:
        django_rq.get_queue("maintenance").enqueue(reconcile_assignees, after_id=batch.last_id, job_timeout=600)


def purge_inbound(after=None):
    """Чистка писем без заявки (7.1): порция в 50 писем; при остатке следующая уходит в `maintenance`."""
    batch = retention.purge_inbound(size=50, after=after)
    if batch.more:
        django_rq.get_queue("maintenance").enqueue(purge_inbound, after=batch.last, job_timeout=600)


def anonymize_tickets(done_total=0, after=None):
    """Обезличивание закрытых заявок (7.1): порция в 50, за ночь не больше 2000; остаток уходит в `maintenance`."""
    batch = retention.anonymize_batch(size=50, done_total=done_total, nightly_limit=2000, after=after)
    if batch.more:
        django_rq.get_queue("maintenance").enqueue(
            anonymize_tickets, done_total=done_total + batch.done, after=batch.last, job_timeout=600)


def purge_requester_previews():
    """Удаление неподтверждённых загрузок заявителей старше суток (7.1)."""
    retention.purge_requester_previews()


def purge_orphan_files(after=""):
    """Стирание файлов писем без строки (7.1): порция в 50 имён; при остатке следующая уходит в `maintenance`."""
    batch = retention.purge_orphan_files(size=50, after=after)
    if batch.more:
        django_rq.get_queue("maintenance").enqueue(purge_orphan_files, after=batch.last, job_timeout=600)


def _notice(cycle, deadline, kind, due_at, recipient, now, number):
    """Записать маркер и уведомление атомарно; уникальный ключ защищает от повтора."""
    try:
        with transaction.atomic():
            notice = SlaNotice.objects.create(
                cycle=cycle, deadline=deadline, kind=kind, due_at=due_at, recipient=recipient, sent_at=now,
            )
            code = "servicedesk.sla_due_soon" if kind == SlaNotice.Kind.DUE_SOON else "servicedesk.sla_overdue"
            dispatch.create(code, [Draft(
                user_id=recipient.pk, text="Срок заявки приближается" if kind == SlaNotice.Kind.DUE_SOON
                else "Заявка просрочена", url=f"/tickets/{number}/",
                object_ref=f"servicedesk.ticket:{cycle.ticket_id}",
            )])
    except IntegrityError:
        return False
    return True


def _overdue(cycle, deadline):
    return (deadline == SlaNotice.Deadline.REACTION and cycle.first_response_at is None) or (
        deadline == SlaNotice.Deadline.SOLUTION and cycle.closed_at is None
    )


def sla_tick(now=None):
    """Напоминания до сроков и одно уведомление о каждой просрочке."""
    now = now or timezone.now()
    if not cache.add("sla:tick", 1, timeout=240):
        return 0
    try:
        from .services import settings as sd_settings
        reminder_hours = getattr(sd_settings.get(), "sla_reminder_hours", 1)
        created = 0
        cycles = SlaCycle.objects.filter(is_current=True).select_related("ticket", "ticket__assignee", "level", "queue")
        for cycle in cycles:
            ticket = cycle.ticket
            if ticket.kind == "closed" and cycle.closed_at is not None:
                continue
            for deadline, due_at in (
                (SlaNotice.Deadline.REACTION, cycle.reaction_due),
                (SlaNotice.Deadline.SOLUTION, cycle.solution_due),
            ):
                if due_at is None:
                    continue
                if _overdue(cycle, deadline) and due_at <= now:
                    kind = SlaNotice.Kind.OVERDUE
                elif due_at > now:
                    from .services.sla import minutes_between
                    minutes = minutes_between(now, due_at, cycle.level)
                    if minutes > reminder_hours * 60:
                        continue
                    kind = SlaNotice.Kind.DUE_SOON
                else:
                    continue
                recipients = ([ticket.assignee] if ticket.assignee_id else []) + structure.heads_of_unit(ticket.queue_id)
                for recipient in {person.pk: person for person in recipients}.values():
                    if _notice(cycle, deadline, kind, due_at, recipient, now, ticket.number):
                        created += 1
        return created
    finally:
        cache.delete("sla:tick")


def sla_digest(now=None):
    """Ежедневная сводка руководителям очередей в первое рабочее окно."""
    now = now or timezone.now()
    local = now
    if calendar.day_kind(local.date()) in {"off", "holiday", "day_off"}:
        return 0
    workday = WorkCalendar.objects.first() or WorkCalendar.objects.create()
    start = datetime.combine(local.date(), workday.day_start, tzinfo=local.tzinfo)
    if not start <= local < start + timedelta(hours=1):
        return 0
    sent = 0
    cycles = SlaCycle.objects.filter(is_current=True).select_related("ticket", "ticket__queue", "queue")
    queues = list(Queue.objects.all())
    recipients = {}
    for queue in queues:
        for person in structure.heads_of_unit(queue.unit_id):
            recipients.setdefault(person.pk, set()).add(queue.unit_id)
    for person_id, unit_ids in recipients.items():
        day = local.date()
        try:
            with transaction.atomic():
                row = SlaDigest.objects.create(recipient_id=person_id, day=day,
                                               units=sorted(unit_ids), sent_at=now)
                overdue, today, week = [], [], []
                week_end = day + timedelta(days=6 - day.weekday())
                for cycle in cycles:
                    if cycle.queue_id not in unit_ids:
                        continue
                    deadlines = [d for d in (cycle.reaction_due, cycle.solution_due) if d is not None]
                    if not deadlines:
                        continue
                    due = min(deadlines)
                    due_day = timezone.localtime(due).date()
                    if _overdue(cycle, SlaNotice.Deadline.REACTION) and cycle.reaction_due <= now:
                        overdue.append(cycle.ticket.number)
                    elif _overdue(cycle, SlaNotice.Deadline.SOLUTION) and cycle.solution_due <= now:
                        overdue.append(cycle.ticket.number)
                    elif due_day == day:
                        today.append(cycle.ticket.number)
                    elif day < due_day <= week_end:
                        week.append(cycle.ticket.number)
                text = (
                    f"Просроченные: {', '.join(map(str, sorted(set(overdue)))) or 'нет'}\n"
                    f"Срок сегодня: {', '.join(map(str, sorted(set(today)))) or 'нет'}\n"
                    f"Срок на неделе: {', '.join(map(str, sorted(set(week)))) or 'нет'}"
                )
                dispatch.create("servicedesk.sla_digest", [Draft(
                    user_id=person_id, text=text, url="/tickets/",
                    object_ref=f"servicedesk.sla_digest:{day.isoformat()}",
                )])
        except IntegrityError:
            continue
        sent += 1
    return sent
