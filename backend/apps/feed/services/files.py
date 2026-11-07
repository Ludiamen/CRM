"""Сервис ленты: загрузка, привязка, «убрать», итог проверки и эскизы файлов (T-7226, T-7227; PLAN-007,
«Файлы и эскизы»).

Проверки содержимого, запись в закрытый том и постановка проверки антивирусом — в `core.services.uploads`;
здесь — правила ленты: один файл отдельным запросом, ранний отказ по числу, предел 30 непривязанных,
условная привязка с проверкой числа обновлённых строк и удаление только своих непривязанных файлов.
Итог проверки решает запись `FilePurpose("feed")` для точки `file_purposes` ядра: «чистый» — перенос в
`attachments/` и эскиз (`services.thumbs`), «карантин» — пометка; сбой ClamAV и хранилища оставляет файл
«проверяется» с повтором прежнего задания ядра (NFR-614).
"""
import logging
import pathlib

from django.conf import settings
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from apps.core.models import Comment, StoredFile
from apps.core.services import files as core_files
from apps.core.services import uploads
from apps.feed.models import FeedFile
from apps.feed.services import thumbs
from apps.feed.services.errors import FeedError

logger = logging.getLogger(__name__)

PURPOSE = StoredFile.Purpose.FEED.value
MAX_FILE = 20 * 1024 * 1024
MAX_POST_FILES = 10
MAX_COMMENT_FILES = 3
MAX_UNBOUND = 30
_REFUSALS = {"too_big": "file_too_big", "executable": "file_type", "encrypted": "file_type"}


def _ids(values) -> list[int]:
    """Номера из значений формы/службы без повторов; нечисловое пропускается."""
    if values is None:
        return []
    if isinstance(values, (str, bytes)):
        values = [values]
    ids = []
    for value in values:
        text = str(value).strip()
        if text.isdigit():
            ids.append(int(text))
    return list(dict.fromkeys(ids))


def _int_or_none(value) -> int | None:
    text = str(value or "").strip()
    return int(text) if text.isdigit() else None


def _comment_target(comment_id: int) -> None:
    """Комментарий номера — только комментарий ленты; иначе 404 (FR-624, К84)."""
    if not Comment.objects.filter(pk=comment_id, object_ref__startswith="feed.post:").exists():
        raise Http404("Комментарий не найден")


def upload(user, uploaded, *, scope, post_id=None, comment_id=None, have=()) -> FeedFile:
    """Загрузить один файл заранее: строка `FeedFile` без записи (CONTRACT-007, 5.5).

    Отказы — `FeedError` с полем `file`: пределы (`post_files_limit`, `comment_files_limit`), 30 непривязанных
    (`too_many_unbound`), содержимое (`file_too_big`, `file_type`). При нарушении двух пределов сначала 10/3,
    затем 30 непривязанных (К73). `have` — номера своих непривязанных файлов формы (подсказка клиента).
    """
    if uploaded is None:
        raise FeedError("file_missing", "file")
    scope = "comment" if str(scope) == "comment" else "post"
    post_id = _int_or_none(post_id)
    comment_id = _int_or_none(comment_id)
    have_ids = _ids(have)
    if scope == "comment":
        if comment_id is not None:
            _comment_target(comment_id)
        attached = FeedFile.objects.filter(comment_id=comment_id).count() if comment_id else 0
        limit, code = MAX_COMMENT_FILES, "comment_files_limit"
    else:
        attached = FeedFile.objects.filter(post_id=post_id, comment__isnull=True).count() if post_id else 0
        limit, code = MAX_POST_FILES, "post_files_limit"
    if attached + len(have_ids) >= limit:
        raise FeedError(code, "file")
    if FeedFile.objects.filter(uploaded_by=user, post__isnull=True).count() >= MAX_UNBOUND:
        raise FeedError("too_many_unbound", "file")

    name = str(uploaded.name)[:255]
    data = uploaded.read()
    reason = uploads.reject_reason(name, data, len(data), MAX_FILE)
    if reason:
        raise FeedError(_REFUSALS[reason], "file")
    try:
        uploads.detect_image(data)
    except uploads.ImageTooLarge:
        # тот же отказ типа: картинка больше 40 Мп или «бомба» (план, F3 Ф22)
        raise FeedError("file_type", "file") from None
    with transaction.atomic():
        stored = uploads.store(data, name, PURPOSE)
        feed_file = FeedFile.objects.create(file=stored, name=name, uploaded_by=user,
                                             uploaded_at=timezone.now())
    return feed_file


