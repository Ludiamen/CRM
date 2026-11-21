"""T-8113: тесты чисел непрочитанного (FR-650, FR-660).

План «Прочтение и счётчики»: у чата — число непрочитанных (`#chat-<id>-unread`), у пункта меню — сумма
(`#menu-badge-messenger`, «99+» выше 99); числа кэшируются на 60 с с версией и сбрасываются при отправке,
прочтении и смене состава; база отсчёта — `joined_at` у личного и группового чата, 0 без отметки у чата отдела
и «Общего чата»; свои, системные и удалённые сообщения не входят. SPEC-008 сценарий 8; CONTRACT-008: 2.2
(`ChatMember.joined_at`, `ChatRead`), 3.5 (`access.changed` на кэш чисел), 5.1 (`unread.counts/total/badge`,
`COUNT_CACHE_SECONDS`, `invalidate`), 5.3, 12.2 (`#chat-<id>-unread[data-count]`, `#menu-badge-messenger[data-count]`,
«99+», `d-none` при 0), 13.3 («99+»).

Код среза на уровне модуля не импортируется (правила для всех тестов среза): модели — `support.model("messenger.*")`,
службы `unread`, `messages`, `members` — ленивые импорты внутри тестов, тексты — литералы раздела 13.3. Секретов
и ПДн нет: адреса и телефоны не создаются, массовые отправители — строки `core.User` без входа.

Допущения писателя (см. отчёт T-8113): 1) `data-count` несёт полное число (120, 319), капируется только текст
узла — «99+» (12.2; точный потолок `data-count` оставил этому файлу T-8112); 2) числа по чатам считаются одним
запросом к `messenger_message` при любом числе чатов (проверка `capture_sql`, как 5.1 для списка); 3) заблокированный
входит в состав `members.members`, но кадров и уведомлений не получает (5.1); 4) у чата отдела и «Общего чата» база
без отметки — 0, поэтому рост числа проверяется после явной отметки прочтения, а не после открытия беседы;
5) истечение кэша по реальному времени (60 с) не ждём: контракт называет константу и три сброса, а не таймер.
"""
from datetime import datetime, timedelta, timezone as dt_timezone
from html.parser import HTMLParser

import pytest

from tests import support
from tests import support_messenger as messenger
from tests import support_org as org

pytestmark = pytest.mark.django_db

UTC = dt_timezone.utc
PLUS = "99+"
HIDDEN = "d-none"
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- разбор разметки (помощник только этого файла; образец — test_messenger_read.py) ----------------------------

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


def _tree(response_or_html) -> _Node:
    html = response_or_html if isinstance(response_or_html, str) else response_or_html.content.decode("utf-8")
    parser = _Parser()
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


def _classes(node) -> set[str]:
    return set(node.attrs.get("class", "").split())


def _row(document, chat) -> _Node:
    """Строка списка чата (`[data-chat-id="<id>"]`, 12.2) на странице `/messenger/`."""
    rows = _q(document, data_chat_id=str(chat.pk))
    assert len(rows) == 1, f"строк списка чата {chat.pk}: {len(rows)}"
    return rows[0]


def _unread(document, chat) -> _Node:
    """Число непрочитанных чата (`#chat-<id>-unread[data-count]`, 12.2)."""
    return _q1(_row(document, chat), id=f"chat-{chat.pk}-unread")


def _badge_node(document) -> _Node:
    """Число пункта меню `#menu-badge-messenger[data-count]` (12.2)."""
    return _q1(document, id="menu-badge-messenger")


# --- модели, службы и действия теста ---------------------------------------------------------------------------

def _Chat():
    return support.model("messenger.Chat")


def _Message():
    return support.model("messenger.Message")


def _ChatMember():
    return support.model("messenger.ChatMember")


def _ChatRead():
    return support.model("messenger.ChatRead")


def _user(value):
    """Сотрудник из `Session` или сам `core.User`."""
    return getattr(value, "user", value)


