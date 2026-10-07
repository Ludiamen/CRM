"""Публичный интерфейс сервис-деска: создание заявок, поля, статусы (PLAN-003, «Где живёт код»; CONTRACT-003, 6.7).

Здесь `next_number`, `create`, `get_for`, `set_status`, `set_status_manual`, `add_incoming`, `require_open`, `UNSET` и
`Created`. Правку полей (`update_fields`) и снятие участника (`remove_participant`) дописывает задача T-3218.
Модели `org` не импортируются: узлы приходят числом, названия очередей читаются через связи.
"""
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from django.db import IntegrityError, connection, transaction
from django.http import Http404
from django.utils import timezone

from apps.core.services import audit
from apps.org.services import calendar

from ..models import ClientUnit, Requester, Source, Status, Ticket, TicketEntry, TicketParticipant
from . import access, dictionaries, events, letters, mail_parse, queues, replies, search
from . import settings as sd_settings
from .errors import ServiceDeskError

MAIL = "mail"
FORM = "form"
STAFF = "staff"
CHANNELS = (MAIL, FORM, STAFF)

MOSCOW = ZoneInfo("Europe/Moscow")
# коды причин смены статуса, журнал которых пишут `closing.*` (иначе журнал был бы двойным)
_CLOSING_REASONS = ("close", "autoclose", "reopen")


class _Unset:
    """Метка «не менять» (у `update_fields` отличает «не передано» от `None`)."""

    def __repr__(self) -> str:
        return "UNSET"

    def __bool__(self) -> bool:
        return False


UNSET = _Unset()


@dataclass(frozen=True)
class Created:
    """Итог `create`: заявка, первый элемент ленты и фраза о нерабочем времени (`None` / `""` / «ДД.ММ.ГГГГ ЧЧ:ММ»)."""

    ticket: Ticket
    entry: TicketEntry
    after_hours: str | None


def _error(code: str, message: str) -> ServiceDeskError:
    return ServiceDeskError(code, message)


