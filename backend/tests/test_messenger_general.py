"""T-8107: «Общий чат» — данные установки, право писать, выключение и включение (FR-651, FR-652, FR-671).

План: «Виды чатов и создание» — «Общий чат» (одна строка `kind='general'` из миграции `0002`; выключение убирает
чат из списка и поиска, прямой адрес — 404, обычный POST отправки — 404, HTMX — 200 с причиной «Чат отключён»;
история остаётся в базе), «Состав чата» («Общий чат» — действующие сотрудники, строк `ChatMember` нет), «Срок
хранения и ночное задание» — «Настройка» (галочка «Общий чат» на `/settings/messenger/`), «Журнал».
CONTRACT-008: 2.3 (данные установки), 5.1 (`members.members/is_member/can_write/visible_chats/get_chat`), 5.4
(`messenger_settings.get`), 8.1 (`messenger.general_changed` — «включён» / «выключен», без текста переписки),
10.1–10.2 (адреса, поля, ответы 404/200), 12.2–12.3 (зацепки списка, беседы, отказов), 13.1 (`chat_disabled`).

Код среза на уровне модуля не импортируется (правила для всех тестов среза): модели берутся через `support.model`,
службы и поставщик поиска — ленивыми импортами внутри тестов; тексты отказов — литералы раздела 13.1.

Допущения писателя (см. отчёт T-8107): переключение «Общего чата» идёт страницей `/settings/messenger/` — это
единственный названный контрактом (10.2) путь смены настройки; имя службы настройки контракт не задаёт, поэтому тест
его не угадывает. Причина `chat_disabled` ищется по `data-code` и принимает обе формы 10.1 — `[data-error="chat"]`
и `[role=alert]`: 10.2 привязывает отказ к полю `chat`, а 13.1 называет его «общим».
"""
import json
import re
from html.parser import HTMLParser

import pytest
from django.http import Http404

from tests import support
from tests import support_messenger as mm

pytestmark = pytest.mark.django_db

GENERAL = "Общий чат"
CHAT_DISABLED = "Чат отключён"
SETTINGS_URL = "/settings/messenger/"
MISSING = 987654
ENABLED_WORD = "включён"
DISABLED_WORD = "выключен"


# --- разбор разметки (помощник только этого файла, как в test_messenger_group.py) -----------------------------

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

    def text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                if isinstance(child, Node):
                    collect(child)
                else:
                    parts.append(child)

        collect(self)
        return " ".join("".join(parts).split())


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


def _tree(response_or_html) -> Node:
    html = response_or_html if isinstance(response_or_html, str) else response_or_html.content.decode("utf-8")
    parser = _Tree()
    parser.feed(html)
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


# --- модели, адреса и действия теста ---------------------------------------------------------------------------

def _Chat():
    return support.model("messenger.Chat")


def _ChatMember():
    return support.model("messenger.ChatMember")


def _Message():
    return support.model("messenger.Message")


def _Settings():
    return support.model("messenger.MessengerSettings")


def _chat_url(chat) -> str:
    return f"/messenger/chats/{chat.pk}/"


def _messages_url(chat) -> str:
    return f"/messenger/chats/{chat.pk}/messages/"


def _general():
    """Единственная строка «Общего чата» (помощник среза, `get_or_create(kind="general")`)."""
    return mm.general()


def _toggle(admin, *, enabled: bool):
    """Включение/выключение «Общего чата» страницей `/settings/messenger/` (CONTRACT-008, 10.2).

    Срок хранения не меняется, поэтому второй шаг `confirm` не нужен; поле-галочка `general_chat_enabled`
    уходит только при включении (снятая галочка браузером не отправляется)."""
    from apps.messenger.services import messenger_settings

    row = messenger_settings.get()
    data = {"retention_years": str(row.retention_years)}
    if enabled:
        data["general_chat_enabled"] = "on"
    response = admin.client.post(SETTINGS_URL, data)
    assert response.status_code == 302, f"настройки мессенджера: {response.status_code}"
    assert response["Location"] == SETTINGS_URL
    row.refresh_from_db()
    assert row.general_chat_enabled is enabled, "галочка «Общий чат» не сохранена"
    return row


def _send(session, chat, text: str, *, htmx: bool = False):
    """`POST /messenger/chats/<id>/messages/` обычным запросом или с `HX-Request: true` (10.1–10.2)."""
    if htmx:
        return session.client.post(_messages_url(chat), {"text": text}, **support.HX)
    return session.client.post(_messages_url(chat), {"text": text})


