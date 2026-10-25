"""T-6149: сценарий 10 — файлы в записях: проверка ClamAV, карантин, отказы, права, история, удаление (FR-514, FR-522,
FR-524, FR-536, FR-537, FR-546, NFR-505).

Общее для файла (шаблон e2e/template.md, CONTRACT-006.md: 10.2, 11.5–11.7, 12.1, 15.4; решение 19 задач):
- каждый тест заводит свой список с полями «файл», запись и правящего («Правят» со своей ролью); общих настроек тесты не
  меняют, шесть стартовых списков не трогают;
- ClamAV стенда настоящий: чистый файл, EICAR из частей (`helpers_lists.eicar_bytes`); сразу после прикрепления состояние —
  `pending` или уже `clean` (у EICAR — `pending` или уже `quarantine`); проверки «пока проверяется» выполняются, если
  файл ещё `pending` в момент проверки (состояние читается одним обращением к DOM), проверки «после проверки» — всегда;
  «проверяется → чистый» — `helpers_lists.wait_file_clean` (предел 1 минута);
- пункт 6 сценария (ClamAV недоступен) в приёмке не проверяется (решение 19): его место — серверный T-6121 и T-6301;
- отказы файла — `[data-error="file"][data-code=…]` (10.1, 12.1), коды: `file_type_refused`, `file_too_big`, `files_limit`.
"""
import re
import time

from playwright.sync_api import expect

from tests.e2e import helpers_lists
from tests.e2e.helpers_lists import (
    add_field, archive_record, attach_file, confirm_dialog, create_list, create_record, make_list_editor,
    make_list_reader, make_list_role, open_record, record_file_row, scan_snapshot, status_of, try_attach_file,
    unique_list_name, unique_word, wait_file_clean)

MB = 1024 * 1024
MISSING_ID = 2_000_000_000  # номер, которого на стенде нет (в пределах целого PostgreSQL)
PDF = (b"%PDF-1.4\n1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n2 0 obj\n<< /Type /Pages /Kids [] /Count 0 >>\n"
       b"endobj\ntrailer\n<< /Root 1 0 R >>\n%%EOF\n")


# --- Общие помощники файла ----------------------------------------------------------------------------------

def _prepare(admin_page, employee, *, fields: int = 1, **kwargs):
    """Список с `fields` полями «файл» (с «несколько значений», чтобы поле не считалось занятым), запись и правящий:
    `(номер списка, коды полей, правящий, номер записи, название списка)`. Страница правящего открыта где угодно."""
    name = unique_list_name("Файлы")
    list_id = create_list(admin_page, name)
    codes = [add_field(admin_page, list_id, f"Скан {index + 1}", "file", multiple=True) for index in range(fields)]
    editor = make_list_editor(employee, admin_page, list_id, **kwargs)
    number = create_record(editor.page, list_id, f"Лицензия {unique_word()}")
    return list_id, codes, editor, number, name


def _pdf_name() -> str:
    return f"{unique_word('scan')}.pdf"


def _exe() -> bytes:
    """Начало исполняемого файла Windows (PE): по содержимому это программа, что бы ни говорило имя."""
    # e_lfanew (0x3C) указывает на подпись `PE\0\0` в 0x40 — так её ищет проверка ядра (CONTRACT-005 3.5: PE)
    return (b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"\x00" * 44 + b"\x40\x00\x00\x00"
            + b"PE\x00\x00" + b"\x00" * 20 + b"This program cannot be run in DOS mode.\r\n" + b"\x00" * 256)


def _encrypted_zip() -> bytes:
    """Архив ZIP с признаком шифрования (бит 0 общих флагов заголовков): пароль не нужен, определение идёт по флагу."""
    import io
    import struct
    import zipfile

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
        archive.writestr("secret.txt", "содержимое архива")
    data = bytearray(buffer.getvalue())
    for signature, offset in ((b"PK\x03\x04", 6), (b"PK\x01\x02", 8)):
        position = data.find(signature)
        while position != -1:
            flags = struct.unpack_from("<H", data, position + offset)[0] | 0x1
            struct.pack_into("<H", data, position + offset, flags)
            position = data.find(signature, position + 4)
    return bytes(data)


