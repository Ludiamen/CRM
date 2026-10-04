"""T-2114: поле выбора даты (FR-148). Сценарии 1–13 спеки: поле «с/по» журнала и дата рождения в `/me/`.

Сетка `/ui/date-picker/` (CONTRACT-002 § 8.1, § 9.6), виджет `PortalDateInput` и разбор `parse_date`
(§ 3), точка расширения `day_marks` (§ 5), скрипт `static/js/datefield.js`. Имена кода среза 002 импортируются
внутри тестов, модели берутся через `support.model`.
"""
import ast
import calendar
import datetime
import re
from html.parser import HTMLParser

import pytest
from django.utils import timezone

from tests import support
from tests.support import BACKEND_DIR, HX, model

pytestmark = pytest.mark.django_db

VOID = {"input", "br", "img", "meta", "link", "hr", "col", "area", "base", "source", "wbr"}
KIND_LABELS = {"off": "выходной", "holiday": "праздник", "day_off": "перенесённый выходной",
               "workday": "перенесённый рабочий день", "short": "сокращённый день"}
MONTH = (2026, 11)          # 1 ноября 2026 — воскресенье, в ноябре 30 дней


class Element:
    def __init__(self, tag, attrs):
        self.tag, self.attrs, self.text, self.children = tag, dict(attrs), "", []
        self.parent = None

    def inside(self, other):
        node = self.parent
        while node is not None:
            if node is other:
                return True
            node = node.parent
        return False

    def ancestor(self, tag):
        node = self.parent
        while node is not None and node.tag != tag:
            node = node.parent
        return node

    def has_class(self, name):
        return name in (self.attrs.get("class") or "").split()


class Page(HTMLParser):
    """Плоский разбор: все элементы по порядку, текст элемента включает текст потомков."""

    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.elements, self._stack = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        el = Element(tag, attrs)
        el.parent = self._stack[-1] if self._stack else None
        self.elements.append(el)
        if tag not in VOID:
            self._stack.append(el)

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                break

    def handle_data(self, data):
        for el in self._stack:
            el.text += data

    def find(self, tag=None, **attrs):
        out = []
        for el in self.elements:
            if tag and el.tag != tag:
                continue
            if all((k.replace("_", "-") in el.attrs) if v is True else el.attrs.get(k.replace("_", "-")) == v
                   for k, v in attrs.items()):
                out.append(el)
        return out


def picker(client, month: str | None = None, **extra):
    url = "/ui/date-picker/" + (f"?month={month}" if month is not None else "")
    return client.get(url, **extra)


def day_buttons(page: Page) -> dict:
    return {el.attrs["data-date"]: el for el in page.find("button") if "data-date" in el.attrs}


def user_client(**extra):
    user = support.make_employee(**extra)
    return user, support.logged_in(user, ip="198.51.100.141")


def make_special_days(user, days: dict):
    """Загруженный год и особые дни через ORM: {date: kind}."""
    CalendarYear, SpecialDay = model("org.CalendarYear"), model("org.SpecialDay")
    for year in {d.year for d in days}:
        CalendarYear.objects.create(year=year, loaded_by=user, loaded_at=timezone.now(), file_name="cal.csv", totals={
            "holidays_on_weekdays": 0, "moved_days_off": 0, "moved_workdays": 0, "short_days": 0, "work_days": 0})
    for day, kind in days.items():
        SpecialDay.objects.create(date=day, kind=kind, origin="file", changed_by=user,
                                   changed_at=timezone.now())


