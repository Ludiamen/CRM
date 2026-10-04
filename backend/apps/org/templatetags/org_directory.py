"""Помощник колонки «Подразделение» списка сотрудников: названия узлов всей страницы — одним запросом (NFR-102)."""
from django import template

from apps.org.models import Membership

register = template.Library()


@register.simple_tag
def unit_names(person, page) -> str:
    """Названия узлов сотрудника через запятую; при первом вызове читает членства всей страницы разом."""
    cache = getattr(page, "_unit_names", None)
    if cache is None:
        cache = {}
        rows = (Membership.objects.filter(user_id__in=[row.pk for row in page])
                .select_related("unit").order_by("unit__path"))
        for row in rows:
            cache.setdefault(row.user_id, []).append(row.unit.name)
        page._unit_names = cache
    return ", ".join(cache.get(person.pk, []))
