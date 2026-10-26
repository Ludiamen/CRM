"""T-6120: этикетки и QR-код (FR-538, FR-539; граница чтения FR-514, пометка архива FR-523, предел FR-546, журнал
FR-542). Сценарии спеки — «Этикетки» (одна этикетка, QR сканирует читающий и не вошедший, не читающий, лист из
нескольких, больше 100, печать).

Раздел 5.7, 10.2, 10.3, 11.1, 11.9 контракта, решения 10, 39, 59 задач. QR не декодируется (декодера нет, решение 10):
картинка из `src` сверяется побайтно с выводом `qrcode` для адреса из `data-qr-url`, а адрес открывается вошедшим,
не вошедшим и не читающим. Код среза импортируется внутри тестов."""
import base64
import io
import re
from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit

import pytest
from django.conf import settings

from tests import factories, support, support_lists
from tests.support_lists import add_field, archive, as_reader, grant_list, make_list, make_record

pytestmark = pytest.mark.django_db

DATA_URI = "data:image/svg+xml;base64,"
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}


# --- разбор разметки (свой, как в тестах среза 005) ---------------------------------------------------------

class Node:
    def __init__(self, tag, attrs, parent=None):
        self.tag, self.attrs, self.parent, self.children, self.chunks = tag, dict(attrs), parent, [], []

    def walk(self):
        yield self
        for child in self.children:
            yield from child.walk()

    def text(self) -> str:
        parts = list(self.chunks)
        for child in self.children:
            parts.append(child.text())
        return " ".join(" ".join(parts).split())


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {})
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, [(k, v if v is not None else "") for k, v in attrs], self.cur)
        self.cur.children.append(node)
        if tag not in VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        node = Node(tag, [(k, v if v is not None else "") for k, v in attrs], self.cur)
        self.cur.children.append(node)

    def handle_endtag(self, tag):
        probe = self.cur
        while probe is not self.root and probe.tag != tag:
            probe = probe.parent
        if probe is not self.root:
            self.cur = probe.parent

    def handle_data(self, data):
        self.cur.chunks.append(data)


def dom(response) -> Node:
    parser = _Tree()
    parser.feed(response.content.decode("utf-8", "replace"))
    return parser.root


def select(root, tag=None, **attrs):
    """Узлы с тегом `tag` (если задан) и атрибутами: значение `True` — атрибут есть, строка — равен."""
    found = []
    for node in root.walk():
        if tag and node.tag != tag:
            continue
        if all((name in node.attrs) if want is True else node.attrs.get(name) == want
               for name, want in ((k.replace("_", "-"), v) for k, v in attrs.items())):
            found.append(node)
    return found


def labels_of(response) -> list[dict]:
    """Этикетки страницы по порядку: название списка, название записи, значение, QR (адрес и `src`)."""
    result = []
    for label in select(dom(response), **{"data_lists_label": True}):
        def part(name):
            nodes = select(label, data_field=name)
            return nodes[0].text() if nodes else None

        images = select(label, "img", data_lists_qr=True)
        result.append({
            "list": part("list"), "title": part("title"), "value": part("value"),
            "url": images[0].attrs.get("data-qr-url") if images else None,
            "src": images[0].attrs.get("src") if images else None,
        })
    return result


# --- данные ---------------------------------------------------------------------------------------------------

def card_address(lst, record) -> str:
    return f"{settings.PORTAL_URL}/lists/{lst.pk}/{record.number}/"


def label_path(lst, record) -> str:
    return f"/lists/{lst.pk}/{record.number}/label/"


def sheet_path(lst, numbers) -> str:
    return f"/lists/{lst.pk}/labels/?" + urlencode([("n", n) for n in numbers])


def reader_of(lst, **extra):
    return as_reader(lst, **extra)


def outsider(**extra):
    """Сотрудник без прав на списки, вошёл."""
    user = support.make_employee(**extra)
    return support_lists.Session(user, support.logged_in(user))


def alerts(response, code):
    return select(dom(response), role="alert", data_code=code)


def no_inline(html: str) -> bool:
    return not re.search(r"<[^>]*\sstyle\s*=", html, re.I) and not re.search(r"<[^>]*\son[a-z]+\s*=", html, re.I)


