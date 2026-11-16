"""T-8118: тесты поиска мессенджера (FR-668, FR-669, NFR-703).

Источники: TASKS-008 T-8118 (точный список имён), PLAN-008 «Поиск» (векторы с `regexp_replace` маркеров, поставщик
`messenger` после «Ленты», видимость в том же SQL, строка выдачи, стоп-слова `numnode`, потолок 300, поиск по
беседе), CONTRACT-008: раздел 9 (таблица поиска), 3.4 (`search_providers`), 5.4 (`search.vectors`, `chat_search`),
5.7 (`capture_sql`, `queries_with_params`), 10.2 (`GET /messenger/chats/<id>/search/?q=`), 12.1 (`time[data-at]`),
12.3 (`[data-messenger-search]`), 12.6 (`section[data-search-group="messenger"]`).

Проверки: поставщик `("messenger", "Мессенджер", 61)` после «Ленты» и доступен вошедшему; слово из своего чата даёт
строку «<чат>, <ФИО>, <дата по Москве> — <отрывок 100>» с адресом `/messenger/chats/<id>/#m<id>`; чужой и покинутый
чат не находятся и не считаются; цепочка узлов и включённый «Общий чат» стоят в том же SQL; слова запроса и цепочка
уходят параметрами, в тексте SQL ввода нет; число с потолком 300; поиск по беседе отдаёт только её сообщения,
подсветку и якорь `#m<id>`; вектор пересчитывается в отправке, правке и удалении, удалённое и старый текст не
находятся; стоп-слова дают пусто без ошибки; маркеры `@[u…]`/`@[c…]` не ломают поиск; без мессенджера группы нет.

Код среза на уровне модуля не импортируется (правила для всех тестов среза): модели — через `support.model`,
службы и поставщик — ленивыми импортами внутри тестов, поэтому `pytest --collect-only` проходит до появления кода.
Секретов и ПДн нет: адреса и телефоны не создаются, ФИО — вымышленные.

Допущения писателя (см. отчёт T-8118): подсказка строки склейки — «Мессенджер» (раздел 9 называет её для всех
строк группы); `time[data-at]` проверяется во фрагменте поиска по беседе (12.1 привязывает его к T-8118, а другого
места с временем эти десять тестов не открывают); подсветка `ts_headline` принимается в любом из тегов
`b`/`strong`/`mark` (контракт называет только функцию, не тег).
"""
import importlib
import re
from datetime import datetime, timedelta, timezone as dt_timezone
from html.parser import HTMLParser

import pytest
from django.db import connection
from django.utils import timezone

from tests import support
from tests import support_messenger as sm

pytestmark = pytest.mark.django_db

UTC = dt_timezone.utc
MISSING = 987650
GROUP_TITLE = "Проект Альфа"
MESSENGER = "Мессенджер"
HIGHLIGHT = re.compile(r"(?is)<(b|strong|mark)\b[^>]*>[^<]*коммутатор")
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- разметка (помощник только этого файла; образец — test_messenger_messages.py) -----------------------------

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


