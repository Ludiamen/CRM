"""T-6123: журнал списков — четырнадцать действий, исполнитель, «было / стало», типы объектов, набор ключей, подписи,
отсутствие значений полей записей, только дописывание (FR-542, NFR-508). Сценарии 1, 2, 3, 4, 5, 6, 9, 14 спеки среза 006.

Каждое действие совершает настоящая служба `lists`; запись читается из `core.AuditEvent` (раздел 8.1 контракта):
код, `object_type`, `object_id`, исполнитель, `before` и `after`. Код среза на уровне модуля не импортируется: имена
берутся внутри тестов (CONTRACT-006, шапка).
"""
import ast
import json
import re
from pathlib import Path

import pytest
from django.db import ProgrammingError, connection, transaction

from tests import factories, support
from tests import support_lists as lp
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

CODES = (
    "lists.list_created", "lists.list_changed", "lists.list_deleted", "lists.access_changed",
    "lists.field_created", "lists.field_changed", "lists.field_hidden", "lists.field_shown",
    "lists.field_deleted", "lists.choices_changed", "lists.record_archived", "lists.record_restored",
    "lists.record_purged", "lists.import_done",
)
# набор ключей плана («Журнал»); `url`, `link`, `key`, `code` в нём нет
ALLOWED = {
    "list", "name", "description", "field", "type", "required", "multiple", "unique", "show_in_table", "hidden",
    "default", "hint", "currency", "target", "thresholds", "choices", "readers", "editors", "number", "title",
    "created", "updated", "errors", "file",
}
FORBIDDEN = {"url", "link", "key", "code"}
_FIELD_PROPS = {"field", "type", "required", "multiple", "unique", "show_in_table", "default", "hint", "currency",
                "target", "thresholds"}
# ключи `before` и `after` по действиям (раздел 8.1): допустимое множество каждого действия
ALLOWED_BY_ACTION = {
    "lists.list_created": {"name", "description"},
    "lists.list_changed": {"name", "description"},
    "lists.list_deleted": {"name"},
    "lists.access_changed": {"list", "readers", "editors"},
    "lists.field_created": {"list"} | _FIELD_PROPS,
    "lists.field_changed": {"list"} | _FIELD_PROPS,
    "lists.field_hidden": {"list", "field", "hidden"},
    "lists.field_shown": {"list", "field", "hidden"},
    "lists.field_deleted": {"list", "field", "type"},
    "lists.choices_changed": {"list", "field", "choices"},
    "lists.record_archived": {"list", "number", "title"},
    "lists.record_restored": {"list", "number", "title"},
    "lists.record_purged": {"list", "number", "title"},
    "lists.import_done": {"list", "file", "created", "updated", "errors"},
}
OBJECT_TYPE_OF_ACTION = {
    "lists.list_created": "lists.list", "lists.list_changed": "lists.list", "lists.list_deleted": "lists.list",
    "lists.access_changed": "lists.list",
    "lists.field_created": "lists.field", "lists.field_changed": "lists.field", "lists.field_hidden": "lists.field",
    "lists.field_shown": "lists.field", "lists.field_deleted": "lists.field", "lists.choices_changed": "lists.field",
    "lists.record_archived": "lists.record", "lists.record_restored": "lists.record",
    "lists.record_purged": "lists.record", "lists.import_done": "lists.import",
}
# подписи раздела 8.2
ACTION_TITLES = {
    "lists.list_created": "Создан список", "lists.list_changed": "Изменён список",
    "lists.list_deleted": "Удалён список", "lists.access_changed": "Изменены права списка",
    "lists.field_created": "Добавлено поле списка", "lists.field_changed": "Изменено поле списка",
    "lists.field_hidden": "Скрыто поле списка", "lists.field_shown": "Показано поле списка",
    "lists.field_deleted": "Удалено поле списка", "lists.choices_changed": "Изменены значения поля списка",
    "lists.record_archived": "Запись перенесена в архив", "lists.record_restored": "Запись возвращена из архива",
    "lists.record_purged": "Запись удалена навсегда", "lists.import_done": "Загрузка в список",
}
OBJECT_TITLES = {
    "lists.list": "список", "lists.field": "поле списка", "lists.record": "запись списка",
    "lists.import": "загрузка в список",
}
FIELD_TITLES = {
    "name": "название", "description": "описание", "number": "номер", "title": "заголовок", "created": "создано",
    "updated": "обновлено", "errors": "с ошибками",
    "list": "список", "field": "поле", "type": "тип", "required": "обязательное", "multiple": "несколько значений",
    "unique": "уникальное", "show_in_table": "показывать в таблице", "hidden": "скрыто",
    "default": "значение по умолчанию", "hint": "подсказка", "currency": "валюта", "target": "целевой список",
    "thresholds": "пороги срока", "choices": "значения", "readers": "читают", "editors": "правят", "file": "файл",
}

