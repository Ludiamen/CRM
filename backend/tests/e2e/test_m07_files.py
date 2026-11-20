"""T-8137: приёмка сценария 7 — файлы и картинки (FR-662, NFR-704).

SPEC-008, сценарий 7 «файлы и картинки», пункты приёмки 1–5 и замер NFR-704:
1. сообщение с картинкой проверено и чисто — в беседе видно уменьшенное изображение, нажатие открывает полное;
2. 11-й файл к сообщению — отказ с причиной (FR-662: до 10 файлов);
3. заражённый файл (EICAR) после проверки — в карантине, не скачивается и помечен, а сообщение остаётся;
4. исполняемый файл или архив с паролем — отказ с причиной;
5. файл ещё проверяется — по ссылке на него скачивания нет и видно «проверяется»;
   NFR-704 — проверка ClamAV стенда не дольше 1 минуты.

Источники: CONTRACT-008 § 10.2 (адреса `/messenger/files/`, `/messenger/files/<id>/`, `/thumb/`, поля `file`,
`chat`, `have`, ответы 404 с текстами), § 12.5 (`[data-messenger-file][data-file-state]`, `[data-messenger-upload]`,
`a[href="/messenger/files/<id>/"] > img[src="/messenger/files/<id>/thumb/"]`), § 13.1 (`files_limit`, `file_type`,
`file_pending`, `file_quarantine` и их тексты), § 13.3 («проверяется», «карантин», «Скачать»), § 14.3 (помощники
`helpers_messenger`); план — «Файлы и эскизы», «Проход в браузере»; задачи — T-8137, T-8130.

Решения файла:
- люди круга — `helpers_messenger.messenger_cast` один раз на круг браузера (фикстура `cast`, как в `test_m02_group`):
  девять учёток через интерфейс на каждый тест — часы прохода; беседа с файлами — личный диалог `writer` ↔ `peer`
  (он же второй участник для проверки выдачи файла);
- помощники T-8130: `open_messenger`, `start_dialog`, `upload`, `wait_clean`, `eicar_file`; таблетка загрузки и
  ответ `POST /messenger/files/` разбираются локально: `upload` утверждает успех, а приёмке нужны и отказы
  (11-й файл, исполняемый файл, архив с паролем), поэтому есть свой `_try_upload`; ожидания карантина в
  помощниках нет — его, как и договаривались в шапке `helpers_messenger`, держит этот файл (`_wait_quarantine`);
- ClamAV стенда настоящий: сразу после загрузки состояние `pending` или уже итоговое; у EICAR — `pending` или
  `quarantine`. Гонка проверки разрешается как в `test_f10_files.py` среза 007: состояние читается одним
  обращением к DOM, «проверяется» утверждается, если файл в этот момент ещё `pending`, а прямая ссылка
  проверяется по свежему ответу страницы; итоговое состояние затем утверждается всегда (контроль) — так «нет
  скачивания» относится именно к проверке, а не к отказу в доступе;
- исполняемый файл (PE) и архив ZIP с признаком шифрования собраны из байтов в самом файле: код приложения
  (`apps.*`) и `tests.support*` в e2e не импортируются, тест идёт с хоста против стенда;
- отказы — пары `(поле, data-code)` из ответа и `[data-error][data-code]` на странице (10.1, 10.2), тексты —
  подстрокой из 13.1; адреса файла отвечают 404 с текстом причины (10.2), без `X-Accel-Redirect`;
- тексты сообщений уникальны на круг, названия файлов — с меткой `_uid()`; ПДн нет (ФИО вымышленные, их заводит
  `messenger_cast`), секретов нет. Пропусков (`skip`/`xfail`) в файле нет: единственный допустимый skip круга —
  прежний в `tests/e2e/conftest.py` (Edge или Яндекс Браузер не установлен).
"""
import re
import secrets
import struct
import time
import zipfile
from io import BytesIO

import pytest
from playwright.sync_api import expect

from tests.e2e import helpers, helpers_messenger, helpers_org

