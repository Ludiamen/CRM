"""Представления ленты: comments (срез 007)."""

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction
from django.http import Http404, HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST, require_http_methods

from apps.core.models import User, UserState
from apps.core.services import files, permissions
from apps.core.views.common import render_page
from apps.feed.models import FeedComment, FeedFile
from apps.feed.services import comments, likes, mentions, page, text, visibility
from apps.feed.services.errors import FeedError, PdnFound
from apps.feed.texts import TEXTS


def _link_staff(user):
    return bool({"staff.view", "accounts.manage"} & permissions.permissions_of(user))


def _people_for_comments(comments_list):
    ids = set()
    for comment in comments_list:
        ids.update(mentions.extract(comment.text))
    if not ids:
        return {}
    return dict(User.objects.filter(pk__in=ids, state=UserState.ACTIVE).values_list("pk", "full_name"))


def _comment_item(comment, people, link_staff, viewer_id, like_data, is_moderator=False):
    data = like_data.get(comment.pk, {"liked": False, "like_count": 0, "likers": []})
    return {
        "comment": comment,
        "body_html": text.render_plain(comment.text, people, link_staff),
        "photo_url": (files.photo_url(comment.author, 96)
                      if (link_staff or comment.author_id == viewer_id)
                      and getattr(comment.author, "photo", None) else None),
        "liked": data["liked"],
        "like_count": data["like_count"],
        "likers": data["likers"],
        "can_edit": comment.author_id == viewer_id,
        "can_delete": comment.author_id == viewer_id or is_moderator,
    }


def _comments_context(post, request):
    card = page._card_data([post], request.user)[post.pk]
    all_comments = comments.list_for(post)
    people = _people_for_comments(all_comments)
    link_staff = _link_staff(request.user)
    viewer_id = request.user.pk
    like_data = likes.comment_like_data([c.pk for c in all_comments], viewer_id)
    return {
        "post": post,
        "card": card._replace(comments=all_comments),
        "comments": [_comment_item(c, people, link_staff, viewer_id, like_data,
                                   visibility.viewer(request.user).moderator) for c in all_comments],
        "link_staff": link_staff,
    }


def _form_context(post, request, *, text="", error=None, found=()):
    errors = {}
    if error is not None:
        params = dict(error.params)
        if error.code == "too_long" and params.get("limit") == "4000":
            params["limit"] = "4000"
        errors[error.field or "text"] = {"code": error.code, "message": TEXTS[error.code].format(**params)}
    return {
        "post": post,
        "text": text,
        "errors": errors,
        "pdn_found": found,
        "link_staff": _link_staff(request.user),
    }


def _list_comments(request, post_id):
    post = visibility.get_post(request.user, post_id)
    return render(request, "feed/_comments.html", _comments_context(post, request))


def _add_comment(request, post_id):
    raw_text = request.POST.get("text", "")
    try:
        comment = comments.add(
            request.user,
            post_id,
            raw_text,
            files=request.POST.getlist("files"),
            pdn_confirmed=request.POST.get("pdn_confirmed", ""),
        )
    except Http404:
        raise
    except IntegrityError as exc:
        raise Http404 from exc
    except FeedError as exc:
        post = visibility.get_post(request.user, post_id)
        return render(request, "feed/_form_comment.html",
                      _form_context(post, request, text=raw_text, error=exc))
    except PdnFound as exc:
        post = visibility.get_post(request.user, post_id)
        return render(request, "feed/_form_comment.html",
                      _form_context(post, request, text=raw_text, found=exc.found))

    if request.headers.get("HX-Request") != "true":
        return redirect(f"/feed/{post_id}/#c{comment.pk}")

    post = visibility.get_post(request.user, post_id)
    comment = comments.enrich(comment)
    comment.author = request.user
    people = _people_for_comments([comment])
    link_staff = _link_staff(request.user)
    viewer_id = request.user.pk
    like_data = likes.comment_like_data([comment.pk], viewer_id)
    item = _comment_item(comment, people, link_staff, viewer_id, like_data)
    all_files = list(FeedFile.objects.filter(comment=comment).select_related("file").order_by("pk"))
    return render(request, "feed/_comment_response.html", {
        "post": post,
        "comment": comment,
        "body_html": item["body_html"],
        "photo_url": item["photo_url"],
        "link_staff": link_staff,
        "liked": item["liked"],
        "like_count": item["like_count"],
        "likers": item["likers"],
        "can_edit": item["can_edit"],
        "can_delete": item["can_delete"],
        "all_files": all_files,
    })


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def comments_view(request, post_id):
    if request.method == "POST":
        return _add_comment(request, post_id)
    return _list_comments(request, post_id)


