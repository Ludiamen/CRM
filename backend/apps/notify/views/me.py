"""«Мои уведомления» (`/me/notifications/` и вложенные маршруты; PLAN-004, «Личные настройки», «Web Push» →
«Подписка»; CONTRACT-004, 13.2, 14.3, 15.4-15.5).

Страница вошедшего сотрудника: чужой страницы нет (в пути нет номера сотрудника, поле `user` в теле игнорируется).
Таблицу и тихие часы сохраняет одна служба `prefs.save`; подписки Web Push — `push`, привязки ботов — `binding`.
Тексты экранирует шаблонизатор (NFR-311); кода привязки, адреса подписки и ключей нет ни в журнале, ни в адресах.
"""
import json
from datetime import time as clock_time

from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, HttpResponseRedirect, JsonResponse
from django.template.loader import render_to_string
from django.views.decorators.http import require_http_methods, require_POST

from apps.core.models import UserSession
from apps.core.views.common import flash, is_fragment, render_page, user_agent

from ..services import binding, bots, kinds, prefs, push
from ..services import settings as notify_settings
from ..services.errors import NotifyError

ME_URL = "/me/notifications/"
SAVED_TEXT = "Настройки уведомлений сохранены."
PUSH_REFUSED_TEXT = "Подписку этого устройства сохранить не удалось"
CHANNEL_TITLES = {"portal": "На портале", "email": "Почта", "push": "Push в браузере", "telegram": "Telegram",
                  "max": "MAX"}
BIND_TITLES = {"telegram": "Telegram", "max": "MAX"}
UNBOUND_FLASH = {"telegram": "Telegram отвязан.", "max": "MAX отвязан."}
HINTS = {
    ("push", "no_subscriptions"): "Разрешите push на этом устройстве",
    ("push", "channel_disabled"): "Push при закрытой вкладке отключён администратором",
    ("telegram", "not_bound"): "Привяжите Telegram",
    ("max", "not_bound"): "Привяжите MAX",
    ("telegram", "channel_disabled"): "Канал отключён администратором",
    ("max", "channel_disabled"): "Канал отключён администратором",
}
DAYS = (("0", "Пн"), ("1", "Вт"), ("2", "Ср"), ("3", "Чт"), ("4", "Пт"), ("5", "Сб"), ("6", "Вс"))
MODES = (("calendar", "По рабочему календарю компании"), ("own", "Свои часы"), ("none", "Без тихих часов"))


# --- блок привязки: общий для страницы, ответов `bind`/`unbind` и кадра соединения -------------------------------

def binding_state(user_id: int, channel: str) -> str:
    """Состояние блока: `disabled` (канал выключен или нет токена), `bound` или `unbound`."""
    if not notify_settings.channel_on(channel):
        return "disabled"
    return "bound" if binding.get(user_id, channel) else "unbound"


def binding_context(channel: str, state: str, *, code=None, error: str = "", oob: bool = False) -> dict:
    """Контекст шаблона `notify/me/_binding.html`; `code` — только что выданный `binding.NewCode` (иначе `None`)."""
    context = {"channel": channel, "title": BIND_TITLES.get(channel, channel), "state": state, "oob": oob,
               "error_code": error, "code": "", "expires_minutes": binding.CODE_MINUTES, "bot_link": ""}
    if code is not None:
        context["code"] = code.code
        context["bot_link"] = bots.bot_link(channel) or ""
    return context


def render_binding(channel: str, state: str, *, code=None, error: str = "", oob: bool = False,
                   request=None) -> str:
    """Блок привязки как строка; в кадре соединения — с `hx-swap-oob` и без кода (CONTRACT-004, 11.3). Запрос нужен
    ответу страницы ради поля CSRF в форме; кадру соединения он не нужен (запросы HTMX берут токен у страницы)."""
    return render_to_string("notify/me/_binding.html",
                            binding_context(channel, state, code=code, error=error, oob=oob), request=request)


def _binding_blocks(user_id: int, issued=None) -> list:
    """Блоки обоих каналов; `issued` — `(канал, NewCode, код отказа)` только что выданного кода."""
    blocks = []
    for channel in binding.CHANNELS:
        code, error = None, ""
        if issued and issued[0] == channel:
            code, error = issued[1], issued[2]
        blocks.append(binding_context(channel, binding_state(user_id, channel), code=code, error=error))
    return blocks


