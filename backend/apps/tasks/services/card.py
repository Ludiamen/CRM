"""Части карточки задачи (PLAN-014, T-14014)."""
from django.utils.html import format_html

from apps.core import extensions


def card_parts(request, task) -> list:
    ref = extensions.TaskRef(number=task.pk, deleted=task.deleted_at is not None)
    found = []
    for factory in extensions.registered("task_card_parts"):
        try:
            records = factory()
        except Exception:  # noqa: BLE001 — чужая регистрация не роняет карточку
            continue
        for record in sorted(records, key=lambda item: item.order):
            try:
                html = record.render(request, ref)
            except Exception:  # noqa: BLE001
                continue
            if html:
                found.append(format_html('<div data-card-part="{}">{}</div>', record.key, html))
    return found
