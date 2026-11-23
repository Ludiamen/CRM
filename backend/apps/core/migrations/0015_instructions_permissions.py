"""Данные установки среза 010: права поручений `instructions.use` и `instructions.assign`.

Права — данные: «Поручения» открывает `instructions.use`, ставить поручения подчинённым — `instructions.assign`.
Выданы «Администратору портала» и «Сотруднику ИТ»; повторный запуск идемпотентен.
"""
from django.db import migrations

PERMISSIONS = [
    ("instructions.use", "Работа с поручениями"),
    ("instructions.assign", "Ставить поручения подчинённым"),
]
GRANTS = [
    ("Администратор портала", ["instructions.use", "instructions.assign"]),
    ("Сотрудник ИТ", ["instructions.use", "instructions.assign"]),
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


dependencies = [("core", "0014_storedfile_instruction_purpose")]
operations = [migrations.RunPython(seed, unseed)]


class Migration(migrations.Migration):

    dependencies = [("core", "0014_storedfile_instruction_purpose")]
    operations = operations
