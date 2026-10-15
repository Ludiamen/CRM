"""Служба опроса ботов Telegram и MAX (FR-325, FR-332, FR-336): два потока, по одному на бота.

Запускается службой `notify-poller` (`python manage.py notify_poll`), ровно одной копией: второй опрашивающий получает
от Telegram ответ 409. Команда не защищена флагом стенда и в журнал событий не пишет. Токены, адреса запросов и тексты
ответов в журнал приложения не попадают (NFR-312).
"""
import logging
import signal
import threading

from django.core.management.base import BaseCommand
from django.db import close_old_connections, connection

from apps.notify.services import bots

logger = logging.getLogger(__name__)

CHANNELS = ("telegram", "max")


def run_loop(channel: str, stop: threading.Event) -> None:
    """Тело потока одного бота (решение E5): шаг за шагом, пока не взведено событие остановки."""
    logger.info("Опрос бота запущен: %s", channel)
    started = False
    while not stop.is_set():
        try:
            if not bots.active(channel):
                started = False
                pause = bots.PAUSE_IDLE
            else:
                if not started:
                    started = bots.start_cycle(channel)
                pause = bots.poll_once(channel)
        except Exception as error:  # сбой вне адаптера не убивает поток; текст исключения не пишется (NFR-312)
            logger.warning("Сбой шага опроса бота %s: %s", channel, type(error).__name__)
            pause = bots.PAUSE_ERROR
        finally:
            close_old_connections()
        stop.wait(pause)


def _thread_body(channel: str, stop: threading.Event) -> None:
    try:
        run_loop(channel, stop)
    finally:
        connection.close()


class Command(BaseCommand):
    help = "Опрос ботов Telegram и MAX: два потока, остановка по SIGTERM и SIGINT после текущего ответа."

    def handle(self, *args, **options):
        stop = threading.Event()
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        threads = [threading.Thread(target=_thread_body, args=(channel, stop), name=f"notify-poll-{channel}")
                   for channel in CHANNELS]
        for thread in threads:
            thread.start()
        while any(thread.is_alive() for thread in threads):
            for thread in threads:
                thread.join(timeout=1)
