"""T-3127: загрузка заявителей — файл и предпросмотр (FR-262, FR-263, FR-265, NFR-204). Сценарий 10 спеки."""
import io
import secrets
import time
import zipfile
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from tests import support, support_org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

DOMAIN = "corp.test"
MAX_BYTES = 2 * 1024 * 1024
MAX_ROWS = 2000
HEADERS = ["Почта", "Фамилия", "Имя", "Отчество", "Подразделение"]
ROW_KEYS = {"email", "last_name", "first_name", "middle_name", "unit"}
IMPORT_URL = "/servicedesk/requesters/import/"
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- помощники этого файла ---------------------------------------------------------------------

class Node:
    def __init__(self, tag, attrs, parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs), parent, []

    def text(self) -> str:
        parts = []
        for child in self.children:
            parts.append(child if isinstance(child, str) else child.text())
        return " ".join("".join(parts).split())

    def walk(self):
        yield self
        for child in self.children:
            if not isinstance(child, str):
                yield from child.walk()


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = Node("#root", {})
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in VOID_TAGS:
            self.cur = node

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def tree(html: str) -> Node:
    parser = _Tree()
    parser.feed(html)
    return parser.root


def import_rows(html: str) -> list[Node]:
    return [n for n in tree(html).walk() if n.tag == "tr" and "data-import-row" in n.attrs]


def reasons_of(row: Node) -> list[str]:
    return [n.text() for n in row.walk() if "data-row-reason" in n.attrs]


def alert_shown(response) -> bool:
    return response.status_code == 200 and any(
        n.attrs.get("role") == "alert" for n in tree(response.content.decode()).walk())


def _recase(email: str, title: bool = False) -> str:
    """Меняет регистр только локальной части: домен остаётся как есть (порядок проверок кода не важен)."""
    local, domain = email.split("@")
    return (local.title() if title else local.upper()) + "@" + domain


def addr(prefix: str = "u") -> str:
    return f"{prefix}{secrets.token_hex(4)}@{DOMAIN}"


def line(email, last="", first="", middle="", unit=""):
    return [email, last, first, middle, unit]


def csv_of(lines, *, headers=HEADERS, delimiter=";", bom=True) -> bytes:
    return support_org.staff_csv(lines, headers=headers, delimiter=delimiter, bom=bom)


def xlsx_of(lines, *, headers=HEADERS) -> bytes:
    return support_org.staff_xlsx(lines, headers=headers)


def service():
    from apps.servicedesk.services import requester_import
    return requester_import


def sd_error():
    from apps.servicedesk.services import ServiceDeskError
    return ServiceDeskError


def unit(name: str, archived: bool = False):
    return model("servicedesk.ClientUnit").objects.create(
        name=name, name_key=support_org.name_key(name), archived=archived)


def preview(content: bytes, user, name: str = "people.csv"):
    return service().make_preview(content, file_name=name, actor=user)


def upload(client, content: bytes, name: str = "people.csv"):
    return client.post(IMPORT_URL, {"file": SimpleUploadedFile(name, content, content_type="application/octet-stream")})


def state() -> dict:
    """Всё, что загрузка могла бы записать: заявители, подразделения, число загрузок и журнала."""
    return {
        "requesters": sorted(model("servicedesk.Requester").objects.values_list(
            "id", "email", "full_name", "client_unit_id", "origin")),
        "units": sorted(model("servicedesk.ClientUnit").objects.values_list("id", "name", "archived")),
        "imports": model("servicedesk.RequesterImport").objects.count(),
        "audit": model("core.AuditEvent").objects.count(),
    }


@pytest.fixture(autouse=True)
def _domains(db):
    sd.configure_servicedesk(domains=[DOMAIN])


@pytest.fixture
def who(db):
    user = support.make_with_permissions("servicedesk.manage")
    return SimpleNamespace(user=user, client=support.logged_in(user))


def refused(who, content: bytes, code: str, *, name: str = "people.csv", must_mention: tuple = ()):
    """Служба отказывает кодом `code`, страница — 200 с `[role=alert]`, ничего не записано (FR-265)."""
    before = state()
    with pytest.raises(sd_error()) as raised:
        service().parse_file(content)
    assert raised.value.code == code, f"parse_file: ожидали {code!r}, получили {raised.value.code!r}"
    for word in must_mention:
        assert word in str(raised.value), f"текст отказа должен называть {word!r}"
    with pytest.raises(sd_error()) as raised:
        preview(content, who.user, name)
    assert raised.value.code == code, f"make_preview: ожидали {code!r}, получили {raised.value.code!r}"
    assert state() == before, "отказ: ничего не записано (служба)"
    response = upload(who.client, content, name)
    assert alert_shown(response), f"{code}: ожидали 200 с [role=alert], получили {response.status_code}"
    assert state() == before, "отказ: ничего не записано (страница)"


