"""Страница таблицы записей: отборы, фильтры, поиск, столбцы, групповое «В архив» и значения фильтра (T-6216; PLAN-006,
«Таблица записей», «Контракты»; CONTRACT-006, 10.1–10.4, 11.3, 12, 15.2, 15.5, 15.6, решение 60).

Полная страница или, при `HX-Target: lists-grid`, фрагмент сетки (`Vary: HX-Request`). Список не читается — 404 (как
несуществующий); читается, а действия нет — 403 (отвечает служба). Подписи людей, узлов, записей и числа файлов
собираются пачкой на страницу: по одному запросу на ссылочное поле (заметка R-6213).
"""
from urllib.parse import urlencode

from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404, QueryDict
from django.shortcuts import redirect
from django.views.decorators.http import require_GET, require_POST

from apps.core.models import UserState
from apps.core.views.common import is_fragment, render_page
from apps.core.widgets import PortalDateInput
from apps.lists.models import Choice, List, Record, RecordFile, UserView
from apps.lists.services import access, archive as archive_service, grid as grid_service, schema
from apps.lists.services import export as export_service
from apps.lists.services import values as values_service
from apps.lists.services.errors import ListsError
from apps.lists.texts import TEXTS

PRESET_TITLES = {"all": "Все", "expiring": "Истекает", "mine": "Закреплено за мной", "archive": "Архив"}
REFERENCE_TYPES = ("choice", "person", "unit", "record")
PICK_LIMIT = 20
HINTS = {"short": "query_short", "long": "query_long"}


def _ascii_int(raw) -> int | None:
    text = str(raw or "")
    return int(text) if text.isascii() and text.isdigit() and len(text) <= 9 else None


# --- подписи значений (пачкой на страницу) ----------------------------------------------------------------

UNAVAILABLE = "запись недоступного списка"  # подпись ссылки на запись нечитаемого списка в ячейке таблицы


def _labels(field, ids, viewer) -> dict:
    """Строки показа ссылочных значений поля: код -> текст (одна выборка на поле)."""
    kind = field.type
    if kind == "choice":
        return dict(Choice.objects.filter(field=field, pk__in=ids).values_list("pk", "title"))
    if kind == "person":
        return {user.pk: user.full_name + (" (уволен)" if user.state == UserState.DISMISSED else "")
                for user in get_user_model().objects.filter(pk__in=ids)}
    if kind == "unit":
        refs = {}
        if apps.is_installed("apps.org"):
            from apps.org.services import structure

            refs = structure.unit_refs(ids)
        return {pk: refs[pk].name if pk in refs else f"узел №{pk}" for pk in ids}
    found = {}
    readable: dict[int, bool] = {}
    for record in Record.objects.filter(pk__in=ids):
        if record.list_id not in readable:
            readable[record.list_id] = access.can_read(viewer, List(pk=record.list_id))
        found[record.pk] = (f"{record.title} — №{record.number}" + (" (в архиве)" if record.archived else "")
                            if readable[record.list_id] else UNAVAILABLE)
    return found


def _cells(rows, fields, viewer) -> list[dict]:
    """Строки таблицы: у каждой запись и ячейки по столбцам `fields` (без «Названия»)."""
    labels: dict[int, dict] = {}
    counts: dict[tuple, int] = {}
    for field in fields:
        if field.type in REFERENCE_TYPES:
            ids = {pk for row in rows for pk in (row.values or {}).get(field.code) or [] if isinstance(pk, int)}
            labels[field.pk] = _labels(field, list(ids), viewer) if ids else {}
    file_fields = [field.pk for field in fields if field.type == "file"]
    if file_fields and rows:
        found = (RecordFile.objects.filter(record_id__in=[row.pk for row in rows], field_id__in=file_fields)
                 .values("record_id", "field_id").annotate(total=Count("pk")))
        counts = {(item["record_id"], item["field_id"]): item["total"] for item in found}
    result = []
    for row in rows:
        cells = []
        for field in fields:
            stored = (row.values or {}).get(field.code)
            parts = None
            if field.type == "file":
                total = counts.get((row.pk, field.pk), 0)
                text = str(total) if total else ""
            elif field.type in REFERENCE_TYPES:
                names = labels[field.pk]
                parts = [{"text": names[pk], "unavailable": field.type == "record" and names[pk] == UNAVAILABLE}
                         for pk in stored or [] if isinstance(pk, int) and pk in names]
                text = "; ".join(part["text"] for part in parts)
            else:
                text = values_service.display(field, stored, viewer)
            # `parts` — значения ссылочного поля по одному: запись нечитаемого списка выводится с пометкой (11.5)
            cells.append({"code": field.code, "text": text, "long": field.type == "text", "parts": parts})
        result.append({"record": row, "cells": cells})
    return result


# --- параметры, ссылки, фильтры ------------------------------------------------------------------------------