MB = 1024 * 1024
FILE_SECONDS = 60.0                     # NFR-704: проверка ClamAV не дольше минуты
STATE_TIMEOUT = int(FILE_SECONDS * 1000)  # предел ожидания итогового состояния файла
BIG_FILE = 19 * MB                      # крупный груз: проверка идёт дольше мелкого (п. 5)
IMAGE_WIDTH = 1600                      # эскиз ≤ 1280 px, значит меньше оригинала
TXT = "Строка файла для приёмки мессенджера.\n".encode("utf-8")
LIMIT_TEXT = "Не больше 10 файлов к сообщению"   # CONTRACT-008, 13.1 (`files_limit`)
TYPE_TEXT = "Файл такого типа не принимается"    # CONTRACT-008, 13.1 (`file_type`)
PENDING_TEXT = "Файл ещё проверяется"            # CONTRACT-008, 13.1 (`file_pending`)
QUARANTINE_TEXT = "Файл в карантине"             # CONTRACT-008, 13.1 (`file_quarantine`)
_CHAT_URL = re.compile(r"/messenger/chats/(\d+)/")

_CASTS: dict = {}


# --- Люди круга и общие помощники файла ---------------------------------------------------------------------------

@pytest.fixture
def cast(admin_page, mailpit, new_context, stand_admin):
    """Люди и узлы сценариев (`helpers_messenger.messenger_cast`), один раз на круг браузера."""
    found = _CASTS.get(stand_admin.email)
    if found is None:
        found = helpers_messenger.messenger_cast(admin_page, mailpit, new_context)
        _CASTS[stand_admin.email] = found
    return found


def _uid() -> str:
    return secrets.token_hex(3)


def _word() -> str:
    """Уникальный текст сообщения круга: беседа пары общая для соседних тестов."""
    return f"файлы-{_uid()}"


def _chat_page(new_context, account, peer) -> tuple:
    """Личный диалог `account` ↔ `peer` (существующий или новый) и страница беседы: `start_dialog` уже
    отправляет первое сообщение и оставляет страницу в беседе (14.3). Возвращает `(страница, номер чата)`."""
    # список ждём без `[data-ws]`: «Общий чат» мог быть выключен соседним сценарием того же круга
    page = helpers_messenger.open_messenger(new_context(), account, live=False)
    chat_id = helpers_messenger.start_dialog(page, peer)
    expect(page.locator('[data-messenger-page="chat"]')).to_be_visible()
    found = _CHAT_URL.search(page.url)
    assert found, f"после начала диалога адрес {page.url!r}, ожидался /messenger/chats/<id>/"
    return page, chat_id


def _write(tmp_path, name: str, data: bytes):
    """Файл с заданными байтами во временном каталоге теста (пути берут помощники загрузки)."""
    path = tmp_path / name
    path.write_bytes(data)
    return path


def _file_node(page, file_id):
    """Файл сообщения `[data-messenger-file="<id>"][data-file-state]` (12.5): у таблетки формы состояния нет."""
    return page.locator(f'[data-messenger-file="{file_id}"][data-file-state]').first


def _state(page, file_id):
    """Состояние файла, прочитанное одним обращением к DOM: между чтениями проверка может закончиться."""
    node = _file_node(page, file_id)
    return node.get_attribute("data-file-state") if node.count() else None


def _fresh_state(page, chat_id, file_id) -> str:
    """Состояние файла по свежему ответу беседы (ответ на прямой запрос мог прийти уже после конца проверки)."""
    html = helpers_org.direct_get(page, f"/messenger/chats/{int(chat_id)}/").text()
    pattern = r'<[^>]*\bdata-messenger-file="%d"[^>]*>' % int(file_id)
    for tag in re.findall(pattern, html):
        found = re.search(r'\bdata-file-state="([^"]*)"', tag)
        if found:
            return found.group(1)
    raise AssertionError(f"в свежем ответе беседы {chat_id} нет файла {file_id} с data-file-state")