VALUE_MARK = "уникальная-метка-значения-поля-записи"
LONG_MARK = "уникальная-метка-многострочного-текста"
IMPORT_NAME = "загрузка-журнала.xlsx"


# --- помощники только этого файла ------------------------------------------------------------------------

def _events(action: str, object_id=None) -> list:
    query = model("core.AuditEvent").objects.filter(action=action)
    if object_id is not None:
        query = query.filter(object_id=str(object_id))
    return list(query.order_by("id"))


def _one(action: str, object_id=None):
    found = _events(action, object_id)
    assert len(found) == 1, f"{action}: записей {len(found)}, ожидалась одна"
    return found[0]


def _all_lists_events() -> list:
    return list(model("core.AuditEvent").objects.filter(action__startswith="lists.").order_by("id"))


def _payload(event) -> dict:
    """Объединение «было» и «стало» (у ключей, записанных с обеих сторон, побеждает «стало»)."""
    return {**event.before, **event.after}


def _written_names(events) -> set:
    names: set = set()
    for event in events:
        names |= set(event.before) | set(event.after)
    return names


def _everything() -> dict:
    """Совершает по настоящей службе все четырнадцать действий; возвращает участников и объекты."""
    from apps.lists.services import archive, imports, schema

    manager = lp.as_manager()
    lst = schema.create_list(name="Склад журнала", description="Первое описание", actor=manager.user)
    schema.update_list(lst, name="Склад переименованный", description="Первое описание", actor=manager.user)
    lst.refresh_from_db()
    schema.update_list(lst, name=lst.name, description="Второе описание", actor=manager.user)
    lst.refresh_from_db()
    editor = lp.as_editor(lst)

    old_reader = factories.make_role(name="Старая")
    lp.grant_list(lst, old_reader, "read")
    apple, melon = factories.make_role(name="Яблоко"), factories.make_role(name="Арбуз")
    unit = org.make_unit("Бухгалтерия журнала")
    schema.save_access(lst, readers=[("role", apple.pk), ("role", melon.pk), ("unit", unit.pk)],
                       editors=[("role", melon.pk)], actor=manager.user)
    schema.save_access(lst, readers=[("role", apple.pk)], editors=[("role", melon.pk), ("unit", unit.pk)],
                       actor=manager.user)

    other = lp.make_list("Список-цель журнала")
    linked = schema.add_field(lst, name="Связь", type="record", target=other, required=True, hint="Подсказка",
                              actor=manager.user)
    plain = schema.add_field(lst, name="Старое имя", type="string", actor=manager.user)
    schema.update_field(plain, actor=manager.user, name="Новое имя", hint="Новая подсказка", type="number")
    text_field = lp.add_field(lst, "string", "Текст журнала")
    long_field = lp.add_field(lst, "text", "Многострочный журнала")
    schema.hide_field(text_field, actor=manager.user)
    schema.show_field(text_field, actor=manager.user)
    doomed = lp.add_field(lst, "string", "Лишнее поле")
    doomed_pk = doomed.pk
    schema.delete_field(doomed, actor=manager.user)

    choice_field = lp.add_field(lst, "choice", "Вид журнала", choices=("Бета", "Альфа", "Гамма"))
    beta, alpha, gamma = (lp.choice_id(choice_field, name) for name in ("Бета", "Альфа", "Гамма"))
    first = lp.make_record(lst, "Запись журнала", {
        text_field.code: VALUE_MARK, long_field.code: LONG_MARK, choice_field.code: [gamma]}, created_by=editor.user)
    purged = lp.make_record(lst, "Запись на удаление", {text_field.code: VALUE_MARK}, created_by=editor.user,
                            archived=True)
    schema.save_choices(choice_field, [(beta, "Бета"), (None, "Дельта"), (alpha, "Альфа")], actor=manager.user)

    archive.archive(lst, first.number, actor=editor.user)
    archive.restore(lst, first.number, actor=editor.user)
    archive.purge(lst, purged.number, actor=manager.user)

    empty = schema.create_list(name="Список под удаление", description="", actor=manager.user)
    empty_pk = empty.pk
    schema.delete_list(empty, actor=manager.user)

    counted = lp.make_list("Список загрузки журнала")
    count_field = lp.add_field(counted, "number", "Количество")
    job = imports.upload(counted, manager.user, name=IMPORT_NAME, content=lp.xlsx_of(
        ["Название", "Количество"], [["Первая", "1"], ["Вторая", "2"], ["Третья", "не число"]]))
    imports.preview(job, {"0": "title", "1": count_field.code}, manager.user)
    result = imports.confirm(counted, job.pk, manager.user)
    return {"manager": manager, "editor": editor, "list": lst, "empty_pk": empty_pk, "other": other,
            "linked": linked, "plain": plain, "text_field": text_field, "doomed_pk": doomed_pk,
            "choice_field": choice_field, "first": first, "purged": purged, "job": job, "result": result,
            "counted": counted, "unit": unit, "ids": {"beta": beta, "alpha": alpha, "gamma": gamma}}