def _file_path(list_id, number, file_id) -> str:
    return f"/lists/{list_id}/{number}/files/{file_id}/"


def _scan_fresh(page, list_id, number, file_id) -> str:
    """Состояние файла (`data-scan`) по свежей карточке: ответ на прямой запрос мог прийти уже после конца проверки."""
    html = page.request.get(f"/lists/{list_id}/{number}/").text()
    tag = re.search(rf'<li\b[^>]*\bdata-file-id="{re.escape(str(file_id))}"[^>]*>', html)
    assert tag, f"в карточке записи нет строки файла {file_id}"
    state = re.search(r'\bdata-scan="([^"]*)"', tag.group(0))
    assert state, f"у строки файла {file_id} нет data-scan"
    return state.group(1)


def _assert_refused(page, code: str, text: str) -> None:
    """Отказ файла виден: `[data-error="file"][data-code=<код>]` с текстом раздела 12.1."""
    refusal = page.locator(f'[data-error="file"][data-code="{code}"]')
    expect(refusal.first).to_be_visible()
    expect(refusal.first).to_contain_text(text)


def _no_row(page, list_id, number, code, name) -> None:
    """Файла с именем `name` в блоке поля нет — ни сразу, ни после обновления карточки."""
    expect(helpers_lists.files_block(page, code).locator("li[data-file-id]").filter(has_text=name)).to_have_count(0)
    open_record(page, list_id, number)
    expect(helpers_lists.files_block(page, code).locator("li[data-file-id]").filter(has_text=name)).to_have_count(0)


# --- Тесты ---------------------------------------------------------------------------------------------------

def test_l10_attached_pdf_is_listed_as_checking_or_already_clean_then_clean_and_downloads(admin_page, employee):
    """Сценарий 10, п. 1: правящий прикрепляет PDF до 20 МБ — файл виден со статусом «проверяется» (или уже «чистый»),
    затем «чистый» и скачивается (FR-536, FR-537)."""
    list_id, (code,), editor, number, _ = _prepare(admin_page, employee)
    page = editor.page
    name = _pdf_name()
    # п. 1: прикрепляет PDF — строка файла с именем появляется; состояние сразу — «проверяется» или уже «чистый»
    file_id, seen = attach_file(page, list_id, number, code, PDF, name, mime="application/pdf")
    assert seen["state"] in ("pending", "clean"), f"состояние сразу после прикрепления: {seen['state']!r}"
    expect(record_file_row(page, file_id)).to_contain_text(name)
    # п. 1: затем «чистый» — со ссылкой скачивания, без пометок
    assert wait_file_clean(page, list_id, number, file_id) == "clean"
    row = record_file_row(page, file_id)
    expect(row).to_have_attribute("data-scan", "clean")
    expect(row).to_contain_text(name)
    expect(row).not_to_contain_text("проверяется")
    expect(row).not_to_contain_text("в карантине")
    link = row.locator('a[data-action="file-download"]')
    expect(link).to_have_count(1)
    # п. 1: скачивается — по ссылке отдаётся тот же файл вложением
    href = link.get_attribute("href")
    assert href.rstrip("/").endswith(_file_path(list_id, number, file_id).rstrip("/")), f"ссылка скачивания: {href!r}"
    response = page.request.get(href, max_redirects=0)
    assert response.status == 200, f"скачивание: {response.status}"
    assert response.body() == PDF, "скачан не тот файл"
    assert "attachment" in response.headers.get("content-disposition", ""), "файл отдан не вложением"
    # п. 1: после обновления страницы файл на месте
    open_record(page, list_id, number)
    expect(helpers_lists.files_block(page, code).locator("li[data-file-id]")).to_have_count(1)


