"""Создание списка и настройка: вкладки «Основное» и «Права», удаление списка (T-6214a; PLAN-006, «Раздел и настройка
списка», «Права и видимость»; CONTRACT-006, 10.1, 10.2, 11.2, 15.4–15.5). Вкладка «Поля» и значения списка значений — T-6214b (конец файла).

Раздел закрыт — 404, раздел открыт, а настройки нет — 403 (FR-514). Отказ службы на POST — 200 со страницей, введённое
остаётся: у поля — `[data-error=<поле>][data-code=<код>]`, общий — `[role=alert][data-code=<код>]`.
"""
from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404
from django.utils.cache import patch_vary_headers
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.models import Role
from apps.core.views.common import is_fragment, render_page
from apps.lists.models import Access, Choice, Field, List
from apps.lists.services import access, schema, values as list_values
from apps.lists.services.errors import ListsError

from .home import done

FORM_FIELDS = ("name", "description")


def _require_manage(request) -> None:
    """Раздел закрыт — 404, нет права управляющего — 403."""
    if not access.sees_section(request.user):
        raise Http404("Раздел не найден")
    if not access.can_manage(request.user):
        raise PermissionDenied


def _manage_list(request, list_id: int) -> List:
    """Список, который управляющий настраивает: не читается — 404, не управляет — 403."""
    lst = access.get_list(request.user, list_id)
    if not access.can_manage(request.user):
        raise PermissionDenied
    return lst


def _refusal(error: ListsError, fields=FORM_FIELDS) -> tuple[dict, ListsError | None]:
    """Отказ у поля формы (`errors`) или общий (`alert`)."""
    if error.field in fields:
        return {error.field: error}, None
    return {}, error


# --- новый список -----------------------------------------------------------------------------------------------------

@login_required
@require_http_methods(["GET", "POST"])
def new(request):
    """Форма нового списка; POST — список и переход на «Настройку списка» (наборов прав у нового списка нет)."""
    _require_manage(request)
    values, errors, alert = {"name": "", "description": ""}, {}, None
    if request.method == "POST":
        values = {name: request.POST.get(name, "") for name in FORM_FIELDS}
        try:
            lst = schema.create_list(name=values["name"], description=values["description"], actor=request.user)
        except ListsError as refused:
            errors, alert = _refusal(refused)
        else:
            return done(request, f"/lists/{lst.pk}/settings/")
    return render_page(request, "lists/new.html", {"values": values, "errors": errors, "alert": alert})


# --- вкладка «Основное» и удаление ------------------------------------------------------------------------------------

