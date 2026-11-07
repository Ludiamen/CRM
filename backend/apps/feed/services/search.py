"""Векторы и поставщик поиска группы «Лента» (план 007, «Поиск»; CONTRACT-007, раздел 9).

`vectors` пересчитывает векторы записи и комментария в транзакциях публикации и правки. Поставщик ищет `слово:*`
по словам `ParsedQuery` (стоп-слова отсеиваются `numnode`), видимость записей решает только
`visibility.visible_posts` — его подзапрос стоит в каждой ветке того же SQL, поэтому невидимая запись и её
комментарии не попадают ни в выдачу, ни в число (FR-606). Выдача — `UNION ALL` веток записей и комментариев по
`LIMIT limit + offset + 1`, снаружи от новых к старым; число — две ветки по `LIMIT 301` с потолком 300 (NFR-603).
Слова запроса уходят в SQL параметрами (NFR-608), текст запроса нигде не сохраняется.
"""
from django.core.exceptions import EmptyResultSet
from django.db import connection

from apps.core.extensions import ParsedQuery, SearchProvider, SearchRow
from apps.core.widgets import MOSCOW
from apps.feed.services import text, visibility

ORDER = 60
SNIPPET_LIMIT = 100
COUNT_CAP = 300

_POST_SQL = """
UPDATE feed_post
SET search =
  setweight(to_tsvector('russian', coalesce(event_title, '') || ' ' || coalesce(event_place, '')), 'A') ||
  setweight(to_tsvector('russian', regexp_replace(text, '@\\[[1-9][0-9]{0,8}\\]', ' ', 'g')), 'B')
WHERE id = ANY(%s)
"""
_COMMENT_SQL = """
UPDATE feed_feedcomment AS fc
SET search = to_tsvector('russian', regexp_replace(c.text, '@\\[[1-9][0-9]{0,8}\\]', ' ', 'g'))
FROM core_comment AS c
WHERE c.id = fc.comment_id AND fc.comment_id = ANY(%s)
"""

# Ветка записей: отрывок события — название вместо текста (план, «Поиск»); `{visible}` — подзапрос
# `visible_posts`, встраивается при вызове, значения его условий уходят параметрами.
_POST_BRANCH = """
(SELECT p.id AS id, p.published_at AS dt, 'post' AS entity, p.id AS post_id, NULL AS comment_id,
        a.full_name AS author_name,
        CASE WHEN p.kind = 'event' THEN p.event_title ELSE p.text END AS body
 FROM feed_post AS p
 JOIN core_user AS a ON a.id = p.author_id
 WHERE p.id IN ({visible}) AND p.search @@ to_tsquery('russian', %s)
 ORDER BY p.published_at DESC, p.id DESC
 LIMIT %s)
"""
# Ветка комментариев: соединение feed_feedcomment → core_comment → feed_post (план, «Поиск»); видимость —
# видимость записи комментария.
_COMMENT_BRANCH = """
(SELECT c.id AS id, c.created_at AS dt, 'comment' AS entity, fc.post_id AS post_id, c.id AS comment_id,
        a.full_name AS author_name, c.text AS body
 FROM feed_feedcomment AS fc
 JOIN core_comment AS c ON c.id = fc.comment_id
 JOIN feed_post AS p ON p.id = fc.post_id
 JOIN core_user AS a ON a.id = c.author_id
 WHERE p.id IN ({visible}) AND fc.search @@ to_tsquery('russian', %s)
 ORDER BY c.created_at DESC, c.id DESC
 LIMIT %s)
"""
_SEARCH_SQL = _POST_BRANCH + "\nUNION ALL\n" + _COMMENT_BRANCH + """
ORDER BY dt DESC, id DESC
LIMIT %s OFFSET %s
"""
_COUNT_SQL = """
SELECT
    (SELECT count(*) FROM (SELECT 1
                           FROM feed_post AS p
                           WHERE p.id IN ({visible}) AND p.search @@ to_tsquery('russian', %s)
                           LIMIT 301) AS posts) AS posts,
    (SELECT count(*) FROM (SELECT 1
                           FROM feed_feedcomment AS fc
                           JOIN feed_post AS p ON p.id = fc.post_id
                           WHERE p.id IN ({visible}) AND fc.search @@ to_tsquery('russian', %s)
                           LIMIT 301) AS comments) AS comments
"""