def test_l10_clean_status_appears_within_one_minute_of_attach_on_stand_clamav(admin_page, employee):
    """Сценарий 10, п. 1 и NFR-505: на настоящем ClamAV стенда файл становится «чистым» не позже, чем через минуту после
    прикрепления (NFR-505)."""
    list_id, (code,), editor, number, _ = _prepare(admin_page, employee)
    page = editor.page
    started = time.monotonic()
    # NFR-505: прикрепление (отсчёт от нажатия «Прикрепить»)
    file_id, _ = attach_file(page, list_id, number, code, PDF, _pdf_name(), mime="application/pdf")
    left = max(1.0, 60.0 - (time.monotonic() - started))
    state = wait_file_clean(page, list_id, number, file_id, timeout=left)
    elapsed = time.monotonic() - started
    # NFR-505: «чистый» и не позже минуты
    assert state == "clean", f"файл признан {state!r}"
    assert elapsed <= 60.0, f"проверка заняла {elapsed:.1f} с (предел 60 с)"
    expect(record_file_row(page, file_id)).to_have_attribute("data-scan", "clean")
    expect(record_file_row(page, file_id).locator('a[data-action="file-download"]')).to_have_count(1)


def test_l10_eicar_file_goes_to_quarantine_listed_with_mark_and_not_downloadable(admin_page, employee):
    """Сценарий 10, п. 1–2: заражённый файл (EICAR) после проверки в карантине: в списке файлов записи с пометкой «в
    карантине», без ссылки скачивания, по адресу — 404 (FR-537, NFR-505)."""
    list_id, (code,), editor, number, _ = _prepare(admin_page, employee)
    page = editor.page
    name = f"{unique_word('virus')}.txt"
    file_id, seen = attach_file(page, list_id, number, code, helpers_lists.eicar_bytes(), name, mime="text/plain")
    assert seen["state"] in ("pending", "quarantine"), f"состояние сразу после прикрепления: {seen['state']!r}"
    # п. 1: проверка завершилась — карантин (не позже минуты)
    assert wait_file_clean(page, list_id, number, file_id) == "quarantine"
    row = record_file_row(page, file_id)
    # п. 2: файл виден в списке с пометкой «в карантине»
    expect(row).to_have_attribute("data-scan", "quarantine")
    expect(row).to_contain_text(name)
    expect(row).to_contain_text("в карантине")
    # п. 2: не скачивается — ни ссылки, ни выдачи по адресу
    expect(row.locator('a[data-action="file-download"]')).to_have_count(0)
    response = page.request.get(_file_path(list_id, number, file_id), max_redirects=0)
    assert response.status == 404, f"карантин отдан по адресу: {response.status}"
    assert "x-accel-redirect" not in response.headers
    # после обновления страницы то же
    open_record(page, list_id, number)
    expect(record_file_row(page, file_id)).to_contain_text("в карантине")
    expect(record_file_row(page, file_id).locator('a[data-action="file-download"]')).to_have_count(0)


