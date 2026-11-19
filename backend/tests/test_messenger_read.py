"""T-8112: тесты прочтения и «Прочитали N из M» (FR-659, FR-660, FR-666).

План: «Прочтение и счётчики» (открытие беседы ставит отметку `ChatRead`, правило
`last_read_at = min(max(прежняя, at), now())`, ответ несёт число чата, общее число и строку «Прочитали N из M»;
числа кэшируются на 5 с и сбрасываются при отправке, прочтении и смене состава), «Открытая беседа» (открытие
публикует `object.viewed` и гасит уведомления чата; пришедшее в открытую беседу сообщение сразу отмечается
`read` и не остаётся непрочитанным); SPEC-008 сценарий 8. CONTRACT-008: 2.2 (`ChatRead`), 3.5 (`object.viewed`),
5.3 (`read.mark`, `read.line`, `unread.counts/total/badge`, `COUNT_CACHE_SECONDS`, `invalidate`), 10.1–10.2
(адрес `/messenger/chats/<id>/read/`, поле `at`, ответы), 11.3 (кадры `#messenger-read`, `#chat-<id>-unread`,
`#menu-badge-messenger`), 12.2–12.3 (зацепки, «99+»), 13.3 («Прочитали N из M», «99+»).

Код среза на уровне модуля не импортируется (правила для всех тестов среза): модели берутся через
`support.model`, службы — ленивыми импортами внутри тестов, тексты — литералы разделов 12–13. Секретов и ПДн
нет: адреса и телефоны не создаются, массовые читатели — строки `core.User` без входа.

Допущения писателя (см. отчёт T-8112): 1) открытие беседы обычным GET ставит отметку прочтения — иначе
сценарий 8 п. 2 («счётчик обнуляется») не работает без JavaScript; 2) повторный `POST /read/` с меньшим `at` —
не ошибка и не уменьшает отметку; 3) `data-count` у числа — счётчик, текст капируется «99+» (12.2); точный
потолок `data-count` закрепляет T-8113, здесь проверяется только «99+»; 4) правилу «только у последнего своего
сообщения» достаточно одного узла `#messenger-read` в беседе.
"""
import re
import uuid
from datetime import datetime, timedelta, timezone as dt_timezone
from html.parser import HTMLParser

import pytest
from django.utils import timezone

from tests import support
from tests import support_messenger as messenger
from tests import support_org as org
from tests.support import HX

pytestmark = pytest.mark.django_db

UTC = dt_timezone.utc
BAD_AT = "вчера вечером"
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- разбор разметки (помощник только этого файла; образец — test_messenger_general.py) --------------------------

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


def _containing_message(node) -> int | None:
    """Номер сообщения `#m<id>`, внутри которого стоит узел (зацепка 12.3)."""
    current = node.parent
    while current is not None:
        ident = current.attrs.get("id", "")
        if re.fullmatch(r"m\d+", ident):
            return int(ident[1:])
        current = current.parent
    return None


# --- модели, адреса и действия теста ---------------------------------------------------------------------------

def _Chat():
    return support.model("messenger.Chat")


def _Message():
    return support.model("messenger.Message")


def _ChatMember():
    return support.model("messenger.ChatMember")


def _ChatRead():
    return support.model("messenger.ChatRead")


def _Notification():
    return support.model("notify.Notification")


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


def _read(session, chat, at=None, *, htmx: bool = False):
    """`POST /messenger/chats/<id>/read/` с `at` (ISO, UTC; `None` — без поля, раздел 10.2)."""
    data = {}
    if at is not None:
        data["at"] = at if isinstance(at, str) else at.astimezone(UTC).isoformat()
    if htmx:
        return session.client.post(_read_url(chat), data, **HX)
    return session.client.post(_read_url(chat), data)


def _read_mark(chat, user):
    return _ChatRead().objects.filter(chat=chat, user=_user(user)).first()


def _counts(user) -> dict:
    from apps.messenger.services import unread

    return unread.counts(_user(user))


def _flood(chat, author, count: int, *, start: datetime, step: timedelta = timedelta(minutes=1)) -> list:
    """`count` чужих сообщений прямой записью: вектор поиска и уведомления не нужны, а 100+ строк дешевле
    одним `bulk_create`. `last_message_at` и кэш чисел правятся вручную (помощник `post` сбрасывает кэш)."""
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


