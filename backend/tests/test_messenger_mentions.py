"""T-8111: тесты упоминаний «@» (FR-655, FR-664, FR-669).

Источники: PLAN-008 «Упоминания „@“» (подсказка только участников текущего чата и своих чатов, в личном — пусто,
пустой или односимвольный запрос — пусто, маркеры `@[u<id>]`/`@[c<id>]`, участник и свой чат, недействительный номер
текстом, предел 20 разных людей, повтор не расходует, упоминание чата — ссылка без уведомлений); TASKS-008 T-8111;
CONTRACT-008: 5.2 (`mentions.extract`, `mentions.suggest`), 5.3 (`notify_rules.decide`), 6 (V5 — подсказка зовёт
`members.get_chat`), 7.1–7.2 (вид `messenger.mention`, тексты), 10.1–10.2 (`/messenger/mentions/`, отказ 200 и
`[data-error="text"][data-code="mentions_limit"]`), 12.3 и 12.6 (`[data-messenger-mention-list]`,
`[data-mention-value]`, `[data-mention]`), 13.1 («Не больше 20 упоминаний»).

Код среза на уровне модуля не импортируется (CONTRACT-008, «Правила для всех тестов среза»): модели берутся через
`support.model`, службы — внутри функций теста. Секретов и ПДн нет: адреса и телефоны не создаются.

Допущения писателя (см. отчёт T-8111): контракт называет зацепку `[data-mention-value]`, но не фиксирует её форму
(`u12`, `c3` или готовый маркер `@[u12]`/`@[c3]`) — помощник `_token` принимает любую из них. «Поле в личном диалоге
не подключает подсказку» проверяется по разметке страницы: нет `[data-messenger-mention-list]` и нет адреса
`/messenger/mentions/`; в групповом чате подсказка подключена. Точный текст уведомления упоминания сверяет T-8116a;
здесь проверяются вид `messenger.mention`, название вида «Упомянул вас в чате» и слово «упомянул» в тексте.
"""
import re
from html.parser import HTMLParser

import pytest

from tests import support
from tests import support_messenger as sm
from tests import support_org as org

pytestmark = pytest.mark.django_db

MISSING = 999999
ROWS_LIMIT = 20
MENTIONS_LIMIT_TEXT = "Не больше 20 упоминаний"
MENTION_TITLE = "Упомянул вас в чате"

_TOKEN = re.compile(r"([uc])(\d+)")
_VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- помощники файла (общие помощники среза не правятся) ------------------------------------------------------------

class _RowParser(HTMLParser):
    """Строки подсказки: элементы с `data-mention-value` и их текст."""

    def __init__(self):
        super().__init__()
        self.rows: list[tuple[str, list[str]]] = []
        self._current: tuple[str, list[str]] | None = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if self._current is not None:
            if tag not in _VOID_TAGS:
                self._depth += 1
        elif "data-mention-value" in values:
            self._current = (values["data-mention-value"], [])
            self._depth = 1
            self.rows.append(self._current)

    def handle_startendtag(self, tag, attrs):
        values = dict(attrs)
        if self._current is None and "data-mention-value" in values:
            self.rows.append((values["data-mention-value"], []))

    def handle_endtag(self, tag):
        if self._current is None:
            return
        self._depth -= 1
        if self._depth <= 0:
            self._current = None

    def handle_data(self, data):
        if self._current is not None:
            self._current[1].append(data)


def _employee(name: str, **extra):
    return sm.make_user(full_name=name, **extra)


def _chat_url(chat) -> str:
    return f"/messenger/chats/{chat.pk}/"


def _send_url(chat) -> str:
    return f"/messenger/chats/{chat.pk}/messages/"


def _suggest(session, chat_id: int, q: str):
    """`GET /messenger/mentions/?chat=<id>&q=<q>` (CONTRACT-008, 10.2)."""
    return session.client.get("/messenger/mentions/", {"chat": chat_id, "q": q})


def _body(value) -> str:
    if hasattr(value, "content"):
        return value.content.decode("utf-8", "replace")
    return value


def _rows(value) -> list[tuple[str, list[str]]]:
    parser = _RowParser()
    parser.feed(_body(value))
    return parser.rows


def _token(value: str) -> str:
    """Номер строки подсказки: `u12`, `c3` или готовый маркер `@[u12]`/`@[c3]` — одно и то же."""
    match = _TOKEN.search(value)
    assert match, f"data-mention-value без номера: {value!r}"
    return f"{match.group(1)}{int(match.group(2))}"


def _tokens(value) -> set[str]:
    return {_token(row_value) for row_value, _text in _rows(value)}


def _row_text(rows, token: str) -> str:
    for row_value, parts in rows:
        if _token(row_value) == token:
            return " ".join("".join(parts).split())
    raise AssertionError(f"в подсказке нет строки {token}")


