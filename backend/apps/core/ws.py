"""Общая проверка сессии соединений WebSocket (PLAN-007, «Живые обновления» → «Проверка сессии», «Исправление
дефекта среза 004»; CONTRACT-007, раздел 3.2).

Примесь `SessionGuardMixin` для `AsyncWebsocketConsumer`: `ws_state` при подключении (не «ok» — принять и закрыть
кодом 4401), затем цикл — сон на `self.check_interval()` секунд, хук `on_check()`, `ws_state` (не «ok» — закрыть
4401). Любая ошибка в цикле пишет предупреждение в журнал `apps.core.ws` и закрывает соединение кодом 1013
(исправление дефекта среза 004: прежде цикл молча прекращался и соединение оставалось без проверки).
"""
import asyncio
import logging

from channels.db import database_sync_to_async

from apps.core.services import sessions

log = logging.getLogger(__name__)

CLOSE_SESSION = 4401       # код закрытия: расширение `ws` после него не переподключается
CLOSE_TRY_LATER = 1013     # код закрытия: расширение `ws` переподключается с задержкой до 64 с


class SessionGuardMixin:
    """Проверка сессии соединения при подключении и раз в `check_interval()` секунд (FR-627)."""

    _guard_task = None

    async def guard_connect(self) -> bool:
        """Состояние сессии при подключении: не «ok» — принять и закрыть 4401 (возвращает `False`, не продолжать)."""
        state = await database_sync_to_async(sessions.ws_state)(self.scope.get("session"), self.scope.get("user"))
        if state != "ok":
            await self.accept()
            await self.close(code=CLOSE_SESSION)
            return False
        return True

    def start_guard(self) -> None:
        """Запускает задачу цикла проверки сессии."""
        self._guard_task = asyncio.ensure_future(self.guard_loop())

    def stop_guard(self) -> None:
        """Отменяет задачу цикла проверки (в `disconnect`)."""
        task = getattr(self, "_guard_task", None)
        if task is not None:
            task.cancel()
            self._guard_task = None

    async def guard_loop(self) -> None:
        """Цикл: сон `check_interval()`, хук `on_check()`, `ws_state`; не «ok» — закрыть 4401 и выйти."""
        try:
            while True:
                await asyncio.sleep(self.check_interval())
                await self.on_check()
                state = await database_sync_to_async(sessions.ws_state)(self.scope.get("session"),
                                                                        self.scope.get("user"))
                if state != "ok":
                    await self.close(code=CLOSE_SESSION)
                    return
        except asyncio.CancelledError:
            raise
        except Exception as error:
            log.warning("Проверка сессии соединения прервана: %s", type(error).__name__)
            await self.close(code=CLOSE_TRY_LATER)

    def check_interval(self) -> float:
        """Секунды между проверками; читается при каждом ожидании. Потребители переопределяют."""
        return 25

    async def on_check(self) -> None:
        """Хук перед каждой проверкой сессии; по умолчанию ничего, у потребителей — отметка присутствия."""
