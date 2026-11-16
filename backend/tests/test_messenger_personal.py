"""T-8104: личный диалог и «Написать» (FR-643, FR-644, FR-645, FR-660).

Один диалог на пару сотрудников и создание сообщением, «Написать» из карточки и из мессенджера, гонка двух
созданий, диалог с уволенным (не создаётся; существующий — только чтение), `/messenger/?to=` без записи в базу,
список с именем собеседника, превью, временем и порядком, первое непрочитанное, поиск людей до 20 действующих и
кнопка в карточке сотрудника.

Источники: CONTRACT-008 § 5.1 (`chats.personal`, `members.can_write`), § 10.2 (адреса и поля), § 12.1–12.3,
12.6 (зацепки), § 13.1 (`dismissed`); PLAN-008 «Виды чатов и создание», «Список чатов и порядок», «Написать из
карточки сотрудника», «Прочтение и счётчики»; TASKS-008, решения 1, 2, 6, 7, 10.

Код среза на уровне модуля не импортируется (CONTRACT-008, «Правила для всех тестов среза»): модели берутся
через `support.model`, службы — внутри функций теста.

Допущения писателя (см. отчёт T-8104): форма страницы `?to=` читается из разметки (адрес отправки, скрытые
поля, `textarea[name="text"]`) — контракт называет только зацепку `[data-messenger-page="write"]` и форму
`#messenger-form` (12.1, 12.3), а план говорит «диалог создаётся при первом сообщении»; поэтому поля берутся из
самой формы, а не угадываются. Отправка в существующий диалог с уволенным собеседником проверяется как 403
(чат виден, действие не разрешено — 10.1), потому что отдельного поля отказа в 10.2 нет.
"""
from datetime import datetime, timedelta
from html.parser import HTMLParser

import pytest

from tests import factories, support
from tests import support_messenger as messenger

pytestmark = pytest.mark.django_db

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
DISMISSED_PEER = "Уволенный Адресат"
DISMISSED_TEXT = "Сотрудник уволен: написать нельзя"


# --- разбор разметки (помощник только этого файла; образец — test_lists_links.py) -------------------------------

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


def _tree(response) -> _Node:
    parser = _Parser()
    parser.feed(response.content.decode("utf-8", "replace"))
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


def _form_with_text(root):
    """Первая форма с `textarea[name="text"]` (12.3) — ввод сообщения на странице `?to=` или в беседе."""
    for form in _q(root, "form"):
        area = _q(form, "textarea", name="text")
        if area:
            return form
    return None


def _controls(form) -> dict:
    """Поля формы как их отправил бы браузер: снятые галочки и переключатели не входят."""
    data = {}
    for control in _q(form, "input"):
        name = control.attrs.get("name")
        if not name:
            continue
        kind = control.attrs.get("type", "text").lower()
        if kind in ("checkbox", "radio") and "checked" not in control.attrs:
            continue
        data[name] = control.attrs.get("value", "")
    for select in _q(form, "select"):
        name = select.attrs.get("name")
        if not name:
            continue
        chosen = [option for option in _q(select, "option") if "selected" in option.attrs]
        if chosen:
            data[name] = chosen[0].attrs.get("value", "")
    return data


def _send_from_write_page(session, peer, text: str):
    """Сообщение со страницы «Написать» (`/messenger/?to=<id>`, план): адрес и поля — из самой формы."""
    page = session.client.get("/messenger/", {"to": peer.user.pk})
    assert page.status_code == 200, f"страница ?to=: {page.status_code}"
    form = _form_with_text(_tree(page))
    assert form is not None, (
        "на /messenger/?to= нет формы с textarea[name=\"text\"] — поле ввода с адресатом (CONTRACT-008 12.3, "
        "PLAN-008 «Написать из карточки сотрудника»)")
    data = _controls(form)
    data["text"] = text
    action = form.attrs.get("action") or form.attrs.get("hx-post")
    assert action and action.startswith("/messenger/"), f"у формы ?to= нет адреса отправки: {action!r}"
    return session.client.post(action, data)


def _row(root, chat_id: int):
    rows = _q(root, data_chat_id=str(chat_id))
    assert len(rows) == 1, f"строк списка с data-chat-id={chat_id}: {len(rows)}"
    return rows[0]


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _pair_key(first, second) -> str:
    low, high = sorted((first.pk, second.pk))
    return f"{low}:{high}"