def next_number() -> int:
    """Следующий номер заявки из последовательности базы одним запросом; откат номер не возвращает."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval('servicedesk_ticket_number')")
        return cursor.fetchone()[0]


def require_open(ticket) -> None:
    """Заявка открыта; закрытой — `ticket_closed` (6.1)."""
    if ticket.kind == Status.Kind.CLOSED:
        raise _error("ticket_closed", "Заявка закрыта: сначала откройте её")


def get_for(user, number):
    """Заявка по номеру среди видимых `user`; нет или не видна — одинаковый `Http404`."""
    ticket = (access.visible_tickets(user).select_related("status", "priority", "category", "assignee")
              .filter(number=number).first())
    if ticket is None:
        raise Http404("Заявка не найдена")
    return ticket


def _lock(ticket) -> None:
    """Блокирует строку заявки и перечитывает состояние объекта."""
    Ticket.objects.select_for_update().filter(pk=ticket.pk).first()
    ticket.refresh_from_db()


def _after_hours(now) -> str | None:
    """Фраза о нерабочем времени (дополнение 6): `None` — рабочее время; `""` — дата неизвестна; иначе дата по Москве."""
    if calendar.is_working_time(now):
        return None
    start = calendar.next_working_start(now)
    return "" if start is None else start.astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M")


def _unit_name(unit) -> str:
    return unit.name if unit is not None else ""


def _find_requester(email: str):
    """Запись заявителя под блокировкой; `None`, если записи нет."""
    return Requester.objects.select_for_update().filter(email=email).first()


def _requester_for(email: str, name: str, unit, *, actor, by_staff: bool):
    """Находит или создаёт запись заявителя и правит её по правилам 6.7; пишет журнал (дополнение 46).

    `unit` — выбранное `ClientUnit` или `None`; `by_staff` — канал исполнителя (его подразделение пишется в запись
    всегда). Возвращает запись и её ФИО до правки.
    """
    record = _find_requester(email)
    if record is None:
        try:
            with transaction.atomic():
                record = Requester.objects.create(email=email, full_name=name, client_unit=unit,
                                                  origin=Requester.Origin.TICKET)
        except IntegrityError:
            record = _find_requester(email)  # параллельная заявка создала запись первой
        else:
            audit.record("requester.created", actor=actor, object_type="requester", object_id=record.pk, before={},
                         after={"origin": Requester.Origin.TICKET, "client_unit": _unit_name(unit)})
            return record, ""
    old_name = record.full_name
    fields, before, after = [], {}, {}
    if by_staff:
        if record.client_unit_id != (unit.pk if unit else None):
            before["client_unit"] = _unit_name(record.client_unit)
            after["client_unit"] = _unit_name(unit)
            record.client_unit = unit
            fields.append("client_unit")
    elif unit is not None and record.client_unit_id is None:
        before["client_unit"] = ""
        after["client_unit"] = unit.name
        record.client_unit = unit
        fields.append("client_unit")
    if name and not record.full_name:
        record.full_name = name
        after["name_changed"] = True
        fields.append("full_name")
    if fields:
        record.save(update_fields=fields + ["updated_at"])
        audit.record("requester.updated", actor=actor, object_type="requester", object_id=record.pk, before=before,
                     after=after)
    return record, old_name


def _check_active(*values) -> None:
    """Архивное значение справочника не выбирается (`archived_value`)."""
    for value in values:
        if value is not None and value.archived:
            raise _error("archived_value", "Значение в архиве: выберите другое")


def _assignee_of(channel: str, take_by, category, queue_id: int):
    """Ответственный при создании: `take_by` (только исполнитель, участник очереди), иначе умолчание категории."""
    if channel == STAFF and take_by is not None and access.is_participant(take_by, queue_id):
        return take_by, take_by
    default = category.default_assignee if category is not None else None
    if default is not None and access.is_participant(default, queue_id):
        return default, None
    return None, None


def create(*, channel, subject, text, requester_email, requester_name="", client_unit_id=None, category=None,
           queue_id=None, priority=None, complexity=None, source=None, take_by=None, created_by=None,
           consent_at=None, previous=None, inbound_id=None, at=None, ip=None) -> Created:
    """Создаёт заявку одним для трёх каналов путём (6.7, план «Создание заявки — общее для трёх каналов»).

    Всё в одной транзакции; поиск заполняется в ней же, подтверждение и событие шины откладываются до фиксации.
    """
    if channel not in CHANNELS:
        raise ValueError(f"неизвестный канал заявки: {channel}")
    email = (requester_email or "").strip().lower()
    if not email:
        raise _error("email_required", "Укажите адрес заявителя")
    staff = channel == STAFF
    if staff and (source is None or source.archived or source.system_code):
        raise _error("source_required", "Выберите источник заявки")
    unit = ClientUnit.objects.get(pk=client_unit_id) if client_unit_id is not None else None
    _check_active(category, priority, complexity, unit)
    if staff and queue_id is not None:
        unit_id = queue_id
    elif category is not None and category.queue_id is not None:
        unit_id = category.queue_id
    else:
        unit_id = queues.default_unit_id()
    if unit_id is None:
        raise _error("no_queue", "Очередь заявки не определена: задайте очередь по умолчанию в настройках сервис-деска")
    if not queues.is_queue(unit_id):
        raise _error("not_queue", "Этот узел не отмечен очередью сервис-деска")
    moment = at or timezone.now()
    actor = created_by if staff else None
    with transaction.atomic():
        number = next_number()
        record, old_name = _requester_for(email, (requester_name or "").strip(), unit, actor=actor, by_staff=staff)
        name = (requester_name or "").strip() or old_name
        ticket_unit = unit if (staff or unit is not None) else record.client_unit
        priority = priority or sd_settings.get().default_priority
        assignee, assigned_by = _assignee_of(channel, take_by, category, unit_id)
        status = dictionaries.default_status(Status.Kind.IN_PROGRESS if assignee else Status.Kind.NEW)
        source = source if staff else Source.objects.get(system_code=channel)
        ticket = Ticket.objects.create(
            number=number, subject=mail_parse.clean_subject(subject), requester=record, requester_email=email,
            requester_name=name, client_unit=ticket_unit, category=category, queue_id=unit_id, priority=priority,
            complexity=complexity, status=status, kind=status.kind, source=source, assignee=assignee,
            assigned_once=assignee is not None, created_by=created_by if staff else None,
            consent_at=consent_at if channel == FORM else None, previous=previous, last_message_at=moment,
            last_message_from=Ticket.MessageFrom.STAFF if staff else Ticket.MessageFrom.REQUESTER)
        entry = TicketEntry.objects.create(
            ticket=ticket, kind=TicketEntry.Kind.INCOMING, at=moment, text=text, inbound_id=inbound_id,
            author=created_by if staff else None, author_email="" if staff else email,
            author_name="" if staff else name)
        queue_name = ticket.queue.name
        after = {"number": number, "channel": channel, "queue": queue_name, "queue_id": unit_id,
                 "category": category.name if category else "", "priority": priority.name, "source": source.name}
        if staff:
            after.update(created_by=created_by.full_name if created_by else "",
                         created_by_id=created_by.pk if created_by else None)
        audit.record("ticket.created", actor=actor, object_type="ticket", object_id=number, before={}, after=after,
                     ip=ip if channel == FORM else None)
        if assignee is not None:
            event = replies.add_event(ticket, "assignee_changed", actor=assigned_by, data={
                "before": "", "after": assignee.full_name, "before_id": None, "after_id": assignee.pk})
            TicketEntry.objects.filter(pk=event.pk).update(at=moment)
            audit.record("ticket.assigned", actor=assigned_by, object_type="ticket", object_id=number,
                         before={"assignee": "", "assignee_id": None},
                         after={"assignee": assignee.full_name, "assignee_id": assignee.pk})
        if previous is not None:
            replies.add_event(previous, "continued", data={"number": number})
        search.index(ticket)
        after_hours = None if staff else _after_hours(timezone.now())
        letters.send(ticket, "ticket.confirmation", entry=entry, extra={"after_hours": after_hours})
        events.ticket_created(ticket)
    return Created(ticket=ticket, entry=entry, after_hours=after_hours)


def set_status(ticket, status, *, actor, reason, ip=None, start_countdown=True) -> bool:
    """Меняет статус и вид, ведёт `waiting_since`, пишет событие ленты и журнал (6.7, «Статусы и переходы»).

    Тот же статус — `False`, ничего не пишется. Журнал `ticket.updated` не пишется при закрытии, автозакрытии и
    открытии заново: его ведёт `closing.*`. `start_countdown=False` — отсчёт ставит `replies` (ответ с флажком).
    """
    with transaction.atomic():
        Ticket.objects.select_for_update().filter(pk=ticket.pk).first()
        ticket.refresh_from_db(fields=["status", "kind", "waiting_since"])
        if ticket.status_id == status.pk:
            return False
        before = ticket.status
        was_waiting = ticket.kind == Status.Kind.WAITING
        ticket.status = status
        ticket.kind = status.kind
        if status.kind != Status.Kind.WAITING:
            ticket.waiting_since = None
        elif not was_waiting and start_countdown:
            ticket.waiting_since = timezone.now()
        ticket.save(update_fields=["status", "kind", "waiting_since", "updated_at"])
        replies.add_event(ticket, "status_changed", actor=actor, data={
            "before": before.name, "after": status.name, "before_id": before.pk, "after_id": status.pk,
            "reason": reason})
        if reason not in _CLOSING_REASONS:
            audit.record("ticket.updated", actor=actor, object_type="ticket", object_id=ticket.number,
                         before={"status": before.name}, after={"status": status.name}, ip=ip)
    return True


def set_status_manual(ticket, status, *, actor, ip=None) -> bool:
    """Ручная смена статуса из карточки (FR-209): только статусы `dictionaries.manual_statuses()`."""
    with transaction.atomic():
        _lock(ticket)
        if not access.can_work(actor, ticket):
            raise _error("no_access", "нет доступа")
        require_open(ticket)
        if not dictionaries.manual_statuses().filter(pk=status.pk).exists():
            raise _error("bad_status", "Этот статус нельзя выбрать здесь")
        return set_status(ticket, status, actor=actor, reason="manual", ip=ip)


def add_incoming(ticket, *, author_email, author_name="", text, at=None, inbound_id=None, cc=()) -> TicketEntry:
    """Письмо заявителя или участника в открытой заявке: элемент `incoming`, участники из копии, «ждёт ответа» → «в работе»."""
    moment = at or timezone.now()
    with transaction.atomic():
        _lock(ticket)
        require_open(ticket)
        entry = TicketEntry.objects.create(
            ticket=ticket, kind=TicketEntry.Kind.INCOMING, at=moment, text=text, inbound_id=inbound_id,
            author_email=author_email.strip().lower(), author_name=author_name)
        for address, name in cc:
            TicketParticipant.objects.get_or_create(ticket=ticket, email=address.strip().lower(),
                                                    defaults={"name": name})
        ticket.last_message_at = moment
        ticket.last_message_from = Ticket.MessageFrom.REQUESTER
        ticket.save(update_fields=["last_message_at", "last_message_from", "updated_at"])
        if ticket.kind == Status.Kind.WAITING:
            set_status(ticket, dictionaries.default_status(Status.Kind.IN_PROGRESS), actor=None, reason="letter")
        search.index(ticket, entry)
        events.reply_received(ticket)
    return entry
