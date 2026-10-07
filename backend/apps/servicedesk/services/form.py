"""Открытая форма заявки: приём, проверки, порог по адресу клиента, страница «готово» (CONTRACT-003, 6.19).

Служба не знает про запрос Django: сессию и адрес клиента передаёт маршрут. Порог — сценарий Lua над упорядоченным
множеством `servicedesk:form:<адрес>` в Valkey (скользящее окно в час, ключ — 7.4); клиент берётся из
`apps.core.services.valkey.conn()` в момент вызова. Ничего не ищется по адресу в таблице заявителей (FR-224).
"""
import logging
import secrets
import time
from dataclasses import dataclass

import redis
from django.db import transaction
from django.utils import timezone

from apps.core.services import valkey

from ..models import Category, ClientUnit
from . import attachments, requesters, tickets
from . import settings as sd_settings
from .errors import ServiceDeskError

logger = logging.getLogger(__name__)

SESSION_KEY = "servicedesk_form_done"
RATE_PREFIX = "servicedesk:form:"
RATE_WINDOW = 3600

EMAIL_LIMIT = 254
NAME_LIMIT = 255
SUBJECT_LIMIT = 255
TEXT_LIMIT = 50_000

LOGIN_LINK = {"url": "/request/", "title": "Подать заявку в ИТ-отдел"}

# Тексты отказов полей (14.1): код -> текст; общие отказы формы берут текст у службы, которая их подняла.
FIELD_TEXTS = {
    "bad_email": "Укажите рабочую почту на корпоративном домене",
    "requester_name_required": "Укажите ФИО",
    "requester_name_too_long": "ФИО не длиннее 255 знаков",
    "category_not_offered": "Выберите категорию из списка",
    "unit_not_offered": "Выберите подразделение из списка или «Нет в списке»",
    "subject_required": "Укажите тему",
    "subject_too_long": "Тема не длиннее 255 знаков",
    "description_required": "Опишите проблему",
    "description_too_long": "Описание не длиннее 50 000 знаков",
    "consent_required": "Подтвердите согласие на обработку персональных данных",
}

# Окно: добавить отметку, убрать записи старше окна, посчитать; сверх порога — снять свою отметку.
# KEYS: ключ адреса. ARGV: время (секунды с долями), элемент, окно (секунды), порог.
_REGISTER_HIT = """
redis.call('ZADD', KEYS[1], ARGV[1], ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', tonumber(ARGV[1]) - tonumber(ARGV[3]))
local count = redis.call('ZCARD', KEYS[1])
if count > tonumber(ARGV[4]) then
  redis.call('ZREM', KEYS[1], ARGV[2])
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
  return 0
end
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[3]))
return 1
"""


class FormInvalid(ServiceDeskError):
    """Ошибки полей открытой формы: `errors` — поле -> код (тексты — `FIELD_TEXTS`)."""

    def __init__(self, errors: dict[str, str]):
        super().__init__("invalid_form", "; ".join(FIELD_TEXTS[code] for code in errors.values()))
        self.errors = errors


@dataclass(frozen=True)
class FormChoices:
    """Что предлагает форма: подразделения-клиенты и категории."""

    client_units: list
    categories: list


def is_open() -> bool:
    """Приём открыт: есть домены и очередь по умолчанию."""
    return sd_settings.is_configured()


def closed_text() -> str:
    return f"Приём заявок через форму сейчас закрыт. Напишите письмо на {sd_settings.mailbox_address()}"


def choices() -> FormChoices:
    """Неархивные подразделения по названию и неархивные категории с отметкой «на форме» по порядку."""
    units = list(ClientUnit.objects.filter(archived=False).order_by("name_key", "id"))
    categories = list(Category.objects.filter(archived=False, on_form=True).order_by("order", "id"))
    return FormChoices(client_units=units, categories=categories)


