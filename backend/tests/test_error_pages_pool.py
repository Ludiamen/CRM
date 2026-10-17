"""Страницы ошибок не оставляют соединение базы в потоке, где отрисованы (этап 4 среза 004, утечка слота пула).

В асинхронной цепочке Django ответ на исключение строится в потоке общего пула (thread_sensitive=False);
request_finished закрывает соединения только потока запроса. Тест вызывает обработчики в отдельном потоке.
"""
import threading

import pytest
from django.db import connections
from django.test import RequestFactory
from django.urls import resolve

from apps.core.views import pages

pytestmark = pytest.mark.django_db


def _in_thread(handler, *args):
    result = {}

    def run():
        try:
            request = RequestFactory().get("/нет-такой-страницы/")
            from django.contrib.auth.models import AnonymousUser
            request.user = AnonymousUser()
            request.session = {}
            result["status"] = handler(request, *args).status_code
            # обращение к базе после ответа: соединение должно быть уже отдано
            result["connection"] = connections["default"].connection
        except BaseException as exc:  # noqa: BLE001
            result["error"] = exc
        finally:
            connections.close_all()

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(30)
    assert "error" not in result, result.get("error")
    return result


@pytest.mark.parametrize("handler,args,status", [
    (pages.not_found, (None,), 404),
    (pages.forbidden, (None,), 403),
    (pages.bad_request, (None,), 400),
    (pages.server_error, (), 500),
    (pages.csrf_failure, ("x",), 403),
])
def test_error_page_releases_connection(handler, args, status):
    result = _in_thread(handler, *args)
    assert result["status"] == status
    assert result["connection"] is None


def test_not_found_thread_uses_database_then_releases():
    """Страница 404 с оболочкой действительно читает базу в своём потоке, и всё равно соединение отдано."""
    seen = {}

    def run():
        request = RequestFactory().get("/x/")
        from django.contrib.auth.models import AnonymousUser
        request.user = AnonymousUser()
        request.session = {}
        connections["default"].ensure_connection()
        seen["before"] = connections["default"].connection is not None
        pages.not_found(request, None)
        seen["after"] = connections["default"].connection

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(30)
    assert seen["before"] is True and seen["after"] is None


def test_not_found_page_looks_as_before(client):
    response = client.get("/favicon.ico")
    assert response.status_code == 404
    assert "Vary" in response and "HX-Request" in response["Vary"]
    assert b"<html" in response.content.lower()


def test_handlers_registered():
    from config import urls
    assert urls.handler400.endswith("pages.bad_request")
    assert urls.handler404.endswith("pages.not_found")