def _cheap_users(count: int, prefix: str) -> list:
    """`count` действующих сотрудников без пароля и TOTP: читатели «Прочитали N из M» входа не требуют."""
    User = support.model("core.User")
    now = timezone.now()
    rows = [User(email=f"reader-{uuid.uuid4().hex[:12]}@example.test",
                 full_name=f"{prefix} {number:02d}", state="active", activated_at=now)
            for number in range(1, count + 1)]
    return User.objects.bulk_create(rows)


def _note(user, chat, label: str):
    """Непрочитанное уведомление мессенджера по чату (поток `notify`, `object_ref` — план «Уведомления»)."""
    return _Notification().objects.create(
        user=_user(user), kind="messenger.message", text=f"Новое сообщение в чате ({label})",
        url=f"/messenger/chats/{chat.pk}/#m0", object_ref=f"messenger.chat:{chat.pk}")


# --- отметка при открытии (FR-659, FR-660) ---------------------------------------------------------------------

def test_opening_chat_creates_read_mark(clock):
    """FR-659, FR-660: открытие беседы обычным GET создаёт (или обновляет) отметку `ChatRead` на текущий момент и
    обнуляет число непрочитанных у чата; повторное открытие — без ошибки. Новичок отдела начинает с нуля и видит
    прежнюю историю, а открытие чата отдела тоже ставит отметку."""
    viewer = _employee("Открывающий Переписку")
    peer = _employee("Пишущий Напрямую")
    base = _moment()
    clock.set(base)
    chat = messenger.personal(viewer, peer)
    messenger.post(chat, peer, "Непрочитанное до открытия", created_at=base + timedelta(minutes=1))
    clock.set(base + timedelta(minutes=1))
    assert _counts(viewer.user).get(chat.pk, 0) == 1, "до открытия у диалога одно непрочитанное"

    clock.set(base + timedelta(minutes=2))
    opened = viewer.client.get(_chat_url(chat))
    assert opened.status_code == 200, f"беседа: {opened.status_code}"
    mark = _read_mark(chat, viewer.user)
    assert mark is not None, "открытие беседы не создало отметку прочтения (FR-659)"
    assert mark.last_read_at == base + timedelta(minutes=2), (
        f"отметка прочтения при открытии: {mark.last_read_at!r}")
    assert _counts(viewer.user).get(chat.pk, 0) == 0, "открытие не обнулило число чата"

    row = _q1(_tree(viewer.client.get("/messenger/")), id=f"chat-{chat.pk}-unread")
    assert row.attrs.get("data-count") == "0", f"data-count после открытия: {row.attrs.get('data-count')!r}"

    again = viewer.client.get(_chat_url(chat))
    assert again.status_code == 200, "повторное открытие беседы — без ошибки"
    assert _read_mark(chat, viewer.user).last_read_at == base + timedelta(minutes=2), (
        "повторное открытие без новых сообщений сдвинуло отметку")

    unit = messenger.unit("Отдел Новичка Прочтения")
    newcomer = _employee("Новичок Прочтения")
    insider = _employee("Сотрудник Отдела Прочтения")
    org.make_member(newcomer.user, unit)
    org.make_member(insider.user, unit)
    clock.set(base + timedelta(minutes=3))
    department = messenger.department_chat(unit)
    history = messenger.post(department, insider, "История до прихода новичка",
                             created_at=base + timedelta(minutes=3))
    # Решение владельца 2026-11-17: у чата отдела без отметки база — создание чата, история считается.
    assert _counts(newcomer.user).get(department.pk, 0) == 1, (
        "история чата отдела после создания не попала в число (FR-660)")

    page = newcomer.client.get(_chat_url(department))
    assert page.status_code == 200, f"беседа отдела: {page.status_code}"
    assert history.text in page.content.decode(), "новичок не видит прежнюю историю"
    assert _read_mark(department, newcomer.user) is not None, "открытие чата отдела не создало отметку"


# --- повтор и максимум (FR-659) --------------------------------------------------------------------------------

