"""T-7149: сценарий 10 — файлы и картинки записи (FR-606, FR-633, FR-634, FR-642, NFR-604).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-007.md разделы 10.2, 12.6, 13.1, 14.4; решения 8, 21, 23, 51
задач; образцы — test_k05_files.py, test_l10_files.py):
- помощники — из `helpers_feed.py` (`publish`, `add_comment`, `upload`, `try_upload`, `wait_clean`, `wait_quarantine`,
  `eicar_file`, `open_card`, `refusals`); пути файлов — во временном каталоге `tmp_path` (помощники берут пути);
- ClamAV стенда настоящий: сразу после прикрепления состояние — `pending` или уже `clean` (у EICAR — `pending` или уже
  `quarantine`); проверки «пока проверяется» выполняются, если файл ещё `pending` в момент проверки (состояние читается
  одним обращением к DOM), проверки «после проверки» — всегда; предел ожидания проверки — минута;
- исполняемый файл, архив с паролем и PDF-образец собраны из байтов в самом файле (код приложения не импортируется);
- отказы файла — `[data-error="file"][data-code=…]`, коды `post_files_limit`, `comment_files_limit`, `file_too_big`,
  `file_type` и тексты — разделы 10.2 и 13.1 контракта; адрес файла — `/feed/files/<id>/`, эскиза — `.../thumb/`;
- пункт ClamAV «недоступен» в приёмке не проверяется (решение 41 задач); правка записи — свой короткий помощник
  `_edit_post` (в `helpers_feed.py` его нет — вопрос Opus в итоге).
"""
import re
import secrets
import struct
import time
import zipfile
from io import BytesIO

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_feed, helpers_org
from tests.e2e.helpers_feed import POST_ALL

MB = 1024 * 1024
MISSING_ID = 2_000_000_000  # номер, которого на стенде нет (в пределах целого PostgreSQL)
PDF = (b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\n"
       b"endobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n")
TXT = "Строка файла для приёмки ленты.\n".encode("utf-8")
FORM = "form#feed-form"


# --- Общие помощники файла ---------------------------------------------------------------------------------------

def _uid() -> str:
    return secrets.token_hex(3)


def _writer(admin_page, employee):
    """Сотрудник с правом «Писать всем»."""
    role = helpers_feed.make_role(admin_page, [POST_ALL])
    return employee(role=role, full_name=f"Писарев{_uid()} Иван Иванович")


def _write(tmp_path, name: str, data: bytes):
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _executable() -> bytes:
    """Начало исполняемого файла Windows (PE): по содержимому это программа, что бы ни говорило имя."""
    return (b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"\x00" * 44 + b"\x40\x00\x00\x00"
            + b"PE\x00\x00" + b"\x00" * 20 + b"This program cannot be run in DOS mode.\r\n" + b"\x00" * 256)


def _encrypted_zip() -> bytes:
    """Архив ZIP с признаком шифрования (бит 0 общих флагов заголовков): пароль не нужен, определение идёт по флагу."""
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("inside.txt", "содержимое архива")
    data = bytearray(buffer.getvalue())
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        position = data.find(signature)
        while position != -1:
            flags = struct.unpack_from("<H", data, position + offset)[0] | 0x1
            struct.pack_into("<H", data, position + offset, flags)
            position = data.find(signature, position + 4)
    return bytes(data)


def _file_nodes(page, post_id):
    """Файлы записи: узлы `[data-feed-file][data-file-state]` внутри `#feed-post-<id>`."""
    return page.locator(f"#feed-post-{post_id} [data-feed-file][data-file-state]")


def _file_ids(page, post_id) -> list:
    return [int(v) for v in _file_nodes(page, post_id).evaluate_all("els => els.map(e => e.dataset.feedFile)")]


def _node(page, file_id):
    return page.locator(f'[data-feed-file="{file_id}"][data-file-state]').first


def _snapshot(page, file_id) -> str:
    """Состояние файла, прочитанное одним обращением к DOM (между чтениями оно может смениться)."""
    return _node(page, file_id).evaluate("el => el.dataset.fileState")


