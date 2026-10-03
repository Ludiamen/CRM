"""Выборка журнала событий для `/audit/` и `/audit/export.csv` (T-248, FR-047, NFR-002).

Только чтение: журнал пишет `audit.record`, здесь события лишь отбираются и выгружаются. Даты фильтра
понимаются по московскому времени (текущий часовой пояс проекта). Страница выборку не считает: журнал
хранится годами, а количество выводится только по запросу (`count`; UX-04, п. 6, PLAN-001 версия 4). Ячейки CSV, начинающиеся с `=`, `+`,
`-`, `@` (и табуляции или возврата каретки), получают апостроф: таблица не должна исполнить их как формулу.
"""
import csv
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.db.models import Q
from django.utils import timezone

from apps.core.models import AuditEvent, User

PAGE_SIZE = 50
MAX_PAGE = 100_000  # дальше — первая страница: огромный номер переполнил бы OFFSET
SORTS = {"at": ("at", "id"), "-at": ("-at", "-id"), "action": ("action", "id"), "-action": ("-action", "-id")}
DEFAULT_SORT = "-at"

# Пресеты «Вход и доступ», «Права и роли», «Настройки»: приставки кодов событий (CONTRACT.md)
PRESETS = {
    "today": "Сегодня",
    "access": "Вход и доступ",
    "roles": "Права и роли",
    "settings": "Настройки",
}
PRESET_PREFIXES = {
    "access": ("login.", "logout", "account.", "ip.", "totp.", "backup_code", "invitation.", "password.", "link.",
               "sessions.", "user."),
    "roles": ("role.",),
    "settings": ("security_settings.", "portal_settings."),
}
CSV_HEADER = ("Номер", "Время (Москва)", "Кто", "Событие", "Вид объекта", "Номер объекта", "Было", "Стало", "Адрес")
FORMULA_START = ("=", "+", "-", "@", "\t", "\r")

ACTION_TITLES = dict([
    ("login.success", "Вход выполнен"), ("login.failed", "Неудачная попытка входа"), ("logout", "Выход"),
    ("account.locked", "Запись заблокирована после неудач"), ("account.unlocked", "Блокировка входа записи снята"),
    ("ip.locked", "Адрес заблокирован"), ("ip.unlocked", "Блокировка адреса снята"),
    ("password.reset_requested", "Запрошено восстановление пароля"), ("password.changed", "Пароль изменён"),
    ("user.created", "Запись создана"), ("user.updated", "Профиль изменён"), ("user.blocked", "Запись заблокирована"),
    ("user.unblocked", "Запись разблокирована"), ("user.activated", "Запись активирована"),
    ("invitation.sent", "Приглашение отправлено"), ("link.revealed", "Ссылка активации показана администратору"),
    ("totp.enrolled", "Второй фактор подключён"), ("totp.reset", "Второй фактор сброшен"),
    ("backup_code.used", "Использован резервный код"), ("backup_codes.issued", "Выпущены резервные коды"),
    ("sessions.closed", "Сессии закрыты после восстановления пароля"),
    ("sessions.logout_everywhere", "Выход со всех устройств"),
    ("role.created", "Роль создана"), ("role.updated", "Роль изменена"), ("role.deleted", "Роль удалена"),
    ("role.assigned", "Роли сотрудника изменены"),
    ("security_settings.updated", "Настройки безопасности изменены"),
    ("portal_settings.updated", "Настройки портала изменены"), ("mail.status_changed", "Состояние письма изменилось"),
])


@dataclass(frozen=True)
class Filters:
    date_from: date | None = None
    date_to: date | None = None
    user: int | None = None
    action: str = ""
    object_type: str = ""
    object_id: str = ""
    preset: str = ""
    sort: str = DEFAULT_SORT


def _date(value) -> date | None:
    try:
        return date.fromisoformat((value or "").strip())
    except ValueError:
        return None


