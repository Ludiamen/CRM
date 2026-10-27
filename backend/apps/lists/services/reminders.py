"""Сервис: напоминания о сроках (срез 006; PLAN-006, «Сроки и напоминания», шаги 1–5; FR-529…FR-531, NFR-511).

Служба без актора: прав не проверяет. Каждая пара «запись, поле-срок» обрабатывается в своей транзакции под
разделяемым замком списка и `FOR UPDATE` записи; отметки порогов (`ReminderSent`) вставляются вместе с уведомлениями.
"""
import logging
from datetime import date, timedelta
from typing import NamedTuple

from django.apps import apps
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Q, Value
from django.db.models.fields.json import KeyTextTransform
from django.db.models.lookups import GreaterThanOrEqual, LessThanOrEqual
from django.utils import timezone

from apps.core.extensions import Draft
from apps.core.models import UserState
from apps.lists import notify_kinds
from apps.lists.models import Field, ImportJob, List, Record, ReminderSent
from apps.lists.services import access

logger = logging.getLogger("apps.lists.reminders")

TEXT_PART_LIMIT = 100
TEXT_LIMIT = 300
PINNED_URL = "/me/#lists-pinned"


class Candidate(NamedTuple):
    """Пара «запись, поле-срок», дата которой лежит в окне порогов."""

    record_id: int
    list_id: int
    field_id: int
    due_date: date


class RunResult(NamedTuple):
    """Итог обхода: число созданных уведомлений и номера записей (`Record.pk`) со сбоем."""

    notified: int
    failed: list


def _thresholds(field: Field) -> list[int]:
    """Пороги поля по убыванию и `0` («срок наступил») в конце."""
    own = {int(item) for item in (field.settings or {}).get("thresholds") or () if int(item) > 0}
    return sorted(own, reverse=True) + [0]


def _deadline_fields():
    """Видимые поля-сроки: тип «дата» с признаком «срок»."""
    return Field.objects.filter(type=Field.Type.DATE, hidden=False, settings__deadline=True).order_by("list_id", "order")


def _parse_date(raw) -> date | None:
    try:
        return date.fromisoformat(raw) if isinstance(raw, str) else None
    except ValueError:
        return None


def select_candidates(today: date) -> list[Candidate]:
    """Шаг 1: один запрос по всем спискам — записи не в архиве, у которых значение видимого поля-срока лежит в
    `[сегодня, сегодня + наибольший порог поля]`. Просроченные даты не берутся (решение плана)."""
    fields = list(_deadline_fields())
    if not fields:
        return []
    condition = Q()
    by_list: dict[int, list[tuple[Field, date]]] = {}
    for field in fields:
        last = today + timedelta(days=max(_thresholds(field)))
        key = KeyTextTransform(field.code, "values")
        condition |= Q(Q(list_id=field.list_id), GreaterThanOrEqual(key, Value(today.isoformat())),
                       LessThanOrEqual(key, Value(last.isoformat())))
        by_list.setdefault(field.list_id, []).append((field, last))
    found = []
    rows = Record.objects.filter(condition, archived=False).order_by("list_id", "pk").values_list(
        "pk", "list_id", "values")
    for record_id, list_id, values in rows.iterator():
        for field, last in by_list.get(list_id, ()):
            due = _parse_date((values or {}).get(field.code))
            if due is not None and today <= due <= last:
                found.append(Candidate(record_id, list_id, field.pk, due))
    return found


def _cut(text: str) -> str:
    """Часть текста: длиннее 100 знаков — первые 99 и «…»."""
    text = text or ""
    return text if len(text) <= TEXT_PART_LIMIT else text[:TEXT_PART_LIMIT - 1] + "…"


def _text(threshold: int, lst: List, record: Record, field: Field, due: date) -> str:
    """Текст уведомления; всё, что длиннее 300 знаков, — первые 299 и «…» (решение 53)."""
    head = "Срок наступил" if threshold == 0 else "Истекает срок"
    text = f"{head}: {_cut(lst.name)} — {_cut(record.title)}: {_cut(field.name)} {due:%d.%m.%Y}"
    return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT - 1] + "…"


class _Cache:
    """Кэш одного обхода: действующие сотрудники (с `Scope`, который хранится на объекте) и «Правят» по спискам."""

    def __init__(self):
        self._users: dict | None = None
        self._editors: dict[int, set] = {}

    def users(self) -> dict:
        if self._users is None:
            self._users = {user.pk: user for user in get_user_model().objects.filter(state=UserState.ACTIVE)}
        return self._users

    def editors(self, lst: List) -> set:
        if lst.pk not in self._editors:
            self._editors[lst.pk] = {pk for pk, user in self.users().items() if access.in_edit_set(user, lst)}
        return self._editors[lst.pk]


