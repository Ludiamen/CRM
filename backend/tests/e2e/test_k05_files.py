"""T-5144: сценарий 5 — вложения и картинки в тексте, карантин (FR-402, FR-409, FR-422, FR-423, NFR-404, NFR-405).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-005.md, разделы 10.5, 11.3, 11.4, 12, 17):
- каждый тест заводит своих сотрудников, свою рубрику и статью; названия уникальны, общих настроек тесты не меняют и
  сброса стенда в файле нет;
- ClamAV стенда настоящий: чистый файл, EICAR из частей (`helpers_kb.eicar_bytes`), ожидание «проверяется → чистый» —
  `helpers_kb.wait_file_clean` (предел 1 минута, NFR-404);
- состояние «проверяется» живёт недолго: как в тестах вложений заявок (test_d12_attachments), сразу после прикрепления
  состояние — `pending` или уже `clean`; проверки «пока проверяется» выполняются, если файл ещё `pending` в момент
  проверки, а проверки «после проверки» — всегда;
- состояние картинки в тексте различает ответ адреса `/kb/<id>/images/<N>/` (заголовок `X-KB-Placeholder` и слово в
  SVG, раздел 11.4, решение 19 раздела 17): `checking` («проверяется»), `removed` («вложение удалено»), `unavailable`
  («недоступно»);
- сбой ClamAV (сценарий 9) в приёмке не воспроизводится (решения 12 и 36 задач).
"""
import re
import struct
import time

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_kb, helpers_org
from tests.e2e.helpers_kb import (
    article_form, attach_file, create_draft, create_rubric, file_row, open_article, open_edit, open_preview, press_save,
    try_attach_file, unique_title, unique_word, wait_file_clean)

MISSING_ID = 2_000_000_000  # номер, которого на стенде нет (в пределах целого PostgreSQL)
MB = 1024 * 1024
MARKUP = re.compile(r"!\[([^\]]*)\]\(att:(\d+)\)")
OVPN = ("client\ndev tun\nproto udp\nremote vpn" + ".example.test 1194\nnobind\n").encode("ascii")


# --- Общие помощники файла ----------------------------------------------------------------------------------

def _rubric(admin_page) -> str:
    """Своя рубрика круга (создаёт управляющий); возвращает название."""
    name = helpers_org.unique_name("Рубрика")
    create_rubric(admin_page, name)
    return name


