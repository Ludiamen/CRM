"""Страницы «Календарь»: год, настройки, загрузка года, правка дня (FR-143…148; T-2237).

Правила — в службах `calendar` и `calendar_file`; здесь формы, разбор запроса и ответ. Проверки прав стоят
на представлениях (T-2230a). День в адресе — строка `<str:day>`: ГГГГ-ММ-ДД разбирает представление, неверная
дата — 404. Время и даты — по Москве.
"""
import calendar as stdlib_calendar
import datetime
import re

from django.http import Http404, HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.services import permissions
from apps.core.services.permissions import require_any_permission, require_permission
from apps.core.views.common import flash, render_page
from apps.org.models import CalendarUpload, SpecialDay
from apps.org.services import calendar as calendar_service
from apps.org.services import calendar_file as calendar_file_service
from apps.org.services.errors import OrgError

MIN_YEAR, MAX_YEAR = 2000, 2100
MONTHS = ["Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь",
          "Декабрь"]
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
# Буква и подпись вида дня — решение Opus (G1); у обычного рабочего дня их нет.
LETTERS = {"off": "В", "holiday": "П", "day_off": "Н", "workday": "Р", "short": "С"}
LABELS = {"off": "выходной", "holiday": "праздник", "day_off": "перенесённый выходной",
          "workday": "перенесённый рабочий день", "short": "сокращённый день"}
LEGEND = [{"kind": kind, "letter": LETTERS[kind], "label": LABELS[kind]}
          for kind in ("off", "holiday", "day_off", "workday", "short")]
DAY_KINDS = [("", "обычный день"), ("holiday", "праздник"), ("day_off", "перенесённый выходной"),
             ("workday", "перенесённый рабочий день"), ("short", "сокращённый день")]
DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
NO_FILE = "Выберите файл календаря (CSV)."
BAD_YEAR = f"Год — целое число от {MIN_YEAR} до {MAX_YEAR}."
BAD_WEEK = "Рабочие дни недели — числа от 0 (понедельник) до 6 (воскресенье)."
BAD_TIME = "Начало и конец рабочего дня — время в виде ЧЧ:ММ."


def _today() -> datetime.date:
    return calendar_service._today()


def _year_param(raw: str | None) -> int:
    """`?year=`: нечисловой или вне 2000…2100 — текущий год по Москве."""
    today = _today().year
    if raw is None or not raw.isascii() or not raw.isdigit():
        return today
    year = int(raw)
    return year if MIN_YEAR <= year <= MAX_YEAR else today


def _time(raw: str | None) -> datetime.time:
    try:
        return datetime.datetime.strptime((raw or "").strip(), "%H:%M").time()
    except ValueError:
        raise OrgError("bad_time", BAD_TIME) from None


def _months(year: int, can_edit: bool) -> list[dict]:
    """Двенадцать месяцев с понедельника; отметки берутся из кэша `month_marks`."""
    result = []
    for number in range(1, 13):
        marks = calendar_service.month_marks(year, number)
        weeks = []
        for week in stdlib_calendar.Calendar(firstweekday=0).monthdayscalendar(year, number):
            row = []
            for day in week:
                if not day:
                    row.append(None)
                    continue
                moment = datetime.date(year, number, day)
                kind = marks.get(moment, "work")
                row.append({"date": moment.isoformat(), "day": day, "kind": kind,
                            "letter": LETTERS.get(kind, ""), "label": LABELS.get(kind, ""), "edit": can_edit})
            weeks.append(row)
        result.append({"number": number, "name": MONTHS[number - 1], "weeks": weeks})
    return result


def _year_page(request, year: int, *, error: str = "", status: int = 200):
    can_manage = permissions.has_permission(request.user, "calendar.manage")
    loaded = calendar_service.loaded_years()
    today = _today().year
    years = sorted({today - 1, today, today + 1, year, *loaded})
    settings = calendar_service._settings()
    context = {
        "year": year, "years": years, "is_loaded": year in loaded, "months": _months(year, can_manage and year in loaded),
        "weekday_names": WEEKDAYS, "legend": LEGEND, "can_manage": can_manage, "error": error,
        "notices": calendar_service.calendar_notices(request.user),
        "week_boxes": [{"value": i, "name": name, "checked": i in settings.work_weekdays}
                       for i, name in enumerate(WEEKDAYS)],
        "day_start": settings.day_start.strftime("%H:%M"), "day_end": settings.day_end.strftime("%H:%M"),
    }
    return render_page(request, "calendar/year.html", context, status=status)


