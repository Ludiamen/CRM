"""Страницы записи: форма новой записи и правки, карточка, история, архив, возврат и удаление навсегда (T-6215; PLAN-006,
«Значения и форма записи», «Запись…», «История записи», «Архив и удаление навсегда», «Связи»; CONTRACT-006, 10.1, 10.2,
10.4, 11.4–11.6, 12, 15.3 № 22, 15.5, 15.6).

Список не читается — 404 (как несуществующий), читается, а действия нет — 403. Отказ службы на POST — 200 с формой и
введённым (HTMX не вставляет 4xx). Значения скрытых полей в карточке не выводятся (решение владельца 2026-10-25).
"""
from django.apps import apps
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.db.models import Prefetch, prefetch_related_objects
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.views.decorators.http import require_GET, require_http_methods, require_POST

from apps.core.views.common import is_fragment, render_page
from apps.core.widgets import PortalDateInput, moscow_today
from apps.lists.models import Choice, Field, Record, RecordFile
from apps.lists.services import access, archive as archive_service, history as history_service, links, schema
from apps.lists.services import tickets as tickets_service
from apps.lists.services import records as records_service
from apps.lists.services import values as values_service
from apps.lists.services.errors import (ListsError, RecordArchived, RecordGone, ValuesInvalid, VersionConflict)
from apps.lists.texts import TEXTS

from .home import done

REFERENCE_TYPES = values_service.REFERENCE_TYPES
HISTORY_LABELS = {"changed": "Изменена", "imported": "Изменено загрузкой", "archived": "Перенесена в архив",
                  "restored": "Возвращена из архива"}


def _ascii_int(raw, default: int = 0) -> int:
    """Целое из параметра: только цифры 0–9 (иначе `default`)."""
    text = str(raw or "")
    return int(text) if text.isascii() and text.isdigit() else default


def _record_url(lst, number: int) -> str:
    return f"/lists/{lst.pk}/{number}/"


def _gone_or_404(request, lst, number: int):
    """Строки нет: номер меньше `next_number` — 404 «Запись удалена» (страница `gone`), иначе обычный 404."""
    if number < lst.next_number:
        return render_page(request, "lists/record_gone.html", {"lst": lst, "text": TEXTS["record_gone"]}, status=404)
    raise Http404("Запись не найдена")


def _alert_context(alert):
    """Общий отказ: для `record_referenced` ссылки собираются в разметке (текст до `{links}` — из словаря)."""
    if alert is None:
        return None
    refs = alert.params.get("refs") if alert.code == "record_referenced" else None
    if alert.code == "record_referenced":
        return {"alert": alert, "refs_alert": {"prefix": TEXTS["record_referenced"].split("{links}")[0],
                                               "refs": refs or [], "hidden": alert.params.get("hidden", 0)}}
    return {"alert": alert, "refs_alert": None}


# --- значения-ссылки (карточка и форма) ---------------------------------------------------------------------

def _ref_items(field: Field, ids, viewer) -> list[dict]:
    """Выбранные значения полей `choice`, `person`, `unit`, `record` как строки показа.

    Ключи: `id`, `text`; `user` — сотрудник (подпись `person_name`); `url` и `archived` — запись; `unavailable` — запись
    списка, которого смотрящий не читает (без названия и ссылки)."""
    ids = [pk for pk in ids if isinstance(pk, int)]
    if not ids:
        return []
    kind = field.type
    items: list[dict] = []
    if kind == "choice":
        titles = dict(Choice.objects.filter(field=field, pk__in=ids).values_list("pk", "title"))
        items = [{"id": pk, "text": titles[pk]} for pk in ids if pk in titles]
    elif kind == "person":
        users = {u.pk: u for u in get_user_model().objects.filter(pk__in=ids)}
        items = [{"id": pk, "text": users[pk].full_name, "user": users[pk]} for pk in ids if pk in users]
    elif kind == "unit":
        refs = {}
        if apps.is_installed("apps.org"):
            from apps.org.services import structure

            refs = structure.unit_refs(ids)
        items = [{"id": pk, "text": refs[pk].name if pk in refs else f"узел №{pk}"} for pk in ids]
    elif kind == "record":
        found = {r.pk: r for r in Record.objects.filter(pk__in=ids).select_related("list")}
        readable: dict[int, bool] = {}
        for pk in ids:
            record = found.get(pk)
            if record is None:
                continue
            if record.list_id not in readable:
                readable[record.list_id] = access.can_read(viewer, record.list)
            if not readable[record.list_id]:
                items.append({"id": pk, "text": "запись недоступного списка", "unavailable": True})
                continue
            items.append({"id": pk, "text": f"{record.title} — №{record.number}", "archived": record.archived,
                          "url": _record_url(record.list, record.number)})
    return items


