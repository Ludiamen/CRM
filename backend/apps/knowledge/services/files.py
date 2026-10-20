"""Вложения статьи поверх ядра (PLAN-005, «Вложения и картинки; проверки файлов в ядре»; CONTRACT-005, 5.5).

Проверки содержимого, запись в закрытый том и перенос после проверки антивирусом — в `core.services.uploads`;
здесь — правила статьи (право, предел числа файлов, корзина), строки `ArticleFile` и запись `FilePurpose("knowledge")`
для точки `file_purposes`. Журнал не пишется (FR-438 вложения не называет).
"""
from django.db import transaction
from django.http import Http404

from apps.core.extensions import FilePurpose
from apps.core.models import StoredFile
from apps.core.services import files as core_files
from apps.core.services import uploads

from ..models import Article, ArticleFile
from . import FileRefused, access

PURPOSE = StoredFile.Purpose.KNOWLEDGE.value
MAX_FILE = 20 * 1024 * 1024
MAX_FILES = 20


def _locked_article(user, article_id: int) -> Article:
    """Статья под замком строки: сохранена (`Http404`), не в корзине (`ArticleGone`), видна и правится (`PermissionDenied`)."""
    from django.core.exceptions import PermissionDenied

    article = Article.objects.select_for_update().filter(pk=article_id).first()
    if article is None:
        raise Http404("Статьи нет")
    if article.state == Article.State.TRASH:
        raise access.ArticleGone
    if not access.is_visible(user, article):
        raise Http404("Статьи нет")
    if not access.can_change(user, article):
        raise PermissionDenied
    return article


def attach(user, article_id: int, upload) -> ArticleFile:
    """Прикрепляет один файл: пределы и проверки содержимого, запись `StoredFile` и строка `ArticleFile`.

    Отказ — `FileRefused` с кодом `too_big`, `executable`, `encrypted`, `limit_20`, `image_too_large` или
    `write_failed`; транзакция откатывается, статья цела.
    """
    with transaction.atomic():
        article = _locked_article(user, article_id)
        if ArticleFile.objects.filter(article=article).count() >= MAX_FILES:
            raise FileRefused("limit_20")
        data = upload.read()
        reason = uploads.reject_reason(upload.name, data, upload.size, MAX_FILE)
        if reason:
            raise FileRefused(reason)
        try:
            image_format = uploads.detect_image(data)
        except uploads.ImageTooLarge:
            raise FileRefused("image_too_large") from None
        try:
            stored = uploads.store(data, upload.name, PURPOSE)
        except OSError:
            # Решение 41: сбой записи — отказ с сообщением; исключение откатывает строки, статья цела
            raise FileRefused("write_failed") from None
        try:
            return ArticleFile.objects.create(article=article, file=stored, name=upload.name,
                                              image_format=image_format, uploaded_by=user)
        except Exception:
            # Запись файла без строки (транзакция откатывается) не нужна
            core_files.remove_paths([core_files.attachment_path(stored)])
            raise


def remove(user, file_id: int) -> None:
    """Удаляет вложение: строки `ArticleFile` и `StoredFile` — в транзакции, файл с диска — после фиксации."""
    row = ArticleFile.objects.filter(pk=file_id).values_list("article_id", flat=True).first()
    if row is None:
        raise Http404("Файла нет")
    with transaction.atomic():
        _locked_article(user, row)
        item = ArticleFile.objects.select_related("file").filter(pk=file_id).first()
        if item is None:
            raise Http404("Файла нет")
        stored = item.file
        path = core_files.attachment_path(stored)
        item.delete()
        stored.delete()
        transaction.on_commit(lambda: core_files.remove_paths([path]))


def list_for(article) -> list:
    """Вложения статьи по времени загрузки; состояние проверки читается без запроса на строку."""
    return list(ArticleFile.objects.filter(article=article).select_related("file").order_by("uploaded_at", "id"))


def files_map(article) -> dict:
    """`{номер вложения: (имя, формат картинки)}` для `render.render`; один запрос."""
    return {pk: (name, image_format) for pk, name, image_format
            in ArticleFile.objects.filter(article=article).values_list("pk", "name", "image_format")}


# --- итог проверки антивирусом (точка `file_purposes`) -------------------------------------------------

def still_waiting(stored) -> bool:
    """Файл ещё ждёт проверки: он `pending` и у него есть строка `ArticleFile`."""
    return stored.status == StoredFile.Status.PENDING and ArticleFile.objects.filter(file=stored).exists()


def on_clean(stored) -> list:
    """Итог «чисто»: файл в `attachments/<id>`, статус `clean`; возвращает прежние пути для стирания после фиксации."""
    return uploads.move(stored, StoredFile.Status.CLEAN)


def on_found(stored, signature: str) -> list:
    """Итог «найдено»: архив с паролем (`Heuristics.Encrypted.*`) — отказ (строки удаляются), иначе карантин."""
    if signature.startswith("Heuristics.Encrypted."):
        leftovers = [core_files.attachment_path(stored)]
        ArticleFile.objects.filter(file=stored).delete()
        stored.delete()
        return leftovers
    return uploads.move(stored, StoredFile.Status.QUARANTINE, signature)


def file_purposes() -> list:
    """Описание назначения «файл статьи» для точки `file_purposes` ядра."""
    return [FilePurpose(purpose=PURPOSE, still_waiting=still_waiting, clean=on_clean, found=on_found)]
