"""T-7117: правка записи — `GET/POST /feed/<id>/edit/` (FR-610, FR-620, FR-640, FR-642). План: «Правка и удаление»
(правка записи), «Контракты» (`/feed/<id>/edit/`), «Тексты отказов»; CONTRACT-007: 5.3 (`posts.edit`,
`recipients.parse(saved=…)`), 10.1, 10.2, 12.2 (таблетки «Кому»), 12.4 (ПДн), 13.1.

Правит только автор (модератор — нет); «Кому» только расширяется; сохранённые адресаты остаются, даже если узел
удалён или человек уволен; всего адресатов `to` не больше 50; «Всем» без права — отказ, а стоящее «Всем» остаётся
(FR-640); вид не меняется. Замок строки записи — по SQL (решение 6 задач). Тексты отказов — литералы раздела 13
(решение 19 задач). ПДн собираются из частей. Код среза на уровне модуля не импортируется.
"""
from html.parser import HTMLParser

import pytest
from django.apps import apps as django_apps
from django.utils import timezone

from tests import support
from tests import support_feed as fd
from tests import support_org as org
from tests.support import HX

pytestmark = pytest.mark.django_db

TEXT_EMPTY = "Напишите текст"
TEXT_ONLY_ADD = "Адресатов можно только добавить"
TEXT_INVALID = "Выберите, кому адресована запись"
TEXT_TOO_MANY = "Не больше 50 адресатов"
TEXT_ALL_DENIED = "Писать всем вам не разрешено"
TEXT_NOT_FOUND = "Не найдено"


# --- разбор разметки (помощник только этого файла) -----------------------------------------------------------------

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
        super().__init__()
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


def tree(response_or_html) -> Node:
    html = response_or_html if isinstance(response_or_html, str) else response_or_html.content.decode("utf-8")
    parser = _Tree()
    parser.feed(html)
    return parser.root


