"""Правила уведомлений ленты: кто и какое уведомление получает (FR-630)."""

from typing import NamedTuple

from apps.core.extensions import Draft
from apps.core.models import User, UserState
from apps.feed.models import Post

# Приоритет плана (FR-630): «Нравится» — отдельное действие без конкуренции, в порядок не входит.
PRIORITY = (
    "feed.mention",
    "feed.invite",
    "feed.event_changed",
    "feed.important",
    "feed.for_you",
    "feed.comment",
)


class RuleEvent(NamedTuple):
    actor_id: int
    action: str
    post: Post
    comment: object | None = None
    audience: frozenset[int] = frozenset()
    commenters: frozenset[int] = frozenset()
    mentioned: frozenset[int] = frozenset()
    to_people: frozenset[int] = frozenset()
    event_changed: bool = False
    before: frozenset[int] = frozenset()
    liked_comment: object | None = None


def _active_ids(ids: frozenset[int]) -> frozenset[int]:
    if not ids:
        return frozenset()
    return frozenset(
        User.objects.filter(pk__in=ids, state=UserState.ACTIVE)
        .values_list("pk", flat=True)
    )


def _draft(uid: int, post: Post, object_ref: str, comment=None) -> Draft:
    url = f"/feed/{post.pk}/"
    if comment is not None:
        url = f"/feed/{post.pk}/#c{comment.pk}"
    return Draft(user_id=uid, text="", url=url, object_ref=object_ref)


def decide(event: RuleEvent) -> dict[int, tuple[str, Draft]]:
    """Определить вид уведомления для каждого получателя по приоритету."""
    candidates = event.audience - {event.actor_id}
    active = _active_ids(candidates)
    result: dict[int, tuple[str, Draft]] = {}
    object_ref = f"feed.post:{event.post.pk}"

    if event.action == "comment":
        for uid in active:
            if uid in event.mentioned:
                kind = "feed.mention"
            elif uid == event.post.author_id or uid in event.commenters:
                kind = "feed.comment"
            else:
                continue
            result[uid] = (kind, _draft(uid, event.post, object_ref, event.comment))
        return result

    if event.action == "like":
        # «Нравится» — отдельное действие без конкуренции; отметка комментария живёт своей ссылкой
        # «feed.post:<id>:c<cid>», чтобы не склеиваться с отметками записи и других комментариев (план).
        liked = event.liked_comment
        like_ref = object_ref if liked is None else f"{object_ref}:c{liked.pk}"
        for uid in active:
            result[uid] = ("feed.like", _draft(uid, event.post, like_ref, liked))
        return result

    if event.action == "publish":
        for uid in active:
            if uid in event.mentioned:
                kind = "feed.mention"
            elif event.post.kind == Post.Kind.EVENT:
                kind = "feed.invite"
            elif event.post.kind == Post.Kind.IMPORTANT:
                kind = "feed.important"
            elif uid in event.to_people:
                kind = "feed.for_you"
            else:
                continue
            result[uid] = (kind, _draft(uid, event.post, object_ref))
        return result

    if event.action == "edit":
        for uid in active:
            # Упомянутый новым маркером — «Вас упомянули» даже участнику события: упоминание
            # сильнее «Событие изменено» (приоритет плана, FR-630).
            if uid in event.mentioned:
                kind = "feed.mention"
            elif uid in event.before:
                if event.event_changed:
                    kind = "feed.event_changed"
                else:
                    continue
            elif event.post.kind == Post.Kind.EVENT:
                kind = "feed.invite"
            elif event.post.kind == Post.Kind.IMPORTANT:
                kind = "feed.important"
            elif uid in event.to_people:
                kind = "feed.for_you"
            else:
                continue
            result[uid] = (kind, _draft(uid, event.post, object_ref))
        return result

    return result
