"""T-7107: форма записи, «Кому», публикация (FR-608, FR-609, FR-610, FR-640, FR-642). Сценарий 1 спеки 007.

Тексты отказов — литералы раздела 13 контракта (решение 19 задач), не импорт `feed/texts.py`. Службы среза и модели —
внутри тестов или через `support.model`. Гонок нет: «после фиксации» — `django_capture_on_commit_callbacks`
(решение 6 задач), время — фикстура `clock` (решение 5). Адреса и телефоны в данных не нужны; ПДн в текстах нет.
"""
import importlib
from datetime import timedelta
from html.parser import HTMLParser

import pytest
from django.contrib.postgres.search import SearchQuery
from django.utils import timezone

from tests import support
from tests import support_feed as sf
from tests import support_org as org
from tests.support import model

pytestmark = pytest.mark.django_db

HX = {"HX-Request": "true"}
TEXT_REFUSAL_NO_RECIPIENTS = "Выберите, кому адресована запись"


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

    def raw_text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                collect(child) if isinstance(child, Node) else parts.append(child)

        collect(self)
        return "".join(parts)

    def text(self) -> str:
        return " ".join(self.raw_text().split())


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


def _tree(response_or_html) -> Node:
    html = response_or_html if isinstance(response_or_html, str) else response_or_html.content.decode("utf-8")
    parser = _Tree()
    parser.feed(html)
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


def _refusals(response) -> list[tuple[str, str, str]]:
    """Отказы формы: пары (поле, код, текст) — `[data-error][data-code]` в ответе."""
    return [(node.attrs["data-error"], node.attrs.get("data-code", ""), node.text())
            for node in _tree(response).walk() if "data-error" in node.attrs]


def _body(response) -> str:
    return response.content.decode("utf-8")


# --- помощники файла ---------------------------------------------------------------------------------------

def _services():
    return importlib.import_module("apps.feed.services.posts")


def _person(**extra):
    return support.make_employee(totp=False, **extra)


def _data(text: str = "Текст записи", to=(), **extra) -> dict:
    return {"kind": "post", "text": text, "to": list(to), **extra}


def _publish(session, data: dict, *, hx: bool = False):
    return session.client.post("/feed/posts/", data, headers=HX if hx else {})


def _posts():
    return model("feed.Post").objects.order_by("id")


def _event_fields(clock, **extra) -> dict:
    start = timezone.now() + timedelta(days=2)
    return {"event_title": "Собрание", "event_place": "Корпус 1", "event_start": sf.moscow_text(start),
            "event_end": sf.moscow_text(start + timedelta(hours=1)), **extra}


# --- 1. форма -----------------------------------------------------------------------------------------------

def test_form_default_kind_is_post_with_three_kinds_and_fields_of_all_kinds_in_markup():
    """FR-608: над лентой форма: три вида, «Сообщение» отмечен; поля всех видов в разметке (без JS форма работает)."""
    session = sf.as_plain()
    response = session.client.get("/")
    assert response.status_code == 200
    tree = _tree(response)
    (form,) = _find(tree, "form", id="feed-form")
    assert "data-feed-form" in form.attrs
    radios = _find(form, "input", name="kind")
    assert [node.attrs.get("value") for node in radios] == ["post", "important", "event"]
    assert [node.attrs.get("value") for node in radios if "checked" in node.attrs] == ["post"]
    assert _find(form, "textarea", name="text")
    assert _find(form, "input", name="to") == [] or all(node.attrs.get("type") == "hidden"
                                                         for node in _find(form, "input", name="to"))
    assert {node.attrs.get("value") for node in _find(form, "input", name="term", type="radio")} \
        >= {"day", "week", "month", "date"}
    assert _find(form, "input", name="until", type="date")
    assert _find(form, "input", name="event_title")
    assert _find(form, "input", name="event_place")
    assert _find(form, "input", name="event_start", type="datetime-local")
    assert _find(form, "input", name="event_end", type="datetime-local")
    assert _find(form, "input", type="file", data_feed_upload="post")
    assert _find(form, data_kind_fields="important") and _find(form, data_kind_fields="event")
    assert any("Опубликовать" in button.text() for button in _find(form, "button"))


