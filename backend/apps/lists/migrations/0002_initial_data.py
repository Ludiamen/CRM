"""Данные установки среза 006: право lists.manage, шесть стартовых списков, права «Сотрудника ИТ» на них.

Право получает встроенная роль «Администратор портала» по названию. Стартовые списки создаются по устойчивым
кодам: создаётся только отсутствующий код, поэтому повторный вызов не дублирует список и не трогает правки
администратора (решение 51 задач). Чтение и правка у роли «Сотрудник ИТ» — строки `Access`, а не право роли.
Функцию `seed` зовут при установке, при обновлении и при каждом сбросе стенда (`lists/stand.py`).
"""
from django.db import migrations

PERMISSION = ("lists.manage", "Управление списками")
ADMIN_ROLE = "Администратор портала"
IT_ROLE = "Сотрудник ИТ"
LICENSE_HINT = "Ключи активации здесь не храните: секреты хранятся вне портала"

# Код списка, название, поля: (код, название, тип, признаки). Порядок списков важен: `equipment` — первым,
# на него ссылаются поля типа «запись». Признаки: unique, multiple, thresholds, currency, target, hint, choices.
SEED_LISTS = [
    ("equipment", "Оборудование", [
        ("kind", "Вид", "choice", {"choices": ["Компьютер", "Ноутбук", "Монитор", "Принтер/МФУ",
                                                "Сетевое оборудование", "Телефон", "Прочее"]}),
        ("inventory_number", "Инвентарный номер", "string", {"unique": True}),
        ("serial_number", "Серийный номер", "string", {"unique": True}),
        ("model", "Модель", "string", {}),
        ("state", "Состояние", "choice", {"choices": ["В работе", "На складе", "В ремонте"]}),
        ("assignee", "За кем закреплено", "person", {}),
        ("unit", "Подразделение", "unit", {}),
        ("place", "Место", "string", {}),
        ("purchased", "Дата покупки", "date", {}),
        ("warranty", "Гарантия до", "date", {"thresholds": [30]}),
        ("cost", "Стоимость", "money", {"currency": "RUB"}),
        ("note", "Примечание", "text", {}),
        ("files", "Файлы", "file", {"multiple": True}),
    ]),
    ("licenses", "Лицензии", [
        ("product", "Продукт", "string", {}),
        ("kind", "Вид", "choice", {"choices": ["Бессрочная", "Подписка"]}),
        ("seats", "Количество мест", "number", {}),
        ("license_number", "Номер лицензии или договора", "string", {"hint": LICENSE_HINT}),
        ("valid_until", "Действует до", "date", {"thresholds": [30, 7]}),
        ("installed_on", "Установлена на", "record", {"target": "equipment", "multiple": True}),
        ("owner", "Ответственный", "person", {}),
        ("cost", "Стоимость", "money", {"currency": "RUB"}),
        ("files", "Файлы", "file", {"multiple": True}),
    ]),
    ("consumables", "Картриджи и расходники", [
        ("kind", "Вид", "choice", {"choices": ["Картридж", "Тонер", "Барабан", "Прочее"]}),
        ("model", "Модель", "string", {}),
        ("printers", "Для принтера", "record", {"target": "equipment", "multiple": True}),
        ("stock", "Количество на складе", "number", {}),
        ("note", "Примечание", "text", {}),
    ]),
    ("signatures", "Сертификаты ЭП", [
        ("holder", "Владелец", "person", {}),
        ("issuer", "Удостоверяющий центр", "string", {}),
        ("serial_number", "Серийный номер", "string", {"unique": True}),
        ("medium", "Носитель", "choice", {"choices": ["Токен", "Реестр", "Облако"]}),
        ("valid_until", "Действует до", "date", {"thresholds": [30, 7]}),
        ("files", "Файлы", "file", {"multiple": True}),
    ]),
    ("contracts", "Договоры", [
        ("counterparty", "Контрагент", "string", {}),
        ("contract_number", "Номер договора", "string", {"unique": True}),
        ("subject", "Предмет", "text", {}),
        ("signed", "Дата заключения", "date", {}),
        ("valid_until", "Действует до", "date", {"thresholds": [30]}),
        ("amount", "Сумма", "money", {"currency": "RUB"}),
        ("owner", "Ответственный", "person", {}),
        ("files", "Файлы", "file", {"multiple": True}),
    ]),
    ("sims", "SIM-карты и телефоны", [
        ("phone", "Номер телефона", "string", {"unique": True}),
        ("operator", "Оператор", "choice", {"choices": []}),
        ("tariff", "Тариф", "string", {}),
        ("assignee", "За кем закреплено", "person", {}),
        ("device", "Устройство", "record", {"target": "equipment"}),
        ("iccid", "ICCID", "string", {}),
        ("note", "Примечание", "text", {}),
    ]),
]
SEED_CODES = [code for code, _, _ in SEED_LISTS]
# «Показывать в таблице» (решение 52 задач): первые четыре поля после «Названия», кроме текста и файлов
NOT_IN_TABLE_TYPES = {"text", "file"}
IN_TABLE_COUNT = 4


