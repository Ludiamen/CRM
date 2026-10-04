"""Регистрация приложения в точках расширения ядра (PLAN-002, «Точки расширения ядра»)."""


def register_all() -> None:
    """Регистрирует функции `org` в девяти точках ядра (вызывается из `OrgConfig.ready()`).

    Пока регистраций нет; их добавляют задачи (функции точек — обычные функции модулей `apps.org…`):
    `home_notices` — T-2219; `role_sources` и `role_usage` — T-2213; `audit_labels` — T-2221;
    `menu_items` — T-2230; `staff_directory` — T-2233; `card_sections` — T-2234;
    `day_marks` — T-2238; `stand_reset` — T-2242.
    """
