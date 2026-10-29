"""T-6150: сценарий 11 — этикетка с QR-кодом, лист этикеток на A4, печать (FR-514, FR-521, FR-538, FR-539, FR-546,
NFR-507).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-006.md 10.2, 11.3, 11.5, 11.9, 12, 15.3, 15.4):
- управляющий — администратор круга `admin_page`; читающий список — `helpers_lists.make_list_reader` (своя роль без прав в
  наборе «Читают»); не читающий — сотрудник с новой ролью без прав на списки (`make_list_role`): «Сотрудник ИТ» читает
  шесть стартовых списков, но не списки, заведённые тестом;
- каждый тест заводит свои списки с уникальными названиями, стартовых не трогает (решение 56); общих настроек не
  меняет; команд стенда и `stand_shell` в файле нет;
- QR (решение 10): SVG из `src` сверяется с генерацией `qrcode` для адреса карточки (`helpers_lists.qr_matches`) и
  адрес читается из `data-qr-url`; сам код не декодируется;
- печать: `page.emulate_media(media="print")` и, в Chromium-браузерах круга (chromium, Edge, Яндекс Браузер), настоящий
  PDF страницы с размером и полями из `@page` (`prefer_css_page_size`); у Firefox PDF нет — там только раскладка;
- пункты сценария: 1 — этикетка, 2 — вошедший читающий, 3 — не вошедший, 4 — вошедший не читающий, 5 — несколько
  этикеток, 6 — больше 100, 7 — печать.
"""
import re
from urllib.parse import parse_qs, urlparse

from playwright.sync_api import expect

from tests.e2e import helpers
from tests.e2e.helpers_lists import (
    add_field, create_list, create_record, field_codes, make_list_reader, make_list_role,
    open_narrow, open_record, page_fits, qr_image_bytes, qr_matches, qr_svg_variants, status_of, unique_list_name,
    unique_word)

CHROMIUM_FAMILY = ("chromium", "edge", "yandex")
MM = 96 / 25.4                          # пикселей CSS в миллиметре: 63,5 × 38,1 мм — 240 × 144 пикселей
CELL_W, CELL_H = 63.5 * MM, 38.1 * MM
LABEL = "[data-lists-label]"
SHEET = "[data-lists-labels-sheet]"
QR = "img[data-lists-qr]"
HIDDEN_BY_PRINT = ("#top-bar", ".app-top-bar", "#main-menu", ".app-menu")  # CONTRACT-006 11.9, решение 59 задач


# --- Подготовка и разбор страниц -------------------------------------------------------------------------------

def _card_path(list_id, number) -> str:
    return f"/lists/{list_id}/{number}/"


def _expected_qr_url(portal_url: str, list_id, number) -> str:
    """Адрес карточки в QR (5.7): `PORTAL_URL` без завершающей «/» + `/lists/<id>/<n>/`, без строки запроса."""
    return portal_url.rstrip("/") + _card_path(list_id, number)


def _same_card_url(actual, portal_url: str, list_id, number) -> bool:
    """`actual` — адрес карточки записи из QR: то же имя хоста, что у адреса круга (conftest: имя хоста стенда — как в
    `PORTAL_URL`), путь `/lists/<id>/<n>/`, без строки запроса и якоря. Схему и порт `PORTAL_URL` стенда приёмка не
    знает (контракт их равенства адресу круга не называет), поэтому они не сравниваются (R-1-E3, находка 10)."""
    got, want = urlparse(actual or ""), urlparse(_expected_qr_url(portal_url, list_id, number))
    return (got.scheme in ("http", "https") and got.hostname == want.hostname and got.path == want.path
            and not got.query and not got.fragment)


def _sibling_card_url(qr_url: str, list_id, number) -> str:
    """Адрес другой карточки на той же основе (схема, хост, порт), что адрес из QR `qr_url`."""
    return urlparse(qr_url)._replace(path=_card_path(list_id, number), query="", fragment="").geturl()


