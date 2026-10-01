"""Помощники тестов почты T-111…T-115: доставка очереди RQ настоящим рабочим процессом.

`SimpleWorker` исполняет задание в том же процессе и в той же транзакции теста, поэтому
задание видит `MailMessage`, созданное тестом, а тест — `MailAttempt`, записанный заданием
(обычный `Worker` форкается и не видел бы данных теста). Очередь и Valkey — настоящие.
"""
import django_rq
from rq.worker import SimpleWorker


def mail_queue():
    return django_rq.get_queue("mail")


def deliver(queue_name: str = "mail") -> None:
    """Исполняет все задания очереди, стоящие к этому моменту (burst). Повторы не ждёт."""
    queue = django_rq.get_queue(queue_name)
    SimpleWorker([queue], connection=queue.connection).work(burst=True)


def device_cookie_names(client) -> list[str]:
    """Имена кук клиента, кроме сессии и CSRF: это кука устройства (имя плана не задаёт)."""
    from django.conf import settings

    return [n for n in client.cookies if n not in (settings.SESSION_COOKIE_NAME, settings.CSRF_COOKIE_NAME)]


def mail_jobs():
    return list(mail_queue().jobs)


def break_smtp(settings) -> None:
    """Почтовый сервер недоступен: адрес без слушателя (сбой соединения, а не подмена кода приложения)."""
    settings.EMAIL_HOST, settings.EMAIL_PORT = "127.0.0.1", 1
    settings.EMAIL_USE_TLS = settings.EMAIL_USE_SSL = False


def run_scheduler_step() -> None:
    """Один шаг планировщика RQ: задания, чей срок наступил, возвращаются в очередь."""
    from rq.scheduler import RQScheduler

    queue = mail_queue()
    scheduler = RQScheduler([queue], connection=queue.connection)
    # без захваченных замков реестры отложенных заданий не готовятся, и шаг планировщика ничего не делает
    scheduler.prepare_registries([queue.name])
    scheduler.enqueue_scheduled_jobs()


def make_due(job) -> None:
    """Сдвигает задание из реестра отложенных на «сейчас» (вместо ожидания паузы повтора)."""
    from datetime import datetime, timezone

    registry = mail_queue().scheduled_job_registry
    registry.schedule(job, datetime.now(timezone.utc))
