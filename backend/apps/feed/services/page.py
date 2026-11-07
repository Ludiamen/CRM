"""Фильтры, курсорная выборка и пакетная сборка карточек ленты."""
import re
from collections import defaultdict
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from typing import NamedTuple
from zoneinfo import ZoneInfo

from django.apps import apps
from django.db import connection
from django.db.models import Q
from django.utils import timezone

from apps.core.models import Comment, User
from apps.feed.models import EventAnswer, FeedFile, Post, ReadMark, Recipient
from apps.feed.services import recipients, visibility


PAGE_SIZE = 20
MOSCOW = ZoneInfo("Europe/Moscow")
FILTER_KINDS = {"all", "important", "events", "mine", "mentions"}
CURSOR_PAGE_BLOCK_EXCLUSION = """
NOT (feed_post.kind = 'important'
     AND feed_post.important_until > %s
     AND feed_post.author_id <> %s
     AND NOT EXISTS (SELECT 1 FROM feed_readmark AS rm
                     WHERE rm.post_id = feed_post.id AND rm.user_id = %s))
"""
RECIPIENTS_SQL = """
SELECT r.id, r.post_id, r.unit_id, r.user_id, r.via
FROM feed_recipient AS r
WHERE r.post_id = ANY(%s)
ORDER BY r.post_id, r.id
"""
LIKES_SQL = """
SELECT p.id, totals.total, totals.mine, recent.user_id, recent.created_at, recent.id
FROM feed_post AS p
LEFT JOIN LATERAL (
    SELECT count(*) AS total, bool_or(user_id = %s) AS mine
    FROM feed_postlike
    WHERE post_id = p.id
) AS totals ON TRUE
LEFT JOIN LATERAL (
    SELECT user_id, created_at, id
    FROM feed_postlike
    WHERE post_id = p.id
    ORDER BY created_at DESC, id DESC
    LIMIT 2
) AS recent ON TRUE
WHERE p.id = ANY(%s)
ORDER BY p.id, recent.created_at DESC, recent.id DESC
"""
COMMENTS_SQL = """
SELECT p.id, totals.total, recent.id, recent.object_ref, recent.author_id,
       recent.text, recent.created_at, recent.edited_at
FROM feed_post AS p
LEFT JOIN LATERAL (
    SELECT count(*) AS total
    FROM core_comment AS c
    JOIN feed_feedcomment AS fc ON fc.comment_id = c.id
    WHERE c.object_ref = 'feed.post:' || p.id
) AS totals ON TRUE
LEFT JOIN LATERAL (
    SELECT c.id, c.object_ref, c.author_id, c.text, c.created_at, fc.edited_at
    FROM core_comment AS c
    JOIN feed_feedcomment AS fc ON fc.comment_id = c.id
    WHERE c.object_ref = 'feed.post:' || p.id
    ORDER BY c.created_at DESC, c.id DESC
    LIMIT 3
) AS recent ON TRUE
WHERE p.id = ANY(%s)
ORDER BY p.id, recent.created_at ASC, recent.id ASC
"""


class FeedFilter(NamedTuple):
    f: str
    author: int | None
    date_from: date | None
    date_to: date | None


class Card(NamedTuple):
    post: Post
    recipients: recipients.Line
    files: list[FeedFile]
    likes: list[User]
    like_count: int
    comments: list[Comment]
    comment_count: int
    liked: bool
    read: bool
    answer: str | None
    read_count: int
    read_total: int
    answer_counts: dict[str, int]


class FeedPage(NamedTuple):
    posts: list[Card]
    important: list[Card]
    more_cursor: str | None
    opened: datetime


def _value(query, key):
    value = query.get(key) if hasattr(query, "get") else None
    if isinstance(value, (list, tuple)):
        value = value[-1] if value else None
    return value


def _positive_id(value, *, digits=9):
    if not isinstance(value, str) or not re.fullmatch(rf"[1-9]\d{{0,{digits - 1}}}", value):
        return None
    number = int(value)
    return number if number <= 9223372036854775807 else None