def exact_size_csv(total: int) -> bytes:
    """Годный по структуре CSV ровно из `total` байт: 1000 строк, лишние байты — в «Фамилии» строк."""
    lines = [line(f"u{i}@{DOMAIN}") for i in range(1000)]
    base = len(csv_of(lines))
    each, rest = divmod(total - base, 1000)
    for i, row in enumerate(lines):
        row[1] = "x" * (each + (rest if i == 999 else 0))
    data = csv_of(lines)
    assert len(data) == total, "помощник теста собрал не тот размер"
    return data


def last_import():
    return model("servicedesk.RequesterImport").objects.order_by("-id").first()


# --- тесты --------------------------------------------------------------------------------------

def test_csv_semicolon_preview(who):
    """FR-262, FR-263: CSV с «;» принимается; предпросмотр по строкам (добавлен, без изменений, ошибка), запись загрузки
    в состоянии `preview`; страница показывает те же строки. Сценарий 10, п. 2."""
    office = unit("Офис")
    known = addr("k")
    sd.make_requester(known, full_name="Сидорова Анна", client_unit=office, origin="table")
    new, foreign = addr("n"), f"x{secrets.token_hex(3)}@other.example"
    lines = [line(new, "Иванов", "Иван", "Петрович", "Офис"),
             line(known, "Сидорова", "Анна", "", "Офис"),
             line(foreign, "Чужой", "Иван", "", "")]
    content = csv_of(lines, delimiter=";")
    parsed = service().parse_file(content)
    assert parsed.file_format == "csv" and parsed.not_loaded == []
    assert [set(r) for r in parsed.rows] == [ROW_KEYS] * 3
    assert [(r["email"], r["last_name"], r["first_name"], r["middle_name"], r["unit"]) for r in parsed.rows] == [
        tuple(row) for row in lines]
    item = preview(content, who.user)
    assert item.state == "preview" and item.file_format == "csv" and item.file_name == "people.csv"
    assert item.delete_missing is False and item.created_by == who.user
    assert [r["number"] for r in item.rows] == [1, 2, 3]
    assert [r["result"] for r in item.rows] == ["will_add", "unchanged", "error"]
    assert (item.rows[0]["email"], item.rows[0]["last_name"], item.rows[0]["unit"]) == (new, "Иванов", "Офис")
    assert [item.summary[k] for k in ("added", "updated", "unchanged", "errors", "deleted", "would_delete")] == [
        1, 0, 1, 1, 0, 0]
    # страница: загрузка файла даёт 302 на предпросмотр, предпросмотр показывает строки
    response = upload(who.client, content)
    assert response.status_code == 302, response.status_code
    created = last_import()
    assert response["Location"].endswith(f"{IMPORT_URL}{created.pk}/")
    shown = who.client.get(response["Location"])
    assert shown.status_code == 200
    html = shown.content.decode()
    assert any("data-import-preview" in n.attrs for n in tree(html).walk())
    rows = import_rows(html)
    assert [r.attrs["data-row-number"] for r in rows] == ["1", "2", "3"]
    assert "будет добавлен" in rows[0].text() and "без изменений" in rows[1].text()
    assert "ошибка:" in rows[2].text() and reasons_of(rows[2]), "у строки с ошибкой есть [data-row-reason]"
    assert reasons_of(rows[0]) == [] and reasons_of(rows[1]) == []


def test_csv_comma_preview(who):
    """FR-262: CSV с разделителем «,» (определяется по строке заголовков), значение в кавычках с запятой читается."""
    e1, e2 = addr("a"), addr("b")
    lines = [line(e1, "Петров", "Пётр", "", "Отдел, сеть"), line(e2, "Орлова", "Мария", "Ивановна", "")]
    content = csv_of(lines, delimiter=",", bom=False)
    parsed = service().parse_file(content)
    assert parsed.file_format == "csv"
    assert [r["unit"] for r in parsed.rows] == ["Отдел, сеть", ""]
    assert [r["email"] for r in parsed.rows] == [e1, e2]
    assert parsed.rows[1]["middle_name"] == "Ивановна"
    item = preview(content, who.user)
    assert item.file_format == "csv" and [r["result"] for r in item.rows] == ["will_add", "will_add"]
    assert item.summary["added"] == 2 and item.new_units == ["Отдел, сеть"]
    response = upload(who.client, content)
    assert response.status_code == 302
    assert len(import_rows(who.client.get(response["Location"]).content.decode())) == 2