# --- действия над списком и правами -----------------------------------------------------------------------

def test_list_create_rename_and_description_change_write_list_actions_with_actor_before_after():
    """FR-542: создание — `lists.list_created` (`after`: название и описание, `before` пуст); переименование — запись
    `lists.list_changed` с одним ключом `name` «было / стало»; смена описания — отдельная запись только с `description`;
    исполнитель — тот, кто изменил; объект — `lists.list` с id списка."""
    from apps.lists.services import schema

    manager = lp.as_manager()
    lst = schema.create_list(name="Склад журнала", description="Первое описание", actor=manager.user)
    created = _one("lists.list_created", lst.pk)
    assert created.actor == manager.user
    assert created.object_type == "lists.list" and created.object_id == str(lst.pk)
    assert created.before == {}
    assert created.after == {"name": "Склад журнала", "description": "Первое описание"}

    schema.update_list(lst, name="Склад переименованный", description="Первое описание", actor=manager.user)
    lst.refresh_from_db()
    schema.update_list(lst, name="Склад переименованный", description="Второе описание", actor=manager.user)
    changes = _events("lists.list_changed", lst.pk)
    assert len(changes) == 2, "две правки — две записи"
    renamed, described = changes
    for event in changes:
        assert event.actor == manager.user
        assert event.object_type == "lists.list" and event.object_id == str(lst.pk)
    assert renamed.before == {"name": "Склад журнала"} and renamed.after == {"name": "Склад переименованный"}
    assert described.before == {"description": "Первое описание"}
    assert described.after == {"description": "Второе описание"}


def test_deleting_empty_list_writes_list_deleted_with_name():
    """FR-542: удаление пустого списка — `lists.list_deleted`: исполнитель, объект `lists.list` с прежним id,
    `before` — только название, `after` пуст."""
    from apps.lists.services import schema

    manager = lp.as_manager()
    lst = schema.create_list(name="Список под удаление", description="", actor=manager.user)
    pk = lst.pk
    schema.delete_list(lst, actor=manager.user)
    event = _one("lists.list_deleted", pk)
    assert event.actor == manager.user
    assert event.object_type == "lists.list" and event.object_id == str(pk)
    assert event.before == {"name": "Список под удаление"}
    assert event.after == {}


