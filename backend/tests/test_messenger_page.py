"""T-8108: тесты списка, беседы и истории (FR-644, FR-658, FR-660, FR-669, FR-673, NFR-703).

Порядок списка `COALESCE(last_message_at, created_at) DESC, id DESC` (пустые чаты — последними), строка списка
(название, превью `snippet` 100, время по Москве, число непрочитанных), имя собеседника в личном диалоге, пустой
список с подсказкой, постоянное число SQL-запросов при любом числе чатов, `q` — параметрами SQL (не в тексте),
история по курсору `(created_at, id)` порциями 50/50/20 без потерь, 100 сообщений с одинаковым `created_at`,
история до первого сообщения, страница беседы с шапкой, полем ввода и узлом `/ws/messenger/?chat=<id>`, невидимый
чат — 404 как несуществующий.

Источники: CONTRACT-008 § 5.1 (`chats.rows`), § 5.4 (`page.chat_title`, `page.history`), § 10.1–10.2 (адреса,
параметры, белый список ключей, ответы), § 11.3, § 12.1–12.4 (зацепки), § 13.3 (тексты интерфейса); PLAN-008
«Список чатов и порядок», «Беседа и история порциями», «360 px и две колонки»; TASKS-008 T-8108.

Код среза на уровне модуля не импортируется (CONTRACT-008, «Правила для всех тестов среза»): модели берутся
через `support.model`, службы (`page`) — ленивым импортом внутри теста. Сбор `pytest --collect-only` проходит до
появления кода.

Допущения писателя (см. отчёт T-8108): разметка беседы показывает сообщения в том порядке, который даёт схема
(`afterbegin` для старых, `beforeend` для новых, CONTRACT-008 11.3), поэтому «без потерь» проверяется по множествам
номеров сообщений, а не по направлению вывода; кнопка «Показать более ранние» ищется подстрокой текста раздела
13.3. Курсор собирается из `Message.created_at` базы в формате контракта `before=<ISO>,<id>`.
"""
from datetime import datetime, timedelta
from html.parser import HTMLParser

import pytest
from django.utils import timezone

from tests import support
from tests import support_messenger as messenger

pytestmark = pytest.mark.django_db

EMPTY_HINT = "Чатов пока нет: напишите коллеге из карточки сотрудника"
MORE = "Показать более ранние"
MISSING_CHAT = 987654
HISTORY_LIMIT = 50

VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- разбор разметки (помощник только этого файла; образец — test_messenger_personal.py) -------------------------

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


def _flat(values):
    for value in values:
        if isinstance(value, (list, tuple, set, frozenset)):
            yield from _flat(value)
        else:
            yield value


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _list(document) -> _Node:
    lists = _q(document, id="messenger-list")
    assert len(lists) == 1, "нет #messenger-list (CONTRACT-008 12.2)"
    return lists[0]


def _list_ids(document) -> list[int]:
    return [int(row.attrs["data-chat-id"]) for row in _q(_list(document), data_chat_id=True)]


def _row(document, chat_id: int) -> _Node:
    rows = _q(document, data_chat_id=str(chat_id))
    assert len(rows) == 1, f"строк списка с data-chat-id={chat_id}: {len(rows)}"
    return rows[0]


def _message_ids(document) -> list[int]:
    return [int(node.attrs["data-message-id"]) for node in _q(document, data_message_id=True)]


def _cursor(message) -> str:
    """Курсор истории в формате контракта: `before=<ISO>,<id>` (UTC, раздел 10.1)."""
    return f"{message.created_at.isoformat()},{message.pk}"


def _history(session, chat, before=None):
    """`GET /messenger/chats/<id>/messages/` — фрагмент предыдущих сообщений (CONTRACT-008 10.2)."""
    params = {"chat": chat.pk}
    if before is not None:
        params["before"] = before
    return session.client.get(f"/messenger/chats/{chat.pk}/messages/", params, **support.HX)


