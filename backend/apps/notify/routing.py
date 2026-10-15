"""Маршруты WebSocket: обработчик соединения `/ws/notify/` (PLAN-004, «Где живёт код»)."""
from django.urls import path

from .consumers import NotifyConsumer

websocket_urlpatterns = [path("ws/notify/", NotifyConsumer.as_asgi())]
