"""Публичный интерфейс сервис-деска: справочники (PLAN-003, «Справочники и настройки»; CONTRACT-003, 6.5).

Шесть справочников задаются строкой-видом (`KINDS`). Право `servicedesk.manage` проверяет маршрут, служба его не читает.
Каждое изменение пишет событие журнала «было / стало» (9.2).
"""
from django.db import transaction

from apps.core.services import audit

from ..models import (Category, ClientUnit, Complexity, Priority, Queue, Requester, ServiceDeskSettings, Source, Status,
                      Ticket, name_key)
from . import access
from .errors import ServiceDeskError

KINDS = ("category", "priority", "complexity", "status", "source", "client_unit")

_MODELS = {"category": Category, "priority": Priority, "complexity": Complexity, "status": Status,
           "source": Source, "client_unit": ClientUnit}
# вид объекта в пути маршрутов (раздел 12) — часть `object_id` журнала
_PATHS = {"category": "categories", "priority": "priorities", "complexity": "complexities", "status": "statuses",
          "source": "sources", "client_unit": "client-units"}
# допустимые `extra` у `update` (у `create` к ним у статуса добавляется `kind`)
_EXTRA = {"category": {"queue_id", "default_assignee", "on_form"}, "status": {"is_default"}}

_SYSTEM_STATUS_CODE = "autoclosed"


def model_of(dictionary: str):
    """Класс модели вида справочника; неизвестный вид — `KeyError`."""
    return _MODELS[dictionary]


def _error(code: str, message: str) -> ServiceDeskError:
    return ServiceDeskError(code, message)


def _limit(dictionary: str) -> int:
    return 150 if dictionary == "client_unit" else 100


def _action(dictionary: str, suffix: str) -> str:
    return f"client_unit.{suffix}" if dictionary == "client_unit" else f"sd_dictionary.{suffix}"


def _object_id(dictionary: str, obj) -> str:
    return f"{_PATHS[dictionary]}:{obj.pk}"


def _check_name(dictionary: str, name: str, exclude_pk=None) -> str:
    """Название без крайних пробелов; отказ: пусто, длинно, занято (по `name_key` в пределах справочника)."""
    name = (name or "").strip()
    if not name:
        raise _error("name_required", "Укажите название")
    if len(name) > _limit(dictionary):
        raise _error("name_too_long", f"Название не длиннее {_limit(dictionary)} знаков")
    taken = _MODELS[dictionary].objects.filter(name_key=name_key(name))
    if exclude_pk is not None:
        taken = taken.exclude(pk=exclude_pk)
    if taken.exists():
        raise _error("name_taken", "Такое название уже есть в этом справочнике")
    return name


def _check_queue(queue_id) -> None:
    if queue_id is None or not Queue.objects.filter(unit_id=queue_id).exists():
        raise _error("queue_not_marked", "Очередью категории может быть только узел, отмеченный очередью")


def _check_assignee(assignee, queue_id) -> None:
    if assignee is not None and not access.is_participant(assignee, queue_id):
        raise _error("assignee_not_participant", "Ответственный по умолчанию должен быть участником очереди категории")


def _queue_name(unit_id) -> str:
    """Название узла-очереди для журнала (через связь отметки: модели `org` не импортируются)."""
    queue = Queue.objects.select_related("unit").filter(unit_id=unit_id).first()
    return queue.unit.name if queue else ""


def _snapshot(dictionary: str, obj) -> dict:
    """Поля записи, которые попадают в журнал (9.2): значения справочников — названия."""
    data = {"name": obj.name}
    if dictionary == "client_unit":
        return data
    data["order"] = obj.order
    if dictionary == "category":
        data["queue"] = obj.queue.name if obj.queue_id else ""
        data["default_assignee"] = obj.default_assignee.full_name if obj.default_assignee_id else ""
        data["on_form"] = obj.on_form
    elif dictionary == "status":
        data["status_kind"] = obj.kind
        data["is_default"] = obj.is_default
    return data


def _unknown(dictionary: str, extra: dict, allowed: set) -> None:
    """Ключи сверх допустимых — `TypeError` (`kind` у `update`, `is_system`, `system_code` и т. п.)."""
    bad = set(extra) - allowed
    if bad:
        raise TypeError(f"{dictionary}: неожиданные аргументы {sorted(bad)}")