def _state_fresh(page, post_id, file_id) -> str:
    """Состояние файла по свежему ответу карточки записи (ответ на прямой запрос мог прийти уже после конца проверки)."""
    html = helpers_org.direct_get(page, f"/feed/{post_id}/").text()
    for tag in re.findall(r"<[^>]*\bdata-feed-file=\"%d\"[^>]*>" % int(file_id), html):
        found = re.search(r'\bdata-file-state="([^"]*)"', tag)
        if found:
            return found.group(1)
    raise AssertionError(f"в карточке записи {post_id} нет файла {file_id} с data-file-state")


def _refusal(page, code: str, text: str) -> None:
    """Отказ у поля `file` виден на странице с причиной (раздел 10.2, 13.1)."""
    refusal = page.locator(f'[data-error="file"][data-code="{code}"]').first
    expect(refusal).to_be_visible()
    expect(refusal).to_contain_text(text)


def _edit_post(page, post_id, *, remove=()) -> None:
    """Правка записи `/feed/<id>/edit/`: флажки «убрать» `input[name="remove"][value="<id>"]` и сохранение; ждёт карточку.
    Помощника правки в `helpers_feed.py` нет."""
    page.goto(f"/feed/{post_id}/edit/")
    expect(page.locator('[data-feed-page="edit"]')).to_be_visible()
    form = page.locator('[data-feed-page="edit"] form:has(textarea[name="text"])').first
    for file_id in remove:
        form.locator(f'input[name="remove"][value="{file_id}"]').check()
    with page.expect_navigation():
        form.locator("button[type=submit]").first.click()
    page.wait_for_load_state()
    expect(page.locator('[data-feed-page="card"]')).to_be_visible()


def _open_feed(new_context, account):
    return helpers_feed.open_feed(new_context(), account)


# --- Тесты -------------------------------------------------------------------------------------------------------

def test_f10_png_and_pdf_of_post_are_listed_as_checking_or_already_clean_without_link_then_clean(
        admin_page, employee, new_context, tmp_path):
    """Сценарий 10, п. 1: запись с картинкой PNG и файлом PDF — пока антивирус проверяет, видны имена с пометкой
    «проверяется», открыть и скачать нельзя; затем «чистые» (FR-633, FR-634)."""
    writer = _writer(admin_page, employee)
    page = _open_feed(new_context, writer)
    png_name, pdf_name = f"экран{_uid()}.png", f"документ{_uid()}.pdf"
    png = _write(tmp_path, png_name, helpers.make_png(64, 48))
    pdf = _write(tmp_path, pdf_name, PDF)
    post_id = helpers_feed.publish(page, f"Файлы {_uid()}", files=[png, pdf])
    ids = _file_ids(page, post_id)
    assert len(ids) == 2, f"в записи файлов {len(ids)}, ожидалось 2"
    for name in (png_name, pdf_name):
        node = _file_nodes(page, post_id).filter(has_text=name)
        expect(node).to_have_count(1)
        file_id = int(node.evaluate("el => el.dataset.feedFile"))
        # п. 1: имя видно; состояние сразу — «проверяется» или уже «чистый» (состояние читается один раз)
        expect(node).to_contain_text(name)
        state = _snapshot(page, file_id)
        assert state in ("pending", "clean"), f"файл {name}: состояние {state!r}"
        if state == "pending":
            # п. 1: пометка «проверяется», ссылки открыть и скачать нет
            expect(node).to_contain_text("проверяется")
            expect(node.locator("a[href]")).to_have_count(0)
    # затем проверка заканчивается (предел — минута)
    for file_id in ids:
        helpers_feed.wait_clean(page, file_id)
        expect(_node(page, file_id)).to_have_attribute("data-file-state", "clean")


