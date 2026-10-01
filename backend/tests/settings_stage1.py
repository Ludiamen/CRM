"""Каркасные настройки тестов Этапа 1 (T-009).

config.settings требует модель core.User, которой до Этапа 3 нет, поэтому тут
Django поднимается без приложений, зависящих от пользовательской модели
(auth, django_otp). Всё остальное — база под crm_app, миграции под crm_owner
(алиас migrate), Valkey, RQ — настоящее и берётся из config.settings.

Удалить в T-200 вместе со сменой DJANGO_SETTINGS_MODULE в pytest.ini.
"""
from config.settings import *  # noqa: F401,F403

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.sessions",
]
MIDDLEWARE = [m for m in MIDDLEWARE if "auth" not in m]  # noqa: F405
del AUTH_USER_MODEL  # noqa: F821