def _employee(name: str, **extra):
    """Действующий сотрудник с клиентом (`messenger.make_user`)."""
    return messenger.make_user(full_name=name, **extra)


def _moment() -> datetime:
    return datetime(2026, 6, 1, 9, 0, tzinfo=UTC)


def _chat_url(chat) -> str:
    return f"/messenger/chats/{chat.pk}/"


def _messages_url(chat) -> str:
    return f"/messenger/chats/{chat.pk}/messages/"


def _read_url(chat) -> str:
    return f"/messenger/chats/{chat.pk}/read/"


def _members_url(chat) -> str:
    return f"/messenger/chats/{chat.pk}/members/"


def _counts(user) -> dict:
    from apps.messenger.services import unread

    return unread.counts(_user(user))


def _total(user) -> int:
    from apps.messenger.services import unread

    return unread.total(_user(user))


def _badge(user) -> int:
    from apps.messenger.services import unread

    return unread.badge(_user(user))


def _message(chat, author, at, text: str = "Прямая запись мимо службы"):
    """Сообщение прямой записью: кэш чисел не сбрасывается — так проверяется, что число кэшировано."""
    return _Message().objects.create(chat=chat, author=_user(author), is_system=False, text=text, created_at=at)


def _flood(chat, author, count: int, *, start: datetime, step: timedelta = timedelta(minutes=1)) -> list:
    """`count` чужих сообщений прямой записью: 100+ строк дешевле одним `bulk_create`.

    `last_message_at` чата поднимается, кэш чисел сбрасывается — иначе список показывал бы прежнее число."""
    Message = _Message()
    messages = [Message(chat=chat, author=_user(author), is_system=False, text=f"Сообщение {number:03d}",
                        created_at=start + step * number) for number in range(count)]
    Message.objects.bulk_create(messages)
    last = start + step * (count - 1)
    _Chat().objects.filter(pk=chat.pk).update(last_message_at=last)
    chat.last_message_at = last
    from apps.messenger.services import unread

    unread.invalidate(None)
    return messages


def _message_selects(sqls) -> list:
    """Запросы-выборки к `messenger_message`: по ним видно, считается ли число на каждый чат отдельно."""
    return [sql for sql in sqls
            if "messenger_message" in sql and sql.lstrip().upper().startswith("SELECT")]


# --- числа по чатам и общее (FR-660) ---------------------------------------------------------------------------