def create(dictionary: str, *, name: str, order: int = 0, actor, ip=None, **extra):
    """Создаёт значение справочника; `extra`: у категории `queue_id`, `default_assignee`, `on_form`; у статуса `kind`, `is_default`."""
    model = model_of(dictionary)
    allowed = set(_EXTRA.get(dictionary, ()))
    if dictionary == "status":
        allowed.add("kind")
    _unknown(dictionary, extra, allowed)
    with transaction.atomic():
        name = _check_name(dictionary, name)
        fields = {}
        if dictionary == "category":
            _check_queue(extra.get("queue_id"))
            assignee = extra.get("default_assignee")
            _check_assignee(assignee, extra["queue_id"])
            fields = {"queue_id": extra["queue_id"], "default_assignee": assignee,
                      "on_form": bool(extra.get("on_form", False))}
        elif dictionary == "status":
            kind = extra.get("kind")
            if kind not in Status.Kind.values:
                raise ValueError(f"вид статуса: {kind!r}")
            fields = {"kind": kind, "is_default": False}
        if dictionary == "client_unit":
            obj = model.objects.create(name=name, name_key=name_key(name))
        else:
            obj = model.objects.create(name=name, name_key=name_key(name), order=order, **fields)
        if dictionary == "status" and extra.get("is_default"):
            Status.objects.filter(kind=obj.kind, is_default=True).exclude(pk=obj.pk).update(is_default=False)
            obj.is_default = True
            obj.save(update_fields=["is_default"])
        if dictionary == "category":
            obj = Category.objects.select_related("queue", "default_assignee").get(pk=obj.pk)
        after = _snapshot(dictionary, obj)
        if dictionary != "client_unit":
            after = {"dictionary": dictionary, **after}
        audit.record(_action(dictionary, "created"), actor=actor, object_type="sd_dictionary",
                     object_id=_object_id(dictionary, obj), after=after, ip=ip)
        return obj


def update(obj, *, name: str, order=None, actor, ip=None, **extra):
    """Меняет значение; журнал `updated` только если что-то изменилось (было и стало по изменённым полям)."""
    dictionary = _kind_of(obj)
    _unknown(dictionary, extra, _EXTRA.get(dictionary, set()))
    if dictionary == "category" and obj.is_system and "queue_id" in extra:
        raise TypeError("у системной категории очередь не задаётся")
    with transaction.atomic():
        model = model_of(dictionary)
        model.objects.select_for_update().get(pk=obj.pk)
        obj.refresh_from_db()
        fresh = obj
        before = _snapshot(dictionary, fresh)
        name = _check_name(dictionary, name, exclude_pk=fresh.pk)
        fresh.name, fresh.name_key = name, name_key(name)
        if order is not None and dictionary != "client_unit":
            fresh.order = order
        if dictionary == "category":
            queue_id = extra.get("queue_id", fresh.queue_id)
            if "queue_id" in extra:
                _check_queue(queue_id)
            assignee = extra["default_assignee"] if "default_assignee" in extra else fresh.default_assignee
            if "queue_id" in extra or "default_assignee" in extra:
                if assignee is not None and queue_id is not None:
                    _check_assignee(assignee, queue_id)
            fresh.queue_id, fresh.default_assignee = queue_id, assignee
            if "on_form" in extra:
                fresh.on_form = bool(extra["on_form"])
        elif dictionary == "status" and extra.get("is_default") and not fresh.is_default:
            Status.objects.filter(kind=fresh.kind, is_default=True).update(is_default=False)
            fresh.is_default = True
        fresh.save()
        fresh.refresh_from_db()
        after = _snapshot(dictionary, fresh)
        changed = {key for key in after if before[key] != after[key]}
        if changed:
            event_after = {key: after[key] for key in after if key in changed}
            if dictionary != "client_unit":
                event_after = {"dictionary": dictionary, "name": after["name"], **event_after}
            audit.record(_action(dictionary, "updated"), actor=actor, object_type="sd_dictionary",
                         object_id=_object_id(dictionary, fresh),
                         before={key: before[key] for key in before if key in changed}, after=event_after, ip=ip)
        return fresh


def _kind_of(obj) -> str:
    for dictionary, model in _MODELS.items():
        if isinstance(obj, model):
            return dictionary
    raise KeyError(type(obj).__name__)


def _active_in_kind(obj) -> int:
    """Сколько действующих (не архивных) статусов того же вида, кроме самого."""
    return Status.objects.filter(kind=obj.kind, archived=False).exclude(pk=obj.pk).count()