def test_csv_with_bom_preview(who):
    """FR-262: CSV в UTF-8 с BOM и без него читается одинаково; BOM не портит первый заголовок «Почта» и первый адрес."""
    lines = [line(addr("a"), "Иванов", "Иван", "", "Склад"), line(addr("b"), "Сидоров", "", "", "")]
    for delimiter in (";", ","):
        with_bom = csv_of(lines, delimiter=delimiter, bom=True)
        without = csv_of(lines, delimiter=delimiter, bom=False)
        assert with_bom.startswith(b"\xef\xbb\xbf") and not without.startswith(b"\xef\xbb\xbf")
        got = [service().parse_file(c) for c in (with_bom, without)]
        assert got[0].rows == got[1].rows, f"разделитель {delimiter!r}: с BOM и без BOM — одно и то же"
        assert got[0].rows[0]["email"] == lines[0][0] and "﻿" not in got[0].rows[0]["email"]
        assert got[0].file_format == "csv"
    item = preview(csv_of(lines, bom=True), who.user)
    assert [r["result"] for r in item.rows] == ["will_add", "will_add"]
    assert item.rows[0]["email"] == lines[0][0]


def test_xlsx_500_rows_preview(who):
    """FR-262, FR-263: XLSX на 500 строк — предпросмотр по каждой строке; формат определён по содержимому.
    Сценарий 10, п. 2."""
    office = unit("Офис")
    existing = [addr(f"e{i:03d}") for i in range(50)]
    for email in existing:
        sd.make_requester(email, full_name="Старое Имя", client_unit=office, origin="table")
    lines = [line(email, "Новая", "Фамилия", "", "Офис") for email in existing]
    lines += [line(addr(f"n{i:03d}"), f"Фамилия{i}", "Имя", "", "Офис") for i in range(450)]
    content = xlsx_of(lines)
    parsed = service().parse_file(content)
    assert parsed.file_format == "xlsx" and len(parsed.rows) == 500 and parsed.not_loaded == []
    item = preview(content, who.user, "people.xlsx")
    assert item.state == "preview" and item.file_format == "xlsx" and item.file_name == "people.xlsx"
    assert [r["number"] for r in item.rows] == list(range(1, 501))
    assert [r["result"] for r in item.rows] == ["will_update"] * 50 + ["will_add"] * 450
    assert (item.summary["added"], item.summary["updated"], item.summary["unchanged"], item.summary["errors"]) == (
        450, 50, 0, 0)
    response = upload(who.client, content, "people.xlsx")
    assert response.status_code == 302
    assert last_import().file_format == "xlsx"
    rows = import_rows(who.client.get(response["Location"]).content.decode())
    assert len(rows) == 500
    assert [r.attrs["data-row-number"] for r in rows] == [str(i) for i in range(1, 501)]


def test_file_over_2mb_refused_nothing_written(who):
    """FR-265: файл больше 2 МБ — отказ `too_big` до разбора, ничего не записано; ровно 2 МБ принимается."""
    from apps.servicedesk.services import requester_import
    assert requester_import.MAX_BYTES == MAX_BYTES and requester_import.MAX_ROWS == MAX_ROWS
    exact = exact_size_csv(MAX_BYTES)
    assert len(service().parse_file(exact).rows) == 1000, "ровно 2 МБ принимается"
    refused(who, exact_size_csv(MAX_BYTES + 1), "too_big")
    refused(who, b"\x00" * (MAX_BYTES + 1), "too_big")


def test_file_over_2000_rows_refused_nothing_written(who):
    """FR-265: больше 2000 строк (CSV и XLSX) — отказ `too_many_rows`, ничего не записано; ровно 2000 принимается."""
    for build, name in ((csv_of, "people.csv"), (xlsx_of, "people.xlsx")):
        exact = build([line(f"u{i}@{DOMAIN}") for i in range(MAX_ROWS)])
        assert len(service().parse_file(exact).rows) == MAX_ROWS, f"{name}: ровно 2000 строк принимается"
        refused(who, build([line(f"u{i}@{DOMAIN}") for i in range(MAX_ROWS + 1)]), "too_many_rows", name=name)


def test_file_not_csv_or_xlsx_refused(who):
    """FR-265: не CSV и не XLSX отклоняется целиком: архив без книги, ZIP-«бомба», XML-«бомба», картинка."""
    plain_zip = io.BytesIO()
    with zipfile.ZipFile(plain_zip, "w") as archive:
        archive.writestr("readme.txt", "это не книга")
    refused(who, plain_zip.getvalue(), "bad_format", name="people.xlsx")
    refused(who, plain_zip.getvalue(), "bad_format", name="people.csv")
    no_book = io.BytesIO()
    with zipfile.ZipFile(no_book, "w") as archive:
        archive.writestr("[Content_Types].xml", '<?xml version="1.0"?><Types/>')
        archive.writestr("xl/worksheets/sheet1.xml", "<worksheet/>")
    refused(who, no_book.getvalue(), "bad_format", name="people.xlsx")
    refused(who, b"\x89PNG\r\n\x1a\n\xff\xfe\xfd" * 50, "not_utf8", name="photo.png")
    # пределы архива и XML — те же коды, что у загрузки сотрудников (6.2, 6.23)
    bomb = support_org.xlsx_zip_bomb()
    assert len(bomb) < MAX_BYTES, "бомба сама в пределе размера: отказ идёт от проверки оглавления"
    refused(who, bomb, "zip_bomb", name="people.xlsx")
    many = support_org.xlsx_many_parts()
    assert len(many) < MAX_BYTES
    refused(who, many, "zip_bomb", name="people.xlsx")
    refused(who, support_org.xlsx_xml_bomb(), "xml_bomb", name="people.xlsx")
    # обычная книга при этом принимается
    assert service().parse_file(xlsx_of([line(addr())])).file_format == "xlsx"


