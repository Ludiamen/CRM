"""T-4118: привязка Telegram и MAX одноразовым кодом (FR-325, FR-339). Сценарии 6 и 7 спеки среза 004.

Код выдаёт `binding.new_code` (открытый код существует только в его возврате и в ответе
`POST /me/notifications/bind/<канал>/`, CONTRACT-004 § 6.13, § 13.2); события бота разбирает
`bots.handle_update(channel, update)` (§ 6.14, формы событий — § 1.2). Ответ бота уходит после фиксации,
поэтому каждое событие идёт внутри `django_capture_on_commit_callbacks(execute=True)`; ответы читаются у учебной
службы `fakebots` (`FakeBots.sent`, фикстура `bots_on`, § 1.1, решения 4 и 23 задач, дополнение 3 раздела 17).
Обход между двумя событиями тест не зовёт, кроме явно названных (решения B4, E1). Имена кода среза 004 —
внутри тестов, модели — через `support.model` (шапка контракта).
"""
import hashlib
import json
import re
import secrets
from datetime import timedelta
from html.parser import HTMLParser
from urllib.parse import urlsplit

import pytest
from django.utils import timezone

from tests import support
from tests import support_notify as notify
from tests.support import HX, model

pytestmark = pytest.mark.django_db

CHANNELS = ("telegram", "max")
PAGE_URL = "/me/notifications/"
BOT_NAME = "stand_notify_bot"

# дословные тексты § 15.3
ASK_CODE = "Отправьте код из раздела «Мои уведомления» портала"
BOUND_TEXT = {"telegram": "Telegram привязан к вашей учётной записи портала",
              "max": "MAX привязан к вашей учётной записи портала"}
CODE_INVALID = "Код недействителен или просрочен. Получите новый код в портале"
CHAT_TAKEN = "Этот чат уже привязан к другой учётной записи портала"
TOO_MANY = "Слишком много попыток, попробуйте позже"
DISABLED_TEXT = "Канал отключён администратором"
LINK_HINT = "Ссылка появится, когда бот подключится"
BOT_LINK_BASE = {"telegram": "https://t.me/", "max": "https://max.ru/"}

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- разбор разметки (помощник только этого файла) ---------------------------------------------------------

class _Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}
        self.parent = parent
        self.children = []

    def walk(self):
        for child in self.children:
            if isinstance(child, _Node):
                yield child
                yield from child.walk()

    def text(self) -> str:
        parts = [c if isinstance(c, str) else c.text() for c in self.children]
        return " ".join("".join(parts).split())


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

    def handle_data(self, data):
        self.cur.children.append(data)


def _tree(response_or_html) -> _Node:
    html = response_or_html if isinstance(response_or_html, str) else response_or_html.content.decode("utf-8")
    parser = _Tree()
    parser.feed(html)
    return parser.root


def _find(root, tag=None, **attrs) -> list:
    """Элементы с тегом `tag` и атрибутами (`data_state="bound"` -> `data-state`); значение `True` — «атрибут есть»."""
    found = []
    for node in root.walk():
        if tag is not None and node.tag != tag:
            continue
        ok = True
        for name, expected in attrs.items():
            name = name.replace("_", "-")
            if name not in node.attrs or (expected is not True and node.attrs[name] != expected):
                ok = False
                break
        if ok:
            found.append(node)
    return found


def _block(response_or_html, channel) -> _Node:
    """Корень блока привязки `#notify-binding-<канал>` (§ 14.3)."""
    found = _find(_tree(response_or_html), id=f"notify-binding-{channel}")
    assert len(found) == 1, f"блок #notify-binding-{channel}: найдено {len(found)}"
    return found[0]


def _links(root) -> list[str]:
    """Все адреса в разметке: href, action, hx-get, hx-post, data-url, src."""
    out = []
    for node in root.walk():
        for name in ("href", "action", "hx-get", "hx-post", "data-url", "src"):
            if node.attrs.get(name):
                out.append(node.attrs[name])
    return out


# --- события ботов и помощники только этого файла ------------------------------------------------------------

def _chat() -> int:
    return 10 ** 9 + secrets.randbelow(10 ** 9)


def _text_update(channel: str, chat: int, text: str, *, kind: str | None = None) -> dict:
    """Текст из чата: Telegram — `message` (`kind`: private/group/supergroup/channel), MAX — `message_created`
    (`kind`: dialog/chat/channel); формы — § 1.2."""
    if channel == "telegram":
        return {"message": {"chat": {"id": chat, "type": kind or "private"}, "from": {"id": chat}, "text": text}}
    return {"update_type": "message_created",
            "message": {"sender": {"user_id": chat},
                        "recipient": {"chat_id": chat, "chat_type": kind or "dialog"},
                        "body": {"text": text}}}


def _start_update(channel: str, chat: int) -> dict:
    if channel == "telegram":
        return _text_update("telegram", chat, "/start")
    return {"update_type": "bot_started", "chat_id": chat, "user": {"user_id": chat}}


def _handle(callbacks, channel: str, update: dict) -> str:
    """Одно событие бота; ответ бота уходит при выходе из блока (после фиксации)."""
    from apps.notify.services import bots

    with callbacks(execute=True):
        return bots.handle_update(channel, update)


