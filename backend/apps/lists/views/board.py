"""Доска «Стадии»: страница, колонка и перенос карточки (срез 015; PLAN-015, «Доска»)."""
from urllib.parse import urlencode

from django.contrib.auth.decorators import login_required
from django.http import Http404, JsonResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_GET, require_POST

from apps.core.views.common import is_fragment, render_page
from apps.lists.models import Record
from apps.lists.services import access, board as board_service, grid, process, transitions
from apps.lists.services.errors import ListsError

from .home import done


def _read(request, lst):
    return grid.read(request.GET, lst, request.user)


def _params(request, base: dict) -> str:
    data = {name: value for name, value in request.GET.items()}
    data.update(base)
    return urlencode(data)


@login_required
@require_GET
def board(request, list_id: int):
    lst = access.get_list(request.user, list_id)
    proc = process.get_process(lst)
    if proc is None or not proc.enabled:
        raise Http404("Процесса нет")
    gp = _read(request, lst)
    columns = board_service.columns(lst, request.user, gp)
    context = {"lst": lst, "proc": proc, "board_columns": columns,
               "board_params": _params(request, {"view": "board"}),
               "can_create": access.can_edit(request.user, lst)}
    return render_page(request, "lists/board/page.html", context)


@login_required
@require_GET
def column(request, list_id: int, key: str):
    lst = access.get_list(request.user, list_id)
    gp = _read(request, lst)
    offset = int(request.GET.get("offset", "0")) if request.GET.get("offset", "0").isdigit() else 0
    found = board_service.column(lst, request.user, gp, key, offset)
    return render_page(request, "lists/board/_column.html",
                       {"lst": lst, "column": found, "board_params": _params(request, {"view": "board"})})


@login_required
@require_POST
def move(request, list_id: int):
    lst = access.get_list(request.user, list_id)
    raw = str(request.POST.get("number", ""))
    record = Record.objects.filter(list=lst, number=int(raw)).first() if raw.isdigit() else None
    if record is None or not access.can_read_record(request.user, record):
        return JsonResponse({"error": "Запись не найдена", "code": "record_absent"}, status=404)
    raw_stage = str(request.POST.get("stage", ""))
    if not raw_stage.isdigit():
        return JsonResponse({"error": "Стадия не найдена", "code": "stage_absent"}, status=404)
    try:
        transitions.move(record, int(raw_stage), base_version=int(request.POST.get("base_version", "0") or 0),
                         expected_stage=request.POST.get("expected") or record.stage_id, actor=request.user)
    except ListsError as refused:
        if request.headers.get("Accept", "").startswith("application/json"):
            return JsonResponse({"error": refused.message, "code": refused.code}, status=409)
        gp = _read(request, lst)
        return render_page(request, "lists/board/page.html",
                           {"lst": lst, "board_columns": board_service.columns(lst, request.user, gp),
                            "board_params": _params(request, {"view": "board"}), "alert": refused})
    gp = _read(request, lst)
    if request.headers.get("Accept", "").startswith("application/json"):
        return JsonResponse({"ok": True, "number": record.number, "stage": int(raw_stage)})
    if request.headers.get("HX-Request"):
        return render_page(request, "lists/board/_board.html",
                           {"lst": lst, "board_columns": board_service.columns(lst, request.user, gp),
                            "board_params": _params(request, {"view": "board"})})
    return redirect(f"/lists/{lst.pk}/board/?{_params(request, {})}")