def test_file_not_utf8_refused(who):
    """FR-265: файл не в UTF-8 (Windows-1251, нулевой байт) отклоняется кодом `not_utf8`, ничего не записано."""
    cp1251 = csv_of([line(addr(), "Иванов", "Иван", "", "")], bom=False).decode("utf-8").encode("cp1251")
    refused(who, cp1251, "not_utf8")
    refused(who, csv_of([line(addr(), "Иван\x00ов", "Иван", "", "")]), "not_utf8")
    refused(who, b"\xef\xbb\xbf" + csv_of([line(addr())], bom=False) + b"\xff\xfe", "not_utf8")


def test_file_without_email_column_refused(who):
    """FR-265: без колонки «Почта» отклоняется весь файл (`missing_columns`, в тексте слово «Почта»); колонки
    проверяются раньше числа строк."""
    no_email = ["Фамилия", "Имя", "Отчество", "Подразделение"]
    rows = [["Иванов", "Иван", "", ""]]
    refused(who, csv_of(rows, headers=no_email), "missing_columns", must_mention=("Почта",))
    refused(who, xlsx_of(rows, headers=no_email), "missing_columns", name="people.xlsx", must_mention=("Почта",))
    wrong = ["Email", "Фамилия", "Имя", "Отчество", "Подразделение"]
    refused(who, csv_of([line(addr(), "Иванов")], headers=wrong), "missing_columns", must_mention=("Почта",))
    many = [["Иванов", "Иван", "", ""] for _ in range(MAX_ROWS + 1)]
    refused(who, csv_of(many, headers=no_email), "missing_columns", must_mention=("Почта",))


def test_only_email_column_required(who):
    """FR-262: обязательна только колонка «Почта»; остальные колонки необязательны, значения отсутствующих — пустые."""
    emails = [addr("a"), addr("b")]
    for content, name in ((csv_of([[e] for e in emails], headers=["Почта"]), "people.csv"),
                          (xlsx_of([[e] for e in emails], headers=["Почта"]), "people.xlsx"),
                          (csv_of([["Склад", e] for e in emails], headers=["Подразделение", "Почта"]), "people.csv")):
        parsed = service().parse_file(content)
        assert parsed.not_loaded == [], name
        assert [set(r) for r in parsed.rows] == [ROW_KEYS] * 2, name
        assert [r["email"] for r in parsed.rows] == emails, name
        assert all(r["last_name"] == r["first_name"] == r["middle_name"] == "" for r in parsed.rows), name
    item = preview(csv_of([[e] for e in emails], headers=["Почта"]), who.user)
    assert [r["result"] for r in item.rows] == ["will_add", "will_add"] and item.summary["errors"] == 0
    assert item.rows[0]["last_name"] == "" and item.rows[0]["unit"] == ""
    response = upload(who.client, csv_of([[e] for e in emails], headers=["Почта"]))
    assert response.status_code == 302


def test_headers_case_space_yo_insensitive_extra_columns_named_not_loaded(who):
    """FR-262: заголовки — без регистра, пробелов и «е/ё», в любом порядке; лишние колонки не читаются, а названы
    в `not_loaded`, в предпросмотре и на странице («не загружаются»)."""
    token = secrets.token_hex(6)
    email = addr()
    messy = ["  ПОЧТА ", "фамилия", "И м Я", "О т ч е с т в о", "Подразделёние", "Роль", "Дата рождения"]
    values = [email, "Сидоров", "Фёдор", "Иванович", "Склад", f"роль-{token}", f"дата-{token}"]
    reverse_headers, reverse_values = messy[::-1], values[::-1]
    for content in (csv_of([values], headers=messy), csv_of([values], headers=messy, delimiter=","),
                    xlsx_of([values], headers=messy), csv_of([reverse_values], headers=reverse_headers)):
        parsed = service().parse_file(content)
        assert [set(r) for r in parsed.rows] == [ROW_KEYS]
        got = parsed.rows[0]
        assert (got["email"], got["last_name"], got["first_name"], got["middle_name"], got["unit"]) == (
            email, "Сидоров", "Фёдор", "Иванович", "Склад")
        assert sorted(parsed.not_loaded) == sorted(["Роль", "Дата рождения"]), parsed.not_loaded
        assert token not in "".join(got.values()), "значения лишних колонок не читаются"
    item = preview(csv_of([values], headers=messy), who.user)
    assert sorted(item.summary["not_loaded"]) == sorted(["Роль", "Дата рождения"])
    assert token not in str(item.rows), "значения лишних колонок в предпросмотре не хранятся"
    response = upload(who.client, csv_of([values], headers=messy))
    assert response.status_code == 302
    html = who.client.get(response["Location"]).content.decode()
    names = [n.text() for n in tree(html).walk() if n.tag == "li" and _inside(n, "data-import-not-loaded")]
    assert len(names) == 2 and any("Роль" in t for t in names) and any("Дата рождения" in t for t in names)
    holders = [n for n in tree(html).walk() if "data-import-not-loaded" in n.attrs]
    assert holders and "не загружаются" in (holders[0].parent or holders[0]).text(), "фраза — у списка лишних колонок"
    assert token not in html
    clean = upload(who.client, csv_of([values[:5]], headers=messy[:5]))
    clean_html = who.client.get(clean["Location"]).content.decode()
    assert [n for n in tree(clean_html).walk() if n.tag == "li" and _inside(n, "data-import-not-loaded")] == []