def _int(value) -> int | None:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse(params) -> Filters:
    """Параметры запроса (QueryDict или словарь) в проверенные значения; непонятное молча отбрасывается."""
    preset = (params.get("preset") or "").strip()
    sort = (params.get("sort") or "").strip()
    return Filters(
        date_from=_date(params.get("date_from")), date_to=_date(params.get("date_to")), user=_int(params.get("user")),
        action=(params.get("action") or "").strip(), object_type=(params.get("object_type") or "").strip(),
        object_id=(params.get("object_id") or "").strip(),
        preset=preset if preset in PRESETS else "", sort=sort if sort in SORTS else DEFAULT_SORT)


def _day_start(day: date) -> datetime:
    return timezone.make_aware(datetime.combine(day, time.min))


def queryset(filters: Filters):
    qs = AuditEvent.objects.select_related("actor")
    start, end = filters.date_from, filters.date_to
    if filters.preset == "today":
        start = end = timezone.localdate()
    if start:
        qs = qs.filter(at__gte=_day_start(start))
    if end:
        qs = qs.filter(at__lt=_day_start(end + timedelta(days=1)))
    if filters.user is not None:
        qs = qs.filter(actor_id=filters.user)
    if filters.action:
        qs = qs.filter(action=filters.action)
    if filters.object_type:
        qs = qs.filter(object_type=filters.object_type)
    if filters.object_id:
        qs = qs.filter(object_id=filters.object_id)
    prefixes = PRESET_PREFIXES.get(filters.preset)
    if prefixes:
        condition = Q()
        for prefix in prefixes:
            condition |= Q(action__startswith=prefix)
        qs = qs.filter(condition)
    return qs.order_by(*SORTS[filters.sort])


@dataclass(frozen=True)
class Page:
    """Страница выборки без общего числа строк: есть ли следующая — видно по лишней строке."""
    rows: list
    number: int
    more: bool  # за страницей есть строки

    def __iter__(self):
        return iter(self.rows)

    def __len__(self):
        return len(self.rows)

    def has_next(self) -> bool:
        return self.more

    def has_previous(self) -> bool:
        return self.number > 1

    def previous_page_number(self) -> int:
        return self.number - 1

    def next_page_number(self) -> int:
        return self.number + 1


def page_of(filters: Filters, page=None) -> Page:
    """Строки страницы `page` (с 1); номер за концом выборки или неверный номер дают первую страницу."""
    number = _int(page)
    number = number if number and 0 < number <= MAX_PAGE else 1
    qs = queryset(filters)
    rows = list(qs[(number - 1) * PAGE_SIZE:number * PAGE_SIZE + 1])
    if not rows and number > 1:
        number, rows = 1, list(qs[:PAGE_SIZE + 1])
    return Page(rows=rows[:PAGE_SIZE], number=number, more=len(rows) > PAGE_SIZE)


def count(filters: Filters) -> int:
    """Число событий выборки — только по запросу пользователя («показать количество»)."""
    return queryset(filters).count()


def actors():
    """Кто может быть действующим лицом: для выпадающего списка фильтра."""
    return User.objects.order_by("full_name", "pk").only("id", "full_name", "email")


def known_actions() -> list[tuple[str, str]]:
    return sorted(ACTION_TITLES.items(), key=lambda item: item[1])


def _safe(value) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True) if value else ""


def actor_text(event) -> str:
    if event.actor_id is None:
        return "система"
    return f"{event.actor.full_name} <{event.actor.email}>"


def write_csv(stream, filters: Filters) -> None:
    """Пишет в `stream` текущую выборку целиком (без постраничного ограничения)."""
    writer = csv.writer(stream)
    writer.writerow(CSV_HEADER)
    for event in queryset(filters).iterator(chunk_size=2000):
        writer.writerow([_safe(cell) for cell in (
            event.pk, timezone.localtime(event.at).strftime("%Y-%m-%d %H:%M:%S"), actor_text(event), event.action,
            event.object_type, event.object_id, _json(event.before), _json(event.after), event.ip)])
