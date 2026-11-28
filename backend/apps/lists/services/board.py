"""Доска «Стадии» (срез 015; PLAN-015, «Доска»; CONTRACT-015, разделы 5 и 9).

Колонки — читаемые стадии по порядку и «Без стадии»; набор — таблица списка без архива и с правами стадий.
Порядок внутри колонки — сортировка таблицы. Одна оконная выборка на доску: до 50 карточек на колонку,
счётчик и «показать ещё» — из того же запроса.
"""
from dataclasses import replace

from django.db.models import Count, F, Window
from django.db.models.functions import RowNumber

from apps.lists.models import Record
from apps.lists.services import access, grid, process

PAGE = 50


def _ordering(gp):
    """Выражение порядка внутри колонки — то же, что у таблицы (число, название, поле, стадия)."""
    if gp.sort == "title":
        return F("title").desc() if gp.dir == "desc" else F("title").asc()
    if gp.sort in ("", "number", "stage"):
        return F("number").desc() if gp.dir == "desc" else F("number").asc()
    queryset, key = grid._sort_expression(Record.objects.none(), gp)
    return key.desc(nulls_last=True) if gp.dir == "desc" else key.asc(nulls_last=True)


def _annotated(lst, viewer, gp):
    base = grid.records(lst, viewer, replace(gp, preset="all")).order_by()
    return base.annotate(
        stage_total=Window(Count("pk"), partition_by=F("stage_id")),
        stage_row=Window(RowNumber(), partition_by=F("stage_id"), order_by=_ordering(gp)))


def _column(key, title, kind, rows, total, *, offset=0):
    return {"key": key, "title": title, "kind": kind, "rows": rows[:PAGE], "count": total,
            "has_next": len(rows) > PAGE, "offset": offset}


def columns(lst, viewer, gp) -> list[dict]:
    """Колонки доски: читаемые стадии по порядку плюс «Без стадии»."""
    base = _annotated(lst, viewer, gp).filter(stage_row__lte=PAGE + 1)
    rows = list(base)
    by_stage = {}
    for row in rows:
        by_stage.setdefault(row.stage_id, []).append(row)
    totals = {row.stage_id: row.stage_total for row in rows}
    # пустые стадии в оконной выборке не встречаются — один запрос счётчиков для них
    if any(stage.pk not in totals for stage in process.visible_stages(lst)):
        for row in (grid.records(lst, viewer, replace(gp, preset="all")).order_by()
                    .values("stage").annotate(total=Count("pk"))):
            totals.setdefault(row["stage"], row["total"])
    result = []
    for stage in process.visible_stages(lst):
        if not access.can_read_stage(viewer, lst, stage.pk):
            continue
        result.append(_column(str(stage.pk), stage.title, stage.kind, by_stage.get(stage.pk, []),
                              totals.get(stage.pk, 0)))
    if totals.get(None, 0):
        result.append(_column("none", "Без стадии", "none", by_stage.get(None, []), totals.get(None, 0)))
    return result


def column(lst, viewer, gp, key: str, offset: int = 0) -> dict:
    """Страница одной колонки; `key` — номер стадии или `none`."""
    base = _annotated(lst, viewer, gp)
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
    rows = list(base.filter(stage_row__gt=offset, stage_row__lte=offset + PAGE + 1))
    total = rows[0].stage_total if rows else 0
    return _column(key, title, kind, rows, total, offset=offset)
