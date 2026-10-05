"""Ночные задания портала для `rq cron config.cron` (T-232, FR-011, FR-039, PLAN-001, «Запуск»).

Отдельный сервис `scheduler` запускает `rq cron config.cron`: модуль загружается им, а
каждое зарегистрированное задание уходит в очередь и исполняется рабочим процессом.
Очередей две — `mail` и `files` (`RQ_QUEUES` в `config/settings.py`); ночные очистки по-прежнему идут через `mail`.
Журнал событий не очищается никаким заданием: срок его хранения не меньше трёх лет.
"""
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from rq.cron import register  # noqa: E402

from apps.core.services.retention import (  # noqa: E402
    purge_expired_links, purge_expired_sessions, purge_login_history)
from apps.core.tasks import purge_quarantine, requeue_pending_scans  # noqa: E402
from apps.org.tasks import purge_previews  # noqa: E402

QUEUE = "mail"

# Ночью, когда на портале тихо; минуты разведены, чтобы очистки не шли одновременно
register(purge_login_history, queue_name=QUEUE, cron="10 3 * * *", name="purge_login_history")
register(purge_expired_links, queue_name=QUEUE, cron="20 3 * * *", name="purge_expired_links")
register(purge_expired_sessions, queue_name=QUEUE, cron="30 3 * * *", name="purge_expired_sessions")

# Путь фото (T-2216): часовой подбор ожидающих проверки и ночная очистка карантина
register(requeue_pending_scans, queue_name=QUEUE, cron="0 * * * *", name="requeue_pending_scans")
register(purge_quarantine, queue_name=QUEUE, cron="50 3 * * *", name="purge_quarantine")

# Загрузки среза 002 (T-2218): неподтверждённые предпросмотры сотрудников и календаря старше суток
register(purge_previews, queue_name=QUEUE, cron="40 3 * * *", name="purge_import_previews")
