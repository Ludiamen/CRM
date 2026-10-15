"""Маршруты: «Уведомления», колокольчик, «Мои уведомления», настройки администратора, `/sw.js` (PLAN-004, «Контракты»).

Объявлены все маршруты среза сразу (T-4230); представления «Мои уведомления» и страницы администратора — в
`views/me.py` и `views/admin.py` (до T-4231 и T-4232 — заглушки 404). Канал в пути — `telegram` или `max`: другое
значение не подходит под образец, и ответ — 404 раньше всего прочего.
"""
from django.urls import path, re_path

from .views import admin, me, pages

urlpatterns = [
    path("notifications/", pages.notification_list, name="notify-list"),
    path("notifications/bell/", pages.bell_panel, name="notify-bell"),
    path("notifications/read-all/", pages.notification_read_all, name="notify-read-all"),
    path("notifications/<int:notification_id>/open/", pages.notification_open, name="notify-open"),
    path("notifications/<int:notification_id>/read/", pages.notification_read, name="notify-read"),
    path("sw.js", pages.service_worker, name="notify-sw"),
    path("me/notifications/", me.notifications_page, name="notify-me"),
    path("me/notifications/push/", me.push_save, name="notify-push-save"),
    path("me/notifications/push/<int:subscription_id>/delete/", me.push_delete, name="notify-push-delete"),
    re_path(r"^me/notifications/bind/(?P<channel>telegram|max)/$", me.bind, name="notify-bind"),
    re_path(r"^me/notifications/unbind/(?P<channel>telegram|max)/$", me.unbind, name="notify-unbind"),
    path("settings/notifications/", admin.settings_page, name="notify-admin"),
]
