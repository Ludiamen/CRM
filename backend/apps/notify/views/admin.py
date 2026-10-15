"""Страница администратора (`/settings/notifications/`, CONTRACT-004, 13.3): заглушка T-4230, представление пишет
T-4232. До того отвечает 404."""
from django.http import Http404


def settings_page(request):
    """GET, POST `/settings/notifications/` — каналы, значения по умолчанию, сроки (T-4232)."""
    raise Http404
