"""Ночные задания портала для `rq cron config.cron` (T-232, FR-011, FR-039, PLAN-001, «Запуск»).

Отдельный сервис `scheduler` запускает `rq cron config.cron`: модуль загружается им, а
каждое зарегистрированное задание уходит в очередь и исполняется рабочим процессом.
Очередь одна — `mail` (другой в настройках нет), поэтому и ночные очистки идут через неё.
Журнал событий не очищается никаким заданием: срок его хранения не меньше трёх лет.
"""
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from rq.cron import register  # noqa: E402

from apps.core.services.retention import (  # noqa: E402
    purge_expired_links, purge_expired_sessions, purge_login_history)

QUEUE = "mail"

# Ночью, когда на портале тихо; минуты разведены, чтобы очистки не шли одновременно
register(purge_login_history, queue_name=QUEUE, cron="10 3 * * *", name="purge_login_history")
register(purge_expired_links, queue_name=QUEUE, cron="20 3 * * *", name="purge_expired_links")
register(purge_expired_sessions, queue_name=QUEUE, cron="30 3 * * *", name="purge_expired_sessions")