def _has_suggest(html: str) -> bool:
    """Поле ввода подключило подсказку «@»: контейнер или адрес подсказки (CONTRACT-008, 12.3, 10.2)."""
    return "data-messenger-mention-list" in html or "/messenger/mentions/" in html


def _notes(*, user=None, kind: str | None = None):
    rows = support.model("notify.Notification").objects.filter(kind__startswith="messenger.")
    if user is not None:
        rows = rows.filter(user=getattr(user, "user", user))
    if kind is not None:
        rows = rows.filter(kind=kind)
    return rows


def _kinds_of(user) -> list[str]:
    return list(_notes(user=user).order_by("pk").values_list("kind", flat=True))


# --- подсказка «@» (FR-655) ---------------------------------------------------------------------------------------

def test_suggestion_lists_active_chat_members_and_own_chats():
    """FR-655: подсказка — действующие участники текущего чата (ФИО и подразделение) и свои чаты (название), до 20
    строк; уволенный участник скрыт."""
    author = _employee("Автор Беседы")
    anna = _employee("Анна Участникова")
    gone = sm.make_user(state="dismissed", full_name="Ангелина Уволенная")
    outsider = _employee("Антон Посторонний")
    unit = sm.unit("Отдел Разработки")
    org.make_member(anna.user, unit)
    chat = sm.group(author, [anna, gone], title="Рабочая группа")
    own_chat = sm.group(author, [anna], title="Аналитика")

    response = _suggest(author, chat.pk, "Ан")

    assert response.status_code == 200
    rows = _rows(response)
    assert len(rows) <= ROWS_LIMIT, f"подсказка длиннее {ROWS_LIMIT} строк: {len(rows)}"
    tokens = _tokens(response)
    assert f"u{anna.user.pk}" in tokens, "нет действующего участника текущего чата"
    assert f"c{own_chat.pk}" in tokens, "нет своего чата"
    assert f"u{gone.user.pk}" not in tokens, "подсказка показала уволенного"
    assert f"u{outsider.user.pk}" not in tokens, "подсказка показала постороннего"
    anna_text = _row_text(rows, f"u{anna.user.pk}")
    assert "Анна Участникова" in anna_text and "Отдел Разработки" in anna_text, (
        f"строка участника без ФИО и подразделения: {anna_text!r}")
    own_text = _row_text(rows, f"c{own_chat.pk}")
    assert "Аналитика" in own_text, f"строка чата без названия: {own_text!r}"


def test_suggestion_hides_strangers_and_foreign_chats():
    """FR-655, 669 (V5): посторонние люди, уволенные и чужие чаты в подсказку не попадают; чужой чат в запросе —
    такой же 404, как несуществующий."""
    author = _employee("Автор Подсказки")
    member = _employee("Аналитик Свой")
    gone = sm.make_user(state="dismissed", full_name="Аналитик Уволенный")
    stranger = _employee("Аналитик Посторонний")
    other = _employee("Владелец Чужого Чата")
    own_chat = sm.group(author, [member, gone], title="Аналитика своя")
    foreign_chat = sm.group(stranger, [other], title="Аналитика чужая")

    response = _suggest(author, own_chat.pk, "Аналитик")

    assert response.status_code == 200
    tokens = _tokens(response)
    assert f"u{member.user.pk}" in tokens
    assert f"c{own_chat.pk}" in tokens
    assert f"u{stranger.user.pk}" not in tokens, "подсказка показала постороннего"
    assert f"u{gone.user.pk}" not in tokens, "подсказка показала уволенного"
    assert f"c{foreign_chat.pk}" not in tokens, "подсказка показала чужой чат"

    foreign = _suggest(author, foreign_chat.pk, "Аналитик")
    missing = _suggest(author, MISSING, "Аналитик")
    assert foreign.status_code == 404, f"чужой чат в подсказке: {foreign.status_code}"
    assert support.same_failure(foreign, missing), "ответ чужого чата отличается от несуществующего"


def test_personal_dialog_suggestion_empty_and_form_has_no_suggest():
    """FR-655 (сценарий 6 п. 4): в личном диалоге сервер отвечает пустой подсказкой, поле ввода её не подключает;
    в групповом чате подсказка подключена."""
    author = _employee("Автор Личного")
    peer = _employee("Пётр Собеседник")
    personal = sm.personal(author, peer)
    group = sm.group(author, [peer], title="Группа с подсказкой")

    response = _suggest(author, personal.pk, "Пё")

    assert response.status_code == 200
    assert _tokens(response) == set(), "в личном диалоге подсказка не пуста"
    assert "data-mention-value" not in _body(response), "в личном диалоге подсказка отдала строки"

    personal_page = author.client.get(_chat_url(personal))
    assert personal_page.status_code == 200
    assert not _has_suggest(_body(personal_page)), "поле личного диалога подключило подсказку «@»"

    group_page = author.client.get(_chat_url(group))
    assert group_page.status_code == 200
    assert _has_suggest(_body(group_page)), "поле группового чата не подключило подсказку «@»"