def test_form_preselects_all_for_employee_with_post_all():
    """FR-608, FR-610: у держателя «Писать всем» в «Кому» при открытии формы уже стоит «Всем»."""
    session = sf.as_writer()
    tree = _tree(session.client.get("/"))
    (form,) = _find(tree, "form", id="feed-form")
    (pill,) = _find(form, data_to_pill="all")
    assert "Всем" in pill.text()
    (hidden,) = _find(pill, "input", name="to")
    assert hidden.attrs.get("type") == "hidden" and hidden.attrs.get("value") == "all"
    assert _find(pill, "button", data_action="to-remove"), "«Всем» снимается крестиком до публикации"


def test_form_without_post_all_has_no_all_option_and_offers_units_and_people():
    """FR-610, FR-640: без права «Писать всем» пункта «Всем» нет; подсказка «Кому» даёт и людей, и подразделения."""
    session = sf.as_plain()
    unit = org.make_unit("Отдел Омега")
    colleague = _person(full_name="Омегов Олег")
    tree = _tree(session.client.get("/"))
    (form,) = _find(tree, "form", id="feed-form")
    assert _find(form, data_to_pill="all") == []
    assert [node for node in _find(form, "input", name="to") if node.attrs.get("value") == "all"] == []
    assert _find(form, "input", data_feed_picker="to")
    picked = _tree(session.client.get("/feed/pick/", {"scope": "to", "q": "омег"}, headers=HX))
    values = {node.attrs["data-pick-value"] for node in _find(picked, data_pick_value=True)}
    assert f"p{colleague.pk}" in values and f"u{unit.pk}" in values


# --- 2. отказы формы ----------------------------------------------------------------------------------------

def test_publish_with_to_all_without_post_all_rejected_with_reason_and_no_post():
    """FR-610, FR-640, FR-642: запрос с «Всем» без права отклоняется на сервере: текст у поля «Кому», записи нет."""
    session = sf.as_plain()
    response = _publish(session, _data(to=["all"]))
    assert response.status_code == 200
    assert _refusals(response) == [("to", "post_all_denied", "Писать всем вам не разрешено")]
    assert _posts().count() == 0


def test_server_takes_only_fields_of_selected_kind():
    """FR-608: сервер берёт только поля выбранного вида; лишние поля других видов отбрасываются, неизвестный вид — «Сообщение»."""
    session = sf.as_writer()
    clock = None
    mixed = {"term": "week", "event_title": "Лишнее", "event_place": "Лишнее", **_event_fields(clock)}
    assert _publish(session, _data("Простое сообщение", ["all"], **mixed)).status_code == 302
    plain = _posts().get(text="Простое сообщение")
    assert plain.kind == "post" and plain.important_until is None
    assert plain.event_title is None and plain.event_place is None
    assert plain.event_start is None and plain.event_end is None and plain.remind_at is None

    body = _data("Важная запись", ["all"], term="week", **_event_fields(clock))
    body["kind"] = "important"
    assert _publish(session, body).status_code == 302
    important = _posts().get(text="Важная запись")
    assert important.kind == "important" and important.important_until is not None
    assert important.event_title is None and important.event_start is None and important.event_end is None

    body = _data("Запись-событие", ["all"], term="week", **_event_fields(clock))
    body["kind"] = "event"
    assert _publish(session, body).status_code == 302
    event = _posts().get(text="Запись-событие")
    assert event.kind == "event" and event.event_title == "Собрание" and event.event_place == "Корпус 1"
    assert event.important_until is None

    body = _data("Неизвестный вид", ["all"])
    body["kind"] = "unknown-kind"
    assert _publish(session, body).status_code == 302
    assert _posts().get(text="Неизвестный вид").kind == "post"


def test_empty_and_whitespace_only_text_rejected_write_text_at_field_input_kept():
    """FR-609, FR-642: пустой текст и текст из одних пробелов — «Напишите текст» у поля текста; введённое сохранено."""
    session = sf.as_plain()
    colleague = _person()
    for blank in ("", "   ", " \n\t \n "):
        response = _publish(session, _data(blank, [f"p{colleague.pk}"]))
        assert response.status_code == 200
        assert _refusals(response) == [("text", "empty_text", "Напишите текст")], repr(blank)
        tree = _tree(response)
        assert [node.attrs.get("value") for node in _find(tree, "input", name="to")] == [f"p{colleague.pk}"]
        assert _find(tree, "textarea", name="text")
    assert _posts().count() == 0


