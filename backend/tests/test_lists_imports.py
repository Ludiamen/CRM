"""T-6118: загрузка из таблицы — файл, сопоставление, предпросмотр (FR-514, FR-533, FR-534, FR-546, NFR-504).

Сценарии 9 (п. 5-8, 10, 12, 14) спеки. Шаги по плану («Загрузка из таблицы и образец»): файл (`/lists/<id>/import/`),
сопоставление и предпросмотр (`/lists/<id>/import/<job>/`); подтверждение — T-6119. Правила значений проверяются
службой `values.parse(..., source="import")` и строкой предпросмотра (`ImportJob.rows`, разметка раздела 11.9).
Код среза на уровне модуля не импортируется: службы берутся внутри тестов (CONTRACT-006, шапка).
"""
import importlib
import io
import json
import re
import time
import zipfile
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from tests import support, support_org
from tests import support_lists as lists

pytestmark = pytest.mark.django_db

TOO_BIG = "Файл больше 5 МБ"
TOO_MANY = "Строк больше 5 000"
BAD_FORMAT = "Формат не поддерживается"
REQUIRED = "Обязательное поле"
BAD_NUMBER = "Введите число"
BAD_DATE = "Введите дату ДД.ММ.ГГГГ"
TIME_MISSING = "Укажите время: ДД.ММ.ГГГГ ЧЧ:ММ"
ARCHIVED = "Запись в архиве"
TWO_RECORDS = "Уникальные поля указывают на разные записи"
NO_TITLE = "Не указано название"
MB = 1024 * 1024


