"""Данные установки среза 007: права ленты и срок хранения по умолчанию."""
from django.db import migrations

PERMISSIONS = [
    ("feed.post_all", "Писать всем"),
    ("feed.moderate", "Модерировать ленту"),
]
ADMIN_ROLE = "Администратор портала"


def seed(apps, schema_editor, *, stand=False):
    db = schema_editor.connection.alias
    Permission, Role = apps.get_model("core", "Permission"), apps.get_model("core", "Role")
    FeedSettings = apps.get_model("feed", "FeedSettings")
    for code, title in PERMISSIONS:
        permission, created = Permission.objects.using(db).get_or_create(code=code, defaults={"title": title})
        if not (created or stand):
            continue
        if code == "feed.post_all":
            for role in Role.objects.using(db).all():
                role.permissions.add(permission)
        else:
            admin = Role.objects.using(db).filter(name=ADMIN_ROLE).first()
            if admin is not None:
                admin.permissions.add(permission)
    FeedSettings.objects.using(db).get_or_create(pk=1, defaults={"retention_years": 3})


def unseed(apps, schema_editor):
    db = schema_editor.connection.alias
    apps.get_model("core", "Permission").objects.using(db).filter(code__in=[c for c, _ in PERMISSIONS]).delete()
    apps.get_model("feed", "FeedSettings").objects.using(db).filter(pk=1).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("feed", "0001_initial"),
        ("core", "0002_initial_data"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
