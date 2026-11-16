"""T-8105: групповой чат — создание, состав, выход и удаление (FR-646, FR-647, FR-648, FR-660, FR-671).

План: «Виды чатов и создание», «Состав чата» (состав на момент просмотра и `joined_at`), «Журнал»; CONTRACT-008:
5.1 (`chats.create_group`, `members.members/is_member/visible_chats/get_chat`), 5.4 (удаление чата и файлов на
каждом пути), 8.1 (`messenger.chat_deleted` — без текста), 10.1–10.2 (поля форм, ответы, 403/404), 13.1
(`title_range`, `no_members`, `dismissed`, `delete_confirm`). Код среза на уровне модуля не импортируется: модели
берутся через `support.model`, службы — ленивыми импортами внутри тестов; тексты отказов — литералы контракта.
"""
import json
import pathlib
from datetime import timedelta
from html.parser import HTMLParser

import pytest
from django.conf import settings
from django.http import Http404
from django.utils import timezone

from tests import support
from tests import support_messenger as mm

pytestmark = pytest.mark.django_db

TITLE_RANGE = "Название чата — от 1 до 200 знаков"
NO_MEMBERS = "Выберите хотя бы одного участника"
DISMISSED = "Сотрудник уволен: написать нельзя"
DELETE_CONFIRM = "Удалить чат вместе с историей?"
MISSING_CHAT = 987654


# --- разбор разметки (помощник только этого файла, как в test_feed_comments.py) ------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}
        self.parent = parent
        self.children = []

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def raw_text(self) -> str:
        parts = []
        for child in self.children:
            parts.append(child.raw_text() if isinstance(child, Node) else child)
        return "".join(parts)

    def text(self) -> str:
        return " ".join(self.raw_text().split())


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in _VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def _tree(response) -> Node:
    parser = _Tree()
    parser.feed(response.content.decode("utf-8"))
    return parser.root


