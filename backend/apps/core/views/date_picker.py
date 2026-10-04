"""Поле даты: сетка месяца с отметками дней (FR-148; T-2238).

Пока заглушка (T-2230a): проверка входа окончательная, ответ — 404; тело заменяет T-2238.
"""
from django.contrib.auth.decorators import login_required
from django.http import Http404
from django.views.decorators.http import require_GET


@login_required
@require_GET
def date_picker(request):
    """`/ui/date-picker/` — фрагмент сетки месяца (`?month=ГГГГ-ММ`)."""
    raise Http404
