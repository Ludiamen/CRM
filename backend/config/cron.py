"""Ночные задания портала для `rq cron config.cron` (T-232, FR-011, FR-039, PLAN-001, «Запуск»).

Отдельный сервис `scheduler` запускает `rq cron config.cron`: модуль загружается им, а
каждое зарегистрированное задание уходит в очередь и исполняется рабочим процессом.
Очереди — `files`, `mail`, `maintenance` и `inbox` (`RQ_QUEUES` в `config/settings.py`); прежние ночные очистки идут через `mail`.
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
from apps.servicedesk.tasks import (  # noqa: E402
    anonymize_tickets, autoclose, poll_mailbox, purge_inbound, purge_orphan_files,
    purge_requester_previews, reconcile_assignees, requeue_inbound)

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

# Сервис-деск (срез 003, T-3240). Время `rq cron` — по UTC; ночные задания назначены по Москве минус три часа
# (после резервной копии 01:30 по Москве). Каждому заданию задан предел выполнения `job_timeout`, секунд.
register(poll_mailbox, queue_name="inbox", cron="* * * * *", name="poll_mailbox", job_timeout=600)
register(requeue_inbound, queue_name="inbox", cron="*/5 * * * *", name="requeue_inbound", job_timeout=300)
register(autoclose, queue_name="maintenance", cron="5 * * * *", name="autoclose", job_timeout=600)
register(reconcile_assignees, queue_name="maintenance", cron="25 * * * *", name="reconcile_assignees", job_timeout=600)
register(purge_inbound, queue_name="maintenance", cron="10 23 * * *", name="purge_inbound", job_timeout=600)
register(anonymize_tickets, queue_name="maintenance", cron="20 23 * * *", name="anonymize_tickets", job_timeout=600)
register(purge_requester_previews, queue_name="maintenance", cron="30 23 * * *", name="purge_requester_previews",
         job_timeout=300)
register(purge_orphan_files, queue_name="maintenance", cron="50 23 * * *", name="purge_orphan_files", job_timeout=600)