def css_block(css: str, header: str) -> str:
    """Тело блока `header { … }` с учётом вложенных скобок (пустая строка, если блока нет)."""
    start = css.find(header)
    if start < 0:
        return ""
    open_at = css.find("{", start)
    depth, i = 0, open_at
    while i < len(css):
        depth += {"{": 1, "}": -1}.get(css[i], 0)
        if depth == 0:
            return css[open_at + 1:i]
        i += 1
    return ""


def serial_list():
    """Список с уникальным полем «Инвентарный номер» (строка) и записью с этим значением."""
    lst = make_list("Оборудование отдела")
    unique = add_field(lst, "string", "Инвентарный номер", unique=True, code="inv")
    return lst, unique


# --- одна этикетка (FR-538) ----------------------------------------------------------------------------------

def test_label_shows_list_name_record_name_and_first_visible_unique_value():
    """FR-538: этикетка читающего — название списка, название записи, значение первого видимого уникального поля
    (как записано, не в нормализованном виде) и QR-код; корень страницы — `[data-lists-page="label"]`."""
    lst, _ = serial_list()
    record = make_record(lst, "Ноутбук бухгалтерии", {"inv": "Sn-A1b2"})
    reader = reader_of(lst)
    response = reader.client.get(label_path(lst, record))
    assert response.status_code == 200
    assert select(dom(response), data_lists_page="label"), "нет корня страницы этикетки"
    labels = labels_of(response)
    assert len(labels) == 1
    assert labels[0]["list"] == "Оборудование отдела"
    assert labels[0]["title"] == "Ноутбук бухгалтерии"
    assert labels[0]["value"] == "Sn-A1b2"
    assert labels[0]["url"] and labels[0]["src"].startswith(DATA_URI)


def test_label_takes_first_unique_field_by_field_order():
    """FR-538: значение берётся у первого по порядку полей уникального поля, а не у созданного первым."""
    lst = make_list("Лицензии отдела")
    created_first = add_field(lst, "string", "Серийный номер", unique=True, code="serial")
    created_second = add_field(lst, "string", "Номер договора", unique=True, code="contract")
    Field = support.model("lists.Field")
    Field.objects.filter(pk=created_second.pk).update(order=1)
    Field.objects.filter(pk=created_first.pk).update(order=2)
    record = make_record(lst, "Лицензия на офис", {"serial": "serial-value-9", "contract": "contract-value-7"})
    response = reader_of(lst).client.get(label_path(lst, record))
    assert response.status_code == 200
    labels = labels_of(response)
    assert len(labels) == 1 and labels[0]["value"] == "contract-value-7"
    assert "serial-value-9" not in response.content.decode()


def test_label_without_unique_field_or_with_empty_value_shows_record_number():
    """FR-538: нет уникального поля или его значение пусто — на этикетке «№ N» (номер записи в списке)."""
    plain = make_list("Без уникальных")
    add_field(plain, "string", "Заметка", code="note")
    make_record(plain, "Первая", {"note": "а"})
    second = make_record(plain, "Вторая", {"note": "б"})
    got = labels_of(reader_of(plain).client.get(label_path(plain, second)))
    assert len(got) == 1 and got[0]["value"] == f"№ {second.number}" and second.number == 2

    lst, _ = serial_list()
    empty = make_record(lst, "Без номера", {})
    got = labels_of(reader_of(lst).client.get(label_path(lst, empty)))
    assert len(got) == 1 and got[0]["value"] == f"№ {empty.number}"
    assert got[0]["title"] == "Без номера"


