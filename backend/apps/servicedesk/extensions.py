"""Регистрация в точках расширения ядра и подписка на события (PLAN-003, «Где живёт код»)."""


def register_all() -> None:
    """Регистрирует функции `servicedesk` в точках ядра (вызывается из `ServicedeskConfig.ready()`).

    Сейчас пусто; регистрации добавляют задачи: `unit_usage` и `home_notices` — T-3211; `menu_items` — T-3212;
    `file_purposes` — T-3216; `mail_renderers` — T-3217; `audit_labels` — T-3224; `login_links` — T-3233;
    `card_sections` — T-3237; `stand_reset` — T-3242. Подписки на события живут не здесь, а в
    `services.events.register()`.
    """
    from apps.core import extensions  # noqa: F401  (понадобится регистрациям задач)
