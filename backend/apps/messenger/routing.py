"""Маршрут соединения беседы `/ws/messenger/` (срез 008, T-8213; CONTRACT-008, 5.5, 11.4).

`chat` — обязательный параметр строки запроса (номер чата в пути не несёт). Проверка Origin и сессии — в
`config/asgi.py` (`AllowedHostsOriginValidator`, `AuthMiddlewareStack`) и в `SessionGuardMixin` потребителя.
"""
from django.urls import path

from apps.messenger.consumers import MessengerConsumer

websocket_urlpatterns = [
    path("ws/messenger/", MessengerConsumer.as_asgi()),
]
