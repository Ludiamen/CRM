"""Общие помощники тестов среза 002 (T-2100b, контракт имён — tests/CONTRACT-002.md).

Код среза (`apps.org`, `apps.integrations.clamav`) на уровне модуля не импортируется: сбор тестов
проходит до появления кода, а падения видны поимённо при вызове. Модели берутся лениво через
`support.model(...)`. Пароли и секреты — только из factories; строка EICAR целиком в файле не лежит.
"""
import csv
import io
import re
import uuid
import zipfile
from collections import namedtuple
from datetime import date
from pathlib import Path

import django_rq
from rq.worker import SimpleWorker

from tests import factories, support

CALENDAR_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "calendar"


# --- название узла ------------------------------------------------------------------------------

def name_key(text: str) -> str:
    """`Unit.name_key` (CONTRACT-002 § 2): без крайних и повторных пробелов, в нижнем регистре, «ё» -> «е»."""
    return " ".join(text.split()).lower().replace("ё", "е")


# --- структура: узлы, членства, роли узла -----------------------------------------------------

_unit_counter = iter(range(1, 10**9))


def root_unit():
    """Корневой отдел (его создаёт миграция `org`; корень создаёт только она)."""
    return support.model("org.Unit").objects.get(is_root=True)


def make_unit(name: str | None = None, *, kind: str = "department", parent=None, description: str = ""):
    """Узел через ORM (не через сервис): `path`, `depth`, `name_key` по правилам § 2. Родитель по умолчанию — корень."""
    Unit = support.model("org.Unit")
    parent = parent or root_unit()
    name = name or f"Узел {next(_unit_counter)}-{uuid.uuid4().hex[:6]}"
    unit = Unit.objects.create(
        name=name, name_key=name_key(name), kind=kind, parent=parent, description=description,
        depth=parent.depth + 1, path="")
    unit.path = f"{parent.path}{unit.pk}/"
    unit.save(update_fields=["path"])
    return unit


def make_member(user, unit, *, mark: str = "", created_by=None):
    """Членство; `mark` — `""`, `"head"` или `"deputy"`. `created_by` обязателен в модели (план), по умолчанию — сам `user`."""
    return support.model("org.Membership").objects.create(
        user=user, unit=unit, mark=mark, created_by=created_by or user)


def make_unit_role(unit, role):
    return support.model("org.UnitRole").objects.create(unit=unit, role=role)


def make_tree(spec: dict, parent=None) -> dict:
    """Дерево из вложенного описания: `{"Сеть": {"Серверы": {}}, "Поддержка": {}}`.

    Ключ с приставкой `team:` — команда (`{"team:Дежурные": {}}`). Возвращает словарь «название -> узел»
    (название без приставки; одинаковые названия на разных ветках перезаписывают друг друга).
    """
    result = {}
    for key, children in spec.items():
        kind, title = ("team", key[len("team:"):]) if key.startswith("team:") else ("department", key)
        unit = make_unit(title, kind=kind, parent=parent)
        result[title] = unit
        result.update(make_tree(children or {}, unit))
    return result


# --- подмена антивируса -----------------------------------------------------------------------

_FallbackResult = namedtuple("ScanResult", "clean signature")


class _FallbackScanUnavailable(Exception):
    """ЗАГЛУШКА: настоящего `ScanUnavailable` ещё нет в `apps.integrations.clamav.services`.

    Тест, ловящий именно настоящий класс, упадёт красным, пока кода нет, — это нормально.
    """


def _clamav_attr(name: str, fallback):
    try:
        from apps.integrations.clamav import services
    except ImportError:
        return fallback
    return getattr(services, name, fallback)


def __getattr__(name: str):
    """`support_org.ScanResult` и `support_org.ScanUnavailable` — настоящие классы, если код уже есть."""
    if name == "ScanResult":
        return _clamav_attr("ScanResult", _FallbackResult)
    if name == "ScanUnavailable":
        return _clamav_attr("ScanUnavailable", _FallbackScanUnavailable)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


_SCAN_TARGET = "apps.integrations.clamav.services.scan"


def _patch_scan(monkeypatch, outcome) -> list:
    calls: list[str] = []

    def fake_scan(path):
        calls.append(str(path))
        return outcome()

    monkeypatch.setattr(_SCAN_TARGET, fake_scan, raising=False)
    return calls


def scan_clean(monkeypatch) -> list:
    """`scan` отвечает «чисто». Возвращает список путей, с которыми его вызвали."""
    return _patch_scan(monkeypatch, lambda: __getattr__("ScanResult")(True, ""))


def scan_found(monkeypatch, signature: str = "Eicar-Signature") -> list:
    """`scan` находит сигнатуру (без слова FOUND и без `stream:`)."""
    return _patch_scan(monkeypatch, lambda: __getattr__("ScanResult")(False, signature))


