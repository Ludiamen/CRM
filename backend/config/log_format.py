"""Форматтер журнала ошибок запросов без текста исключения.

В тексте ошибок базы данных бывают значения полей записей (персональные данные, 152-ФЗ), поэтому в вывод
контейнера идут время, уровень, логгер, сообщение Django («Internal Server Error: /путь/»), метод запроса,
класс исключения и строки стека, но не `str(exc)`; для исключений цепочки (`__cause__`, `__context__`) — то же
самое (решение 64 задач среза 006)."""

import logging
import traceback


class NoExceptionTextFormatter(logging.Formatter):
    """Как обычная строка журнала, но исключение — только класс и стек, без текста."""

    def __init__(self):
        super().__init__("%(asctime)s %(levelname)s %(name)s %(message)s")

    def format(self, record):
        # Строку без исключения строит logging.Formatter; исключение добавляем сами один раз. exc_text записи не
        # используется: его мог заполнить полным текстом другой обработчик раньше нашего.
        exc_info, exc_text = record.exc_info, record.exc_text
        record.exc_info, record.exc_text = None, None
        try:
            line = super().format(record)
        finally:
            record.exc_info, record.exc_text = exc_info, exc_text
        method = getattr(getattr(record, "request", None), "method", None)
        if method:
            line += f" [{method}]"
        if exc_info and exc_info[1] is not None:
            line += "\n" + self._without_text(exc_info[1])
        return line

    @staticmethod
    def _without_text(exc):
        parts, seen = [], set()
        while exc is not None and id(exc) not in seen:
            seen.add(id(exc))
            stack = "".join(traceback.format_tb(exc.__traceback__)) if exc.__traceback__ else ""
            parts.append(f"{type(exc).__module__}.{type(exc).__qualname__}\n{stack}".rstrip("\n"))
            if exc.__cause__ is not None:
                exc = exc.__cause__
            elif not exc.__suppress_context__:
                exc = exc.__context__
            else:
                exc = None
        return "\n".join(parts)
