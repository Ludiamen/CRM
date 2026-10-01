"""Соединение с Valkey для счётчиков (блокировки, лимиты запросов)."""
import django_rq
from django.conf import settings

_connections: dict = {}


def conn():
    """Соединение на адресе из настроек; пул потокобезопасен, соединение одно на адрес."""
    url = settings.VALKEY_URL
    if url not in _connections:
        _connections[url] = django_rq.get_connection("mail")
    return _connections[url]
