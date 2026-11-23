"""Регистрации поручений в точках расширения ядра (срез 010; PLAN-010 «Точки расширения ядра»).

T-10008: первая и пока единственная регистрация — `stand_reset` (последней записью, чтобы общий сброс стенда
вызывал её первой). Остальные точки (меню, виды уведомлений, подписи журнала, назначение файла) добавляют задачи
Этапа 3 (T-10209/T-10211/T-10212/T-10217); порядок сохраняется: `stand_reset` — всегда последняя.

Подписка `core.user_dismissed` → `services.instructions.reassign` добавляется T-10202 (моделей здесь нет).
"""


def register_all() -> None:
    """Зарегистрировать точки поручений (T-10008: сброс стенда; прочие — Этап 3)."""
    from apps.core import extensions
    from apps.instructions import audit_labels, notify_kinds, stand
    from apps.instructions.services import files as file_service

    extensions.register("menu_items", menu_items)
    extensions.register("notification_kinds", notify_kinds.notification_kinds)
    extensions.register("file_purposes", file_service.file_purposes)
    extensions.register("audit_labels", audit_labels.audit_labels)
    extensions.register("stand_reset", stand.stand_reset)


def menu_items() -> list[dict]:
    """Пункты меню: «Поручения» (order 3) и «Настройки поручений» (order 66)."""
    return [
        {"permissions": ("instructions.use",), "url": "/instructions/", "title": "Поручения",
         "icon": "icons/instructions.html", "order": 3},
        {"permissions": ("settings.portal",), "url": "/settings/instructions/", "title": "Настройки поручений",
         "icon": "icons/gear.html", "order": 66},
    ]