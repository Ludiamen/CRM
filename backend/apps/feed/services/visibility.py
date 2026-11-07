"""Единственная служба видимости записей ленты и прав действий."""

from typing import NamedTuple

from django.apps import apps
from django.http import Http404

from apps.core.models import User, UserState
from apps.core.services import permissions
from apps.feed.models import Post, Recipient


class Viewer(NamedTuple):
    id: int | None
    chain: frozenset[int]
    moderator: bool
    post_all: bool
    link_staff: bool


INACTIVE_STATES = ("blocked", "dismissed")


def _is_active(user) -> bool:
    return bool(getattr(user, "is_authenticated", False)) and getattr(user, "state", None) not in INACTIVE_STATES


def viewer(user) -> Viewer:
    """Права и цепочка сотрудника; кэш живёт только на переданном объекте пользователя."""
    cached = getattr(user, "_feed_viewer", None)
    if cached is not None:
        return cached

    user_id = getattr(user, "pk", None)
    chain = frozenset()
    if _is_active(user) and user_id is not None and apps.is_installed("apps.org"):
        from apps.org.services import structure

        chain = structure.unit_chain_ids(user)

    authenticated = bool(getattr(user, "is_authenticated", False))
    result = Viewer(
        id=user_id,
        chain=frozenset(chain),
        moderator=authenticated and permissions.has_permission(user, "feed.moderate"),
        post_all=authenticated and permissions.has_permission(user, "feed.post_all"),
        link_staff=authenticated and permissions.has_any_permission(user, ("staff.view", "accounts.manage")),
    )
    user._feed_viewer = result
    return result


def visible_posts(user):
    """Записи автора, общие записи и адресованные сотруднику или его узлам."""
    current = viewer(user)
    posts = Post.objects.all()
    if current.id is None or getattr(user, "state", None) in INACTIVE_STATES:
        return posts.none()

    recipient_table = Recipient._meta.db_table
    post_table = Post._meta.db_table
    return posts.extra(
        where=[
            f"({post_table}.author_id = %s OR {post_table}.to_all OR "
            f"EXISTS (SELECT TRUE FROM {recipient_table} AS r "
            f"WHERE r.post_id = {post_table}.id "
            "AND (r.unit_id = ANY(%s) OR r.user_id = %s)))"
        ],
        params=[current.id, list(current.chain), current.id],
    )


def get_post(user, post_id: int) -> Post:
    """Вернуть видимую запись; отсутствие и запрет неразличимы."""
    try:
        return visible_posts(user).get(pk=post_id)
    except Post.DoesNotExist as exc:
        raise Http404 from exc


def can_see(user_id: int, post_id: int) -> bool:
    """Проверить видимость тем же запросом, что и выдача ленты."""
    user = User.objects.filter(pk=user_id).first()
    return user is not None and visible_posts(user).filter(pk=post_id).exists()


def audience(post) -> frozenset[int]:
    """Собрать множество действующих адресатов одним проходом по каждому набору данных."""
    if post.to_all:
        return frozenset(User.objects.exclude(
            state__in=(UserState.BLOCKED, UserState.DISMISSED)
        ).values_list("pk", flat=True))

    recipient_rows = Recipient.objects.filter(post_id=post.pk).values_list("unit_id", "user_id")
    unit_ids: set[int] = set()
    user_ids: set[int] = {post.author_id}
    for unit_id, user_id in recipient_rows:
        if unit_id is not None:
            unit_ids.add(unit_id)
        if user_id is not None:
            user_ids.add(user_id)

    if unit_ids and apps.is_installed("apps.org"):
        from apps.org.services import structure

        user_ids.update(structure.subtree_member_ids(unit_ids))

    return frozenset(
        User.objects.extra(where=["core_user.id = ANY(%s)"], params=[sorted(user_ids)]).exclude(
            state__in=(UserState.BLOCKED, UserState.DISMISSED)
        ).values_list("pk", flat=True)
    )


def can_edit(user, post) -> bool:
    return _is_active(user) and user.pk == post.author_id


def can_delete(user, post) -> bool:
    if not _is_active(user):
        return False
    return user.pk == post.author_id or (viewer(user).moderator and can_see(user.pk, post.pk))


def can_comment(user, post) -> bool:
    return can_see(user.pk, post.pk)


def can_edit_comment(user, comment) -> bool:
    return _is_active(user) and user.pk == comment.author_id


def can_delete_comment(user, post, comment) -> bool:
    if can_edit_comment(user, comment):
        return True
    return _is_active(user) and viewer(user).moderator and can_see(user.pk, post.pk)