def _some_messages(chat, author, count: int, *, same_at=None, base=None):
    """`count` сообщений подряд: время растёт по минуте, если не задано одно общее `same_at`."""
    messages = []
    for number in range(1, count + 1):
        created_at = same_at if same_at is not None else base + timedelta(minutes=number)
        messages.append(messenger.post(chat, author, f"Сообщение {number:03d}", created_at=created_at))
    return messages


# --- список: порядок, строка, личный диалог, пустой список --------------------------------------------------------

def test_list_orders_by_last_message_and_puts_empty_chats_last(clock):
    """FR-644: порядок — `COALESCE(last_message_at, created_at) DESC, id DESC`; чаты без сообщений — последними.

    `last_message_at DESC` без `COALESCE` поднял бы `NULL` наверх (в PostgreSQL `DESC` ставит `NULL` первыми);
    поэтому пустые чаты создаются раньше всех сообщений, а ожидаемый порядок задают три разных `last_message_at`
    и `created_at` двух пустых чатов между собой. Общий чат установки удалён: иначе его `created_at` (время
    миграции) оказался бы новее данных теста и закрыл проверку."""
    Chat = support.model("messenger.Chat")
    viewer = messenger.make_user(full_name="Смотрящий Порядок")
    empty_peer_a = messenger.make_user(full_name="Пустой Собеседник А")
    empty_peer_b = messenger.make_user(full_name="Пустой Собеседник Б")
    old_peer = messenger.make_user(full_name="Старый Собеседник")
    mid_peer = messenger.make_user(full_name="Средний Собеседник")
    new_peer = messenger.make_user(full_name="Новый Собеседник")
    Chat.objects.filter(kind="general").delete()
    assert not Chat.objects.filter(kind="general").exists()

    base = messenger.moscow(2026, 3, 10, 18, 0)
    clock.set(base - timedelta(hours=6))
    empty_a = messenger.personal(viewer, empty_peer_a)
    clock.set(base - timedelta(hours=5))
    empty_b = messenger.personal(viewer, empty_peer_b)
    clock.set(base - timedelta(hours=4))
    old_chat = messenger.group(viewer, [old_peer], title="Старая Группа")
    clock.set(base - timedelta(hours=3))
    mid_chat = messenger.personal(viewer, mid_peer)
    clock.set(base - timedelta(hours=2))
    new_chat = messenger.group(viewer, [new_peer], title="Новая Группа")
    clock.set(base - timedelta(hours=1))
    messenger.post(old_chat, old_peer, "Последнее в старой", created_at=base - timedelta(hours=3))
    messenger.post(mid_chat, mid_peer, "Последнее в средней", created_at=base - timedelta(hours=2))
    messenger.post(new_chat, new_peer, "Последнее в новой", created_at=base - timedelta(hours=1))

    assert (empty_a.last_message_at, empty_b.last_message_at) == (None, None)
    expected = [new_chat.pk, mid_chat.pk, old_chat.pk, empty_b.pk, empty_a.pk]

    with messenger.capture_sql() as sqls:
        fragment = viewer.client.get("/messenger/list/")
    assert fragment.status_code == 200, f"фрагмент списка: {fragment.status_code}"
    assert _list_ids(_tree(fragment)) == expected, (
        f"порядок фрагмента списка: {_list_ids(_tree(fragment))}")
    order_sql = [sql for sql in sqls if '"messenger_chat"' in sql and "COALESCE" in sql.upper()]
    assert order_sql, "порядок списка не по COALESCE(last_message_at, created_at) (CONTRACT-008 5.1)"
    assert any("last_message_at" in sql and "created_at" in sql for sql in order_sql), (
        f"ключ порядка списка: {order_sql[0][:160]}")

    page = viewer.client.get("/messenger/")
    assert page.status_code == 200, f"страница списка: {page.status_code}"
    assert _list_ids(_tree(page)) == expected, f"порядок страницы списка: {_list_ids(_tree(page))}"