def _staff_viewer(full_name: str = "Смотрящий Карточку"):
    """Действующий сотрудник с правом `staff.view`: карточка `/staff/<id>/` без него — 403."""
    return messenger.make_user(roles=[factories.make_role(permissions=("staff.view",))], full_name=full_name)


# --- диалог: создание, один на пару, «Написать» -----------------------------------------------------------------

def test_first_message_creates_single_dialog_and_second_goes_there():
    """FR-645: первое сообщение со страницы «Написать» создаёт один личный диалог, второе идёт в него же.

    `chats.personal` берёт `pair_key` и `get_or_create` (CONTRACT-008 5.1), поэтому явное создание из мессенджера
    (`POST /messenger/chats/` с `kind=personal&user=<id>`) возвращает тот же чат."""
    Chat, Message = support.model("messenger.Chat"), support.model("messenger.Message")
    author = messenger.make_user(full_name="Первый Автор")
    peer = messenger.make_user(full_name="Второй Собеседник")
    pair = _pair_key(author.user, peer.user)

    answer = _send_from_write_page(author, peer, "Первое сообщение")
    assert answer.status_code == 302, f"первое сообщение: {answer.status_code}"
    rows = Chat.objects.filter(kind="personal", pair_key=pair)
    assert rows.count() == 1, f"диалогов пары после первого сообщения: {rows.count()}"
    chat = rows.get()
    assert answer["Location"] == f"/messenger/chats/{chat.pk}/", answer["Location"]
    assert list(Message.objects.filter(chat=chat).values_list("text", flat=True)) == ["Первое сообщение"]

    again = _send_from_write_page(author, peer, "Второе сообщение")
    assert again.status_code == 302, f"второе сообщение: {again.status_code}"
    assert again["Location"] == f"/messenger/chats/{chat.pk}/", again["Location"]
    assert Chat.objects.filter(kind="personal", pair_key=pair).count() == 1
    assert list(Message.objects.filter(chat=chat).order_by("id").values_list("text", flat=True)) == [
        "Первое сообщение", "Второе сообщение"]

    explicit = author.client.post("/messenger/chats/", {"kind": "personal", "user": peer.user.pk})
    assert explicit.status_code == 302, f"создание из мессенджера: {explicit.status_code}"
    assert explicit["Location"] == f"/messenger/chats/{chat.pk}/", explicit["Location"]
    assert Chat.objects.filter(kind="personal", pair_key=pair).count() == 1
    assert Message.objects.filter(chat=chat).count() == 2


def test_dialog_from_card_and_from_messenger_is_same_chat():
    """FR-645: «Написать» из карточки сотрудника и из поиска людей открывают один и тот же диалог.

    Кнопка карточки ведёт на `/messenger/?to=<id>` (CONTRACT-008 12.6, 3.4 `card_sections`), строка поиска людей —
    туда же (10.2); первое сообщение идёт из карточки, второе — из мессенджера, строка `Chat` остаётся одна."""
    Chat, Message = support.model("messenger.Chat"), support.model("messenger.Message")
    viewer = _staff_viewer("Пишущий Из Карточки")
    peer = messenger.make_user(full_name="Собеседник Из Карточки")
    pair = _pair_key(viewer.user, peer.user)
    target = f"/messenger/?to={peer.user.pk}"

    card = viewer.client.get(f"/staff/{peer.user.pk}/")
    assert card.status_code == 200, f"карточка сотрудника: {card.status_code}"
    marks = _q(_tree(card), data_messenger_card_write=True)
    assert marks, "в карточке коллеги нет кнопки «Написать»"
    hrefs = [mark.attrs.get("href") for mark in marks if mark.attrs.get("href")]
    hrefs += [link.attrs.get("href", "") for mark in marks for link in _q(mark, "a")]
    assert target in hrefs, f"ссылки кнопки «Написать»: {hrefs}"

    first = _send_from_write_page(viewer, peer, "Из карточки")
    assert first.status_code == 302, f"сообщение из карточки: {first.status_code}"
    chats = Chat.objects.filter(kind="personal", pair_key=pair)
    assert chats.count() == 1, f"диалогов пары: {chats.count()}"
    chat = chats.get()

    people = viewer.client.get("/messenger/people/", {"q": "Собеседник Из Карточки"})
    assert people.status_code == 200, f"поиск людей: {people.status_code}"
    persons = _q(_tree(people), data_person_id=str(peer.user.pk))
    assert len(persons) == 1, f"строк поиска с data-person-id={peer.user.pk}: {len(persons)}"
    row_hrefs = [persons[0].attrs.get("href", "")]
    row_hrefs += [link.attrs.get("href", "") for link in persons[0].walk() if link.attrs.get("href")]
    assert target in row_hrefs, f"действие «Написать» в поиске людей ведёт на {row_hrefs}"

    second = _send_from_write_page(viewer, peer, "Из мессенджера")
    assert second.status_code == 302, f"сообщение из мессенджера: {second.status_code}"
    assert second["Location"] == f"/messenger/chats/{chat.pk}/", second["Location"]
    assert Chat.objects.filter(kind="personal", pair_key=pair).count() == 1
    assert list(Message.objects.filter(chat=chat).order_by("id").values_list("text", flat=True)) == [
        "Из карточки", "Из мессенджера"]


