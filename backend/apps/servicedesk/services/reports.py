"""Показатели отчёта по заявкам (FR-746…750, решения 5б, 9 и 11)."""
import io
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from apps.core.models import User
from apps.core.services import audit
from django.db.models import Avg, Count, Q
from apps.org.services import structure

from ..models import Category, SlaCycle, SlaLevel, Ticket

MOSCOW = ZoneInfo("Europe/Moscow")
# Москва с 2014 года без перехода на летнее время: фиксированный сдвиг для быстрой записи дат в Excel.
MSK_FIXED = timezone(timedelta(hours=3))
PERIODS = ("day", "week", "month", "custom")


class ReportError(ValueError):
    def __init__(self, code, field, message):
        super().__init__(message)
        self.code, self.field, self.message = code, field, message


@dataclass(frozen=True)
class ReportPeriod:
    kind: str
    date_from: date
    date_to: date

    @property
    def start(self):
        from django.utils import timezone
        return timezone.make_aware(datetime.combine(self.date_from, time.min), MOSCOW)

    @property
    def end(self):
        from django.utils import timezone
        return timezone.make_aware(datetime.combine(self.date_to + timedelta(days=1), time.min), MOSCOW)


def _date(value, field):
    """Дата периода из строки формы: ДД.ММ.ГГГГ или ГГГГ-ММ-ДД (поле даты портала, FR-148)."""
    from apps.core.widgets import parse_date

    parsed = parse_date(str(value or ""))
    if parsed is None:
        raise ReportError("report_period_range", field, "Укажите корректную дату периода отчёта")
    return parsed


def period_from_params(params):
    from django.utils import timezone
    kind = params.get("period") or "month"
    if kind not in PERIODS:
        raise ReportError("report_period_range", "period", "Неизвестный период отчёта")
    today = timezone.now().astimezone(MOSCOW).date()
    if kind == "day":
        start = _date(params.get("date"), "from") if params.get("date") else today
        finish = start
    elif kind == "week":
        start = today - timedelta(days=today.weekday())
        finish = start + timedelta(days=6)
    elif kind == "month":
        start = today.replace(day=1)
        finish = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    else:
        start, finish = _date(params.get("from"), "from"), _date(params.get("to"), "to")
    if finish < start or (finish - start).days > 369:
        raise ReportError("report_period_range", "from", "Период отчёта не может быть длиннее 370 дней")
    return ReportPeriod(kind, start, finish)


def _int_param(params, name):
    try:
        return int(params.get(name)) if params.get(name) else None
    except (TypeError, ValueError):
        return None


def _empty_numbers():
    return {"created": 0, "closed": 0, "average_reaction_minutes": 0,
            "average_solution_minutes": 0, "reaction_on_time": 0,
            "solution_on_time": 0, "closed_without_response": 0}


def _cycles(user, filters, params):
    """Текущие циклы в области `managed_units` с фильтрами; `(managed, cycles)`."""
    managed = structure.managed_units(user)
    if not managed:
        raise ReportError("report_forbidden", "report", "Отчёт доступен только руководителю управляемой очереди")
    cycles = SlaCycle.objects.filter(is_current=True, queue_id__in=managed)
    if filters["queue"]:
        cycles = cycles.filter(queue_id=filters["queue"])
    if filters["sla"]:
        cycles = cycles.filter(level_id=filters["sla"])
    if filters["category"]:
        cycles = cycles.filter(category_id=filters["category"])
    if filters["assignee"]:
        cycles = cycles.filter(assignee_id=filters["assignee"])
    return managed, cycles


def build(user, params):
    """Показатели и строки отчёта в области `managed_units`; агрегаты — SQL, без загрузки всех циклов."""
    from django.db.models import Avg, Count

    report_period = period_from_params(params)
    filters = {name: _int_param(params, name) for name in ("queue", "sla", "category", "assignee")}
    managed, cycles = _cycles(user, filters, params)
    start = report_period.start
    end = report_period.end
    tickets = Ticket.objects.filter(queue_id__in=managed, created_at__gte=start, created_at__lt=end)
    if any(filters.values()):
        tickets = tickets.filter(pk__in=cycles.values("ticket_id"))
    closed = cycles.filter(closed_at__gte=start, closed_at__lt=end)
    numbers = _empty_numbers()
    numbers["created"] = tickets.count()
    numbers["closed"] = closed.count()
    averages = closed.aggregate(reaction=Avg("reaction_minutes"), solution=Avg("solution_minutes"))
    numbers["average_reaction_minutes"] = round(averages["reaction"] or 0)
    numbers["average_solution_minutes"] = round(averages["solution"] or 0)
    reaction = closed.filter(reaction_met__in=(True, False)).aggregate(ok=Count("pk", filter=Q(reaction_met=True)),
                                                                      total=Count("pk"))
    solution = closed.filter(solution_met__in=(True, False)).aggregate(ok=Count("pk", filter=Q(solution_met=True)),
                                                                      total=Count("pk"))
    numbers["reaction_on_time"] = round(100 * reaction["ok"] / reaction["total"]) if reaction["total"] else 0
    numbers["solution_on_time"] = round(100 * solution["ok"] / solution["total"]) if solution["total"] else 0
    numbers["closed_without_response"] = closed.filter(reaction_met__isnull=True).count()
    overdue = list(closed.filter(solution_met=False).values("level_title").annotate(amount=Count("pk"))
                   .order_by("-amount", "level_title").values_list("level_title", "amount"))
    load = list(closed.values("assignee_name").annotate(amount=Count("pk")).order_by("-amount", "assignee_name")
                .values_list("assignee_name", "amount"))
    load = [(name or "Не назначен", amount) for name, amount in load]
    page_rows = list(tickets.order_by("number").values_list("number", "pk")[:200])
    snapshots = {ticket_id: (level, category, assignee)
                 for ticket_id, level, category, assignee in
                 cycles.filter(ticket_id__in=[pk for _, pk in page_rows])
                 .values_list("ticket_id", "level_title", "category_name", "assignee_name")}
    rows = [{"number": number, "level": snapshots.get(pk, ("", "", ""))[0],
             "category": snapshots.get(pk, ("", "", ""))[1],
             "assignee": snapshots.get(pk, ("", "", ""))[2]} for number, pk in page_rows]
    return {"period": report_period, "numbers": numbers, "tickets": rows,
            "overdue": overdue, "load": load, "managed_units": managed, "requester_rating": None,
            "filters": filters}