def _list_with_unique_fields(page, prefix="Этикетки"):
    """Список с тремя строковыми полями: «Модель» (не уникальное), «Инвентарный номер» и «Серийный номер» (уникальные).
    Возвращает `(номер списка, название, код неуникального, [коды уникальных по порядку сетки полей])`."""
    name = unique_list_name(prefix)
    list_id = create_list(page, name)
    model = add_field(page, list_id, "Модель", "string")
    add_field(page, list_id, "Инвентарный номер", "string", unique=True)
    add_field(page, list_id, "Серийный номер", "string", unique=True)
    order = field_codes(page, list_id)
    uniques = [code for code in order if code not in ("title", model)]
    assert len(uniques) == 2, f"ожидались два уникальных поля, коды сетки: {order}"
    return list_id, name, model, uniques


def _open_label(page, list_id, number) -> None:
    """Страница этикетки записи `/lists/<id>/<n>/label/`: ждёт `[data-lists-page="label"]` и этикетку."""
    page.goto(f"/lists/{list_id}/{number}/label/")
    expect(page.locator('[data-lists-page="label"]')).to_be_visible()
    expect(page.locator(LABEL)).to_have_count(1)


def _open_sheet(page, list_id, numbers) -> None:
    """Лист этикеток `/lists/<id>/labels/?n=…&n=…` прямым адресом: ждёт `[data-lists-labels-sheet]`."""
    page.goto(f"/lists/{list_id}/labels/?" + "&".join(f"n={n}" for n in numbers))
    expect(page.locator('[data-lists-page="labels"]')).to_be_visible()
    expect(page.locator(SHEET)).to_have_count(1)


def _label_texts(page) -> dict:
    """Единственная этикетка страницы: `{list, title, value, qr_url}`."""
    label = page.locator(LABEL)
    return {
        "list": label.locator('[data-field="list"]').inner_text().strip(),
        "title": label.locator('[data-field="title"]').inner_text().strip(),
        "value": label.locator('[data-field="value"]').inner_text().strip(),
        "qr_url": label.locator(QR).get_attribute("data-qr-url"),
    }


def _sheet_labels(page) -> list:
    """Все этикетки листа: `[{title, value, qr_url, matches}]` в порядке разметки (порядок тесты не сравнивают)."""
    result = []
    for label in page.locator(LABEL).all():
        img = label.locator(QR)
        result.append({
            "title": label.locator('[data-field="title"]').inner_text().strip(),
            "value": label.locator('[data-field="value"]').inner_text().strip(),
            "qr_url": img.get_attribute("data-qr-url"),
            "matches": qr_matches(img),
        })
    return result


def _is_number_mark(text: str, number) -> bool:
    """Значение этикетки без уникального поля — «№ N» (12.4); пробелы по краям и между знаком и числом не важны."""
    return re.fullmatch(rf"\s*№\s*{number}\s*", text) is not None


def _own_page_ready(page) -> None:
    """Страница портала с верхней панелью (для выхода и проверки печати)."""
    page.goto("/lists/")
    expect(page.locator("#top-bar")).to_be_visible()


def _boxes(page) -> list:
    """Прямоугольники всех этикеток листа в пикселях CSS: `[{x, y, w, h}]` (по `getBoundingClientRect`, с прокруткой)."""
    return page.locator(LABEL).evaluate_all(
        "els => els.map(e => { const r = e.getBoundingClientRect(); "
        "return {x: r.left + window.scrollX, y: r.top + window.scrollY, w: r.width, h: r.height}; })")


def _clusters(values, tolerance=2.0) -> list:
    """Группы близких чисел (разброс до `tolerance`): возвращает среднее каждой группы по возрастанию."""
    groups = []
    for value in sorted(values):
        if groups and value - groups[-1][-1] <= tolerance:
            groups[-1].append(value)
        else:
            groups.append([value])
    return [sum(group) / len(group) for group in groups]


def _hidden_in_print(page, selector: str) -> bool:
    """Все элементы по `selector` (если они есть) скрыты: `display: none` или нулевой размер."""
    return page.locator(selector).evaluate_all(
        "els => els.every(e => getComputedStyle(e).display === 'none' || "
        "(e.getBoundingClientRect().width === 0 && e.getBoundingClientRect().height === 0))")