def _chat_rows(html: str) -> set:
    """Номера чатов списка — зацепка строки `[data-chat-id="<id>"]` (раздел 12.2)."""
    return {int(found) for found in re.findall(r'data-chat-id="(\d+)"', html)}


def _list_html(session) -> str:
    response = session.client.get("/messenger/")
    assert response.status_code == 200, f"/messenger/: {response.status_code}"
    return response.content.decode("utf-8")


def _list_node(html: str) -> Node:
    """Контейнер списка `#messenger-list` (12.2) — без заголовков и вкладок страницы."""
    return _q1(_tree(html), None, id="messenger-list")


def _refusal(response, field: str, code: str) -> Node:
    """Отказ по коду: `[data-error="<поле>"][data-code]` либо общий `[role=alert][data-code]` (10.1, 13.1)."""
    found = [node for node in _tree(response).walk() if node.attrs.get("data-code") == code]
    assert found, f"нет data-code=\"{code}\" в ответе {response.status_code}"
    assert len(found) == 1, f"data-code=\"{code}\" встречается {len(found)} раз"
    node = found[0]
    marked = node.attrs.get("data-error") == field or node.attrs.get("role") == "alert"
    assert marked, f"отказ \"{code}\" не у поля \"{field}\" и не общий: {node.attrs}"
    return node


def _journal(action: str = "messenger.general_changed") -> list:
    return list(support.model("core.AuditEvent").objects.filter(action=action).order_by("id"))


def _message_texts(chat) -> list:
    return list(_Message().objects.filter(chat=chat).order_by("created_at", "id")
                .values_list("text", flat=True))


def _messenger_provider():
    """Поставщик группы «Мессенджер» из точки `search_providers` (раздел 9)."""
    from apps.core import extensions

    found = [provider for factory in extensions.registered("search_providers")
             for provider in factory() if provider.key == "messenger"]
    assert len(found) == 1, f"поставщик «Мессенджер» зарегистрирован не один раз: {len(found)}"
    return found[0]


# --- данные установки и первое сообщение (FR-651) --------------------------------------------------------------

def test_seed_creates_single_general_chat_and_employee_may_write():
    """FR-651: данные установки дают ровно один «Общий чат» (название «Общий чат», создателя нет, строк участников
    нет), повторный запуск ничего не дублирует; действующий сотрудник пишет в него обычным POST, сообщение
    сохраняется с автором и видно в беседе и в списке."""
    mm.run_seed(using="default")
    mm.run_seed(using="default")

    chat = _general()
    assert chat.kind == "general"
    assert chat.title == GENERAL
    assert chat.created_by_id is None, "у «Общего чата» нет создателя"
    assert _Chat().objects.filter(kind="general").count() == 1, "строка «Общего чата» одна"
    assert not _ChatMember().objects.filter(chat=chat).exists(), "строк участников у «Общего чата» нет"

    employee = mm.make_user(full_name="Пишущий Сотрудник")
    text = "Первое сообщение в общем чате"
    response = _send(employee, chat, text)
    assert response.status_code == 302, f"отправка в «Общий чат»: {response.status_code}"
    assert response["Location"] == _chat_url(chat)

    message = _Message().objects.get(chat=chat, text=text)
    assert message.author_id == employee.user.pk
    assert message.is_system is False
    assert message.deleted_at is None
    assert text in employee.client.get(_chat_url(chat)).content.decode()
    assert chat.pk in _chat_rows(employee.client.get("/messenger/").content.decode())
    assert not _ChatMember().objects.filter(chat=chat).exists(), "сообщение не создаёт строк участников"

    from apps.messenger.services import members as membership

    assert membership.is_member(employee.user, chat) is True
    assert membership.can_write(employee.user, chat) is True


# --- выключение (FR-651) --------------------------------------------------------------------------------------

