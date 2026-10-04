"""T-2108: путь фото (FR-132, FR-150, FR-151, NFR-105, NFR-108). Сценарий 10 спеки.

Загрузка, проверка форматом и антивирусом, перекодирование, карантин, повторы при недоступном clamd,
часовая постановка и ночная очистка, выдача через `X-Accel-Redirect`, удаление, заглушка с инициалами,
события журнала. Антивирус подменяется только `support_org.scan_clean/scan_found/scan_unavailable`;
каталог тома — фикстура `protected_root`; задание — `support_org.run_files_worker()`.
Состояние «уже есть чистое фото» и т. п. строится через ORM внутри файла (тесты выдачи и страниц не
зависят от пути проверки).
"""
import hashlib
import io
import json
import re
import struct
import zlib
from datetime import timedelta

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from tests import support, support_org
from tests.support import HX, model

pytestmark = pytest.mark.django_db

MAX_PHOTO = 5 * 1024 * 1024
RETRY_INTERVALS = [60, 300, 900] + [3600] * 21
SCAN = "apps.core.tasks.scan_file"


# --- помощники файла --------------------------------------------------------------------------

def stored_model():
    return model("core.StoredFile")


def fresh(user):
    return model("core.User").objects.get(pk=user.pk)


def stored_files(user):
    return list(stored_model().objects.filter(owner=user).order_by("created_at", "id"))


def pending_of(user):
    """`StoredFile`, на который указывает `photo_pending` (после обновления из базы)."""
    return stored_model().objects.get(pk=fresh(user).photo_pending_id)


def paths(root, stored):
    return {"incoming": root / "incoming" / str(stored.id), "quarantine": root / "quarantine" / str(stored.id),
            "512": root / "photos" / f"{stored.id}-512.jpg", "96": root / "photos" / f"{stored.id}-96.jpg"}


