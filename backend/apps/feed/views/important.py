"""Представления ленты: important (срез 007)."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.core.models import User
from apps.feed.services import important, page, visibility
from apps.feed.views import home


def _post_item(request, post, opened=None):
    """Контекст `item` для рендера `_post.html` одной записи после действия."""
    card_data = page._card_data([post], request.user)[post.pk]
    result = page.FeedPage(posts=[card_data], important=[], more_cursor=None,
                           opened=opened or timezone.now())
    context = home._context(request.user, page.parse_filter({}), result)
    return {"item": context["posts"][0], "opened": result.opened,
            "link_staff": context["link_staff"]}


@login_required
@require_POST
@transaction.atomic
def read(request, post_id):
    """Отметить важное прочитанным: 302 для обычного POST, фрагмент записи для HTMX."""
    post = visibility.get_post(request.user, post_id)
    try:
        important.mark_read(request.user, post_id)
    except PermissionDenied as exc:
        message = " ".join(exc.args) if exc.args else ""
        return HttpResponseForbidden(message)

    opened = page._moment(request.POST.get("opened")) or timezone.now()
    if request.headers.get("HX-Request") != "true":
        return redirect("/")
    return render(request, "feed/_post.html", _post_item(request, post, opened=opened))


@login_required
@require_GET
def reads(request, post_id):
    """Списки прочитавших и непрочитавших: автору и модератору-адресату."""
    post = visibility.get_post(request.user, post_id)
    if request.user.pk != post.author_id and not visibility.viewer(request.user).moderator:
        return HttpResponseForbidden()

    total_ids = visibility.audience(post) - {post.author_id}
    read_rows = list(post.read_marks.select_related("user").filter(
        user_id__in=total_ids, user__state__in=("active", "invited")).order_by("read_at"))
    read_ids = {row.user_id for row in read_rows}
    unread_ids = total_ids - read_ids
    unread_users = list(User.objects.filter(pk__in=unread_ids).order_by("full_name"))

    return render(request, "feed/reads.html", {
        "post": post,
        "read_users": [(row.user, row.read_at) for row in read_rows],
        "unread_users": unread_users,
    })
