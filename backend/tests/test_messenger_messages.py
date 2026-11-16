"""T-8109a: тесты отправки, правки и удаления сообщений (FR-644, FR-652, FR-653, FR-656, FR-657, FR-669, FR-670).

Источники: PLAN-008 «Отправка, правка, удаление, цитата» (пределы текста, хранение как есть, пометка «изменено»,
серая запись, пересчёт `last_message_at`), TASKS-008 T-8109a; CONTRACT-008: 2.2 (`Message`), 5.1 (`chats.rows`),
5.2 (`messages.send`/`edit`/`delete`, `search.vectors`), 5.4 (`retention.run`), 10.1 (HTMX, отказ 200, 403/404),
10.2 (поля и ответы адресов), 12.1–12.3 (зацепки `#m<id>`, `time[data-at]`, `[data-messenger-edited]`,
`[data-messenger-deleted]`, `[data-error]`), 13.1 (`empty_text`, `too_long`), 13.3 («Сообщение удалено», «изменено»).

Код среза на уровне модуля не импортируется (CONTRACT-008, «Правила для всех тестов среза»): модели берутся
через `support.model`, службы — внутри функций теста. Тексты отказов — литералы раздела 13.1, ищутся подстрокой.
Секретов и ПДн нет: адреса и телефоны не создаются.

Допущения писателя (см. отчёт T-8109a): контракт не говорит, какое время показывает серая запись удалённого
сообщения — отправки или удаления; тест принимает оба и сверяет только формат `time[data-at]`. Вектор поиска
сверяется с `to_tsvector('russian', <текст>)` — точная форма SQL-пересчёта в контракте 5.4 (`search.vectors`).
"""
import re
from datetime import datetime, timezone as dt_timezone
from html.parser import HTMLParser

import pytest
from django.db import connection

from tests import support
from tests import support_messenger as messenger
from tests.support import HX

pytestmark = pytest.mark.django_db

UTC = dt_timezone.utc
EMPTY_TEXT = "Напишите текст"
LIMIT_4000 = "Предел: 4000 знаков"
DELETED = "Сообщение удалено"
EDITED = "изменено"
MISSING = 999999

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- разбор разметки (помощник только этого файла; образец — test_messenger_personal.py) ------------------------

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
        super().__init__()
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


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _rows(chat) -> list:
    return list(_Message().objects.filter(chat=chat).order_by("created_at", "id"))


def _list_ids(session) -> list[int]:
    """Номера чатов списка в порядке вывода (`[data-chat-id]`, CONTRACT-008, 12.2)."""
    response = session.client.get("/messenger/list/")
    assert response.status_code == 200, f"/messenger/list/: {response.status_code}"
    return [int(found) for found in re.findall(r'data-chat-id="(\d+)"', _html(response))]