@require_any_permission("staff.view", "calendar.manage")
@require_GET
def calendar_year(request):
    """`/calendar/` — календарь года; `?year=`."""
    return _year_page(request, _year_param(request.GET.get("year")))


@require_permission("calendar.manage")
@require_POST
def calendar_settings(request):
    """`/calendar/settings/` — рабочие дни недели, начало и конец дня."""
    try:
        try:
            weekdays = [int(value) for value in request.POST.getlist("work_weekdays")]
        except ValueError:
            raise OrgError("bad_weekday", BAD_WEEK) from None
        calendar_service.update_settings(
            work_weekdays=weekdays, day_start=_time(request.POST.get("day_start")),
            day_end=_time(request.POST.get("day_end")), actor=request.user, ip=request.client_ip)
    except OrgError as error:
        return _year_page(request, _today().year, error=str(error))
    flash(request, "Рабочая неделя сохранена.")
    return HttpResponseRedirect("/calendar/")


def _upload_page(request, *, error: str = ""):
    return render_page(request, "calendar/upload.html", {
        "error": error, "default_year": _today().year, "min_year": MIN_YEAR, "max_year": MAX_YEAR,
        "max_mb": calendar_file_service.MAX_BYTES // (1024 * 1024)})


@require_permission("calendar.manage")
@require_http_methods(["GET", "POST"])
def calendar_upload(request):
    """`/calendar/upload/` — файл года; успех — 302 на предпросмотр, отказ — 200 с `[role=alert]`."""
    if request.method == "GET":
        return _upload_page(request)
    raw_year = (request.POST.get("year") or "").strip()
    if not raw_year.isascii() or not raw_year.isdigit() or not MIN_YEAR <= int(raw_year) <= MAX_YEAR:
        return _upload_page(request, error=BAD_YEAR)
    upload = request.FILES.get("file")
    if upload is None:
        return _upload_page(request, error=NO_FILE)
    content = upload.read(calendar_file_service.MAX_BYTES + 1)
    try:
        item = calendar_file_service.make_preview(content, year=int(raw_year), file_name=upload.name,
                                                  actor=request.user, ip=request.client_ip)
    except OrgError as error:
        return _upload_page(request, error=str(error))
    return HttpResponseRedirect(f"/calendar/upload/{item.pk}/")


@require_permission("calendar.manage")
@require_http_methods(["GET", "POST"])
def calendar_upload_preview(request, upload_id: int):
    """`/calendar/upload/<id>/` — предпросмотр и применение; стёртый предпросмотр — 404."""
    item = get_object_or_404(CalendarUpload, pk=upload_id)
    if request.method == "POST":
        if request.POST.get("confirm") != "1":
            return HttpResponseRedirect(f"/calendar/upload/{item.pk}/")
        # повторное подтверждение — без действия и без сообщения об успехе (R-2237-2)
        already = item.state == CalendarUpload.State.APPLIED
        try:
            calendar_file_service.apply(item, actor=request.user, ip=request.client_ip)
        except CalendarUpload.DoesNotExist:
            raise Http404 from None
        if not already:
            flash(request, f"Календарь на {item.year} год загружен.")
        return HttpResponseRedirect(f"/calendar/?year={item.year}")
    return render_page(request, "calendar/preview.html", {
        "item": item, "totals": item.totals, "warnings": calendar_file_service.preview_warnings(item),
        "applied": item.state == CalendarUpload.State.APPLIED})


def _parse_day(raw: str) -> datetime.date:
    if not DAY_RE.match(raw):
        raise Http404
    try:
        return datetime.date.fromisoformat(raw)
    except ValueError:
        raise Http404 from None


def _day_page(request, day: datetime.date, *, error: str = ""):
    current = calendar_service.day_kind(day)
    return render_page(request, "calendar/day.html", {
        "day": day, "day_iso": day.isoformat(), "kinds": DAY_KINDS, "error": error,
        "selected": current if current in SpecialDay.Kind.values else ""})


@require_permission("calendar.manage")
@require_http_methods(["GET", "POST"])
def calendar_day(request, day: str):
    """`/calendar/days/<ГГГГ-ММ-ДД>/` — правка вида дня."""
    moment = _parse_day(day)
    if request.method == "GET":
        return _day_page(request, moment)
    try:
        calendar_service.set_day(moment, request.POST.get("kind", ""), actor=request.user, ip=request.client_ip)
    except OrgError as error:
        return _day_page(request, moment, error=str(error))
    return HttpResponseRedirect(f"/calendar/?year={moment.year}")