def _stored_ids(value) -> list[int]:
    return [pk for pk in (value or []) if isinstance(pk, int)] if isinstance(value, list) else []


# --- форма --------------------------------------------------------------------------------------------------

def _default_text(field: Field, viewer) -> str:
    """Умолчание поля для новой записи строкой формы (у даты «сегодня» — дата по Москве)."""
    default = field.default
    if default in (None, "", [], {}):
        return ""
    if isinstance(default, dict):
        return moscow_today().strftime("%d.%m.%Y") if default.get("today") else ""
    if field.type == "money":
        return str(default).replace(".", ",")
    return values_service.display(field, default, viewer)


def _stored_text(field: Field, stored, viewer) -> str:
    """Сохранённое значение строкой формы: дата «ДД.ММ.ГГГГ», дата и время по Москве, число и деньги с запятой."""
    if stored in (None, "", []):
        return ""
    if field.type == "money":
        return str(stored).replace(".", ",")
    return values_service.display(field, stored, viewer)


def _initial(field: Field, record, viewer) -> dict:
    """Значение поля до правки пользователя: у новой записи — умолчание, у записи — сохранённое."""
    if record is None:
        default = field.default
        if field.type == "bool":
            return {"checked": default is True}
        if field.type in ("choice", "person", "unit", "record"):
            return {"ids": _stored_ids(default)}
        return {"text": _default_text(field, viewer)}
    stored = (record.values or {}).get(field.code)
    if field.type == "bool":
        return {"checked": stored is True}
    if field.type in ("choice", "person", "unit", "record"):
        return {"ids": _stored_ids(stored)}
    return {"text": _stored_text(field, stored, viewer)}


def _typed(field: Field, post) -> dict:
    """Введённое в форме значение поля (для показа формы после отказа)."""
    if field.type == "bool":
        return {"checked": post.get(field.code) == "on"}
    if field.type in ("choice", "person", "unit", "record"):
        return {"ids": [int(v) for v in post.getlist(field.code) if v.isascii() and v.isdigit()]}
    return {"text": post.get(field.code, "")}


def _form_fields(lst, record, viewer, *, post=None, errors=None) -> list[dict]:
    """Поля формы по `order`: видимые — с элементом ввода, скрытое за время правки — только для чтения."""
    errors = errors or {}
    rows = []
    for field in schema.all_fields(lst):
        if field.type == "file":
            continue
        error = errors.get(field.code)
        if field.hidden:
            if error is not None and error.code == "field_hidden_meanwhile":
                stored = (record.values or {}).get(field.code) if record is not None else None
                rows.append({"field": field, "hidden_meanwhile": True, "error": error,
                             "text": values_service.display(field, stored, viewer)})
            continue
        state = _typed(field, post) if post is not None else _initial(field, record, viewer)
        row = {"field": field, "error": error, "state": state, "hidden_meanwhile": False, "kind": field.type}
        if field.type == "date":
            row["date_html"] = PortalDateInput().render(field.code, state["text"], attrs={"id": f"lists-f-{field.code}"})
        elif field.type == "choice":
            chosen = set(state["ids"])
            row["options"] = [
                {"id": c.pk, "title": c.title, "selected": c.pk in chosen}
                for c in Choice.objects.filter(field=field).order_by("order", "pk") if not c.archived or c.pk in chosen]
        elif field.type in ("person", "unit", "record"):
            row["selected"] = _ref_items(field, state["ids"], viewer)
            row["pick_url"] = {"person": "/lists/people/", "unit": "/lists/units/"}.get(
                field.type, f"/lists/{field.target_id}/pick/")
            row["picker"] = {"person": "people", "unit": "units", "record": "record"}[field.type]
        rows.append(row)
    return rows


