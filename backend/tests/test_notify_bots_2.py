"""T-4119: отправка в Telegram и MAX, ошибки адаптеров, снятие привязки, токены (FR-325, FR-326, FR-332, FR-333,
FR-339, FR-344, NFR-312). Сценарии 6, 8 и 11 спеки среза 004.

Механизм — план «Telegram и MAX» («Адаптеры», «Привязка», «Отвязка», «Канал отвязан»), контракт 5.1-5.2, 6.5, 6.9,
6.13, 6.14, 9.2, 15.1-15.3. Отправка и коды ошибок идут на учебной службе `fakebots` (`bots_on`, решение 4 задач);
запросы клиентов видны через `bots_capture`, ответ 400, сеть и таймаут — подмена точки `transport` (контракт 5.1);
`fake_bot_send` берётся только там, где нужен ChannelGone без сети. Токены — сгенерированные фикстурой `bots_on`;
в названиях переменных слов secret/token/key/password нет, значения токенов в сообщения проверок не попадают.
Код среза 004 на уровне модуля не импортируется (CONTRACT-004, шапка).
"""
import contextlib
import datetime
import html
import json
import logging
import secrets
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings as django_settings
from django.utils import timezone

from tests import support, support_notify as notify
from tests.support import model

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
MOMENT = datetime.datetime(2026, 10, 13, 11, 0, 0, tzinfo=MSK)   # вторник, рабочее время
NIGHT = datetime.datetime(2026, 10, 10, 3, 0, 0, tzinfo=MSK)     # суббота, ночь
KIND = "servicedesk.assigned"
KIND_TEXT = "Вам назначена заявка"                                 # внешний текст вида (15.2)
BUTTON = "Открыть уведомления"                                     # delivery.BUTTON_LABEL (15.2)
SEND_METHOD = {"telegram": "sendMessage", "max": "messages"}       # имя метода для `FakeBots.fail`
ERROR_TEXT = {"telegram": "sendMessage", "max": "POST /messages"}  # начало `str(ChannelError)` (5.1)
LOG_FIELDS = {"at", "outcome", "code", "reason", "sub"}              # ключи записи `Delivery.log` (2.2)


# --- помощники только этого файла -------------------------------------------------------------------------

def _chat_id() -> str:
    """Цифровой номер чата: MAX на `fakebots` принимает только целый `chat_id` (1.2)."""
    return str(700_000_000 + secrets.randbelow(10**8))


def _client(channel: str):
    import importlib
    return importlib.import_module(f"apps.integrations.{channel}.client")


def _bind(user, channel: str, chat: str | None = None):
    return model("notify.ChatBinding").objects.create(user=user, channel=channel, chat_id=chat or _chat_id())


def _bound(user, channel: str) -> bool:
    return model("notify.ChatBinding").objects.filter(user=user, channel=channel).exists()


def _note(user, *, kind: str = KIND, text: str | None = None):
    return model("notify.Notification").objects.create(
        user=user, kind=kind, text=text or "Тест " + secrets.token_hex(5), url="/tickets/1/",
        object_ref="servicedesk.ticket:1", created_at=timezone.now())


def _delivery(channel: str, *, user=None, bind: bool = True, kind: str = KIND, text: str | None = None):
    """Доставка `waiting` со сроком в прошлом; привязка с цифровым номером чата создаётся, если её ещё нет."""
    user = user or support.make_employee()
    if bind and not _bound(user, channel):
        _bind(user, channel)
    return model("notify.Delivery").objects.create(
        notification=_note(user, kind=kind, text=text), channel=channel, state="waiting",
        due_at=timezone.now() - datetime.timedelta(seconds=5))


def _chat_of(user, channel: str) -> str:
    return model("notify.ChatBinding").objects.get(user=user, channel=channel).chat_id


def _send(row) -> str:
    from apps.notify.services import delivery
    return delivery.send_delivery(row.pk)


def _fresh(row):
    row.refresh_from_db()
    return row


def _status(channel: str):
    from apps.notify.services import settings as notify_settings
    return notify_settings.channel_error(channel)


def _raised(call):
    try:
        call()
    except Exception as exc:  # noqa: BLE001 - тест ищет исключение адаптера
        return exc
    pytest.fail("ожидалось исключение адаптера, его не было")


def _body_400(channel: str) -> bytes:
    if channel == "telegram":
        return json.dumps({"ok": False, "error_code": 400, "description": "Bad Request: chat not found"}).encode()
    return json.dumps({"code": "proto.payload", "message": "Invalid chat"}).encode()


@contextlib.contextmanager
def _failing(channel: str, how, bots, monkeypatch, *, hostile: bool = False):
    """Следующий запрос отправки канала получит сбой `how`: код 401/403/409/429/500 — через `fakebots`,
    400 — ответ из `bots_capture`, `"network"` и `"timeout"` — подмена `transport`. `hostile` — подменная функция
    кладёт в текст ошибки адрес запроса и заголовки (проверка, что адаптер их не пропускает)."""
    from apps.integrations import channel as shared

    client = _client(channel)
    if isinstance(how, int) and how != 400:
        bots.fail(channel, how, method=SEND_METHOD[channel], retry_after=3)
        yield
    elif how == 400:
        answer = shared.Response(400, {"content-type": "application/json"}, _body_400(channel))
        with notify.bots_capture(client, passthrough=False, responses=answer):
            yield
    else:
        error_class = OSError if how == "network" else TimeoutError

        def broken(request, timeout):
            text = "connection problem"
            if hostile:
                text = request.full_url + " " + repr(dict(request.header_items()))
            raise error_class(text)

        with monkeypatch.context() as patch:
            patch.setattr(client, "transport", broken)
            yield


