"""T-2112: файл производственного календаря (FR-123, FR-144, FR-145, NFR-108). Сценарий 11 спеки SPEC-002.

Итоги по годам берутся из `tests/fixtures/calendar/SOURCE.md` и из самих файлов, а не придумываются.
Имена кода среза 002 импортируются внутри тестов: сбор проходит до появления кода.
"""
import datetime
from collections import Counter
from html.parser import HTMLParser

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from tests import support, support_org
from tests.support import model

pytestmark = pytest.mark.django_db

MAX_BYTES = 1_048_576
KINDS = {"holiday", "day_off", "workday", "short"}

# Итоги настоящих файлов (SOURCE.md, «Сверка с постановлениями»). Рабочая суббота с «*» (02.11.2024,
# 01.11.2025, 20.02.2027) считается только в `short_days` (решение Q13), поэтому `moved_workdays` 2024 — два дня.
REAL = {
    2024: {"holidays_on_weekdays": 12, "moved_days_off": 5, "moved_workdays": 2, "short_days": 5, "work_days": 248},
    2025: {"holidays_on_weekdays": 10, "moved_days_off": 5, "moved_workdays": 0, "short_days": 4, "work_days": 247},
    2026: {"holidays_on_weekdays": 10, "moved_days_off": 4, "moved_workdays": 0, "short_days": 4, "work_days": 247},
    2027: {"holidays_on_weekdays": 9, "moved_days_off": 6, "moved_workdays": 0, "short_days": 4, "work_days": 247},
}
KIND_BY_TOTAL = {"holidays_on_weekdays": "holiday", "moved_days_off": "day_off", "moved_workdays": "workday",
                 "short_days": "short"}


# --- помощники этого файла ------------------------------------------------------------------------

def cf():
    from apps.org.services import calendar_file
    return calendar_file


def cal():
    from apps.org.services import calendar
    return calendar


def expect_code(code, func, *args, **kwargs):
    """Служба отказывает `OrgError` с нужным кодом; возвращает ошибку."""
    from apps.org.services import OrgError

    with pytest.raises(OrgError) as raised:
        func(*args, **kwargs)
    assert raised.value.code == code, f"ожидали код {code!r}, получили {raised.value.code!r}"
    return raised.value


def fixture(name: str) -> bytes:
    return support_org.calendar_fixture(name)


def date_(text: str) -> datetime.date:
    return datetime.date.fromisoformat(text)


def manager():
    """Тот, у кого есть право «Рабочий календарь» (и только оно)."""
    return support.make_with_permissions("calendar.manage")


class Node:
    def __init__(self, tag, attrs):
        self.tag, self.attrs, self.content = tag, attrs, []

    def text(self) -> str:
        return " ".join(c if isinstance(c, str) else c.text() for c in self.content).strip()

    def walk(self):
        yield self
        for child in self.content:
            if isinstance(child, Node):
                yield from child.walk()


class _Parser(HTMLParser):
    VOID = {"br", "input", "img", "meta", "link", "hr"}

    def __init__(self):
        super().__init__()
        self.root = Node("#root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v or "") for k, v in attrs})
        self.stack[-1].content.append(node)
        if tag not in self.VOID:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].content.append(Node(tag, {k: (v or "") for k, v in attrs}))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].content.append(data)


def nodes(response, *, tag=None, **attrs) -> list[Node]:
    """Элементы ответа с нужным тегом и атрибутами (`True` — атрибут есть, строка — равен ей)."""
    parser = _Parser()
    parser.feed(response.content.decode("utf-8"))
    found = []
    for node in parser.root.walk():
        if tag and node.tag != tag:
            continue
        if all(name in node.attrs and (want is True or node.attrs[name] == want)
               for name, want in {k.replace("_", "-"): v for k, v in attrs.items()}.items()):
            found.append(node)
    return found


def alert_text(response) -> str:
    alerts = nodes(response, role="alert")
    assert alerts, "в ответе нет [role=alert]"
    return " ".join(a.text() for a in alerts)


def upload_file(client, content: bytes, year, name: str = "calendar.csv"):
    return client.post("/calendar/upload/", {
        "year": year, "file": SimpleUploadedFile(name, content, content_type="text/csv")})


