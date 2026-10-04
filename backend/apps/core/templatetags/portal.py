"""Фильтры шаблонов: «было / стало» журнала и значения настроек в человеческом виде (T-248).

Названия живут в `services/audit_labels.py` (общие для страницы и выгрузки CSV); здесь — только фильтры.
"""
from django import template

from apps.core.services import audit_labels, audit_search

register = template.Library()


@register.filter
def pairs(value):
    """Словарь «было» или «стало» — список (название поля, значение) для вывода."""
    return audit_labels.pairs(value)


@register.filter
def action_title(code):
    """Русское название события журнала; незнакомый код показывается как есть."""
    return audit_search.ACTION_TITLES.get(code, code)


@register.filter
def side_pairs(event, side):
    """«Было» или «Стало» события: если обе стороны — словари, показываются только изменившиеся поля."""
    return audit_labels.side_pairs(event, side)


@register.filter
def object_label(kind, object_id=""):
    """Вид объекта по-русски: «сотрудник № 1»; незнакомый вид показывается как есть."""
    return audit_labels.object_label(kind, object_id)