def _comment_form_context(comment, post, request, *, text=None, error=None, found=()):
    if text is None:
        text = comment.text
    errors = {}
    if error is not None:
        params = dict(error.params)
        if error.code == "too_long" and params.get("limit") == "4000":
            params["limit"] = "4000"
        errors[error.field or "text"] = {"code": error.code, "message": TEXTS[error.code].format(**params)}
    attached = list(FeedFile.objects.filter(post=post, comment=comment).order_by("pk"))
    remove = request.POST.getlist("remove") if request.method == "POST" else []
    attached_ids = {str(file.pk) for file in attached}
    return {
        "post": post,
        "comment": comment,
        "text": text,
        "errors": errors,
        "pdn_found": found,
        "link_staff": _link_staff(request.user),
        "pdn_button": "Сохранить всё равно",
        "form_files": attached,
        "form_remove": remove,
        "form_extra_remove": [value for value in remove if value not in attached_ids],
        "form_new_files": request.POST.getlist("files") if request.method == "POST" else [],
    }


@login_required
@require_http_methods(["GET", "POST"])
@transaction.atomic
def edit_comment(request, comment_id):
    try:
        comment, feed_comment = comments._feed_comment_or_404(comment_id)
    except Http404:
        raise
    post = feed_comment.post
    if not visibility.can_see(request.user.pk, post.pk):
        raise Http404
    if not (request.user.pk == comment.author_id):
        return HttpResponseForbidden()

    if request.method == "GET":
        context = _comment_form_context(comment, post, request)
        return render_page(request, "feed/form_comment_edit.html", context)

    data = request.POST.copy()
    data["text"] = data.get("text", "").replace("\x00", "")
    error, found = None, ()
    try:
        comment = comments.edit(request.user, comment_id, data.get("text", ""),
                                files=data.getlist("files"), remove=data.getlist("remove"),
                                pdn_confirmed=data.get("pdn_confirmed", ""))
    except Http404:
        raise
    except PermissionDenied:
        return HttpResponseForbidden()
    except FeedError as exc:
        error = exc
    except PdnFound as exc:
        found = exc.found
    else:
        if request.headers.get("HX-Request") != "true":
            return redirect(f"/feed/{post.pk}/#c{comment.pk}")
        comment = comments.enrich(comment)
        people = _people_for_comments([comment])
        link_staff = _link_staff(request.user)
        like_data = likes.comment_like_data([comment.pk], request.user.pk)
        item = _comment_item(comment, people, link_staff, request.user.pk, like_data)
        all_files = list(FeedFile.objects.filter(comment=comment).select_related("file").order_by("pk"))
        return render(request, "feed/_comment.html", {
            "post": post, "comment": comment,
            "body_html": item["body_html"],
            "photo_url": item["photo_url"],
            "link_staff": link_staff,
            "liked": item["liked"],
            "like_count": item["like_count"],
            "likers": item["likers"],
            "can_edit": True,
            "can_delete": True,
            "all_files": all_files,
        })
    context = _comment_form_context(comment, post, request, text=data.get("text"), error=error, found=found)
    if request.headers.get("HX-Request") == "true":
        response = render(request, "feed/_form_comment_edit.html", context)
        response["HX-Retarget"] = "#feed-comment-edit"
        response["HX-Reswap"] = "outerHTML"
        return response
    return render_page(request, "feed/form_comment_edit.html", context)


@login_required
@require_POST
@transaction.atomic
def delete_comment(request, comment_id):
    try:
        comment, feed_comment = comments._feed_comment_or_404(comment_id)
    except Http404:
        raise
    post_id = feed_comment.post_id
    try:
        comments.delete(request.user, comment_id)
    except Http404:
        raise
    except PermissionDenied:
        return HttpResponseForbidden()

    if request.headers.get("HX-Request") == "true":
        return render(request, "feed/_comment_delete_response.html", {"comment_id": comment_id})
    return redirect(f"/feed/{post_id}/")
