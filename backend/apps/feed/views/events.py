"""Ответ участника и списки ответов события, доступные только автору."""
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.core.models import User
from apps.feed.models import EventAnswer, Post
from apps.feed.services import events, page, visibility
from apps.feed.services.errors import FeedError
from apps.feed.texts import TEXTS


@login_required
@require_POST
@transaction.atomic
def answer(request, post_id):
    post = visibility.get_post(request.user, post_id)
    if post.kind != Post.Kind.EVENT or post.author_id == request.user.pk:
        raise PermissionDenied
    now = timezone.now()
    error = None
    value = request.POST.get("answer")
    if value in EventAnswer.Answer.values:
        try:
            events.answer(request.user, post_id, value, now=now)
        except FeedError as exc:
            error = exc
    if error is None and value in EventAnswer.Answer.values and request.headers.get("HX-Request") != "true":
        return redirect(f"/feed/{post.pk}/")
    return render(request, "feed/_event.html", {
        "post": post, "card": page._card_data([post], request.user)[post.pk],
        "event_now": now, "event_error": TEXTS[error.code] if error else None,
    })


@login_required
@require_GET
def answers(request, post_id):
    post = visibility.get_post(request.user, post_id)
    if post.kind != Post.Kind.EVENT or post.author_id != request.user.pk:
        raise PermissionDenied
    audience = visibility.audience(post) - {post.author_id}
    rows = dict(EventAnswer.objects.filter(post=post, user_id__in=audience).values_list("user_id", "answer"))
    groups = {"go": [], "no": [], "none": []}
    for user in User.objects.filter(pk__in=audience).order_by("full_name", "pk"):
        groups[rows.get(user.pk, "none")].append(user)
    return render(request, "feed/answers.html", {"groups": groups})