def _settings(field_type, props):
    result = {}
    if props.get("currency"):
        result["currency"] = props["currency"]
    if props.get("thresholds"):
        result["deadline"] = True
        result["thresholds"] = list(props["thresholds"])
    return result


def seed(apps, schema_editor):
    db = schema_editor.connection.alias  # миграции идут под владельцем схемы (алиас migrate)
    Permission, Role = apps.get_model("core", "Permission"), apps.get_model("core", "Role")
    List, Field, Choice, Access = (apps.get_model("lists", name) for name in ("List", "Field", "Choice", "Access"))
    code, title = PERMISSION
    permission, _ = Permission.objects.using(db).get_or_create(code=code, defaults={"title": title})
    admin = Role.objects.using(db).filter(name=ADMIN_ROLE, is_builtin=True).first()
    if admin is not None:
        admin.permissions.add(permission)
    it_staff = Role.objects.using(db).filter(name=IT_ROLE, is_builtin=True).first()
    lists = {lst.code: lst for lst in List.objects.using(db).filter(code__in=SEED_CODES)}
    for list_code, list_name, fields in SEED_LISTS:
        if list_code in lists:
            continue
        lst = List.objects.using(db).create(code=list_code, name=list_name, created_by=None)
        lists[list_code] = lst
        shown = 0
        for order, (field_code, field_name, field_type, props) in enumerate(fields, start=1):
            show = False
            if field_type not in NOT_IN_TABLE_TYPES and shown < IN_TABLE_COUNT:
                show = True
                shown += 1
            target = lists[props["target"]] if props.get("target") else None
            field = Field.objects.using(db).create(
                list=lst, code=field_code, name=field_name, hint=props.get("hint", ""), type=field_type,
                multiple=bool(props.get("multiple")), unique=bool(props.get("unique")), show_in_table=show,
                order=order, target=target, settings=_settings(field_type, props))
            for choice_order, choice_title in enumerate(props.get("choices", []), start=1):
                Choice.objects.using(db).create(field=field, title=choice_title, order=choice_order)
        if it_staff is not None:
            for level in ("read", "edit"):
                Access.objects.using(db).get_or_create(list=lst, level=level, role=it_staff)


def unseed(apps, schema_editor):
    db = schema_editor.connection.alias
    apps.get_model("core", "Permission").objects.using(db).filter(code=PERMISSION[0]).delete()
    List, Field, Record = (apps.get_model("lists", name) for name in ("List", "Field", "Record"))
    with_records = set(Record.objects.using(db).filter(list__code__in=SEED_CODES).values_list("list_id", flat=True))
    doomed = set(List.objects.using(db).filter(code__in=SEED_CODES).values_list("pk", flat=True)) - with_records
    # Список, на который ссылается поле остающегося списка, удалять нельзя (RESTRICT): он остаётся без ошибки
    changed = True
    while changed:
        changed = False
        for target_id in set(Field.objects.using(db).filter(target_id__in=doomed).exclude(list_id__in=doomed)
                             .values_list("target_id", flat=True)):
            doomed.discard(target_id)
            changed = True
    List.objects.using(db).filter(pk__in=doomed).delete()


class Migration(migrations.Migration):
    dependencies = [
        ("lists", "0001_initial"),
        ("core", "0002_initial_data"),
    ]
    operations = [migrations.RunPython(seed, unseed)]