def _draft(admin_page, employee):
    """Автор («Сотрудник ИТ») с черновиком в своей рубрике: `(автор, страница автора, номер статьи)`; страница автора
    остаётся на форме правки."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    article_id = create_draft(author.page, title=unique_title("Вложения"), text="Текст статьи.", rubric=rubric)
    return author, author.page, article_id


def _png(name_prefix: str = "screen", size: int = 40) -> tuple:
    """Настоящий PNG и его имя."""
    return helpers.make_png(size, size), f"{name_prefix}.png"


def _text_field(page):
    return article_form(page).locator("textarea[name=text]")


def _save_and_open(page, article_id) -> None:
    """Сохраняет форму правки (после правки — адрес статьи `/kb/<id>/`)."""
    press_save(page)
    page.wait_for_url(re.compile(rf"/kb/{article_id}/$"))
    expect(page.locator(f'article[data-article-id="{article_id}"]')).to_be_visible()


def _image_response(page, article_id, file_id):
    """Прямой запрос адреса картинки `/kb/<id>/images/<N>/`: `(ответ, значение X-KB-Placeholder или "", тело)`."""
    response = page.request.get(f"/kb/{article_id}/images/{file_id}/", max_redirects=0)
    header = response.headers.get("x-kb-placeholder", "")
    body = response.body()
    return response, header, body


def _image_loaded(page, image, timeout: float = 20.0) -> int:
    """Ждёт, пока картинка `img` загрузится (`naturalWidth > 0`); возвращает ширину; иначе `AssertionError`."""
    expect(image).to_be_visible()
    image.scroll_into_view_if_needed()
    deadline = time.monotonic() + timeout
    while True:
        width = image.evaluate("el => (el.complete ? el.naturalWidth : 0)")
        if width > 0:
            return width
        if time.monotonic() > deadline:
            raise AssertionError("картинка не загрузилась (naturalWidth равен нулю)")
        page.wait_for_timeout(250)


def _body_image(page, article_id, file_id):
    """Картинка вложения `file_id` в тексте открытой статьи."""
    return page.locator(f'[data-field="body"] img[src="/kb/{article_id}/images/{file_id}/"]')


def _file_state(page, file_id) -> str:
    return file_row(page, file_id).get_attribute("data-file-state")


def _encrypted_zip() -> bytes:
    """Архив ZIP с признаком шифрования (бит 0 в общих флагах заголовков): настоящий пароль не нужен, определение
    идёт по флагу, как у любого проверяющего «архив с паролем»."""
    import io
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


def _executable() -> bytes:
    """Начало исполняемого файла Windows (PE): по содержимому это программа, что бы ни говорило имя."""
    # e_lfanew (0x3C) указывает на подпись `PE\0\0` в 0x40 — так её ищет проверка ядра (CONTRACT-005 3.5: PE)
    return (b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"\x00" * 44 + b"\x40\x00\x00\x00"
            + b"PE\x00\x00" + b"\x00" * 20 + b"This program cannot be run in DOS mode.\r\n" + b"\x00" * 256)


def _file_state_fresh(page, article_id, file_id) -> str:
    """Состояние файла по свежей странице правки (ответ на прямой запрос мог прийти уже после конца проверки)."""
    html = page.request.get(f"/kb/{article_id}/edit/").text()
    tag = re.search(rf'<li\b[^>]*\bdata-file-id="{re.escape(str(file_id))}"[^>]*>', html)
    assert tag, f"в странице правки нет строки вложения {file_id}"
    state = re.search(r'\bdata-file-state="([^"]*)"', tag.group(0))
    assert state, f"у строки вложения {file_id} нет data-file-state"
    return state.group(1)


def _snapshot_checking(page, file_id) -> str:
    """Состояние строки вложения, прочитанное в момент проверки (одним обращением к DOM). Если оно «pending» — тут же
    проверяется «проверяется» и отсутствие ссылки скачивания (п. 61 раздела 17: ветвь проверяется, если наблюдается).
    Возвращает прочитанное состояние."""
    seen = file_row(page, file_id).evaluate(
        """el => ({state: el.getAttribute("data-file-state"),
                   text: (el.querySelector('[data-field="state"]') || {textContent: ""}).textContent,
                   links: el.querySelectorAll('a[data-action="kb-download"]').length})""")
    assert seen["state"] in ("pending", "clean"), f"состояние сразу после прикрепления: {seen['state']!r}"
    if seen["state"] == "pending":
        assert "проверяется" in seen["text"], f"у вложения «pending» подпись {seen['text']!r}"
        assert seen["links"] == 0, "у вложения «проверяется» есть ссылка скачивания"
    return seen["state"]


# --- Тесты ---------------------------------------------------------------------------------------------------

def test_k05_attach_ovpn_and_png_listed_as_checking_then_clean(admin_page, employee):
    """Сценарий 5, п. 1: автор открыл сохранённую статью, прикрепил `vpn.ovpn` и `screen.png` — оба в списке
    «Вложения» в состоянии «проверяется», затем «чистый» (FR-422)."""
    author, page, article_id = _draft(admin_page, employee)
    # п. 1: статья сохранена, форма правки открыта, форма «Вложить» на месте
    open_edit(page, article_id)
    expect(page.locator('button[data-action="kb-attach"]')).to_be_enabled()
    png, png_name = _png()
    # п. 1: прикрепляет vpn.ovpn и screen.png
    # п. 61: «проверяется» проверяется сразу после каждого прикрепления, до следующего (состояние читается в момент проверки)
    ovpn_id = attach_file(page, article_id, OVPN, "vpn.ovpn")
    _snapshot_checking(page, ovpn_id)
    png_id = attach_file(page, article_id, png, png_name, mime="image/png")
    _snapshot_checking(page, png_id)
    # п. 1: оба видны в списке «Вложения» (имя, размер, тип картинки)
    ovpn_row, png_row = file_row(page, ovpn_id), file_row(page, png_id)
    expect(ovpn_row.locator('[data-field="name"]')).to_have_text("vpn.ovpn")
    expect(png_row.locator('[data-field="name"]')).to_have_text(png_name)
    expect(ovpn_row.locator('[data-field="size"]')).not_to_be_empty()
    expect(png_row).to_have_attribute("data-image", "png")
    expect(ovpn_row).to_have_attribute("data-image", "")
    # п. 1: затем «чистый» — оба
    assert wait_file_clean(page, article_id, ovpn_id) == "clean"
    assert wait_file_clean(page, article_id, png_id) == "clean"
    for row in (file_row(page, ovpn_id), file_row(page, png_id)):
        expect(row).to_have_attribute("data-file-state", "clean")
        expect(row.locator('[data-field="state"]')).not_to_contain_text("проверяется")
        expect(row.locator('[data-field="state"]')).not_to_contain_text("карантин")
        expect(row.locator('a[data-action="kb-download"]')).to_have_count(1)
    # п. 1: после обновления страницы оба вложения на месте
    open_edit(page, article_id)
    expect(page.locator("[data-kb-files] li[data-file-id]")).to_have_count(2)


def test_k05_insert_image_button_of_clean_attachment_puts_markup_and_image_shows_in_preview_and_article(
        admin_page, employee):
    """Сценарий 5, п. 2: вложение `screen.png` чистое; автор нажимает «Картинка» у него — в текст вставлена разметка
    картинки, в «Предпросмотре» и в статье картинка показана (FR-423)."""
    author, page, article_id = _draft(admin_page, employee)
    png, png_name = _png()
    png_id = attach_file(page, article_id, png, png_name, mime="image/png")
    # п. 2: вложение чистое
    assert wait_file_clean(page, article_id, png_id) == "clean"
    row = file_row(page, png_id)
    # п. 2: «Картинка» у чистой картинки
    button = row.locator('button[data-action="kb-insert-image"]')
    expect(button).to_be_visible()
    insert = button.get_attribute("data-insert")
    assert insert and MARKUP.fullmatch(insert) and insert.endswith(f"(att:{png_id})"), f"разметка вставки: {insert!r}"
    _text_field(page).fill("Снимок экрана:\n")
    button.click()
    # п. 2: в тексте — разметка картинки
    expect(_text_field(page)).to_have_value(re.compile(rf"!\[[^\]]*\]\(att:{png_id}\)"))
    # п. 2: в «Предпросмотре» картинка показана
    open_preview(page)
    preview_image = page.locator(f'[data-kb-panel=preview] [data-kb-preview] img[src="/kb/{article_id}/images/{png_id}/"]')
    assert _image_loaded(page, preview_image) > 0
    # п. 2: в сохранённой статье картинка показана
    helpers_kb.open_text_tab(page)
    _save_and_open(page, article_id)
    assert _image_loaded(page, _body_image(page, article_id, png_id)) > 0


def test_k05_image_of_checking_attachment_shows_checking_placeholder_then_image_after_scan_without_article_edit(
        admin_page, employee):
    """Сценарий 5, п. 3: картинка вставлена, пока вложение «проверяется» — вместо неё заглушка «проверяется»; после
    проверки картинка показывается без правки статьи (FR-423)."""
    author, page, article_id = _draft(admin_page, employee)
    open_edit(page, article_id)
    name = f"{unique_word('pic')}.png"
    # п. 3: картинка вставлена кнопкой «Картинка» панели сразу после загрузки (вопрос C-16)
    with page.expect_file_chooser(timeout=10_000) as chooser:
        page.locator('[data-kb-toolbar] button[data-md="image"]').click()
    chooser.value.set_files({"name": name, "mimeType": "image/png", "buffer": helpers.make_png(1000, 1000, noise=True)})
    expect(_text_field(page)).to_have_value(MARKUP, timeout=30_000)
    found = MARKUP.search(_text_field(page).input_value())
    png_id = found.group(2)
    # п. 3: пока файл «проверяется» — адрес картинки отдаёт заглушку «проверяется»
    response, header, body = _image_response(page, article_id, png_id)
    assert response.status == 200
    saw_checking = header == "checking"
    if saw_checking:
        assert "проверяется" in body.decode("utf-8", "replace"), "в заглушке нет слова «проверяется»"
    else:
        assert header == "", f"заглушка {header!r} у файла, который не карантин и не удалён"
    # п. 3: статья сохранена с картинкой в тексте
    _save_and_open(page, article_id)
    image = _body_image(page, article_id, png_id)
    expect(image).to_be_visible()
    # п. 3 (п. 61): сначала запрос картинки, потом свежее состояние; заглушка обязательна, если файл всё ещё «pending»
    _, header, body = _image_response(page, article_id, png_id)
    if _file_state_fresh(page, article_id, png_id) == "pending":
        assert header == "checking" and "проверяется" in body.decode("utf-8", "replace")
    else:
        assert header in ("checking", ""), f"заглушка {header!r} у файла, который не карантин и не удалён"
    versions_before = helpers_kb.history_versions(page, article_id)
    # п. 3: после проверки картинка показывается без правки статьи
    assert wait_file_clean(page, article_id, png_id) == "clean"
    open_article(page, article_id)
    response, header, body = _image_response(page, article_id, png_id)
    assert response.status == 200 and header == "", "после проверки адрес картинки всё ещё отдаёт заглушку"
    assert body[:8] == b"\x89PNG\r\n\x1a\n", "после проверки адрес картинки отдаёт не PNG"
    assert _image_loaded(page, _body_image(page, article_id, png_id)) > 0
    assert helpers_kb.history_versions(page, article_id) == versions_before, "картинка появилась правкой статьи"


def test_k05_eicar_attachment_goes_to_quarantine_marked_not_downloadable_not_shown_with_placeholder_in_text(
        admin_page, employee):
    """Сценарий 5, п. 4: заражённое вложение (EICAR) после проверки в карантине: в списке с пометкой «в карантине»,
    не скачивается и не показывается, на месте картинки заглушка (FR-422, FR-423)."""
    author, page, article_id = _draft(admin_page, employee)
    name = f"{unique_word('virus')}.txt"
    file_id = attach_file(page, article_id, helpers_kb.eicar_bytes(), name, mime="text/plain")
    # п. 4: проверка завершилась — карантин
    assert wait_file_clean(page, article_id, file_id) == "quarantine"
    row = file_row(page, file_id)
    # п. 4: в списке с пометкой «в карантине»
    expect(row.locator('[data-field="name"]')).to_have_text(name)
    expect(row.locator('[data-field="state"]')).to_contain_text("в карантине")
    # п. 4: не скачивается: ни ссылки, ни кнопок вставки (решение 20 раздела 17)
    expect(row.locator('a[data-action="kb-download"]')).to_have_count(0)
    expect(row.locator('button[data-action="kb-insert-link"]')).to_have_count(0)
    expect(row.locator('button[data-action="kb-insert-image"]')).to_have_count(0)
    assert helpers_org.direct_get(page, f"/kb/{article_id}/files/{file_id}/").status == 404, "карантин отдан по адресу"
    # п. 4: на месте картинки заглушка
    _text_field(page).fill(f"Заражённый файл:\n\n![{name}](att:{file_id})\n")
    _save_and_open(page, article_id)
    expect(page.locator(f'[data-kb-files] li[data-file-id="{file_id}"] [data-field="state"]')).to_contain_text("в карантине")
    expect(page.locator(f'[data-kb-files] li[data-file-id="{file_id}"] a[data-action="kb-download"]')).to_have_count(0)
    response, header, body = _image_response(page, article_id, file_id)
    assert response.status == 200
    assert header == "unavailable", f"заглушка карантина: {header!r}"
    assert "недоступно" in body.decode("utf-8", "replace"), "в заглушке нет слова «недоступно»"
    assert body[:4] != b"\x89PNG" and not response.headers.get("content-type", "").startswith("text/plain")


def test_k05_file_25mb_executable_and_password_archive_are_rejected_with_visible_reason(admin_page, employee):
    """Сценарий 5, п. 5: файл 25 МБ, исполняемый файл и архив с паролем не приняты, у каждого видна причина
    (FR-422)."""
    author, page, article_id = _draft(admin_page, employee)
    cases = (
        ("too_big", "Файл больше 20 МБ", b"\x00" * (25 * MB), "big-25mb.bin"),
        ("executable", "Исполняемые файлы не принимаются", _executable(), "tool.exe"),
        ("encrypted", "Архивы с паролем не принимаются", _encrypted_zip(), "locked.zip"),
    )
    for code, text, data, name in cases:
        # п. 5: файл прикрепляется — отказ с причиной над списком
        got = try_attach_file(page, article_id, data, name)
        assert got == code, f"{name}: отказ {got!r}, ожидался {code!r}"
        alert = page.locator(f'[data-kb-files] [role=alert][data-code="{code}"]')
        expect(alert).to_be_visible()
        expect(alert).to_contain_text(text)
        # п. 5: файла в списке нет
        expect(page.locator("[data-kb-files] li[data-file-id]").filter(has_text=name)).to_have_count(0)
    open_edit(page, article_id)
    expect(page.locator("[data-kb-files] li[data-file-id]")).to_have_count(0)


def test_k05_twenty_first_attachment_is_refused_with_explanation(admin_page, employee):
    """Сценарий 5, п. 6: у статьи уже 20 вложений — двадцать первое получает отказ с пояснением (FR-422)."""
    author, page, article_id = _draft(admin_page, employee)
    # п. 6: у статьи 20 вложений
    for index in range(20):
        code = try_attach_file(page, article_id, f"файл номер {index}\n".encode(), f"doc-{index:02d}.txt",
                               mime="text/plain")
        assert code == "", f"вложение {index + 1} отклонено: {code}"
    open_edit(page, article_id)
    expect(page.locator("[data-kb-files] li[data-file-id]")).to_have_count(20)
    # п. 6: двадцать первое — отказ с пояснением
    code = try_attach_file(page, article_id, b"21\n", "doc-21.txt", mime="text/plain")
    assert code == "limit_20", f"отказ {code!r}, ожидался limit_20"
    alert = page.locator('[data-kb-files] [role=alert][data-code="limit_20"]')
    expect(alert).to_contain_text("У статьи уже 20 файлов")
    expect(page.locator("[data-kb-files] li[data-file-id]")).to_have_count(20)
    expect(page.locator("[data-kb-files] li[data-file-id]").filter(has_text="doc-21.txt")).to_have_count(0)
    open_edit(page, article_id)
    expect(page.locator("[data-kb-files] li[data-file-id]")).to_have_count(20)


def test_k05_external_image_or_other_article_attachment_in_text_is_not_shown_and_link_text_is_shown(
        admin_page, employee):
    """Сценарий 5, п. 7: в тексте картинка по внешнему адресу и картинка-вложение другой статьи — при открытии статьи
    не показаны, на их месте виден текст (заглушка «[вложение недоступно: подпись]», 17.21) (FR-402, FR-423,
    NFR-405)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    page = author.page
    # п. 7: у другой статьи есть чистое вложение-картинка
    other_id = create_draft(page, title=unique_title("Чужая"), text="Другая статья.", rubric=rubric)
    png, png_name = _png("other")
    other_file = attach_file(page, other_id, png, png_name, mime="image/png")
    assert wait_file_clean(page, other_id, other_file) == "clean"
    # п. 7: в тексте этой статьи — внешняя картинка и вложение другой статьи
    host = "img.evil" + ".example.test"
    foreign_caption, external_caption = unique_word("foreign"), unique_word("external")
    text = (f"Текст до.\n\n![{foreign_caption}](att:{other_file})\n\n"
            f"![{external_caption}](https://{host}/p.png)\n\nТекст после.\n")
    article_id = create_draft(page, title=unique_title("Своя"), text=text, rubric=rubric)

    def check(scope, where):
        # п. 7: картинки нет, внешнего адреса и адреса чужой картинки в выводе нет
        expect(scope.locator("img")).to_have_count(0)
        for caption in (foreign_caption, external_caption):
            expect(scope.locator("span.kb-noimg").filter(has_text=f"вложение недоступно: {caption}")).to_have_count(1)
        html = scope.inner_html()
        assert host not in html, f"{where}: внешний адрес картинки остался в выводе"
        assert f"/kb/{other_id}/images/" not in html, f"{where}: адрес картинки другой статьи остался в выводе"

    # п. 7: «Предпросмотр» формы
    open_edit(page, article_id)
    open_preview(page)
    check(page.locator("[data-kb-panel=preview] [data-kb-preview]"), "предпросмотр")
    # п. 7: открытая статья
    open_article(page, article_id)
    check(page.locator(f'article[data-article-id="{article_id}"] [data-field="body"]'), "статья")