def _protect(dictionary: str, obj) -> None:
    """Общие отказы архива и удаления: системное, последний действующий, по умолчанию (в таком порядке)."""
    if (dictionary == "category" and obj.is_system) or (dictionary in ("status", "source") and obj.system_code):
        raise _error("system_protected", "Системное значение нельзя убрать в архив или удалить; переименовать его можно")
    if dictionary == "status" and not obj.archived and _active_in_kind(obj) == 0:
        raise _error("last_active", "Это последний действующий статус своего вида: убрать его в архив нельзя")
    default = (dictionary == "status" and obj.is_default) or (
        dictionary == "priority" and ServiceDeskSettings.objects.filter(pk=1, default_priority_id=obj.pk).exists())
    if default:
        raise _error("default_protected", "Значение по умолчанию нельзя убрать в архив или удалить: сначала отметьте другое")


def archive(obj, *, actor, ip=None) -> None:
    """Убирает значение в архив (архивное не предлагается в выборах, в заявках остаётся)."""
    dictionary = _kind_of(obj)
    with transaction.atomic():
        _protect(dictionary, obj)
        if obj.archived:
            return
        obj.archived = True
        obj.save(update_fields=["archived"])
        _record_simple(dictionary, "archived", obj, actor, ip)


def restore(obj, *, actor, ip=None) -> None:
    """Возвращает значение из архива; не архивное — тихо ничего."""
    dictionary = _kind_of(obj)
    with transaction.atomic():
        if not obj.archived:
            return
        obj.archived = False
        obj.save(update_fields=["archived"])
        _record_simple(dictionary, "restored", obj, actor, ip)


def _record_simple(dictionary: str, suffix: str, obj, actor, ip) -> None:
    """События архива и возврата: в `after` — вид и название; у подразделения-клиента — только название."""
    after = {"name": obj.name} if dictionary == "client_unit" else {"dictionary": dictionary, "name": obj.name}
    audit.record(_action(dictionary, suffix), actor=actor, object_type="sd_dictionary",
                 object_id=_object_id(dictionary, obj), after=after, ip=ip)


def delete(obj, *, actor, ip=None) -> None:
    """Удаляет значение, если оно нигде не используется."""
    dictionary = _kind_of(obj)
    with transaction.atomic():
        _protect(dictionary, obj)
        if is_used(obj):
            tail = "в заявках или в записях заявителей" if dictionary == "client_unit" else "в заявках"
            raise _error("in_use", f"Значение используется {tail}, удалить его нельзя. Уберите его в архив")
        before = {"name": obj.name} if dictionary == "client_unit" else {"dictionary": dictionary, "name": obj.name}
        object_id = _object_id(dictionary, obj)
        obj.delete()
        audit.record(_action(dictionary, "deleted"), actor=actor, object_type="sd_dictionary",
                     object_id=object_id, before=before, ip=ip)


def is_used(obj) -> bool:
    """Значение есть в заявках (у подразделения — и в записях заявителей, у критичности — и в настройках)."""
    dictionary = _kind_of(obj)
    field = {"category": "category", "priority": "priority", "complexity": "complexity", "status": "status",
             "source": "source", "client_unit": "client_unit"}[dictionary]
    if Ticket.objects.filter(**{field: obj}).exists():
        return True
    if dictionary == "priority":
        return ServiceDeskSettings.objects.filter(default_priority_id=obj.pk).exists()
    if dictionary == "client_unit":
        return Requester.objects.filter(client_unit=obj).exists()
    return False


def offered(dictionary: str):
    """Неархивные значения для выборов формы и карточки: по `order`, затем `name` (подразделения — по `name`)."""
    model = model_of(dictionary)
    ordering = ("name",) if dictionary == "client_unit" else ("order", "name")
    return model.objects.filter(archived=False).order_by(*ordering)


def manual_statuses():
    """Статусы ручной смены: неархивные виды «в работе» и «ждёт ответа заявителя» по `order`."""
    return Status.objects.filter(archived=False, kind__in=[Status.Kind.IN_PROGRESS, Status.Kind.WAITING]).order_by("order", "name")


def closing_statuses() -> list:
    """Статусы формы закрытия: вида «закрыта» без системного `autoclosed`; статус по умолчанию — первым."""
    found = Status.objects.filter(archived=False, kind=Status.Kind.CLOSED).exclude(
        system_code=_SYSTEM_STATUS_CODE).order_by("order", "name")
    return sorted(found, key=lambda status: not status.is_default)


def manual_sources():
    """Источники ручного выбора: неархивные без системных, по `order`."""
    return Source.objects.filter(archived=False, system_code="").order_by("order", "name")


def default_status(kind: str):
    """Статус по умолчанию вида `kind` (вид статуса, не справочника)."""
    return Status.objects.get(kind=kind, is_default=True)
