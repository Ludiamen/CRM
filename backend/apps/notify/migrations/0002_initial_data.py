"""Данные установки среза 004: право «Настройка уведомлений» и единственная строка настроек.

Право получает только «Администратор портала». Остальные таблицы `notify` после установки пусты.
"""
from django.db import migrations

ADMIN_ROLE = "Администратор портала"
PERMISSIONS = [("notify.manage", "Настройка уведомлений")]


def seed(apps, schema_editor):
    db = schema_editor.connection.alias  # миграции идут под владельцем схемы (алиас migrate)
    Permission, Role = apps.get_model("core", "Permission"), apps.get_model("core", "Role")
    admin = Role.objects.using(db).get(name=ADMIN_ROLE, is_builtin=True)
    for code, title in PERMISSIONS:
        admin.permissions.add(Permission.objects.using(db).create(code=code, title=title))
    apps.get_model("notify", "NotifySettings").objects.using(db).create(
        pk=1, webpush_enabled=False, telegram_enabled=False, max_enabled=False,
        email_delay_minutes=15, retention_days=90, defaults={}, channel_status={})


def unseed(apps, schema_editor):
    db = schema_editor.connection.alias
    apps.get_model("notify", "NotifySettings").objects.using(db).all().delete()
    apps.get_model("core", "Permission").objects.using(db).filter(code__in=[c for c, _ in PERMISSIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("notify", "0001_initial"),
        ("servicedesk", "0003_initial_data"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