def test_k05_attachment_url_of_invisible_article_is_denied_like_missing_file(admin_page, employee):
    """Сценарий 5, п. 8: сотрудник, который не видит статью (чужой черновик; статья в корзине — не управляющий),
    открывает адрес вложения напрямую — отказ, как у несуществующего файла (FR-422, FR-409)."""
    rubric = _rubric(admin_page)
    author = helpers_kb.make_editor(employee)
    reader = helpers_kb.make_reader(employee)
    png, png_name = _png()
    # п. 8: чужой черновик с чистым вложением
    draft_id = create_draft(author.page, title=unique_title("Черновик"), text="Черновик.", rubric=rubric)
    draft_file = attach_file(author.page, draft_id, png, png_name, mime="image/png")
    assert wait_file_clean(author.page, draft_id, draft_file) == "clean"
    # контроль: автору файл выдаётся, адреса несуществующего файла и статьи — 404
    assert helpers_org.direct_get(author.page, f"/kb/{draft_id}/files/{draft_file}/").status == 200
    missing_file = helpers_org.direct_get(reader.page, f"/kb/{draft_id}/files/{MISSING_ID}/")
    missing_article = helpers_org.direct_get(reader.page, f"/kb/{MISSING_ID}/files/{MISSING_ID}/")
    assert missing_file.status == 404 and missing_article.status == 404
    # п. 8: читатель открывает адреса вложения чужого черновика — отказ, как у несуществующего
    for path in (f"/kb/{draft_id}/files/{draft_file}/", f"/kb/{draft_id}/images/{draft_file}/"):
        response = helpers_org.direct_get(reader.page, path)
        assert response.status == missing_file.status == 404, f"{path}: {response.status}"
        assert "x-accel-redirect" not in response.headers
        assert response.headers.get("content-type", "").split(";")[0] != "image/png"
    # п. 8: статья в корзине — не управляющему
    trash_id = create_draft(admin_page, title=unique_title("Корзина"), text="Будет в корзине.", rubric=rubric)
    trash_file = attach_file(admin_page, trash_id, png, png_name, mime="image/png")
    assert wait_file_clean(admin_page, trash_id, trash_file) == "clean"
    helpers_kb.publish_from_article_page(admin_page, trash_id)
    # контроль: опубликованной статьи файл читателю выдаётся
    assert helpers_org.direct_get(reader.page, f"/kb/{trash_id}/files/{trash_file}/").status == 200
    open_article(admin_page, trash_id)
    admin_page.once("dialog", lambda dialog: dialog.accept())
    admin_page.locator('form[data-form="kb-trash"] button').first.click()
    expect(admin_page.locator("[data-kb-trash-mark]")).to_be_visible()
    open_article(admin_page, trash_id)
    expect(admin_page.locator(f'article[data-article-id="{trash_id}"]')).to_have_attribute("data-article-state", "trash")
    for path in (f"/kb/{trash_id}/files/{trash_file}/", f"/kb/{trash_id}/images/{trash_file}/"):
        response = helpers_org.direct_get(reader.page, path)
        assert response.status == 404, f"{path}: статья в корзине, а ответ {response.status}"
        assert "x-accel-redirect" not in response.headers


