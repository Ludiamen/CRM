"""Данные первой установки: семь прав среза, три начальные роли, настройки по умолчанию.

Значения «по умолчанию» (инвариант «настройка-без-кода») — единственное место, где они лежат в
коде: дальше их меняет администратор в интерфейсе.
"""
from django.db import migrations

PERMISSIONS = [
    ("accounts.manage", "Управлять учётными записями"),
    ("accounts.reset_2fa", "Сбрасывать второй фактор сотрудникам"),
    ("accounts.view_logins", "Просматривать устройства и входы сотрудников"),
    ("roles.manage", "Управлять ролями и правами"),
    ("audit.view", "Просматривать журнал событий"),
    ("settings.portal", "Менять настройки портала"),
    ("settings.security", "Менять политику безопасности"),
]
# «Руководитель» и «Сотрудник ИТ» — только свои данные: профиль, безопасность, устройства и входы (FR-020)
ROLES = [("Администратор портала", [code for code, _ in PERMISSIONS]), ("Руководитель", []), ("Сотрудник ИТ", [])]


def seed(apps, schema_editor):
    db = schema_editor.connection.alias  # миграции идут под владельцем схемы (алиас migrate)
    Permission, Role = apps.get_model("core", "Permission"), apps.get_model("core", "Role")
    SecuritySettings, PortalSettings = apps.get_model("core", "SecuritySettings"), apps.get_model("core", "PortalSettings")
    by_code = {code: Permission.objects.using(db).create(code=code, title=title) for code, title in PERMISSIONS}
    for name, codes in ROLES:
        role = Role.objects.using(db).create(name=name, is_builtin=True)
        role.permissions.set([by_code[code] for code in codes])
    SecuritySettings.objects.using(db).create()  # значения по умолчанию заданы в модели (NFR-005, ADR-0006)
    PortalSettings.objects.using(db).create(name="Портал ИТ-отдела")


def unseed(apps, schema_editor):
    db = schema_editor.connection.alias
    for name in ("Role", "Permission", "SecuritySettings", "PortalSettings"):
        apps.get_model("core", name).objects.using(db).all().delete()


class Migration(migrations.Migration):
    dependencies = [("core", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
