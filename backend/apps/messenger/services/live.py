"""Рассылка живых обновлений и числа получателей (срез 008, T-8212; CONTRACT-008, 5.1, 5.3, 11.1).

PLAN-008 «Живые обновления и рассылка». Получатели — `members.members(chat)` на момент рассылки без автора
действия (у `read` — включая автора сообщения, чтобы ему ушёл кадр «Прочитали N из M»). Фрагмент рендерится
один раз на класс «роль + право видеть карточки»; одно сообщение `messenger.event` с `counts`, `total`,
`variants` и `meta` уходит в группы `messenger.u.<id>` через слой `publish` (таймаут 2 с). Каждому получателю в
`notify.u.<id>` — `notify.html` с числом пункта меню и OOB-строкой списка. Ошибки слоя и постановки задания
ловятся и пишутся предупреждением `apps.messenger.services.live`; текст сообщения в журнал не попадает.
"""
import asyncio
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.template.loader import render_to_string
from django.utils import timezone

from apps.core.models import User, UserState
from apps.core.services import permissions
from apps.core.services import text as core_text
from apps.messenger.models import Chat, Message
from apps.messenger.services import members, text as text_service, unread

logger = logging.getLogger(__name__)
PUBLISH_QUEUE = "notify"
PUBLISH_TIMEOUT = 2.0
LAYER_ALIAS = "publish"
ROLE_AUTHOR = "author"
ROLE_READER = "reader"


def group(user_id: int) -> str:
    """Группа слоя сотрудника для кадров беседы."""
    return f"messenger.u.{user_id}"


def enqueue(chat_id: int, message_id, action: str, owner_id=None, recipients=None) -> None:
    """Поставить задание рассылки в очередь `notify`; сбой постановки не ломает действие (FR-661)."""
    try:
        import django_rq

        from apps.messenger import tasks

        queue = django_rq.get_queue(PUBLISH_QUEUE, commit_mode="auto")
        queue.enqueue(tasks.publish_event, chat_id, message_id, action,
                      owner_id=owner_id, recipients=recipients)
    except Exception:
        logger.warning("Рассылка %s чата %s не поставлена в очередь", action, chat_id)


def publish(chat, action: str = "new", message=None, *, owner=None, recipients=None) -> None:
    """Собрать и разослать один кадр `messenger.event` и числа в личные группы (FR-661).

    `chat` и `message` — строка или запись (задание очереди передаёт номера); `owner` — автор действия.
    """
    raw_chat, chat = chat, _record(Chat, chat)
    chat_id = getattr(chat, "pk", None) or (raw_chat if isinstance(raw_chat, int) else None)
    if chat_id is None and recipients is None:
        return
    owner_id = getattr(owner, "pk", owner)
    audience = _audience(chat, owner_id, recipients, action)
    if not audience:
        return
    raw_message, message = message, _record(Message, message)
    message_id = getattr(message, "pk", None) or (raw_message if isinstance(raw_message, int) else None)
    variants = _variants(chat, message, audience, owner_id, action) if chat is not None else {}
    counts, totals = {}, []
    for user_id in audience:
        person = _person(user_id)
        if person is None:
            continue
        numbers = unread.counts(person)
        counts[str(user_id)] = numbers.get(chat_id, 0)
        totals.append(unread.total(person))
    payload = {
        "type": "messenger.event",
        "chat": chat_id,
        "action": action,
        "message": message_id,
        "owner": owner_id,
        "counts": counts,
        "total": max(totals) if totals else 0,
        "variants": variants,
        "meta": {"created_at": (message.created_at if message is not None else timezone.now()).isoformat()},
    }
    _send_groups({group(user_id): payload for user_id in audience})
    _send_badges(chat, action, audience)


def _record(model, value):
    """Запись по объекту или номеру; `None` и несуществующий номер — `None`."""
    if value is None or hasattr(value, "pk"):
        return value
    try:
        return model.objects.filter(pk=int(value)).first()
    except (TypeError, ValueError):
        return None


