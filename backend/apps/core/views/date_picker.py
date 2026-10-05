"""Поле даты: сетка месяца с отметками дней (FR-148; T-2238).

Сетку видит любой вошедший (право не нужно); ответ — всегда фрагмент, даже без заголовков HTMX.
"""
import calendar
import datetime
import re

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.views.decorators.http import require_GET

from apps.core import extensions
from apps.core.widgets import moscow_today

MIN_YEAR, MAX_YEAR, YEARS_AHEAD = 1900, 2100, 5
MONTH_TITLES = ("январь", "февраль", "март", "апрель", "май", "июнь",
                "июль", "август", "сентябрь", "октябрь", "ноябрь", "декабрь")
KIND_LABELS = {"off": "выходной", "holiday": "праздник", "day_off": "перенесённый выходной",
               "workday": "перенесённый рабочий день", "short": "сокращённый день"}


def _shown_month(params, today: datetime.date) -> tuple[int, int]:
    """Месяц сетки: `month=ГГГГ-ММ` или `month=М` с `year=ГГГГ` (списки сетки); иначе — текущий по Москве."""
    month = (params.get("month") or "").strip()
    found = re.fullmatch(r"(\d{4})-(\d{2})", month)
    if found:
        year, number = int(found.group(1)), int(found.group(2))
    elif re.fullmatch(r"\d{1,2}", month) and re.fullmatch(r"\d{4}", (params.get("year") or "").strip()):
        year, number = int(params["year"].strip()), int(month)
    else:
        return today.year, today.month
    if MIN_YEAR <= year <= MAX_YEAR and 1 <= number <= 12:
        return year, number
    return today.year, today.month


def _marks(year: int, month: int) -> dict[datetime.date, str]:
    """Виды дней месяца от точки `day_marks`; без функций выходные — суббота и воскресенье."""
    funcs = extensions.registered("day_marks")
    if not funcs:
        return {datetime.date(year, month, number): "off"
                for number in range(1, calendar.monthrange(year, month)[1] + 1)
                if datetime.date(year, month, number).weekday() >= 5}
    marks = {}
    for func in funcs:
        marks.update(func(year, month))
    return marks


def _neighbour(year: int, month: int, step: int) -> str | None:
    """Соседний месяц `ГГГГ-ММ`; за пределами 1900…2100 — None (кнопка недоступна)."""
    index = year * 12 + month - 1 + step
    if not MIN_YEAR <= index // 12 <= MAX_YEAR:
        return None
    return f"{index // 12:04d}-{index % 12 + 1:02d}"


@login_required
@require_GET
def date_picker(request):
    """`/ui/date-picker/` — фрагмент сетки месяца (`?month=ГГГГ-ММ`)."""
    today = moscow_today()
    year, month = _shown_month(request.GET, today)
    marks = _marks(year, month)
    weeks = []
    for week in calendar.Calendar(firstweekday=0).monthdayscalendar(year, month):
        row = []
        for number in week:
            if not number:
                row.append(None)
                continue
            day = datetime.date(year, month, number)
            kind = marks.get(day, "work")
            row.append({"number": number, "iso": day.isoformat(), "kind": kind,
                        "label": KIND_LABELS.get(kind, ""), "today": day == today})
        weeks.append(row)
    context = {"year": year, "month": month, "month_key": f"{year:04d}-{month:02d}", "today": today.isoformat(), "weeks": weeks,
               "months": list(enumerate(MONTH_TITLES, 1)),
               "years": sorted(set(range(MIN_YEAR, today.year + YEARS_AHEAD + 1)) | {year}),
               "prev_month": _neighbour(year, month, -1), "next_month": _neighbour(year, month, 1)}
    return render(request, "widgets/date_picker_grid.html", context)
