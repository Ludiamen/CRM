"""T-8117b (догоняющая работа по решению владельца 2026-11-17): выдача, эскизы и карантин.

Файл отсутствовал в репозитории после Этапа 2; восстановлен по TASKS-008 T-8117b и CONTRACT-008 § 1.3, 5.4, 12.5,
13.1, 13.3 перед T-8216. Проверяет итог антивируса через точку `file_purposes` (настоящее задание очереди
`files`), выдачу оригинала и эскиза через `X-Accel-Redirect`, состояние «проверяется»/«карантин», эскиз 1280 без
EXIF и первый кадр GIF, чужой чат и непривязанный файл, ночную уборку непривязанных старше суток.

Код среза на уровне модуля не импортируется (кроме помощников среза и `support_org`); модели — `support.model`.
"""
import pathlib

import pytest
from django.conf import settings as django_settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone
from PIL import Image

from tests import support
from tests import support_messenger as mm
from tests import support_org as org

pytestmark = pytest.mark.django_db

MISSING = 999999
PENDING_TEXT = "Файл ещё проверяется"
QUARANTINE_TEXT = "Файл в карантине"


def _chat():
    author = mm.make_user(full_name="Автор Выдачи Файлов")
    friend = mm.make_user(full_name="Читатель Выдачи Файлов")
    return author, friend, mm.group(author, [friend], title="Выдача файлов")


def _upload(session, chat, name: str, data: bytes):
    fields = {"file": SimpleUploadedFile(name, data), "chat": chat.pk}
    return session.client.post("/messenger/files/", fields, **support.HX)


def _item(response):
    """Строка `MessageAttachment` из ответа загрузки (таблетка `[data-messenger-file]`)."""
    import re

    found = re.search(r'data-messenger-file="(\d+)"', response.content.decode("utf-8"))
    assert found, response.content.decode()[:400]
    return support.model("messenger.MessageAttachment").objects.get(pk=int(found.group(1)))


def _scan(item):
    """Проверка одного файла тем же заданием, что и очередь (файл уже сохранён)."""
    from apps.core import tasks

    tasks.scan_file(str(item.file_id))


def _send(author, chat, item):
    return author.client.post(f"/messenger/chats/{chat.pk}/messages/",
                              {"text": "Сообщение с файлом", "files": [str(item.pk)]}, **support.HX)


def _row(response, item):
    import re

    html = response.content.decode("utf-8")
    match = re.search(rf'<span data-messenger-file="{item.pk}" data-file-state="([^"]+)"', html)
    assert match, f"нет файла {item.pk} в ответе"
    return match.group(1)


def test_clean_image_shown_thumbnail_and_full_on_click(monkeypatch):
    """FR-662: «чистый» файл картинки — `a[href="/messenger/files/<id>/"] > img[src="…/thumb/"]`, оригинал и эскиз
    отдаются 200 через `X-Accel-Redirect`; файл сообщения виден участнику."""
    author, friend, chat = _chat()
    org.scan_clean(monkeypatch)
    item = _item(_upload(author, chat, "схема.png", org.png_bytes()))
    _scan(item)
    item.refresh_from_db()
    assert item.file.status == "clean" and item.thumb, (item.file.status, item.thumb)
    assert _send(author, chat, item).status_code == 200

    page = friend.client.get(f"/messenger/chats/{chat.pk}/")
    assert page.status_code == 200
    assert _row(page, item) == "clean"
    html = page.content.decode("utf-8")
    assert f'href="/messenger/files/{item.pk}/"' in html
    assert f'src="/messenger/files/{item.pk}/thumb/"' in html

    original = friend.client.get(f"/messenger/files/{item.pk}/")
    thumb = friend.client.get(f"/messenger/files/{item.pk}/thumb/")
    assert original.status_code == 200 and original["X-Accel-Redirect"].startswith("/protected/attachments/")
    assert thumb.status_code == 200 and thumb["X-Accel-Redirect"].startswith("/protected/attachments/thumbs/")
    for response in (original, thumb):
        assert response["X-Content-Type-Options"] == "nosniff" and response["Cache-Control"] == "no-store"