def test_label_hidden_unique_field_not_shown_next_unique_or_number_used():
    """FR-509, FR-538 (перечень V16): значение скрытого уникального поля на этикетке не показано — берётся следующее
    видимое уникальное поле, а если его нет — «№ N»."""
    lst = make_list("Подписи отдела")
    add_field(lst, "string", "Скрытый номер", unique=True, hidden=True, code="hid_no")
    add_field(lst, "string", "Видимый номер", unique=True, code="shown_no")
    record = make_record(lst, "Подпись директора", {"hid_no": "HID-4455", "shown_no": "vis-6677"})
    response = reader_of(lst).client.get(label_path(lst, record))
    assert response.status_code == 200
    got = labels_of(response)
    assert len(got) == 1 and got[0]["value"] == "vis-6677"
    assert "HID-4455" not in response.content.decode() and "hid-4455" not in response.content.decode().lower()

    only_hidden = make_list("Только скрытое")
    add_field(only_hidden, "string", "Скрытый номер", unique=True, hidden=True, code="hid")
    other = make_record(only_hidden, "Запись", {"hid": "ONLY-HIDDEN-12"})
    response = reader_of(only_hidden).client.get(label_path(only_hidden, other))
    assert response.status_code == 200
    got = labels_of(response)
    assert len(got) == 1 and got[0]["value"] == f"№ {other.number}"
    assert "only-hidden-12" not in response.content.decode().lower()


def test_label_available_for_archived_record():
    """FR-538 (спека, план: «запись в архиве — тоже»): этикетка записи в архиве печатается."""
    lst, _ = serial_list()
    record = make_record(lst, "Старый принтер", {"inv": "ARC-001"}, archived=True)
    response = reader_of(lst).client.get(label_path(lst, record))
    assert response.status_code == 200
    got = labels_of(response)
    assert len(got) == 1
    assert got[0]["title"] == "Старый принтер" and got[0]["value"] == "ARC-001"
    assert got[0]["url"] == card_address(lst, record)


def test_qr_link_of_archived_record_opens_card_with_archived_mark():
    """FR-538, FR-523: ссылка из QR записи в архиве открывает карточку с пометкой `[data-lists-archived]` «в архиве»;
    у записи не в архиве пометки нет."""
    lst, _ = serial_list()
    old = make_record(lst, "Списанный сервер", {"inv": "OLD-1"}, archived=True)
    live = make_record(lst, "Рабочий сервер", {"inv": "LIVE-1"})
    reader = reader_of(lst)
    old_url = labels_of(reader.client.get(label_path(lst, old)))[0]["url"]
    live_url = labels_of(reader.client.get(label_path(lst, live)))[0]["url"]
    assert old_url, "у этикетки нет адреса в QR"
    opened = reader.client.get(urlsplit(old_url).path)
    assert opened.status_code == 200
    page = dom(opened)
    assert select(page, data_lists_record=True), "открылась не карточка записи"
    marks = select(page, data_lists_archived=True)
    assert marks and "в архиве" in marks[0].text()
    live_page = reader.client.get(urlsplit(live_url).path)
    assert live_page.status_code == 200 and not select(dom(live_page), data_lists_archived=True)


# --- QR-код (FR-538, решение 10 задач) ----------------------------------------------------------------------

def test_qr_is_img_with_svg_base64_data_uri_and_data_qr_url_attribute_holding_card_address():
    """FR-538 (11.9): QR — `img[data-lists-qr]` с `src="data:image/svg+xml;base64,…"` (корректная base64, внутри SVG)
    и `data-qr-url` с абсолютным адресом карточки `PORTAL_URL/lists/<id>/<n>/`."""
    lst, _ = serial_list()
    record = make_record(lst, "Роутер", {"inv": "R-100"})
    response = reader_of(lst).client.get(label_path(lst, record))
    assert response.status_code == 200
    images = select(dom(response), "img", data_lists_qr=True)
    assert len(images) == 1
    image = images[0]
    assert image.attrs["data-qr-url"] == card_address(lst, record)
    src = image.attrs["src"]
    assert src.startswith(DATA_URI) and len(src) > len(DATA_URI)
    raw = base64.b64decode(src[len(DATA_URI):], validate=True)
    assert b"<svg" in raw[:500], "после base64 не SVG"


