"""Поля дат портала: форматы ввода и разбор строки (CONTRACT-002, § 5; виджет `PortalDateInput` добавляет T-2238)."""
import datetime

DATE_INPUT_FORMATS = ("%d.%m.%Y", "%Y-%m-%d")


def parse_date(value: str) -> datetime.date | None:
    """Дата из строки в формате ДД.ММ.ГГГГ или ГГГГ-ММ-ДД; пустая или неразборная строка — `None`."""
    text = (value or "").strip()
    for fmt in DATE_INPUT_FORMATS:
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None
