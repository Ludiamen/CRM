"""Названия событий журнала по-русски (PLAN-003, «Журнал»; CONTRACT-003, §§ 9.1–9.2).

Регистрируется в точке ядра `audit_labels` (регистрацию вносит сборщик круга в `extensions.register_all`); ядро
сливает словари со словарями ядра и `org` (поздние побеждают) в одном месте, общем для страницы `/audit/` и
выгрузки CSV. Модели `org` не импортируются.
"""

ACTIONS = dict([
    ("ticket.created", "Заявка создана"), ("ticket.assigned", "Назначен ответственный"),
    ("ticket.assignee_removed", "Ответственный снят"),
    ("ticket.transferred", "Заявка передана в другую очередь"), ("ticket.updated", "Заявка изменена"),
    ("ticket.closed", "Заявка закрыта"), ("ticket.autoclosed", "Заявка закрыта автоматически"),
    ("ticket.reopened", "Заявка открыта заново"), ("ticket.reply_sent", "Ответ отправлен"),
    ("ticket.comment_added", "Комментарий добавлен"), ("ticket.attachment_quarantined", "Вложение в карантине"),
    ("ticket.mail_failed", "Письмо не доставлено"), ("ticket.participant_removed", "Участник снят"),
    ("ticket.anonymized", "Заявка обезличена"),
    ("requester.created", "Заявитель добавлен"), ("requester.updated", "Заявитель изменён"),
    ("requester.deleted", "Заявитель удалён"), ("requester_import.completed", "Загрузка заявителей выполнена"),
    ("queue.marked", "Очередь отмечена"), ("queue.unmarked", "Отметка очереди снята"),
    ("queue.default_changed", "Очередь по умолчанию изменена"),
    ("sd_dictionary.created", "Значение справочника добавлено"),
    ("sd_dictionary.updated", "Значение справочника изменено"),
    ("sd_dictionary.archived", "Значение справочника в архиве"),
    ("sd_dictionary.restored", "Значение справочника возвращено из архива"),
    ("sd_dictionary.deleted", "Значение справочника удалено"),
    ("client_unit.created", "Подразделение-клиент добавлено"), ("client_unit.updated", "Подразделение-клиент изменено"),
    ("client_unit.archived", "Подразделение-клиент в архиве"),
    ("client_unit.restored", "Подразделение-клиент возвращено из архива"),
    ("client_unit.deleted", "Подразделение-клиент удалено"),
    ("servicedesk.settings_changed", "Настройки сервис-деска изменены"),
    ("mailbox.connected", "Ящик заявок подключён"), ("mailbox.recreated", "Ящик заявок пересоздан"),
])
FIELDS = dict([
    ("number", "номер"), ("channel", "канал"), ("queue", "очередь"), ("queue_id", "номер очереди"),
    ("category", "категория"), ("priority", "критичность"), ("complexity", "сложность"), ("source", "источник"),
    ("status", "статус"), ("assignee", "ответственный"), ("assignee_id", "номер ответственного"),
    ("created_by", "кто создал"), ("created_by_id", "номер создавшего"), ("client_unit", "подразделение"),
    ("reason", "причина"), ("reason_given", "указана причина"),
    ("requester_name_changed", "ФИО заявителя изменено"), ("name_changed", "ФИО изменено"),
    ("entry_id", "номер элемента ленты"), ("participant_id", "номер участника"), ("mail_kind", "вид письма"),
    ("via", "способ"), ("origin", "отметка записи"), ("delete_missing", "удалять отсутствующих"),
    ("domains", "домены"), ("default_priority", "критичность по умолчанию"),
    ("autoclose_days", "срок автозакрытия, дней"), ("reopen_days", "срок открытия заново, дней"),
    ("form_hourly_limit", "порог формы в час"), ("retention_years", "срок хранения заявок, лет"),
    ("inbound_retention_days", "срок хранения писем без заявки, дней"),
    ("dictionary", "справочник"), ("name", "название"), ("order", "порядок"),
    ("default_assignee", "ответственный по умолчанию"), ("on_form", "на форме"), ("status_kind", "вид статуса"),
    ("is_default", "по умолчанию"), ("uidvalidity", "UIDVALIDITY"), ("last_uid", "последний UID"),
    # итоги загрузки заявителей (вложенные ключи `totals`)
    ("added", "добавлено"), ("updated", "обновлено"), ("unchanged", "без изменений"), ("deleted", "удалено"),
    ("origin_changed", "сменили отметку на «заявка»"),
])
OBJECT_TYPES = dict([
    ("ticket", "заявка"), ("requester", "заявитель"), ("requester_import", "загрузка"), ("queue", "очередь"),
    ("sd_dictionary", "справочник"), ("servicedesk", "сервис-деск"), ("mailbox", "ящик заявок"),
])
VALUES = {
    "channel": dict([("mail", "письмо"), ("form", "форма"), ("staff", "исполнитель")]),
    "via": dict([("manual", "вручную"), ("mail", "письмом заявителя")]),
    "reason": dict([("manual", "вручную"), ("queue_changed", "смена очереди"),
                    ("not_participant", "больше не участник очереди")]),
    "origin": dict([("table", "таблица"), ("ticket", "заявка")]),
    "dictionary": dict([("category", "категория"), ("priority", "критичность"), ("complexity", "сложность"),
                        ("status", "статус"), ("source", "источник")]),
    "status_kind": dict([("new", "новая"), ("in_progress", "в работе"), ("waiting", "ждёт ответа заявителя"),
                         ("closed", "закрыта")]),
    "mail_kind": dict([("confirmation", "подтверждение заявки"), ("assigned", "взята в работу"),
                       ("closed", "закрыта с решением"), ("autoclosed", "закрыта автоматически"),
                       ("reopened", "открыта заново"), ("reply", "ответ исполнителя")]),
}


def audit_labels() -> dict:
    """Функция точки `audit_labels`: названия событий, полей, видов объекта и значений среза."""
    return {"actions": ACTIONS, "fields": FIELDS, "object_types": OBJECT_TYPES, "values": VALUES}