def test_each_row_has_title_preview_time_and_unread_count(clock):
    """FR-644, FR-660: у каждой строки — название, превью последнего сообщения, время по Москве и число непрочитанных.

    Название: групповой — `title`, «Общий чат» — «Общий чат», личный — ФИО собеседника (CONTRACT-008 5.4);
    превью — `#chat-<id>-preview`, время — `time[data-at]` с ISO в `datetime` и «ДД.ММ.ГГГГ ЧЧ:ММ» по Москве,
    число — `#chat-<id>-unread[data-count]` (12.1–12.2). У «Общего чата» отметка прочтения стоит до сообщения,
    иначе база отсчёта даёт 0 (план «Прочтение и счётчики»)."""
    viewer = messenger.make_user(full_name="Смотрящий Строки")
    peer = messenger.make_user(full_name="Пишущий В Чаты")
    base = messenger.moscow(2026, 3, 12, 10, 0)
    clock.set(base - timedelta(hours=1))
    personal_chat = messenger.personal(viewer, peer)
    group_chat = messenger.group(viewer, [peer], title="Группа Со Счётчиком")
    general_chat = messenger.general()
    messenger.read(general_chat, viewer, base - timedelta(minutes=30))
    personal_msg = messenger.post(personal_chat, peer, "Личное превью",
                                  created_at=base - timedelta(minutes=20))
    group_msg = messenger.post(group_chat, peer, "Групповое превью",
                               created_at=base - timedelta(minutes=10))
    general_msg = messenger.post(general_chat, peer, "Общее превью", created_at=base)

    page = viewer.client.get("/messenger/")
    assert page.status_code == 200, f"страница списка: {page.status_code}"
    document = _tree(page)
    rows = _q(_list(document), data_chat_id=True)
    assert len(rows) == 3, f"строк списка: {len(rows)}"
    assert {int(row.attrs["data-chat-id"]) for row in rows} == {
        personal_chat.pk, group_chat.pk, general_chat.pk}

    cases = [
        (personal_chat, peer.user.full_name, personal_msg),
        (group_chat, "Группа Со Счётчиком", group_msg),
        (general_chat, "Общий чат", general_msg),
    ]
    for chat, title, message in cases:
        row = _row(document, chat.pk)
        body = row.text()
        assert title in body, f"в строке чата {chat.pk} нет названия {title!r}: {body!r}"
        preview = _q(row, id=f"chat-{chat.pk}-preview")
        assert len(preview) == 1, f"нет #chat-{chat.pk}-preview (CONTRACT-008 12.2)"
        assert preview[0].text() == message.text, (
            f"превью чата {chat.pk}: {preview[0].text()!r} вместо {message.text!r}")
        stamps = _q(row, "time", data_at=True)
        assert len(stamps) == 1, f"нет time[data-at] в строке чата {chat.pk} (CONTRACT-008 12.1)"
        assert _instant(stamps[0].attrs["datetime"]) == message.created_at, (
            f"момент строки чата {chat.pk}: {stamps[0].attrs['datetime']!r}")
        assert stamps[0].text() == messenger.moscow_text(message.created_at), (
            f"время строки чата {chat.pk}: {stamps[0].text()!r}")
        count = _q(row, id=f"chat-{chat.pk}-unread")
        assert len(count) == 1, f"нет #chat-{chat.pk}-unread (CONTRACT-008 12.2)"
        assert count[0].attrs.get("data-count") == "1", (
            f"data-count чата {chat.pk}: {count[0].attrs.get('data-count')!r}")
        assert count[0].text() == "1", f"число чата {chat.pk}: {count[0].text()!r}"


