"""Главная и курсорный фрагмент ленты (T-7213a)."""
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.utils import timezone
from django.views.decorators.http import require_GET

from apps.core.models import User, UserState
from apps.core.services import files, permissions
from apps.core.views.common import render_page
from apps.core.views.pages import collect_notices
from apps.core.widgets import PortalDateInput
from apps.feed.services import likes, mentions, page, text, unread, visibility


def _people(cards):
    """PLAN-007:405: имена только из маркеров видимой страницы одним запросом."""
    ids = set()
    for card in cards:
        ids.update(mentions.extract(card.post.text))
        for comment in card.comments:
            ids.update(mentions.extract(comment.text))
    if not ids:
        return {}
    return dict(User.objects.filter(pk__in=ids, state=UserState.ACTIVE).values_list("pk", "full_name"))


def _filter_values(flt):
    values = {"f": flt.f}
    if flt.author is not None:
        values["author"] = str(flt.author)
    if flt.date_from is not None:
        values["from"] = flt.date_from.isoformat()
    if flt.date_to is not None:
        values["to"] = flt.date_to.isoformat()
    return values


def _comment_items(card, people, link_staff, viewer_id, is_moderator, like_data):
    items = []
    for comment in card.comments:
        data = like_data[comment.pk]
        can_edit = viewer_id == comment.author_id
        can_delete = can_edit or is_moderator
        items.append(
            {
                "comment": comment,
                "body_html": text.render_plain(comment.text, people, link_staff),
                "photo_url": (
                    files.photo_url(comment.author, 96)
                    if link_staff or comment.author_id == viewer_id
                    and getattr(comment.author, "photo", None)
                    else None
                ),
                "liked": data["liked"],
                "like_count": data["like_count"],
                "likers": data["likers"],
                "can_edit": can_edit,
                "can_delete": can_delete,
            }
        )
    return items


def _cards(cards, people, link_staff, viewer_id, is_moderator, like_data):
    items = []
    for card in cards:
        can_edit = viewer_id == card.post.author_id
        can_delete = can_edit or is_moderator
        items.append({"post": card.post, "card": card,
                      "body_html": text.render_plain(card.post.text, people, link_staff),
                      "photo_url": (files.photo_url(card.post.author, 96)
                                    if link_staff or card.post.author_id == viewer_id else None),
                      "comments": _comment_items(card, people, link_staff, viewer_id, is_moderator, like_data),
                      "is_moderator": is_moderator,
                      "can_edit": can_edit,
                      "can_delete": can_delete})
    return items


def _context(user, flt, result, *, continuation=False):
    visible = result.posts if continuation else [*result.posts, *result.important]
    people = _people(visible)
    link_staff = bool({"staff.view", "accounts.manage"} & permissions.permissions_of(user))
    is_moderator = permissions.has_permission(user, "feed.moderate")
    values = _filter_values(flt)
    date_from = PortalDateInput().render("from", flt.date_from, attrs={"id": "id_feed_date_from"})
    date_to = PortalDateInput().render("to", flt.date_to, attrs={"id": "id_feed_date_to"})
    more_url = None
    if result.more_cursor:
        more_url = "/feed/more/?" + urlencode({**values, "before": result.more_cursor,
                                               "opened": result.opened.isoformat()})
    all_comment_ids = [c.pk for card in visible for c in card.comments]
    like_data = likes.comment_like_data(all_comment_ids, user.pk)
    return {"posts": _cards(result.posts, people, link_staff, user.pk, is_moderator, like_data),
            "important": [] if continuation else _cards(result.important, people, link_staff, user.pk, is_moderator, like_data),
            "link_staff": link_staff, "is_moderator": is_moderator, "flt": flt, "filter_values": values,
             "filter_options": (("all", "Все"), ("important", "Важные"), ("events", "События"),
                                ("mine", "Мои"), ("mentions", "Упоминают меня")),
             "date_from": date_from, "date_to": date_to,
             "filtered": flt != page.parse_filter({}), "more_url": more_url,
             "ws_url": "/ws/feed/?" + urlencode(values), "opened": result.opened,
             "event_now": timezone.now()}


@login_required
@require_GET
def body(request):
    flt = page.parse_filter(request.GET)
    result = page.build(request.user, flt)
    unread.mark_shown(request.user, [card.post.pk for card in [*result.posts, *result.important]])
    context = _context(request.user, flt, result)
    context["notices"] = collect_notices(request.user)
    from apps.feed.views.posts import form_context

    context.update(form_context(request.user))
    return render_page(request, "feed/body.html", context)


