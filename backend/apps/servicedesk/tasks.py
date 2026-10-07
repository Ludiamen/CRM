"""Задания RQ: опрос, разбор, автозакрытие, сроки хранения, сверка ответственных, подбор зависших писем (PLAN-003, «Где живёт код»)."""

import django_rq

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