# --- разбор разметки (помощник только этого файла) --------------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}
        self.parent = parent
        self.children = []

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                if isinstance(child, Node):
                    collect(child)
                else:
                    parts.append(child)

        collect(self)
        return " ".join("".join(parts).split())


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = Node("#root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in _VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def tree(response) -> Node:
    parser = _Tree()
    parser.feed(response.content.decode("utf-8"))
    return parser.root


def q(scope, tag=None, **attrs) -> list:
    """Потомки `scope` по тегу и атрибутам; имя с дефисом пишется через `_`."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            found.append(node)
    return found


# --- данные и вызовы теста ----------------------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.lists.services.{name}")


def _model(name: str):
    return support.model(f"lists.{name}")


def _setup():
    """Пустой список и правящий его сотрудник."""
    lst = lists.make_list()
    return lst, lists.as_editor(lst)


def _csv(header, rows) -> bytes:
    return lists.csv_of(header, rows)


def _upload_raw(session, lst, content: bytes, name: str = "table.csv"):
    return session.client.post(f"/lists/{lst.pk}/import/", {"file": SimpleUploadedFile(name, content)})


def _job_of(response):
    """Задание по адресу `Location` ответа на загрузку файла (раздел 10.2)."""
    assert response.status_code == 302, f"загрузка отклонена: {response.status_code}"
    found = re.fullmatch(r"/lists/(\d+)/import/(\d+)/", response["Location"])
    assert found, f"адрес {response['Location']!r} не вида /lists/<id>/import/<job>/"
    return _model("ImportJob").objects.get(pk=int(found.group(2)))


def _upload(session, lst, content: bytes, name: str = "table.csv"):
    return _job_of(_upload_raw(session, lst, content, name))


def _post_map(session, lst, job, codes):
    """Сопоставление: `codes` — код поля, `"title"` или `""` (не загружать) по порядку столбцов с нуля."""
    data = {f"map.{number}": code for number, code in enumerate(codes)}
    return session.client.post(f"/lists/{lst.pk}/import/{job.pk}/", data)


def _run(session, lst, header, rows, codes, *, name: str = "table.csv"):
    """Файл → сопоставление → предпросмотр. Возвращает задание после проверки, строки по номеру строки файла и ответ."""
    job = _upload(session, lst, _csv(header, rows), name)
    response = _post_map(session, lst, job, codes)
    assert response.status_code == 200, f"предпросмотр не построен: {response.status_code}"
    job = _model("ImportJob").objects.get(pk=job.pk)
    assert job.state == "preview"
    return SimpleNamespace(job=job, rows={item["row"]: item for item in job.rows}, response=response)


def _reason(run, number: int) -> str:
    return run.rows[number]["reason"]


def _parse(field, raw, viewer):
    return _svc("values").parse(field, raw, viewer=viewer, source="import")


def _counts_of(*models_) -> tuple:
    return tuple(model.objects.count() for model in models_)


def _side_effects() -> tuple:
    return _counts_of(_model("ImportJob"), _model("Record"), support.model("core.StoredFile"), _model("Change"),
                      _model("UniqueValue"))


def _assert_refusal(response, code: str, text: str):
    assert response.status_code == 200
    nodes = q(tree(response), data_error="file", data_code=code)
    assert nodes, f"нет [data-error=file][data-code={code}]"
    assert text in nodes[0].parent.text()


def _snapshot(lst) -> tuple:
    records = _model("Record").objects.filter(list=lst).order_by("number")
    shown = [(r.number, r.title, json.dumps(r.values, sort_keys=True), r.version, r.archived) for r in records]
    lst.refresh_from_db()
    return (shown, lst.next_number, _model("Change").objects.count(), _model("UniqueValue").objects.count())


def _with_parts(content: bytes, extra: dict) -> bytes:
    """Та же книга XLSX с добавленными частями архива."""
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(content)) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for item in source.infolist():
            target.writestr(item, source.read(item))
        for name, data in extra.items():
            target.writestr(name, data)
    return out.getvalue()


def _html_rows(response) -> dict:
    """Строки предпросмотра: номер строки файла -> `tr`."""
    return {int(tr.attrs["data-import-row"]): tr for tr in q(tree(response), "tr", data_import_row=True)}


# --- файл -------------------------------------------------------------------------------------------------------

def test_upload_over_5_mb_over_5000_rows_or_unsupported_format_refused_nothing_created():
    """FR-533, FR-546: файл больше 5 МБ, больше 5 000 строк, не UTF-8 и архив не книги — отказ у поля `file` с
    кодом и текстом, задание не создаётся, записей нет; ровно 5 000 строк принимаются."""
    lst, session = _setup()
    lists.add_field(lst, "string", "Модель")
    before = _side_effects()
    big = _csv(["Название"], [["x" * (5 * MB + 1024)]])
    assert len(big) > 5 * MB
    _assert_refusal(_upload_raw(session, lst, big), "import_too_big", TOO_BIG)
    many = _csv(["Название"], [[f"Запись {n}"] for n in range(5001)])
    _assert_refusal(_upload_raw(session, lst, many), "import_too_many_rows", TOO_MANY)
    not_utf8 = "Название;Модель\nКомпьютер;Тест\n".encode("cp1251")
    _assert_refusal(_upload_raw(session, lst, not_utf8), "import_bad_format", BAD_FORMAT)
    plain_zip = io.BytesIO()
    with zipfile.ZipFile(plain_zip, "w") as archive:
        archive.writestr("readme.txt", "не книга")
    _assert_refusal(_upload_raw(session, lst, plain_zip.getvalue(), "table.xlsx"), "import_bad_format", BAD_FORMAT)
    assert _side_effects() == before
    edge = _csv(["Название"], [[f"Запись {n}"] for n in range(5000)])
    job = _upload(session, lst, edge)
    assert len(job.rows) == 5000


def test_upload_xlsx_bomb_unpacked_size_or_parts_refused_not_500():
    """FR-533: книга, которая в распакованном виде больше 50 МБ, с числом частей больше 100 или с «взрывом» XML,
    отклоняется как неподдерживаемый файл (200, не 500), задание не создаётся."""
    lst, session = _setup()
    before = _side_effects()
    book = lists.xlsx_of(["Название"], [["Запись"]])
    heavy = _with_parts(book, {"xl/pad.bin": b"\0" * (51 * MB)})
    assert len(heavy) < 5 * MB
    many_parts = _with_parts(book, {f"xl/extra/part{n}.xml": "<x/>" for n in range(101)})
    for content in (heavy, many_parts, support_org.xlsx_xml_bomb()):
        _assert_refusal(_upload_raw(session, lst, content, "table.xlsx"), "import_bad_format", BAD_FORMAT)
    assert _side_effects() == before
    ListsError = _svc("errors").ListsError
    with pytest.raises(ListsError) as raised:
        _svc("imports").upload(lst, session.user, name="table.xlsx", content=heavy)
    assert raised.value.code == "import_bad_format"
    assert _side_effects() == before


def test_upload_csv_and_xlsx_create_mapping_job_file_not_stored(protected_root):
    """FR-533: CSV и XLSX разбираются; создаётся задание в состоянии `mapping` с заголовком и строками, автор и
    список записаны, файл нигде не хранится (ни `StoredFile`, ни на диске)."""
    lst, session = _setup()
    lists.add_field(lst, "string", "Модель")
    header = ["Название", "Модель"]
    data = [["Ноутбук", "Lenovo"], ["Принтер", "HP"], ["Сканер", "Epson"]]
    files = support.model("core.StoredFile")
    for name, content, file_format in (("table.csv", _csv(header, data), "csv"),
                                       ("table.xlsx", lists.xlsx_of(header, data), "xlsx")):
        stored_before = files.objects.count()
        job = _upload(session, lst, content, name)
        assert job.list_id == lst.pk
        assert job.created_by_id == session.user.pk
        assert job.state == "mapping"
        assert job.file_format == file_format
        assert job.header == header
        assert len(job.rows) == len(data)
        dumped = json.dumps(job.rows, ensure_ascii=False)
        for row in data:
            assert row[0] in dumped and row[1] in dumped
        assert job.file_name == name
        assert files.objects.count() == stored_before
    assert not [path for path in protected_root.rglob("*") if path.is_file()]
    assert _model("ImportJob").objects.filter(list=lst).count() == 2
    assert _model("Record").objects.filter(list=lst).count() == 0
    page = session.client.get(f"/lists/{lst.pk}/import/{job.pk}/")
    assert page.status_code == 200
    assert len(q(tree(page), "select", data_lists_map_column=True)) == len(header)


# --- сопоставление ----------------------------------------------------------------------------------------------

def test_mapping_matches_columns_by_name_ignoring_case_and_edge_spaces():
    """FR-533: столбцы сопоставляются с видимыми полями по названию без учёта регистра и крайних пробелов;
    «Название» — системное `title`; чужой столбец и столбец скрытого поля не сопоставляются; страница
    сопоставления показывает выбор по умолчанию."""
    lst, session = _setup()
    model = lists.add_field(lst, "string", "Инв. номер")
    cost = lists.add_field(lst, "money", "Стоимость")
    lists.add_field(lst, "string", "Служебное", hidden=True)
    header = ["  НАЗВАНИЕ ", "  инв. номер ", " Стоимость", "Лишний", "служебное"]
    mapping = _svc("imports").auto_mapping(lst, header)
    assert mapping["0"] == "title"
    assert mapping["1"] == model.code
    assert mapping["2"] == cost.code
    assert mapping.get("3", "") == ""
    assert mapping.get("4", "") == "", "столбец скрытого поля сопоставлен"
    job = _upload(session, lst, _csv(header, [["Запись", "ИН-1", "5", "-", "-"]]))
    page = session.client.get(f"/lists/{lst.pk}/import/{job.pk}/")
    assert page.status_code == 200
    selects = {s.attrs["data-lists-map-column"]: s for s in q(tree(page), "select", data_lists_map_column=True)}
    assert sorted(selects) == ["0", "1", "2", "3", "4"]
    for number in selects:
        assert selects[number].attrs["name"] == f"map.{number}"

    def chosen(number):
        picked = [o.attrs.get("value", "") for o in q(selects[number], "option") if "selected" in o.attrs]
        return picked[0] if picked else ""

    assert chosen("0") == "title"
    assert chosen("1") == model.code
    assert chosen("2") == cost.code
    assert chosen("3") == ""
    assert chosen("4") == ""


def test_mapping_manual_change_used_by_preview():
    """FR-533: ручной выбор столбца сопоставления сохраняется в задании и работает в предпросмотре (столбцы
    «Название» и «Инв. номер» поменяны местами, лишний столбец не загружается)."""
    lst, session = _setup()
    inventory = lists.add_field(lst, "string", "Инв. номер", unique=True)
    owner = lists.make_record(lst, "Ноутбук", {inventory.code: "ИН-1"}, created_by=session.user)
    header = ["Название", "Инв. номер", "Примечание"]
    rows = [["ИН-1", "Принтер", "не число"], ["ИН-2", "Сканер", "ещё"]]
    auto = _svc("imports").auto_mapping(lst, header)
    assert auto["0"] == "title" and auto["1"] == inventory.code
    run = _run(session, lst, header, rows, [inventory.code, "title", ""])
    assert run.job.mapping["0"] == inventory.code
    assert run.job.mapping["1"] == "title"
    assert not run.job.mapping.get("2")
    assert run.rows[2]["result"] == "will_update"
    assert run.rows[2]["number"] == owner.number
    assert run.rows[3]["result"] == "will_create"
    assert run.rows[3]["number"] is None


def test_mapping_file_field_not_offered_and_not_accepted():
    """FR-533: поля «файл» в выборе сопоставления нет, столбец с его названием не сопоставляется автоматически, а
    выбор его кода в запросе не принимается (в задании сопоставления нет, файлов не создано)."""
    lst, session = _setup()
    model = lists.add_field(lst, "string", "Модель")
    scan = lists.add_field(lst, "file", "Скан", multiple=True)
    header = ["Название", "Модель", "Скан"]
    rows = [["Ноутбук", "Lenovo", "scan.pdf"]]
    assert scan.code not in _svc("imports").auto_mapping(lst, header).values()
    job = _upload(session, lst, _csv(header, rows))
    page = session.client.get(f"/lists/{lst.pk}/import/{job.pk}/")
    assert page.status_code == 200
    selects = q(tree(page), "select", data_lists_map_column=True)
    assert len(selects) == 3
    for select in selects:
        values = [o.attrs.get("value", "") for o in q(select, "option")]
        assert scan.code not in values
        assert model.code in values and "title" in values
        assert not [o for o in q(select, "option") if o.text() == "Скан"]
    response = _post_map(session, lst, job, ["title", model.code, scan.code])
    assert response.status_code == 200
    job = _model("ImportJob").objects.get(pk=job.pk)
    assert scan.code not in job.mapping.values()
    assert _model("RecordFile").objects.count() == 0
    assert _model("Record").objects.filter(list=lst).count() == 0


# --- задание: чужое, старое, право ----------------------------------------------------------------------------

def _job_urls(lst, job):
    base = f"/lists/{lst.pk}/import/{job.pk}/"
    return [("get", base, {}), ("post", base, {"map.0": "title"}), ("post", base + "confirm/", {})]


def _call(client, method, url, data):
    return client.get(url) if method == "get" else client.post(url, data)


def test_job_of_other_author_or_other_list_returns_404():
    """FR-514, FR-533: задание другого автора, другого списка и несуществующее — 404 на всех шагах, без данных
    задания в теле; свой — 200."""
    lst, session = _setup()
    marker = "Приметный заголовок"
    job = _upload(session, lst, _csv(["Название", marker], [["Запись", "x"]]))
    for method, url, data in _job_urls(lst, job):
        if method == "get":
            own = _call(session.client, method, url, data)
            assert own.status_code == 200
            assert marker in own.content.decode("utf-8")
    other_author = lists.as_editor(lst)
    for method, url, data in _job_urls(lst, job):
        response = _call(other_author.client, method, url, data)
        assert response.status_code == 404, (method, url)
        assert marker not in response.content.decode("utf-8")
    other_list = lists.make_list()
    lists.grant_list(other_list, session.user.roles.first(), "edit")
    for method, url, data in _job_urls(other_list, job):
        response = _call(session.client, method, url, data)
        assert response.status_code == 404, (method, url)
        assert marker not in response.content.decode("utf-8")
    ghost = SimpleNamespace(pk=_model("ImportJob").objects.order_by("-pk").first().pk + 1000)
    for method, url, data in _job_urls(lst, ghost):
        assert _call(session.client, method, url, data).status_code == 404, (method, url)
    from django.http import Http404

    imports = _svc("imports")
    assert imports.get_job(session.user, lst, job.pk).pk == job.pk
    for user, target in ((other_author.user, lst), (session.user, other_list)):
        with pytest.raises(Http404):
            imports.get_job(user, target, job.pk)
    with pytest.raises(Http404):
        imports.get_job(session.user, lst, ghost.pk)


def test_job_older_than_one_day_is_404_and_edit_right_rechecked_on_each_step():
    """FR-514, FR-533: задание старше суток — 404 на каждом шаге (страница, сопоставление, подтверждение,
    `get_job`), моложе суток — 200; право «правит» проверяется заново: уровень «читает» — 403, права нет — 404."""
    from datetime import timedelta

    from django.http import Http404
    from django.utils import timezone

    lst, session = _setup()
    header, rows = ["Название"], [["Запись"]]
    jobs = _model("ImportJob")
    fresh = _upload(session, lst, _csv(header, rows))
    jobs.objects.filter(pk=fresh.pk).update(created_at=timezone.now() - timedelta(hours=23, minutes=59))
    assert session.client.get(f"/lists/{lst.pk}/import/{fresh.pk}/").status_code == 200
    assert _post_map(session, lst, fresh, ["title"]).status_code == 200
    old = _upload(session, lst, _csv(header, rows))
    jobs.objects.filter(pk=old.pk).update(created_at=timezone.now() - timedelta(days=1, minutes=1))
    for method, url, data in _job_urls(lst, old):
        assert _call(session.client, method, url, data).status_code == 404, (method, url)
    with pytest.raises(Http404):
        _svc("imports").get_job(session.user, lst, old.pk)
    assert jobs.objects.get(pk=old.pk).state == "mapping"
    assert _model("Record").objects.filter(list=lst).count() == 0
    # право правки проверяется на каждом шаге заново
    job = _upload(session, lst, _csv(header, rows))
    access = _model("Access").objects.get(list=lst, level="edit")
    access.level = "read"
    access.save(update_fields=["level"])
    for method, url, data in _job_urls(lst, job):
        assert _call(session.client, method, url, data).status_code == 403, (method, url)
    access.level = "edit"
    access.save(update_fields=["level"])
    assert session.client.get(f"/lists/{lst.pk}/import/{job.pk}/").status_code == 200
    access.delete()
    for method, url, data in _job_urls(lst, job):
        assert _call(session.client, method, url, data).status_code == 404, (method, url)
    assert _model("Record").objects.filter(list=lst).count() == 0


def test_reader_has_no_import_button_post_403_non_reader_404():
    """FR-514, FR-533: у читающего нет кнопки «Загрузить из таблицы», прямое обращение — 403 и ничего не создано;
    у правящего кнопка есть; у не читающего список — 404."""
    lst, editor = _setup()
    reader = lists.as_reader(lst)
    stranger = support.make_employee()
    stranger_client = support.logged_in(stranger)
    editor_page = editor.client.get(f"/lists/{lst.pk}/")
    assert editor_page.status_code == 200
    assert q(tree(editor_page), "a", data_action="import"), "у правящего нет кнопки загрузки"
    reader_page = reader.client.get(f"/lists/{lst.pk}/")
    assert reader_page.status_code == 200
    assert not q(tree(reader_page), data_action="import")
    before = _side_effects()
    content = _csv(["Название"], [["Запись"]])
    assert reader.client.get(f"/lists/{lst.pk}/import/").status_code == 403
    assert _upload_raw(reader, lst, content).status_code == 403
    assert stranger_client.get(f"/lists/{lst.pk}/import/").status_code == 404
    assert stranger_client.post(
        f"/lists/{lst.pk}/import/", {"file": SimpleUploadedFile("table.csv", content)}).status_code == 404
    assert _side_effects() == before


# --- значения по типам (правила загрузки, FR-533) -------------------------------------------------------------

def test_preview_employee_by_email_or_unique_full_name_among_active():
    """FR-533: сотрудник — по адресу почты или однозначному ФИО среди действующих (уволенный однофамилец
    однозначности не мешает); значение — id сотрудника; строки предпросмотра без ошибок."""
    lst, session = _setup()
    person = lists.add_field(lst, "person", "Сотрудник")
    ivanov = support.make_employee(full_name="Иванов Иван Иванович", email=lists.email_of("ivanov"))
    support.make_employee(full_name="Сидоров Сидор Сидорович", state="dismissed", email=lists.email_of("sidorov0"))
    sidorov = support.make_employee(full_name="Сидоров Сидор Сидорович", email=lists.email_of("sidorov1"))
    assert _parse(person, ivanov.email, session.user).value == [ivanov.pk]
    assert _parse(person, ivanov.full_name, session.user).value == [ivanov.pk]
    assert _parse(person, sidorov.full_name, session.user).value == [sidorov.pk]
    assert _parse(person, sidorov.email, session.user).error is None
    cells = [ivanov.email, ivanov.full_name, sidorov.full_name]
    run = _run(session, lst, ["Название", "Сотрудник"], [[f"Запись {n}", cell] for n, cell in enumerate(cells)],
               ["title", person.code])
    assert [run.rows[n]["result"] for n in (2, 3, 4)] == ["will_create"] * 3
    assert [run.rows[n]["reason"] for n in (2, 3, 4)] == [""] * 3


def test_preview_ambiguous_name_unknown_email_or_dismissed_employee_is_row_error():
    """FR-533: неоднозначное ФИО, неизвестная почта и ФИО, уволенный, заблокированный и приглашённый сотрудник —
    ошибка строки с причиной «<Поле>: …» и номером строки; значение не принимается."""
    lst, session = _setup()
    person = lists.add_field(lst, "person", "Сотрудник")
    first = support.make_employee(full_name="Кузнецов Кузьма Кузьмич", email=lists.email_of("kuznetsov1"))
    support.make_employee(full_name="Кузнецов Кузьма Кузьмич", email=lists.email_of("kuznetsov2"))
    dismissed = support.make_employee(full_name="Уволенов Уволен Уволенович", state="dismissed",
                                      email=lists.email_of("dismissed"))
    blocked = support.make_employee(full_name="Блокиров Блок Блокович", state="blocked",
                                    email=lists.email_of("blocked"))
    invited = support.make_employee(full_name="Приглашёнов Приглаш Приглашёнович", state="invited",
                                    email=lists.email_of("invited"))
    unknown_email = lists.email_of("nobody")
    ambiguous = _parse(person, first.full_name, session.user)
    assert ambiguous.value is None
    assert ambiguous.error.code == "import_ambiguous"
    assert first.full_name in ambiguous.error.message
    not_found = _parse(person, unknown_email, session.user)
    assert not_found.value is None
    assert not_found.error.code == "import_not_found"
    assert unknown_email in not_found.error.message
    assert _parse(person, "Никто Никтович", session.user).error.code == "import_not_found"
    cells = [first.full_name, unknown_email, "Никто Никтович", dismissed.email, dismissed.full_name,
             blocked.email, invited.email]
    for user in (dismissed, blocked, invited):
        parsed = _parse(person, user.email, session.user)
        assert parsed.value is None and parsed.error is not None
    run = _run(session, lst, ["Название", "Сотрудник"], [[f"Запись {n}", cell] for n, cell in enumerate(cells)],
               ["title", person.code])
    for number in range(2, 2 + len(cells)):
        assert run.rows[number]["result"] == "error", number
        assert run.rows[number]["number"] is None
        assert run.rows[number]["reason"].startswith("Сотрудник"), run.rows[number]["reason"]
    assert "Неоднозначно: " + first.full_name in _reason(run, 2)
    assert "Не найдено: " + unknown_email in _reason(run, 3)
    shown = _html_rows(run.response)
    assert shown[2].attrs["data-result"] == "error"
    assert "Неоднозначно" in q(shown[2], data_field="reason")[0].text()


def test_preview_unit_by_name_or_path_ambiguous_is_row_error():
    """FR-533: подразделение — по названию или пути (названия от корня через « / »); одинаковое название у двух
    узлов — «Неоднозначно», путь однозначен; неизвестное — «Не найдено»."""
    lst, session = _setup()
    unit_field = lists.add_field(lst, "unit", "Подразделение")
    root = support_org.root_unit()
    office = support_org.make_unit("Офис Север")
    south = support_org.make_unit("Офис Юг")
    unique = support_org.make_unit("Бухгалтерия Особая", parent=office)
    store_north = support_org.make_unit("Склад Общий", parent=office)
    store_south = support_org.make_unit("Склад Общий", parent=south)
    by_name = _parse(unit_field, unique.name, session.user)
    assert by_name.value == [unique.pk] and by_name.error is None
    path_unique = " / ".join([root.name, office.name, unique.name])
    assert _parse(unit_field, path_unique, session.user).value == [unique.pk]
    path_north = " / ".join([root.name, office.name, store_north.name])
    path_south = " / ".join([root.name, south.name, store_south.name])
    assert _parse(unit_field, path_north, session.user).value == [store_north.pk]
    assert _parse(unit_field, path_south, session.user).value == [store_south.pk]
    ambiguous = _parse(unit_field, "Склад Общий", session.user)
    assert ambiguous.value is None and ambiguous.error.code == "import_ambiguous"
    unknown = _parse(unit_field, "Нет такого узла", session.user)
    assert unknown.value is None and unknown.error.code == "import_not_found"
    cells = [unique.name, path_north, path_south, "Склад Общий", "Нет такого узла"]
    run = _run(session, lst, ["Название", "Подразделение"], [[f"Запись {n}", cell] for n, cell in enumerate(cells)],
               ["title", unit_field.code])
    assert [run.rows[n]["result"] for n in (2, 3, 4, 5, 6)] == ["will_create"] * 3 + ["error"] * 2
    assert "Неоднозначно: Склад Общий" in _reason(run, 5)
    assert "Не найдено: Нет такого узла" in _reason(run, 6)


def test_preview_choice_by_name_unknown_or_archived_value_is_row_error():
    """FR-533: значение списка значений — по названию; неизвестное и значение из архива значений — ошибка строки;
    несколько значений через «;» — все по названиям."""
    lst, session = _setup()
    state = lists.add_field(lst, "choice", "Состояние", choices=("Новый", "В работе", "Старый"))
    tags = lists.add_field(lst, "choice", "Метки", multiple=True, choices=("Срочно", "Офис"))
    _model("Choice").objects.filter(field=state, title="Старый").update(archived=True)
    work = lists.choice_id(state, "В работе")
    parsed = _parse(state, "В работе", session.user)
    assert parsed.value == [work] and parsed.error is None
    unknown = _parse(state, "Нет такого", session.user)
    assert unknown.value is None and unknown.error.code == "import_not_found"
    archived = _parse(state, "Старый", session.user)
    assert archived.value is None and archived.error.code == "value_unavailable"
    many = _parse(tags, "Срочно; Офис", session.user)
    assert many.value == [lists.choice_id(tags, "Срочно"), lists.choice_id(tags, "Офис")]
    assert _parse(tags, "Срочно; Нет такого", session.user).error is not None
    cells = [["Запись 1", "В работе", "Срочно; Офис"], ["Запись 2", "Нет такого", ""], ["Запись 3", "Старый", ""],
             ["Запись 4", "", "Срочно; Нет такого"]]
    run = _run(session, lst, ["Название", "Состояние", "Метки"], cells, ["title", state.code, tags.code])
    assert [run.rows[n]["result"] for n in (2, 3, 4, 5)] == ["will_create", "error", "error", "error"]
    assert run.rows[3]["reason"].startswith("Состояние") and "Не найдено: Нет такого" in _reason(run, 3)
    assert run.rows[4]["reason"].startswith("Состояние")
    assert run.rows[5]["reason"].startswith("Метки")


def test_preview_record_link_by_name_or_number_among_active_records_of_readable_target():
    """FR-533, FR-514: запись другого списка — по названию или номеру среди записей не в архиве целевого списка,
    который читает загружающий; одинаковое название — «Неоднозначно»; архивная запись, неизвестный номер и запись
    нечитаемого списка — ошибка строки."""
    lst, session = _setup()
    target = lists.make_list("Оборудование для связи")
    hidden_target = lists.make_list("Закрытый список")
    lists.grant_list(target, session.user.roles.first(), "read")
    link = lists.add_field(lst, "record", "Устройство", target=target)
    closed_link = lists.add_field(lst, "record", "Закрытое", target=hidden_target)
    author = session.user
    laptop = lists.make_record(target, "Ноутбук Lenovo", created_by=author)
    lists.make_record(target, "Двойник", created_by=author)
    lists.make_record(target, "Двойник", created_by=author)
    old = lists.make_record(target, "Старый ноутбук", archived=True, created_by=author)
    closed = lists.make_record(hidden_target, "Секретная запись", created_by=author)
    by_name = _parse(link, "Ноутбук Lenovo", author)
    assert by_name.value == [laptop.pk] and by_name.error is None
    by_number = _parse(link, str(laptop.number), author)
    assert by_number.value == [laptop.pk] and by_number.error is None
    assert _parse(link, "Двойник", author).error.code == "import_ambiguous"
    assert _parse(link, "Старый ноутбук", author).value is None
    assert _parse(link, str(old.number), author).value is None
    assert _parse(link, "999", author).value is None
    assert _parse(link, "Нет такой", author).error.code == "import_not_found"
    assert _parse(closed_link, closed.title, author).value is None
    assert _parse(closed_link, str(closed.number), author).value is None
    header = ["Название", "Устройство", "Закрытое"]
    rows = [["Запись 1", "Ноутбук Lenovo", ""], ["Запись 2", str(laptop.number), ""], ["Запись 3", "Двойник", ""],
            ["Запись 4", "Старый ноутбук", ""], ["Запись 5", "", closed.title], ["Запись 6", "", str(closed.number)]]
    run = _run(session, lst, header, rows, ["title", link.code, closed_link.code])
    assert [run.rows[n]["result"] for n in range(2, 8)] == ["will_create", "will_create"] + ["error"] * 4
    assert "Неоднозначно: Двойник" in _reason(run, 4)
    assert run.rows[5]["reason"].startswith("Устройство")
    assert run.rows[6]["reason"].startswith("Закрытое")


def test_preview_date_and_datetime_formats_date_only_datetime_error_with_hint():
    """FR-533: дата — ДД.ММ.ГГГГ или ГГГГ-ММ-ДД; дата и время — «ДД.ММ.ГГГГ ЧЧ:ММ» по Москве (в хранении UTC);
    дата без времени в поле «дата и время» — ошибка с подсказкой «Укажите время: ДД.ММ.ГГГГ ЧЧ:ММ»."""
    lst, session = _setup()
    day = lists.add_field(lst, "date", "Куплено")
    moment = lists.add_field(lst, "datetime", "Осмотр")
    viewer = session.user
    assert _parse(day, "25.10.2026", viewer).value == "2026-10-25"
    assert _parse(day, "2026-10-25", viewer).value == "2026-10-25"
    assert _parse(day, "31.02.2026", viewer).error.code == "bad_date"
    assert _parse(day, "2026/10/25", viewer).error.code == "bad_date"
    assert _parse(moment, "25.10.2026 14:30", viewer).value == "2026-10-25T11:30:00Z"
    assert _parse(moment, "01.02.2026 00:15", viewer).value == "2026-01-31T21:15:00Z"
    only_date = _parse(moment, "25.10.2026", viewer)
    assert only_date.value is None and only_date.error.code == "import_time_missing"
    assert TIME_MISSING in only_date.error.message
    assert _parse(moment, "25.10.2026 25:61", viewer).error.code == "bad_datetime"
    rows = [["Запись 1", "25.10.2026", "25.10.2026 14:30"], ["Запись 2", "2026-10-25", "01.02.2026 00:15"],
            ["Запись 3", "25.10.2026", "25.10.2026"], ["Запись 4", "31.02.2026", ""]]
    run = _run(session, lst, ["Название", "Куплено", "Осмотр"], rows, ["title", day.code, moment.code])
    assert [run.rows[n]["result"] for n in (2, 3, 4, 5)] == ["will_create", "will_create", "error", "error"]
    assert run.rows[4]["reason"].startswith("Осмотр") and TIME_MISSING in _reason(run, 4)
    assert run.rows[5]["reason"].startswith("Куплено") and BAD_DATE in _reason(run, 5)
    shown = _html_rows(run.response)
    assert TIME_MISSING in q(shown[4], data_field="reason")[0].text()


def test_preview_number_money_dot_or_comma_bool_and_multiple_values():
    """FR-533: число и деньги — с точкой или запятой (хранение раздела 2.3); да/нет — «Да» или «Нет» («Нет» и
    пусто — значения нет); несколько значений — через «;»; прочее в числе и да/нет — ошибка строки."""
    lst, session = _setup()
    count = lists.add_field(lst, "number", "Количество")
    price = lists.add_field(lst, "money", "Цена")
    flag = lists.add_field(lst, "bool", "На гарантии")
    people = lists.add_field(lst, "person", "Ответственные", multiple=True)
    viewer = session.user
    assert _parse(count, "12,5", viewer).value == "12.5"
    assert _parse(count, "12.5", viewer).value == "12.5"
    assert _parse(count, "100.0", viewer).value == "100"
    assert _parse(count, "abc", viewer).error.code == "bad_number"
    assert _parse(price, "1234,5", viewer).value == "1234.50"
    assert _parse(price, "1234.5", viewer).value == "1234.50"
    assert _parse(price, "1234", viewer).value == "1234.00"
    assert _parse(price, "много", viewer).error.code == "bad_number"
    assert _parse(flag, "Да", viewer).value is True
    for raw in ("Нет", ""):
        parsed = _parse(flag, raw, viewer)
        assert parsed.value is None and parsed.error is None
    assert _parse(flag, "Возможно", viewer).error is not None
    first = support.make_employee(full_name="Первов Пётр Петрович", email=lists.email_of("first"))
    second = support.make_employee(full_name="Второв Иван Петрович", email=lists.email_of("second"))
    several = _parse(people, f"{first.email}; {second.full_name}", viewer)
    assert several.value == [first.pk, second.pk] and several.error is None
    assert _parse(people, f"{first.email};{lists.email_of('nobody')}", viewer).error.code == "import_not_found"
    rows = [["Запись 1", "12,5", "1234,5", "Да", f"{first.email}; {second.email}"],
            ["Запись 2", "100.0", "1 234", "Нет", ""], ["Запись 3", "abc", "10", "", ""],
            ["Запись 4", "1", "10", "Возможно", ""]]
    run = _run(session, lst, ["Название", "Количество", "Цена", "На гарантии", "Ответственные"], rows,
               ["title", count.code, price.code, flag.code, people.code])
    assert run.rows[2]["result"] == "will_create"
    assert run.rows[3]["result"] in ("will_create", "error")
    assert run.rows[4]["result"] == "error" and run.rows[4]["reason"].startswith("Количество")
    assert BAD_NUMBER in _reason(run, 4)
    assert run.rows[5]["result"] == "error" and run.rows[5]["reason"].startswith("На гарантии")


def test_preview_apostrophe_before_formula_sign_stripped():
    """FR-533: одиночный апостроф перед знаком `=`, `+`, `-`, `@` снимается (обратная сторона защиты выгрузки):
    строка совпадает с записью, у которой значение без апострофа; апостроф перед другим знаком остаётся."""
    lst, session = _setup()
    code = lists.add_field(lst, "string", "Код", unique=True)
    amount = lists.add_field(lst, "number", "Остаток", unique=True)
    author = session.user
    equals = lists.make_record(lst, "Первая", {code.code: "=1+1"}, created_by=author)
    plus = lists.make_record(lst, "Вторая", {code.code: "+7 999"}, created_by=author)
    at = lists.make_record(lst, "Третья", {code.code: "@mention"}, created_by=author)
    minus = lists.make_record(lst, "Четвёртая", {code.code: "-q"}, created_by=author)
    quoted = lists.make_record(lst, "Пятая", {code.code: "'abc"}, created_by=author)
    plain = lists.make_record(lst, "Шестая", {code.code: "abc"}, created_by=author)
    negative = lists.make_record(lst, "Седьмая", {amount.code: "-5"}, created_by=author)
    cells = ["'=1+1", "'+7 999", "'@mention", "'-q", "'abc", "abc", "'novel"]
    run = _run(session, lst, ["Название", "Код"], [[f"Строка {n}", cell] for n, cell in enumerate(cells)],
               ["title", code.code])
    expected = [equals, plus, at, minus, quoted, plain]
    for position, record in enumerate(expected, start=2):
        assert run.rows[position]["result"] == "will_update", (position, run.rows[position])
        assert run.rows[position]["number"] == record.number, position
    assert run.rows[8]["result"] == "will_create"
    other = _run(session, lst, ["Название", "Остаток"], [["Строка", "'-5"]], ["title", amount.code])
    assert other.rows[2]["result"] == "will_update"
    assert other.rows[2]["number"] == negative.number


# --- итог строки (FR-534) ---------------------------------------------------------------------------------------

def test_preview_unique_match_will_update_with_record_number_else_will_create():
    """FR-534: сопоставлено уникальное поле и значение есть у записи не в архиве — `will_update` с номером записи
    (сравнение по нормализованному значению); иначе, в том числе при пустом значении и несопоставленном поле, —
    `will_create`."""
    lst, session = _setup()
    inventory = lists.add_field(lst, "string", "Инв. номер", unique=True)
    quantity = lists.add_field(lst, "number", "Номер партии", unique=True)
    author = session.user
    one = lists.make_record(lst, "Ноутбук", {inventory.code: "ИН-1", quantity.code: "100"}, created_by=author)
    two = lists.make_record(lst, "Принтер", {inventory.code: "ИН-2"}, created_by=author)
    header = ["Название", "Инв. номер", "Номер партии"]
    rows = [["Ноутбук", " ин-1 ", ""], ["Другой", "ИН-3", ""], ["Принтер", "ИН-2", "7"], ["Пусто", "", ""],
            ["Партия", "", "100,0"], ["Совпали", "ИН-1", "100"]]
    run = _run(session, lst, header, rows, ["title", inventory.code, quantity.code])
    assert [run.rows[n]["result"] for n in range(2, 8)] == [
        "will_update", "will_create", "will_update", "will_create", "will_update", "will_update"]
    assert run.rows[2]["number"] == one.number
    assert run.rows[3]["number"] is None
    assert run.rows[4]["number"] == two.number
    assert run.rows[5]["number"] is None
    assert run.rows[6]["number"] == one.number
    assert run.rows[7]["number"] == one.number
    shown = _html_rows(run.response)
    assert shown[2].attrs["data-result"] == "will_update"
    assert str(one.number) in q(shown[2], data_field="number")[0].text()
    assert shown[3].attrs["data-result"] == "will_create"
    created_number = q(shown[3], data_field="number")
    assert not created_number or not re.search(r"\d", created_number[0].text())
    unmapped = _run(session, lst, header, [["Ноутбук", "ИН-1", ""]], ["title", "", ""])
    assert unmapped.rows[2]["result"] == "will_create"
    assert unmapped.rows[2]["number"] is None


def test_preview_archived_match_or_two_unique_fields_on_different_records_is_row_error():
    """FR-534: значение есть у записи в архиве — ошибка «Запись в архиве»; два уникальных поля указывают на разные
    записи — ошибка «Уникальные поля указывают на разные записи»; на одну запись — `will_update`."""
    lst, session = _setup()
    first = lists.add_field(lst, "string", "Код", unique=True)
    second = lists.add_field(lst, "number", "Номер", unique=True)
    author = session.user
    a = lists.make_record(lst, "А", {first.code: "A1", second.code: "1"}, created_by=author)
    lists.make_record(lst, "Б", {first.code: "B1", second.code: "2"}, created_by=author)
    lists.make_record(lst, "В", {first.code: "C1", second.code: "3"}, archived=True, created_by=author)
    rows = [["Строка 1", "A1", "2"], ["Строка 2", "A1", "1"], ["Строка 3", "C1", "9"], ["Строка 4", "A1", ""],
            ["Строка 5", "N1", "3"], ["Строка 6", "A1", "7"]]
    run = _run(session, lst, ["Название", "Код", "Номер"], rows, ["title", first.code, second.code])
    assert run.rows[2]["result"] == "error" and TWO_RECORDS in _reason(run, 2)
    assert run.rows[3]["result"] == "will_update" and run.rows[3]["number"] == a.number
    assert run.rows[4]["result"] == "error" and ARCHIVED in _reason(run, 4)
    assert run.rows[5]["result"] == "will_update" and run.rows[5]["number"] == a.number
    assert run.rows[6]["result"] == "error" and ARCHIVED in _reason(run, 6)
    assert run.rows[7]["result"] == "will_update" and run.rows[7]["number"] == a.number
    shown = _html_rows(run.response)
    assert TWO_RECORDS in q(shown[2], data_field="reason")[0].text()
    assert ARCHIVED in q(shown[4], data_field="reason")[0].text()


def test_preview_repeated_unique_value_in_later_row_error_with_row_number():
    """FR-534, FR-546: повтор нормализованного уникального значения в более поздней строке файла — ошибка
    «Значение повторяется в строке N» (N — номер строки файла); первая строка и пустые значения не повторы."""
    lst, session = _setup()
    code = lists.add_field(lst, "string", "Код", unique=True)
    amount = lists.add_field(lst, "number", "Номер", unique=True)
    rows = [["Строка 1", "ИН-5", "100"], ["Строка 2", "ин-5", ""], ["Строка 3", "ИН-6", ""], ["Строка 4", "", ""],
            ["Строка 5", "", ""], ["Строка 6", "ИН-7", "100,0"]]
    run = _run(session, lst, ["Название", "Код", "Номер"], rows, ["title", code.code, amount.code])
    assert run.rows[2]["result"] == "will_create"
    assert run.rows[3]["result"] == "error"
    assert "Значение повторяется в строке 2" in _reason(run, 3)
    assert run.rows[4]["result"] == "will_create"
    assert run.rows[5]["result"] == "will_create"
    assert run.rows[6]["result"] == "will_create"
    assert run.rows[7]["result"] == "error"
    assert "Значение повторяется в строке 2" in _reason(run, 7)
    shown = _html_rows(run.response)
    assert shown[3].attrs["data-result"] == "error"
    assert "Значение повторяется в строке 2" in q(shown[3], data_field="reason")[0].text()


def test_file_without_title_column_updates_by_unique_field_unmatched_row_has_no_title_error():
    """FR-534, FR-546: файл без столбца «Название» обновляет записи по уникальному полю; строка без совпадения
    (и с пустым уникальным значением) — ошибка «Не указано название»."""
    lst, session = _setup()
    code = lists.add_field(lst, "string", "Код", unique=True)
    lists.add_field(lst, "string", "Примечание")
    owner = lists.make_record(lst, "Ноутбук", {code.code: "ИН-1"}, created_by=session.user)
    run = _run(session, lst, ["Код", "Примечание"], [["ИН-1", "новое"], ["ИН-9", "нет такой"], ["", "пусто"]],
               [code.code, ""])
    assert run.rows[2]["result"] == "will_update" and run.rows[2]["number"] == owner.number
    assert run.rows[3]["result"] == "error" and NO_TITLE in _reason(run, 3)
    assert run.rows[4]["result"] == "error" and NO_TITLE in _reason(run, 4)
    shown = _html_rows(run.response)
    assert NO_TITLE in q(shown[3], data_field="reason")[0].text()
    assert shown[2].attrs["data-result"] == "will_update"


def test_preview_each_record_rule_violation_has_reason_and_row_number():
    """FR-533, FR-534: каждое нарушение правил записи (обязательное, число, дата, предел длины, переносы строк) —
    ошибка строки с причиной «<Поле>: <текст>» у нужной строки файла; правильные строки между ними — без ошибок."""
    lst, session = _setup()
    model = lists.add_field(lst, "string", "Модель", required=True)
    quantity = lists.add_field(lst, "number", "Количество")
    bought = lists.add_field(lst, "date", "Куплено")
    serial = lists.add_field(lst, "string", "Серийный")
    codes = ["title", model.code, quantity.code, bought.code, serial.code]
    rows = [
        ["Строка 1", "Модель", "1", "25.10.2026", "S1"],
        ["Строка 2", "", "1", "25.10.2026", "S2"],
        ["Строка 3", "Модель", "2", "25.10.2026", "S3"],
        ["Строка 4", "Модель", "abc", "25.10.2026", "S4"],
        ["Строка 5", "Модель", "3", "31.02.2026", "S5"],
        ["Строка 6", "Модель", "4", "25.10.2026", "я" * 501],
        ["Строка 7", "две\nстроки", "5", "25.10.2026", "S7"],
    ]
    run = _run(session, lst, ["Название", "Модель", "Количество", "Куплено", "Серийный"], rows, codes)
    wanted = {3: ("Модель", REQUIRED), 5: ("Количество", BAD_NUMBER), 6: ("Куплено", BAD_DATE),
              7: ("Серийный", "Предел: 500 знаков"), 8: ("Модель", "Без переносов строк")}
    for number in (2, 4):
        assert run.rows[number]["result"] == "will_create", number
        assert run.rows[number]["reason"] == ""
    shown = _html_rows(run.response)
    for number, (name, text) in wanted.items():
        assert run.rows[number]["result"] == "error", number
        assert f"{name}: {text}" in _reason(run, number), (number, _reason(run, number))
        assert shown[number].attrs["data-result"] == "error"
        assert text in q(shown[number], data_field="reason")[0].text()
        assert run.rows[number]["number"] is None
    assert shown[2].attrs["data-result"] == "will_create"


def test_preview_shows_counts_will_create_will_update_with_errors():
    """FR-534: предпросмотр показывает «будет создано / будет обновлено / с ошибками»: `imports.counts` и
    счётчики страницы совпадают с числом строк по итогам; кнопка подтверждения есть."""
    lst, session = _setup()
    code = lists.add_field(lst, "string", "Код", unique=True)
    lists.add_field(lst, "number", "Количество")
    author = session.user
    lists.make_record(lst, "Старая", {code.code: "ИН-1"}, created_by=author)
    rows = [["Новая 1", "ИН-10", "1"], ["Новая 2", "ИН-11", "2"], ["Старая", "ИН-1", "3"], ["Плохая 1", "ИН-12", "x"],
            ["Плохая 2", "ИН-13", "y"]]
    run = _run(session, lst, ["Название", "Код", "Количество"], rows, ["title", code.code, "f2"])
    assert _svc("imports").counts(run.job) == {"will_create": 2, "will_update": 1, "error": 2}
    root = tree(run.response)
    for name, expected in (("will_create", 2), ("will_update", 1), ("error", 2)):
        nodes = q(root, data_import_count=name)
        assert len(nodes) == 1, name
        assert re.findall(r"\d+", nodes[0].text()) == [str(expected)], (name, nodes[0].text())
    assert q(root, "button", data_action="import-confirm")
    assert len(_html_rows(run.response)) == len(rows)


def test_preview_changes_nothing_in_database_before_confirm():
    """FR-534: до подтверждения в базе ничего не меняется: записи, значения, версии, счётчик номеров, строки
    `UniqueValue` и история прежние, даже когда в файле есть строки на создание и на обновление."""
    lst, session = _setup()
    code = lists.add_field(lst, "string", "Код", unique=True)
    lists.add_field(lst, "string", "Примечание")
    author = session.user
    lists.make_record(lst, "Ноутбук", {code.code: "ИН-1", "f2": "было"}, created_by=author)
    lists.make_record(lst, "Архивный", {code.code: "ИН-2"}, archived=True, created_by=author)
    before = _snapshot(lst)
    rows = [["Ноутбук", "ИН-1", "стало"], ["Новый", "ИН-3", "новая"], ["Архивный", "ИН-2", "x"]]
    header = ["Название", "Код", "Примечание"]
    run = _run(session, lst, header, rows, ["title", code.code, "f2"])
    assert [run.rows[n]["result"] for n in (2, 3, 4)] == ["will_update", "will_create", "error"]
    assert _snapshot(lst) == before
    job = _upload(session, lst, _csv(header, rows))
    _svc("imports").preview(job, {"0": "title", "1": code.code, "2": "f2"}, session.user)
    assert _snapshot(lst) == before
    job = _model("ImportJob").objects.get(pk=job.pk)
    assert job.state == "preview"
    assert [item["result"] for item in job.rows] == ["will_update", "will_create", "error"]


def test_preview_5000_rows_within_15_seconds():
    """NFR-504: предпросмотр 5 000 строк (1 000 из них обновляют имеющиеся записи) строится не дольше 15 секунд,
    итог по строкам верен."""
    lst, session = _setup()
    code = lists.add_field(lst, "string", "Инв. номер", unique=True)
    author = session.user
    Record, UniqueValue = _model("Record"), _model("UniqueValue")
    from django.utils import timezone

    now = timezone.now()
    existing = [Record(list=lst, number=n + 1, title=f"Запись {n}", values={code.code: f"ИН-{n}"}, version=1,
                       created_at=now, created_by=author, updated_at=now, updated_by=author) for n in range(1000)]
    Record.objects.bulk_create(existing)
    saved = {r.number: r for r in Record.objects.filter(list=lst)}
    UniqueValue.objects.bulk_create([
        UniqueValue(list=lst, field=code, norm_value=f"ин-{n}", record=saved[n + 1]) for n in range(1000)])
    lst.next_number = 1001
    lst.save(update_fields=["next_number"])
    rows = [[f"Запись {n}", f"ИН-{n}"] for n in range(5000)]
    job = _upload(session, lst, _csv(["Название", "Инв. номер"], rows))
    assert len(job.rows) == 5000
    started = time.perf_counter()
    result = _svc("imports").preview(job, {"0": "title", "1": code.code}, session.user)
    elapsed = time.perf_counter() - started
    assert elapsed < 15, f"предпросмотр 5 000 строк: {elapsed:.1f} с"
    job = _model("ImportJob").objects.get(pk=job.pk)
    assert job.state == "preview"
    assert _svc("imports").counts(job) == {"will_create": 4000, "will_update": 1000, "error": 0}
    assert result is not None
    assert Record.objects.filter(list=lst).count() == 1000