def scan_unavailable(monkeypatch) -> list:
    """`scan` поднимает `ScanUnavailable`."""
    def fail():
        raise __getattr__("ScanUnavailable")("clamd недоступен")

    return _patch_scan(monkeypatch, fail)


def eicar_bytes() -> bytes:
    """Тестовая строка EICAR (68 байт) собирается из частей при вызове."""
    parts = ("X5O!P%@AP[4\\PZX54(P^)7CC)7}$", "EICAR-STANDARD-", "ANTIVIRUS-TEST-", "FILE!$H+H*")
    return "".join(parts).encode("ascii")


# --- картинки ---------------------------------------------------------------------------------

def png_bytes(width: int = 64, height: int = 64, *, exif: bool = False) -> bytes:
    from PIL import Image

    image = Image.new("RGB", (width, height), (200, 80, 40))
    out = io.BytesIO()
    if exif:
        data = Image.Exif()
        data[0x010F] = "FakeMaker"
        image.save(out, "PNG", exif=data)
    else:
        image.save(out, "PNG")
    return out.getvalue()


def jpeg_bytes(width: int = 64, height: int = 64, *, exif_gps: bool = False, orientation: int | None = None) -> bytes:
    """JPEG; `exif_gps` — с координатами (тест проверяет, что в сохранённом фото их нет), `orientation` — тег 0x0112."""
    from PIL import Image

    image = Image.new("RGB", (width, height), (40, 120, 200))
    exif = Image.Exif()
    if orientation is not None:
        exif[0x0112] = orientation
    if exif_gps:
        exif[0x8825] = {1: "N", 2: (55.0, 45.0, 21.0), 3: "E", 4: (37.0, 37.0, 4.0)}
    out = io.BytesIO()
    if exif_gps or orientation is not None:
        image.save(out, "JPEG", exif=exif)
    else:
        image.save(out, "JPEG")
    return out.getvalue()


def fake_png() -> bytes:
    """Подпись PNG, но не картинка."""
    return b"\x89PNG\r\n\x1a\n" + b"this is not an image " * 8


def huge_pixels_png() -> bytes:
    """PNG больше 40 000 000 точек (7000 x 6000 = 42 000 000) при малом размере файла."""
    from PIL import Image

    out = io.BytesIO()
    Image.new("1", (7000, 6000), 0).save(out, "PNG", optimize=True)
    return out.getvalue()


# --- файлы сотрудников (CONTRACT-002 § 4.7) ----------------------------------------------------

STAFF_HEADERS = ("Почта", "Фамилия", "Имя", "Должность",
                 "Отчество", "Телефон", "Внутренний телефон", "Место работы", "Подразделение", "Руководитель")
# латинские имена -> названия колонок; `staff_row(**over)` принимает любые из них
STAFF_COLUMN_NAMES = {
    "email": "Почта", "last_name": "Фамилия", "first_name": "Имя", "position": "Должность",
    "middle_name": "Отчество", "phone": "Телефон", "internal_phone": "Внутренний телефон",
    "workplace": "Место работы", "unit_path": "Подразделение", "head": "Руководитель",
}


def staff_row(**over) -> dict:
    """Годная строка загрузки; ключи — названия колонок по-русски. Переопределяют латинские имена
    (`email`, `last_name`, …, `unit_path`, `head`) или русские названия колонок (через `**{"Почта": …}`)."""
    row = {
        "Почта": factories.new_email("staff"), "Фамилия": "Тестов", "Имя": "Тест", "Должность": "Инженер",
        "Отчество": "Тестович", "Телефон": "+7 900 000-00-00", "Внутренний телефон": "101",
        "Место работы": "Кабинет 1", "Подразделение": "", "Руководитель": "нет",
    }
    for key, value in over.items():
        column = STAFF_COLUMN_NAMES.get(key, key)
        if column not in row:
            raise KeyError(f"нет колонки {key!r}; допустимы {sorted(STAFF_COLUMN_NAMES)}")
        row[column] = value
    return row


def _table(rows, headers):
    headers = list(headers or STAFF_HEADERS)
    body = [[("" if r.get(h) is None else str(r.get(h))) for h in headers] if isinstance(r, dict) else list(r)
            for r in rows]
    return headers, body


def staff_csv(rows, *, headers=None, delimiter: str = ";", bom: bool = True) -> bytes:
    """CSV (UTF-8, по умолчанию с BOM). `rows` — словари «колонка -> значение» или списки по порядку `headers`."""
    headers, body = _table(rows, headers)
    out = io.StringIO()
    writer = csv.writer(out, delimiter=delimiter, lineterminator="\r\n")
    writer.writerow(headers)
    writer.writerows(body)
    data = out.getvalue().encode("utf-8")
    return (b"\xef\xbb\xbf" + data) if bom else data