def _pdf_pages(data: bytes) -> int:
    """Число страниц PDF (Chromium): записи `/Type /Page` без `/Pages`; если их не нашли — наибольший `/Count`."""
    pages = len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", data))
    if pages:
        return pages
    counts = [int(n) for n in re.findall(rb"/Count\s+(\d+)", data)]
    assert counts, "в PDF нет ни страниц, ни счётчика страниц"
    return max(counts)


def _log_in_after_redirect(page, account) -> None:
    """Входит на странице входа, открытой переходом по защищённому адресу: почта, пароль, код TOTP (как
    `helpers.sign_in`, но без нового перехода на `/login/`, чтобы не потерять `next`)."""
    page.fill("input[name=email]", account.email)
    page.fill("input[name=password]", account.password)
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/login/code/"))
    page.fill("input[name=code]", helpers.totp_for(account.totp_secret))
    page.click("button[type=submit]")


# --- Тесты ---------------------------------------------------------------------------------------------------

def test_l11_label_page_shows_list_title_record_title_first_unique_value_and_qr_code(admin_page, employee):
    """Сценарий 11, п. 1: читающий список нажимает «Этикетка» на карточке — страница печати показывает название списка,
    название записи, значение ПЕРВОГО уникального поля (не неуникального поля перед ним и не второго уникального) и
    QR-код (FR-538)."""
    list_id, list_name, model, (first_unique, second_unique) = _list_with_unique_fields(admin_page)
    title = f"Ноутбук {unique_word()}"
    model_value, first_value, second_value = unique_word("mod"), unique_word("inv"), unique_word("ser")
    number = create_record(admin_page, list_id, title, {
        model: model_value, first_unique: first_value, second_unique: second_value})
    reader = make_list_reader(employee, admin_page, list_id)

    # п. 1: читающий на карточке нажимает «Этикетка»
    open_record(reader.page, list_id, number)
    button = reader.page.locator('a[data-action="record-label"]')
    expect(button).to_have_text("Этикетка")
    expect(button).to_have_attribute("href", f"/lists/{list_id}/{number}/label/")
    button.click()
    reader.page.wait_for_url(re.compile(rf"/lists/{list_id}/{number}/label/$"))
    expect(reader.page.locator('[data-lists-page="label"]')).to_be_visible()

    # п. 1: название списка, название записи, значение первого уникального поля, QR-код
    expect(reader.page.locator(LABEL)).to_have_count(1)
    texts = _label_texts(reader.page)
    assert texts["list"] == list_name, "на этикетке нет названия списка"
    assert texts["title"] == title, "на этикетке нет названия записи"
    assert texts["value"] == first_value, \
        f"значение этикетки не значение первого уникального поля: {texts['value']!r}"
    assert model_value not in texts["value"] and second_value not in texts["value"]
    img = reader.page.locator(LABEL).locator(QR)
    expect(img).to_be_visible()
    expect(img).to_have_attribute("src", re.compile(r"^data:image/svg\+xml;base64,[A-Za-z0-9+/=]+$"))


