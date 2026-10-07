"""Ошибка и порция служб сервис-деска (CONTRACT-003, 6.1)."""
from dataclasses import dataclass


class ServiceDeskError(Exception):
    """Единственная ошибка `servicedesk`: `code` — строка из таблицы контракта, `str(error)` — текст по-русски."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class Batch:
    """Итог одной порции фоновой работы.

    `done` — сколько обработано в порции; `more` — есть ли следующая порция; `last_id` и `last` — где остановились
    (число или составной курсор), чтобы следующая порция продолжила с этого места.
    """

    done: int
    more: bool
    last_id: int | None = None
    last: str | tuple | None = None