def _provoke(channel: str, how, bots, monkeypatch):
    """Исключение адаптера на вызове `send_message` при сбое `how`."""
    client = _client(channel)
    chat = _chat_id()
    with _failing(channel, how, bots, monkeypatch, hostile=True):
        return _raised(lambda: client.send_message(chat, "Проверка"))


def _values() -> dict:
    return {"telegram": django_settings.TELEGRAM_BOT_TOKEN, "max": django_settings.MAX_BOT_TOKEN}


def _expected_type(channel: str, how):
    from apps.integrations import channel as shared
    if how == 401:
        return shared.BadToken
    if how == 403:
        return shared.ChannelGone
    if how == 400:
        return shared.BadRequest
    return shared.RetryLater


def _audit(user=None) -> list:
    rows = model("core.AuditEvent").objects.filter(action="notify.channel_unbound")
    if user is not None:
        rows = rows.filter(object_id=str(user.pk))
    return list(rows.order_by("id"))


def _unbound_notes(user) -> list:
    return list(model("notify.Notification").objects.filter(user=user, kind="notify.channel_unbound").order_by("id"))


# --- разбор разметки (страница администратора, зацепки 14.4) ---------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.parent, self.children = tag, parent, []
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}

    def walk(self):
        for child in self.children:
            if isinstance(child, _Node):
                yield child
                yield from child.walk()


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = _Node("#root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in _VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(_Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent


def _channel_error_nodes(page: str, channel: str) -> list:
    """Элементы `[data-channel-error]` внутри `section[data-channel-block="<канал>"]` (14.4)."""
    parser = _Tree()
    parser.feed(page)
    found = []
    for block in parser.root.walk():
        if block.tag == "section" and block.attrs.get("data-channel-block") == channel:
            found += [n for n in block.walk() if "data-channel-error" in n.attrs]
    return found


def _time_nodes(node) -> list:
    return [n for n in node.walk() if n.tag == "time" and "data-at" in n.attrs]


# --- 1-7. сообщение: разметка, кнопка, экранирование, длина, состав --------------------------------------------

def test_telegram_send_uses_html_parse_mode_and_disabled_link_preview(bots_on):
    """FR-325 (план, «Адаптеры»): `sendMessage` — POST с телом JSON, `parse_mode=HTML`, предпросмотр ссылок выключен;
    текст — внешний текст вида; ответ службы принят, доставка `sent`."""
    user = support.make_employee()
    row = _delivery("telegram", user=user)
    chat = _chat_of(user, "telegram")
    with notify.bots_capture(_client("telegram")) as capture:
        assert _send(row) == "sent"
    assert len(capture.requests) == 1
    request = capture.requests[0]
    assert request.method == "POST"
    assert request.headers["content-type"].startswith("application/json")
    assert request.json["parse_mode"] == "HTML"
    assert request.json["link_preview_options"] == {"is_disabled": True}
    assert str(request.json["chat_id"]) == chat and request.json["text"] == KIND_TEXT
    stored = bots_on.sent("telegram")
    assert len(stored) == 1
    assert stored[0]["parse_mode"] == "HTML" and stored[0]["link_preview_options"] == {"is_disabled": True}
    assert str(stored[0]["chat_id"]) == chat and stored[0]["text"] == KIND_TEXT
    row = _fresh(row)
    assert (row.state, row.attempts, row.reason) == ("sent", 1, "")


def test_max_send_uses_format_html_and_link_button_attachment(bots_on):
    """FR-325 (план, «Адаптеры»): MAX — `POST /messages` с `chat_id` в адресе, телом `text` и `format=html`, кнопкой
    `inline_keyboard` с одной ссылкой `type=link` на страницу уведомлений (контракт 5.2)."""
    user = support.make_employee()
    row = _delivery("max", user=user)
    chat = _chat_of(user, "max")
    page = django_settings.PORTAL_URL.rstrip("/") + "/notifications/"
    buttons = [{"type": "inline_keyboard", "payload": {"buttons": [[{"type": "link", "text": BUTTON, "url": page}]]}}]
    with notify.bots_capture(_client("max")) as capture:
        assert _send(row) == "sent"
    assert len(capture.requests) == 1
    request = capture.requests[0]
    assert request.method == "POST" and str(request.params["chat_id"]) == chat
    assert request.json["format"] == "html" and request.json["text"] == KIND_TEXT
    assert request.json["attachments"] == buttons
    stored = bots_on.sent("max")
    assert len(stored) == 1
    assert stored[0]["format"] == "html" and stored[0]["text"] == KIND_TEXT and stored[0]["attachments"] == buttons
    assert str(stored[0]["chat_id"]) == chat
    assert _fresh(row).state == "sent"


def test_telegram_message_has_link_button_to_notifications_page_only(bots_on):
    """FR-325 (план, «Адаптеры»): в кнопке только адрес страницы уведомлений `PORTAL_URL/notifications/` — ни номера
    заявки, ни адреса уведомления, ни параметров; кнопка одна, подпись — «Открыть уведомления» (решение E14)."""
    row = _delivery("telegram")
    assert _send(row) == "sent"
    markup = bots_on.sent("telegram")[0]["reply_markup"]
    if isinstance(markup, str):
        markup = json.loads(markup)
    page = django_settings.PORTAL_URL.rstrip("/") + "/notifications/"
    assert markup == {"inline_keyboard": [[{"text": BUTTON, "url": page}]]}
    url = markup["inline_keyboard"][0][0]["url"]
    no_extras = "?" not in url and "#" not in url and "/tickets/" not in url and "/open/" not in url
    assert no_extras, "в адресе кнопки лишние части"


def test_dynamic_parts_of_message_are_html_escaped(bots_on):
    """FR-325, NFR-312 (решение E14): внешний текст вида проходит `html.escape` — «<b>&» уходит в Telegram и MAX как
    «&lt;b&gt;&amp;» (формат разметки HTML)."""
    from apps.core import extensions
    from apps.core.extensions import NotificationKind

    user = support.make_employee()
    kind = NotificationKind(code="test.markup", title="Проверка разметки", module="Тест", external_text="<b>&",
                            default_channels=("portal", "telegram", "max"))
    with extensions.empty():
        notify.register_kind(kind)
        for channel in ("telegram", "max"):
            row = _delivery(channel, user=user, kind="test.markup", text="Текст для портала")
            assert _send(row) == "sent"
            assert bots_on.sent(channel)[-1]["text"] == "&lt;b&gt;&amp;"


def _long_text_case(channel: str, bots, limit: int) -> None:
    from apps.core import extensions
    from apps.core.extensions import NotificationKind

    user = support.make_employee()
    for length in (limit - 1, limit, limit + 1, limit + 900):
        text = ("абвгдежзик" * (length // 10 + 1))[:length]
        kind = NotificationKind(code="test.long", title="Длинный текст", module="Тест", external_text=text,
                                default_channels=("portal", channel))
        with extensions.empty():
            notify.register_kind(kind)
            row = _delivery(channel, user=user, kind="test.long", text="Текст для портала")
            assert _send(row) == "sent"
        sent = bots.sent(channel)[-1]["text"]
        assert sent == text[:limit], f"{channel}: при длине {length} сообщение имеет длину {len(sent)}, ждали {min(length, limit)}"


def test_telegram_text_is_cut_to_4096_characters(bots_on):
    """FR-325 (план, «Адаптеры»): текст Telegram не длиннее 4096 знаков — простой срез `[:4096]`; короче или ровно
    4096 уходит без изменений (контракт 5.2)."""
    _long_text_case("telegram", bots_on, 4096)


def test_max_text_is_cut_to_4000_characters(bots_on):
    """FR-325 (план, «Адаптеры»): текст MAX не длиннее 4000 знаков — срез `[:4000]`; короче или ровно 4000 — без
    изменений (контракт 5.2)."""
    _long_text_case("max", bots_on, 4000)


def test_message_has_no_ticket_number_subject_names_or_addresses(bots_on):
    """FR-325, FR-317 (дополнение 9 контракта): в сообщении бота только внешний текст вида; номер заявки, тема,
    имя и адрес сотрудника в него и в кнопку не попадают, хотя стоят в `Notification.text`."""
    user = support.make_employee()
    subject = "Секретная тема " + secrets.token_hex(4)
    full = f"Вам назначена заявка #4821: {subject}, Иван Петров-Сидоров, {user.email}"
    for channel in ("telegram", "max"):
        row = _delivery(channel, user=user, text=full)
        assert _send(row) == "sent"
        message = {k: v for k, v in bots_on.sent(channel)[-1].items()
                   if k not in ("chat_id", "user_id", "message_id", "time")}
        assert message["text"] == html.escape(KIND_TEXT)
        dumped = json.dumps(message, ensure_ascii=False)
        markers = ("#4821", "Секретная", subject, "Петров", user.email)
        leaked = [m for m in markers if m in dumped]
        assert not leaked, f"{channel}: в сообщении есть {len(leaked)} из внутренних данных уведомления"


# --- 8-10. отвязка (FR-326, FR-339) ---------------------------------------------------------------------------

def test_unbind_deletes_binding_and_unused_codes(bots_on):
    """FR-326, FR-339: «Отвязать» удаляет привязку и неиспользованные коды сотрудника в этом канале; другой канал
    и коды другого сотрудника остаются; повторная отвязка — `False` (контракт 6.13)."""
    from apps.notify.services import binding

    user, other = support.make_employee(), support.make_employee()
    for channel in ("telegram", "max"):
        _bind(user, channel)
        binding.new_code(user, channel)
    binding.new_code(other, "telegram")
    codes = model("notify.BindCode").objects
    assert codes.filter(user=user, channel="telegram").count() == 1

    assert binding.unbind(user, "telegram", actor=user) is True

    assert not _bound(user, "telegram") and not codes.filter(user=user, channel="telegram").exists()
    assert _bound(user, "max") and codes.filter(user=user, channel="max").count() == 1
    assert codes.filter(user=other, channel="telegram").count() == 1
    assert binding.unbind(user, "telegram", actor=user) is False
    assert not codes.filter(user=user, channel="telegram").exists()


def test_no_message_is_sent_after_unbind(bots_on):
    """FR-326 (решение B2): после «Отвязать» ожидающая доставка не трогается, но отправка без привязки — `skipped`
    с причиной `not_bound`; в бот не уходит ни запроса, ни сообщения."""
    from apps.notify.services import binding

    for channel in ("telegram", "max"):
        user = support.make_employee()
        row = _delivery(channel, user=user)
        assert binding.unbind(user, channel, actor=user) is True
        assert _fresh(row).state == "waiting"
        with notify.bots_capture(_client(channel)) as capture:
            assert _send(row) == "skipped"
        assert capture.requests == []
        row = _fresh(row)
        assert (row.state, row.reason) == ("skipped", "not_bound")
        assert bots_on.sent(channel) == []


def test_old_code_after_unbind_is_not_accepted(bots_on, django_capture_on_commit_callbacks):
    """FR-326, FR-339: код, выданный до отвязки, после неё недействителен — привязки нет, бот отвечает отказом с
    подсказкой «Код недействителен или просрочен» (`code_invalid`); коды сотрудника удалены."""
    from apps.notify.services import binding, bots

    for channel in ("telegram", "max"):
        user = support.make_employee()
        old = binding.new_code(user, channel).code
        _bind(user, channel)
        assert binding.unbind(user, channel, actor=user) is True
        assert not model("notify.BindCode").objects.filter(user=user, channel=channel).exists()

        chat, person = int(_chat_id()), int(_chat_id())
        if channel == "telegram":
            start = {"message": {"chat": {"id": chat, "type": "private"}, "from": {"id": person}, "text": "/start"}}
            text = {"message": {"chat": {"id": chat, "type": "private"}, "from": {"id": person}, "text": old}}
        else:
            start = {"update_type": "bot_started", "chat_id": chat, "user": {"user_id": person}}
            text = {"update_type": "message_created",
                    "message": {"sender": {"user_id": person}, "recipient": {"chat_id": chat, "chat_type": "dialog"},
                                "body": {"text": old}}}
        with django_capture_on_commit_callbacks(execute=True):
            assert bots.handle_update(channel, start) == "dialog_started"
        with django_capture_on_commit_callbacks(execute=True):
            assert bots.handle_update(channel, text) == "code_invalid"
        assert not _bound(user, channel)
        assert not model("notify.ChatBinding").objects.filter(channel=channel, chat_id=str(chat)).exists()
        replies = [m["text"] for m in bots_on.sent(channel)]
        assert replies[-1] == bots.reply_text("code_invalid", channel)
        assert replies[-1] == "Код недействителен или просрочен. Получите новый код в портале"


# --- 11-16. канал отвязан (FR-332, FR-344) --------------------------------------------------------------------

def _gone_case(channel: str, bots):
    """Доставка в канал получает 403 от `fakebots`: итог, привязка и уведомление «Канал отвязан»."""
    user = support.make_employee()
    other_channel = "max" if channel == "telegram" else "telegram"
    neighbour = support.make_employee()
    row = _delivery(channel, user=user)
    _bind(user, other_channel)
    _bind(neighbour, channel)
    bots.fail(channel, 403, method=SEND_METHOD[channel])
    assert _send(row) == "failed"
    row = _fresh(row)
    assert (row.state, row.reason, row.attempts, row.lease_until) == ("failed", "channel_unbound", 1, None)
    assert (row.log[-1]["outcome"], row.log[-1]["code"], row.log[-1]["reason"]) == ("failed", 403, "channel_unbound")
    assert not _bound(user, channel)
    # снимается только привязка этого канала этого сотрудника (FR-332, § 6.13 unbind)
    assert _bound(user, other_channel) and _bound(neighbour, channel)
    assert _unbound_notes(neighbour) == []
    assert bots.sent(channel) == []
    return user, row


def test_telegram_403_unbinds_chat_and_creates_channel_unbound_notification(bots_on):
    """FR-332, FR-344: ответ 403 Telegram — привязка снята, доставка `failed` (`channel_unbound`), на портале
    создано уведомление вида «Канал отвязан» с текстом по FR-316 и ссылкой на «Мои уведомления»."""
    user, row = _gone_case("telegram", bots_on)
    notes = _unbound_notes(user)
    assert len(notes) == 1
    assert (notes[0].text, notes[0].url) == ("Telegram отвязан: бот недоступен", "/me/notifications/")
    assert row.log and row.log[-1]["code"] == 403


def test_max_channel_gone_unbinds_chat_and_creates_channel_unbound_notification(bots_on):
    """FR-332, FR-344: ответ 403 MAX (бот остановлен или недоступен) — привязка снята, доставка `failed`
    (`channel_unbound`), создано уведомление «MAX отвязан: бот недоступен»."""
    user, row = _gone_case("max", bots_on)
    notes = _unbound_notes(user)
    assert len(notes) == 1
    assert (notes[0].text, notes[0].url) == ("MAX отвязан: бот недоступен", "/me/notifications/")
    assert row.log and row.log[-1]["code"] == 403


def test_channel_unbound_texts_for_telegram_and_max(bots_on):
    """FR-344, FR-316: автоматическая отвязка (`reason="bot_unavailable"`) создаёт уведомление «Telegram отвязан: бот
    недоступен» или «MAX отвязан: бот недоступен»; текст зависит от канала, вид — `notify.channel_unbound`."""
    from apps.notify.services import binding

    expected = {"telegram": "Telegram отвязан: бот недоступен", "max": "MAX отвязан: бот недоступен"}
    user = support.make_employee()
    for channel in ("telegram", "max"):
        _bind(user, channel)
        assert binding.unbind(user, channel, actor=None, reason="bot_unavailable") is True
    notes = _unbound_notes(user)
    assert [n.text for n in notes] == [expected["telegram"], expected["max"]]
    assert {n.kind for n in notes} == {"notify.channel_unbound"} and {n.url for n in notes} == {"/me/notifications/"}


def test_channel_unbound_is_portal_only_and_not_held_by_quiet_hours(bots_on, webpush_on, clock,
                                                                   django_capture_on_commit_callbacks):
    """FR-344: уведомление «Канал отвязан» идёт только на портал — без доставок, без задержки тихими часами (и в
    рабочее, и в ночное время), без сводки и заданий в очереди, хотя у сотрудника доступны все внешние каналы."""
    from apps.notify.services import binding

    user = support.make_employee()
    notify.subscribe(user)
    for moment in (MOMENT, NIGHT):
        clock.set(moment)
        _bind(user, "telegram")
        _bind(user, "max")
        with django_capture_on_commit_callbacks(execute=True):
            assert binding.unbind(user, "telegram", actor=None, reason="bot_unavailable") is True
        note = _unbound_notes(user)[-1]
        assert not model("notify.Delivery").objects.filter(notification__user=user).exists()
        assert model("notify.Digest").objects.filter(user=user).count() == 0
        assert not model("notify.UserNotifySettings").objects.filter(user=user, digest_due_at__isnull=False).exists()
        assert notify.queued() == [] and note.read_at is None
        model("notify.ChatBinding").objects.filter(user=user).delete()


def test_channel_unbound_audit_record_is_by_system_without_chat_id(bots_on):
    """FR-332 (9.2): автоматическая отвязка пишет `notify.channel_unbound` от системы (без автора): объект —
    сотрудник, «было» `{channel, bound: true}`, «стало» `{bound: false, reason: bot_unavailable}`; идентификатора
    чата нет."""
    for channel in ("telegram", "max"):
        user = support.make_employee()
        row = _delivery(channel, user=user)
        chat = _chat_of(user, channel)
        bots_on.fail(channel, 403, method=SEND_METHOD[channel])
        assert _send(row) == "failed"
        events = _audit(user)
        assert len(events) == 1
        event = events[0]
        assert event.actor is None and (event.object_type, event.object_id) == ("user", str(user.pk))
        assert event.before == {"channel": channel, "bound": True}
        assert event.after == {"bound": False, "reason": "bot_unavailable"}
        leaked = chat in json.dumps([event.before, event.after])
        assert not leaked, "идентификатор чата попал в запись журнала"


def test_delivery_to_unbound_channel_fails_with_reason_channel_unbound(settings):
    """FR-332 (имя неточно, решения B2, E25): проверяется доставка, на которой адаптер ответил `ChannelGone` —
    `failed` с причиной `channel_unbound`, привязка снята; доставка без привязки вовсе — `skipped` с причиной
    `not_bound` и без обращения к боту."""
    from apps.integrations import channel as shared

    settings.TELEGRAM_BOT_TOKEN = "t-" + secrets.token_hex(8)
    settings.MAX_BOT_TOKEN = "t-" + secrets.token_hex(8)
    model("notify.NotifySettings").objects.update_or_create(pk=1, defaults={"telegram_enabled": True, "max_enabled": True})
    for channel in ("telegram", "max"):
        user = support.make_employee()
        gone = _delivery(channel, user=user)
        with notify.fake_bot_send(channel, raises=shared.ChannelGone) as bot:
            assert _send(gone) == "failed"
        assert len(bot.calls) == 1
        gone = _fresh(gone)
        assert (gone.state, gone.reason, gone.attempts, gone.lease_until) == ("failed", "channel_unbound", 1, None)
        assert not _bound(user, channel)

        free = _delivery(channel, bind=False)
        with notify.fake_bot_send(channel) as bot:
            assert _send(free) == "skipped"
        assert bot.calls == []
        free = _fresh(free)
        assert (free.state, free.reason) == ("skipped", "not_bound")


# --- 17-18. ответ 401: токен не принят -------------------------------------------------------------------------

def test_401_keeps_binding_and_retries_by_schedule(bots_on, clock):
    """FR-332 (план, «BadToken»): ответ 401 — привязка остаётся, доставка `waiting` повторяется по расписанию
    (1 минута, 5 минут), после исправления токена уходит; в `log` код 401 и причина `bad_token`."""
    clock.set(MOMENT)
    user = support.make_employee()
    row = _delivery("telegram", user=user)
    chat = _chat_of(user, "telegram")

    bots_on.fail("telegram", 401, method="sendMessage")
    assert _send(row) == "waiting"
    row = _fresh(row)
    assert (row.state, row.attempts, row.reason) == ("waiting", 1, "")
    assert row.due_at == MOMENT + datetime.timedelta(seconds=60) and row.enqueued_at is None
    assert row.lease_until is None and _chat_of(user, "telegram") == chat
    assert (row.log[-1]["outcome"], row.log[-1]["code"], row.log[-1]["reason"]) == ("retry", 401, "bad_token")
    assert bots_on.sent("telegram") == []

    clock.advance(seconds=61)
    bots_on.fail("telegram", 401, method="sendMessage")
    assert _send(row) == "waiting"
    row = _fresh(row)
    assert row.attempts == 2 and row.due_at == MOMENT + datetime.timedelta(seconds=61 + 300)
    assert len(row.log) == 2 and _chat_of(user, "telegram") == chat

    clock.advance(seconds=301)
    assert _send(row) == "sent"
    row = _fresh(row)
    assert (row.state, row.attempts, len(row.log)) == ("sent", 3, 3)
    assert [m["text"] for m in bots_on.sent("telegram")] == [KIND_TEXT] and _bound(user, "telegram")


def test_401_writes_token_not_accepted_with_time_to_channel_status(bots_on, clock):
    """FR-332 (14.4): 401 пишет в `channel_status` канала `{at, code: bad_token}`; страница администратора показывает
    `[data-channel-error]` с `data-code="bad_token"` и временем только у этого канала; удачная отправка запись
    очищает."""
    clock.set(MOMENT)
    row = _delivery("telegram")
    bots_on.fail("telegram", 401, method="sendMessage")
    assert _send(row) == "waiting"

    status = _status("telegram")
    assert status is not None and set(status) == {"at", "code"} and status["code"] == "bad_token"
    stored = model("notify.NotifySettings").objects.get(pk=1).channel_status
    assert stored["telegram"] == status and "max" not in stored
    moment = datetime.datetime.fromisoformat(status["at"])
    assert moment.tzinfo is not None and moment == MOMENT
    assert _status("max") is None

    admin = support.make_with_permissions("notify.manage")
    client = support.logged_in(admin)
    response = client.get("/settings/notifications/")
    assert response.status_code == 200
    page = response.content.decode("utf-8")
    nodes = _channel_error_nodes(page, "telegram")
    assert len(nodes) == 1 and nodes[0].attrs.get("data-code") == "bad_token"
    stamps = _time_nodes(nodes[0])
    assert len(stamps) == 1 and stamps[0].attrs["data-at"]
    assert _channel_error_nodes(page, "max") == []

    clock.advance(seconds=61)
    assert _send(row) == "sent"
    assert _status("telegram") is None
    assert _channel_error_nodes(client.get("/settings/notifications/").content.decode("utf-8"), "telegram") == []


# --- 19-21. 429, сбои сети, 400 ------------------------------------------------------------------------------

def test_429_with_retry_after_gives_retry_later(bots_on, clock):
    """FR-333 (5.1, 6.9): 429 Telegram (`parameters.retry_after`) и MAX (заголовок `Retry-After`) — `RetryLater` с
    `after`; доставка `waiting`, срок не раньше `retry_after` (120 с больше шага расписания 60 с), канал помечен
    `rate_limited`."""
    from apps.integrations import channel as shared

    clock.set(MOMENT)
    for channel in ("telegram", "max"):
        client = _client(channel)
        bots_on.fail(channel, 429, method=SEND_METHOD[channel], retry_after=120)
        exc = _raised(lambda: client.send_message(_chat_id(), "Проверка"))
        assert isinstance(exc, shared.RetryLater)
        assert (exc.code, exc.after, str(exc)) == (429, 120, f"{ERROR_TEXT[channel]} 429")

        row = _delivery(channel)
        bots_on.fail(channel, 429, method=SEND_METHOD[channel], retry_after=120)
        assert _send(row) == "waiting"
        row = _fresh(row)
        assert (row.state, row.attempts, row.enqueued_at) == ("waiting", 1, None)
        assert row.due_at >= MOMENT + datetime.timedelta(seconds=120)
        assert (row.log[-1]["code"], row.log[-1]["reason"]) == (429, "rate_limited")
        assert _status(channel)["code"] == "rate_limited"
        assert bots_on.sent(channel) == []


def test_5xx_network_and_timeout_give_retry_later(bots_on, clock, monkeypatch):
    """FR-333 (5.1, 6.9): 5xx, сеть и таймаут — `RetryLater` (у сети и таймаута `code` пуст, `reason` — `network` или
    `timeout`; у 409 Telegram `code == 409`); доставка `waiting` со сроком через минуту, канал помечен
    `unavailable`, в `log` код и причина попытки."""
    from apps.integrations import channel as shared

    clock.set(MOMENT)
    expected_log = {500: (500, "server_error"), "network": (None, "network"), "timeout": (None, "timeout")}
    for channel in ("telegram", "max"):
        for how in (500, "network", "timeout"):
            exc = _provoke(channel, how, bots_on, monkeypatch)
            assert isinstance(exc, shared.RetryLater)
            if how == 500:
                assert (exc.code, exc.reason) == (500, "")
            else:
                assert (exc.code, exc.reason) == (None, how)
            assert str(exc) == f"{ERROR_TEXT[channel]} {how}"

            row = _delivery(channel)
            with _failing(channel, how, bots_on, monkeypatch):
                assert _send(row) == "waiting"
            row = _fresh(row)
            assert (row.state, row.attempts) == ("waiting", 1)
            assert row.due_at == MOMENT + datetime.timedelta(seconds=60) and row.enqueued_at is None
            assert (row.log[-1]["code"], row.log[-1]["reason"]) == expected_log[how]
            assert _status(channel)["code"] == "unavailable"
    bots_on.fail("telegram", 409, method="sendMessage")
    conflict = _raised(lambda: _client("telegram").send_message(_chat_id(), "Проверка"))
    assert isinstance(conflict, shared.RetryLater) and conflict.code == 409


def test_400_gives_bad_request_and_delivery_fails_without_retry(bots_on, clock, monkeypatch):
    """FR-332 (5.1, 6.9): ответ 400 — `BadRequest`; доставка `failed` с причиной `bad_request` без повторов
    (второй вызов — «noop», в бот больше не ходит); привязка остаётся."""
    from apps.integrations import channel as shared

    clock.set(MOMENT)
    for channel in ("telegram", "max"):
        exc = _provoke(channel, 400, bots_on, monkeypatch)
        assert isinstance(exc, shared.BadRequest) and (exc.code, str(exc)) == (400, f"{ERROR_TEXT[channel]} 400")

        user = support.make_employee()
        row = _delivery(channel, user=user)
        client = _client(channel)
        answer = shared.Response(400, {"content-type": "application/json"}, _body_400(channel))
        with notify.bots_capture(client, passthrough=False, responses=answer) as capture:
            assert _send(row) == "failed"
            assert len(capture.requests) == 1
            assert _send(row) == "noop"
            assert len(capture.requests) == 1
        row = _fresh(row)
        assert (row.state, row.reason, row.attempts, row.lease_until) == ("failed", "bad_request", 1, None)
        assert (row.log[-1]["code"], row.log[-1]["outcome"]) == (400, "failed")
        assert _bound(user, channel) and bots_on.sent(channel) == []


# --- 22-26. токены и тексты ошибок (NFR-312) ------------------------------------------------------------------

def test_adapter_exception_text_has_method_and_code_without_request_url(bots_on, monkeypatch, settings):
    """NFR-312 (5.1): текст ошибки адаптера — метод и код ответа («sendMessage 403», «POST /messages 403»), у сети и
    таймаута — метод и причина; адреса запроса нет; тип исключения — по коду ответа; пустой токен — `BadToken` без
    обращения к сети."""
    from apps.integrations import channel as shared

    forbidden = ("http", "fakebots", "/bot", "8099")
    for channel in ("telegram", "max"):
        hows = [400, 401, 403, 429, 500, "network", "timeout"] + ([409] if channel == "telegram" else [])
        for how in hows:
            exc = _provoke(channel, how, bots_on, monkeypatch)
            assert isinstance(exc, _expected_type(channel, how)), f"{channel} {how}: {type(exc).__name__}"
            assert isinstance(exc, shared.ChannelError) and exc.method == ERROR_TEXT[channel]
            assert str(exc) == f"{ERROR_TEXT[channel]} {how}"
            leaked = [w for w in forbidden if w in str(exc)]
            assert not leaked, f"{channel} {how}: в тексте ошибки адрес запроса"
        bots_on.fail(channel, 401, method="me" if channel == "max" else "getMe")
        info = _raised(lambda: _client(channel).get_me())
        assert isinstance(info, shared.BadToken) and str(info) == ("GET /me 401" if channel == "max" else "getMe 401")

        setting_name = "TELEGRAM_BOT_TOKEN" if channel == "telegram" else "MAX_BOT_TOKEN"
        setattr(settings, setting_name, "")
        with notify.bots_capture(_client(channel)) as capture:
            empty = _raised(lambda: _client(channel).send_message(_chat_id(), "Проверка"))
        assert capture.requests == []
        assert isinstance(empty, shared.BadToken) and (empty.code, str(empty)) == (401, f"{ERROR_TEXT[channel]} 401")


def test_token_not_in_adapter_exceptions(bots_on, monkeypatch):
    """NFR-312: токен бота нет ни в тексте, ни в `repr`, ни в аргументах и полях исключений адаптера — при ответах
    400, 401, 403, 409, 429, 5xx и при сбоях сети и таймауте, даже если подменная функция сети кладёт адрес запроса
    и заголовки в собственное исключение (токены задаёт `bots_on`)."""
    values = _values()
    assert all(values.values())
    for channel in ("telegram", "max"):
        hows = [400, 401, 403, 429, 500, "network", "timeout"] + ([409] if channel == "telegram" else [])
        for how in hows:
            exc = _provoke(channel, how, bots_on, monkeypatch)
            shown = [str(exc), repr(exc), repr(exc.args), repr(vars(exc))]
            for name, value in values.items():
                leaked = any(value in part for part in shown)
                assert not leaked, f"{channel} {how}: токен канала {name} виден в исключении"


def test_token_not_in_application_log_on_errors(bots_on, clock, monkeypatch, caplog):
    """NFR-312: при каждом виде сбоя отправки (400, 401, 403, 429, 5xx, сеть, таймаут) в журнале приложения нет
    токенов ботов; предупреждения адаптеров и служб пишутся без них."""
    clock.set(MOMENT)
    values = _values()
    caplog.set_level(logging.DEBUG)
    for channel in ("telegram", "max"):
        for how in (400, 401, 403, 429, 500, "network", "timeout"):
            row = _delivery(channel)
            with _failing(channel, how, bots_on, monkeypatch):
                result = _send(row)
            assert result in ("waiting", "failed"), f"{channel} {how}: {result}"
    ok = _delivery("telegram")
    assert _send(ok) == "sent"
    for name, value in values.items():
        leaked = value in caplog.text
        assert not leaked, f"токен канала {name} попал в журнал приложения"


def test_token_not_in_delivery_log(bots_on, clock, monkeypatch):
    """NFR-312 (2.2): запись `Delivery.log` — только `at`, `outcome`, `code`, `reason`; в ней нет токена, адреса
    запроса и номера чата; время — ISO-8601 с поясом; запись есть у каждой попытки, в том числе удачной."""
    clock.set(MOMENT)
    values = _values()
    rows = []
    for channel in ("telegram", "max"):
        for how in (400, 401, 403, 429, 500, "network", "timeout", None):
            row = _delivery(channel)
            chat = _chat_of(row.notification.user, channel)
            if how is None:
                assert _send(row) == "sent"
            else:
                with _failing(channel, how, bots_on, monkeypatch):
                    _send(row)
            rows.append((channel, how, chat, _fresh(row)))
    for channel, how, chat, row in rows:
        assert len(row.log) == 1, f"{channel} {how}: записей в log {len(row.log)}"
        record = row.log[0]
        assert set(record) <= LOG_FIELDS and {"at", "outcome", "code", "reason"} <= set(record)
        assert datetime.datetime.fromisoformat(record["at"]).tzinfo is not None
        dumped = json.dumps(row.log, ensure_ascii=False)
        assert chat not in dumped and "http" not in dumped and "/bot" not in dumped
        for name, value in values.items():
            leaked = value in dumped
            assert not leaked, f"{channel} {how}: токен канала {name} попал в Delivery.log"


def test_telegram_url_has_base_bot_token_and_method_and_max_token_goes_in_header(bots_on):
    """NFR-312, FR-325 (5.2): Telegram — `TELEGRAM_API_BASE/bot<токен>/<метод>`, токен только в пути; MAX —
    `MAX_API_BASE/<путь>`, токен только в заголовке `Authorization` (без слова Bearer), в адресе и теле его нет."""
    values = _values()
    tg_base = django_settings.TELEGRAM_API_BASE.rstrip("/")
    mx_base = django_settings.MAX_API_BASE.rstrip("/")
    tg, mx = _client("telegram"), _client("max")

    with notify.bots_capture(tg) as capture:
        tg.get_me()
        tg.send_message(_chat_id(), "Проверка")
    me, send = capture.requests
    assert (me.method, send.method) == ("GET", "POST")
    expected_me = f"{tg_base}/bot{values['telegram']}/getMe"
    expected_send = f"{tg_base}/bot{values['telegram']}/sendMessage"
    same_me = me.url == expected_me
    assert same_me, "адрес getMe: база, /bot<токен>/, метод"
    same_send = send.url == expected_send
    assert same_send, "адрес sendMessage: база, /bot<токен>/, метод"
    in_header = any(values["telegram"] in str(v) for v in send.headers.values())
    in_body = values["telegram"] in (send.body or b"").decode("utf-8")
    assert not in_header and not in_body, "токен Telegram вне пути запроса"

    with notify.bots_capture(mx) as capture:
        mx.get_me()
        mx.send_message(_chat_id(), "Проверка")
    me, send = capture.requests
    assert (me.method, send.method) == ("GET", "POST")
    assert me.url.split("?")[0] == mx_base + "/me" and send.url.split("?")[0] == mx_base + "/messages"
    for request in (me, send):
        same_header = request.headers.get("authorization") == values["max"]
        assert same_header, "заголовок Authorization: значение токена без слова Bearer"
        in_url = values["max"] in request.url
        in_body = values["max"] in (request.body or b"").decode("utf-8")
        assert not in_url and not in_body, "токен MAX виден вне заголовка"
    assert send.params["chat_id"]