def test_disabled_general_chat_absent_from_list_and_search_and_404_on_direct_address():
    """FR-651: выключенный «Общий чат» исчезает из списка и из сквозного поиска, прямой адрес и `get_chat` дают
    тот же 404, что несуществующий чат, `can_write` ложь; история остаётся в базе."""
    chat = _general()
    employee = mm.make_user(full_name="Сотрудник Списка")
    text = "Квазар остаётся в истории"
    mm.post(chat, employee, text)

    from apps.search.parse import parse

    parsed = parse("Квазар")
    provider = _messenger_provider()
    before = provider.search(employee.user, parsed, 20, 0)
    assert len(before) == 1, f"включённый «Общий чат» не найден: {len(before)} строк"
    assert f"/messenger/chats/{chat.pk}/#m" in before[0].url
    assert GENERAL in before[0].title
    assert chat.pk in _chat_rows(_list_html(employee)), "включённый «Общий чат» есть в списке"

    _toggle(mm.as_admin(), enabled=False)

    html = _list_html(employee)
    assert chat.pk not in _chat_rows(html), "выключенный «Общий чат» остался в списке"
    assert GENERAL not in html, "названия выключенного чата нет на странице списка"

    assert provider.search(employee.user, parsed, 20, 0) == [], "выключенный чат не попадает в поиск"
    assert provider.count(employee.user, parsed) == (0, False)

    hidden = employee.client.get(_chat_url(chat))
    missing = employee.client.get(f"/messenger/chats/{MISSING}/")
    assert hidden.status_code == 404
    assert "Не найдено" in hidden.content.decode()
    assert support.same_failure(hidden, missing), "прямой адрес отвечает как несуществующий чат"

    from apps.messenger.services import members as membership

    assert chat.pk not in {getattr(item, "pk", item) for item in membership.visible_chats(employee.user)}
    assert membership.can_write(employee.user, chat) is False
    with pytest.raises(Http404):
        membership.get_chat(employee.user, chat.pk)
    assert _Message().objects.filter(chat=chat, text=text).exists(), "история осталась в базе"


def test_disabled_general_chat_refuses_send_plain_404_and_htmx_reason():
    """FR-651, FR-652: выключенный «Общий чат» не принимает сообщение — обычный POST отвечает 404, как на
    несуществующий чат, HTMX получает 200 с фрагментом и причиной `chat_disabled` («Чат отключён»); сообщение не
    записывается ни в одном случае."""
    chat = _general()
    employee = mm.make_user(full_name="Пишущий В Выключенный")
    _toggle(mm.as_admin(), enabled=False)

    text = "Сообщение в выключенный чат"
    plain = _send(employee, chat, text)
    missing = employee.client.post(f"/messenger/chats/{MISSING}/messages/", {"text": text})
    assert plain.status_code == 404, "обычный POST отправки — 404"
    assert support.same_failure(plain, missing), "обычный POST отвечает как на несуществующий чат"
    assert not _Message().objects.filter(chat=chat, text=text).exists(), "отказ не пишет сообщение"

    htmx = _send(employee, chat, text, htmx=True)
    assert htmx.status_code == 200, f"HTMX-POST: {htmx.status_code}"
    body = htmx.content.decode("utf-8")
    assert "<html" not in body.lower(), "HTMX получает фрагмент без страницы"
    node = _refusal(htmx, "chat", "chat_disabled")
    assert CHAT_DISABLED in node.text(), node.text()
    assert not _Message().objects.filter(chat=chat, text=text).exists(), "HTMX-отказ не пишет сообщение"
    assert _Settings().objects.get(pk=1).general_chat_enabled is False, "отказ не включает чат обратно"


# --- включение и журнал (FR-651, FR-671) ----------------------------------------------------------------------

def test_enable_again_restores_history_and_writes_two_audit_records():
    """FR-651, FR-671: выключение и включение страницей настроек пишут две записи `messenger.general_changed`
    («включён» → «выключен» и обратно, без текста переписки); после включения история возвращается в беседу и
    список, отправка снова работает."""
    chat = _general()
    author = mm.make_user(full_name="Автор Истории")
    first_text = "История до выключения"
    second_text = "Второе сообщение истории"
    mm.post(chat, author, first_text)
    mm.post(chat, author, second_text)
    admin = mm.as_admin()

    _toggle(admin, enabled=False)
    off_events = _journal()
    assert len(off_events) == 1, "выключение — одна запись журнала"
    assert chat.pk not in _chat_rows(_list_html(author)), "выключенный чат не в списке"
    assert author.client.get(_chat_url(chat)).status_code == 404
    assert _message_texts(chat) == [first_text, second_text], "история осталась в базе"

    _toggle(admin, enabled=True)
    events = _journal()
    assert len(events) == 2, "обе смены — в журнал"

    off, on = events
    for event in events:
        assert event.actor_id == admin.user.pk, "автор записи — администратор портала"
        assert event.object_type == "messenger.settings"
    assert ENABLED_WORD in off.before.values() and DISABLED_WORD in off.after.values(), (
        f"запись выключения: было {off.before}, стало {off.after}")
    assert DISABLED_WORD in on.before.values() and ENABLED_WORD in on.after.values(), (
        f"запись включения: было {on.before}, стало {on.after}")
    for event in events:
        dump = json.dumps([event.before, event.after], ensure_ascii=False)
        assert first_text not in dump and second_text not in dump, "в журнале нет текста переписки"

    row = _Settings().objects.get(pk=1)
    assert row.general_chat_enabled is True
    assert row.updated_by_id == admin.user.pk
    assert row.updated_at is not None

    conversation = author.client.get(_chat_url(chat))
    assert conversation.status_code == 200, "после включения беседа снова открывается"
    body = conversation.content.decode()
    assert first_text in body and second_text in body, "история вернулась"
    assert chat.pk in _chat_rows(_list_html(author)), "чат вернулся в список"

    new_text = "Сообщение после включения"
    assert _send(author, chat, new_text).status_code == 302
    assert _Message().objects.filter(chat=chat, text=new_text, author_id=author.user.pk).exists()


