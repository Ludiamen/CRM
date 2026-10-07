"""Публичный интерфейс сервис-деска: заявители (PLAN-003, «Подразделения-клиенты, заявители и загрузка таблицы»;
CONTRACT-003, 6.22).

Запись заявителя создаёт `tickets.create` и загрузка таблицы (`requester_import`); своей функции создания здесь нет.
Право `servicedesk.manage` проверяет маршрут, служба его не читает. Журнал записи — без адреса и ФИО (FR-289):
подразделение «было и стало» названиями, ФИО — только `name_changed`.
"""
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db import transaction
from django.db.models import Count, Q, Value
from django.db.models.functions import Lower, Replace

from apps.core.services import audit

from ..models import ClientUnit, Requester, Ticket, name_key
from . import settings
from .errors import ServiceDeskError

PAGE_SIZE = 50
NAME_LIMIT = 255
EMAIL_LIMIT = 254


@dataclass(frozen=True)
class RequesterRow:
    """Строка страницы: запись и число её заявок (без обезличенных)."""

    requester: Requester
    tickets_count: int


@dataclass(frozen=True)
class RequesterPage:
    """Страница списка: строки, есть ли следующая и номер страницы."""

    rows: list
    has_next: bool
    page: int


@dataclass(frozen=True)
class RequesterHint:
    """Подсказка по адресу: найдена ли запись, ФИО и номер неархивного подразделения."""

    found: bool
    name: str = ""
    client_unit_id: int | None = None


def normalize_email(text) -> str:
    """Адрес строчными без крайних пробелов; формат и домен из списка доменов проверяются, иначе `bad_email`."""
    email = str(text or "").strip().lower()
    bad = ServiceDeskError("bad_email", "Укажите рабочую почту на корпоративном домене")
    if not email or len(email) > EMAIL_LIMIT:
        raise bad
    try:
        validate_email(email)
    except ValidationError:
        raise bad from None
    if not settings.accepts_domain(email.rsplit("@", 1)[1]):
        raise bad
    return email


def lookup(email) -> RequesterHint:
    """Подсказка по одному полному корпоративному адресу; чужой, неполный или неизвестный адрес — `found=False`."""
    try:
        address = normalize_email(email)
    except ServiceDeskError:
        return RequesterHint(found=False)
    record = Requester.objects.select_related("client_unit").filter(email=address).first()
    if record is None:
        return RequesterHint(found=False)
    unit = record.client_unit
    return RequesterHint(found=True, name=record.full_name,
                         client_unit_id=unit.pk if unit is not None and not unit.archived else None)


def page(*, query="", client_unit_id=None, number=1) -> RequesterPage:
    """Страница записей по адресу; поиск по адресу и ФИО без учёта регистра и «е/ё», фильтр по подразделению."""
    try:
        number = max(int(number), 1)
    except (TypeError, ValueError):
        number = 1
    records = Requester.objects.select_related("client_unit").annotate(
        tickets_count=Count("tickets", filter=Q(tickets__anonymized_at__isnull=True)),
        name_search=Replace(Lower("full_name"), Value("ё"), Value("е")))
    text = " ".join(str(query or "").split())
    if text:
        records = records.filter(Q(email__icontains=text) | Q(name_search__contains=name_key(text)))
    if client_unit_id:
        records = records.filter(client_unit_id=client_unit_id)
    start = (number - 1) * PAGE_SIZE
    found = list(records.order_by("email", "id")[start:start + PAGE_SIZE + 1])
    rows = [RequesterRow(requester=record, tickets_count=record.tickets_count) for record in found[:PAGE_SIZE]]
    return RequesterPage(rows=rows, has_next=len(found) > PAGE_SIZE, page=number)


def update(requester, *, name, client_unit_id, actor, ip=None) -> bool:
    """Меняет ФИО и подразделение записи. `True` — что-то изменилось (тогда пишет `requester.updated`)."""
    name = str(name or "").strip()
    if len(name) > NAME_LIMIT:
        raise ServiceDeskError("requester_name_too_long", "ФИО не длиннее 255 знаков")
    unit = None
    if client_unit_id:
        unit = ClientUnit.objects.filter(pk=client_unit_id).first()
        # Отказ — только при выборе другого подразделения; текущее (пусть архивное) остаётся как есть.
        if (unit is None or unit.archived) and str(client_unit_id) != str(requester.client_unit_id):
            raise ServiceDeskError("archived_value", "Значение в архиве: выберите другое")
    with transaction.atomic():
        record = Requester.objects.select_for_update(of=("self",)).select_related("client_unit").get(pk=requester.pk)
        before, after = {}, {}
        if (unit.pk if unit else None) != record.client_unit_id:
            before["client_unit"] = record.client_unit.name if record.client_unit_id else ""
            after["client_unit"] = unit.name if unit else ""
        if name != record.full_name:
            after["name_changed"] = True
        if not before and not after:
            return False
        record.full_name, record.client_unit = name, unit
        record.save()
        audit.record("requester.updated", actor=actor, object_type="requester", object_id=record.pk,
                     before=before, after=after, ip=ip)
    requester.full_name, requester.client_unit_id = record.full_name, record.client_unit_id
    requester.client_unit = unit
    return True


def delete(requester, *, actor, ip=None) -> None:
    """Удаляет запись без заявок; журнал `requester.deleted` — отметка в `before`, без адреса и ФИО."""
    with transaction.atomic():
        record = Requester.objects.select_for_update().get(pk=requester.pk)
        if Ticket.objects.filter(requester=record).exists():
            raise ServiceDeskError("requester_has_tickets", "У заявителя есть заявки: запись удалить нельзя")
        number, origin = record.pk, record.origin
        record.delete()
        audit.record("requester.deleted", actor=actor, object_type="requester", object_id=number,
                     before={"origin": origin}, after={}, ip=ip)


def delete_if_orphan(requester, *, reason, actor=None) -> bool:
    """Удаляет запись «заявка», у которой нет других заявок (зовёт обезличивание); иначе `False`.

    Запись берётся под `select_for_update`; журнал `requester.deleted` несёт причину `reason`.
    """
    with transaction.atomic():
        record = Requester.objects.select_for_update().filter(pk=requester.pk).first()
        if record is None or record.origin != Requester.Origin.TICKET:
            return False
        if Ticket.objects.filter(requester=record).exists():
            return False
        number, origin = record.pk, record.origin
        record.delete()
        audit.record("requester.deleted", actor=actor, object_type="requester", object_id=number,
                     before={"origin": origin}, after={"reason": reason})
    return True
