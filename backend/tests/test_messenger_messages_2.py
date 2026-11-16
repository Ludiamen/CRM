"""T-8109b: тесты цитаты и пределов (FR-652, FR-654, FR-655, FR-656, FR-657, FR-662, FR-666, FR-669).

Источники: PLAN-008 «Отправка, правка, удаление, цитата» (цитата одного уровня, цепочка не строится, правка без
уведомлений, удаление вместе с вложениями и файлами) и «Упоминания „@“» (предел 20 разных людей при отправке и
правке), TASKS-008 T-8109b; CONTRACT-008: 2.2 (`Message.quote` — `SET_NULL`, `MessageAttachment`, `StoredFile`),
5.2 (`messages.send`/`edit`/`delete`, `mentions.extract`), 5.4 (`files`, эскизы), 10.1 (HTMX, отказ 200, 403/404),
10.2 (поля `text`, `quote` и коды отказов), 12.3 (зацепки `#m<id>`, `[data-quote-id]`, `[data-messenger-deleted]`,
`[data-messenger-file]`), 13.1 (`message_missing`, `mentions_limit`), 13.3 («Сообщение удалено»), 1.3 (пути
оригиналов и эскизов собираются до удаления строк).

Код среза на уровне модуля не импортируется (CONTRACT-008, «Правила для всех тестов среза»): модели берутся
через `support.model`, службы и пути ядра — внутри функций теста. Тексты отказов — литералы раздела 13.1, ищутся
подстрокой. Секретов и ПДн нет: адреса и телефоны не создаются.

Допущения писателя (см. отчёт T-8109b): 1) цитата сообщения *другого видимого* чата — отказ формы `quote` /
`message_missing` (10.2), цитата сообщения чата, которого сотрудник не видит, — 404 «Не найдено» (FR-669);
2) удаление сообщения стирает и оригиналы, и эскизы вложений — «файлы» плана (1.3 перечисляет пути эскизов вместе
с оригиналами); 3) «отправка не создаёт уведомлений» проверяется там, где их и не должно быть: сообщение себе
(чат, где автор единственный участник) и упоминание себя (FR-666); правка не создаёт их никому (FR-656).
"""
import pathlib
from html.parser import HTMLParser

import pytest
from django.conf import settings as django_settings

from tests import support
from tests import support_messenger as messenger
from tests.support import HX

pytestmark = pytest.mark.django_db

DELETED = "Сообщение удалено"
MESSAGE_MISSING = "Сообщение не найдено"
MENTIONS_LIMIT = "Не больше 20 упоминаний"
MISSING = 999999

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- разбор разметки (помощник только этого файла; образец — test_messenger_messages.py) ------------------------

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
        parts = []

        def collect(node):
            for child in node.children:
                if isinstance(child, _Node):
                    collect(child)
                else:
                    parts.append(child)

        collect(self)
        return " ".join("".join(parts).split())


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in VOID_TAGS:
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


def _html(value) -> str:
    """Тело ответа или готовая строка разметки."""
    if hasattr(value, "content"):
        return value.content.decode("utf-8", "replace")
    return value


def _tree(value) -> _Node:
    parser = _Parser()
    parser.feed(_html(value))
    return parser.root


