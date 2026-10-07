"""Данные установки среза 003: права, статусы, критичности, сложность, источники, категория «Другое», настройки.

Права получает только «Администратор портала». Строки `Queue` и `MailboxState` не создаются.
"""
from django.db import migrations

ADMIN_ROLE = "Администратор портала"
PERMISSIONS = [
    ("servicedesk.all", "Все заявки"),
    ("servicedesk.manage", "Настройка сервис-деска"),
]
# (название, вид, по умолчанию, системный код, порядок)
STATUSES = [
    ("Новая", "new", True, "", 10),
    ("В работе", "in_progress", True, "", 20),
    ("Ждёт ответа заявителя", "waiting", True, "", 30),
    ("Решена", "closed", True, "", 40),
    ("Не может быть решена", "closed", False, "", 50),
    ("Закрыта автоматически", "closed", False, "autoclosed", 60),
]
PRIORITIES = [("Низкая", 10), ("Средняя", 20), ("Высокая", 30)]
COMPLEXITIES = [("Лёгкий", 10), ("Средний", 20), ("Высокий", 30)]
SOURCES = [("Почта", "mail", 10), ("Форма", "form", 20), ("Телефон", "", 30), ("Лично", "", 40)]
OTHER_CATEGORY = "Другое"
DEFAULT_PRIORITY = "Средняя"


def name_key(text):
    """Ключ названия — та же формула, что у `org.services.structure.name_key`."""
    return " ".join(text.split()).lower().replace("ё", "е")


def seed(apps, schema_editor):
    db = schema_editor.connection.alias  # миграции идут под владельцем схемы (алиас migrate)
    Permission, Role = apps.get_model("core", "Permission"), apps.get_model("core", "Role")
    admin = Role.objects.using(db).get(name=ADMIN_ROLE, is_builtin=True)
    for code, title in PERMISSIONS:
        admin.permissions.add(Permission.objects.using(db).create(code=code, title=title))

    get = lambda name: apps.get_model("servicedesk", name).objects.using(db)  # noqa: E731
    for name, kind, is_default, system_code, order in STATUSES:
        get("Status").create(name=name, name_key=name_key(name), kind=kind, is_default=is_default,
                             system_code=system_code, order=order)
    for name, order in PRIORITIES:
        get("Priority").create(name=name, name_key=name_key(name), order=order)
    for name, order in COMPLEXITIES:
        get("Complexity").create(name=name, name_key=name_key(name), order=order)
    for name, system_code, order in SOURCES:
        get("Source").create(name=name, name_key=name_key(name), system_code=system_code, order=order)
    get("Category").create(name=OTHER_CATEGORY, name_key=name_key(OTHER_CATEGORY), queue=None, is_system=True,
                           on_form=True, order=100)
    get("ServiceDeskSettings").create(pk=1, default_priority=get("Priority").get(name_key=name_key(DEFAULT_PRIORITY)))


def unseed(apps, schema_editor):
    db = schema_editor.connection.alias
    get = lambda name: apps.get_model("servicedesk", name).objects.using(db)  # noqa: E731
    get("ServiceDeskSettings").all().delete()  # держит Priority через PROTECT
    for name in ("Category", "Source", "Complexity", "Priority", "Status"):
        get(name).all().delete()
    apps.get_model("core", "Permission").objects.using(db).filter(code__in=[c for c, _ in PERMISSIONS]).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("servicedesk", "0002_ticket_number_sequence"),
        ("core", "0007_storedfile_attachment"),
        ("org", "0002_initial_data"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