def test_f10_checking_file_direct_url_gives_not_found_with_still_checking_text(
        admin_page, employee, new_context, tmp_path):
    """Сценарий 10, п. 1 (прямой адрес): пока файл проверяется, его адрес отвечает «не найдено» с текстом «Файл ещё
    проверяется»; после проверки файл выдаётся (FR-634, FR-642)."""
    writer = _writer(admin_page, employee)
    page = _open_feed(new_context, writer)
    # крупный файл проверяется дольше мелкого
    big = _write(tmp_path, f"крупный{_uid()}.bin", b"\x00" * (19 * MB))
    post_id = helpers_feed.publish(page, f"Крупный файл {_uid()}", files=[big])
    (file_id,) = _file_ids(page, post_id)
    if _snapshot(page, file_id) == "pending":
        response = helpers_org.direct_get(page, f"/feed/files/{file_id}/")
        # проверка по свежей странице: если файл всё ещё «проверяется», отказ обязан быть именно таким
        if _state_fresh(page, post_id, file_id) == "pending":
            assert response.status == 404, f"файл «проверяется» отдан: {response.status}"
            assert "x-accel-redirect" not in response.headers
            assert "Файл ещё проверяется" in response.text()
    # контроль: после проверки файл выдаётся
    helpers_feed.wait_clean(page, file_id)
    assert helpers_org.direct_get(page, f"/feed/files/{file_id}/").status == 200


def test_f10_clean_status_appears_within_one_minute_of_attach_on_stand_clamav(
        admin_page, employee, new_context, tmp_path):
    """Сценарий 10, NFR-604: на настоящем ClamAV стенда файл становится «чистым» не позже минуты после прикрепления
    (NFR-604)."""
    writer = _writer(admin_page, employee)
    page = _open_feed(new_context, writer)
    png = _write(tmp_path, f"экран{_uid()}.png", helpers.make_png(64, 48))
    started = time.monotonic()  # отсчёт — от прикрепления
    post_id = helpers_feed.publish(page, f"Минута {_uid()}", files=[png])
    (file_id,) = _file_ids(page, post_id)
    left = max(1.0, 60.0 - (time.monotonic() - started))
    helpers_feed.wait_clean(page, file_id, timeout=int(left * 1000))
    elapsed = time.monotonic() - started
    assert elapsed <= 60.0, f"проверка заняла {elapsed:.1f} с (предел 60 с)"
    expect(_node(page, file_id)).to_have_attribute("data-file-state", "clean")


def test_f10_clean_image_in_post_and_comment_shows_reduced_and_click_opens_full_image(
        admin_page, employee, new_context, tmp_path):
    """Сценарий 10, п. 2 (картинка): после проверки картинка видна уменьшенной — в записи и в комментарии; по нажатию
    открывается целиком (FR-634)."""
    writer = _writer(admin_page, employee)
    width = 1600
    png_post = _write(tmp_path, f"запись{_uid()}.png", helpers.make_png(width, 1200))
    png_comment = _write(tmp_path, f"ответ{_uid()}.png", helpers.make_png(width, 1200))
    page = _open_feed(new_context, writer)
    post_id = helpers_feed.publish(page, f"Картинка {_uid()}", files=[png_post])
    card = helpers_feed.open_card(new_context(), writer, post_id)
    comment_id = helpers_feed.add_comment(card, post_id, f"Ответ {_uid()}", files=[png_comment])
    scopes = {"запись": f"#feed-post-{post_id}", "комментарий": f"#c{comment_id}"}
    for what, scope in scopes.items():
        (file_id,) = [int(v) for v in card.locator(f"{scope} [data-feed-file]").evaluate_all(
            "els => els.map(e => e.dataset.feedFile)")][:1]
        helpers_feed.wait_clean(card, file_id)
        link = card.locator(f'{scope} a[href="/feed/files/{file_id}/"]').first
        thumb = link.locator(f'img[src="/feed/files/{file_id}/thumb/"]')
        # п. 2: уменьшенная картинка видна и загружена, она меньше оригинала
        expect(thumb).to_be_visible()
        expect(thumb).to_have_js_property("complete", True)
        natural = thumb.evaluate("img => img.naturalWidth")
        assert 0 < natural < width, f"{what}: ширина уменьшенной картинки {natural}, оригинал {width}"
        # п. 2: по нажатию — целиком (адрес оригинала; в новой вкладке или в этой же)
        if link.get_attribute("target") == "_blank":
            with card.context.expect_page() as opened:
                link.click()
            target = opened.value
        else:
            with card.expect_navigation():
                link.click()
            target = card
        target.wait_for_load_state()
        assert target.url.rstrip("/").endswith(f"/feed/files/{file_id}"), target.url
        assert target.evaluate("() => document.images.length && document.images[0].naturalWidth") == width
        if target is not card:
            target.close()
        else:
            card.goto(f"/feed/{post_id}/")


