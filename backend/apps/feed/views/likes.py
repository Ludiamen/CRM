"""Представления ленты: likes (срез 007)."""

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.core.models import Comment, User
from apps.core.services import permissions
from apps.feed.models import CommentLike, FeedComment, PostLike
from apps.feed.services import likes, visibility


def _link_staff(user):
    return bool({"staff.view", "accounts.manage"} & permissions.permissions_of(user))


def _post_likers(post, limit=None):
    qs = PostLike.objects.filter(post=post).order_by("-created_at", "-id").select_related("user")
    if limit:
        qs = qs[:limit]
    return [like.user for like in qs]


def _comment_likers(comment, limit=None):
    qs = CommentLike.objects.filter(comment=comment).order_by("-created_at", "-id").select_related("user")
    if limit:
        qs = qs[:limit]
    return [like.user for like in qs]


def _like_context(post, user, comment=None):
    if comment:
        liked = likes.find_mark("comment", comment.pk, user.pk)
        liker_users = _comment_likers(comment, limit=2)
        like_count = CommentLike.objects.filter(comment=comment).count()
    else:
        liked = likes.find_mark("post", post.pk, user.pk)
        liker_users = _post_likers(post, limit=2)
        like_count = PostLike.objects.filter(post=post).count()
    return {
        "post": post,
        "comment": comment,
        "liked": liked,
        "likers": liker_users,
        "like_count": like_count,
        "link_staff": _link_staff(user),
    }


def _comment_or_404(comment_id: int) -> Comment:
    comment = get_object_or_404(Comment, pk=comment_id)
    if not comment.object_ref.startswith("feed.post:"):
        raise Http404
    return comment


@login_required
@require_POST
@transaction.atomic
def toggle_post_like(request, post_id):
    post = visibility.get_post(request.user, post_id)
    likes.toggle_post(request.user, post_id)
    if request.headers.get("HX-Request") == "true":
        return render(request, "feed/_likes.html", _like_context(post, request.user))
    return redirect(f"/feed/{post.pk}/")


@login_required
@require_POST
@transaction.atomic
def toggle_comment_like(request, comment_id):
    comment = _comment_or_404(comment_id)
    feed_comment = FeedComment.objects.get(comment=comment)
    post = visibility.get_post(request.user, feed_comment.post_id)
    likes.toggle_comment(request.user, comment_id)
    if request.headers.get("HX-Request") == "true":
        return render(
            request,
            "feed/_likes.html",
            _like_context(post, request.user, comment=comment),
        )
    return redirect(f"/feed/{post.pk}/")


@login_required
@require_GET
def post_likers(request, post_id):
    post = visibility.get_post(request.user, post_id)
    return render(
        request,
        "feed/_likers.html",
        {"likers": _post_likers(post), "kind": "post"},
    )


@login_required
@require_GET
def comment_likers(request, comment_id):
    comment = _comment_or_404(comment_id)
    feed_comment = FeedComment.objects.get(comment=comment)
    visibility.get_post(request.user, feed_comment.post_id)
    return render(
        request,
        "feed/_likers.html",
        {"likers": _comment_likers(comment), "kind": "comment"},
    )