def test_empty_or_one_char_query_returns_nothing():
    """FR-655: пустой запрос и запрос короче двух знаков дают пустую подсказку; два знака уже ищут."""
    author = _employee("Автор Запроса")
    anna = _employee("Анна Найдёнова")
    chat = sm.group(author, [anna], title="Анна и коллеги")

    for q in ("", "А", " "):
        response = _suggest(author, chat.pk, q)
        assert response.status_code == 200
        assert _tokens(response) == set(), f"q={q!r} вернул строки"
        assert "data-mention-value" not in _body(response), f"q={q!r} вернул разметку подсказки"

    found = _tokens(_suggest(author, chat.pk, "Ан"))
    assert f"u{anna.user.pk}" in found and f"c{chat.pk}" in found, "два знака не нашли участника и свой чат"


def test_extract_returns_people_and_chats_sets():
    """FR-655: `mentions.extract` возвращает два набора номеров по маркерам `@[u<id>]` и `@[c<id>]`; повтор не
    добавляет элемент, синтаксически неверный маркер не становится упоминанием."""
    from apps.messenger.services import mentions

    people, chats = mentions.extract("Привет @[u12] и @[u34], снова @[u12]; чат @[c7] и @[c9]")
    assert people == frozenset({12, 34}), f"люди: {people!r}"
    assert chats == frozenset({7, 9}), f"чаты: {chats!r}"

    broken_people, broken_chats = mentions.extract("@[u] @[uabc] @[x12] просто @Анна")
    assert broken_people == frozenset(), f"неверный маркер человека учтён: {broken_people!r}"
    assert broken_chats == frozenset(), f"неверный маркер чата учтён: {broken_chats!r}"


# --- упоминания в сообщении (FR-655, FR-664) -----------------------------------------------------------------------

def test_mention_outside_suggestion_unknown_word_is_no_mention():
    """FR-655 (сценарий 6 п. 2): «@» и слово, набранные вне подсказки, упоминанием не становятся — уведомления
    «упомянул» нет, в тексте остаётся обычное слово."""
    from apps.messenger.services import mentions, messages

    author = _employee("Автор Слова")
    anna = _employee("Анна Участникова")
    chat = sm.group(author, [anna], title="Беседа без упоминания")
    text = "Привет, @Анна! Смотри задачу."

    people, chats = mentions.extract(text)
    assert people == frozenset() and chats == frozenset(), "слово вне подсказки стало упоминанием"
    message = messages.send(chat, author.user, text)
    assert message.text == text

    assert _notes(user=anna.user, kind="messenger.mention").count() == 0, "уведомление об упоминании создано"
    assert _notes(user=anna.user, kind="messenger.message").count() == 1, "нет обычного уведомления о сообщении"
    body = _body(author.client.get(_chat_url(chat)))
    assert "@Анна" in body, "слово пропало из текста"
    assert "data-mention=" not in body, "слово вне подсказки стало ссылкой упоминания"


def test_mention_of_non_member_kept_as_text_and_sends_no_notification():
    """FR-655: маркер постороннего человека и чужого чата остаётся текстом и уведомлений не шлёт; сообщение
    сохраняется как есть."""
    from apps.messenger.services import messages

    author = _employee("Автор Маркера")
    member = _employee("Участник Беседы")
    outsider = _employee("Посторонний Упомянутый")
    other = _employee("Хозяин Чужого Чата")
    chat = sm.group(author, [member], title="Своя беседа")
    foreign_chat = sm.group(outsider, [other], title="Чужой чат")
    text = f"Привет @[u{outsider.user.pk}] и @[c{foreign_chat.pk}]"

    message = messages.send(chat, author.user, text)

    assert message.text == text, "недействительный номер не остался текстом"
    assert _notes(user=outsider.user).count() == 0, "постороннему ушло уведомление"
    assert _notes(kind="messenger.mention").count() == 0, "создан вид «упоминание»"
    body = _body(author.client.get(_chat_url(chat)))
    assert f'data-mention="{outsider.user.pk}"' not in body, "посторонний стал ссылкой упоминания"
    assert f'data-mention="c{foreign_chat.pk}"' not in body, "чужой чат стал ссылкой упоминания"
    assert f'href="/messenger/chats/{foreign_chat.pk}/"' not in body, "чужой чат стал ссылкой"
    assert f"@[u{outsider.user.pk}]" in body or outsider.user.full_name in body, "номер постороннего пропал из текста"
    assert f"@[c{foreign_chat.pk}]" in body or foreign_chat.title in body, "номер чужого чата пропал из текста"


