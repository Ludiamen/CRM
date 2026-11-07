"""Сервис ленты: live (срез 007)."""

import asyncio
import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.apps import apps
from django.template.loader import render_to_string
from django.utils import timezone

from apps.core.models import User
from apps.core.services import files, permissions
from apps.feed.services import mentions, text, unread, visibility

logger = logging.getLogger("apps.feed.services.live")


# Действия, после которых у затронутых сотрудников может измениться число «Ленты».
_COUNT_ACTIONS = frozenset({"new", "delete", "post", "comment"})


_ROLES = ("reader", "author", "moderator")


def _classify_role(user_id: int, owner_id: int, moderator_ids: frozenset[int]) -> str:
    if user_id == owner_id:
        return "author"
    if user_id in moderator_ids:
        return "moderator"
    return "reader"


def _recipient_users(recipient_ids: frozenset[int]) -> dict[int, User]:
    return {
        user.pk: user
        for user in User.objects.filter(pk__in=sorted(recipient_ids)).select_related("photo")
    }


def _moderators_and_staff(recipient_ids: frozenset[int]) -> tuple[frozenset[int], frozenset[int]]:
    users = _recipient_users(recipient_ids)
    moderators = {uid for uid, user in users.items() if permissions.has_permission(user, "feed.moderate")}
    staff_viewers = {
        uid for uid, user in users.items()
        if permissions.has_any_permission(user, ("staff.view", "accounts.manage"))
    }
    return frozenset(moderators), frozenset(staff_viewers)


def _now():
    return timezone.now()


async def _send_to_groups(layer, groups, message):
    if groups:
        await asyncio.gather(*[layer.group_send(group, message) for group in groups])


def publish_event(post_id: int, action: str, *, comment_id: int | None = None,
                  recipients: frozenset[int] | None = None, owner_id: int | None = None) -> None:
    """Разослать кадр `feed.event` в личные группы видящих запись.

    Вызывается из `transaction.on_commit`, поэтому отправка выполняется сразу.
    Сбои рассылки журналируются, но не влияют на действие. Для удаления записи
    получатели передаются готовым множеством, потому что после фиксации
    адресатов в базе уже нет.
    """
    try:
        layer = get_channel_layer("publish")
        if layer is None:
            raise RuntimeError("слой каналов не настроен")

        # Для удаления записи или комментария не обращаемся к уже удалённым строкам.
        if action == "delete":
            audience = recipients if recipients is not None else frozenset()
            variants = _render_delete_variants(post_id, audience, owner_id)
            message = _build_message(post_id, action, owner_id, comment_id, audience, variants)
            async_to_sync(_send_to_groups)(
                layer, [f"feed.u.{uid}" for uid in audience], message
            )
            _push_counts(audience)
            return

        from apps.feed.models import Post

        post = Post.objects.get(pk=post_id)
        audience = recipients if recipients is not None else visibility.audience(post)
        moderator_ids, staff_viewer_ids = _moderators_and_staff(audience)
        users = _recipient_users(audience)

        if action == "new":
            variants = {}
        else:
            variants = _render_variants(
                post, action, comment_id, audience, moderator_ids, staff_viewer_ids, users, owner_id or post.author_id
            )
        message = _build_message(post_id, action, owner_id, comment_id, audience, variants, post)

        async_to_sync(_send_to_groups)(
            layer, [f"feed.u.{uid}" for uid in audience], message
        )

        if action in _COUNT_ACTIONS:
            _push_counts(audience)
    except Exception:
        logger.warning("Failed to publish feed.event for post %s action %s", post_id, action, exc_info=True)


def _build_message(post_id: int, action: str, owner_id: int | None, comment_id: int | None,
                   audience: frozenset[int], variants: dict[str, str], post=None) -> dict:
    moderator_ids, staff_viewer_ids = _moderators_and_staff(audience)
    message = {
        "type": "feed.event",
        "post": post_id,
        "action": action,
        "owner": owner_id,
        "comment": comment_id,
        "moderators": sorted(moderator_ids),
        "staff_viewers": sorted(staff_viewer_ids),
        "variants": variants,
    }
    if action == "new" and post is not None:
        message["meta"] = {
            "kind": post.kind,
            "author": post.author_id,
            "mentioned": sorted(mentions.extract(post.text)),
            "published_at": post.published_at.isoformat(),
        }
    return message


def _classes(audience: frozenset[int], owner_id: int, moderator_ids: frozenset[int],
             staff_viewer_ids: frozenset[int], users: dict[int, User]) -> set[tuple[str, bool]]:
    classes = set()
    for uid in audience:
        role = _classify_role(uid, owner_id, moderator_ids)
        link_staff = uid in staff_viewer_ids
        classes.add((role, link_staff))
    return classes


def _render_variants(post, action: str, comment_id: int | None, audience: frozenset[int],
                     moderator_ids: frozenset[int], staff_viewer_ids: frozenset[int],
                     users: dict[int, User], owner_id: int) -> dict[str, str]:
    classes = _classes(audience, owner_id, moderator_ids, staff_viewer_ids, users)
    variants = {}
    opened = _now()
    event_now = opened

    # Данные карточки без личного состояния читателя.
    from apps.feed.services import page
    dummy = User(pk=0)
    card = page._card_data([post], dummy).get(post.pk)
    if card is None:
        card = page.Card(
            post=post, recipients=page.recipients.line(post), files=[], likes=[], like_count=0,
            comments=[], comment_count=0, liked=False, read=False, answer=None, read_count=0,
            read_total=0, answer_counts={},
        )

    people = _people_for_post(post, card)

    for role, link_staff in classes:
        variants[f"{role}:{int(link_staff)}"] = _render_variant(
            post, action, comment_id, card, people, role, link_staff, opened, event_now
        )
    return variants