def special_days(year: int | None = None) -> list[tuple]:
    """Особые дни (дата, вид, происхождение) по возрастанию даты."""
    query = model("org.SpecialDay").objects.order_by("date")
    if year is not None:
        query = query.filter(date__year=year)
    return [(d.date.isoformat(), d.kind, d.origin) for d in query]


def years_state() -> list[tuple]:
    return list(model("org.CalendarYear").objects.order_by("year").values_list("year", "file_name", "totals"))


def make_special(day: str, kind: str, origin: str, user):
    return model("org.SpecialDay").objects.create(
        date=date_(day), kind=kind, origin=origin, changed_by=user, changed_at=timezone.now())


def make_year(year: int, user, totals: dict | None = None, file_name: str = "old.csv"):
    return model("org.CalendarYear").objects.create(
        year=year, loaded_at=timezone.now(), loaded_by=user, file_name=file_name,
        totals=totals if totals is not None else dict(REAL[2026]))


def year_events():
    return list(model("core.AuditEvent").objects.filter(action="calendar.year_loaded").order_by("id"))


def set_weekdays(weekdays):
    model("org.WorkCalendar").objects.update(work_weekdays=list(weekdays))


def snapshot():
    return special_days(), years_state(), support.valkey_int("calendar:version"), len(year_events())


# --- разбор и сверка -----------------------------------------------------------------------------

def test_parse_real_files_2024_2027_totals_match():
    """FR-145: настоящие файлы 2024–2027 разбираются; итоги по видам и рабочие дни совпадают с SOURCE.md и с
    итоговой колонкой файла; набор из четырёх лет в одном файле даёт те же дни, что одногодичные файлы."""
    ParsedYear = cf().ParsedYear
    for year, expected in REAL.items():
        parsed = cf().parse(fixture(f"cal{year}.csv"), year=year)
        assert isinstance(parsed, ParsedYear) and parsed.year == year
        assert parsed.totals == expected, f"{year}: итоги разбора"
        days = [d for d, _ in parsed.days]
        assert days == sorted(days) and len(set(days)) == len(days), f"{year}: даты по возрастанию, без повторов"
        assert all(isinstance(d, datetime.date) and d.year == year for d in days)
        assert {k for _, k in parsed.days} <= KINDS
        counted = Counter(k for _, k in parsed.days)
        for key, kind in KIND_BY_TOTAL.items():
            assert counted[kind] == expected[key], f"{year}: число дней вида {kind}"
        assert len(parsed.days) == sum(expected[k] for k in KIND_BY_TOTAL), f"{year}: сумма видов равна числу дней"
        # итоговая колонка файла «Всего рабочих дней» (SOURCE.md)
        assert parsed.totals["work_days"] == {2024: 248, 2025: 247, 2026: 247, 2027: 247}[year]
        combined = cf().parse(fixture("years_2024_2027.csv"), year=year)
        assert combined.days == parsed.days and combined.totals == parsed.totals, f"{year}: набор из четырёх лет"
    # примеры из SOURCE.md
    days_2024 = dict(cf().parse(fixture("cal2024.csv"), year=2024).days)
    assert days_2024[date_("2024-04-27")] == "workday" and days_2024[date_("2024-12-28")] == "workday"
    assert days_2024[date_("2024-11-02")] == "short", "рабочая суббота с «*» — одна запись «сокращённый»"
    assert dict(cf().parse(fixture("cal2025.csv"), year=2025).days)[date_("2025-11-01")] == "short"
    days_2027 = dict(cf().parse(fixture("cal2027.csv"), year=2027).days)
    assert days_2027[date_("2027-02-20")] == "short"
    assert days_2027[date_("2027-05-03")] == days_2027[date_("2027-06-14")] == days_2027[date_("2027-05-10")] == "day_off"
    assert days_2027[date_("2027-02-23")] == "holiday"


