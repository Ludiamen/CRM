"""Сервис ленты: likes (срез 007)."""

from dataclasses import replace

from django.apps import apps
from django.db import IntegrityError, transaction
from django.http import Http404
from django.utils import timezone

from apps.core.models import Comment
from apps.feed.models import CommentLike, FeedComment, Post, PostLike
from apps.feed.services import text, visibility


def comment_like_data(comment_ids: list[int], viewer_id: int) -> dict[int, dict]:
    """Like-данные для списка комментариев: count, liked, последние 2 отметивших."""
    result = {cid: {"liked": False, "like_count": 0, "likers": []} for cid in comment_ids}
    if not comment_ids:
        return result
    likes = (
        CommentLike.objects.filter(comment_id__in=comment_ids)
        .order_by("-created_at", "-id")
        .select_related("user")
    )
    for like in likes:
        cid = like.comment_id
        if len(result[cid]["likers"]) < 2:
            result[cid]["likers"].append(like.user)
        result[cid]["like_count"] += 1
        if like.user_id == viewer_id:
            result[cid]["liked"] = True
    return result


def find_mark(kind: str, target_id: int, user_id: int) -> bool:
    """Есть ли отметка у пользователя; точка подмены §5.8."""
    if kind == "post":
        return PostLike.objects.filter(post_id=target_id, user_id=user_id).exists()
    if kind == "comment":
        return CommentLike.objects.filter(comment_id=target_id, user_id=user_id).exists()
    return False


def _comment_or_404(comment_id: int) -> Comment:
    """Только комментарии ленты; иначе 404."""
    try:
        comment = Comment.objects.get(pk=comment_id)
    except Comment.DoesNotExist as exc:
        raise Http404 from exc
    if not comment.object_ref.startswith("feed.post:"):
        raise Http404
    return comment


def _like_text(user, post: Post, comment: Comment | None) -> str:
    """Текст «Нравится»: ФИО отметившего и отрывок записи или комментария (CONTRACT-007, 7.2)."""
    source = comment.text if comment is not None else post.text
    snippet = text.snippet(source, 100)
    return text.snippet(f"Нравится {user.full_name}: «{snippet}»", 300)


def _notify(user, post: Post, comment: Comment | None):
    """Уведомления «Нравится» видящим записи (себе — нет)."""
    from apps.feed.services.notify_rules import RuleEvent, decide

    recipient_id = comment.author_id if comment is not None else post.author_id
    decisions = decide(
        RuleEvent(
            actor_id=user.pk,
            action="like",
            post=post,
            liked_comment=comment,
            audience=frozenset(visibility.audience(post)) & {recipient_id},
        )
    )
    if apps.is_installed("apps.notify") and decisions:
        from apps.notify.services import dispatch

        for kind_code, draft in decisions.values():
            dispatch.create(kind_code, [replace(draft, text=_like_text(user, post, comment))])


def _broadcast(user, post: Post, comment: Comment | None):
    """Живой кадр после фиксации транзакции."""
    from apps.feed.services import live

    action = "comment_like" if comment else "like"
    owner_id = comment.author_id if comment else post.author_id
    transaction.on_commit(
        lambda: live.publish_event(
            post.pk,
            action,
            comment_id=comment.pk if comment else None,
            owner_id=owner_id,
        )
    )


def toggle_post(user, post_id: int) -> bool:
    """Переключить отметку записи. True — отметка стоит после нажатия."""
    post = visibility.get_post(user, post_id)
    now = timezone.now()

    with transaction.atomic():
        created = False
        if find_mark("post", post_id, user.pk):
            PostLike.objects.filter(post=post, user=user).delete()
            result = False
        else:
            try:
                PostLike.objects.create(post=post, user=user, created_at=now)
                result = True
                created = True
            except IntegrityError:
                result = True
        if created:
            _notify(user, post, None)
        _broadcast(user, post, None)
    return result


def toggle_comment(user, comment_id: int) -> bool:
    """Переключить отметку комментария. True — отметка стоит после нажатия."""
    comment = _comment_or_404(comment_id)
    feed_comment = FeedComment.objects.get(comment=comment)
    post = visibility.get_post(user, feed_comment.post_id)
    now = timezone.now()

    with transaction.atomic():
        created = False
        if find_mark("comment", comment_id, user.pk):
            CommentLike.objects.filter(comment=comment, user=user).delete()
            result = False
        else:
            try:
                CommentLike.objects.create(
                    comment=comment, post=post, user=user, created_at=now
                )
                result = True
                created = True
            except IntegrityError:
                result = True
        if created:
            _notify(user, post, comment)
        _broadcast(user, post, comment)
    return result
