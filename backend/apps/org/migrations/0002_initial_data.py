"""Данные установки среза 002: корневой отдел, права org.manage и calendar.manage, строка календаря.

Права получает только «Администратор портала»; участников у корня нет (FR-103, FR-112).
"""
from django.db import migrations

ROOT_NAME = "ИТ-отдел"
ROOT_NAME_KEY = "ит-отдел"
ADMIN_ROLE = "Администратор портала"
PERMISSIONS = [
    ("org.manage", "Управление структурой"),
    ("calendar.manage", "Рабочий календарь"),
]


def seed(apps, schema_editor):
    db = schema_editor.connection.alias  # миграции идут под владельцем схемы (алиас migrate)
    Unit, WorkCalendar = apps.get_model("org", "Unit"), apps.get_model("org", "WorkCalendar")
    Permission, Role = apps.get_model("core", "Permission"), apps.get_model("core", "Role")
    root = Unit.objects.using(db).create(
        name=ROOT_NAME, name_key=ROOT_NAME_KEY, kind="department", is_root=True, parent=None, depth=0,
        description="", path="")
    root.path = f"/{root.pk}/"
    root.save(using=db, update_fields=["path"])
    admin = Role.objects.using(db).get(name=ADMIN_ROLE, is_builtin=True)
    for code, title in PERMISSIONS:
        admin.permissions.add(Permission.objects.using(db).create(code=code, title=title))
    WorkCalendar.objects.using(db).create()  # значения по умолчанию заданы в модели


def unseed(apps, schema_editor):
    db = schema_editor.connection.alias
    apps.get_model("org", "WorkCalendar").objects.using(db).all().delete()
    apps.get_model("org", "Unit").objects.using(db).filter(is_root=True).delete()
    apps.get_model("core", "Permission").objects.using(db).filter(code__in=[code for code, _ in PERMISSIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("org", "0001_initial"),
        ("core", "0006_staff_view_permission"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
