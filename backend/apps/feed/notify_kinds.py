"""Виды уведомлений ленты (срез 007)."""

import re
from datetime import datetime

from apps.core.extensions import NotificationKind
from apps.feed.services import text


# Строгие формы ссылки записи и комментария: feed.post:<id> и feed.post:<id>:c<cid> (PLAN-007, «Перед письмом и сводкой»).
_OBJECT_REF = re.compile(r"feed\.post:(\d+)(?::c(\d+))?")
# Номер за пределами bigint не доходит до базы: длина — до int() (сверх 4300 знаков int() бросает
# ValueError и сорвал бы отправку письма), значение — до запроса (иначе ошибка СУБД).
_MAX_DIGITS = 19
_MAX_ID = 2**63 - 1


def _ref_parts(object_ref: str) -> tuple[int, int | None] | None:
    """Строго разобрать ссылку: (номер записи, номер комментария или None); вне форм и диапазона — None."""
    if not isinstance(object_ref, str):
        return None
    match = _OBJECT_REF.fullmatch(object_ref)
    if match is None:
        return None
    post_digits, comment_digits = match.group(1), match.group(2)
    if len(post_digits) > _MAX_DIGITS:
        return None
    if comment_digits is not None and len(comment_digits) > _MAX_DIGITS:
        return None
    post_id = int(post_digits)
    comment_id = int(comment_digits) if comment_digits is not None else None
    if post_id > _MAX_ID or (comment_id is not None and comment_id > _MAX_ID):
        return None
    return post_id, comment_id


def still_relevant(user_id: int, object_ref: str) -> bool:
    """FR-630, FR-632: письмо и сводка идут, только пока запись (и её комментарий) живы и видны получателю."""
    from apps.feed.models import FeedComment
    from apps.feed.services import visibility

    parts = _ref_parts(object_ref)
    if parts is None:
        return False
    post_id, comment_id = parts
    if not visibility.can_see(user_id, post_id):
        return False
    if comment_id is None:
        return True
    return FeedComment.objects.filter(comment_id=comment_id, post_id=post_id).exists()


def comment_coalesce_text(user_id: int, object_ref: str, since: datetime) -> str:
    """Текст склейки «Новый комментарий»: N комментариев других после `since` плюс один (FR-629)."""
    from apps.feed.models import FeedComment, Post

    parts = _ref_parts(object_ref)
    if parts is None or parts[1] is not None:
        return ""
    post = Post.objects.filter(pk=parts[0]).first()
    if post is None:
        return ""
    others = FeedComment.objects.filter(post_id=post.pk).exclude(comment__author_id=user_id)
    count = others.filter(comment__created_at__gt=since).count() + 1
    snippet = text.snippet(post.text, 100)
    if count == 1:
        latest = others.select_related("comment__author").order_by("-comment__created_at").first()
        if latest is None:
            return ""
        ordinary = f"{latest.comment.author.full_name} прокомментировал(а) запись «{snippet}»"
        return text.snippet(ordinary, 300)
    return text.snippet(f"Новых комментариев: {count} к записи «{snippet}»", 300)


def like_coalesce_text(user_id: int, object_ref: str, since: datetime) -> str:
    """Текст склейки «Нравится»: последний отметивший и отметившие после `since` (FR-629)."""
    from apps.feed.models import CommentLike, FeedComment, PostLike, Post

    parts = _ref_parts(object_ref)
    if parts is None:
        return ""
    post_id, comment_id = parts
    if comment_id is None:
        post = Post.objects.filter(pk=post_id).first()
        if post is None:
            return ""
        marks = PostLike.objects.filter(post_id=post.pk).exclude(user_id=user_id)
        source = post.text
    else:
        link = FeedComment.objects.filter(comment_id=comment_id, post_id=post_id).first()
        if link is None:
            return ""
        marks = CommentLike.objects.filter(comment_id=comment_id).exclude(user_id=user_id)
        source = link.comment.text
    latest = marks.select_related("user").order_by("-created_at").first()
    if latest is None:
        return ""
    extra = marks.filter(created_at__gt=since).count()
    snippet = text.snippet(source, 100)
    if extra:
        return text.snippet(f"Нравится {latest.user.full_name} (и ещё {extra}): «{snippet}»", 300)
    return text.snippet(f"Нравится {latest.user.full_name}: «{snippet}»", 300)


def kinds() -> list[NotificationKind]:
    return [
        NotificationKind(
            code="feed.for_you",
            title="Запись для вас",
            module="Лента",
            still_relevant=still_relevant,
            order=70,
            default_channels=("portal", "email"),
            external_text="Новая запись в ленте для вас",
        ),
        NotificationKind(
            code="feed.mention",
            title="Вас упомянули",
            module="Лента",
            still_relevant=still_relevant,
            order=71,
            default_channels=("portal", "email"),
            external_text="Вас упомянули в ленте",
        ),
        NotificationKind(
            code="feed.comment",
            title="Новый комментарий",
            module="Лента",
            still_relevant=still_relevant,
            order=72,
            coalesce=True,
            default_channels=("portal", "email"),
            external_text="Новый комментарий в ленте",
            coalesce_text=comment_coalesce_text,
        ),
        NotificationKind(
            code="feed.important",
            title="Важная запись",
            module="Лента",
            still_relevant=still_relevant,
            order=73,
            default_channels=("portal", "email"),
            external_text="Новая важная запись в ленте",
        ),
        NotificationKind(
            code="feed.invite",
            title="Приглашение на событие",
            module="Лента",
            still_relevant=still_relevant,
            order=74,
            default_channels=("portal", "email"),
            external_text="Приглашение на событие в ленте",
        ),
        NotificationKind(
            code="feed.event_changed",
            title="Событие изменено",
            module="Лента",
            still_relevant=still_relevant,
            order=75,
            default_channels=("portal", "email"),
            external_text="Событие в ленте изменено",
        ),
        NotificationKind(
            code="feed.event_reminder",
            title="Напоминание о событии",
            module="Лента",
            still_relevant=still_relevant,
            order=76,
            default_channels=("portal", "email"),
            external_text="Скоро событие в ленте",
        ),
        NotificationKind(
            code="feed.like",
            title="Нравится",
            module="Лента",
            still_relevant=still_relevant,
            order=77,
            default_channels=("portal",),
            channels=("portal",),
            coalesce=True,
            coalesce_text=like_coalesce_text,
            external_text="",
        ),
    ]