def _dialog(callbacks, channel: str, chat: int) -> None:
    result = _handle(callbacks, channel, _start_update(channel, chat))
    assert result == "dialog_started", f"{channel}: начало диалога дало {result!r}"


def _say(callbacks, channel: str, chat: int, text: str, **kind) -> str:
    return _handle(callbacks, channel, _text_update(channel, chat, text, **kind))


def _issue(user, channel: str):
    from apps.notify.services import binding

    return binding.new_code(user, channel)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _code_rows(user=None, channel=None):
    qs = model("notify.BindCode").objects.all()
    if user is not None:
        qs = qs.filter(user=user)
    if channel is not None:
        qs = qs.filter(channel=channel)
    return qs


def _row(code: str, channel: str):
    return model("notify.BindCode").objects.get(channel=channel, code_hash=_sha(code))


def _bindings(channel=None, **filters):
    qs = model("notify.ChatBinding").objects.filter(**filters)
    return qs.filter(channel=channel) if channel else qs


def _texts(bots, channel: str) -> list[str]:
    return [message["text"] for message in bots.sent(channel)]


def _audit(action: str, user=None) -> list:
    qs = model("core.AuditEvent").objects.filter(action=action)
    if user is not None:
        qs = qs.filter(object_id=str(user.pk))
    return list(qs.order_by("id"))


def _wrong() -> str:
    return "x" + secrets.token_hex(4)


def _set_bot_name(channel: str, name: str = BOT_NAME) -> None:
    model("notify.BotState").objects.update_or_create(channel=channel, defaults={"bot_username": name})


def _post_bind(client, channel: str, *, htmx: bool = True):
    return client.post(f"{PAGE_URL}bind/{channel}/", **(HX if htmx else {}))


def _credentials(settings) -> tuple:
    """Токены ботов этого теста: значения нигде не печатаются."""
    return (settings.TELEGRAM_BOT_TOKEN, settings.MAX_BOT_TOKEN)


def _leaks(text: str, *values: str) -> bool:
    """Есть ли среди значений непустое, входящее в текст (значения в сообщениях проверок не показываются)."""
    return any(value and value in text for value in values)


# --- выдача и хранение кода ----------------------------------------------------------------------------------

def test_bind_code_has_8_digits(bots_on, monkeypatch):
    """FR-325: код — ровно восемь цифр (`"%08d"`) в обоих каналах; малое число из `secrets.randbelow` дополняется нулями."""
    user = support.make_employee()
    for channel in CHANNELS:
        for _ in range(30):
            code = _issue(user, channel).code
            assert re.fullmatch(r"[0-9]{8}", code), f"{channel}: код не из восьми цифр (длина {len(code)})"
    monkeypatch.setattr(secrets, "randbelow", lambda limit: 42)
    padded = _issue(support.make_employee(), "telegram").code
    assert padded == "00000042", "число меньше 10**7 должно дополняться нулями слева до восьми цифр"


def test_bind_code_expires_in_10_minutes(bots_on, django_capture_on_commit_callbacks):
    """FR-325, FR-339: код действует 10 минут — срок в базе и в возврате совпадают; до срока код принимается, после — нет."""
    for channel in CHANNELS:
        user = support.make_employee()
        before = timezone.now()
        new = _issue(user, channel)
        after = timezone.now()
        assert before + timedelta(minutes=10) <= new.expires_at <= after + timedelta(minutes=10), \
            f"{channel}: срок кода не равен «сейчас + 10 минут»"
        row = _row(new.code, channel)
        assert row.expires_at == new.expires_at and row.used_at is None and row.user_id == user.pk
        # ещё действует за минуту до срока
        row.expires_at = timezone.now() + timedelta(minutes=1)
        row.save(update_fields=["expires_at"])
        chat = _chat()
        _dialog(django_capture_on_commit_callbacks, channel, chat)
        assert _say(django_capture_on_commit_callbacks, channel, chat, new.code) == "bound"
        # срок вышел — другой код другого сотрудника не принимается
        late_user = support.make_employee()
        late = _issue(late_user, channel)
        _code_rows(late_user, channel).update(expires_at=timezone.now() - timedelta(seconds=1))
        late_chat = _chat()
        _dialog(django_capture_on_commit_callbacks, channel, late_chat)
        assert _say(django_capture_on_commit_callbacks, channel, late_chat, late.code) == "code_invalid"
        assert not _bindings(channel, user=late_user).exists()


def test_bind_code_is_stored_only_as_sha256_hash(bots_on):
    """FR-325: в базе только SHA-256 кода (64 символа шестнадцатеричной записи в нижнем регистре), самого кода нет."""
    for channel in CHANNELS:
        user = support.make_employee()
        code = _issue(user, channel).code
        row = _code_rows(user, channel).get()
        assert row.code_hash == hashlib.sha256(code.encode("utf-8")).hexdigest()
        assert re.fullmatch(r"[0-9a-f]{64}", row.code_hash)
        for field in model("notify.BindCode")._meta.concrete_fields:
            if field.name == "code_hash":
                continue
            assert str(getattr(row, field.name)) != code, f"поле {field.name} хранит открытый код"


