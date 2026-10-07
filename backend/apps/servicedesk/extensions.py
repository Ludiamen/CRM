"""Регистрация в точках расширения ядра и подписка на события (PLAN-003, «Где живёт код»)."""
from apps.core import extensions


def card_sections(viewer, person) -> list[extensions.CardSection]:
    """Раздел «Заявки» «Профиля» карточки сотрудника (FR-281): ссылка на список по ответственному.

    Пункт меню не виден смотрящему (`listing.card_link` вернул `None`) — раздела нет. Заявки сотрудника не считаются.
    """
    from apps.servicedesk.services import listing

    url = listing.card_link(viewer, person.pk)
    if url is None:
        return []
    return [extensions.CardSection("tickets", "profile", 60, "servicedesk/staff/_card_tickets.html", {"url": url})]


def register_all() -> None:
    """Регистрирует функции `servicedesk` в точках ядра (вызывается из `ServicedeskConfig.ready()`).

    Собрано в круге б2: `unit_usage`, `home_notices` — T-3211; `menu_items` — T-3221; `file_purposes` — T-3216;
    `mail_renderers` — T-3217; `audit_labels` — T-3224; `card_sections` — T-3237. `login_links` — T-3233
    (сборка в2); `stand_reset` — T-3242: все точки зарегистрированы. Подписки на события живут не здесь, а в `services.events.register()`.
    """
    from apps.core import extensions
    from apps.servicedesk import audit_labels, stand
    from apps.servicedesk.services import attachments, form, letters, listing, queues
    from apps.servicedesk.services import settings as sd_settings

    extensions.register("unit_usage", queues.unit_usage)
    extensions.register("home_notices", sd_settings.home_notices)
    extensions.register("menu_items", listing.menu_items)
    extensions.register("file_purposes", attachments.file_purposes)
    extensions.register("mail_renderers", letters.renderers)
    extensions.register("audit_labels", audit_labels.audit_labels)
    extensions.register("card_sections", card_sections)
    extensions.register("login_links", form.login_links)
    extensions.register("stand_reset", stand.stand_reset)