def _people_for_post(post, card) -> dict[int, str]:
    ids = set(mentions.extract(post.text))
    for comment in card.comments:
        ids.update(mentions.extract(comment.text))
    if not ids:
        return {}
    return dict(User.objects.filter(pk__in=ids, state="active").values_list("pk", "full_name"))


def _people_for_comment(comment) -> dict[int, str]:
    ids = set(mentions.extract(comment.text))
    if not ids:
        return {}
    return dict(User.objects.filter(pk__in=ids, state="active").values_list("pk", "full_name"))


def _render_variant(post, action: str, comment_id: int | None, card, people: dict[int, str],
                    role: str, link_staff: bool, opened, event_now) -> str:
    is_author = role == "author"
    is_moderator = role == "moderator"
    is_author_or_moderator = is_author or is_moderator

    if action == "comment_delete":
        return render_to_string("feed/_frame_delete_comment.html", {"comment_id": comment_id})

    if action == "delete":
        return render_to_string("feed/_frame_delete_post.html", {"post_id": post.pk})

    if action in ("comment", "comment_edit", "comment_like"):
        from apps.core.models import Comment
        from apps.feed.services import likes

        comment = Comment.objects.select_related("author", "author__photo").get(pk=comment_id)
        body_html = text.render_plain(comment.text, _people_for_comment(comment), link_staff)
        like_data = likes.comment_like_data([comment.pk], 0)[comment.pk]
        photo_url = None
        if link_staff or (is_author and getattr(comment.author, "photo", None)):
            photo_url = files.photo_url(comment.author, 96)
        context = {
            "comment": comment,
            "body_html": body_html,
            "photo_url": photo_url,
            "link_staff": link_staff,
            "can_edit": is_author,
            "can_delete": is_author_or_moderator,
            "like_count": like_data["like_count"],
            "likers": like_data["likers"],
            "post": post,
            # файлы комментария — из карточки записи (запрос `_card_data` уже выбран пакетно)
            "all_files": [file for file in card.files if file.comment_id == comment.pk],
        }
        if action == "comment_like":
            return render_to_string("feed/_frame_likers.html", context)
        inner = render_to_string("feed/_frame_comment_content.html", context)
        if action == "comment":
            return render_to_string("feed/_frame_comment_beforeend.html", {"post": post, "comment": comment, "inner": inner})
        # comment_edit / comment_like
        return render_to_string("feed/_frame_comment_outer.html", {"comment": comment, "inner": inner})

    body_html = text.render_plain(post.text, people, link_staff)
    context = {
        "post": post,
        "card": card,
        "like_count": card.like_count,
        "likers": card.likes,
        "body_html": body_html,
        "link_staff": link_staff,
        "is_author": is_author,
        "is_moderator": is_moderator,
        "is_author_or_moderator": is_author_or_moderator,
        "opened": opened,
        "event_now": event_now,
    }

    if action == "like":
        return render_to_string("feed/_frame_likers.html", context)
    if action == "read":
        return render_to_string("feed/_frame_important.html", context)
    if action == "answer":
        return render_to_string("feed/_frame_event.html", context)
    # "post" и прочие обновления записи
    return render_to_string("feed/_frame_post_parts.html", context)


def _render_delete_variants(post_id: int, audience: frozenset[int], owner_id: int | None) -> dict[str, str]:
    html = render_to_string("feed/_frame_delete_post.html", {"post_id": post_id})
    if not audience:
        return {}
    users = _recipient_users(audience)
    moderator_ids, staff_viewer_ids = _moderators_and_staff(audience)
    variants = {}
    for role, link_staff in _classes(audience, owner_id or 0, moderator_ids, staff_viewer_ids, users):
        variants[f"{role}:{int(link_staff)}"] = html
    return variants


def push_counts(user_ids: frozenset[int] | set[int]) -> None:
    """Вторая рассылка: новое число «Ленты» затронутым сотрудникам."""
    if not apps.is_installed("apps.notify"):
        return
    from apps.notify.services import live as notify_live

    user_ids = list(user_ids)
    if not user_ids:
        return
    try:
        counts = unread.counts(user_ids)
        layer = get_channel_layer("publish")
        if layer is None:
            raise RuntimeError("слой каналов не настроен")

        async def send():
            results = await asyncio.gather(
                *[
                    layer.group_send(
                        notify_live.group(uid),
                        {
                            "type": "notify.html",
                            "html": render_to_string(
                                "feed/_badge.html", {"count": counts.get(uid, 0), "badge_oob": True}
                            ),
                        },
                    )
                    for uid in user_ids
                ],
                return_exceptions=True,
            )
            for exc in results:
                if isinstance(exc, BaseException):
                    logger.warning("Failed to push feed count to notify group", exc_info=exc)

        async_to_sync(send)()
    except Exception:
        logger.warning("Failed to push feed counts to notify groups", exc_info=True)


_push_counts = push_counts