def test_chat_count_and_total_grow_by_new_message(clock, django_capture_on_commit_callbacks):
    """FR-660, сценарий 8 п. 1: каждое новое сообщение увеличивает число своего чата и общее число пункта меню.

    Личный диалог даёт 1 у получателя, групповой — тоже; общее число — сумма по чатам, `unread.badge` — то же
    число (5.1, 5.3). Заблокированный входит в состав, но кадров и уведомлений не получает (5.1). Числа по чатам
    считаются одним запросом к `messenger_message` при любом числе чатов (capture_sql, как 5.1 для списка).
    """
    _Chat().objects.filter(kind="general").delete()
    viewer = _employee("Считающий Числа Чатов")
    peer = _employee("Пишущий Числа Чатов")
    blocked = messenger.make_user(state="blocked", full_name="Заблокированный Числа Чатов")
    base = _moment()
    clock.set(base - timedelta(hours=1))
    group_chat = messenger.group(viewer, [peer, blocked], title="Числа Группы")
    personal_chat = messenger.personal(viewer, peer)

    clock.set(base)
    messenger.post(group_chat, peer, "Первое в группе", created_at=base)
    numbers = _counts(viewer)
    assert numbers.get(group_chat.pk) == 1, f"число группового чата: {numbers!r}"
    assert numbers.get(personal_chat.pk, 0) == 0, "сообщение попало не в тот чат"
    assert _total(viewer) == 1, f"общее число: {_total(viewer)!r}"
    assert _badge(viewer) == 1, "число пункта меню не равно общему"
    page = _tree(viewer.client.get("/messenger/"))
    assert (_unread(page, group_chat).attrs.get("data-count"), _unread(page, group_chat).text()) == ("1", "1")
    assert _badge_node(page).attrs.get("data-count") == "1"

    clock.set(base + timedelta(minutes=1))
    messenger.post(personal_chat, peer, "Первое в личном", created_at=base + timedelta(minutes=1))
    numbers = _counts(viewer)
    assert (numbers.get(group_chat.pk), numbers.get(personal_chat.pk)) == (1, 1), numbers
    assert sum(numbers.values()) == _total(viewer) == 2, "общее число не равно сумме по чатам"
    assert _badge(viewer) == 2
    page = _tree(viewer.client.get("/messenger/"))
    assert _unread(page, group_chat).attrs.get("data-count") == "1"
    assert _unread(page, personal_chat).attrs.get("data-count") == "1"
    assert _badge_node(page).attrs.get("data-count") == "2"

    from apps.messenger.services import members, messages

    assert members.members(group_chat) == frozenset({viewer.user.pk, peer.user.pk, blocked.user.pk}), (
        "заблокированный выпал из состава (5.1)")
    clock.set(base + timedelta(minutes=2))
    with messenger.layer_spy() as spy:
        with django_capture_on_commit_callbacks(execute=True):
            messages.send(group_chat, peer.user, "Второе в группе")
        messenger.run_jobs("notify")
    assert f"messenger.u.{viewer.user.pk}" in spy.by_group, "новое сообщение не разослано участнику"
    assert f"messenger.u.{blocked.user.pk}" not in spy.by_group, "кадр ушёл заблокированному"
    assert f"notify.u.{blocked.user.pk}" not in spy.by_group, "кадр колокольчика ушёл заблокированному"
    numbers = _counts(viewer)
    assert (numbers.get(group_chat.pk), numbers.get(personal_chat.pk)) == (2, 1), numbers
    assert sum(numbers.values()) == _total(viewer) == 3
    assert _badge(viewer) == 3
    page = _tree(viewer.client.get("/messenger/"))
    assert _unread(page, group_chat).attrs.get("data-count") == "2"
    assert _badge_node(page).attrs.get("data-count") == "3"

    from apps.messenger.services import unread

    message_queries = {}
    for number in (1, 12):
        clock.set(base + timedelta(hours=1 + number))
        person = _employee(f"Считающий Запросы {number:02d}")
        pairs = []
        for index in range(number):
            writer = _employee(f"Пишущий Запросы {number:02d}-{index:02d}")
            pairs.append((messenger.personal(person, writer), writer))
        clock.set(base + timedelta(hours=1 + number, minutes=5))
        for index, (chat, writer) in enumerate(pairs):
            messenger.post(chat, writer, f"Непрочитанное {index:02d}")
        unread.invalidate([person.user.pk])
        with messenger.capture_sql() as sqls:
            found = unread.counts(person.user)
        assert sum(found.values()) == number, f"числа {number} чатов: {found!r}"
        message_queries[number] = len(_message_selects(sqls))
    assert message_queries[1] == message_queries[12], (
        f"числа по чатам считаются на каждый чат отдельно: {message_queries}")
    assert message_queries[1] == 1, f"числа по чатам — не один запрос к messenger_message: {message_queries}"


# --- свои, системные и удалённые сообщения (FR-660) ------------------------------------------------------------

