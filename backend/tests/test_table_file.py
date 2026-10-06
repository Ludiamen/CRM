"""T-3137: общее чтение таблиц в ядре `apps.core.services.table_file` (FR-262, FR-265). Сценарии загрузки таблицы
заявителей и загрузки сотрудников. Файлы-«бомбы» — маленькие самодельные, на пределах 6.23; коды отказов прежние."""
import csv
import inspect
import io
import zipfile

import pytest

from tests import support_org

KEYS = ("too_big", "bad_format", "bad_format_archive", "bad_format_csv", "not_utf8", "too_many_rows", "zip_bomb",
        "xml_bomb")
MB = 1024 * 1024
LIMITS = dict(max_bytes=MB, max_rows=1000, max_parts=100, max_unpacked=20 * MB)


def texts_of(tag: str = "A") -> dict:
    """Тексты отказов для вызова: у каждого кода свой, отличимый от текстов org и от текстов другого набора."""
    return {key: f"ТЕСТОВЫЙ-ТЕКСТ-{tag}-{key}" for key in KEYS}


def core():
    from apps.core.services import table_file
    return table_file


def read(content: bytes, *, tag: str = "A", **over):
    limits = {**LIMITS, **over}
    limits.setdefault("texts", texts_of(tag))
    return core().read(content, **limits)


def refusal(content: bytes, code: str, *, tag: str = "A", text_key: str | None = None, **over):
    """Читает файл и требует `TableFileError` с кодом `code` и текстом `texts[text_key or code]`."""
    table_file = core()
    texts = texts_of(tag)
    with pytest.raises(table_file.TableFileError) as caught:
        table_file.read(content, **{**LIMITS, "texts": texts, **over})
    assert caught.value.code == code, f"код {caught.value.code!r}, ожидался {code!r}"
    assert caught.value.message == texts[text_key or code], f"текст отказа {code}: {caught.value.message!r}"
    return caught.value


def csv_bytes(header, rows, *, delimiter: str = ";", bom: bool = True) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(header)
    writer.writerows(rows)
    data = out.getvalue().encode("utf-8")
    return (b"\xef\xbb\xbf" + data) if bom else data


def xlsx_bytes(header, rows, *, second_sheet=None) -> bytes:
    from openpyxl import Workbook
    book = Workbook()
    sheet = book.active
    sheet.append(list(header))
    for line in rows:
        sheet.append(list(line))
    if second_sheet is not None:
        other = book.create_sheet("Второй")
        for line in second_sheet:
            other.append(list(line))
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def xlsx_with_cached_formula(cached: str) -> bytes:
    """Книга, где в B2 формула `=1+1` с сохранённым значением `cached` (как после пересчёта в Excel)."""
    import re
    raw = xlsx_bytes(["Почта", "Значение"], [["a@example.test", "=1+1"]])
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as source, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            data = source.read(info.filename)
            if info.filename == "xl/worksheets/sheet1.xml":
                text, count = re.subn(r'<c r="B2"[^>]*>.*?</c>', f'<c r="B2" t="str"><f>1+1</f><v>{cached}</v></c>',
                                      data.decode("utf-8"), flags=re.S)
                assert count == 1, "помощник теста не нашёл ячейку B2"
                data = text.encode("utf-8")
            target.writestr(info.filename, data)
    return out.getvalue()


def zip_of(files: dict) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in files.items():
            archive.writestr(name, text)
    return out.getvalue()


def not_a_book(parts: int = 1) -> bytes:
    """ZIP без частей книги (нет `xl/workbook.xml`); `parts` — сколько в нём частей."""
    return zip_of({f"readme{i}.txt": "это не книга" for i in range(parts)})


def corrupt_book() -> bytes:
    """Архив с частями книги, но с неразбираемой книгой: openpyxl не читает её (не бомба)."""
    return zip_of({"[Content_Types].xml": "<<< not xml", "xl/workbook.xml": "<<< not xml"})


def parts_and_unpacked(content: bytes) -> tuple[int, int]:
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        infos = archive.infolist()
        return len(infos), sum(info.file_size for info in infos)


