"""Доска «Стадии» (срез 015; PLAN-015, «Доска»; CONTRACT-015, разделы 5 и 9).

Колонки — читаемые стадии по порядку и «Без стадии»; набор — таблица списка без архива и с правами стадий.
Порядок внутри колонки — сортировка таблицы. До 50 карточек на колонку, «показать ещё» — отдельным запросом.
"""
from dataclasses import replace

from django.db.models import Count

from apps.lists.services import access, grid, process

PAGE = 50


def _column(key, title, kind, rows, total, *, offset=0):
    return {"key": key, "title": title, "kind": kind, "rows": rows[:PAGE], "count": total,
            "has_next": len(rows) > PAGE, "offset": offset}


def columns(lst, viewer, gp) -> list[dict]:
    """Колонки доски: читаемые стадии по порядку плюс «Без стадии»."""
    base = grid.records(lst, viewer, replace(gp, preset="all"))
    counts = {row["stage"]: row["total"] for row in base.order_by().values("stage").annotate(total=Count("pk"))}
    result = []
    for stage in process.visible_stages(lst):
        if not access.can_read_stage(viewer, lst, stage.pk):
            continue
        rows = list(base.filter(stage_id=stage.pk)[:PAGE + 1])
        result.append(_column(str(stage.pk), stage.title, stage.kind, rows, counts.get(stage.pk, 0)))
    if counts.get(None, 0):
        rows = list(base.filter(stage__isnull=True)[:PAGE + 1])
        result.append(_column("none", "Без стадии", "none", rows, counts.get(None, 0)))
    return result


def column(lst, viewer, gp, key: str, offset: int = 0) -> dict:
    """Страница одной колонки; `key` — номер стадии или `none`."""
    base = grid.records(lst, viewer, replace(gp, preset="all"))
    if key == "none":
        stage = None
        title, kind = "Без стадии", "none"
        base = base.filter(stage__isnull=True)
    else:
        stage = process.stage_of(lst, int(key))
        if not access.can_read_stage(viewer, lst, stage.pk):
            from django.http import Http404

            raise Http404("Стадия не найдена")
        title, kind = stage.title, stage.kind
        base = base.filter(stage_id=stage.pk)
    total = base.count()
    rows = list(base[offset:offset + PAGE + 1])
    return _column(key, title, kind, rows, total, offset=offset)
