"""T-6105: данные установки среза 006 — миграция данных `lists 0002` (право `lists.manage`, шесть стартовых списков,
поля, строки `Access`, `unseed`) и пустая главная (FR-501, FR-503, FR-505, FR-512, FR-513, FR-545). Сценарии 1 и 13
(п. 1 «после обновления») спеки.

Вызовы идут на соединении `default` (`run_seed(using="default")`): тестовая база уже мигрирована, поэтому каждый тест
сначала возвращает её к виду «до миграции данных» через `support_lists.clear_seed()`.
"""
import pytest

from tests import support
from tests import support_lists as ls

pytestmark = pytest.mark.django_db

IT_ROLE = "Сотрудник ИТ"
CHIEF_ROLE = "Руководитель"
ADMIN_ROLE = "Администратор портала"

HINT = "Ключи активации здесь не храните: секреты хранятся вне портала"
EMPTY_TEXT = "Списков пока нет. Список — это ваш реестр: оборудование, лицензии, договоры. Создайте первый"

# Раздел 2.4 контракта: код списка -> (название, [(код поля, название, тип, признаки)]).
# Признаки: unique, multiple, thresholds, target, choices, currency.
SEED = {
    "equipment": ("Оборудование", [
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
    "licenses": ("Лицензии", [
        ("product", "Продукт", "string", {}),
        ("kind", "Вид", "choice", {"choices": ["Бессрочная", "Подписка"]}),
        ("seats", "Количество мест", "number", {}),
        ("license_number", "Номер лицензии или договора", "string", {}),
        ("valid_until", "Действует до", "date", {"thresholds": [30, 7]}),
        ("installed_on", "Установлена на", "record", {"target": "equipment", "multiple": True}),
        ("owner", "Ответственный", "person", {}),
        ("cost", "Стоимость", "money", {"currency": "RUB"}),
        ("files", "Файлы", "file", {"multiple": True}),
    ]),
    "consumables": ("Картриджи и расходники", [
        ("kind", "Вид", "choice", {"choices": ["Картридж", "Тонер", "Барабан", "Прочее"]}),
        ("model", "Модель", "string", {}),
        ("printers", "Для принтера", "record", {"target": "equipment", "multiple": True}),
        ("stock", "Количество на складе", "number", {}),
        ("note", "Примечание", "text", {}),
    ]),
    "signatures": ("Сертификаты ЭП", [
        ("holder", "Владелец", "person", {}),
        ("issuer", "Удостоверяющий центр", "string", {}),
        ("serial_number", "Серийный номер", "string", {"unique": True}),
        ("medium", "Носитель", "choice", {"choices": ["Токен", "Реестр", "Облако"]}),
        ("valid_until", "Действует до", "date", {"thresholds": [30, 7]}),
        ("files", "Файлы", "file", {"multiple": True}),
    ]),
    "contracts": ("Договоры", [
        ("counterparty", "Контрагент", "string", {}),
        ("contract_number", "Номер договора", "string", {"unique": True}),
        ("subject", "Предмет", "text", {}),
        ("signed", "Дата заключения", "date", {}),
        ("valid_until", "Действует до", "date", {"thresholds": [30]}),
        ("amount", "Сумма", "money", {"currency": "RUB"}),
        ("owner", "Ответственный", "person", {}),
        ("files", "Файлы", "file", {"multiple": True}),
    ]),
    "sims": ("SIM-карты и телефоны", [
        ("phone", "Номер телефона", "string", {"unique": True}),
        ("operator", "Оператор", "choice", {"choices": []}),
        ("tariff", "Тариф", "string", {}),
        ("assignee", "За кем закреплено", "person", {}),
        ("device", "Устройство", "record", {"target": "equipment"}),
        ("iccid", "ICCID", "string", {}),
        ("note", "Примечание", "text", {}),
    ]),
}

# «Показывать в таблице» (решение 52 задач, раздел 2.4): первые четыре поля после «Названия», кроме text и file
SHOW_IN_TABLE = {
    "equipment": {"kind", "inventory_number", "serial_number", "model"},
    "licenses": {"product", "kind", "seats", "license_number"},
    "consumables": {"kind", "model", "printers", "stock"},
    "signatures": {"holder", "issuer", "serial_number", "medium"},
    "contracts": {"counterparty", "contract_number", "signed", "valid_until"},
    "sims": {"phone", "operator", "tariff", "assignee"},
}


def _model(label: str):
    return support.model(label)


def _role(name: str):
    return _model("core.Role").objects.get(name=name, is_builtin=True)


def _codes(role) -> set:
    return set(role.permissions.values_list("code", flat=True))


def _start() -> None:
    """«До миграции данных»: стартовых данных нет, права `lists.manage` нет."""
    ls.clear_seed()
    assert not _model("core.Permission").objects.filter(code__in=ls.PERMISSIONS_006).exists()
    assert not _model("lists.List").objects.filter(code__in=list(SEED)).exists()


def _seeded() -> None:
    _start()
    ls.run_seed(using="default")


def _lst(code: str):
    return _model("lists.List").objects.get(code=code)


def _fields(code: str) -> dict:
    return {f.code: f for f in _model("lists.Field").objects.filter(list__code=code)}


# --- право ----------------------------------------------------------------------------------------------------

def test_seed_on_slice_005_base_creates_lists_manage_and_grants_it_to_admin_role_only():
    """FR-512, FR-545: на базе среза 005 `seed` создаёт право «Управление списками» и выдаёт его только встроенной
    роли «Администратор портала»; «Сотрудник ИТ», «Руководитель» и пользовательская роль права не получают."""
    _start()
    custom = support.model("core.Role").objects.create(name="Своя роль без прав", is_builtin=False)
    names = (ADMIN_ROLE, IT_ROLE, CHIEF_ROLE)
    before = {name: _codes(_role(name)) for name in names}
    assert not any("lists.manage" in codes for codes in before.values())
    ls.run_seed(using="default")
    Permission = _model("core.Permission")
    assert Permission.objects.get(code="lists.manage").title == "Управление списками"
    assert _codes(_role(ADMIN_ROLE)) == before[ADMIN_ROLE] | {"lists.manage"}
    assert _codes(_role(IT_ROLE)) == before[IT_ROLE]
    assert _codes(_role(CHIEF_ROLE)) == before[CHIEF_ROLE]
    assert _codes(custom) == set()
    holders = _model("core.Role").objects.filter(permissions__code="lists.manage")
    assert [r.name for r in holders] == [ADMIN_ROLE]


def test_seed_adds_lists_manage_to_existing_admin_role_and_keeps_its_prior_rights():
    """FR-512, FR-545: при обновлении портала администратор уже существует с набором прав: `seed` добавляет
    `lists.manage` (`add`, не `set`), все прежние права роли остаются, чужие названия прав не перезаписываются."""
    _start()
    admin = _role(ADMIN_ROLE)
    prior_perm = _model("core.Permission").objects.get(code="audit.view")
    admin.permissions.add(prior_perm)
    prior = _codes(admin)
    assert "audit.view" in prior and len(prior) >= 2
    _model("core.Permission").objects.filter(code="audit.view").update(title="Свой заголовок права")
    ls.run_seed(using="default")
    after = _codes(_role(ADMIN_ROLE))
    assert after == prior | {"lists.manage"}
    assert _model("core.Permission").objects.get(code="audit.view").title == "Свой заголовок права"


def test_portal_has_sixteen_permissions_after_seed():
    """FR-512, CONTRACT-007: до `seed` в портале семнадцать прав (прежние пятнадцать и два права среза 007, которые
    `_start()` не трогает), после — восемнадцать, и новое `lists.manage` — последнее по порядку
    создания (раздел 1.4 контракта)."""
    _start()
    Permission = _model("core.Permission")
    assert Permission.objects.count() == 17
    ls.run_seed(using="default")
    assert Permission.objects.count() == 18
    assert Permission.objects.order_by("-pk").first().code == "lists.manage"


# --- списки и поля --------------------------------------------------------------------------------------------

def test_seed_creates_six_lists_with_codes_and_names_from_plan_table():
    """FR-505, FR-545: после `seed` ровно шесть списков с устойчивыми кодами и названиями из FR-505; счётчик
    `next_field_no` у каждого — 1, `next_number` — 1, описание пустое, записей нет."""
    _seeded()
    List = _model("lists.List")
    assert {lst.code: lst.name for lst in List.objects.exclude(code="")} == {code: name for code, (name, _) in SEED.items()}
    assert List.objects.count() == 6
    for lst in List.objects.all():
        assert (lst.next_field_no, lst.next_number) == (1, 1), lst.code
    assert not _model("lists.Record").objects.exists()


def test_seed_list_fields_have_codes_types_and_names_from_plan_table():
    """FR-505: у каждого стартового списка поля — те же коды, названия и типы, в порядке таблицы, `order` с 1 подряд;
    поля «Название» среди строк `Field` нет (оно системное)."""
    _seeded()
    Field = _model("lists.Field")
    for code, (_, fields) in SEED.items():
        rows = list(Field.objects.filter(list__code=code).order_by("order"))
        assert [(f.code, f.name, f.type) for f in rows] == [(c, n, t) for c, n, t, _ in fields], code
        assert [f.order for f in rows] == list(range(1, len(fields) + 1)), code
        assert not any(f.hidden or f.required for f in rows), code


def test_seed_unique_fields_and_deadline_thresholds_30_or_30_and_7():
    """FR-505: уникальны ровно перечисленные поля; срок (`settings.deadline`) и пороги — у `warranty` [30],
    `licenses.valid_until` [30, 7], `signatures.valid_until` [30, 7], `contracts.valid_until` [30]; у прочих полей срока нет."""
    _seeded()
    for code, (_, fields) in SEED.items():
        rows = _fields(code)
        for field_code, _, field_type, props in fields:
            row = rows[field_code]
            where = f"{code}.{field_code}"
            assert row.unique is bool(props.get("unique")), where
            thresholds = props.get("thresholds")
            if thresholds:
                assert row.type == "date", where
                assert row.settings.get("deadline") is True, where
                assert row.settings.get("thresholds") == thresholds, where
            else:
                assert not row.settings.get("deadline"), where
                assert not row.settings.get("thresholds"), where


def test_seed_multiple_fields_record_target_equipment_and_money_in_rubles():
    """FR-505: «несколько значений» — у файлов и у полей «Установлена на», «Для принтера»; поля типа «запись»
    ссылаются на список `equipment` (`target`), у остальных `target` пуст; деньги — в рублях (`currency` `RUB`)."""
    _seeded()
    equipment = _lst("equipment")
    for code, (_, fields) in SEED.items():
        rows = _fields(code)
        for field_code, _, field_type, props in fields:
            row = rows[field_code]
            where = f"{code}.{field_code}"
            assert row.multiple is bool(props.get("multiple")), where
            assert row.target_id == (equipment.pk if props.get("target") else None), where
            if field_type == "money":
                assert row.settings.get("currency") == "RUB", where
            else:
                assert not row.settings.get("currency"), where


def test_seed_license_number_field_has_hint_text_from_plan_table():
    """FR-505: у поля «Номер лицензии или договора» подсказка о том, что ключи активации не хранятся; ни у одного
    другого стартового поля подсказки нет."""
    _seeded()
    Field = _model("lists.Field")
    assert Field.objects.get(list__code="licenses", code="license_number").hint == HINT
    others = Field.objects.filter(list__code__in=list(SEED)).exclude(list__code="licenses", code="license_number")
    assert others.count() == sum(len(f) for _, f in SEED.values()) - 1
    assert not [f for f in others if f.hint]


def test_seed_show_in_table_on_first_four_fields_after_title_except_text_and_file():
    """FR-505: «показывать в таблице» — у первых четырёх полей после «Названия», кроме многострочного текста и
    файлов (решение 52 задач); у остальных полей признака нет."""
    _seeded()
    for code, expected in SHOW_IN_TABLE.items():
        shown = {f.code for f in _fields(code).values() if f.show_in_table}
        assert shown == expected, code
        types = {f.type for f in _fields(code).values() if f.show_in_table}
        assert not types & {"text", "file"}, code


def test_seed_choice_values_per_plan_table_and_operator_without_values():
    """FR-505: значения полей-списков — как в плане, в порядке строки, `order` с 1, не в архиве; у поля «Оператор» значений
    нет; у полей прочих типов значений списка нет."""
    _seeded()
    Choice = _model("lists.Choice")
    for code, (_, fields) in SEED.items():
        rows = _fields(code)
        for field_code, _, field_type, props in fields:
            got = list(Choice.objects.filter(field=rows[field_code]).order_by("order"))
            expected = props.get("choices", [])
            where = f"{code}.{field_code}"
            assert [c.title for c in got] == expected, where
            assert [c.order for c in got] == list(range(1, len(expected) + 1)), where
            assert not any(c.archived for c in got), where
    assert Choice.objects.filter(field__code="operator").count() == 0


# --- права на стартовые списки ----------------------------------------------------------------------------------

def test_seed_gives_it_staff_read_and_edit_access_rows_on_each_of_six_lists():
    """FR-513, FR-545: на каждом из шести списков ровно две строки `Access` — «читают» и «правят» роли «Сотрудник ИТ»;
    «Руководитель» и «Администратор портала» наборов не получают, подразделений нет."""
    _seeded()
    it_role = _role(IT_ROLE)
    Access = _model("lists.Access")
    for code in SEED:
        rows = Access.objects.filter(list__code=code)
        assert sorted((a.level, a.role_id, a.unit_id) for a in rows) == [
            ("edit", it_role.pk, None), ("read", it_role.pk, None)], code
    assert Access.objects.count() == 12


def test_seed_lists_have_empty_created_by():
    """FR-505, FR-545: у стартовых списков автор пуст (решение 34 задач): миграция данных не знает сотрудника, а
    список от этого не отличается от созданного вручную."""
    _seeded()
    lists = _model("lists.List").objects.filter(code__in=list(SEED))
    assert lists.count() == 6
    assert not [lst.code for lst in lists if lst.created_by_id is not None]


# --- повторный вызов -----------------------------------------------------------------------------------------------

def test_second_seed_call_does_not_duplicate_and_keeps_admin_renamed_list_and_field():
    """FR-545: повторный `seed` не дублирует списки, поля, значения и строки `Access` и не отменяет переименование
    списка и поля администратором."""
    _seeded()
    List, Field = _model("lists.List"), _model("lists.Field")
    Choice, Access = _model("lists.Choice"), _model("lists.Access")
    equipment = _lst("equipment")
    List.objects.filter(pk=equipment.pk).update(name="Техника офиса")
    Field.objects.filter(list=equipment, code="place").update(name="Кабинет")
    counts = (List.objects.count(), Field.objects.count(), Choice.objects.count(), Access.objects.count())
    ids = sorted(List.objects.values_list("pk", flat=True))
    ls.run_seed(using="default")
    assert (List.objects.count(), Field.objects.count(), Choice.objects.count(), Access.objects.count()) == counts
    assert sorted(List.objects.values_list("pk", flat=True)) == ids
    assert List.objects.get(code="equipment").name == "Техника офиса"
    assert Field.objects.get(list=equipment, code="place").name == "Кабинет"
    assert _model("core.Permission").objects.filter(code="lists.manage").count() == 1


def test_second_seed_call_recreates_deleted_seed_list_by_code_as_stand_reset_needs():
    """FR-545: удалённый стартовый список повторный `seed` создаёт заново по коду (сброс стенда стирает данные и
    зовёт `seed`, решение 51 задач): список, его поля, значения и две строки `Access`; остальные списки не тронуты."""
    _seeded()
    List, Field = _model("lists.List"), _model("lists.Field")
    Access = _model("lists.Access")
    old = _lst("sims")
    others = {lst.code: lst.pk for lst in List.objects.exclude(pk=old.pk)}
    Access.objects.filter(list=old).delete()
    Field.objects.filter(list=old).delete()
    old.delete()
    assert not List.objects.filter(code="sims").exists()
    ls.run_seed(using="default")
    assert List.objects.count() == 6
    new = _lst("sims")
    assert new.name == "SIM-карты и телефоны"
    assert {lst.code: lst.pk for lst in List.objects.exclude(pk=new.pk)} == others
    rows = list(Field.objects.filter(list=new).order_by("order"))
    assert [(f.code, f.type) for f in rows] == [(c, t) for c, _, t, _ in SEED["sims"][1]]
    assert sorted(a.level for a in Access.objects.filter(list=new)) == ["edit", "read"]
    assert _fields("sims")["device"].target_id == _lst("equipment").pk


def test_seed_without_it_staff_or_admin_role_passes_without_error():
    """FR-545: нет встроенных ролей «Сотрудник ИТ» и «Администратор портала» (переименованы; одноимённые
    пользовательские не встроенные) — `seed` не падает: право и списки создаются, строк `Access` нет, пользовательские
    роли ничего не получают."""
    _start()
    Role = _model("core.Role")
    Role.objects.filter(name=IT_ROLE, is_builtin=True).update(name="Сотрудник ИТ (старая)")
    Role.objects.filter(name=ADMIN_ROLE, is_builtin=True).update(name="Администратор портала (старая)")
    custom_it = Role.objects.create(name=IT_ROLE, is_builtin=False)
    custom_admin = Role.objects.create(name=ADMIN_ROLE, is_builtin=False)
    ls.run_seed(using="default")
    assert _model("core.Permission").objects.filter(code="lists.manage").count() == 1
    assert _model("lists.List").objects.filter(code__in=list(SEED)).count() == 6
    assert not _model("lists.Access").objects.exists()
    assert _codes(Role.objects.get(pk=custom_it.pk)) == set()
    assert _codes(Role.objects.get(pk=custom_admin.pk)) == set()
    assert not Role.objects.filter(permissions__code="lists.manage").exists()


# --- unseed ---------------------------------------------------------------------------------------------------------

def test_unseed_removes_lists_manage_and_seed_lists_without_records_and_keeps_lists_with_records():
    """FR-545: `unseed` снимает право `lists.manage` и его выдачу, удаляет стартовые списки без записей и оставляет без
    ошибки списки, где есть запись (в том числе только в архиве) — вместе с записями."""
    _seeded()
    author = support.make_employee()
    kept_with_record = ls.make_record(_lst("equipment"), "Ноутбук", created_by=author)
    kept_archived = ls.make_record(_lst("contracts"), "Старый договор", created_by=author, archived=True)
    ls.run_unseed(using="default")
    assert not _model("core.Permission").objects.filter(code="lists.manage").exists()
    assert not _model("core.Role").objects.filter(permissions__code="lists.manage").exists()
    assert set(_model("lists.List").objects.filter(code__in=list(SEED)).values_list("code", flat=True)) == {
        "equipment", "contracts"}
    Record = _model("lists.Record")
    assert Record.objects.get(pk=kept_with_record.pk).title == "Ноутбук"
    archived = Record.objects.get(pk=kept_archived.pk)
    assert archived.archived is True and archived.list.code == "contracts"
    assert Record.objects.count() == 2


# --- главная без стартовых данных -----------------------------------------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}
        self.parent = parent
        self.children = []

    def walk(self):
        for child in self.children:
            if isinstance(child, _Node):
                yield child
                yield from child.walk()

    def text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                if isinstance(child, _Node):
                    collect(child)
                else:
                    parts.append(child)

        collect(self)
        return " ".join("".join(parts).split())


def _tree(response):
    from html.parser import HTMLParser

    class Parser(HTMLParser):
        def __init__(self):
            super().__init__()
            self.root = _Node("#root", [], None)
            self.cur = self.root

        def handle_starttag(self, tag, attrs):
            node = _Node(tag, attrs, self.cur)
            self.cur.children.append(node)
            if tag not in _VOID:
                self.cur = node

        def handle_startendtag(self, tag, attrs):
            self.cur.children.append(_Node(tag, attrs, self.cur))

        def handle_endtag(self, tag):
            node = self.cur
            while node is not None and node.tag != tag:
                node = node.parent
            if node is not None and node.parent is not None:
                self.cur = node.parent

        def handle_data(self, data):
            self.cur.children.append(data)

    parser = Parser()
    parser.feed(response.content.decode("utf-8"))
    return parser.root


def _find(root, **attrs):
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    return [n for n in root.walk() if all(n.attrs.get(name) == value for name, value in wanted.items())]


def test_home_after_clear_seed_shows_purpose_text_and_create_list_button_to_manager():
    """FR-501, FR-503: на базе без стартовых данных (`clear_seed()`) главная `/lists/` управляющему показывает пустое
    состояние `[data-empty-state="lists"]` с текстом о назначении и кнопкой «Создать список» (`/lists/new/`), строк
    списков нет; после `seed` пустого состояния нет, управляющий видит все шесть списков."""
    _start()
    manager = ls.as_manager()
    page = manager.client.get("/lists/")
    assert page.status_code == 200
    tree = _tree(page)
    empty = _find(tree, data_empty_state="lists")
    assert len(empty) == 1
    assert EMPTY_TEXT in empty[0].text()
    buttons = [n for n in _find(tree, data_action="lists-create") if n.tag == "a"]
    assert len(buttons) == 1 and buttons[0].attrs["href"] == "/lists/new/"
    assert "Создать список" in buttons[0].text()
    assert not [n for n in tree.walk() if n.tag == "li" and "data-list-id" in n.attrs]

    ls.run_seed(using="default")
    after = _tree(manager.client.get("/lists/"))
    assert not _find(after, data_empty_state="lists")
    rows = [n for n in after.walk() if n.tag == "li" and "data-list-id" in n.attrs]
    assert sorted(n.attrs["data-list-id"] for n in rows) == sorted(
        str(pk) for pk in _model("lists.List").objects.values_list("pk", flat=True))
