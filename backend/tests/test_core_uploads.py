"""T-5113: проверки загрузки в ядре — `apps.core.services.uploads` (FR-424, NFR-411). Сценарии 3 и 12 спеки.

Перенос проверок вложений из `servicedesk` в ядро (CONTRACT-005, 3.5, 4.4, 2.1, 2.3): отказ по размеру,
исполняемому файлу и архиву с паролем, формат картинки по содержимому, предел точек, `store`/`move`,
итог проверки ClamAV и прежние имена `servicedesk.attachments`. Антивирус подменяется только строкой
`apps.integrations.clamav.services.scan` (помощники `scan_clean`/`scan_found`); файловый том — настоящий
(`protected_root`). Код среза на уровне модуля не импортируется (CONTRACT-005, шапка).
"""
import hashlib
import importlib
import io

import pytest

from tests import support
from tests import support_kb as kb
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

MB = 1024 * 1024
SCAN_JOB = "apps.core.tasks.scan_file"
EXECUTABLE_SAMPLES = ("exe_pe.bin", "exe_elf.bin", "exe_macho64_le.bin", "exe_macho32_be.bin", "exe_macho_fat.bin",
                      "exe_script.bin", "exe_msi.bin", "exe_jar.zip")
ENCRYPTED_ZIP_SAMPLES = ("enc_zip_zipcrypto.zip", "enc_zip_aes.zip", "enc_zip_second_entry.zip")
ENCRYPTED_OTHER_SAMPLES = ("enc_rar4_data.rar", "enc_rar4_headers.rar", "enc_rar5_data.rar", "enc_rar5_headers.rar",
                           "enc_7z_plain_header.7z", "enc_7z_encrypted_header.7z")
CLEAN_SAMPLES = ("plain.zip", "plain_rar4.rar", "plain_rar5.rar", "plain_7z_plain_header.7z", "image.png",
                 "image.jpg", "not_exe_odf_manifest.zip")


# --- помощники файла --------------------------------------------------------------------------------

def _uploads():
    from apps.core.services import uploads

    return uploads


def _reason(name: str, data: bytes, max_file: int = 20 * MB, size: int | None = None) -> str:
    return _uploads().reject_reason(name, data, len(data) if size is None else size, max_file)


def _image(fmt: str, width: int = 32, height: int = 24) -> bytes:
    """Картинка формата Pillow (`PNG`, `JPEG`, `GIF`, `WEBP`) без внешних файлов."""
    from PIL import Image

    out = io.BytesIO()
    Image.new("RGB", (width, height), (30, 90, 160)).save(out, fmt)
    return out.getvalue()


def _att():
    from apps.servicedesk.services import attachments

    return attachments


def _jobs_of(stored) -> list:
    return [job for job in org.files_jobs() if job.func_name == SCAN_JOB and tuple(job.args) == (str(stored.pk),)]


def _store(data: bytes, name: str = "файл.txt", purpose: str = "knowledge"):
    """`uploads.store` без исполнения заданий после фиксации (очередь остаётся пустой)."""
    return _uploads().store(data, name, purpose)


def _paths(protected_root, stored) -> dict:
    sid = str(stored.pk)
    return {"incoming": protected_root / "incoming" / sid, "attachments": protected_root / "attachments" / sid,
            "quarantine": protected_root / "quarantine" / sid}


def _fresh(obj):
    obj.refresh_from_db()
    return obj


# --- reject_reason ----------------------------------------------------------------------------------

def test_reject_reason_too_big_over_limit():
    """FR-424: размер больше `max_file` — `"too_big"`; размер проверяется раньше содержимого (исполняемый файл тоже «слишком большой»)."""
    assert _reason("отчёт.txt", b"x" * 11, max_file=10) == "too_big"
    assert _reason("большой.bin", b"x", max_file=10, size=11) == "too_big", "решает переданный `size`"
    pe = sd.sample("exe_pe.bin")
    assert _reason("setup.exe", pe, max_file=len(pe) - 1) == "too_big", "размер раньше `is_executable`"
    enc = sd.sample("enc_zip_zipcrypto.zip")
    assert _reason("a.zip", enc, max_file=len(enc) - 1) == "too_big", "размер раньше `is_encrypted_archive`"
    assert _reason("a.txt", b"x" * (20 * MB + 1)) == "too_big", "предел статьи — 20 МБ, его передаёт вызывающий"


