"""Данные установки среза 009: права задач `tasks.use` и `tasks.assign` (T-9004; PLAN-009, «Права»).

Права — данные, а не код (ADR-0018 п. 13): «Задачи» открывает `tasks.use`, ставить задачу другому в
управляемых узлах — `tasks.assign`. Оба права выданы встроенным ролям «Администратор портала» и
«Сотрудник ИТ»; дальше состав меняет администратор в разделе ролей. Функция `seed` идемпотентна.

Списки `PERMISSIONS`, `GRANTS` и `operations` — на уровне модуля: класс `Migration` берёт их как есть, а тесты
среза сверяют состав по модулю (CONTRACT-009, 2.2).
"""
from django.db import migrations

PERMISSIONS = [
    ("tasks.use", "Работа с задачами"),
    ("tasks.assign", "Ставить задачи другим сотрудникам"),
]
GRANTS = [
    ("Администратор портала", ["tasks.use", "tasks.assign"]),
    ("Сотрудник ИТ", ["tasks.use", "tasks.assign"]),
]


def seed(apps, schema_editor):
    db = schema_editor.connection.alias  # миграции идут под владельцем схемы (алиас migrate)
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


dependencies = [("core", "0012_storedfile_task_purpose")]
operations = [migrations.RunPython(seed, unseed)]


class Migration(migrations.Migration):

    dependencies = [("core", "0012_storedfile_task_purpose")]
    operations = operations