@login_required
@require_GET
def more(request):
    flt = page.parse_filter(request.GET)
    result = page.build(request.user, flt, before=request.GET.get("before"), opened=request.GET.get("opened"))
    is_hx = request.headers.get("HX-Request") == "true"
    if is_hx:
        unread.mark_shown(request.user, [card.post.pk for card in result.posts])
    context = _context(request.user, flt, result, continuation=True)
    context["badge_oob"] = is_hx
    if is_hx:
        context["count"] = unread.count(request.user)
    response = render(request, "feed/_lists.html", context)
    response["Vary"] = "HX-Request"
    return response


@login_required
@require_GET
def new(request):
    """Новые записи после since: вставка сверху ленты и обнуление плашки."""
    from apps.feed.models import Post, Recipient

    flt = page.parse_filter(request.GET)
    since = page._moment(request.GET.get("since"))
    if since is None:
        since = timezone.now()
    now = timezone.now()
    is_hx = request.headers.get("HX-Request") == "true"

    posts_qs = visibility.visible_posts(request.user).filter(published_at__gt=since)
    if flt.f == "important":
        posts_qs = posts_qs.filter(kind=Post.Kind.IMPORTANT)
    elif flt.f == "events":
        posts_qs = posts_qs.filter(kind=Post.Kind.EVENT)
    elif flt.f == "mine":
        posts_qs = posts_qs.filter(author_id=request.user.pk)
    elif flt.f == "mentions":
        posts_qs = posts_qs.filter(recipients__via=Recipient.Via.MENTION, recipients__user_id=request.user.pk)
    if flt.author is not None:
        posts_qs = posts_qs.filter(author_id=flt.author)
    start = page._boundary(flt.date_from)
    end = page._boundary(flt.date_to, following=True)
    if start is not None:
        posts_qs = posts_qs.filter(published_at__gte=start)
    if end is not None:
        posts_qs = posts_qs.filter(published_at__lt=end)

    important = []
    if page._block_enabled(flt):
        important = list(
            visibility.visible_posts(request.user)
            .filter(kind=Post.Kind.IMPORTANT, important_until__gt=now, published_at__gt=since)
            .exclude(author_id=request.user.pk)
            .exclude(read_marks__user_id=request.user.pk)
            .order_by("-published_at", "-pk")
        )

    important_ids = {post.pk for post in important}
    has_more = False
    if len(important) >= 50:
        has_more = len(important) > 50 or posts_qs.exclude(pk__in=important_ids).exists()
        important = important[:50]
        posts = []
    else:
        regular_limit = 50 - len(important)
        candidates = list(posts_qs.exclude(pk__in=important_ids).order_by("-published_at", "-pk")[:regular_limit + 1])
        has_more = len(candidates) > regular_limit
        posts = candidates[:regular_limit]

    cards = page._card_data([*posts, *important], request.user)
    post_items = [cards[post.pk] for post in posts]
    important_items = [cards[post.pk] for post in important]

    link_staff = bool({"staff.view", "accounts.manage"} & permissions.permissions_of(request.user))
    is_moderator = permissions.has_permission(request.user, "feed.moderate")
    all_comment_ids = [c.pk for card in post_items + important_items for c in card.comments]
    like_data = likes.comment_like_data(all_comment_ids, request.user.pk)
    people = _people([*post_items, *important_items])

    shown_ids = [card.post.pk for card in post_items + important_items]
    if is_hx:
        unread.mark_shown(request.user, shown_ids)

    newest = since
    for card in post_items + important_items:
        if card.post.published_at > newest:
            newest = card.post.published_at

    filter_values = _filter_values(flt)
    from urllib.parse import urlencode
    reload_url = "/?" + urlencode(filter_values)
    context = {
        "posts": _cards(post_items, people, link_staff, request.user.pk, is_moderator, like_data),
        "important": _cards(important_items, people, link_staff, request.user.pk, is_moderator, like_data),
        "opened": now,
        "link_staff": link_staff,
        "is_moderator": is_moderator,
        "flt": flt,
        "filter_values": filter_values,
        "has_more": has_more,
        "newest": newest,
        "reload_url": reload_url,
        "badge_oob": is_hx,
    }
    if is_hx:
        context["count"] = unread.count(request.user, now=now)

    response = render(request, "feed/_new_response.html", context)
    response["Vary"] = "HX-Request"
    return response
