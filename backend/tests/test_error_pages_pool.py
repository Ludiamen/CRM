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


# --- Слой ErrorResponseInRequestThreadMiddleware: страница ошибки представления строится в потоке запроса ---
from django.core.exceptions import PermissionDenied  # noqa: E402
from django.http import Http404  # noqa: E402
from django.urls import path  # noqa: E402


def _raise_404(request):
    raise Http404("нет")


def _raise_403(request):
    raise PermissionDenied("нельзя")


def _raise_500(request):
    raise RuntimeError("сбой")


urlpatterns = [
    path("t404/", _raise_404),
    path("t403/", _raise_403),
    path("t500/", _raise_500),
]
handler400 = "apps.core.views.pages.bad_request"
handler403 = "apps.core.views.pages.forbidden"
handler404 = "apps.core.views.pages.not_found"
handler500 = "apps.core.views.pages.server_error"


def test_middleware_is_registered_last():
    from django.conf import settings
    assert settings.MIDDLEWARE[-1] == "apps.core.middleware.ErrorResponseInRequestThreadMiddleware"


@pytest.mark.parametrize("url,status", [("/t404/", 404), ("/t403/", 403), ("/t500/", 500)])
def test_view_exception_page_built_by_process_exception(client, settings, monkeypatch, url, status):
    from apps.core import middleware
    settings.ROOT_URLCONF = __name__
    calls = []
    original = middleware.response_for_exception

    def spy(request, exc):
        calls.append(type(exc))
        return original(request, exc)

    monkeypatch.setattr(middleware, "response_for_exception", spy)
    client.raise_request_exception = False
    response = client.get(url)
    assert response.status_code == status
    assert len(calls) == 1
    if status != 500:  # страница 500 — простой текст по замыслу server_error
        assert b"<html" in response.content.lower()
        assert "HX-Request" in response["Vary"]
    assert response["Cache-Control"] == "no-store"


@pytest.mark.parametrize("url,handler", [("/t404/", pages.not_found), ("/t403/", pages.forbidden)])
def test_error_page_same_as_handler(client, settings, url, handler):
    """Вид страницы прежний: тело совпадает с тем, что отдаёт обработчик ошибок напрямую."""
    from django.contrib.auth.models import AnonymousUser
    settings.ROOT_URLCONF = __name__
    response = client.get(url)
    request = RequestFactory().get(url)
    request.user = AnonymousUser()
    request.session = {}
    direct = handler(request, None)
    assert response.status_code == direct.status_code
    assert response.content == direct.content


def test_server_error_signal_and_log_once(client, settings, caplog):
    from django.core.signals import got_request_exception
    settings.ROOT_URLCONF = __name__
    got = []
    receiver = lambda sender, **kw: got.append(1)  # noqa: E731
    got_request_exception.connect(receiver)
    try:
        client.raise_request_exception = False
        with caplog.at_level("ERROR", logger="django.request"):
            response = client.get("/t500/")
    finally:
        got_request_exception.disconnect(receiver)
    assert response.status_code == 500
    assert len(got) == 1
    assert len([r for r in caplog.records if r.name == "django.request" and r.levelname == "ERROR"]) == 1


# --- Resolver404: страница «адреса нет» тоже строится слоем, в потоке запроса ---
def test_unresolved_path_page_built_by_layer(client, monkeypatch):
    from django.contrib.auth.models import AnonymousUser
    from apps.core import middleware
    calls = []
    original = middleware.response_for_exception
    monkeypatch.setattr(middleware, "response_for_exception",
                        lambda request, exc: calls.append(type(exc).__name__) or original(request, exc))
    response = client.get("/нет-такого-адреса/")
    assert response.status_code == 404
    assert calls == ["Resolver404"]
    request = RequestFactory().get("/x/")
    request.user = AnonymousUser()
    request.session = {}
    assert response.content == pages.not_found(request, None).content


def test_missing_slash_still_redirects(client):
    response = client.get("/notifications")
    assert response.status_code in (301, 302)
    assert response["Location"].endswith("/notifications/")


def test_existing_path_untouched_by_layer(client, monkeypatch):
    from apps.core import middleware
    calls = []
    monkeypatch.setattr(middleware, "response_for_exception", lambda r, e: calls.append(1))
    client.get("/login/")
    assert calls == []