def test_repeat_read_keeps_max_and_does_not_decrease(clock):
    """FR-659: повторная отметка не ошибка и не уменьшает `last_read_at`: служба держит максимум из прежней и
    присланной; кэш чисел живёт 5 с и сбрасывается при записи сообщения и при прочтении."""
    viewer = _employee("Читающий Повторно")
    peer = _employee("Пишущий Повторно")
    base = _moment()
    clock.set(base)
    chat = messenger.personal(viewer, peer)
    messenger.post(chat, peer, "Первое", created_at=base + timedelta(minutes=1))
    messenger.post(chat, peer, "Второе", created_at=base + timedelta(minutes=2))
    clock.set(base + timedelta(minutes=2))
    assert _counts(viewer.user).get(chat.pk) == 2

    clock.set(base + timedelta(minutes=3))
    first = _read(viewer, chat, base + timedelta(minutes=3))
    assert first.status_code == 302, f"отметка прочтения обычным POST: {first.status_code}"
    assert first["Location"] == _chat_url(chat)
    assert _read_mark(chat, viewer.user).last_read_at == base + timedelta(minutes=3)
    assert _counts(viewer.user).get(chat.pk, 0) == 0

    clock.set(base + timedelta(minutes=5))
    later = _read(viewer, chat, base + timedelta(minutes=5))
    assert later.status_code == 302
    assert _read_mark(chat, viewer.user).last_read_at == base + timedelta(minutes=5)

    earlier = _read(viewer, chat, base + timedelta(minutes=4))
    assert earlier.status_code == 302, f"повтор с меньшим at — не ошибка: {earlier.status_code}"
    assert _read_mark(chat, viewer.user).last_read_at == base + timedelta(minutes=5), (
        "повтор с меньшим at уменьшил отметку прочтения")

    from apps.messenger.services import unread

    assert unread.COUNT_CACHE_SECONDS == 5, "кэш чисел мессенджера — 5 секунд (5.3)"
    clock.set(base + timedelta(minutes=6))
    messenger.post(chat, peer, "Третье", created_at=base + timedelta(minutes=6))
    assert _counts(viewer.user).get(chat.pk) == 1, "кэш чисел не сброшен записью сообщения"

    _Message().objects.create(chat=chat, author=peer.user, is_system=False,
                              text="Прямая запись мимо службы", created_at=base + timedelta(minutes=6))
    assert _counts(viewer.user).get(chat.pk) == 1, "числа не кэшируются на 5 секунд (5.3)"
    unread.invalidate([viewer.user.pk])
    assert _counts(viewer.user).get(chat.pk) == 2, "invalidate не сбросил число сотрудника"

    clock.set(base + timedelta(minutes=7))
    assert _read(viewer, chat, base + timedelta(minutes=7)).status_code == 302
    assert _counts(viewer.user).get(chat.pk, 0) == 0, "кэш чисел не сброшен отметкой прочтения"


# --- будущее время (FR-659, FR-660) ----------------------------------------------------------------------------

def test_future_at_clamped_to_now_and_does_not_suppress_next_messages(clock):
    """FR-659, FR-660: `at` из будущего обрезается до `now` — последующее сообщение остаётся непрочитанным и
    не попадает в «Прочитали»; неверный или отсутствующий `at` — как `now` (10.1). Отправка нового сообщения
    сбрасывает кэш чисел."""
    viewer = _employee("Читающий Будущее")
    peer = _employee("Пишущий После Будущего")
    base = _moment()
    clock.set(base)
    chat = messenger.personal(viewer, peer)
    messenger.post(chat, peer, "До отметки", created_at=base)
    assert _counts(viewer.user).get(chat.pk) == 1

    clamped = _read(viewer, chat, base + timedelta(days=1))
    assert clamped.status_code == 302, f"отметка с будущим at: {clamped.status_code}"
    mark = _read_mark(chat, viewer.user)
    assert mark.last_read_at == base, f"будущее at не обрезано до now: {mark.last_read_at!r}"
    assert _counts(viewer.user).get(chat.pk, 0) == 0

    clock.set(base + timedelta(minutes=1))
    sent = peer.client.post(_messages_url(chat), {"text": "Новое после будущего времени"})
    assert sent.status_code == 302, f"отправка: {sent.status_code}"
    message = _Message().objects.get(chat=chat, text="Новое после будущего времени")
    assert _counts(viewer.user).get(chat.pk) == 1, (
        "сообщение после обрезанного прочтения осталось прочитанным (кэш или отметка)")
    from apps.messenger.services import read as read_service

    assert read_service.line(chat, message) == (0, 1), "будущая отметка зачла новое сообщение прочитанным"

    clock.set(base + timedelta(minutes=2))
    assert _read(viewer, chat, BAD_AT).status_code == 302
    assert _read_mark(chat, viewer.user).last_read_at == base + timedelta(minutes=2), (
        "неверный at принят не как now (10.1)")

    clock.set(base + timedelta(minutes=3))
    assert _read(viewer, chat, None).status_code == 302
    assert _read_mark(chat, viewer.user).last_read_at == base + timedelta(minutes=3), (
        "отсутствующий at принят не как now (10.2)")


