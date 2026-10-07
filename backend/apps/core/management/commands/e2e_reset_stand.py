"""Сброс данных стенда для приёмочных проходов Playwright (решение Opus, CONTRACT.md).

Работает ТОЛЬКО при E2E_STAND=1 в окружении (его задаёт лишь профиль dev compose);
без флага отказывает с ненулевым кодом и ничего не трогает. Очищает пользовательские
данные (учётные записи, сессии, ссылки, устройства, историю, журнал, письма),
возвращает настройки безопасности и портала к значениям по умолчанию, оставляет
права и начальные роли, чистит счётчики Valkey и очередь писем.

Точки `stand_reset` приложений и файлы фото в томе `protected` стираются здесь же.

Журнал для роли приложения неизменяем, поэтому очистка идёт под владельцем схемы
(алиас базы `migrate`, `DATABASE_MIGRATE_URL`).
"""
import os

import django_rq
from django.core.management.base import BaseCommand, CommandError
from django.db import connections

from apps.core import extensions
from apps.core.models import PortalSettings, Role, SecuritySettings, StoredFile
from apps.core.services import files, portal_settings, valkey

KEEP_TABLES = {"django_migrations", "core_permission", "core_role", "core_role_permissions",
               "core_securitysettings", "core_portalsettings"}
DATA_PREFIXES = ("core_", "mail_", "django_session")  # данные портала; справочники Django не трогаем
COUNTER_PATTERNS = ("fail:*", "lock:*", "accts:*", "*forgot:*", "*perms:*")


def _file_paths(stored) -> list:
    """Все возможные пути файла записи в томе `protected` (отсутствующие `remove_paths` пропускает)."""
    paths = [files.photo_path(stored, size) for size in files.SIZES]
    for status in (StoredFile.Status.PENDING, StoredFile.Status.QUARANTINE):
        stored.status = status
        paths.append(files.photo_path(stored))
    return paths


class Command(BaseCommand):
    help = "Очищает данные стенда (только при E2E_STAND=1)."

    def handle(self, *args, **options):
        if os.environ.get("E2E_STAND") != "1":
            raise CommandError("Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено.")
        if "migrate" not in connections.databases:
            raise CommandError("Нужен DATABASE_MIGRATE_URL: очистка идёт под владельцем схемы.")
        owner = connections["migrate"]
        # записи о файлах стираются вместе с таблицами ядра, поэтому пути берём до очистки
        stale_files = [path for stored in StoredFile.objects.using("migrate").all() for path in _file_paths(stored)]
        tables = [t for t in owner.introspection.django_table_names(only_existing=True, include_views=False)
                  if t not in KEEP_TABLES and t.startswith(DATA_PREFIXES)]
        statements = owner.ops.sql_flush(self.style, tables, reset_sequences=True, allow_cascade=True)
        owner.ops.execute_sql_flush(statements)
        files.remove_paths(stale_files)
        # данные приложений — до удаления своих ролей; обратный порядок: данные приложений, зарегистрированных
        # позже, держат ссылки PROTECT на данные зарегистрированных раньше (роли узлов `org`, узлы `org`)
        for reset in reversed(extensions.registered("stand_reset")):
            reset()
        Role.objects.using("migrate").filter(is_builtin=False).delete()
        defaults = {f.name: f.get_default() for f in SecuritySettings._meta.concrete_fields if not f.primary_key}
        SecuritySettings.objects.using("migrate").update(**defaults)
        PortalSettings.objects.using("migrate").update(name=portal_settings.DEFAULT_NAME, logo="")
        conn = valkey.conn()
        for pattern in COUNTER_PATTERNS:
            for key in conn.scan_iter(match=pattern, count=500):
                conn.delete(key)
        django_rq.get_queue("mail").empty()
        self.stdout.write("Данные стенда очищены.")