def test_reject_reason_file_exactly_at_limit_accepted():
    """FR-424: размер ровно `max_file` принимается (`""`), на байт больше — `"too_big"`."""
    assert _reason("справка.txt", b"x" * 10, max_file=10) == ""
    assert _reason("справка.txt", b"x" * 11, max_file=10) == "too_big"
    assert _reason("пустой.txt", b"", max_file=0) == "", "нулевой размер при нулевом пределе — ровно на пределе"
    assert _reason("ровно.txt", b"x", max_file=1, size=1) == ""
    assert _reason("ровно.dat", b"\0" * (20 * MB)) == "", "20 МБ ровно — принимается"


def test_reject_reason_executable_pe_elf_macho_shebang_msi_jar():
    """FR-424: исполняемый по содержимому (PE, ELF, Mach-O, `#!`, MSI, JAR) и по расширению — `"executable"`, `is_executable` согласен."""
    uploads = _uploads()
    for sample in EXECUTABLE_SAMPLES:
        data = sd.sample(sample)
        assert uploads.is_executable("данные.dat", data) is True, sample
        assert _reason("данные.dat", data) == "executable", sample
    for name in ("setup.exe", "RUN.BAT", "архив.tar.sh", "макрос.js", "прога.JAR"):
        assert uploads.is_executable(name, b"text") is True, name
        assert _reason(name, b"text") == "executable", name
    assert uploads.is_executable("exe.txt", b"text") is False, "расширение берётся последнее"
    assert uploads.is_executable("readme", b"text") is False
    for sample in ("not_exe_dos_mz.bin", "not_exe_mz_text.txt", "not_exe_java_class.bin", "not_exe_ole_doc.bin",
                   "not_exe_odf_manifest.zip"):
        assert uploads.is_executable("данные.dat", sd.sample(sample)) is False, sample
        assert _reason("данные.dat", sd.sample(sample)) == "", sample
    assert isinstance(uploads.EXECUTABLE_EXTENSIONS, (tuple, list, set, frozenset))
    assert {"exe", "msi", "jar", "sh"} <= set(uploads.EXECUTABLE_EXTENSIONS)


def test_reject_reason_executable_by_content_under_image_extension():
    """FR-424: PE, ELF и скрипт под именем `.png`/`.jpg` — `"executable"`; настоящая картинка с тем же именем — чисто."""
    for sample, name in (("exe_pe.bin", "логотип.png"), ("exe_elf.bin", "фото.JPG"), ("exe_script.bin", "схема.gif"),
                         ("exe_macho64_le.bin", "значок.webp")):
        assert _reason(name, sd.sample(sample)) == "executable", (sample, name)
    assert _reason("логотип.png", sd.sample("image.png")) == ""
    assert _reason("фото.jpg", sd.sample("image.jpg")) == ""


def test_reject_reason_encrypted_zip():
    """FR-424: ZIP с паролем (ZipCrypto, AES, пароль на втором элементе) — `"encrypted"`; ZIP без пароля — чисто."""
    uploads = _uploads()
    for sample in ENCRYPTED_ZIP_SAMPLES:
        data = sd.sample(sample)
        assert uploads.is_encrypted_archive(data) is True, sample
        assert _reason("архив.zip", data) == "encrypted", sample
    assert uploads.is_encrypted_archive(sd.sample("plain.zip")) is False
    assert _reason("архив.zip", sd.sample("plain.zip")) == ""


def test_reject_reason_encrypted_rar4_rar5_7z():
    """FR-424: RAR4, RAR5 и 7z с паролем — `"encrypted"`; такие же архивы без пароля — чисто."""
    uploads = _uploads()
    for sample in ENCRYPTED_OTHER_SAMPLES:
        data = sd.sample(sample)
        assert uploads.is_encrypted_archive(data) is True, sample
        assert _reason("архив.dat", data) == "encrypted", sample
    for sample in ("plain_rar4.rar", "plain_rar5.rar", "plain_7z_plain_header.7z", "plain_7z_compressed_header.7z"):
        assert uploads.is_encrypted_archive(sd.sample(sample)) is False, sample
        assert _reason("архив.dat", sd.sample(sample)) == "", sample


def test_reject_reason_clean_file_returns_empty():
    """FR-424: годные файлы (текст, картинки, архивы без пароля, документ Office) — пустая строка, не `None` и не `False`."""
    for sample in CLEAN_SAMPLES:
        result = _reason("файл.dat", sd.sample(sample))
        assert result == "" and isinstance(result, str), sample
    result = _reason("заметка.txt", "обычный текст".encode())
    assert result == "" and isinstance(result, str)
    assert _reason("пустой", b"") == ""