# --- «Прочитали N из M» (FR-659) --------------------------------------------------------------------------------

def test_author_sees_read_12_of_40_only_under_last_own_message(clock):
    """FR-659, сценарий 8 п. 3: M — участники без автора, N — отметки не раньше сообщения; строка «Прочитали
    12 из 40» стоит только у последнего своего сообщения, у прочих своих её нет."""
    author = _employee("Автор Своих Сообщений")
    readers = _cheap_users(40, "Читатель")
    base = _moment()
    clock.set(base - timedelta(hours=1))
    chat = messenger.group(author, readers, title="Сорок Читателей")
    clock.set(base)
    earlier = messenger.post(chat, author, "Раннее своё сообщение", created_at=base)
    last = messenger.post(chat, author, "Последнее своё сообщение", created_at=base + timedelta(minutes=1))
    for person in readers[:12]:
        messenger.read(chat, person, base + timedelta(minutes=2))
    clock.set(base + timedelta(minutes=2))

    from apps.messenger.services import read as read_service

    assert read_service.line(chat, last) == (12, 40), (
        f"read.line: {read_service.line(chat, last)!r}")

    response = author.client.get(_chat_url(chat))
    assert response.status_code == 200, f"беседа автора: {response.status_code}"
    document = _tree(response)
    lines = _q(document, id="messenger-read")
    assert len(lines) == 1, f"строка «Прочитали N из M» встречается {len(lines)} раз(а)"
    line = lines[0]
    assert "Прочитали 12 из 40" in line.text(), line.text()
    assert _containing_message(line) == last.pk, (
        f"строка стоит у сообщения {_containing_message(line)}, а не у последнего своего {last.pk}")
    assert _q(_q1(document, id=f"m{earlier.pk}"), id="messenger-read") == [], (
        "строка «Прочитали» есть у не-последнего своего сообщения")


# --- состав M (FR-659) ------------------------------------------------------------------------------------------

def test_dismissed_and_left_members_not_in_m(clock):
    """FR-659: уволенный и вышедший не входят в M и не увеличивают N, даже если их отметка прочтения новее
    сообщения; смена состава сбрасывает кэш чисел затронутого сотрудника."""
    author = _employee("Автор Состава")
    first = _employee("Первый Читающий")
    second = _employee("Второй Читающий")
    left = _employee("Вышедший Член")
    dismissed = messenger.make_user(state="dismissed", full_name="Уволенный Член")
    base = _moment()
    clock.set(base - timedelta(hours=1))
    chat = messenger.group(author, [first, second, left, dismissed], title="Состав И Чтение")
    clock.set(base)
    message = messenger.post(chat, author, "Кто прочитал", created_at=base)
    _ChatMember().objects.filter(chat=chat, user=left.user).update(left_at=base + timedelta(minutes=2))
    for person in (first, second, left, dismissed):
        messenger.read(chat, person, base + timedelta(minutes=3))

    from apps.messenger.services import read as read_service

    assert read_service.line(chat, message) == (2, 2), (
        f"уволенный или вышедший учтён в M/N: {read_service.line(chat, message)!r}")
    page = author.client.get(_chat_url(chat))
    assert page.status_code == 200, f"беседа автора: {page.status_code}"
    line = _q1(_tree(page), id="messenger-read")
    assert "Прочитали 2 из 2" in line.text(), line.text()

    clock.set(base + timedelta(minutes=4))
    messenger.post(chat, author, "Новое после прочтения", created_at=base + timedelta(minutes=4))
    from apps.messenger.services import unread

    assert unread.counts(first.user).get(chat.pk) == 1
    removed = author.client.post(f"/messenger/chats/{chat.pk}/members/", {"remove": str(first.user.pk)})
    assert removed.status_code == 302, f"смена состава: {removed.status_code}"
    assert _ChatMember().objects.get(chat=chat, user=first.user).left_at is not None
    assert unread.counts(first.user).get(chat.pk, 0) == 0, "смена состава не сбросила кэш чисел"


# --- открытая беседа и поток уведомлений (FR-666) ---------------------------------------------------------------