def test_tick_deletes_expired_codes_and_keeps_active_ones(bots_on):
    """FR-339: обход `notify_tick` удаляет использованные и просроченные коды (решение B4) и оставляет действующие."""
    used_user, old_user, live_user, max_old_user, max_live_user = (support.make_employee() for _ in range(5))
    used = _issue(used_user, "telegram").code
    old = _issue(old_user, "telegram").code
    live = _issue(live_user, "telegram").code
    max_old = _issue(max_old_user, "max").code
    max_live = _issue(max_live_user, "max").code
    _code_rows(used_user).update(used_at=timezone.now())
    _code_rows(old_user).update(expires_at=timezone.now() - timedelta(minutes=1))
    _code_rows(max_old_user).update(expires_at=timezone.now() - timedelta(seconds=1))
    tick = notify.run_tick()
    assert tick["codes"] == 3, f"удалено кодов: {tick['codes']}, ждали 3 (использованный и два просроченных)"
    model_code = model("notify.BindCode")
    for gone, channel in ((used, "telegram"), (old, "telegram"), (max_old, "max")):
        assert not model_code.objects.filter(channel=channel, code_hash=_sha(gone)).exists()
    for kept, channel in ((live, "telegram"), (max_live, "max")):
        assert model_code.objects.filter(channel=channel, code_hash=_sha(kept), used_at=None).exists()
    assert model_code.objects.count() == 2


def test_bind_code_differs_from_active_code_of_other_user_in_channel(bots_on, monkeypatch):
    """FR-325: код не совпадает с действующим кодом другого сотрудника в этом канале — при совпадении берётся другой."""
    first = support.make_employee()
    taken = _issue(first, "telegram").code
    calls = []
    real = secrets.randbelow
    sequence = [int(taken), (int(taken) + 1) % 10 ** 8]

    def fake(limit):
        calls.append(limit)
        return sequence.pop(0) if sequence else real(limit)

    monkeypatch.setattr(secrets, "randbelow", fake)
    second = support.make_employee()
    other = _issue(second, "telegram").code
    assert len(calls) >= 2, "совпавшее число не заменено новым обращением к secrets.randbelow"
    assert other != taken and re.fullmatch(r"[0-9]{8}", other)
    assert _code_rows(first, "telegram").get().code_hash == _sha(taken), "код первого сотрудника тронут"
    assert _code_rows(second, "telegram").get().code_hash == _sha(other)


def test_new_code_deletes_previous_unused_code_in_same_transaction(bots_on, django_capture_on_commit_callbacks):
    """FR-325: новый код заменяет прежний неиспользованный того же сотрудника в этом канале; чужие и другого канала целы."""
    user, other_user = support.make_employee(), support.make_employee()
    first = _issue(user, "telegram").code
    other_channel = _issue(user, "max").code
    foreign = _issue(other_user, "telegram").code
    second = _issue(user, "telegram").code
    rows = _code_rows(user, "telegram")
    assert rows.count() == 1 and rows.get().code_hash == _sha(second), "прежний код не удалён или остался второй"
    assert not rows.filter(code_hash=_sha(first)).exists()
    assert _code_rows(user, "max").get().code_hash == _sha(other_channel), "код другого канала удалён"
    assert _code_rows(other_user, "telegram").get().code_hash == _sha(foreign), "код другого сотрудника удалён"
    chat = _chat()
    _dialog(django_capture_on_commit_callbacks, "telegram", chat)
    assert _say(django_capture_on_commit_callbacks, "telegram", chat, first) == "code_invalid"
    assert _say(django_capture_on_commit_callbacks, "telegram", chat, second) == "bound"


# --- страница «Мои уведомления» ------------------------------------------------------------------------------

def test_bind_page_shows_code_and_bot_link_only_to_owner(bots_on):
    """FR-325: код и ссылка на бота — только в ответе «Привязать» самому сотруднику; повторный GET и чужие их не содержат."""
    for channel in CHANNELS:
        _set_bot_name(channel)
    owner, stranger = support.make_employee(), support.make_employee()
    own, foreign = support.logged_in(owner), support.logged_in(stranger)
    for channel in CHANNELS:
        response = _post_bind(own, channel)
        assert response.status_code == 200
        block = _block(response, channel)
        shown = _find(block, data_bind_code=True)
        assert len(shown) == 1
        code = shown[0].text()
        assert re.fullmatch(r"[0-9]{8}", code), "код на странице — не восемь цифр"
        assert _code_rows(owner, channel).get().code_hash == _sha(code), "показан не тот код, что в базе"
        expires = _find(block, data_bind_expires=True)
        assert len(expires) == 1 and "10 минут" in expires[0].text()
        links = _find(block, "a", data_bot_link=True)
        assert len(links) == 1 and links[0].attrs["href"] == BOT_LINK_BASE[channel] + BOT_NAME
        # повторный GET владельца и страница другого сотрудника кода не содержат
        assert code not in own.get(PAGE_URL).content.decode("utf-8"), "повторный GET показывает код"
        assert code not in foreign.get(PAGE_URL).content.decode("utf-8"), "код виден другому сотруднику"
        # обычный POST — полная страница с тем же блоком
        full = _post_bind(own, channel, htmx=False)
        assert full.status_code == 200
        again = _find(_block(full, channel), data_bind_code=True)
        assert len(again) == 1 and _code_rows(owner, channel).get().code_hash == _sha(again[0].text())
    # без входа кода нет
    anonymous = support.make_client().post(f"{PAGE_URL}bind/telegram/")
    assert anonymous.status_code == 302 and not _find(_tree(anonymous), data_bind_code=True)


