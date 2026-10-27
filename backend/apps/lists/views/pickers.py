"""Подсказки людей и узлов для полей «сотрудник», «подразделение» и вкладки «Права» (T-6214a; PLAN-006, «Контракты»;
CONTRACT-006, 10.2, 15.4 п. 6).

Только правящему хотя бы один список или управляющему, остальным — 404. Люди — действующие сотрудники, только ФИО и
должность (без почты и телефона, решение плана о ПДн); узлы — название и путь. Не больше 20 строк, `q` без
минимальной длины.
"""
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.http import Http404
from django.views.decorators.http import require_GET

from apps.core.models import UserState
from apps.core.views.common import render_page
from apps.lists.models import Record
from apps.lists.services import access

LIMIT = 20


def _query(request) -> str:
    return " ".join(request.GET.get("q", "").split())


def _gate(request) -> None:
    if not access.edits_any(request.user):
        raise Http404("Страница не найдена")


@login_required
@require_GET
def people(request):
    """Действующие сотрудники: ФИО и должность."""
    _gate(request)
    found = get_user_model().objects.filter(state=UserState.ACTIVE)
    text = _query(request)
    if text:
        found = found.filter(full_name__icontains=text)
    rows = [{"id": user.pk, "title": user.full_name, "note": user.position}
            for user in found.order_by("full_name", "pk")[:LIMIT]]
    return render_page(request, "lists/_pick.html", {"rows": rows, "kind": "people"})


@login_required
@require_GET
def units(request):
    """Узлы структуры: название и путь словами от корня; без модуля `org` список пуст."""
    _gate(request)
    rows = []
    if apps.is_installed("apps.org"):
        from apps.org.services import structure

        refs = structure.all_units()
        names = {ref.id: ref.name for ref in refs}
        wanted = _query(request).casefold()
        for ref in refs:
            chain = [names.get(int(part), "") for part in ref.path.strip("/").split("/") if part.isdigit()]
            path = " / ".join(chain)
            if wanted and wanted not in ref.name.casefold() and wanted not in path.casefold():
                continue
            rows.append({"id": ref.id, "title": ref.name, "note": path})
            if len(rows) >= LIMIT:
                break
    return render_page(request, "lists/_pick.html", {"rows": rows, "kind": "units"})


@login_required
@require_GET
def record(request, list_id: int):
    """Записи целевого списка не в архиве по названию или номеру: «Название — №N», до 20 строк (только читающим список)."""
    lst = access.get_list(request.user, list_id)
    found = Record.objects.filter(list=lst, archived=False)
    text = _query(request)
    if text:
        match = Q(title__icontains=text)
        if text.isascii() and text.isdigit() and len(text) <= 9:
            match |= Q(number=int(text))
        found = found.filter(match)
    rows = [{"id": item.pk, "title": f"{item.title} — №{item.number}", "note": ""}
            for item in found.order_by("title", "number")[:LIMIT]]
    return render_page(request, "lists/_pick.html", {"rows": rows, "kind": "record"})