def test_own_and_deleted_messages_not_counted(clock):
    """FR-660: свои, системные и удалённые сообщения не входят в число непрочитанных — ни у автора, ни у других.

    Своё живое сообщение автору не считается, а собеседнику считается; удалённое (`deleted_at`, текст пуст по
    проверке модели, 2.2) и системная запись не считаются никому (5.3). Узел числа при 0 остаётся с
    `data-count="0"` и классом `d-none` (12.2).
    """
    _Chat().objects.filter(kind="general").delete()
    viewer = _employee("Автор Своих Чисел")
    peer = _employee("Пишущий Удалённое")
    base = _moment()
    clock.set(base - timedelta(hours=1))
    chat = messenger.group(viewer, [peer], title="Свои И Удалённые Числа")

    clock.set(base)
    own = messenger.post(chat, viewer, "Своё живое", created_at=base)
    own_deleted = messenger.post(chat, viewer, "", created_at=base + timedelta(minutes=1),
                                 deleted_at=base + timedelta(minutes=2))
    other_deleted = messenger.post(chat, peer, "", created_at=base + timedelta(minutes=3),
                                   deleted_at=base + timedelta(minutes=4))
    system = _Message().objects.create(chat=chat, author=None, is_system=True, text="Создал чат",
                                       created_at=base + timedelta(minutes=5))
    assert (own.deleted_at, own_deleted.deleted_at, other_deleted.deleted_at) == (
        None, base + timedelta(minutes=2), base + timedelta(minutes=4))
    assert system.is_system and system.author_id is None

    assert _counts(viewer).get(chat.pk, 0) == 0, "свои, удалённые или системные сообщения попали в число"
    assert _total(viewer) == 0
    page = _tree(viewer.client.get("/messenger/"))
    quiet = _unread(page, chat)
    assert quiet.attrs.get("data-count") == "0", quiet.attrs
    assert HIDDEN in _classes(quiet), "узел нуля без класса d-none (12.2)"

    clock.set(base + timedelta(minutes=6))
    live = messenger.post(chat, peer, "Чужое живое", created_at=base + timedelta(minutes=6))
    assert _counts(viewer).get(chat.pk) == 1, "чужое живое сообщение не посчитано"
    assert _total(viewer) == 1
    page = _tree(viewer.client.get("/messenger/"))
    counted = _unread(page, chat)
    assert (counted.attrs.get("data-count"), counted.text()) == ("1", "1")
    assert HIDDEN not in _classes(counted), "ненулевое число скрыто классом d-none"

    peer_numbers = _counts(peer)
    assert peer_numbers.get(chat.pk) == 1, "своё живое сообщение автора не посчитано собеседнику"
    assert _total(peer) == 1, "у собеседника в числе лишние свои или удалённые сообщения"
    assert live.text == "Чужое живое"


# --- «99+» и потолок текста (FR-660) ---------------------------------------------------------------------------

def test_120_unread_shown_as_99_plus(clock):
    """FR-660, 12.2: при числе больше 99 текст узла — «99+», а `data-count` несёт полное число.

    Границы: 99 — текст «99», 100 — «99+», 120 — «99+»/`data-count="120"`; у пункта меню то же правило,
    `data-count` — сумма по чатам (319). У чата без непрочитанных узел остаётся с `data-count="0"` и `d-none`.
    """
    _Chat().objects.filter(kind="general").delete()
    viewer = _employee("Смотрящий Потолок Чисел")
    writer = _employee("Пишущий Потолок Чисел")
    base = _moment()
    clock.set(base - timedelta(hours=2))
    many = messenger.group(viewer, [writer], title="Сто Двадцать")
    almost = messenger.group(viewer, [writer], title="Девяносто Девять")
    hundred = messenger.group(viewer, [writer], title="Сто")
    quiet = messenger.group(viewer, [writer], title="Тихая Группа")
    clock.set(base - timedelta(hours=1))
    _flood(many, writer, 120, start=base - timedelta(hours=1))
    _flood(almost, writer, 99, start=base - timedelta(hours=1))
    _flood(hundred, writer, 100, start=base - timedelta(hours=1))
    from apps.messenger.services import unread

    unread.invalidate(None)

    numbers = _counts(viewer)
    assert (numbers.get(many.pk), numbers.get(almost.pk), numbers.get(hundred.pk)) == (120, 99, 100), numbers
    assert _total(viewer) == 319, f"общее число: {_total(viewer)!r}"
    assert _badge(viewer) == 319, "число пункта меню — не полное число"

    page = _tree(viewer.client.get("/messenger/"))
    big = _unread(page, many)
    assert (big.text(), big.attrs.get("data-count")) == (PLUS, "120"), big.attrs
    boundary_low = _unread(page, almost)
    assert (boundary_low.text(), boundary_low.attrs.get("data-count")) == ("99", "99"), boundary_low.attrs
    boundary_high = _unread(page, hundred)
    assert (boundary_high.text(), boundary_high.attrs.get("data-count")) == (PLUS, "100"), boundary_high.attrs
    empty = _unread(page, quiet)
    assert empty.attrs.get("data-count") == "0", empty.attrs
    assert HIDDEN in _classes(empty), "узел нуля без класса d-none (12.2)"
    badge = _badge_node(page)
    assert (badge.text(), badge.attrs.get("data-count")) == (PLUS, "319"), badge.attrs