def _q(scope, tag=None, **attrs) -> list:
    """Потомки `scope` по тегу и атрибутам; `_` в имени — дефис; значение `True` — «атрибут есть»."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value)
               for name, value in wanted.items()):
            found.append(node)
    return found


def _q1(scope, tag=None, **attrs):
    found = _q(scope, tag, **attrs)
    assert len(found) == 1, f"ожидали один элемент {tag or ''}{attrs}, нашли {len(found)}"
    return found[0]


# --- модели среза и данные теста ------------------------------------------------------------------------------

def _Chat():
    return support.model("messenger.Chat")


def _ChatMember():
    return support.model("messenger.ChatMember")


def _Message():
    return support.model("messenger.Message")


def _Attachment():
    return support.model("messenger.MessageAttachment")


def _person(value):
    """Сотрудник из `mm.Session` или сам `core.User`."""
    return getattr(value, "user", value)


def _chat_url(chat) -> str:
    return f"/messenger/chats/{chat.pk}/"


def _messages_url(chat) -> str:
    return f"/messenger/chats/{chat.pk}/messages/"


def _create(session, title, members, *, kind="group"):
    """`POST /messenger/chats/`: название и участники; создатель входит сам (FR-646)."""
    data = {"kind": kind, "title": title}
    member_ids = [str(_person(member).pk) for member in members]
    if member_ids:
        data["members"] = member_ids
    return session.client.post("/messenger/chats/", data)


def _chat_from(response):
    """Чат из ответа создания: обычный POST — 302 в `/messenger/chats/<id>/` (CONTRACT-008, 10.2)."""
    assert response.status_code == 302, f"создание: {response.status_code}"
    location = response["Location"]
    prefix = "/messenger/chats/"
    assert location.startswith(prefix) and location.endswith("/"), location
    return _Chat().objects.get(pk=int(location[len(prefix):-1]))


def _group_chat(session, title, members):
    return _chat_from(_create(session, title, members))


def _members(session, chat, *, add=(), remove=()):
    data = {}
    if add:
        data["add"] = [str(_person(person).pk) for person in add]
    if remove:
        data["remove"] = [str(_person(person).pk) for person in remove]
    return session.client.post(f"/messenger/chats/{chat.pk}/members/", data)


def _leave(session, chat, **fields):
    return session.client.post(f"/messenger/chats/{chat.pk}/leave/", fields)


def _delete(session, chat, **fields):
    return session.client.post(f"/messenger/chats/{chat.pk}/delete/", fields)


def _error(response, field, code):
    """Отказ у поля: `[data-error="<поле>"][data-code="<код>"]` (CONTRACT-008, 10.1)."""
    nodes = _q(_tree(response), data_error=field, data_code=code)
    assert nodes, f"нет [data-error=\"{field}\"][data-code=\"{code}\"] в ответе {response.status_code}"
    return nodes[0]


def _confirm_step(response):
    """Второй шаг подтверждения: `[data-messenger-confirm]`, текст и `button[name="confirm"][value="1"]`."""
    node = _q1(_tree(response), data_messenger_confirm=True)
    assert DELETE_CONFIRM in node.text(), node.text()
    buttons = [button for button in _q(node, "button", name="confirm") if button.attrs.get("value") == "1"]
    assert buttons, "нет button[name=confirm][value=1] во втором шаге"
    return node


def _list_html(session) -> str:
    response = session.client.get("/messenger/")
    assert response.status_code == 200, f"/messenger/: {response.status_code}"
    return response.content.decode("utf-8")


def _composition(chat) -> set:
    """Снимок состава в базе: (сотрудник, создатель, вышел)."""
    return {(row.user_id, row.is_creator, row.left_at is not None)
            for row in _ChatMember().objects.filter(chat=chat)}


def _audit(action: str) -> list:
    return list(support.model("core.AuditEvent").objects.filter(action=action).order_by("id"))


# --- создание (FR-646) ----------------------------------------------------------------------------------------

def test_creator_creates_group_with_title_and_two_members():
    """FR-646: создатель создаёт групповой чат с названием (1–200 после среза пробелов) и двумя участниками;
    создатель входит сам, чат виден всем троим, сообщений в новом чате нет."""
    creator = mm.make_user(full_name="Создатель Группы")
    first = mm.make_user(full_name="Первый Участник")
    second = mm.make_user(full_name="Второй Участник")

    response = _create(creator, "  Переезд серверной  ", [first, second])
    chat = _chat_from(response)
    assert response["Location"] == _chat_url(chat)
    assert chat.kind == "group"
    assert chat.title == "Переезд серверной", "название хранится после среза пробелов"
    assert chat.created_by_id == creator.user.pk
    assert chat.last_message_at is None, "у нового чата сообщений нет"
    assert _Message().objects.filter(chat=chat).count() == 0

    rows = list(_ChatMember().objects.filter(chat=chat))
    assert {row.user_id for row in rows} == {creator.user.pk, first.user.pk, second.user.pk}
    assert len(rows) == 3, "создатель входит сам, строк ровно три"
    assert next(row for row in rows if row.user_id == creator.user.pk).is_creator is True
    assert all(row.is_creator is False for row in rows if row.user_id != creator.user.pk)
    assert all(row.left_at is None and row.joined_at is not None for row in rows)

    from apps.messenger.services import members as membership

    assert membership.members(chat) == frozenset(row.user_id for row in rows)
    for session in (creator, first, second):
        conversation = session.client.get(_chat_url(chat))
        assert conversation.status_code == 200
        assert "Переезд серверной" in conversation.content.decode()
        assert "Переезд серверной" in _list_html(session)
        assert membership.is_member(session.user, chat)
        assert chat.pk in {visible.pk for visible in membership.visible_chats(session.user)}


def test_title_empty_and_201_chars_refused_with_reason():
    """FR-646: пустое (в том числе из пробелов) и длиной 201 знак название не принимается с причиной
    `title_range`; 1 и 200 знаков принимаются."""
    creator = mm.make_user()
    member = mm.make_user()

    for title in ("", "   ", "Ж" * 201):
        before = _Chat().objects.count()
        response = _create(creator, title, [member])
        assert response.status_code == 200, f"название {len(title)}: ожидали отказ формы"
        assert _Chat().objects.count() == before, "отказ не создаёт чат"
        assert TITLE_RANGE in _error(response, "title", "title_range").text()

    shortest = _chat_from(_create(creator, "Я", [member]))
    assert shortest.title == "Я"
    longest_title = "Ж" * 200
    longest = _chat_from(_create(creator, longest_title, [member]))
    assert longest.title == longest_title


def test_group_without_members_or_with_dismissed_member_refused():
    """FR-646: без участников — `members`/`no_members`; с уволенным — `members`/`dismissed`; чат не создаётся."""
    creator = mm.make_user()
    member = mm.make_user()

    for payload in ({}, {"members": ""}, {"members": []}):
        before = _Chat().objects.count()
        response = creator.client.post("/messenger/chats/",
                                       {"kind": "group", "title": "Без участников", **payload})
        assert response.status_code == 200
        assert _Chat().objects.count() == before
        assert NO_MEMBERS in _error(response, "members", "no_members").text()

    dismissed = mm.make_user(state="dismissed", full_name="Уволенный Сотрудник")
    before = _Chat().objects.count()
    response = _create(creator, "С уволенным", [member, dismissed])
    assert response.status_code == 200
    assert _Chat().objects.count() == before
    assert DISMISSED in _error(response, "members", "dismissed").text()
    assert not _ChatMember().objects.exists(), "состав отклонённого чата не пишется"


def test_creator_included_and_any_active_employee_may_create():
    """FR-646: создатель входит в состав сам (и не дублируется); создать групповой чат может любой действующий
    сотрудник без особых прав."""
    plain = mm.make_user(roles=(), full_name="Рядовой Сотрудник")
    assert plain.user.roles.count() == 0, "у сотрудника нет ролей"
    colleague = mm.make_user(full_name="Коллега")

    chat = _chat_from(_create(plain, "Чат рядового сотрудника", [colleague, plain]))
    rows = list(_ChatMember().objects.filter(chat=chat))
    assert {row.user_id for row in rows} == {plain.user.pk, colleague.user.pk}
    assert len(rows) == 2, "создатель в списке участников не дублируется"
    assert next(row for row in rows if row.user_id == plain.user.pk).is_creator is True
    assert chat.created_by_id == plain.user.pk
    assert plain.client.get(_chat_url(chat)).status_code == 200

    another = mm.make_user(roles=(), full_name="Другой Рядовой Сотрудник")
    second_chat = _chat_from(_create(another, "Второй чат рядового", [colleague]))
    assert second_chat.created_by_id == another.user.pk


# --- состав (FR-646) ------------------------------------------------------------------------------------------

def test_creator_adds_and_removes_members_while_in_chat():
    """FR-646: создатель добавляет и удаляет участников, пока он в чате; не создатель состав не меняет (403);
    удалённый участник перестаёт видеть чат, его строка сохраняет `left_at`."""
    creator = mm.make_user(full_name="Создатель Состава")
    member = mm.make_user(full_name="Участник Состава")
    newcomer = mm.make_user(full_name="Новый Участник")
    chat = _group_chat(creator, "Состав чата", [member])

    added = _members(creator, chat, add=[newcomer])
    assert added.status_code == 302
    assert added["Location"] == _chat_url(chat)
    row = _ChatMember().objects.get(chat=chat, user=newcomer.user)
    assert row.left_at is None

    from apps.messenger.services import members as membership

    assert membership.members(chat) == frozenset({creator.user.pk, member.user.pk, newcomer.user.pk})
    assert membership.is_member(newcomer.user, chat)

    foreign = mm.make_user(full_name="Посторонний Сотрудник")
    assert _members(member, chat, add=[foreign]).status_code == 403, "состав ведёт только создатель"

    removed = _members(creator, chat, remove=[member])
    assert removed.status_code == 302
    assert removed["Location"] == _chat_url(chat)
    row = _ChatMember().objects.get(chat=chat, user=member.user)
    assert row.left_at is not None, "строка выбывшего остаётся ради истории"
    assert not membership.is_member(member.user, chat)
    assert membership.members(chat) == frozenset({creator.user.pk, newcomer.user.pk})
    assert member.client.get(_chat_url(chat)).status_code == 404


# --- выход (FR-647) -------------------------------------------------------------------------------------------

def test_member_leaves_and_stops_seeing_chat_and_messages():
    """FR-647: участник выходит сам, перестаёт видеть чат и сообщения (404 как у несуществующего), не может
    писать; остальные продолжают беседу."""
    creator = mm.make_user(full_name="Создатель Беседы")
    member = mm.make_user(full_name="Выходящий Участник")
    other = mm.make_user(full_name="Остающийся Участник")
    chat = _group_chat(creator, "Чат для выхода", [member, other])
    text = "Сообщение до выхода участника"
    mm.post(chat, creator, text)
    assert text in member.client.get(_chat_url(chat)).content.decode()

    response = _leave(member, chat)
    assert response.status_code == 302
    assert response["Location"] == "/messenger/"
    row = _ChatMember().objects.get(chat=chat, user=member.user)
    assert row.left_at is not None

    from apps.messenger.services import members as membership

    assert not membership.is_member(member.user, chat)
    assert membership.members(chat) == frozenset({creator.user.pk, other.user.pk})

    page = member.client.get(_chat_url(chat))
    missing = member.client.get(f"/messenger/chats/{MISSING_CHAT}/")
    assert page.status_code == missing.status_code == 404
    assert "Не найдено" in page.content.decode()
    assert support.same_failure(page, missing), "вышедший видит тот же ответ, что на несуществующий чат"
    assert member.client.get(_messages_url(chat)).status_code == 404
    sent = member.client.post(_messages_url(chat), {"text": "Попытка после выхода"})
    assert sent.status_code == 404
    assert not _Message().objects.filter(chat=chat, text="Попытка после выхода").exists()
    assert "Чат для выхода" not in _list_html(member)
    with pytest.raises(Http404):
        membership.get_chat(member.user, chat.pk)

    conversation = other.client.get(_chat_url(chat))
    assert conversation.status_code == 200
    assert text in conversation.content.decode(), "остальные продолжают беседу"
    assert _Chat().objects.filter(pk=chat.pk).exists()


def test_creator_leaves_and_composition_frozen_403():
    """FR-646: после выхода создателя чат остаётся у остальных, а состав больше не меняется: создатель и любой
    участник получают 403 на добавление и удаление."""
    creator = mm.make_user(full_name="Уходящий Создатель")
    first = mm.make_user(full_name="Первый Оставшийся")
    second = mm.make_user(full_name="Второй Оставшийся")
    outsider = mm.make_user(full_name="Внешний Сотрудник")
    chat = _group_chat(creator, "Замороженный состав", [first, second])
    text = "Переписка после выхода создателя"
    mm.post(chat, first, text)

    response = _leave(creator, chat)
    assert response.status_code == 302
    assert _Chat().objects.filter(pk=chat.pk).exists(), "чат остаётся у остальных"
    creator_row = _ChatMember().objects.get(chat=chat, user=creator.user)
    assert creator_row.left_at is not None and creator_row.is_creator is True
    for session in (first, second):
        conversation = session.client.get(_chat_url(chat))
        assert conversation.status_code == 200
        assert text in conversation.content.decode()

    frozen = _composition(chat)
    assert _members(creator, chat, add=[outsider]).status_code == 403, "создатель вышел — состав заморожен"
    assert _members(creator, chat, remove=[first]).status_code == 403
    assert _members(first, chat, add=[outsider]).status_code == 403, "участник состав не меняет"
    assert _members(first, chat, remove=[second]).status_code == 403
    assert _members(second, chat, add=[outsider]).status_code == 403
    assert _composition(chat) == frozen, "ни добавлений, ни выходов"
    assert not _ChatMember().objects.filter(chat=chat, user=outsider.user).exists()


# --- удаление (FR-648, FR-671) --------------------------------------------------------------------------------

def test_creator_deletes_chat_with_confirm_history_gone_and_audit_without_text(
        protected_root, django_capture_on_commit_callbacks):
    """FR-648, FR-671: создатель удаляет чат после подтверждения; исчезают чат, участники, сообщения, вложения
    и файлы с диска; в журнале одна запись `messenger.chat_deleted` без текста переписки."""
    creator = mm.make_user(full_name="Создатель Удаления")
    member = mm.make_user(full_name="Участник Удаления")
    title = "Чат под удаление"
    chat = _group_chat(creator, title, [member])

    attachment = mm.attach(chat, name="схема.png", data=b"file body for delete", write=True, thumb=True)
    stored = support.model("core.StoredFile").objects.get(pk=attachment.file_id)
    from apps.core.services import files as core_files

    stored_path = core_files.attachment_path(stored)
    thumb_path = pathlib.Path(settings.PROTECTED_ROOT) / attachment.thumb
    assert stored_path.exists() and thumb_path.exists()

    first_text = "Первый секрет переписки"
    second_text = "Второй секрет переписки"
    mm.post(chat, creator, first_text)
    mm.post(chat, member, second_text, files=[attachment])

    step = _delete(creator, chat)
    assert step.status_code == 200, "без confirm — второй шаг, чат цел"
    _confirm_step(step)
    assert _Chat().objects.filter(pk=chat.pk).exists()
    assert _Message().objects.filter(chat=chat).count() == 2

    with django_capture_on_commit_callbacks(execute=True):
        done = _delete(creator, chat, confirm="1")
    assert done.status_code == 302
    assert done["Location"] == "/messenger/"
    assert not _Chat().objects.filter(pk=chat.pk).exists()
    assert not _ChatMember().objects.filter(chat_id=chat.pk).exists()
    assert not _Message().objects.filter(chat_id=chat.pk).exists()
    assert not _Attachment().objects.filter(pk=attachment.pk).exists()
    assert not support.model("core.StoredFile").objects.filter(pk=stored.pk).exists()
    assert not stored_path.exists(), "файл стёрт с диска после фиксации"
    assert not thumb_path.exists(), "эскиз стёрт с диска после фиксации"

    events = _audit("messenger.chat_deleted")
    assert len(events) == 1, "удаление создателем — одна запись журнала"
    event = events[0]
    assert event.actor_id == creator.user.pk
    assert event.object_type == "messenger.chat"
    assert event.object_id == str(chat.pk)
    assert event.before == {}
    assert set(event.after) == {"chat_title", "chat_members", "chat_created_at"}
    assert event.after["chat_title"] == title
    assert event.after["chat_members"] == 2
    assert event.after["chat_created_at"]
    dump = json.dumps(event.after, ensure_ascii=False)
    assert first_text not in dump and second_text not in dump, "в журнале нет текста сообщений"
    assert not set(event.after) & {"text", "message", "body", "content"}

    assert title not in _list_html(member)
    assert member.client.get(_chat_url(chat)).status_code == 404


def test_last_member_leaves_with_confirm_deletes_chat_and_history():
    """FR-647: выход последнего участника требует подтверждения; после него чат и история удаляются."""
    creator = mm.make_user(full_name="Последний Создатель")
    member = mm.make_user(full_name="Уходящий Раньше")
    chat = _group_chat(creator, "Последний участник", [member])
    text = "История до выхода последнего"
    mm.post(chat, creator, text)

    assert _leave(member, chat).status_code == 302, "не последний участник выходит без второго шага"
    assert _Chat().objects.filter(pk=chat.pk).exists()

    step = _leave(creator, chat)
    assert step.status_code == 200, "последний участник — второй шаг с подтверждением"
    _confirm_step(step)
    assert _Chat().objects.filter(pk=chat.pk).exists(), "без confirm чат и история целы"
    assert _Message().objects.filter(chat=chat).count() == 1

    done = _leave(creator, chat, confirm="1")
    assert done.status_code == 302
    assert done["Location"] == "/messenger/"
    assert not _Chat().objects.filter(pk=chat.pk).exists()
    assert not _ChatMember().objects.filter(chat_id=chat.pk).exists()
    assert not _Message().objects.filter(chat_id=chat.pk).exists()
    assert creator.client.get(_chat_url(chat)).status_code == 404
    assert "Последний участник" not in _list_html(creator)


def test_non_creator_delete_forbidden_and_missing_confirm_keeps_chat():
    """FR-648: удаление не создателем — 403 при видимом чате и 404 при чужом; без confirm — 200 со вторым шагом,
    чат и история остаются, журнал не пишется."""
    creator = mm.make_user(full_name="Создатель Права")
    member = mm.make_user(full_name="Не Создатель")
    outsider = mm.make_user(full_name="Посторонний Для Удаления")
    title = "Чат без права удаления"
    chat = _group_chat(creator, title, [member])
    text = "История остаётся на месте"
    mm.post(chat, creator, text)

    assert _delete(member, chat, confirm="1").status_code == 403, "чат виден, действие не разрешено"
    assert _Chat().objects.filter(pk=chat.pk).exists()
    assert _Message().objects.filter(chat=chat, text=text).exists()

    hidden = _delete(outsider, chat, confirm="1")
    missing = outsider.client.post(f"/messenger/chats/{MISSING_CHAT}/delete/", {"confirm": "1"})
    assert hidden.status_code == missing.status_code == 404, "чужой чат отвечает как несуществующий"
    assert support.same_failure(hidden, missing)

    step = _delete(creator, chat)
    assert step.status_code == 200, "создатель без confirm получает второй шаг"
    _confirm_step(step)
    assert _Chat().objects.filter(pk=chat.pk).exists()
    assert _Message().objects.filter(chat=chat, text=text).exists()
    assert not _audit("messenger.chat_deleted"), "без подтверждения журнал не пишется"


# --- возврат участника (FR-647, FR-660) -----------------------------------------------------------------------

def test_removed_member_added_again_gets_joined_at_updated(clock):
    """FR-647, FR-660: повторное добавление вышедшего участника снимает `left_at` и обновляет `joined_at`;
    непрочитанное считается после возврата, сообщения пропущенного времени не входят."""
    creator = mm.make_user(full_name="Создатель Возврата")
    member = mm.make_user(full_name="Возвращающийся Участник")
    other = mm.make_user(full_name="Второй Участник Возврата")
    chat = _group_chat(creator, "Возврат участника", [member, other])

    old_joined = timezone.now() - timedelta(days=5)
    _ChatMember().objects.filter(chat=chat, user=member.user).update(joined_at=old_joined)
    mm.post(chat, creator, "До выхода участника", created_at=old_joined + timedelta(days=1))

    assert _members(creator, chat, remove=[member]).status_code == 302
    assert _ChatMember().objects.get(chat=chat, user=member.user).left_at is not None
    mm.post(chat, other, "Пока участник отсутствовал", created_at=timezone.now() - timedelta(hours=1))

    re_added_at = timezone.now()
    assert _members(creator, chat, add=[member]).status_code == 302
    row = _ChatMember().objects.get(chat=chat, user=member.user)
    assert row.left_at is None, "возврат снимает выход"
    assert row.joined_at > old_joined, "вступление обновлено"
    assert row.joined_at >= re_added_at
    assert _ChatMember().objects.filter(chat=chat, user=member.user).count() == 1, "строка одна"

    clock.advance(minutes=1)
    mm.post(chat, creator, "После возврата")
    from apps.messenger.services import unread

    assert unread.counts(member.user).get(chat.pk) == 1, "непрочитанное считается после возврата"

    from apps.messenger.services import members as membership

    assert membership.members(chat) == frozenset({creator.user.pk, member.user.pk, other.user.pk})
    assert member.client.get(_chat_url(chat)).status_code == 200