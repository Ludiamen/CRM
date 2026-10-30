"""T-7110: упоминания в ленте (FR-605, FR-611, FR-620, FR-622, FR-635, FR-642). Сценарий 6 спеки среза 007.

Подсказка `scope=mention` (только действующие сотрудники, без подразделений), форма правки без JS (сохранённые маркеры
`@[id]` и соответствие «номер → ФИО» в `data-mention-names`), предел 20 разных упоминаний (повтор предел не
расходует), строки `Recipient(via="mention")` отдельно от строк `to`, упомянутый в записи и в комментарии становится
адресатом записи и остаётся им после удаления комментария и правки текста, фильтр «Упоминают меня», маркеры
недействующих и несуществующих остаются текстом, набранный руками маркер равен выбору из подсказки, «новое» упоминание
при правке — номер, которого не было в прежнем тексте (`mentions.sync`, решение 47 задач). План: «Текст и упоминания»,
«Модель данных» (упоминания строками `via='mention'`), «Публикация: форма, «Кому», подсказки»; CONTRACT-007, 5.3, 10.2,
12.2. Код среза на уровне модуля не импортируется: имена берутся внутри тестов (CONTRACT-007, шапка).
"""
import json
import uuid
from datetime import timedelta
from html.parser import HTMLParser

import pytest
from django.contrib.auth.hashers import make_password
from django.utils import timezone

from tests import support
from tests import support_feed as feed
from tests import support_org as org
from tests.support import HX

pytestmark = pytest.mark.django_db

TOO_MANY = "Не больше 20 упоминаний"


# --- разбор разметки (помощник только этого файла) ------------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.parent, self.children = tag, parent, []
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}

    def walk(self):
        for child in self.children:
            if isinstance(child, _Node):
                yield child
                yield from child.walk()

    def text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                collect(child) if isinstance(child, _Node) else parts.append(child)

        collect(self)
        return " ".join("".join(parts).split())

    def raw_text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                collect(child) if isinstance(child, _Node) else parts.append(child)

        collect(self)
        return "".join(parts)

    def ancestors(self):
        node = self.parent
        while node is not None:
            yield node
            node = node.parent


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
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


def tree(response_or_html) -> _Node:
    html = response_or_html if isinstance(response_or_html, str) else response_or_html.content.decode("utf-8")
    parser = _Tree()
    parser.feed(html)
    return parser.root


