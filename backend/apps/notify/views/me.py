"""«Мои уведомления» (`/me/notifications/` и вложенные маршруты, CONTRACT-004, 13.2): заглушки T-4230, представления
пишет T-4231. До того каждый отвечает 404."""
from django.http import Http404


def notifications_page(request):
    """GET, POST `/me/notifications/` — таблица, тихие часы, устройства, привязки (T-4231)."""
    raise Http404


def push_save(request):
    """POST `/me/notifications/push/` — сохранить подписку этого устройства (T-4231)."""
    raise Http404


def push_delete(request, subscription_id: int):
    """POST `/me/notifications/push/<id>/delete/` — удалить устройство (T-4231)."""
    raise Http404


def bind(request, channel: str):
    """POST `/me/notifications/bind/<канал>/` — новый код привязки (T-4231)."""
    raise Http404


def unbind(request, channel: str):
    """POST `/me/notifications/unbind/<канал>/` — отвязать канал (T-4231)."""
    raise Http404