def test_message_in_opened_chat_is_marked_read_and_leaves_notification_flow(
        clock, django_capture_on_commit_callbacks):
    """FR-666, сценарий 9 п. 6: сообщение, пришедшее в открытую беседу, сразу отмечается `read` (так делает
    клиент открытой беседы) и уходит из непрочитанного потока уведомлений; у закрытой беседы уведомление
    остаётся непрочитанным и число чата растёт."""
    author = _employee("Автор Живой Беседы")
    reader = _employee("Читатель Открытой Беседы")
    closed = _employee("Читатель Закрытой Беседы")
    base = _moment()
    clock.set(base)
    chat = messenger.group(author, [reader, closed], title="Открытая Беседа")
    assert reader.client.get(_chat_url(chat)).status_code == 200, "открытие беседы"
    assert _read_mark(chat, reader.user).last_read_at == base

    clock.set(base + timedelta(minutes=1))
    text = "Пришло в открытую беседу"
    sent = author.client.post(_messages_url(chat), {"text": text})
    assert sent.status_code == 302, f"отправка: {sent.status_code}"
    message = _Message().objects.get(chat=chat, text=text)

    ref = f"messenger.chat:{chat.pk}"
    note = _Notification().objects.get(user=reader.user, object_ref=ref)
    assert note.read_at is None, "портал должен сначала показать уведомление непрочитанным"
    assert _counts(reader.user).get(chat.pk) == 1, "сообщение в открытой беседе ещё не отмечено"

    clock.set(base + timedelta(minutes=2))
    with django_capture_on_commit_callbacks(execute=True):
        marked = _read(reader, chat, base + timedelta(minutes=2))
    assert marked.status_code == 302, f"отметка прочтения: {marked.status_code}"
    assert _read_mark(chat, reader.user).last_read_at >= message.created_at, (
        "отметка открытой беседы не покрыла пришедшее сообщение")
    assert _counts(reader.user).get(chat.pk, 0) == 0, "сообщение осталось непрочитанным у открытой беседы"
    note.refresh_from_db()
    assert note.read_at is not None, "уведомление открытой беседы осталось в непрочитанном потоке (FR-666)"

    closed_note = _Notification().objects.get(user=closed.user, object_ref=ref)
    assert closed_note.read_at is None, "у закрытой беседы уведомление прочитано без открытия"
    assert _counts(closed.user).get(chat.pk) == 1, "у закрытой беседы число чата не выросло"


def test_object_viewed_event_silences_chat_notifications(clock, bus_spy, django_capture_on_commit_callbacks):
    """FR-666, CONTRACT-008 3.5: открытие беседы и отметка прочтения публикуют `object.viewed` с
    `object_ref="messenger.chat:<id>"`; подписчик `notify` гасит непрочитанные уведомления этого чата и только
    этого сотрудника — уведомления другого чата и другого сотрудника остаются непрочитанными."""
    author = _employee("Автор Двух Бесед")
    reader = _employee("Читатель Двух Бесед")
    other = _employee("Другой Читатель")
    base = _moment()
    clock.set(base)
    chat_a = messenger.group(author, [reader, other], title="Беседа Первая")
    chat_b = messenger.group(author, [reader], title="Беседа Вторая")
    first = _note(reader, chat_a, "первое")
    second = _note(reader, chat_a, "второе")
    foreign = _note(reader, chat_b, "другая беседа")
    outsider = _note(other, chat_a, "чужое уведомление")
    ref = f"messenger.chat:{chat_a.pk}"

    bus_spy.listen("object.viewed")
    with django_capture_on_commit_callbacks(execute=True):
        opened = reader.client.get(_chat_url(chat_a))
    assert opened.status_code == 200, f"беседа: {opened.status_code}"
    calls = bus_spy.calls("object.viewed")
    assert calls, "открытие беседы не опубликовало object.viewed"
    assert {(call["object_ref"], call["user_id"]) for call in calls} == {(ref, reader.user.pk)}, (
        f"событие открытия: {calls!r}")
    for note in (first, second):
        note.refresh_from_db()
        assert note.read_at is not None, "уведомление открытого чата осталось непрочитанным"
    foreign.refresh_from_db()
    outsider.refresh_from_db()
    assert foreign.read_at is None, "погашено уведомление другого чата"
    assert outsider.read_at is None, "погашено уведомление другого сотрудника"

    fresh = _note(reader, chat_a, "после отметки")
    before = len(calls)
    clock.set(base + timedelta(minutes=1))
    with django_capture_on_commit_callbacks(execute=True):
        marked = _read(reader, chat_a, base + timedelta(minutes=1))
    assert marked.status_code == 302, f"отметка прочтения: {marked.status_code}"
    fresh.refresh_from_db()
    assert fresh.read_at is not None, "отметка прочтения не погасила уведомление чата"
    assert len(bus_spy.calls("object.viewed")) > before, "отметка прочтения не опубликовала object.viewed"