def test_qr_matches_qrcode_generation_of_portal_url_card_address():
    """FR-538 (решение 10 задач, факт T-6006): `src` совпадает побайтно с `qrcode.make(адрес, image_factory=
    SvgPathImage, box_size=10, border=4)` для адреса карточки; тот же результат даёт `labels.qr_data_uri`."""
    import qrcode
    from qrcode.image.svg import SvgPathImage

    from apps.lists.services import labels

    lst, _ = serial_list()
    record = make_record(lst, "Коммутатор", {"inv": "SW-7"})
    response = reader_of(lst).client.get(label_path(lst, record))
    assert response.status_code == 200
    got = labels_of(response)
    assert len(got) == 1
    url = got[0]["url"]
    assert url == f"{settings.PORTAL_URL}/lists/{lst.pk}/{record.number}/"
    out = io.BytesIO()
    qrcode.make(url, image_factory=SvgPathImage, box_size=10, border=4).save(out)
    expected = DATA_URI + base64.b64encode(out.getvalue()).decode("ascii")
    assert got[0]["src"] == expected
    assert labels.qr_data_uri(url) == expected


def test_qr_address_has_no_query_or_session_data():
    """FR-538: в адресе QR только `PORTAL_URL` и путь карточки — без строки запроса, фрагмента и сведений сеанса;
    параметры запроса страницы этикетки в адрес не попадают; `labels.card_url` даёт тот же адрес."""
    from apps.lists.services import labels

    lst, _ = serial_list()
    record = make_record(lst, "Сканер", {"inv": "SC-5"})
    reader = reader_of(lst)
    response = reader.client.get(label_path(lst, record) + "?utm=marker77&view=full")
    assert response.status_code == 200
    got = labels_of(response)
    assert len(got) == 1
    parts = urlsplit(got[0]["url"])
    assert parts.query == "" and parts.fragment == "" and "?" not in got[0]["url"] and "#" not in got[0]["url"]
    assert parts.path == f"/lists/{lst.pk}/{record.number}/"
    assert got[0]["url"] == card_address(lst, record) == labels.card_url(record)
    assert "marker77" not in got[0]["url"]
    cookies = [morsel.value for morsel in reader.client.cookies.values() if len(morsel.value) >= 16]
    assert cookies, "у вошедшего клиента должен быть cookie сеанса"
    assert not [value for value in cookies if value in got[0]["url"]]
    assert not [value for value in cookies if value in base64.b64decode(got[0]["src"][len(DATA_URI):]).decode("utf-8", "replace")]


def test_card_address_redirects_anonymous_to_login_and_back():
    """FR-538 (сценарий 3): не вошедший по адресу из QR попадает на вход с `next=<путь>` (и на странице этикетки тоже),
    после входа возвращается на карточку записи."""
    lst, _ = serial_list()
    record = make_record(lst, "Док-станция", {"inv": "DK-2"})
    role = factories.make_role()
    grant_list(lst, role, "read")
    user = support.make_employee(roles=[role])
    path = f"/lists/{lst.pk}/{record.number}/"
    for guarded in (label_path(lst, record), sheet_path(lst, [record.number])):
        gate = support.make_client(ip="198.51.100.141").get(guarded)
        assert gate.status_code == 302 and gate["Location"].startswith("/login/") and "next=" in gate["Location"]
    client = support.make_client(ip="198.51.100.140")
    gate = client.get(path)
    assert gate.status_code == 302 and gate["Location"].startswith("/login/") and "next=" in gate["Location"]
    first = client.post(gate["Location"], {"email": user.email, "password": user.test_password})
    assert first.status_code == 302 and first["Location"].endswith("/login/code/")
    second = client.post("/login/code/", {"code": support.current_code(user)})
    assert second.status_code == 302 and second["Location"] == path
    card = client.get(path)
    assert card.status_code == 200 and select(dom(card), data_lists_record=True)


def test_card_address_for_non_reader_is_404_like_missing_record():
    """FR-514, FR-538: вошедшему, не читающему список, адрес карточки отвечает 404, неотличимым от ответа для
    несуществующей записи и несуществующего списка (того же сотрудника); данных записи в ответе нет."""
    lst, _ = serial_list()
    record = make_record(lst, "Секретный проект", {"inv": "PRIVATE-77"})
    stranger = outsider()
    stray = stranger.client.get(f"/lists/{lst.pk}/{record.number}/")
    missing_number = stranger.client.get(f"/lists/{lst.pk}/{record.number + 40}/")
    missing_list = stranger.client.get(f"/lists/{lst.pk + 100000}/1/")
    assert stray.status_code == missing_number.status_code == missing_list.status_code == 404
    assert support.same_failure(stray, missing_number, missing_list)
    body = stray.content.decode()
    assert "Секретный проект" not in body and "PRIVATE-77" not in body and lst.name not in body
    other = make_list("Чужой список")
    grant = reader_of(other)
    assert grant.client.get(f"/lists/{lst.pk}/{record.number}/").status_code == 404, "читающий другой список"
    own = reader_of(lst)
    assert own.client.get(f"/lists/{lst.pk}/{record.number}/").status_code == 200