def test_l10_reader_sees_file_with_checking_mark_if_still_pending_without_download_and_direct_url_gives_not_found(
        admin_page, employee):
    """Сценарий 10, п. 2: читающий открывает карточку — файл «проверяется» (если ещё не проверен) и «в карантине» виден с
    пометкой, но не скачивается, адрес напрямую — 404; после проверки «чистый» ему выдаётся (FR-537)."""
    list_id, (code,), editor, number, _ = _prepare(admin_page, employee)
    reader = make_list_reader(employee, admin_page, list_id)
    page = reader.page
    # п. 2: крупный файл проверяется дольше мелкого — правящий прикрепляет его первым
    big_name = f"{unique_word('big')}.bin"
    big_id, _ = attach_file(editor.page, list_id, number, code, b"\x00" * (19 * MB), big_name)
    # п. 2: читающий открывает карточку сразу (состояние читается в момент проверки)
    open_record(page, list_id, number)
    expect(record_file_row(page, big_id)).to_contain_text(big_name)
    seen = scan_snapshot(page, big_id)
    if seen["state"] == "pending":
        # п. 2: «проверяется» — с пометкой и без ссылки (scan_snapshot), по адресу — 404, если файл всё ещё «pending»
        response = page.request.get(_file_path(list_id, number, big_id), max_redirects=0)
        if _scan_fresh(page, list_id, number, big_id) == "pending":
            assert response.status == 404, f"файл «проверяется» отдан читающему: {response.status}"
            assert "x-accel-redirect" not in response.headers
    # п. 2: «карантин» (детерминированно): виден с пометкой, не скачивается
    virus_name = f"{unique_word('virus')}.txt"
    virus_id, _ = attach_file(editor.page, list_id, number, code, helpers_lists.eicar_bytes(), virus_name,
                              mime="text/plain")
    assert wait_file_clean(editor.page, list_id, number, virus_id) == "quarantine"
    open_record(page, list_id, number)
    row = record_file_row(page, virus_id)
    expect(row).to_contain_text(virus_name)
    expect(row).to_contain_text("в карантине")
    expect(row.locator('a[data-action="file-download"]')).to_have_count(0)
    response = page.request.get(_file_path(list_id, number, virus_id), max_redirects=0)
    assert response.status == 404, f"карантин отдан читающему: {response.status}"
    assert "x-accel-redirect" not in response.headers
    # контроль: после проверки крупный файл «чистый» и читающему выдаётся (отказ выше был из-за состояния)
    assert wait_file_clean(editor.page, list_id, number, big_id) == "clean"
    open_record(page, list_id, number)
    expect(record_file_row(page, big_id).locator('a[data-action="file-download"]')).to_have_count(1)
    assert page.request.get(_file_path(list_id, number, big_id), max_redirects=0).status == 200
    # читающий не правит: кнопки удаления файла у него нет (11.7: «правящим»)
    expect(helpers_lists.files_block(page, code).locator('button[data-action="file-delete"]')).to_have_count(0)


def test_l10_executable_encrypted_archive_and_file_over_20mb_are_refused_with_reason(admin_page, employee):
    """Сценарий 10, п. 3: исполняемый файл, архив с паролем и файл больше 20 МБ не приняты, у каждого видна причина
    (FR-536, FR-546)."""
    list_id, (code,), editor, number, _ = _prepare(admin_page, employee)
    page = editor.page
    cases = (
        ("file_type_refused", "Файл такого типа не принимается", _exe(), "tool.exe"),
        ("file_type_refused", "Файл такого типа не принимается", _encrypted_zip(), "locked.zip"),
        ("file_too_big", "Файл больше 20 МБ", b"\x00" * (25 * MB), "big-25mb.bin"),
    )
    for refusal, text, data, name in cases:
        # п. 3: файл прикрепляется — отказ с причиной
        got = try_attach_file(page, list_id, number, code, data, name)
        assert got == refusal, f"{name}: отказ {got!r}, ожидался {refusal!r}"
        _assert_refused(page, refusal, text)
        # п. 3: файла в списке нет
        _no_row(page, list_id, number, code, name)


def test_l10_executable_renamed_to_pdf_is_refused_by_content_type(admin_page, employee):
    """Сценарий 10, п. 3: исполняемый файл, переименованный в `.pdf` и заявленный как PDF, не принят — тип определён по
    содержимому; настоящий PDF с тем же именем принимается (FR-536, FR-546)."""
    list_id, (code,), editor, number, _ = _prepare(admin_page, employee)
    page = editor.page
    name = _pdf_name()
    # п. 3: исполняемый файл под именем .pdf (тип pdf заявлен и в имени, и в заголовке)
    got = try_attach_file(page, list_id, number, code, _exe(), name, mime="application/pdf")
    assert got == "file_type_refused", f"отказ {got!r}, ожидался file_type_refused"
    _assert_refused(page, "file_type_refused", "Файл такого типа не принимается")
    _no_row(page, list_id, number, code, name)
    # контроль: отказ был из-за содержимого — настоящий PDF с тем же именем принят
    file_id, _ = attach_file(page, list_id, number, code, PDF, name, mime="application/pdf")
    expect(record_file_row(page, file_id)).to_contain_text(name)