def test_race_of_two_creations_leaves_one_row(monkeypatch):
    """FR-645: при гонке двух созданий личного диалога остаётся одна строка.

    Гонка без потоков (CONTRACT-008, «Правила для всех тестов среза»): первый создатель уже зафиксировал диалог,
    а `Chat.objects.get_or_create` второго поднимает `IntegrityError`, как при одновременной вставке; служба
    перехватывает ошибку и читает строку заново (5.1)."""
    from django.db import IntegrityError

    from apps.messenger.services import chats

    Chat, ChatMember = support.model("messenger.Chat"), support.model("messenger.ChatMember")
    first = messenger.make_user(full_name="Первый Участник Гонки")
    second = messenger.make_user(full_name="Второй Участник Гонки")
    pair = _pair_key(first.user, second.user)

    winner = messenger.personal(first, second)
    assert Chat.objects.filter(kind="personal", pair_key=pair).count() == 1

    manager = Chat.objects
    real = manager.get_or_create
    calls = []

    def racy(*args, **kwargs):
        """Строку уже вставил параллельный запрос — `get_or_create` второго получает нарушение уникальности."""
        calls.append(1)
        if len(calls) == 1:
            raise IntegrityError("duplicate key value violates unique constraint (подмена гонки)")
        return real(*args, **kwargs)

    monkeypatch.setattr(manager, "get_or_create", racy)

    chat = chats.personal(first.user, second.user)
    assert calls, "служба не позвала get_or_create личного диалога"
    rows = Chat.objects.filter(kind="personal", pair_key=pair)
    assert rows.count() == 1, f"строк диалога после гонки: {rows.count()}"
    assert chat.pk == winner.pk == rows.get().pk

    same = chats.personal(first.user, second.user)
    assert same.pk == winner.pk
    assert Chat.objects.filter(kind="personal", pair_key=pair).count() == 1
    members = ChatMember.objects.filter(chat=winner)
    assert members.count() == 2, f"участников диалога: {members.count()}"
    assert set(members.values_list("user_id", flat=True)) == {first.user.pk, second.user.pk}
    assert not members.exclude(left_at=None).exists(), "участники созданного диалога не вышли"


# --- диалог с уволенным, страница «?to», список -----------------------------------------------------------------