def test_label_for_non_reader_or_missing_record_returns_404():
    """FR-514, FR-538: этикетка не читающему список и этикетка несуществующей записи или списка — 404 без данных,
    ответы одного сотрудника неотличимы; читающему несуществующий номер — тоже 404."""
    lst, _ = serial_list()
    record = make_record(lst, "Секретный проект", {"inv": "PRIVATE-88"})
    stranger = outsider()
    stray = stranger.client.get(label_path(lst, record))
    missing = stranger.client.get(f"/lists/{lst.pk}/{record.number + 40}/label/")
    nowhere = stranger.client.get(f"/lists/{lst.pk + 100000}/1/label/")
    assert stray.status_code == missing.status_code == nowhere.status_code == 404
    assert support.same_failure(stray, missing, nowhere)
    body = stray.content.decode()
    assert "Секретный проект" not in body and "PRIVATE-88" not in body and "data-lists-label" not in body
    reader = reader_of(lst)
    assert reader.client.get(label_path(lst, record)).status_code == 200
    assert reader.client.get(f"/lists/{lst.pk}/{record.number + 40}/label/").status_code == 404
    assert reader.client.get(f"/lists/{lst.pk}/0/label/").status_code == 404


# --- лист этикеток (FR-539) -----------------------------------------------------------------------------------

def test_labels_sheet_renders_one_label_per_requested_number():
    """FR-539: `/lists/<id>/labels/?n=…` — `[data-lists-labels-sheet]` с одной `[data-lists-label]` на каждый
    запрошенный номер (и только на них), у каждой — своя запись и свой адрес в QR; класс печати `lists-labels`."""
    lst, _ = serial_list()
    records = [make_record(lst, f"Устройство {i}", {"inv": f"DEV-{i}"}) for i in range(1, 6)]
    wanted = [records[0], records[2], records[4]]
    reader = reader_of(lst)
    response = reader.client.get(sheet_path(lst, [r.number for r in wanted]))
    assert response.status_code == 200
    page = dom(response)
    assert select(page, data_lists_page="labels")
    sheets = select(page, data_lists_labels_sheet=True)
    assert len(sheets) == 1
    inside = select(sheets[0], data_lists_label=True)
    assert len(inside) == 3
    got = labels_of(response)
    assert sorted(item["url"] for item in got) == sorted(card_address(lst, r) for r in wanted)
    by_url = {item["url"]: item for item in got}
    for record in wanted:
        item = by_url[card_address(lst, record)]
        assert item["title"] == record.title and item["list"] == lst.name
        assert item["value"] == record.values["inv"] and item["src"].startswith(DATA_URI)
    # класс печати — у корня листа `[data-lists-labels-sheet]` (ответ 52, CONTRACT-006, 11.9, 15.3)
    assert "lists-labels" in sheets[0].attrs.get("class", "").split(), "нет класса печати `lists-labels` у листа"


def test_labels_sheet_100_numbers_accepted_101_refused():
    """FR-539, FR-546: 100 номеров — 100 этикеток без отказа; 101 номер — 200 с `[role=alert][data-code=
    "labels_too_many"]` «Не больше 100 записей» и без единой этикетки."""
    lst = make_list("Много записей")
    author = support.make_employee()
    records = [make_record(lst, f"Запись {i}", created_by=author) for i in range(1, 102)]
    numbers = [r.number for r in records]
    reader = reader_of(lst)
    accepted = reader.client.get(sheet_path(lst, numbers[:100]))
    assert accepted.status_code == 200
    assert len(labels_of(accepted)) == 100 and not alerts(accepted, "labels_too_many")
    refused = reader.client.get(sheet_path(lst, numbers))
    assert refused.status_code == 200
    found = alerts(refused, "labels_too_many")
    assert found and "Не больше 100 записей" in found[0].text()
    assert labels_of(refused) == []