def bind(user, ids, *, post, comment=None) -> None:
    """Привязать файлы условным UPDATE с проверкой числа строк (CONTRACT-007, 5.5).

    `UPDATE … WHERE id IN (…) AND post_id IS NULL AND comment_id IS NULL AND uploaded_by_id = <я>`:
    обновлено меньше, чем прислано, — `FeedError("file_missing", "files")` и откат транзакции зовущего.
    Пределы (10 у записи, 3 у комментария, считая прикреплённые) проверяются здесь же — звать под
    `select_for_update` строки записи.
    """
    file_ids = _ids(ids)
    if comment is not None:
        attached = FeedFile.objects.filter(comment=comment).count()
        limit, code = MAX_COMMENT_FILES, "comment_files_limit"
    else:
        attached = FeedFile.objects.filter(post=post, comment__isnull=True).count()
        limit, code = MAX_POST_FILES, "post_files_limit"
    if attached + len(file_ids) > limit:
        raise FeedError(code, "files")
    if not file_ids:
        return
    bound = FeedFile.objects.filter(
        pk__in=file_ids, post__isnull=True, comment__isnull=True, uploaded_by=user,
    ).update(post=post, comment=comment)
    if bound != len(file_ids):
        raise FeedError("file_missing", "files")


def _erase(paths) -> None:
    """Стирает файлы с диска после фиксации; отсутствующий файл — не ошибка."""
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def remove_unbound(user, file_id: int) -> None:
    """Убрать свой непривязанный файл до публикации: строки — в транзакции, диск — после фиксации.

    Чужой, привязанный и несуществующий — `Http404` одним и тем же ответом.
    """
    try:
        feed_file = FeedFile.objects.select_related("file").get(pk=file_id)
    except FeedFile.DoesNotExist as exc:
        raise Http404("Файл не найден") from exc
    if feed_file.uploaded_by_id != user.pk or feed_file.post_id is not None:
        raise Http404("Файл не найден")
    paths = [core_files.attachment_path(feed_file.file)]
    if feed_file.thumb:
        paths.append(pathlib.Path(settings.PROTECTED_ROOT) / feed_file.thumb)
    with transaction.atomic():
        stored_id = feed_file.file_id
        feed_file.delete()
        StoredFile.objects.filter(pk=stored_id).delete()
        transaction.on_commit(lambda: _erase(paths))


# --- итог проверки антивирусом (точка `file_purposes`; CONTRACT-007, 5.5, 5.7) --------------------------

def still_waiting(stored) -> bool:
    """Файл ещё ждёт проверки: он `pending` и у него есть строка `FeedFile`."""
    return stored.status == StoredFile.Status.PENDING and FeedFile.objects.filter(file=stored).exists()


def _remove_partial_thumbs(stored_id) -> None:
    """Стереть недописанный эскиз (и временный файл): сбой не должен оставлять мусор в томе."""
    folder = pathlib.Path(settings.PROTECTED_ROOT) / "attachments" / "thumbs"
    for path in folder.glob(f"{stored_id}.*"):
        try:
            path.unlink()
        except FileNotFoundError:
            pass


def clean(stored) -> list:
    """Итог «чисто»: перенос в `attachments/<id>` и эскиз; сбой эскиза не откладывает «чистый».

    Ошибка построения эскиза ловится отдельно от переноса (план, F3 Ф24): пишется предупреждение в журнал
    `apps.feed.services.files` без имени файла, недописанный эскиз стирается, `FeedFile.thumb` остаётся
    пустым, файл — «чистый» и показывается именем. Сбой переноса не ловится: транзакция проверки
    откатывается, файл остаётся «проверяется» с повтором прежнего задания ядра (NFR-614).
    """
    leftovers = uploads.move(stored, StoredFile.Status.CLEAN)
    relative = ""
    try:
        relative = thumbs.build(core_files.attachment_path(stored), stored.pk)
    except Exception as exc:  # noqa: BLE001 — сбой эскиза не должен откатывать перенос и проверку
        _remove_partial_thumbs(stored.pk)
        logger.warning("thumbs: сбой построения эскиза, файл остался чистым без эскиза (%s)",
                       type(exc).__name__)
    if relative:
        FeedFile.objects.filter(file=stored).update(thumb=relative)
    return leftovers


def found(stored, signature: str) -> list:
    """Итог «найдено»: пометка карантина с переносом файла; строка `FeedFile` остаётся, эскиза нет."""
    return uploads.move(stored, StoredFile.Status.QUARANTINE, signature)


def file_purposes() -> list:
    """Описание назначения «вложение ленты» для точки `file_purposes` ядра."""
    from apps.core.extensions import FilePurpose

    return [FilePurpose(purpose=PURPOSE, still_waiting=still_waiting, clean=clean, found=found)]