def test_personal_row_shows_peer_name_instead_of_title():
    """FR-644, FR-645: у личного диалога `title` пуст, а строка списка показывает ФИО собеседника, не своё имя.

    `page.chat_title(chat)` для личного диалога берёт ФИО второго участника (CONTRACT-008 5.4); в строке
    `[data-chat-id]` — та же подпись и ссылка на беседу (12.2)."""
    from apps.messenger.services import page as page_service

    viewer = messenger.make_user(full_name="Смотрящий Личное")
    peer = messenger.make_user(full_name="Собеседник Вместо Названия")
    chat = messenger.personal(viewer, peer)
    chat.refresh_from_db()
    messenger.post(chat, peer, "Превью личного диалога")

    assert chat.title == "", f"у личного диалога непустой title: {chat.title!r}"
    assert page_service.chat_title(chat) == peer.user.full_name, (
        f"chat_title личного диалога: {page_service.chat_title(chat)!r}")

    fragment = viewer.client.get("/messenger/list/")
    assert fragment.status_code == 200, f"фрагмент списка: {fragment.status_code}"
    row = _row(_tree(fragment), chat.pk)
    assert peer.user.full_name in row.text(), f"в строке нет ФИО собеседника: {row.text()!r}"
    assert viewer.user.full_name not in row.text(), (
        f"строка личного диалога показывает своё имя: {row.text()!r}")
    hrefs = [link.attrs.get("href", "") for link in row.walk() if link.attrs.get("href")]
    assert f"/messenger/chats/{chat.pk}/" in hrefs, f"строка без ссылки на беседу: {hrefs}"


def test_empty_list_shows_hint_to_write_colleague():
    """FR-644: пустой список показывает подсказку «Чатов пока нет: напишите коллеге из карточки сотрудника».

    У нового сотрудника нет личных и групповых чатов; «Общий чат» выключен (строка удалена), иначе список не пуст
    (CONTRACT-008 12.1 — `[data-empty-state="messenger"]`, 10.2)."""
    Chat = support.model("messenger.Chat")
    Chat.objects.filter(kind="general").delete()
    viewer = messenger.make_user(full_name="Новый Без Чатов")

    page = viewer.client.get("/messenger/")
    assert page.status_code == 200, f"страница списка: {page.status_code}"
    document = _tree(page)
    states = _q(document, data_empty_state="messenger")
    assert len(states) == 1, "нет [data-empty-state=\"messenger\"] (CONTRACT-008 12.1)"
    assert EMPTY_HINT in states[0].text(), f"подсказка пустого списка: {states[0].text()!r}"
    assert EMPTY_HINT in page.content.decode("utf-8"), "текста подсказки нет в разметке страницы"
    assert not _q(document, data_chat_id=True), "пустой список показал строки чатов"

    fragment = viewer.client.get("/messenger/list/")
    assert fragment.status_code == 200, f"фрагмент списка: {fragment.status_code}"
    assert not _q(_tree(fragment), data_chat_id=True), "фрагмент пустого списка показал строки"


# --- число запросов и параметры фильтра ---------------------------------------------------------------------------

def test_list_sql_count_does_not_grow_with_number_of_chats():
    """FR-644, NFR-703: число SQL-запросов списка не зависит от числа чатов — на 1 и на 12 чатах равно.

    Список собирается одним запросом с `LATERAL` (CONTRACT-008 5.1: название, превью, время, число непрочитанных).
    «Общий чат» удалён, чтобы строк было ровно столько, сколько диалогов теста; прогрев перед замером снимает
    разовые запросы сессии и кэша прав, как в `test_feed_page_2`. Запросы к `messenger_chat` тоже не растут."""
    Chat = support.model("messenger.Chat")
    Chat.objects.filter(kind="general").delete()
    counts: dict[int, int] = {}
    chat_queries: dict[int, int] = {}
    for number in (1, 12):
        viewer = messenger.make_user(full_name=f"Считающий Запросы {number:02d}")
        for index in range(number):
            peer = messenger.make_user(full_name=f"Собеседник Счёта {number:02d}-{index:02d}")
            chat = messenger.personal(viewer, peer)
            messenger.post(chat, peer, f"Сообщение {index:02d}")
        warm = viewer.client.get("/messenger/list/")
        assert warm.status_code == 200, f"прогрев списка: {warm.status_code}"
        with messenger.capture_sql() as sqls:
            response = viewer.client.get("/messenger/list/")
        assert response.status_code == 200, f"список из {number} чатов: {response.status_code}"
        rows = _q(_list(_tree(response)), data_chat_id=True)
        assert len(rows) == number, f"строк списка при {number} чатах: {len(rows)}"
        counts[number] = len(sqls)
        chat_queries[number] = sum(
            1 for sql in sqls
            if '"messenger_chat"' in sql and sql.lstrip().upper().startswith("SELECT"))

    assert counts[1] == counts[12], f"число запросов списка зависит от числа чатов: {counts}"
    assert chat_queries[1] == chat_queries[12] >= 1, (
        f"запросы к messenger_chat растут с числом чатов: {chat_queries}")