def test_l11_label_of_record_without_unique_value_shows_record_number(admin_page):
    """Сценарий 11, п. 1: у записи, у которой первое уникальное поле пусто, и у записи списка без уникальных полей
    этикетка показывает «№ N» (номер записи), а не чужое значение (FR-538)."""
    list_id, list_name, _model, (unique_code, _second) = _list_with_unique_fields(admin_page)
    empty_title, filled_title = f"Монитор {unique_word()}", f"Монитор {unique_word()}"
    filled_value = unique_word("inv")
    empty_number = create_record(admin_page, list_id, empty_title)
    filled_number = create_record(admin_page, list_id, filled_title, {unique_code: filled_value})

    # п. 1: уникальное поле пусто — «№ N» с номером этой записи
    _open_label(admin_page, list_id, empty_number)
    texts = _label_texts(admin_page)
    assert texts["title"] == empty_title and texts["list"] == list_name
    assert _is_number_mark(texts["value"], empty_number), f"вместо «№ {empty_number}» показано {texts['value']!r}"
    assert filled_value not in admin_page.locator(LABEL).inner_text()

    # соседняя запись с заполненным значением показывает значение, а не номер
    _open_label(admin_page, list_id, filled_number)
    assert _label_texts(admin_page)["value"] == filled_value

    # п. 1: в списке вообще без уникальных полей — тоже «№ N»
    plain_id = create_list(admin_page, unique_list_name("Этикетки без уникальных"))
    plain_title = f"Стол {unique_word()}"
    plain_number = create_record(admin_page, plain_id, plain_title)
    _open_label(admin_page, plain_id, plain_number)
    texts = _label_texts(admin_page)
    assert texts["title"] == plain_title
    assert _is_number_mark(texts["value"], plain_number), f"показано {texts['value']!r}"


def test_l11_qr_svg_equals_generated_for_card_url_and_data_qr_url_holds_card_url(admin_page, portal_url):
    """Сценарий 11, п. 1–2 (решение 10 задач): `data-qr-url` — адрес карточки записи (адрес портала, номер списка и
    записи, без строки запроса), `src` — SVG в base64, побайтно равный генерации `qrcode` для этого адреса; чужой адрес
    давал бы другие байты (FR-538)."""
    list_id, _name, _model, (unique_code, _second) = _list_with_unique_fields(admin_page)
    number = create_record(admin_page, list_id, f"Принтер {unique_word()}", {unique_code: unique_word("inv")})
    other = create_record(admin_page, list_id, f"Принтер {unique_word()}", {unique_code: unique_word("inv")})

    _open_label(admin_page, list_id, number)
    img = admin_page.locator(LABEL).locator(QR)
    qr_url = img.get_attribute("data-qr-url")
    assert _same_card_url(qr_url, portal_url, list_id, number), f"data-qr-url — не адрес карточки записи: {qr_url}"
    assert qr_matches(img), "SVG картинки не равен генерации qrcode для data-qr-url"
    assert qr_image_bytes(img) in qr_svg_variants(qr_url), "SVG не равен генерации qrcode для адреса карточки"
    other_url = _sibling_card_url(qr_url, list_id, other)
    first_bytes = qr_image_bytes(img)  # локатор ленивый: после перехода он указал бы на картинку другой записи
    assert first_bytes not in qr_svg_variants(other_url), "QR одинаков у разных записей"

    # у другой записи — свой адрес (та же основа, свой путь) и свой рисунок
    _open_label(admin_page, list_id, other)
    img_other = admin_page.locator(LABEL).locator(QR)
    assert img_other.get_attribute("data-qr-url") == other_url
    assert qr_matches(img_other)
    assert qr_image_bytes(img_other) != first_bytes


def test_l11_qr_url_opened_by_logged_in_reader_shows_record_card(admin_page, employee):
    """Сценарий 11, п. 2: адрес из QR-кода (`data-qr-url`) открывает вошедший читающий список — карточка этой записи
    (FR-538)."""
    list_id, _name, _model, (unique_code, _second) = _list_with_unique_fields(admin_page)
    title, value = f"Сервер {unique_word()}", unique_word("inv")
    number = create_record(admin_page, list_id, title, {unique_code: value})
    reader = make_list_reader(employee, admin_page, list_id)

    _open_label(reader.page, list_id, number)
    qr_url = reader.page.locator(LABEL).locator(QR).get_attribute("data-qr-url")
    assert qr_url.endswith(_card_path(list_id, number))

    # п. 2: «сканирование» — переход по адресу из QR вошедшим читающим
    reader.page.goto(qr_url)
    reader.page.wait_for_url(re.compile(rf"/lists/{list_id}/{number}/$"))
    expect(reader.page.locator('[data-lists-page="record"]')).to_be_visible()
    expect(reader.page.locator("[data-lists-record]")).to_contain_text(title)
    expect(reader.page.locator("[data-lists-record]")).to_contain_text(value)