def test_dialog_with_dismissed_not_created_and_existing_send_refused():
    """FR-645, FR-643: с уволенным диалог не создаётся; существующий виден, история читается, отправка — 403."""
    Chat, Message = support.model("messenger.Chat"), support.model("messenger.Message")
    author = messenger.make_user(full_name="Пишущий Сотрудник")
    gone = messenger.make_user(state="dismissed", full_name=DISMISSED_PEER)

    refused = author.client.post("/messenger/chats/", {"kind": "personal", "user": gone.user.pk})
    assert refused.status_code == 200, f"отказ создания диалога: {refused.status_code}"
    root = _tree(refused)
    assert _q(root, data_error="user", data_code="dismissed"), "нет [data-error=\"user\"][data-code=\"dismissed\"]"
    assert DISMISSED_TEXT in refused.content.decode("utf-8"), "нет текста отказа «Сотрудник уволен: написать нельзя»"
    assert not Chat.objects.filter(kind="personal", pair_key=_pair_key(author.user, gone.user)).exists()

    from apps.messenger.services import members

    peer = messenger.make_user(full_name="Позже Уволенный Собеседник")
    chat = messenger.personal(author, peer)
    messenger.post(chat, author, "История до увольнения")
    support.model("core.User").objects.filter(pk=peer.user.pk).update(state="dismissed")
    peer.user.refresh_from_db()

    assert members.can_write(author.user, chat) is False, "отправка в диалог с уволенным разрешена"

    page = author.client.get(f"/messenger/chats/{chat.pk}/")
    assert page.status_code == 200, f"диалог с уволенным: {page.status_code}"
    assert "История до увольнения" in page.content.decode("utf-8"), "история диалога не видна"

    before = Message.objects.filter(chat=chat).count()
    send = author.client.post(f"/messenger/chats/{chat.pk}/messages/", {"text": "После увольнения"})
    assert send.status_code == 403, f"отправка в диалог с уволенным: {send.status_code}"
    assert Message.objects.filter(chat=chat).count() == before, "сообщение в диалог с уволенным записалось"


def test_opening_to_page_creates_no_empty_dialog():
    """FR-645: `GET /messenger/?to=<id>` ничего не пишет в базу — ни для действующего, ни для уволенного.

    Диалог создаётся при первом сообщении (план), поэтому открытие страницы с адресатом не оставляет пустых чатов."""
    Chat, ChatMember, Message = (support.model("messenger.Chat"), support.model("messenger.ChatMember"),
                                 support.model("messenger.Message"))
    viewer = messenger.make_user(full_name="Открывающий Страницу")
    peer = messenger.make_user(full_name="Будущий Собеседник")
    gone = messenger.make_user(state="dismissed", full_name=DISMISSED_PEER)

    for person_id in (peer.user.pk, peer.user.pk, gone.user.pk, 10 ** 9):
        answer = viewer.client.get("/messenger/", {"to": person_id})
        assert answer.status_code == 200, f"страница ?to={person_id}: {answer.status_code}"

    assert not Chat.objects.filter(kind="personal").exists(), "страница ?to= создала пустой личный диалог"
    assert not Chat.objects.filter(kind="personal", pair_key__in=[
        _pair_key(viewer.user, peer.user), _pair_key(viewer.user, gone.user)]).exists()
    assert not ChatMember.objects.filter(user__in=[viewer.user, peer.user]).exists(), "появились участники чата"
    assert not Message.objects.filter(chat__kind="personal").exists(), "появились сообщения"

    page = viewer.client.get("/messenger/", {"to": peer.user.pk})
    assert page.status_code == 200
    assert _q(_tree(page), data_messenger_page="write"), (
        "страница ?to= не помечена [data-messenger-page=\"write\"] (CONTRACT-008 12.1)")
    assert not Chat.objects.filter(kind="personal").exists(), "страница ?to= с действующим адресатом создала чат"