def test_access_change_writes_readers_and_editors_role_and_unit_names_before_after():
    """FR-542: изменение прав — `lists.access_changed`: «читают» и «правят» — названия ролей и подразделений через
    «, » по алфавиту; `before` второй записи равен `after` первой; в `before` первой — прежний набор «читают»;
    пустой набор — пустая строка; название списка есть в записи."""
    from apps.lists.services import schema

    manager = lp.as_manager()
    lst = lp.make_list("Список прав журнала")
    lp.grant_list(lst, factories.make_role(name="Старая"), "read")
    apple, melon = factories.make_role(name="Яблоко"), factories.make_role(name="Арбуз")
    unit = org.make_unit("Бухгалтерия журнала")
    schema.save_access(lst, readers=[("role", apple.pk), ("role", melon.pk), ("unit", unit.pk)],
                       editors=[("role", melon.pk)], actor=manager.user)
    schema.save_access(lst, readers=[("role", apple.pk)], editors=[("role", melon.pk), ("unit", unit.pk)],
                       actor=manager.user)
    schema.save_access(lst, readers=[], editors=[], actor=manager.user)
    first, second, third = _events("lists.access_changed", lst.pk)
    for event in (first, second, third):
        assert event.actor == manager.user
        assert event.object_type == "lists.list" and event.object_id == str(lst.pk)
        assert _payload(event)["list"] == lst.name
        assert set(event.before) | set(event.after) <= {"list", "readers", "editors"}
    assert first.before["readers"] == "Старая"
    assert first.after["readers"] == "Арбуз, Бухгалтерия журнала, Яблоко"
    assert first.after["editors"] == "Арбуз"
    assert second.before["readers"] == first.after["readers"] and second.before["editors"] == first.after["editors"]
    assert second.after["readers"] == "Яблоко"
    assert second.after["editors"] == "Арбуз, Бухгалтерия журнала"
    # пустой набор — пустая строка `""` (раздел 8.2, К-12)
    assert third.before["readers"] == "Яблоко" and third.after["readers"] == ""
    assert third.before["editors"] == "Арбуз, Бухгалтерия журнала" and third.after["editors"] == ""


# --- действия над полем -----------------------------------------------------------------------------------

def test_field_create_change_hide_show_delete_write_five_field_actions_with_before_after():
    """FR-542: добавление поля — `lists.field_created` (список, название поля, подпись типа, заданные свойства, название
    целевого списка); изменение — `lists.field_changed` с «было / стало» названия, типа и подсказки без неизменённых
    свойств; скрытие и показ — `lists.field_hidden` и `lists.field_shown` с признаком `hidden`; удаление —
    `lists.field_deleted` с `before` из списка, названия и типа; объект — `lists.field` с id поля."""
    from apps.lists.services import schema

    manager = lp.as_manager()
    lst = lp.make_list("Список полей журнала")
    other = lp.make_list("Список-цель журнала")

    linked = schema.add_field(lst, name="Связь", type="record", target=other, required=True, hint="Подсказка",
                              actor=manager.user)
    created = _one("lists.field_created", linked.pk)
    assert created.actor == manager.user
    assert created.object_type == "lists.field" and created.object_id == str(linked.pk)
    assert created.before == {}
    assert set(created.after) <= ALLOWED_BY_ACTION["lists.field_created"]
    assert {"list", "field", "type", "required", "hint", "target"} <= set(created.after)
    assert created.after["list"] == lst.name and created.after["field"] == "Связь"
    assert created.after["type"] == "Запись другого списка"
    assert created.after["hint"] == "Подсказка" and created.after["target"] == other.name
    assert not set(created.after) & {"currency", "thresholds", "default"}

    plain = schema.add_field(lst, name="Старое имя", type="string", actor=manager.user)
    schema.update_field(plain, actor=manager.user, name="Новое имя", hint="Новая подсказка", type="number")
    changed = _one("lists.field_changed", plain.pk)
    assert changed.actor == manager.user
    assert changed.object_type == "lists.field" and changed.object_id == str(plain.pk)
    assert changed.before["field"] == "Старое имя" and changed.after["field"] == "Новое имя"
    assert changed.before["type"] == "Строка" and changed.after["type"] == "Число"
    assert changed.after["hint"] == "Новая подсказка"
    assert _payload(changed)["list"] == lst.name
    assert not _written_names([changed]) & {"required", "multiple", "unique", "show_in_table"}

    hidable = lp.add_field(lst, "string", "Скрываемое поле")
    schema.hide_field(hidable, actor=manager.user)
    schema.show_field(hidable, actor=manager.user)
    hidden = _one("lists.field_hidden", hidable.pk)
    shown = _one("lists.field_shown", hidable.pk)
    for event in (hidden, shown):
        assert event.actor == manager.user
        assert event.object_type == "lists.field" and event.object_id == str(hidable.pk)
        assert set(event.before) | set(event.after) <= {"list", "field", "hidden"}
        assert _payload(event)["list"] == lst.name and _payload(event)["field"] == "Скрываемое поле"
    assert _payload(hidden)["hidden"] is True
    assert _payload(shown)["hidden"] is False

    doomed = lp.add_field(lst, "string", "Лишнее поле")
    pk = doomed.pk
    schema.delete_field(doomed, actor=manager.user)
    deleted = _one("lists.field_deleted", pk)
    assert deleted.actor == manager.user
    assert deleted.object_type == "lists.field" and deleted.object_id == str(pk)
    assert deleted.before == {"list": lst.name, "field": "Лишнее поле", "type": "Строка"}
    assert deleted.after == {}