def _inside(node: Node, attr: str) -> bool:
    parent = node.parent
    while parent is not None:
        if attr in parent.attrs:
            return True
        parent = parent.parent
    return False


def test_row_error_email_missing_or_bad_format(who):
    """FR-263: строка без почты — `email_missing`, с неверным форматом — `email_invalid`; причина по-русски
    «ошибка: …»; остальные строки не затронуты. Сценарий 10, п. 4."""
    good = addr()
    lines = [line("", "Без", "Почты"), line("plainaddress", "Без", "Собаки"), line("a b@corp.test", "С", "Пробелом"),
             line("@corp.test", "Без", "Имени"), line(good, "Годная", "Строка")]
    item = preview(csv_of(lines), who.user)
    codes = [r["code"] for r in item.rows]
    assert codes[0] == "email_missing", codes
    assert codes[1:4] == ["email_invalid"] * 3, codes
    assert [r["result"] for r in item.rows] == ["error"] * 4 + ["will_add"]
    assert item.rows[0]["reason"] == "ошибка: не указана почта"
    assert all(r["reason"] == "ошибка: неверный формат почты" for r in item.rows[1:4])
    assert item.summary["errors"] == 4 and item.summary["added"] == 1
    response = upload(who.client, csv_of(lines))
    rows = import_rows(who.client.get(response["Location"]).content.decode())
    assert [r.attrs["data-row-result"] for r in rows][:4] == ["error"] * 4
    assert reasons_of(rows[0]) == ["ошибка: не указана почта"]
    assert reasons_of(rows[1]) == ["ошибка: неверный формат почты"]
    assert reasons_of(rows[4]) == []


def test_row_error_foreign_domain(who):
    """FR-262, FR-263: почта не из корпоративного домена — `foreign_domain`; домен без учёта регистра годен."""
    lines = [line(f"x{secrets.token_hex(3)}@other.example", "Чужой"), line(f"Y{secrets.token_hex(3)}@{DOMAIN}", "Свой")]
    item = preview(csv_of(lines), who.user)
    assert item.rows[0]["code"] == "foreign_domain" and item.rows[0]["result"] == "error"
    assert item.rows[0]["reason"] == "ошибка: почта не из корпоративного домена"
    assert item.rows[1]["result"] == "will_add" and item.rows[1]["code"] in ("", None)
    assert item.summary["errors"] == 1 and item.summary["added"] == 1
    response = upload(who.client, csv_of(lines))
    rows = import_rows(who.client.get(response["Location"]).content.decode())
    assert reasons_of(rows[0]) == ["ошибка: почта не из корпоративного домена"] and reasons_of(rows[1]) == []


def test_row_error_duplicate_email_other_case_second_row(who):
    """FR-262, FR-263: повтор почты в другом регистре — ошибка второй и следующих строк («ошибка: повтор почты»),
    первая строка остаётся годной. Сценарий 10, п. 14."""
    base = addr("dup")
    lines = [line(base, "Первый", "Иван"), line(_recase(base), "Второй", "Иван"), line(_recase(base, True), "Третий", "Иван"),
             line(addr(), "Другой", "Иван")]
    item = preview(csv_of(lines), who.user)
    assert [r["result"] for r in item.rows] == ["will_add", "error", "error", "will_add"]
    assert [r["code"] for r in item.rows[1:3]] == ["email_repeated"] * 2
    assert all(r["reason"] == "ошибка: повтор почты" for r in item.rows[1:3])
    assert item.summary["added"] == 2 and item.summary["errors"] == 2
    response = upload(who.client, csv_of(lines))
    rows = import_rows(who.client.get(response["Location"]).content.decode())
    assert reasons_of(rows[0]) == [] and reasons_of(rows[1]) == ["ошибка: повтор почты"]
    assert reasons_of(rows[2]) == ["ошибка: повтор почты"]


