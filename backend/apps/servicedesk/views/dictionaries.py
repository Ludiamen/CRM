"""Справочники сервис-деска: `/servicedesk/dictionaries/<вид>/…` (CONTRACT-003, 12.6, 13.7).

Право `servicedesk.manage` проверяется раньше вида и записи. Вид в пути — `categories`, `priorities`, `complexities`,
`statuses`, `sources`, `client-units`; чужой вид — 404, запись другого вида — 404. Отказ службы — 200 со списком
(или формой) и `[role=alert][data-code]`; успех — 302 на список вида и разовое сообщение.
"""
from django.contrib.auth import get_user_model
from django.http import Http404, HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.services.permissions import require_permission
from apps.core.views.common import flash, is_fragment, render_page

from ..models import Status
from ..services import dictionaries, queues
from ..services.errors import ServiceDeskError
from .settings import CONFIRM_REQUIRED, MANAGE, _int

# вид в пути -> (вид службы, заголовок страницы)
KINDS = {
    "categories": ("category", "Категории"),
    "priorities": ("priority", "Критичность"),
    "complexities": ("complexity", "Сложность"),
    "statuses": ("status", "Статусы"),
    "sources": ("source", "Источники"),
    "client-units": ("client_unit", "Подразделения заявителей"),
}
STATUS_KINDS = ("new", "in_progress", "waiting", "closed")
KIND_TITLES = dict(Status.Kind.choices)


def _kind(path_kind: str) -> str:
    if path_kind not in KINDS:
        raise Http404
    return KINDS[path_kind][0]


def _list_url(path_kind: str) -> str:
    return f"/servicedesk/dictionaries/{path_kind}/"


def _item(kind: str, item_id: int):
    item = dictionaries.model_of(kind).objects.filter(pk=item_id).first()
    if item is None:
        raise Http404
    return item


def _is_system(kind: str, item) -> bool:
    return (kind == "category" and item.is_system) or (kind in ("status", "source") and bool(item.system_code))


def _rows(kind: str) -> list[dict]:
    model = dictionaries.model_of(kind)
    queryset = model.objects.order_by("name") if kind == "client_unit" else model.objects.order_by("order", "name")
    if kind == "category":
        queryset = queryset.select_related("queue", "default_assignee")
    return [{"item": item, "system": _is_system(kind, item),
             "kind_title": KIND_TITLES.get(item.kind, "") if kind == "status" else ""} for item in queryset]


def _assignee_choices() -> list:
    """Кандидаты в ответственные по умолчанию: все действующие сотрудники (доп. 42 (г)); участие проверяет служба."""
    return list(get_user_model().objects.exclude(state__in=("blocked", "dismissed"))
                .order_by("full_name", "id"))


def _form_context(kind: str, item, values: dict) -> dict:
    context = {"item": item, "values": values, "system": bool(item) and _is_system(kind, item),
               "status_kinds": [(code, KIND_TITLES[code]) for code in STATUS_KINDS]}
    if kind == "category":
        context["queue_choices"] = queues.marked_units()
        context["assignee_choices"] = _assignee_choices()
    return context


def _initial(kind: str, item) -> dict:
    if item is None:
        return {"name": "", "order": "0", "queue": "", "default_assignee": "", "on_form": "", "kind": "in_progress",
                "is_default": ""}
    values = {"name": item.name, "order": str(getattr(item, "order", ""))}
    if kind == "category":
        values.update(queue=str(item.queue_id or ""), default_assignee=str(item.default_assignee_id or ""),
                      on_form="1" if item.on_form else "")
    if kind == "status":
        values.update(kind=item.kind, is_default="1" if item.is_default else "")
    return values


def _page(request, path_kind: str, *, error=None, slider=None, dialog=None, status=200):
    kind = KINDS[path_kind][0]
    context = {"nav_active": "dictionaries", "path_kind": path_kind, "kind": kind, "title": KINDS[path_kind][1],
               "tabs": [(path, title) for path, (_, title) in KINDS.items()], "rows": _rows(kind),
               "error": error, "slider": slider, "dialog": dialog}
    return render_page(request, "servicedesk/settings/dictionary_list.html", context, status=status)


def _fragment(request, template: str, context: dict, status=200):
    response = render(request, template, context, status=status)
    response["Vary"] = "HX-Request"
    return response


def _alert(error: ServiceDeskError) -> dict:
    return {"code": error.code, "message": error.message}


def _slider_response(request, path_kind: str, kind: str, item, values: dict, error=None, status=200):
    slider = {**_form_context(kind, item, values), "path_kind": path_kind, "kind": kind, "error": error,
              "action": _list_url(path_kind) + (f"{item.pk}/edit/" if item else "new/"),
              "close_url": _list_url(path_kind), "title": KINDS[path_kind][1]}
    if is_fragment(request):
        return _fragment(request, "servicedesk/settings/_slider.html", {"slider": slider}, status=status)
    return _page(request, path_kind, slider=slider, status=status)