def _codes_in(html: str) -> list:
    """Пары `(поле или "", data-code)` отказов в HTML ответа (10.1)."""
    out = []
    for tag in re.findall(r"<[^>]*\bdata-code=\"[^\"]*\"[^>]*>", html):
        code = re.search(r'data-code="([^"]*)"', tag).group(1)
        field = re.search(r'data-error="([^"]*)"', tag)
        out.append((field.group(1) if field else "", code))
    return out


def _try_upload(page, path) -> list:
    """То же, что `upload`, но без утверждения успеха: пары `(поле, код)` отказов из ответа `POST /messenger/files/`
    (у `files_limit` в 13.1 указаны оба поля — `files` и `file`)."""
    form = page.locator("#messenger-form")
    with page.expect_response(lambda r: r.request.method == "POST" and "/messenger/files/" in r.url) as info:
        form.locator('input[type="file"][data-messenger-upload]').set_input_files(str(path))
    return _codes_in(info.value.text())


def _refusal(page, code: str, text: str) -> None:
    """Отказ файла на странице с причиной (10.1, 10.2): `[data-error="file"][data-code]`; поле `files` тоже
    принимается — в 13.1 у `files_limit` названы оба."""
    refusal = page.locator(f'[data-code="{code}"][data-error]').first
    expect(refusal).to_be_visible()
    field = refusal.get_attribute("data-error")
    assert field in ("file", "files"), f"отказ {code} у поля {field!r}, ожидались file/files"
    expect(refusal).to_contain_text(text)


def _wait_quarantine(page, file_id, timeout: int = STATE_TIMEOUT) -> None:
    """Ждёт `[data-file-state="quarantine"]` (EICAR) опросом с обновлением страницы, как `wait_clean` (14.3):
    пауза 2 с, предел — минута (NFR-704). «Чистый» — `AssertionError`."""
    deadline = time.monotonic() + timeout / 1000
    selector = f'[data-messenger-file="{file_id}"][data-file-state]'
    while True:
        node = page.locator(selector).first
        if node.count():
            state = node.get_attribute("data-file-state")
            if state == "quarantine":
                return
            assert state != "clean", f"файл {file_id}: ожидался карантин, а состояние «чистый»"
        if time.monotonic() > deadline:
            raise AssertionError(f"файл {file_id}: итог проверки не наступил за {timeout // 1000} с")
        page.wait_for_timeout(2_000)
        page.reload()
        page.wait_for_load_state()


def _executable() -> bytes:
    """Начало исполняемого файла Windows (PE): по содержимому это программа, что бы ни говорило имя."""
    return (b"MZ\x90\x00\x03\x00\x00\x00\x04\x00\x00\x00\xff\xff\x00\x00" + b"\x00" * 44 + b"\x40\x00\x00\x00"
            + b"PE\x00\x00" + b"\x00" * 20 + b"This program cannot be run in DOS mode.\r\n" + b"\x00" * 256)


def _encrypted_zip() -> bytes:
    """Архив ZIP с признаком шифрования (бит 0 общих флагов заголовков): пароль не нужен, признак — в байтах."""
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


# --- Тесты (по пунктам приёмки сценария 7) ------------------------------------------------------------------------

