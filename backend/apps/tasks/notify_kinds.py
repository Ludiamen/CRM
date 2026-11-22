"""Виды уведомлений задач (срез 009, T-9212; FR-691, NFR-714; CONTRACT-009, 9.1).

Восемь видов после мессенджера (order 210–217); каналы по умолчанию — портал и почта; внешний текст постоянный, без
названия, описания и ФИО. `still_relevant` — правило задач (`notify_rules`), `available` — право `tasks.use`.
"""
from apps.core.extensions import NotificationKind

MODULE = "Задачи"

KINDS = (
    ("tasks.assigned", "Назначена задача", 210, "Вам назначена задача"),
    ("tasks.due_soon", "Задача скоро просрочена", 211, "Срок задачи приближается"),
    ("tasks.due", "Срок наступил", 212, "Срок задачи наступил"),
    ("tasks.overdue", "Задача просрочена", 213, "Задача просрочена"),
    ("tasks.subordinate_overdue", "Задача подчинённого просрочена", 214, "Задача подчинённого просрочена"),
    ("tasks.reminder", "Вы просили напомнить", 215, "Напоминание о задаче"),
    ("tasks.comment", "Новый комментарий", 216, "Новый комментарий к задаче"),
    ("tasks.subordinate_digest", "Сводка по задачам подчинённых", 217, "Сводка по задачам подчинённых"),
)


def _available(user) -> bool:
    from apps.core.services import permissions

    return permissions.has_permission(user, "tasks.use")


def notification_kinds() -> list:
    """Записи точки `notification_kinds`: восемь видов задач (order 210–217)."""
    from apps.tasks.services import notify_rules

    return [
        NotificationKind(code=code, title=title, module=MODULE, order=order, default_channels=("portal", "email"),
                         external_text=external, available=_available,
                         still_relevant=notify_rules.still_relevant)
        for code, title, order, external in KINDS
    ]