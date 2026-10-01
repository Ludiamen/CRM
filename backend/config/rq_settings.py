"""Настройки рабочего процесса RQ: `rq worker -c config.rq_settings --with-scheduler mail`.

Рабочий процесс rq сам Django не поднимает, а задания (почта, ночные очистки) работают
с моделями. Модуль, который rq импортирует по ключу `-c`, поднимает Django и отдаёт
адрес Valkey из тех же настроек, что и портал.
"""
import os

import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()

from django.conf import settings  # noqa: E402

REDIS_URL = settings.VALKEY_URL