def test_choices_change_writes_choices_changed_with_before_after():
    """FR-542: изменение значений поля — `lists.choices_changed`: `before` и `after` — названия значений не в архиве по
    порядку через «, »; значение, использованное в записи и убранное из списка, в `after` не попадает (оно в архиве);
    список и название поля есть в записи."""
    from apps.lists.services import schema

    manager = lp.as_manager()
    lst = lp.make_list("Список значений журнала")
    field = lp.add_field(lst, "choice", "Вид журнала", choices=("Бета", "Альфа", "Гамма"))
    beta, alpha, gamma = (lp.choice_id(field, name) for name in ("Бета", "Альфа", "Гамма"))
    lp.make_record(lst, "Запись со значением", {field.code: [gamma]}, created_by=manager.user)

    schema.save_choices(field, [(beta, "Бета"), (None, "Дельта"), (alpha, "Альфа")], actor=manager.user)
    event = _one("lists.choices_changed", field.pk)
    assert event.actor == manager.user
    assert event.object_type == "lists.field" and event.object_id == str(field.pk)
    assert event.before["choices"] == "Бета, Альфа, Гамма"
    assert event.after["choices"] == "Бета, Дельта, Альфа"
    assert _payload(event)["list"] == lst.name and _payload(event)["field"] == "Вид журнала"
    assert set(event.before) | set(event.after) <= {"list", "field", "choices"}
    assert model("lists.Choice").objects.get(pk=gamma).archived is True, "использованное значение уходит в архив"


# --- действия над записью и загрузкой ---------------------------------------------------------------------

