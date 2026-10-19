"""Публичный интерфейс уведомлений: создание уведомления и раскладка по каналам (PLAN-004, «Создание уведомления и
раскладка по каналам», «Тихие часы и сводка»; CONTRACT-004, 6.7).

`on_event` — подписчик шины: для каждого вида события собирает черновики и зовёт `create`. `create` в одной транзакции
пишет `Notification` и `Delivery`, планирует сводку, а после фиксации рассылает число и системное уведомление в группы
и ставит в очередь доставки, которым пора уходить.
"""
import logging
from datetime import timedelta

from django.contrib.auth import get_user_model
from django.db import connection, transaction
from django.utils import timezone

from ..models import Delivery, Notification, UserNotifySettings
from . import kinds, live, prefs, quiet
from . import settings as notify_settings

log = logging.getLogger(__name__)

RECIPIENT_STATES = ("active", "blocked")
_CHANNEL_TO_DELIVERY = {"email": "email", "push": "webpush", "telegram": "telegram", "max": "max"}
_IMMEDIATE = ("webpush", "telegram", "max")
_handlers: dict = {}


def handler_for(name: str):
    """Обёртка `handler(**data)`, которая зовёт `on_event(name, **data)`; для одного имени — всегда один объект."""
    if name not in _handlers:
        def handler(**data):
            return on_event(name, **data)

        handler.__name__ = "on_event_" + name.replace(".", "_")
        handler.__qualname__ = handler.__name__
        _handlers[name] = handler
    return _handlers[name]


def subscribe_all() -> None:
    """Подписывает обёртку на каждое событие видов каталога; зовёт `NotifyConfig.ready()`."""
    from apps.core import events

    for name in kinds.event_names():
        events.subscribe(name, handler_for(name))


def on_event(name: str, **data) -> list[int]:
    """Номера созданных `Notification` для события `name`; события без видов — `[]`."""
    created: list[int] = []
    for kind in kinds.for_event(name):
        created.extend(create(kind.code, kind.build(name, data)))
    return created


def _toast_show(kind, user_id: int, working: bool) -> bool:
    """`data-show`: у вида включена ячейка «Push в браузере» и сейчас не тихие часы; у обязательных видов — нет."""
    if kind.mandatory or not working:
        return False
    return "push" in prefs.channels_for(user_id, kind)


def coalesce_key(user_id: int, kind_code: str, object_ref: str) -> str:
    """Ключ замка склейки: `'<user_id>:<код вида>:<object_ref>'` (PLAN-005, «Правка `notify`»; CONTRACT-005, 4.1)."""
    return f"{user_id}:{kind_code}:{object_ref}"


def _lock_coalesce(kind, drafts, states) -> None:
    """Транзакционные замки склейки одним проходом, по возрастанию строки ключа.

    Хэш считает база (`hashtextextended`): `hash()` Python в каждом процессе свой. Единый порядок взятия исключает
    взаимную блокировку двух событий об одной статье; замки живут до конца транзакции `create`."""
    keys = {coalesce_key(d.user_id, kind.code, d.object_ref)
            for d in drafts if d.object_ref and states.get(d.user_id) in RECIPIENT_STATES}
    with connection.cursor() as cursor:
        for key in sorted(keys):
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", [key])


