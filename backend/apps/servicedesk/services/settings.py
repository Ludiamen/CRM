"""Публичный интерфейс сервис-деска: настройки (PLAN-003, «Справочники и настройки»; CONTRACT-003, 6.6).

Строка настроек одна (`pk=1`). Внутри модуля `django.conf.settings` импортируется как `dj_settings`.
"""
import re

from django.conf import settings as dj_settings
from django.db import transaction

from apps.core.services import audit, permissions

from ..models import Priority, ServiceDeskSettings
from .errors import ServiceDeskError

_LABEL = re.compile(r"^[a-z0-9]([a-z0-9-]*[a-z0-9])?$")
_MAX_DOMAIN = 253
MANAGE = "servicedesk.manage"

# поле -> (название для сообщения, минимум, максимум): границы раздела 2.2
_RANGES = {
    "autoclose_days": ("срок автозакрытия, дней", 1, 90),
    "reopen_days": ("срок открытия заново, дней", 1, 90),
    "form_hourly_limit": ("порог формы в час", 1, 1000),
    "retention_years": ("срок хранения заявок, лет", 1, 10),
    "inbound_retention_days": ("срок хранения писем без заявки, дней", 1, 365),
}
_FIELDS = {"domains", "default_priority", *_RANGES}


def get() -> ServiceDeskSettings:
    """Строка настроек (`pk=1`)."""
    return ServiceDeskSettings.objects.get(pk=1)


def _bad(domain: str) -> ServiceDeskError:
    return ServiceDeskError("bad_domain", f"Домен записан неверно: {domain}")


def _one_domain(raw: str) -> str:
    """Домен строчными, кириллица — в виде `xn--…`; не прошедший проверку — `bad_domain`."""
    domain = raw.strip().lower()
    try:
        encoded = domain.encode("idna").decode("ascii")
    except UnicodeError:
        raise _bad(raw.strip()) from None
    labels = encoded.split(".")
    if len(encoded) > _MAX_DOMAIN or len(labels) < 2 or not all(_LABEL.match(label) for label in labels):
        raise _bad(raw.strip())
    return encoded


def parse_domains(text) -> list[str]:
    """Список доменов: строка через запятую или перевод строки (или список строк); без дубликатов, по порядку."""
    parts = re.split(r"[,\n]", text) if isinstance(text, str) else [piece for item in text for piece in re.split(r"[,\n]", item)]
    found = []
    for part in parts:
        if not part.strip():
            continue
        domain = _one_domain(part)
        if domain not in found:
            found.append(domain)
    return found


def accepts_domain(domain: str) -> bool:
    """Домен есть в списке на момент вызова (читает базу); непреобразуемый домен — `False`."""
    try:
        encoded = _one_domain(domain)
    except ServiceDeskError:
        return False
    return encoded in get().domains


def is_configured() -> bool:
    """Домены заданы и очередь по умолчанию выбрана."""
    row = get()
    return bool(row.domains) and row.default_queue_id is not None


def mailbox_address() -> str:
    """Адрес ящика заявок — только для чтения."""
    return dj_settings.SERVICEDESK_MAILBOX


def _int_in_range(field: str, value) -> int:
    title, low, high = _RANGES[field]
    try:
        number = int(value)
        if isinstance(value, bool) or (isinstance(value, float) and value != number):
            raise ValueError
    except (TypeError, ValueError):
        number = None
    if number is None or not low <= number <= high:
        raise ServiceDeskError("out_of_range", f"Значение поля «{title}» должно быть от {low} до {high}")
    return number


def update(*, actor, ip=None, **fields) -> ServiceDeskSettings:
    """Меняет настройки; журнал `servicedesk.settings_changed` — каждое изменённое поле до и после."""
    bad = set(fields) - _FIELDS
    if bad:
        raise TypeError(f"неожиданные аргументы {sorted(bad)}")
    with transaction.atomic():
        row = ServiceDeskSettings.objects.select_related("default_priority").select_for_update(of=("self",)).get(pk=1)
        before, after = {}, {}
        for field, value in fields.items():
            if field == "domains":
                new = parse_domains(value)
                old = row.domains
            elif field == "default_priority":
                priority = value if isinstance(value, Priority) else Priority.objects.get(pk=value)
                if priority.archived:
                    raise ServiceDeskError("archived_value", "Значение в архиве: выберите другое")
                new, old = priority, row.default_priority
            else:
                new, old = _int_in_range(field, value), getattr(row, field)
            if new != old:
                setattr(row, field, new)
                if field == "default_priority":
                    before[field], after[field] = old.name, new.name
                else:
                    before[field], after[field] = old, new
        if after:
            row.save()
            audit.record("servicedesk.settings_changed", actor=actor, object_type="servicedesk", object_id="1",
                         before=before, after=after, ip=ip)
        return row


def home_notices(user) -> list[dict]:
    """Точка `home_notices`: напоминание о ненастроенном сервис-деске — только обладателю `servicedesk.manage`."""
    if not permissions.has_permission(user, MANAGE) or is_configured():
        return []
    return [{"key": "servicedesk-setup", "level": "warning", "url": "/servicedesk/", "link": "Настроить",
             "text": "Сервис-деск не настроен: укажите домены и очередь по умолчанию"}]