def test_pending_and_quarantine_not_downloadable_with_texts(monkeypatch):
    """FR-662: «проверяется» и «карантин» не скачиваются — 404 с текстами контракта; в беседе — имя и пометка без
    ссылки."""
    author, friend, chat = _chat()
    org.scan_unavailable(monkeypatch)
    pending = _item(_upload(author, chat, "ждёт.txt", b"data"))
    try:
        _scan(pending)
    except Exception:  # noqa: BLE001 — недоступный антивирус оставляет файл «проверяется»
        pass
    pending.refresh_from_db()
    assert pending.file.status == "pending"
    _send(author, chat, pending)
    page = friend.client.get(f"/messenger/chats/{chat.pk}/")
    assert _row(page, pending) == "pending" and "проверяется" in page.content.decode("utf-8")
    refused = friend.client.get(f"/messenger/files/{pending.pk}/")
    assert refused.status_code == 404 and PENDING_TEXT in refused.content.decode("utf-8")

    org.scan_found(monkeypatch)
    virus = _item(_upload(author, chat, "вирус.txt", b"data"))
    _scan(virus)
    virus.refresh_from_db()
    assert virus.file.status == "quarantine"
    _send(author, chat, virus)
    page = friend.client.get(f"/messenger/chats/{chat.pk}/")
    assert _row(page, virus) == "quarantine" and "карантин" in page.content.decode("utf-8")
    refused = friend.client.get(f"/messenger/files/{virus.pk}/")
    assert refused.status_code == 404 and QUARANTINE_TEXT in refused.content.decode("utf-8")
    assert friend.client.get(f"/messenger/files/{virus.pk}/thumb/").status_code == 404


def test_clamav_down_keeps_message_and_file_pending_for_retry(monkeypatch):
    """FR-662: антивирус недоступен — файл остаётся «проверяется», попытка записана, сообщение и вложение на месте:
    проверку повторит очередь."""
    author, friend, chat = _chat()
    org.scan_unavailable(monkeypatch)
    item = _item(_upload(author, chat, "позже.txt", b"data" * 100))
    _send(author, chat, item)
    try:
        _scan(item)
    except Exception:  # noqa: BLE001 — антивирус недоступен
        pass
    item.refresh_from_db()
    assert item.file.status == "pending", item.file.status
    assert item.file.attempts >= 1 and item.file.last_error
    assert support.model("messenger.Message").objects.filter(chat=chat).exists()
    page = friend.client.get(f"/messenger/chats/{chat.pk}/")
    assert _row(page, item) == "pending"


def test_thumb_1280_without_exif_and_gif_first_frame(monkeypatch):
    """FR-662: эскиз не больше 1280 px по стороне, EXIF-ориентация применена, у GIF — первый кадр."""
    author, _, chat = _chat()
    images = mm.images()
    org.scan_clean(monkeypatch)
    jpeg = _item(_upload(author, chat, "поворот.jpg", images["jpeg_exif"]))
    gif = _item(_upload(author, chat, "кадры.gif", images["gif_frames"]))
    _scan(jpeg)
    _scan(gif)
    jpeg.refresh_from_db()
    gif.refresh_from_db()
    assert jpeg.thumb and gif.thumb, (jpeg.thumb, gif.thumb)

    with Image.open(pathlib.Path(django_settings.PROTECTED_ROOT) / jpeg.thumb) as thumb:
        assert max(thumb.size) <= 1280
        assert thumb.height > thumb.width, f"EXIF-ориентация не применена: {thumb.size}"
    with Image.open(pathlib.Path(django_settings.PROTECTED_ROOT) / gif.thumb) as thumb:
        assert max(thumb.size) <= 1280
        assert getattr(thumb, "n_frames", 1) == 1, "эскиз GIF содержит больше одного кадра"


