"""T-2113: рабочий календарь и его сервисы (FR-123, FR-143…147, FR-149, FR-150, NFR-102).

Сценарии 11 (401–429), 12 (430–450) и 13 (451–466) спеки среза 002. Имена кода среза 002 импортируются внутри
тестов (`apps.org.services.calendar`, `calendar_file`); модели берутся через `support.model`. Помощники,
нужные только этому файлу (разбор разметки, засев года, ожидаемые отметки), лежат здесь.
"""
import datetime
from datetime import date, time, timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from tests import support, support_org
from tests.support import model

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
UTC = datetime.timezone.utc
TOTAL_KEYS = ("holidays_on_weekdays", "moved_days_off", "moved_workdays", "short_days", "work_days")
KINDS = ("holiday", "day_off", "workday", "short")
LETTERS = {"off": "В", "holiday": "П", "day_off": "Н", "workday": "Р", "short": "С"}
LABELS = {"off": "выходной", "holiday": "праздник", "day_off": "перенесённый выходной",
          "workday": "перенесённый рабочий день", "short": "сокращённый день"}
_VOID = {"input", "br", "img", "hr", "meta", "link", "area", "base", "col", "source", "wbr"}


# --- разбор разметки (помощник только этого файла) -------------------------------------------------

class _El:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.kids = tag, attrs, parent, []

    def walk(self):
        yield self
        for kid in self.kids:
            if isinstance(kid, _El):
                yield from kid.walk()

    def text(self) -> str:
        return " ".join(" ".join(k if isinstance(k, str) else k.text() for k in self.kids).split())

    def find_all(self, tag=None, **want):
        """Элементы (и сам) с тегом `tag` и атрибутами `want` (`data_x` -> `data-x`; True — любое значение)."""
        wanted = {key.replace("_", "-"): value for key, value in want.items()}
        return [el for el in self.walk()
                if (tag is None or el.tag == tag)
                and all(n in el.attrs and (v is True or el.attrs[n] == str(v)) for n, v in wanted.items())]

    def classes(self) -> list[str]:
        return self.attrs.get("class", "").split()


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _El("#root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        el = _El(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.kids.append(el)
        if tag not in _VOID:
            self.cur = el

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(_El(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.kids.append(data)


def dom(response) -> _El:
    builder = _Builder()
    builder.feed(response.content.decode())
    return builder.root


def has_alert(response) -> bool:
    return bool(dom(response).find_all(role="alert"))


# --- помощники данных -----------------------------------------------------------------------------

def admin():
    return support.make_with_permissions("calendar.manage", full_name="Календарёв Админ")


def viewer():
    return support.make_with_permissions("staff.view", full_name="Смотров Смотр")


def services():
    from apps.org.services import calendar as cal
    return cal


def seed_year(year: int, days: dict | None = None, *, by=None):
    """Загруженный год напрямую в базе (без служб: версия календаря не растёт). `days` — {date: kind}."""
    by = by or support.make_employee()
    now = timezone.now()
    model("org.CalendarYear").objects.create(
        year=year, loaded_at=now, loaded_by=by, file_name=f"cal{year}.csv", totals={k: 0 for k in TOTAL_KEYS})
    SpecialDay = model("org.SpecialDay")
    SpecialDay.objects.bulk_create([
        SpecialDay(date=d, kind=kind, origin="file", changed_by=by, changed_at=now) for d, kind in (days or {}).items()])
    return by


def moment(y, m, d, h=0, mi=0):
    return datetime.datetime(y, m, d, h, mi, tzinfo=MSK)


def events(action, **filters):
    return list(model("core.AuditEvent").objects.filter(action=action, **filters).order_by("id"))


def settings_row():
    return model("org.WorkCalendar").objects.get()


def weekday_expectation(day: date, weekdays=(0, 1, 2, 3, 4)) -> str:
    return "work" if day.weekday() in weekdays else "off"


def expected_marks(year: int, month: int, records: dict, weekdays=(0, 1, 2, 3, 4)) -> dict:
    """Отметки месяца по правилу плана: особый день, иначе день недели; обычные рабочие дни не входят."""
    out, day = {}, date(year, month, 1)
    while day.month == month:
        kind = records.get(day) or weekday_expectation(day, weekdays)
        if kind != "work":
            out[day] = kind
        day += timedelta(days=1)
    return out


# --- FR-143: одна запись и значения по умолчанию --------------------------------------------------

def test_one_calendar_defaults_mon_fri_9_to_18_monday_first():
    """FR-143: одна строка `WorkCalendar`, по умолчанию пн–пт, 09:00–18:00, вторую создать нельзя; на странице
    календаря неделя начинается с понедельника, а форма настроек показывает рабочими дни 0–4 (сценарий 12, п. 1)."""
    from django.db import IntegrityError, transaction

    WorkCalendar = model("org.WorkCalendar")
    assert WorkCalendar.objects.count() == 1
    row = WorkCalendar.objects.get()
    assert row.work_weekdays == [0, 1, 2, 3, 4]
    assert (row.day_start, row.day_end) == (time(9, 0), time(18, 0))
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            WorkCalendar.objects.create()
    assert WorkCalendar.objects.count() == 1
    cal = services()
    assert cal.day_kind(date(2026, 6, 15)) == "work" and cal.day_kind(date(2026, 6, 13)) == "off"
    client = support.logged_in(admin())
    page = dom(client.get("/calendar/?year=2026"))
    form = page.find_all("form", action="/calendar/settings/")[0]
    boxes = form.find_all("input", type="checkbox", name="work_weekdays")
    assert sorted(b.attrs["value"] for b in boxes) == [str(i) for i in range(7)]
    assert sorted(b.attrs["value"] for b in boxes if "checked" in b.attrs) == ["0", "1", "2", "3", "4"]
    assert form.find_all("input", name="day_start")[0].attrs["value"][:5] == "09:00"
    assert form.find_all("input", name="day_end")[0].attrs["value"][:5] == "18:00"
    month = page.find_all(data_month="1")[0]
    for row_el in month.find_all("tr"):
        cells = [c for c in row_el.kids if isinstance(c, _El) and c.tag == "td"]
        if len(cells) == 7:
            for index, cell in enumerate(cells):
                if "data-date" in cell.attrs:
                    assert date.fromisoformat(cell.attrs["data-date"]).weekday() == index, "неделя идёт с понедельника"
    assert "Пн Вт Ср Чт Пт Сб Вс" in month.text()


def test_week_needs_one_day_and_day_end_two_hours_after_start():
    """FR-143: нужен хотя бы один рабочий день, конец дня не раньше начала + 2 часа; отказ ничего не меняет;
    набор дней хранится по возрастанию без повторов; через страницу отказ — 200 с `[role=alert]` (сценарий 12, п. 2–3)."""
    from apps.org.services import OrgError

    cal, user = services(), admin()
    before = (settings_row().work_weekdays, settings_row().day_start, settings_row().day_end)

    def refuse(code, **args):
        base = dict(work_weekdays=[0, 1, 2, 3, 4], day_start=time(9, 0), day_end=time(18, 0), actor=user)
        base.update(args)
        with pytest.raises(OrgError) as error:
            cal.update_settings(**base)
        assert error.value.code == code
        row = settings_row()
        assert (row.work_weekdays, row.day_start, row.day_end) == before, "после отказа настройки прежние"

    refuse("no_weekday", work_weekdays=[])
    refuse("bad_weekday", work_weekdays=[0, 7])
    refuse("bad_weekday", work_weekdays=[-1, 2])
    refuse("day_too_short", day_end=time(10, 59))
    refuse("day_too_short", day_end=time(9, 0))
    refuse("day_too_short", day_end=time(8, 0))
    assert not events("calendar.settings_changed")
    saved = cal.update_settings(work_weekdays=[5, 0, 0, 2], day_start=time(9, 0), day_end=time(11, 0), actor=user)
    assert saved.work_weekdays == [0, 2, 5] and settings_row().work_weekdays == [0, 2, 5]
    assert settings_row().day_end == time(11, 0), "ровно два часа допустимо"
    assert cal.day_kind(date(2026, 6, 20)) == "work", "суббота без особого дня стала рабочей"
    assert cal.day_kind(date(2026, 6, 16)) == "off", "вторник перестал быть рабочим"
    client = support.logged_in(user)
    snap = (settings_row().work_weekdays, settings_row().day_start, settings_row().day_end)
    for bad in ({"day_start": "09:00", "day_end": "10:59", "work_weekdays": ["0", "1"]},
                {"day_start": "09:00", "day_end": "18:00"},
                {"day_start": "12:00", "day_end": "09:00", "work_weekdays": ["0"]}):
        response = client.post("/calendar/settings/", bad)
        assert response.status_code == 200 and has_alert(response), bad
        assert (settings_row().work_weekdays, settings_row().day_start, settings_row().day_end) == snap
    ok = client.post("/calendar/settings/", {"work_weekdays": ["0", "1", "5"], "day_start": "08:00", "day_end": "17:00"})
    assert ok.status_code == 302 and ok["Location"] == "/calendar/"
    row = settings_row()
    assert (row.work_weekdays, row.day_start, row.day_end) == ([0, 1, 5], time(8, 0), time(17, 0))


# --- FR-144, FR-145: особые дни -------------------------------------------------------------------

def test_four_special_day_kinds_short_day_one_hour_less():
    """FR-144: четыре вида особых дней (праздник, перенесённый выходной, перенесённый рабочий, сокращённый);
    сокращённый заканчивается на час раньше; неизвестный вид — `bad_kind`; пустой вид снимает запись."""
    from apps.org.services import OrgError

    cal, user = services(), admin()
    seed_year(2026)
    days = {"holiday": date(2026, 6, 12), "day_off": date(2026, 6, 15), "workday": date(2026, 6, 13),
            "short": date(2026, 6, 16)}
    SpecialDay = model("org.SpecialDay")
    for kind, day in days.items():
        cal.set_day(day, kind, actor=user)
        record = SpecialDay.objects.get(date=day)
        assert (record.kind, record.origin, record.changed_by_id) == (kind, "manual", user.pk)
        assert cal.day_kind(day) == kind
    assert SpecialDay.objects.count() == 4
    assert not cal.is_working_time(moment(2026, 6, 12, 11)), "праздник в пятницу"
    assert not cal.is_working_time(moment(2026, 6, 15, 11)), "перенесённый выходной в понедельник"
    assert cal.is_working_time(moment(2026, 6, 13, 11)), "перенесённый рабочий день в субботу"
    assert cal.is_working_time(moment(2026, 6, 16, 16, 59))
    assert not cal.is_working_time(moment(2026, 6, 16, 17, 0)), "сокращённый день кончается на час раньше (17:00)"
    assert cal.is_working_time(moment(2026, 6, 17, 17, 59)) and not cal.is_working_time(moment(2026, 6, 17, 18, 0))
    with pytest.raises(OrgError) as error:
        cal.set_day(date(2026, 6, 17), "vacation", actor=user)
    assert error.value.code == "bad_kind" and not SpecialDay.objects.filter(date=date(2026, 6, 17)).exists()
    cal.set_day(days["holiday"], "", actor=user)
    assert not SpecialDay.objects.filter(date=days["holiday"]).exists()
    assert cal.day_kind(days["holiday"]) == "work", "после снятия отметки день снова обычный"
    assert SpecialDay.objects.count() == 3


def test_day_edit_only_in_loaded_year_all_kinds():
    """FR-144, FR-145: правка дня только в загруженном году (`year_not_loaded`, ни записи, ни события); в загруженном —
    все виды, форма дня и маршрут `/calendar/days/<дата>/` (сценарий 11, п. 4)."""
    from apps.org.services import OrgError

    cal, user = services(), admin()
    SpecialDay = model("org.SpecialDay")
    seed_year(2026)
    with pytest.raises(OrgError) as error:
        cal.set_day(date(2027, 3, 10), "holiday", actor=user)
    assert error.value.code == "year_not_loaded"
    assert not SpecialDay.objects.exists() and not events("calendar.day_changed")
    client = support.logged_in(user)
    response = client.post("/calendar/days/2027-03-10/", {"kind": "holiday"})
    assert response.status_code == 200 and has_alert(response)
    assert not SpecialDay.objects.exists()
    assert client.get("/calendar/days/2027-02-30/").status_code == 404
    form_page = dom(client.get("/calendar/days/2026-06-12/"))
    form = form_page.find_all("form", data_form="calendar-day", action="/calendar/days/2026-06-12/")[0]
    select = form.find_all("select", name="kind")[0]
    options = [o.attrs.get("value") for o in select.find_all("option")]
    assert options == ["", "holiday", "day_off", "workday", "short"]
    assert [o.attrs["value"] for o in select.find_all("option") if "selected" in o.attrs] == [""], "день обычный"
    assert form.find_all("button", type="submit")
    for kind in KINDS:
        response = client.post("/calendar/days/2026-06-12/", {"kind": kind})
        assert response.status_code == 302 and response["Location"] == "/calendar/?year=2026"
        assert SpecialDay.objects.get(date=date(2026, 6, 12)).kind == kind
        selected = [o.attrs["value"] for o in dom(client.get("/calendar/days/2026-06-12/")).find_all("option")
                    if "selected" in o.attrs]
        assert selected == [kind], "в форме выбран текущий вид"
    response = client.post("/calendar/days/2026-06-12/", {"kind": ""})
    assert response.status_code == 302 and not SpecialDay.objects.exists()
    assert not model("org.CalendarYear").objects.filter(year=2027).exists()


# --- FR-146: вид дня и напоминание ----------------------------------------------------------------

def test_day_kind_special_then_weekdays_unloaded_year_weekdays_only():
    """FR-146: `day_kind` берёт особый день из `SpecialDay`, иначе — день недели по настройке; год без `CalendarYear`
    считается только по дням недели, даже если в базе лежит запись `SpecialDay` (сценарий 11, п. 5)."""
    cal = services()
    assert cal.loaded_years() == []
    seed_year(2026, {date(2026, 6, 12): "holiday", date(2026, 6, 13): "workday", date(2026, 6, 15): "day_off",
                     date(2026, 6, 16): "short"})
    assert [cal.day_kind(date(2026, 6, d)) for d in (12, 13, 14, 15, 16, 17)] == [
        "holiday", "workday", "off", "day_off", "short", "work"]
    SpecialDay = model("org.SpecialDay")
    SpecialDay.objects.create(date=date(2027, 3, 10), kind="holiday", origin="file", changed_by=support.make_employee(),
                              changed_at=timezone.now())
    assert cal.day_kind(date(2027, 3, 10)) == "work", "год не загружен: запись не учитывается, среда — рабочий день"
    assert cal.day_kind(date(2027, 3, 13)) == "off" and cal.day_kind(date(2027, 3, 12)) == "work"
    assert {cal.day_kind(date(2027, 3, d)) for d in range(1, 32)} == {"work", "off"}
    seed_year(2024)
    assert cal.loaded_years() == [2024, 2026]
    user = admin()
    cal.update_settings(work_weekdays=[0, 1, 2, 3, 4, 5], day_start=time(9, 0), day_end=time(18, 0), actor=user)
    assert cal.day_kind(date(2026, 6, 20)) == "work" and cal.day_kind(date(2026, 6, 21)) == "off"
    assert cal.day_kind(date(2026, 6, 13)) == "workday", "особый день сильнее настройки недели"
    assert cal.day_kind(date(2027, 3, 13)) == "work"
    cal.update_settings(work_weekdays=[6], day_start=time(9, 0), day_end=time(18, 0), actor=user)
    assert cal.day_kind(date(2026, 6, 17)) == "off" and cal.day_kind(date(2026, 6, 14)) == "work"
    assert cal.day_kind(date(2026, 6, 12)) == "holiday"


def _calendar_notices(user):
    from apps.core import extensions

    return [n for func in extensions.registered("home_notices") for n in func(user) if n.get("key") == "calendar-year"]


def test_reminder_whole_year_when_current_missing_and_from_december_for_next(clock, django_capture_on_commit_callbacks):
    """FR-146: напоминание — на весь год, пока текущий год не загружен, и с 1 декабря, пока не загружен следующий;
    видит его только обладатель `calendar.manage`: на `/` внутри `[data-home-notices]` и на `/calendar/`
    (сценарий 11, п. 5). Время — по Москве."""
    cal = services()
    seed_year_user = support.make_employee()
    june, december = datetime.date(2026, 6, 15), datetime.date(2026, 12, 1)
    assert cal.missing_years(june) == [2026]
    assert cal.missing_years(date(2026, 11, 30)) == [2026]
    assert cal.missing_years(december) == [2026, 2027]
    seed_year(2026, by=seed_year_user)
    assert cal.missing_years(june) == [] and cal.missing_years(date(2026, 11, 30)) == []
    assert cal.missing_years(december) == [2027] and cal.missing_years(date(2026, 12, 31)) == [2027]
    seed_year(2027, by=seed_year_user)
    assert cal.missing_years(date(2026, 12, 15)) == []
    model("org.CalendarYear").objects.filter(year=2026).delete()
    assert cal.missing_years(date(2026, 12, 15)) == [2026], "загружен следующий год, текущий — нет"
    model("org.CalendarYear").objects.all().delete()
    clock.set(datetime.datetime(2026, 6, 15, 12, 0, tzinfo=MSK))
    boss, colleague = admin(), viewer()
    boss_client, colleague_client = support.logged_in(boss), support.logged_in(colleague)
    notices = _calendar_notices(boss)
    assert [n["year"] for n in notices] == [2026]
    assert notices[0]["level"] == "warning" and notices[0]["url"] == "/calendar/upload/"
    assert "Не загружен производственный календарь на 2026 год." in notices[0]["text"]
    assert _calendar_notices(colleague) == []
    for path in ("/", "/calendar/"):
        page = dom(boss_client.get(path))
        found = page.find_all(data_notice="calendar-year")
        assert [n.attrs["data-year"] for n in found] == ["2026"], path
        assert found[0].attrs.get("role") == "status"
        assert "Не загружен производственный календарь на 2026 год." in found[0].text() and "Загрузить файл" in found[0].text()
        assert any(a.attrs.get("href") == "/calendar/upload/" for a in found[0].find_all("a"))
        assert not dom(colleague_client.get(path)).find_all(data_notice="calendar-year"), path
    assert dom(boss_client.get("/")).find_all(data_home_notices=True)[0].find_all(data_notice="calendar-year")
    seed_year(2026, by=seed_year_user)
    assert _calendar_notices(boss) == []
    assert not dom(boss_client.get("/")).find_all(data_notice="calendar-year")
    clock.set(datetime.datetime(2026, 11, 30, 21, 30, tzinfo=UTC))  # 1 декабря 00:30 по Москве
    boss_client, colleague_client = support.logged_in(boss), support.logged_in(colleague)  # прежние сессии истекли по простою
    assert cal.missing_years() == [2027], "по умолчанию «сегодня» — по Москве, а не по UTC"
    assert [n["year"] for n in _calendar_notices(boss)] == [2027]
    page = dom(boss_client.get("/calendar/"))
    assert [n.attrs["data-year"] for n in page.find_all(data_notice="calendar-year")] == ["2027"]
    assert _calendar_notices(colleague) == []


# --- FR-147, FR-123: страница календаря -----------------------------------------------------------

def test_calendar_page_12_months_marks_not_only_color_legend_year_choice(clock):
    """FR-147: страница `/calendar/` — 12 месяцев с понедельника; у дня вид, буква и скрытая подпись, а не только цвет;
    легенда; выбор года; в незагруженном году — только выходные дни недели; нечисловой год и вне 2000…2100 — текущий
    (сценарий 13, п. 1, 3)."""
    clock.set(datetime.datetime(2026, 6, 15, 12, 0, tzinfo=MSK))
    y = 2026
    records = {date(y, 3, 10): "holiday", date(y, 3, 11): "day_off", date(y, 3, 14): "workday", date(y, 3, 15): "short",
               date(y, 5, 5): "short", date(y, 12, 31): "holiday"}
    seed_year(y, records)
    seed_year(2010)
    client = support.logged_in(viewer())
    response = client.get(f"/calendar/?year={y}")
    assert response.status_code == 200
    page = dom(response)
    (container,) = page.find_all(data_calendar_year=True, data_year=str(y), data_loaded="true")
    months = container.find_all(data_month=True)
    assert sorted(int(m.attrs["data-month"]) for m in months) == list(range(1, 13))
    cells = container.find_all("td", data_date=True)
    assert len(cells) == (date(y + 1, 1, 1) - date(y, 1, 1)).days
    assert len({c.attrs["data-date"] for c in cells}) == len(cells)
    for cell in cells:
        day = date.fromisoformat(cell.attrs["data-date"])
        kind = cell.attrs["data-day-kind"]
        assert kind == (records.get(day) or weekday_expectation(day)), day
        letters = [s for s in cell.find_all("span") if "cal-letter" in s.classes()]
        hidden = [s for s in cell.find_all("span") if "visually-hidden" in s.classes()]
        assert f"cal-{kind}" in cell.classes(), day
        if kind == "work":
            assert not letters and not hidden, "у обычного дня нет ни буквы, ни подписи"
        else:
            assert [s.text() for s in letters] == [LETTERS[kind]], (day, kind)
            assert [s.text() for s in hidden] == [LABELS[kind]], (day, kind)
    for month in months:
        number = int(month.attrs["data-month"])
        assert {date.fromisoformat(c.attrs["data-date"]).month for c in month.find_all("td", data_date=True)} == {number}
        assert "Пн Вт Ср Чт Пт Сб Вс" in month.text()
    (legend,) = page.find_all(data_legend=True)
    items = {i.attrs["data-legend-item"]: i.text() for i in legend.find_all(data_legend_item=True)}
    assert set(items) == set(LETTERS)
    for kind, text in items.items():
        assert LETTERS[kind] in text and LABELS[kind] in text, kind
    select = page.find_all("select", name="year")[0]
    offered = [int(o.attrs["value"]) for o in select.find_all("option")]
    assert set(offered) == {y - 1, y, y + 1, 2010}
    assert [o.attrs["value"] for o in select.find_all("option") if "selected" in o.attrs] == [str(y)]
    form_el = select.parent
    while form_el is not None and form_el.tag != "form":
        form_el = form_el.parent
    assert form_el is not None and form_el.attrs.get("method", "get").lower() == "get", "select[name=year] — в форме GET"
    for bad in ("abc", "1999", "2101", ""):
        assert dom(client.get(f"/calendar/?year={bad}")).find_all(data_calendar_year=True)[0].attrs["data-year"] == str(y), bad
    other = dom(client.get(f"/calendar/?year={y + 1}"))
    (unloaded,) = other.find_all(data_calendar_year=True)
    assert unloaded.attrs["data-year"] == str(y + 1) and unloaded.attrs["data-loaded"] == "false"
    kinds = {c.attrs["data-day-kind"] for c in unloaded.find_all("td", data_date=True)}
    assert kinds == {"work", "off"}, "год не загружен: выделены только выходные дни недели"
    for cell in unloaded.find_all("td", data_date=True):
        day = date.fromisoformat(cell.attrs["data-date"])
        assert cell.attrs["data-day-kind"] == weekday_expectation(day)


def test_calendar_page_with_staff_view_or_calendar_manage_settings_and_day_edit_need_calendar_manage(clock):
    """FR-147, FR-123: страницу видят `staff.view` или `calendar.manage`, остальные — 403; форма недели и часов,
    ссылка загрузки и правка дня — только у `calendar.manage`, а правка дня — только в загруженном году; прямые
    запросы без права — 403 и ничего не меняют (сценарий 11, п. 6)."""
    clock.set(datetime.datetime(2026, 6, 15, 12, 0, tzinfo=MSK))
    y = 2026
    seed_year(y, {date(y, 3, 10): "holiday"})
    SpecialDay = model("org.SpecialDay")
    outsider = support.make_with_permissions("accounts.manage")
    assert support.logged_in(outsider).get("/calendar/").status_code == 403
    assert support.make_client().get("/calendar/").status_code == 302, "без входа — на вход"
    for user, may_manage in ((viewer(), False), (admin(), True)):
        client = support.logged_in(user)
        response = client.get(f"/calendar/?year={y}")
        assert response.status_code == 200
        page = dom(response)
        assert bool(page.find_all("form", action="/calendar/settings/")) == may_manage
        assert bool(page.find_all("a", data_action="calendar-upload", href="/calendar/upload/")) == may_manage
        links = {a.attrs["href"] for a in page.find_all("a", data_day_edit=True)}
        if may_manage:
            form = page.find_all("form", action="/calendar/settings/")[0]
            assert len(form.find_all("input", type="checkbox", name="work_weekdays")) == 7
            assert form.find_all("input", name="day_start") and form.find_all("input", name="day_end")
            assert f"/calendar/days/{y}-03-10/" in links
            assert len(links) == (date(y + 1, 1, 1) - date(y, 1, 1)).days, "ссылка в каждой ячейке загруженного года"
            assert not dom(client.get(f"/calendar/?year={y + 1}")).find_all("a", data_day_edit=True), "год не загружен"
        else:
            assert not links
    colleague = support.logged_in(viewer())
    row = settings_row()
    snap = (row.work_weekdays, row.day_start, row.day_end)
    assert colleague.post("/calendar/settings/", {"work_weekdays": ["0"], "day_start": "08:00", "day_end": "12:00"}).status_code == 403
    assert colleague.get(f"/calendar/days/{y}-03-10/").status_code == 403
    assert colleague.post(f"/calendar/days/{y}-03-10/", {"kind": "short"}).status_code == 403
    assert colleague.post(f"/calendar/days/{y}-03-11/", {"kind": "holiday"}).status_code == 403
    row = settings_row()
    assert (row.work_weekdays, row.day_start, row.day_end) == snap
    assert SpecialDay.objects.get(date=date(y, 3, 10)).kind == "holiday" and SpecialDay.objects.count() == 1
    assert not events("calendar.settings_changed") and not events("calendar.day_changed")


# --- FR-149: рабочее время для других срезов ------------------------------------------------------

def test_is_working_time_holiday_day_off_workday_short_day_saturday_utc_input():
    """FR-149: `is_working_time` — день недели и часы по Europe/Moscow, праздник и перенесённый выходной — нет,
    перенесённый рабочий — да, сокращённый кончается на час раньше (в том числе в субботу); время на входе в UTC
    приводится к Москве; время без пояса — `ValueError` (сценарий 12, п. 5)."""
    cal, user = services(), admin()
    seed_year(2026, {date(2026, 6, 12): "holiday", date(2026, 6, 13): "workday", date(2026, 6, 15): "day_off",
                     date(2026, 6, 16): "short", date(2026, 6, 20): "short"})
    wed = date(2026, 6, 17)
    assert cal.is_working_time(moment(wed.year, wed.month, wed.day, 9, 0)), "начало включительно"
    assert cal.is_working_time(moment(2026, 6, 17, 17, 59))
    assert not cal.is_working_time(moment(2026, 6, 17, 18, 0)), "конец не включительно"
    assert not cal.is_working_time(moment(2026, 6, 17, 8, 59))
    assert not cal.is_working_time(moment(2026, 6, 14, 12, 0)), "воскресенье"
    assert not cal.is_working_time(moment(2026, 6, 12, 11, 0)), "праздник"
    assert not cal.is_working_time(moment(2026, 6, 15, 11, 0)), "перенесённый выходной"
    assert cal.is_working_time(moment(2026, 6, 13, 11, 0)), "перенесённый рабочий день в субботу"
    assert not cal.is_working_time(moment(2026, 6, 13, 18, 0))
    assert cal.is_working_time(moment(2026, 6, 16, 16, 59)) and not cal.is_working_time(moment(2026, 6, 16, 17, 0))
    assert cal.is_working_time(moment(2026, 6, 20, 12, 0)), "сокращённый день в субботу — рабочий"
    assert cal.is_working_time(moment(2026, 6, 20, 16, 59)) and not cal.is_working_time(moment(2026, 6, 20, 17, 0))
    assert not cal.is_working_time(moment(2026, 6, 20, 8, 59))
    # UTC на входе: 06:00 UTC = 09:00 по Москве.
    assert cal.is_working_time(datetime.datetime(2026, 6, 17, 6, 0, tzinfo=UTC))
    assert not cal.is_working_time(datetime.datetime(2026, 6, 17, 5, 59, tzinfo=UTC))
    assert cal.is_working_time(datetime.datetime(2026, 6, 17, 14, 59, tzinfo=UTC))
    assert not cal.is_working_time(datetime.datetime(2026, 6, 17, 15, 0, tzinfo=UTC))
    assert cal.is_working_time(datetime.datetime(2026, 6, 17, 11, 0, tzinfo=datetime.timezone(timedelta(hours=5))))
    assert not cal.is_working_time(datetime.datetime(2026, 6, 17, 23, 0, tzinfo=datetime.timezone(timedelta(hours=5))))  # 21:00 МСК
    for naive in (datetime.datetime(2026, 6, 17, 10, 0), datetime.datetime(2026, 6, 13, 10, 0)):
        with pytest.raises(ValueError):
            cal.is_working_time(naive)
    # Граница суток по Москве: 22:00 UTC вторника — это 01:00 среды, а среда стала перенесённым выходным;
    # вторник 16 июня засеян как `short`, поэтому при day_end=23:00 он кончается в 22:00 по Москве.
    cal.update_settings(work_weekdays=[0, 1, 2, 3, 4, 5, 6], day_start=time(0, 0), day_end=time(23, 0), actor=user)
    cal.set_day(date(2026, 6, 17), "day_off", actor=user)
    assert not cal.is_working_time(datetime.datetime(2026, 6, 16, 22, 0, tzinfo=UTC)), "01:00 17 июня по Москве"
    assert cal.is_working_time(datetime.datetime(2026, 6, 16, 18, 59, tzinfo=UTC)), "21:59 16 июня по Москве"
    assert not cal.is_working_time(datetime.datetime(2026, 6, 16, 19, 0, tzinfo=UTC)), "22:00 — конец сокращённого дня"
    assert not cal.is_working_time(datetime.datetime(2026, 6, 16, 20, 0, tzinfo=UTC)), "23:00 — после конца"


def test_next_working_start_and_400_days_limit():
    """FR-149: `next_working_start` — сам момент, если он в рабочее время; иначе ближайшее начало рабочего дня с учётом
    недели и особых дней, результат по Москве; ищет не дальше 400 суток, дальше — `None`; без пояса — `ValueError`."""
    cal, user = services(), admin()
    seed_year(2026)
    seed_year(2027)
    inside = moment(2026, 6, 17, 10, 30)
    assert cal.next_working_start(inside) == inside, "рабочее время: возвращается сам момент"
    assert cal.next_working_start(moment(2026, 6, 17, 7, 0)) == moment(2026, 6, 17, 9, 0)
    assert cal.next_working_start(moment(2026, 6, 17, 18, 0)) == moment(2026, 6, 18, 9, 0)
    friday = cal.next_working_start(moment(2026, 6, 19, 18, 0))
    assert friday == moment(2026, 6, 22, 9, 0) and friday.utcoffset() == timedelta(hours=3)
    from_utc = cal.next_working_start(datetime.datetime(2026, 6, 19, 15, 0, tzinfo=UTC))
    assert from_utc == moment(2026, 6, 22, 9, 0) and from_utc.utcoffset() == timedelta(hours=3), "результат по Москве"
    cal.set_day(date(2026, 6, 22), "holiday", actor=user)
    cal.set_day(date(2026, 6, 23), "day_off", actor=user)
    cal.set_day(date(2026, 6, 20), "workday", actor=user)
    cal.set_day(date(2026, 6, 30), "short", actor=user)
    assert cal.next_working_start(moment(2026, 6, 19, 18, 0)) == moment(2026, 6, 20, 9, 0), "рабочая суббота"
    assert cal.next_working_start(moment(2026, 6, 20, 18, 0)) == moment(2026, 6, 24, 9, 0), "праздник и перенос пропущены"
    assert cal.next_working_start(moment(2026, 6, 30, 16, 59)) == moment(2026, 6, 30, 16, 59)
    assert cal.next_working_start(moment(2026, 6, 30, 17, 0)) == moment(2026, 7, 1, 9, 0), "сокращённый день уже кончился"
    with pytest.raises(ValueError):
        cal.next_working_start(datetime.datetime(2026, 6, 17, 10, 0))
    # Предел 400 суток: работают все дни недели, а особые «праздники» закрывают подряд идущие дни.
    cal.update_settings(work_weekdays=[0, 1, 2, 3, 4, 5, 6], day_start=time(9, 0), day_end=time(18, 0), actor=user)
    SpecialDay = model("org.SpecialDay")
    SpecialDay.objects.all().delete()
    start = moment(2026, 6, 15, 20, 0)
    now = timezone.now()

    def close_days(first: int, last: int):
        SpecialDay.objects.bulk_create([
            SpecialDay(date=start.date() + timedelta(days=n), kind="holiday", origin="manual", changed_by=user, changed_at=now)
            for n in range(first, last + 1)])

    close_days(0, 389)
    found = cal.next_working_start(start)
    assert found == moment(2027, 7, 10, 9, 0) and (found.date() - start.date()).days == 390
    close_days(390, 409)
    assert (start.date() + timedelta(days=410)) == date(2027, 7, 30)
    assert cal.next_working_start(start) is None, "ближайший рабочий день дальше 400 суток"


# --- NFR-102: кэш отметок месяца по номеру версии --------------------------------------------------

def test_month_marks_cached_by_calendar_version_bumped_by_settings_day_edit_and_file_apply(django_capture_on_commit_callbacks):
    """NFR-102: отметки месяца кэшируются в Valkey по ключу с номером версии (`calendar:marks:<версия>:<ГГГГ-ММ>`);
    версия (`calendar:version`) растёт на 1 при настройках, правке дня и применении файла — на фиксации;
    пустая правка, отказ и предпросмотр версию не меняют; после смены версии старый ключ не читается."""
    from apps.org.services import OrgError, calendar_file

    cal, user = services(), admin()
    seed_year(2026, {date(2026, 6, 12): "holiday", date(2026, 6, 15): "day_off"})
    SpecialDay = model("org.SpecialDay")
    records = {date(2026, 6, 12): "holiday", date(2026, 6, 15): "day_off"}
    assert cal.version() == 0 and support.valkey_int("calendar:version") == 0
    first = cal.month_marks(2026, 6)
    assert first == expected_marks(2026, 6, records)
    assert all(isinstance(k, date) and isinstance(v, str) for k, v in first.items())
    assert date(2026, 6, 17) not in first, "обычные рабочие дни в отметки не входят"
    assert support.valkey_key("calendar:marks:0:2026-06"), "результат лёг в кэш по версии 0"
    SpecialDay.objects.filter(date=date(2026, 6, 12)).update(kind="short")  # мимо служб: версия та же
    assert cal.month_marks(2026, 6) == first, "в рамках версии отметки берутся из кэша"
    # настройки недели
    with django_capture_on_commit_callbacks(execute=True):
        cal.update_settings(work_weekdays=[0, 1, 2, 3, 4, 5], day_start=time(9, 0), day_end=time(18, 0), actor=user)
    assert cal.version() == 1 and support.valkey_int("calendar:version") == 1
    after_settings = cal.month_marks(2026, 6)
    assert after_settings == expected_marks(2026, 6, {date(2026, 6, 12): "short", date(2026, 6, 15): "day_off"},
                                            weekdays=(0, 1, 2, 3, 4, 5)), "старый кэш не читается"
    assert date(2026, 6, 13) not in after_settings, "суббота стала рабочей"
    assert support.valkey_key("calendar:marks:1:2026-06")
    # пустая правка и отказ версию не меняют
    with django_capture_on_commit_callbacks(execute=True):
        cal.update_settings(work_weekdays=[0, 1, 2, 3, 4, 5], day_start=time(9, 0), day_end=time(18, 0), actor=user)
        with pytest.raises(OrgError):
            cal.update_settings(work_weekdays=[], day_start=time(9, 0), day_end=time(18, 0), actor=user)
        with pytest.raises(OrgError):
            cal.set_day(date(2027, 1, 11), "holiday", actor=user)
    assert cal.version() == 1
    # правка дня
    with django_capture_on_commit_callbacks(execute=True):
        cal.set_day(date(2026, 6, 17), "holiday", actor=user)
    assert cal.version() == 2 and support.valkey_int("calendar:version") == 2
    assert cal.month_marks(2026, 6)[date(2026, 6, 17)] == "holiday"
    assert support.valkey_key("calendar:marks:2:2026-06")
    with django_capture_on_commit_callbacks(execute=True):
        cal.set_day(date(2026, 6, 17), "holiday", actor=user)
    assert cal.version() == 2, "тот же вид — версия не растёт"
    # применение файла
    jan_before = cal.month_marks(2027, 1)
    assert date(2027, 1, 1) not in jan_before, "год не загружен: пятница 1 января — обычный день"
    with django_capture_on_commit_callbacks(execute=True):
        upload = calendar_file.make_preview(support_org.calendar_fixture("cal2027.csv"), year=2027,
                                            file_name="cal2027.csv", actor=user)
    assert cal.version() == 2, "предпросмотр календарь не меняет"
    with django_capture_on_commit_callbacks(execute=True):
        calendar_file.apply(upload, actor=user)
    assert cal.version() == 3 and support.valkey_int("calendar:version") == 3
    assert cal.month_marks(2027, 1)[date(2027, 1, 1)] == "holiday", "после применения файла кэш пересчитан"
    assert support.valkey_key("calendar:marks:3:2027-01")
    with django_capture_on_commit_callbacks(execute=True):
        calendar_file.apply(upload, actor=user)
    assert cal.version() == 3, "повторное применение того же предпросмотра ничего не меняет"


# --- FR-150: журнал -------------------------------------------------------------------------------

def test_calendar_events_settings_year_loaded_day_changed(django_capture_on_commit_callbacks):
    """FR-150: события `calendar.settings_changed`, `calendar.year_loaded` и `calendar.day_changed` — «было / стало»,
    вид объекта `calendar`; пустая правка событий не пишет; числа — целые JSON (сценарии 11, п. 7; 12, п. 4)."""
    from apps.org.services import calendar_file

    cal, user = services(), admin()
    row = settings_row()
    with django_capture_on_commit_callbacks(execute=True):
        cal.update_settings(work_weekdays=[0, 1, 2, 3, 4, 5], day_start=time(8, 30), day_end=time(17, 30), actor=user)
    (changed,) = events("calendar.settings_changed")
    assert (changed.object_type, changed.object_id, changed.actor_id) == ("calendar", str(row.pk), user.pk)
    assert changed.before["work_weekdays"] == [0, 1, 2, 3, 4] and changed.after["work_weekdays"] == [0, 1, 2, 3, 4, 5]
    assert (changed.before["day_start"], changed.before["day_end"]) == ("09:00", "18:00")
    assert (changed.after["day_start"], changed.after["day_end"]) == ("08:30", "17:30")
    with django_capture_on_commit_callbacks(execute=True):
        cal.update_settings(work_weekdays=[0, 1, 2, 3, 4, 5], day_start=time(8, 30), day_end=time(17, 30), actor=user)
    assert len(events("calendar.settings_changed")) == 1, "пустая правка событий не пишет"
    # загрузка года
    with django_capture_on_commit_callbacks(execute=True):
        upload = calendar_file.make_preview(support_org.calendar_fixture("cal2027.csv"), year=2027,
                                            file_name="cal2027.csv", actor=user)
        calendar_file.apply(upload, actor=user)
    (loaded,) = events("calendar.year_loaded")
    year = model("org.CalendarYear").objects.get(year=2027)
    assert set(year.totals) == set(TOTAL_KEYS) and all(isinstance(v, int) for v in year.totals.values())
    assert (loaded.object_type, loaded.object_id, loaded.actor_id) == ("calendar", "2027", user.pk)
    assert loaded.before == {"year": 2027, "totals": {}}, "год не был загружен"
    assert loaded.after["year"] == 2027 and loaded.after["totals"] == year.totals
    assert loaded.after["file_name"] == "cal2027.csv"
    with django_capture_on_commit_callbacks(execute=True):
        again = calendar_file.make_preview(support_org.calendar_fixture("cal2027.csv"), year=2027,
                                           file_name="again.csv", actor=user)
        calendar_file.apply(again, actor=user)
    second = events("calendar.year_loaded")[-1]
    assert len(events("calendar.year_loaded")) == 2
    assert second.before["totals"] == year.totals and second.before["year"] == 2027
    assert second.after["file_name"] == "again.csv"
    # правка дня: день обычный → праздник → сокращённый → обычный
    day = next(d for d in (date(2027, 3, n) for n in range(1, 32)) if cal.day_kind(d) == "work")
    chain = [("holiday", ""), ("short", "holiday"), ("", "short")]
    for new, old in chain:
        with django_capture_on_commit_callbacks(execute=True):
            cal.set_day(day, new, actor=user)
    with django_capture_on_commit_callbacks(execute=True):
        cal.set_day(day, "", actor=user)
    made = events("calendar.day_changed")
    assert len(made) == 3, "повтор того же вида событий не пишет"
    for event, (new, old) in zip(made, chain):
        assert (event.object_type, event.object_id, event.actor_id) == ("calendar", day.isoformat(), user.pk)
        assert event.before == {"date": day.isoformat(), "kind": old}
        assert event.after == {"date": day.isoformat(), "kind": new}
    assert not model("org.SpecialDay").objects.filter(date=day).exists()