def test_csv_read_with_header_delimiter_detected_by_header_line():
    """FR-262, FR-265: CSV — UTF-8 с BOM и без; разделитель «;» или «,» определяется по строке заголовков, а не по
    данным; пустые строки данных не считаются; `read` отдаёт `TableFile` с `file_format`, `header`, `rows`."""
    header = ["Почта", "Фамилия", "Имя"]
    for bom in (True, False):
        # заголовок с «;», в данных запятая внутри значения — разделитель всё равно «;»
        data = csv_bytes(header, [["a@example.test", "Петров, мл.", "Ян"], [], ["", "", ""], ["b@example.test", "Ким", "Ли"]],
                         delimiter=";", bom=bom)
        got = read(data)
        assert got.file_format == "csv"
        assert got.header == header, f"bom={bom}: {got.header}"
        assert got.rows == [["a@example.test", "Петров, мл.", "Ян"], ["b@example.test", "Ким", "Ли"]], \
            f"bom={bom}: пустые строки данных не считаются, разделитель «;»: {got.rows}"
        # заголовок с «,», в данных «;» внутри значения — разделитель «,»
        data = csv_bytes(header, [["a@example.test", "Иванов;Пётр", "Ян"]], delimiter=",", bom=bom)
        got = read(data)
        assert got.header == header and got.rows == [["a@example.test", "Иванов;Пётр", "Ян"]], \
            f"bom={bom}: разделитель «,»: {got.header} {got.rows}"
    # BOM не попадает в первое название колонки
    assert read(csv_bytes(["Почта"], [["a@example.test"]])).header == ["Почта"]


def test_csv_strict_utf8_refuses_other_encoding():
    """FR-265: CSV читается строгим UTF-8: Windows-1251, битая последовательность и NUL — `not_utf8` с текстом
    из `texts`; прежний код `not_utf8`, нового кода нет."""
    cp1251 = csv_bytes(["Почта", "Фамилия"], [["a@example.test", "Иванов"]], bom=False).decode("utf-8").encode("cp1251")
    refusal(cp1251, "not_utf8")
    refusal(b"\xef\xbb\xbfPochta;Name\r\na@example.test;\xff\xfe\xfd\r\n", "not_utf8")
    refusal(b"\x89PNG\r\n\x1a\n\xff\xfe\xfd" * 50, "not_utf8")
    refusal(csv_bytes(["Почта", "Имя"], [["a@example.test", "Ка\x00б"]]), "not_utf8")
    # верный UTF-8 принимается и с кириллицей
    assert read(csv_bytes(["Почта", "Имя"], [["a@example.test", "Ёжик"]])).rows == [["a@example.test", "Ёжик"]]


def test_xlsx_read_without_formulas_read_only():
    """FR-262: XLSX читается только на чтение, без вычисления формул: вместо формулы — сохранённое значение; первый
    лист; пустые строки не считаются; даты ДД.ММ.ГГГГ, целые без «.0», дробные без экспоненты."""
    import datetime
    # формула `=1+1` с сохранённым значением 7: берётся 7, не текст формулы и не результат пересчёта
    got = read(xlsx_with_cached_formula("7"))
    assert got.file_format == "xlsx"
    assert got.header == ["Почта", "Значение"]
    assert got.rows == [["a@example.test", "7"]], f"формулы не вычисляются и не отдаются: {got.rows}"
    # значения ячеек; пустые строки (в том числе из пробелов) не считаются; второй лист не читается
    book = xlsx_bytes(["Дата", "Целое", "Дробное", "Текст"], [
        [datetime.datetime(2025, 12, 31, 13, 0), 12.0, 1.5, "слово"],
        [None, None, None, None],
        ["  ", " ", None, ""],
        [datetime.date(2026, 3, 5), 7, 0.25, "ещё"],
    ], second_sheet=[["Лишний"], ["лист"]])
    got = read(book)
    assert got.header == ["Дата", "Целое", "Дробное", "Текст"]
    assert got.rows == [["31.12.2025", "12", "1.5", "слово"], ["05.03.2026", "7", "0.25", "ещё"]], got.rows