def test_record_archive_restore_purge_write_actions_with_number_and_title_only():
    """FR-542: «В архив», «Вернуть», «Удалить навсегда» — по записи журнала; в записи только список, номер и название
    (без значений полей); исполнитель — тот, кто действовал; объект — `lists.record` с id записи."""
    from apps.lists.services import archive

    lst = lp.make_list("Список записей журнала")
    text_field = lp.add_field(lst, "string", "Текст журнала")
    editor, manager = lp.as_editor(lst), lp.as_manager()
    record = lp.make_record(lst, "Запись журнала", {text_field.code: VALUE_MARK}, created_by=editor.user)
    doomed = lp.make_record(lst, "Запись на удаление", {text_field.code: VALUE_MARK}, created_by=editor.user,
                            archived=True)
    record_pk, doomed_pk = record.pk, doomed.pk

    archive.archive(lst, record.number, actor=editor.user)
    archive.restore(lst, record.number, actor=editor.user)
    archive.purge(lst, doomed.number, actor=manager.user)

    # Р4, К-12: у `record_archived` и `record_restored` ключи — в `after`, у `record_purged` — в `before`
    cases = (("lists.record_archived", record_pk, record, editor.user, "after"),
             ("lists.record_restored", record_pk, record, editor.user, "after"),
             ("lists.record_purged", doomed_pk, doomed, manager.user, "before"))
    for action, pk, row, actor, side in cases:
        event = _one(action, pk)
        assert event.actor == actor, action
        assert event.object_type == "lists.record" and event.object_id == str(pk), action
        assert set(event.before) | set(event.after) == {"list", "number", "title"}, action
        body = getattr(event, side)
        assert set(body) == {"list", "number", "title"}, action
        assert body["list"] == lst.name and int(body["number"]) == row.number and body["title"] == row.title, action
        assert VALUE_MARK not in json.dumps([event.before, event.after], ensure_ascii=False), action


def test_import_confirm_writes_import_done_with_counts_and_file_name():
    """FR-542: подтверждение загрузки из таблицы — одна запись `lists.import_done`: объект `lists.import` с id задания,
    в `after` список, имя файла и числа «создано», «обновлено», «с ошибками» (2, 0, 1); повторное подтверждение
    второй записи не добавляет."""
    from apps.lists.services import imports

    manager = lp.as_manager()
    lst = lp.make_list("Список загрузки журнала")
    count_field = lp.add_field(lst, "number", "Количество")
    job = imports.upload(lst, manager.user, name=IMPORT_NAME, content=lp.xlsx_of(
        ["Название", "Количество"], [["Первая", "1"], ["Вторая", "2"], ["Третья", "не число"]]))
    imports.preview(job, {"0": "title", "1": count_field.code}, manager.user)
    result = imports.confirm(lst, job.pk, manager.user)
    assert result == {"created": 2, "updated": 0, "errors": 1}
    event = _one("lists.import_done", job.pk)
    assert event.actor == manager.user
    assert event.object_type == "lists.import" and event.object_id == str(job.pk)
    assert event.before == {}
    assert set(event.after) == {"list", "file", "created", "updated", "errors"}
    assert event.after["list"] == lst.name and event.after["file"] == IMPORT_NAME
    assert (int(event.after["created"]), int(event.after["updated"]), int(event.after["errors"])) == (2, 0, 1)

    assert imports.confirm(lst, job.pk, manager.user) == result
    assert len(_events("lists.import_done", job.pk)) == 1, "повтор подтверждения не пишет в журнал"


# --- состав записей ---------------------------------------------------------------------------------------

def test_audit_object_types_are_lists_list_field_record_import():
    """FR-542: после всех четырнадцати действий тип объекта каждой записи — один из `lists.list`, `lists.field`,
    `lists.record`, `lists.import` и соответствует действию (раздел 8.1); `object_id` — число в виде строки."""
    _everything()
    events = _all_lists_events()
    assert {event.action for event in events} == set(CODES), "не все четырнадцать действий записаны"
    for event in events:
        assert event.object_type == OBJECT_TYPE_OF_ACTION[event.action], event.action
        assert event.object_id.isdigit(), (event.action, event.object_id)
    assert {event.object_type for event in events} == set(OBJECT_TITLES)


def test_audit_before_after_keys_are_from_plan_set_without_url_link_key_code():
    """FR-542: ключи `before` и `after` — только из набора плана и из допустимого набора своего действия (раздел 8.1);
    ключей `url`, `link`, `key`, `code` нет; ядро не скрыло ни одного значения (`***`)."""
    _everything()
    events = _all_lists_events()
    assert {event.action for event in events} == set(CODES), "не все четырнадцать действий записаны"
    seen: set = set()
    for event in events:
        for side in (event.before, event.after):
            seen |= set(side)
            assert set(side) <= ALLOWED_BY_ACTION[event.action], (event.action, sorted(side))
            for value in side.values():
                assert value != "***", event.action
    assert seen <= ALLOWED and seen, seen
    assert not seen & FORBIDDEN, seen & FORBIDDEN


