"""Маршруты ядра: вход и доступ, профиль, активация, разделы администратора (срез 001)."""
from django.urls import path, re_path

from .views import (activation, audit, auth, date_picker, locks, me, pages, photo, roles, settings, staff,
                    staff_actions)

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
    path("me/photo/", photo.me_photo, name="me-photo"),
    path("me/photo/delete/", photo.me_photo_delete, name="me-photo-delete"),
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
    # сотрудники (T-244, T-245, T-246)
    path("staff/", staff.staff_list, name="staff"),
    path("staff/new/", staff_actions.staff_new, name="staff-new"),
    path("staff/locks/", locks.locks, name="staff-locks"),
    path("staff/<int:user_id>/", staff.staff_card, name="staff-card"),
    path("staff/<int:user_id>/edit/", staff_actions.staff_edit, name="staff-edit"),
    path("staff/<int:user_id>/roles/", staff_actions.staff_roles, name="staff-roles"),
    path("staff/<int:user_id>/block/", staff_actions.staff_block, name="staff-block"),
    path("staff/<int:user_id>/unblock/", staff_actions.staff_unblock, name="staff-unblock"),
    path("staff/<int:user_id>/invite/", staff_actions.staff_invite, name="staff-invite"),
    path("staff/<int:user_id>/unlock/", staff_actions.staff_unlock, name="staff-unlock"),
    path("staff/<int:user_id>/reset-2fa/", staff_actions.staff_reset_2fa, name="staff-reset-2fa"),
    path("staff/<int:user_id>/photo/delete/", photo.staff_photo_delete, name="staff-photo-delete"),
    path("staff/<int:user_id>/photo/<uuid:photo_id>/<int:size>/", photo.staff_photo, name="staff-photo"),
    path("staff/<int:user_id>/logins/", staff.staff_logins, name="staff-logins"),
    # поле даты (T-2230a)
    path("ui/date-picker/", date_picker.date_picker, name="date-picker"),
    # роли (T-247)
    path("roles/", roles.role_list, name="roles"),
    path("roles/new/", roles.role_new, name="role-new"),
    path("roles/<int:role_id>/", roles.role_edit, name="role-edit"),
    path("roles/<int:role_id>/delete/", roles.role_delete, name="role-delete"),
    # журнал (T-248)
    path("audit/", audit.audit_list, name="audit"),
    path("audit/export.csv", audit.audit_export, name="audit-export"),
    # настройки (T-249)
    path("settings/portal/", settings.portal, name="settings-portal"),
    path("settings/security/", settings.security, name="settings-security"),
    path("settings/mail-log/", settings.mail_log, name="settings-mail-log"),
]