def test_format_detected_by_content_not_extension():
    """FR-265: формат определяет содержимое: книга — `xlsx`, текст — `csv` (даже начинающийся с «PK»), чужой архив —
    отказ `bad_format`; у `read` нет параметров с именем файла и типом."""
    parameters = set(inspect.signature(core().read).parameters)
    assert parameters == {"content", "max_bytes", "max_rows", "max_parts", "max_unpacked", "texts"}, parameters
    assert read(xlsx_bytes(["Почта"], [["a@example.test"]])).file_format == "xlsx"
    assert read(csv_bytes(["Почта"], [["a@example.test"]])).file_format == "csv"
    # текст, который только выглядит как начало архива, — CSV
    looks_zip = read("PK;Имя\r\nа;б\r\n".encode("utf-8"))
    assert looks_zip.file_format == "csv" and looks_zip.header == ["PK", "Имя"] and looks_zip.rows == [["а", "б"]]
    # ZIP с CSV-файлом внутри и ZIP без частей книги — не таблица; ZIP с `[Content_Types].xml`, но без книги — тоже
    refusal(zip_of({"a.csv": "Почта;Фамилия"}), "bad_format", text_key="bad_format_archive")
    refusal(zip_of({"[Content_Types].xml": "<Types/>", "xl/worksheets/sheet1.xml": "<worksheet/>"}), "bad_format",
            text_key="bad_format_archive")


def test_size_limit_is_parameter_and_refused_above():
    """FR-265: предел размера — параметр `max_bytes`: ровно предел принимается, на байт больше — `too_big` до разбора
    (любое содержимое, в том числе не UTF-8)."""
    data = csv_bytes(["Почта"], [["a@example.test"]])
    size = len(data)
    assert read(data, max_bytes=size).rows == [["a@example.test"]]
    refusal(data, "too_big", max_bytes=size - 1)
    # другой предел — другой порог; отказ по размеру раньше отказов разбора
    refusal(b"\x00" * 1001, "too_big", max_bytes=1000)
    refusal(support_org.xlsx_zip_bomb(), "too_big", max_bytes=1000)
    assert read(data, max_bytes=10 * size).file_format == "csv"
    # предел не зашит: при пределе 2 МБ (загрузка заявителей) файл чуть больше 1 МБ годен
    big = csv_bytes(["Почта", "Имя"], [["a@example.test", "x" * 1000] for _ in range(1100)])
    assert MB < len(big) < 2 * MB
    assert len(read(big, max_bytes=2 * MB, max_rows=2000).rows) == 1100
    refusal(big, "too_big", max_bytes=MB)


def test_rows_limit_is_parameter_and_stops_on_row_over_limit():
    """FR-265: предел строк — параметр: `read` останавливается на строке `max_rows + 1` и о числе строк не судит;
    `check_rows(rows, max_rows, texts)` отказывает `too_many_rows` при строках больше предела, при равных — нет."""
    table_file = core()
    for max_rows in (3, 5):
        data = csv_bytes(["Почта"], [[f"u{i}@example.test"] for i in range(50)])
        got = read(data, max_rows=max_rows)
        assert len(got.rows) == max_rows + 1, f"остановка на строке max_rows+1={max_rows + 1}: прочитано {len(got.rows)}"
        assert got.rows[0] == ["u0@example.test"]
        xlsx = xlsx_bytes(["Почта"], [[f"u{i}@example.test"] for i in range(50)])
        got = read(xlsx, max_rows=max_rows)
        assert len(got.rows) == max_rows + 1, f"XLSX: прочитано {len(got.rows)}"
        # ровно предел — читается всё, отказа нет
        exact = read(csv_bytes(["Почта"], [[f"u{i}@example.test"] for i in range(max_rows)]), max_rows=max_rows)
        assert len(exact.rows) == max_rows
        # пустые строки данных предел не занимают
        padded = csv_bytes(["Почта"], [[f"u{i}@example.test"] if i % 2 else [] for i in range(2 * max_rows + 1)])
        assert len(read(padded, max_rows=max_rows).rows) == max_rows
    texts = texts_of()
    rows = [[f"u{i}"] for i in range(5)]
    assert table_file.check_rows(rows, 5, texts) is None
    with pytest.raises(table_file.TableFileError) as caught:
        table_file.check_rows(rows, 4, texts)
    assert caught.value.code == "too_many_rows" and caught.value.message == texts["too_many_rows"]
    with pytest.raises(table_file.TableFileError) as other:
        table_file.check_rows(rows, 0, texts_of("B"))
    assert other.value.message == texts_of("B")["too_many_rows"]