def test_audit_records_have_no_record_field_values():
    """FR-542: в записях журнала нет значений полей записей (строки, многострочного текста) и нет ключей значений;
    у записей — только номер и название."""
    _everything()
    events = _all_lists_events()
    assert len(events) >= len(CODES)
    dump = json.dumps([[event.object_type, event.object_id, event.before, event.after] for event in events],
                      ensure_ascii=False)
    for marker in (VALUE_MARK, LONG_MARK):
        assert marker not in dump, marker
    for event in events:
        for side in (event.before, event.after):
            assert not set(side) & {"values", "value", "text", "cells", "rows", "html"}, event.action


def test_record_edit_file_ticket_link_export_label_and_search_write_no_audit(
        protected_root, monkeypatch, django_capture_on_commit_callbacks):
    """FR-542: создание и правка записи, прикрепление и удаление файла, привязка и отвязка заявки, выгрузка, этикетка
    и поиск не добавляют записей `lists.*` в журнал."""
    from apps.lists.services import files, records, tickets

    lp.scan_clean(monkeypatch)
    lst = lp.make_list("Список без записей журнала")
    text_field = lp.add_field(lst, "string", "Текст журнала")
    file_field = lp.add_field(lst, "file", "Файлы журнала", multiple=True)
    editor = lp.as_editor(lst)
    queue = sd.make_queue()
    org.make_member(editor.user, queue.unit)
    ticket = sd.make_ticket(queue=queue)
    before = [event.pk for event in _all_lists_events()]

    created = records.create(lst, {"title": "Запись для проверки", text_field.code: VALUE_MARK}, editor.user)
    saved = records.save(lst, created.number, {"title": "Запись после правки", text_field.code: "другое значение"},
                         base_version=created.version, actor=editor.user)
    assert saved.changed is True, "правка должна сохраниться"
    with django_capture_on_commit_callbacks(execute=True):
        attached = files.attach(lst, created.number, field_code=file_field.code, name="акт.pdf",
                                data=b"%PDF-1.4\n% test body\n", actor=editor.user)
    with django_capture_on_commit_callbacks(execute=True):
        files.remove(lst, created.number, attached.pk, actor=editor.user)
    link = tickets.link(editor.user, ticket.number, created.pk)
    tickets.unlink(editor.user, link.pk)
    assert editor.client.get(f"/lists/{lst.pk}/export/").status_code == 200
    assert editor.client.get(f"/lists/{lst.pk}/{created.number}/label/").status_code == 200
    assert editor.client.get("/search/", {"q": "запись"}).status_code == 200

    assert [event.pk for event in _all_lists_events()] == before


# --- подписи ----------------------------------------------------------------------------------------------

def test_audit_labels_cover_every_action_object_type_and_written_key():
    """FR-542: точка `audit_labels` среза даёт подписи четырнадцати действий, четырёх видов объекта и двадцати четырёх
    ключей раздела 8.2; подписи общих ключей (`name`, `description`, `number`, `title`, `created`, `updated`, `errors`)
    — прежние слова прежних модулей; словарь значений пуст; ядро после слияния отдаёт те же слова; у каждого
    записанного настоящими действиями ключа подпись есть."""
    from apps.core.services import audit_labels as core_labels
    from apps.core.services import audit_search
    from apps.lists import audit_labels as own

    data = own.audit_labels()
    assert set(data) == {"actions", "fields", "object_types", "values"}
    assert data["actions"] == ACTION_TITLES
    assert data["object_types"] == OBJECT_TITLES
    assert {name: data["fields"].get(name) for name in FIELD_TITLES} == FIELD_TITLES
    assert data["values"] == {}
    cyrillic = re.compile("[а-яА-ЯёЁ]")
    for title in list(data["actions"].values()) + list(data["fields"].values()) + list(data["object_types"].values()):
        assert cyrillic.search(title), title

    titles = dict(audit_search.known_actions())
    for action, title in ACTION_TITLES.items():
        assert titles.get(action) == title, action
    for kind, title in OBJECT_TITLES.items():
        assert core_labels.object_title(kind) == title, kind
    for name, title in FIELD_TITLES.items():
        assert core_labels.label(name) == title, name

    _everything()
    written = _written_names(_all_lists_events())
    assert written, "действия ничего не записали"
    for name in written:
        assert data["fields"].get(name), f"нет подписи ключа {name}"
        assert core_labels.label(name) == data["fields"][name], name