# --- база отсчёта: чат отдела и «Общий чат» (FR-650, FR-660) ---------------------------------------------------

def test_newcomer_of_department_has_zero_and_history_available(clock):
    """FR-650, FR-660: у чата отдела без отметки база — создание чата (решение владельца 2026-11-17), история видна.

    База чата отдела и «Общего чата» — `GREATEST(ChatRead.last_read_at, Chat.created_at)`: до отметки в число
    входит вся история после создания чата, отметка её обнуляет, следующее сообщение даёт 1. Чат чужого отдела в
    числа не входит. Имя теста сохранено (на него ссылаются TASKS-008), ожидания — по решению владельца.
    """
    general = messenger.general()
    unit = messenger.unit("Отдел Новичка Чисел")
    insider = _employee("Сотрудник Отдела Чисел")
    org.make_member(insider.user, unit)
    outsider = _employee("Посторонний Отделу Чисел")
    base = _moment()
    clock.set(base - timedelta(hours=2))
    department = messenger.department_chat(unit)
    clock.set(base - timedelta(hours=1))
    history = [messenger.post(department, insider, f"История до прихода {number:02d}",
                              created_at=base - timedelta(hours=1) + timedelta(minutes=number))
               for number in range(3)]
    general_message = messenger.post(general, insider, "Общее сообщение до отметки",
                                     created_at=base - timedelta(minutes=30))
    newcomer = _employee("Новичок Чисел Отдела")
    org.make_member(newcomer.user, unit)
    assert _ChatMember().objects.filter(chat=department).count() == 0, "у чата отдела появились строки состава"

    assert _counts(newcomer).get(department.pk, 0) == 3, "история после создания чата не попала в число"
    assert _counts(newcomer).get(general.pk, 0) == 1, "сообщение «Общего чата» не попало в число"
    assert _total(newcomer) == 4, f"без отметок числа не те: {_counts(newcomer)!r}"
    opened = newcomer.client.get(_chat_url(department))
    assert opened.status_code == 200, f"беседа отдела: {opened.status_code}"
    body = opened.content.decode("utf-8")
    for message in history:
        assert message.text in body, f"новичок не видит историю: {message.text!r}"

    clock.set(base)
    marked = newcomer.client.post(_read_url(department), {"at": base.astimezone(UTC).isoformat()})
    assert marked.status_code == 302, f"отметка прочтения чата отдела: {marked.status_code}"
    assert _counts(newcomer).get(department.pk, 0) == 0, "история до отметки попала в число"

    clock.set(base + timedelta(minutes=1))
    fresh = messenger.post(department, insider, "Сообщение после прихода",
                           created_at=base + timedelta(minutes=1))
    assert _counts(newcomer).get(department.pk) == 1, "сообщение после отметки не посчитано"
    assert _total(newcomer) == 2
    page = _tree(newcomer.client.get("/messenger/"))
    assert _unread(page, department).attrs.get("data-count") == "1"
    general_node = _unread(page, general)
    assert general_node.attrs.get("data-count") == "1", general_node.attrs
    assert HIDDEN not in _classes(general_node), "узел «Общего чата» с непрочитанным скрыт"
    assert general_message.text == "Общее сообщение до отметки"

    clock.set(base + timedelta(minutes=2))
    cleared = newcomer.client.post(_read_url(department),
                                   {"at": (base + timedelta(minutes=2)).astimezone(UTC).isoformat()})
    assert cleared.status_code == 302
    assert _counts(newcomer).get(department.pk, 0) == 0, "отметка не обнулила число чата отдела"
    assert _counts(outsider).get(department.pk, 0) == 0, "чат чужого отдела попал в числа"
    assert fresh.text == "Сообщение после прихода"