def test_date_picker_grid_monday_first_with_day_marks():
    """FR-148: сетка месяца с понедельника, корень с `data-month`, переходы, списки месяца и года; отметки из `day_marks` (`org`)."""
    user, client = user_client()
    make_special_days(user, {datetime.date(2026, 11, 4): "holiday", datetime.date(2026, 11, 7): "workday",
                             datetime.date(2026, 11, 3): "short", datetime.date(2026, 11, 9): "day_off"})
    response = picker(client, "2026-11")
    assert response.status_code == 200
    page = Page(response.content.decode())
    grid = page.find(data_month="2026-11")
    assert len(grid) == 1 and "data-datefield-grid" in grid[0].attrs, "корень сетки [data-datefield-grid][data-month]"

    # устройство сетки (дополнение 23): table, thead th, tbody tr[data-week] по 7 td, дни вне месяца — пустые td
    tables = [el for el in page.find("table") if el.inside(grid[0])]
    assert len(tables) == 1, "внутри [data-datefield-grid] одна table"
    table = tables[0]
    ths = [el for el in page.find("th") if el.inside(table) and el.ancestor("thead") is not None]
    assert [el.text.strip() for el in ths] == ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"], "thead th с понедельника"
    weeks = [el for el in page.find("tr") if el.inside(table) and "data-week" in el.attrs]
    assert 4 <= len(weeks) <= 6 and all(el.ancestor("tbody") is not None for el in weeks)
    cells = {id(w): [el for el in page.find("td") if el.parent is w] for w in weeks}
    assert all(len(cells[id(w)]) == 7 for w in weeks), "в каждой неделе ровно 7 td"
    first_week = cells[id(weeks[0])]
    assert [bool(c.text.strip()) for c in first_week] == [False] * 6 + [True], "1 ноября 2026 — седьмая ячейка первой недели"
    assert [b.attrs.get("data-date") for b in page.find("button") if b.inside(first_week[6])] == ["2026-11-01"]
    for week in weeks:
        for cell in cells[id(week)]:
            if not cell.text.strip():
                assert not [b for b in page.find("button") if b.inside(cell)], "день вне месяца — пустая td без кнопки"

    header = re.findall(r"Пн|Вт|Ср|Чт|Пт|Сб|Вс", " ".join(el.text for el in page.elements if el.tag in ("th", "span", "div", "abbr", "td")
                                                           and el.text.strip() in ("Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс")))
    assert header[:7] == ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"], f"заголовок дней должен идти с понедельника: {header}"

    buttons = day_buttons(page)
    month_days = [f"2026-11-{d:02d}" for d in range(1, 31)]
    assert [d for d in buttons if d.startswith("2026-11-")] == month_days, "кнопка у каждого дня месяца, по порядку"
    assert [buttons[d].text.strip().split()[0] for d in month_days] == [str(n) for n in range(1, 31)]
    kinds = {d: buttons[d].attrs["data-day-kind"] for d in month_days}
    assert kinds["2026-11-04"] == "holiday" and kinds["2026-11-07"] == "workday"
    assert kinds["2026-11-03"] == "short" and kinds["2026-11-09"] == "day_off"
    assert kinds["2026-11-01"] == "off" and kinds["2026-11-08"] == "off", "воскресенья — выходные по неделе"
    assert kinds["2026-11-02"] == "work" and kinds["2026-11-10"] == "work"
    for day, kind in (("2026-11-04", "holiday"), ("2026-11-07", "workday"), ("2026-11-03", "short"), ("2026-11-09", "day_off")):
        assert buttons[day].has_class(f"date-day-{kind}"), (day, buttons[day].attrs)
    assert buttons["2026-11-02"].attrs.get("class", "").find("date-day-") == -1, "у рабочего дня класса вида нет"

    prev, nxt = page.find(data_datefield_prev=True), page.find(data_datefield_next=True)
    assert len(prev) == 1 and len(nxt) == 1
    assert prev[0].attrs["hx-get"].endswith("month=2026-10") and nxt[0].attrs["hx-get"].endswith("month=2026-12")
    months = page.find("select", name="month")
    years = page.find("select", name="year")
    assert len(months) == 1 and len(years) == 1
    month_values = [el.attrs.get("value") for el in page.elements if el.tag == "option" and el.inside(months[0])]
    assert month_values == [str(n) for n in range(1, 13)], "список месяцев — значения 1…12"
    assert any(el.tag == "option" and el.inside(years[0]) and el.attrs.get("value") == "2026" for el in page.elements), "в списке лет есть текущий год сетки"

    january = Page(picker(client, "2027-01").content.decode())
    assert january.find(data_month="2027-01"), "переход на другой месяц и год"
    assert prev[0].attrs["hx-get"] != nxt[0].attrs["hx-get"]
    assert any(b.attrs["data-date"] == "2027-01-01" for b in january.find("button") if "data-date" in b.attrs)


