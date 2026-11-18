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


def card_sections(viewer, target) -> list:
    """Кнопка «Написать» в карточке коллеги: не себе и не уволенному (T-8214, CONTRACT-008 3.4, 12.6)."""
    from apps.core import extensions

    if target is None or viewer is None or target.pk == viewer.pk:
        return []
    if getattr(target, "state", "") == "dismissed":
        return []
    return [extensions.CardSection("messenger", "profile", 70, "messenger/_card_write.html", {})]


def register_all() -> None:
    """Зарегистрировать точки мессенджера: поле формы узла, меню и карточку сотрудника."""
    from apps.core import extensions
    from apps.messenger import unit_form

    for part in unit_form.unit_form_parts():
        extensions.register("unit_form_parts", part)
    extensions.register("menu_items", menu_items)
    extensions.register("card_sections", card_sections)
    from apps.messenger.services import files as file_service

    extensions.register("file_purposes", file_service.file_purposes)
    from apps.messenger import notify_kinds

    extensions.register("notification_kinds", notify_kinds.notification_kinds)