def test_text_of_10000_chars_accepted_and_10001_rejected_with_limit_at_field():
    """FR-609, FR-642: 10 000 знаков — принят; 10 001 — «Предел: 10 000 знаков» у поля текста, введённое сохранено."""
    session = sf.as_plain()
    colleague = _person()
    assert _publish(session, _data("ж" * 10000, [f"p{colleague.pk}"])).status_code == 302
    assert len(_posts().get().text) == 10000
    too_long = "ж" * 10001
    response = _publish(session, _data(too_long, [f"p{colleague.pk}"]))
    assert response.status_code == 200
    assert _refusals(response) == [("text", "too_long", "Предел: 10 000 знаков")]
    (area,) = _find(_tree(response), "textarea", name="text")
    assert area.raw_text().strip("\r\n") == too_long, "введённый текст остался в поле"
    assert _posts().count() == 1


def test_publish_without_recipient_rejected_choose_recipient_at_field():
    """FR-610, FR-642: без адресата запись не публикуется: «Выберите, кому адресована запись» у поля «Кому»."""
    for session in (sf.as_plain(), sf.as_writer()):
        response = _publish(session, _data("Без адресата"))
        assert response.status_code == 200
        assert _refusals(response) == [("to", "no_recipients", TEXT_REFUSAL_NO_RECIPIENTS)]
        assert "Без адресата" in _body(response), "введённый текст остался в форме"
    assert _posts().count() == 0


def test_50_recipients_accepted_51_rejected_unit_and_all_count_as_one():
    """FR-610, FR-642: до 50 адресатов; подразделение (с любым числом людей) и «Всем» считаются по одному."""
    writer = sf.as_writer()
    plain = sf.as_plain()
    people = [_person() for _ in range(51)]
    people_refs = [f"p{person.pk}" for person in people]
    unit = org.make_unit("Отдел Двенадцать")
    for person in people[:3]:
        org.make_member(person, unit)

    assert _publish(plain, _data("Пятьдесят людей", people_refs[:50])).status_code == 302
    response = _publish(plain, _data("Пятьдесят один человек", people_refs))
    assert response.status_code == 200
    assert _refusals(response) == [("to", "too_many_recipients", "Не больше 50 адресатов")]

    # «Всем» + подразделение (с тремя людьми) + 48 людей = 50 адресатов
    assert _publish(writer, _data("Все, узел и сорок восемь", ["all", f"u{unit.pk}", *people_refs[:48]])) \
        .status_code == 302
    # ещё один человек — 51
    response = _publish(writer, _data("Все, узел и сорок девять", ["all", f"u{unit.pk}", *people_refs[:49]]))
    assert response.status_code == 200
    assert _refusals(response) == [("to", "too_many_recipients", "Не больше 50 адресатов")]
    assert _posts().count() == 2


def test_mentioned_people_not_counted_in_50_recipient_limit():
    """FR-610: упомянутые через «@» в предел 50 не входят (у них свой предел 20, FR-611)."""
    session = sf.as_plain()
    people = [_person() for _ in range(50)]
    mentioned = [_person(), _person()]
    text = "Коллеги " + " ".join(f"@[{person.pk}]" for person in mentioned)
    response = _publish(session, _data(text, [f"p{person.pk}" for person in people]))
    assert response.status_code == 302, _refusals(response)
    post = _posts().get()
    Recipient = model("feed.Recipient")
    assert Recipient.objects.filter(post=post, via="to").count() == 50
    assert set(Recipient.objects.filter(post=post, via="mention").values_list("user_id", flat=True)) \
        == {person.pk for person in mentioned}


def test_nonexistent_unit_dismissed_or_blocked_person_rejected_as_recipient():
    """FR-610: несуществующее подразделение, уволенный и заблокированный человек как адресат отклоняются на сервере."""
    session = sf.as_plain()
    dismissed = _person(state="dismissed")
    blocked = _person(state="blocked")
    missing_unit = model("org.Unit").objects.order_by("-pk").first().pk + 1000
    missing_user = model("core.User").objects.order_by("-pk").first().pk + 1000
    for ref in (f"u{missing_unit}", f"p{dismissed.pk}", f"p{blocked.pk}", f"p{missing_user}"):
        response = _publish(session, _data("Некому", [ref]))
        assert response.status_code == 200, ref
        assert _refusals(response) == [("to", "recipient_invalid", TEXT_REFUSAL_NO_RECIPIENTS)], ref
    assert _posts().count() == 0