def test_marks_plus_star_and_weekend_absent_mean_day_off_short_and_workday_independent_of_work_weekdays_setting():
    """FR-144, FR-145: число без пометки в будни — праздник; «+» — перенесённый выходной; «*» — сокращённый (и в
    субботу, и в воскресенье); суббота и воскресенье вне списка — перенесённый рабочий день; выходные без пометки
    не особые. Перевод не зависит от `WorkCalendar.work_weekdays`."""
    # 2027: 1 янв — пт, 4 — пн, 8 — пт, 9 — сб, 10 — вс, 16 — сб
    content = support_org.calendar_csv(2027, {1: "1,4+,8*,9,10*"})
    expected_totals = None
    for weekdays in ([0, 1, 2, 3, 4], [0, 1, 2, 3, 4, 5, 6], [1, 2, 3], [5, 6]):
        set_weekdays(weekdays)
        parsed = cf().parse(content, year=2027)
        days = dict(parsed.days)
        assert days[date_("2027-01-01")] == "holiday", weekdays
        assert days[date_("2027-01-04")] == "day_off", weekdays
        assert days[date_("2027-01-08")] == "short", weekdays
        assert days[date_("2027-01-10")] == "short", f"«*» в воскресенье — сокращённый: {weekdays}"
        assert date_("2027-01-09") not in days, f"суббота без пометки — не особый день: {weekdays}"
        assert days[date_("2027-01-16")] == "workday", f"суббота вне списка — рабочий день: {weekdays}"
        assert date_("2027-01-18") not in days, f"обычный будний день вне списка: {weekdays}"
        expected_totals = expected_totals or parsed.totals
        assert parsed.totals == expected_totals, f"итоги не зависят от рабочих дней недели: {weekdays}"
    weekends = [d for d in (date_("2027-01-01") + datetime.timedelta(n) for n in range(365)) if d.weekday() >= 5]
    listed = {date_("2027-01-09"), date_("2027-01-10")}
    assert expected_totals == {
        "holidays_on_weekdays": 1, "moved_days_off": 1, "moved_workdays": len([d for d in weekends if d not in listed]),
        "short_days": 2, "work_days": 365 - 3}
    assert Counter(k for _, k in parsed.days)["workday"] == expected_totals["moved_workdays"]


def test_file_without_requested_year_refused():
    """FR-145: в файле нет строки запрошенного года — отказ `year_missing` с текстом «в файле нет <год> года»;
    ничего не создаётся (сценарий 11, п. 3)."""
    error = expect_code("year_missing", cf().parse, fixture("cal2026.csv"), year=2027)
    assert "в файле нет 2027 года" in str(error)
    expect_code("year_missing", cf().parse, fixture("years_2024_2027.csv"), year=2028)
    assert cf().parse(fixture("years_2024_2027.csv"), year=2025).year == 2025

    user = manager()
    expect_code("year_missing", cf().make_preview, fixture("cal2026.csv"), year=2027, file_name="cal2026.csv",
                actor=user)
    client = support.logged_in(user)
    before = snapshot()
    response = upload_file(client, fixture("cal2026.csv"), 2027, "cal2026.csv")
    assert response.status_code == 200 and "в файле нет 2027 года" in alert_text(response)
    assert model("org.CalendarUpload").objects.count() == 0
    assert snapshot() == before


def test_corrupted_totals_refused():
    """FR-145: пересчёт не сходится с итоговыми колонками (рабочие дни, нерабочие дни, часы при 40-часовой неделе) —
    отказ `totals_mismatch`; календарь не меняется (сценарий 11, п. 3)."""
    expect_code("totals_mismatch", cf().parse, fixture("bad_totals_2026.csv"), year=2026)
    for column in ("work_days", "off_days", "hours40"):
        genuine = support_org.calendar_totals(2027, {1: "1,2"})
        broken = support_org.calendar_csv(2027, {1: "1,2"}, totals={column: genuine[column] + 1})
        expect_code("totals_mismatch", cf().parse, broken, year=2027)
    assert cf().parse(support_org.calendar_csv(2027, {1: "1,2"}), year=2027).year == 2027, "честный файл разбирается"

    user = manager()
    client = support.logged_in(user)
    before = snapshot()
    response = upload_file(client, fixture("bad_totals_2026.csv"), 2026, "bad_totals_2026.csv")
    assert response.status_code == 200 and alert_text(response)
    assert model("org.CalendarUpload").objects.count() == 0
    assert snapshot() == before