def staff_xlsx(rows, *, headers=None) -> bytes:
    from openpyxl import Workbook

    headers, body = _table(rows, headers)
    book = Workbook()
    sheet = book.active
    sheet.append(headers)
    for line in body:
        sheet.append(line)
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


_XLSX_PARTS = {
    "[Content_Types].xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.'
        'spreadsheetml.sheet.main+xml"/>'
        '<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.'
        'spreadsheetml.worksheet+xml"/></Types>'),
    "_rels/.rels": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        'officeDocument" Target="xl/workbook.xml"/></Relationships>'),
    "xl/workbook.xml": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        '<sheets><sheet name="Лист1" sheetId="1" r:id="rId1"/></sheets></workbook>'),
    "xl/_rels/workbook.xml.rels": (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/'
        'worksheet" Target="worksheets/sheet1.xml"/></Relationships>'),
}
_SHEET = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
          '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">{pad}'
          '<sheetData><row r="1"><c r="A1" t="inlineStr"><is><t>Почта</t></is></c></row></sheetData></worksheet>')


def _zip_xlsx(extra: dict | None = None, *, sheet: str | None = None, shared: str | None = None) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, text in _XLSX_PARTS.items():
            if shared is not None and name == "xl/_rels/workbook.xml.rels":
                text = text.replace("</Relationships>", (
                    '<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/'
                    'relationships/sharedStrings" Target="sharedStrings.xml"/></Relationships>'))
            if shared is not None and name == "[Content_Types].xml":
                text = text.replace("</Types>", (
                    '<Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-'
                    'officedocument.spreadsheetml.sharedStrings+xml"/></Types>'))
            archive.writestr(name, text)
        archive.writestr("xl/worksheets/sheet1.xml", sheet if sheet is not None else _SHEET.format(pad=""))
        if shared is not None:
            archive.writestr("xl/sharedStrings.xml", shared)
        for name, data in (extra or {}).items():
            archive.writestr(name, data)
    return out.getvalue()


def xlsx_zip_bomb() -> bytes:
    """Архив меньше 1 МБ, в распакованном виде больше 20 МБ (лист с 25 МБ пробелов)."""
    return _zip_xlsx(sheet=_SHEET.format(pad=" " * (25 * 1024 * 1024)))


def xlsx_many_parts() -> bytes:
    """Книга, в архиве которой больше 100 частей (всего 130)."""
    return _zip_xlsx({f"xl/extra/part{i}.xml": "<x/>" for i in range(125)})


def xlsx_xml_bomb() -> bytes:
    """«Billion laughs» в sharedStrings: openpyxl с defusedxml отвергает объявление сущностей."""
    entities = ['<!ENTITY a0 "lol">'] + [
        f'<!ENTITY a{i} "' + f"&a{i - 1};" * 10 + '">' for i in range(1, 9)]
    shared = ('<?xml version="1.0" encoding="UTF-8"?><!DOCTYPE sst [' + "".join(entities) + ']>'
              '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="1" uniqueCount="1">'
              '<si><t>&a8;</t></si></sst>')
    sheet = ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
             '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
             '<row r="1"><c r="A1" t="s"><v>0</v></c></row></sheetData></worksheet>')
    return _zip_xlsx(sheet=sheet, shared=shared)


# --- календарь --------------------------------------------------------------------------------

def calendar_fixture(name: str) -> bytes:
    """Файл из `tests/fixtures/calendar/` (например `cal2026.csv`, `bad_totals_2026.csv`)."""
    return (CALENDAR_FIXTURES / name).read_bytes()


CALENDAR_HEADERS = (
    "Год/Месяц", "Январь", "Февраль", "Март", "Апрель", "Май", "Июнь", "Июль", "Август", "Сентябрь", "Октябрь",
    "Ноябрь", "Декабрь", "Всего рабочих дней", "Всего праздничных и выходных дней",
    "Количество рабочих часов при 40-часовой рабочей неделе",
    "Количество рабочих часов при 36-часовой рабочей неделе",
    "Количество рабочих часов при 24-часовой рабочей неделе",
)
_TOTAL_KEYS = ("work_days", "off_days", "hours40", "hours36", "hours24")


def _month_cells(months) -> list[str]:
    if isinstance(months, dict):
        cells = [months.get(m, "") for m in range(1, 13)]
    else:
        cells = list(months) + [""] * (12 - len(list(months)))
    return [c if isinstance(c, str) else ",".join(str(x) for x in c) for c in cells]


def _number(value: float) -> str:
    return f"{value:.1f}".rstrip("0").rstrip(".") if value != int(value) else str(int(value))