def test_l11_qr_url_opened_without_login_leads_to_login_and_back_to_card_by_next(admin_page, employee, portal_url):
    """Сценарий 11, п. 3: тот, кто не вошёл, по адресу из QR попадает на вход с `next` на карточку, после входа
    открывается карточка записи (FR-538)."""
    list_id, _name, _model, (unique_code, _second) = _list_with_unique_fields(admin_page)
    title = f"Сервер {unique_word()}"
    number = create_record(admin_page, list_id, title, {unique_code: unique_word("inv")})
    reader = make_list_reader(employee, admin_page, list_id)
    page = reader.page
    _open_label(page, list_id, number)
    qr_url = page.locator(LABEL).locator(QR).get_attribute("data-qr-url")
    assert _same_card_url(qr_url, portal_url, list_id, number), f"data-qr-url — не адрес карточки: {qr_url}"

    # п. 3: тот же человек, но не вошедший (выход), открывает адрес из QR
    _own_page_ready(page)
    helpers.sign_out(page)
    page.goto(qr_url)
    page.wait_for_url(re.compile(r"/login/"))
    assert parse_qs(urlparse(page.url).query).get("next") == [_card_path(list_id, number)], \
        f"в адресе входа нет next на карточку: {page.url}"
    expect(page.locator("[data-lists-record]")).to_have_count(0)
    expect(page.locator("input[name=email]")).to_be_visible()

    # п. 3: вход — и открывается карточка записи
    _log_in_after_redirect(page, reader)
    page.wait_for_url(re.compile(rf"/lists/{list_id}/{number}/$"))
    expect(page.locator("[data-lists-record]")).to_contain_text(title)


def test_l11_qr_url_opened_by_employee_not_reading_list_gives_same_answer_as_missing_record(
        admin_page, employee, portal_url):
    """Сценарий 11, п. 4: вошедший, не читающий список, по адресу из QR, по адресу этикетки и листа получает 404 — тот
    же ответ (статус и видимый текст), что на несуществующую запись и несуществующий список; ни названия записи,
    ни значения, ни «Запись удалена» там нет, то есть существование записи не выдаётся (FR-514, FR-538)."""
    list_id, list_name, _model, (unique_code, _second) = _list_with_unique_fields(admin_page)
    title, value = f"Секретный сервер {unique_word()}", unique_word("inv")
    number = create_record(admin_page, list_id, title, {unique_code: value})
    _open_label(admin_page, list_id, number)
    qr_url = admin_page.locator(LABEL).locator(QR).get_attribute("data-qr-url")
    assert _same_card_url(qr_url, portal_url, list_id, number), f"data-qr-url — не адрес карточки: {qr_url}"
    outsider = employee(role=make_list_role(admin_page)[1])
    page = outsider.page

    def answer(url: str, mask: tuple = ()):
        # сравнение 404 (CONTRACT-006, 15.5 п. 11): нейтральная страница забирает ожидающие всплывающие сообщения,
        # затем — текст области содержимого `main#content` без `.alert` (меню и счётчики оболочки не сравниваются)
        page.goto("/me/")
        response = page.goto(url)
        text = page.locator("main#content").evaluate(
            "el => { const c = el.cloneNode(true); c.querySelectorAll('.alert').forEach(a => a.remove());"
            " return c.textContent.replace(/\\s+/g, ' ').trim(); }")
        for part in mask:
            text = text.replace(part, "<адрес>")
        return response.status, text

    # п. 4: адрес из QR — как у несуществующей записи того же списка и несуществующего списка
    missing_number = number + 500
    nowhere = list_id + "00000"
    real = answer(qr_url, (_card_path(list_id, number), qr_url))
    same_list_missing = answer(_sibling_card_url(qr_url, list_id, missing_number),
                               (_card_path(list_id, missing_number),))
    no_list = answer(_sibling_card_url(qr_url, nowhere, 1), (_card_path(nowhere, 1),))
    assert real[0] == 404, f"не читающему открылась карточка или не 404: {real[0]}"
    assert real == same_list_missing == no_list, "ответ не читающему отличается от ответа на несуществующую запись"
    for secret in (title, value, list_name, "Запись удалена"):
        assert secret not in real[1], f"в ответе не читающему есть {secret!r}"
    expect(page.locator("[data-lists-record]")).to_have_count(0)

    # то же для страниц этикеток: статус как у несуществующих
    for path in (f"/lists/{list_id}/{number}/label/", f"/lists/{list_id}/labels/?n={number}"):
        assert status_of(page, path) == 404, f"{path}: не читающему не 404"
    assert status_of(page, f"/lists/{list_id}/{missing_number}/label/") == 404
    label_answer = answer(f"/lists/{list_id}/{number}/label/", (f"/lists/{list_id}/{number}/label/",))
    assert title not in label_answer[1] and value not in label_answer[1] and "Запись удалена" not in label_answer[1]