def choices(user):
    unit_ids = structure.managed_units(user)
    cycle_ids = SlaCycle.objects.filter(is_current=True, queue_id__in=unit_ids)
    return {
        "queues": [{"pk": ref.id, "name": ref.name}
                   for ref in structure.unit_refs(unit_ids).values()],
        "levels": SlaLevel.objects.filter(sla_cycles__in=cycle_ids).distinct().order_by("priority", "pk"),
        "categories": Category.objects.filter(sla_cycles__in=cycle_ids).distinct().order_by("name"),
        "assignees": User.objects.filter(sla_cycles__in=cycle_ids).distinct().order_by("full_name", "pk"),
    }


EXPORT_COLUMNS = ("номер", "создана", "закрыта", "очередь", "уровень", "срок реакции", "факт реакции",
                  "срок решения", "факт решения", "вердикты", "вид закрытия", "исполнитель")
METRIC_TITLES = (
    ("created", "Создано"), ("closed", "Закрыто"),
    ("average_reaction_minutes", "Среднее время реакции, минут"),
    ("average_solution_minutes", "Среднее время решения, минут"),
    ("reaction_on_time", "Реакция в срок, %"), ("solution_on_time", "Решение в срок, %"),
    ("closed_without_response", "Закрыто без ответа"), ("requester_rating", "Оценка заявителей"),
)


def _verdicts(row) -> str:
    """Строка вердиктов листа «Заявки»: «реакция: в срок, решение: с просрочкой»."""
    titles = {True: "в срок", False: "с просрочкой", None: "нет факта"}
    return f"реакция: {titles[row.reaction_met]}, решение: {titles[row.solution_met]}"


def export(user, params):
    """Книга xlsx с листами «Показатели» и «Заявки» (до 20 000 строк) в области `managed_units` пользователя."""
    from openpyxl import Workbook

    context = build(user, params)
    numbers = context["numbers"]
    period = context["period"]
    managed, cycles = _cycles(user, context["filters"], params)
    rows = (cycles.filter(ticket__created_at__gte=period.start, ticket__created_at__lt=period.end)
            .values_list("ticket__number", "ticket__created_at", "closed_at", "queue_name", "level_title",
                         "reaction_due", "first_response_at", "solution_due", "reaction_met", "solution_met",
                         "closed_kind", "assignee_name")[:20_000])
    workbook = Workbook(write_only=True)
    metrics = workbook.create_sheet("Показатели")
    metrics.append(["показатель", "значение"])
    for key, title in METRIC_TITLES:
        metrics.append([key, "" if key == "requester_rating" else numbers[key]])
    tickets = workbook.create_sheet("Заявки")
    tickets.append(list(EXPORT_COLUMNS))

    def local(value):
        """Дата строкой по Москве — так выгрузка строится заметно быстрее ячеек с типом даты."""
        return value.astimezone(MSK_FIXED).strftime("%d.%m.%Y %H:%M") if value is not None else ""

    titles = {True: "в срок", False: "с просрочкой", None: "нет факта"}
    kinds = {"manual": "вручную", "autoclosed": "автоматически"}
    for (number, created_at, closed_at, queue_name, level_title, reaction_due, responded, solution_due,
         reaction_met, solution_met, closed_kind, assignee_name) in rows.iterator(chunk_size=4000):
        tickets.append([
            number, local(created_at), local(closed_at), queue_name, level_title, local(reaction_due),
            local(responded), local(solution_due), local(closed_at),
            f"реакция: {titles[reaction_met]}, решение: {titles[solution_met]}",
            kinds.get(closed_kind, ""), assignee_name,
        ])
    buffer = io.BytesIO()
    workbook.save(buffer)
    audit.record("servicedesk.report_exported", actor=user, object_type="servicedesk.report", object_id="0",
                 after={"period": period.kind, "from": period.date_from.isoformat(),
                        "to": period.date_to.isoformat()})
    return buffer.getvalue()


def filename(now=None) -> str:
    """Имя файла выгрузки: `tickets-YYYY-MM-DD.xlsx` по Москве."""
    from django.utils import timezone as django_timezone

    day = (now or django_timezone.now()).astimezone(MOSCOW).date()
    return f"tickets-{day.isoformat()}.xlsx"
