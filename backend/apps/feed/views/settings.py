"""Настройка срока хранения `/settings/feed/` (T-7230; CONTRACT-007, 5.5, 10.2, 12.7).

Право ядра `settings.portal` проверяет декоратор раньше всего прочего: без него 403 на
GET и POST, служба настройки не вызывается (решение 11 задач). Отказ и не число — 200
той же страницей с причиной у поля; уменьшение без подтверждения — 200 со вторым шагом
`[data-feed-confirm]` и числом записей к удалению; успех — 302 на ту же страницу.
"""
from django.http import HttpResponseRedirect
from django.views.decorators.http import require_http_methods

from apps.core.services.permissions import require_permission
from apps.core.views.common import render_page

from apps.feed.services import feed_settings
from apps.feed.services.errors import FeedError
from apps.feed.texts import TEXTS

SETTINGS_URL = "/settings/feed/"
PERMISSION = "settings.portal"


def _error(code: str, field: str, params: dict | None = None) -> dict:
    return {"field": field, "code": code, "message": TEXTS[code].format(**(params or {}))}


def _page(request, *, error=None, value=None, confirm=None):
    """Страница с текущим значением; после отказа поле показывает присланный ввод."""
    row = feed_settings.get()
    context = {
        "value": row.retention_years if value is None else value,
        "error": error,
        "confirm": confirm,
    }
    return render_page(request, "feed/settings.html", context)


def _parse_years(raw: str) -> int | None:
    """Строгий разбор целого: не число и пусто — отказ (в границах проверяет служба)."""
    try:
        return int(str(raw).strip())
    except ValueError:
        return None


@require_permission(PERMISSION)
@require_http_methods(["GET", "POST"])
def settings_page(request):
    """GET, POST `/settings/feed/` — срок хранения записей ленты, лет (T-7230)."""
    if request.method == "GET":
        return _page(request)
    raw = request.POST.get("retention_years", "")
    years = _parse_years(raw)
    if years is None:
        return _page(request, error=_error("retention_range", "retention_years"), value=raw)
    try:
        result = feed_settings.save(request.user, years, confirmed=request.POST.get("confirm") == "1")
    except FeedError as exc:
        return _page(request, error=_error(exc.code, exc.field, exc.params), value=raw)
    if not result.saved:
        return _page(request, confirm={"years": years, "to_delete": result.to_delete})
    return HttpResponseRedirect(SETTINGS_URL)
