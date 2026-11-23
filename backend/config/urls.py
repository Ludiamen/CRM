"""Маршруты портала. Разделы администратора (`/staff/`, `/roles/`, `/audit/`, `/settings/`) подключают следующие проходы; срез 003 — `apps.servicedesk.urls`, срез 008 — `apps.messenger.urls`."""
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

if apps.is_installed("apps.messenger"):
    # Адреса мессенджера — только у установленного модуля (T-8001, Этап 3).
    urlpatterns.append(path("", include("apps.messenger.urls")))  # /messenger/…

if apps.is_installed("apps.tasks"):
    # Адреса задач — только у установленного модуля (T-9001, Этап 1).
    urlpatterns.append(path("", include("apps.tasks.urls")))  # /tasks/…, /settings/tasks/…

if apps.is_installed("apps.instructions"):
    # Адреса поручений — только у установленного модуля (T-10001, Этап 1).
    urlpatterns.append(path("", include("apps.instructions.urls")))  # /instructions/…, /settings/instructions/…

handler400 = "apps.core.views.pages.bad_request"
handler403 = "apps.core.views.pages.forbidden"
handler404 = "apps.core.views.pages.not_found"
handler500 = "apps.core.views.pages.server_error"