# --- detect_image -----------------------------------------------------------------------------------

def test_detect_image_png_jpeg_gif_webp_by_content():
    """FR-424: `detect_image` по содержимому даёт `png`, `jpeg`, `gif`, `webp` — ровно значения `ArticleFile.ImageFormat`."""
    uploads = _uploads()
    for fmt, expected in (("PNG", "png"), ("JPEG", "jpeg"), ("GIF", "gif"), ("WEBP", "webp")):
        assert uploads.detect_image(_image(fmt)) == expected, fmt
    assert uploads.detect_image(org.png_bytes()) == "png"
    assert uploads.detect_image(org.jpeg_bytes()) == "jpeg"
    values = [value for value, _ in model("knowledge.ArticleFile").ImageFormat.choices]
    assert values == ["png", "jpeg", "gif", "webp"]


def test_detect_image_foreign_extension_still_detected_by_content():
    """FR-424: имя и тип из браузера роли не играют — JPEG «под `.png`» остаётся `jpeg`, PNG «под `.txt`» остаётся `png` (`store` пишет тип по содержимому)."""
    uploads = _uploads()
    jpeg, png = _image("JPEG"), _image("PNG")
    assert uploads.detect_image(jpeg) == "jpeg"
    assert uploads.detect_image(png) == "png"
    assert uploads.detect_image(_image("GIF")) == "gif"
    stored = _store(jpeg, "будто-png.png")
    assert _fresh(stored).content_type == "image/jpeg", "тип по `detect_image`, а не по расширению"
    stored_png = _store(png, "заметка.txt")
    assert _fresh(stored_png).content_type == "image/png"


def test_detect_image_not_an_image_returns_empty():
    """FR-424: не картинка — пустая строка и без исключения: текст, пустые данные, повреждённый и обрезанный PNG, SVG, PDF, BMP/TIFF."""
    uploads = _uploads()
    from PIL import Image

    other = io.BytesIO()
    Image.new("RGB", (8, 8)).save(other, "BMP")
    tiff = io.BytesIO()
    Image.new("RGB", (8, 8)).save(tiff, "TIFF")
    samples = {
        "текст": "это не картинка".encode(), "пусто": b"", "подпись PNG без картинки": org.fake_png(),
        "обрезанный PNG": org.png_bytes()[:40], "SVG": b"<svg xmlns='http://www.w3.org/2000/svg'><rect/></svg>",
        "PDF": b"%PDF-1.4\n1 0 obj<<>>endobj\n", "BMP (формат не из списка)": other.getvalue(),
        "TIFF (формат не из списка)": tiff.getvalue(), "исполняемый": sd.sample("exe_pe.bin"),
    }
    for label, data in samples.items():
        result = uploads.detect_image(data)
        assert result == "" and isinstance(result, str), label


def test_detect_image_pixel_bomb_raises_image_too_large_without_server_error():
    """FR-424, NFR-411: больше 40 млн точек (и бомба Pillow) — `uploads.ImageTooLarge`; это не `OSError`/`ValueError`, не-картинка исключения не даёт."""
    uploads = _uploads()
    assert issubclass(uploads.ImageTooLarge, Exception)
    assert not issubclass(uploads.ImageTooLarge, (OSError, ValueError))
    with pytest.raises(uploads.ImageTooLarge):
        uploads.detect_image(org.huge_pixels_png())
    from PIL import Image

    bomb = io.BytesIO()
    Image.new("1", (14000, 14000), 0).save(bomb, "PNG", optimize=True)  # 196 млн точек: Pillow сам считает бомбой
    assert len(bomb.getvalue()) < 5 * MB
    with pytest.raises(uploads.ImageTooLarge):
        uploads.detect_image(bomb.getvalue())
    assert uploads.detect_image("не картинка".encode()) == "", "для не-картинки исключения нет"
    assert uploads.detect_image(org.png_bytes(200, 100)) == "png", "обычный размер проходит"


# --- store ------------------------------------------------------------------------------------------