def test_date_picker_without_org_marks_saturday_and_sunday(no_extensions):
    """FR-148: без зарегистрированных `day_marks` выходными считаются суббота и воскресенье (`off`), остальное — `work`."""
    from apps.core import extensions

    assert extensions.registered("day_marks") == []
    _, client = user_client()
    page = Page(picker(client, "2026-11").content.decode())
    buttons = day_buttons(page)
    assert len(buttons) >= 30
    for number in range(1, 31):
        day = datetime.date(2026, 11, number)
        button = buttons[day.isoformat()]
        want = "off" if day.weekday() >= 5 else "work"
        assert button.attrs["data-day-kind"] == want, (day, day.weekday(), button.attrs)
        assert button.has_class("date-day-off") == (want == "off")
    off_button = buttons["2026-11-07"]
    assert "выходной" in off_button.text, "подпись выходного — скрытый текст внутри кнопки"
    assert "выходной" not in buttons["2026-11-02"].text
    spans = [e for e in page.elements if e.tag == "span" and e.has_class("visually-hidden") and e.text.strip() == "выходной"]
    assert len(spans) == sum(1 for n in range(1, 31) if datetime.date(2026, 11, n).weekday() >= 5)


def test_date_picker_open_to_any_logged_in_user(clock):
    """FR-148: сетку видит любой вошедший без прав; без входа — 302; фрагмент всегда без `<html>`; пустой или неверный `month` — текущий месяц по Москве."""
    user, client = user_client()
    assert user.roles.count() == 0
    plain, with_hx = picker(client, "2026-11"), picker(client, "2026-11", **HX)
    for response in (plain, with_hx):
        assert response.status_code == 200
        assert "<html" not in response.content.decode().lower(), "фрагмент всегда без <html>"
        assert Page(response.content.decode()).find(data_month="2026-11")

    anonymous = support.make_client(ip="198.51.100.142").get("/ui/date-picker/?month=2026-11")
    assert anonymous.status_code == 302 and "/login/" in anonymous["Location"]

    from datetime import datetime as dt, timezone as tz
    clock.set(dt(2026, 9, 30, 21, 30, tzinfo=tz.utc))   # по Москве уже 1 октября 2026, 00:30
    for bad in (None, "", "abc", "2026-13", "1899-12", "2101-01", "0000-00", "2026-1-5"):
        response = picker(client, bad)
        assert response.status_code == 200, bad
        assert Page(response.content.decode()).find(data_month="2026-10"), f"month={bad!r}: ожидали текущий месяц по Москве"

    # допустимый год month — 1900…2100 (дополнение 24)
    old = Page(picker(client, "1955-03").content.decode())
    assert old.find(data_month="1955-03"), "month=1955-03 — сетка марта 1955"
    assert "1955-03-31" in day_buttons(old) and "1955-03-01" in day_buttons(old) and "1955-04-01" not in day_buttons(old)
    for edge in ("1900-01", "2100-12"):
        assert Page(picker(client, edge).content.decode()).find(data_month=edge), edge

    # список лет: от 1900 до текущего года +5 (по Москве сейчас 2026), год сетки всегда в списке
    for shown, want_last in (("2026-10", 2031), ("1955-03", 2031)):
        page = Page(picker(client, shown).content.decode())
        [select] = page.find("select", name="year")
        years = [int(o.attrs["value"]) for o in page.find("option") if o.inside(select)]
        assert years == list(range(1900, want_last + 1)), shown


