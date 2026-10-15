"""Обработчик соединения `/ws/notify/` (PLAN-004, «Колокольчик…» → «Соединение», «Что приходит по соединению»;
CONTRACT-004, раздел 11).

Кадры сервера — фрагменты HTML для расширения `ws` (`hx-swap-oob="true"`); значения экранирует шаблонизатор
(NFR-311). Соединение не продлевает сессию: `sessions.touch` отсюда не зовётся. Обращения к базе — через
`database_sync_to_async`, только при подключении, раз в `CHECK_INTERVAL` секунд и при сборке блока привязки;
`close_old_connections` и закрытие соединения базы вручную здесь не вызываются (дополнение 17.2).
"""
import asyncio
import logging

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncWebsocketConsumer

from apps.core.services import sessions

from .services import live
from .views import me, pages

log = logging.getLogger(__name__)

CHECK_INTERVAL = 25   # секунд между проверками сессии и обновлениями присутствия (решение 35 задач)
CLOSE_UNAUTHORIZED = 4401   # код закрытия: расширение `ws` после него не переподключается


def count_fragment(count: int) -> str:
    """Фрагмент числа непрочитанных: общий шаблон с колокольчиком страницы, в кадре с `hx-swap-oob` (T-4230)."""
    return pages.render_count(count, oob=True).strip()


def toast_fragment(toast: dict) -> str:
    """Фрагмент системного уведомления: пустой элемент со значениями в атрибутах (общий шаблон с колокольчиком)."""
    return pages.render_toast(toast, oob=True).strip()


def binding_fragment(channel: str, state: str) -> str:
    """Блок привязки канала в состоянии `bound`, `unbound` или `disabled`: общий шаблон со страницей «Мои
    уведомления» (CONTRACT-004, 14.3), в кадре с `hx-swap-oob`; кода привязки в кадре нет."""
    return me.render_binding(channel, state, oob=True).strip()


def _unread_count(user_id: int) -> int:
    return live._counts([user_id])[user_id]


def _binding_state(user_id: int, channel: str) -> str:
    return me.binding_state(user_id, channel)


class NotifyConsumer(AsyncWebsocketConsumer):
    """Живые обновления колокольчика сотрудника: число, системное уведомление, блок привязки."""

    user_id = None
    checker = None

    async def connect(self):
        user = self.scope.get("user")
        state = await database_sync_to_async(sessions.ws_state)(self.scope.get("session"), user)
        if state != "ok":
            await self.accept()
            await self.close(code=CLOSE_UNAUTHORIZED)
            return
        self.user_id = user.pk
        await self.accept()
        await self.channel_layer.group_add(live.group(self.user_id), self.channel_name)
        await database_sync_to_async(live.mark_online)(self.user_id, self.channel_name)
        count = await database_sync_to_async(_unread_count)(self.user_id)
        await self.send(text_data=count_fragment(count))
        self.checker = asyncio.ensure_future(self._check_loop())

    async def _check_loop(self):
        """Раз в `CHECK_INTERVAL` секунд: присутствие, затем состояние сессии; не «ok» — закрыть кодом 4401."""
        try:
            while True:
                await asyncio.sleep(CHECK_INTERVAL)   # имя модуля читается при каждом ожидании
                await database_sync_to_async(live.mark_online)(self.user_id, self.channel_name)
                state = await database_sync_to_async(sessions.ws_state)(self.scope.get("session"),
                                                                        self.scope.get("user"))
                if state != "ok":
                    await self.close(code=CLOSE_UNAUTHORIZED)
                    return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.warning("Проверка соединения уведомлений прервана: %s", type(error).__name__)

    async def disconnect(self, code):
        if self.checker is not None:
            self.checker.cancel()
            self.checker = None
        if self.user_id is not None:
            await self.channel_layer.group_discard(live.group(self.user_id), self.channel_name)
            await database_sync_to_async(live.mark_offline)(self.user_id, self.channel_name)

    async def receive(self, text_data=None, bytes_data=None):
        """Входящие кадры игнорируются: сессию они не продлевают."""

    async def notify_update(self, event):
        """Сообщение слоя каналов `notify.update`: один кадр из фрагментов в порядке число, уведомление, привязка."""
        parts = [count_fragment(int(event.get("count") or 0))]
        if event.get("toast"):
            parts.append(toast_fragment(event["toast"]))
        channel = event.get("binding")
        if channel:
            state = await database_sync_to_async(_binding_state)(self.user_id, channel)
            parts.append(binding_fragment(channel, state))
        await self.send(text_data="".join(parts))