def test_bot_link_has_no_code_or_secrets_in_url(bots_on, settings):
    """FR-325, FR-339: ссылка на бота — `https://t.me/<имя>` или `https://max.ru/<имя>`, без кода, запроса и секретов."""
    from apps.notify.services import bots

    for channel in CHANNELS:
        _set_bot_name(channel)
    user = support.make_employee()
    client = support.logged_in(user)
    for channel in CHANNELS:
        assert bots.bot_link(channel) == BOT_LINK_BASE[channel] + BOT_NAME
        response = _post_bind(client, channel)
        code = _find(_block(response, channel), data_bind_code=True)[0].text()
        href = _find(_block(response, channel), "a", data_bot_link=True)[0].attrs["href"]
        parts = urlsplit(href)
        assert (parts.scheme, parts.path) == ("https", "/" + BOT_NAME) and not parts.query and not parts.fragment
        assert parts.username is None and parts.port is None
        assert not _leaks(href, code, *_credentials(settings)), "в ссылке на бота есть код или токен"


def test_notification_links_have_no_code_or_secrets(bots_on, settings):
    """FR-325, FR-339: ни в адресах страницы и блока привязки, ни в ссылке уведомления нет кода и токенов."""
    for channel in CHANNELS:
        _set_bot_name(channel)
    user = support.make_employee()
    client = support.logged_in(user)
    note = model("notify.Notification").objects.create(user=user, kind="notify.channel_unbound", text="Канал отвязан",
                                                       url=PAGE_URL)
    for channel in CHANNELS:
        response = _post_bind(client, channel)
        code = _find(_block(response, channel), data_bind_code=True)[0].text()
        bind_links = _links(_tree(response))
        page_links = _links(_tree(client.get(PAGE_URL)))
        assert bind_links and page_links
        for href in bind_links + page_links:
            assert not _leaks(href, code, *_credentials(settings)), "в адресе есть одноразовый код или токен"
        opened = client.get(f"/notifications/{note.pk}/open/")
        assert opened.status_code == 302 and opened["Location"] == PAGE_URL
        assert not _leaks(opened["Location"], code, *_credentials(settings))
    assert not _leaks(note.url, *_credentials(settings))


def test_bot_link_replaced_by_hint_when_bot_name_unknown(bots_on):
    """FR-325: имени бота ещё нет — `bot_link` пуст, в ответе «Привязать» вместо ссылки подсказка, код показан."""
    from apps.notify.services import bots

    user = support.make_employee()
    client = support.logged_in(user)
    for channel in CHANNELS:
        assert bots.bot_link(channel) is None
        response = _post_bind(client, channel)
        assert response.status_code == 200
        block = _block(response, channel)
        assert not _find(block, "a", data_bot_link=True), "ссылка показана без имени бота"
        hint = _find(block, data_bot_link_hint=True)
        assert len(hint) == 1 and hint[0].text() == LINK_HINT
        assert len(_find(block, data_bind_code=True)) == 1, "кода нет рядом с подсказкой"
    # пустое имя — то же, что отсутствие
    _set_bot_name("telegram", "")
    assert bots.bot_link("telegram") is None


def test_bind_button_absent_and_disabled_text_shown_when_channel_off_or_token_missing(bots_on, settings):
    """FR-325: канал выключен или токен не задан — кнопки «Привязать» нет, «Канал отключён администратором», код не выдан."""
    from apps.notify.services import binding
    from apps.notify.services import NotifyError

    user = support.make_employee()
    client = support.logged_in(user)
    for channel in CHANNELS:
        for how in ("switch", "token"):
            attr = f"{channel.upper()}_BOT_TOKEN"
            saved = getattr(settings, attr)
            if how == "switch":
                model("notify.NotifySettings").objects.filter(pk=1).update(**{f"{channel}_enabled": False})
            else:
                setattr(settings, attr, "")
            try:
                page = client.get(PAGE_URL)
                block = _block(page, channel)
                assert block.attrs.get("data-state") == "disabled", f"{channel}/{how}: блок не в состоянии disabled"
                texts = _find(block, data_disabled_text=True)
                assert len(texts) == 1 and texts[0].text() == DISABLED_TEXT
                assert not _find(block, "button", data_action="bind"), f"{channel}/{how}: кнопка «Привязать» есть"
                other = "max" if channel == "telegram" else "telegram"
                other_block = _block(page, other)
                assert other_block.attrs.get("data-state") == "unbound"
                assert _find(other_block, "button", data_action="bind"), f"{other}: кнопки «Привязать» нет"
                response = _post_bind(client, channel)
                assert response.status_code == 200
                blocked = _block(response, channel)
                assert blocked.attrs.get("data-state") == "disabled"
                errors = _find(blocked, data_error="channel")
                assert len(errors) == 1 and errors[0].attrs.get("data-code") == "channel_disabled"
                assert not _find(blocked, data_bind_code=True), "код выдан выключенному каналу"
                with pytest.raises(NotifyError) as refused:
                    binding.new_code(user, channel)
                assert refused.value.code == "channel_disabled" and refused.value.field == "channel"
                assert not _code_rows(user, channel).exists(), "код создан в выключенном канале"
            finally:
                if how == "switch":
                    model("notify.NotifySettings").objects.filter(pk=1).update(**{f"{channel}_enabled": True})
                else:
                    setattr(settings, attr, saved)