def test_duplicate_email_error_even_if_first_row_has_error(who):
    """FR-262, FR-263: вторая строка с той же почтой — `email_repeated`, даже если первая сама с ошибкой."""
    first, second = addr("one"), addr("two")
    unit("Склад", archived=True)
    lines = [line(first, "Ф" * 100, "И" * 100, "О" * 60),          # ФИО длиннее 255: too_long
             line(_recase(first), "Повтор", "Иван"),
             line(second, "Архивный", "Иван", "", "Склад"),         # подразделение в архиве
             line(_recase(second, True), "Повтор", "Иван", "", "")]
    item = preview(csv_of(lines), who.user)
    assert [r["code"] for r in item.rows] == ["too_long", "email_repeated", "unit_archived", "email_repeated"]
    assert [r["result"] for r in item.rows] == ["error"] * 4
    assert item.rows[1]["reason"] == item.rows[3]["reason"] == "ошибка: повтор почты"
    assert item.summary["errors"] == 4 and item.summary["added"] == 0


def test_row_error_unit_in_archive(who):
    """FR-262, FR-263: подразделение из архива справочника — «ошибка: подразделение в архиве»; архивное не попадает
    в список создаваемых. Сценарий 10, п. 14 (первая строка — архив, вторая — повтор почты)."""
    unit("Склад", archived=True)
    unit("Офис")
    mail = addr()
    lines = [line(mail, "Архивный", "Иван", "", "Склад"), line(mail.upper(), "Повтор", "Иван", "", "Офис"),
             line(addr(), "Годный", "Иван", "", "Офис")]
    item = preview(csv_of(lines), who.user)
    assert item.rows[0]["code"] == "unit_archived" and item.rows[0]["result"] == "error"
    assert item.rows[0]["reason"] == "ошибка: подразделение в архиве"
    assert item.rows[1]["code"] == "email_repeated" and item.rows[1]["reason"] == "ошибка: повтор почты"
    assert item.rows[2]["result"] == "will_add"
    assert "Склад" not in item.new_units and "Офис" not in item.new_units
    assert model("servicedesk.ClientUnit").objects.count() == 2, "предпросмотр подразделений не создаёт"
    response = upload(who.client, csv_of(lines))
    rows = import_rows(who.client.get(response["Location"]).content.decode())
    assert reasons_of(rows[0]) == ["ошибка: подразделение в архиве"]
    assert reasons_of(rows[1]) == ["ошибка: повтор почты"]


def test_row_error_field_length_exceeded(who):
    """FR-263: слишком длинное значение — `too_long`: почта больше 254, ФИО (непустые части через пробел) больше 255,
    подразделение больше 150; ровно по пределу — годно."""
    over_email = "a" * 250 + f"@{DOMAIN}"
    edge_email = "b" * (254 - len(DOMAIN) - 1) + f"@{DOMAIN}"
    assert len(over_email) > 254 and len(edge_email) == 254
    lines = [line(over_email, "Иванов", "Иван"),
             line(addr(), "Ф" * 100, "И" * 100, "О" * 60),     # 100 + 1 + 100 + 1 + 60 = 262 при частях до 255
             line(addr(), "Ф" * 256),                            # одна часть длиннее 255
             line(addr(), "Иванов", "Иван", "", "Ю" * 151),
             line(edge_email, "Предел", "Почты"),
             line(addr(), "Ф" * 100, "И" * 100, "О" * 53),      # ровно 255
             line(addr(), "Иванов", "Иван", "", "Ю" * 150)]
    assert len(" ".join(["Ф" * 100, "И" * 100, "О" * 53])) == 255
    item = preview(csv_of(lines), who.user)
    assert [r["code"] for r in item.rows[:4]] == ["too_long"] * 4, [r["code"] for r in item.rows]
    assert all(r["reason"] == "ошибка: значение слишком длинное" for r in item.rows[:4])
    assert [r["result"] for r in item.rows[4:]] == ["will_add"] * 3, "по пределу — без ошибки"
    assert item.summary["errors"] == 4 and item.summary["added"] == 3
    response = upload(who.client, csv_of(lines))
    rows = import_rows(who.client.get(response["Location"]).content.decode())
    assert all(reasons_of(r) == ["ошибка: значение слишком длинное"] for r in rows[:4])