def _form_page(request, lst, *, record=None, number=None, post=None, errors=None, alert=None, base_version=None,
               status=200):
    """Страница формы: `add` без записи, `edit` с записью (`base_version` — скрытое поле)."""
    errors = errors or {}
    title = post.get("title", "") if post is not None else (record.title if record is not None else "")
    rows = _form_fields(lst, record, request.user, post=post, errors=errors)
    shown = {row["field"].code for row in rows}
    leftover = [err for code, err in errors.items() if code != "title" and code not in shown]
    context = {"lst": lst, "record": record, "number": number, "rows": rows, "title_value": title,
               "title_error": errors.get("title"), "base_version": base_version,
               "mode": "edit" if number is not None else "add", **(_alert_context(alert or (leftover or [None])[0]) or {})}
    return render_page(request, "lists/record_form.html", context, status=status)


def _post_data(lst, post) -> dict:
    """Данные для службы: «Название» и значения по кодам полей (списки — у выбора, строки — у остальных)."""
    data = {"title": post.get("title", "")}
    for field in schema.all_fields(lst):
        if field.type == "file" or field.code not in post:
            continue
        if field.type in ("choice", "person", "unit", "record"):
            data[field.code] = [v for v in post.getlist(field.code) if v.strip()]
        else:
            data[field.code] = post.get(field.code, "")
    return data


def _require_edit(request, lst) -> None:
    if not access.can_edit(request.user, lst):
        raise PermissionDenied


@login_required
@require_http_methods(["GET", "POST"])
def add(request, list_id: int):
    """Форма новой записи; POST — запись и переход на её карточку (302)."""
    lst = access.get_list(request.user, list_id)
    _require_edit(request, lst)
    if request.method == "POST":
        try:
            record = records_service.create(lst, _post_data(lst, request.POST), request.user)
        except ValuesInvalid as refused:
            return _form_page(request, lst, post=request.POST, errors=refused.errors)
        except ListsError as refused:
            return _form_page(request, lst, post=request.POST, alert=refused)
        return done(request, _record_url(lst, record.number))
    return _form_page(request, lst)


@login_required
@require_http_methods(["GET", "POST"])
def edit(request, list_id: int, number: int):
    """Правка записи: GET — форма (запись в архиве — страница без формы), POST — сохранение (302 на карточку)."""
    lst = access.get_list(request.user, list_id)
    _require_edit(request, lst)
    record = Record.objects.filter(list=lst, number=number).first()
    if request.method == "GET":
        if record is None:
            return _gone_or_404(request, lst, number)
        if record.archived:
            return render_page(request, "lists/record_archived_edit.html",
                               {"lst": lst, "record": record, "text": TEXTS["record_archived"]})
        return _form_page(request, lst, record=record, number=number, base_version=record.version)
    base = _ascii_int(request.POST.get("base_version"), -1)
    try:
        records_service.save(lst, number, _post_data(lst, request.POST), base_version=base, actor=request.user)
    except ValuesInvalid as refused:
        return _form_page(request, lst, record=record, number=number, post=request.POST, errors=refused.errors,
                          base_version=base)
    except VersionConflict as refused:
        current = Record.objects.filter(list=lst, number=number).values_list("version", flat=True).first()
        return _form_page(request, lst, record=record, number=number, post=request.POST, alert=refused,
                          base_version=current if current is not None else base)
    except (RecordGone, RecordArchived) as refused:
        return _form_page(request, lst, record=record, number=number, post=request.POST, alert=refused,
                          base_version=base)
    except ListsError as refused:
        return _form_page(request, lst, record=record, number=number, post=request.POST, alert=refused,
                          base_version=base)
    return done(request, _record_url(lst, number))


# --- карточка -----------------------------------------------------------------------------------------------