def test_store_creates_stored_file_with_empty_owner_in_incoming(protected_root):
    """FR-424: `store` — строка `StoredFile` (`owner=None`, `purpose` как передан, `pending`, размер, sha256, тип) и файл в `incoming/<id>`."""
    from apps.core.services import files

    data = "содержимое файла".encode()
    stored = _store(data, "справка.txt", "knowledge")
    assert type(stored) is model("core.StoredFile")
    row = _fresh(model("core.StoredFile").objects.get(pk=stored.pk))
    assert (row.purpose, row.owner_id, row.status) == ("knowledge", None, "pending")
    assert row.size == len(data) and row.sha256 == hashlib.sha256(data).hexdigest()
    assert row.content_type == "application/octet-stream"
    path = protected_root / "incoming" / str(row.pk)
    assert files.attachment_path(row) == path and path.read_bytes() == data
    assert not (protected_root / "attachments" / str(row.pk)).exists()
    picture = _image("PNG")
    stored_png = _store(picture, "схема.png", "knowledge")
    assert _fresh(stored_png).content_type == "image/png"
    assert (protected_root / "incoming" / str(stored_png.pk)).read_bytes() == picture
    other = _store(b"1", "вложение.txt", "attachment")
    assert _fresh(other).purpose == "attachment", "назначение — переданное значение"