def test_units_missing_in_dictionary_listed_as_to_be_created(who):
    """FR-263: подразделения из файла, которых нет в справочнике, названы списком «будут созданы» — по первому
    написанию, без повторов; есть в справочнике и архивные — не названы. Сценарий 10, п. 3."""
    unit("Бухгалтерия")
    unit("Склад", archived=True)
    lines = [line(addr(), "А", "А", "", "Новый отдел"), line(addr(), "Б", "Б", "", "новый отдел"),
             line(addr(), "В", "В", "", "Бухгалтерия"), line(addr(), "Г", "Г", "", "Склад"),
             line(addr(), "Д", "Д", "", "Другой отдел"), line(addr(), "Е", "Е", "", "")]
    before = state()
    item = preview(csv_of(lines), who.user)
    assert sorted(item.new_units) == ["Другой отдел", "Новый отдел"], item.new_units
    assert len(item.new_units) == 2
    assert state()["units"] == before["units"], "предпросмотр подразделений не создаёт"
    response = upload(who.client, csv_of(lines))
    html = who.client.get(response["Location"]).content.decode()
    listed = [n.text() for n in tree(html).walk() if n.tag == "li" and _inside(n, "data-import-new-units")]
    assert sorted(listed) == ["Другой отдел", "Новый отдел"], listed


def test_row_results_added_updated_unchanged_error(who):
    """FR-263: у строки один из результатов — «будет добавлен», «будет обновлён: …», «без изменений», «ошибка: …».
    Сценарий 10, п. 2."""
    office = unit("Офис")
    same, other = addr("same"), addr("other")
    sd.make_requester(same, full_name="Иванов Иван", client_unit=office, origin="table")
    sd.make_requester(other, full_name="Петров", client_unit=office, origin="table")
    lines = [line(addr("new"), "Новый", "Заявитель", "", "Офис"),
             line(other, "Петров", "Пётр", "", "Офис"),
             line(same, "Иванов", "Иван", "", "Офис"),
             line(f"q{secrets.token_hex(3)}@other.example", "Чужой")]
    item = preview(csv_of(lines), who.user)
    assert [r["result"] for r in item.rows] == ["will_add", "will_update", "unchanged", "error"]
    assert item.rows[2]["changes"] == {} and item.rows[2]["origin_change"] is False
    assert set(item.rows[1]["changes"]) == {"name"}
    assert [item.summary[k] for k in ("added", "updated", "unchanged", "errors")] == [1, 1, 1, 1]
    response = upload(who.client, csv_of(lines))
    rows = import_rows(who.client.get(response["Location"]).content.decode())
    texts = [r.text() for r in rows]
    assert "будет добавлен" in texts[0] and "будет обновлён" in texts[1]
    assert "без изменений" in texts[2] and "ошибка:" in texts[3]
    assert [bool(reasons_of(r)) for r in rows] == [False, False, False, True]
    assert all("data-row-result" in r.attrs for r in rows)


def test_updated_row_shows_name_and_unit_was_became(who):
    """FR-263: у обновляемой строки видно, что изменится: ФИО и подразделение — «было → стало»;
    значение из таблицы заменяет поправленное исполнителем. Сценарий 10, п. 11."""
    warehouse, office = unit("Склад"), unit("Офис")
    both, only_name, only_unit = addr("b"), addr("n"), addr("u")
    sd.make_requester(both, full_name="Иванов Иван", client_unit=warehouse, origin="table")
    sd.make_requester(only_name, full_name="Орлов Олег", client_unit=office, origin="table")
    sd.make_requester(only_unit, full_name="Фомин Фёдор", client_unit=warehouse, origin="table")
    lines = [line(both, "Иванов", "Пётр", "", "Офис"), line(only_name, "Орлов", "Игорь", "", "Офис"),
             line(only_unit, "Фомин", "Фёдор", "", "Офис")]
    item = preview(csv_of(lines), who.user)
    assert [r["result"] for r in item.rows] == ["will_update"] * 3
    assert item.rows[0]["changes"]["name"] == {"before": "Иванов Иван", "after": "Иванов Пётр"}
    assert (item.rows[0]["changes"]["unit"]["before"], item.rows[0]["changes"]["unit"]["after"]) == ("Склад", "Офис")
    assert set(item.rows[1]["changes"]) == {"name"}, "подразделение не менялось — в изменениях его нет"
    assert set(item.rows[2]["changes"]) == {"unit"}, "ФИО не менялось — в изменениях его нет"
    assert item.summary["updated"] == 3
    response = upload(who.client, csv_of(lines))
    rows = import_rows(who.client.get(response["Location"]).content.decode())
    first = rows[0].text()
    for word in ("будет обновлён", "Иванов Иван", "Иванов Пётр", "Склад", "Офис"):
        assert word in first, f"в строке обновления нет {word!r}: {first}"
    assert "Орлов Игорь" in rows[1].text() and "Орлов Олег" in rows[1].text()
    assert "Склад" in rows[2].text() and "Офис" in rows[2].text()