def test_invited_employee_accepted_as_recipient():
    """FR-610: приглашённый (ещё не вошедший) сотрудник — допустимый адресат."""
    session = sf.as_plain()
    invited = _person(state="invited")
    assert _publish(session, _data("Для приглашённого", [f"p{invited.pk}"])).status_code == 302
    post = _posts().get()
    assert model("feed.Recipient").objects.filter(post=post, user=invited, via="to").count() == 1


def test_employee_without_roles_publishes_to_unit_and_people_and_sees_no_all_option():
    """FR-608, FR-610, FR-640: сотрудник без ролей публикует подразделению и людям; пункта «Всем» у него нет."""
    session = sf.as_plain()
    assert session.user.roles.count() == 0
    unit = org.make_unit("Отдел Ноль")
    colleague = _person()
    response = _publish(session, _data("Без ролей", [f"u{unit.pk}", f"p{colleague.pk}"]))
    assert response.status_code == 302
    post = _posts().get()
    assert post.author_id == session.user.pk and post.to_all is False
    Recipient = model("feed.Recipient")
    assert Recipient.objects.filter(post=post, kind="unit", unit_id=unit.pk, via="to").count() == 1
    assert Recipient.objects.filter(post=post, kind="user", user=colleague, via="to").count() == 1
    tree = _tree(session.client.get("/"))
    assert _find(tree, data_to_pill="all") == []


def test_htmx_refusal_returns_200_form_fragment_with_reason_and_entered_values():
    """FR-642: отказ на запрос HTMX — 200 с фрагментом формы, причиной у поля и введённым."""
    session = sf.as_plain()
    typed = "Введённый-текст-№7"
    response = _publish(session, _data(typed), hx=True)
    assert response.status_code == 200
    body = _body(response)
    assert "<html" not in body.lower()
    assert _refusals(response) == [("to", "no_recipients", TEXT_REFUSAL_NO_RECIPIENTS)]
    (area,) = _find(_tree(response), "textarea", name="text")
    assert area.raw_text().strip("\r\n") == typed
    assert _posts().count() == 0


# --- 3. публикация ------------------------------------------------------------------------------------------

def test_publish_creates_post_to_rows_mention_rows_file_binding_and_vector(clock, django_capture_on_commit_callbacks):
    """FR-608, FR-610: запись, строки «Кому», строки упоминаний, привязка файла и вектор поиска — одной публикацией."""
    writer = sf.as_writer()
    unit = org.make_unit("Отдел Публикации")
    colleague = _person()
    mentioned = _person(full_name="Упомянутов Умар")
    attached = sf.attach(None, uploaded_by=writer.user)
    text = f"Квартальный отчёт готов @[{mentioned.pk}]"
    with django_capture_on_commit_callbacks(execute=True):
        response = _publish(writer, _data(text, [f"u{unit.pk}", f"p{colleague.pk}"], files=[attached.pk]))
    assert response.status_code == 302
    post = _posts().get()
    assert (post.author_id, post.kind, post.to_all, post.text) == (writer.user.pk, "post", False, text)
    assert post.published_at == timezone.now()
    Recipient = model("feed.Recipient")
    rows = {(row.kind, row.unit_id, row.user_id, row.via) for row in Recipient.objects.filter(post=post)}
    assert rows == {("unit", unit.pk, None, "to"), ("user", None, colleague.pk, "to"),
                    ("user", None, mentioned.pk, "mention")}
    attached.refresh_from_db()
    assert attached.post_id == post.pk and attached.comment_id is None
    assert model("feed.Post").objects.filter(pk=post.pk, search=SearchQuery("отчёт", config="russian")).exists()
    assert not model("feed.Post").objects.filter(pk=post.pk, search=SearchQuery(str(mentioned.pk), config="russian")).exists(), \
        "маркер упоминания в вектор не идёт"


def test_dispatch_create_error_rolls_back_post_recipients_and_file_binding(monkeypatch):
    """FR-608: сбой создания уведомления в той же транзакции откатывает запись, адресатов и привязку файла."""
    writer = sf.as_writer()
    colleague = _person()
    attached = sf.attach(None, uploaded_by=writer.user)

    def broken(kind_code, drafts):
        raise RuntimeError("сбой создания уведомления (подмена теста)")

    monkeypatch.setattr("apps.notify.services.dispatch.create", broken)
    with pytest.raises(RuntimeError):
        _services().publish(writer.user, {"kind": "post", "text": "Откат", "to": [f"p{colleague.pk}"],
                                          "files": [attached.pk]})
    assert _posts().count() == 0
    assert model("feed.Recipient").objects.count() == 0
    attached.refresh_from_db()
    assert attached.post_id is None and attached.comment_id is None


