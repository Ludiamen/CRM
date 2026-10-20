"""Статьи: создание, сохранение, публикация, корзина, удаление навсегда, комментарии (PLAN-005, «Создание, сохранение
и публикация», «Корзина и ночная очистка»; FR-401, FR-404, FR-408, FR-410, FR-413, FR-415…FR-417, FR-447).

Все записи идут в транзакции под `select_for_update` строки статьи; представления только разбирают форму. Порядок
шагов `save`, `publish` и `versions.restore` — шаги плана: корзина → право → рубрика → устаревшая версия →
«Изменений нет» → ПДн → запись. Векторы поиска считает только `vectors.refresh`; события шины (`events.publish`)
уходят после фиксации сами.
"""
import logging
from typing import NamedTuple

from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.http import Http404
from django.utils import timezone

from apps.core import events
from apps.core.models import Comment, StoredFile
from apps.core.services import audit, comments
from apps.core.services import files as core_files

from ..models import Article, ArticleFile, ArticleVersion, Rubric, Tag
from . import ArticleError, VersionConflict, access, files, pdn, render, vectors
from . import tags as tag_service

logger = logging.getLogger(__name__)

OBJECT_TYPE = "knowledge.article"
MAX_TITLE = 200
MAX_TEXT = 200_000
MAX_COMMENT = 200
TAGS_LOCK_KEY = "knowledge.tags"


class ArticleForm(NamedTuple):
    """Поля формы статьи как введены; `tags` — строка через запятую, `comment` — комментарий к правке."""

    title: str
    text: str
    rubric_id: int | None
    tags: str
    comment: str = ""


class SaveResult(NamedTuple):
    """Итог сохранения: `kind` — `saved`, `no_changes` или `pdn_warning`; `version` — новая версия или `None`;
    `pdn` — найденное при `pdn_warning`."""

    kind: str
    article: Article
    version: ArticleVersion | None
    pdn: list


class CleanForm(NamedTuple):
    """Форма после приведения: заголовок без пробелов по краям, переводы строк `\\n`, теги — список строчных."""

    title: str
    text: str
    rubric_id: int | None
    tags: list
    comment: str


def clean_form(form: ArticleForm) -> CleanForm:
    """Проверяет и приводит поля формы (не зависят от состояния статьи); отказ — `ArticleError` или `TagError`."""
    title = (form.title or "").strip()
    if not title:
        raise ArticleError("title_empty", "title")
    if len(title) > MAX_TITLE:
        raise ArticleError("title_too_long", "title")
    text = (form.text or "").replace("\r\n", "\n").replace("\r", "\n")
    if len(text) > MAX_TEXT:
        raise ArticleError("text_too_long", "text")
    comment = form.comment or ""
    if len(comment) > MAX_COMMENT:
        raise ArticleError("comment_too_long", "comment")
    names = tag_service.normalize(form.tags)
    return CleanForm(title, text, form.rubric_id, names, comment)


# --- общие шаги цепочки (их зовёт и `versions.restore`) ---------------------------------------------------------

def lock_article(user, article_id: int) -> Article:
    """Шаги 1 и 2: строка статьи под `FOR UPDATE`; в корзине — `ArticleGone`; не видна — `Http404`; нет права
    править — `PermissionDenied`. Зовётся внутри транзакции."""
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


def lock_rubric(rubric_id: int | None) -> Rubric:
    """Шаг 3: строка рубрики под `FOR UPDATE` (удаление рубрики не успеет между проверкой и записью)."""
    rubric = None
    if rubric_id is not None:
        rubric = Rubric.objects.select_for_update().filter(pk=rubric_id).first()
    if rubric is None:
        raise ArticleError("rubric_missing", "rubric")
    return rubric


def check_base_version(article: Article, base_version: int) -> None:
    """Шаг 4: форму открывали на другой версии — `VersionConflict` с тем, кто и когда сохранил последним."""
    if article.version_no != base_version:
        raise VersionConflict(who=article.updated_by.full_name, when=article.updated_at,
                              current_version=article.version_no, base_version=base_version)


def tag_names_of(article: Article) -> list:
    return sorted(article.tags.values_list("name", flat=True))


