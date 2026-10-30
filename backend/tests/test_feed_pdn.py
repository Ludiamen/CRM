"""T-7111: предупреждение о ПДн в ленте (FR-612). Сценарий 15 спеки среза 007, пункты 1–4.

Адрес почты и номер телефона в тексте записи, в названии и месте события, в комментарии и при правке записи и
комментария: ответ с предупреждением (список найденного, «Исправить», «Опубликовать всё равно» / «Сохранить всё
равно»), записи нет, введённое остаётся в форме того же ответа; с `pdn_confirmed=1` запись сохраняется. Проверка своя,
без разбора Markdown и без исключения кода (план: «Предупреждение о ПДн»; CONTRACT-007, 5.3, 10.2, 12.4). Код среза
на уровне модуля не импортируется: имена берутся внутри тестов (CONTRACT-007, шапка). Адреса и телефоны собираются из
частей (`email_of`, `phone_of`; решение 23 задач).
"""
from datetime import timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from tests import support
from tests import support_feed as feed
from tests.support import HX

pytestmark = pytest.mark.django_db

MOSCOW = ZoneInfo("Europe/Moscow")


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


def _email(local: str = "ivanov") -> str:
    return feed.email_of(local, "example.org")


def _phone() -> str:
    return feed.phone_of("+7", "912", "345", "67", "89")


def _form(**over) -> dict:
    data = {"kind": "post", "text": "Собрание завтра", "to": ["all"]}
    data.update(over)
    return data


