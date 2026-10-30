"""Маршруты портала. Разделы администратора (`/staff/`, `/roles/`, `/audit/`, `/settings/`) подключают следующие проходы; срез 003 — `apps.servicedesk.urls`."""
from django.apps import apps
from django.urls import include, path

urlpatterns = [
    path("", include("apps.core.urls")),
    path("", include("apps.org.urls")),
    path("", include("apps.servicedesk.urls")),
    path("", include("apps.notify.urls")),
    path("", include("apps.knowledge.urls")),
    path("lists/", include("apps.lists.urls")),
    path("", include("apps.search.urls")),
]

if apps.is_installed("apps.feed"):
    urlpatterns.append(path("", include("apps.feed.urls")))  # /feed/…, /settings/feed/

handler400 = "apps.core.views.pages.bad_request"
handler403 = "apps.core.views.pages.forbidden"
handler404 = "apps.core.views.pages.not_found"
handler500 = "apps.core.views.pages.server_error"