def test_k05_deleting_quarantined_attachment_removes_it_from_list_and_image_markup_shows_deleted_placeholder(
        admin_page, employee):
    """Сценарий 5, п. 10: вложение в карантине; автор удаляет его из статьи — оно исчезает из списка, разметка
    картинки в тексте показывает заглушку «вложение удалено» (FR-423)."""
    author, page, article_id = _draft(admin_page, employee)
    name = f"{unique_word('virus')}.txt"
    file_id = attach_file(page, article_id, helpers_kb.eicar_bytes(), name, mime="text/plain")
    assert wait_file_clean(page, article_id, file_id) == "quarantine"
    # п. 10: разметка картинки с этим вложением стоит в тексте сохранённой статьи
    _text_field(page).fill(f"До.\n\n![{name}](att:{file_id})\n\nПосле.\n")
    _save_and_open(page, article_id)
    open_edit(page, article_id)
    # п. 10: автор удаляет вложение из статьи
    page.once("dialog", lambda dialog: dialog.accept())
    file_row(page, file_id).locator('button[data-action="kb-file-delete"]').click()
    # п. 10: оно исчезает из списка (и после обновления страницы)
    expect(file_row(page, file_id)).to_have_count(0)
    open_edit(page, article_id)
    expect(file_row(page, file_id)).to_have_count(0)
    assert "att:" + file_id in _text_field(page).input_value(), "разметка картинки пропала из текста"
    # п. 10: разметка в тексте остаётся и показывает заглушку «вложение удалено»
    response, header, body = _image_response(page, article_id, file_id)
    assert response.status == 200
    assert header == "removed", f"заглушка удалённого вложения: {header!r}"
    assert "вложение удалено" in body.decode("utf-8", "replace"), "в заглушке нет слов «вложение удалено»"
    assert helpers_org.direct_get(page, f"/kb/{article_id}/files/{file_id}/").status == 404
    open_article(page, article_id)
    body_block = page.locator(f'article[data-article-id="{article_id}"] [data-field="body"]')
    image = _body_image(page, article_id, file_id)
    if image.count():
        expect(image).to_have_count(1)  # картинка остаётся разметкой адреса, а адрес отдаёт заглушку «removed»
    else:
        expect(body_block.locator("span.kb-noimg").filter(has_text=f"вложение недоступно: {name}")).to_have_count(1)
    expect(page.locator(f'[data-kb-files] li[data-file-id="{file_id}"]')).to_have_count(0)


