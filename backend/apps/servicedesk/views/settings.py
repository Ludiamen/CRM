"""Настройки и очереди сервис-деска: `/servicedesk/` и `/servicedesk/queues/` (CONTRACT-003, 12.6).

Сейчас в модуле только заглушки: маршруты объявлены в T-3230 (решение 1 волны (в)), T-3234 заменяет тела.
"""
from django.http import Http404


def settings_page(request):
    """Заглушка до T-3234: маршрут объявлен в T-3230 (решение 1 волны (в))."""
    raise Http404


def queues_page(request):
    """Заглушка до T-3234: маршрут объявлен в T-3230 (решение 1 волны (в))."""
    raise Http404