# --- события бота ----------------------------------------------------------------------------------------------

def test_telegram_start_marks_dialog_started_and_bot_asks_for_code(bots_on, django_capture_on_commit_callbacks):
    """FR-325: `/start` в личном чате Telegram создаёт `BotChat`, бот просит код (результат `dialog_started`)."""
    cb = django_capture_on_commit_callbacks
    chat = _chat()
    assert not model("notify.BotChat").objects.filter(channel="telegram", chat_id=str(chat)).exists()
    assert _handle(cb, "telegram", _start_update("telegram", chat)) == "dialog_started"
    row = model("notify.BotChat").objects.get(channel="telegram", chat_id=str(chat))
    assert row.bad_attempts == 0 and row.started_at is not None
    sent = bots_on.sent("telegram")
    assert [m["text"] for m in sent] == [ASK_CODE] and str(sent[0]["chat_id"]) == str(chat)
    # `/start` с параметром — тоже начало диалога; повтор не создаёт второй строки
    second = _chat()
    assert _handle(cb, "telegram", _text_update("telegram", second, "/start abc")) == "dialog_started"
    assert model("notify.BotChat").objects.filter(channel="telegram", chat_id=str(second)).count() == 1
    assert _handle(cb, "telegram", _start_update("telegram", chat)) == "dialog_started"
    assert model("notify.BotChat").objects.filter(channel="telegram", chat_id=str(chat)).count() == 1
    assert not model("notify.BotChat").objects.filter(channel="max").exists()


def test_max_bot_started_marks_dialog_started_and_bot_asks_for_code(bots_on, django_capture_on_commit_callbacks):
    """FR-325, FR-339: `bot_started` в MAX создаёт `BotChat`, бот просит код (результат `dialog_started`)."""
    cb = django_capture_on_commit_callbacks
    chat = _chat()
    assert _handle(cb, "max", _start_update("max", chat)) == "dialog_started"
    row = model("notify.BotChat").objects.get(channel="max", chat_id=str(chat))
    assert row.bad_attempts == 0 and row.started_at is not None
    sent = bots_on.sent("max")
    assert [m["text"] for m in sent] == [ASK_CODE] and str(sent[0]["chat_id"]) == str(chat)
    assert _handle(cb, "max", _start_update("max", chat)) == "dialog_started"
    assert model("notify.BotChat").objects.filter(channel="max", chat_id=str(chat)).count() == 1
    assert not model("notify.BotChat").objects.filter(channel="telegram").exists()


def test_code_from_chat_without_started_dialog_is_not_accepted(bots_on, django_capture_on_commit_callbacks):
    """FR-325: код из личного чата без начатого диалога не принимается: ответ `ask_code`, строки и привязки нет (решение A2)."""
    cb = django_capture_on_commit_callbacks
    for channel in CHANNELS:
        user = support.make_employee()
        code = _issue(user, channel).code
        chat = _chat()
        assert _say(cb, channel, chat, code) == "ask_code"
        assert bots_on.sent(channel) and _texts(bots_on, channel) == [ASK_CODE]
        assert not model("notify.BotChat").objects.filter(channel=channel, chat_id=str(chat)).exists()
        assert not _bindings(channel, user=user).exists()
        assert _row(code, channel).used_at is None, "код потрачен чатом без начатого диалога"
        # после начала диалога тот же код действует
        _dialog(cb, channel, chat)
        assert _say(cb, channel, chat, code) == "bound"


def test_code_from_group_chat_is_ignored_without_reply(bots_on, django_capture_on_commit_callbacks):
    """FR-325: сообщения из групп и каналов игнорируются без ответа, без строки и без привязки — код к группе не привязать."""
    cb = django_capture_on_commit_callbacks
    user_tg, user_max = support.make_employee(), support.make_employee()
    code_tg, code_max = _issue(user_tg, "telegram").code, _issue(user_max, "max").code
    for kind in ("group", "supergroup", "channel"):
        chat = -_chat()
        assert _say(cb, "telegram", chat, "/start", kind=kind) == "ignored"
        assert _say(cb, "telegram", chat, code_tg, kind=kind) == "ignored"
    for kind in ("chat", "channel"):
        chat = _chat()
        assert _say(cb, "max", chat, code_max, kind=kind) == "ignored"
    assert bots_on.sent("telegram") == [] and bots_on.sent("max") == [], "бот ответил в групповой чат"
    assert not model("notify.BotChat").objects.exists()
    assert not _bindings().exists()
    assert _row(code_tg, "telegram").used_at is None and _row(code_max, "max").used_at is None


