"""Публичный интерфейс уведомлений: обработка входящих сообщений ботов (PLAN-004, «Где живёт код»; CONTRACT-004, 5.4, 6.14).

`handle_update` разбирает одно событие бота (привязка чата кодом, снятие привязки), `poll_once` — один шаг цикла
опроса, `start_cycle` — начало цикла. Клиенты ботов зовутся через модуль (`telegram_client.get_updates(...)`):
тесты подменяют атрибуты модулей.
"""
import logging
from datetime import timedelta

from django.db import transaction
from django.utils import timezone

from apps.integrations import channel as channel_errors
from apps.integrations.max import client as max_client
from apps.integrations.telegram import client as telegram_client

from ..models import BindCode, BotChat, BotState, ChatBinding
from . import binding
from . import settings as notify_settings
from .errors import NotifyError

log = logging.getLogger(__name__)

PAUSE_CONFLICT = 30
PAUSE_IDLE = 60
PAUSE_ERROR = 5
PAUSE_BAD_TOKEN = 60
MAX_ATTEMPTS = 5
WINDOW_MINUTES = 10

REPLY_KEYS = ("ask_code", "bound", "code_invalid", "chat_taken", "too_many")
_REPLIES = {
    "ask_code": "Отправьте код из раздела «Мои уведомления» портала",
    "code_invalid": "Код недействителен или просрочен. Получите новый код в портале",
    "chat_taken": "Этот чат уже привязан к другой учётной записи портала",
    "too_many": "Слишком много попыток, попробуйте позже",
}
_BOUND = {"telegram": "Telegram привязан к вашей учётной записи портала",
          "max": "MAX привязан к вашей учётной записи портала"}
_LINKS = {"telegram": "https://t.me/", "max": "https://max.ru/"}


def _client(channel: str):
    return telegram_client if channel == "telegram" else max_client


def active(channel: str) -> bool:
    """Канал включён администратором и токен задан."""
    return notify_settings.channel_on(channel)


def bot_link(channel: str) -> str | None:
    """Ссылка на бота по имени из `BotState`; имени ещё нет — `None`. Кода и токена в ссылке нет."""
    state = BotState.objects.filter(channel=channel).first()
    if state is None or not state.bot_username:
        return None
    return _LINKS[channel] + state.bot_username


def reply_text(key: str, channel: str) -> str:
    """Текст ответа бота по ключу из `REPLY_KEYS`; чужой ключ — `KeyError`."""
    if key not in REPLY_KEYS:
        raise KeyError(key)
    return _BOUND[channel] if key == "bound" else _REPLIES[key]


# --- ответы бота -----------------------------------------------------------------------------------------------

def _reply(channel: str, chat_id: str, key: str) -> None:
    """Ответ бота после фиксации: ошибки адаптера ловятся (в журнал приложения — без токена и адреса)."""
    try:
        _client(channel).send_message(chat_id, reply_text(key, channel))
    except channel_errors.ChannelGone:
        log.warning("Ответ бота (%s): чат недоступен", channel)
        try:
            link = ChatBinding.objects.filter(channel=channel, chat_id=chat_id).first()
            if link is not None:
                binding.unbind(link.user_id, channel, actor=None, reason="bot_unavailable")
        except Exception:  # noqa: BLE001 - ответ боту не должен ронять обработку события
            log.warning("Ответ бота (%s): не удалось снять привязку недоступного чата", channel)
    except channel_errors.ChannelError as exc:
        log.warning("Ответ бота (%s): %s", channel, exc)


def _answer(channel: str, chat_id: str, key: str) -> None:
    transaction.on_commit(lambda: _reply(channel, chat_id, key))


# --- разбор события --------------------------------------------------------------------------------------------

def _parse(channel: str, update: dict) -> tuple[str, str, str]:
    """(вид, номер чата, текст). Вид: `start`, `text`, `stopped` или `ignored`."""
    ignored = ("ignored", "", "")
    if channel == "telegram":
        message = update.get("message")
        if isinstance(message, dict):
            chat = message.get("chat") or {}
            text = message.get("text")
            if chat.get("type") != "private" or "id" not in chat or not isinstance(text, str):
                return ignored
            kind = "start" if text.startswith("/start") else "text"
            return kind, str(chat["id"]), text
        member = update.get("my_chat_member")
        if isinstance(member, dict):
            chat = member.get("chat") or {}
            status = (member.get("new_chat_member") or {}).get("status")
            if chat.get("type") == "private" and "id" in chat and status == "kicked":
                return "stopped", str(chat["id"]), ""
        return ignored
    kind = update.get("update_type")
    if kind in ("bot_started", "bot_stopped"):
        if update.get("chat_id") is None:
            return ignored
        return ("start" if kind == "bot_started" else "stopped"), str(update["chat_id"]), ""
    if kind == "message_created":
        message = update.get("message") or {}
        recipient = message.get("recipient") or {}
        text = (message.get("body") or {}).get("text")
        if recipient.get("chat_type") != "dialog" or recipient.get("chat_id") is None or not isinstance(text, str):
            return ignored
        return "text", str(recipient["chat_id"]), text
    return ignored


