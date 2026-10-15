"""Ошибка служб уведомлений (CONTRACT-004, 6.1)."""


class NotifyError(Exception):
    """Единственная ошибка `notify`: `code` — строка из таблицы контракта, `field` — имя поля формы или пусто."""

    def __init__(self, code: str, message: str, *, field: str = ""):
        super().__init__(message)
        self.code = code
        self.message = message
        self.field = field