def test_m07_clean_image_in_chat_is_reduced_and_click_opens_full_size(cast, new_context, tmp_path):
    """Сценарий 7, п. 1 (FR-662): сообщение с картинкой — после проверки в беседе видно уменьшенное изображение
    ссылкой на оригинал, нажатие открывает полное."""
    page, _chat = _chat_page(new_context, cast.writer, cast.peer)
    name = f"снимок{_uid()}.png"
    path = _write(tmp_path, name, helpers.make_png(IMAGE_WIDTH, 1200))
    file_id = helpers_messenger.upload(page, path)
    message_id = helpers_messenger.write(page, f"Картинка {_word()}")
    helpers_messenger.wait_clean(page, file_id)
    # п. 1: картинка проверена и чиста — эскиз ссылкой на оригинал (12.5: `a[href] > img[src=…/thumb/]`)
    node = _file_node(page, file_id)
    expect(node).to_have_attribute("data-file-state", "clean")
    expect(node).to_contain_text(name)
    message = page.locator(f'article[data-message-id="{message_id}"]')
    link = message.locator(f'a[href="/messenger/files/{file_id}/"]').first
    thumb = link.locator(f'img[src="/messenger/files/{file_id}/thumb/"]')
    expect(thumb).to_be_visible()
    expect(thumb).to_have_js_property("complete", True)
    natural = thumb.evaluate("img => img.naturalWidth")
    assert 0 < natural < IMAGE_WIDTH, f"эскиз шириной {natural} px, оригинал {IMAGE_WIDTH} px — не уменьшен"
    # п. 1: нажатие открывает полное изображение (новая вкладка или эта же)
    if link.get_attribute("target") == "_blank":
        with page.context.expect_page() as opened:
            link.click()
        target = opened.value
    else:
        with page.expect_navigation():
            link.click()
        target = page
    target.wait_for_load_state()
    assert target.url.rstrip("/").endswith(f"/messenger/files/{file_id}"), target.url
    full = target.evaluate("() => document.images.length && document.images[0].naturalWidth")
    assert full == IMAGE_WIDTH, f"открылась картинка шириной {full} px, ожидалась {IMAGE_WIDTH} px"
    if target is not page:
        target.close()


def test_m07_eleventh_file_to_message_is_refused_with_reason(cast, new_context, tmp_path):
    """Сценарий 7, п. 2 (FR-662): десять файлов к сообщению принимаются, 11-й — отказ с причиной, лишний файл
    к сообщению не попадает."""
    page, _chat = _chat_page(new_context, cast.writer, cast.peer)
    form = page.locator("#messenger-form")
    for index in range(10):
        helpers_messenger.upload(page, _write(tmp_path, f"файл{index}-{_uid()}.txt", TXT + str(index).encode()))
    expect(form.locator("[data-messenger-file]")).to_have_count(10)
    # п. 2: 11-й файл — отказ «Не больше 10 файлов к сообщению» у поля файла
    codes = _try_upload(page, _write(tmp_path, f"лишний-{_uid()}.txt", TXT))
    assert ("file", "files_limit") in codes or ("files", "files_limit") in codes, codes
    _refusal(page, "files_limit", LIMIT_TEXT)
    expect(form.locator("[data-messenger-file]")).to_have_count(10)
    # десять принятых привязываются к сообщению: отказ был только у 11-го
    message_id = helpers_messenger.write(page, f"Десять файлов {_word()}")
    expect(page.locator(f'article[data-message-id="{message_id}"] [data-messenger-file]')).to_have_count(10)


def test_m07_eicar_file_is_quarantined_marked_not_downloadable_and_message_remains(
        cast, new_context, tmp_path):
    """Сценарий 7, п. 3 (FR-662, NFR-704): заражённый файл (EICAR) после проверки — в карантине, помечен и не
    скачивается ни по ссылке, ни по прямому адресу, а сообщение остаётся."""
    page, chat = _chat_page(new_context, cast.writer, cast.peer)
    text = f"Тест антивируса {_word()}"
    file_id = helpers_messenger.upload(page, helpers_messenger.eicar_file(tmp_path))
    message_id = helpers_messenger.write(page, text)
    _wait_quarantine(page, file_id)
    # п. 3: файл помечен «карантин», ссылки на скачивание нет
    message = page.locator(f'article[data-message-id="{message_id}"]')
    expect(message).to_contain_text(text)          # сообщение остаётся
    node = message.locator(f'[data-messenger-file="{file_id}"][data-file-state]')
    expect(node).to_have_count(1)
    expect(node).to_contain_text("eicar-test.txt")
    expect(node).to_contain_text("карантин")
    expect(node.locator("a[href]")).to_have_count(0)
    # п. 3: прямой адрес — 404 с причиной, выдачи и эскиза нет; проверяется у автора и у собеседника-участника
    peer = helpers_messenger.open_chat(new_context(), cast.peer, chat)
    for who in (page, peer):
        response = helpers_org.direct_get(who, f"/messenger/files/{file_id}/")
        assert response.status == 404, f"файл в карантине, а ответ {response.status}"
        assert "x-accel-redirect" not in response.headers
        assert QUARANTINE_TEXT in response.text()
        assert helpers_org.direct_get(who, f"/messenger/files/{file_id}/thumb/").status == 404


