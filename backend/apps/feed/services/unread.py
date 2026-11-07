"""Показы и число непрочитанных записей ленты (FR-626)."""

from django.apps import apps
from django.db import connection
from django.utils import timezone

from apps.core.models import UserState


_INACTIVE_STATES = (UserState.BLOCKED, UserState.DISMISSED)


def _unit_chain(user) -> frozenset[int]:
    if not apps.is_installed("apps.org"):
        return frozenset()

    from apps.org.services import structure

    return structure.unit_chain_ids(user)


def _unit_chains(user_ids) -> dict[int, frozenset[int]]:
    if not apps.is_installed("apps.org"):
        return {user_id: frozenset() for user_id in user_ids}

    from apps.org.services import structure

    return structure.unit_chains(user_ids)


def mark_shown(user, post_ids) -> None:
    """Записать одним INSERT только показы записей, видимых сотруднику, кроме своих."""
    user_id = getattr(user, "pk", None)
    if user_id is None or getattr(user, "state", None) in _INACTIVE_STATES:
        return None

    post_ids = list(post_ids)
    if not post_ids:
        return None

    chain = list(_unit_chain(user))
    sql = """
        INSERT INTO feed_shown (user_id, post_id, shown_at)
        SELECT %s, p.id, %s
        FROM feed_post AS p
        WHERE p.id = ANY(%s)
          AND p.author_id <> %s
          AND EXISTS (
              SELECT 1 FROM core_user AS u
              WHERE u.id = %s AND u.state NOT IN (%s, %s)
          )
          AND (
              p.to_all
              OR EXISTS (
                  SELECT 1 FROM feed_recipient AS r
                  WHERE r.post_id = p.id
                    AND (r.user_id = %s OR r.unit_id = ANY(%s))
              )
          )
        ON CONFLICT DO NOTHING
    """
    with connection.cursor() as cursor:
        cursor.execute(
            sql,
            [
                user_id,
                timezone.now(),
                post_ids,
                user_id,
                user_id,
                *_INACTIVE_STATES,
                user_id,
                chain,
            ],
        )
    return None


def count(user, *, now=None) -> int:
    """Сосчитать до 100 видимых чужих записей за последние 30 дней без показа."""
    user_id = getattr(user, "pk", None)
    if user_id is None or getattr(user, "state", None) in _INACTIVE_STATES:
        return 0

    moment = timezone.now() if now is None else now
    chain = list(_unit_chain(user))
    sql = """
        SELECT count(*)
        FROM (
            SELECT 1
            FROM feed_post AS p
            WHERE p.published_at >= %s - interval '30 days'
              AND p.author_id <> %s
              AND (
                  p.author_id = %s
                  OR p.to_all
                  OR EXISTS (
                      SELECT 1 FROM feed_recipient AS r
                      WHERE r.post_id = p.id
                        AND (r.unit_id = ANY(%s) OR r.user_id = %s)
                  )
              )
              AND NOT EXISTS (
                  SELECT 1 FROM feed_shown AS s
                  WHERE s.user_id = %s AND s.post_id = p.id
              )
              AND EXISTS (
                  SELECT 1 FROM core_user AS u
                  WHERE u.id = %s AND u.state NOT IN (%s, %s)
              )
            LIMIT 100
        ) AS unread
    """
    with connection.cursor() as cursor:
        cursor.execute(
            sql,
            [moment, user_id, user_id, chain, user_id, user_id, user_id, *_INACTIVE_STATES],
        )
        return cursor.fetchone()[0]


def counts(user_ids, *, now=None) -> dict[int, int]:
    """Вернуть число непрочитанных для каждого сотрудника одним set-based SQL-запросом."""
    requested_ids = list(dict.fromkeys(int(user_id) for user_id in user_ids))
    if not requested_ids:
        return {}

    chains = _unit_chains(requested_ids)
    pair_user_ids: list[int] = []
    pair_unit_ids: list[int] = []
    for user_id in requested_ids:
        for unit_id in sorted(chains.get(user_id, ())):
            pair_user_ids.append(user_id)
            pair_unit_ids.append(unit_id)

    moment = timezone.now() if now is None else now
    sql = """
        WITH bounds AS (
            SELECT %s::timestamptz - interval '30 days' AS cutoff
        ), requested AS (
            SELECT DISTINCT unnest(%s::int[]) AS user_id
        ), unit_pairs AS (
            SELECT *
            FROM unnest(%s::int[], %s::int[]) AS pairs(user_id, unit_id)
        ), visible(user_id, post_id) AS (
            SELECT requested.user_id, p.id
            FROM requested
            CROSS JOIN feed_post AS p
            CROSS JOIN bounds
            WHERE p.to_all AND p.published_at >= bounds.cutoff

            UNION

            SELECT unit_pairs.user_id, r.post_id
            FROM unit_pairs
            JOIN feed_recipient AS r ON r.unit_id = unit_pairs.unit_id
            CROSS JOIN bounds
            WHERE r.published_at >= bounds.cutoff

            UNION

            SELECT r.user_id, r.post_id
            FROM feed_recipient AS r
            JOIN requested ON requested.user_id = r.user_id
            CROSS JOIN bounds
            WHERE r.published_at >= bounds.cutoff
        ), unread AS (
            SELECT visible.user_id, visible.post_id
            FROM visible
            JOIN feed_post AS p ON p.id = visible.post_id
            WHERE p.author_id <> visible.user_id
              AND NOT EXISTS (
                  SELECT 1 FROM feed_shown AS s
                  WHERE s.user_id = visible.user_id AND s.post_id = visible.post_id
              )
        )
        SELECT requested.user_id,
               LEAST(count(unread.post_id) FILTER (
                   WHERE users.state NOT IN (%s, %s)
               ), 100)::int AS unread_count
        FROM requested
        LEFT JOIN core_user AS users ON users.id = requested.user_id
        LEFT JOIN unread ON unread.user_id = requested.user_id
        GROUP BY requested.user_id, users.state
    """
    with connection.cursor() as cursor:
        cursor.execute(
            sql,
            [moment, requested_ids, pair_user_ids, pair_unit_ids, *_INACTIVE_STATES],
        )
        return {user_id: unread_count for user_id, unread_count in cursor.fetchall()}