def test_type_size_encoding_checked_before_parse():
    """NFR-108: тип, размер и кодировка проверяются до разбора: порядок размер, строгий UTF-8, колонки. Ровно
    1 048 576 байт проходит проверку размера, на байт больше — `too_big`; не UTF-8 и нулевой байт — `not_utf8`;
    не те колонки — `bad_format`."""
    good = fixture("cal2026.csv")
    # размер — раньше кодировки и разбора
    expect_code("too_big", cf().parse, b"\xff" * (MAX_BYTES + 1), year=2026)
    expect_code("too_big", cf().parse, b"x" * (MAX_BYTES + 1), year=2026)
    expect_code("bad_format", cf().parse, b"x" * MAX_BYTES, year=2026)  # размер принят, дальше — колонки
    expect_code("bad_format", cf().parse, b"", year=2026)  # пустой файл
    # кодировка — раньше колонок
    png = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00"
    expect_code("not_utf8", cf().parse, png, year=2026)  # файл другого вида под именем calendar.csv
    expect_code("not_utf8", cf().parse, fixture("cp1251_2026.csv"), year=2026)
    expect_code("not_utf8", cf().parse, "Год,Месяц\n2026,1".encode("cp1251"), year=2026)
    expect_code("not_utf8", cf().parse, good + b"\x00", year=2026)
    expect_code("not_utf8", cf().parse, good[:100] + b"\x00" + good[100:], year=2026)
    # колонки
    expect_code("bad_format", cf().parse, fixture("extra_column_2026.csv"), year=2026)
    expect_code("bad_format", cf().parse, fixture("missing_column_2026.csv"), year=2026)
    expect_code("bad_format", cf().parse, b"just text, not a calendar", year=2026)

    user = manager()
    client = support.logged_in(user)
    before = snapshot()
    for content, name in ((b"x" * (MAX_BYTES + 1), "big.csv"), (fixture("cp1251_2026.csv"), "cp1251_2026.csv"),
                          (b"", "empty.csv"), (png, "calendar.csv"),
                          (fixture("extra_column_2026.csv"), "extra_column_2026.csv"),
                          (fixture("missing_column_2026.csv"), "missing_column_2026.csv")):
        response = upload_file(client, content, 2026, name)
        assert response.status_code == 200 and alert_text(response), name
        assert model("org.CalendarUpload").objects.count() == 0, name
    assert snapshot() == before


# --- предпросмотр и применение -----------------------------------------------------------------------

def test_preview_counts_warns_about_manual_days_and_changes_nothing():
    """FR-145: предпросмотр называет число праздников, перенесённых выходных, перенесённых рабочих и сокращённых
    дней, предупреждает о ручных правках года; до подтверждения ничего не меняется (сценарий 11, п. 1, 4)."""
    user = manager()
    make_year(2027, user)
    make_special("2027-03-08", "holiday", "manual", user)
    make_special("2027-05-03", "workday", "manual", user)
    make_special("2027-02-23", "holiday", "file", user)
    before = snapshot()

    upload = cf().make_preview(fixture("cal2027.csv"), year=2027, file_name="cal2027.csv", actor=user)
    CalendarUpload = model("org.CalendarUpload")
    stored = CalendarUpload.objects.get(pk=upload.pk)
    assert stored.state == "preview" and stored.year == 2027 and stored.file_name == "cal2027.csv"
    assert stored.created_by_id == user.pk
    assert stored.totals == REAL[2027]
    parsed = cf().parse(fixture("cal2027.csv"), year=2027)
    assert stored.days == [{"date": d.isoformat(), "kind": k} for d, k in parsed.days]
    assert snapshot() == before, "календарь, особые дни и версия до подтверждения не меняются"

    assert cf().preview_warnings(stored) == {
        "manual_days": 2, "existing_days": 3, "year_loaded": True, "weekend_work": False}

    client = support.logged_in(user)
    page = client.get(f"/calendar/upload/{stored.pk}/")
    assert page.status_code == 200
    (preview,) = nodes(page, data_calendar_preview=True)
    assert {k: preview.attrs[k] for k in ("data-holidays", "data-day-offs", "data-workdays", "data-shorts",
                                          "data-work-days")} == {
        "data-holidays": "9", "data-day-offs": "6", "data-workdays": "0", "data-shorts": "4", "data-work-days": "247"}
    (warning,) = nodes(page, data_manual_warning=True)
    assert warning.attrs["data-manual-days"] == "2"
    confirm = nodes(page, tag="input", name="confirm", value="1")
    assert confirm and nodes(page, tag="button")
    assert snapshot() == before, "просмотр страницы предпросмотра ничего не меняет"

    # через страницу загрузки: год без особых дней — предупреждения о ручных правках нет
    sent = upload_file(client, fixture("cal2026.csv"), 2026, "cal2026.csv")
    assert sent.status_code == 302
    fresh = CalendarUpload.objects.get(year=2026)
    assert sent["Location"] == f"/calendar/upload/{fresh.pk}/"
    assert cf().preview_warnings(fresh) == {
        "manual_days": 0, "existing_days": 0, "year_loaded": False, "weekend_work": False}
    page = client.get(sent["Location"])
    assert nodes(page, data_calendar_preview=True)[0].attrs["data-holidays"] == "10"
    assert not nodes(page, data_manual_warning=True)
    assert snapshot() == before and CalendarUpload.objects.count() == 2