def test_thumb_path_under_protected_attachments_thumbs(monkeypatch):
    """FR-662: путь эскиза — `attachments/thumbs/<имя>` под `PROTECTED_ROOT`, ответ — `X-Accel-Redirect:
    /protected/attachments/thumbs/<имя>`; эскиз не строится для не-картинки."""
    author, friend, chat = _chat()
    org.scan_clean(monkeypatch)
    image = _item(_upload(author, chat, "снимок.png", org.png_bytes()))
    text_file = _item(_upload(author, chat, "план.txt", b"plain text"))
    _scan(image)
    _scan(text_file)
    image.refresh_from_db()
    text_file.refresh_from_db()
    assert image.thumb.startswith("attachments/thumbs/")
    assert (pathlib.Path(django_settings.PROTECTED_ROOT) / image.thumb).is_file()
    assert text_file.file.status == "clean" and text_file.thumb == ""
    _send(author, chat, image)
    _send(author, chat, text_file)
    thumb = friend.client.get(f"/messenger/files/{image.pk}/thumb/")
    assert thumb.status_code == 200
    assert thumb["X-Accel-Redirect"] == f"/protected/{image.thumb}"
    assert friend.client.get(f"/messenger/files/{text_file.pk}/thumb/").status_code == 404


def test_foreign_chat_original_and_thumb_404(monkeypatch):
    """FR-669: оригинал и эскиз файла чужого чата — тот же 404, что у несуществующего файла."""
    author, friend, chat = _chat()
    stranger = mm.make_user(full_name="Посторонний Выдачи")
    org.scan_clean(monkeypatch)
    item = _item(_upload(author, chat, "закрытый.png", org.png_bytes()))
    _scan(item)
    _send(author, chat, item)

    for path in (f"/messenger/files/{item.pk}/", f"/messenger/files/{item.pk}/thumb/"):
        hidden = stranger.client.get(path)
        missing = stranger.client.get(path.replace(str(item.pk), str(MISSING)))
        assert hidden.status_code == missing.status_code == 404
        assert support.same_failure(hidden, missing)


def test_unbound_file_visible_only_to_uploader(monkeypatch):
    """FR-662, 669: непривязанный файл видит только загрузивший; остальным — 404, как у несуществующего."""
    author, friend, chat = _chat()
    org.scan_clean(monkeypatch)
    item = _item(_upload(author, chat, "черновик.png", org.png_bytes()))
    _scan(item)
    item.refresh_from_db()
    assert author.client.get(f"/messenger/files/{item.pk}/").status_code == 200
    refused = friend.client.get(f"/messenger/files/{item.pk}/")
    missing = friend.client.get(f"/messenger/files/{MISSING}/")
    assert refused.status_code == 404 and support.same_failure(refused, missing)


def test_night_purge_removes_unbound_older_than_day(monkeypatch, protected_root,
                                                  django_capture_on_commit_callbacks):
    """FR-662, 670: ночное задание убирает непривязанные файлы старше суток — строки вложения и файла и файл на
    диске; свежий непривязанный и привязанный остаются."""
    author, _, chat = _chat()
    org.scan_clean(monkeypatch)
    old = _item(_upload(author, chat, "старый.png", org.png_bytes()))
    fresh = _item(_upload(author, chat, "свежий.png", org.png_bytes()))
    bound = _item(_upload(author, chat, "привязанный.png", org.png_bytes()))
    _send(author, chat, bound)
    for item in (old, fresh, bound):
        _scan(item)
    for item in (old, fresh, bound):
        item.refresh_from_db()
    now = timezone.now()
    support.model("messenger.MessageAttachment").objects.filter(pk=old.pk).update(
        uploaded_at=now - timezone.timedelta(days=2))
    old_path = pathlib.Path(django_settings.PROTECTED_ROOT) / "attachments" / str(old.file_id)
    assert old_path.is_file()

    with django_capture_on_commit_callbacks(execute=True):
        mm.run_retention(now)

    assert not support.model("messenger.MessageAttachment").objects.filter(pk=old.pk).exists()
    assert not support.model("core.StoredFile").objects.filter(pk=old.file_id).exists()
    assert not old_path.exists()
    assert support.model("messenger.MessageAttachment").objects.filter(pk=fresh.pk).exists()
    assert support.model("messenger.MessageAttachment").objects.filter(pk=bound.pk).exists()