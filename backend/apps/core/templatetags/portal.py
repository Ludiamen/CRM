"""Фильтры шаблонов: «было / стало» журнала и значения настроек в человеческом виде (T-248)."""
from django import template

from apps.core.services import audit_search, security_settings

register = template.Library()

FIELD_LABELS = dict([
    ("email", "почта"), ("full_name", "ФИО"), ("position", "должность"), ("phone", "телефон"),
    ("contacts", "контакты"), ("state", "состояние"), ("roles", "роли"), ("name", "название"),
    ("permissions", "права"), ("reason", "причина"), ("logo", "логотип"), ("devices", "устройств второго фактора"),
    ("expires_at", "действует до"), ("status", "статус"),
])
STATE_TITLES = {"invited": "приглашён", "active": "активен", "blocked": "заблокирован"}


def _label(key: str) -> str:
    if key in FIELD_LABELS:
        return FIELD_LABELS[key]
    bound = security_settings.BOUNDS.get(key)
    return bound.title if bound else key


def _text(key: str, value) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "да" if value else "нет"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value) or "—"
    if key == "state":
        return STATE_TITLES.get(str(value), str(value))
    return str(value)


@register.filter
def pairs(value):
    """Словарь «было» или «стало» — список (название поля, значение) для вывода."""
    if not isinstance(value, dict):
        return []
    return [(_label(str(key)), _text(str(key), item)) for key, item in value.items()]


@register.filter
def action_title(code):
    """Русское название события журнала; незнакомый код показывается как есть."""
    return audit_search.ACTION_TITLES.get(code, code)