def vectors(*, post_ids=(), comment_ids=()) -> None:
    """Пересчитать переданные векторы; значения всегда передаются SQL-параметрами."""
    posts = list(dict.fromkeys(post_ids))
    comments = list(dict.fromkeys(comment_ids))
    if not posts and not comments:
        return
    with connection.cursor() as cursor:
        if posts:
            cursor.execute(_POST_SQL, [posts])
        if comments:
            cursor.execute(_COMMENT_SQL, [comments])


def _useful_words(words) -> list[str]:
    """Слова без стоп-слов: `numnode(to_tsquery('russian', слово:*)) = 0` проверяется одним запросом."""
    words = list(dict.fromkeys(words))
    if not words:
        return []
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT w FROM unnest(%s::text[]) AS w WHERE numnode(to_tsquery('russian', w || ':*')) > 0",
            [words])
        kept = {row[0] for row in cursor.fetchall()}
    return [word for word in words if word in kept]


def _tsquery(words: list[str]) -> str:
    """Строка `to_tsquery`: `слово:*`, слова по И (стоп-слова уже отсеяны); уходит в SQL параметром."""
    return " & ".join(f"{word}:*" for word in words)


def _visible_subquery(user):
    """Подзапрос видимых записей и его параметры — то же правило, что `visibility.visible_posts` (план 007:
    видимость решает только эта служба). `(None, None)` — видимых записей нет (не вошедшему или
    недействующему сотруднику)."""
    sub = visibility.visible_posts(user).values("pk").order_by()
    try:
        return sub.query.sql_with_params()
    except EmptyResultSet:
        return None, None


def _row(row) -> SearchRow:
    """Строка выдачи: «<ФИО>, <ДД.ММ.ГГГГ по Москве> — <отрывок>», подсказка «Запись»/«Комментарий» и адрес."""
    _id, dt, entity, post_id, comment_id, author_name, body = row
    date = dt.astimezone(MOSCOW).strftime("%d.%m.%Y")
    if entity == "post":
        subtitle, url = "Запись", f"/feed/{post_id}/"
    else:
        subtitle, url = "Комментарий", f"/feed/{post_id}/#c{comment_id}"
    return SearchRow(
        title=f"{author_name}, {date} — {text.snippet(body, SNIPPET_LIMIT)}",
        subtitle=subtitle,
        url=url,
    )


def available(user) -> bool:
    """Группа «Лента» показывается каждому вошедшему (FR-636)."""
    return bool(getattr(user, "is_authenticated", False))


def search(user, parsed: ParsedQuery, limit: int, offset: int) -> list[SearchRow]:
    """Строки группы: до `limit + 1` со смещением `offset`, от новых к старым по времени записи и создания."""
    if parsed.hint:
        return []
    words = _useful_words(parsed.words)
    if not words:
        return []
    query = _tsquery(words)
    visible_sql, visible_params = _visible_subquery(user)
    if visible_sql is None:
        return []
    branch_limit = limit + offset + 1
    sql = _SEARCH_SQL.format(visible=visible_sql)
    params = [*visible_params, query, branch_limit,
              *visible_params, query, branch_limit,
              limit + 1, offset]
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        rows = cursor.fetchall()
    return [_row(row) for row in rows]


def count(user, parsed: ParsedQuery) -> tuple[int, bool]:
    """`(число, упёрлись ли в потолок)`: две ветки по `LIMIT 301`, сумма с потолком 300 (NFR-603)."""
    if parsed.hint:
        return 0, False
    words = _useful_words(parsed.words)
    if not words:
        return 0, False
    query = _tsquery(words)
    visible_sql, visible_params = _visible_subquery(user)
    if visible_sql is None:
        return 0, False
    sql = _COUNT_SQL.format(visible=visible_sql)
    params = [*visible_params, query, *visible_params, query]
    with connection.cursor() as cursor:
        cursor.execute(sql, params)
        posts, comments = cursor.fetchone()
    total = posts + comments
    return min(total, COUNT_CAP), total > COUNT_CAP


def search_providers() -> list[SearchProvider]:
    """Запись точки `search_providers`: группа «Лента» после «Списков» (order 60, FR-636, FR-641)."""
    return [SearchProvider(key="feed", title="Лента", order=ORDER, search=search, count=count,
                           available=available)]
