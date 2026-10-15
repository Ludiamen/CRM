"""Названия событий журнала по-русски (PLAN-004, «Журнал»; CONTRACT-004, §§ 9.1–9.2).

Регистрируется в точке ядра `audit_labels` (регистрацию вносит сборщик круга в `extensions.register_all`); ядро
сливает словари со словарями ядра, `org` и `servicedesk` (поздние побеждают, внутренние словари `values`
объединяются) в одном месте, общем для страницы `/audit/` и выгрузки CSV. Ключи `channel` и `reason` имеют тот же
смысл, что в других модулях: здесь только дополнения их значений. Вложенные ключи `cells` и `defaults` — названия
видов уведомлений (решение C5), они пишутся по-русски самими службами.
"""

ACTIONS = dict([
    ("notify.settings_changed", "Настройки уведомлений изменены"),
    ("notify.user_settings_changed", "Личные настройки уведомлений изменены"),
    ("notify.channel_bound", "Канал уведомлений привязан"),
    ("notify.channel_unbound", "Канал уведомлений отвязан"),
    ("notify.push_subscribed", "Устройство подписано на push"),
    ("notify.push_removed", "Подписка push удалена"),
])
FIELDS = dict([
    ("webpush_enabled", "Web Push включён"), ("telegram_enabled", "Telegram включён"),
    ("max_enabled", "MAX включён"), ("email_delay_minutes", "срок до письма, минут"),
    ("retention_days", "срок хранения уведомлений, дней"), ("defaults", "значения по умолчанию"),
    ("cells", "ячейки таблицы"), ("quiet_mode", "тихие часы"), ("own_days", "дни своих часов"),
    ("own_start", "свои часы: с"), ("own_end", "свои часы: до"), ("bound", "привязан"),
    ("browser", "браузер"), ("platform", "платформа"),
])
OBJECT_TYPES = dict([("notify_settings", "настройки уведомлений")])
VALUES = {
    "quiet_mode": dict([("calendar", "по рабочему календарю компании"), ("own", "свои часы"),
                        ("none", "без тихих часов")]),
    "channel": dict([("telegram", "Telegram"), ("max", "MAX")]),
    "reason": dict([("bot_unavailable", "бот недоступен"), ("dismissed", "увольнение"),
                    ("gone", "подписка недействительна"), ("logout", "выход из портала"),
                    ("moved", "подписка перенесена на другую учётную запись"), ("limit", "больше десяти подписок")]),
}


def audit_labels() -> dict:
    """Функция точки `audit_labels`: названия событий, полей, видов объекта и значений среза."""
    return {"actions": ACTIONS, "fields": FIELDS, "object_types": OBJECT_TYPES, "values": VALUES}
