"""Данные установки среза 005: права knowledge.edit и knowledge.manage, рубрика «Общее», строка настроек.

Права получают встроенные роли по названию: «Администратор портала» — оба, «Сотрудник ИТ» — `knowledge.edit`.
Функция `seed` идемпотентна: её зовут при установке, при обновлении и при каждом сбросе стенда (решение 27 задач).
"""
from django.db import migrations

PERMISSIONS = [
    ("knowledge.edit", "Редактирование базы знаний"),
    ("knowledge.manage", "Управление базой знаний"),
]
GRANTS = [
    ("Администратор портала", ["knowledge.edit", "knowledge.manage"]),
    ("Сотрудник ИТ", ["knowledge.edit"]),
]
DEFAULT_RUBRIC = "Общее"


def seed(apps, schema_editor):
    db = schema_editor.connection.alias  # миграции идут под владельцем схемы (алиас migrate)
    Permission, Role = apps.get_model("core", "Permission"), apps.get_model("core", "Role")
    Rubric, Settings = apps.get_model("knowledge", "Rubric"), apps.get_model("knowledge", "KnowledgeSettings")
    permissions = {}
    for code, title in PERMISSIONS:
        permissions[code], _ = Permission.objects.using(db).get_or_create(code=code, defaults={"title": title})
    for role_name, codes in GRANTS:
        role = Role.objects.using(db).filter(name=role_name, is_builtin=True).first()
        if role is None:
            continue
        for code in codes:
            role.permissions.add(permissions[code])
    if not Rubric.objects.using(db).filter(is_default=True).exists():
        Rubric.objects.using(db).create(name=DEFAULT_RUBRIC, parent=None, depth=1, is_default=True)
    if not Settings.objects.using(db).filter(pk=1).exists():
        Settings.objects.using(db).create(pk=1, trash_days=90)


def unseed(apps, schema_editor):
    db = schema_editor.connection.alias
    apps.get_model("knowledge", "KnowledgeSettings").objects.using(db).all().delete()
    apps.get_model("knowledge", "Rubric").objects.using(db).filter(is_default=True, parent=None).delete()
    apps.get_model("core", "Permission").objects.using(db).filter(code__in=[c for c, _ in PERMISSIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("knowledge", "0001_initial"),
        ("core", "0002_initial_data"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
