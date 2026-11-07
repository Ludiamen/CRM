"""Карточка, адресаты и серверная форма публикации ленты."""
import json
from datetime import timedelta

from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_POST

from apps.core import events
from apps.core.models import Comment, User, UserState
from apps.core.services import permissions
from apps.core.views.common import render_page
from apps.core.widgets import MOSCOW, PortalDateInput, moscow_today
from apps.feed.models import FeedFile, Post, Recipient
from apps.feed.services import comments, likes, mentions, page, posts, recipients, text, unread, visibility
from apps.feed.services.errors import FeedError, PdnFound
from apps.feed.texts import TEXTS
from apps.feed.views import home


def form_context(user, data=None, *, error=None, found=(), oob=False):
    """Только данные формы: значения и подписи не определяют права публикации."""
    can_all = visibility.viewer(user).post_all
    values = {name: data.get(name, "") if data is not None else "" for name in (
        "text", "until", "event_title", "event_place", "event_start", "event_end")}
    values["kind"] = data.get("kind", "post") if data is not None else "post"
    if values["kind"] not in ("post", "important", "event"):
        values["kind"] = "post"
    values["term"] = data.get("term", "day") if data is not None else "day"
    refs = data.getlist("to") if data is not None else (["all"] if can_all else [])
    ids = {ref: int(ref[1:]) for ref in refs
           if ref[:1] in ("p", "u") and ref[1:].isascii() and ref[1:].isdigit()
           and 1 <= len(ref[1:]) <= 9}
    people = dict(User.objects.filter(pk__in=[pk for ref, pk in ids.items() if ref[0] == "p"])
                  .values_list("pk", "full_name"))
    units = {}
    unit_ids = [pk for ref, pk in ids.items() if ref[0] == "u"]
    if unit_ids and apps.is_installed("apps.org"):
        from apps.org.services import structure

        units = structure.unit_refs(unit_ids)
    pills = []
    for ref in dict.fromkeys(refs):
        pk = ids.get(ref)
        label = ("Всем" if ref == "all" else people.get(pk, ref) if ref.startswith("p")
                 else units[pk].name if pk in units else ref)
        pills.append({"value": ref, "label": label})
    try:
        mentioned_ids = mentions.extract(values["text"])
    except FeedError:
        mentioned_ids = []
    mentioned = list(User.objects.filter(pk__in=mentioned_ids, state=UserState.ACTIVE)
                     .values_list("pk", "full_name"))
    today = moscow_today()
    try:
        last_day = today.replace(year=today.year + 1)
    except ValueError:
        last_day = today.replace(year=today.year + 1, day=28)
    errors = {}
    if error is not None:
        params = dict(error.params)
        if error.code == "too_long" and params.get("limit") == "10000":
            params["limit"] = "10 000"
        errors[error.field] = {"code": error.code, "message": TEXTS[error.code].format(**params)}
    return {"form_values": values, "form_kinds": (("post", "Сообщение"), ("important", "Важное"),
                                                  ("event", "Событие")),
            "form_terms": (("day", "День"), ("week", "Неделя"), ("month", "Месяц"), ("date", "До даты")),
            "form_can_all": can_all, "form_pills": pills, "form_mentioned": mentioned,
            "form_mention_names": json.dumps(dict(mentioned), ensure_ascii=False),
            "form_until": PortalDateInput().render("until", values["until"], attrs={
                "id": "id_feed_until", "data-min": (today + timedelta(days=1)).isoformat(),
                "data-max": last_day.isoformat()}),
            "form_errors": errors, "pdn_found": found, "form_oob": oob}


@login_required
@require_POST
def publish(request):
    data = request.POST.copy()
    for name in ("text", "event_title", "event_place"):
        data[name] = data.get(name, "").replace("\x00", "")
    if data.get("kind") not in ("post", "important", "event"):
        data["kind"] = "post"
    error, found = None, ()
    try:
        post = posts.publish(request.user, data)
    except FeedError as exc:
        error = exc
    except PdnFound as exc:
        found = exc.found
    else:
        if request.headers.get("HX-Request") != "true":
            return redirect("/")
        card_data = page._card_data([post], request.user)[post.pk]
        result = page.FeedPage(posts=[card_data], important=[], more_cursor=None, opened=timezone.now())
        context = home._context(request.user, page.parse_filter({}), result)
        context.update(form_context(request.user, oob=True))
        return render(request, "feed/_publish_response.html", context)
    context = form_context(request.user, data, error=error, found=found)
    response = render_page(request, "feed/form.html", context)
    response["HX-Retarget"] = "#feed-form"
    response["HX-Reswap"] = "outerHTML"
    return response