def test_apply_replaces_year_keeps_other_years(django_capture_on_commit_callbacks):
    """FR-145: подтверждение заменяет особые дни года (в том числе ручные) днями из файла с происхождением «файл»,
    создаёт или обновляет `CalendarYear`, поднимает версию календаря и пишет `calendar.year_loaded` с итогами
    «было» и «стало»; другие годы не трогаются; повторное применение ничего не делает."""
    user = manager()
    old_totals = {"holidays_on_weekdays": 1, "moved_days_off": 0, "moved_workdays": 0, "short_days": 0,
                  "work_days": 364}
    make_year(2026, user, file_name="cal2026.csv")
    make_special("2026-01-01", "holiday", "file", user)
    make_special("2026-03-09", "workday", "manual", user)
    make_year(2027, user, totals=old_totals, file_name="old2027.csv")
    make_special("2027-03-08", "holiday", "manual", user)
    make_special("2027-05-03", "workday", "manual", user)
    other_years = (special_days(2026), [y for y in years_state() if y[0] == 2026])

    upload = cf().make_preview(fixture("cal2027.csv"), year=2027, file_name="cal2027.csv", actor=user)
    version = support.valkey_int("calendar:version")
    started = timezone.now()
    with django_capture_on_commit_callbacks(execute=True):
        applied = cf().apply(upload, actor=user, ip="198.51.100.7")
    finished = timezone.now()

    parsed = cf().parse(fixture("cal2027.csv"), year=2027)
    assert special_days(2027) == [(d.isoformat(), k, "file") for d, k in parsed.days], \
        "особые дни года — ровно из файла, ручные заменены"
    for day in model("org.SpecialDay").objects.filter(date__year=2027):
        assert day.changed_by_id == user.pk, f"{day.date}: changed_by — не загрузивший"
        assert started <= day.changed_at <= finished, f"{day.date}: changed_at — не момент применения"
    assert (special_days(2026), [y for y in years_state() if y[0] == 2026]) == other_years, "другой год не тронут"
    year = model("org.CalendarYear").objects.get(year=2027)
    assert applied.pk == year.pk and year.file_name == "cal2027.csv" and year.totals == REAL[2027]
    assert year.loaded_by_id == user.pk and year.loaded_at is not None
    assert model("org.CalendarYear").objects.count() == 2
    assert model("org.CalendarUpload").objects.get(pk=upload.pk).state == "applied"
    assert support.valkey_int("calendar:version") == version + 1

    (event,) = year_events()
    assert (event.object_type, event.object_id, event.actor_id) == ("calendar", "2027", user.pk)
    assert event.before["year"] == 2027 and event.before["totals"] == old_totals
    assert event.after["year"] == 2027 and event.after["totals"] == REAL[2027]
    assert event.after["file_name"] == "cal2027.csv"
    assert all(isinstance(v, int) for v in event.after["totals"].values()), "числа журнала — целые JSON"

    # повторное применение: возвращает год, ничего не меняя
    again = (special_days(), years_state())
    with django_capture_on_commit_callbacks(execute=True):
        repeated = cf().apply(model("org.CalendarUpload").objects.get(pk=upload.pk), actor=user)
    assert repeated.pk == year.pk and (special_days(), years_state()) == again
    assert len(year_events()) == 1 and support.valkey_int("calendar:version") == version + 1

    # через страницы: год загружается впервые — «было» пустое; повторный POST — тот же ответ без действия
    client = support.logged_in(user)
    sent = upload_file(client, fixture("cal2025.csv"), 2025, "cal2025.csv")
    assert sent.status_code == 302
    with django_capture_on_commit_callbacks(execute=True):
        confirmed = client.post(sent["Location"], {"confirm": "1"})
    assert confirmed.status_code == 302 and confirmed["Location"] == "/calendar/?year=2025"
    assert len(special_days(2025)) == 19 and set(k for _, k, o in special_days(2025)) <= KINDS
    assert {o for _, _, o in special_days(2025)} == {"file"}
    first_load = year_events()[-1]
    assert first_load.object_id == "2025" and first_load.after["totals"] == REAL[2025]
    assert first_load.before == {"year": 2025, "totals": {}}, "дополнение 34"
    assert support.valkey_int("calendar:version") == version + 2
    with django_capture_on_commit_callbacks(execute=True):
        repeat = client.post(sent["Location"], {"confirm": "1"})
    assert repeat.status_code == 302 and repeat["Location"] == "/calendar/?year=2025"
    assert len(year_events()) == 2 and support.valkey_int("calendar:version") == version + 2
    assert special_days(2027) == [(d.isoformat(), k, "file") for d, k in parsed.days]


