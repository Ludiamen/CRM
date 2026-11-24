"""Данные установки среза 011: права сроков и отчётов заявок.

Права — данные (SPEC-011, FR-756): «Уровни обслуживания» открывает `servicedesk.sla` и общие частые ответы —
`servicedesk.answers`, «Отчёт по заявкам» — `servicedesk.reports`. Начальные выдачи: «Администратор портала»
получает `servicedesk.sla` и `servicedesk.answers` (отчёт администратору по умолчанию не выдаётся — SPEC-011,
решение 10), роль «Руководитель» — `servicedesk.reports`. Повторный запуск идемпотентен.
"""
from django.db import migrations

PERMISSIONS = [
    ("servicedesk.sla", "Уровни обслуживания заявок"),
    ("servicedesk.reports", "Отчёт по заявкам"),
    ("servicedesk.answers", "Общие частые ответы"),
]
GRANTS = [
    ("Администратор портала", ["servicedesk.sla", "servicedesk.answers"]),
    ("Руководитель", ["servicedesk.reports"]),
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

    dependencies = [("core", "0015_instructions_permissions")]
    operations = [migrations.RunPython(seed, unseed)]
