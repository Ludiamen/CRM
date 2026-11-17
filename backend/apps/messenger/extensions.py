"""Регистрации мессенджера в точках расширения ядра (срез 008, T-8205 и следующие задачи).

CONTRACT-008 § 3.4; PLAN-008 «Точки расширения ядра и шина событий». Пока одна запись — поле формы узла
`unit_form_parts` («Создадим чат для всего отдела», T-8205); остальные точки добавляют T-8211 (меню), T-8214
(карточка сотрудника), T-8216 (назначение файла), T-8217 (виды уведомлений), T-8219 (поиск), T-8221 (подписи
журнала), T-8224 (сброс стенда). Модели мессенджера здесь не импортируются.
"""


def menu_items() -> list[dict]:
    """Пункты меню: «Мессенджер» (order 1, живое число) и «Настройки мессенджера» (order 64) — T-8211."""
    from apps.messenger.services import unread

    return [
        {"permissions": (), "url": "/messenger/", "title": "Мессенджер", "icon": "icons/chat.html", "order": 1,
         "visible": lambda user: True, "badge": lambda user: unread.badge(user), "live_badge": "messenger"},
        {"permissions": ("settings.portal",), "url": "/settings/messenger/", "title": "Настройки мессенджера",
         "icon": "icons/gear.html", "order": 64},
    ]


def register_all() -> None:
    """Зарегистрировать точки мессенджера: поле формы узла (T-8205) и пункты меню (T-8211)."""
    from apps.core import extensions
    from apps.messenger import unit_form

    for part in unit_form.unit_form_parts():
        extensions.register("unit_form_parts", part)
    extensions.register("menu_items", menu_items)