# --- база отсчёта: `joined_at` группового чата (FR-660) --------------------------------------------------------

def test_new_group_member_counts_only_messages_after_join(clock):
    """FR-660: в групповом чате новому участнику считаются только сообщения после его `joined_at`.

    База группового и личного чата — `ChatMember.joined_at` (5.3); сообщения до вступления не входят, хотя видны
    в истории. У давнего участника считаются все чужие сообщения, включая прежние: база у каждого своя.
    """
    _Chat().objects.filter(kind="general").delete()
    creator = _employee("Создатель Группы Чисел")
    old = _employee("Давний Участник Чисел")
    newcomer = _employee("Вступивший Позже Чисел")
    base = _moment()
    clock.set(base - timedelta(hours=3))
    chat = messenger.group(creator, [old], title="Вступление В Группу Чисел")
    clock.set(base - timedelta(hours=2))
    messenger.post(chat, creator, "До вступления", created_at=base - timedelta(hours=2))
    clock.set(base - timedelta(hours=1))
    messenger.post(chat, old, "Тоже до вступления", created_at=base - timedelta(hours=1))
    joined = _ChatMember().objects.create(chat=chat, user=newcomer.user, is_creator=False, joined_at=base)
    assert joined.joined_at == base

    from apps.messenger.services import unread

    unread.invalidate(None)
    assert _counts(newcomer).get(chat.pk, 0) == 0, "сообщения до вступления посчитаны новому участнику"
    assert _total(newcomer) == 0

    clock.set(base + timedelta(minutes=1))
    messenger.post(chat, creator, "После вступления", created_at=base + timedelta(minutes=1))
    assert _counts(newcomer).get(chat.pk) == 1, "сообщение после вступления не посчитано"
    assert _total(newcomer) == 1
    assert _counts(old).get(chat.pk) == 2, "у давнего участника потерялись прежние чужие сообщения"
    assert _counts(creator).get(chat.pk) == 1, "автору посчитаны свои сообщения"

    page = _tree(newcomer.client.get("/messenger/"))
    assert _unread(page, chat).attrs.get("data-count") == "1"


# --- личный диалог: первое сообщение (FR-660) ------------------------------------------------------------------