# --- ответ отметки и числа (FR-659, FR-660) ---------------------------------------------------------------------

def test_read_answer_carries_chat_count_total_and_read_line(clock):
    """FR-659, FR-660, сценарий 8: ответ отметки HTMX несёт узел числа чата, общее число пункта меню и строку
    «Прочитали N из M»; числа показывают «99+» выше 99, а после прочтения чат обнуляется, общее уменьшается."""
    viewer = _employee("Автор Ответа Прочтения")
    p1, p2, p3 = (_employee("Читающий Первый"), _employee("Читающий Второй"), _employee("Читающий Третий"))
    base = _moment()
    clock.set(base - timedelta(hours=4))
    chat_a = messenger.group(viewer, [p1, p2, p3], title="Сто Непрочитанных")
    chat_b = messenger.group(viewer, [p1], title="Двадцать Непрочитанных")
    clock.set(base - timedelta(hours=2))
    _flood(chat_a, p1, 100, start=base - timedelta(hours=2))
    own = messenger.post(chat_a, viewer, "Последнее своё сообщение", created_at=base - timedelta(minutes=30))
    _flood(chat_b, p1, 20, start=base - timedelta(hours=2))
    messenger.read(chat_a, p1, own.created_at + timedelta(minutes=1))
    clock.set(base)

    page = viewer.client.get("/messenger/")
    assert page.status_code == 200, f"страница списка: {page.status_code}"
    page = _tree(page)
    chat_count = _q1(page, id=f"chat-{chat_a.pk}-unread")
    assert chat_count.text() == "99+", f"число чата 100: {chat_count.text()!r}"
    assert int(chat_count.attrs.get("data-count", "0")) >= 99, chat_count.attrs
    other_count = _q1(page, id=f"chat-{chat_b.pk}-unread")
    assert (other_count.text(), other_count.attrs.get("data-count")) == ("20", "20")
    badge = _q1(page, id="menu-badge-messenger")
    assert badge.text() == "99+", f"общее число 120: {badge.text()!r}"
    assert int(badge.attrs.get("data-count", "0")) >= 99, badge.attrs

    response = _read(viewer, chat_a, base, htmx=True)
    assert response.status_code == 200, f"ответ отметки HTMX: {response.status_code}"
    body = response.content.decode("utf-8")
    assert "<html" not in body.lower(), "ответ отметки — фрагмент без страницы"
    answer = _tree(response)
    read_chat = _q1(answer, id=f"chat-{chat_a.pk}-unread")
    assert read_chat.attrs.get("data-count") == "0", read_chat.attrs
    assert "hx-swap-oob" in read_chat.attrs, "узел числа чата в ответе — OOB-замена (11.3)"
    read_badge = _q1(answer, id="menu-badge-messenger")
    assert (read_badge.text(), read_badge.attrs.get("data-count")) == ("20", "20"), (
        f"общее число после прочтения: {read_badge.text()!r}, {read_badge.attrs!r}")
    assert read_badge.attrs.get("hx-swap-oob") == "true", read_badge.attrs
    line = _q1(answer, id="messenger-read")
    assert "Прочитали 1 из 3" in line.text(), line.text()
    assert line.attrs.get("hx-swap-oob") == "true", line.attrs

    from apps.messenger.services import unread

    assert unread.counts(viewer.user).get(chat_a.pk, 0) == 0, "число прочитанного чата не обнулилось"
    assert unread.counts(viewer.user).get(chat_b.pk) == 20
    assert unread.total(viewer.user) == 20, f"общее число после прочтения: {unread.total(viewer.user)!r}"

    conversation = _tree(viewer.client.get(_chat_url(chat_a)))
    shown = _q1(conversation, id="messenger-read")
    assert "Прочитали 1 из 3" in shown.text(), shown.text()
    assert _containing_message(shown) == own.pk, (
        f"строка стоит у сообщения {_containing_message(shown)}, а не у последнего своего {own.pk}")