def test_l11_labels_for_checked_table_rows_show_several_labels_on_one_a4_sheet(admin_page, employee):
    """Сценарий 11, п. 5: читающий отмечает три записи из четырёх в таблице и нажимает «Этикетки» — одна страница
    (один лист) с тремя этикетками, у каждой своё название, значение уникального поля и QR на свою карточку;
    неотмеченной записи нет; в печати три этикетки стоят в один ряд на одном листе (FR-521, FR-539)."""
    list_id, _name, _model, (unique_code, _second) = _list_with_unique_fields(admin_page)
    records = {}
    for i in range(4):
        title, value = f"Телефон {i} {unique_word()}", unique_word("inv")
        records[create_record(admin_page, list_id, title, {unique_code: value})] = (title, value)
    numbers = sorted(records)
    checked, skipped = numbers[:3], numbers[3]
    reader = make_list_reader(employee, admin_page, list_id)
    page = reader.page

    # п. 5: таблица, три отмеченные строки, «Этикетки»
    page.goto(f"/lists/{list_id}/")
    expect(page.locator('[data-lists-page="grid"]')).to_be_visible()
    for n in checked:
        row = page.locator(f'tr[data-record-number="{n}"]')
        expect(row).to_have_count(1)
        row.locator("input[data-lists-row-check]").check()
    button = page.locator('button[data-action="bulk-labels"]')
    expect(button).to_have_text("Этикетки")
    button.click()
    page.wait_for_url(re.compile(rf"/lists/{list_id}/labels/\?"))
    assert sorted(int(n) for n in parse_qs(urlparse(page.url).query)["n"]) == checked, \
        "в адресе листа не те номера, что отмечены"

    # п. 5: один лист, три этикетки со своими данными
    expect(page.locator('[data-lists-page="labels"]')).to_be_visible()
    expect(page.locator(SHEET)).to_have_count(1)
    expect(page.locator(LABEL)).to_have_count(3)
    shown = {item["title"]: item for item in _sheet_labels(page)}
    assert set(shown) == {records[n][0] for n in checked}, "на листе не те записи"
    assert records[skipped][0] not in shown
    for n in checked:
        title, value = records[n]
        assert shown[title]["value"] == value
        assert shown[title]["qr_url"].endswith(_card_path(list_id, n))
        assert shown[title]["matches"], f"QR записи №{n} не равен генерации для её адреса"

    # п. 5 (FR-539): на листе A4 при печати — три этикетки в одном ряду, один под другим не стоят
    page.emulate_media(media="print")
    boxes = _boxes(page)
    assert len(_clusters([b["y"] for b in boxes])) == 1, f"три этикетки не в одном ряду листа: {boxes}"
    assert len(_clusters([b["x"] for b in boxes])) == 3