def test_chat_mention_inserts_link_and_notifies_only_mentioned_people():
    """FR-655, 664: упоминание человека — ссылка с уведомлением «Упомянул вас в чате», упоминание своего чата —
    ссылка без уведомлений; остальные участники получают обычное уведомление, участники упомянутого чата — ничего."""
    from apps.messenger.services import messages
    from apps.notify.services import kinds

    author = _employee("Автор Упоминания")
    alice = _employee("Алиса Упомянутая")
    bob = _employee("Борис Молчащий")
    dave = _employee("Дмитрий Целевой")
    chat = sm.group(author, [alice, bob], title="Рабочая беседа")
    target = sm.group(author, [dave], title="Целевой чат")
    text = f"@[u{alice.user.pk}] посмотри @[c{target.pk}]"

    messages.send(chat, author.user, text)

    body = _body(author.client.get(_chat_url(chat)))
    assert f'data-mention="{alice.user.pk}"' in body, "упомянутый человек без ссылки"
    assert f'href="/staff/{alice.user.pk}/"' in body, "ссылка человека ведёт не на карточку"
    assert f'data-mention="c{target.pk}"' in body, "упоминание чата без ссылки"
    assert f'href="/messenger/chats/{target.pk}/"' in body, "ссылка упомянутого чата не на беседу"

    assert kinds.get("messenger.mention").title == MENTION_TITLE
    note = _notes(user=alice.user, kind="messenger.mention").get()
    assert "упомянул" in note.text.lower(), f"текст уведомления: {note.text!r}"
    assert _kinds_of(alice.user) == ["messenger.mention"], "упомянутый получил лишнее уведомление"
    assert _kinds_of(bob.user) == ["messenger.message"], "обычному участнику не ушло уведомление о сообщении"
    assert not _notes(user=dave.user).exists(), "участнику упомянутого чата ушло уведомление"
    assert not _notes(user=author.user).exists(), "автору ушло уведомление"
    assert _notes(kind="messenger.mention").count() == 1, "уведомление «упоминание» создано не только упомянутому"


def test_21_distinct_mentions_refused_and_20_allowed():
    """FR-655: 21 разное упоминание — отказ «Не больше 20 упоминаний» без сообщения; 20 разных — отправляются."""
    author = _employee("Автор Предела")
    people = [_employee(f"Участник Предела {number:02d}") for number in range(21)]
    chat = sm.group(author, people, title="Большая беседа")
    Message = support.model("messenger.Message")
    before = Message.objects.filter(chat=chat).count()

    text_21 = " ".join(f"@[u{person.user.pk}]" for person in people)
    refused = author.client.post(_send_url(chat), {"text": text_21})

    assert refused.status_code == 200, f"отказ 21 упоминания: {refused.status_code}"
    body = _body(refused)
    assert 'data-error="text"' in body, "причина отказа не у поля text"
    assert 'data-code="mentions_limit"' in body, "нет кода mentions_limit"
    assert MENTIONS_LIMIT_TEXT in body, "нет текста «Не больше 20 упоминаний»"
    assert Message.objects.filter(chat=chat).count() == before, "сообщение с 21 упоминанием сохранено"

    text_20 = " ".join(f"@[u{person.user.pk}]" for person in people[:20])
    accepted = author.client.post(_send_url(chat), {"text": text_20})

    assert accepted.status_code == 302, f"отправка 20 упоминаний: {accepted.status_code}"
    assert accepted["Location"] == _chat_url(chat)
    assert Message.objects.filter(chat=chat).count() == before + 1, "сообщение с 20 упоминаниями не сохранено"


def test_repeated_mention_does_not_consume_limit():
    """FR-655: повтор одного и того же маркера не расходует предел — 40 повторов одного человека отправляются и
    дают одно уведомление."""
    from apps.messenger.services import mentions, messages

    author = _employee("Автор Повтора")
    anna = _employee("Анна Повторяемая")
    chat = sm.group(author, [anna], title="Беседа повторов")
    marker = f"@[u{anna.user.pk}]"
    text = " ".join([marker] * 40)

    people, chats = mentions.extract(text)
    assert people == frozenset({anna.user.pk}), f"повтор увеличил набор людей: {people!r}"
    assert chats == frozenset()

    message = messages.send(chat, author.user, text)

    assert message.text == text
    assert _notes(user=anna.user, kind="messenger.mention").count() == 1, "повтор дал не одно уведомление"
    assert not _notes(kind="messenger.mention").exclude(user=anna.user).exists()