def test_list_shows_peer_name_preview_time_and_order(clock):
    """FR-644: список — имя собеседника, превью последнего сообщения, время по Москве и порядок по последнему.

    Порядок — `COALESCE(last_message_at, created_at) DESC, id DESC` (план «Список чатов и порядок»); чат без
    сообщений стоит последним. Общий чат установки удалён, чтобы порядок задавали только три диалога теста."""
    Chat = support.model("messenger.Chat")
    viewer = messenger.make_user(full_name="Читающий Список")
    peer_b = messenger.make_user(full_name="Борис Собеседник")
    peer_c = messenger.make_user(full_name="Виктор Собеседник")
    peer_d = messenger.make_user(full_name="Дмитрий Без Сообщений")
    Chat.objects.filter(kind="general").delete()
    assert not Chat.objects.filter(kind="general").exists()

    base = messenger.moscow(2026, 3, 10, 15, 0)
    clock.set(base - timedelta(hours=3))
    chat_b = messenger.personal(viewer, peer_b)
    clock.set(base - timedelta(hours=2, minutes=50))
    chat_c = messenger.personal(viewer, peer_c)
    clock.set(base - timedelta(hours=2, minutes=30))
    chat_d = messenger.personal(viewer, peer_d)
    at_b, at_c = base - timedelta(hours=2), base - timedelta(hours=1)
    clock.set(base)
    first = messenger.post(chat_b, viewer, "Превью Бориса", created_at=at_b)
    messenger.post(chat_c, viewer, "Превью Виктора", created_at=at_c)

    page = viewer.client.get("/messenger/")
    assert page.status_code == 200, f"список чатов: {page.status_code}"
    root = _tree(page)
    lists = _q(root, id="messenger-list")
    assert len(lists) == 1, "нет #messenger-list (CONTRACT-008 12.2)"
    ids = [int(row.attrs["data-chat-id"]) for row in _q(lists[0], data_chat_id=True)]
    assert ids == [chat_c.pk, chat_b.pk, chat_d.pk], f"порядок чатов: {ids}"

    row = _row(root, chat_b.pk)
    body = row.text()
    assert peer_b.user.full_name in body, f"в строке нет имени собеседника: {body!r}"
    preview = _q(row, id=f"chat-{chat_b.pk}-preview")
    assert len(preview) == 1, "нет #chat-<id>-preview (CONTRACT-008 12.2)"
    assert preview[0].text() == "Превью Бориса", preview[0].text()

    stamps = _q(row, "time", data_at=True)
    assert len(stamps) == 1, "нет time[data-at] в строке списка (CONTRACT-008 12.1)"
    assert _instant(stamps[0].attrs["datetime"]) == first.created_at, stamps[0].attrs["datetime"]
    assert stamps[0].text() == messenger.moscow_text(at_b), stamps[0].text()

    row_c = _row(root, chat_c.pk)
    assert peer_c.user.full_name in row_c.text(), row_c.text()
    assert _q(row_c, id=f"chat-{chat_c.pk}-preview")[0].text() == "Превью Виктора"


def test_first_message_in_new_dialog_gives_one_unread():
    """FR-660: первое сообщение в новом диалоге даёт собеседнику одно непрочитанное, автору — ноль."""
    from apps.messenger.services import unread

    Chat = support.model("messenger.Chat")
    author = messenger.make_user(full_name="Автор Первого")
    peer = messenger.make_user(full_name="Получатель Первого")
    answer = _send_from_write_page(author, peer, "Первое в диалоге")
    assert answer.status_code == 302, f"первое сообщение: {answer.status_code}"
    chats = Chat.objects.filter(kind="personal", pair_key=_pair_key(author.user, peer.user))
    assert chats.count() == 1, f"диалогов пары: {chats.count()}"
    chat = chats.get()

    counts = unread.counts(peer.user)
    assert counts.get(chat.pk) == 1, f"непрочитанных у собеседника: {counts}"
    assert unread.total(peer.user) == 1, f"общее число у собеседника: {unread.total(peer.user)}"
    assert unread.counts(author.user).get(chat.pk, 0) == 0, "своё сообщение дало автору непрочитанное"

    root = _tree(peer.client.get("/messenger/"))
    tag = _q(root, id=f"chat-{chat.pk}-unread")
    assert len(tag) == 1, "нет #chat-<id>-unread у чата (CONTRACT-008 12.2)"
    assert tag[0].attrs.get("data-count") == "1", tag[0].attrs.get("data-count")
    assert tag[0].text() == "1", tag[0].text()
    badge = _q(root, id="menu-badge-messenger")
    assert len(badge) == 1, "нет #menu-badge-messenger (CONTRACT-008 12.2)"
    assert badge[0].attrs.get("data-count") == "1", badge[0].attrs.get("data-count")

    own = _q(_tree(author.client.get("/messenger/")), id=f"chat-{chat.pk}-unread")
    assert len(own) == 1, "у автора нет узла числа чата"
    assert own[0].attrs.get("data-count") == "0", own[0].attrs.get("data-count")
    assert "d-none" in own[0].attrs.get("class", "").split(), "нулевое число не скрыто (решение К18)"


# --- поиск людей и кнопка «Написать» в карточке ------------------------------------------------------------------

