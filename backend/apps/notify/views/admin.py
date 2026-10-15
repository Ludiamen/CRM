"""Страница администратора (`/settings/notifications/`, PLAN-004, «Администратор»; CONTRACT-004, 13.3, 14.4, 15.4–15.5).

Право `notify.manage` проверяется раньше всего прочего (403 на GET и на POST без обращения к службе). Отправка
собирается по группам: переключатели — только с `channels`, сроки — только с `limits`, таблица — только с
`defaults_present`. Отказ службы — 200 той же страницы с `[data-error][data-code]`, ничего не сохранено; успех —
302 на ту же страницу и разовое сообщение. Значений ключей и токенов страница не получает вообще: только «заданы /
не заданы».
"""
from django.http import HttpResponseRedirect
from django.utils.dateparse import parse_datetime
from django.views.decorators.http import require_http_methods

from apps.core.services.permissions import require_permission
from apps.core.views.common import flash, render_page

from ..models import BotState
from ..services import kinds
from ..services import settings as notify_settings
from ..services.errors import NotifyError

MANAGE = "notify.manage"
SETTINGS_URL = "/settings/notifications/"
SAVED = "Настройки уведомлений сохранены."
CHANNEL_TITLES = {"webpush": "Web Push", "telegram": "Telegram", "max": "MAX"}
SWITCHES = {channel: f"{channel}_enabled" for channel in notify_settings.CHANNELS}
CELL_CHANNELS = kinds.EXTERNAL  # email, push, telegram, max
CELL_TITLES = (("email", "Почта"), ("push", "Push в браузере"), ("telegram", "Telegram"), ("max", "MAX"))
ERROR_TEXTS = dict((  # пары «код последней ошибки канала → текст» (§ 15.5)
    ("bad_token", "токен не принят"),
    ("unavailable", "канал недоступен"),
    ("rate_limited", "слишком много запросов"),
))


def _error_text(channel: str, code: str) -> str:
    if code == "bad_token" and channel == "webpush":
        return "ключи не приняты"
    return ERROR_TEXTS.get(code, "")


def _channel_blocks(row, *, switches: dict | None = None) -> list:
    """Блоки трёх каналов: переключатель (значение, не `channel_on`), ключи, имя бота, последняя ошибка."""
    bots = dict(BotState.objects.filter(channel__in=("telegram", "max")).values_list("channel", "bot_username"))
    blocks = []
    for channel in notify_settings.CHANNELS:
        error = (row.channel_status or {}).get(channel)
        blocks.append({
            "channel": channel,
            "title": CHANNEL_TITLES[channel],
            "flag": SWITCHES[channel],
            "enabled": switches[channel] if switches is not None else bool(getattr(row, SWITCHES[channel])),
            "keys": "set" if notify_settings.keys_set(channel) else "unset",
            "has_bot": channel != "webpush",
            "bot_name": bots.get(channel, ""),
            "error": ({"code": error.get("code", ""), "text": _error_text(channel, error.get("code", "")),
                       "at": parse_datetime(error.get("at", ""))} if error else None),
        })
    return blocks


def _rows(row, *, cells: set | None = None) -> list:
    """Строки таблицы: нематериальные виды каталога; `checked` — действующие значения или присланные."""
    mapping = row.defaults or {}
    rows = []
    for kind in kinds.catalog():
        if kind.mandatory:
            continue
        if kind.code in mapping:
            effective = set(mapping[kind.code])
        else:
            effective = set(kind.default_channels)
        rows.append({"code": kind.code, "title": kind.title, "cells": [
            {"channel": channel, "title": title, "value": f"{kind.code}:{channel}",
             "checked": (f"{kind.code}:{channel}" in cells) if cells is not None else channel in effective}
            for channel, title in CELL_TITLES]})
    return rows


def _context(*, error=None, switches=None, limits=None, cells=None) -> dict:
    row = notify_settings.get()
    limits = limits or {"email_delay_minutes": str(row.email_delay_minutes), "retention_days": str(row.retention_days)}
    return {"blocks": _channel_blocks(row, switches=switches), "rows": _rows(row, cells=cells), "limits": limits,
            "error": error, "cell_titles": CELL_TITLES}


def _page(request, **kwargs):
    return render_page(request, "notify/admin/settings.html", _context(**kwargs))


@require_permission(MANAGE)
@require_http_methods(["GET", "POST"])
def settings_page(request):
    """GET, POST `/settings/notifications/` — каналы, значения по умолчанию, сроки (T-4232)."""
    if request.method == "GET":
        return _page(request)
    post = request.POST
    fields = {}
    switches = limits = cells = None
    if "channels" in post:
        switches = {channel: post.get(flag) == "1" for channel, flag in SWITCHES.items()}
        fields.update({SWITCHES[channel]: value for channel, value in switches.items()})
    if "limits" in post:
        limits = {"email_delay_minutes": post.get("email_delay_minutes", ""),
                  "retention_days": post.get("retention_days", "")}
        fields.update(limits)
    if "defaults_present" in post:
        cells = set(post.getlist("cell"))
        defaults = {kind.code: [] for kind in kinds.catalog() if not kind.mandatory}
        for value in cells:
            code, _, channel = value.partition(":")
            if code in defaults and channel in CELL_CHANNELS and channel not in defaults[code]:
                defaults[code].append(channel)
        fields["defaults"] = defaults
    try:
        notify_settings.update(actor=request.user, ip=request.client_ip, **fields)
    except NotifyError as error:
        return _page(request, error={"field": error.field, "code": error.code, "message": error.message},
                     switches=switches, limits=limits, cells=cells)
    flash(request, SAVED)
    return HttpResponseRedirect(SETTINGS_URL)