def test_xlsx_archive_parts_and_unpacked_size_limits_are_parameters():
    """FR-265, NFR-108: число частей архива и распакованный объём — параметры `max_parts`, `max_unpacked`; бомбы
    (больше 100 частей; больше 20 МБ внутри при малом файле) — `zip_bomb`; ровно предел принимается."""
    many = support_org.xlsx_many_parts()
    bomb = support_org.xlsx_zip_bomb()
    assert len(many) < MB and len(bomb) < MB, "бомбы малы: отказ идёт от оглавления, а не от размера"
    refusal(many, "zip_bomb")
    refusal(bomb, "zip_bomb")
    # число частей — параметр
    count, _ = parts_and_unpacked(many)
    assert count > 100
    assert read(many, max_parts=count).file_format == "xlsx"
    refusal(many, "zip_bomb", max_parts=count - 1)
    # распакованный объём — параметр
    book = xlsx_bytes(["Почта"], [["a@example.test"]])
    parts, unpacked = parts_and_unpacked(book)
    assert read(book, max_parts=parts, max_unpacked=unpacked).rows == [["a@example.test"]]
    refusal(book, "zip_bomb", max_unpacked=unpacked - 1)
    refusal(book, "zip_bomb", max_parts=parts - 1)
    # обычная книга при пределах по умолчанию принимается
    assert read(book).file_format == "xlsx"


def test_xlsx_archive_directory_checked_before_reading():
    """NFR-108: оглавление архива проверяется до чтения книги, порядок отказов: `too_big`, `bad_format` (не книга),
    `zip_bomb`, затем чтение (`xml_bomb`)."""
    xml_bomb = support_org.xlsx_xml_bomb()
    assert len(xml_bomb) < MB
    refusal(xml_bomb, "xml_bomb")
    # XML-бомба, у которой ещё и больше 100 частей: оглавление раньше разбора -> zip_bomb
    both = io.BytesIO(xml_bomb)
    with zipfile.ZipFile(both, "a") as archive:
        for number in range(101):
            archive.writestr(f"xl/extra/part{number}.xml", "<a/>")
    refusal(both.getvalue(), "zip_bomb")
    # то же по объёму: предел распакованного меньше объёма бомбы -> zip_bomb, а не xml_bomb
    _, unpacked = parts_and_unpacked(xml_bomb)
    refusal(xml_bomb, "zip_bomb", max_unpacked=unpacked - 1)
    # не книга с кучей частей: отказ «не XLSX» раньше проверки частей
    refusal(not_a_book(150), "bad_format", text_key="bad_format_archive")
    # размер раньше всего
    refusal(both.getvalue(), "too_big", max_bytes=len(both.getvalue()) - 1)
    # проверка оглавления: один большой лист без лишних частей даёт zip_bomb по распакованному объёму (max_unpacked=MB)
    refusal(support_org.xlsx_zip_bomb(), "zip_bomb", max_unpacked=MB)