def q(scope, tag=None, **attrs) -> list:
    """Потомки `scope` по тегу и атрибутам; `_` в имени — дефис; значение `True` — «атрибут есть»."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            found.append(node)
    return found


def q1(scope, tag=None, **attrs):
    found = q(scope, tag, **attrs)
    assert len(found) == 1, f"ожидали один элемент {tag or ''}{attrs}, нашли {len(found)}"
    return found[0]


# --- данные теста -----------------------------------------------------------------------------------------

def _Post():
    return support.model("feed.Post")


def _Recipient():
    return support.model("feed.Recipient")


def _person(name: str, **extra):
    """Сотрудник без входа (второй фактор не нужен)."""
    return support.make_employee(full_name=name, totp=False, **extra)


def _bulk_people(count: int, prefix: str = "Упоминаемый") -> list:
    """`count` действующих сотрудников одной вставкой (без входа; пароль не задаётся)."""
    User = support.model("core.User")
    now = timezone.now()
    unusable = make_password(None)
    users = [User(email=f"{prefix.lower()}-{number}-{uuid.uuid4().hex[:6]}@example.com",
                  full_name=f"{prefix}{number:02d} Тестов", state="active", activated_at=now, password=unusable)
             for number in range(count)]
    return User.objects.bulk_create(users)


def _markers(users) -> str:
    return " ".join(f"@[{user.pk}]" for user in users)


def _publish(session, **fields):
    data = {"kind": "post", "text": "Запись", "to": ["all"]}
    data.update(fields)
    extra = data.pop("_extra", {})
    return session.client.post("/feed/posts/", data, **extra)


def _error(response, field: str = "text", code: str = "too_many_mentions"):
    assert response.status_code == 200, f"ждали 200 с отказом, получили {response.status_code}"
    return q1(tree(response), None, data_error=field, data_code=code)


def _mention_rows(post) -> list:
    return list(_Recipient().objects.filter(post=post, via="mention"))


def _feed_ids(response) -> list[int]:
    root = tree(response)
    lists = q(root, "ol", id="feed-list")
    assert len(lists) == 1, "на странице нет ленты `ol#feed-list`"
    return [int(node.attrs["data-post-id"]) for node in q(lists[0], "article", data_post_id=True)]


def _comment_setup():
    """Запись автора A адресату B; Сидоров S записи не видит; у A уже есть комментарий."""
    author, addressee = feed.as_plain(full_name="Автор Записи"), feed.as_plain(full_name="Адресат Записи")
    outsider = feed.as_plain(full_name="Сидоров Сидор")
    post = feed.make_post(author.user, to=(addressee.user,), text="Запись для адресата")
    first = feed.comment(post, author.user, "Первый комментарий автора")
    return post, author, addressee, outsider, first


# --- подсказка и форма правки -------------------------------------------------------------------------------

def test_pick_mention_returns_only_active_employees_without_dismissed_and_units():
    """FR-611, сценарий 6 п. 1 и 5: в подсказке «@» — действующие сотрудники; уволенных, заблокированных и
    подразделений нет (в подсказке «Кому» подразделение есть)."""
    viewer = feed.as_plain()
    active = _person("Петров Пётр")
    _person("Петрова Уволена", state="dismissed")
    _person("Петренко Заблокирован", state="blocked")
    unit = org.make_unit("Петровский отдел")

    response = viewer.client.get("/feed/pick/", {"scope": "mention", "q": "Пет"})

    assert response.status_code == 200
    rows = q(tree(response), None, data_pick_value=True)
    assert [row.attrs["data-pick-value"] for row in rows] == [f"p{active.pk}"]
    assert rows[0].attrs["data-pick-label"] == "Петров Пётр"

    to_rows = q(tree(viewer.client.get("/feed/pick/", {"scope": "to", "q": "Пет"})), None, data_pick_value=True)
    assert f"u{unit.pk}" in {row.attrs["data-pick-value"] for row in to_rows}


def test_edit_form_without_js_returns_saved_markers_and_id_to_name_map_in_data_attribute():
    """FR-611, FR-620: форма правки отдаёт текст с маркерами `@[id]` (без JS поле работает как есть) и соответствие
    «номер → ФИО» в `textarea[name="text"][data-mention-names]` (JSON-объект)."""
    author = feed.as_plain()
    petrov, sidorov = _person("Петров Пётр"), _person("Сидоров Сидор")
    post = feed.make_post(author.user, to=(sidorov,), mentions=(petrov,), text="Привет,")

    response = author.client.get(f"/feed/{post.pk}/edit/")

    assert response.status_code == 200
    field = q1(tree(response), "textarea", name="text")
    assert f"@[{petrov.pk}]" in field.raw_text()
    assert "@Петров" not in field.raw_text()
    assert json.loads(field.attrs["data-mention-names"]) == {str(petrov.pk): "Петров Пётр"}


# --- предел 20 -----------------------------------------------------------------------------------------------

def test_post_with_21_distinct_mentions_rejected_with_reason():
    """FR-611, FR-642, сценарий 6 п. 6: 21 разный сотрудник в тексте записи — публикации нет, причина у поля текста
    (и в обычном ответе, и на запрос HTMX)."""
    writer = feed.as_writer()
    people = _bulk_people(21)
    text = "Все: " + _markers(people)

    plain = _publish(writer, text=text)
    assert TOO_MANY in _error(plain).text()
    hx = _publish(writer, text=text, _extra=HX)
    assert TOO_MANY in _error(hx).text()

    assert _Post().objects.count() == 0
    assert _Recipient().objects.count() == 0


def test_comment_with_21_distinct_mentions_rejected_with_reason():
    """FR-611, FR-642: то же в комментарии — комментария нет, причина у поля текста."""
    author = feed.as_writer()
    post = feed.make_post(author.user, to=("all",))
    people = _bulk_people(21)
    url = f"/feed/{post.pk}/comments/"

    response = author.client.post(url, {"text": "Все: " + _markers(people)})
    assert TOO_MANY in _error(response).text()
    hx = author.client.post(url, {"text": "Все: " + _markers(people)}, **HX)
    assert TOO_MANY in _error(hx).text()

    assert support.model("core.Comment").objects.filter(object_ref=f"feed.post:{post.pk}").count() == 0
    assert _mention_rows(post) == []


def test_repeated_mention_of_same_employee_does_not_consume_limit():
    """FR-611: 20 разных сотрудников и повторы тех же — не больше 20 разных, запись опубликована; строк
    упоминаний — по одной на человека."""
    writer = feed.as_writer()
    people = _bulk_people(20)
    text = _markers(people) + " " + _markers(people[:5]) + " " + _markers(people)

    response = _publish(writer, text=text)

    assert response.status_code == 302
    post = _Post().objects.get()
    assert post.text == text
    rows = _mention_rows(post)
    assert len(rows) == 20
    assert {row.user_id for row in rows} == {person.pk for person in people}


# --- упомянутый становится адресатом ---------------------------------------------------------------------------

def test_mentioned_in_post_gets_mention_row_and_sees_post_with_name_link_to_card():
    """FR-605, FR-611, сценарий 6 п. 2: упомянутый вне «Кому» получает строку `via="mention"`, видит запись, имя в
    тексте — ссылка на его карточку (читателю с правом просмотра сотрудников)."""
    author = feed.as_plain()
    addressee = _person("Адресат Записи")
    petrov = support.make_with_permissions("staff.view", full_name="Петров Пётр")
    reader = support.logged_in(petrov)

    response = author.client.post("/feed/posts/", {"kind": "post", "to": [f"p{addressee.pk}"],
                                                   "text": f"Группа, привет, @[{petrov.pk}]!"})

    assert response.status_code == 302
    post = _Post().objects.get()
    rows = _mention_rows(post)
    assert [(row.kind, row.user_id, row.unit_id) for row in rows] == [("user", petrov.pk, None)]
    assert rows[0].published_at == post.published_at
    page = reader.get("/")
    assert post.pk in _feed_ids(page)
    article = q1(tree(page), "article", data_post_id=str(post.pk))
    link = q1(article, "a", data_mention=str(petrov.pk))
    assert link.attrs["href"] == f"/staff/{petrov.pk}/"
    assert link.text() == "Петров Пётр"


def test_mentioned_already_in_to_gets_separate_mention_row():
    """FR-611: упомянутый, который уже есть в «Кому», получает отдельную строку `mention` (уникальность —
    запись, человек, способ)."""
    author = feed.as_plain()
    petrov = _person("Петров Пётр")

    response = author.client.post("/feed/posts/", {"kind": "post", "to": [f"p{petrov.pk}"],
                                                   "text": f"Петров, @[{petrov.pk}], посмотрите"})

    assert response.status_code == 302
    post = _Post().objects.get()
    rows = _Recipient().objects.filter(post=post, user_id=petrov.pk)
    assert sorted(row.via for row in rows) == ["mention", "to"]


def test_mentioned_in_comment_becomes_post_recipient_and_sees_card_with_all_comments():
    """FR-605, FR-611, сценарий 6 п. 3: Сидоров записи не видит; упомянутый в комментарии, он становится адресатом
    записи и видит её со всеми комментариями."""
    post, author, addressee, outsider, first = _comment_setup()
    assert outsider.client.get(f"/feed/{post.pk}/").status_code == 404

    response = addressee.client.post(f"/feed/{post.pk}/comments/",
                                     {"text": f"Сидоров, посмотрите @[{outsider.user.pk}]"})

    assert response.status_code == 302
    second = support.model("core.Comment").objects.get(object_ref=f"feed.post:{post.pk}", author=addressee.user)
    rows = _mention_rows(post)
    assert [row.user_id for row in rows] == [outsider.user.pk]
    card = outsider.client.get(f"/feed/{post.pk}/")
    assert card.status_code == 200
    root = tree(card)
    assert "Первый комментарий автора" in q1(root, None, id=f"c{first.pk}").text()
    assert "Сидоров, посмотрите" in q1(root, None, id=f"c{second.pk}").text()


def test_deleting_comment_keeps_mentioned_as_recipient():
    """FR-611, FR-622: комментарий с упоминанием удалён — адресат остаётся, запись ему по-прежнему видна."""
    post, author, addressee, outsider, first = _comment_setup()
    addressee.client.post(f"/feed/{post.pk}/comments/", {"text": f"Сидоров, @[{outsider.user.pk}]"})
    second = support.model("core.Comment").objects.get(object_ref=f"feed.post:{post.pk}", author=addressee.user)

    response = addressee.client.post(f"/feed/comments/{second.pk}/delete/")

    assert response.status_code == 302
    assert not support.model("core.Comment").objects.filter(pk=second.pk).exists()
    assert [row.user_id for row in _mention_rows(post)] == [outsider.user.pk]
    assert outsider.client.get(f"/feed/{post.pk}/").status_code == 200


def test_removing_mention_on_edit_keeps_recipient():
    """FR-611, FR-620: упоминание стёрто из текста при правке — строка адресата остаётся, запись упомянутому видна."""
    author = feed.as_plain()
    addressee = _person("Адресат Записи")
    petrov_user = support.make_employee(full_name="Петров Пётр")
    petrov = support.logged_in(petrov_user)
    post = feed.make_post(author.user, to=(addressee,), mentions=(petrov_user,), text="Привет,")

    response = author.client.post(f"/feed/{post.pk}/edit/", {"text": "Привет без упоминания",
                                                              "to": [f"p{addressee.pk}"]})

    assert response.status_code == 302
    post.refresh_from_db()
    assert "@[" not in post.text
    assert [row.user_id for row in _mention_rows(post)] == [petrov_user.pk]
    assert petrov.get(f"/feed/{post.pk}/").status_code == 200


def test_mentions_me_filter_finds_mention_of_to_recipient():
    """FR-611, FR-635: «Упоминают меня» находит и упоминание адресата «Кому»; запись, где он только адресат, не
    попадает в выдачу."""
    author = support.make_employee()
    petrov = support.make_employee(full_name="Петров Пётр")
    reader = support.logged_in(petrov)
    mentioned = feed.make_post(author, to=(petrov,), mentions=(petrov,), text="Упомянут адресат")
    only_to = feed.make_post(author, to=(petrov,), text="Только адресат",
                             published_at=timezone.now() - timedelta(minutes=5))

    everything = reader.get("/")
    filtered = reader.get("/", {"f": "mentions"})

    assert set(_feed_ids(everything)) == {mentioned.pk, only_to.pk}
    assert _feed_ids(filtered) == [mentioned.pk]


# --- маркеры, которые адресатов не дают ---------------------------------------------------------------------------

def test_marker_of_dismissed_blocked_or_nonexistent_employee_stays_text_and_adds_no_recipient():
    """FR-611: маркер уволенного, заблокированного и несуществующего сотрудника остаётся в тексте, выводится
    текстом (не ссылкой) и адресата не добавляет."""
    writer = feed.as_writer()
    fired = _person("Уволенов Иван", state="dismissed")
    blocked = _person("Блокиров Пётр", state="blocked")
    ghost = 999999999
    text = f"Раз @[{fired.pk}] два @[{blocked.pk}] три @[{ghost}]"

    response = _publish(writer, text=text)

    assert response.status_code == 302
    post = _Post().objects.get()
    assert post.text == text
    assert _Recipient().objects.filter(post=post).count() == 0
    card = writer.client.get(f"/feed/{post.pk}/")
    body = feed.post_part(card.content.decode("utf-8"), post.pk, "body")
    assert body is not None
    assert not q(tree(card), None, data_mention=True)
    for number in (fired.pk, blocked.pk, ghost):
        assert f"@[{number}]" in body.text


def test_hand_typed_marker_equals_picked_employee():
    """FR-611: набранный руками `@[id]` — то же, что выбор сотрудника из подсказки; подменить имя надписью нельзя
    (имя берётся из базы, адресатов добавляют только маркеры)."""
    from apps.feed.services import mentions

    author = feed.as_plain()
    addressee = _person("Адресат Записи")
    petrov = _person("Петров Пётр")
    namesake = _person("Иванов Иван")

    response = author.client.post("/feed/posts/", {"kind": "post", "to": [f"p{addressee.pk}"],
                                                   "text": f"@Иванов Иван, @[{petrov.pk}]"})

    assert response.status_code == 302
    post = _Post().objects.get()
    assert {row.user_id for row in _mention_rows(post)} == {petrov.pk}
    assert namesake.pk not in {row.user_id for row in _Recipient().objects.filter(post=post)}
    assert mentions.extract("а @[5] б @[7] в @[5] @[0] @[05] @[1234567890]") == [5, 7]


def test_only_id_absent_from_previous_version_of_text_is_new_mention_on_edit():
    """FR-611, FR-620, решение 47 задач: `mentions.sync(post, text, old_text)` возвращает номера, которых не было в
    прежнем тексте; строки упоминаний у всех действующих упомянутых, недействующий — не адресат."""
    from apps.feed.services import mentions

    author = support.make_employee()
    addressee = _person("Адресат Записи")
    first, second = _person("Первый Упомянутый"), _person("Второй Упомянутый")
    fired = _person("Уволенов Иван", state="dismissed")
    post = feed.make_post(author, to=(addressee,), text="Запись")

    new = mentions.sync(post, f"@[{first.pk}] и @[{second.pk}]", f"@[{first.pk}]")

    assert new == {second.pk}
    assert {row.user_id for row in _mention_rows(post)} == {first.pk, second.pk}

    mentions.sync(post, f"@[{first.pk}] и @[{second.pk}]", f"@[{first.pk}] и @[{second.pk}]")
    assert len(_mention_rows(post)) == 2

    mentions.sync(post, f"@[{fired.pk}]", "")
    assert fired.pk not in {row.user_id for row in _mention_rows(post)}