# --- только дописывание -----------------------------------------------------------------------------------

def test_app_role_cannot_update_or_delete_audit_rows():
    """NFR-508: у роли приложения нет UPDATE, DELETE, TRUNCATE на журнал; правка и удаление записей `lists.*` отвергаются
    базой, строки остаются прежними."""
    Event = model("core.AuditEvent")
    _everything()
    ids = sorted(event.pk for event in _all_lists_events())
    assert ids
    columns = ("id", "action", "object_type", "object_id", "before", "after", "actor_id")
    snapshot = list(Event.objects.filter(id__in=ids).order_by("id").values_list(*columns))
    codes = list(CODES)

    with connection.cursor() as cur:
        cur.execute("SELECT has_table_privilege('crm_app', 'core_auditevent', 'UPDATE'), "
                    "has_table_privilege('crm_app', 'core_auditevent', 'DELETE'), "
                    "has_table_privilege('crm_app', 'core_auditevent', 'TRUNCATE')")
        assert cur.fetchone() == (False, False, False)
    with pytest.raises(ProgrammingError), transaction.atomic():
        Event.objects.filter(action__in=codes).update(action="tampered")
    with pytest.raises(ProgrammingError), transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("DELETE FROM core_auditevent WHERE action = ANY(%s)", [codes])
    assert list(Event.objects.filter(id__in=ids).order_by("id").values_list(*columns)) == snapshot


def test_no_lists_cron_entry_or_task_deletes_audit_rows(django_capture_on_commit_callbacks):
    """NFR-508: ночной обход сроков (запись `lists_reminders` расписания) журнал не трогает; в расписании
    `config/cron.py` нет задания, чистящего журнал; код `lists` не правит и не удаляет `AuditEvent`."""
    from apps.core.widgets import moscow_today

    Event = model("core.AuditEvent")
    _everything()
    ids = sorted(event.pk for event in _all_lists_events())
    assert ids
    columns = ("id", "action", "object_type", "object_id", "before", "after", "actor_id")
    snapshot = list(Event.objects.filter(id__in=ids).order_by("id").values_list(*columns))
    with django_capture_on_commit_callbacks(execute=True):
        lp.run_reminders(moscow_today())
    assert list(Event.objects.filter(id__in=ids).order_by("id").values_list(*columns)) == snapshot

    cron = ast.parse((support.BACKEND_DIR / "config" / "cron.py").read_text(encoding="utf-8"))
    registered = []
    for node in ast.walk(cron):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "register":
            names = [kw.value.value for kw in node.keywords if kw.arg == "name" and isinstance(kw.value, ast.Constant)]
            registered += names + [a.id for a in node.args if isinstance(a, ast.Name)]
    assert registered, "в расписании нет ни одного задания"
    assert "lists_reminders" in registered, "в расписании нет записи lists_reminders"
    assert not [name for name in registered if "audit" in name.lower()], registered

    sources = [p for p in Path(support.BACKEND_DIR / "apps" / "lists").rglob("*.py") if "migrations" not in p.parts]
    assert sources, "нет кода apps/lists"
    for path in sources:
        for line in path.read_text(encoding="utf-8").splitlines():
            assert not (re.search(r"auditevent", line, re.I)
                        and re.search(r"\.delete\(|_raw_delete|truncate|\.update\(", line, re.I)), (
                f"{path}: правка журнала: {line.strip()}")
