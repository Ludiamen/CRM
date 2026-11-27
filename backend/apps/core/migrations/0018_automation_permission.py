"""Данные установки среза 013: право управления автоматизацией (T-13002; SPEC-013, FR-812).

Право — данные: глобальные правила открывает `automation.manage`; начальная выдача — только встроенной роли
«Администратор портала». Повторный запуск идемпотентен.
"""
from django.db import migrations

PERMISSIONS = [
    ("automation.manage", "Управление автоматизацией"),
]
GRANTS = [
    ("Администратор портала", ["automation.manage"]),
]


def seed(apps, schema_editor):
    db = schema_editor.connection.alias
    Permission, Role = apps.get_model("core", "Permission"), apps.get_model("core", "Role")
    permissions = {}
    for code, title in PERMISSIONS:
        permissions[code], _ = Permission.objects.using(db).get_or_create(code=code, defaults={"title": title})
    for role_name, codes in GRANTS:
        role = Role.objects.using(db).filter(name=role_name, is_builtin=True).first()
        if role is None:
            continue
        for code in codes:
            role.permissions.add(permissions[code])


def unseed(apps, schema_editor):
    db = schema_editor.connection.alias
    apps.get_model("core", "Permission").objects.using(db).filter(
        code__in=[code for code, _ in PERMISSIONS]).delete()


class Migration(migrations.Migration):

    dependencies = [("core", "0017_user_unavailability")]
    operations = [migrations.RunPython(seed, unseed)]