def test_filter_q_by_title_and_peer_name_passes_values_as_parameters():
    """FR-644, NFR-703: `q` фильтрует названия групп и ФИО собеседников на сервере, значения — параметры SQL.

    Совпадают групповой чат по `title` и личный диалог по ФИО собеседника (CONTRACT-008 5.1); посторонний чат
    в выдачу не входит. Пробное значение есть среди параметров захваченных запросов и его нет в тексте SQL до
    подстановки (правила среза, NFR-703). Неизвестные ключи строки запроса отбрасываются (10.1, белый список
    `q`, `to`, `before`, `f`, `page`, `chat`), значение с SQL-текстом до запроса не доходит."""
    Chat = support.model("messenger.Chat")
    viewer = messenger.make_user(full_name="Фильтрующий Список")
    peer = messenger.make_user(full_name="Искомый Собеседник")
    stranger = messenger.make_user(full_name="Посторонний Собеседник")
    personal_chat = messenger.personal(viewer, peer)
    messenger.post(personal_chat, peer, "Превью искомого диалога")
    group_hit = messenger.group(viewer, [peer], title="Искомый Проект")
    messenger.post(group_hit, viewer, "Превью искомой группы")
    group_miss = messenger.group(viewer, [stranger], title="Другой Проект")
    messenger.post(group_miss, viewer, "Превью другой группы")

    with messenger.queries_with_params() as pairs:
        found = viewer.client.get("/messenger/list/", {"q": "Искомый"})
    assert found.status_code == 200, f"список с q: {found.status_code}"
    ids = {int(row.attrs["data-chat-id"]) for row in _q(_list(_tree(found)), data_chat_id=True)}
    assert ids == {personal_chat.pk, group_hit.pk}, f"строки по q: {ids}"
    assert group_miss.pk not in ids, "поиск по списку показал несовпавший чат"
    sql_text = " ".join(sql for sql, _ in pairs).lower()
    values = [str(value) for _, params in pairs for value in _flat(params)]
    assert "искомый" not in sql_text, "значение q склеено в текст SQL"
    assert any("искомый" in value.lower() for value in values), "значение q не передано параметром"

    attack = "НетТакого' OR 1=1 --"
    with messenger.queries_with_params() as pairs:
        refused = viewer.client.get("/messenger/list/", {"q": attack})
    assert refused.status_code == 200, f"список с SQL-текстом в q: {refused.status_code}"
    assert not _q(_tree(refused), data_chat_id=True), "значение с SQL-текстом дало строки"
    for sql, _ in pairs:
        assert "OR 1=1" not in sql and "DROP" not in sql.upper(), f"SQL-текст из q дошёл до запроса: {sql[:80]}"

    unknown = "ДропниТаблицу"
    with messenger.queries_with_params() as pairs:
        extra = viewer.client.get("/messenger/list/", {"q": "Искомый", "kind": unknown, "debug": "1"})
    assert extra.status_code == 200, f"список с лишними ключами: {extra.status_code}"
    extra_ids = {int(row.attrs["data-chat-id"]) for row in _q(_list(_tree(extra)), data_chat_id=True)}
    assert extra_ids == ids, f"лишний ключ изменил выдачу: {extra_ids}"
    sql_text = " ".join(sql for sql, _ in pairs).lower()
    values = [str(value).lower() for _, params in pairs for value in _flat(params)]
    assert unknown.lower() not in sql_text, "значение неизвестного ключа склеено в текст SQL"
    assert not any(unknown.lower() in value for value in values), (
        "значение неизвестного ключа дошло до параметров запроса")
    assert Chat.objects.filter(pk__in=[personal_chat.pk, group_hit.pk, group_miss.pk]).count() == 3