def _instant(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


# --- помощники файла (общие помощники среза не правятся) ------------------------------------------------------

def _employee(name: str, **extra):
    """Действующий сотрудник с клиентом (`sm.make_user`)."""
    return sm.make_user(full_name=name, **extra)


def _svc():
    return importlib.import_module("apps.messenger.services.search")


def _parsed(query: str):
    from apps.search.parse import parse

    return parse(query)


def _provider():
    """Единственная запись `search_providers` мессенджера (раздел 3.4)."""
    found = _svc().search_providers()
    assert len(found) == 1, f"поставщиков мессенджера: {len(found)}"
    return found[0]


def _fresh(user):
    return support.model("core.User").objects.get(pk=user.pk)


def _rows(user, query: str, limit: int = 50, offset: int = 0) -> list:
    return _provider().search(_fresh(user), _parsed(query), limit, offset)


def _urls(user, query: str, limit: int = 50, offset: int = 0) -> list[str]:
    return [row.url for row in _rows(user, query, limit, offset)]


def _count(user, query: str) -> tuple:
    return _provider().count(_fresh(user), _parsed(query))


def _group_keys(user) -> list[str]:
    from apps.search import services

    return [provider.key for provider in services.providers(_fresh(user))]


def _world(title: str = GROUP_TITLE):
    """Групповой чат с названием: автор «Сидорова Анна» и читатель «Петров Пётр»."""
    author = _employee("Сидорова Анна")
    reader = _employee("Петров Пётр")
    return author, reader, sm.group(author, [reader], title=title)


def _chat_url(chat) -> str:
    return f"/messenger/chats/{chat.pk}/"


def _message_url(chat, message) -> str:
    return f"{_chat_url(chat)}#m{message.pk}"


def _chat_search_url(chat) -> str:
    return f"/messenger/chats/{chat.pk}/search/"


def _values(params) -> list:
    """Параметры SQL одним списком (массивы раскрыты)."""
    out = []
    for value in params or ():
        out.extend(value if isinstance(value, (list, tuple, set, frozenset)) else [value])
    return out


def _arrays(params) -> list[set[int]]:
    """Целочисленные массивы среди параметров (цепочка узлов уходит именно массивом)."""
    found = []
    for value in _values(params):
        if isinstance(value, (list, tuple, set, frozenset)) and value:
            if all(isinstance(item, int) and not isinstance(item, bool) for item in value):
                found.append({int(item) for item in value})
    return found


def _delete_vector(message):
    """Вектор сообщения — пустой (NULL или пустой `tsvector`) после удаления."""
    Message = support.model("messenger.Message")
    assert Message._meta.db_table == "messenger_message"
    with connection.cursor() as cursor:
        cursor.execute("SELECT search FROM messenger_message WHERE id = %s", [message.pk])
        return cursor.fetchone()[0]


def _matches(message, word: str) -> bool:
    """Есть ли слово в векторе сообщения (через `to_tsquery` базы)."""
    with connection.cursor() as cursor:
        cursor.execute("SELECT search @@ to_tsquery('russian', %s) FROM messenger_message WHERE id = %s",
                       [word, message.pk])
        return cursor.fetchone()[0]


# --- 1. слово из своего чата ----------------------------------------------------------------------------------

def test_word_in_own_chat_found_with_chat_author_time_and_snippet():
    """FR-668: слово из своего чата находит сообщение; строка — «<название чата>, <ФИО>, <дата по Москве> —
    <отрывок>» с подсказкой «Мессенджер» и адресом `/messenger/chats/<id>/#m<id>`; отрывок не длиннее 100 знаков с
    «…»; на странице `/search/` строка стоит в группе `section[data-search-group="messenger"]` с заголовком
    «Мессенджер»."""
    author, reader, chat = _world()
    sent_at = datetime(2026, 5, 11, 21, 30, tzinfo=UTC)  # по Москве уже 12.05.2026 00:30
    message = sm.post(chat, author, "Заменили коммутатор в серверной", created_at=sent_at)
    sm.post(chat, author, "Совсем другое сообщение про принтеры", created_at=sent_at + timedelta(minutes=1))

    rows = _rows(reader.user, "коммутатор")
    assert [row.url for row in rows] == [_message_url(chat, message)]
    row = rows[0]
    assert row.title == f"{GROUP_TITLE}, Сидорова Анна, 12.05.2026 — Заменили коммутатор в серверной", row.title
    assert row.subtitle == MESSENGER, f"подсказка строки: {row.subtitle!r}"

    long_message = sm.post(chat, author, "маршрутизатор " + "слово " * 60,
                           created_at=sent_at + timedelta(minutes=2))
    (long_row,) = _rows(reader.user, "маршрутизатор")
    assert long_row.url == _message_url(chat, long_message)
    snippet = long_row.title.split(" — ", 1)[1]
    assert snippet.startswith("маршрутизатор"), snippet
    assert snippet.endswith("…") and len(snippet) <= 100, f"отрывок: {snippet!r}"

    page = reader.client.get("/search/", {"q": "коммутатор"})
    assert page.status_code == 200, f"/search/: {page.status_code}"
    section = _q1(_tree(page), "section", data_search_group="messenger")
    assert MESSENGER in section.text(), section.text()
    link = _q1(section, "a", href=_message_url(chat, message))
    assert "коммутатор" in link.text(), link.text()


# --- 2. чужое не находится и не считается ---------------------------------------------------------------------

def test_word_in_foreign_chat_absent_and_not_counted():
    """FR-668, FR-669: сообщение чужого чата не попадает ни в выдачу, ни в число; участник находит его и число
    точное; покинувший чат (строка `ChatMember` с `left_at`) тоже не находит и не считает."""
    author, reader, chat = _world()
    outsider = _employee("Посторонний Сотрудник")
    message = sm.post(chat, author, "Хризантемы в закрытом чате")

    assert [row.url for row in _rows(reader.user, "хризантемы")] == [_message_url(chat, message)]
    assert _count(reader.user, "хризантемы") == (1, False)
    assert _rows(outsider.user, "хризантемы") == []
    assert _count(outsider.user, "хризантемы") == (0, False)

    leaver = _employee("Вышедший Сотрудник")
    left_chat = sm.group(author, [leaver], title="Чат до выхода")
    sm.post(left_chat, author, "Хризантемы после выхода")
    support.model("messenger.ChatMember").objects.filter(chat=left_chat, user=leaver.user).update(
        left_at=timezone.now())
    assert _rows(leaver.user, "хризантемы") == []
    assert _count(leaver.user, "хризантемы") == (0, False)
    assert len(_rows(author.user, "хризантемы")) == 2
    assert _count(author.user, "хризантемы") == (2, False)


# --- 3. поставщик ---------------------------------------------------------------------------------------------

def test_provider_order_61_after_feed_and_group_title():
    """FR-668: в точке `search_providers` одна запись из `apps.messenger`; поставщик
    `("messenger", "Мессенджер", 61)`; в сборщике поиска группа идёт после «Ленты» (60); доступен вошедшему
    сотруднику и администратору портала; на странице `/search/` группа «Мессенджер» стоит после «Ленты»."""
    from apps.core import extensions
    from tests import support_feed as fd

    author, searcher, chat = _world()
    admin = sm.as_admin(full_name="Администратор Портала")
    registered = [func for func in extensions.registered("search_providers")
                  if func.__module__.startswith("apps.messenger")]
    assert len(registered) == 1, f"записей мессенджера в search_providers: {len(registered)}"

    provider = _provider()
    assert (provider.key, provider.title, provider.order) == ("messenger", MESSENGER, 61)
    for name in ("search", "count", "available"):
        assert callable(getattr(provider, name)), f"поле {name} не функция"

    for session in (searcher, admin):
        assert provider.available(_fresh(session.user)) is True
        assert "messenger" in _group_keys(session.user)
    keys = _group_keys(searcher.user)
    assert "feed" in keys and "messenger" in keys
    assert keys.index("feed") < keys.index("messenger"), f"порядок групп: {keys}"

    sm.post(chat, author, "Ромашка в чате", created_at=sm.moscow(2026, 5, 12, 10, 0))
    fd.make_post(fd.as_writer().user, to=("all",), text="Ромашка в ленте")
    page = searcher.client.get("/search/", {"q": "ромашка"}).content.decode("utf-8")
    assert 'data-search-group="feed"' in page and 'data-search-group="messenger"' in page
    assert MESSENGER in _q1(_tree(page), "section", data_search_group="messenger").text()
    assert page.index('data-search-group="feed"') < page.index('data-search-group="messenger"')


# --- 4. поиск по беседе ---------------------------------------------------------------------------------------

def test_chat_search_returns_only_its_messages_available_to_member():
    """FR-668: `GET /messenger/chats/<id>/search/?q=` отдаёт фрагмент только с сообщениями этой беседы, доступной
    участнику: чужое сообщение и сообщение другого чата не попадают, найденное подсвечено `ts_headline`, у него
    `time[data-at]` и якорь `#m<id>`; содержимое файла не ищется; поле `[data-messenger-search]` есть в беседе;
    постороннему — 404, неотличимый от несуществующего чата."""
    author, reader, chat = _world()
    at = sm.moscow(2026, 5, 12, 14, 5)
    hit = sm.post(chat, author, "Заменили коммутатор доступа", created_at=at)
    sm.post(chat, reader, "Сообщение без искомого слова", created_at=at + timedelta(minutes=1))
    other_chat = sm.group(author, [reader], title="Соседний чат")
    sm.post(other_chat, author, "Коммутатор в другом чате", created_at=at + timedelta(minutes=2))
    attachment = sm.attach(chat, "отчёт.txt", "хризолитовый отчёт о закупках".encode("utf-8"))
    support.model("messenger.MessageAttachment").objects.filter(pk=attachment.pk).update(message=hit)

    url = _chat_search_url(chat)
    response = reader.client.get(url, {"q": "коммутатор"})
    assert response.status_code == 200, f"{url}: {response.status_code}"
    fragment = _html(response)
    assert f"#m{hit.pk}" in fragment, "во фрагменте нет якоря найденного сообщения"
    assert "другом чате" not in fragment, "во фрагмент попало сообщение другого чата"
    assert "без искомого" not in fragment, "во фрагмент попало сообщение без искомого слова"
    assert HIGHLIGHT.search(fragment), "нет подсветки ts_headline вокруг найденного слова"
    root = _tree(response)
    stamps = [node for node in _q(root, "time", data_at=True)
              if node.attrs.get("datetime") and _instant(node.attrs["datetime"]) == at]
    assert stamps, "у найденного сообщения нет time[data-at] с его временем (12.1)"
    assert stamps[0].text() == sm.moscow_text(at), stamps[0].text()

    chat_page = reader.client.get(_chat_url(chat))
    assert chat_page.status_code == 200
    assert _q(_tree(chat_page), data_messenger_search=True), "в беседе нет поля [data-messenger-search] (12.3)"

    empty = reader.client.get(url, {"q": "хризолитовый"})
    assert empty.status_code == 200
    assert "хризолитовый" not in _html(empty), "поиск заглянул в содержимое файла"

    outsider = _employee("Посторонний Наблюдатель")
    missing = f"/messenger/chats/{MISSING}/search/"
    denied = outsider.client.get(url, {"q": "коммутатор"})
    unknown = outsider.client.get(missing, {"q": "коммутатор"})
    assert denied.status_code == 404, f"чужой чат: {denied.status_code}"
    assert support.same_failure(denied, unknown), "404 чужого чата отличается от 404 несуществующего"


# --- 5. удалённое, правка и пересчёт вектора ------------------------------------------------------------------

def test_deleted_and_old_edited_text_not_found(django_capture_on_commit_callbacks):
    """FR-657, FR-668: вектор пересчитывается в транзакциях отправки, правки и удаления: новое сообщение находится до
    действий «после фиксации», после правки старый текст не находится, а новый находится; удалённое сообщение не
    находится и не считается, его вектор пуст."""
    from apps.messenger.services import messages

    author, reader, chat = _world()
    neighbour = sm.post(chat, author, "Соседнее сообщение про кофемашину")
    assert _count(reader.user, "кофемашину") == (1, False)

    with django_capture_on_commit_callbacks(execute=False):
        sent = messages.send(chat, author.user, "Привезли холодильник")
        assert _urls(reader.user, "холодильник") == [_message_url(chat, sent)], "вектор отправки не пересчитан"

        messages.edit(sent, author.user, "Привезли чайник")
        assert _urls(reader.user, "холодильник") == [], "старый текст правки находится"
        assert _urls(reader.user, "чайник") == [_message_url(chat, sent)], "вектор правки не пересчитан"
        assert _matches(sent, "чайник") and not _matches(sent, "холодильник")

        doomed = messages.send(chat, author.user, "Уйдёт про незабудки")
        assert _urls(reader.user, "незабудки") == [_message_url(chat, doomed)]
        messages.delete(doomed, author.user)
        assert _rows(reader.user, "незабудки") == [], "удалённое сообщение находится"
        assert _count(reader.user, "незабудки") == (0, False)
        assert not _delete_vector(doomed), f"у удалённого остался вектор: {_delete_vector(doomed)!r}"

    assert _urls(reader.user, "кофемашину") == [_message_url(chat, neighbour)], "правка задела соседнее сообщение"


# --- 6. стоп-слова --------------------------------------------------------------------------------------------

def test_stop_word_gives_empty_without_error():
    """FR-668: запрос из одних стоп-слов («как», «что», «как что») не даёт ошибки — выдача пуста, число
    `(0, False)`; стоп-слово рядом со значимым отбрасывается, значимое находит сообщение."""
    author, reader, chat = _world()
    message = sm.post(chat, author, "Как обновить прошивку, что делать с коммутатором")
    for query in ("как", "что", "как что"):
        parsed = _parsed(query)
        assert parsed.hint == "", f"подсказка на {query!r}: {parsed.hint!r}"
        assert _provider().search(_fresh(reader.user), parsed, 20, 0) == [], query
        assert _provider().count(_fresh(reader.user), parsed) == (0, False), query
    assert _urls(reader.user, "как прошивку") == [_message_url(chat, message)]


# --- 7. без мессенджера ---------------------------------------------------------------------------------------

def test_without_messenger_no_group():
    """FR-668: без модуля `messenger` группы «Мессенджер» нет ни в сборщике, ни на странице `/search/`, прочие
    группы работают; с модулем группа возвращается."""
    from tests import support_feed as fd

    author, reader, chat = _world()
    sm.post(chat, author, "Ромашка в чате")
    fd.make_post(fd.as_writer().user, to=("all",), text="Ромашка в ленте")

    page = reader.client.get("/search/", {"q": "ромашка"}).content.decode("utf-8")
    assert 'data-search-group="messenger"' in page
    with sm.without_messenger():
        keys = _group_keys(reader.user)
        assert "messenger" not in keys and "feed" in keys, f"группы без мессенджера: {keys}"
        page = reader.client.get("/search/", {"q": "ромашка"}).content.decode("utf-8")
        assert 'data-search-group="messenger"' not in page
        assert 'data-search-group="feed"' in page, "без мессенджера пропала группа «Лента»"
    assert "messenger" in _group_keys(reader.user)


# --- 8. SQL: видимость, цепочка узлов, параметры ---------------------------------------------------------------

def test_search_sql_passes_words_and_unit_chain_as_parameters():
    """NFR-703: слова запроса уходят параметрами (в тексте SQL ввода нет), цепочка узлов — массивом `= ANY(%s)`,
    условие включённого «Общего чата» стоит в том же SQL; сотрудник узла находит сообщение чата отдела, сотрудник без
    узла — нет; запрос с кавычками и знаками `tsquery` не ломает выдачу и не трогает таблицу."""
    from apps.org.services import structure
    from tests import support_org as org

    unit = org.make_unit("Отдел Поиска")
    member = _employee("Сотрудник Отдела Поиска")
    org.make_member(member.user, unit)
    author = _employee("Автор Отдела Поиска")
    org.make_member(author.user, unit)
    chat = sm.department_chat(unit)
    message = sm.post(chat, author, "Протокол совещания отдела")
    outsider = _employee("Сотрудник Без Отдела")
    assert [row.url for row in _rows(member.user, "протокол")] == [_message_url(chat, message)]
    assert _rows(outsider.user, "протокол") == [], "чат отдела виден сотруднику без узла"

    marker = "zqxmsgword"
    with sm.queries_with_params() as pairs:
        _rows(member.user, marker)
        _count(member.user, marker)
    message_pairs = [(sql, params) for sql, params in pairs if "messenger_message" in sql]
    assert message_pairs, "запросов к messenger_message не было"
    text = "\n".join(sql for sql, _ in message_pairs)
    assert marker not in text, "слово запроса попало в текст SQL"
    assert marker in [str(value) for _, params in message_pairs for value in _values(params)], (
        "слова запроса нет среди параметров")
    assert re.search(r"unit_id\s*=\s*ANY\s*\(\s*%s\s*\)", text, re.I), (
        "цепочка узлов не сравнивается массивом `= ANY(%s)`")
    chain = {int(value) for value in structure.unit_chain_ids(_fresh(member.user))}
    assert chain, "у сотрудника отдела пустая цепочка узлов"
    assert any(chain == values for _, params in message_pairs for values in _arrays(params)), (
        f"цепочки {sorted(chain)} нет среди параметров-массивов")
    assert re.search(r"\bgeneral\b", text, re.I), "в SQL нет условия «Общего чата»"
    assert ("messenger_settings" in text
            or any(True in (_values(params)) for _, params in message_pairs)), (
        "в SQL не видно условия «Общий чат включён»")

    for hostile in ("o'reilly", "a'b & c | !d :* (e)", "'; drop table messenger_message; --",
                    "проверки:* & !(x"):
        _rows(member.user, hostile)
        _count(member.user, hostile)
    assert support.model("messenger.Message").objects.filter(pk=message.pk).exists()


# --- 9. потолок числа -----------------------------------------------------------------------------------------

def test_count_ceiling_300():
    """FR-668: число группы — с потолком 300: ровно 300 сообщений дают `(300, False)`, 301-е — `(300, True)`."""
    author, reader, chat = _world()
    base = sm.moscow(2026, 6, 1, 8, 0)
    for step in range(300):
        sm.post(chat, author, "Протокол собрания", created_at=base + timedelta(minutes=step))
    assert _count(reader.user, "протокол") == (300, False)
    sm.post(chat, author, "Протокол собрания, ещё один", created_at=base + timedelta(minutes=301))
    assert support.model("messenger.Message").objects.filter(chat=chat).count() == 301
    assert _count(reader.user, "протокол") == (300, True)


# --- 10. маркеры упоминаний -----------------------------------------------------------------------------------

def test_mention_markers_do_not_break_search():
    """FR-668: маркеры `@[u<id>]` и `@[c<id>]` заменяются пробелом до вектора: слова рядом с маркером находятся,
    а номер сотрудника и ФИО из маркера — нет; вектор сообщения не содержит номера."""
    author = _employee("Сидорова Анна")
    reader = _employee("Петров Пётр")
    mentioned = _employee("Громова Елена")
    chat = sm.group(author, [reader, mentioned], title="Проект Бета")
    user_marker = sm.post(chat, author, f"Посмотри @[u{mentioned.user.pk}], коммутатор не отвечает",
                          created_at=sm.moscow(2026, 5, 12, 9, 0))
    chat_marker = sm.post(chat, author, f"Перешли в @[c{chat.pk}] коммутатор доступа",
                          created_at=sm.moscow(2026, 5, 12, 9, 5))
    assert f"@[u{mentioned.user.pk}]" in user_marker.text
    assert f"@[c{chat.pk}]" in chat_marker.text

    assert _urls(reader.user, "коммутатор") == [
        _message_url(chat, chat_marker), _message_url(chat, user_marker)]
    assert _urls(reader.user, "посмотри") == [_message_url(chat, user_marker)]
    assert _rows(reader.user, "громова") == [], "ФИО из маркера попало в вектор"
    assert _rows(reader.user, str(mentioned.user.pk)) == [], "номер из маркера попал в вектор"
    assert not _matches(user_marker, str(mentioned.user.pk))
    assert _matches(user_marker, "коммутатор") and _matches(chat_marker, "коммутатор")