def _audience(chat, owner_id, recipients, action) -> list[int]:
    """Получатели на момент рассылки: готовый список (удаление) или текущий состав по правилу действия."""
    if recipients is not None:
        return [int(item) for item in recipients if item is not None and int(item) != owner_id]
    if chat is None:
        return []
    try:
        everyone = sorted(members.members(chat))
    except Exception:
        return []
    allowed = set(User.objects.filter(pk__in=everyone, state=UserState.ACTIVE)
                  .values_list("pk", flat=True))
    if action == "read":
        return [user_id for user_id in everyone if user_id in allowed]
    return [user_id for user_id in everyone if user_id in allowed and user_id != owner_id]


def _person(user_id: int):
    return User.objects.filter(pk=user_id).first()


def _variants(chat, message, audience, owner_id, action: str = "new") -> dict:
    """Фрагмент один раз на класс «роль + link_staff»: не больше четырёх вариантов (FR-661)."""
    variants = {}
    for user_id in audience:
        person = _person(user_id)
        if person is None:
            continue
        role = ROLE_AUTHOR if user_id == owner_id else ROLE_READER
        link_staff = permissions.has_permission(person, "staff.view")
        key = f"{role}:{1 if link_staff else 0}"
        if key not in variants:
            variants[key] = _frame(chat, message, person, role, link_staff, action)
    return variants


def _frame(chat, message, person, role: str, link_staff: bool, action: str = "new") -> str:
    """HTML кадра: сообщение с учётом роли и права на карточки; у `read` — ещё строка «Прочитали N из M»."""
    body = ""
    if message is not None:
        body = text_service.render_plain(message.text, link_staff=link_staff, chat=chat, viewer=person)
    html = render_to_string("messenger/_frame_message.html", {
        "chat": chat, "message": message, "body_html": body, "role": role, "viewer": person})
    if action == "read":
        from apps.messenger.services import read

        own = read.last_own(chat, person)
        readers, audience = read.line(chat, own)
        if own is not None and audience:
            html += render_to_string("messenger/_read_line_frame.html",
                                     {"text": f"Прочитали {readers} из {audience}"})
    return html


def _send_badges(chat, action, audience) -> None:
    """`notify.html` каждому получателю: число пункта меню и OOB-строка списка (11.3, FR-660)."""
    if action == "chat_delete" or chat is None:
        return
    from apps.notify.services import live as notify_live

    for user_id in audience:
        person = _person(user_id)
        if person is None:
            continue
        numbers = unread.counts(person)
        html = render_to_string("messenger/_badge.html", {
            "chat": chat, "count": numbers.get(chat.pk, 0), "total": unread.total(person),
            "preview": _preview(chat)})
        _send_groups({notify_live.group(user_id): {"type": "notify.html", "html": html}})


def _preview(chat) -> str:
    """Превью последнего неудалённого сообщения — как в списке чатов (snippet 100)."""
    last = (Message.objects.filter(chat=chat, deleted_at__isnull=True)
            .order_by("-created_at", "-id").values_list("text", flat=True).first())
    return core_text.snippet(last or "", 100)


def _send_groups(messages: dict) -> None:
    """Отправить сообщения слоя `publish`; таймаут 2 с, ошибки — предупреждением, без текста переписки."""
    if not messages:
        return
    layer = get_channel_layer(LAYER_ALIAS)

    async def guarded():
        async def fanout():
            await asyncio.gather(*[layer.group_send(group_name, message)
                                   for group_name, message in messages.items()])

        await asyncio.wait_for(fanout(), timeout=PUBLISH_TIMEOUT)

    try:
        async_to_sync(guarded)()
    except Exception as error:  # noqa: BLE001 — сбой слоя не отменяет сохранение
        logger.warning("Рассылка мессенджера не доставлена (%s): %s", type(error).__name__, error)