def test_store_enqueues_scan_only_after_commit(django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-424, NFR-411: до фиксации в очереди `files` ничего нет, после — одно задание `scan_file` с номером файла; сам `store` ClamAV не зовёт."""
    calls = org.scan_clean(monkeypatch)
    assert org.files_jobs() == []
    with django_capture_on_commit_callbacks(execute=True):
        stored = _store(b"to be checked", "файл.txt")
        assert org.files_jobs() == [], "проверка ставится только после фиксации"
        assert _jobs_of(stored) == []
    assert len(_jobs_of(stored)) == 1, "после фиксации — одно задание `scan_file` с номером файла"
    assert calls == [], "`store` только ставит проверку: `scan` не вызывается"
    with django_capture_on_commit_callbacks(execute=True):
        second = _store(b"second", "второй.txt")
        assert _jobs_of(second) == []
    assert len(_jobs_of(second)) == 1


# --- move -------------------------------------------------------------------------------------------

def test_move_clean_to_attachments_returns_old_path_for_erasure(protected_root):
    """FR-424: `move(clean)` — копия в `attachments/<id>`, статус и `scanned_at` в базе, возвращает `[incoming/<id>]` и сам не стирает."""
    from apps.core.services import files

    data = b"clean content"
    stored = _store(data)
    paths = _paths(protected_root, stored)
    leftovers = _uploads().move(stored, "clean")
    assert isinstance(leftovers, list) and [str(p) for p in leftovers] == [str(paths["incoming"])]
    assert paths["incoming"].read_bytes() == data, "`move` сам ничего не стирает"
    assert paths["attachments"].read_bytes() == data
    row = _fresh(model("core.StoredFile").objects.get(pk=stored.pk))
    assert row.status == "clean" and row.scanned_at is not None and row.signature == ""
    assert files.attachment_path(row) == paths["attachments"]
    assert not list((protected_root / "attachments").glob("*.tmp")), "временного файла не остаётся"
    files.remove_paths(leftovers)
    assert not paths["incoming"].exists() and paths["attachments"].exists()


def test_move_found_to_quarantine_returns_old_path(protected_root):
    """FR-424: `move(quarantine, сигнатура)` — файл в `quarantine/<id>`, сигнатура и время в базе, возвращает `[incoming/<id>]`."""
    data = b"suspicious bytes"
    stored = _store(data)
    paths = _paths(protected_root, stored)
    leftovers = _uploads().move(stored, "quarantine", "Eicar-Signature")
    assert [str(p) for p in leftovers] == [str(paths["incoming"])]
    assert paths["incoming"].exists(), "стирание — дело вызывающего, после фиксации"
    assert paths["quarantine"].read_bytes() == data and not paths["attachments"].exists()
    row = _fresh(model("core.StoredFile").objects.get(pk=stored.pk))
    assert row.status == "quarantine" and row.signature == "Eicar-Signature" and row.scanned_at is not None


# --- итог проверки через задание ядра ---------------------------------------------------------------

def test_scan_task_erases_old_path_returned_by_move_only_after_commit(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-424, NFR-411: файл статьи — задание `scan_file` переносит его через `uploads.move`, прежний путь стирается только после этого; при «найдено» файл в карантине."""
    article = kb.make_published()
    clean_row = kb.attach_file(article, "чистый.txt", b"clean body", status="pending", write=True)
    found_row = kb.attach_file(article, "плохой.txt", b"bad body", status="pending", write=True)
    clean_paths, found_paths = _paths(protected_root, clean_row.file), _paths(protected_root, found_row.file)
    assert clean_paths["incoming"].exists() and found_paths["incoming"].exists()
    from apps.core import tasks

    sd.scan_clean(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        tasks.scan_file(str(clean_row.file.pk))
    assert _fresh(clean_row.file).status == "clean"
    assert clean_paths["attachments"].read_bytes() == b"clean body"
    assert not clean_paths["incoming"].exists(), "прежний путь стёрт после переноса"
    sd.scan_found(monkeypatch, "Eicar-Signature")
    with django_capture_on_commit_callbacks(execute=True):
        tasks.scan_file(str(found_row.file.pk))
    found = _fresh(found_row.file)
    assert found.status == "quarantine" and found.signature == "Eicar-Signature"
    assert found_paths["quarantine"].read_bytes() == b"bad body" and not found_paths["incoming"].exists()


# --- servicedesk: прежние имена и пределы -----------------------------------------------------------

def test_servicedesk_attachments_old_names_still_exported():
    """FR-424: `servicedesk.attachments` по-прежнему отдаёт прежние имена; `EXECUTABLE_EXTENSIONS` определён в `uploads` и тот же объект."""
    att, uploads = _att(), _uploads()
    for name in ("is_executable", "is_encrypted_archive", "reason_of", "still_waiting", "on_clean", "on_found"):
        assert callable(getattr(att, name)), name
    for name in ("EXECUTABLE_EXTENSIONS", "MAX_FILE", "MAX_MAIL", "MAX_FILES", "MAX_TOTAL"):
        assert hasattr(att, name), name
    assert att.EXECUTABLE_EXTENSIONS is uploads.EXECUTABLE_EXTENSIONS or (
        tuple(att.EXECUTABLE_EXTENSIONS) == tuple(uploads.EXECUTABLE_EXTENSIONS))
    assert att.MAX_FILE == 20 * MB and att.MAX_MAIL == 50 * MB
    assert att.is_executable("a.exe", b"") is True and att.is_executable("a.txt", sd.sample("exe_pe.bin")) is True
    assert att.is_executable("a.txt", b"text") is False
    assert att.is_encrypted_archive(sd.sample("enc_zip_zipcrypto.zip")) is True
    assert att.is_encrypted_archive(sd.sample("plain.zip")) is False


def test_servicedesk_rejected_codes_translated_from_core_reasons(django_capture_on_commit_callbacks, protected_root):
    """FR-424: коды ядра `executable`/`encrypted` у вложений заявок остаются значениями `Attachment.Rejected`; «слишком большой» — прежний `too_big`."""
    att, uploads = _att(), _uploads()
    Rejected = model("servicedesk.Attachment").Rejected
    pe, enc, clean = sd.sample("exe_pe.bin"), sd.sample("enc_zip_zipcrypto.zip"), b"clean data"
    assert uploads.reject_reason("a.dat", pe, len(pe), att.MAX_FILE) == "executable"
    assert uploads.reject_reason("a.dat", enc, len(enc), att.MAX_FILE) == "encrypted"
    assert att.reason_of("a.dat", pe) == Rejected.EXECUTABLE.value == "executable"
    assert att.reason_of("a.dat", enc) == Rejected.ENCRYPTED.value == "encrypted"
    assert att.reason_of("a.dat", clean) == ""
    assert att.reason_of("setup.exe", clean) == "executable", "по расширению тоже"
    ticket = sd.make_ticket(queue=sd.make_queue())
    entry = sd.make_entry(ticket, "incoming")
    parts = [att.Part(name=name, data=data, content_type="application/octet-stream", inline=False)
             for name, data in (("прога.dat", pe), ("архив.zip", enc), ("справка.txt", clean))]
    with django_capture_on_commit_callbacks(execute=True):
        accepted = att.accept(entry, parts, strict=False)
    assert [item.rejected for item in accepted] == ["executable", "encrypted", ""]
    assert [item.file is None for item in accepted] == [True, True, False]
    errors = importlib.import_module("apps.servicedesk.services.errors")
    with pytest.raises(errors.ServiceDeskError) as caught:
        att.precheck(parts[:1])
    assert caught.value.code == "file_rejected" and Rejected.EXECUTABLE.label in str(caught.value)
    big = [att.Part(name="огромный.dat", data=b"\0" * (att.MAX_FILE + 1), content_type="x/y", inline=False)]
    with pytest.raises(errors.ServiceDeskError) as caught:
        att.precheck(big)
    assert caught.value.code == "file_rejected" and Rejected.TOO_BIG.label in str(caught.value)


def test_servicedesk_limits_10_files_and_50_mb_unchanged():
    """FR-424: пределы сервис-деска свои и прежние — 10 файлов и 50 МБ на письмо; число проверяется раньше суммы."""
    att = _att()
    errors = importlib.import_module("apps.servicedesk.services.errors")

    def part(name: str, data: bytes):
        return att.Part(name=name, data=data, content_type="application/octet-stream", inline=False)

    assert att.MAX_FILES == 10 and att.MAX_TOTAL == 50 * MB and att.MAX_MAIL == 50 * MB
    ten = [part(f"f{i}.txt", b"x") for i in range(10)]
    assert att.precheck(ten) is None
    with pytest.raises(errors.ServiceDeskError) as caught:
        att.precheck(ten + [part("f10.txt", b"x")])
    assert caught.value.code == "too_many_files"
    five = [part(f"p{i}.dat", b"\0" * (10 * MB)) for i in range(5)]
    assert att.precheck(five) is None, "ровно 50 МБ допустимо"
    with pytest.raises(errors.ServiceDeskError) as caught:
        att.precheck(five + [part("лишний.dat", b"\0")])
    assert caught.value.code == "total_too_big"
    assert att.MAX_FILE == 20 * MB, "предел файла заявки — прежние 20 МБ"


# --- ClamAV: подмена строкой ------------------------------------------------------------------------

def test_scan_task_calls_clamav_through_module_attribute_so_scan_patch_applies(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-424: подмена `apps.integrations.clamav.services.scan` действует и для вложения заявки, и для файла статьи; `scan` получает путь `incoming/<id>`."""
    from apps.core import tasks

    calls = sd.scan_clean(monkeypatch)
    ticket = sd.make_ticket(queue=sd.make_queue())
    entry = sd.make_entry(ticket, "incoming")
    att = _att()
    with django_capture_on_commit_callbacks(execute=True):
        (accepted,) = att.accept(entry, [att.Part(name="a.txt", data=b"ticket file", content_type="text/plain",
                                                  inline=False)])
    assert calls == [], "приём файла проверку не вызывает, только ставит"
    ticket_incoming = protected_root / "incoming" / str(accepted.file.pk)
    with django_capture_on_commit_callbacks(execute=True):
        tasks.scan_file(str(accepted.file.pk))
    assert calls == [str(ticket_incoming)]
    assert _fresh(accepted.file).status == "clean"
    article = kb.make_published()
    row = kb.attach_file(article, "из-статьи.txt", b"article file", status="pending", write=True)
    article_incoming = protected_root / "incoming" / str(row.file.pk)
    with django_capture_on_commit_callbacks(execute=True):
        tasks.scan_file(str(row.file.pk))
    assert calls == [str(ticket_incoming), str(article_incoming)], "тот же атрибут модуля обслуживает и файлы статей"
    assert _fresh(row.file).status == "clean"
    unavailable = kb.attach_file(article, "ждёт.txt", b"waits", status="pending", write=True)
    sd.scan_unavailable(monkeypatch)
    with pytest.raises(Exception) as caught:
        with django_capture_on_commit_callbacks(execute=True):
            tasks.scan_file(str(unavailable.file.pk))
    assert type(caught.value).__name__ == "ScanUnavailable"
    waiting = _fresh(unavailable.file)
    assert waiting.status == "pending" and (protected_root / "incoming" / str(waiting.pk)).exists()


# --- значение назначения ----------------------------------------------------------------------------

def test_stored_file_purpose_knowledge_value_exists():
    """FR-424: `StoredFile.Purpose.KNOWLEDGE == "knowledge"`, подпись «файл статьи», влезает в `max_length` поля; прежние назначения на месте."""
    StoredFile = model("core.StoredFile")
    purpose = StoredFile.Purpose.KNOWLEDGE
    assert purpose.value == "knowledge" and purpose.label == "файл статьи"
    values = [value for value, _ in StoredFile.Purpose.choices]
    assert values[:2] == ["photo", "attachment"] and "knowledge" in values
    field = StoredFile._meta.get_field("purpose")
    assert field.max_length >= len("knowledge") and field.max_length == 16
    assert "knowledge" in [value for value, _ in field.choices]
    row = StoredFile.objects.create(purpose=purpose, owner=None, size=1, sha256="0" * 64,
                                    content_type="application/octet-stream")
    assert _fresh(row).purpose == "knowledge" and row.get_purpose_display() == "файл статьи"
