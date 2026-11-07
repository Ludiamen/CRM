"""Сроки, статистика и прочтение важных записей ленты."""

from calendar import monthrange
from datetime import date as Date, datetime, time, timedelta
from typing import NamedTuple

from django.db import transaction

from apps.core import widgets
from apps.feed.models import Post, ReadMark
from apps.feed.services import visibility
from apps.feed.services.errors import FeedError
from apps.feed.services import live as _live


class ReadStats(NamedTuple):
    read: int
    total: int


def until(term, date, today) -> datetime:
    """Полночь Москвы после последнего дня срока.

    Пользовательские ошибки возвращаются как FeedError с кодом и полем формы.
    ValueError остаётся для программных ошибок вызывающего (например, date не
    datetime.date при term="date").
    """
    if term is None or str(term).strip() == "":
        raise FeedError("term_required", "term")
    if term not in ("day", "week", "month", "date"):
        raise FeedError("term_required", "term")

    if term == "date":
        if date is None or (isinstance(date, str) and str(date).strip() == ""):
            raise FeedError("invalid_until", "until")
        if not isinstance(date, Date) or isinstance(date, datetime):
            raise ValueError("Important date must be a datetime.date")
        if date <= today:
            raise FeedError("date_passed", "term")
        try:
            year_limit = today.replace(year=today.year + 1)
        except ValueError:
            year_limit = today.replace(year=today.year + 1, day=28)
        if date > year_limit:
            raise FeedError("term_too_far", "term")
        last_day = date
    elif term == "day":
        last_day = today + timedelta(days=1)
    elif term == "week":
        last_day = today + timedelta(days=7)
    elif term == "month":
        year = today.year + (today.month == 12)
        month = today.month % 12 + 1
        last_day = today.replace(year=year, month=month,
                                 day=min(today.day, monthrange(year, month)[1]))
    return datetime.combine(last_day + timedelta(days=1), time.min, tzinfo=widgets.MOSCOW)


def stats(post) -> ReadStats:
    """Прочтения только текущей действующей аудитории, без автора и повторов."""
    audience = visibility.audience(post) - {post.author_id}
    read = ReadMark.objects.filter(post_id=post.pk, user_id__in=audience).count()
    return ReadStats(read=read, total=len(audience))


def mark_read(user, post_id, *, now=None) -> None:
    """Отметить важную запись прочитанной.

    Повторный вызов не ошибка: создание пропускается, время прочтения не меняется.
    Автору, после окончания срока или неважной записи — PermissionDenied
    с текстом причины (CONTRACT-007 §5.4, §10.2).
    """
    from django.core.exceptions import PermissionDenied
    from django.utils import timezone

    from apps.feed.texts import TEXTS

    post = visibility.get_post(user, post_id)
    if post.kind != Post.Kind.IMPORTANT:
        raise PermissionDenied()
    if post.author_id == user.pk:
        raise PermissionDenied(TEXTS["read_author"])
    moment = now if now is not None else timezone.now()
    if moment >= post.important_until:
        raise PermissionDenied(TEXTS["read_expired"])
    with transaction.atomic():
        ReadMark.objects.get_or_create(post=post, user=user, defaults={"read_at": moment})
        transaction.on_commit(
            lambda: _live.publish_event(post.pk, "read", owner_id=post.author_id)
        )