def test_valid_telegram_code_binds_chat_marks_code_used_and_bot_confirms(bots_on, django_capture_on_commit_callbacks):
    """FR-325: верный код из начатого чата Telegram — привязка, `used_at`, подтверждение бота и журнал без `chat_id`."""
    cb = django_capture_on_commit_callbacks
    user = support.make_employee()
    code = _issue(user, "telegram").code
    chat = _chat()
    _dialog(cb, "telegram", chat)
    assert _say(cb, "telegram", chat, f"  {code}\n") == "bound"
    link = _bindings("telegram", user=user).get()
    assert link.chat_id == str(chat)
    assert _row(code, "telegram").used_at is not None
    assert _texts(bots_on, "telegram") == [ASK_CODE, BOUND_TEXT["telegram"]]
    assert str(bots_on.sent("telegram")[-1]["chat_id"]) == str(chat)
    events = _audit("notify.channel_bound", user)
    assert len(events) == 1 and events[0].after == {"channel": "telegram", "bound": True}
    assert str(chat) not in json.dumps([events[0].before, events[0].after])
    assert not _bindings("max").exists()


def test_valid_max_code_binds_chat_marks_code_used_and_bot_confirms(bots_on, django_capture_on_commit_callbacks):
    """FR-325: верный код из начатого диалога MAX — привязка, `used_at` и подтверждение «MAX привязан …»."""
    cb = django_capture_on_commit_callbacks
    user = support.make_employee()
    code = _issue(user, "max").code
    chat = _chat()
    _dialog(cb, "max", chat)
    assert _say(cb, "max", chat, code) == "bound"
    assert _bindings("max", user=user).get().chat_id == str(chat)
    assert _row(code, "max").used_at is not None
    assert _texts(bots_on, "max") == [ASK_CODE, BOUND_TEXT["max"]]
    assert str(bots_on.sent("max")[-1]["chat_id"]) == str(chat)
    assert not _bindings("telegram").exists() and bots_on.sent("telegram") == []


def test_binding_block_is_pushed_to_user_group_after_bind(bots_on, django_capture_on_commit_callbacks):
    """FR-325: после привязки в группу сотрудника уходит блок `#notify-binding-telegram` в состоянии «Привязан»."""
    cb = django_capture_on_commit_callbacks
    from apps.notify.services import bots

    user, stranger = support.make_employee(), support.make_employee()
    code = _issue(user, "telegram").code
    chat = _chat()
    owner_client, stranger_client = support.logged_in(user), support.logged_in(stranger)

    def do_bind():
        with cb(execute=True):
            assert bots.handle_update("telegram", _start_update("telegram", chat)) == "dialog_started"
            assert bots.handle_update("telegram", _text_update("telegram", chat, code)) == "bound"

    async def scenario(hub):
        owner = await hub.connect(owner_client)
        assert owner.accepted and await owner.receive() is not None, "нет начального кадра"
        other = await hub.connect(stranger_client)
        assert other.accepted and await other.receive() is not None
        await hub.do(do_bind)
        frames = []
        for _ in range(3):
            frame = await owner.receive(5.0)
            if frame is None:
                break
            frames.append(frame)
            if "notify-binding-telegram" in frame:
                break
        return frames, await other.receive(1.0)

    frames, foreign_frame = notify.ws_run(scenario)
    carriers = [frame for frame in frames if "notify-binding-telegram" in frame]
    assert carriers, "блок привязки в кадре не пришёл"
    fragment = notify.ws_fragments(carriers[0])["notify-binding-telegram"]
    assert fragment.tag == "div" and fragment.attrs.get("hx-swap-oob") == "true"
    assert fragment.attrs.get("data-state") == "bound" and fragment.attrs.get("data-channel") == "telegram"
    block = _block(carriers[0], "telegram")
    assert _find(block, data_bound=True) and re.search(r"\bПривязан\b", _find(block, data_bound=True)[0].text())
    assert _find(block, "button", data_action="unbind") and not _find(block, "button", data_action="bind")
    assert foreign_frame is None or "notify-binding-telegram" not in foreign_frame, "блок ушёл чужому сотруднику"
    assert "notify-binding-max" not in carriers[0]


def test_expired_code_is_rejected_with_hint_and_no_binding(bots_on, django_capture_on_commit_callbacks):
    """FR-325, FR-339: просроченный код — `code_invalid` с подсказкой получить новый, привязки нет, неверная попытка засчитана."""
    cb = django_capture_on_commit_callbacks
    for channel in CHANNELS:
        user = support.make_employee()
        code = _issue(user, channel).code
        _code_rows(user, channel).update(expires_at=timezone.now() - timedelta(minutes=1))
        chat = _chat()
        _dialog(cb, channel, chat)
        assert _say(cb, channel, chat, code) == "code_invalid"
        assert _texts(bots_on, channel) == [ASK_CODE, CODE_INVALID]
        assert not _bindings(channel, user=user).exists()
        assert model("notify.BotChat").objects.get(channel=channel, chat_id=str(chat)).bad_attempts == 1