def test_personal_first_message_counts_one(clock, django_capture_on_commit_callbacks):
    """FR-660: первое сообщение нового личного диалога даёт получателю ровно одно непрочитанное.

    База личного чата — `joined_at` обоих участников (создание диалога, 5.3), поэтому первое же сообщение
    считается один раз, а не дважды и не по всей истории. Автор видит 0, отметки прочтения ещё нет; строка
    списка и пункт меню показывают 1.
    """
    _Chat().objects.filter(kind="general").delete()
    first = _employee("Первый Собеседник Чисел")
    second = _employee("Второй Собеседник Чисел")
    base = _moment()
    clock.set(base - timedelta(minutes=10))
    chat = messenger.personal(first, second)
    assert chat.created_at == base - timedelta(minutes=10)
    assert _ChatMember().objects.filter(chat=chat).count() == 2
    assert _ChatRead().objects.filter(chat=chat).count() == 0, "у нового диалога уже есть отметка прочтения"
    assert _counts(first).get(chat.pk, 0) == 0, "пустой диалог начал не с нуля"
    assert _counts(second).get(chat.pk, 0) == 0
    assert _total(first) == 0

    clock.set(base)
    with django_capture_on_commit_callbacks(execute=True):
        sent = second.client.post(_messages_url(chat), {"text": "Первое сообщение диалога"})
    assert sent.status_code == 302, f"отправка первого сообщения: {sent.status_code}"
    message = _Message().objects.get(chat=chat, text="Первое сообщение диалога")
    assert message.created_at > _ChatMember().objects.get(chat=chat, user=first.user).joined_at

    assert _counts(first).get(chat.pk) == 1, "первое сообщение посчитано не один раз"
    assert _total(first) == 1
    assert _badge(first) == 1
    assert _counts(second).get(chat.pk, 0) == 0, "автору посчитано своё первое сообщение"
    page = _tree(first.client.get("/messenger/"))
    unread_node = _unread(page, chat)
    assert (unread_node.attrs.get("data-count"), unread_node.text()) == ("1", "1")
    assert _badge_node(page).attrs.get("data-count") == "1"


# --- кэш чисел и три сброса (FR-660) -----------------------------------------------------------------------------

def test_cache_invalidated_by_send_read_and_membership_change(clock, django_capture_on_commit_callbacks):
    """FR-660, 5.3: числа кэшируются на 60 с и сбрасываются отправкой, прочтением и сменой состава.

    `COUNT_CACHE_SECONDS == 60`; прямая вставка `Message` мимо службы не меняет уже посчитанное число, `invalidate`
    сбрасывает. Затем число растёт после обычной отправки, обнуляется после отметки прочтения, а у выведенного из
    состава участника числа больше нет — каждый шаг проверяется без ручного сброса кэша.
    """
    _Chat().objects.filter(kind="general").delete()
    viewer = _employee("Создатель Кэша Чисел")
    peer = _employee("Участник Кэша Чисел")
    base = _moment()
    clock.set(base - timedelta(hours=1))
    chat = messenger.group(viewer, [peer], title="Кэш Чисел")
    from apps.messenger.services import unread

    assert unread.COUNT_CACHE_SECONDS == 60, "кэш чисел мессенджера — 60 секунд (решение владельца 2026-11-21)"

    clock.set(base)
    messenger.post(chat, peer, "Первое", created_at=base)
    assert _counts(viewer).get(chat.pk) == 1, "первое сообщение не посчитано"
    _message(chat, peer, base + timedelta(minutes=1))
    assert _counts(viewer).get(chat.pk) == 1, "числа не кэшируются на 60 секунд (5.3)"
    unread.invalidate([viewer.user.pk])
    assert _counts(viewer).get(chat.pk) == 2, "invalidate списка сотрудников не сбросил число"

    clock.set(base + timedelta(minutes=2))
    with django_capture_on_commit_callbacks(execute=True):
        sent = peer.client.post(_messages_url(chat), {"text": "Отправка службой"})
    assert sent.status_code == 302, f"отправка: {sent.status_code}"
    assert _counts(viewer).get(chat.pk) == 3, "отправка не сбросила кэш чисел"

    clock.set(base + timedelta(minutes=3))
    with django_capture_on_commit_callbacks(execute=True):
        marked = viewer.client.post(_read_url(chat),
                                    {"at": (base + timedelta(minutes=3)).astimezone(UTC).isoformat()})
    assert marked.status_code == 302, f"отметка прочтения: {marked.status_code}"
    assert _counts(viewer).get(chat.pk, 0) == 0, "прочтение не сбросило кэш чисел"

    clock.set(base + timedelta(minutes=4))
    with django_capture_on_commit_callbacks(execute=True):
        own = viewer.client.post(_messages_url(chat), {"text": "От создателя группе"})
    assert own.status_code == 302, f"отправка создателя: {own.status_code}"
    assert _counts(viewer).get(chat.pk, 0) == 0, "своё сообщение посчитано автору"
    assert _counts(peer).get(chat.pk) == 1, "сообщение создателя не посчитано участнику"

    clock.set(base + timedelta(minutes=5))
    with django_capture_on_commit_callbacks(execute=True):
        removed = viewer.client.post(_members_url(chat), {"remove": str(peer.user.pk)})
    assert removed.status_code == 302, f"смена состава: {removed.status_code}"
    assert _ChatMember().objects.get(chat=chat, user=peer.user).left_at is not None
    assert _counts(peer).get(chat.pk, 0) == 0, "смена состава не сбросила кэш чисел"
    assert _total(peer) == 0, "у вышедшего осталось общее число"


