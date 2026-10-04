"""Ошибка службы оргструктуры (CONTRACT-002, § 4)."""


class OrgError(Exception):
    """Единственная ошибка `org`: `code` — строка из таблицы контракта, `str(error)` — текст по-русски."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message