def _pairs(gp, **over) -> list[tuple[str, str]]:
    """Параметры адреса таблицы по разобранным: отбор, поиск, фильтры, порядок; `over` заменяет или (`None`) убирает."""
    data: dict = {"preset": gp.preset, "q": gp.q, "sort": gp.sort, "dir": gp.dir if gp.sort else ""}
    data.update(over)
    pairs = [(name, str(value)) for name, value in data.items() if value not in (None, "") and
             not (name == "preset" and value == "all")]
    for name, items in (gp.values or {}).items():
        pairs.extend((name, item) for item in items)
    return pairs


def _url(lst, gp, **over) -> str:
    pairs = _pairs(gp, **over)
    return f"/lists/{lst.pk}/" + (f"?{urlencode(pairs)}" if pairs else "")


def _headers(lst, gp, columns, viewer) -> list[dict]:
    """Заголовки: «Название» и столбцы; у сортируемых — ссылка (повторное нажатие меняет направление)."""
    heads = [{"code": "title", "name": "Название", "sortable": True}]
    heads += [{"code": field.code, "name": field.name, "sortable": grid_service.sortable(field, viewer)}
              for field in columns]
    for head in heads:
        if not head["sortable"]:
            continue
        current = gp.sort == head["code"]
        head["current"] = current
        head["dir"] = gp.dir if current else ""
        head["href"] = _url(lst, gp, sort=head["code"], dir="desc" if current and gp.dir == "asc" else "asc", page=None)
    return heads


def _filters(lst, gp, viewer) -> list[dict]:
    """Фильтры формы: «Название» и видимые поля по их типу; принятые значения берутся из `gp.values`."""
    shown = gp.values or {}

    def one(name):
        return (shown.get(name) or [""])[0]

    rows = [{"code": "title", "name": "Название", "kind": "text", "value": one("f.title")}]
    for field in gp.fields:
        name, kind = f"f.{field.code}", field.type
        row = {"code": field.code, "name": field.name, "kind": kind, "param": name}
        if kind in ("string", "text"):
            row.update(kind="text", value=one(name))
        elif kind in ("number", "money", "datetime"):
            row.update(kind="range", start=one(f"{name}.from"), end=one(f"{name}.to"))
        elif kind == "date":
            row.update(kind="range", date=True,
                       start_html=PortalDateInput().render(f"{name}.from", one(f"{name}.from"),
                                                           attrs={"id": f"lists-filter-{field.code}-from"}),
                       end_html=PortalDateInput().render(f"{name}.to", one(f"{name}.to"),
                                                         attrs={"id": f"lists-filter-{field.code}-to"}))
        elif kind == "bool":
            row.update(value=one(name))
        elif kind == "file":
            row.update(param=f"{name}.files", value=one(f"{name}.files"))
        else:
            row.update(kind="pick", url=f"/lists/{lst.pk}/filter-values/{field.code}/",
                       selected=_selected(field, shown.get(name) or [], viewer))
        rows.append(row)
    return rows


def _selected(field, items, viewer) -> list[dict]:
    ids = [int(item) for item in items if item.isascii() and item.isdigit()]
    if not ids:
        return []
    names = _labels(field, ids, viewer)
    # запись нечитаемого списка в выбранных значениях фильтра — как несуществующая (К-10; правка Opus по R-6216)
    return [{"id": pk, "text": names[pk]} for pk in ids if pk in names and names[pk] != UNAVAILABLE]


# --- страница ------------------------------------------------------------------------------------------------

def _render(request, lst, params, *, notice=None, alert=None):
    viewer = request.user
    gp = grid_service.read(params, lst, viewer)
    page = grid_service.page(grid_service.records(lst, viewer, gp), gp)
    codes = grid_service.columns(lst, viewer)
    by_code = {field.code: field for field in gp.fields}
    columns = [by_code[code] for code in codes if code in by_code]
    chosen = {field.code for field in columns}
    spare = [field for field in gp.fields if field.code not in chosen]
    plain = not gp.filters and not gp.q and gp.preset == "all"
    hint = TEXTS[HINTS[gp.search.hint]] if gp.search is not None and gp.search.hint in HINTS else ""
    can_edit = access.can_edit(viewer, lst)
    context = {
        "lst": lst, "gp": gp, "rows": _cells(page.rows, columns, viewer), "headers": _headers(lst, gp, columns, viewer),
        "found": page.found, "has_next": page.has_next, "page_number": gp.page,
        "next_url": _url(lst, gp, page=gp.page + 1), "prev_url": _url(lst, gp, page=gp.page - 1 or None),
        "presets": [{"code": code, "name": PRESET_TITLES[code], "current": code == gp.preset,
                     "href": _url(lst, gp, preset=code, page=None)} for code in grid_service.presets(gp.fields)],
        "filters": _filters(lst, gp, viewer), "reset_url": f"/lists/{lst.pk}/" + (
            f"?preset={gp.preset}" if gp.preset != "all" else ""),
        "column_choices": [{"field": field, "checked": field.code in chosen} for field in columns + spare],
        "hint": hint, "can_edit": can_edit, "can_manage": access.can_manage(viewer),
        "empty_text": TEXTS["grid_empty"], "empty_plain": plain, "stale_text": TEXTS["vectors_stale"],
        "stale": lst.vectors_stale_since is not None, "notice": notice, "alert": alert,
    }
    template = "lists/_grid.html" if is_fragment(request) and request.headers.get("HX-Target") == "lists-grid" \
        else "lists/grid.html"
    return render_page(request, template, context)