def test_broadcast_runs_only_after_commit(django_capture_on_commit_callbacks):
    """FR-608: рассылка по слою `publish` идёт только после фиксации; до неё сообщений слоя нет."""
    writer = sf.as_writer()
    colleague = _person()
    with sf.layer_spy() as spy:
        with django_capture_on_commit_callbacks(execute=True):
            response = _publish(writer, _data("После фиксации", [f"p{colleague.pk}"]))
            assert response.status_code == 302
            assert spy.calls == [], "до фиксации в слой ничего не отправлено"
        assert spy.calls, "после фиксации рассылка ушла"
    post = _posts().get()
    messages = spy.by_group.get(f"feed.u.{colleague.pk}", [])
    assert [(m["type"], m["post"], m["action"]) for m in messages] == [("feed.event", post.pk, "new")]
    assert spy.aliases and set(spy.aliases) == {"publish"}


def test_htmx_publish_returns_cleared_form_and_own_post_on_top_with_author_to_all_and_time(clock):
    """FR-608, FR-610: ответ HTMX — своя запись (автор, «Всем», время) и очищенная форма с `hx-swap-oob`."""
    writer = sf.as_writer(full_name="Писарев Павел")
    response = _publish(writer, _data("Моя первая запись", ["all"]), hx=True)
    assert response.status_code == 200
    assert "<html" not in _body(response).lower()
    post = _posts().get()
    tree = _tree(response)
    (article,) = _find(tree, "article", id=f"feed-post-{post.pk}")
    assert article.attrs.get("data-post-id") == str(post.pk)
    assert "Писарев Павел" in _find(article, data_feed_author=True)[0].text()
    (to_part,) = _find(article, id=f"feed-post-{post.pk}-to")
    assert "Всем" in to_part.text()
    assert "Моя первая запись" in article.text()
    times = _find(article, "time", data_at=True)
    assert times and sf.moscow_text(timezone.now()) in times[0].text()
    (form,) = _find(tree, "form", id="feed-form")
    assert form.attrs.get("hx-swap-oob") == "true"
    (area,) = _find(form, "textarea", name="text")
    assert area.raw_text().strip() == ""


def test_plain_post_publish_redirects_to_home():
    """FR-608: обычный (не HTMX) POST публикации — переход на главную."""
    writer = sf.as_writer()
    response = _publish(writer, _data("Переход", ["all"]))
    assert response.status_code == 302 and response["Location"] == "/"
    assert _posts().count() == 1


def test_nul_removed_from_text_event_title_and_place(clock):
    """FR-609: символ NUL удаляется из текста, названия и места события (PostgreSQL его не принимает)."""
    writer = sf.as_writer()
    fields = _event_fields(clock, event_title="Соб\x00рание", event_place="Кор\x00пус 1")
    body = _data("При\x00вет", ["all"], term="day", **fields)
    body["kind"] = "event"
    response = _publish(writer, body)
    assert response.status_code == 302
    post = _posts().get()
    assert post.text == "Привет"
    assert post.event_title == "Собрание" and post.event_place == "Корпус 1"
    assert "\x00" not in post.text + post.event_title + post.event_place


def test_recipient_published_at_copies_post_published_at(clock):
    """FR-608: у каждой строки адресата `published_at` — копия времени публикации записи."""
    writer = sf.as_writer()
    unit = org.make_unit("Отдел Копий")
    colleague = _person()
    mentioned = _person()
    first_moment = timezone.now()
    _publish(writer, _data(f"Первая @[{mentioned.pk}]", [f"u{unit.pk}", f"p{colleague.pk}"]))
    clock.advance(hours=5)
    _publish(writer, _data("Вторая", [f"p{colleague.pk}"]))
    Recipient = model("feed.Recipient")
    posts = list(_posts())
    assert len(posts) == 2
    assert posts[0].published_at == first_moment and posts[1].published_at == first_moment + timedelta(hours=5)
    for post in posts:
        rows = list(Recipient.objects.filter(post=post))
        assert rows
        assert {row.published_at for row in rows} == {post.published_at}
    assert Recipient.objects.filter(post=posts[0]).count() == 3