def same_as_current(article: Article, title: str, text: str, rubric_id: int, tag_names) -> bool:
    """Шаг 5: заголовок, текст, рубрика и набор тегов совпадают с текущими."""
    return (article.title == title and article.text == text and article.rubric_id == rubric_id
            and tag_names_of(article) == sorted(set(tag_names)))


def _lock_tags_shared() -> None:
    """Разделяемый замок тегов: ночная очистка тегов (исключительный замок) дождётся конца сохранения."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT pg_advisory_xact_lock_shared(hashtextextended(%s, 0))", [TAGS_LOCK_KEY])


def _create_version(article: Article, user, number: int, comment: str, rubric: Rubric, tag_names, created_at):
    """Строка версии: снимок полей статьи на момент сохранения (номера не переиспользуются)."""
    return ArticleVersion.objects.create(
        article=article, number=number, author=user, created_at=created_at, comment=comment, title=article.title,
        text=article.text, html=article.html, rubric=rubric, rubric_name=rubric.name, tags=sorted(tag_names))


def write_edit(article: Article, user, *, title: str, text: str, rubric: Rubric, tag_names, comment: str,
               publish: bool = False) -> ArticleVersion:
    """Шаг 7: разделяемый замок тегов, новая версия `version_no + 1`, поля статьи, теги, векторы, событие.

    `publish=True` — публикация вместе с правкой: состояние и `published_at` ставятся здесь же, событие — `published`
    (его даёт `publish`), а не `changed`.
    """
    now = timezone.now()
    rendered = render.render(text, files.files_map(article), article.pk)
    _lock_tags_shared()
    tag_objects = [Tag.objects.get_or_create(name=name)[0] for name in tag_names]
    article.title, article.text, article.html, article.plain = title, text, rendered.html, rendered.plain
    article.rubric = rubric
    article.version_no += 1
    article.updated_by, article.updated_at = user, now
    fields = ["title", "text", "html", "plain", "rubric", "version_no", "updated_by", "updated_at"]
    if publish:
        _mark_published(article, user, now)
        fields += ["state", "published_at"]
    article.save(update_fields=fields)
    article.tags.set(tag_objects)
    version = _create_version(article, user, article.version_no, comment, rubric, tag_names, now)
    if article.state == Article.State.PUBLISHED:
        vectors.refresh([article.pk])
        if not publish:
            events.publish("knowledge.article_changed", article_id=article.pk, actor_id=user.pk,
                           rubric_id=article.rubric_id)
    return version


def _mark_published(article: Article, user, now) -> None:
    article.state = Article.State.PUBLISHED
    if article.published_at is None:
        article.published_at = now
    article.updated_by, article.updated_at = user, now


# --- создание, сохранение, публикация ---------------------------------------------------------------------------

def create(user, form: ArticleForm, *, from_ticket: int | None = None) -> Article:
    """Первое сохранение: черновик и версия 1 одной транзакцией; журнал `knowledge.article_created`; векторов и
    событий нет."""
    if not access.can_edit(user):
        raise PermissionDenied
    clean = clean_form(form)
    with transaction.atomic():
        rubric = lock_rubric(clean.rubric_id)
        now = timezone.now()
        rendered = render.render(clean.text, {}, None)
        _lock_tags_shared()
        article = Article.objects.create(
            title=clean.title, text=clean.text, html=rendered.html, plain=rendered.plain, rubric=rubric,
            state=Article.State.DRAFT, author=user, created_at=now, updated_by=user, updated_at=now, version_no=1,
            from_ticket=from_ticket)
        article.tags.set([Tag.objects.get_or_create(name=name)[0] for name in clean.tags])
        _create_version(article, user, 1, clean.comment, rubric, clean.tags, now)
        audit.record("knowledge.article_created", actor=user, object_type=OBJECT_TYPE, object_id=article.pk,
                     after={"number": article.pk, "title": article.title, "version": 1})
    return article


def save(user, article_id: int, base_version: int, form: ArticleForm, confirm_pdn: bool = False) -> SaveResult:
    """Сохранение правки (шаги плана 1–7); версия — только если что-то изменилось."""
    clean = clean_form(form)
    with transaction.atomic():
        article = lock_article(user, article_id)
        rubric = lock_rubric(clean.rubric_id)
        check_base_version(article, base_version)
        if same_as_current(article, clean.title, clean.text, rubric.pk, clean.tags):
            return SaveResult("no_changes", article, None, [])
        if article.state == Article.State.PUBLISHED and not confirm_pdn:
            found = pdn.find(clean.title, clean.text)
            if found:
                return SaveResult("pdn_warning", article, None, found)
        version = write_edit(article, user, title=clean.title, text=clean.text, rubric=rubric,
                             tag_names=clean.tags, comment=clean.comment)
    return SaveResult("saved", article, version, [])


def publish(user, article_id: int, base_version: int, form: ArticleForm | None = None,
            confirm_pdn: bool = False) -> SaveResult:
    """Публикация черновика: с изменённой формой — новая версия и публикация, иначе публикация без версии.

    Обратного перехода в черновик нет. Журнал `knowledge.article_published`, событие шины после фиксации.
    """
    clean = clean_form(form) if form is not None else None
    with transaction.atomic():
        article = lock_article(user, article_id)
        if article.state == Article.State.PUBLISHED:
            raise ArticleError("already_published")
        rubric = lock_rubric(clean.rubric_id) if clean is not None else None
        check_base_version(article, base_version)
        changed = clean is not None and not same_as_current(
            article, clean.title, clean.text, rubric.pk, clean.tags)
        title, text = (clean.title, clean.text) if changed else (article.title, article.text)
        if not confirm_pdn:
            found = pdn.find(title, text)
            if found:
                return SaveResult("pdn_warning", article, None, found)
        version = None
        if changed:
            version = write_edit(article, user, title=clean.title, text=clean.text, rubric=rubric,
                                 tag_names=clean.tags, comment=clean.comment, publish=True)
        else:
            _mark_published(article, user, timezone.now())
            article.save(update_fields=["state", "published_at", "updated_by", "updated_at"])
            vectors.refresh([article.pk])
        audit.record("knowledge.article_published", actor=user, object_type=OBJECT_TYPE, object_id=article.pk,
                     after={"number": article.pk, "title": article.title, "version": article.version_no})
        events.publish("knowledge.article_published", article_id=article.pk, actor_id=user.pk,
                       rubric_id=article.rubric_id)
    return SaveResult("saved", article, version, [])


def viewed(user, article: Article) -> None:
    """Показ страницы статьи: событие ядра `object.viewed` (глушит непрочитанные уведомления об этой статье)."""
    events.publish("object.viewed", object_ref=f"knowledge.article:{article.pk}", user_id=user.pk)


# --- корзина и удаление -----------------------------------------------------------------------------------------

def _lock_for_manage(user, article_id: int) -> Article:
    """Строка статьи под замком для действий управляющего: нет — `Http404`; в корзине — `ArticleGone`; нет права —
    `PermissionDenied`."""
    article = Article.objects.select_for_update().filter(pk=article_id).first()
    if article is None:
        raise Http404("Статьи нет")
    if article.state == Article.State.TRASH:
        raise access.ArticleGone
    if not access.can_manage(user):
        raise PermissionDenied
    return article


def trash(user, article_id: int) -> Article:
    """В корзину (управляющий): состояние запоминается, векторы пустеют; журнал `knowledge.article_trashed`."""
    with transaction.atomic():
        article = _lock_for_manage(user, article_id)
        article.state_before_trash = article.state
        article.state = Article.State.TRASH
        article.deleted_at = timezone.now()
        article.deleted_by = user
        article.save(update_fields=["state_before_trash", "state", "deleted_at", "deleted_by"])
        vectors.refresh([article.pk])
        audit.record("knowledge.article_trashed", actor=user, object_type=OBJECT_TYPE, object_id=article.pk,
                     after={"number": article.pk, "title": article.title})
    return article


def restore(user, article_id: int) -> Article:
    """Возврат из корзины (управляющий): прежнее состояние, поля удаления очищены; журнал `knowledge.article_restored`.

    Порядок отказов: в корзине и не управляющий — `ArticleGone`; не в корзине и не управляющий — `PermissionDenied`;
    не в корзине и управляющий — `not_in_trash`.
    """
    with transaction.atomic():
        article = Article.objects.select_for_update().filter(pk=article_id).first()
        if article is None:
            raise Http404("Статьи нет")
        manager = access.can_manage(user)
        if article.state == Article.State.TRASH:
            if not manager:
                raise access.ArticleGone
        else:
            if not manager:
                raise PermissionDenied
            raise ArticleError("not_in_trash")
        article.state = article.state_before_trash or Article.State.DRAFT
        article.state_before_trash = ""
        article.deleted_at = None
        article.deleted_by = None
        article.save(update_fields=["state", "state_before_trash", "deleted_at", "deleted_by"])
        vectors.refresh([article.pk])
        audit.record("knowledge.article_restored", actor=user, object_type=OBJECT_TYPE, object_id=article.pk,
                     after={"number": article.pk, "title": article.title})
    return article


def _erase_files(paths, number: int) -> None:
    """Стирает файлы вложений с диска (после фиксации); отсутствующий файл — не ошибка: запись без имени файла."""
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            logger.warning("Статья %s: файл вложения на диске отсутствует", number)
        except OSError as exc:
            logger.warning("Статья %s: файл вложения не стёрт (%s)", number, type(exc).__name__)


def purge(article: Article, actor, by_term: bool = False) -> None:
    """Удаление навсегда одной транзакцией: комментарии ядра, вложения (строки и файлы), версии, связи, статья.

    Права не проверяет (ручное удаление проверяет представление, срок — `retention`). Файлы стираются с диска после
    фиксации; строки тегов не удаляются; журнал `knowledge.article_purged` (`actor` пуст у срока).
    """
    with transaction.atomic():
        current = Article.objects.select_for_update().filter(pk=article.pk).first()
        # под замком: статью, которую успели вернуть из корзины, не удаляем (гонка с «Вернуть», R-5214-3)
        if current is None or current.state != Article.State.TRASH:
            return
        number, title = current.pk, current.title
        comments.delete_for(f"knowledge.article:{number}")
        attached = list(ArticleFile.objects.filter(article=current).select_related("file"))
        # пути считаются до удаления строк: они зависят от состояния проверки файла
        paths = [core_files.attachment_path(item.file) for item in attached]
        stored_ids = [item.file_id for item in attached]
        ArticleFile.objects.filter(article=current).delete()
        if stored_ids:
            StoredFile.objects.filter(pk__in=stored_ids).delete()
        current.delete()
        audit.record("knowledge.article_purged", actor=actor, object_type=OBJECT_TYPE, object_id=number,
                     before={"number": number, "title": title, "by_term": bool(by_term)})
        if paths:
            transaction.on_commit(lambda: _erase_files(paths, number))


# --- комментарии ------------------------------------------------------------------------------------------------

def add_comment(user, article_id: int, text: str) -> Comment:
    """Комментарий к опубликованной статье (черновик — `Http404`, корзина — `ArticleGone`); `CommentError` ядра
    пробрасывается; событие `knowledge.comment_added` после фиксации."""
    with transaction.atomic():
        article = Article.objects.select_for_update().filter(pk=article_id).first()
        if article is None:
            raise Http404("Статьи нет")
        if article.state == Article.State.TRASH:
            raise access.ArticleGone
        if article.state != Article.State.PUBLISHED:
            raise Http404("Статьи нет")
        comment = comments.add(user, f"knowledge.article:{article.pk}", text)
        events.publish("knowledge.comment_added", article_id=article.pk, comment_id=comment.pk, actor_id=user.pk)
    return comment


def delete_comment(user, comment_id: int) -> None:
    """Удаляет комментарий: автор или управляющий (иначе `PermissionDenied`); чужой — журнал `knowledge.comment_deleted`."""
    prefix = "knowledge.article:"
    found = Comment.objects.filter(pk=comment_id, object_ref__startswith=prefix).first()
    if found is None:
        raise Http404("Комментария нет")
    try:
        article_id = int(found.object_ref[len(prefix):])
    except ValueError:
        raise Http404("Комментария нет") from None
    with transaction.atomic():
        article = Article.objects.select_for_update().filter(pk=article_id).first()
        if article is None:
            raise Http404("Статьи нет")
        if article.state == Article.State.TRASH:
            raise access.ArticleGone
        comment = Comment.objects.select_for_update().filter(pk=comment_id).first()
        if comment is None:
            raise Http404("Комментария нет")
        own = comment.author_id == user.pk
        if not own and not access.can_manage(user):
            raise PermissionDenied
        comments.delete(comment)
        if not own:
            audit.record("knowledge.comment_deleted", actor=user, object_type=OBJECT_TYPE, object_id=article.pk,
                         before={"number": article.pk, "title": article.title})