def test_labels_sheet_prints_archived_and_silently_skips_missing_and_purged_numbers():
    """FR-514, FR-539: запись в архиве печатается; номера несуществующих, удалённых навсегда записей и номер,
    которого нет в этом списке (есть только в другом), пропускаются молча — без отказа и без чужих данных."""
    lst, _ = serial_list()
    live = make_record(lst, "Живая запись", {"inv": "LIVE-9"})
    old = make_record(lst, "Архивная запись", {"inv": "OLD-9"}, archived=True)
    purged = make_record(lst, "Удалённая запись", {"inv": "GONE-9"})
    support.model("lists.Record").objects.filter(pk=purged.pk).delete()
    elsewhere = make_list("Другой список")
    for i in range(1, 8):
        make_record(elsewhere, f"Чужая запись {i}", created_by=live.created_by)
    reader = reader_of(lst)
    response = reader.client.get(sheet_path(lst, [live.number, old.number, purged.number, 999, 7]))
    assert response.status_code == 200
    page = dom(response)
    assert not select(page, role="alert")
    got = labels_of(response)
    assert sorted(item["title"] for item in got) == ["Архивная запись", "Живая запись"]
    body = response.content.decode()
    assert "Удалённая запись" not in body and "GONE-9" not in body and "Чужая запись" not in body
    assert {item["url"] for item in got} == {card_address(lst, live), card_address(lst, old)}


def test_labels_sheet_for_non_reader_returns_404():
    """FR-514, FR-539: лист этикеток не читающему список — 404, неотличимый от ответа для несуществующего списка,
    без названий и значений записей."""
    lst, _ = serial_list()
    record = make_record(lst, "Закрытая запись", {"inv": "CLOSED-5"})
    stranger = outsider()
    stray = stranger.client.get(sheet_path(lst, [record.number]))
    nowhere = stranger.client.get(f"/lists/{lst.pk + 100000}/labels/?n={record.number}")
    assert stray.status_code == nowhere.status_code == 404
    assert support.same_failure(stray, nowhere)
    body = stray.content.decode()
    assert "Закрытая запись" not in body and "CLOSED-5" not in body and "data-lists-label" not in body
    assert reader_of(lst).client.get(sheet_path(lst, [record.number])).status_code == 200


# --- разметка и печать (FR-538, FR-539, решение 59 задач) ---------------------------------------------------

def test_label_pages_have_no_inline_style_or_event_attributes():
    """FR-538, FR-539 (NFR-506, CSP): ни одна страница этикеток — одна этикетка, лист, этикетка записи в архиве —
    не содержит `style=` и атрибутов `on…=`."""
    lst, _ = serial_list()
    first = make_record(lst, "Первая", {"inv": "A-1"})
    second = make_record(lst, "Вторая", {"inv": "A-2"}, archived=True)
    reader = reader_of(lst)
    for path in (label_path(lst, first), label_path(lst, second), sheet_path(lst, [first.number, second.number])):
        response = reader.client.get(path)
        assert response.status_code == 200, path
        assert labels_of(response), f"{path}: нет этикеток"
        assert no_inline(response.content.decode()), f"{path}: style= или on…="


def test_label_pages_link_labels_css_and_other_list_pages_do_not():
    """FR-538, FR-539 (решение 59 задач): `static/lists/labels.css` подключён `<link rel="stylesheet">` на `/label/`
    и `/labels/` и только на них; остальные страницы списков (главная, таблица, карточка, история, правка) его
    не подключают."""
    link = re.compile(r"<link\b[^>]*\brel=\"stylesheet\"[^>]*\bhref=\"[^\"]*lists/labels(\.[\w-]+)?\.css[^\"]*\"|"
                      r"<link\b[^>]*\bhref=\"[^\"]*lists/labels(\.[\w-]+)?\.css[^\"]*\"[^>]*\brel=\"stylesheet\"")
    lst, _ = serial_list()
    record = make_record(lst, "Проектор", {"inv": "PR-3"})
    editor = support_lists.as_editor(lst)
    pages = support_lists.list_pages(lst, record)
    label_pages = {label_path(lst, record), sheet_path(lst, [record.number])}
    assert set(pages) >= label_pages
    for path in sorted(label_pages):
        response = editor.client.get(path)
        assert response.status_code == 200, path
        assert link.search(response.content.decode()), f"{path}: нет <link> на labels.css"
    others = 0
    for path in pages:
        if path in label_pages:
            continue
        response = editor.client.get(path)
        if response.status_code != 200:
            continue
        others += 1
        assert "labels.css" not in response.content.decode(), f"{path}: labels.css не для этой страницы"
    assert others >= 5, "проверено слишком мало прочих страниц списков"