def q(scope, tag=None, **attrs) -> list:
    """Потомки `scope` по тегу и атрибутам; имя с дефисом пишется через `_`; значение `True` — «атрибут есть»."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            found.append(node)
    return found


# --- помощники файла ------------------------------------------------------------------------------------------

def _url(post) -> str:
    return f"/feed/{post.pk}/edit/"


def _saved(post) -> list:
    """Значения `to` сохранённых адресатов записи (как их шлёт форма)."""
    values = ["all"] if post.to_all else []
    for row in support.model("feed.Recipient").objects.filter(post=post, via="to").order_by("pk"):
        values.append(f"u{row.unit_id}" if row.kind == "unit" else f"p{row.user_id}")
    return values


def _send(session, post, text="Новый текст записи", to=None, hx=False, **extra):
    data = {"text": text, "to": _saved(post) if to is None else to}
    data.update(extra)
    return session.client.post(_url(post), data, **(HX if hx else {}))


def _rows(post, via="to") -> set:
    return {(row.kind, row.unit_id, row.user_id)
            for row in support.model("feed.Recipient").objects.filter(post=post, via=via)}


def _fresh(post):
    return support.model("feed.Post").objects.get(pk=post.pk)


def _errors(response, field: str, code: str) -> list:
    return q(tree(response), data_error=field, data_code=code)


def _plain_post(**extra):
    """Запись автора с правом «Писать всем» адресату-человеку; возвращает автора, адресата, запись."""
    author, viewer = fd.as_writer(), fd.as_plain()
    return author, viewer, fd.make_post(author.user, to=(viewer.user,), text="Старый текст", **extra)


# --- автор правит ---------------------------------------------------------------------------------------------

def test_author_edit_updates_text_sets_edited_at_and_shows_changed_time(clock):
    """FR-620: автор правит текст в любое время; `edited_at` — время правки; карточка показывает «изменено» и время."""
    author, viewer, post = _plain_post()
    assert post.edited_at is None
    clock.advance(minutes=7)
    response = _send(author, post, "Новый текст записи")
    assert response.status_code == 302
    assert response["Location"] == f"/feed/{post.pk}/"
    post = _fresh(post)
    assert post.text == "Новый текст записи"
    assert post.edited_at == timezone.now()
    page = tree(author.client.get(f"/feed/{post.pk}/"))
    marks = q(page, data_feed_edited=True)
    assert marks
    assert "изменено" in marks[0].text()
    times = q(marks[0], "time", data_at=True)
    assert times
    assert fd.moscow_text(post.edited_at) in times[0].text()


def test_edit_overwrites_text_without_keeping_edit_history():
    """FR-620: правка перезаписывает текст, истории правок нет ни в моделях, ни на странице."""
    author, viewer, post = _plain_post()
    _send(author, post, "Первая версия текста")
    _send(author, post, "Вторая версия текста")
    assert _fresh(post).text == "Вторая версия текста"
    names = [model._meta.model_name for model in django_apps.get_app_config("feed").get_models()]
    assert not [name for name in names if any(word in name for word in ("history", "revision", "version"))]
    html = author.client.get(f"/feed/{post.pk}/").content.decode("utf-8")
    assert "Вторая версия текста" in html
    assert "Первая версия текста" not in html
    assert "Старый текст" not in html


def test_edit_others_post_returns_403_on_get_and_post():
    """FR-620: адресат, который видит запись, но не автор, правит её — 403 и на GET, и на POST; запись цела."""
    author, viewer, post = _plain_post()
    assert viewer.client.get(f"/feed/{post.pk}/").status_code == 200
    assert viewer.client.get(_url(post)).status_code == 403
    assert _send(viewer, post, "Чужая правка").status_code == 403
    post = _fresh(post)
    assert post.text == "Старый текст"
    assert post.edited_at is None


def test_moderator_edit_others_post_returns_403_on_get_and_post():
    """FR-620: модератор, который видит запись, её не правит — 403 на GET и POST."""
    author, moderator = fd.as_writer(), fd.as_moderator()
    post = fd.make_post(author.user, to=(moderator.user,), text="Старый текст")
    assert moderator.client.get(f"/feed/{post.pk}/").status_code == 200
    assert moderator.client.get(_url(post)).status_code == 403
    assert _send(moderator, post, "Правка модератора").status_code == 403
    assert _fresh(post).text == "Старый текст"


def test_edit_invisible_post_returns_404_like_nonexistent():
    """FR-620 (решение 18 задач): запись не видна — 404 «Не найдено», как у несуществующей; запись цела."""
    author, viewer, post = _plain_post()
    outsider = fd.as_plain()
    missing = support.model("feed.Post").objects.order_by("-pk").first().pk + 1000
    got = outsider.client.get(_url(post))
    gone = outsider.client.get(f"/feed/{missing}/edit/")
    assert got.status_code == gone.status_code == 404
    assert TEXT_NOT_FOUND in got.content.decode("utf-8")
    assert TEXT_NOT_FOUND in gone.content.decode("utf-8")
    sent = _send(outsider, post, "Чужая правка")
    assert sent.status_code == 404
    assert TEXT_NOT_FOUND in sent.content.decode("utf-8")
    assert _fresh(post).text == "Старый текст"


# --- «Кому» расширяется ---------------------------------------------------------------------------------------

def test_person_added_by_edit_sees_post_from_now_on():
    """FR-620: человек, добавленный правкой, видит запись с этого момента (строка `to`); прежний адресат — по-прежнему."""
    author, first, post = _plain_post()
    second = fd.as_plain()
    assert second.client.get(f"/feed/{post.pk}/").status_code == 404
    response = _send(author, post, to=[f"p{first.user.pk}", f"p{second.user.pk}"])
    assert response.status_code == 302
    assert ("user", None, second.user.pk) in _rows(post)
    assert ("user", None, first.user.pk) in _rows(post)
    assert second.client.get(f"/feed/{post.pk}/").status_code == 200
    assert first.client.get(f"/feed/{post.pk}/").status_code == 200


def test_unit_added_by_edit_members_see_post_from_now_on():
    """FR-620: подразделение, добавленное правкой, — его сотрудники видят запись с этого момента."""
    author, first, post = _plain_post()
    unit = org.make_unit()
    member = fd.as_plain()
    org.make_member(member.user, unit)
    assert member.client.get(f"/feed/{post.pk}/").status_code == 404
    response = _send(author, post, to=[f"p{first.user.pk}", f"u{unit.pk}"])
    assert response.status_code == 302
    assert ("unit", unit.pk, None) in _rows(post)
    assert member.client.get(f"/feed/{post.pk}/").status_code == 200


def test_edit_set_without_saved_recipient_refused_only_add_recipients_unchanged():
    """FR-620: набор без сохранённого адресата — отказ «Адресатов можно только добавить»; адресаты и текст прежние."""
    author, first, post = _plain_post()
    second, third = fd.as_plain(), fd.as_plain()
    support.model("feed.Recipient").objects.create(
        post=post, kind="user", user=second.user, via="to", published_at=post.published_at)
    before = _rows(post)
    assert len(before) == 2
    response = _send(author, post, "Новый текст записи", to=[f"p{first.user.pk}", f"p{third.user.pk}"])
    assert response.status_code == 200
    errors = _errors(response, "to", "only_add_recipients")
    assert len(errors) == 1
    assert TEXT_ONLY_ADD in errors[0].text()
    assert _rows(post) == before
    assert _fresh(post).text == "Старый текст"


def test_edit_form_shows_saved_recipients_without_remove_control():
    """FR-620: форма правки показывает сохранённых адресатов таблетками `[data-saved]` со скрытым `to`, без крестика."""
    author, first, post = _plain_post()
    unit = org.make_unit()
    support.model("feed.Recipient").objects.create(
        post=post, kind="unit", unit_id=unit.pk, via="to", published_at=post.published_at)
    response = author.client.get(_url(post))
    assert response.status_code == 200
    page = tree(response)
    assert q(page, data_feed_page="edit")
    for value in (f"p{first.user.pk}", f"u{unit.pk}"):
        pills = q(page, data_to_pill=value)
        assert len(pills) == 1, value
        assert "data-saved" in pills[0].attrs
        hidden = q(pills[0], "input", name="to")
        assert [node.attrs.get("value") for node in hidden] == [value]
        assert not q(pills[0], "button", data_action="to-remove")
    assert not q(page, "button", data_action="to-remove")


def test_post_with_deleted_unit_and_dismissed_recipient_saves_and_keeps_them():
    """FR-620: сохранённые адресаты — удалённый узел и уволенный человек — остаются и не мешают сохранить правку."""
    author = fd.as_writer()
    unit = org.make_unit()
    dismissed = support.make_employee(state="dismissed")
    post = fd.make_post(author.user, to=(f"u{unit.pk}", dismissed), text="Старый текст")
    support.model("org.Unit").objects.filter(pk=unit.pk).delete()
    before = _rows(post)
    assert len(before) == 2
    response = _send(author, post, "Новый текст записи")
    assert response.status_code == 302
    assert _fresh(post).text == "Новый текст записи"
    assert _rows(post) == before


def test_edit_adding_nonexistent_unit_or_dismissed_person_refused():
    """FR-620, FR-610: добавленный узел должен существовать, добавленный человек — быть действующим; иначе отказ."""
    author, first, post = _plain_post()
    dismissed = support.make_employee(state="dismissed")
    before = _rows(post)
    for extra in ("u987654", f"p{dismissed.pk}", "p987654"):
        response = _send(author, post, "Новый текст записи", to=[f"p{first.user.pk}", extra])
        assert response.status_code == 200, extra
        errors = _errors(response, "to", "recipient_invalid")
        assert len(errors) == 1, extra
        assert TEXT_INVALID in errors[0].text()
        assert _rows(post) == before
        assert _fresh(post).text == "Старый текст"


def test_edit_saved_and_new_recipients_total_50_accepted_51_refused_with_reason():
    """FR-610, FR-642: сохранённых и новых адресатов `to` всего не больше 50: 50 принимаются, 51 — отказ."""
    author = fd.as_writer()
    newcomers = [support.make_employee() for _ in range(21)]
    saved = tuple(f"u{9_000_000 + number}" for number in range(30))   # сохранённые узлы без проверки существования
    accepted = fd.make_post(author.user, to=saved, text="Старый текст")
    refused = fd.make_post(author.user, to=saved, text="Старый текст")
    ok = _send(author, accepted, to=_saved(accepted) + [f"p{user.pk}" for user in newcomers[:20]])
    assert ok.status_code == 302
    assert len(_rows(accepted)) == 50
    assert _fresh(accepted).text == "Новый текст записи"
    bad = _send(author, refused, to=_saved(refused) + [f"p{user.pk}" for user in newcomers[:21]])
    assert bad.status_code == 200
    errors = _errors(bad, "to", "too_many_recipients")
    assert len(errors) == 1
    assert TEXT_TOO_MANY in errors[0].text()
    assert len(_rows(refused)) == 30
    assert _fresh(refused).text == "Старый текст"


def test_edit_adding_all_without_post_all_refused_post_all_not_allowed():
    """FR-610, FR-620: «Всем» при правке без права «Писать всем» — отказ «Писать всем вам не разрешено»."""
    plain_author, first = fd.as_plain(), fd.as_plain()
    mine = fd.make_post(plain_author.user, to=(first.user,), text="Старый текст")
    response = _send(plain_author, mine, to=[f"p{first.user.pk}", "all"])
    assert response.status_code == 200
    errors = _errors(response, "to", "post_all_denied")
    assert len(errors) == 1
    assert TEXT_ALL_DENIED in errors[0].text()
    assert _fresh(mine).to_all is False
    assert _fresh(mine).text == "Старый текст"


def test_edit_keeps_saved_all_after_post_all_right_removed():
    """FR-640, FR-620: стоящее «Всем» остаётся при правке, даже если у автора право «Писать всем» уже снято."""
    author = fd.as_writer()
    post = fd.make_post(author.user, to=("all",), text="Старый текст")
    fd.without_post_all(author.user.roles.get())
    response = _send(author, post, "Новый текст записи", to=["all"])
    assert response.status_code == 302
    post = _fresh(post)
    assert post.to_all is True
    assert post.text == "Новый текст записи"


# --- что правка не меняет, отказы ------------------------------------------------------------------------------

def test_edit_ignores_sent_kind_and_kind_stays_unchanged():
    """FR-620: вид записи не меняется; присланный `kind` и поля чужого вида игнорируются."""
    author, viewer, post = _plain_post()
    response = _send(author, post, kind="important", term="day", event_title="Событие", event_place="Зал",
                     event_start="2030-01-01T10:00", event_end="2030-01-01T11:00")
    assert response.status_code == 302
    post = _fresh(post)
    assert post.kind == "post"
    assert post.important_until is None
    assert post.event_title is None
    assert post.text == "Новый текст записи"


def test_edit_empty_text_refused_with_reason_post_unchanged():
    """FR-620, FR-642: пустой текст (и из одних пробелов) — «Напишите текст» у поля; запись и `edited_at` прежние."""
    author, viewer, post = _plain_post()
    for empty in ("", "   \n "):
        response = _send(author, post, empty)
        assert response.status_code == 200
        errors = _errors(response, "text", "empty_text")
        assert len(errors) == 1
        assert TEXT_EMPTY in errors[0].text()
        post_now = _fresh(post)
        assert post_now.text == "Старый текст"
        assert post_now.edited_at is None


def test_edit_with_email_or_phone_shows_pdn_warning_like_publish():
    """FR-620: адрес почты или телефон в тексте — предупреждение о ПДн, как при публикации; без подтверждения запись
    не меняется, с «Сохранить всё равно» — сохраняется."""
    author, viewer, post = _plain_post()
    for found in (fd.email_of(), fd.phone_of()):
        text = f"Свяжитесь: {found}"
        response = _send(author, post, text)
        assert response.status_code == 200
        page = tree(response)
        assert len(q(page, data_feed_pdn=True)) >= 1
        items = q(page, "li", data_feed_pdn_item=True)
        assert any(found in item.text() for item in items)
        assert q(page, "button", data_action="pdn-fix")
        confirm = q(page, "button", name="pdn_confirmed", value="1")
        assert len(confirm) == 1
        assert "Сохранить всё равно" in confirm[0].text()
        assert _fresh(post).text == "Старый текст"
        again = _send(author, post, text, pdn_confirmed="1")
        assert again.status_code == 302
        assert _fresh(post).text == text
        _send(author, post, "Старый текст")


def test_edit_locks_post_row_with_select_for_update():
    """FR-620: правка берёт строку записи под `SELECT … FOR UPDATE` (решение 6 задач)."""
    from apps.feed.services import posts

    author, viewer, post = _plain_post()
    data = {"text": "Новый текст записи", "to": _saved(post)}
    with fd.capture_sql() as sqls:
        posts.edit(author.user, post.pk, data)
    fd.assert_for_update(sqls, "feed_post")
    assert _fresh(post).text == "Новый текст записи"


def test_edit_htmx_refusal_returns_200_fragment_with_reason_and_entered_values():
    """FR-642: отказ при правке по HTMX — 200 и фрагмент без `<html>` с причиной у поля и введёнными значениями."""
    author, first, post = _plain_post()
    other = fd.as_plain()
    response = _send(author, post, "Введённый новый текст", to=[f"p{other.user.pk}"], hx=True)
    assert response.status_code == 200
    html = response.content.decode("utf-8")
    assert "<html" not in html.lower()
    page = tree(html)
    errors = q(page, data_error="to", data_code="only_add_recipients")
    assert len(errors) == 1
    assert TEXT_ONLY_ADD in errors[0].text()
    area = q(page, "textarea", name="text")
    assert area and "Введённый новый текст" in area[0].text()
    assert _fresh(post).text == "Старый текст"