def test_used_code_is_rejected_with_hint_and_no_binding(bots_on, django_capture_on_commit_callbacks):
    """FR-325, FR-339: использованный код из другого чата — `code_invalid`; и после обхода тот же текст отвергается (решение E1)."""
    cb = django_capture_on_commit_callbacks
    for channel in CHANNELS:
        user = support.make_employee()
        code = _issue(user, channel).code
        first, second = _chat(), _chat()
        _dialog(cb, channel, first)
        _dialog(cb, channel, second)
        assert _say(cb, channel, first, code) == "bound"
        assert _say(cb, channel, second, code) == "code_invalid", "использованный код принят из другого чата"
        assert _texts(bots_on, channel)[-1] == CODE_INVALID
        assert _bindings(channel, user=user).get().chat_id == str(first)
        assert not _bindings(channel, chat_id=str(second)).exists()
        assert model("notify.BotChat").objects.get(channel=channel, chat_id=str(second)).bad_attempts == 1
        # после обхода использованного кода нет, тот же текст из привязанного чата — неверный код
        notify.run_tick()
        assert not _code_rows(user, channel).exists()
        assert _say(cb, channel, first, code) == "code_invalid"
        assert _bindings(channel, user=user).get().chat_id == str(first)


def test_text_not_matching_any_code_gets_refusal_with_hint(bots_on, django_capture_on_commit_callbacks):
    """FR-325: текст, не совпавший с действующим кодом, — отказ с подсказкой; код другого канала тоже не подходит."""
    cb = django_capture_on_commit_callbacks
    user = support.make_employee()
    telegram_code = _issue(user, "telegram").code
    chat = _chat()
    _dialog(cb, "max", chat)
    for text in (_wrong(), "12345670", telegram_code):
        assert _say(cb, "max", chat, text) == "code_invalid", "текст принят как код"
    assert _texts(bots_on, "max") == [ASK_CODE] + [CODE_INVALID] * 3
    assert not _bindings().exists()
    assert _row(telegram_code, "telegram").used_at is None
    assert model("notify.BotChat").objects.get(channel="max", chat_id=str(chat)).bad_attempts == 3
    chat_tg = _chat()
    _dialog(cb, "telegram", chat_tg)
    assert _say(cb, "telegram", chat_tg, _wrong()) == "code_invalid"
    assert _texts(bots_on, "telegram") == [ASK_CODE, CODE_INVALID]


def test_chat_bound_to_other_account_is_rejected_with_explanation(bots_on, django_capture_on_commit_callbacks):
    """FR-325: чат, привязанный к другой учётной записи, — `chat_taken` с объяснением; код и счётчик попыток не тронуты (B3)."""
    from apps.notify.services import NotifyError, binding

    cb = django_capture_on_commit_callbacks
    for channel in CHANNELS:
        owner, other = support.make_employee(), support.make_employee()
        chat, spare = _chat(), _chat()
        code_owner = _issue(owner, channel).code
        _dialog(cb, channel, chat)
        assert _say(cb, channel, chat, code_owner) == "bound"
        code_other = _issue(other, channel).code
        assert _say(cb, channel, chat, code_other) == "chat_taken"
        assert _texts(bots_on, channel)[-1] == CHAT_TAKEN
        assert _bindings(channel, chat_id=str(chat)).get().user_id == owner.pk, "чат перешёл к другой записи"
        assert not _bindings(channel, user=other).exists()
        assert _row(code_other, channel).used_at is None, "код потрачен при отказе chat_taken"
        assert model("notify.BotChat").objects.get(channel=channel, chat_id=str(chat)).bad_attempts == 0
        with pytest.raises(NotifyError) as refused:
            binding.bind(other.pk, channel, str(chat))
        assert refused.value.code == "chat_taken" and refused.value.field == "channel"
        assert _bindings(channel, chat_id=str(chat)).get().user_id == owner.pk
        # не потраченный код привязывает другой чат
        _dialog(cb, channel, spare)
        assert _say(cb, channel, spare, code_other) == "bound"
        assert _bindings(channel, user=other).get().chat_id == str(spare)


def test_sixth_wrong_code_in_10_minutes_gets_too_many_attempts(bots_on, django_capture_on_commit_callbacks):
    """FR-325: после пяти неверных кодов за 10 минут чат получает `too_many` — даже на верный код (предел проверяется раньше кода)."""
    cb = django_capture_on_commit_callbacks
    for channel in CHANNELS:
        user = support.make_employee()
        code = _issue(user, channel).code
        chat, free = _chat(), _chat()
        _dialog(cb, channel, chat)
        for _ in range(5):
            assert _say(cb, channel, chat, _wrong()) == "code_invalid"
        assert _say(cb, channel, chat, code) == "too_many", "шестая попытка принята как код"
        assert _texts(bots_on, channel) == [ASK_CODE] + [CODE_INVALID] * 5 + [TOO_MANY]
        assert not _bindings(channel, user=user).exists()
        assert _row(code, channel).used_at is None
        assert _say(cb, channel, chat, _wrong()) == "too_many"
        # предел — на чат: другой чат с тем же кодом привязывается
        _dialog(cb, channel, free)
        assert _say(cb, channel, free, code) == "bound"