def test_f10_clean_pdf_shows_name_size_and_download_gives_file(admin_page, employee, new_context, tmp_path):
    """Сценарий 10, п. 2 (PDF): после проверки PDF показан именем, размером и ссылкой «Скачать»; скачивание отдаёт тот же
    файл (FR-634)."""
    writer = _writer(admin_page, employee)
    page = _open_feed(new_context, writer)
    name = f"договор{_uid()}.pdf"
    post_id = helpers_feed.publish(page, f"Документ {_uid()}", files=[_write(tmp_path, name, PDF)])
    (file_id,) = _file_ids(page, post_id)
    helpers_feed.wait_clean(page, file_id)
    node = _node(page, file_id)
    # п. 2: имя и размер строкой
    expect(node).to_contain_text(name)
    assert re.search(r"\d+(?:[.,]\d+)?\s*(?:Б|КБ|МБ|байт|B|KB|kB)", " ".join(node.inner_text().split())), (
        f"в строке файла нет размера: {node.inner_text()!r}")
    # п. 2: ссылка «Скачать» ведёт на файл и отдаёт его
    link = node.locator(f'a[href="/feed/files/{file_id}/"]').first
    expect(link).to_have_text(re.compile("Скачать"))
    with page.expect_download() as info:
        link.click()
    download = info.value
    assert download.suggested_filename == name
    assert open(download.path(), "rb").read() == PDF, "скачан не тот файл"


def test_f10_eicar_file_goes_to_quarantine_with_mark_and_is_not_downloadable_by_link_or_direct_url(
        admin_page, employee, new_context, tmp_path):
    """Сценарий 10, п. 3: файл в карантине — в записи пометка «карантин», скачать нельзя ни по ссылке, ни по прямому адресу
    (FR-634, FR-642, NFR-604)."""
    writer, reader = _writer(admin_page, employee), employee(full_name=f"Простов{_uid()} Иван Иванович")
    page = _open_feed(new_context, writer)
    post_id = helpers_feed.publish(page, f"Тест антивируса {_uid()}", files=[helpers_feed.eicar_file(tmp_path)])
    (file_id,) = _file_ids(page, post_id)
    helpers_feed.wait_quarantine(page, file_id)
    node = _node(page, file_id)
    # п. 3: пометка «карантин», ссылки нет
    expect(node).to_contain_text("карантин")
    expect(node.locator("a[href]")).to_have_count(0)
    # п. 3: прямой адрес — отказ у автора и у другого сотрудника; нет ни выдачи, ни эскиза
    for who in (page, reader.page):
        for path in (f"/feed/files/{file_id}/", f"/feed/files/{file_id}/thumb/"):
            response = helpers_org.direct_get(who, path)
            assert response.status == 404, f"{path}: файл в карантине, а ответ {response.status}"
            assert "x-accel-redirect" not in response.headers
        assert "Файл в карантине" in helpers_org.direct_get(who, f"/feed/files/{file_id}/").text()