def _q(scope, tag=None, **attrs) -> list:
    """Потомки по тегу и атрибутам; `_` в имени атрибута — дефис, `True` — «атрибут есть»."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value)
               for name, value in wanted.items()):
            found.append(node)
    return found


def _q1(scope, tag=None, **attrs) -> _Node:
    found = _q(scope, tag, **attrs)
    assert len(found) == 1, f"узлов {tag or '*'}: {len(found)} (ожидали один)"
    return found[0]


# --- помощники файла (общие помощники среза не правятся) -------------------------------------------------------

def _Message():
    return support.model("messenger.Message")


def _chat_url(chat) -> str:
    return f"/messenger/chats/{chat.pk}/"


def _messages_url(chat) -> str:
    return f"/messenger/chats/{chat.pk}/messages/"


def _action_url(message, action: str) -> str:
    return f"/messenger/messages/{message.pk}/{action}/"


def _send(session, chat, text: str, *, hx: bool = True, **fields):
    """`POST /messenger/chats/<id>/messages/` (CONTRACT-008, 10.2)."""
    data = {"text": text, **fields}
    return session.client.post(_messages_url(chat), data, **(HX if hx else {}))


def _edit(session, message, text: str, *, hx: bool = True):
    """`POST /messenger/messages/<mid>/edit/` (CONTRACT-008, 10.2)."""
    return session.client.post(_action_url(message, "edit"), {"text": text}, **(HX if hx else {}))


def _delete(session, message, *, hx: bool = True):
    """`POST /messenger/messages/<mid>/delete/` (CONTRACT-008, 10.2)."""
    return session.client.post(_action_url(message, "delete"), {}, **(HX if hx else {}))


def _error(root, field: str, code: str) -> _Node:
    """Отказ у поля: `[data-error="<поле>"][data-code="<код>"]` (CONTRACT-008, 10.1)."""
    nodes = _q(root, data_error=field, data_code=code)
    assert nodes, f"нет [data-error=\"{field}\"][data-code=\"{code}\"]"
    return nodes[0]


def _message_node(root, message) -> _Node:
    """Сообщение `#m<id>[data-message-id]` (CONTRACT-008, 12.3)."""
    node = _q1(root, id=f"m{message.pk}")
    assert node.attrs.get("data-message-id") == str(message.pk), node.attrs
    return node


def _rows(chat) -> list:
    return list(_Message().objects.filter(chat=chat).order_by("created_at", "id"))


def _marks(*people) -> str:
    """Маркеры упоминаний людей (CONTRACT-008, 5.2): `@[u<id>]`."""
    return " ".join(f"@[u{person.pk}]" for person in people)


def _paths(attachment) -> list[pathlib.Path]:
    """Пути оригинала и эскиза строки `MessageAttachment` под `PROTECTED_ROOT` (CONTRACT-008, 1.3, 12.5)."""
    from apps.core.services import files

    paths = [files.attachment_path(attachment.file)]
    if attachment.thumb:
        paths.append(pathlib.Path(django_settings.PROTECTED_ROOT) / attachment.thumb)
    return paths


# --- цитата (FR-654) ---------------------------------------------------------------------------------------------

def test_quote_one_level_and_quote_of_other_chat_refused():
    """FR-654: цитата — ссылка на исходное сообщение этого же чата, у ответа ровно одна `[data-quote-id]` с
    текстом исходного; цитата одного уровня — у исходного цитаты нет; цитата сообщения другого (видимого) чата и
    несуществующего номера — отказ 200 `quote` / `message_missing` без записи (CONTRACT-008, 10.2)."""
    author = messenger.make_user(full_name="Автор Цитаты")
    friend = messenger.make_user(full_name="Собеседник Цитаты")
    chat = messenger.group(author, [friend], title="Цитаты")
    other = messenger.group(author, [friend], title="Другая беседа")

    source = messenger.post(chat, friend, "Исходный текст для цитаты")
    foreign = messenger.post(other, friend, "Текст из другого чата")

    response = _send(author, chat, "Ответ с цитатой", quote=str(source.pk))
    assert response.status_code == 200, f"отправка с цитатой: {response.status_code}"
    assert _q(_tree(response), data_error=True) == [], "принятая цитата отказа не даёт"
    reply = _rows(chat)[-1]
    assert reply.quote_id == source.pk, f"цитата хранит ссылку на исходное: {reply.quote_id}"

    node = _message_node(_tree(response), reply)
    quote = _q1(node, data_quote_id=str(source.pk))
    assert "Исходный текст для цитаты" in quote.text(), quote.text()

    page = friend.client.get(_chat_url(chat))
    assert page.status_code == 200, f"беседа: {page.status_code}"
    page_reply = _message_node(_tree(page), reply)
    assert len(_q(page_reply, data_quote_id=True)) == 1, "у ответа ровно одна цитата — один уровень"
    page_source = _message_node(_tree(page), source)
    assert _q(page_source, data_quote_id=True) == [], "у исходного сообщения цитаты нет"

    for quote_id in (foreign.pk, MISSING):
        refused = _send(author, chat, "Цитата не оттуда", quote=str(quote_id))
        assert refused.status_code == 200, f"цитата {quote_id}: {refused.status_code}"
        reason = _error(_tree(refused), "quote", "message_missing")
        assert MESSAGE_MISSING in reason.text(), reason.text()
    assert _rows(chat) == [source, reply], "отказ цитаты ничего не сохраняет"
    assert _Message().objects.filter(pk=foreign.pk).exists(), "сообщение другого чата цело"


def test_quote_of_deleted_message_shown_as_deleted():
    """FR-654, 657: у ответа на удалённое сообщение цитата остаётся на месте и показывает «Сообщение удалено»;
    текста удалённого нет ни в цитате, ни на странице."""
    author = messenger.make_user(full_name="Автор Удалённой Цитаты")
    friend = messenger.make_user(full_name="Собеседник Удалённой Цитаты")
    chat = messenger.group(author, [friend], title="Удалённая цитата")

    source = messenger.post(chat, friend, "Текст, который удалят")
    reply = messenger.post(chat, author, "Ответ на удаляемое", quote=source)

    deleted = _delete(friend, source)
    assert deleted.status_code == 200, f"удаление исходного: {deleted.status_code}"

    page = author.client.get(_chat_url(chat))
    assert page.status_code == 200, f"беседа: {page.status_code}"
    reply_node = _message_node(_tree(page), reply)
    quote = _q1(reply_node, data_quote_id=str(source.pk))
    assert DELETED in quote.text(), quote.text()
    assert "Текст, который удалят" not in quote.text(), "текста удалённого в цитате нет"
    assert "Текст, который удалят" not in _html(page), "текст удалённого не виден и вне цитаты"

    source_node = _message_node(_tree(page), source)
    assert _q(source_node, data_messenger_deleted=True), "исходное — серая запись «Сообщение удалено»"
    reply.refresh_from_db()
    assert reply.quote_id == source.pk, "мягкое удаление строку не стирает: ссылка цитаты жива"
    assert reply.text == "Ответ на удаляемое", "ответ не меняется"


def test_quote_cannot_be_nested_second_level():
    """FR-654: ответ на ответ цитирует ровно своё исходное сообщение; цепочка не строится — вторая цитата не
    вкладывается, текста более раннего сообщения в ней нет."""
    author = messenger.make_user(full_name="Автор Цепочки")
    friend = messenger.make_user(full_name="Собеседник Цепочки")
    chat = messenger.group(author, [friend], title="Цепочка цитат")

    first = messenger.post(chat, friend, "Первый текст")
    assert _send(author, chat, "Ответ первому", quote=str(first.pk)).status_code == 200
    reply = _rows(chat)[-1]
    assert reply.quote_id == first.pk

    response = _send(author, chat, "Ответ на ответ", quote=str(reply.pk))
    assert response.status_code == 200, f"ответ на ответ: {response.status_code}"
    assert _q(_tree(response), data_error=True) == []
    second = _rows(chat)[-1]
    assert second.quote_id == reply.pk, "цитата — прямое исходное сообщение"
    assert second.quote.quote_id == first.pk, "связь одна: цепочка хранится только ссылками сообщений"

    node = _message_node(_tree(response), second)
    quotes = _q(node, data_quote_id=True)
    assert len(quotes) == 1, f"цитат в сообщении: {len(quotes)} (второй уровень не создаётся)"
    assert quotes[0].attrs["data-quote-id"] == str(reply.pk), quotes[0].attrs
    assert "Ответ первому" in quotes[0].text(), quotes[0].text()
    assert "Первый текст" not in quotes[0].text(), "в цитате нет текста более раннего сообщения"
    assert _q(quotes[0], data_quote_id=True) == [], "вложенной цитаты внутри цитаты нет"
    assert _q(node, id=f"m{first.pk}") == [], "вложенного исходного сообщения нет"
    assert len(_rows(chat)) == 3, "второй уровень не создаёт новых сообщений"


def test_quote_to_message_of_invisible_chat_returns_404():
    """FR-669: цитата сообщения чата, которого сотрудник не видит, — 404 «Не найдено», неотличимый от
    несуществующего чата; сообщение в свой чат не сохраняется (цитата другого *видимого* чата — отказ формы,
    см. test_quote_one_level_and_quote_of_other_chat_refused)."""
    owner = messenger.make_user(full_name="Владелец Закрытого")
    peer = messenger.make_user(full_name="Собеседник Закрытого")
    outsider = messenger.make_user(full_name="Посторонний Цитаты")
    witness = messenger.make_user(full_name="Свидетель Цитаты")

    closed = messenger.group(owner, [peer], title="Закрытая беседа")
    hidden = messenger.post(closed, peer, "Секрет закрытой беседы")
    own = messenger.group(outsider, [witness], title="Свой чат")

    for hx in (True, False):
        fields = {"text": "Цитата секрета", "quote": str(hidden.pk)}
        response = _send(outsider, own, "Цитата секрета", hx=hx, quote=str(hidden.pk))
        missing = outsider.client.post(f"/messenger/chats/{MISSING}/messages/", fields, **(HX if hx else {}))
        assert response.status_code == 404, f"цитата невидимого чата (hx={hx}): {response.status_code}"
        assert support.same_failure(response, missing), "404 отличается от несуществующего чата"

    assert _rows(own) == [], "отказ ничего не сохраняет"
    assert _Message().objects.filter(pk=hidden.pk).exists(), "сообщение закрытого чата цело"


# --- уведомления (FR-656, 666) -----------------------------------------------------------------------------------

def test_sending_and_editing_create_no_notifications():
    """FR-656, 666: отправка себе (в чат, где автор единственный участник) и упоминание себя уведомлений не дают;
    правка не создаёт уведомлений, в том числе при добавлении нового упоминания; своё сообщение автору
    уведомления не даёт."""
    Notification = support.model("notify.Notification")
    author = messenger.make_user(full_name="Автор Без Уведомлений")
    friend = messenger.make_user(full_name="Собеседник Без Уведомлений")
    third = messenger.make_user(full_name="Третий Без Уведомлений")

    solo = messenger.group(author, [], title="Сам с собой")
    alone = f"Заметка себе {_marks(author)}"
    response = _send(author, solo, alone)
    assert response.status_code == 200, f"отправка себе: {response.status_code}"
    assert _q(_tree(response), data_error=True) == []
    assert _rows(solo)[-1].text == alone
    assert Notification.objects.count() == 0, "своё сообщение и упоминание себя уведомлений не дают (FR-666)"

    chat = messenger.group(author, [friend, third], title="Без уведомлений")
    draft = messenger.post(chat, author, "Черновик")
    before = set(Notification.objects.values_list("pk", flat=True))
    edited = _edit(author, draft, f"Черновик {_marks(friend, third, author)}")
    assert edited.status_code == 200, f"правка: {edited.status_code}"
    assert _q(_tree(edited), data_error=True) == []
    after = set(Notification.objects.values_list("pk", flat=True))
    assert after == before, "правка уведомлений не создаёт, в том числе при новом упоминании (FR-656)"
    assert not Notification.objects.filter(kind__startswith="messenger.").exists()

    sent = _send(author, chat, f"Привет {_marks(author)}")
    assert sent.status_code == 200, f"отправка в чат: {sent.status_code}"
    assert _q(_tree(sent), data_error=True) == []
    assert not Notification.objects.filter(user=author).exists(), "своё сообщение автору уведомления не даёт"


# --- предел упоминаний (FR-652, 655) -----------------------------------------------------------------------------

def test_mentions_limit_on_edit_same_as_on_send():
    """FR-652, 655: 20 разных упоминаний принимаются и при отправке, и при правке; 21-е — отказ `text` /
    `mentions_limit` «Не больше 20 упоминаний»; повтор не расходует предел; отказ правки текст не меняет."""
    author = messenger.make_user(full_name="Автор Упоминаний")
    people = [messenger.make_user(full_name=f"Упомянутый {number:02d}") for number in range(1, 22)]
    chat = messenger.group(author, people, title="Упоминания")

    allowed = f"{_marks(*people[:20])} {_marks(*people[:5])}"
    sent = _send(author, chat, allowed)
    assert sent.status_code == 200, f"20 упоминаний при отправке: {sent.status_code}"
    assert _q(_tree(sent), data_error=True) == [], "20 разных людей и повторы принимаются"
    message = _rows(chat)[-1]
    assert message.text == allowed

    over = _send(author, chat, _marks(*people))
    assert over.status_code == 200, f"21 упоминание при отправке: {over.status_code}"
    reason = _error(_tree(over), "text", "mentions_limit")
    assert MENTIONS_LIMIT in reason.text(), reason.text()
    assert _rows(chat) == [message], "отказ по упоминаниям ничего не сохраняет"

    refused = _edit(author, message, _marks(*people))
    assert refused.status_code == 200, f"21 упоминание при правке: {refused.status_code}"
    reason = _error(_tree(refused), "text", "mentions_limit")
    assert MENTIONS_LIMIT in reason.text(), reason.text()
    message.refresh_from_db()
    assert message.text == allowed, "отказ правки оставляет прежний текст"
    assert message.edited_at is None

    twenty = _marks(*people[:20])
    accepted = _edit(author, message, twenty)
    assert accepted.status_code == 200, f"20 упоминаний при правке: {accepted.status_code}"
    assert _q(_tree(accepted), data_error=True) == []
    message.refresh_from_db()
    assert message.text == twenty, "правка с 20 упоминаниями сохраняется"
    assert message.edited_at is not None, "пометка «изменено» (FR-656)"


# --- удаление с вложениями (FR-657, 662) -------------------------------------------------------------------------

def test_delete_message_removes_attachments_rows_and_files_after_commit(
        django_capture_on_commit_callbacks, protected_root):
    """FR-657, 662: удаление сообщения убирает строки `MessageAttachment`, строки `StoredFile` и файлы (оригиналы
    и эскизы) с диска — стирание диска после фиксации (`transaction.on_commit`); вложения другого сообщения целы;
    серая запись «Сообщение удалено» файлов не показывает."""
    MessageAttachment = support.model("messenger.MessageAttachment")
    StoredFile = support.model("core.StoredFile")

    author = messenger.make_user(full_name="Автор Файлов Удаления")
    friend = messenger.make_user(full_name="Собеседник Файлов Удаления")
    chat = messenger.group(author, [friend], title="Файлы удаления")

    scheme = messenger.attach(chat, "схема.png", write=True, thumb=True)
    plan = messenger.attach(chat, "план.pdf", b"%PDF-1.4\nplan body\n", write=True)
    kept = messenger.attach(chat, "живой.png", write=True)
    message = messenger.post(chat, author, "Удаляемое с файлами", files=[scheme, plan])
    messenger.post(chat, friend, "Живое сообщение", files=[kept])

    doomed = _paths(scheme) + _paths(plan)
    alive = _paths(kept)
    assert all(path.exists() for path in doomed), "оригиналы и эскизы записаны"
    assert all(path.exists() for path in alive)

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        response = _delete(author, message)
        assert response.status_code == 200, f"удаление: {response.status_code}"
        assert not MessageAttachment.objects.filter(message_id=message.pk).exists(), "строки вложений удалены"
        assert not StoredFile.objects.filter(pk__in=[scheme.file_id, plan.file_id]).exists(), "строки файлов удалены"
        assert all(path.exists() for path in doomed), "диск стирается после фиксации, а не в транзакции"

    assert callbacks, "стирание диска — transaction.on_commit после фиксации"
    for callback in callbacks:
        callback()
    assert all(not path.exists() for path in doomed), "после фиксации оригиналы и эскизы стёрты"

    node = _message_node(_tree(response), message)
    assert _q(node, data_messenger_deleted=True), "на месте сообщения — серая запись"
    assert DELETED in node.text(), node.text()
    assert _q(node, data_messenger_file=True) == [], "у удалённого сообщения файлов нет"
    assert "Удаляемое с файлами" not in _html(response)

    assert MessageAttachment.objects.filter(pk=kept.pk).exists(), "вложение другого сообщения цело"
    assert all(path.exists() for path in alive), "файлы другого сообщения на диске целы"

    message.refresh_from_db()
    assert message.deleted_at is not None and message.text == "", "мягкое удаление сообщения (FR-657)"
    assert _Message().objects.filter(pk=message.pk).exists(), "строка сообщения остаётся серой записью"

    page = friend.client.get(_chat_url(chat))
    assert page.status_code == 200, f"беседа: {page.status_code}"
    page_node = _message_node(_tree(page), message)
    assert _q(page_node, data_messenger_deleted=True) and DELETED in page_node.text()
    assert _q(page_node, data_messenger_file=True) == [], "файлы удалённого не показываются и в беседе"