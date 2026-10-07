"""Справочники сервис-деска (CONTRACT-003, 12.6).

Сейчас в модуле только заглушки: маршруты объявлены в T-3230 (решение 1 волны (в)), T-3234 заменяет тела.
"""
from django.http import Http404


def dictionary_list(request, kind):
    """Заглушка до T-3234: маршрут объявлен в T-3230 (решение 1 волны (в))."""
    raise Http404


def dictionary_new(request, kind):
    """Заглушка до T-3234: маршрут объявлен в T-3230 (решение 1 волны (в))."""
    raise Http404


def dictionary_edit(request, kind, item_id):
    """Заглушка до T-3234: маршрут объявлен в T-3230 (решение 1 волны (в))."""
    raise Http404


def dictionary_archive(request, kind, item_id):
    """Заглушка до T-3234: маршрут объявлен в T-3230 (решение 1 волны (в))."""
    raise Http404


def dictionary_restore(request, kind, item_id):
    """Заглушка до T-3234: маршрут объявлен в T-3230 (решение 1 волны (в))."""
    raise Http404


def dictionary_delete(request, kind, item_id):
    """Заглушка до T-3234: маршрут объявлен в T-3230 (решение 1 волны (в))."""
    raise Http404