# --- событие смены доступа (FR-650, FR-660) --------------------------------------------------------------------

def test_access_changed_event_invalidates_counts_of_affected_employees(clock, django_capture_on_commit_callbacks):
    """FR-650, FR-660, CONTRACT-008 3.5: событие `access.changed` сбрасывает кэш чисел только затронутых.

    Подписка `messenger` на `access.changed` нужна только кэшу: состав и видимость считаются на момент запроса.
    После события с `user_ids=[…]` пересчитывается число перечисленного сотрудника, у остальных остаётся прежнее
    (кэш цел); событие с `user_ids=None` сбрасывает кэш всех.
    """
    _Chat().objects.filter(kind="general").delete()
    first = _employee("Первый При Смене Доступа")
    second = _employee("Второй При Смене Доступа")
    third = _employee("Третий При Смене Доступа")
    base = _moment()
    clock.set(base - timedelta(hours=1))
    shared = messenger.group(first, [second], title="Общая Беседа Доступа")
    other = messenger.group(third, [first], title="Другая Беседа Доступа")

    clock.set(base)
    assert _counts(first).get(shared.pk, 0) == 0
    assert _counts(second).get(shared.pk, 0) == 0
    assert _counts(third).get(other.pk, 0) == 0
    _message(shared, second, base + timedelta(minutes=1))
    _message(shared, first, base + timedelta(minutes=2))
    _message(other, first, base + timedelta(minutes=3))
    assert _counts(first).get(shared.pk, 0) == 0, "прямая запись обошла кэш чисел"
    assert _counts(second).get(shared.pk, 0) == 0
    assert _counts(third).get(other.pk, 0) == 0

    from apps.core import events

    subscribed = [handler for handler in events.subscribers("access.changed")
                  if getattr(handler, "__module__", "").startswith("apps.messenger")]
    assert subscribed, "кэш чисел не подписан на access.changed (CONTRACT-008 3.5)"

    clock.set(base + timedelta(minutes=4))
    with django_capture_on_commit_callbacks(execute=True):
        events.publish("access.changed", user_ids=[second.user.pk])
    assert _counts(second).get(shared.pk) == 1, "смена доступа не сбросила кэш затронутого сотрудника"
    assert _counts(first).get(shared.pk, 0) == 0, "сброшен кэш незатронутого сотрудника"
    assert _counts(third).get(other.pk, 0) == 0, "сброшен кэш сотрудника другого чата"

    with django_capture_on_commit_callbacks(execute=True):
        events.publish("access.changed", user_ids=None)
    assert _counts(first).get(shared.pk) == 1, "событие user_ids=None не сбросило кэш всех"
    assert _counts(third).get(other.pk) == 1, "событие user_ids=None не сбросило кэш всех"
    assert _total(first) == 1, f"общее число первого: {_total(first)!r}"
    assert _total(third) == 1, f"общее число третьего: {_total(third)!r}"