def test_l11_labels_for_over_100_records_are_refused_with_limit(admin_page):
    """Сценарий 11, п. 6: «Этикетки» при отмеченных 101 номере — отказ «Не больше 100 записей» без этикеток; ровно
    100 номеров (несуществующие пропускаются молча) этикетки показывает (FR-539, FR-546)."""
    list_id, _name, _model, (unique_code, _second) = _list_with_unique_fields(admin_page)
    title, value = f"Сканер {unique_word()}", unique_word("inv")
    number = create_record(admin_page, list_id, title, {unique_code: value})

    def press_with_extra(extra: int) -> None:
        """Отмечает строку записи и добавляет в ту же форму ещё `extra` номеров отмеченных записей (таблица держит
        50 строк на странице, 101 строку отметить нельзя), затем нажимает «Этикетки»."""
        admin_page.goto(f"/lists/{list_id}/")
        expect(admin_page.locator('[data-lists-page="grid"]')).to_be_visible()
        admin_page.locator(f'tr[data-record-number="{number}"] input[data-lists-row-check]').check()
        button = admin_page.locator('button[data-action="bulk-labels"]')
        button.evaluate(
            """(b, count) => { for (let i = 0; i < count; i++) { const h = document.createElement('input');
            h.type = 'hidden'; h.name = 'n'; h.value = String(100000 + i); b.form.appendChild(h); } }""", extra)
        button.click()
        admin_page.wait_for_url(re.compile(rf"/lists/{list_id}/labels/\?"))

    # п. 6, граница: 100 номеров — не отказ, этикетка одной существующей записи, остальные пропущены молча
    press_with_extra(99)
    assert len(parse_qs(urlparse(admin_page.url).query)["n"]) == 100
    expect(admin_page.locator('[role=alert][data-code="labels_too_many"]')).to_have_count(0)
    expect(admin_page.locator(LABEL)).to_have_count(1)
    assert _label_texts(admin_page)["title"] == title

    # п. 6: 101 номер — отказ с пределом, этикеток нет
    press_with_extra(100)
    assert len(parse_qs(urlparse(admin_page.url).query)["n"]) == 101
    alert = admin_page.locator('[role=alert][data-code="labels_too_many"]')
    expect(alert).to_be_visible()
    expect(alert).to_contain_text("Не больше 100 записей")
    expect(admin_page.locator(LABEL)).to_have_count(0)


def test_l11_print_media_shows_only_labels_without_menu_and_panels(admin_page):
    """Сценарий 11, п. 7: на экране верхняя панель видна, а при печати (media print) на странице этикетки и на листе
    этикеток панель и меню скрыты, этикетки остаются видны (FR-538)."""
    list_id, _name, _model, (unique_code, _second) = _list_with_unique_fields(admin_page)
    numbers = [create_record(admin_page, list_id, f"Мышь {i} {unique_word()}", {unique_code: unique_word("inv")})
               for i in range(2)]

    for opener, hook in ((lambda: _open_label(admin_page, list_id, numbers[0]), "label"),
                         (lambda: _open_sheet(admin_page, list_id, numbers), "labels")):
        admin_page.emulate_media(media="screen")
        opener()
        expect(admin_page.locator("#top-bar")).to_be_visible()

        # п. 7: печать средствами браузера
        admin_page.emulate_media(media="print")
        expect(admin_page.locator(f'[data-lists-page="{hook}"]')).to_be_visible()
        for label in admin_page.locator(LABEL).all():
            expect(label).to_be_visible()
            expect(label.locator(QR)).to_be_visible()
        for selector in HIDDEN_BY_PRINT:
            assert _hidden_in_print(admin_page, selector), f"страница «{hook}»: при печати виден {selector}"
    admin_page.emulate_media(media="screen")


