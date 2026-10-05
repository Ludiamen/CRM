"""Подписи событий журнала оргструктуры (PLAN-002, «Где живёт код»; CONTRACT-002, §§ 5–6, дополнения 29, 62).

Регистрируется в точке ядра `audit_labels`; ядро сливает словари со своими (поздние побеждают) в одном месте,
общем для страницы `/audit/` и выгрузки CSV.
"""

ACTIONS = dict([
    ("unit.created", "Узел создан"), ("unit.updated", "Узел изменён"), ("unit.deleted", "Узел удалён"),
    ("unit.moved", "Узел перемещён"), ("unit.marks_changed", "Руководители и заместители узла изменены"),
    ("unit.roles_changed", "Роли узла изменены"),
    ("membership.added", "Сотрудник добавлен в узел"), ("membership.removed", "Сотрудник исключён из узла"),
    ("membership.transferred", "Сотрудник переведён между узлами"),
    ("user.dismissed", "Сотрудник уволен"), ("user.rehired", "Сотрудник возвращён"),
    ("photo.uploaded", "Фото загружено"), ("photo.checked", "Фото проверено"), ("photo.deleted", "Фото удалено"),
    ("staff_import.completed", "Загрузка сотрудников выполнена"),
    ("calendar.settings_changed", "Настройки календаря изменены"), ("calendar.year_loaded", "Год календаря загружен"),
    ("calendar.day_changed", "День календаря изменён"),
])
FIELDS = dict([
    ("kind", "вид"), ("description", "описание"), ("parent", "вышестоящий узел"),
    ("parent_id", "номер вышестоящего узла"), ("heads", "руководители"), ("deputies", "заместители"),
    ("unit", "узел"), ("unit_id", "номер узла"), ("mode", "режим"), ("mark", "отметка"),
    ("units", "подразделения"), ("internal_phone", "внутренний телефон"), ("workplace", "место работы"),
    ("birth_date", "дата рождения"), ("file_id", "номер файла"), ("size", "размер, байт"),
    ("content_type", "тип содержимого"), ("signature", "сигнатура"), ("files", "файлы"),
    ("file_name", "имя файла"), ("send_invites", "отправка приглашений"), ("created", "создано"),
    ("skipped", "пропущено"), ("errors", "с ошибками"), ("units_created", "создано узлов"),
    ("work_weekdays", "Рабочие дни"), ("day_start", "начало дня"), ("day_end", "конец дня"),
    ("year", "год"), ("totals", "итоги"), ("date", "дата"),
    # вложенные ключи итогов календаря (дополнение 29)
    ("holidays_on_weekdays", "праздники в будние дни"), ("moved_days_off", "перенесённые выходные"),
    ("moved_workdays", "перенесённые рабочие дни"), ("short_days", "сокращённые дни"),
    ("work_days", "рабочих дней в году"),
])
OBJECT_TYPES = dict([("unit", "узел"), ("staff_import", "загрузка"), ("calendar", "календарь")])
VALUES = {
    "kind": dict([
        ("", "обычный день"), ("department", "отдел"), ("team", "команда"), ("holiday", "праздник"), ("day_off", "перенесённый выходной"),
        ("workday", "перенесённый рабочий день"), ("short", "сокращённый день"),
    ]),
    "mode": dict([("transfer", "перевод"), ("concurrent", "совместительство")]),
    "mark": dict([("head", "руководитель"), ("deputy", "заместитель")]),
    "reason": dict([("manual", "вручную"), ("transfer", "перевод"), ("dismissal", "увольнение")]),
    "result": dict([("clean", "чисто"), ("quarantine", "карантин")]),
    "state": dict([("dismissed", "уволен")]),
    # дополнение 62: в событии — целые 0…6, ключи — строки
    "work_weekdays": dict([("0", "Пн"), ("1", "Вт"), ("2", "Ср"), ("3", "Чт"), ("4", "Пт"), ("5", "Сб"), ("6", "Вс")]),
}


def audit_labels() -> dict:
    """Функция точки `audit_labels`: названия событий, полей, видов объекта и значений среза."""
    return {"actions": ACTIONS, "fields": FIELDS, "object_types": OBJECT_TYPES, "values": VALUES}
