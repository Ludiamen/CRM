"""Сервис ленты: comments (срез 007)."""

import pathlib

from django.apps import apps
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404
from django.utils import timezone

from apps.core import events
from apps.core.extensions import Draft
from apps.core.models import Comment, StoredFile
from apps.core.services import audit
from apps.core.services import comments as core_comments
from apps.core.services import files as core_files
from apps.feed.models import FeedComment, FeedFile, Post
from apps.core.widgets import MOSCOW
from apps.feed.services import live as _live, mentions, pdn, search, text, visibility
from apps.feed.services import files as feed_files
from apps.feed.services.errors import FeedError, PdnFound
from apps.feed.services.notify_rules import RuleEvent, decide
from apps.feed.services.visibility import audience, can_see


def post_for_comment(user, post_id: int) -> Post:
    """Проверка видимости записи перед вставкой комментария; точка подмены §5.8."""
    try:
        post = Post.objects.get(pk=post_id)
    except Post.DoesNotExist as exc:
        raise Http404 from exc
    if not can_see(user.pk, post.pk):
        raise Http404
    return post


def _get(data, name, default=""):
    if hasattr(data, "get"):
        return data.get(name, default)
    return default


def _int_ids(values):
    """Номера из значений формы."""
    if values is None:
        return []
    if hasattr(values, "getlist"):
        values = values.getlist("files") or values.getlist("remove") or []
    if isinstance(values, (str, bytes)):
        values = [values]
    ids = []
    for value in values:
        text = str(value).strip()
        if text.isdigit():
            ids.append(int(text))
    return ids


def _file_inputs(data):
    """Разобрать списки files/remove с учётом QueryDict."""
    files, remove = [], []
    if hasattr(data, "getlist"):
        files = data.getlist("files") if "files" in data else []
        remove = data.getlist("remove") if "remove" in data else []
    else:
        files = data.get("files") if isinstance(data.get("files"), (list, tuple)) else []
        remove = data.get("remove") if isinstance(data.get("remove"), (list, tuple)) else []
    return list(dict.fromkeys(_int_ids(files))), list(dict.fromkeys(_int_ids(remove)))


def _notify_text(kind_code: str, post: Post, comment: Comment) -> str:
    """Тексты уведомлений комментария по шаблонам плана (CONTRACT-007, 7.2); весь текст — не длиннее 300 (К26)."""
    author_name = comment.author.full_name
    if kind_code == "feed.comment":
        snippet = text.snippet(post.text, 100)
        return text.snippet(f"{author_name} прокомментировал(а) запись «{snippet}»", 300)
    if kind_code == "feed.mention":
        snippet = text.snippet(comment.text, 100)
        return text.snippet(f"{author_name} упомянул(а) вас: «{snippet}»", 300)
    return ""


def add(user, post_id: int, text: str, *, files=(), pdn_confirmed=False, now=None) -> Comment:
    """Добавить комментарий к записи ленты: ядро, FeedComment, упоминания, уведомления — в одной транзакции."""
    text = str(text).replace("\x00", "")
    stripped = text.strip()
    if not stripped:
        raise FeedError("empty_text", "text")
    if len(stripped) > 4000:
        raise FeedError("too_long", "text", {"limit": "4000"})

    found = pdn.find_plain(stripped)
    if found and str(pdn_confirmed) not in ("1", "true", "True"):
        raise PdnFound(found)

    object_ref = f"feed.post:{post_id}"

    with transaction.atomic():
        post = post_for_comment(user, post_id)
        core_comment = core_comments.add(user, object_ref, stripped)
        core_comment.author = user
        feed_comment = FeedComment.objects.create(comment=core_comment, post=post)
        mentioned = mentions.sync(post, stripped)
        search.vectors(comment_ids=[core_comment.pk])
        feed_files.bind(user, files, post=post, comment=core_comment)

        current_audience = audience(post)
        commenters = set(
            Comment.objects.filter(object_ref=object_ref)
            .exclude(author_id=user.pk)
            .values_list("author_id", flat=True)
        )
        decisions = decide(
            RuleEvent(
                actor_id=user.pk,
                action="comment",
                post=post,
                comment=core_comment,
                audience=frozenset(current_audience),
                commenters=frozenset(commenters),
                mentioned=frozenset(mentioned),
            )
        )
        if apps.is_installed("apps.notify"):
            from apps.notify.services import dispatch

            for uid, (kind_code, _) in decisions.items():
                dispatch.create(
                    kind_code,
                    [
                        Draft(
                            user_id=uid,
                            text=_notify_text(kind_code, post, core_comment),
                            url=f"/feed/{post.pk}/#c{core_comment.pk}",
                            object_ref=object_ref,
                        )
                    ],
                )

        from apps.feed.services import live

        transaction.on_commit(
            lambda: live.publish_event(
                post.pk, "comment", comment_id=core_comment.pk, owner_id=user.pk
            )
        )
        events.publish(
            "object.viewed",
            object_ref=f"{object_ref}:c{core_comment.pk}",
            user_id=user.pk,
        )

    return core_comment


def list_for(post: Post):
    """Все комментарии записи, старые первыми, с данными ленты."""
    result = list(
        Comment.objects.filter(object_ref=f"feed.post:{post.pk}")
        .select_related("author", "author__photo")
        .order_by("created_at", "id")
    )
    edited = dict(FeedComment.objects.filter(post=post).values_list("comment_id", "edited_at"))
    for comment in result:
        comment.edited_at = edited.get(comment.pk)
    return result


