"""Маршруты портала. Разделы администратора (`/staff/`, `/roles/`, `/audit/`, `/settings/`) подключают следующие проходы; срез 003 — `apps.servicedesk.urls`."""
from django.urls import include, path

urlpatterns = [
    path("", include("apps.core.urls")),
    path("", include("apps.org.urls")),
    path("", include("apps.servicedesk.urls")),
    path("", include("apps.notify.urls")),
    path("", include("apps.knowledge.urls")),
]

handler400 = "apps.core.views.pages.bad_request"
handler403 = "apps.core.views.pages.forbidden"
handler404 = "apps.core.views.pages.not_found"
handler500 = "apps.core.views.pages.server_error"
