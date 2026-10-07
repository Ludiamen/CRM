"""Контекст шаблонов оболочки (T-240): название и логотип портала, меню по правам, подсказки сессии."""
from apps.core.services import permissions, portal_settings, sessions

HOME_ICON = "icons/home.html"


def _active(item_url: str, path: str) -> bool:
    if item_url == "/":
        return path == "/"
    return path.startswith(item_url)


def shell(request):
    """`portal` — название и логотип; `menu` — разделы, доступные по правам; `flashes` — разовые сообщения."""
    row = portal_settings.get()
    context = {
        "portal": {"name": row.name, "logo_url": row.logo.url if row.logo else ""},
        "flashes": [],
    }
    if hasattr(request, "session") and "flashes" in request.session:
        context["flashes"] = request.session.pop("flashes")
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated and not sessions.is_limited(request):
        items = [{"url": "/", "title": "Главная", "icon": HOME_ICON}] + [
            {key: entry[key] for key in ("url", "title", "icon", "badge") if key in entry}
            for entry in permissions.menu_for(user)]
        context["menu"] = [{**item, "active": _active(item["url"], request.path)} for item in items]
    return context