def test_l10_twenty_first_file_across_file_fields_is_refused_with_limit(admin_page, employee):
    """Сценарий 10, п. 4: у записи уже 20 файлов (по всем полям «файл») — двадцать первый, в любое из полей, получает
    отказ с пределом (FR-536, FR-546)."""
    list_id, (first, second), editor, number, _ = _prepare(admin_page, employee, fields=2)
    page = editor.page
    # п. 4: 20 файлов — 12 в первом поле и 8 во втором
    for index in range(20):
        code = first if index < 12 else second
        refusal = try_attach_file(page, list_id, number, code, f"файл номер {index}\n".encode(), f"doc-{index:02d}.txt",
                                  mime="text/plain")
        assert refusal == "", f"файл {index + 1} отклонён: {refusal}"
    open_record(page, list_id, number)
    expect(helpers_lists.files_block(page, first).locator("li[data-file-id]")).to_have_count(12)
    expect(helpers_lists.files_block(page, second).locator("li[data-file-id]")).to_have_count(8)
    # п. 4: двадцать первый — отказ с пределом, и в первое поле, и во второе
    for code, name in ((first, "doc-21.txt"), (second, "doc-22.txt")):
        got = try_attach_file(page, list_id, number, code, b"21\n", name, mime="text/plain")
        assert got == "files_limit", f"{name}: отказ {got!r}, ожидался files_limit"
        _assert_refused(page, "files_limit", "У записи уже 20 файлов")
        expect(page.locator("[data-lists-files] li[data-file-id]").filter(has_text=name)).to_have_count(0)
    open_record(page, list_id, number)
    expect(page.locator("[data-lists-files] li[data-file-id]")).to_have_count(20)


def test_l10_file_url_for_employee_not_reading_list_gives_same_answer_as_missing_file(admin_page, employee):
    """Сценарий 10, п. 5: сотрудник, не читающий список, запрашивает файл по прямой ссылке — отказ, как у несуществующего
    файла; читающему тот же файл выдаётся (FR-514, FR-537)."""
    list_id, (code,), editor, number, list_name = _prepare(admin_page, employee)
    name = _pdf_name()
    file_id, _ = attach_file(editor.page, list_id, number, code, PDF, name, mime="application/pdf")
    assert wait_file_clean(editor.page, list_id, number, file_id) == "clean"
    path = _file_path(list_id, number, file_id)
    # контроль: правящему файл выдаётся
    assert editor.page.request.get(path, max_redirects=0).status == 200
    # не читают: сотрудник со стартовыми правами раздела (список ему не выдан) и сотрудник без прав на списки
    outsiders = (employee(), employee(role=make_list_role(admin_page)[1]))
    for outsider in outsiders:
        page = outsider.page
        # то, чего нет: номер файла, номер записи, номер списка
        missing = [page.request.get(_file_path(list_id, number, MISSING_ID), max_redirects=0),
                   page.request.get(_file_path(list_id, MISSING_ID, file_id), max_redirects=0),
                   page.request.get(_file_path(MISSING_ID, number, file_id), max_redirects=0)]
        assert [r.status for r in missing] == [404, 404, 404], [r.status for r in missing]
        # п. 5: тот же файл по прямой ссылке — ответ как у несуществующего
        response = page.request.get(path, max_redirects=0)
        assert response.status == 404, f"файл выдан или отказ иной: {response.status}"
        assert "x-accel-redirect" not in response.headers
        assert "content-disposition" not in response.headers
        assert response.headers.get("content-type", "").split(";")[0] == \
            missing[0].headers.get("content-type", "").split(";")[0]
        body = response.text()
        for secret in (name, list_name):
            assert secret not in body, f"в отказе есть данные объекта: {secret!r}"
        # запись и список закрыты так же
        assert status_of(page, f"/lists/{list_id}/{number}/") == 404
        assert status_of(page, f"/lists/{list_id}/") == 404


