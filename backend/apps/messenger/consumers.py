"""Соединение `/ws/messenger/?chat=<id>` (срез 008, T-8213; CONTRACT-008, 5.5, 11.2–11.4).

Проверка сессии — `SessionGuardMixin` (не «ok» — 4401, цикл раз в `CHECK_INTERVAL`), затем `chat`: нет, `0`,
`-1`, текст, `01`, дробное — принять и закрыть 4400 **до** подписки на группу; невидимый, несуществующий и
удалённый чат — 4404. Группа — личная `messenger.u.<id>`, поэтому кадры списка и чисел приходят одним
соединением.Кадры: `messenger.event` чужого чата игнорируется; `new` — в конец беседы, `edit` — замена сообщения,
`delete` — `hx-swap-oob="delete"`, `read` — строка «Прочитали N из M», `chat_delete` — переход на список.
Входящие: `{"sync": …}` — служебный `#messenger-synced`, `{"read": …}` — отметка прочтения и рассылка;
неизвестное игнорируется; больше 4 КБ — 1009. Ошибка слоя при подписке — 1011.
"""
import json
from datetime import datetime

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer
from django.utils import timezone

from apps.core.ws import SessionGuardMixin

CHECK_INTERVAL = 25
LIMIT_BYTES = 4096
CLOSE_CHAT = 4400
CLOSE_FORBIDDEN = 4404
CLOSE_TOO_BIG = 1009
CLOSE_LAYER = 1011


def _chat_id(value):
    """Строго положительное целое без ведущего нуля: `None` — параметр неверный."""
    if not isinstance(value, str) or not value.isascii() or not value.isdigit():
        return None
    if value.startswith("0"):
        return None
    return int(value)


def _moment(value):
    """Aware datetime из ISO; `None` — значение неверное."""
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if timezone.is_naive(moment):
        return None
    return moment


@database_sync_to_async
def _visible(user, chat_id: int) -> bool:
    from apps.messenger.services import members

    try:
        members.get_chat(user, chat_id)
    except Exception:
        return False
    return True


def _staff_view(user) -> bool:
    from apps.core.services import permissions

    return permissions.has_permission(user, "staff.view")


@database_sync_to_async
def _mark_read(user, chat_id: int, at) -> None:
    from apps.messenger.services import members, read

    from apps.messenger.models import Message
    from apps.messenger.services import live

    chat = members.get_chat(user, chat_id)
    read.mark(chat, user, read.parse_at(at.isoformat() if at is not None else None), enqueue=False)
    message = (Message.objects.filter(chat=chat, deleted_at__isnull=True)
               .order_by("-created_at", "-id").first())
    live.enqueue(chat.pk, message.pk if message is not None else None, "read",
                 owner_id=message.author_id if message is not None else None)


class MessengerConsumer(SessionGuardMixin, AsyncWebsocketConsumer):
    """Соединение беседы: личная группа кадров, `sync` и `read`, переход на список при удалении чата."""

    user_id = None
    chat_id = None
    link_staff = False

    def check_interval(self) -> float:
        return CHECK_INTERVAL

    async def connect(self):
        if not await self.guard_connect():
            return
        user = self.scope.get("user")
        self.user_id = user.pk
        chat = _chat_id(self._query().get("chat", [None])[0])
        if chat is None:
            await self.accept()
            await self.close(code=CLOSE_CHAT)
            return
        if not await _visible(user, chat):
            await self.accept()
            await self.close(code=CLOSE_FORBIDDEN)
            return
        self.chat_id = chat
        self.link_staff = await database_sync_to_async(_staff_view)(user)
        # Подписка до `accept()`: клиент сразу получает соединение уже в личной группе кадров.
        try:
            await self.channel_layer.group_add(self._group(), self.channel_name)
        except Exception:
            await self.close(code=CLOSE_LAYER)
            return
        await self.accept()
        self.start_guard()

    async def disconnect(self, code):
        self.stop_guard()
        if self.chat_id is not None:
            await self.channel_layer.group_discard(self._group(), self.channel_name)

    def _query(self) -> dict:
        from urllib.parse import parse_qs

        return parse_qs(self.scope.get("query_string", b"").decode("utf-8"))

    def _group(self) -> str:
        return f"messenger.u.{self.user_id}"

    async def receive(self, text_data=None, bytes_data=None):
        if text_data is None:
            return
        if len(text_data.encode("utf-8")) > LIMIT_BYTES:
            await self.close(code=CLOSE_TOO_BIG)
            return
        try:
            payload = json.loads(text_data)
        except (json.JSONDecodeError, TypeError, ValueError):
            return
        if not isinstance(payload, dict):
            return
        if "sync" in payload:
            await self._handle_sync(payload.get("sync"))
        elif "read" in payload:
            await self._handle_read(payload.get("read"))

    async def _handle_sync(self, payload) -> None:
        """`sync` со своим чатом — служебный кадр `#messenger-synced`; чужой и неверный номер — тишина."""
        if not isinstance(payload, dict) or payload.get("chat") != self.chat_id:
            return
        await self.send(text_data='<div id="messenger-synced" hx-swap-oob="true"></div>')

    async def _handle_read(self, payload) -> None:
        """`read` со своим чатом и верным временем — отметка прочтения и рассылка автору (FR-659)."""
        if not isinstance(payload, dict) or payload.get("chat") != self.chat_id:
            return
        at = _moment(payload.get("at"))
        if at is None:
            return
        await _mark_read(self.scope.get("user"), self.chat_id, at)

    async def messenger_event(self, event) -> None:
        """Кадр рассылки: фильтр по чату, замена/вставка/удаление сообщения или переход на список."""
        if event.get("chat") != self.chat_id:
            return
        action = event.get("action")
        message_id = event.get("message")
        if action == "chat_delete":
            await self.send(text_data='<div data-hx-redirect="/messenger/" hx-swap-oob="true">HX-Redirect</div>')
            return
        html = self._variant(event)
        if not html:
            return
        if action == "delete" and message_id is not None:
            await self.send(text_data=f'<div id="m{message_id}" hx-swap-oob="delete"></div>')
            return
        if action == "read":
            line = html[html.find("<p id=\"messenger-read\""):] if "<p id=\"messenger-read\"" in html else ""
            if line:
                await self.send(text_data=line)
            return
        oob = "beforeend:#messenger-messages" if action == "new" else "outerHTML"
        await self.send(text_data=html.replace("<article ", f'<article hx-swap-oob="{oob}" ', 1))

    def _variant(self, event) -> str:
        role = "author" if event.get("owner") == self.user_id else "reader"
        return event.get("variants", {}).get(f"{role}:{int(self.link_staff)}", "")