def test_f10_eleventh_file_to_post_and_fourth_to_comment_are_refused_with_reason(
        admin_page, employee, new_context, tmp_path):
    """Сценарий 10, п. 4 (число файлов): одиннадцатый файл к записи и четвёртый к комментарию — отказ с причиной
    (FR-633, FR-642)."""
    writer = _writer(admin_page, employee)
    page = _open_feed(new_context, writer)
    for index in range(10):
        helpers_feed.upload(page, _write(tmp_path, f"файл{index}.txt", TXT + str(index).encode()), scope="post")
    # п. 4: одиннадцатый к записи — отказ «У записи уже 10 файлов»
    codes = helpers_feed.try_upload(page, _write(tmp_path, "лишний.txt", TXT), scope="post")
    assert ("file", "post_files_limit") in codes, codes
    _refusal(page, "post_files_limit", "У записи уже 10 файлов")
    expect(page.locator(f"{FORM} [data-feed-file]")).to_have_count(10)
    # комментарий: три файла принимаются, четвёртый — отказ «У комментария уже 3 файла»
    post_id = helpers_feed.publish(page, f"Для комментариев {_uid()}", files=[])  # запись с десятью файлами формы
    card = helpers_feed.open_card(new_context(), writer, post_id)
    for index in range(3):
        helpers_feed.upload(card, _write(tmp_path, f"к{index}.txt", TXT + bytes([65 + index])),
                            scope="comment", post_id=post_id)
    codes = helpers_feed.try_upload(card, _write(tmp_path, "четвёртый.txt", TXT), scope="comment", post_id=post_id)
    assert ("file", "comment_files_limit") in codes, codes
    _refusal(card, "comment_files_limit", "У комментария уже 3 файла")


def test_f10_file_over_20mb_executable_and_password_archive_are_refused_with_reason(
        admin_page, employee, new_context, tmp_path):
    """Сценарий 10, п. 4 (размер и тип): файл больше 20 МБ, исполняемый файл и архив с паролем — отказ с причиной
    (FR-633, FR-642, NFR-604)."""
    writer = _writer(admin_page, employee)
    page = _open_feed(new_context, writer)
    cases = (
        ("file_too_big", "Файл больше 20 МБ", b"\x00" * (21 * MB), "большой.bin"),
        ("file_type", "Файл такого типа не принимается", _executable(), "программа.exe"),
        ("file_type", "Файл такого типа не принимается", _encrypted_zip(), "закрытый.zip"),
    )
    for code, text, data, name in cases:
        codes = helpers_feed.try_upload(page, _write(tmp_path, name, data), scope="post")
        assert ("file", code) in codes, f"{name}: отказ {codes}, ожидался {code!r}"
        _refusal(page, code, text)
        # файла в форме нет
        expect(page.locator(f"{FORM} [data-feed-file]")).to_have_count(0)


def test_f10_executable_renamed_to_pdf_is_refused_by_content_type(admin_page, employee, new_context, tmp_path):
    """Сценарий 10, п. 4 (подмена типа): исполняемый файл с именем .pdf отвергается по содержимому (FR-633, FR-642)."""
    writer = _writer(admin_page, employee)
    page = _open_feed(new_context, writer)
    codes = helpers_feed.try_upload(page, _write(tmp_path, "отчёт.pdf", _executable()), scope="post")
    assert ("file", "file_type") in codes, f"отказ {codes}, ожидался file_type"
    _refusal(page, "file_type", "Файл такого типа не принимается")
    expect(page.locator(f"{FORM} [data-feed-file]")).to_have_count(0)


def test_f10_author_removes_attached_file_before_publish_and_post_has_no_such_file(
        admin_page, employee, new_context, tmp_path):
    """Сценарий 10, п. 4 (убрать до публикации): автор убирает прикреплённый файл крестиком до публикации — в записи такого
    файла нет, адрес файла не выдаётся (FR-633)."""
    writer = _writer(admin_page, employee)
    page = _open_feed(new_context, writer)
    removed_name, kept_name = f"убрать{_uid()}.txt", f"остаться{_uid()}.txt"
    removed = helpers_feed.upload(page, _write(tmp_path, removed_name, TXT + b"1"), scope="post")
    kept = helpers_feed.upload(page, _write(tmp_path, kept_name, TXT + b"2"), scope="post")
    # автор убирает первый файл крестиком таблетки
    pill = page.locator(f'{FORM} [data-feed-file="{removed}"]')
    with page.expect_response(lambda r: r.request.method == "POST" and f"/feed/files/{removed}/delete/" in r.url):
        pill.locator('button[data-action="file-remove"]').click()
    expect(pill).to_have_count(0)
    # публикует запись: остался только второй файл
    post_id = helpers_feed.publish(page, f"Один файл {_uid()}")
    assert _file_ids(page, post_id) == [kept]
    expect(page.locator(f"#feed-post-{post_id}")).not_to_contain_text(removed_name)
    # убранный файл адресом не выдаётся
    response = helpers_org.direct_get(page, f"/feed/files/{removed}/")
    assert response.status == 404 and "x-accel-redirect" not in response.headers


