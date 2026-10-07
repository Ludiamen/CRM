"""Очистка данных среза командой стенда (PLAN-003, «Где живёт код»; CONTRACT-003, 8.3).

`stand_reset` — функция точки `stand_reset`: возвращает данные среза к состоянию сразу после миграций (`0003_initial_data`):
стирает заявки, письма, заявителей, подразделения-клиенты, очереди-отметки, справочники и настройки и создаёт начальные
справочники и настройки заново; сбрасывает последовательность номеров, файлы `attachments/` и `inbound/`, очереди `inbox`
и `maintenance`, ключи порога формы и ставит `MailboxState` на конец ящика. Идёт под владельцем схемы (алиас `migrate`).
Общая очистка таблиц ядра с каскадом уже стёрла часть таблиц среза, поэтому функция не рассчитывает на их строки.
"""
import importlib
import pathlib
import shutil

import django_rq
from django.conf import settings
from django.db import connections, transaction
from django.utils import timezone

from apps.core.services import valkey
from apps.integrations.mail import imap

from .models import (Category, ClientUnit, Complexity, InboundMail, MailboxState, Priority, Queue, Requester,
                     RequesterImport, ServiceDeskSettings, Source, Status, Ticket)
from .services import form

# Начальные значения — константы миграции данных (имя модуля начинается с цифры, поэтому `importlib`)
_initial = importlib.import_module("apps.servicedesk.migrations.0003_initial_data")
PROTECTED_DIRS = ("attachments", "inbound")
QUEUES = ("inbox", "maintenance")


def _clear_dir(root: pathlib.Path) -> None:
    """Стирает содержимое каталога; сам каталог остаётся (нет каталога — ничего не делает)."""
    if not root.is_dir():
        return
    for item in root.iterdir():
        if item.is_dir() and not item.is_symlink():
            shutil.rmtree(item, ignore_errors=True)
        else:
            item.unlink(missing_ok=True)


def _erase(db: str) -> None:
    """Стирает данные среза в порядке зависимостей `PROTECT`: заявки раньше справочников, настройки раньше критичностей."""
    for model in (Ticket, InboundMail, Requester, RequesterImport, ClientUnit, Queue, ServiceDeskSettings, Category,
                  Source, Complexity, Status, Priority):
        model.objects.using(db).all().delete()


def _seed(db: str) -> None:
    """Начальные справочники и настройки, как после миграций; `Priority` — раньше `ServiceDeskSettings`."""
    key = _initial.name_key
    for name, kind, is_default, system_code, order in _initial.STATUSES:
        Status.objects.using(db).create(name=name, name_key=key(name), kind=kind, is_default=is_default,
                                        system_code=system_code, order=order)
    for name, order in _initial.PRIORITIES:
        Priority.objects.using(db).create(name=name, name_key=key(name), order=order)
    for name, order in _initial.COMPLEXITIES:
        Complexity.objects.using(db).create(name=name, name_key=key(name), order=order)
    for name, system_code, order in _initial.SOURCES:
        Source.objects.using(db).create(name=name, name_key=key(name), system_code=system_code, order=order)
    Category.objects.using(db).create(name=_initial.OTHER_CATEGORY, name_key=key(_initial.OTHER_CATEGORY), queue=None,
                                      is_system=True, on_form=True, order=100)
    ServiceDeskSettings.objects.using(db).create(
        pk=1, default_priority=Priority.objects.using(db).get(name_key=key(_initial.DEFAULT_PRIORITY)))


def _reset_mailbox_state(db: str) -> None:
    """`MailboxState` — на текущий конец ящика; ящик не задан или не отвечает — строки нет (создаст первое подключение)."""
    MailboxState.objects.using(db).all().delete()
    if not settings.IMAP_HOST:
        return
    try:
        with imap.connect() as conn:  # через модуль: подмена в тестах
            uidvalidity, uidnext = int(conn.uidvalidity), int(conn.uidnext)
    except (imap.MailboxUnavailable, OSError):
        return
    now = timezone.now()
    MailboxState.objects.using(db).create(pk=1, uidvalidity=uidvalidity, last_uid=uidnext - 1, connected_at=now,
                                          last_poll_at=now, last_ok_at=now, last_error="")


def stand_reset() -> None:
    """Приводит данные среза к состоянию после миграций; идёт под владельцем схемы (алиас `migrate`), если он настроен."""
    db = "migrate" if "migrate" in connections.databases else "default"
    with transaction.atomic(using=db):
        _erase(db)
        _seed(db)
        with connections[db].cursor() as cursor:
            cursor.execute("SELECT setval('servicedesk_ticket_number', 1, false)")
    _reset_mailbox_state(db)
    for name in PROTECTED_DIRS:
        _clear_dir(pathlib.Path(settings.PROTECTED_ROOT) / name)
    for name in QUEUES:
        django_rq.get_queue(name).empty()
    conn = valkey.conn()
    for key in conn.scan_iter(match=f"{form.RATE_PREFIX}*", count=500):  # порог формы: заявки сверх него закрыли бы форму
        conn.delete(key)