def test_preview_writes_nothing(who):
    """FR-263: до подтверждения ничего не записано — ни заявителей, ни подразделений, ни журнала; предпросмотр
    пишет только свою запись загрузки (файл не хранится). Сценарий 10, п. 2."""
    office = unit("Офис")
    known = addr("k")
    sd.make_requester(known, full_name="Старое Имя", client_unit=office, origin="ticket")
    lines = [line(addr(), "Новый", "Иван", "", "Новый отдел"), line(known, "Новое", "Имя", "", "Офис"),
             line(f"x{secrets.token_hex(3)}@other.example", "Чужой")]
    before = state()
    item = preview(csv_of(lines), who.user)
    after = state()
    assert after["requesters"] == before["requesters"], "заявители не изменились"
    assert after["units"] == before["units"], "подразделения не созданы"
    assert after["audit"] == before["audit"], "предпросмотр журнала не пишет"
    assert after["imports"] == before["imports"] + 1 and item.state == "preview"
    response = upload(who.client, csv_of(lines))
    assert response.status_code == 302
    who.client.get(response["Location"])
    after_page = state()
    assert after_page["requesters"] == before["requesters"] and after_page["units"] == before["units"]
    assert after_page["audit"] == before["audit"]
    assert after_page["imports"] == before["imports"] + 2


def test_preview_2000_rows_within_10_seconds(who):
    """NFR-204: предпросмотр на 2000 строк строится не дольше 10 с; итоги сходятся со строками."""
    office = unit("Офис")
    Requester = model("servicedesk.Requester")
    now = timezone.now()
    emails = [f"p{i:04d}@{DOMAIN}" for i in range(2000)]
    Requester.objects.bulk_create([
        Requester(email=emails[i], full_name=f"Иванов Иван{i}" if i < 300 else "Старое Имя", client_unit=office,
                  origin="table", created_at=now) for i in range(600)])
    lines = []
    for i in range(2000):
        if i < 300:
            lines.append(line(emails[i], "Иванов", f"Иван{i}", "", "Офис"))           # без изменений
        elif i < 600:
            lines.append(line(emails[i], "Новое", "Имя", "", "Офис"))                 # обновлена
        elif i < 1500:
            lines.append(line(emails[i], "Новый", f"Заявитель{i}", "", "Офис"))       # добавлена
        elif i < 1600:
            lines.append(line(f"f{i}@other.example", "Чужой"))                         # чужой домен
        elif i < 1700:
            lines.append(line(emails[i - 1600].upper(), "Повтор"))                     # повтор почты
        else:
            lines.append(line(emails[i], "Новый", f"Заявитель{i}", "", f"Отдел {i % 20}"))   # добавлена, новые отделы
    content = csv_of(lines)
    started = time.perf_counter()
    item = preview(content, who.user)
    elapsed = time.perf_counter() - started
    assert elapsed < 10, f"предпросмотр 2000 строк занял {elapsed:.1f} с"
    assert len(item.rows) == 2000 and [r["number"] for r in item.rows] == list(range(1, 2001))
    assert (item.summary["added"], item.summary["updated"], item.summary["unchanged"], item.summary["errors"]) == (
        1200, 300, 300, 200)
    assert len(item.new_units) == 20


def test_preview_counts_rows_with_empty_cells_kept(who):
    """FR-263: строки с пустыми ячейками остаются и считаются; пустые ФИО и подразделение прежних значений не стирают
    (одна пустая часть ФИО — не пусто); совсем пустая строка не считается."""
    office = unit("Офис")
    keep, partial = addr("keep"), addr("part")
    sd.make_requester(keep, full_name="Сидорова Анна", client_unit=office, origin="table")
    sd.make_requester(partial, full_name="Иванов Иван", client_unit=office, origin="table")
    lines = [line(addr("only")),                                  # одна почта: добавляется
             line(addr("named"), "Орлов"),                        # почта и часть ФИО
             line(keep),                                          # ФИО и подразделение пусты: без изменений
             line(partial, "Иванов"),                             # одна часть ФИО — не пусто: имя заменится
             line("", "Петров", "Пётр", "", "Офис"),              # почты нет, прочее есть: ошибка
             line("", "", "", "", "")]                            # совсем пустая строка не считается
    item = preview(csv_of(lines), who.user)
    assert len(item.rows) == 5, "пять строк с данными; пустая строка не считается"
    assert [r["result"] for r in item.rows] == ["will_add", "will_add", "unchanged", "will_update", "error"]
    assert item.rows[2]["changes"] == {} and item.rows[3]["changes"]["name"]["after"] == "Иванов"
    assert item.rows[4]["code"] == "email_missing"
    assert [item.summary[k] for k in ("added", "updated", "unchanged", "errors")] == [2, 1, 1, 1]
    response = upload(who.client, csv_of(lines))
    rows = import_rows(who.client.get(response["Location"]).content.decode())
    assert len(rows) == 5 and "без изменений" in rows[2].text()
