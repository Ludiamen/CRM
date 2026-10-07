"""Настройки и очереди сервис-деска: `/servicedesk/` и `/servicedesk/queues/` (CONTRACT-003, 12.6, 13.7).

Право `servicedesk.manage` проверяется раньше всего остального. Дерево узлов берётся из служб `org.structure`
(моделей `org` здесь нет), отметки — из службы `queues`. Отказ службы — ответ 200 с `[role=alert][data-code]`,
успех — 302 на тот же адрес и разовое сообщение.
"""
from django.conf import settings as dj_settings
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from apps.core.services.permissions import require_permission
from apps.core.views.common import flash, is_fragment, render_page
from apps.org.services import structure

from ..models import Priority
from ..services import mailbox, queues
from ..services import settings as sd_settings
from ..services.errors import ServiceDeskError

MANAGE = "servicedesk.manage"
CONFIRM_REQUIRED = "Подтвердите действие"
SETTINGS_URL = "/servicedesk/"
QUEUES_URL = "/servicedesk/queues/"
INT_FIELDS = ("autoclose_days", "reopen_days", "form_hourly_limit", "retention_years", "inbound_retention_days")
MAX_DEPTH = 8


def _int(raw):
    """Целое из строки или `None` (пусто, нечисло)."""
    try:
        return int(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _redirect(url: str):
    return HttpResponseRedirect(url)


def _alert(error: ServiceDeskError) -> dict:
    return {"code": error.code, "message": error.message}


# --- настройки -----------------------------------------------------------------------------------

def _settings_context(*, values=None, error=None) -> dict:
    """Контекст страницы настроек: поля формы (текущие или присланные), состояние ящика, очередь по умолчанию."""
    row = sd_settings.get()
    state = mailbox.status()
    if values is None:
        values = {"domains": "\n".join(row.domains), "default_priority": str(row.default_priority_id),
                  **{name: str(getattr(row, name)) for name in INT_FIELDS}}
    priorities = [p for p in Priority.objects.order_by("order", "name")
                  if not p.archived or str(p.pk) == values.get("default_priority")]
    default_id = queues.default_unit_id()
    default_name = next((u.name for u in queues.marked_units() if u.id == default_id), "") if default_id else ""
    return {"nav_active": "settings", "values": values, "priorities": priorities, "error": error,
            "mailbox_address": sd_settings.mailbox_address(), "last_ok_at": state.last_ok_at,
            "last_error": state.last_error, "default_queue_name": default_name,
            "imap_none": dj_settings.IMAP_SECURITY == "none"}


@require_permission(MANAGE)
@require_http_methods(["GET", "POST"])
def settings_page(request):
    """`/servicedesk/` — форма настроек; адрес ящика и очередь по умолчанию только показываются."""
    if request.method == "GET":
        return render_page(request, "servicedesk/settings/settings.html", _settings_context())
    post = request.POST
    values = {"domains": post.get("domains", ""), "default_priority": post.get("default_priority", ""),
              **{name: post.get(name, "") for name in INT_FIELDS}}
    fields = {name: post[name] for name in INT_FIELDS if name in post}
    try:
        if "domains" in post:
            fields["domains"] = post["domains"]
        if "default_priority" in post:
            priority = Priority.objects.filter(pk=_int(post["default_priority"])).first()
            if priority is None:
                raise ServiceDeskError("archived_value", "Выберите критичность из списка")
            fields["default_priority"] = priority
        sd_settings.update(actor=request.user, ip=request.client_ip, **fields)
    except ServiceDeskError as error:
        return render_page(request, "servicedesk/settings/settings.html",
                           _settings_context(values=values, error=_alert(error)))
    flash(request, "Настройки сохранены.")
    return _redirect(SETTINGS_URL)


# --- очереди -------------------------------------------------------------------------------------

def _tree():
    """Узлы структуры с отметками: по `path`, глубина — по числу звеньев пути."""
    marked = {unit.id for unit in queues.marked_units()}
    default_id = queues.default_unit_id()
    nodes = []
    for unit in structure.descendants(structure.root()):
        depth = max(unit.path.count("/") - 2, 0)
        nodes.append({"id": unit.pk, "name": unit.name, "depth": min(depth, MAX_DEPTH),
                      "queue": unit.pk in marked, "default": unit.pk == default_id})
    return nodes


def _queues_context(*, error=None, dialog=None) -> dict:
    return {"nav_active": "queues", "tree": _tree(), "error": error, "dialog": dialog}


def _unmark_dialog(unit_id: int) -> dict:
    """Диалог снятия отметки: число открытых заявок и категории; не очередь — 404, нет очереди по умолчанию — отказ."""
    unit = next((u for u in queues.marked_units() if u.id == unit_id), None)
    if unit is None:
        raise Http404
    try:
        preview = queues.unmark_preview(unit_id)
    except ServiceDeskError as error:
        if error.code == "not_queue":
            raise Http404 from None
        return {"unit": unit, "error": _alert(error), "blocked": True}
    default_id = queues.default_unit_id()
    default_name = next((u.name for u in queues.marked_units() if u.id == default_id), "")
    return {"unit": unit, "open_tickets": preview.open_tickets, "categories": preview.categories,
            "default_name": default_name, "blocked": False}


def _queues_response(request, *, error=None, dialog=None, status=200):
    if dialog is not None and is_fragment(request) and request.method == "GET":
        response = render(request, "servicedesk/settings/_unmark_dialog.html", {"dialog": dialog}, status=status)
        response["Vary"] = "HX-Request"
        return response
    return render_page(request, "servicedesk/settings/queues.html", _queues_context(error=error, dialog=dialog),
                       status=status)


@require_permission(MANAGE)
@require_http_methods(["GET", "POST"])
def queues_page(request):
    """`/servicedesk/queues/` — дерево узлов, отметка очереди, очередь по умолчанию, диалог снятия `?unmark=<id>`."""
    if request.method == "GET":
        raw = request.GET.get("unmark")
        if raw is None:
            return _queues_response(request)
        unit_id = _int(raw)
        if unit_id is None:
            raise Http404
        return _queues_response(request, dialog=_unmark_dialog(unit_id))
    action, unit_id = request.POST.get("action", ""), _int(request.POST.get("unit"))
    if action not in ("mark", "unmark", "default"):
        return _queues_response(request, error={"code": "bad_action", "message": "Неизвестное действие"})
    if unit_id is None:
        return _queues_response(request, error={"code": "not_queue", "message": "Выберите узел структуры"})
    try:
        if action == "mark":
            queues.mark(unit_id, actor=request.user, ip=request.client_ip)
            text = "Узел отмечен очередью."
        elif action == "default":
            queues.set_default(unit_id, actor=request.user, ip=request.client_ip)
            text = "Очередь по умолчанию выбрана."
        else:
            if request.POST.get("confirm") != "1":
                try:
                    dialog = _unmark_dialog(unit_id)
                except Http404:
                    raise ServiceDeskError("not_queue", "Этот узел не отмечен очередью сервис-деска") from None
                if not dialog.get("blocked"):
                    dialog["error"] = {"code": "confirm_required", "message": CONFIRM_REQUIRED}
                return _queues_response(request, error=dialog["error"], dialog=dialog)
            queues.unmark(unit_id, actor=request.user, ip=request.client_ip)
            text = "Отметка очереди снята."
    except ServiceDeskError as error:
        return _queues_response(request, error=_alert(error))
    flash(request, text)
    return _redirect(QUEUES_URL)