def test_k05_executable_renamed_to_photo_png_is_rejected_by_content_type(admin_page, employee):
    """Сценарий 5, п. 11: исполняемый файл, переименованный в `photo.png`, не принят — тип определён по содержимому
    (FR-422)."""
    author, page, article_id = _draft(admin_page, employee)
    # п. 11: прикрепляет исполняемый файл под именем photo.png (тип png заявлен и в имени, и в заголовке)
    code = try_attach_file(page, article_id, _executable(), "photo.png", mime="image/png")
    assert code == "executable", f"отказ {code!r}, ожидался executable"
    # п. 11: файл не принят, причина видна
    alert = page.locator('[data-kb-files] [role=alert][data-code="executable"]')
    expect(alert).to_be_visible()
    expect(alert).to_contain_text("Исполняемые файлы не принимаются")
    expect(page.locator("[data-kb-files] li[data-file-id]")).to_have_count(0)
    open_edit(page, article_id)
    expect(page.locator("[data-kb-files] li[data-file-id]")).to_have_count(0)


def test_k05_checking_attachment_is_not_given_by_download_button_or_direct_url(admin_page, employee):
    """Сценарий 5, п. 12: вложение «проверяется» — кнопка скачивания не выдаёт файл, адрес напрямую тоже (FR-422)."""
    author, page, article_id = _draft(admin_page, employee)
    name = f"{unique_word('big')}.bin"
    # п. 12: крупный файл проверяется дольше мелкого
    file_id = attach_file(page, article_id, b"\x00" * (19 * MB), name)
    # п. 12 (п. 61): кнопки скачивания нет, пока «pending» (состояние читается в момент проверки)
    state = _snapshot_checking(page, file_id)
    if state == "pending":
        # п. 12: адрес напрямую — файл не выдан (404), если после запроса файл всё ещё «проверяется»
        response = helpers_org.direct_get(page, f"/kb/{article_id}/files/{file_id}/")
        if _file_state_fresh(page, article_id, file_id) == "pending":
            assert response.status == 404, f"файл «проверяется» отдан: {response.status}"
            assert "x-accel-redirect" not in response.headers
    # после проверки файл выдаётся (контроль того, что отказ был из-за состояния)
    assert wait_file_clean(page, article_id, file_id) == "clean"
    expect(file_row(page, file_id).locator('a[data-action="kb-download"]')).to_have_count(1)
    assert helpers_org.direct_get(page, f"/kb/{article_id}/files/{file_id}/").status == 200