def test_f10_author_removes_file_when_editing_post_and_its_url_gives_not_found(
        admin_page, employee, new_context, tmp_path):
    """Сценарий 10, п. 4 (убрать при правке): автор убирает файл при правке записи — файла в записи нет, его адрес отвечает
    «не найдено» (FR-633)."""
    writer = _writer(admin_page, employee)
    page = _open_feed(new_context, writer)
    name = f"убрать{_uid()}.pdf"
    post_id = helpers_feed.publish(page, f"Правка {_uid()}", files=[_write(tmp_path, name, PDF)])
    (file_id,) = _file_ids(page, post_id)
    helpers_feed.wait_clean(page, file_id)
    # контроль: до правки файл выдаётся
    assert helpers_org.direct_get(page, f"/feed/files/{file_id}/").status == 200
    # когда: автор отмечает «убрать» при правке и сохраняет
    _edit_post(page, post_id, remove=[file_id])
    expect(page.locator(f"#feed-post-{post_id}")).not_to_contain_text(name)
    assert _file_ids(page, post_id) == []
    # адрес убранного файла — «не найдено»
    response = helpers_org.direct_get(page, f"/feed/files/{file_id}/")
    assert response.status == 404 and "x-accel-redirect" not in response.headers


def test_f10_file_and_image_urls_of_invisible_post_give_same_answer_as_missing_file(
        admin_page, employee, new_context, tmp_path):
    """Сценарий 10, п. 5: сотрудник не видит запись — адреса её файла и картинки отвечают как у несуществующего файла
    (FR-606, FR-634)."""
    mark = _uid()
    writer = _writer(admin_page, employee)
    addressee = employee(full_name=f"Петров{mark} Пётр Петрович")
    outsider = employee(full_name=f"Чужов{mark} Иван Иванович")
    page = _open_feed(new_context, writer)
    png = _write(tmp_path, f"экран{mark}.png", helpers.make_png(400, 300))
    # запись лично Петрову: Чужов её не видит
    post_id = helpers_feed.publish(page, f"Лично {mark}", to=[("person", addressee.full_name)], files=[png])
    (file_id,) = _file_ids(page, post_id)
    helpers_feed.wait_clean(page, file_id)
    paths = (f"/feed/files/{file_id}/", f"/feed/files/{file_id}/thumb/")
    # контроль: автору и адресату файл и картинка выдаются
    for who, checked in ((page, paths), (addressee.page, paths[:1])):
        for path in checked:
            assert helpers_org.direct_get(who, path).status == 200, f"{path}: видящему не выдан"
    # п. 5: невидящему — тот же ответ, что у несуществующего файла
    missing = {path: helpers_org.direct_get(outsider.page, path) for path in (
        f"/feed/files/{MISSING_ID}/", f"/feed/files/{MISSING_ID}/thumb/")}
    assert all(r.status == 404 for r in missing.values())
    for path, reference in zip(paths, missing.values()):
        response = helpers_org.direct_get(outsider.page, path)
        assert response.status == reference.status == 404, f"{path}: ответ {response.status}"
        assert "x-accel-redirect" not in response.headers
        assert response.headers.get("content-type", "").split(";")[0] != "image/png"
        assert "проверяется" not in response.text() and "карантине" not in response.text()
        assert response.headers.get("content-type") == reference.headers.get("content-type")