def _main_page(request, lst: List, *, values=None, errors=None, alert=None):
    """Страница вкладки «Основное»: форма, кнопка удаления (недоступна, пока удалять нельзя) и пояснение."""
    blocker = schema.can_delete_list(lst)
    context = {"lst": lst, "tab": "main", "values": values or {"name": lst.name, "description": lst.description},
               "errors": errors or {}, "alert": alert, "delete_reason": blocker.message if blocker else ""}
    return render_page(request, "lists/settings_main.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def main(request, list_id: int):
    """Название и описание списка (`lists.list_changed`); успех — 302 на тот же адрес."""
    lst = _manage_list(request, list_id)
    if request.method == "POST":
        values = {name: request.POST.get(name, "") for name in FORM_FIELDS}
        try:
            schema.update_list(lst, name=values["name"], description=values["description"], actor=request.user)
        except ListsError as refused:
            errors, alert = _refusal(refused)
            return _main_page(request, lst, values=values, errors=errors, alert=alert)
        return done(request, f"/lists/{lst.pk}/settings/")
    return _main_page(request, lst)


@login_required
@require_POST
def delete(request, list_id: int):
    """Удаляет пустой список; отказ (`list_has_records`, `list_referenced`) — 200 со страницей «Основное» и общим
    отказом; успех — 302 на `/lists/`."""
    lst = _manage_list(request, list_id)
    try:
        schema.delete_list(lst, actor=request.user)
    except ListsError as refused:
        return _main_page(request, lst, alert=refused)
    return done(request, "/lists/")


# --- вкладка «Права» --------------------------------------------------------------------------------------------------

def _pairs(values) -> list[tuple[str, int]]:
    """`role:<id>` и `unit:<id>` из формы -> пары; всё иное — 404 (как неизвестный субъект в службе)."""
    result = []
    for value in values:
        kind, _, pk = str(value).partition(":")
        if kind not in ("role", "unit") or not (pk.isascii() and pk.isdigit()):
            raise Http404("Субъект не найден")
        result.append((kind, int(pk)))
    return result


def _subjects(lst: List, level: str) -> list[dict]:
    """Строки набора: значение `role:<id>` или `unit:<id>`, название, вид; по названию без учёта регистра."""
    rows = list(Access.objects.filter(list=lst, level=level))
    roles = {role.pk: role.name for role in Role.objects.filter(pk__in=[r.role_id for r in rows if r.role_id])}
    refs = {}
    unit_ids = [r.unit_id for r in rows if r.unit_id]
    if unit_ids and apps.is_installed("apps.org"):
        from apps.org.services import structure

        refs = structure.unit_refs(unit_ids)
    items = []
    for row in rows:
        if row.role_id:
            items.append({"value": f"role:{row.role_id}", "name": roles.get(row.role_id, ""), "kind": "role"})
        else:
            name = refs[row.unit_id].name if row.unit_id in refs else f"узел №{row.unit_id}"
            items.append({"value": f"unit:{row.unit_id}", "name": name, "kind": "unit"})
    return sorted(items, key=lambda item: (item["name"].casefold(), item["value"]))


def _access_page(request, lst: List, *, sets=None, alert=None):
    """Страница вкладки «Права»: наборы «Читают» и «Правят», выбор ролей; подразделения — подсказка `/lists/units/`."""
    sets = sets or {"read": _subjects(lst, Access.Level.READ), "edit": _subjects(lst, Access.Level.EDIT)}
    context = {"lst": lst, "tab": "access", "alert": alert, "roles": list(Role.objects.order_by("name", "pk")),
               "boxes": [{"level": "read", "title": "Читают", "field": "readers", "items": sets["read"]},
                         {"level": "edit", "title": "Правят", "field": "editors", "items": sets["edit"]}]}
    return render_page(request, "lists/settings_access.html", context)


@login_required
@require_http_methods(["GET", "POST"])
def access_tab(request, list_id: int):
    """Наборы «Читают» и «Правят» (роли и подразделения); успех — 302 на тот же адрес."""
    lst = _manage_list(request, list_id)
    if request.method == "POST":
        readers, editors = request.POST.getlist("readers"), request.POST.getlist("editors")
        try:
            schema.save_access(lst, readers=_pairs(readers), editors=_pairs(editors), actor=request.user)
        except ListsError as refused:
            sets = {"read": _typed(readers), "edit": _typed(editors)}
            return _access_page(request, lst, sets=sets, alert=refused)
        return done(request, f"/lists/{lst.pk}/settings/access/")
    return _access_page(request, lst)


def _typed(values) -> list[dict]:
    """Присланные значения наборов как строки для повторного показа формы после отказа (названия — из базы)."""
    result = []
    for kind, pk in _pairs(values):
        if kind == "role":
            role = Role.objects.filter(pk=pk).first()
            result.append({"value": f"role:{pk}", "name": role.name if role else "", "kind": "role"})
        else:
            result.append({"value": f"unit:{pk}", "name": f"узел №{pk}", "kind": "unit"})
    return result


# --- вкладка «Поля» (T-6214b) -----------------------------------------------------------------------------------------
# PLAN-006, «Поля и изменение схемы»; CONTRACT-006, 10.2, 11.2, 15.5 пп. 1, 7, 8, 13, 15, 15.6.

# Какие свойства показывает форма поля у типа (FR-508; совпадает с правилами службы `schema`).
TYPE_PROPS = {
    "string": ("required", "default", "unique"), "text": ("required",), "number": ("required", "default", "unique"),
    "money": ("required", "default", "currency"), "date": ("required", "default", "deadline"),
    "datetime": ("required",), "bool": ("default",), "choice": ("required", "multiple", "default"),
    "person": ("required", "multiple"), "unit": ("required", "multiple"),
    "record": ("required", "multiple", "target"), "file": ("multiple",),
}
DEFAULT_TYPES = frozenset({"string", "number", "money", "date", "bool", "choice"})
FLAGS = ("required", "multiple", "unique", "show_in_table", "deadline")
THRESHOLD_SLOTS = 3
FIELD_ERRORS = ("name", "hint", "type", "required", "multiple", "unique", "default", "currency", "target",
                "thresholds", "choices")
PROPS_TARGET = "lists-field-props"  # `HX-Target` запроса, который меняет только свойства по выбранному типу
TYPE_CHOICES = [(value, label) for value, label in Field.Type.choices]
CURRENCY_CHOICES = (("RUB", "Рубль"), ("USD", "Доллар"), ("EUR", "Евро"))


def _fields_url(lst: List) -> str:
    return f"/lists/{lst.pk}/settings/fields/"


def _get_field(lst: List, code: str) -> Field:
    """Поле списка по коду; кода нет (и `title` — системное «Название», строки `Field` у него нет) — 404."""
    return get_object_or_404(Field, list=lst, code=code)


def _fields_page(request, lst: List, *, alert=None):
    """Страница вкладки «Поля»: сетка полей (в блоке прокрутки), кнопки по состоянию поля, диалог подтверждения."""
    fields = list(schema.all_fields(lst))
    with_data = schema.has_data_many(lst, fields)
    rows = [{"code": f.code, "pk": f.pk, "name": f.name, "type_label": Field.Type(f.type).label, "hidden": f.hidden,
             "has_data": f.pk in with_data} for f in fields]
    context = {"lst": lst, "tab": "fields", "rows": rows, "alert": alert}
    return render_page(request, "lists/settings_fields.html", context)


@login_required
@require_http_methods(["GET"])
def fields(request, list_id: int):
    """Вкладка «Поля»: «Название» (системное, без кнопок) и поля списка по порядку, со скрытыми."""
    return _fields_page(request, _manage_list(request, list_id))


def _padded(thresholds) -> list[str]:
    """Три входа порогов: сохранённые значения, остальные пустые."""
    items = [str(item) for item in thresholds][:THRESHOLD_SLOTS]
    return items + [""] * (THRESHOLD_SLOTS - len(items))


def _is_id(text) -> bool:
    return isinstance(text, str) and text.isascii() and text.isdigit()


def _values_of_field(field: Field | None, kind: str) -> dict:
    """Начальные значения формы: у нового поля пустые (пороги подставляет скрипт при первом включении «срока»), у
    сохранённого — его собственные."""
    if field is None:
        return {"name": "", "hint": "", "required": False, "multiple": False, "unique": False, "show_in_table": False,
                "deadline": False, "default": "", "default_mode": "", "currency": "RUB", "target": "",
                "thresholds": _padded([])}
    settings = field.settings or {}
    default, mode = "", ""
    if kind == "date" and isinstance(field.default, dict):
        mode = "today"
    elif kind == "date" and field.default:
        mode, default = "date", _iso_to_ru(field.default)
    elif kind == "bool":
        default = "on" if field.default else ""
    elif kind == "choice" and isinstance(field.default, list) and field.default:
        default = str(field.default[0])
    elif field.default is not None:
        default = str(field.default)
    return {"name": field.name, "hint": field.hint, "required": field.required, "multiple": field.multiple,
            "unique": field.unique, "show_in_table": field.show_in_table, "deadline": bool(settings.get("deadline")),
            "default": default, "default_mode": mode, "currency": settings.get("currency") or "RUB",
            "target": str(field.target_id or ""), "thresholds": _padded(settings.get("thresholds") or [])}


def _iso_to_ru(text) -> str:
    """`ГГГГ-ММ-ДД` -> `ДД.ММ.ГГГГ` для поля ввода."""
    parts = str(text).split("-")
    return ".".join(reversed(parts)) if len(parts) == 3 else str(text)


def _values_of_post(post, kind: str) -> dict:
    """Введённое в форму (для повторного показа после отказа)."""
    result = {name: post.get(name, "") for name in ("name", "hint", "default", "default_mode", "currency", "target")}
    result.update({flag: post.get(flag) == "on" for flag in FLAGS})
    result["thresholds"] = _padded(post.getlist("thresholds"))
    result["currency"] = result["currency"] or "RUB"
    return result


def _field_form_context(request, lst: List, *, field: Field | None, kind: str, form_values: dict, errors=None,
                        alert=None) -> dict:
    """Всё для `_field_form.html`: свойства типа, замок поля с данными, ошибки у полей и общие."""
    locked = field is not None and field.pk in schema.has_data_many(lst, [field])
    kind = field.type if locked else kind
    props = set(TYPE_PROPS.get(kind, ())) | {"show_in_table"}
    if kind == "date" and "deadline" in props:
        props.add("thresholds")
    editable = {"name", "hint", "show_in_table"} | (props - {"currency", "target"} if locked else props)
    editable |= {"type"} if not locked else set()
    editable |= {"choices"} if kind == "choice" else set()
    errors = dict(errors or {})
    inline = {name: err for name, err in errors.items() if name in editable}
    general = [err for name, err in errors.items() if name not in inline]
    choices = []
    if field is not None and kind == "choice":
        choices = list(Choice.objects.filter(field=field).order_by("archived", "order", "pk"))
    return {"lst": lst, "field": field, "kind": kind, "kind_label": Field.Type(kind).label if kind in Field.Type.values
            else "", "locked": locked, "props": props, "v": form_values, "inline": inline, "general": general,
            "alert": alert, "types": TYPE_CHOICES, "currencies": CURRENCY_CHOICES,
            "target_name": field.target.name if field is not None and field.target_id else "",
            "lists": list(List.objects.order_by("name", "pk")) if "target" in props and not locked else [],
            "choice_rows": [c for c in choices if not c.archived], "archived_rows": [c for c in choices if c.archived],
            "default_choices": [c for c in choices if not c.archived], "props_target": PROPS_TARGET,
            "new_url": f"/lists/{lst.pk}/settings/fields/new/",
            "action": (f"/lists/{lst.pk}/settings/fields/{field.code}/" if field is not None
                       else f"/lists/{lst.pk}/settings/fields/new/")}


def _field_page(request, lst: List, *, field: Field | None, kind: str, form_values: dict, errors=None, alert=None):
    """Страница формы поля; запрос смены типа (`HX-Target`) получает только блок свойств."""
    context = _field_form_context(request, lst, field=field, kind=kind, form_values=form_values, errors=errors,
                                  alert=alert)
    if is_fragment(request) and request.headers.get("HX-Target") == PROPS_TARGET:
        response = render_page(request, "lists/_field_props.html", context)
        patch_vary_headers(response, ("HX-Request", "HX-Target"))
        return response
    context["tab"] = "fields"
    response = render_page(request, "lists/settings_field.html", context)
    patch_vary_headers(response, ("HX-Request", "HX-Target"))
    return response


def _default_of(request, lst: List, kind: str, field: Field | None):
    """Значение по умолчанию из формы (служба проверяет только «свойство своего типа»; разбор — здесь, `values.parse`).

    Дата: `default_mode` (`today` — «сегодня», `date` — дата из `default`, пусто — нет); без `default_mode` слово
    `today` — «сегодня», иное — дата (15.5 п. 15). Тип без умолчания: сырая строка идёт в службу — она откажет
    (`property_not_allowed`)."""
    post = request.POST
    raw = post.get("default", "").strip()
    mode = post.get("default_mode")
    if kind not in DEFAULT_TYPES:
        return raw or None
    if kind == "date":
        if mode == "today" or (mode is None and raw.lower() == "today"):
            return {"today": True}
        if mode is not None and mode != "date":
            return None
    if not raw:
        return None
    if kind == "bool":
        return True if raw.lower() in list_values.TRUE_FORM else None
    if kind == "choice":
        if field is None or not _is_id(raw) or not Choice.objects.filter(field=field, pk=int(raw),
                                                                        archived=False).exists():
            raise ListsError("property_not_allowed", field="default")
        return [int(raw)]
    parsed = list_values.parse(Field(type=kind, code="default", list=lst), raw, viewer=request.user)
    if parsed.error is not None:
        raise ListsError(parsed.error.code, field="default", params=parsed.error.params)
    return parsed.value


def _target_of(post):
    """Список-цель из формы: пусто — `None`; нет такого — `target_required` у поля `target`."""
    raw = post.get("target", "").strip()
    if not raw:
        return None
    target = List.objects.filter(pk=int(raw)).first() if _is_id(raw) else None
    if target is None:
        raise ListsError("target_required", field="target")
    return target


def _field_kwargs(request, lst: List, kind: str, field: Field | None, *, editing: bool) -> dict:
    """Параметры службы из формы: флажки — всегда (снятый флажок в POST не приходит), `currency`, `target`, `type` —
    только присланные."""
    post = request.POST
    kwargs = {"name": post.get("name", ""), "hint": post.get("hint", "")}
    for flag in FLAGS:
        kwargs[flag] = post.get(flag) == "on"
    kwargs["default"] = _default_of(request, lst, kind, field)
    thresholds = post.getlist("thresholds")
    if kwargs["deadline"] or any(item.strip() for item in thresholds):
        kwargs["thresholds"] = thresholds
    currency = post.get("currency", "").strip()
    if currency:
        kwargs["currency"] = currency
    target = _target_of(post)
    if target is not None:
        kwargs["target"] = target
    if editing and "type" in post:
        kwargs["type"] = post.get("type", "")
    return kwargs


@login_required
@require_http_methods(["GET", "POST"])
def field_new(request, list_id: int):
    """Форма нового поля (`?type=<тип>` — со свойствами типа; по умолчанию «Строка»); POST — поле, 302 на «Поля»."""
    lst = _manage_list(request, list_id)
    if request.method == "GET":
        kind = request.GET.get("type", "string")
        kind = kind if kind in Field.Type.values else "string"
        return _field_page(request, lst, field=None, kind=kind, form_values=_values_of_field(None, kind))
    kind = request.POST.get("type", "")
    shown_kind = kind if kind in Field.Type.values else "string"
    try:
        kwargs = _field_kwargs(request, lst, kind, None, editing=False)
        schema.add_field(lst, type=kind, actor=request.user, **kwargs)
    except ListsError as refused:
        errors, alert = _refusal(refused, FIELD_ERRORS)
        return _field_page(request, lst, field=None, kind=shown_kind, form_values=_values_of_post(request.POST, kind),
                           errors=errors, alert=alert)
    return done(request, _fields_url(lst))


@login_required
@require_http_methods(["GET", "POST"])
def field_edit(request, list_id: int, code: str):
    """Форма поля: у пустого — со сменой типа, у поля с данными — без `type`, валюты и целевого списка; POST — 302."""
    lst = _manage_list(request, list_id)
    field = _get_field(lst, code)
    if request.method == "GET":
        kind = request.GET.get("type", field.type)
        if kind not in Field.Type.values or kind == field.type:
            return _field_page(request, lst, field=field, kind=field.type,
                               form_values=_values_of_field(field, field.type))
        # смена типа в форме (`hx-get`): свойства нового типа пустые, название и подсказка остаются
        form_values = {**_values_of_field(None, kind), "name": field.name, "hint": field.hint}
        return _field_page(request, lst, field=field, kind=kind, form_values=form_values)
    kind = request.POST.get("type", field.type)
    if kind not in Field.Type.values:
        kind = field.type
    try:
        kwargs = _field_kwargs(request, lst, kind, field, editing=True)
        schema.update_field(field, actor=request.user, **kwargs)
    except ListsError as refused:
        errors, alert = _refusal(refused, FIELD_ERRORS)
        return _field_page(request, lst, field=field, kind=kind, form_values=_values_of_post(request.POST, kind),
                           errors=errors, alert=alert)
    return done(request, _fields_url(lst))


def _field_action(request, list_id: int, code: str, action):
    """POST-действие над полем (скрыть, показать, удалить, стрелки): успех — 302 на «Поля», отказ — «Поля» с общим
    отказом (200)."""
    lst = _manage_list(request, list_id)
    field = _get_field(lst, code)
    try:
        action(field)
    except ListsError as refused:
        return _fields_page(request, lst, alert=refused)
    return done(request, _fields_url(lst))


@login_required
@require_POST
def field_hide(request, list_id: int, code: str):
    """Скрывает поле (данные остаются)."""
    return _field_action(request, list_id, code, lambda field: schema.hide_field(field, actor=request.user))


@login_required
@require_POST
def field_show(request, list_id: int, code: str):
    """Возвращает скрытое поле."""
    return _field_action(request, list_id, code, lambda field: schema.show_field(field, actor=request.user))


@login_required
@require_POST
def field_delete(request, list_id: int, code: str):
    """Удаляет пустое поле (диалог подтверждения — на странице); с данными — отказ `field_has_data` на странице."""
    return _field_action(request, list_id, code, lambda field: schema.delete_field(field, actor=request.user))


@login_required
@require_POST
def field_up(request, list_id: int, code: str):
    """Поле на место выше."""
    return _field_action(request, list_id, code, lambda field: schema.move_field(field, "up", actor=request.user))


@login_required
@require_POST
def field_down(request, list_id: int, code: str):
    """Поле на место ниже."""
    return _field_action(request, list_id, code, lambda field: schema.move_field(field, "down", actor=request.user))


@login_required
@require_POST
def field_order(request, list_id: int):
    """Новый порядок полей: `codes` — все коды в порядке; успех — 302, на HTMX — 204; `bad_order` — 200 «Поля» с отказом."""
    lst = _manage_list(request, list_id)
    try:
        schema.set_order(lst, request.POST.getlist("codes"), actor=request.user)
    except ListsError as refused:
        return _fields_page(request, lst, alert=refused)
    if is_fragment(request):
        return HttpResponse(status=204)
    return done(request, _fields_url(lst))


@login_required
@require_POST
def field_choices(request, list_id: int, code: str):
    """Значения поля «список значений»: пары `id` и `title` в новом порядке (пустой `id` — новое значение; `new_title`
    без скрипта добавляет значение в конец); успех — 302 на страницу поля, отказ — 200 со страницей поля."""
    lst = _manage_list(request, list_id)
    field = _get_field(lst, code)
    ids, titles = request.POST.getlist("id"), request.POST.getlist("title")
    items = []
    for raw_id, title in zip(ids, titles):
        if raw_id == "":
            items.append((None, title))
        elif _is_id(raw_id):
            items.append((int(raw_id), title))
        else:
            raise Http404("Значение не найдено")
    extra = request.POST.get("new_title", "").strip()
    if extra:
        items.append((None, extra))
    try:
        schema.save_choices(field, items, actor=request.user)
    except ListsError as refused:
        errors, alert = _refusal(refused, FIELD_ERRORS)
        return _field_page(request, lst, field=field, kind=field.type, form_values=_values_of_field(field, field.type),
                           errors=errors, alert=alert)
    return done(request, f"{_fields_url(lst)}{field.code}/")
