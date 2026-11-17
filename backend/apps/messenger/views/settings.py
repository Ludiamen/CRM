"""Настройки портала → Мессенджер: «Общий чат» (срез 008, T-8206; CONTRACT-008, 10.1–10.2, 12.6).

Право ядра `settings.portal` проверяет декоратор раньше всего прочего: без него 403 на GET и POST, служба
настройки не вызывается (CONTRACT-008, 10.1). Здесь — галочка «Общий чат включён» и её сохранение; поле срока
хранения рисуется со значением строки настроек, а сохранение срока и второй шаг при уменьшении — T-8220.
Успех — 302 на ту же страницу; выключение убирает чат из списка, поиска и прямых адресов, история остаётся.
"""
from django.http import HttpResponseRedirect
from django.views.decorators.http import require_http_methods

from apps.core.services.permissions import require_permission
from apps.core.views.common import render_page
from apps.messenger.services import messenger_settings

SETTINGS_URL = "/settings/messenger/"
PERMISSION = "settings.portal"


@require_permission(PERMISSION)
@require_http_methods(["GET", "POST"])
def settings_page(request):
    """GET, POST `/settings/messenger/` — «Общий чат» (T-8206) и срок хранения (T-8220)."""
    if request.method == "POST":
        messenger_settings.set_general(bool(request.POST.get("general_chat_enabled")), request.user)
        return HttpResponseRedirect(SETTINGS_URL)
    return render_page(request, "messenger/settings.html", {"row": messenger_settings.get()})