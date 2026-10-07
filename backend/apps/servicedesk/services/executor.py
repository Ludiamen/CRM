"""Заявка от исполнителя: кнопка, выбор очереди, создание (CONTRACT-003, 6.20; план «Заявка от исполнителя»).

Создание — тот же `tickets.create` (канал `STAFF`), вложения принимает `attachments.accept` в той же транзакции.
Справочники загружаются вместе с архивными: архивное значение даёт `archived_value`, а не «не найдено».
"""
from dataclasses import dataclass

from django.db import transaction

from ..models import Category, ClientUnit, Priority, Source
from . import access, attachments, mail_parse, queues, requesters, settings, tickets
from .errors import ServiceDeskError

SUBJECT_LIMIT = 255
TEXT_LIMIT = 50_000


@dataclass(frozen=True)
class ExecutorResult:
    """Итог `create`: созданная заявка и видна ли она заводящему (от этого зависит переход после создания)."""

    created: tickets.Created
    visible: bool


def _error(code: str, message: str) -> ServiceDeskError:
    return ServiceDeskError(code, message)


def can_start(user) -> bool:
    """Кнопка «Новая заявка»: участник очереди или держатель «Все заявки»."""
    return access.can_create(user)


def can_take(user, queue_id) -> bool:
    """Флажок «Взять себе» доступен участнику выбранной очереди и держателю «Все заявки»."""
    return queue_id is not None and access.is_participant(user, queue_id)


def queue_for_category(category_id) -> int:
    """Очередь категории; у категории без очереди («Другое») — очередь по умолчанию из настроек."""
    category = Category.objects.filter(pk=category_id).first() if category_id is not None else None
    if category is None or category.archived:
        raise _error("archived_value", "Значение в архиве: выберите другое")
    unit_id = category.queue_id if category.queue_id is not None else queues.default_unit_id()
    if unit_id is None:
        raise _error("no_queue", "Очередь заявки не определена: задайте очередь по умолчанию в настройках сервис-деска")
    return unit_id


def create(*, actor, email, name="", client_unit_id=None, category_id, queue_id, priority_id=None, source_id,
           subject, text, take=False, parts=(), ip=None) -> ExecutorResult:
    """Создаёт заявку от имени исполнителя; порядок проверок и коды — по строке `create` контракта 6.20."""
    if not access.can_create(actor):
        raise _error("no_access", "нет доступа")
    if not settings.get().domains:
        raise _error("intake_closed", "Приём заявок закрыт: в настройках сервис-деска не заданы почтовые домены")
    address = requesters.normalize_email(email)
    name = (name or "").strip()
    if len(name) > requesters.NAME_LIMIT:
        raise _error("requester_name_too_long", "ФИО не длиннее 255 знаков")
    subject = (subject or "").strip()
    if not subject:
        raise _error("subject_required", "Укажите тему")
    if len(subject) > SUBJECT_LIMIT:
        raise _error("subject_too_long", "Тема не длиннее 255 знаков")
    text = mail_parse.clean_text(text or "").strip()
    if not text:
        raise _error("description_required", "Опишите проблему")
    if len(text) > TEXT_LIMIT:
        raise _error("description_too_long", "Описание не длиннее 50 000 знаков")
    if category_id is None:
        raise _error("category_required", "Выберите категорию")
    if queue_id is None:
        raise _error("queue_required", "Выберите очередь")
    parts = list(parts)
    if not queues.is_queue(queue_id):
        raise _error("not_queue", "Этот узел не отмечен очередью сервис-деска")
    attachments.precheck(parts)
    category = Category.objects.filter(pk=category_id).first()
    unit = ClientUnit.objects.filter(pk=client_unit_id).first() if client_unit_id is not None else None
    if category is None or (client_unit_id is not None and unit is None):
        raise _error("archived_value", "Значение в архиве: выберите другое")
    priority = Priority.objects.filter(pk=priority_id).first() if priority_id is not None else None
    source = Source.objects.filter(pk=source_id).first() if source_id is not None else None
    with transaction.atomic():
        created = tickets.create(
            channel=tickets.STAFF, subject=subject, text=text, requester_email=address, requester_name=name,
            client_unit_id=unit.pk if unit is not None else None, category=category, queue_id=queue_id,
            priority=priority, source=source, take_by=actor if take and can_take(actor, queue_id) else None,
            created_by=actor, ip=ip)
        attachments.accept(created.entry, parts)
    return ExecutorResult(created=created, visible=access.can_work(actor, created.ticket))