def _extra(kind: str, post, item) -> dict:
    """Поля службы из формы: по виду; `kind` статуса — только при создании; `queue_id` у системной категории не идёт."""
    extra = {}
    if kind == "category":
        if item is None or not item.is_system:
            extra["queue_id"] = _int(post.get("queue"))
        raw = (post.get("default_assignee") or "").strip()
        if not raw:
            extra["default_assignee"] = None
        else:
            user = get_user_model().objects.filter(pk=_int(raw)).first()
            if user is None:
                raise ServiceDeskError("assignee_not_participant",
                                       "Ответственный по умолчанию должен быть участником очереди категории")
            extra["default_assignee"] = user
        extra["on_form"] = bool(post.get("on_form"))
    elif kind == "status":
        if item is None:
            if post.get("kind") not in STATUS_KINDS:
                raise ServiceDeskError("bad_kind", "Выберите вид статуса")
            extra["kind"] = post.get("kind")
        if post.get("is_default"):
            extra["is_default"] = True
    return extra


def _order(kind: str, post, default):
    """Порядок из формы: пусто — `default`, не целое — отказ."""
    if kind == "client_unit":
        return None
    raw = (post.get("order") or "").strip()
    if not raw:
        return default
    number = _int(raw)
    if number is None:
        raise ServiceDeskError("bad_order", "Порядок — целое число")
    return number


def _save(request, path_kind: str, item):
    kind = KINDS[path_kind][0]
    post = request.POST
    values = {key: post.get(key, "") for key in ("name", "order", "queue", "default_assignee", "on_form", "kind",
                                                  "is_default")}
    if item is not None and kind == "status":
        values["kind"] = item.kind
    try:
        extra = _extra(kind, post, item)
        if item is None:
            order = _order(kind, post, 0)
            fields = {} if order is None else {"order": order}
            created = dictionaries.create(kind, name=post.get("name", ""), actor=request.user, ip=request.client_ip,
                                          **fields, **extra)
            text = f"Значение «{created.name}» добавлено."
        else:
            updated = dictionaries.update(item, name=post.get("name", ""), order=_order(kind, post, None),
                                          actor=request.user, ip=request.client_ip, **extra)
            text = f"Значение «{updated.name}» сохранено."
    except ServiceDeskError as error:
        return _slider_response(request, path_kind, kind, item, values, _alert(error))
    flash(request, text)
    return HttpResponseRedirect(_list_url(path_kind))


@require_permission(MANAGE)
@require_http_methods(["GET"])
def dictionary_list(request, kind):
    """`/servicedesk/dictionaries/<вид>/` — все значения вида: действующие и архивные с меткой."""
    _kind(kind)
    return _page(request, kind)


@require_permission(MANAGE)
@require_http_methods(["GET", "POST"])
def dictionary_new(request, kind):
    """`…/new/` — форма значения в слайдере; POST — создание."""
    service_kind = _kind(kind)
    if request.method == "POST":
        return _save(request, kind, None)
    return _slider_response(request, kind, service_kind, None, _initial(service_kind, None))


@require_permission(MANAGE)
@require_http_methods(["GET", "POST"])
def dictionary_edit(request, kind, item_id):
    """`…/<id>/edit/` — форма правки; POST — сохранение (`kind` статуса отбрасывается)."""
    service_kind = _kind(kind)
    item = _item(service_kind, item_id)
    if request.method == "POST":
        return _save(request, kind, item)
    return _slider_response(request, kind, service_kind, item, _initial(service_kind, item))


def _simple(request, kind, item_id, action, text):
    service_kind = _kind(kind)
    item = _item(service_kind, item_id)
    try:
        action(item, actor=request.user, ip=request.client_ip)
    except ServiceDeskError as error:
        return _page(request, kind, error=_alert(error))
    flash(request, f"Значение «{item.name}» {text}.")
    return HttpResponseRedirect(_list_url(kind))


@require_permission(MANAGE)
@require_POST
def dictionary_archive(request, kind, item_id):
    """`…/<id>/archive/` — убрать значение в архив."""
    return _simple(request, kind, item_id, dictionaries.archive, "убрано в архив")


@require_permission(MANAGE)
@require_POST
def dictionary_restore(request, kind, item_id):
    """`…/<id>/restore/` — вернуть значение из архива."""
    return _simple(request, kind, item_id, dictionaries.restore, "возвращено из архива")


@require_permission(MANAGE)
@require_http_methods(["GET", "POST"])
def dictionary_delete(request, kind, item_id):
    """`…/<id>/delete/` — диалог; POST с `confirm=1` — удаление."""
    service_kind = _kind(kind)
    item = _item(service_kind, item_id)
    dialog = {"item": item, "action": _list_url(kind) + f"{item.pk}/delete/", "error": None}
    if request.method == "GET":
        return _delete_dialog(request, kind, dialog)
    if request.POST.get("confirm") != "1":
        dialog["error"] = {"code": "confirm_required", "message": CONFIRM_REQUIRED}
        return _delete_dialog(request, kind, dialog)
    name = item.name
    try:
        dictionaries.delete(item, actor=request.user, ip=request.client_ip)
    except ServiceDeskError as error:
        return _page(request, kind, error={**_alert(error), "archive_item": item if error.code == "in_use" else None})
    flash(request, f"Значение «{name}» удалено.")
    return HttpResponseRedirect(_list_url(kind))


def _delete_dialog(request, path_kind, dialog):
    if is_fragment(request) and request.method == "GET":
        return _fragment(request, "servicedesk/settings/_delete_dialog.html", {"dialog": dialog})
    return _page(request, path_kind, dialog=dialog)