# --- устройства ------------------------------------------------------------------------------------------------

def _current_device_id(request):
    row = UserSession.objects.filter(session_key=request.session.session_key).only("device_id").first()
    return row.device_id if row else None


def _devices_context(user) -> dict:
    return {"devices": push.list_for(user.pk)}


# --- таблица и тихие часы ---------------------------------------------------------------------------------------

def _hint(channel: str, reason: str) -> str:
    return HINTS.get((channel, reason), "")


def _cell_set(post) -> set:
    return set(post.getlist("cell"))


def _table_context(user, posted=None) -> dict:
    """Строки таблицы для шаблона. `posted` — множество присланных ячеек: при отказе формы флажки остаются как есть."""
    table = prefs.effective(user)
    rows = []
    for item in table.rows:
        cells = []
        for channel in kinds.CHANNELS:
            cell = {"channel": channel, "label": CHANNEL_TITLES[channel], "value": f"{item.kind.code}:{channel}"}
            if channel == "portal":
                cell["locked"] = True
            elif channel == "push":
                cell.update(available=table.web_push_available, reason=table.web_push_reason,
                            hint=_hint("push", table.web_push_reason), has_box=True)
            elif channel == "email":
                cell.update(available=True, reason="", hint="", has_box=True)
            else:
                state = table.channels[channel]
                cell.update(available=state.available, reason=state.reason, hint=_hint(channel, state.reason),
                            has_box=state.available)
            if cell.get("has_box"):
                cell["checked"] = (cell["value"] in posted) if posted is not None else item.cells[channel]
            cells.append(cell)
        rows.append({"code": item.kind.code, "title": item.kind.title, "module": item.kind.module, "cells": cells})
    return {"rows": rows, "channel_columns": [(channel, CHANNEL_TITLES[channel]) for channel in kinds.CHANNELS]}


def _quiet_context(user, post=None) -> dict:
    """Значения тихих часов: из строки сотрудника (нет строки — календарь) или из присланной формы при отказе."""
    if post is not None:
        return {"mode": post.get("quiet_mode") or "calendar", "days": set(post.getlist("own_days")),
                "start": post.get("own_start", ""), "end": post.get("own_end", "")}
    row = prefs.row_of(user.pk)
    if row is None:
        return {"mode": "calendar", "days": set(), "start": "", "end": ""}
    return {"mode": row.quiet_mode, "days": {str(day) for day in (row.own_days or [])},
            "start": _hhmm(row.own_start), "end": _hhmm(row.own_end)}


def _hhmm(value) -> str:
    return value.strftime("%H:%M") if isinstance(value, clock_time) else ""


def _page_context(request, *, post=None, error=None, issued=None) -> dict:
    user = request.user
    web_push_on = notify_settings.channel_on("webpush")
    device_id = _current_device_id(request)
    devices_ctx = _devices_context(user)
    subscribed = device_id is not None and any(item.device_id == device_id for item in devices_ctx["devices"])
    quiet = _quiet_context(user, post)
    return {
        **_table_context(user, _cell_set(post) if post is not None and "table" in post else None),
        "quiet": quiet, "modes": MODES, "days": [(value, title, value in quiet["days"]) for value, title in DAYS],
        "error": error,
        "web_push_on": web_push_on, "vapid_public": settings.VAPID_PUBLIC_KEY if web_push_on else "",
        "device_subscribed": "1" if subscribed else "0", **devices_ctx,
        "bindings": _binding_blocks(user.pk, issued),
    }


def _render_page(request, context: dict):
    return render_page(request, "notify/me/page.html", context)


def _chosen_table(post, user):
    """`table` для `prefs.save` по присланным ячейкам: по каждому виду таблицы — список его внешних каналов."""
    chosen = {}
    for value in post.getlist("cell"):
        code, _, channel = value.rpartition(":")
        if code and channel in kinds.EXTERNAL:
            chosen.setdefault(code, []).append(channel)
    return {item.kind.code: chosen.get(item.kind.code, []) for item in prefs.effective(user).rows}