def _vector(message):
    """Вектор поиска строкой: `NULL` — `None`, пустой — `""` (поле `search`, CONTRACT-008, 2.2)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT search::text FROM messenger_message WHERE id = %s", [message.pk])
        row = cursor.fetchone()
    assert row is not None, f"сообщения {message.pk} нет в таблице"
    return row[0]


def _expected_vector(text: str) -> str:
    with connection.cursor() as cursor:
        cursor.execute("SELECT to_tsvector('russian', %s)::text", [text])
        return cursor.fetchone()[0]


def _chat(author, friend, title: str):
    return messenger.group(author, [friend], title=title)


# --- отправка: пустой и предельный текст (FR-652) ---------------------------------------------------------------

def test_empty_and_spaces_only_refused_with_reason():
    """FR-652: пустой и состоящий из пробелов текст — 200 с причиной «Напишите текст» у поля `text`, сообщения нет;
    отказ одинаков для обычного POST и HTMX (CONTRACT-008, 10.1)."""
    author = messenger.make_user(full_name="Автор Пустого")
    friend = messenger.make_user(full_name="Собеседник Пустого")
    chat = _chat(author, friend, "Пустой текст")

    for hx in (True, False):
        for blank in ("", "   \n\t "):
            response = _send(author, chat, blank, hx=hx)
            assert response.status_code == 200, f"пустой текст (hx={hx}): {response.status_code}"
            reason = _error(_tree(response), "text", "empty_text")
            assert EMPTY_TEXT in reason.text(), reason.text()

    assert _rows(chat) == [], "отказ не должен сохранять сообщение"
    chat.refresh_from_db()
    assert chat.last_message_at is None, "у чата без сообщений времени последнего быть не должно"


def test_4000_accepted_4001_refused_and_nul_removed():
    """FR-652: 4 000 знаков принимаются и хранятся целиком; 4 001 — причина «Предел: 4000 знаков» у `text`;
    символ NUL удаляется из текста до записи."""
    author = messenger.make_user(full_name="Автор Предела")
    friend = messenger.make_user(full_name="Собеседник Предела")
    chat = _chat(author, friend, "Предел текста")

    limit = "я" * 4000
    accepted = _send(author, chat, limit)
    assert accepted.status_code == 200, f"4 000 знаков: {accepted.status_code}"
    assert _q(_tree(accepted), data_error=True) == [], "4 000 знаков приняты без отказа"
    (stored,) = _rows(chat)
    assert stored.text == limit and len(stored.text) == 4000
    node = _message_node(_tree(accepted), stored)
    assert node.attrs.get("data-own") == "1", "своё сообщение помечено data-own=1"
    assert limit[:40] in node.text()

    refused = _send(author, chat, "я" * 4001)
    assert refused.status_code == 200, f"4 001 знак: {refused.status_code}"
    reason = _error(_tree(refused), "text", "too_long")
    assert LIMIT_4000 in reason.text(), reason.text()
    assert _rows(chat) == [stored], "отказ по пределу ничего не сохраняет"

    nul = _send(author, chat, "При\x00вет\x00, коллега")
    assert nul.status_code == 200 and _q(_tree(nul), data_error=True) == []
    second = _rows(chat)[-1]
    assert second.text == "Привет, коллега", f"NUL удаляется: {second.text!r}"
    assert "\x00" not in second.text


def test_text_stored_as_is_with_paragraphs_and_breaks():
    """FR-652, FR-653: текст хранится как есть — абзацы и переносы строк сохраняются, срезаются только пробелы
    по краям; участник видит все абзацы в беседе."""
    author = messenger.make_user(full_name="Автор Абзацев")
    friend = messenger.make_user(full_name="Собеседник Абзацев")
    chat = _chat(author, friend, "Абзацы")

    text = "Первый абзац.\n\nВторой абзац.\nТретья строка."
    response = _send(author, chat, f"  {text} \n")
    assert response.status_code == 200 and _q(_tree(response), data_error=True) == []
    (stored,) = _rows(chat)
    assert stored.text == text, f"текст должен храниться как есть: {stored.text!r}"
    assert stored.text.count("\n") == 3, "абзац и перенос строки не схлопываются"

    page = friend.client.get(_chat_url(chat))
    assert page.status_code == 200, f"беседа: {page.status_code}"
    _message_node(_tree(page), stored)
    html = _html(page)
    for part in ("Первый абзац.", "Второй абзац.", "Третья строка."):
        assert part in html, f"«{part}» не видно в беседе"


# --- правка (FR-656) ---------------------------------------------------------------------------------------------

def test_author_edits_text_gets_edited_mark_and_old_text_gone(clock):
    """FR-656: автор правит своё сообщение; `edited_at` — время правки, пометка `[data-messenger-edited]` и слово
    «изменено», прежнего текста нет ни в ответе, ни в базе; вектор пересчитан; обычный POST — 302 в беседу."""
    author = messenger.make_user(full_name="Автор Правки")
    friend = messenger.make_user(full_name="Собеседник Правки")
    chat = _chat(author, friend, "Правка")
    clock.set(messenger.moscow(2026, 3, 10, 13, 0))
    message = messenger.post(chat, author, "Старый текст", created_at=messenger.moscow(2026, 3, 10, 13, 0))
    created_at = message.created_at

    edited_at = messenger.moscow(2026, 3, 10, 14, 5)
    clock.set(edited_at)
    response = _edit(author, message, "Новый текст")
    assert response.status_code == 200, f"правка HTMX: {response.status_code}"
    assert "<html" not in _html(response).lower(), "HTMX-ответ — фрагмент, а не страница"
    node = _message_node(_tree(response), message)
    assert _q(node, data_messenger_edited=True), "нет пометки [data-messenger-edited]"
    assert EDITED in node.text(), node.text()
    assert "Новый текст" in node.text(), node.text()
    assert "Старый текст" not in _html(response), "прежний текст не хранится (FR-656)"

    message.refresh_from_db()
    assert message.text == "Новый текст"
    assert message.edited_at == edited_at, f"edited_at: {message.edited_at}"
    assert message.created_at == created_at, "время отправки не меняется"
    assert message.deleted_at is None
    assert _vector(message) == _expected_vector("Новый текст"), "вектор поиска пересчитан"

    page = author.client.get(_chat_url(chat))
    assert page.status_code == 200
    page_node = _message_node(_tree(page), message)
    assert _q(page_node, data_messenger_edited=True) and EDITED in page_node.text()
    assert "Старый текст" not in _html(page)

    later = messenger.moscow(2026, 3, 10, 14, 30)
    clock.set(later)
    plain = _edit(author, message, "Третий текст", hx=False)
    assert plain.status_code == 302, f"обычный POST правки: {plain.status_code}"
    assert plain["Location"] == _chat_url(chat), plain["Location"]
    message.refresh_from_db()
    assert message.text == "Третий текст" and message.edited_at == later


def test_foreign_message_edit_and_delete_403_or_404():
    """FR-656, FR-657, FR-669: участнику, но не автору, правка и удаление чужого сообщения — 403; постороннему чужой
    чат — 404, неотличимый от несуществующего сообщения; сообщение цело."""
    author = messenger.make_user(full_name="Автор Чужого")
    friend = messenger.make_user(full_name="Участник Чужого")
    outsider = messenger.make_user(full_name="Посторонний Чужого")
    chat = _chat(author, friend, "Чужие действия")
    message = messenger.post(chat, author, "Не трогать")
    stored = _Message().objects.get(pk=message.pk)
    before = (stored.text, stored.edited_at, stored.deleted_at)

    edit = _edit(friend, message, "Подмена")
    assert edit.status_code == 403, f"правка участником: {edit.status_code}"
    delete = _delete(friend, message)
    assert delete.status_code == 403, f"удаление участником: {delete.status_code}"

    for action, fields in (("edit", {"text": "Подмена"}), ("delete", {})):
        response = outsider.client.post(_action_url(message, action), fields, **HX)
        missing = outsider.client.post(f"/messenger/messages/{MISSING}/{action}/", fields, **HX)
        assert response.status_code == 404, f"{action} посторонним: {response.status_code}"
        assert support.same_failure(response, missing), f"{action}: 404 отличается от несуществующего сообщения"

    after = _Message().objects.get(pk=message.pk)
    assert (after.text, after.edited_at, after.deleted_at) == before, "чужое действие ничего не изменило"
    assert _rows(chat) == [after], "новых сообщений нет"


# --- удаление (FR-657) -------------------------------------------------------------------------------------------

def test_author_deletes_message_leaves_grey_record_with_time(clock):
    """FR-657: автор удаляет сообщение; на месте `#m<id>` — серая запись «Сообщение удалено» со временем; в базе
    `deleted_at`, пустой текст и пустой вектор; обычный POST — 302 в беседу."""
    author = messenger.make_user(full_name="Автор Удаления")
    friend = messenger.make_user(full_name="Собеседник Удаления")
    chat = _chat(author, friend, "Удаление")
    clock.set(messenger.moscow(2026, 3, 10, 13, 0))
    message = messenger.post(chat, author, "Удаляемый текст", created_at=messenger.moscow(2026, 3, 10, 13, 0))
    created_at = message.created_at

    deleted_at = messenger.moscow(2026, 3, 10, 14, 5)
    clock.set(deleted_at)
    response = _delete(author, message)
    assert response.status_code == 200, f"удаление HTMX: {response.status_code}"
    assert "<html" not in _html(response).lower(), "HTMX-ответ — фрагмент"
    node = _message_node(_tree(response), message)
    assert _q(node, data_messenger_deleted=True), "нет серой записи [data-messenger-deleted]"
    assert DELETED in node.text(), node.text()
    assert "Удаляемый текст" not in node.text(), "текста удалённого сообщения нет"
    stamp = _q1(node, "time", data_at=True)
    instant = _instant(stamp.attrs["datetime"])
    assert instant.astimezone(UTC) in {created_at.astimezone(UTC), deleted_at.astimezone(UTC)}, (
        "время серой записи — отправка или удаление (контракт не уточняет)")
    assert stamp.text() == messenger.moscow_text(instant), "текст времени по Москве"

    message.refresh_from_db()
    assert message.deleted_at == deleted_at, f"deleted_at: {message.deleted_at}"
    assert message.text == "", "текст стирается"
    assert _vector(message) in (None, ""), "вектор поиска пуст"

    page = friend.client.get(_chat_url(chat))
    assert page.status_code == 200
    page_node = _message_node(_tree(page), message)
    assert _q(page_node, data_messenger_deleted=True) and DELETED in page_node.text()
    assert "Удаляемый текст" not in _html(page)

    clock.set(messenger.moscow(2026, 3, 10, 14, 30))
    second = messenger.post(chat, author, "Второе сообщение")
    plain = _delete(author, second, hx=False)
    assert plain.status_code == 302, f"обычный POST удаления: {plain.status_code}"
    assert plain["Location"] == _chat_url(chat), plain["Location"]
    second.refresh_from_db()
    assert second.deleted_at is not None and second.text == ""


def test_delete_recalculates_last_message_at(clock):
    """FR-657, FR-644: `last_message_at` после удаления — время последнего живого сообщения чата (в том числе
    чужого); удаление единственного оставшегося обнуляет его."""
    author = messenger.make_user(full_name="Автор Пересчёта")
    friend = messenger.make_user(full_name="Собеседник Пересчёта")
    chat = _chat(author, friend, "Пересчёт")

    first_at = messenger.moscow(2026, 3, 10, 12, 0)
    second_at = messenger.moscow(2026, 3, 10, 12, 30)
    third_at = messenger.moscow(2026, 3, 10, 13, 0)
    clock.set(first_at)
    first = messenger.post(chat, author, "Первый", created_at=first_at)
    clock.set(second_at)
    second = messenger.post(chat, friend, "Второй", created_at=second_at)
    clock.set(third_at)
    third = messenger.post(chat, author, "Третий", created_at=third_at)

    chat.refresh_from_db()
    assert chat.last_message_at == third_at, "отправка поднимает время последнего сообщения"

    clock.set(messenger.moscow(2026, 3, 10, 14, 5))
    assert _delete(author, third).status_code == 200
    chat.refresh_from_db()
    assert chat.last_message_at == second_at, f"после удаления третьего: {chat.last_message_at}"

    assert _delete(author, first).status_code == 200
    chat.refresh_from_db()
    assert chat.last_message_at == second_at, "живое чужое сообщение остаётся последним"

    assert _delete(friend, second).status_code == 200
    chat.refresh_from_db()
    assert chat.last_message_at is None, "живых сообщений нет — времени нет"


# --- срок хранения (FR-670) --------------------------------------------------------------------------------------

def test_message_deleted_by_retention_cannot_be_edited_404():
    """FR-670 (п. 4): сообщение, удалённое ночным заданием по сроку, править нельзя — 404, неотличимый от
    несуществующего; свежее сообщение того же чата правится."""
    Settings = support.model("messenger.MessengerSettings")
    years = Settings.objects.get(pk=1).retention_years
    author = messenger.make_user(full_name="Автор Срока")
    friend = messenger.make_user(full_name="Собеседник Срока")
    chat = _chat(author, friend, "Срок хранения")

    old_at = messenger.moscow(2020, 1, 15, 10, 0)
    old = messenger.post(chat, author, "Старое сообщение", created_at=old_at)
    fresh = messenger.post(chat, author, "Свежее сообщение")

    now = messenger.moscow(2020 + years + 1, 1, 15, 10, 0)
    assert messenger.run_retention(now) >= 1, "ночное задание не удалило ни одного сообщения"
    assert not _Message().objects.filter(pk=old.pk).exists(), "сообщение старше срока удалено"
    assert _Message().objects.filter(pk=fresh.pk).exists(), "свежее сообщение осталось"

    for action, fields in (("edit", {"text": "Оживление"}), ("delete", {})):
        gone = author.client.post(f"/messenger/messages/{old.pk}/{action}/", fields, **HX)
        absent = author.client.post(f"/messenger/messages/{MISSING}/{action}/", fields, **HX)
        assert gone.status_code == 404, f"{action} удалённого по сроку: {gone.status_code}"
        assert support.same_failure(gone, absent), f"{action}: ответ отличается от несуществующего сообщения"

    alive = _edit(author, fresh, "Свежий текст")
    assert alive.status_code == 200, f"правка свежего: {alive.status_code}"
    fresh.refresh_from_db()
    assert fresh.text == "Свежий текст"


# --- порядок списка (FR-644) -------------------------------------------------------------------------------------

def test_send_updates_last_message_at_and_list_order(clock):
    """FR-644: отправка поднимает `last_message_at` чата до своего времени, и список ставит этот чат выше более
    позднего по прежним сообщениям (порядок — `COALESCE(last_message_at, created_at) DESC`, CONTRACT-008, 5.1)."""
    author = messenger.make_user(full_name="Автор Порядка")
    friend = messenger.make_user(full_name="Собеседник Порядка")

    clock.set(messenger.moscow(2026, 3, 10, 12, 0))
    older = _chat(author, friend, "Старый чат")
    older_at = messenger.moscow(2026, 3, 10, 12, 0)
    messenger.post(older, friend, "Раньше", created_at=older_at)

    clock.set(messenger.moscow(2026, 3, 10, 13, 0))
    newer = _chat(author, friend, "Новый чат")
    newer_at = messenger.moscow(2026, 3, 10, 13, 0)
    messenger.post(newer, friend, "Позже", created_at=newer_at)

    order = _list_ids(author)
    assert older.pk in order and newer.pk in order, order
    assert order.index(newer.pk) < order.index(older.pk), "свежий чат выше старого"

    sent_at = messenger.moscow(2026, 3, 10, 14, 5)
    clock.set(sent_at)
    response = _send(author, older, "Свежее сообщение")
    assert response.status_code == 200 and _q(_tree(response), data_error=True) == []
    newer.refresh_from_db()
    older.refresh_from_db()
    assert older.last_message_at == sent_at, f"время чата: {older.last_message_at}"
    assert newer.last_message_at == newer_at, "у другого чата время не меняется"
    assert _rows(older)[-1].text == "Свежее сообщение"

    order = _list_ids(author)
    assert order.index(older.pk) < order.index(newer.pk), "отправка подняла чат в списке"