@login_required
@require_GET
def grid(request, list_id: int):
    """Таблица записей списка (полная страница или фрагмент сетки)."""
    lst = access.get_list(request.user, list_id)
    return _render(request, lst, request.GET)


@login_required
@require_POST
def columns(request, list_id: int):
    """Выбор столбцов сотрудника для списка: коды видимых полей и `title`, порядок как прислан; без повторов."""
    lst = access.get_list(request.user, list_id)
    allowed = {field.code for field in schema.visible_fields(lst)} | {"title"}
    chosen: list[str] = []
    for code in request.POST.getlist("columns"):
        if code in allowed and code not in chosen:
            chosen.append(code)
    UserView.objects.update_or_create(user=request.user, list=lst, defaults={"columns": chosen})
    if is_fragment(request):
        return _render(request, lst, QueryDict())
    return redirect(f"/lists/{lst.pk}/")


@login_required
@require_POST
def bulk_archive(request, list_id: int):
    """Групповое «В архив» отмеченных строк: страница таблицы с итогом «В архив: N, пропущено: M» либо отказом."""
    lst = access.get_list(request.user, list_id)
    numbers = [number for number in (_ascii_int(raw) for raw in request.POST.getlist("n")) if number is not None]
    try:
        result = archive_service.bulk_archive(lst, numbers, actor=request.user)
    except ListsError as error:
        return _render(request, lst, QueryDict(), alert=error)
    notice = TEXTS["bulk_result"].format(archived=result.archived, skipped=result.skipped)
    return _render(request, lst, QueryDict(), notice=notice)


# --- значения фильтра ----------------------------------------------------------------------------------------

@login_required
@require_GET
def filter_values(request, list_id: int, code: str):
    """Значения для выбора в фильтре ссылочного поля: до 20 строк, `q` — подстрока строки показа без учёта регистра."""
    lst = access.get_list(request.user, list_id)
    field = next((item for item in schema.visible_fields(lst) if item.code == code), None)
    if field is None or field.type not in REFERENCE_TYPES:
        raise Http404("Поле не найдено")
    wanted = " ".join(request.GET.get("q", "").split())
    rows: list[dict] = []
    if field.type == "choice":
        found = Choice.objects.filter(field=field)
        if wanted:
            found = found.filter(title__icontains=wanted)
        rows = [{"id": item.pk, "title": item.title, "note": "в архиве" if item.archived else ""}
                for item in found.order_by("archived", "order", "pk")[:PICK_LIMIT]]
    elif field.type == "person":
        found = get_user_model().objects.filter(state=UserState.ACTIVE)
        if wanted:
            found = found.filter(full_name__icontains=wanted)
        rows = [{"id": user.pk, "title": user.full_name, "note": user.position}
                for user in found.order_by("full_name", "pk")[:PICK_LIMIT]]
    elif field.type == "unit":
        rows = _unit_rows(wanted)
    else:
        target = List.objects.filter(pk=field.target_id).first()
        if target is None or not access.can_read(request.user, target):
            raise Http404("Список не найден")
        found = Record.objects.filter(list=target)
        number = _ascii_int(wanted)
        if wanted:
            match = Q(title__icontains=wanted)
            if number is not None:
                match |= Q(number=number)
            found = found.filter(match)
        rows = [{"id": item.pk, "title": f"{item.title} — №{item.number}", "note": "в архиве" if item.archived else ""}
                for item in found.order_by("title", "number")[:PICK_LIMIT]]
    return render_page(request, "lists/_pick.html", {"rows": rows, "kind": field.type})


def _unit_rows(wanted: str) -> list[dict]:
    """Узлы структуры: название и путь словами от корня; без модуля `org` список пуст."""
    rows: list[dict] = []
    if not apps.is_installed("apps.org"):
        return rows
    from apps.org.services import structure

    refs = structure.all_units()
    names = {ref.id: ref.name for ref in refs}
    needle = wanted.casefold()
    for ref in refs:
        chain = [names.get(int(part), "") for part in ref.path.strip("/").split("/") if part.isdigit()]
        path = " / ".join(chain)
        if needle and needle not in ref.name.casefold() and needle not in path.casefold():
            continue
        rows.append({"id": ref.id, "title": ref.name, "note": path})
        if len(rows) >= PICK_LIMIT:
            break
    return rows


# --- выгрузка в Excel (T-6220) ----------------------------------------------------------------------------

@login_required
@require_GET
def export(request, list_id: int):
    """Выгрузка набора таблицы в XLSX (параметры те же); записей больше предела — страница таблицы с отказом."""
    lst = access.get_list(request.user, list_id)
    try:
        return export_service.build(lst, request.user, request.GET)
    except ListsError as error:
        return _render(request, lst, request.GET, alert=error)
