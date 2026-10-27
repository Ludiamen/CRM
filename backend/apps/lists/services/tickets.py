"""Сервис: связи записей списков с заявками (срез 006; PLAN-006, «Связь с заявками»; CONTRACT-006, 5.5, 5.7).

Заявки видит только `apps.servicedesk.services.public` (`ticket_brief`, `briefs`) и только под
`apps.is_installed("apps.servicedesk")`; модели сервис-деска не импортируются, номер заявки в `TicketLink` — число.
Права (П3): запись читает тот, кто читает её список, и видит заявку; права «правит» не нужно. Нет записи, список не
читается или заявка не видна — один `Http404`. В журнал связи не пишутся (FR-528).
"""
import re

from django.apps import apps
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db import transaction
from django.db.models import F, Q
from django.http import Http404
from django.template.loader import render_to_string

from apps.core.extensions import ParsedQuery
from apps.lists.models import List, Record, TicketLink
from apps.lists.services import access, search
from apps.lists.services.errors import RecordArchived

PICK_LIMIT = 10
MAX_QUERY = 200
MAX_WORDS = 8
MIN_WORD = 2
MAX_NUMBER_DIGITS = 9
CONFIG = "russian"

_WORD = re.compile(r"\w+")
_NUMBER = re.compile(r"#?([0-9]+)")


def installed() -> bool:
    """Сервис-деск включён: без него раздела, подсказки и привязок нет."""
    return apps.is_installed("apps.servicedesk")


def _brief(user, number: int):
    """Справка о заявке, которую видит `user`; нет модуля, нет заявки или она не видна — `Http404` (один ответ)."""
    if not installed():
        raise Http404("Страница не найдена")
    from apps.servicedesk.services import public

    found = public.ticket_brief(user, number)
    if found is None:
        raise Http404("Заявка не найдена")
    return found


def _readable_ids(user) -> list[int]:
    """Списки, которые `user` читает (управляющему — все)."""
    current = access.scope(user)
    if current.manage:
        return list(List.objects.values_list("pk", flat=True))
    return list(current.readable)


def _links(user, number: int):
    """Связи заявки с записями читаемых списков, по порядку привязки."""
    found = TicketLink.objects.filter(ticket_number=number)
    current = access.scope(user)
    if not current.manage:
        found = found.filter(record__list_id__in=current.readable)
    return found.select_related("record", "record__list").order_by("linked_at", "pk")


def render(request, ref) -> str | None:
    """Раздел «Записи списков» карточки заявки; `None` — раздела нет: нет сервис-деска, заявка не видна смотрящему или он
    не читает ни одного списка."""
    user = request.user
    if not installed():
        return None
    from apps.servicedesk.services import public

    if public.ticket_brief(user, ref.number) is None or not access.sees_section(user):
        return None
    return render_to_string("lists/_ticket_section.html", section_context(user, ref.number), request=request)


def section_context(user, number: int, *, alert=None) -> dict:
    """Контекст раздела: номер заявки, строки связей, отказ (`alert` — `ListsError`) или ничего."""
    return {"ticket_number": number, "rows": list(_links(user, number)), "alert": alert}


def _words(text: str) -> list[str]:
    return [word for word in _WORD.findall(text.lower()) if len(word) >= MIN_WORD][:MAX_WORDS]


def pick(user, ticket_number: int, q: str) -> list[Record]:
    """До 10 записей не в архиве читаемых списков: по началу слова названия и видимых текстовых полей (префиксный
    запрос по вектору записи), по номеру записи целиком (цифры, можно с `#`) и по запросу целиком, равному значению
    видимого уникального поля. Заявку не видит — `Http404`."""
    _brief(user, ticket_number)
    text = " ".join((q or "").split())[:MAX_QUERY]
    if not text:
        return []
    ids = _readable_ids(user)
    words = _words(text)
    parsed = ParsedQuery(words=words, number=None, raw=" & ".join(f"{word}:*" for word in words), hint="", text=text)
    found = search.record_condition(parsed, ids, archived=False) or Q(pk__in=[])
    digits = _NUMBER.fullmatch(text)
    if digits and len(digits.group(1)) <= MAX_NUMBER_DIGITS:
        found |= Q(number=int(digits.group(1)), list_id__in=ids, archived=False)
    records = Record.objects.filter(found).select_related("list")
    if parsed.raw:
        query = SearchQuery(parsed.raw, config=CONFIG, search_type="raw")
        records = records.annotate(rank=SearchRank(F("search"), query)).order_by("-rank", "list_id", "number", "pk")
    else:
        records = records.order_by("list_id", "number", "pk")
    return list(records[:PICK_LIMIT])


def link(user, ticket_number: int, record_id: int) -> TicketLink:
    """Привязывает запись к заявке; повтор возвращает прежнюю связь. Записи нет, список не читается или заявка не видна —
    `Http404`; запись в архиве — `RecordArchived`."""
    _brief(user, ticket_number)
    with transaction.atomic():
        record = Record.objects.select_for_update().filter(pk=record_id).first()
        if record is None:
            raise Http404("Запись не найдена")
        access.get_list(user, record.list_id)
        if record.archived:
            raise RecordArchived()
        found, _created = TicketLink.objects.get_or_create(
            record=record, ticket_number=ticket_number, defaults={"linked_by": user})
    return found


def unlink(user, link_id: int) -> int:
    """Отвязывает запись от заявки и возвращает номер заявки; нет связи, заявка не видна или список записи не читается —
    `Http404`."""
    found = TicketLink.objects.filter(pk=link_id).select_related("record").first()
    if found is None:
        raise Http404("Связь не найдена")
    _brief(user, found.ticket_number)
    access.get_list(user, found.record.list_id)
    number = found.ticket_number
    found.delete()
    return number


def related(user, record: Record) -> list:
    """Заявки записи в виде `TicketBrief`: только видимые `user` (невидимые пропускает сервис-деск); без сервис-деска —
    пустой список."""
    if not installed():
        return []
    from apps.servicedesk.services import public

    numbers = list(TicketLink.objects.filter(record=record).order_by("linked_at", "pk")
                   .values_list("ticket_number", flat=True))
    briefs = public.briefs(user, numbers)
    return [briefs[number] for number in numbers if number in briefs]