def _value_cell(field: Field, stored, viewer) -> dict:
    """Значение поля для карточки: `kind` выбирает разметку, `items` — значения-ссылки, `text` — остальные."""
    if field.type in REFERENCE_TYPES:
        return {"field": field, "kind": "refs", "items": _ref_items(field, _stored_ids(stored), viewer)}
    if field.type in ("string", "text"):
        return {"field": field, "kind": "text" if field.type == "text" else "plain", "text": str(stored or "")}
    return {"field": field, "kind": "plain", "text": values_service.display(field, stored, viewer)}


def _card_context(request, lst, record, *, alert=None) -> dict:
    user = request.user
    fields = schema.visible_fields(lst)
    stored = record.values or {}
    can_edit = access.can_edit(user, lst)
    found = links.referrers(record, user)
    page = history_service.page(record, 0)
    # файлы карточки — одним запросом вместе с `StoredFile` (блок «Файлы», T-6222; сборка Opus)
    prefetch_related_objects([record], Prefetch("files", queryset=RecordFile.objects.select_related("file")))
    return {
        "lst": lst, "record": record, "can_edit": can_edit,
        "can_purge": record.archived and access.can_manage(user),
        "cells": [_value_cell(f, stored.get(f.code), user) for f in fields if f.type != "file"],
        "file_fields": [f for f in fields if f.type == "file"],
        "referrers": found.rows,
        "history_rows": history_service.for_viewer(page.rows, lst, user), "next_offset": page.next_offset,
        "related_tickets": tickets_service.related(user, record),  # «Связанные заявки», T-6218; сборка Opus
        **(_alert_context(alert) or {}),
    }


def _card_page(request, lst, record, *, alert=None, status=200):
    return render_page(request, "lists/record.html", _card_context(request, lst, record, alert=alert), status=status)


@login_required
@require_GET
def record(request, list_id: int, number: int):
    """Карточка записи: видимые поля, файлы, связанные заявки, «Ссылаются на эту запись», история."""
    lst = access.get_list(request.user, list_id)
    found = Record.objects.filter(list=lst, number=number).first()
    if found is None:
        return _gone_or_404(request, lst, number)
    return _card_page(request, lst, found)


# --- история ------------------------------------------------------------------------------------------------

@login_required
@require_GET
def history(request, list_id: int, number: int):
    """История записи по 50 строк, новые сверху: запрос HTMX — фрагмент строк, обычный — страница истории."""
    lst = access.get_list(request.user, list_id)
    found = Record.objects.filter(list=lst, number=number).first()
    if found is None:
        raise Http404("Запись не найдена")
    page = history_service.page(found, _ascii_int(request.GET.get("offset")))
    context = {"lst": lst, "record": found, "history_rows": history_service.for_viewer(page.rows, lst, request.user),
               "next_offset": page.next_offset}
    if is_fragment(request):
        return render_page(request, "lists/_history_rows.html", context)
    return render_page(request, "lists/record_history.html", context)


# --- архив, возврат, удаление навсегда ----------------------------------------------------------------------

def _acting(request, list_id: int, number: int):
    lst = access.get_list(request.user, list_id)
    return lst, _record_url(lst, number)


@login_required
@require_POST
def archive(request, list_id: int, number: int):
    """«В архив» (правящий): 302 на карточку."""
    lst, url = _acting(request, list_id, number)
    archive_service.archive(lst, number, actor=request.user)
    return done(request, url)


@login_required
@require_POST
def restore(request, list_id: int, number: int):
    """«Вернуть из архива» (правящий): 302 на карточку."""
    lst, url = _acting(request, list_id, number)
    archive_service.restore(lst, number, actor=request.user)
    return done(request, url)


@login_required
@require_POST
def purge(request, list_id: int, number: int):
    """«Удалить навсегда» (управляющий, запись в архиве): 302 на отбор «Архив»; ссылки на запись — 200 с отказом."""
    lst, _url = _acting(request, list_id, number)
    try:
        archive_service.purge(lst, number, actor=request.user)
    except ListsError as refused:
        found = Record.objects.filter(list=lst, number=number).first()
        if found is None:
            raise Http404("Запись не найдена") from None
        return _card_page(request, lst, found, alert=refused)
    return done(request, f"/lists/{lst.pk}/?preset=archive")