def _event_form(**over) -> dict:
    start = (timezone.now() + timedelta(days=3)).astimezone(MOSCOW).replace(minute=0, second=0, microsecond=0)
    data = _form(kind="event", text="", event_title="Переезд серверной", event_place="Корпус 2",
                 event_start=start.strftime("%Y-%m-%dT%H:%M"),
                 event_end=(start + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"))
    data.update(over)
    return data


def _publish(session, data, **extra):
    return session.client.post("/feed/posts/", data, **extra)


def _warning(response):
    """Блок предупреждения о ПДн в ответе (ровно один)."""
    assert response.status_code == 200, f"ждали 200 с предупреждением, получили {response.status_code}"
    return q1(tree(response), None, data_feed_pdn=True)


def _items(response) -> list[str]:
    return [node.text() for node in q(tree(response), "li", data_feed_pdn_item=True)]


def _core_comments(post) -> int:
    return support.model("core.Comment").objects.filter(object_ref=f"feed.post:{post.pk}").count()


def _fresh_post(author, **extra):
    return feed.make_post(author.user, to=("all",), text="Исходный текст", **extra)


# --- запись: предупреждение --------------------------------------------------------------------------------

def test_email_and_phone_in_post_text_show_warning_with_found_list_and_no_post():
    """FR-612, сценарий 15 п. 1: адрес и телефон в тексте — предупреждение со списком найденного, записи нет."""
    writer = feed.as_writer()
    email, phone = _email(), _phone()

    response = _publish(writer, _form(text=f"звонил {phone}, {email}"))

    _warning(response)
    found = _items(response)
    assert sorted(found) == sorted([email, phone])
    assert _Post().objects.count() == 0


def test_warning_has_fix_and_publish_anyway_with_confirm_field():
    """FR-612, сценарий 15 п. 1: кнопки «Исправить» (`pdn-fix`) и «Опубликовать всё равно» (`pdn_confirmed=1`);
    введённое — в полях формы того же ответа."""
    writer = feed.as_writer()
    text = f"пишите на {_email()}"

    response = _publish(writer, _form(text=text))

    root = tree(response)
    _warning(response)
    fix = q1(root, "button", data_action="pdn-fix")
    assert fix.text() == "Исправить"
    confirm = q1(root, "button", name="pdn_confirmed", value="1")
    assert confirm.text() == "Опубликовать всё равно"
    form = next((node for node in confirm.ancestors() if node.tag == "form"), None)
    assert form is not None, "кнопка «Опубликовать всё равно» стоит вне формы: повторить POST нечем"
    field = q1(form, "textarea", name="text")
    assert text in field.raw_text()


def test_found_items_in_warning_are_escaped():
    """FR-612: найденное и введённое выводятся экранированными, разметка из текста не исполняется."""
    writer = feed.as_writer()
    email = _email("a.b")
    hostile = '"><img src=x onerror=alert(1)> <b>жирный</b> <script>alert(2)</script>'

    response = _publish(writer, _form(text=f"{hostile} {email}"))

    _warning(response)
    assert _items(response) == [email]
    body = response.content.decode("utf-8")
    assert "<img src=x onerror" not in body
    assert "<b>жирный</b>" not in body
    assert "<script>alert(2)</script>" not in body
    assert "&lt;script&gt;" in body


def test_pdn_in_event_title_or_place_shows_warning():
    """FR-612: название и место события проверяются так же, как текст; записи нет."""
    writer = feed.as_writer()
    email, phone = _email("events"), _phone()

    in_title = _publish(writer, _event_form(event_title=f"Встреча, писать {email}"))
    _warning(in_title)
    assert _items(in_title) == [email]

    in_place = _publish(writer, _event_form(event_place=f"Кабинет, тел. {phone}"))
    _warning(in_place)
    assert _items(in_place) == [phone]

    assert _Post().objects.count() == 0


def test_fix_keeps_entered_values_in_form_and_creates_no_post():
    """FR-612, сценарий 15 п. 2: «Исправить» — действие клиента над тем же ответом: форма с введённым, записи нет
    (решение 47 задач)."""
    writer = feed.as_writer()
    text = f"контакт {_email('fix')}"

    response = _publish(writer, _event_form(text=text, event_title="Название для правки", event_place="Место для правки"))

    root = tree(response)
    _warning(response)
    assert text in q1(root, "textarea", name="text").raw_text()
    assert q1(root, "input", name="event_title").attrs.get("value") == "Название для правки"
    assert q1(root, "input", name="event_place").attrs.get("value") == "Место для правки"
    assert "checked" in q1(root, "input", name="kind", value="event").attrs
    assert q(root, "input", name="to", value="all"), "«Кому» с введённым адресатом потеряно"
    assert _Post().objects.count() == 0


def test_pdn_confirmed_publishes_post():
    """FR-612, сценарий 15 п. 3: тот же POST с `pdn_confirmed=1` публикует запись с прежним текстом."""
    writer = feed.as_writer()
    text = f"звонил {_phone()}, {_email('ok')}"

    response = _publish(writer, _form(text=text, pdn_confirmed="1"))

    assert response.status_code == 302
    assert response["Location"] == "/"
    post = _Post().objects.get()
    assert post.text == text
    assert post.author_id == writer.user.pk


def test_pdn_in_comment_shows_warning_and_confirmed_saves_comment():
    """FR-612, сценарий 15 п. 4: комментарий с адресом — предупреждение, комментария нет; с подтверждением — сохранён."""
    author = feed.as_writer()
    post = _fresh_post(author)
    viewer = feed.as_plain()
    text = f"пишите {_email('comment')}"
    url = f"/feed/{post.pk}/comments/"

    response = viewer.client.post(url, {"text": text})

    root = tree(response)
    _warning(response)
    assert _items(response) == [_email("comment")]
    assert text in q1(root, "textarea", name="text").raw_text()
    assert _core_comments(post) == 0
    assert support.model("feed.FeedComment").objects.filter(post=post).count() == 0

    confirmed = viewer.client.post(url, {"text": text, "pdn_confirmed": "1"})

    assert confirmed.status_code == 302
    saved = support.model("core.Comment").objects.get(object_ref=f"feed.post:{post.pk}")
    assert saved.text == text
    assert confirmed["Location"] == f"/feed/{post.pk}/#c{saved.pk}"


def test_pdn_on_post_edit_shows_save_anyway_and_confirmed_saves_edit():
    """FR-612, сценарий 15 п. 4: при правке записи — «Сохранить всё равно»; без подтверждения текст не меняется."""
    author = feed.as_writer()
    post = _fresh_post(author)
    text = f"новый текст, {_phone()}"
    url = f"/feed/{post.pk}/edit/"

    response = author.client.post(url, {"text": text, "to": ["all"]})

    root = tree(response)
    _warning(response)
    assert _items(response) == [_phone()]
    confirm = q1(root, "button", name="pdn_confirmed", value="1")
    assert confirm.text() == "Сохранить всё равно"
    assert "Опубликовать всё равно" not in response.content.decode("utf-8")
    post.refresh_from_db()
    assert post.text == "Исходный текст"
    assert post.edited_at is None

    confirmed = author.client.post(url, {"text": text, "to": ["all"], "pdn_confirmed": "1"})

    assert confirmed.status_code == 302
    assert confirmed["Location"] == f"/feed/{post.pk}/"
    post.refresh_from_db()
    assert post.text == text
    assert post.edited_at is not None


def test_pdn_on_comment_edit_shows_warning_and_confirmed_saves_edit():
    """FR-612, сценарий 15 п. 4: при правке комментария — то же предупреждение; с подтверждением правка сохранена."""
    author = feed.as_writer()
    post = _fresh_post(author)
    commenter = feed.as_plain()
    comment = feed.comment(post, commenter.user, "Первый вариант")
    text = f"исправил, теперь {_email('edit')}"
    url = f"/feed/comments/{comment.pk}/edit/"

    response = commenter.client.post(url, {"text": text})

    root = tree(response)
    _warning(response)
    assert _items(response) == [_email("edit")]
    assert q1(root, "button", name="pdn_confirmed", value="1").text() == "Сохранить всё равно"
    comment.refresh_from_db()
    assert comment.text == "Первый вариант"

    confirmed = commenter.client.post(url, {"text": text, "pdn_confirmed": "1"})

    assert confirmed.status_code == 302
    assert confirmed["Location"] == f"/feed/{post.pk}/#c{comment.pk}"
    comment.refresh_from_db()
    assert comment.text == text


# --- список найденного, шаблоны, HTMX, без находок -------------------------------------------------------------

def test_found_list_without_duplicates_and_at_most_20_items():
    """FR-612: список без повторов и не больше 20 строк — и на странице, и в `pdn.find_plain`."""
    from apps.feed.services import pdn

    writer = feed.as_writer()
    distinct = [_email(f"user{number:02d}") for number in range(25)]
    text = " ".join(distinct + [distinct[0], distinct[1], distinct[0]])

    response = _publish(writer, _form(text=text))

    _warning(response)
    shown = _items(response)
    assert len(shown) == 20
    assert len(set(shown)) == 20
    assert set(shown) <= set(distinct)

    twice = pdn.find_plain(f"{_email('same')} {_phone()}", f"{_email('same')} {_phone()}")
    assert sorted(twice) == sorted([_email("same"), _phone()])
    assert len(pdn.find_plain(text)) == 20
    assert len(set(pdn.find_plain(text))) == 20


def test_address_in_backticks_and_markdown_still_found():
    """FR-612: исключения для кода нет, текст ленты без разметки — адрес в обратных кавычках, в блоке кода и в
    ссылке `mailto:` найден (в отличие от статьи базы знаний)."""
    from apps.feed.services import pdn

    email, phone = _email("code"), _phone()

    assert pdn.find_plain(f"`{email}`") == [email]
    assert pdn.find_plain(f"```\n{phone}\n```") == [phone]
    assert pdn.find_plain(f"[написать](mailto:{email})") == [email]
    assert pdn.find_plain(f"**{email}**") == [email]

    writer = feed.as_writer()
    response = _publish(writer, _form(text=f"в коде `{email}` и ```{phone}```"))
    _warning(response)
    assert sorted(_items(response)) == sorted([email, phone])
    assert _Post().objects.count() == 0


def test_htmx_warning_returns_200_fragment():
    """FR-612, решение 18 задач: запрос HTMX получает 200 с фрагментом (без `<html>`), записи нет; то же у комментария."""
    writer = feed.as_writer()
    email = _email("htmx")

    response = _publish(writer, _form(text=f"почта {email}"), **HX)

    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "<html" not in body.lower()
    assert _items(response) == [email]
    assert q1(tree(response), "button", name="pdn_confirmed", value="1")
    assert _Post().objects.count() == 0

    post = _fresh_post(writer)
    commented = writer.client.post(f"/feed/{post.pk}/comments/", {"text": f"почта {email}"}, **HX)
    assert commented.status_code == 200
    assert "<html" not in commented.content.decode("utf-8").lower()
    assert _items(commented) == [email]
    assert _core_comments(post) == 0


def test_text_without_email_or_phone_publishes_without_warning():
    """FR-612: нет почты и телефона — публикация без предупреждения (десять цифр без `+7` и `8` — не телефон)."""
    writer = feed.as_writer()

    response = _publish(writer, _form(text="Кабинет 12-34, ИНН 1234567890, звоните позже"))

    assert response.status_code == 302
    assert _Post().objects.get().text == "Кабинет 12-34, ИНН 1234567890, звоните позже"

    answered = _publish(writer, _form(text="Ещё одна запись без адресов"), **HX)
    assert answered.status_code == 200
    root = tree(answered)
    assert not q(root, None, data_feed_pdn=True)
    assert q(root, None, data_post_id=True), "ответ HTMX не несёт новую запись"
    assert _Post().objects.count() == 2
