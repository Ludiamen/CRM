"""Маршруты WebSocket ленты (срез 007)."""
from django.urls import path

from .consumers import FeedConsumer

websocket_urlpatterns = [path("ws/feed/", FeedConsumer.as_asgi())]
