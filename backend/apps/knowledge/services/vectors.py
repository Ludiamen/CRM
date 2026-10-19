"""Векторы поиска статей: единственное место расчёта (контракт 17, п. 71; план 005, «Поиск»)."""
from django.db import connection

# Литерал с параметрами: список номеров — `%s`, имена таблиц — буквально.
_SQL = """
UPDATE knowledge_article AS a SET
  search_head = CASE WHEN a.state = %s THEN
      setweight(to_tsvector('russian', a.title), 'A') ||
      setweight(to_tsvector('russian', COALESCE((
          SELECT string_agg(t.name, ' ' ORDER BY t.name)
          FROM knowledge_article_tags ta JOIN knowledge_tag t ON t.id = ta.tag_id
          WHERE ta.article_id = a.id), '')), 'B')
  ELSE NULL END,
  search_full = CASE WHEN a.state = %s THEN
      setweight(to_tsvector('russian', a.title), 'A') ||
      setweight(to_tsvector('russian', COALESCE((
          SELECT string_agg(t.name, ' ' ORDER BY t.name)
          FROM knowledge_article_tags ta JOIN knowledge_tag t ON t.id = ta.tag_id
          WHERE ta.article_id = a.id), '')), 'B') ||
      setweight(to_tsvector('russian', left(a.plain, 100000)), 'C')
  ELSE NULL END
WHERE a.id = ANY(%s)
"""


def refresh(article_ids) -> None:
    """Пересчитывает векторы статей из списка: опубликованным — заново, остальным — `NULL` (FR-447)."""
    ids = list(article_ids)
    if not ids:
        return
    with connection.cursor() as cursor:
        cursor.execute(_SQL, ["published", "published", ids])
