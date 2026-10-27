"""Подписи журнала аудита для действий со списками по-русски (PLAN-006, «Журнал»; CONTRACT-006, 8.2).

Регистрируется в точке ядра `audit_labels` (`extensions.register_all`); ядро сливает словари точек, при совпадении
ключа побеждает поздний, а `lists` регистрируется после `knowledge`, `servicedesk` и `org`. Поэтому общие ключи
(`name`, `description`, `number`, `title`, `created`, `updated`, `errors`) подписаны теми же словами и регистром,
что у прежних модулей (решение Opus при проверке контракта, Н1): слияние ничего не меняет у их записей. Словарь
`values` пуст: значения ключей службы пишут по-русски, а общий ключ значений изменил бы чужие подписи.
Модели не импортируются.
"""

ACTIONS = dict([
    ("lists.list_created", "Создан список"), ("lists.list_changed", "Изменён список"),
    ("lists.list_deleted", "Удалён список"), ("lists.access_changed", "Изменены права списка"),
    ("lists.field_created", "Добавлено поле списка"), ("lists.field_changed", "Изменено поле списка"),
    ("lists.field_hidden", "Скрыто поле списка"), ("lists.field_shown", "Показано поле списка"),
    ("lists.field_deleted", "Удалено поле списка"), ("lists.choices_changed", "Изменены значения поля списка"),
    ("lists.record_archived", "Запись перенесена в архив"), ("lists.record_restored", "Запись возвращена из архива"),
    ("lists.record_purged", "Запись удалена навсегда"), ("lists.import_done", "Загрузка в список"),
])
FIELDS = dict([
    ("name", "название"), ("description", "описание"), ("number", "номер"), ("title", "заголовок"),
    ("created", "создано"), ("updated", "обновлено"), ("errors", "с ошибками"),
    ("list", "список"), ("field", "поле"), ("type", "тип"), ("required", "обязательное"),
    ("multiple", "несколько значений"), ("unique", "уникальное"), ("show_in_table", "показывать в таблице"),
    ("hidden", "скрыто"), ("default", "значение по умолчанию"), ("hint", "подсказка"), ("currency", "валюта"),
    ("target", "целевой список"), ("thresholds", "пороги срока"), ("choices", "значения"),
    ("readers", "читают"), ("editors", "правят"), ("file", "файл"),
])
OBJECT_TYPES = dict([
    ("lists.list", "список"), ("lists.field", "поле списка"), ("lists.record", "запись списка"),
    ("lists.import", "загрузка в список"),
])


def audit_labels() -> dict:
    """Функция точки `audit_labels`: действия, поля, виды объектов; значений для перевода нет."""
    return {"actions": dict(ACTIONS), "fields": dict(FIELDS), "object_types": dict(OBJECT_TYPES), "values": {}}