def test_l10_removed_file_shows_file_removed_with_name_in_history(admin_page, employee):
    """Сценарий 10, п. 7: файл удалён из записи — в истории «Удалён файл <имя>» (и ранее «Добавлен файл <имя>»);
    из списка файлов и по адресу файл исчез (FR-522)."""
    list_id, (code,), editor, number, _ = _prepare(admin_page, employee)
    page = editor.page
    name = _pdf_name()
    file_id, _ = attach_file(page, list_id, number, code, PDF, name, mime="application/pdf")
    assert wait_file_clean(page, list_id, number, file_id) == "clean"
    open_record(page, list_id, number)
    history = page.locator("[data-lists-history]")
    expect(history.locator('li[data-change-kind="file_added"]').filter(has_text=f"Добавлен файл {name}")).to_have_count(1)
    expect(history.locator('li[data-change-kind="file_removed"]')).to_have_count(0)
    # п. 7: файл удалён из записи кнопкой «Удалить» (подтверждение — если оно есть: встроенное или диалог)
    page.on("dialog", lambda dialog: dialog.accept())
    page.locator(f'li[data-file-id="{file_id}"] button[data-action="file-delete"]').click()
    try:
        expect(record_file_row(page, file_id)).to_have_count(0, timeout=3000)
    except AssertionError:
        confirm_dialog(page)
        expect(record_file_row(page, file_id)).to_have_count(0)
    # п. 7: открыта история — «Удалён файл <имя>»
    open_record(page, list_id, number)
    expect(record_file_row(page, file_id)).to_have_count(0)
    removed = page.locator('[data-lists-history] li[data-change-kind="file_removed"]')
    expect(removed).to_have_count(1)
    expect(removed).to_contain_text(f"Удалён файл {name}")
    expect(page.locator('[data-lists-history] li[data-change-kind="file_added"]')).to_have_count(1)
    assert status_of(page, _file_path(list_id, number, file_id)) == 404, "удалённый файл отдан по адресу"


def test_l10_files_of_purged_record_give_not_found_by_url(admin_page, employee):
    """Сценарий 10, п. 8: запись удалена навсегда — её файлов нет: адреса файла и записи дают 404, как у
    несуществующих (FR-524)."""
    list_id, (code,), editor, number, _ = _prepare(admin_page, employee)
    name = _pdf_name()
    file_id, _ = attach_file(editor.page, list_id, number, code, PDF, name, mime="application/pdf")
    assert wait_file_clean(editor.page, list_id, number, file_id) == "clean"
    path = _file_path(list_id, number, file_id)
    # контроль: пока запись жива, файл выдаётся
    assert editor.page.request.get(path, max_redirects=0).status == 200
    # п. 8: запись в архив, затем «Удалить навсегда» управляющим с подтверждением
    archive_record(editor.page, list_id, number)
    page = admin_page
    open_record(page, list_id, number)
    page.locator('button[data-action="record-purge"]').click()
    confirm_dialog(page)
    page.wait_for_url(re.compile(rf"/lists/{list_id}/\?preset=archive"))
    # п. 8: файла нет — по адресу 404, как у несуществующего, у управляющего и у правящего
    for who in (page, editor.page):
        response = who.request.get(path, max_redirects=0)
        assert response.status == 404, f"файл удалённой записи: {response.status}"
        assert "x-accel-redirect" not in response.headers
        assert who.request.get(_file_path(list_id, number, MISSING_ID), max_redirects=0).status == 404
        assert status_of(who, f"/lists/{list_id}/{number}/") == 404, "карточка удалённой записи открывается"
