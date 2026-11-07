"""Общие типы ошибок служб ленты (CONTRACT-007, §5.1)."""


class FeedError(Exception):
    """Отказ службы с кодом текста, полем формы и подстановками."""

    def __init__(self, code: str, field: str = "", params: dict | None = None):
        self.code = code
        self.field = field
        self.params = dict(params or {})
        super().__init__(code)


class PdnFound(Exception):
    """Предупреждение о найденных персональных данных, не отказ службы."""

    def __init__(self, found: list[str]):
        self.found = list(dict.fromkeys(found))[:20]
        # Не помещаем найденные персональные данные в текст исключения.
        super().__init__("pdn_found")