def test_five_wrong_codes_are_answered_normally_and_window_resets_after_10_minutes(bots_on,
                                                                                  django_capture_on_commit_callbacks):
    """FR-325: пять неверных кодов получают обычный отказ; окно в 10 минут: внутри окна — `too_many`, после — счёт заново."""
    cb = django_capture_on_commit_callbacks
    for channel in CHANNELS:
        chat = _chat()
        _dialog(cb, channel, chat)
        for _ in range(5):
            assert _say(cb, channel, chat, _wrong()) == "code_invalid"
        row = model("notify.BotChat").objects.get(channel=channel, chat_id=str(chat))
        assert row.bad_attempts == 5 and row.window_started_at is not None
        assert _texts(bots_on, channel) == [ASK_CODE] + [CODE_INVALID] * 5
        # окно началось 9 минут назад — ещё действует
        model("notify.BotChat").objects.filter(pk=row.pk).update(
            window_started_at=timezone.now() - timedelta(minutes=9))
        assert _say(cb, channel, chat, _wrong()) == "too_many"
        # окно началось 11 минут назад — счёт заново
        model("notify.BotChat").objects.filter(pk=row.pk).update(
            window_started_at=timezone.now() - timedelta(minutes=11))
        assert _say(cb, channel, chat, _wrong()) == "code_invalid"
        fresh = model("notify.BotChat").objects.get(pk=row.pk)
        assert fresh.bad_attempts == 1
        assert timezone.now() - fresh.window_started_at < timedelta(minutes=1)
        user = support.make_employee()
        code = _issue(user, channel).code
        assert _say(cb, channel, chat, code) == "bound"
        assert _bindings(channel, user=user).get().chat_id == str(chat)


def test_rebinding_channel_to_another_chat_replaces_previous_binding(bots_on, django_capture_on_commit_callbacks):
    """FR-325: повторная привязка того же канала к другому чату заменяет прежнюю; другой канал и журнал — как в § 9.2."""
    cb = django_capture_on_commit_callbacks
    user = support.make_employee()
    old_chat, new_chat = _chat(), _chat()
    _dialog(cb, "telegram", old_chat)
    assert _say(cb, "telegram", old_chat, _issue(user, "telegram").code) == "bound"
    max_chat = _chat()
    _dialog(cb, "max", max_chat)
    assert _say(cb, "max", max_chat, _issue(user, "max").code) == "bound"
    _dialog(cb, "telegram", new_chat)
    assert _say(cb, "telegram", new_chat, _issue(user, "telegram").code) == "bound"
    assert _bindings("telegram", user=user).count() == 1
    assert _bindings("telegram", user=user).get().chat_id == str(new_chat)
    assert not _bindings("telegram", chat_id=str(old_chat)).exists()
    assert _bindings("max", user=user).get().chat_id == str(max_chat), "привязка другого канала тронута"
    # освобождённый чат можно привязать к другой записи
    other = support.make_employee()
    assert _say(cb, "telegram", old_chat, _issue(other, "telegram").code) == "bound"
    # прямой вызов службы: тоже замена, журнал «было / стало» по § 9.2
    from apps.notify.services import binding

    direct_chat = str(_chat())
    binding.bind(user.pk, "telegram", direct_chat)
    assert _bindings("telegram", user=user).get().chat_id == direct_chat
    events = _audit("notify.channel_bound", user)
    telegram_events = [e for e in events if e.after.get("channel") == "telegram"]
    assert len(telegram_events) == 3
    assert telegram_events[0].before == {"bound": False}
    assert telegram_events[-1].before == {"channel": "telegram", "bound": True}
    assert telegram_events[-1].after == {"channel": "telegram", "bound": True}


def test_repeated_event_after_failure_gives_one_binding_and_one_reply(bots_on, django_capture_on_commit_callbacks):
    """FR-325: повтор того же сообщения из уже привязанного чата — `repeat`: одна привязка, один ответ, одна запись журнала."""
    cb = django_capture_on_commit_callbacks
    for channel in CHANNELS:
        user = support.make_employee()
        code = _issue(user, channel).code
        chat = _chat()
        _dialog(cb, channel, chat)
        update = _text_update(channel, chat, code)
        assert _handle(cb, channel, update) == "bound"
        sent_before = bots_on.sent(channel)
        used_at = _row(code, channel).used_at
        assert _handle(cb, channel, update) == "repeat"
        assert bots_on.sent(channel) == sent_before, "на повтор события бот ответил"
        assert _texts(bots_on, channel) == [ASK_CODE, BOUND_TEXT[channel]]
        assert _bindings(channel, user=user).count() == 1
        assert _bindings(channel, user=user).get().chat_id == str(chat)
        assert _row(code, channel).used_at == used_at
        assert model("notify.BotChat").objects.get(channel=channel, chat_id=str(chat)).bad_attempts == 0
        assert len([e for e in _audit("notify.channel_bound", user) if e.after.get("channel") == channel]) == 1