def test_m07_executable_and_password_archive_are_refused_with_reason(cast, new_context, tmp_path):
    """Сценарий 7, п. 4 (FR-662, NFR-704): исполняемый файл и архив с паролем не принимаются — отказ с причиной,
    к сообщению не прикладываются."""
    page, _chat = _chat_page(new_context, cast.writer, cast.peer)
    form = page.locator("#messenger-form")
    cases = (("программа.exe", _executable()), ("закрытый.zip", _encrypted_zip()))
    for name, data in cases:
        codes = _try_upload(page, _write(tmp_path, name, data))
        assert ("file", "file_type") in codes, f"{name}: отказ {codes}, ожидался file_type"
        _refusal(page, "file_type", TYPE_TEXT)
        expect(form.locator("[data-messenger-file]")).to_have_count(0)


def test_m07_file_still_checking_is_shown_with_note_and_link_gives_no_download(
        cast, new_context, tmp_path):
    """Сценарий 7, п. 5 (FR-662, NFR-704): пока файл проверяется, в беседе имя и пометка «проверяется» без
    ссылки, а прямой адрес файла не скачивает и отвечает «Файл ещё проверяется». Контроль: после проверки файл
    выдаётся — значит отказ был из-за проверки, а не из-за прав."""
    page, chat = _chat_page(new_context, cast.writer, cast.peer)
    name = f"груз{_uid()}.bin"
    path = _write(tmp_path, name, b"\x00" * BIG_FILE)   # крупный файл проверяется дольше мелкого
    file_id = helpers_messenger.upload(page, path)
    helpers_messenger.write(page, f"Ещё проверяется {_word()}")
    state = _state(page, file_id)
    if state == "pending":
        # п. 5: имя и пометка «проверяется», ссылки на скачивание нет
        node = _file_node(page, file_id)
        expect(node).to_contain_text(name)
        expect(node).to_contain_text("проверяется")
        expect(node.locator("a[href]")).to_have_count(0)
        # п. 5: пока по свежему ответу страницы файл ещё «проверяется» — прямая ссылка не скачивает
        if _fresh_state(page, chat, file_id) == "pending":
            response = helpers_org.direct_get(page, f"/messenger/files/{file_id}/")
            assert response.status == 404, f"файл «проверяется», а отдан: {response.status}"
            assert "x-accel-redirect" not in response.headers
            assert PENDING_TEXT in response.text()
    # контроль: проверка закончилась — файл выдаётся (сбой доступа исключён)
    helpers_messenger.wait_clean(page, file_id)
    assert helpers_org.direct_get(page, f"/messenger/files/{file_id}/").status == 200


def test_m07_clean_within_one_minute_of_attach_on_stand_clamav(cast, new_context, tmp_path):
    """Сценарий 7, NFR-704: на настоящем ClamAV стенда файл становится «чистым» не позже минуты после
    прикрепления."""
    page, _chat = _chat_page(new_context, cast.writer, cast.peer)
    path = _write(tmp_path, f"минута{_uid()}.png", helpers.make_png(640, 480))
    started = time.monotonic()                       # отсчёт — от прикрепления файла
    file_id = helpers_messenger.upload(page, path)
    helpers_messenger.write(page, f"Минута {_word()}")
    left = max(1.0, FILE_SECONDS - (time.monotonic() - started))
    helpers_messenger.wait_clean(page, file_id, timeout=int(left * 1000))
    elapsed = time.monotonic() - started
    assert elapsed <= FILE_SECONDS, f"проверка заняла {elapsed:.1f} с (предел {FILE_SECONDS:.0f} с)"
    expect(_file_node(page, file_id)).to_have_attribute("data-file-state", "clean")
    assert helpers_org.direct_get(page, f"/messenger/files/{file_id}/").status == 200