# --- история: курсор 50/50/20, одинаковое время, первое сообщение --------------------------------------------------

def test_history_returns_50_then_50_then_20_by_cursor_without_gaps():
    """FR-658: история — 50, 50 и 20 сообщений по курсору `(created_at, id)` без потерь и повторов.

    Страница беседы — последние 50; старые — `before=<ISO>,<id>` (`WHERE (created_at, id) < (%s, %s)
    ORDER BY created_at DESC LIMIT 50`, без `OFFSET`, CONTRACT-008 5.4, 10.2). Значение курсора уходит параметром
    SQL; третья порция — 20 сообщений, кнопки «Показать более ранние» больше нет."""
    viewer = messenger.make_user(full_name="Читающий Историю")
    peer = messenger.make_user(full_name="Пишущий Историю")
    chat = messenger.personal(viewer, peer)
    base = timezone.now() - timedelta(days=400)
    messages = _some_messages(chat, peer, 120, base=base)
    all_ids = {message.pk for message in messages}

    page = viewer.client.get(f"/messenger/chats/{chat.pk}/")
    assert page.status_code == 200, f"беседа: {page.status_code}"
    first_page = _message_ids(_tree(page))
    assert len(first_page) == HISTORY_LIMIT, f"на странице беседы сообщений: {len(first_page)}"
    assert set(first_page) == {message.pk for message in messages[-HISTORY_LIMIT:]}, (
        "страница беседы — не последние 50 сообщений")
    assert MORE in page.content.decode("utf-8"), "на странице нет кнопки «Показать более ранние»"

    older = messages[-HISTORY_LIMIT]
    with messenger.queries_with_params() as pairs:
        second = _history(viewer, chat, _cursor(older))
    assert second.status_code == 200, f"вторая порция истории: {second.status_code}"
    second_ids = _message_ids(_tree(second))
    assert len(second_ids) == HISTORY_LIMIT, f"во второй порции сообщений: {len(second_ids)}"
    assert set(second_ids) == {message.pk for message in messages[20:70]}, (
        "вторая порция — не предыдущие 50 сообщений")
    assert MORE in second.content.decode("utf-8"), "во второй порции нет кнопки «Показать более ранние»"
    assert "<html" not in second.content.decode("utf-8").lower(), "история вернула страницу, а не фрагмент"
    texts = [sql for sql, _ in pairs]
    assert any('"messenger_message"' in sql for sql in texts), "история не читала messenger_message"
    for sql in texts:
        if '"messenger_message"' in sql:
            assert "OFFSET" not in sql.upper(), f"история использует OFFSET вместо курсора: {sql[:120]}"
    values = [value for _, params in pairs for value in _flat(params)]
    assert any(str(older.pk) == str(value) for value in values), "номер курсора — не параметр SQL"

    third = _history(viewer, chat, _cursor(messages[20]))
    assert third.status_code == 200, f"третья порция истории: {third.status_code}"
    third_ids = _message_ids(_tree(third))
    assert len(third_ids) == 20, f"в третьей порции сообщений: {len(third_ids)}"
    assert set(third_ids) == {message.pk for message in messages[:20]}, (
        "третья порция — не первые 20 сообщений")
    assert MORE not in third.content.decode("utf-8"), "кнопка «Показать более ранние» осталась на последней порции"

    union = first_page + second_ids + third_ids
    assert len(union) == 120, f"порций всего сообщений: {len(union)}"
    assert len(set(union)) == 120, "история повторила сообщение"
    assert set(union) == all_ids, "история потеряла сообщения"


