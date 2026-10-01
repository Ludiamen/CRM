"""ASGI-вход портала: gunicorn -k uvicorn_worker.UvicornWorker config.asgi:application.

Channels в срезе 001 не нужен (появится в срезе 004), но сервер запускается на
ASGI с первого дня (PLAN-001, «Сверка с конституцией»).
"""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

application = get_asgi_application()