def calendar_totals(year: int, months) -> dict:
    """Итоги по правилам плана («Сверка»): число из списка месяца без «*» — нерабочий день; с «*» — рабочий
    сокращённый (на час короче); всё остальное — рабочий. 36 и 24 часа — 7,2 и 4,8 за день, сокращённый на час короче."""
    off, short = set(), 0
    for month, cell in enumerate(_month_cells(months), start=1):
        for token in filter(None, (t.strip() for t in cell.split(","))):
            number = int(token.rstrip("*+"))
            if token.endswith("*"):
                short += 1
            else:
                off.add(date(year, month, number))
    days = (date(year + 1, 1, 1) - date(year, 1, 1)).days
    work = days - len(off)
    return {"work_days": work, "off_days": len(off), "hours40": work * 8 - short,
            "hours36": round(work * 7.2 - short, 1), "hours24": round(work * 4.8 - short, 1)}


def calendar_csv(year: int, months, *, totals: dict | None = None) -> bytes:
    """Файл года в формате открытых данных (UTF-8 без BOM, «,», ячейки месяцев в кавычках, без перевода строки в конце).

    `months` — словарь «номер месяца -> ячейка» (`{2: "6,7,22+,23"}`) или список из 12 ячеек; ячейка — строка
    или список токенов; пропущенный месяц — без нерабочих дней. Итоги считаются по правилам плана;
    `totals` переопределяет любые из ключей `work_days`, `off_days`, `hours40`, `hours36`, `hours24`
    (например, чтобы получить файл, где итоги не сходятся).
    """
    values = {**calendar_totals(year, months), **(totals or {})}
    unknown = set(totals or {}) - set(_TOTAL_KEYS)
    if unknown:
        raise KeyError(f"неизвестные ключи итогов: {sorted(unknown)}; допустимы {_TOTAL_KEYS}")
    header = ",".join(f'"{h}"' for h in CALENDAR_HEADERS)
    cells = [f'"{c}"' for c in _month_cells(months)]
    line = ",".join([str(year), *cells, *(_number(values[k]) for k in _TOTAL_KEYS)])
    return f"{header}\n{line}".encode("utf-8")


# --- очередь `files` --------------------------------------------------------------------------

def files_queue():
    return django_rq.get_queue("files")


def files_jobs():
    return list(files_queue().jobs)


def run_files_worker() -> None:
    """Исполняет все задания очереди `files` (SimpleWorker в процессе теста, burst), как `support_mail.deliver`."""
    queue = files_queue()
    SimpleWorker([queue], connection=queue.connection).work(burst=True)


def no_extensions():
    """Обычная функция-обёртка: контекстный менеджер `apps.core.extensions.empty()`.

    Фикстура с тем же именем живёт в `tests/conftest.py` (pytest находит фикстуры только там)."""
    from apps.core import extensions

    return extensions.empty()


# --- права и маршруты среза под /staff/ и /me/ -------------------------------------------------

LOGIN_ONLY = "вход"   # в кортеже прав: достаточно войти, права не нужны (без входа — 302 на /login/)
SELF = "сам"          # в кортеже прав: ещё и сам сотрудник (id в адресе равен id смотрящего)

# (метод, шаблон пути, права). Права — кортеж кодов: достаточно ЛЮБОГО (как «или» в плане), плюс отметки
# LOGIN_ONLY и SELF. Форма совместима с `protected_table` из test_permissions.py (метод, путь, право):
# шаблон превращается в путь `route_path(template, user, ...)`, а право — любой код из кортежа.
SLICE_002_STAFF_ROUTES = (
    ("get", "/staff/", ("staff.view", "accounts.manage")),
    ("get", "/staff/{user_id}/", ("staff.view", "accounts.manage")),
    ("post", "/staff/{user_id}/edit/", ("accounts.manage",)),
    ("get", "/staff/{user_id}/photo/{photo_id}/{size}/", ("staff.view", "accounts.manage", SELF)),
    ("post", "/staff/{user_id}/photo/delete/", ("accounts.manage",)),
)

# Свои маршруты среза (`/me/…`): не под `staff/`, поэтому отдельно от SLICE_002_STAFF_ROUTES (T-2119, п. 3).
SLICE_002_ME_ROUTES = (
    ("get", "/me/", (LOGIN_ONLY,)),
    ("post", "/me/", (LOGIN_ONLY,)),
    ("post", "/me/photo/", (LOGIN_ONLY,)),
    ("post", "/me/photo/delete/", (LOGIN_ONLY,)),
)


def route_path(template: str, user=None, *, photo_id=None, size: int = 96) -> str:
    """Путь по шаблону маршрута: `user` даёт `{user_id}`, `photo_id` по умолчанию — случайный UUID."""
    return template.format(user_id=getattr(user, "pk", user), photo_id=photo_id or uuid.uuid4(), size=size)


def route_regex(template: str) -> "re.Pattern":
    """Регулярное выражение для сверки шаблона с `support.all_routes()` (в нём параметры вида `<int:user_id>`)."""
    return re.compile("^" + re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(template)) + "$")
