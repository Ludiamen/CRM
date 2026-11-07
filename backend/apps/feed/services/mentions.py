"""Разбор и сохранение маркеров упоминаний в ленте."""

import re

from apps.core.models import User, UserState
from apps.feed.models import Post, Recipient
from apps.feed.services.errors import FeedError


_MARKER = re.compile(r"@\[([1-9]\d{0,8})\]")
_MAX_MENTIONS = 20


def extract(text: str) -> list[int]:
    """Вернуть уникальные синтаксически корректные ID в порядке появления."""
    ids = list(dict.fromkeys(int(match.group(1)) for match in _MARKER.finditer(text)))
    if len(ids) > _MAX_MENTIONS:
        raise FeedError("too_many_mentions", "text")
    return ids


def sync(post: Post, text: str, old_text: str = "") -> set[int]:
    """Добавить отсутствующие активные строки упоминаний и вернуть новые синтаксические ID."""
    ids = extract(text)
    new_ids = set(ids).difference(extract(old_text))
    if ids:
        active_ids = set(User.objects.filter(
            pk__in=ids,
            state=UserState.ACTIVE,
        ).values_list("pk", flat=True))
        if active_ids:
            existing_ids = set(Recipient.objects.filter(
                post=post,
                via=Recipient.Via.MENTION,
                user_id__in=active_ids,
            ).values_list("user_id", flat=True))
            Recipient.objects.bulk_create(
                [
                    Recipient(
                        post=post,
                        kind=Recipient.Kind.USER,
                        user_id=user_id,
                        via=Recipient.Via.MENTION,
                        published_at=post.published_at,
                    )
                    for user_id in active_ids - existing_ids
                ],
                ignore_conflicts=True,
            )
    return new_ids
