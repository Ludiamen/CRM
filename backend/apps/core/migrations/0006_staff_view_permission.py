"""Право среза 002 `staff.view` («Просмотр сотрудников и структуры») — его получают все начальные роли."""
from django.db import migrations

CODE, TITLE = "staff.view", "Просмотр сотрудников и структуры"


def add_permission(apps, schema_editor):
    db = schema_editor.connection.alias
    Permission, Role = apps.get_model("core", "Permission"), apps.get_model("core", "Role")
    permission, _ = Permission.objects.using(db).get_or_create(code=CODE, defaults={"title": TITLE})
    for role in Role.objects.using(db).filter(is_builtin=True):
        role.permissions.add(permission)


def remove_permission(apps, schema_editor):
    db = schema_editor.connection.alias
    apps.get_model("core", "Permission").objects.using(db).filter(code=CODE).delete()  # связи с ролями уйдут с правом


class Migration(migrations.Migration):
    dependencies = [("core", "0005_user_dismissal_and_card_fields")]
    operations = [migrations.RunPython(add_permission, remove_permission)]