def test_any_day_selectable_including_holiday():
    """FR-148: выбрать можно любой день, в том числе праздник и выходной: кнопки без `disabled`, подписи видов скрытым текстом."""
    user, client = user_client()
    make_special_days(user, {datetime.date(2026, 11, 4): "holiday", datetime.date(2026, 11, 7): "workday",
                             datetime.date(2026, 11, 3): "short", datetime.date(2026, 11, 9): "day_off"})
    page = Page(picker(client, "2026-11").content.decode())
    buttons = day_buttons(page)
    days = [f"2026-11-{n:02d}" for n in range(1, 31)]
    for day in days:
        button = buttons[day]
        assert button.tag == "button" and button.attrs.get("type") == "button", day
        assert "disabled" not in button.attrs and button.attrs.get("aria-disabled") in (None, "false"), f"{day} недоступен для выбора"
    labels = {"2026-11-04": "holiday", "2026-11-07": "workday", "2026-11-03": "short", "2026-11-09": "day_off", "2026-11-01": "off"}
    for day, kind in labels.items():
        button = buttons[day]
        assert button.attrs["data-day-kind"] == kind
        assert KIND_LABELS[kind] in button.text, f"{day}: подпись «{KIND_LABELS[kind]}» внутри кнопки"
        hidden = [e for e in page.elements if e.tag == "span" and e.has_class("visually-hidden") and e.text.strip() == KIND_LABELS[kind]]
        assert hidden, f"нет span.visually-hidden с подписью «{KIND_LABELS[kind]}»"
    assert "праздник" not in buttons["2026-11-05"].text and not buttons["2026-11-05"].has_class("date-day-holiday")


def test_field_value_not_in_picker_request():
    """FR-148: кнопка открытия несёт `hx-get` на сетку по месяцу, цель — контейнер своего поля; сама дата в адрес не попадает."""
    user, client = user_client()
    model("core.User").objects.filter(pk=user.pk).update(birth_date=datetime.date(1990, 5, 17))
    audit_user = support.make_admin()
    audit_client = support.logged_in(audit_user, ip="198.51.100.143")
    pages = {"/me/": client.get("/me/"), "/audit/?date_from=2026-09-03&date_to=2026-09-04": audit_client.get("/audit/?date_from=2026-09-03&date_to=2026-09-04")}
    expected = {"/me/": {"birth_date": "17.05.1990"},
                "/audit/?date_from=2026-09-03&date_to=2026-09-04": {"date_from": "03.09.2026", "date_to": "04.09.2026"}}
    for path, response in pages.items():
        assert response.status_code == 200, path
        page = Page(response.content.decode())
        wrappers = page.find(data_datefield=True)
        assert len(wrappers) == len(expected[path]), (path, len(wrappers))
        inputs = {el.attrs["name"]: el for el in page.find("input", data_datefield_input=True)}
        assert set(inputs) == set(expected[path]), (path, sorted(inputs))
        for name, value in expected[path].items():
            field = inputs[name]
            assert field.attrs.get("type") == "text" and field.attrs.get("inputmode") == "numeric"
            assert field.attrs.get("placeholder") == "ДД.ММ.ГГГГ"
            assert field.attrs.get("value") == value, f"{path}: в поле {name} значение выводится как ДД.ММ.ГГГГ"
            opener = [b for b in page.find("button", data_datefield_open=True) if b.attrs.get("hx-target") == f"#{field.attrs['id']}-picker"]
            assert len(opener) == 1, f"{name}: одна кнопка открытия с hx-target=#<id>-picker"
            assert opener[0].attrs.get("type") == "button" and "Выбрать дату" in opener[0].text
            hx_get = opener[0].attrs["hx-get"]
            assert re.fullmatch(r"/ui/date-picker/\?month=\d{4}-\d{2}", hx_get), hx_get
            for part in ("1990", "05-17", "17.05", "2026-09-03", "03.09.2026", "04.09", "birth", "date_from", "date_to", "value"):
                assert part not in hx_get, f"в адресе запроса сетки значение поля: {hx_get}"
            containers = [e for e in page.elements if e.attrs.get("id") == f"{field.attrs['id']}-picker"]
            assert len(containers) == 1 and "hidden" in containers[0].attrs and "data-datefield-picker" in containers[0].attrs


def test_no_native_date_inputs_in_templates():
    """FR-148: ни в одном шаблоне портала нет `type="date"` (в журнале «с» и «по» — поле портала)."""
    pattern = re.compile(r"""(?<![\w-])type\s*=\s*["']?date\b""", re.IGNORECASE)
    offenders = []
    for path in sorted((BACKEND_DIR / "templates").rglob("*.html")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if pattern.search(line):
                offenders.append(f"{path.relative_to(BACKEND_DIR)}:{number}")
    assert not offenders, "родное поле даты в шаблонах: " + ", ".join(offenders)


def _date_field_calls():
    files = sorted((BACKEND_DIR / "apps").glob("*/forms.py")) + sorted((BACKEND_DIR / "apps").glob("*/forms/*.py"))
    for path in files:
        source = path.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call):
                name = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                if name == "DateField":
                    widget = next((kw.value for kw in node.keywords if kw.arg == "widget"), None)
                    yield f"{path.relative_to(BACKEND_DIR)}:{node.lineno}", (ast.get_source_segment(source, widget) if widget else "")