def test_people_search_returns_20_active_and_hides_dismissed():
    """FR-645: `/messenger/people/` — до 20 действующих сотрудников с действием «Написать», уволенных нет."""
    viewer = messenger.make_user(full_name="Ищущий Сотрудник")
    active = [messenger.make_user(full_name=f"Изыскание {number:02d} Действующий").user for number in range(22)]
    dismissed = [messenger.make_user(state="dismissed", full_name=f"Изыскание {number:02d} Уволенный").user
                 for number in range(2)]
    stranger = messenger.make_user(full_name="Другой Профиль").user
    active_ids = {person.pk for person in active}

    found = viewer.client.get("/messenger/people/", {"q": "Изыскание"})
    assert found.status_code == 200, f"поиск людей: {found.status_code}"
    rows = _q(_tree(found), data_person_id=True)
    assert len(rows) == 20, f"строк поиска: {len(rows)}"
    ids = [int(row.attrs["data-person-id"]) for row in rows]
    assert set(ids) <= active_ids, "в выдаче есть не действующий сотрудник"
    assert not ({person.pk for person in dismissed} & set(ids)), "в выдаче уволенный"
    assert stranger.pk not in ids and viewer.user.pk not in ids, "в выдаче лишний сотрудник"
    for row in rows:
        hrefs = [link.attrs.get("href", "") for link in row.walk() if link.attrs.get("href")]
        assert any(href.endswith(f"/messenger/?to={row.attrs['data-person-id']}") for href in hrefs), (
            f"у строки {row.attrs['data-person-id']} нет действия «Написать»: {hrefs}")

    empty = viewer.client.get("/messenger/people/")
    assert empty.status_code == 200
    assert not _q(_tree(empty), data_person_id=True), "пустой запрос вернул строки"
    assert "начните вводить имя" in empty.content.decode("utf-8"), "нет подсказки «начните вводить имя»"

    gone = viewer.client.get("/messenger/people/", {"q": "Уволенный"})
    assert gone.status_code == 200
    assert not _q(_tree(gone), data_person_id=True), "поиск по уволенным вернул строки"


def test_card_write_button_hidden_for_self_and_dismissed():
    """FR-645: кнопка «Написать» в карточке есть у действующего коллеги и скрыта у себя и уволенного.

    Запись точки `card_sections` — `CardSection("messenger", "profile", 70, "messenger/_card_write.html", {})`
    (CONTRACT-008 3.4); на странице карточки — `[data-messenger-card-write]` со ссылкой `/messenger/?to=<id>` (12.6)."""
    from apps.core import extensions as core_extensions
    from apps.messenger import extensions

    viewer = _staff_viewer("Смотрящий На Кнопку")
    peer = messenger.make_user(full_name="Действующий Собеседник")
    dismissed = messenger.make_user(state="dismissed", full_name=DISMISSED_PEER)

    assert extensions.card_sections(viewer.user, peer.user) == [
        core_extensions.CardSection("messenger", "profile", 70, "messenger/_card_write.html", {})], (
        "раздел карточки для действующего коллеги не тот (CONTRACT-008 3.4)")
    assert extensions.card_sections(viewer.user, viewer.user) == [], "кнопка «Написать» показана себе"
    assert extensions.card_sections(viewer.user, dismissed.user) == [], "кнопка «Написать» показана уволенному"

    card = viewer.client.get(f"/staff/{peer.user.pk}/")
    assert card.status_code == 200, f"карточка коллеги: {card.status_code}"
    marks = _q(_tree(card), data_messenger_card_write=True)
    assert marks, "в карточке коллеги нет кнопки «Написать»"
    hrefs = [mark.attrs.get("href") for mark in marks if mark.attrs.get("href")]
    hrefs += [link.attrs.get("href", "") for mark in marks for link in _q(mark, "a")]
    assert f"/messenger/?to={peer.user.pk}" in hrefs, f"ссылка кнопки «Написать»: {hrefs}"

    for person in (viewer.user, dismissed.user):
        page = viewer.client.get(f"/staff/{person.pk}/")
        assert page.status_code == 200, f"карточка {person.pk}: {page.status_code}"
        assert not _q(_tree(page), data_messenger_card_write=True), (
            f"кнопка «Написать» показана в карточке {person.pk}")