def _people(record: Record, fields) -> set[int]:
    """Номера сотрудников из значений видимых полей «сотрудник» записи."""
    found: set[int] = set()
    for field in fields:
        raw = (record.values or {}).get(field.code)
        for item in raw if isinstance(raw, (list, tuple)) else [raw]:
            if isinstance(item, int) and not isinstance(item, bool):
                found.add(item)
    return found


def notify_record(candidate: Candidate, today: date, cache: "_Cache | None" = None) -> int:
    """Шаги 2–4 для одной пары «запись, поле» в своей транзакции; возвращает число созданных уведомлений.

    Порядок замков: разделяемый замок списка → `FOR UPDATE` записи; поле, дата и отметки читаются под замком.
    Удалённая, архивная запись, скрытое поле, сменившаяся дата — пропуск (NFR-511)."""
    cache = cache or _Cache()
    with transaction.atomic():
        access.lock_list(candidate.list_id, shared=True)
        record = Record.objects.select_for_update().filter(
            pk=candidate.record_id, list_id=candidate.list_id, archived=False).first()
        if record is None:
            return 0
        field = Field.objects.filter(pk=candidate.field_id, list_id=candidate.list_id, hidden=False,
                                     type=Field.Type.DATE).first()
        if field is None or not (field.settings or {}).get("deadline"):
            return 0
        due = _parse_date((record.values or {}).get(field.code))
        if due is None or due != candidate.due_date:
            return 0
        days = (due - today).days
        if days < 0:
            return 0
        sent = set(ReminderSent.objects.filter(record=record, field=field, due_date=due).values_list(
            "threshold_days", flat=True))
        candidates = [t for t in _thresholds(field) if t >= days and t not in sent]
        if not candidates:
            return 0
        threshold = min(candidates)
        lst = List.objects.get(pk=candidate.list_id)
        person_fields = list(Field.objects.filter(list=lst, type=Field.Type.PERSON, hidden=False))
        recipients = cache.editors(lst) | {pk for pk in _people(record, person_fields) if pk in cache.users()}
        if not recipients:
            # без получателей отметок нет: появившийся позже получатель догонит порог (решение Opus И9)
            return 0
        readers, others = [], []
        for pk in sorted(recipients):
            (readers if access.can_read(cache.users()[pk], lst) else others).append(pk)
        text = _text(threshold, lst, record, field, due)
        ref = notify_kinds.make_ref(record.pk, field.pk, threshold)
        card = f"/lists/{lst.pk}/{record.number}/"
        created = 0
        from apps.notify.services import dispatch

        for url, group in ((card, readers), (PINNED_URL, others)):
            if group:
                ids = dispatch.create(notify_kinds.DEADLINE, [
                    Draft(user_id=pk, text=text, url=url, object_ref=ref) for pk in group])
                created += len(ids or [])
        ReminderSent.objects.bulk_create(
            [ReminderSent(record=record, field=field, threshold_days=t, due_date=due,
                          notified=(t == threshold)) for t in candidates])
        return created


def cleanup(today: date) -> None:
    """Шаг 5: загрузки (`ImportJob`) старше суток в любом состоянии и отметки со сроком раньше, чем год назад."""
    ImportJob.objects.filter(created_at__lt=timezone.now() - timedelta(days=1)).delete()
    ReminderSent.objects.filter(due_date__lt=today - timedelta(days=365)).delete()


def run(today: date) -> RunResult:
    """Шаги 1–5: выборка, напоминания по записям, уборка. Без приложения `notify` напоминания пропускаются целиком
    (отметок нет), уборка выполняется; сбой записи — в журнал приложения, обход продолжается."""
    notified, failed = 0, []
    if apps.is_installed("apps.notify"):
        cache = _Cache()
        for candidate in select_candidates(today):
            try:
                notified += notify_record(candidate, today, cache) or 0
            except Exception as error:  # noqa: BLE001 — сбой одной записи не должен останавливать обход
                logger.error("список %s, запись %s: %s", candidate.list_id, candidate.record_id, type(error).__name__)
                if candidate.record_id not in failed:
                    failed.append(candidate.record_id)
    cleanup(today)
    return RunResult(notified, failed)