def test_refusal_texts_are_parameters():
    """FR-262, FR-265: тексты отказов — параметр `texts` (код -> текст): два разных набора дают разные тексты для
    каждого отказа `read` и `check_rows`; ключи: `too_big`, `bad_format`, `bad_format_archive`, `bad_format_csv`,
    `not_utf8`, `too_many_rows`, `zip_bomb`, `xml_bomb`."""
    table_file = core()
    huge_field = csv_bytes(["Почта", "Имя"], [["a@example.test", "x" * 200_000]])
    small = csv_bytes(["Почта"], [["a@example.test"]])
    cases = [
        ("too_big", "too_big", small, {"max_bytes": 5}),
        ("bad_format", "bad_format_archive", not_a_book(), {}),
        ("bad_format", "bad_format_csv", huge_field, {}),
        ("bad_format", "bad_format", corrupt_book(), {}),
        ("not_utf8", "not_utf8", b"\xff\xfe\xfd;\xff\r\n", {}),
        ("zip_bomb", "zip_bomb", support_org.xlsx_many_parts(), {}),
        ("xml_bomb", "xml_bomb", support_org.xlsx_xml_bomb(), {}),
    ]
    for code, key, content, over in cases:
        first = refusal(content, code, tag="A", text_key=key, **over)
        second = refusal(content, code, tag="B", text_key=key, **over)
        assert first.message != second.message, f"{key}: текст не зависит от параметра"
    for tag in ("A", "B"):
        with pytest.raises(table_file.TableFileError) as caught:
            table_file.check_rows([[1], [2]], 1, texts_of(tag))
        assert caught.value.message == texts_of(tag)["too_many_rows"]


def test_refusal_raises_core_exception_with_code_and_text():
    """FR-265: отказ — собственное исключение ядра `TableFileError(Exception)` с `code` и `message` (не `OrgError`
    и не `ServiceDeskError`); `str(error)` — текст; коды — прежние шесть."""
    table_file = core()
    from apps.org.services.errors import OrgError
    assert issubclass(table_file.TableFileError, Exception) and not issubclass(table_file.TableFileError, OrgError)
    samples = {
        "too_big": (csv_bytes(["Почта"], [["a@example.test"]]), {"max_bytes": 3}),
        "bad_format": (corrupt_book(), {}),
        "not_utf8": (b"\xff\xfe\xfd", {}),
        "zip_bomb": (support_org.xlsx_many_parts(), {}),
        "xml_bomb": (support_org.xlsx_xml_bomb(), {}),
    }
    for code, (content, over) in samples.items():
        error = refusal(content, code, **over)
        assert isinstance(error, table_file.TableFileError) and not isinstance(error, OrgError)
        assert isinstance(error.code, str) and isinstance(error.message, str) and error.message
        assert str(error) == error.message, f"{code}: str(error) — текст отказа"
    with pytest.raises(table_file.TableFileError) as caught:
        table_file.check_rows([[1], [2]], 1, texts_of())
    assert caught.value.code == "too_many_rows"