def validate(*, email, name, client_unit_id, category_id, subject, text, consent) -> dict[str, str]:
    """Поле -> код ошибки; пустой словарь — всё верно. Адрес в таблице заявителей не ищется."""
    errors: dict[str, str] = {}
    try:
        requesters.normalize_email(email)
    except ServiceDeskError:
        errors["email"] = "bad_email"
    name = (name or "").strip()
    if not name:
        errors["name"] = "requester_name_required"
    elif len(name) > NAME_LIMIT:
        errors["name"] = "requester_name_too_long"
    if category_id is None or not Category.objects.filter(
            pk=category_id, archived=False, on_form=True).exists():
        errors["category"] = "category_not_offered"
    if client_unit_id is not None and not ClientUnit.objects.filter(pk=client_unit_id, archived=False).exists():
        errors["client_unit"] = "unit_not_offered"
    subject = (subject or "").strip()
    if not subject:
        errors["subject"] = "subject_required"
    elif len(subject) > SUBJECT_LIMIT:
        errors["subject"] = "subject_too_long"
    text = (text or "").strip()
    if not text:
        errors["text"] = "description_required"
    elif len(text) > TEXT_LIMIT:
        errors["text"] = "description_too_long"
    if not consent:
        errors["consent"] = "consent_required"
    return errors


def register_hit(ip) -> bool:
    """Учитывает отправку с адреса; `False` — порог за час превышен (отметка снята).

    Порог читается из настроек при каждом вызове. Ошибка Valkey (в том числе при получении клиента) — `True` и
    предупреждение в лог: заявка важнее порога.
    """
    try:
        conn = valkey.conn()
        now = time.time()
        script = conn.register_script(_REGISTER_HIT)
        member = f"{now:.6f}:{secrets.token_hex(6)}"
        admitted = script(keys=[f"{RATE_PREFIX}{ip}"],
                          args=[f"{now:.6f}", member, RATE_WINDOW, sd_settings.get().form_hourly_limit])
    except redis.exceptions.RedisError:
        logger.warning("Valkey недоступен: порог открытой формы не проверен", exc_info=True)
        return True
    return bool(admitted)


def submit(*, email, name, client_unit_id, category_id, subject, text, consent, parts=(), ip=None):
    """Принимает форму: закрыто, поля, вложения, порог, затем заявка и вложения одной транзакцией.

    Отказы: `intake_closed`, `invalid_form` (`FormInvalid`), `too_many_files`, `total_too_big`, `file_rejected`,
    `rate_limited`. Порядок важен: отказы полей и вложений порог не расходуют.
    """
    if not is_open():
        raise ServiceDeskError("intake_closed", closed_text())
    errors = validate(email=email, name=name, client_unit_id=client_unit_id, category_id=category_id,
                      subject=subject, text=text, consent=consent)
    if errors:
        raise FormInvalid(errors)
    parts = list(parts)
    attachments.precheck(parts)
    if not register_hit(ip):
        raise ServiceDeskError(
            "rate_limited", "С вашего адреса отправлено слишком много заявок за час. "
                            f"Напишите письмо на {sd_settings.mailbox_address()}")
    category = Category.objects.get(pk=category_id)
    with transaction.atomic():
        created = tickets.create(
            channel=tickets.FORM, subject=subject.strip(), text=text.strip(),
            requester_email=requesters.normalize_email(email), requester_name=name.strip(),
            client_unit_id=client_unit_id, category=category, consent_at=timezone.now(), ip=ip)
        attachments.accept(created.entry, parts)
    return created


def remember_done(session, email) -> None:
    """Кладёт адрес в сессию для страницы «готово» (номер заявки в сессию не кладётся)."""
    session[SESSION_KEY] = email


def pop_done(session):
    """Адрес из сессии с удалением ключа; второй вызов — `None`."""
    return session.pop(SESSION_KEY, None)


def login_links() -> list[dict]:
    """Точка ядра `login_links`: ссылка на открытую форму (FR-226); видна и пока приём закрыт."""
    return [dict(LOGIN_LINK)]