def test_labels_css_a4_page_margins_3x7_grid_and_print_media_hides_app_top_bar_and_app_menu():
    """FR-538, FR-539 (11.9): `static/lists/labels.css` — `@page { size: A4; margin: 10mm 9mm }`, этикетка 63,5 × 38,1 мм
    в сетке из трёх колонок, `break-inside: avoid`, `@media print` скрывает `#top-bar`, `.app-top-bar`,
    `#main-menu`, `.app-menu`."""
    path = support.BACKEND_DIR / "static" / "lists" / "labels.css"
    assert path.is_file(), "нет static/lists/labels.css"
    css = re.sub(r"/\*.*?\*/", "", path.read_text(encoding="utf-8"), flags=re.S)
    flat = " ".join(css.split())
    page = " ".join(css_block(css, "@page").split()).lower()
    assert re.search(r"size:\s*a4(\s+portrait)?\s*;?", page), f"@page без size: A4: {page!r}"
    assert re.search(r"margin:\s*10mm\s+9mm\s*;?", page), f"@page без margin: 10mm 9mm: {page!r}"
    assert "63.5mm" in flat and "38.1mm" in flat, "нет размера этикетки 63.5 × 38.1 мм"
    three = re.search(r"repeat\(\s*3\s*,", flat) or re.search(r"63\.5mm\s+63\.5mm\s+63\.5mm", flat) \
        or ("flex-wrap" in flat and "width: 63.5mm" in flat)
    assert three, "нет сетки из трёх колонок (repeat(3, …), три ширины 63.5mm или flex-wrap с width: 63.5mm)"
    assert "break-inside: avoid" in flat
    printing = " ".join(css_block(css, "@media print").split())
    assert printing, "нет блока @media print"
    for selector in ("#top-bar", ".app-top-bar", "#main-menu", ".app-menu"):
        assert selector in printing, f"@media print не скрывает {selector}"
    assert re.search(r"display:\s*none", printing)
    # Группировка селекторов контрактом не задана (11.9): для каждого ищется своё правило со скрытием.
    rules = [rule.split("{", 1) for rule in printing.split("}") if "{" in rule]
    for selector in ("#top-bar", ".app-top-bar", "#main-menu", ".app-menu"):
        mention = re.compile(r"(?<![\w-])" + re.escape(selector) + r"(?![\w-])")
        hiding = [body for head, body in rules if mention.search(head) and re.search(r"display:\s*none", body)]
        assert hiding, f"в @media print нет правила с {selector} и display: none"


def test_label_and_labels_sheet_not_written_to_audit_log():
    """FR-542: открытие этикетки, листа этикеток и карточки по адресу из QR в журнал ничего не пишет."""
    lst, _ = serial_list()
    live = make_record(lst, "Монитор", {"inv": "MN-4"})
    old = make_record(lst, "Старый монитор", {"inv": "MN-1"}, archived=True)
    reader = reader_of(lst)
    Event = support.model("core.AuditEvent")
    before = list(Event.objects.order_by("id").values_list("id", flat=True))
    for path in (label_path(lst, live), label_path(lst, old), sheet_path(lst, [live.number, old.number]),
                 f"/lists/{lst.pk}/{live.number}/"):
        assert reader.client.get(path).status_code == 200, path
    after = list(Event.objects.order_by("id").values_list("id", flat=True))
    assert after == before, [e.action for e in Event.objects.exclude(id__in=before)]