def test_hundred_messages_with_same_created_at_cursor_has_no_loss_or_repeat():
    """FR-658: 100 сообщений с одинаковым `created_at` делятся курсором по `id` без потерь и повторов.

    Курсор `(created_at, id) < (%s, %s)` (CONTRACT-008 5.4): при равном времени решает `id`, поэтому вторая
    порция — ровно 50 самых старых по номеру, а третья пуста."""
    viewer = messenger.make_user(full_name="Читающий Одинаковое")
    peer = messenger.make_user(full_name="Пишущий Одинаковое")
    chat = messenger.personal(viewer, peer)
    same_at = timezone.now() - timedelta(days=200)
    messages = _some_messages(chat, peer, 100, same_at=same_at)
    assert len({message.created_at for message in messages}) == 1, "время сообщений различается"

    page = viewer.client.get(f"/messenger/chats/{chat.pk}/")
    assert page.status_code == 200, f"беседа: {page.status_code}"
    first_page = _message_ids(_tree(page))
    assert len(first_page) == HISTORY_LIMIT, f"на странице сообщений: {len(first_page)}"
    assert set(first_page) == {message.pk for message in messages[50:]}, (
        "при равном времени страница — не последние 50 по id")

    second = _history(viewer, chat, _cursor(messages[50]))
    assert second.status_code == 200, f"вторая порция истории: {second.status_code}"
    second_ids = _message_ids(_tree(second))
    assert len(second_ids) == HISTORY_LIMIT, f"во второй порции сообщений: {len(second_ids)}"
    assert set(second_ids) == {message.pk for message in messages[:50]}, (
        "при равном времени курсор потерял или повторил сообщения")
    assert not set(first_page) & set(second_ids), "порции истории пересекаются"

    third = _history(viewer, chat, _cursor(messages[0]))
    assert third.status_code == 200, f"третья порция истории: {third.status_code}"
    assert not _message_ids(_tree(third)), "после первого сообщения история не пуста"
    assert MORE not in third.content.decode("utf-8"), "кнопка «Показать более ранние» осталась в конце истории"

    union = first_page + second_ids
    assert len(union) == 100 and set(union) == {message.pk for message in messages}


def test_history_reaches_first_message():
    """FR-658: история доступна до первого сообщения: короткая беседа показывает все, курсор первого даёт пусто.

    Кнопки «Показать более ранние» нет, когда страница короткая; неверный `before` читается как отсутствующий —
    отдаётся первая (последняя по времени) порция (CONTRACT-008 10.1–10.2)."""
    viewer = messenger.make_user(full_name="Дочитывающий Историю")
    peer = messenger.make_user(full_name="Пишущий Первое")
    chat = messenger.personal(viewer, peer)
    messages = _some_messages(chat, peer, 7, base=timezone.now() - timedelta(hours=3))
    all_ids = {message.pk for message in messages}

    page = viewer.client.get(f"/messenger/chats/{chat.pk}/")
    assert page.status_code == 200, f"беседа: {page.status_code}"
    assert set(_message_ids(_tree(page))) == all_ids, "короткая беседа показала не все сообщения"
    assert MORE not in page.content.decode("utf-8"), "кнопка «Показать более ранние» есть у короткой беседы"

    first = messages[0]
    older = _history(viewer, chat, _cursor(first))
    assert older.status_code == 200, f"история до первого сообщения: {older.status_code}"
    assert not _message_ids(_tree(older)), "до первого сообщения история не пуста"
    assert MORE not in older.content.decode("utf-8"), "кнопка «Показать более ранние» есть до первого сообщения"

    for bad in ("abc", "1' OR 1=1 --", ""):
        again = _history(viewer, chat, bad)
        assert again.status_code == 200, f"неверный before={bad!r}: {again.status_code}"
        assert set(_message_ids(_tree(again))) == all_ids, (
            f"неверный before={bad!r} не прочитан как отсутствующий")


# --- страница беседы и невидимый чат -------------------------------------------------------------------------------