def test_org_staff_import_wraps_core_exception_into_org_error_with_same_codes():
    """FR-262, FR-265: `org.staff_import.parse_file` оборачивает `TableFileError` в `OrgError` с прежними кодами и
    текстами среза 002 (пределы 1 МБ, 1000 строк); отказы колонок остаются за `org`."""
    from apps.core.services import table_file
    from apps.org.services import staff_import
    from apps.org.services.errors import OrgError

    def org_refusal(content: bytes, code: str, text: str | None = None):
        with pytest.raises(OrgError) as caught:
            staff_import.parse_file(content)
        assert not isinstance(caught.value, table_file.TableFileError)
        assert caught.value.code == code, f"код {caught.value.code!r}, ожидался {code!r}"
        if text is not None:
            assert caught.value.message == text and str(caught.value) == text
        return caught.value

    org_refusal(b"\x00" * (1_048_576 + 1), "too_big", "Файл больше 1 МБ: разделите его на части.")
    rows = [support_org.staff_row() for _ in range(1001)]
    org_refusal(support_org.staff_csv(rows), "too_many_rows", "В файле больше 1000 строк: разделите его на части.")
    org_refusal(support_org.staff_xlsx(rows), "too_many_rows", "В файле больше 1000 строк: разделите его на части.")
    org_refusal(not_a_book(), "bad_format", "Это архив, но не таблица XLSX. Загрузите CSV (UTF-8) или XLSX.")
    org_refusal(corrupt_book(), "bad_format", "Не удалось прочитать таблицу XLSX: файл повреждён.")
    org_refusal(support_org.xlsx_zip_bomb(), "zip_bomb",
                "Файл отклонён: слишком много частей или слишком большой объём внутри.")
    org_refusal(support_org.xlsx_many_parts(), "zip_bomb")
    org_refusal(support_org.xlsx_xml_bomb(), "xml_bomb", "Файл отклонён: внутри таблицы опасная XML-конструкция.")
    cp1251 = support_org.staff_csv([support_org.staff_row(last_name="Иванов")], bom=False).decode("utf-8").encode("cp1251")
    org_refusal(cp1251, "not_utf8", "Файл не в кодировке UTF-8: сохраните таблицу как CSV UTF-8 или XLSX.")
    org_refusal(support_org.staff_csv([support_org.staff_row(workplace="Каб\x00инет")]), "not_utf8")
    huge = support_org.staff_csv([support_org.staff_row(workplace="x" * 200_000)])
    org_refusal(huge, "bad_format",
                "Не удалось прочитать CSV: слишком длинное значение или нарушена разметка.")
    # порядок: колонки раньше числа строк (вызывающий проверяет колонки, потом `check_rows`)
    no_email = [h for h in support_org.STAFF_HEADERS if h != "Почта"]
    many = [[support_org.staff_row()[h] for h in no_email] for _ in range(1001)]
    org_refusal(support_org.staff_csv(many, headers=no_email), "missing_columns")
    # годный файл по-прежнему разбирается
    parsed = staff_import.parse_file(support_org.staff_csv([support_org.staff_row()]))
    assert parsed.file_format == "csv" and len(parsed.rows) == 1


def test_org_calls_core_reader_with_own_limits_and_texts(monkeypatch):
    """FR-262, FR-265: загрузка сотрудников зовёт `table_file.read` через имя модуля со своими пределами (1 МБ,
    1000 строк, 100 частей, 20 МБ) и прежними текстами отказов; результат ядра используется."""
    from apps.core.services import table_file
    from apps.org.services import staff_import

    calls = []
    real = table_file.read

    def spy(*args, **kwargs):
        calls.append((args, kwargs))
        return real(*args, **kwargs)

    monkeypatch.setattr(table_file, "read", spy)
    content = support_org.staff_csv([support_org.staff_row()])
    parsed = staff_import.parse_file(content)
    assert len(parsed.rows) == 1 and parsed.file_format == "csv"
    assert len(calls) == 1, f"ядро должно читаться один раз через имя модуля: {len(calls)}"
    args, kwargs = calls[0]
    passed = args[0] if args else kwargs.get("content")
    assert passed == content
    assert kwargs["max_bytes"] == 1_048_576
    assert kwargs["max_rows"] == 1000
    assert kwargs["max_parts"] == 100
    assert kwargs["max_unpacked"] == 20 * 1024 * 1024
    texts = kwargs["texts"]
    assert set(KEYS) <= set(texts), f"нет ключей texts: {set(KEYS) - set(texts)}"
    assert texts["too_big"] == "Файл больше 1 МБ: разделите его на части."
    assert texts["too_many_rows"] == "В файле больше 1000 строк: разделите его на части."
    assert texts["bad_format_archive"] == "Это архив, но не таблица XLSX. Загрузите CSV (UTF-8) или XLSX."
    assert texts["bad_format"] == "Не удалось прочитать таблицу XLSX: файл повреждён."
    assert texts["bad_format_csv"] == "Не удалось прочитать CSV: слишком длинное значение или нарушена разметка."
    assert texts["zip_bomb"] == "Файл отклонён: слишком много частей или слишком большой объём внутри."
    assert texts["xml_bomb"] == "Файл отклонён: внутри таблицы опасная XML-конструкция."
    assert texts["not_utf8"] == "Файл не в кодировке UTF-8: сохраните таблицу как CSV UTF-8 или XLSX."
