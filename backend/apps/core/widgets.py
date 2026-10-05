"""Поля дат портала: форматы ввода, разбор строки и виджет `PortalDateInput` (CONTRACT-002, § 3, § 9.6; FR-148)."""
import datetime
from zoneinfo import ZoneInfo

from django import forms
from django.forms.renderers import TemplatesSetting
from django.utils import timezone

MOSCOW = ZoneInfo("Europe/Moscow")

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


def moscow_today() -> datetime.date:
    """Сегодняшняя дата по Москве (NFR-107)."""
    return timezone.now().astimezone(MOSCOW).date()


class PortalDateInput(forms.DateInput):
    """Поле даты портала: текстовое поле с маской ДД.ММ.ГГГГ и кнопка «Выбрать дату» (FR-148).

    Кнопка загружает сетку месяца `/ui/date-picker/?month=ГГГГ-ММ` HTMX-запросом; месяц в адресе всегда текущий
    по Москве, значение поля в адрес не попадает (дополнение 63). Шаблон лежит в `templates/`, а не в приложении,
    поэтому разметка берётся через `TemplatesSetting`, какой бы отрисовщик ни передала форма.
    """

    template_name = "widgets/date_field.html"
    format = "%d.%m.%Y"

    def __init__(self, attrs=None, format=None):
        super().__init__(attrs=attrs, format=format or self.format)

    def render(self, name, value, attrs=None, renderer=None):
        return super().render(name, value, attrs=attrs, renderer=TemplatesSetting())

    def get_context(self, name, value, attrs):
        context = super().get_context(name, value, attrs)
        widget = context["widget"]
        field_attrs = {key: val for key, val in widget["attrs"].items()
                       if key not in ("type", "name", "value", "inputmode", "placeholder")}
        field_attrs.setdefault("id", f"id_{name}")
        field_attrs["class"] = field_attrs.get("class", "form-control")
        widget["attrs"] = field_attrs
        widget["field_id"] = field_attrs["id"]
        widget["picker_month"] = moscow_today().strftime("%Y-%m")
        return context
