"""Заявители и загрузка таблицы заявителей (CONTRACT-003, 12.6).

Сейчас в модуле только заглушки: маршруты объявлены в T-3230 (решение 1 волны (в)), T-3235 заменяет тела.
"""
from django.http import Http404


def requester_list(request):
    """Заглушка до T-3235: маршрут объявлен в T-3230 (решение 1 волны (в))."""
    raise Http404


def import_start(request):
    """Заглушка до T-3235: маршрут объявлен в T-3230 (решение 1 волны (в))."""
    raise Http404


def import_sample_csv(request):
    """Заглушка до T-3235: маршрут объявлен в T-3230 (решение 1 волны (в))."""
    raise Http404


def import_sample_xlsx(request):
    """Заглушка до T-3235: маршрут объявлен в T-3230 (решение 1 волны (в))."""
    raise Http404


def import_preview(request, import_id):
    """Заглушка до T-3235: маршрут объявлен в T-3230 (решение 1 волны (в))."""
    raise Http404


def requester_edit(request, requester_id):
    """Заглушка до T-3235: маршрут объявлен в T-3230 (решение 1 волны (в))."""
    raise Http404


def requester_delete(request, requester_id):
    """Заглушка до T-3235: маршрут объявлен в T-3230 (решение 1 волны (в))."""
    raise Http404