def test_l11_print_sheet_places_21_labels_in_3_by_7_grid_on_a4(admin_page, browser):
    """Сценарий 11, п. 5 и 7: 21 этикетка при печати стоит сеткой 3 × 7 по 63,5 × 38,1 мм от самого начала области печати
    (без отступов оболочки портала — иначе сетка сдвигается с наклеек листа: замечание ручного прохода T-6308, отступ
    `.app-main` ~5 мм); в Chromium-браузерах круга это ровно одна страница PDF формата A4, а 22 этикетки дают две (FR-539)."""
    list_id, _name, _model, (unique_code, _second) = _list_with_unique_fields(admin_page)
    word = unique_word()
    numbers = [create_record(admin_page, list_id, f"Метка {i} {word}", {unique_code: unique_word("inv")})
               for i in range(22)]

    _open_sheet(admin_page, list_id, numbers[:21])
    expect(admin_page.locator(LABEL)).to_have_count(21)
    admin_page.emulate_media(media="print")

    # сетка: 3 столбца и 7 рядов с шагом 63,5 и 38,1 мм, по три этикетки в ряду
    boxes = _boxes(admin_page)
    columns, rows = _clusters([b["x"] for b in boxes]), _clusters([b["y"] for b in boxes])
    assert len(columns) == 3, f"столбцов не 3: {columns}"
    assert len(rows) == 7, f"рядов не 7: {rows}"
    for earlier, later in zip(columns, columns[1:]):
        assert abs((later - earlier) - CELL_W) <= 2, f"шаг по горизонтали не 63,5 мм: {columns}"
    for earlier, later in zip(rows, rows[1:]):
        assert abs((later - earlier) - CELL_H) <= 2, f"шаг по вертикали не 38,1 мм: {rows}"
    for box in boxes:
        assert box["w"] <= CELL_W + 2 and box["h"] <= CELL_H + 2, f"этикетка больше ячейки 63,5 × 38,1 мм: {box}"
    for row in rows:
        assert sum(1 for b in boxes if abs(b["y"] - row) <= 2) == 3
    # лист начинается в начале области печати: первая этикетка — в левом верхнем углу, не дальше 1 мм (T-6308)
    assert min(columns) <= MM and min(rows) <= MM, f"лист сдвинут от начала области печати: x={min(columns):.1f}, y={min(rows):.1f} px"
    grid = admin_page.locator(SHEET).evaluate(
        "el => { const s = getComputedStyle(el); return {display: s.display, columns: s.gridTemplateColumns}; }")
    assert grid["display"] == "grid", f"лист этикеток при печати не сетка: {grid}"
    widths = [float(part[:-2]) for part in grid["columns"].split() if part.endswith("px")]
    assert len(widths) == 3 and all(abs(w - CELL_W) <= 2 for w in widths), f"столбцы сетки: {grid['columns']}"

    # настоящая печать (Chromium, Edge, Яндекс Браузер): размер и поля из `@page`, 21 этикетка — одна страница
    if browser.e2e_project in CHROMIUM_FAMILY:
        one = admin_page.pdf(prefer_css_page_size=True)
        assert _pdf_pages(one) == 1, "21 этикетка заняла не одну страницу A4"
        media_box = re.search(rb"/MediaBox\s*\[\s*0\s+0\s+([\d.]+)\s+([\d.]+)\s*\]", one)
        if media_box:
            width, height = float(media_box.group(1)), float(media_box.group(2))
            assert abs(width - 595.3) <= 1.5 and abs(height - 841.9) <= 1.5, f"страница не A4: {width} × {height}"
        _open_sheet(admin_page, list_id, numbers)
        two = admin_page.pdf(prefer_css_page_size=True)
        assert _pdf_pages(two) == 2, "22 этикетки должны занять две страницы A4"


def test_l11_label_page_does_not_widen_page_at_360px(admin_page, browser, browser_context_args):
    """Сценарий 11 (NFR-507): на экране 360 px страница этикетки не имеет горизонтальной прокрутки и показывает
    этикетку с QR-кодом."""
    list_id, _name, _model, (unique_code, _second) = _list_with_unique_fields(admin_page)
    number = create_record(admin_page, list_id, f"Планшет {unique_word()}", {unique_code: unique_word("inv")})

    context, page = open_narrow(browser, browser_context_args, admin_page, f"/lists/{list_id}/{number}/label/", "label")
    try:
        expect(page.locator(LABEL)).to_have_count(1)
        expect(page.locator(LABEL).locator(QR)).to_be_visible()
        assert page_fits(page), "страница этикетки шире экрана 360 px"
    finally:
        context.close()
