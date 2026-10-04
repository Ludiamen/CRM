"""Названия для журнала по-русски: поля, значения, права, вид объекта (T-248, NFR-010).

Одно место для страницы `/audit/` (фильтры шаблонов в `templatetags/portal.py`) и выгрузки `/audit/export.csv`
(PLAN-001 версия 4, «Журнал по-русски», «Выгрузка журнала — как экран»).
"""
import re
from collections.abc import Mapping
from datetime import datetime
from zoneinfo import ZoneInfo

from apps.core import extensions
from apps.core.services import security_settings

FIELD_LABELS = dict([
    ("email", "почта"), ("full_name", "ФИО"), ("position", "должность"), ("phone", "телефон"),
    ("contacts", "контакты"), ("state", "состояние"), ("roles", "роли"), ("name", "название"),
    ("permissions", "права"), ("reason", "причина"), ("logo", "логотип"), ("devices", "устройств второго фактора"),
    ("expires_at", "действует до"), ("status", "статус"),
    ("via", "способ входа"), ("count", "выпущено кодов"), ("confirmed", "подтверждено"),
    ("remaining", "осталось кодов"), ("result", "итог"), ("step", "шаг"), ("attempts", "попыток отправки"),
    ("minutes", "на сколько минут"), ("closed", "закрыто сессий"), ("changed", "изменено"),
])
STATE_TITLES = {"invited": "приглашён", "active": "активен", "blocked": "заблокирован", "dismissed": "уволен"}
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
_OBJECT_TYPES = dict([
    ("user", "сотрудник"), ("link", "ссылка"), ("mail", "письмо"), ("role", "роль"), ("ip", "адрес"),
    ("security_settings", "настройки безопасности"), ("portal_settings", "настройки портала"),
])


def extra(part: str) -> dict:
    """Слияние словаря `part` («actions», «fields», «object_types», «values») из функций точки `audit_labels`.

    Функции зовутся в порядке регистрации, поздние побеждают; у `values` внутренние словари (по полям) объединяются.
    Без зарегистрированных функций — пусто, и журнал такой же, как в срезе 001.
    """
    merged: dict = {}
    for func in extensions.registered("audit_labels"):
        data = (func() or {}).get(part) or {}
        for key, item in data.items():
            if part == "values":
                merged.setdefault(key, {}).update(item)
            else:
                merged[key] = item
    return merged


class Layered(Mapping):
    """Только чтение: базовый словарь ядра, поверх него — названия из точки `audit_labels` (читаются при обращении)."""

    def __init__(self, part: str, base: dict):
        self._part, self._base = part, base

    def _all(self) -> dict:
        return {**self._base, **extra(self._part)}

    def __getitem__(self, key):
        return self._all()[key]

    def __iter__(self):
        return iter(self._all())

    def __len__(self):
        return len(self._all())


OBJECT_TYPES = Layered("object_types", _OBJECT_TYPES)
MOSCOW = ZoneInfo("Europe/Moscow")
ISO_MOMENT = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")


def label(key: str) -> str:
    fields = extra("fields")
    if key in fields:
        return fields[key]
    if key in FIELD_LABELS:
        return FIELD_LABELS[key]
    bound = security_settings.BOUNDS.get(key)
    return bound.title if bound else key


def text(key: str, value) -> str:
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "да" if value else "нет"
    if key == "permissions" and isinstance(value, (list, tuple)):
        return ", ".join(permission_titles(value)) or "—"
    titles = value_titles(key)
    if isinstance(value, (list, tuple)):
        return ", ".join(titles.get(str(item), str(item)) for item in value) or "—"
    if isinstance(value, dict):  # вложенные итоги: «название: число; …», без латинских ключей
        return "; ".join(f"{label(str(name))}: {text(str(name), item)}" for name, item in value.items()) or "—"
    if titles:
        return titles.get(str(value), str(value))
    if isinstance(value, str) and ISO_MOMENT.match(value):
        try:
            moment = datetime.fromisoformat(value)
        except ValueError:
            return value
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=ZoneInfo("UTC"))
        return moment.astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M")
    return str(value)


def value_titles(key: str) -> dict:
    """Названия значений поля: ядра, затем из точки `audit_labels`; у `state` — ещё и `STATE_TITLES`."""
    titles = dict(STATE_TITLES) if key == "state" else dict(VALUE_TITLES.get(key, {}))
    titles.update(extra("values").get(key, {}))
    return titles


PERMISSION_TITLES: dict[str, str] = {}  # набор прав задаёт миграция, во время работы он не меняется


def permission_titles(codes) -> list[str]:
    """Названия прав; к базе — только за кодами, которых ещё нет в памяти процесса (журнал без запроса на строку)."""
    from apps.core.models import Permission

    codes = [str(code) for code in codes]
    missing = [code for code in codes if code not in PERMISSION_TITLES]
    if missing:
        PERMISSION_TITLES.update(Permission.objects.filter(code__in=missing).values_list("code", "title"))
    return [PERMISSION_TITLES.get(code, code) for code in codes]


def pairs(value) -> list[tuple[str, str]]:
    """Словарь «было» или «стало» — список (название поля, значение); не словарь — пусто."""
    if not isinstance(value, dict):
        return []
    return [(label(str(key)), text(str(key), item)) for key, item in value.items()]


def side_pairs(event, side: str) -> list[tuple[str, str]]:
    """«Было» (`before`) или «Стало» (`after`) события: если обе стороны — словари, только изменившиеся поля."""
    mine, other = (event.before, event.after) if side == "before" else (event.after, event.before)
    if not isinstance(mine, dict):
        return []
    if isinstance(other, dict):
        changed = {k: v for k, v in mine.items() if not (k in other and other[k] == v)}
        if changed:
            mine = changed
    return pairs(mine)


def side_text(event, side: str) -> str:
    """Те же пары одной строкой для выгрузки: «поле: значение; поле: значение»."""
    return "; ".join(f"{name}: {value}" for name, value in side_pairs(event, side))


def object_title(kind) -> str:
    """Вид объекта по-русски («сотрудник»); незнакомый вид — как есть, пустой — «—»."""
    return OBJECT_TYPES.get(str(kind), str(kind)) if kind else "—"


def object_label(kind, object_id="") -> str:
    """Вид объекта с номером: «сотрудник № 1»."""
    title = object_title(kind)
    return f"{title} № {object_id}" if kind and object_id not in ("", None) else title