def test_chat_page_has_header_input_and_ws_node_with_chat_id():
    """FR-658, FR-673: страница беседы — шапка, история, поле ввода и узел `/ws/messenger/?chat=<id>`.

    Зацепки: `[data-messenger-page="chat"]`, `[data-chat-kind]`, `#messenger-messages`, `#messenger-form` с
    `textarea[name="text"]`, `[data-ws]` с `hx-ext="ws"` и `ws-connect="/ws/messenger/?chat=<id>"` в состоянии
    `connecting` (решение К19), кнопка «Назад» на `/messenger/` (12.3–12.4). Соединений мессенджера на странице
    одно (12.4)."""
    viewer = messenger.make_user(full_name="Смотрящий Беседу")
    peer = messenger.make_user(full_name="Второй Участник Беседы")
    chat = messenger.group(viewer, [peer], title="Шапка Беседы")
    messages = [messenger.post(chat, peer, f"Сообщение в беседе {number}") for number in (1, 2)]

    page = viewer.client.get(f"/messenger/chats/{chat.pk}/")
    assert page.status_code == 200, f"беседа: {page.status_code}"
    body = page.content.decode("utf-8")
    document = _tree(page)

    assert _q(document, data_messenger_page="chat"), "нет [data-messenger-page=\"chat\"] (CONTRACT-008 12.1)"
    assert "Шапка Беседы" in body, "в шапке беседы нет названия чата"
    assert peer.user.full_name in body, "в шапке беседы нет участника"
    assert _q(document, data_chat_kind="group"), "нет [data-chat-kind=\"group\"] (CONTRACT-008 12.2)"

    containers = _q(document, id="messenger-messages")
    assert len(containers) == 1, "нет #messenger-messages (CONTRACT-008 12.3)"
    assert set(_message_ids(containers[0])) == {message.pk for message in messages}, (
        "в контейнере истории не все сообщения")

    forms = _q(document, id="messenger-form")
    assert len(forms) == 1, "нет #messenger-form (CONTRACT-008 12.3)"
    assert _q(forms[0], "textarea", name="text"), "в форме отправки нет textarea[name=\"text\"]"

    ws_nodes = _q(document, data_ws=True)
    assert len(ws_nodes) == 1, f"узлов [data-ws]: {len(ws_nodes)} (CONTRACT-008 12.4)"
    ws = ws_nodes[0]
    assert ws.attrs.get("hx-ext") == "ws", f"hx-ext узла соединения: {ws.attrs.get('hx-ext')!r}"
    assert ws.attrs.get("ws-connect") == f"/ws/messenger/?chat={chat.pk}", (
        f"ws-connect узла соединения: {ws.attrs.get('ws-connect')!r}")
    assert ws.attrs.get("data-ws") == "connecting", f"состояние соединения: {ws.attrs.get('data-ws')!r}"
    assert body.count("/ws/messenger/") == 1, (
        f"соединений /ws/messenger/ на странице: {body.count('/ws/messenger/')}")

    back = _q(document, data_messenger_back=True)
    assert len(back) == 1, "нет [data-messenger-back] (CONTRACT-008 12.3)"
    assert back[0].attrs.get("href") == "/messenger/", (
        f"кнопка «Назад» ведёт на {back[0].attrs.get('href')!r}")


def test_invisible_chat_page_is_404_like_missing():
    """FR-669: страница невидимого чата отвечает 404, неотличимым от несуществующего, без названия и переписки.

    Правило среза: чужой, несуществующий и удалённый чат отвечают одинаково — 404 обычной страницы «Не найдено»
    без подробностей (CONTRACT-008, «Правила для всех тестов среза», 10.1); сравнение — в пределах одного клиента
    (`support.same_failure`)."""
    author = messenger.make_user(full_name="Автор Закрытого Чата")
    friend = messenger.make_user(full_name="Собеседник Закрытого Чата")
    stranger = messenger.make_user(full_name="Посторонний Смотрящий")
    chat = messenger.personal(author, friend)
    marker = "Секретная переписка двух сотрудников"
    messenger.post(chat, author, marker)

    foreign = stranger.client.get(f"/messenger/chats/{chat.pk}/")
    missing = stranger.client.get(f"/messenger/chats/{MISSING_CHAT}/")
    assert foreign.status_code == 404, f"чужой чат: {foreign.status_code}"
    assert missing.status_code == 404, f"несуществующий чат: {missing.status_code}"
    assert support.same_failure(foreign, missing), "404 чужого чата отличается от 404 несуществующего"
    body = foreign.content.decode("utf-8")
    assert marker not in body, "404 показал текст переписки"
    assert friend.user.full_name not in body, "404 показал участника чужого чата"