"""Чат отдела: создание по галочке, системные записи и удаление (срез 008, T-8205).

PLAN-008 «Виды чатов и создание» (чат отдела), «Состав чата отдела и перевод/приём», «Системные записи чата
отдела», «Журнал»; CONTRACT-008 § 3.2, 4.1, 5.2, 8.1. Чат отдела — одна строка `kind="department"` с номером
узла и пустым `title`: название даёт узел через `page.chat_title` (`unit_refs`), поэтому переименование видно
сразу. Создание идемпотентно по номеру узла; две системные записи («Создал чат», «К чату присоединились
сотрудники отдела «<название>»») пишутся в одной транзакции с чатом. Удаление — общее с групповым чатом
(`chats.delete`), журнал получает снимок «название отдела + номер узла» без текста переписки. Модели `org` не
импортируются: номер узла — число, имя берётся через `org.services.structure.unit_refs` под `apps.is_installed`.
"""
from django.apps import apps
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.core.models import User
from apps.messenger.models import Chat, Message
from apps.messenger.services import chats

SYSTEM_CREATED = "Создал чат"
SYSTEM_JOINED = "К чату присоединились сотрудники отдела «{name}»"


def create(unit, actor=None) -> Chat | None:
    """Чат отдела по галочке: одна строка на узел и две системные записи (FR-649).

    Повторное сохранение с галочкой второй строки и лишних записей не делает. Для команды, корня и
    отсутствующего узла — `None` (поля мессенджера у них нет).
    """
    if unit is None or unit.is_root or unit.kind != "department":
        return None
    now = timezone.now()
    lookup = {"kind": Chat.Kind.DEPARTMENT, "unit_id": unit.pk}
    try:
        with transaction.atomic():
            chat, created = Chat.objects.get_or_create(
                **lookup, defaults={"title": "", "created_at": now, "last_message_at": now})
            if created:
                Message.objects.bulk_create([
                    Message(chat=chat, author=None, is_system=True, text=SYSTEM_CREATED, created_at=now),
                    Message(chat=chat, author=None, is_system=True,
                            text=SYSTEM_JOINED.format(name=unit.name), created_at=now),
                ])
    except IntegrityError:
        # Параллельное сохранение уже создало чат: второй строки не появляется.
        chat = Chat.objects.get(**lookup)
    return chat


def delete(chat, actor) -> None:
    """Удаление чата отдела администратором портала: журнал «название отдела, номер узла» (FR-672, 671)."""
    unit_id = chat.unit_id
    name = _unit_name(unit_id)
    chats.delete(chat, actor, audit_code="messenger.department_chat_deleted",
                 snapshot={"chat_title": name, "unit_id": unit_id})


def on_unit_deleted(unit_id: int, name: str = "", actor_id=None, **extra) -> None:
    """Обработчик шины `unit.deleted`: чат удалённого узла исчезает вместе с историей (FR-650, 671).

    Событие приходит после фиксации удаления узла, поэтому сбой обработчика удаление не откатывает.
    """
    chat = Chat.objects.filter(kind=Chat.Kind.DEPARTMENT, unit_id=unit_id).first()
    if chat is None:
        return
    actor = User.objects.filter(pk=actor_id).first() if actor_id else None
    chats.delete(chat, actor, audit_code="messenger.unit_chat_deleted",
                 snapshot={"chat_title": name, "unit_id": unit_id})


def _unit_name(unit_id) -> str:
    """Имя узла через публичную службу `org`; без `apps.org` и у исчезнувшего узла — пустая строка."""
    if unit_id is None or not apps.is_installed("apps.org"):
        return ""

    from apps.org.services import structure

    ref = structure.unit_refs([unit_id]).get(int(unit_id))
    return ref.name if ref is not None else ""