@login_required
@require_GET
def card(request, post_id):
    post = visibility.get_post(request.user, post_id)
    card_data = page._card_data([post], request.user)[post.pk]
    card_data = card_data._replace(comments=comments.list_for(post))
    result = page.FeedPage(posts=[card_data], important=[], more_cursor=None, opened=timezone.now())
    unread.mark_shown(request.user, [post.pk])
    object_ref = f"feed.post:{post.pk}"
    events.publish("object.viewed", object_ref=object_ref, user_id=request.user.pk)
    own_comment_ids = Comment.objects.filter(object_ref=object_ref, author_id=request.user.pk).order_by(
        "created_at", "pk").values_list("pk", flat=True)
    for comment_id in own_comment_ids:
        events.publish("object.viewed", object_ref=f"{object_ref}:c{comment_id}", user_id=request.user.pk)
    context = home._context(request.user, page.parse_filter({}), result)
    context["ws_url"] = f"/ws/feed/?post={post.pk}"
    return render_page(request, "feed/card.html", context)


@login_required
@require_POST
@transaction.atomic
def delete_post(request, post_id):
    try:
        posts.delete(request.user, post_id)
    except PermissionDenied:
        return HttpResponseForbidden()
    if request.headers.get("HX-Request") == "true":
        return render(request, "feed/_delete_response.html", {"post_id": post_id})
    return redirect("/")


@login_required
@require_GET
def to(request, post_id):
    post = visibility.get_post(request.user, post_id)
    return render(request, "feed/_recipients.html", {"recipients": recipients.full(post)})


def _post_item(user, post):
    """Словарь записи для шаблона `_post.html`."""
    card = page._card_data([post], user)[post.pk]
    people = home._people([card])
    link_staff = bool({"staff.view", "accounts.manage"} & permissions.permissions_of(user))
    is_moderator = permissions.has_permission(user, "feed.moderate")
    comment_ids = [comment.pk for comment in card.comments]
    like_data = likes.comment_like_data(comment_ids, user.pk)
    item = home._cards([card], people, link_staff, user.pk, is_moderator, like_data)[0]
    item["link_staff"] = link_staff
    return item