def test_every_portal_datefield_uses_portal_widget():
    """FR-148: у каждого `forms.DateField` портала виджет `PortalDateInput`; виджет и страницы выводят разметку `[data-datefield]`."""
    for place, widget in _date_field_calls():
        assert "PortalDateInput" in widget, f"{place}: у DateField нет виджета PortalDateInput"

    from apps.core.widgets import PortalDateInput

    assert PortalDateInput.template_name == "widgets/date_field.html"
    html = PortalDateInput().render("born", datetime.date(2026, 3, 5), attrs={"id": "id_born"})
    page = Page(html)
    assert len(page.find(data_datefield=True)) == 1
    field = page.find("input", data_datefield_input=True)[0]
    assert (field.attrs.get("type"), field.attrs.get("name"), field.attrs.get("id")) == ("text", "born", "id_born")
    assert field.attrs.get("value") == "05.03.2026" and field.attrs.get("placeholder") == "ДД.ММ.ГГГГ"
    assert field.attrs.get("inputmode") == "numeric"
    assert "Выбрать дату" in page.find("button", data_datefield_open=True)[0].text
    assert page.find("div", id="id_born-picker") or [e for e in page.elements if e.attrs.get("id") == "id_born-picker"]

    admin_client = support.logged_in(support.make_admin(), ip="198.51.100.144")
    audit = Page(admin_client.get("/audit/").content.decode())
    assert sorted(el.attrs["name"] for el in audit.find("input", data_datefield_input=True)) == ["date_from", "date_to"]
    _, me_client = user_client()
    me = Page(me_client.get("/me/").content.decode())
    assert [el.attrs["name"] for el in me.find("input", data_datefield_input=True)] == ["birth_date"]


def test_field_accepts_dd_mm_yyyy_and_iso():
    """FR-148: `parse_date`, форма и `/me/` принимают ДД.ММ.ГГГГ и ГГГГ-ММ-ДД; пустое и неразборное — `None`; вывод — ДД.ММ.ГГГГ."""
    from django import forms
    from apps.core import widgets

    assert widgets.DATE_INPUT_FORMATS == ("%d.%m.%Y", "%Y-%m-%d")
    assert widgets.parse_date("05.03.2026") == datetime.date(2026, 3, 5)
    assert widgets.parse_date("2026-03-05") == datetime.date(2026, 3, 5)
    assert widgets.parse_date("29.02.2028") == datetime.date(2028, 2, 29)
    for bad in ("", "   ", "31.02.2026", "2026-02-30", "5 марта", "05/03/2026", "2026.03.05"):
        assert widgets.parse_date(bad) is None, bad
    assert widgets.PortalDateInput().format == "%d.%m.%Y" or widgets.PortalDateInput().format_value(datetime.date(2026, 3, 5)) == "05.03.2026"

    field = forms.DateField(input_formats=widgets.DATE_INPUT_FORMATS, widget=widgets.PortalDateInput())
    assert field.clean("05.03.2026") == field.clean("2026-03-05") == datetime.date(2026, 3, 5)

    user, client = user_client()
    base = {"phone": user.phone, "contacts": "", "internal_phone": "", "workplace": ""}
    User = model("core.User")
    for sent, want in (("05.03.1990", datetime.date(1990, 3, 5)), ("1991-04-06", datetime.date(1991, 4, 6)), ("", None)):
        response = client.post("/me/", {**base, "birth_date": sent})
        assert response.status_code == 302, (sent, response.status_code)
        assert User.objects.get(pk=user.pk).birth_date == want, sent
    client.post("/me/", {**base, "birth_date": "07.08.1992"})
    shown = Page(client.get("/me/").content.decode()).find("input", data_datefield_input=True)
    assert shown[0].attrs.get("value") == "07.08.1992"


