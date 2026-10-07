"""Публичный интерфейс сервис-деска: очереди — отметка узла структуры (PLAN-003, «Отметка очереди»; CONTRACT-003, 6.4).

Узел передаётся числом `unit_id`; модели `org` не импортируются. Право `servicedesk.manage` проверяет маршрут.
"""
from dataclasses import dataclass

from django.db import transaction

from apps.core.services import audit
from apps.org.services.refs import UnitRef

from ..models import Category, InboundMail, Queue, ServiceDeskSettings, Status, Ticket
from . import access, intake
from .errors import ServiceDeskError

OPEN_KINDS = (Status.Kind.NEW, Status.Kind.IN_PROGRESS, Status.Kind.WAITING)


@dataclass(frozen=True)
class UnmarkPreview:
    """Что произойдёт при снятии отметки: число открытых заявок и категории, которые перейдут в очередь по умолчанию."""

    open_tickets: int
    categories: list


def marked_units() -> list[UnitRef]:
    """Отмеченные узлы по `path`; один запрос."""
    queues = Queue.objects.select_related("unit").order_by("unit__path")
    return [UnitRef(id=q.unit.pk, name=q.unit.name, kind=q.unit.kind, path=q.unit.path) for q in queues]


def is_queue(unit_id: int) -> bool:
    """Узел отмечен очередью."""
    return Queue.objects.filter(unit_id=unit_id).exists()


def default_unit_id() -> int | None:
    """Очередь по умолчанию — номер узла или `None`."""
    return ServiceDeskSettings.objects.filter(pk=1).values_list("default_queue_id", flat=True).first()


def mark(unit_id: int, *, actor, ip=None) -> Queue:
    """Отмечает узел очередью; журнал `queue.marked`."""
    with transaction.atomic():
        if is_queue(unit_id):
            raise ServiceDeskError("already_queue", "Узел уже отмечен очередью")
        queue = Queue.objects.create(unit_id=unit_id, created_by=actor)
        audit.record("queue.marked", actor=actor, object_type="queue", object_id=unit_id,
                     after={"unit": queue.unit.name, "unit_id": unit_id}, ip=ip)
        return queue


def _open_count(unit_id: int) -> int:
    return Ticket.objects.filter(queue_id=unit_id, kind__in=OPEN_KINDS).count()


def _categories(unit_id: int):
    return Category.objects.filter(queue_id=unit_id).order_by("order", "id")


def _require_default_for_categories(unit_id: int, default_id) -> None:
    """Дополнение 45: без очереди по умолчанию категории снимаемой очереди некуда переводить."""
    if default_id is None and _categories(unit_id).exists():
        raise ServiceDeskError("no_default_queue",
                               "Сначала выберите очередь по умолчанию: в неё перейдут категории этой очереди.")


def unmark_preview(unit_id: int) -> UnmarkPreview:
    """Для диалога подтверждения: ничего не меняет; не очередь — `not_queue`."""
    if not is_queue(unit_id):
        raise ServiceDeskError("not_queue", "Этот узел не отмечен очередью сервис-деска")
    _require_default_for_categories(unit_id, ServiceDeskSettings.objects.get(pk=1).default_queue_id)
    return UnmarkPreview(open_tickets=_open_count(unit_id), categories=list(_categories(unit_id)))


def unmark(unit_id: int, *, actor, ip=None) -> list:
    """Снимает отметку; категории узла уходят в очередь по умолчанию (ответственный, не участник её, снимается)."""
    with transaction.atomic():
        queue = Queue.objects.select_related("unit").select_for_update(of=("self",)).filter(unit_id=unit_id).first()
        if queue is None:
            raise ServiceDeskError("not_queue", "Этот узел не отмечен очередью сервис-деска")
        settings_row = ServiceDeskSettings.objects.select_related("default_queue").get(pk=1)
        _require_default_for_categories(unit_id, settings_row.default_queue_id)
        if settings_row.default_queue_id == unit_id:
            raise ServiceDeskError("queue_is_default",
                                   "Отметку снять нельзя: это очередь по умолчанию. Сначала выберите другую")
        open_count = _open_count(unit_id)
        if open_count:
            raise ServiceDeskError("queue_has_open_tickets",
                                   f"Отметку снять нельзя: в очереди есть открытые заявки — {open_count}")
        default_id = settings_row.default_queue_id
        default_name = settings_row.default_queue.name if default_id else ""
        moved = list(_categories(unit_id).select_related("default_assignee"))
        for category in moved:
            before = {"queue": queue.unit.name}
            after = {"dictionary": "category", "name": category.name, "queue": default_name}
            assignee = category.default_assignee
            if assignee is not None and not (default_id and access.is_participant(assignee, default_id)):
                before["default_assignee"] = assignee.full_name
                after["default_assignee"] = ""
                category.default_assignee = None
            category.queue_id = default_id
            category.save(update_fields=["queue", "default_assignee"])
            audit.record("sd_dictionary.updated", actor=actor, object_type="sd_dictionary",
                         object_id=f"categories:{category.pk}", before=before, after=after, ip=ip)
        before = {"unit": queue.unit.name, "unit_id": unit_id}
        queue.delete()
        audit.record("queue.unmarked", actor=actor, object_type="queue", object_id=unit_id, before=before, ip=ip)
        return moved


def set_default(unit_id: int, *, actor, ip=None) -> None:
    """Выбирает очередь по умолчанию среди отмеченных; ставит разбор писем `waiting_setup` после фиксации."""
    with transaction.atomic():
        queue = Queue.objects.select_related("unit").filter(unit_id=unit_id).first()
        if queue is None:
            raise ServiceDeskError("not_queue", "Этот узел не отмечен очередью сервис-деска")
        row = ServiceDeskSettings.objects.select_related("default_queue").select_for_update(of=("self",)).get(pk=1)
        if row.default_queue_id == unit_id:
            return
        before = {"unit": row.default_queue.name, "unit_id": row.default_queue_id} if row.default_queue_id else {}
        row.default_queue_id = unit_id
        row.save(update_fields=["default_queue", "updated_at"])
        audit.record("queue.default_changed", actor=actor, object_type="queue", object_id=unit_id, before=before,
                     after={"unit": queue.unit.name, "unit_id": unit_id}, ip=ip)
        waiting = list(InboundMail.objects.filter(status=InboundMail.Status.WAITING_SETUP)
                       .order_by("id").values_list("pk", flat=True))
        if waiting:
            transaction.on_commit(lambda: [intake.enqueue(pk) for pk in waiting])


def unit_usage(unit_id: int) -> str | None:
    """Точка `unit_usage`: почему узел нельзя удалить (заявки, затем отметка очереди) или `None`."""
    if Ticket.objects.filter(queue_id=unit_id).exists():
        return "к узлу привязаны заявки сервис-деска"
    if Queue.objects.filter(unit_id=unit_id).exists():
        return "узел — очередь сервис-деска: сначала снимите отметку"
    return None
