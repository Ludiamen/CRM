"""Публичный интерфейс уведомлений: коды и привязки чатов (PLAN-004, «Где живёт код»; CONTRACT-004, 6.13).

Привязка Telegram и MAX одноразовым кодом: сотрудник получает код на портале, отправляет его боту, а бот-служба
(`bots.handle_update`) зовёт `bind`. В базе хранится только SHA-256 кода; открытый код есть лишь в возврате `new_code`.
"""
import hashlib
import secrets
from datetime import timedelta
from typing import NamedTuple

from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from apps.core.extensions import Draft
from apps.core.services import audit

from ..models import BindCode, ChatBinding
from . import settings as notify_settings
from .errors import NotifyError

CHANNELS = ("telegram", "max")
CODE_MINUTES = 10
_TITLES = {"telegram": "Telegram", "max": "MAX"}
UNBOUND_URL = "/me/notifications/"


class NewCode(NamedTuple):
    """Выданный код: открытый текст существует только здесь."""
    code: str
    expires_at: object


def hash_code(code: str) -> str:
    """SHA-256 текста кода (шестнадцатеричная запись в нижнем регистре)."""
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def _check_channel(channel: str) -> None:
    if channel not in CHANNELS:
        raise NotifyError("bad_channel", "Неизвестный канал", field="channel")


def _user_id(user) -> int:
    return user if isinstance(user, int) else user.pk


def new_code(user, channel: str) -> NewCode:
    """Новый код привязки: восемь цифр, не совпадающих с действующим кодом другого сотрудника в этом канале.

    Прежний неиспользованный код этого сотрудника в канале удаляется в той же транзакции. Канал не включён —
    `channel_disabled`."""
    _check_channel(channel)
    if not notify_settings.channel_on(channel):
        raise NotifyError("channel_disabled", "Канал отключён администратором", field="channel")
    user_id = _user_id(user)
    with transaction.atomic():
        now = timezone.now()
        BindCode.objects.filter(user_id=user_id, channel=channel, used_at__isnull=True).delete()
        while True:
            code = "%08d" % secrets.randbelow(10 ** 8)
            code_hash = hash_code(code)
            taken = BindCode.objects.filter(channel=channel, code_hash=code_hash, used_at__isnull=True,
                                            expires_at__gt=now).exclude(user_id=user_id).exists()
            if not taken:
                break
        expires_at = now + timedelta(minutes=CODE_MINUTES)
        BindCode.objects.create(user_id=user_id, channel=channel, code_hash=code_hash, expires_at=expires_at)
    return NewCode(code, expires_at)


def get(user_id: int, channel: str) -> ChatBinding | None:
    """Привязка сотрудника в канале или `None`."""
    return ChatBinding.objects.filter(user_id=user_id, channel=channel).first()


def bind(user_id: int, channel: str, chat_id, *, ip=None) -> ChatBinding:
    """Привязывает чат; привязка того же канала к другому чату заменяет прежнюю.

    Чат, уже привязанный к другой учётной записи, — `chat_taken`. Пишет в журнал `notify.channel_bound` (без номера
    чата); после фиксации отправляет сотруднику обновлённый блок привязки."""
    _check_channel(channel)
    chat_id = str(chat_id)
    with transaction.atomic():
        if ChatBinding.objects.filter(channel=channel, chat_id=chat_id).exclude(user_id=user_id).exists():
            raise NotifyError("chat_taken", "Этот чат уже привязан к другой учётной записи портала", field="channel")
        current = ChatBinding.objects.select_for_update().filter(user_id=user_id, channel=channel).first()
        if current is not None and current.chat_id == chat_id:
            return current  # тот же чат: ничего не меняется
        before = {"bound": False}
        if current is None:
            link = ChatBinding.objects.create(user_id=user_id, channel=channel, chat_id=chat_id)
        else:
            before = {"channel": channel, "bound": True}
            link = current
            link.chat_id = chat_id
            link.bound_at = timezone.now()
            link.save(update_fields=["chat_id", "bound_at"])
        actor = get_user_model().objects.filter(pk=user_id).first()
        audit.record("notify.channel_bound", actor=actor, object_type="user", object_id=user_id,
                     before=before, after={"channel": channel, "bound": True}, ip=ip)
        transaction.on_commit(lambda: _push_block(user_id, channel))
    return link


def _push_block(user_id: int, channel: str) -> None:
    from . import live

    live.push([user_id], binding=channel)


def unbind(user, channel: str, *, actor=None, ip=None, reason: str = "") -> bool:
    """Снимает привязку и удаляет неиспользованные коды сотрудника в канале; была ли привязка.

    `reason`: `""` (сам сотрудник), `bot_unavailable` (бот недоступен: создаёт уведомление «Канал отвязан»),
    `dismissed`. Ожидающих доставок не трогает. Привязки не было — журнала нет."""
    _check_channel(channel)
    user_id = _user_id(user)
    with transaction.atomic():
        BindCode.objects.filter(user_id=user_id, channel=channel, used_at__isnull=True).delete()
        deleted, _ = ChatBinding.objects.filter(user_id=user_id, channel=channel).delete()
        if not deleted:
            return False
        after = {"bound": False}
        if reason:
            after["reason"] = reason
        audit.record("notify.channel_unbound", actor=actor, object_type="user", object_id=user_id,
                     before={"channel": channel, "bound": True}, after=after, ip=ip)
        if reason == "bot_unavailable":
            from . import dispatch

            text = f"{_TITLES[channel]} отвязан: бот недоступен"
            dispatch.create("notify.channel_unbound", [Draft(user_id, text, UNBOUND_URL, "")])
    return True


def purge_expired_codes() -> int:
    """Удаляет использованные и просроченные коды; возвращает число удалённых."""
    from django.db.models import Q

    deleted, _ = BindCode.objects.filter(Q(used_at__isnull=False) | Q(expires_at__lt=timezone.now())).delete()
    return deleted