def test_audit_filter_accepts_dd_mm_yyyy(clock):
    """FR-148: `audit_search.parse` и список `/audit/` принимают «с» и «по» в ДД.ММ.ГГГГ и ГГГГ-ММ-ДД, неверная дата игнорируется."""
    from datetime import datetime as dt, timedelta, timezone as tz
    from apps.core.services import audit_search
    from apps.core.services.audit import record

    parsed = audit_search.parse({"date_from": "05.03.2026", "date_to": "2026-03-07"})
    assert parsed.date_from == datetime.date(2026, 3, 5) and parsed.date_to == datetime.date(2026, 3, 7)
    assert audit_search.parse({"date_from": "2026-03-05", "date_to": "07.03.2026"}).date_to == datetime.date(2026, 3, 7)
    ignored = audit_search.parse({"date_from": "31.02.2026", "date_to": "вчера"})
    assert ignored.date_from is None and ignored.date_to is None

    admin_user = support.make_admin()
    client = support.logged_in(admin_user, ip="198.51.100.145")
    base = dt(2026, 9, 1, 9, 0, tzinfo=tz.utc)
    ids = {}
    for name, days in (("first", 0), ("second", 1), ("third", 5)):
        clock.set(base + timedelta(days=days))
        record("role.updated", actor=admin_user, object_type="role", object_id=name)
        ids[name] = model("core.AuditEvent").objects.filter(object_id=name).order_by("-id").first().pk

    def found(**params):
        html = client.get("/audit/", params).content.decode()
        return {int(n) for n in re.findall(r'data-event-id="(\d+)"', html)} & set(ids.values())

    window = {ids["second"]}
    assert found(date_from="02.09.2026", date_to="02.09.2026") == window
    assert found(date_from="2026-09-02", date_to="2026-09-02") == window
    assert found(date_from="02.09.2026", date_to="2026-09-02") == window
    assert found(date_from="02.09.2026") == {ids["second"], ids["third"]}
    assert found(date_to="01.09.2026") == {ids["first"]}
    assert found(date_from="31.02.2026") == set(ids.values()), "неверная дата игнорируется, как в срезе 001"


def test_datefield_script_external_delegated_without_eval():
    """FR-148: скрипт — внешний файл, подключён тегом `<script src>`; делегирование на `document`, клавиши плана; без `eval`, `new Function` и встроенных обработчиков."""
    path = BACKEND_DIR / "static" / "js" / "datefield.js"
    source = path.read_text(encoding="utf-8")
    assert "eval(" not in source and "new Function" not in source
    assert not re.search(r"""setAttribute\(\s*["']on""", source) and not re.search(r"\.on[a-z]+\s*=", source)
    assert re.search(r"document\.addEventListener\(", source), "обработчики навешиваются делегированием на document"
    for key in ("ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "PageUp", "PageDown", "Home", "End", "Enter", "Escape"):
        assert key in source, f"в datefield.js нет обработки клавиши {key}"
    for hook in ("data-datefield-open", "data-datefield-picker", "data-date", "aria-pressed"):
        assert hook in source, f"скрипт не использует зацепку {hook}"

    admin_client = support.logged_in(support.make_admin(), ip="198.51.100.146")
    html = admin_client.get("/audit/").content.decode()
    tags = re.findall(r"<script\b[^>]*datefield[^>]*>(.*?)</script>", html, re.S)
    assert re.search(r'<script\b[^>]*\bsrc="[^"]*js/datefield[^"]*\.js"', html), "нет тега <script src> со static/js/datefield.js"
    assert all(not body.strip() for body in tags), "скрипт поля даты не должен быть встроенным"
    fragment = picker(admin_client, "2026-11").content.decode()
    for body in (html, fragment):
        assert not re.search(r"\son[a-z]+\s*=", body, re.IGNORECASE), "встроенный обработчик on…= в ответе"
        assert "eval(" not in body and "new Function" not in body and "javascript:" not in body.lower()
    assert "<script" not in fragment.lower()
    widget = (BACKEND_DIR / "templates" / "widgets" / "date_field.html").read_text(encoding="utf-8")
    assert not re.search(r"\son[a-z]+\s*=|<script|eval\(", widget, re.IGNORECASE)
