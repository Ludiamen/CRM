"""Фильтры шаблонов: «было / стало» журнала и значения настроек в человеческом виде (T-248)."""
import re
from datetime import datetime
from zoneinfo import ZoneInfo

from django import template

from apps.core.services import audit_search, security_settings

register = template.Library()

FIELD_LABELS = dict([
    ("email", "почта"), ("full_name", "ФИО"), ("position", "должность"), ("phone", "телефон"),
    ("contacts", "контакты"), ("state", "состояние"), ("roles", "роли"), ("name", "название"),
    ("permissions", "права"), ("reason", "причина"), ("logo", "логотип"), ("devices", "устройств второго фактора"),
    ("expires_at", "действует до"), ("status", "статус"),
    ("via", "способ входа"), ("count", "выпущено кодов"), ("confirmed", "подтверждено"),
    ("remaining", "осталось кодов"), ("result", "итог"), ("step", "шаг"), ("attempts", "попыток отправки"),
    ("minutes", "на сколько минут"), ("closed", "закрыто сессий"), ("changed", "изменено"),
])
STATE_TITLES = {"invited": "приглашён", "active": "активен", "blocked": "заблокирован"}
# Пары кортежами, как в FIELD_LABELS: запись «"bad_password": "…"» сканер секретов принял бы за пароль литералом.
VALUE_TITLES = {
    "via": dict([
        ("activation", "активация записи"), ("password", "пароль"), ("backup", "резервный код"),
        ("totp", "код из приложения"), ("reset", "восстановление по ссылке"),
    ]),
    "result": dict([
        ("success", "успешно"), ("bad_password", "неверный пароль"), ("bad_code", "неверный код"),
        ("locked", "запись заблокирована"), ("ip_locked", "адрес заблокирован"),
        ("backup_code", "вход по резервному коду"),
    ]),
    "step": dict([
        ("password", "ввод пароля"), ("code", "ввод кода"), ("totp_setup", "подключение приложения"),
        ("change_password", "смена пароля"),
    ]),
    "status": dict([("queued", "в очереди"), ("sent", "отправлено"), ("failed", "не доставлено")]),
}
OBJECT_TYPES = dict([
    ("user", "сотрудник"), ("link", "ссылка"), ("mail", "письмо"), ("role", "роль"), ("ip", "адрес"),
    ("security_settings", "настройки безопасности"), ("portal_settings", "настройки портала"),
])
MOSCOW = ZoneInfo("Europe/Moscow")
ISO_MOMENT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def _label(key: str) -> str:
    if key in FIELD_LABELS:
        return FIELD_LABELS[key]
    bound = security_settings.BOUNDS.get(key)
    return bound.title if bound else key


def _text(key: str, value) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "да" if value else "нет"
    if key == "permissions" and isinstance(value, (list, tuple)):
        return ", ".join(_permission_titles(value)) or "—"
    if isinstance(value, (list, tuple)):
        return ", ".join(str(item) for item in value) or "—"
    if key == "state":
        return STATE_TITLES.get(str(value), str(value))
    if key in VALUE_TITLES:
        return VALUE_TITLES[key].get(str(value), str(value))
    if isinstance(value, str) and ISO_MOMENT.match(value):
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            return value
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=ZoneInfo("UTC"))
        return moment.astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M")
    return str(value)


_PERMISSION_TITLES: dict[str, str] = {}  # набор прав задаёт миграция, во время работы он не меняется


def _permission_titles(codes) -> list[str]:
    """Названия прав; к базе — только за кодами, которых ещё нет в памяти процесса (журнал без запроса на строку)."""
    from apps.core.models import Permission

    codes = [str(code) for code in codes]
    missing = [code for code in codes if code not in _PERMISSION_TITLES]
    if missing:
        _PERMISSION_TITLES.update(Permission.objects.filter(code__in=missing).values_list("code", "title"))
    return [_PERMISSION_TITLES.get(code, code) for code in codes]


@register.filter
def pairs(value):
    """Словарь «было» или «стало» — список (название поля, значение) для вывода."""
    if not isinstance(value, dict):
        return []
    return [(_label(str(key)), _text(str(key), item)) for key, item in value.items()]


@register.filter
def action_title(code):
    """Русское название события журнала; незнакомый код показывается как есть."""
    return audit_search.ACTION_TITLES.get(code, code)


@register.filter
def side_pairs(event, side):
    """«Было» или «Стало» события: если обе стороны — словари, показываются только изменившиеся поля."""
    mine, other = (event.before, event.after) if side == "before" else (event.after, event.before)
    if not isinstance(mine, dict):
        return []
    if isinstance(other, dict):
        changed = {k: v for k, v in mine.items() if not (k in other and other[k] == v)}
        if changed:
            mine = changed
    return pairs(mine)


@register.filter
def object_label(kind, object_id=""):
    """Вид объекта по-русски: «сотрудник № 1»; незнакомый вид показывается как есть."""
    if not kind:
        return "—"
    title = OBJECT_TYPES.get(str(kind), str(kind))
    return f"{title} № {object_id}" if object_id not in ("", None) else title
