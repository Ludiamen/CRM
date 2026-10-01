"""Маршруты ядра: вход и доступ, профиль, активация (срез 001). Разделы администратора добавляют следующие проходы."""
from django.urls import path, re_path

from .views import activation, auth, me, pages

urlpatterns = [
    path("", pages.home, name="home"),
    path("health/", pages.health, name="health"),
    re_path(r"^media/(?P<path>.+)$", pages.media, name="media"),
    # вход и восстановление
    path("login/", auth.login_view, name="login"),
    path("login/code/", auth.login_code, name="login-code"),
    path("logout/", auth.logout_view, name="logout"),
    path("password/forgot/", auth.forgot, name="password-forgot"),
    path("password/reset/exchange/", auth.reset_exchange, name="password-reset-exchange"),
    path("password/reset/", auth.reset_password, name="password-reset"),
    # мастер активации
    path("activate/", activation.start, name="activate"),
    path("activate/exchange/", activation.exchange, name="activate-exchange"),
    path("activate/<str:step>/", activation.step, name="activate-step"),
    # профиль и «Безопасность»
    path("me/", me.profile, name="me"),
    path("me/security/", me.security, name="me-security"),
    path("me/security/password/", me.password, name="me-password"),
    path("me/security/logout-everywhere/", me.logout_everywhere, name="me-logout-everywhere"),
    path("me/security/totp/", me.totp_page, name="me-totp"),
    path("me/security/backup-codes/", me.backup_codes_page, name="me-backup-codes"),
    path("me/security/backup-codes/new/", me.new_backup_codes, name="me-backup-codes-new"),
    path("me/security/devices/", me.devices_page, name="me-devices"),
    path("me/security/devices/<int:device_id>/close/", me.device_close, name="me-device-close"),
    path("me/security/devices/<int:device_id>/forget/", me.device_forget, name="me-device-forget"),
    path("me/security/history/", me.history_page, name="me-history"),
]