# --- право писать (FR-651) ------------------------------------------------------------------------------------

def test_any_active_employee_writes_to_general_chat():
    """FR-651: писать в «Общий чат» может любой действующий сотрудник — с ролью и без ролей; уволенному
    `can_write` ложь. Каждое сообщение сохраняется со своим автором, видно остальным, а строк `ChatMember` у
    «Общего чата» по-прежнему нет."""
    chat = _general()
    admin = mm.as_admin(full_name="Администратор Общего")
    plain = mm.make_user(roles=(), full_name="Рядовой Общего")
    dismissed = mm.make_user(state="dismissed", full_name="Уволенный Без Доступа")
    assert plain.user.roles.count() == 0, "у рядового сотрудника нет ролей"

    from apps.messenger.services import members as membership

    assert membership.can_write(admin.user, chat) is True
    assert membership.can_write(plain.user, chat) is True
    assert membership.can_write(dismissed.user, chat) is False, "уволенный в «Общий чат» не пишет"

    texts = ((admin, "Сообщение администратора в общем"), (plain, "Ответ рядового сотрудника"))
    for session, text in texts:
        response = _send(session, chat, text)
        assert response.status_code == 302, f"{text}: {response.status_code}"
        assert response["Location"] == _chat_url(chat)
        assert _Message().objects.filter(chat=chat, text=text, author_id=session.user.pk).exists()

    for session, _ in texts:
        body = session.client.get(_chat_url(chat)).content.decode()
        for _, text in texts:
            assert text in body, f"«{text}» не видно сотруднику {session.user.pk}"

    assert membership.members(chat) >= frozenset({admin.user.pk, plain.user.pk})
    assert dismissed.user.pk not in membership.members(chat), "уволенный не входит в состав «Общего чата»"
    assert not _ChatMember().objects.filter(chat=chat).exists(), "состав «Общего чата» не материализуется"


def test_general_chat_visible_to_employee_without_roles():
    """FR-651: сотрудник без ролей видит «Общий чат» в списке и беседе (вид чата — `general`), читает прежнюю
    историю и пишет в него."""
    chat = _general()
    author = mm.make_user(full_name="Автор Перед Новичком")
    history = "История видна всем действующим"
    mm.post(chat, author, history)

    newcomer = mm.make_user(roles=(), full_name="Сотрудник Без Ролей")
    assert newcomer.user.roles.count() == 0, "у сотрудника нет ролей"

    page = _list_html(newcomer)
    assert chat.pk in _chat_rows(page), "«Общий чат» есть в списке у сотрудника без ролей"
    assert GENERAL in _list_node(page).text()

    conversation = newcomer.client.get(_chat_url(chat))
    assert conversation.status_code == 200, f"беседа «Общего чата»: {conversation.status_code}"
    kinds = [node.attrs.get("data-chat-kind") for node in _q(_tree(conversation), data_chat_kind=True)]
    assert "general" in kinds, f"вид чата у заголовка беседы: {kinds}"
    assert history in conversation.content.decode(), "прежняя история видна"

    from apps.messenger.services import members as membership

    assert chat.pk in {getattr(item, "pk", item) for item in membership.visible_chats(newcomer.user)}
    assert membership.is_member(newcomer.user, chat) is True

    text = "Пишет сотрудник без ролей"
    assert _send(newcomer, chat, text).status_code == 302
    assert text in newcomer.client.get(_chat_url(chat)).content.decode()
    assert _Message().objects.filter(chat=chat, text=text, author_id=newcomer.user.pk).exists()