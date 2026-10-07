"""Задания RQ: опрос, разбор, автозакрытие, сроки хранения, сверка ответственных, подбор зависших писем (PLAN-003, «Где живёт код»)."""

import django_rq

from .services import closing, intake


def process_inbound(inbound_id):
    """Разбор входящего письма (7.2); исключение шага идёт наружу, повтор делает RQ."""
    return intake.process(inbound_id)


def autoclose(limit=50, after=None):
    """Порция автозакрытия (7.1); при остатке следующая порция уходит в `maintenance` (аргументы только по ключам)."""
    batch = closing.autoclose_batch(limit=limit, after=after)
    if batch.more:
        django_rq.get_queue("maintenance").enqueue(autoclose, limit=limit, after=batch.last, job_timeout=600)
