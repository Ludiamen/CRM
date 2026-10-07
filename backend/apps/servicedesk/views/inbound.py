"""Входящие письма: `/servicedesk/inbound/` и повторный разбор (CONTRACT-003, 12.6).

Сейчас в модуле только заглушки: маршруты объявлены в T-3230 (решение 1 волны (в)), T-3236 заменяет тела.
"""
from django.http import Http404


def inbound_list(request):
    """Заглушка до T-3236: маршрут объявлен в T-3230 (решение 1 волны (в))."""
    raise Http404


def inbound_retry(request, inbound_id):
    """Заглушка до T-3236: маршрут объявлен в T-3230 (решение 1 волны (в))."""
    raise Http404