def enrich(comment: Comment):
    """Дополнить объект комментария данными FeedComment, если есть."""
    try:
        feed_comment = FeedComment.objects.select_related("post").get(comment=comment)
    except FeedComment.DoesNotExist:
        feed_comment = None
    comment.feed_comment = feed_comment
    comment.edited_at = feed_comment.edited_at if feed_comment else None
    return comment


def _feed_comment_or_404(comment_id: int) -> tuple[Comment, FeedComment]:
    """Комментарий ленты по номеру; иначе Http404."""
    try:
        comment = Comment.objects.get(pk=comment_id)
    except Comment.DoesNotExist as exc:
        raise Http404 from exc
    if not comment.object_ref.startswith("feed.post:"):
        raise Http404
    try:
        feed_comment = FeedComment.objects.select_related("post").get(comment=comment)
    except FeedComment.DoesNotExist as exc:
        raise Http404 from exc
    return comment, feed_comment


def _erase_paths(paths) -> None:
    """Стирает файлы с диска после фиксации; отсутствующий файл — не ошибка."""
    for path in paths:
        try:
            path.unlink()
        except FileNotFoundError:
            pass


@transaction.atomic
def edit(user, comment_id: int, text: str, *, files=(), remove=(), pdn_confirmed=False, now=None) -> Comment:
    """Править комментарий: ядро, edited_at, вектор, новые упоминания, файлы remove."""
    comment, feed_comment = _feed_comment_or_404(comment_id)
    post = feed_comment.post
    if not can_see(user.pk, post.pk):
        raise Http404
    if not (user.pk == comment.author_id):
        raise PermissionDenied

    try:
        Post.objects.select_for_update().get(pk=post.pk)
    except Post.DoesNotExist as exc:
        raise Http404 from exc
    comment, feed_comment = _feed_comment_or_404(comment_id)
    text = str(text).replace("\x00", "")
    stripped = text.strip()
    if not stripped:
        raise FeedError("empty_text", "text")
    if len(stripped) > 4000:
        raise FeedError("too_long", "text", {"limit": "4000"})

    found = pdn.find_plain(stripped)
    if found and str(pdn_confirmed) not in ("1", "true", "True"):
        raise PdnFound(found)

    file_ids, remove_ids = _file_inputs({"files": list(files), "remove": list(remove)})
    old_text = comment.text

    # Сбор путей и id удаляемых файлов до изменения строк.
    paths: list[pathlib.Path] = []
    stored_ids: list[str] = []
    current_files = {
        ff.pk: ff
        for ff in FeedFile.objects.filter(comment=comment, post=post).select_related("file")
    }
    for rid in remove_ids:
        if rid not in current_files:
            raise FeedError("file_missing", "files")

    with transaction.atomic():
        for rid in remove_ids:
            feed_file = current_files[rid]
            paths.append(core_files.attachment_path(feed_file.file))
            stored_ids.append(str(feed_file.file_id))
            if feed_file.thumb:
                paths.append(pathlib.Path(settings.PROTECTED_ROOT) / feed_file.thumb)
            feed_file.delete()
        if stored_ids:
            StoredFile.objects.filter(pk__in=stored_ids).delete()
        # Привязка новых файлов условным UPDATE с проверкой числа строк и пределом 3.
        feed_files.bind(user, file_ids, post=post, comment=comment)

        core_comment = core_comments.update(comment, stripped)
        FeedComment.objects.filter(pk=feed_comment.pk).update(
            edited_at=timezone.now() if now is None else now
        )
        mentions.sync(post, stripped, old_text=old_text)
        search.vectors(comment_ids=[core_comment.pk])

        transaction.on_commit(
            lambda: _live.publish_event(
                post.pk, "comment_edit", comment_id=comment.pk, owner_id=user.pk
            )
        )

        if paths:
            transaction.on_commit(lambda: _erase_paths(paths))

    return comment


@transaction.atomic
def delete(user, comment_id: int) -> None:
    """Удалить комментарий: файлы до delete, аудит модератора чужого, диск после фиксации."""
    comment, feed_comment = _feed_comment_or_404(comment_id)
    post = feed_comment.post
    if not can_see(user.pk, post.pk):
        raise Http404
    if not (user.pk == comment.author_id or visibility.viewer(user).moderator):
        raise PermissionDenied

    try:
        Post.objects.select_for_update().get(pk=post.pk)
    except Post.DoesNotExist as exc:
        raise Http404 from exc
    comment, feed_comment = _feed_comment_or_404(comment_id)

    is_moderator = user.pk != comment.author_id and visibility.viewer(user).moderator
    created_at = comment.created_at
    author_full_name = comment.author.full_name

    paths: list[pathlib.Path] = []
    stored_ids: list[str] = []
    for feed_file in FeedFile.objects.filter(comment=comment).select_related("file"):
        paths.append(core_files.attachment_path(feed_file.file))
        stored_ids.append(str(feed_file.file_id))
        if feed_file.thumb:
            paths.append(pathlib.Path(settings.PROTECTED_ROOT) / feed_file.thumb)

    with transaction.atomic():
        transaction.on_commit(
            lambda: _live.publish_event(
                post.pk, "comment_delete", comment_id=comment_id, owner_id=comment.author_id
            )
        )
        core_comments.delete(comment)
        if stored_ids:
            StoredFile.objects.filter(pk__in=stored_ids).delete()
        if is_moderator:
            audit.record(
                "feed.comment_deleted",
                actor=user,
                object_type="feed.comment",
                object_id=comment_id,
                before={
                    "author": author_full_name,
                    "created_at": created_at.astimezone(MOSCOW).strftime("%d.%m.%Y %H:%M"),
                    "post": post.pk,
                },
            )
        if paths:
            transaction.on_commit(lambda: _erase_paths(paths))
