"""T-7108: подсказка «Кому» и «Автор», карточка записи (FR-604, FR-610, FR-630, FR-635).

Подсказка — `/feed/pick/` (контракт 10.2): `scope=to|author|mention`, `q`; строка `[data-pick-value][data-pick-label]`,
значения `p<id>`/`u<id>` у `to`, `<id>` у `author`. Карточка — `/feed/<id>/`; событие шины `object.viewed` — фикстура `bus`.
Адреса почты и телефоны собираются из частей (решение 23 задач).
"""
from html.parser import HTMLParser

import pytest

from tests import support
from tests import support_feed as sf
from tests import support_org as org
from tests.support import model

pytestmark = pytest.mark.django_db

HX = {"HX-Request": "true"}


# --- разбор разметки (помощник только этого файла) ---------------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.parent, self.children = tag, parent, []
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                collect(child) if isinstance(child, Node) else parts.append(child)

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
        while node is not self.root:
            if node.tag == tag:
                self.cur = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def _tree(response) -> Node:
    parser = _Tree()
    parser.feed(response.content.decode("utf-8"))
    return parser.root


def _find(scope, tag=None, **attrs) -> list:
    wanted = {name.rstrip("_").replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            found.append(node)
    return found


# --- помощники файла ---------------------------------------------------------------------------------------

def _person(**extra):
    return support.make_employee(totp=False, **extra)


def _pick(session, scope: str, query: str, *, hx: bool = True):
    return session.client.get("/feed/pick/", {"scope": scope, "q": query}, headers=HX if hx else {})


def _rows(response) -> list[Node]:
    return _find(_tree(response), data_pick_value=True)


def _values(response) -> set[str]:
    return {row.attrs["data-pick-value"] for row in _rows(response)}


# --- 1. подсказка «Кому» и «Автор» -------------------------------------------------------------------------

def test_pick_open_to_every_logged_in_employee_and_redirects_anonymous_to_login():
    """FR-610: подсказка открыта каждому вошедшему сотруднику (без ролей и прав); не вошедшего ведёт на вход."""
    plain = sf.as_plain()
    for scope in ("to", "mention", "author"):
        assert _pick(plain, scope, "ив").status_code == 200, scope
    anonymous = support.make_client()
    response = anonymous.get("/feed/pick/", {"scope": "to", "q": "ив"})
    assert response.status_code == 302
    assert response["Location"].startswith("/login/?next=")


def test_pick_to_rows_show_name_and_unit_without_position_email_and_phone():
    """FR-610: строка сотрудника — ФИО и подразделение; должности, почты и телефона в подсказке нет."""
    session = sf.as_plain()
    position = "Главный-инженер-по-тестам"
    mail = sf.email_of("sidorova.anna", "example.test")
    phone = sf.phone_of("+7", "901", "222", "33", "44")
    person = _person(full_name="Сидорова Анна Петровна", position=position, email=mail, phone=phone)
    unit = org.make_unit("Бухгалтерия подсказок")
    org.make_member(person, unit)
    response = _pick(session, "to", "сидоров")
    (row,) = [node for node in _rows(response) if node.attrs["data-pick-value"] == f"p{person.pk}"]
    assert row.attrs["data-pick-label"] == "Сидорова Анна Петровна"
    assert "Бухгалтерия подсказок" in row.text()
    body = response.content.decode("utf-8")
    for hidden in (position, mail, phone, "sidorova.anna"):
        assert hidden not in body, hidden


def test_pick_to_finds_employee_by_name_part_ignoring_yo():
    """FR-610: поиск по части ФИО без учёта «ё»: «Темк» находит «Тёмкин», «Тёмк» — «Темкина»."""
    session = sf.as_plain()
    with_yo = _person(full_name="Тёмкин Игорь Семёнович")
    without_yo = _person(full_name="Темкина Ольга Ивановна")
    unrelated = _person(full_name="Совсем Другой Человек")
    for query in ("темк", "Тёмк", "ТЕМК", "тёмкин игорь", "семенович"):
        values = _values(_pick(session, "to", query))
        assert f"p{with_yo.pk}" in values, query
        assert f"p{unrelated.pk}" not in values, query
    assert f"p{without_yo.pk}" in _values(_pick(session, "to", "Тёмк"))
    assert f"p{without_yo.pk}" not in _values(_pick(session, "to", "семенович"))


def test_pick_to_finds_unit_by_name_part_and_path_part_and_shows_path():
    """FR-610: узлы — по части названия и по части пути; в строке — путь через « / »."""
    session = sf.as_plain()
    parent = org.make_unit("Альфаотдел")
    child = org.make_unit("Бетагруппа", parent=parent)
    by_name = _pick(session, "to", "бетагр")
    (row,) = [node for node in _rows(by_name) if node.attrs["data-pick-value"] == f"u{child.pk}"]
    assert row.attrs["data-pick-label"] == "Бетагруппа"
    assert "Альфаотдел / Бетагруппа" in row.text()
    by_path = _values(_pick(session, "to", "альфаотд"))
    assert f"u{child.pk}" in by_path and f"u{parent.pk}" in by_path


def test_pick_to_excludes_dismissed_and_blocked_and_includes_invited():
    """FR-610: недействующих (уволенных, заблокированных) в подсказке «Кому» нет; приглашённые есть."""
    session = sf.as_plain()
    active = _person(full_name="Корниенко Активный")
    invited = _person(full_name="Корниенко Приглашённый", state="invited")
    blocked = _person(full_name="Корниенко Заблокированный", state="blocked")
    dismissed = _person(full_name="Корниенко Уволенный", state="dismissed")
    values = _values(_pick(session, "to", "корниенко"))
    assert {f"p{active.pk}", f"p{invited.pk}"} <= values
    assert f"p{blocked.pk}" not in values and f"p{dismissed.pk}" not in values


def test_pick_author_includes_active_and_dismissed_with_full_name_row():
    """FR-635: «Автор» ищет среди действующих и уволенных; значение — номер, подпись — ФИО."""
    session = sf.as_plain()
    active = _person(full_name="Авторин Действующий")
    dismissed = _person(full_name="Авторин Уволенный", state="dismissed")
    response = _pick(session, "author", "авторин")
    rows = {node.attrs["data-pick-value"]: node for node in _rows(response)}
    assert set(rows) >= {str(active.pk), str(dismissed.pk)}
    assert rows[str(active.pk)].attrs["data-pick-label"] == "Авторин Действующий"
    assert rows[str(dismissed.pk)].attrs["data-pick-label"] == "Авторин Уволенный"
    assert all(value.isdigit() for value in rows), "у «Автор» значение — номер без префикса"


def test_pick_returns_at_most_20_rows_for_to_and_author():
    """FR-610, FR-635: не больше 20 строк и для «Кому», и для «Автор»."""
    session = sf.as_plain()
    for number in range(25):
        _person(full_name=f"Массовый Сотрудник{number:02d}")
    for scope in ("to", "author"):
        rows = _rows(_pick(session, scope, "массовый"))
        assert len(rows) == 20, scope


def test_pick_query_shorter_than_two_chars_returns_empty():
    """FR-610: запрос короче двух знаков (в том числе пустой) — пустой фрагмент."""
    session = sf.as_plain()
    _person(full_name="Аркадьев Сотрудник")
    org.make_unit("Архив")
    for scope in ("to", "mention", "author"):
        for query in ("", "а", " а ", "  "):
            response = _pick(session, scope, query)
            assert response.status_code == 200, (scope, query)
            assert _rows(response) == [], (scope, query)
        assert _rows(_pick(session, scope, "ар")) != [], scope


def test_pick_query_passed_as_sql_parameter():
    """FR-610, FR-635 (NFR-608): введённый запрос уходит в SQL параметром, а не частью текста запроса."""
    session = sf.as_plain()
    probe = "ПробаЗначение42"
    _person(full_name="Другой Человек")
    for scope in ("to", "mention", "author"):
        with sf.queries_with_params() as pairs:
            assert _pick(session, scope, probe).status_code == 200
        carrying = [(sql, params) for sql, params in pairs
                    if any(probe.lower() in str(param).lower() for param in (params or ()))]
        assert carrying, f"{scope}: запрос не найден среди параметров"
        assert not any(probe.lower() in sql.lower() for sql, _ in pairs), f"{scope}: запрос попал в текст SQL"
    injection = "'; DROP TABLE core_user; --"
    for scope in ("to", "mention", "author"):
        assert _pick(session, scope, injection).status_code == 200
    assert model("core.User").objects.filter(pk=session.user.pk).exists()


def test_pick_returns_htmx_fragment():
    """FR-610: ответ на запрос HTMX — фрагмент без `<html>`: строки `[data-pick-value][data-pick-label]`."""
    session = sf.as_plain()
    person = _person(full_name="Фрагментов Фёдор")
    response = _pick(session, "to", "фрагментов")
    assert response.status_code == 200
    body = response.content.decode("utf-8").lower()
    assert "<html" not in body and "<!doctype" not in body
    assert f"p{person.pk}" in _values(response)
    assert all("data-pick-label" in row.attrs for row in _rows(response))


# --- 2. карточка записи -------------------------------------------------------------------------------------

def test_card_shows_post_with_all_comments_and_comment_anchors():
    """FR-604: карточка — запись со всеми комментариями; у каждого комментария якорь `#c<id>` и `data-comment-id`."""
    author = sf.as_writer()
    reader = _person()
    post = sf.make_post(author.user, to=[reader], text="Запись для карточки")
    commenter = _person()
    comments = [sf.comment(post, commenter, f"Комментарий номер {number}") for number in range(25)]
    session = sf.Session(reader, support.logged_in(reader))
    response = session.client.get(f"/feed/{post.pk}/")
    assert response.status_code == 200
    tree = _tree(response)
    (article,) = _find(tree, "article", id=f"feed-post-{post.pk}")
    assert "Запись для карточки" in article.text()
    shown = _find(tree, data_comment_id=True)
    assert [node.attrs["id"] for node in shown] == [f"c{comment.pk}" for comment in comments]
    assert [node.attrs["data-comment-id"] for node in shown] == [str(comment.pk) for comment in comments]
    assert "Комментарий номер 24" in shown[-1].text()


def test_card_has_ws_node_with_post_query():
    """FR-604: на карточке узел соединения `#feed-live` с адресом `/ws/feed/?post=<id>`."""
    author = sf.as_writer()
    post = sf.make_post(author.user)
    response = author.client.get(f"/feed/{post.pk}/")
    assert response.status_code == 200
    (node,) = _find(_tree(response), id="feed-live")
    assert node.attrs.get("hx-ext") == "ws"
    assert node.attrs.get("ws-connect") == f"/ws/feed/?post={post.pk}"
    assert node.attrs.get("data-ws") == "connecting"


def test_card_publishes_object_viewed_for_post_and_each_own_comment(bus, django_capture_on_commit_callbacks):
    """FR-604, FR-630: показ карточки публикует `object.viewed` для записи и для каждого СВОЕГО комментария записи."""
    author = sf.as_writer()
    reader = _person()
    post = sf.make_post(author.user, to=[reader])
    own_first = sf.comment(post, reader, "Мой первый")
    other = sf.comment(post, author.user, "Чужой")
    own_second = sf.comment(post, reader, "Мой второй")
    bus.listen("object.viewed")
    session = sf.Session(reader, support.logged_in(reader))
    with django_capture_on_commit_callbacks(execute=True):
        assert session.client.get(f"/feed/{post.pk}/").status_code == 200
    calls = bus.calls("object.viewed")
    refs = [call["object_ref"] for call in calls]
    assert sorted(refs) == sorted([f"feed.post:{post.pk}", f"feed.post:{post.pk}:c{own_first.pk}",
                                   f"feed.post:{post.pk}:c{own_second.pk}"])
    assert f"feed.post:{post.pk}:c{other.pk}" not in refs
    assert {call["user_id"] for call in calls} == {reader.pk}


def test_card_for_non_viewer_same_404_as_nonexistent():
    """FR-604: не видящему запись карточка отвечает так же, как несуществующая: 404 «Не найдено», тот же ответ."""
    author = sf.as_writer()
    addressee = _person()
    hidden = sf.make_post(author.user, to=[addressee])
    stranger = sf.as_plain()
    missing = model("feed.Post").objects.order_by("-pk").first().pk + 1000
    invisible = stranger.client.get(f"/feed/{hidden.pk}/")
    absent = stranger.client.get(f"/feed/{missing}/")
    assert invisible.status_code == 404 and absent.status_code == 404
    assert support.same_failure(invisible, absent)
    assert "Не найдено" in invisible.content.decode("utf-8")
    anonymous = support.make_client().get(f"/feed/{hidden.pk}/")
    assert anonymous.status_code == 302 and anonymous["Location"].startswith("/login/?next=")


def test_literal_paths_not_confused_with_post_id_route():
    """FR-604: литеральные пути `more/`, `new/`, `pick/`, `posts/`, `files/` не путаются с `<int:id>/`; нечисловой — 404."""
    session = sf.as_plain()
    post = sf.make_post(session.user)
    assert session.client.get("/feed/more/").status_code == 200
    assert session.client.get("/feed/new/").status_code == 200
    assert session.client.get("/feed/pick/", {"scope": "to", "q": "ab"}).status_code == 200
    for literal in ("/feed/posts/", "/feed/files/"):
        response = session.client.get(literal)
        assert response.status_code == 405, f"{literal}: только POST, а не карточка записи"
    assert session.client.get(f"/feed/{post.pk}/").status_code == 200
    assert session.client.get("/feed/abc/").status_code == 404
