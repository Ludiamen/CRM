"""Отказ служб мессенджера `MessengerError` (срез 008; CONTRACT-008, 5).

Форма — как у `FeedError`/`ListsError`: `code` — ключ словаря `apps.messenger.texts.TEXTS` (разделы 13.1–13.2
контракта), `field` — имя поля формы для `[data-error="<поле>"]` (раздел 10.1), `params` — подстановки текста
(единственная — `purge_count`). Текст берётся из словаря при чтении `message`, поэтому служба может поднять отказ
до загрузки текстов и не дублирует строки по-русски.
"""


class MessengerError(Exception):
    """Отказ службы мессенджера: код, поле формы и подстановки текста."""

    def __init__(self, code: str, field: str = "", params: dict | None = None):
        self.code = code
        self.field = field
        self.params = dict(params or {})
        super().__init__(code)

    @property
    def message(self) -> str:
        """Готовый текст отказа из `TEXTS`; неизвестный код — пустая строка (наружу уходит `code`)."""
        from apps.messenger.texts import TEXTS

        text = TEXTS.get(self.code, "")
        return text.format(**self.params) if self.params else text

    def __str__(self) -> str:
        return self.message or self.code