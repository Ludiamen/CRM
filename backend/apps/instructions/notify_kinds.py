"""Виды уведомлений поручений (срез 010, T-10209; FR-711, NFR-723; CONTRACT-010, 9.1).

Десять видов с `order` 220–229, модуль «Поручения», каналы портал и почта; внешний текст без названия и основания.
Ссылка на объект — `instructions.instruction:<номер>`, по ней `still_relevant` проверяет видимость и закрытие.
"""
from apps.core import extensions
from apps.core.services import permissions

KINDS = (
    ("instructions.assigned", "Вам поручено", 220, "Вам поручено"),
    ("instructions.deadline", "Срок поручения приближается", 221, "Срок поручения приближается"),
    ("instructions.report_due", "Нужен отчёт по поручению", 222, "Нужен отчёт по поручению"),
    ("instructions.report_overdue", "Отчёт по поручению просрочен", 223, "Отчёт по поручению просрочен"),
    ("instructions.overdue", "Поручение просрочено", 224, "Поручение просрочено"),
    ("instructions.report_submitted", "Отчёт по поручению пришёл", 225, "Отчёт по поручению пришёл"),
    ("instructions.report_accepted", "Отчёт принят", 226, "Отчёт принят"),
    ("instructions.report_returned", "Отчёт возвращён", 227, "Отчёт возвращён"),
    ("instructions.transfer", "Перенос срока", 228, "Перенос срока поручения"),
    ("instructions.digest", "Сводка по поручениям", 229, "Сводка по поручениям"),
)


def _reference(object_ref: str):
    if not object_ref.startswith("instructions.instruction:"):
        return None
    try:
        number = int(object_ref.rsplit(":", 1)[1])
    except (TypeError, ValueError):
        return None
    from apps.instructions.models import Instruction

    return Instruction.objects.filter(pk=number, deleted_at__isnull=True).first()


def _still_relevant(user_id: int, object_ref: str) -> bool:
    row = _reference(object_ref)
    return row is not None and row.closed_at is None


def _available(user) -> bool:
    return permissions.has_permission(user, "instructions.use")


def notification_kinds() -> list:
    """Записи видов поручений для точки `notification_kinds`."""
    return [extensions.NotificationKind(
        code=code, title=title, module="Поручения", order=order,
        default_channels=("portal", "email"), external_text=text,
        available=_available, still_relevant=_still_relevant)
        for code, title, order, text in KINDS]