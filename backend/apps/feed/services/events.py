"""Поля публикации события и ответы действующих участников (T-7217)."""
from datetime import datetime, timedelta
from typing import NamedTuple

from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.core import widgets
from apps.feed.models import EventAnswer, Post
from apps.feed.services import live as _live, visibility
from apps.feed.services.errors import FeedError


class EventFields(NamedTuple):
    title: str
    place: str
    start: datetime
    end: datetime


def _time(value, field):
    for fmt in ("%d.%m.%Y %H:%M", "%Y-%m-%dT%H:%M"):
        try:
            return datetime.strptime(str(value or "").strip(), fmt).replace(tzinfo=widgets.MOSCOW)
        except ValueError:
            continue
    raise FeedError("event_time_required", field)


def validate(data, *, now, editing=None) -> EventFields:
    """Проверить поля события; правила правки подключаются задачей T-7220."""
    title = str(data.get("event_title", "")).replace("\x00", "").strip()
    place = str(data.get("event_place", "")).replace("\x00", "").strip()
    for value, field, code in ((title, "event_title", "event_title_required"),
                               (place, "event_place", "event_place_required")):
        if not value:
            raise FeedError(code, field)
        if len(value) > 200:
            raise FeedError("too_long", field, {"limit": "200"})
    start = _time(data.get("event_start"), "event_start")
    end = _time(data.get("event_end"), "event_end")
    if end <= start:
        raise FeedError("event_end_before_start", "event_end")

    if editing is not None and editing.kind == Post.Kind.EVENT and editing.event_start <= now:
        # Событие уже началось: время и место не меняются.
        if (start != editing.event_start or end != editing.event_end
                or place != editing.event_place):
            raise FeedError("event_started", "event_start")
        return EventFields(title, place, start, end)

    if start < now:
        raise FeedError("event_start_passed", "event_start")
    return EventFields(title, place, start, end)


def remind_at(start, now):
    return start - timedelta(hours=1) if start - now >= timedelta(hours=1) else None


def edit_remind_at(post, new_start, now):
    """Пересчёт remind_at при правке события (FR-619)."""
    if new_start - now < timedelta(hours=1):
        return None
    if post.reminded_for_start is None:
        return new_start - timedelta(hours=1)
    if new_start > post.reminded_for_start + timedelta(hours=1):
        return new_start - timedelta(hours=1)
    return None


@transaction.atomic
def answer(user, post_id, answer, *, now=None) -> EventAnswer:
    post = get_object_or_404(Post.objects.select_for_update(), pk=post_id)
    post = visibility.get_post(user, post.pk)
    if post.kind != Post.Kind.EVENT or post.author_id == user.pk:
        raise PermissionDenied
    moment = now if now is not None else timezone.now()
    if moment >= post.event_start:
        raise FeedError("answers_closed")
    if answer not in EventAnswer.Answer.values:
        raise ValueError("Unknown event answer")
    row, _ = EventAnswer.objects.update_or_create(
        post=post, user=user, defaults={"answer": answer, "answered_at": moment})
    transaction.on_commit(
        lambda: _live.publish_event(post.pk, "answer", owner_id=post.author_id)
    )
    return row