def test_k05_clean_status_appears_within_one_minute_of_attach_on_stand_clamav(admin_page, employee):
    """Сценарий 5, п. 1 и NFR-404: на настоящем ClamAV стенда файл становится «чистым» не позже, чем через минуту
    после прикрепления (FR-422, NFR-404)."""
    author, page, article_id = _draft(admin_page, employee)
    png, png_name = _png()
    started = time.monotonic()
    # NFR-404: прикрепление (отсчёт от нажатия «Вложить»)
    file_id = attach_file(page, article_id, png, png_name, mime="image/png")
    left = max(1.0, 60.0 - (time.monotonic() - started))
    state = wait_file_clean(page, article_id, file_id, timeout=left)
    elapsed = time.monotonic() - started
    # NFR-404: «чистый» и не позже минуты
    assert state == "clean", f"файл признан {state!r}"
    assert elapsed <= 60.0, f"проверка заняла {elapsed:.1f} с (предел 60 с)"
    expect(file_row(page, file_id)).to_have_attribute("data-file-state", "clean")
    expect(file_row(page, file_id).locator('a[data-action="kb-download"]')).to_have_count(1)


def test_k05_article_image_through_real_nginx_has_natural_width_above_zero_and_png_response_type(
        admin_page, employee):
    """Сценарий 5, п. 2 через настоящий nginx стенда: картинка статьи загружается (`naturalWidth > 0`), адрес отдаёт
    PNG, а не пустой ответ (FR-423)."""
    author, page, article_id = _draft(admin_page, employee)
    png, png_name = _png("nginx", 64)
    png_id = attach_file(page, article_id, png, png_name, mime="image/png")
    assert wait_file_clean(page, article_id, png_id) == "clean"
    _text_field(page).fill(f"Картинка через nginx:\n\n![{png_name}](att:{png_id})\n")
    _save_and_open(page, article_id)
    # картинка в статье загружена браузером
    image = _body_image(page, article_id, png_id)
    assert _image_loaded(page, image) > 0
    # адрес картинки: PNG, тело есть, служебный заголовок наружу не виден
    response = page.request.get(image.get_attribute("src"), max_redirects=0)
    assert response.status == 200
    assert response.headers.get("content-type", "").split(";")[0].strip() == "image/png", response.headers.get("content-type")
    assert "x-accel-redirect" not in response.headers
    assert "x-kb-placeholder" not in response.headers
    assert response.body()[:8] == b"\x89PNG\r\n\x1a\n", "тело ответа не PNG"
    assert "content-disposition" not in response.headers
    # и на странице статьи после обновления
    page.reload()
    assert _image_loaded(page, _body_image(page, article_id, png_id)) > 0