def test_holiday_on_weekend_shown_as_day_off_upload_page_warns(django_capture_on_commit_callbacks):
    """FR-145: праздник на субботу или воскресенье в файле не отличим от выходного, в календаре он выходной; если
    рабочей сделали субботу или воскресенье, он станет рабочим днём, и страница загрузки предупреждает об этом."""
    user = manager()
    upload = cf().make_preview(fixture("cal2027.csv"), year=2027, file_name="cal2027.csv", actor=user)
    days = dict(cf().parse(fixture("cal2027.csv"), year=2027).days)
    for weekend_holiday in ("2027-05-01", "2027-06-12", "2027-05-09"):
        assert date_(weekend_holiday) not in days, "в файле это обычный выходной, особого дня нет"
    client = support.logged_in(user)
    url = f"/calendar/upload/{upload.pk}/"

    set_weekdays([0, 1, 2, 3, 4])
    assert cf().preview_warnings(upload)["weekend_work"] is False
    assert not nodes(client.get(url), data_weekend_holiday_warning=True)

    for weekdays in ([0, 1, 2, 3, 4, 5], [0, 1, 2, 3, 4, 6], [0, 1, 2, 3, 4, 5, 6]):
        set_weekdays(weekdays)
        assert cf().preview_warnings(upload)["weekend_work"] is True, weekdays
        assert nodes(client.get(url), data_weekend_holiday_warning=True), f"предупреждение при {weekdays}"
    set_weekdays([0, 1, 2, 3])
    assert cf().preview_warnings(upload)["weekend_work"] is False

    # после применения: при обычной неделе такие праздники показаны выходными
    set_weekdays([0, 1, 2, 3, 4])
    with django_capture_on_commit_callbacks(execute=True):
        cf().apply(upload, actor=user)
    assert cal().day_kind(date_("2027-05-01")) == "off"
    page = client.get("/calendar/?year=2027")
    assert page.status_code == 200
    for weekend_holiday in ("2027-05-01", "2027-06-12", "2027-05-09"):
        (cell,) = nodes(page, tag="td", data_date=weekend_holiday)
        assert cell.attrs["data-day-kind"] == "off", weekend_holiday
    (moved,) = nodes(page, tag="td", data_date="2027-05-03")
    assert moved.attrs["data-day-kind"] == "day_off"
    # а если рабочей сделали субботу, такой праздник — рабочий день, пока его не поправят вручную
    set_weekdays([0, 1, 2, 3, 4, 5])
    assert cal().day_kind(date_("2027-05-01")) == "work"
    assert cal().day_kind(date_("2027-05-09")) == "off"