def handle_update(channel: str, update: dict) -> str:
    """Одно событие бота в своей транзакции; возвращает код результата (CONTRACT-004, 6.14).

    Ответ бота уходит после фиксации: откатившееся событие ответа не даёт."""
    kind, chat_id, text = _parse(channel, update)
    with transaction.atomic():
        if kind == "ignored":
            return "ignored"
        if kind == "stopped":
            return _stopped(channel, chat_id)
        if kind == "start":
            BotChat.objects.get_or_create(channel=channel, chat_id=chat_id)
            _answer(channel, chat_id, "ask_code")
            return "dialog_started"
        return _text(channel, chat_id, text)


def _stopped(channel: str, chat_id: str) -> str:
    link = ChatBinding.objects.filter(channel=channel, chat_id=chat_id).first()
    if link is None:
        return "ignored"
    binding.unbind(link.user_id, channel, actor=None, reason="bot_unavailable")
    return "unbound"


def _text(channel: str, chat_id: str, text: str) -> str:
    chat = BotChat.objects.select_for_update().filter(channel=channel, chat_id=chat_id).first()
    if chat is None:
        _answer(channel, chat_id, "ask_code")
        return "ask_code"
    now = timezone.now()
    if chat.window_started_at is None or now - chat.window_started_at > timedelta(minutes=WINDOW_MINUTES):
        chat.window_started_at = now
        chat.bad_attempts = 0
        chat.save(update_fields=["window_started_at", "bad_attempts"])
    if chat.bad_attempts >= MAX_ATTEMPTS:
        _answer(channel, chat_id, "too_many")
        return "too_many"
    code_hash = binding.hash_code(text.strip())
    rows = BindCode.objects.select_for_update().filter(channel=channel, code_hash=code_hash)
    code = rows.filter(used_at__isnull=True, expires_at__gt=now).first()
    if code is not None:
        link = ChatBinding.objects.filter(channel=channel, chat_id=chat_id).first()
        if link is None or link.user_id == code.user_id:
            try:
                binding.bind(code.user_id, channel, chat_id)
            except NotifyError:
                pass  # чат занят другой записью (гонка) — как `chat_taken`
            else:
                code.used_at = now
                code.save(update_fields=["used_at"])
                _answer(channel, chat_id, "bound")
                return "bound"
        _answer(channel, chat_id, "chat_taken")
        return "chat_taken"
    for used in rows.filter(used_at__isnull=False):
        if ChatBinding.objects.filter(user_id=used.user_id, channel=channel, chat_id=chat_id).exists():
            return "repeat"
    chat.bad_attempts += 1
    chat.save(update_fields=["bad_attempts"])
    _answer(channel, chat_id, "code_invalid")
    return "code_invalid"


# --- шаг опроса ------------------------------------------------------------------------------------------------

def _state(channel: str) -> BotState:
    return BotState.objects.get_or_create(channel=channel)[0]


def _save_state(channel: str, **fields) -> None:
    BotState.objects.filter(channel=channel).update(updated_at=timezone.now(), **fields)


def start_cycle(channel: str) -> bool:
    """Начало цикла: обновляет имя бота; у Telegram снимает webhook без сброса ожидающих событий.

    Канал не активен — `False` без сети и записей; ошибка адаптера пишется в `last_error`, наружу не идёт."""
    if not active(channel):
        return False
    _state(channel)
    try:
        client = _client(channel)
        username = str(client.get_me().get("username") or "")
        _save_state(channel, bot_username=username)
        if channel == "telegram":
            client.delete_webhook()
    except channel_errors.ChannelError as exc:
        _note_error(channel, exc)
        return False
    return True


def _note_error(channel: str, exc: Exception) -> float:
    """Записывает код ошибки шага в `BotState.last_error`; возвращает паузу цикла."""
    if isinstance(exc, channel_errors.BadToken):
        _save_state(channel, last_error="bad_token")
        notify_settings.note_channel_error(channel, "bad_token")
        return PAUSE_BAD_TOKEN
    if isinstance(exc, channel_errors.RetryLater):
        if exc.code == 409:
            _save_state(channel, last_error="conflict")
            return PAUSE_CONFLICT
        _save_state(channel, last_error="unavailable")
        return max(1, exc.after) if exc.after is not None else PAUSE_ERROR
    _save_state(channel, last_error="unavailable")
    return PAUSE_ERROR


def poll_once(channel: str, *, wait: int = 25) -> float:
    """Один шаг опроса: запрос, обработка событий (каждое в своей транзакции), курсор после пачки.

    Возвращает паузу в секундах до следующего шага. Исключение обработчика события наружу не ловится: курсор
    не записывается, событие придёт снова."""
    if not active(channel):
        return PAUSE_IDLE
    state = _state(channel)
    try:
        client = _client(channel)
        if channel == "telegram":
            offset = int(state.cursor) + 1 if state.cursor else None
            updates = client.get_updates(offset, timeout=wait)
            new_cursor = str(updates[-1]["update_id"]) if updates else None
        else:
            updates, marker = client.get_updates(int(state.cursor) if state.cursor else None, timeout=wait)
            new_cursor = str(marker) if marker is not None else None
    except channel_errors.ChannelError as exc:
        return _note_error(channel, exc)
    for update in updates:
        handle_update(channel, update)
    fields = {"last_error": ""}
    if new_cursor is not None:
        fields["cursor"] = new_cursor
    _save_state(channel, **fields)
    status = notify_settings.channel_error(channel)
    if status and status.get("code") == "bad_token":
        notify_settings.clear_channel_error(channel)
    return 0.0
