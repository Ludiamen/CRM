"""T-2106: поиск и фильтры списка «Сотрудники» (FR-119, FR-130, FR-131, NFR-108). Сценарий 4 спеки."""
from html.parser import HTMLParser

import pytest
from django.db import connection

from tests import factories, support, support_org
from tests.support import model

pytestmark = pytest.mark.django_db

VOID = {"img", "br", "input", "hr", "meta", "link", "col", "source", "wbr"}
COLLEAGUE_PRESETS = ["", "dismissed", "no_unit", "all"]
SERVICE_PRESETS = ["", "dismissed", "no_unit", "all", "invited", "active", "blocked"]


class _Page(HTMLParser):
    """Читает `/staff/`: строки `tr[data-user-id]` с ячейками `data-cell`, ссылки `a[data-preset]`, `select[name=unit]`."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.rows, self.presets, self.unit_options, self.headers = [], [], [], []
        self._stack, self._row, self._preset, self._option, self._header = [], None, None, None, None
        self._in_unit_select = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "tr" and "data-user-id" in a:
            self._row = {"attrs": a, "cells": {}, "cell_attrs": {}, "name_href": None, "photo": {}}
            self.rows.append(self._row)
        if tag == "th":
            self._header = []
            self.headers.append(self._header)
        if tag == "a" and "data-preset" in a:
            self._preset = {"value": a["data-preset"], "current": a.get("aria-current"), "text": ""}
            self.presets.append(self._preset)
        if tag == "select" and a.get("name") == "unit":
            self._in_unit_select = True
        if tag == "option" and self._in_unit_select:
            self._option = {"value": a.get("value", ""), "text": ""}
            self.unit_options.append(self._option)
        key = a.get("data-cell")
        if self._row is not None:
            if key:
                self._row["cells"][key] = ""
                self._row["cell_attrs"][key] = a
            if tag == "a" and a.get("href", "").startswith("/staff/") and self._row["name_href"] is None:
                if "name" in self._open_cells() or not self._open_cells():
                    self._row["name_href"] = a["href"]
            for marker in ("data-photo", "data-photo-img", "data-photo-placeholder"):
                if marker in a:
                    self._row["photo"][marker] = a
        if tag not in VOID:
            self._stack.append((tag, key))

    def _open_cells(self):
        return [k for _, k in self._stack if k]

    def handle_endtag(self, tag):
        while self._stack:
            popped, _ = self._stack.pop()
            if popped == tag:
                break
        if tag == "tr":
            self._row = None
        if tag == "th":
            self._header = None
        if tag == "a":
            self._preset = None
        if tag == "option":
            self._option = None
        if tag == "select":
            self._in_unit_select = False

    def handle_data(self, data):
        if self._row is not None:
            for key in self._open_cells():
                self._row["cells"][key] += data
        if self._preset is not None:
            self._preset["text"] += data
        if self._option is not None:
            self._option["text"] += data
        if self._header is not None:
            self._header.append(data)


def read(client, query: str = "") -> _Page:
    response = client.get("/staff/" + query)
    assert response.status_code == 200, f"/staff/{query}: код {response.status_code}"
    page = _Page()
    page.feed(response.content.decode())
    return page


def ids(page: _Page, mine=None) -> set[int]:
    """Номера строк списка; `mine` ограничивает набором пользователей теста (без смотрящего и записей миграций)."""
    found = {int(row["attrs"]["data-user-id"]) for row in page.rows}
    return found & {u.pk for u in mine} if mine is not None else found


def cell(row, key: str) -> str:
    return " ".join(row["cells"][key].split())


def person(**over):
    return support.make_employee(email=factories.new_email("srch"), **over)


# --- база ------------------------------------------------------------------------------------

def test_database_lower_and_translate_handle_cyrillic():
    """NFR-108 (план, инвариант «бд»): функции базы `lower` и `translate` приводят кириллицу и «ё» -> «е» при локали базы."""
    User = model("core.User")
    with connection.cursor() as cursor:
        cursor.execute("SELECT translate(lower(%s), 'ё', 'е')", ["ЁЛКА Ёж СЕТЬ"])
        assert cursor.fetchone()[0] == "елка еж сеть"
    user = person(full_name="Алёна ВЁТОВА")
    other = person(full_name="Борис Бетов")
    with connection.cursor() as cursor:
        cursor.execute(
            f"SELECT id FROM {User._meta.db_table} WHERE translate(lower(full_name), 'ё', 'е') LIKE %s AND id IN (%s, %s)",
            ["%алена вет%", user.pk, other.pk])
        assert [row[0] for row in cursor.fetchall()] == [user.pk]


# --- поиск -----------------------------------------------------------------------------------

def test_search_each_field_case_and_yo_insensitive():
    """FR-130: строка ищет вхождение в ФИО, должность, почту, телефон, внутренний телефон и место работы — без учёта регистра и «е/ё»."""
    by_name = person(full_name="Фёдор Зубов")
    by_position = person(position="Тёплый инженер")
    by_email = factories.make_user(email="Kamil.Needle@Example.com", full_name="Камиль Н", activated_at=None)
    by_phone = person(phone="+7 900 123-45-67")
    by_internal = person(internal_phone="Доб. 4455")
    by_workplace = person(workplace="Кабинет 12, Ёлочная")
    reverse = person(position="Берёза-мастер", full_name="Береза Ёлкина")
    mine = [by_name, by_position, by_email, by_phone, by_internal, by_workplace, reverse]
    client = support.logged_in(support.make_admin())
    cases = [
        ("ФЕДОР", {by_name}), ("фёдор зуб", {by_name}),
        ("ТЕПЛЫЙ ИНЖ", {by_position}), ("тёплый", {by_position}),
        ("kamil.NEEDLE", {by_email}),
        ("123-45", {by_phone}),
        ("доб. 4455", {by_internal}), ("ДОБ. 44", {by_internal}),
        ("ЕЛОЧНАЯ", {by_workplace}), ("кабинет 12", {by_workplace}),
        ("БЕРЁЗА", {reverse}), ("береза-м", {reverse}),
        ("нет-такого-значения-zz", set()),
    ]
    for text, expected in cases:
        found = ids(read(client, "?" + _qs(q=text)), mine)
        assert found == {u.pk for u in expected}, f"поиск «{text}»: ждали {sorted(u.full_name for u in expected)}"


def _qs(**params) -> str:
    from urllib.parse import urlencode
    return urlencode(params)


def test_search_by_unit_name():
    """FR-130: через `staff_directory` поиск находит сотрудников по названиям их узлов (без учёта регистра и «е/ё»)."""
    tree = support_org.make_tree({"Сеть": {"Серверы": {}}, "Ёлки": {}})
    in_net, in_servers, in_elki, nobody = person(), person(), person(), person()
    support_org.make_member(in_net, tree["Сеть"])
    support_org.make_member(in_servers, tree["Серверы"])
    support_org.make_member(in_elki, tree["Ёлки"])
    mine = [in_net, in_servers, in_elki, nobody]
    client = support.logged_in(support.make_admin())
    assert ids(read(client, "?q=сеть"), mine) == {in_net.pk}
    assert ids(read(client, "?q=СЕТЬ"), mine) == {in_net.pk}
    assert ids(read(client, "?q=серв"), mine) == {in_servers.pk}
    assert ids(read(client, "?q=" + "ЕЛКИ"), mine) == {in_elki.pk}
    assert ids(read(client, "?q=" + "ёлки"), mine) == {in_elki.pk}
    assert ids(read(client, "?q=нет-такого-узла-zz"), mine) == set()


# --- фильтры и пресеты ----------------------------------------------------------------------

def test_unit_filter_includes_nested_units():
    """FR-131: фильтр «Подразделение» показывает членов узла и всех вложенных; человек в двух узлах — одна строка."""
    tree = support_org.make_tree({"Сеть": {"Серверы": {"Стойки": {}}}, "Поддержка": {}})
    a, b, c, d, e, both = (person() for _ in range(6))
    support_org.make_member(a, tree["Сеть"])
    support_org.make_member(b, tree["Серверы"])
    support_org.make_member(c, tree["Стойки"])
    support_org.make_member(d, tree["Поддержка"])
    support_org.make_member(both, tree["Сеть"])
    support_org.make_member(both, tree["Серверы"])
    mine = [a, b, c, d, e, both]
    client = support.logged_in(support.make_admin())
    page = read(client, f"?unit={tree['Сеть'].pk}")
    assert ids(page, mine) == {a.pk, b.pk, c.pk, both.pk}
    assert [int(r["attrs"]["data-user-id"]) for r in page.rows].count(both.pk) == 1
    assert ids(read(client, f"?unit={tree['Серверы'].pk}"), mine) == {b.pk, c.pk, both.pk}
    assert ids(read(client, f"?unit={tree['Стойки'].pk}"), mine) == {c.pk}
    assert ids(read(client, f"?unit={tree['Поддержка'].pk}"), mine) == {d.pk}
    options = read(client).unit_options
    assert options and options[0]["value"] == "", "первая строка фильтра — «все подразделения» с пустым значением"
    values = {o["value"] for o in options}
    assert {str(tree[n].pk) for n in ("Сеть", "Серверы", "Стойки", "Поддержка")} <= values


def test_presets_in_company_default_dismissed_without_unit_all():
    """FR-131, FR-119: «В компании» (пустой `state`) — все, кроме уволенных; «Уволены», «Без подразделения» (не уволенные без членств), «Все» (`state=all`); у коллеги нет служебных пресетов."""
    unit = support_org.make_unit("Сеть")
    working = person()
    free = person()
    invited = person(state="invited", totp=False)
    gone_in_unit = person()
    gone_free = person(state="dismissed")
    support_org.make_member(working, unit)
    support_org.make_member(invited, unit)
    support_org.make_member(gone_in_unit, unit)
    from apps.org.services import people
    people.dismiss(gone_in_unit, actor=support.make_admin())  # членство снимается (FR-125)
    gone_in_unit.refresh_from_db()
    assert gone_in_unit.state == "dismissed" and not support.model("org.Membership").objects.filter(user=gone_in_unit).exists()
    mine = [working, free, invited, gone_in_unit, gone_free]
    viewer = support.make_with_permissions("staff.view")
    client = support.logged_in(viewer)
    assert ids(read(client), mine) == {working.pk, free.pk, invited.pk}
    assert ids(read(client, "?state="), mine) == {working.pk, free.pk, invited.pk}
    assert ids(read(client, "?state=dismissed"), mine) == {gone_in_unit.pk, gone_free.pk}
    assert ids(read(client, "?state=no_unit"), mine) == {free.pk}
    assert ids(read(client, "?state=all"), mine) == {working.pk, free.pk, invited.pk, gone_in_unit.pk, gone_free.pk}
    assert ids(read(client, "?state=no-such-state"), mine) == {working.pk, free.pk, invited.pk}
    marks = {int(r["attrs"]["data-user-id"]): r["attrs"] for r in read(client, "?state=dismissed").rows}
    assert marks[gone_in_unit.pk].get("data-dismissed") == "true" and "data-state" not in marks[gone_in_unit.pk]
    # ссылки пресетов: порядок и подписи, активный помечен
    page = read(client)
    assert [p["value"] for p in page.presets] == COLLEAGUE_PRESETS
    titles = [" ".join(p["text"].split()).lower() for p in page.presets]
    assert titles == ["в компании", "уволены", "без подразделения", "все"]
    assert [p["value"] for p in page.presets if p["current"] == "true"] == [""]
    assert [p["value"] for p in read(client, "?state=dismissed").presets if p["current"] == "true"] == ["dismissed"]
    assert [p["value"] for p in read(client, "?state=all").presets if p["current"] == "true"] == ["all"]


def test_service_presets_role_filter_and_state_column_only_with_accounts_manage():
    """FR-131, FR-119: «Приглашены», «Активные», «Заблокированные», фильтр роли и колонка состояния — только с `accounts.manage`; у коллеги такие `state` и `role` не действуют."""
    role = factories.make_role(name="Аудитор-поиск")
    active = person(roles=[role])
    invited = person(state="invited", totp=False)
    blocked = person(state="blocked")
    gone = person(state="dismissed", roles=[role])
    mine = [active, invited, blocked, gone]
    admin_client = support.logged_in(support.make_admin())
    page = read(admin_client)
    assert [p["value"] for p in page.presets] == SERVICE_PRESETS
    titles = [" ".join(p["text"].split()).lower() for p in page.presets]
    assert titles == ["в компании", "уволены", "без подразделения", "все", "приглашены", "активные", "заблокированные"]
    assert ids(page, mine) == {active.pk, invited.pk, blocked.pk}
    assert ids(read(admin_client, "?state=invited"), mine) == {invited.pk}
    assert ids(read(admin_client, "?state=active"), mine) == {active.pk}
    assert ids(read(admin_client, "?state=blocked"), mine) == {blocked.pk}
    assert ids(read(admin_client, f"?role={role.pk}"), mine) == {active.pk}
    assert ids(read(admin_client, f"?state=all&role={role.pk}"), mine) == {active.pk, gone.pk}
    assert all("state" in r["cells"] for r in page.rows), "у accounts.manage есть колонка состояния"
    # коллега без accounts.manage
    colleague = support.logged_in(support.make_with_permissions("staff.view"))
    page = read(colleague)
    assert [p["value"] for p in page.presets] == COLLEAGUE_PRESETS
    assert page.rows and all("state" not in r["cells"] for r in page.rows), "у коллеги колонки состояния нет"
    default = ids(page, mine)
    for r in page.rows:
        assert "data-state" not in r["attrs"], "у коллеги служебное состояние строки скрыто (FR-119)"
    gone_rows = [r for r in read(colleague, "?state=all").rows if r["attrs"]["data-user-id"] == str(gone.pk)]
    assert len(gone_rows) == 1 and gone_rows[0]["attrs"].get("data-dismissed") == "true"
    assert "data-state" not in gone_rows[0]["attrs"]
    admin_rows = {r["attrs"]["data-user-id"]: r["attrs"].get("data-state") for r in read(admin_client, "?state=all").rows}
    assert admin_rows[str(blocked.pk)] == "blocked" and admin_rows[str(gone.pk)] == "dismissed"
    assert default == {active.pk, invited.pk, blocked.pk}
    for query in ("?state=invited", "?state=active", "?state=blocked", f"?role={role.pk}"):
        assert ids(read(colleague, query), mine) == default, f"{query} у коллеги действует как пустой"


def test_columns_photo_name_position_unit_internal_phone_email():
    """FR-130: колонки — фото (заглушка с инициалами), ФИО со ссылкой на карточку, должность, подразделение, внутренний телефон, почта; состояние — только у `accounts.manage`, колонки ролей нет."""
    tree = support_org.make_tree({"Сеть": {}, "Поддержка": {}})
    target = person(full_name="Иван Петров", position="Инженер связи", internal_phone="Доб. 321")
    support_org.make_member(target, tree["Сеть"])
    support_org.make_member(target, tree["Поддержка"])
    base = {"photo", "name", "position", "unit", "internal-phone", "email"}
    colleague = support.logged_in(support.make_with_permissions("staff.view"))
    row = _row_of(read(colleague, "?q=" + "Инженер связи"), target)
    assert set(row["cells"]) == base
    assert row["name_href"] == f"/staff/{target.pk}/"
    assert "Иван Петров" in cell(row, "name")
    assert cell(row, "position") == "Инженер связи"
    assert {part.strip() for part in cell(row, "unit").split(",")} == {"Сеть", "Поддержка"}
    assert cell(row, "internal-phone") == "Доб. 321"
    assert cell(row, "email") == target.email
    assert row["photo"].get("data-photo-placeholder") is not None, "без фото — заглушка с инициалами"
    assert row["photo"]["data-photo-placeholder"].get("data-initials") == "ИП"
    admin = support.logged_in(support.make_admin())
    page = read(admin, "?q=" + "Инженер связи")
    assert set(_row_of(page, target)["cells"]) == base | {"state"}
    for client in (colleague, admin):
        titles = [" ".join("".join(parts).split()) for parts in read(client).headers]
        assert "Роли" not in titles, "колонки ролей в списке нет"


def _row_of(page: _Page, user):
    rows = [r for r in page.rows if r["attrs"]["data-user-id"] == str(user.pk)]
    assert len(rows) == 1, f"строка сотрудника {user.pk} не найдена или не одна"
    return rows[0]


# --- параметры SQL ---------------------------------------------------------------------------

def test_search_values_passed_as_parameters():
    """NFR-108: значение поиска передаётся параметром запроса, а не вставляется в текст SQL."""
    needle = "zqx9needle'quote;--ёЁ"
    normalized = needle.lower().replace("ё", "е")
    captured: list[tuple[str, object]] = []

    def wrapper(execute, sql, params, many, context):
        captured.append((sql, params))
        return execute(sql, params, many, context)

    client = support.logged_in(support.make_admin())
    with connection.execute_wrapper(wrapper):
        response = client.get("/staff/?" + _qs(q=needle))
    assert response.status_code == 200
    assert captured, "запросы к базе не перехвачены"
    for sql, _ in captured:
        text = sql.lower().replace("ё", "е")
        assert "zqx9needle" not in text and "quote;--" not in text, "строка поиска попала в текст SQL"

    def flat(params):
        if params is None:
            return []
        values = params.values() if isinstance(params, dict) else params
        return [str(p) for p in values]

    def carrying_params(items):
        return [(sql, params) for sql, params in items if any("zqx9needle" in v.lower() for v in flat(params))]

    carrying = [sql for sql, params in captured if any("zqx9needle" in v.lower() for v in flat(params))]
    assert carrying, "строки поиска нет среди параметров ни одного запроса"
    assert any("translate" in sql.lower() and "lower" in sql.lower() for sql in carrying), (
        "поиск должен сравнивать translate(lower(поле), 'ё', 'е') (план: «Список «Сотрудники» и поиск»)")
    assert any(normalized in v for sql, params in carrying_params(captured) for v in flat(params)), (
        "параметр должен нести приведённую строку (нижний регистр, «ё»→«е»), допускается обрамление %…%")