def _save(request):
    """POST: таблица и тихие часы одним вызовом `prefs.save`; отказ — та же страница с `[data-error]`, ничего не сохранено."""
    post, user = request.POST, request.user
    table = _chosen_table(post, user) if "table" in post else None
    quiet_mode = post.get("quiet_mode") if "quiet_mode" in post else None
    fields = {}
    if quiet_mode == "own":
        fields = {"own_days": post.getlist("own_days"), "own_start": post.get("own_start", ""),
                  "own_end": post.get("own_end", "")}
    try:
        prefs.save(user, table=table, quiet_mode=quiet_mode, ip=request.client_ip, **fields)
    except NotifyError as error:
        return _render_page(request, _page_context(request, post=post, error=error))
    flash(request, SAVED_TEXT)
    if is_fragment(request):
        response = HttpResponse("")
        response["HX-Redirect"] = ME_URL
        return response
    return HttpResponseRedirect(ME_URL)


@login_required
@require_http_methods(["GET", "POST"])
def notifications_page(request):
    """GET, POST `/me/notifications/` — таблица, тихие часы, устройства, привязки."""
    if request.method == "POST":
        return _save(request)
    return _render_page(request, _page_context(request))


# --- Web Push -------------------------------------------------------------------------------------------------

def _push_refused(code: str, field: str = "") -> JsonResponse:
    return JsonResponse({"ok": False, "code": code, "field": field, "message": PUSH_REFUSED_TEXT}, status=400)


@login_required
@require_POST
def push_save(request):
    """POST `/me/notifications/push/` — сохранить подписку этого устройства (JSON `PushSubscription.toJSON()`)."""
    if not notify_settings.channel_on("webpush"):
        return _push_refused("channel_disabled")
    try:
        data = json.loads(request.body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return _push_refused("bad_json")
    keys = data.get("keys") if isinstance(data, dict) else None
    if not isinstance(keys, dict) or "endpoint" not in data:
        return _push_refused("bad_json")
    try:
        subscription = push.save(request.user, endpoint=data["endpoint"], p256dh=keys.get("p256dh"),
                                 auth=keys.get("auth"), device_id=_current_device_id(request),
                                 user_agent=user_agent(request), ip=request.client_ip)
    except NotifyError as error:
        return _push_refused(error.code, error.field)
    return JsonResponse({"ok": True, "id": subscription.pk})


@login_required
@require_POST
def push_delete(request, subscription_id: int):
    """POST `/me/notifications/push/<id>/delete/` — удалить своё устройство; чужое и несуществующее — 404."""
    push.delete(request.user, subscription_id, ip=request.client_ip)
    if is_fragment(request):
        return HttpResponse(render_to_string("notify/me/_devices.html", _devices_context(request.user),
                                             request=request))
    flash(request, "Устройство удалено.")
    return HttpResponseRedirect(ME_URL)


# --- привязки Telegram и MAX ------------------------------------------------------------------------------------

def _binding_response(request, channel: str, issued=None):
    """Блок привязки: на запрос HTMX — один блок, иначе полная страница с тем же блоком. Ответ всегда 200."""
    if is_fragment(request):
        code, error = (issued[1], issued[2]) if issued else (None, "")
        return HttpResponse(render_binding(channel, binding_state(request.user.pk, channel), code=code,
                                           error=error, request=request))
    return _render_page(request, _page_context(request, issued=issued))


@login_required
@require_POST
def bind(request, channel: str):
    """POST `/me/notifications/bind/<канал>/` — новый код привязки (открытый, показывается только в этом ответе)."""
    try:
        code = binding.new_code(request.user, channel)
    except NotifyError as error:
        return _binding_response(request, channel, (channel, None, error.code))
    return _binding_response(request, channel, (channel, code, ""))


@login_required
@require_POST
def unbind(request, channel: str):
    """POST `/me/notifications/unbind/<канал>/` — отвязать канал; без привязки — тот же ответ."""
    binding.unbind(request.user, channel, actor=request.user, ip=request.client_ip)
    if is_fragment(request):
        return _binding_response(request, channel)
    flash(request, UNBOUND_FLASH[channel])
    return HttpResponseRedirect(ME_URL)