def put(path, data: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def make_clean_photo(user, root, *, set_photo=True):
    """Чистое фото через ORM: строка `clean` и настоящие JPEG двух размеров на диске."""
    stored = stored_model().objects.create(
        owner=user, purpose="photo", status="clean", content_type="image/jpeg", size=100, sha256="0" * 64,
        scanned_at=timezone.now())
    p = paths(root, stored)
    put(p["512"], support_org.jpeg_bytes(512, 512))
    put(p["96"], support_org.jpeg_bytes(96, 96))
    if set_photo:
        model("core.User").objects.filter(pk=user.pk).update(photo=stored)
    return stored


def make_waiting(user, root, status="pending", *, set_pending=True, content=None):
    """Файл на проверке (`incoming/<id>`) или в карантине (`quarantine/<id>`), `photo_pending` на него."""
    content = content or support_org.png_bytes()
    stored = stored_model().objects.create(
        owner=user, purpose="photo", status=status, content_type="image/png", size=len(content),
        sha256=hashlib.sha256(content).hexdigest(), signature="Eicar-Signature" if status == "quarantine" else "",
        scanned_at=timezone.now() if status == "quarantine" else None)
    put(paths(root, stored)["incoming" if status == "pending" else "quarantine"], content)
    if set_pending:
        model("core.User").objects.filter(pk=user.pk).update(photo_pending=stored)
    return stored


def post_photo(client, content, name="me.png", ctype="image/png"):
    return client.post("/me/photo/", {"photo": SimpleUploadedFile(name, content, content_type=ctype)})


def upload_queued(client, cb, content, name="me.png", ctype="image/png"):
    """Загрузка с исполнением обратных вызовов фиксации (задание проверки встаёт в очередь)."""
    with cb(execute=True):
        response = post_photo(client, content, name, ctype)
    assert response.status_code == 302, response.content[:300]
    return response


def scan_jobs(stored):
    return [j for j in support_org.files_jobs() if j.func_name == SCAN and j.args == (str(stored.id),)]


def events(action, user=None):
    qs = model("core.AuditEvent").objects.filter(action=action)
    if user is not None:
        qs = qs.filter(object_type="user", object_id=str(user.pk))
    return list(qs.order_by("id"))


def has_alert(response) -> bool:
    return 'role="alert"' in response.content.decode()


def padded_png(total: int) -> bytes:
    """Настоящий PNG ровно в `total` байт: между данными и IEND вставлен неизвестный вспомогательный блок."""
    base = support_org.png_bytes(32, 32)
    body, iend = base[:-12], base[-12:]
    assert iend[4:8] == b"IEND"
    size = total - len(base) - 12
    assert size >= 0
    data = b"\0" * size
    chunk = struct.pack(">I", size) + b"prVt" + data + struct.pack(">I", zlib.crc32(b"prVt" + data) & 0xFFFFFFFF)
    result = body + chunk + iend
    assert len(result) == total
    return result


def photo_markup(segment: str):
    """(src картинки или None, инициалы заглушки или None) из куска разметки одного человека."""
    img = re.search(r"<img[^>]*data-photo-img[^>]*>", segment)
    src = re.search(r'src="([^"]+)"', img.group(0)).group(1) if img else None
    span = re.search(r"<[^>]*data-photo-placeholder[^>]*>", segment)
    initials = re.search(r'data-initials="([^"]*)"', span.group(0)).group(1) if span else None
    return src, initials


def tag_start(html: str, *needles: str, bare: str | None = None):
    """Позиция первого тега, содержащего все атрибуты-подстроки `needles` (и слово `bare` как отдельный атрибут)."""
    for m in re.finditer(r"<[a-zA-Z][^>]*>", html):
        tag = m.group(0)
        if all(n in tag for n in needles) and (bare is None or re.search(rf"\b{bare}(?![-\w])", tag)):
            return m.start()
    return None


def row_segment(html: str, user) -> str:
    """Строка списка `/staff/` данного человека."""
    start = tag_start(html, f'data-user-id="{user.pk}"', bare="data-user-id")
    assert start is not None, "в списке нет строки сотрудника"
    end = html.find("</tr>", start)
    return html[start:end]


def member_segment(html: str, user) -> str:
    """Строка участника `[data-member]` в карточке узла."""
    start = tag_start(html, f'data-user-id="{user.pk}"', bare="data-member")
    assert start is not None, "в карточке узла нет строки участника"
    nxt = re.search(r"<[a-zA-Z][^>]*\bdata-member(?![-\w])[^>]*>", html[start + 1:])
    return html[start:(start + 1 + nxt.start()) if nxt else len(html)]


def card_segment(html: str, user) -> str:
    start = tag_start(html, f'data-user-id="{user.pk}"', bare="data-card")
    assert start is not None, "в ответе нет карточки сотрудника"
    return html[start:]


# --- 1. формат ---------------------------------------------------------------------------------

def test_photo_format_by_content_png_jpeg_only(protected_root, django_capture_on_commit_callbacks):
    """FR-132, NFR-108: формат — по содержимому: PNG и JPEG принимаются при любом имени, остальное — отказ."""
    from PIL import Image

    from apps.core.services import files

    user = support.make_employee()
    gif, bmp = io.BytesIO(), io.BytesIO()
    Image.new("P", (16, 16)).save(gif, "GIF")
    Image.new("RGB", (16, 16)).save(bmp, "BMP")
    for content in (support_org.fake_png(), gif.getvalue(), bmp.getvalue(), b"GIF89a-not-image"):
        with pytest.raises(files.PhotoError) as caught:
            files.upload_photo(user, SimpleUploadedFile("face.png", content, content_type="image/png"),
                               actor=user)
        assert caught.value.code == "bad_format"
    assert stored_files(user) == [] and fresh(user).photo_pending_id is None
    assert not (protected_root / "incoming").exists() or not list((protected_root / "incoming").iterdir())

    client = support.logged_in(user)
    response = post_photo(client, support_org.fake_png(), "face.png")
    assert response.status_code == 200 and has_alert(response)
    assert stored_files(user) == [] and support_org.files_jobs() == []

    for content, name, ctype in ((support_org.png_bytes(), "a.txt", "text/plain"),
                                 (support_org.jpeg_bytes(), "b.png", "image/png")):
        owner = support.make_employee()
        with django_capture_on_commit_callbacks(execute=True):
            ok = post_photo(support.logged_in(owner), content, name, ctype)
        assert ok.status_code == 302 and ok["Location"] == "/me/"
        stored = pending_of(owner)
        assert stored.status == "pending" and stored.owner_id == owner.pk
        assert stored.content_type == ("image/png" if content.startswith(b"\x89PNG") else "image/jpeg")
        assert (protected_root / "incoming" / str(stored.id)).read_bytes() == content


# --- 2. размер и точки -------------------------------------------------------------------------

def test_photo_over_5mb_or_40_megapixels_refused(protected_root):
    """FR-132, NFR-108: до 5 МБ (5 242 880 байт) и 40 млн точек принимается, больше — отказ с кодом."""
    from PIL import Image

    from apps.core.services import files

    user = support.make_employee()

    def upload(content):
        return files.upload_photo(user, SimpleUploadedFile("p.png", content, content_type="image/png"), actor=user)

    exact = upload(padded_png(MAX_PHOTO))
    assert exact.status == "pending" and exact.size == MAX_PHOTO

    over = io.BytesIO()
    Image.new("1", (8001, 5000), 0).save(over, "PNG", optimize=True)    # 40 005 000 точек: сразу за границей
    for content, code in ((padded_png(MAX_PHOTO + 1), "too_big"), (support_org.huge_pixels_png(), "too_many_pixels"),
                          (over.getvalue(), "too_many_pixels")):
        before = stored_model().objects.count()
        with pytest.raises(files.PhotoError) as caught:
            upload(content)
        assert caught.value.code == code
        assert stored_model().objects.count() == before
        assert fresh(user).photo_pending_id == exact.id

    edge = io.BytesIO()
    Image.new("1", (8000, 5000), 0).save(edge, "PNG", optimize=True)    # ровно 40 000 000 точек
    assert upload(edge.getvalue()).status == "pending"

    # маршрут `/me/photo/`: отказ — 200 с alert, прежнее чистое фото остаётся, строка не создаётся, очередь пуста
    holder = support.make_employee()
    old = make_clean_photo(holder, protected_root)
    client = support.logged_in(holder)
    for content in (padded_png(MAX_PHOTO + 1), over.getvalue()):
        response = post_photo(client, content)
        assert response.status_code == 200 and has_alert(response)
        assert fresh(holder).photo_id == old.id and fresh(holder).photo_pending_id is None
        assert [s.id for s in stored_files(holder)] == [old.id]
        assert support_org.files_jobs() == []
        assert paths(protected_root, old)["512"].exists()


# --- 3. загрузка -------------------------------------------------------------------------------

def test_upload_creates_pending_file_enqueues_scan_after_commit_previous_clean_photo_still_shown(
        protected_root, django_capture_on_commit_callbacks):
    """FR-132, NFR-105: загрузка — `StoredFile(pending)`, задание после фиксации с повторами; прежнее фото на месте."""
    user = support.make_employee()
    old = make_clean_photo(user, protected_root)
    client = support.logged_in(user)
    content = support_org.png_bytes(80, 60)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        response = post_photo(client, content)
    assert response.status_code == 302 and response["Location"] == "/me/"
    assert support_org.files_jobs() == [], "задание не должно уходить в очередь до фиксации транзакции"
    assert callbacks, "постановка задания должна быть отложена на фиксацию"
    for callback in callbacks:
        callback()

    stored = pending_of(user)
    assert stored.status == "pending" and stored.purpose == "photo" and stored.owner_id == user.pk
    assert stored.content_type == "image/png" and stored.size == len(content)
    assert (protected_root / "incoming" / str(stored.id)).read_bytes() == content

    jobs = scan_jobs(stored)
    assert len(jobs) == 1 and len(support_org.files_jobs()) == 1
    job = jobs[0]
    assert job.kwargs == {} and job.retries_left == 24
    assert list(job.retry_intervals) == RETRY_INTERVALS

    user = fresh(user)
    assert user.photo_id == old.id and user.photo_pending_id == stored.id
    assert paths(protected_root, old)["512"].exists() and stored_model().objects.filter(pk=old.pk).exists()
    page = client.get("/me/").content.decode()
    src, initials = photo_markup(card_segment(page, user))
    assert src == f"/staff/{user.pk}/photo/{old.id}/96/" and initials is None
    assert 'data-photo-status="pending"' in page and "Фото проверяется" in page


# --- 4. чисто ----------------------------------------------------------------------------------

def test_clean_scan_reencodes_512_and_96_without_exif_and_switches_photo(
        protected_root, monkeypatch, django_capture_on_commit_callbacks):
    """FR-132: «чисто» — JPEG 512 и 96 с поворотом, без EXIF, белый фон; исходник и прежнее фото удалены."""
    from PIL import Image

    user = support.make_employee()
    old = make_clean_photo(user, protected_root)
    client = support.logged_in(user)
    source = support_org.jpeg_bytes(1024, 512, exif_gps=True, orientation=6)
    assert b"Exif" in source
    calls = support_org.scan_clean(monkeypatch)

    upload_queued(client, django_capture_on_commit_callbacks, source, "me.jpg", "image/jpeg")
    stored = pending_of(user)
    incoming = paths(protected_root, stored)["incoming"]
    support_org.run_files_worker()

    assert calls == [str(incoming)]
    stored.refresh_from_db()
    user = fresh(user)
    p = paths(protected_root, stored)
    assert stored.status == "clean" and stored.scanned_at is not None
    assert user.photo_id == stored.id and user.photo_pending_id is None
    assert not incoming.exists()
    for key, size in (("512", (256, 512)), ("96", (48, 96))):
        raw = p[key].read_bytes()
        image = Image.open(io.BytesIO(raw))
        assert image.format == "JPEG" and image.size == size, "поворот учтён, пропорции сохранены, длинная сторона по размеру"
        assert len(image.getexif()) == 0 and b"Exif" not in raw
    assert not stored_model().objects.filter(pk=old.pk).exists()
    assert not paths(protected_root, old)["512"].exists() and not paths(protected_root, old)["96"].exists()
    [event] = events("photo.checked", user)
    assert event.actor_id is None and event.after["result"] == "clean" and event.after["file_id"] == str(stored.id)

    # прозрачный фон PNG заливается белым, широкий снимок вписывается по ширине
    other = support.make_employee()
    transparent = io.BytesIO()
    Image.new("RGBA", (1024, 512), (0, 0, 0, 0)).save(transparent, "PNG")
    upload_queued(support.logged_in(other), django_capture_on_commit_callbacks, transparent.getvalue())
    support_org.run_files_worker()
    wide = stored_model().objects.get(pk=fresh(other).photo_id)
    assert fresh(other).photo_id == wide.id
    for key, size in (("512", (512, 256)), ("96", (96, 48))):
        image = Image.open(paths(protected_root, wide)[key]).convert("RGB")
        assert image.size == size
        assert all(channel >= 235 for channel in image.getpixel((5, 5))), "прозрачное должно стать белым"


# --- 5. найдено --------------------------------------------------------------------------------

def test_found_scan_quarantines_keeps_previous_photo_user_sees_failed(
        protected_root, monkeypatch, django_capture_on_commit_callbacks):
    """FR-132: «найдено» — карантин, сигнатура, прежнее фото на месте; сотрудник видит, что фото не прошло проверку."""
    user = support.make_employee()
    old = make_clean_photo(user, protected_root)
    client = support.logged_in(user)
    support_org.scan_found(monkeypatch, "Eicar-Signature")

    upload_queued(client, django_capture_on_commit_callbacks, support_org.png_bytes())
    stored = pending_of(user)
    support_org.run_files_worker()

    stored.refresh_from_db()
    user = fresh(user)
    p = paths(protected_root, stored)
    assert stored.status == "quarantine" and stored.signature == "Eicar-Signature" and stored.scanned_at is not None
    assert p["quarantine"].exists() and not p["incoming"].exists()
    assert not p["512"].exists() and not p["96"].exists()
    assert user.photo_id == old.id and user.photo_pending_id == stored.id
    assert paths(protected_root, old)["512"].exists()
    [event] = events("photo.checked", user)
    assert event.actor_id is None and event.after["result"] == "quarantine"
    assert event.after["signature"] == "Eicar-Signature"

    page = client.get("/me/").content.decode()
    assert 'data-photo-status="failed"' in page and "Фото не прошло проверку" in page
    assert 'data-photo-status="pending"' not in page
    src, _ = photo_markup(card_segment(page, user))
    assert src == f"/staff/{user.pk}/photo/{old.id}/96/"
    assert client.get(f"/staff/{user.pk}/photo/{stored.id}/96/").status_code == 404


# --- 6. clamd недоступен -----------------------------------------------------------------------

def test_unavailable_clamd_retries_24_times_with_plan_intervals_portal_keeps_working(
        protected_root, monkeypatch, django_capture_on_commit_callbacks):
    """NFR-105: при `ScanUnavailable` попытка записана, задание уходит на повтор по плану, портал работает."""
    from rq.job import Job

    from apps.core import tasks

    user = support.make_employee()
    client = support.logged_in(user)
    calls = support_org.scan_unavailable(monkeypatch)

    upload_queued(client, django_capture_on_commit_callbacks, support_org.png_bytes())
    stored = pending_of(user)
    support_org.run_files_worker()

    assert calls, "антивирус должен быть вызван"
    stored.refresh_from_db()
    assert stored.status == "pending" and stored.attempts == 1
    assert stored.last_error and str(protected_root) not in stored.last_error
    queue = support_org.files_queue()
    ids = queue.scheduled_job_registry.get_job_ids()
    assert len(ids) == 1, "повтор ждёт в реестре отложенных заданий"
    job = Job.fetch(ids[0], connection=queue.connection)
    assert job.func_name == SCAN and job.args == (str(stored.id),)
    assert list(job.retry_intervals) == RETRY_INTERVALS and len(job.retry_intervals) == 24
    user = fresh(user)
    assert user.photo_id is None and user.photo_pending_id == stored.id
    assert events("photo.checked", user) == []
    assert client.get("/me/").status_code == 200
    page = client.get("/me/").content.decode()
    assert 'data-photo-status="pending"' in page and photo_markup(card_segment(page, user))[1] is not None

    for expected in (2, 3):     # прямые вызовы: число попыток растёт и фиксируется, исключение идёт дальше
        with pytest.raises(support_org.ScanUnavailable):
            tasks.scan_file(str(stored.id))
        stored.refresh_from_db()
        assert stored.attempts == expected and stored.status == "pending"

    support_org.scan_clean(monkeypatch)     # позже проверка проходит
    tasks.scan_file(str(stored.id))
    stored.refresh_from_db()
    assert stored.status == "clean" and fresh(user).photo_id == stored.id


# --- 7. часовое задание ------------------------------------------------------------------------

def test_hourly_job_requeues_pending_scans_without_job(protected_root, django_capture_on_commit_callbacks):
    """NFR-105: раз в час ставятся проверки ожидающих дольше часа файлов, у которых нет задания."""
    from apps.core import tasks

    queue = support_org.files_queue()
    old_ago = timezone.now() - timedelta(hours=2)

    def waiting(created):
        stored = make_waiting(support.make_employee(), protected_root)
        stored_model().objects.filter(pk=stored.pk).update(created_at=created)
        return stored

    lost = waiting(old_ago)
    queued = waiting(old_ago)
    scheduled = waiting(old_ago)
    young = waiting(timezone.now() - timedelta(minutes=10))
    done = make_clean_photo(support.make_employee(), protected_root)
    stored_model().objects.filter(pk=done.pk).update(created_at=old_ago)
    queue.enqueue(SCAN, str(queued.id))
    queue.enqueue_in(timedelta(hours=1), SCAN, str(scheduled.id))
    assert len(support_org.files_jobs()) == 1

    with django_capture_on_commit_callbacks(execute=True):
        assert tasks.requeue_pending_scans() == 1
    assert len(scan_jobs(lost)) == 1 and scan_jobs(lost)[0].kwargs == {}
    assert scan_jobs(lost)[0].retries_left == 24 and list(scan_jobs(lost)[0].retry_intervals) == RETRY_INTERVALS
    assert len(scan_jobs(queued)) == 1, "задание в очереди не дублируется"
    assert scan_jobs(scheduled) == [] and len(queue.scheduled_job_registry.get_job_ids()) == 1
    assert scan_jobs(young) == [] and scan_jobs(done) == []
    with django_capture_on_commit_callbacks(execute=True):
        assert tasks.requeue_pending_scans() == 0, "повторный запуск ничего не добавляет"
    assert len(scan_jobs(lost)) == 1


# --- 8. замена загрузки ------------------------------------------------------------------------

def test_new_upload_replaces_pending_quarantine_kept(protected_root, monkeypatch):
    """FR-132: новая загрузка заменяет `photo_pending`: ожидающий файл удаляется, файл в карантине остаётся."""
    from apps.core import tasks
    from apps.core.services import files

    user = support.make_employee()

    def upload(content):
        return files.upload_photo(user, SimpleUploadedFile("p.png", content, content_type="image/png"), actor=user)

    first = upload(support_org.png_bytes(40, 40))
    second = upload(support_org.png_bytes(50, 50))
    assert not stored_model().objects.filter(pk=first.pk).exists()
    assert not paths(protected_root, first)["incoming"].exists()
    assert paths(protected_root, second)["incoming"].exists()
    assert fresh(user).photo_pending_id == second.id

    support_org.scan_found(monkeypatch)
    tasks.scan_file(str(second.id))
    second.refresh_from_db()
    assert second.status == "quarantine" and paths(protected_root, second)["quarantine"].exists()

    third = upload(support_org.png_bytes(60, 60))
    assert fresh(user).photo_pending_id == third.id and third.status == "pending"
    second.refresh_from_db()
    assert second.status == "quarantine" and paths(protected_root, second)["quarantine"].exists()
    assert paths(protected_root, third)["incoming"].exists()
    assert {s.id for s in stored_files(user)} == {second.id, third.id}


# --- 9. устаревший результат -------------------------------------------------------------------

def test_scan_result_ignored_when_file_no_longer_pending(protected_root, monkeypatch):
    """FR-132: задание не меняет ничего и не пишет событий, если файл уже не `pending` или не `photo_pending` владельца."""
    from apps.core import tasks
    from apps.core.services import files

    calls = support_org.scan_clean(monkeypatch)
    user = support.make_employee()
    stored = files.upload_photo(user, SimpleUploadedFile("p.png", support_org.png_bytes(), content_type="image/png"),
                                actor=user)
    tasks.scan_file(str(stored.id))
    assert fresh(user).photo_id == stored.id and len(events("photo.checked", user)) == 1
    scans = len(calls)
    tasks.scan_file(str(stored.id))                      # повторная доставка задания
    assert len(calls) == scans and len(events("photo.checked", user)) == 1
    assert fresh(user).photo_id == stored.id and fresh(user).photo_pending_id is None

    # файл ещё `pending`, но владелец уже ждёт другую загрузку
    other = support.make_employee()
    stale = make_waiting(other, protected_root, set_pending=False)
    newer = make_waiting(other, protected_root)
    tasks.scan_file(str(stale.id))
    stale.refresh_from_db()
    assert stale.status == "pending" and paths(protected_root, stale)["incoming"].exists()
    assert not paths(protected_root, stale)["512"].exists()
    assert fresh(other).photo_id is None and fresh(other).photo_pending_id == newer.id
    assert events("photo.checked", other) == [] and len(calls) == scans, "антивирус не вызывался"

    # карантинный файл не проверяется заново
    third = support.make_employee()
    held = make_waiting(third, protected_root, "quarantine")
    tasks.scan_file(str(held.id))
    held.refresh_from_db()
    assert held.status == "quarantine" and fresh(third).photo_id is None
    assert fresh(third).photo_pending_id == held.id and events("photo.checked", third) == []
    assert len(calls) == scans, "антивирус не вызывался"

    # строки `StoredFile` уже нет (замена загрузки или удаление фото), задание осталось в очереди
    gone_owner = support.make_employee()
    first = files.upload_photo(gone_owner, SimpleUploadedFile("p.png", support_org.png_bytes(40, 40),
                                                              content_type="image/png"), actor=gone_owner)
    second = files.upload_photo(gone_owner, SimpleUploadedFile("p.png", support_org.png_bytes(50, 50),
                                                               content_type="image/png"), actor=gone_owner)
    assert not stored_model().objects.filter(pk=first.pk).exists()
    snapshot = (stored_model().objects.count(), fresh(gone_owner).photo_id, fresh(gone_owner).photo_pending_id)
    audit = model("core.AuditEvent").objects.count()
    tasks.scan_file(str(first.id))                       # без исключения
    assert len(calls) == scans
    assert snapshot == (stored_model().objects.count(), fresh(gone_owner).photo_id, fresh(gone_owner).photo_pending_id)
    assert fresh(gone_owner).photo_pending_id == second.id and audit == model("core.AuditEvent").objects.count()
    assert paths(protected_root, second)["incoming"].exists() and events("photo.checked", gone_owner) == []


# --- 10. выдача --------------------------------------------------------------------------------

def test_photo_served_only_clean_only_with_right_via_x_accel_redirect(protected_root):
    """FR-132: выдаётся только действующее чистое `photo`, только со `staff.view`, `accounts.manage` или самому."""
    owner = support.make_employee()
    clean = make_clean_photo(owner, protected_root)
    waiting = make_waiting(owner, protected_root)
    url = lambda size="96", uid=None, pid=None: f"/staff/{uid or owner.pk}/photo/{pid or clean.id}/{size}/"

    for user, label in ((owner, "сам"), (support.make_with_permissions("staff.view"), "staff.view"),
                        (support.make_with_permissions("accounts.manage"), "только accounts.manage")):
        client = support.logged_in(user)
        for size in ("96", "512"):
            response = client.get(url(size))
            assert response.status_code == 200, label
            assert response["X-Accel-Redirect"] == f"/protected/photos/{clean.id}-{size}.jpg"
            assert response.content == b""

    anon = support.make_client().get(url())
    assert anon.status_code == 302 and anon["Location"].startswith("/login/")
    outsider = support.logged_in(support.make_employee())
    assert outsider.get(url()).status_code == 403
    foreign = support.logged_in(support.make_with_permissions("org.manage"))
    assert foreign.get(url()).status_code == 403, "постороннее право доступа к фото не даёт"
    assert outsider.get(url(pid="00000000-0000-4000-8000-000000000000")).status_code == 403, "право проверяется раньше объекта"

    viewer = support.logged_in(support.make_with_permissions("staff.view"))
    another = support.make_employee()
    other_clean = make_clean_photo(another, protected_root)
    assert viewer.get(url(pid=waiting.id)).status_code == 404, "файл на проверке не выдаётся"
    assert viewer.get(url(pid="00000000-0000-4000-8000-000000000000")).status_code == 404
    assert viewer.get(url(pid=other_clean.id)).status_code == 404, "чужой файл под адресом этого сотрудника"
    assert viewer.get(url(size="300")).status_code == 404
    assert viewer.get(url(uid=999999)).status_code == 404
    quarantined = make_waiting(another, protected_root, "quarantine")
    assert viewer.get(url(uid=another.pk, pid=quarantined.id)).status_code == 404


# --- 11. заголовки -----------------------------------------------------------------------------

def test_photo_response_headers_type_nosniff_private_cache(protected_root):
    """FR-132: `image/jpeg`, `nosniff`, `Cache-Control: private, max-age=86400` (исключение из `no-store` — только здесь)."""
    owner = support.make_employee()
    clean = make_clean_photo(owner, protected_root)
    client = support.logged_in(owner)

    for size in ("512", "96"):
        response = client.get(f"/staff/{owner.pk}/photo/{clean.id}/{size}/")
        assert response.status_code == 200 and response["X-Accel-Redirect"].startswith("/protected/photos/")
        assert response["Content-Type"] == "image/jpeg"
        assert response["X-Content-Type-Options"] == "nosniff"
        cache = response["Cache-Control"]
        assert "private" in cache and "max-age=86400" in cache and "no-store" not in cache and "public" not in cache
    assert "no-store" in client.get("/me/")["Cache-Control"], "прочие страницы остаются с no-store"


# --- 12. адрес меняется с фото -----------------------------------------------------------------

def test_photo_url_changes_with_photo_old_url_404(protected_root, monkeypatch):
    """FR-132: номер файла в адресе меняется вместе с фото; адрес прежнего фото отвечает 404."""
    from apps.core import tasks
    from apps.core.services import files

    user = support.make_employee()
    assert files.photo_url(user, 96) is None
    first = make_clean_photo(user, protected_root)
    user = fresh(user)
    old96, old512 = files.photo_url(user, 96), files.photo_url(user, 512)
    assert old96 == f"/staff/{user.pk}/photo/{first.id}/96/" and old512 == f"/staff/{user.pk}/photo/{first.id}/512/"
    viewer = support.logged_in(support.make_with_permissions("staff.view"))
    assert viewer.get(old96).status_code == 200

    waiting = make_waiting(user, protected_root)
    assert files.photo_url(fresh(user), 96) == old96, "файл на проверке адреса не даёт"

    support_org.scan_clean(monkeypatch)
    tasks.scan_file(str(waiting.id))
    user = fresh(user)
    new96 = files.photo_url(user, 96)
    assert user.photo_id == waiting.id and new96 == f"/staff/{user.pk}/photo/{waiting.id}/96/" and new96 != old96
    assert viewer.get(new96).status_code == 200
    assert viewer.get(old96).status_code == 404 and viewer.get(old512).status_code == 404

    files.delete_photo(user, actor=user)
    assert files.photo_url(fresh(user), 96) is None
    assert viewer.get(new96).status_code == 404


# --- 13. удаление ------------------------------------------------------------------------------

def test_photo_delete_by_self_or_accounts_manage_quarantine_kept(protected_root):
    """FR-132: сам сотрудник или `accounts.manage` удаляют `photo` и `photo_pending`; файл в карантине остаётся."""
    # сам: чистое фото и ожидающая загрузка
    owner = support.make_employee()
    clean = make_clean_photo(owner, protected_root)
    waiting = make_waiting(owner, protected_root)
    client = support.logged_in(owner)
    response = client.post("/me/photo/delete/")
    assert response.status_code == 302 and response["Location"] == "/me/"
    user = fresh(owner)
    assert user.photo_id is None and user.photo_pending_id is None
    assert stored_files(owner) == []
    p, w = paths(protected_root, clean), paths(protected_root, waiting)
    assert not p["512"].exists() and not p["96"].exists() and not w["incoming"].exists()
    [event] = events("photo.deleted", owner)
    assert event.actor_id == owner.pk and sorted(event.before["files"]) == sorted([str(clean.id), str(waiting.id)])

    # администратор: чужое фото, в карантине — прежний файл остаётся
    target = support.make_employee()
    clean2 = make_clean_photo(target, protected_root)
    held = make_waiting(target, protected_root, "quarantine")
    admin = support.make_admin()
    viewer = support.logged_in(support.make_with_permissions("staff.view"))
    assert viewer.post(f"/staff/{target.pk}/photo/delete/").status_code == 403
    assert support.logged_in(target).post(f"/staff/{target.pk}/photo/delete/").status_code == 403
    assert fresh(target).photo_id == clean2.id
    response = support.logged_in(admin).post(f"/staff/{target.pk}/photo/delete/")
    assert response.status_code == 302 and response["Location"] == f"/staff/{target.pk}/"
    user = fresh(target)
    assert user.photo_id is None and user.photo_pending_id is None
    assert [s.id for s in stored_files(target)] == [held.id]
    assert paths(protected_root, held)["quarantine"].exists() and not paths(protected_root, clean2)["512"].exists()
    [event] = events("photo.deleted", target)
    assert event.actor_id == admin.pk and event.before["files"] == [str(clean2.id)]

    # без фото — тихо
    plain = support.make_employee()
    response = support.logged_in(plain).post("/me/photo/delete/")
    assert response.status_code == 302 and events("photo.deleted", plain) == []
    assert support.make_client().post("/me/photo/delete/")["Location"].startswith("/login/")


# --- 14. заглушка ------------------------------------------------------------------------------

def test_initials_placeholder_until_clean_in_card_list_and_structure(protected_root):
    """FR-132: пока фото не проверено — заглушка с инициалами, затем картинка: в карточке, списке и «Структуре»."""
    person = support.make_employee(full_name="Иван Петров Сергеевич")
    single = support.make_employee(full_name="Мадонна")
    unit = support_org.make_unit("Сеть")
    support_org.make_member(person, unit)
    support_org.make_member(single, unit)
    viewer_user = support.make_with_permissions("staff.view")
    viewer = support.logged_in(viewer_user)
    mine = support.logged_in(person)
    make_waiting(person, protected_root)

    def views():
        card = card_segment(viewer.get(f"/staff/{person.pk}/", **HX).content.decode(), person)
        own = card_segment(mine.get("/me/").content.decode(), person)
        lst = viewer.get("/staff/?q=" + "Петров").content.decode()
        tree = viewer.get(f"/structure/{unit.pk}/").content.decode()
        return card, own, row_segment(lst, person), member_segment(tree, person), tree

    for segment in views()[:4]:
        assert photo_markup(segment) == (None, "ИП"), "пока файл не проверен — заглушка"
    assert photo_markup(member_segment(views()[4], single)) == (None, "М")
    assert 'data-photo-status="pending"' in mine.get("/me/").content.decode()

    clean = make_clean_photo(person, protected_root)
    expected = f"/staff/{person.pk}/photo/{clean.id}/96/"
    for segment in views()[:4]:
        assert photo_markup(segment) == (expected, None)
    tree = views()[4]
    assert photo_markup(member_segment(tree, single)) == (None, "М")


# --- 15. ночная очистка ------------------------------------------------------------------------

def test_quarantine_files_purged_after_30_days(protected_root):
    """FR-132: файлы карантина старше 30 суток стираются, строка остаётся, `photo_pending` обнуляется, событий нет."""
    from apps.core import tasks

    now = timezone.now()
    owner_old, owner_new = support.make_employee(), support.make_employee()
    clean = make_clean_photo(owner_old, protected_root)
    old = make_waiting(owner_old, protected_root, "quarantine")
    orphan = make_waiting(support.make_employee(), protected_root, "quarantine", set_pending=False)
    young = make_waiting(owner_new, protected_root, "quarantine")
    stored_model().objects.filter(pk__in=[old.pk, orphan.pk]).update(scanned_at=now - timedelta(days=31))
    stored_model().objects.filter(pk=young.pk).update(scanned_at=now - timedelta(days=29))
    before = model("core.AuditEvent").objects.count()

    assert tasks.purge_quarantine() == 2
    for stored in (old, orphan):
        stored.refresh_from_db()
        assert not paths(protected_root, stored)["quarantine"].exists()
        assert stored.status == "quarantine" and stored.signature == "Eicar-Signature" and stored.sha256
    assert fresh(owner_old).photo_pending_id is None and fresh(owner_old).photo_id == clean.id
    assert paths(protected_root, clean)["512"].exists()
    assert paths(protected_root, young)["quarantine"].exists() and fresh(owner_new).photo_pending_id == young.id
    assert model("core.AuditEvent").objects.count() == before
    assert tasks.purge_quarantine() == 0


# --- 16. события -------------------------------------------------------------------------------

def test_photo_events_signature_without_path_or_content(protected_root, monkeypatch, django_capture_on_commit_callbacks):
    """FR-150, FR-151: события `photo.*` — ключи `before/after` по контракту, без пути на диске и содержимого."""
    user = support.make_employee()
    client = support.logged_in(user)
    content = support_org.png_bytes(70, 70)
    support_org.scan_found(monkeypatch, "Eicar-Signature")

    upload_queued(client, django_capture_on_commit_callbacks, content)
    first = pending_of(user)
    [uploaded] = events("photo.uploaded", user)
    assert uploaded.actor_id == user.pk and uploaded.object_type == "user"
    assert uploaded.after["file_id"] == str(first.id) and uploaded.after["size"] == len(content)
    assert uploaded.after["content_type"] == "image/png"

    support_org.run_files_worker()
    [found] = events("photo.checked", user)
    assert found.actor_id is None and found.after["result"] == "quarantine"
    assert found.after["signature"] == "Eicar-Signature" and found.after["file_id"] == str(first.id)

    support_org.scan_clean(monkeypatch)
    upload_queued(client, django_capture_on_commit_callbacks, support_org.png_bytes(72, 72))
    second = pending_of(user)
    support_org.run_files_worker()
    clean_event = events("photo.checked", user)[-1]
    assert clean_event.actor_id is None and clean_event.after["result"] == "clean"
    assert clean_event.after["file_id"] == str(second.id) and "signature" not in clean_event.after

    assert client.post("/me/photo/delete/").status_code == 302
    [deleted] = events("photo.deleted", user)
    assert deleted.actor_id == user.pk and deleted.before["files"] == [str(second.id)]

    forbidden = (str(protected_root), "incoming", "quarantine/", "photos/", "/protected", ".jpg")
    for event in model("core.AuditEvent").objects.filter(action__startswith="photo."):
        text = json.dumps([event.before, event.after], ensure_ascii=False)
        assert not any(bad in text for bad in forbidden), (event.action, text)
        assert "iVBOR" not in text and "\\x89PNG" not in text