def create(kind_code: str, drafts) -> list[int]:
    """Записи и доставки по черновикам; номера записей в порядке создания. Неизвестный вид — `NotifyError`."""
    kind = kinds.get(kind_code)
    drafts = list(drafts or [])
    if not drafts:
        return []
    user_model = get_user_model()
    states = dict(user_model.objects.filter(pk__in={d.user_id for d in drafts}).values_list("pk", "state"))
    now = timezone.now()
    delay = None
    created: list[int] = []
    recipients: list[int] = []
    toasts: dict[int, dict] = {}
    immediate: list[int] = []
    with transaction.atomic():
        held_users: list[int] = []
        if kind.coalesce:
            _lock_coalesce(kind, drafts, states)
        for draft in drafts:
            state = states.get(draft.user_id)
            if state not in RECIPIENT_STATES:
                continue
            if kind.coalesce and draft.object_ref and Notification.objects.filter(
                    user_id=draft.user_id, kind=kind.code, object_ref=draft.object_ref, read_at__isnull=True).exists():
                continue
            note = Notification.objects.create(user_id=draft.user_id, kind=kind.code, text=draft.text, url=draft.url,
                                               object_ref=draft.object_ref, created_at=now)
            created.append(note.pk)
            if draft.user_id not in recipients:
                recipients.append(draft.user_id)
            working = True
            if not kind.mandatory and state == "active":
                if delay is None:
                    delay = timedelta(minutes=notify_settings.get().email_delay_minutes)
                working = _external(kind, draft.user_id, note, now, delay, immediate, held_users)
            toasts[draft.user_id] = {"text": note.text, "url": f"/notifications/{note.pk}/open/", "tag": f"n-{note.pk}",
                                     "show": _toast_show(kind, draft.user_id, working)}
        for user_id in (sorted(set(held_users)) if kind.coalesce else dict.fromkeys(held_users)):
            plan_digest(user_id)
        if recipients:
            transaction.on_commit(lambda: _after_commit(recipients, toasts, immediate))
    return created


def _external(kind, user_id: int, note, now, delay, immediate: list, held_users: list) -> bool:
    """Доставки одной записи по включённым и доступным каналам вида; возвращает «рабочее ли время у получателя»."""
    row = prefs.row_of(user_id)
    working = quiet.is_working(row, now)
    wanted = prefs.channels_for(user_id, kind)
    if not wanted:
        return working
    states, push_available, _ = prefs._channels(user_id)
    for channel in wanted:
        available = push_available if channel == "push" else states[channel].available
        if not available:
            continue
        target = _CHANNEL_TO_DELIVERY[channel]
        if target == "email":
            Delivery.objects.create(notification=note, channel=target, state=Delivery.State.WAITING,
                                    due_at=note.created_at + delay)
        elif working:
            delivery = Delivery.objects.create(notification=note, channel=target, state=Delivery.State.WAITING,
                                               due_at=now, enqueued_at=now)
            immediate.append(delivery.pk)
        else:
            Delivery.objects.create(notification=note, channel=target, state=Delivery.State.HELD)
            held_users.append(user_id)
    return working


def _after_commit(recipients: list, toasts: dict, immediate: list) -> None:
    """После фиксации: число и системные уведомления в группы одним вызовом, затем постановка доставок."""
    live.push(recipients, toasts=toasts)
    if immediate:
        from . import delivery

        delivery.enqueue(immediate)


def plan_digest(user_id: int):
    """Срок сводки — меньшее из прежнего и ближайшего начала рабочего времени; `None` — планировать некуда."""
    row, _ = UserNotifySettings.objects.get_or_create(user_id=user_id)
    start = quiet.next_start(row, timezone.now())
    if start is None:
        log.warning("Сводку сотруднику %s планировать некуда: за 400 суток рабочего времени нет", user_id)
        return row.digest_due_at
    if row.digest_due_at is None or start < row.digest_due_at:
        row.digest_due_at = start
        row.save(update_fields=["digest_due_at"])
    return row.digest_due_at


def replan_digest(user_id: int):
    """Пересчёт срока после смены тихих часов: есть `held` — срок заменяется, нет — снимается."""
    if not Delivery.objects.filter(notification__user_id=user_id, state=Delivery.State.HELD).exists():
        UserNotifySettings.objects.filter(user_id=user_id).update(digest_due_at=None)
        return None
    row, _ = UserNotifySettings.objects.get_or_create(user_id=user_id)
    start = quiet.next_start(row, timezone.now())
    if start is None:
        log.warning("Сводку сотруднику %s планировать некуда: за 400 суток рабочего времени нет", user_id)
    row.digest_due_at = start
    row.save(update_fields=["digest_due_at"])
    return start