def test_unconfirmed_calendar_preview_purged_after_day(django_capture_on_commit_callbacks):
    """FR-145: неподтверждённый предпросмотр стирается через сутки (`org.tasks.purge_previews`); подтверждённый и
    свежий остаются; применённый календарь не меняется."""
    from apps.org.tasks import purge_previews

    user = manager()
    old = cf().make_preview(fixture("cal2026.csv"), year=2026, file_name="cal2026.csv", actor=user)
    fresh = cf().make_preview(fixture("cal2027.csv"), year=2027, file_name="cal2027.csv", actor=user)
    applied = cf().make_preview(fixture("cal2025.csv"), year=2025, file_name="cal2025.csv", actor=user)
    with django_capture_on_commit_callbacks(execute=True):
        cf().apply(applied, actor=user)
    CalendarUpload = model("org.CalendarUpload")
    now = timezone.now()
    CalendarUpload.objects.filter(pk=old.pk).update(created_at=now - datetime.timedelta(hours=25))
    CalendarUpload.objects.filter(pk=applied.pk).update(created_at=now - datetime.timedelta(hours=25))
    CalendarUpload.objects.filter(pk=fresh.pk).update(created_at=now - datetime.timedelta(hours=23))
    calendar_state = (special_days(), years_state())

    assert purge_previews() == 1, "стёрт только старый неподтверждённый предпросмотр"
    assert sorted(CalendarUpload.objects.values_list("pk", flat=True)) == sorted([fresh.pk, applied.pk])
    assert CalendarUpload.objects.get(pk=applied.pk).state == "applied"
    assert (special_days(), years_state()) == calendar_state, "календарь не меняется"
    client = support.logged_in(user)
    assert client.get(f"/calendar/upload/{old.pk}/").status_code == 404
    assert client.get(f"/calendar/upload/{fresh.pk}/").status_code == 200
    assert purge_previews() == 0


def test_upload_needs_calendar_manage():
    """FR-123: загрузка файла календаря и подтверждение требуют права «Рабочий календарь»; без него — отказ (403),
    без входа — переход на вход, и ничего не создаётся и не меняется (сценарий 11, п. 6)."""
    owner = manager()
    upload = cf().make_preview(fixture("cal2027.csv"), year=2027, file_name="cal2027.csv", actor=owner)
    CalendarUpload = model("org.CalendarUpload")
    before = snapshot()

    denied = {
        "только просмотр": support.make_with_permissions("staff.view"),
        "другие права": support.make_with_permissions("staff.view", "accounts.manage", "org.manage"),
    }
    for label, user in denied.items():
        client = support.logged_in(user)
        assert client.get("/calendar/upload/").status_code == 403, label
        assert upload_file(client, fixture("cal2027.csv"), 2027).status_code == 403, label
        assert client.get(f"/calendar/upload/{upload.pk}/").status_code == 403, label
        assert client.post(f"/calendar/upload/{upload.pk}/", {"confirm": "1"}).status_code == 403, label
        assert CalendarUpload.objects.count() == 1 and CalendarUpload.objects.get().state == "preview", label
        assert snapshot() == before, label

    anonymous = support.make_client()
    for response in (anonymous.get("/calendar/upload/"), upload_file(anonymous, fixture("cal2027.csv"), 2027),
                     anonymous.post(f"/calendar/upload/{upload.pk}/", {"confirm": "1"})):
        assert response.status_code == 302 and "/login/" in response["Location"]
    assert snapshot() == before and CalendarUpload.objects.count() == 1

    allowed = support.logged_in(owner)
    page = allowed.get("/calendar/upload/")
    assert page.status_code == 200
    assert nodes(page, data_format_help=True), "описание формата и мест, где взять файл"
    (form,) = nodes(page, tag="form", data_form="calendar-upload")
    assert any(n.attrs.get("name") == "year" for n in form.walk())
    assert any(n.attrs.get("type") == "file" and n.attrs.get("name") == "file" for n in form.walk())
    assert upload_file(allowed, fixture("cal2026.csv"), 2026, "cal2026.csv").status_code == 302
    assert CalendarUpload.objects.count() == 2