def _date(value):
    if not isinstance(value, str):
        return None
    for fmt in ("%d.%m.%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    return None


def parse_filter(query) -> FeedFilter:
    """Разобрать только контрактные значения; чужие и неверные отбросить."""
    kind = _value(query, "f")
    if kind not in FILTER_KINDS:
        kind = "all"
    return FeedFilter(
        f=kind,
        author=_positive_id(_value(query, "author")),
        date_from=_date(_value(query, "from")),
        date_to=_date(_value(query, "to")),
    )


def _moment(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value)
        except ValueError:
            return None
    if not isinstance(value, datetime) or timezone.is_naive(value):
        return None
    return value.astimezone(dt_timezone.utc)


def _cursor(value):
    if isinstance(value, (tuple, list)) and len(value) == 2:
        stamp, number = value
    elif isinstance(value, str) and value.count(",") == 1:
        stamp, number = value.rsplit(",", 1)
    else:
        return None
    stamp = _moment(stamp)
    number = _positive_id(number, digits=18) if isinstance(number, str) else number
    if stamp is None or not isinstance(number, int) or isinstance(number, bool) or number <= 0:
        return None
    if number > 9223372036854775807:
        return None
    return stamp, number


def _boundary(value, *, following=False):
    if value is None:
        return None
    day = value + timedelta(days=1) if following else value
    return datetime.combine(day, time.min, tzinfo=MOSCOW)


def _block_enabled(flt):
    return flt.f in {"all", "important"} and flt.author is None and flt.date_from is None and flt.date_to is None


def _important_posts(user, moment):
    return list(
        visibility.visible_posts(user)
        .filter(kind=Post.Kind.IMPORTANT, important_until__gt=moment)
        .exclude(author_id=user.pk)
        .exclude(read_marks__user_id=user.pk)
        .order_by("-published_at", "-pk")
    )


def _page_posts(user, flt, *, opened, before, moment, block_ids):
    posts = visibility.visible_posts(user).filter(published_at__lte=opened)
    if flt.f == "important":
        posts = posts.filter(kind=Post.Kind.IMPORTANT)
    elif flt.f == "events":
        posts = posts.filter(kind=Post.Kind.EVENT)
    elif flt.f == "mine":
        posts = posts.filter(author_id=user.pk)
    elif flt.f == "mentions":
        posts = posts.filter(recipients__via=Recipient.Via.MENTION, recipients__user_id=user.pk)
    if flt.author is not None:
        posts = posts.filter(author_id=flt.author)
    start = _boundary(flt.date_from)
    end = _boundary(flt.date_to, following=True)
    if start is not None:
        posts = posts.filter(published_at__gte=start)
    if end is not None:
        posts = posts.filter(published_at__lt=end)
    if before is not None:
        stamp, number = before
        posts = posts.filter(Q(published_at__lt=stamp) | Q(published_at=stamp, pk__lt=number))
    if block_ids is not None:
        posts = posts.extra(where=[CURSOR_PAGE_BLOCK_EXCLUSION], params=[moment, user.pk, user.pk])
    return list(posts.order_by("-published_at", "-pk")[:PAGE_SIZE + 1])


def _fetchall(sql, params):
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        return cursor.fetchall()


def _audiences(posts, recipient_rows):
    """Текущая действующая аудитория каждой записи (без автора), пакетно."""

    to_all_posts = [post for post in posts if post.to_all]
    eligible_all = set()
    if to_all_posts:
        eligible_all = set(User.objects.filter(state__in=("active", "invited")).values_list("pk", flat=True))

    non_to_all_user_ids = set()
    non_to_all_unit_ids = set()
    for post in posts:
        if post.to_all:
            continue
        non_to_all_user_ids.add(post.author_id)
        for row in recipient_rows[post.pk]:
            if row.user_id is not None:
                non_to_all_user_ids.add(row.user_id)
            if row.unit_id is not None:
                non_to_all_unit_ids.add(row.unit_id)
    unit_members = defaultdict(set)
    if non_to_all_unit_ids and apps.is_installed("apps.org"):
        from apps.org.services import structure

        member_ids = structure.subtree_member_ids(non_to_all_unit_ids)
        non_to_all_user_ids.update(member_ids)
        for user_id, chain in structure.unit_chains(member_ids).items():
            for unit_id in non_to_all_unit_ids.intersection(chain):
                unit_members[unit_id].add(user_id)

    states = {}
    if non_to_all_user_ids:
        states = dict(User.objects.extra(
            where=["core_user.id = ANY(%s)"], params=[sorted(non_to_all_user_ids)]
        ).values_list("pk", "state"))

    audiences = {}
    for post in posts:
        if post.to_all:
            audiences[post.pk] = eligible_all - {post.author_id}
            continue
        ids = {post.author_id}
        for row in recipient_rows[post.pk]:
            if row.user_id is not None:
                ids.add(row.user_id)
            if row.unit_id is not None:
                ids.update(unit_members[row.unit_id])
        audiences[post.pk] = {uid for uid in ids if states.get(uid) in ("active", "invited")} - {post.author_id}
    return audiences


def _card_data(posts, user):
    """Загрузить все связи одним набором запросов, не зависящим от числа записей."""
    if not posts:
        return {}
    post_ids = [post.pk for post in posts]
    recipient_rows = defaultdict(list)
    user_ids = {post.author_id for post in posts}
    unit_ids = set()
    for row_id, post_id, unit_id, user_id, via in _fetchall(RECIPIENTS_SQL, [post_ids]):
        recipient_rows[post_id].append(Recipient(id=row_id, post_id=post_id, unit_id=unit_id,
                                                  user_id=user_id, via=via))
        if unit_id is not None:
            unit_ids.add(unit_id)
        if user_id is not None:
            user_ids.add(user_id)

    files = defaultdict(list)
    for item in FeedFile.objects.extra(where=["feed_feedfile.post_id = ANY(%s)"], params=[post_ids]) \
            .select_related("file").order_by("post_id", "pk"):
        files[item.post_id].append(item)

    likes = defaultdict(lambda: [0, False, []])
    for post_id, total, mine, user_id, _, _ in _fetchall(LIKES_SQL, [user.pk, post_ids]):
        likes[post_id][0] = total
        likes[post_id][1] = bool(mine)
        if user_id is not None:
            likes[post_id][2].append(user_id)
            user_ids.add(user_id)

    comments = defaultdict(list)
    comment_counts = defaultdict(int)
    for post_id, total, comment_id, object_ref, author_id, text, created_at, edited_at in _fetchall(
            COMMENTS_SQL, [post_ids]):
        comment_counts[post_id] = total
        if comment_id is not None:
            comments[post_id].append((comment_id, object_ref, author_id, text, created_at, edited_at))
            user_ids.add(author_id)

    audiences = _audiences(posts, recipient_rows)
    marks_by_post = defaultdict(list)
    for post_id, user_id in _fetchall("""
        SELECT rm.post_id, rm.user_id
        FROM feed_readmark rm
        JOIN core_user u ON u.id = rm.user_id
        WHERE rm.post_id = ANY(%s)
          AND u.state NOT IN ('blocked', 'dismissed')
    """, [post_ids]):
        if user_id in audiences.get(post_id, set()):
            marks_by_post[post_id].append(user_id)
    read_stats = {}
    for post in posts:
        audience = audiences.get(post.pk, set())
        post_marks = marks_by_post.get(post.pk, [])
        read_count = len(post_marks)
        read = user.pk in audience and user.pk in post_marks
        read_stats[post.pk] = (read_count, read, len(audience))

    answer_stats = defaultdict(lambda: [0, 0, None])
    for post_id, user_id, answer in EventAnswer.objects.extra(
            where=["feed_eventanswer.post_id = ANY(%s)"], params=[post_ids]
    ).values_list("post_id", "user_id", "answer"):
        if user_id not in audiences[post_id]:
            continue
        counts = answer_stats[post_id]
        counts[0 if answer == EventAnswer.Answer.GO else 1] += 1
        if user_id == user.pk:
            counts[2] = answer

    users = {
        person.pk: person
        for person in User.objects.extra(where=["core_user.id = ANY(%s)"], params=[sorted(user_ids)])
        .select_related("photo")
    }
    units = {}
    if unit_ids and apps.is_installed("apps.org"):
        from apps.org.services import structure

        units = structure.unit_refs(unit_ids)

    cards = {}
    for post in posts:
        post.author = users[post.author_id]
        liker_ids = likes[post.pk][2]
        comment_items = []
        for comment_id, object_ref, author_id, text, created_at, edited_at in comments[post.pk]:
            comment = Comment(id=comment_id, object_ref=object_ref, author_id=author_id,
                              text=text, created_at=created_at)
            comment.author = users[author_id]
            comment.edited_at = edited_at
            comment_items.append(comment)
        read_count, read, read_total = read_stats.get(post.pk, (0, False, 0))
        go, no, answer = answer_stats.get(post.pk, (0, 0, None))
        cards[post.pk] = Card(
            post=post,
            recipients=recipients.line(post, rows=recipient_rows[post.pk], users=users, units=units),
            files=files[post.pk],
            likes=[users[user_id] for user_id in liker_ids],
            like_count=likes[post.pk][0],
            comments=comment_items,
            comment_count=comment_counts[post.pk],
            liked=likes[post.pk][1],
            read=read,
            answer=answer,
            read_count=read_count,
            read_total=read_total,
            answer_counts={EventAnswer.Answer.GO: go, EventAnswer.Answer.NO: no},
        )
    return cards


def build(user, flt, *, before=None, opened=None, now=None) -> FeedPage:
    """Собрать первую или курсорную страницу; неверный курсор означает первую страницу."""
    moment = _moment(now) or timezone.now()
    opened_value = _moment(opened) or moment
    before_value = _cursor(before)
    block = _block_enabled(flt)
    important = _important_posts(user, moment) if block else []
    rows = _page_posts(
        user, flt, opened=opened_value, before=before_value, moment=moment,
        block_ids=[post.pk for post in important] if block else None,
    )
    has_more = len(rows) > PAGE_SIZE
    rows = rows[:PAGE_SIZE]
    more_cursor = None
    if has_more and rows:
        last = rows[-1]
        more_cursor = f"{last.published_at.isoformat()},{last.pk}"
    if before_value is not None:
        cards = _card_data(rows, user)
        important_cards = []
    else:
        cards = _card_data([*rows, *important], user)
        important_cards = [cards[post.pk] for post in important]
    return FeedPage(
        posts=[cards[post.pk] for post in rows],
        important=important_cards,
        more_cursor=more_cursor,
        opened=opened_value,
    )