def edit_form_context(user, post, data=None, *, error=None, found=(), oob=False):
    """Данные формы правки записи."""
    can_all = visibility.viewer(user).post_all
    values = {
        "text": post.text,
        "until": "",
        "event_title": post.event_title or "",
        "event_place": post.event_place or "",
        "event_start": "",
        "event_end": "",
    }
    if post.event_start:
        values["event_start"] = post.event_start.astimezone(MOSCOW).strftime("%Y-%m-%dT%H:%M")
        values["event_end"] = post.event_end.astimezone(MOSCOW).strftime("%Y-%m-%dT%H:%M")
    values["kind"] = post.kind
    if post.kind == Post.Kind.IMPORTANT and post.important_until:
        values["term"] = "date"
        last_day = post.important_until.astimezone(MOSCOW).date() - timedelta(days=1)
        values["until"] = last_day.isoformat()
    else:
        values["term"] = "date"

    if data is not None:
        for name in values:
            if name in data:
                values[name] = data.get(name, "")
        sent_term = data.get("term")
        if sent_term in ("day", "week", "month", "date"):
            values["term"] = sent_term

    # Сохранённые адресаты.
    saved_refs = ["all"] if post.to_all else []
    saved_rows = list(Recipient.objects.filter(post=post, via=Recipient.Via.TO).select_related("user"))
    saved_user_ids = []
    saved_unit_ids = []
    for row in saved_rows:
        if row.kind == Recipient.Kind.UNIT:
            saved_refs.append(f"u{row.unit_id}")
            saved_unit_ids.append(row.unit_id)
        else:
            saved_refs.append(f"p{row.user_id}")
            saved_user_ids.append(row.user_id)

    refs = list(dict.fromkeys(data.getlist("to") if data is not None else saved_refs))
    refs_set = set(refs)
    full_refs = list(dict.fromkeys([r for r in saved_refs if r not in refs_set] + refs))

    ids = {ref: int(ref[1:]) for ref in full_refs
           if ref[:1] in ("p", "u") and ref[1:].isascii() and ref[1:].isdigit()
           and 1 <= len(ref[1:]) <= 9}
    people = dict(User.objects.filter(pk__in=[pk for ref, pk in ids.items() if ref[0] == "p"])
                  .values_list("pk", "full_name"))
    units = {}
    unit_ids = [pk for ref, pk in ids.items() if ref[0] == "u"]
    if unit_ids and apps.is_installed("apps.org"):
        from apps.org.services import structure
        units = structure.unit_refs(unit_ids)

    pills = []
    for ref in full_refs:
        pk = ids.get(ref)
        is_saved = ref in saved_refs
        if ref == "all":
            label = "Всем"
        elif ref.startswith("p"):
            label = people.get(pk, ref)
        elif ref.startswith("u"):
            label = units[pk].name if pk in units else ref
        else:
            label = ref
        pills.append({"value": ref, "label": label, "saved": is_saved})

    try:
        mentioned_ids = mentions.extract(values["text"])
    except FeedError:
        mentioned_ids = []
    mentioned = list(User.objects.filter(pk__in=mentioned_ids, state=UserState.ACTIVE)
                     .values_list("pk", "full_name"))

    files = list(FeedFile.objects.filter(post=post, comment__isnull=True).select_related("file").order_by("pk"))

    remove_ids = set()
    if data is not None:
        raw = data.getlist("remove") if hasattr(data, "getlist") else (data.get("remove") or [])
        if isinstance(raw, (str, bytes)):
            raw = [raw]
        for value in raw:
            text = str(value).strip()
            if text.isdigit():
                remove_ids.add(int(text))

    today = moscow_today()
    try:
        last_day = today.replace(year=today.year + 1)
    except ValueError:
        last_day = today.replace(year=today.year + 1, day=28)
    errors = {}
    if error is not None:
        params = dict(error.params)
        if error.code == "too_long" and params.get("limit") == "10000":
            params["limit"] = "10 000"
        errors[error.field] = {"code": error.code, "message": TEXTS[error.code].format(**params)}
    return {
        "form_values": values,
        "form_kind": post.kind,
        "form_terms": (("day", "День"), ("week", "Неделя"), ("month", "Месяц"), ("date", "До даты")),
        "form_can_all": can_all,
        "form_pills": pills,
        "form_mentioned": mentioned,
        "form_mention_names": json.dumps(dict(mentioned), ensure_ascii=False),
        "form_files": files,
        "form_remove": remove_ids,
        "form_until": PortalDateInput().render("until", values["until"], attrs={
            "id": "id_feed_until", "data-min": (today + timedelta(days=1)).isoformat(),
            "data-max": last_day.isoformat()}),
        "form_errors": errors,
        "pdn_found": found,
        "form_oob": oob,
        "post": post,
    }


@login_required
@transaction.atomic
def edit_post(request, post_id):
    post = visibility.get_post(request.user, post_id)
    if not visibility.can_edit(request.user, post):
        return HttpResponseForbidden()
    if request.method == "GET":
        context = edit_form_context(request.user, post)
        return render_page(request, "feed/form_edit.html", context)

    data = request.POST.copy()
    for name in ("text", "event_title", "event_place"):
        data[name] = data.get(name, "").replace("\x00", "")
    error, found = None, ()
    try:
        post = posts.edit(request.user, post_id, data)
    except FeedError as exc:
        error = exc
    except PdnFound as exc:
        found = exc.found
    except PermissionDenied:
        return HttpResponseForbidden()
    else:
        if request.headers.get("HX-Request") != "true":
            return redirect(f"/feed/{post.pk}/")
        item = _post_item(request.user, post)
        context = {"item": item, "link_staff": item["link_staff"], "is_moderator": item["is_moderator"],
                   "opened": timezone.now(), "event_now": timezone.now()}
        return render(request, "feed/_post.html", context)
    context = edit_form_context(request.user, post, data=data, error=error, found=found)
    response = render(request, "feed/_form_edit.html", context)
    response["HX-Retarget"] = "#feed-form"
    response["HX-Reswap"] = "outerHTML"
    return response
