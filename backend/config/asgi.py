"""ASGI-вход портала: gunicorn -k uvicorn_worker.UvicornWorker config.asgi:application.

Сервер запускается на ASGI с первого дня (PLAN-001, «Сверка с конституцией»). С среза 004
http идёт в Django, websocket — через проверку Origin, сессию и маршрутизатор `notify`
(PLAN-004, «Запуск»).
"""
import os

from channels.auth import AuthMiddlewareStack
from channels.routing import ProtocolTypeRouter, URLRouter
from channels.security.websocket import AllowedHostsOriginValidator
from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# Приложение Django создаётся до импорта маршрутов: иначе модели загрузятся раньше реестра приложений.
django_asgi_app = get_asgi_application()

from apps.notify import routing as notify_routing  # noqa: E402

application = ProtocolTypeRouter({
    "http": django_asgi_app,
    "websocket": AllowedHostsOriginValidator(AuthMiddlewareStack(URLRouter(notify_routing.websocket_urlpatterns))),
})
