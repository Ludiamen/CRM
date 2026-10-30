"""T-7123: кадры живых обновлений — классы рендера, безопасность, слой `publish`, число «Ленты» (FR-626, FR-627, FR-628,
NFR-605, NFR-614).

План: «Живые обновления» (шаги 2–3, формат кадров, CSP, без WebSocket), «Главная, меню и число у «Ленты»» (живое число),
«Непрочитанное» (обновление числа), «Контракты» («Сообщения слоя каналов»); CONTRACT-007: 5.5, 5.8, 11.1, 11.3, 12.3,
решения 7, 20, 49 задач. Сообщения слоя читает `layer_spy(passthrough=False)`; действия — обычные запросы по путям плана,
рассылка — внутри `django_capture_on_commit_callbacks(execute=True)`. Разбор разметки вариантов — свой, на `html.parser`.
Код среза на уровне модуля не импортируется.
"""
import json
import logging
import re
import time
from datetime import timedelta
from html.parser import HTMLParser

import pytest
from django.utils import timezone

from tests import factories, support
from tests import support_feed as ff
from tests.support import HX
from tests.support_notify import ws_fragments

pytestmark = pytest.mark.django_db

VARIANT_CLASS = re.compile(r"^(reader|author|moderator):[01]$")
PROBE_TEXT = ("<script>alert(1)</script> <b>жирный</b> <a href=\"javascript:alert(2)\">клик</a> "
              "<img src=x onerror=alert(3)> javascript:alert(4)")


# --- разбор разметки вариантов (помощник только этого файла) ---------------------------------------------------------

class _Dom(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes: list[tuple[str, dict]] = []
        self._text: list[str] = []

    def handle_starttag(self, tag, attrs):
        self.nodes.append((tag, {name: ("" if value is None else value) for name, value in attrs}))

    handle_startendtag = handle_starttag

    def handle_data(self, data):
        self._text.append(data)

    @property
    def text(self) -> str:
        return " ".join("".join(self._text).split())


def _dom(html: str) -> _Dom:
    parser = _Dom()
    parser.feed(html)
    parser.close()
    return parser


def _find(html: str, tag: str | None = None, **attrs) -> list[dict]:
    """Атрибуты элементов разметки, у которых есть все заданные атрибуты (`_` в имени — это `-`; `True` — любой)."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node_tag, node_attrs in _dom(html).nodes:
        if tag is not None and node_tag != tag:
            continue
        if all(name in node_attrs and (value is True or node_attrs[name] == value) for name, value in wanted.items()):
            found.append(node_attrs)
    return found


def _text(html: str) -> str:
    return _dom(html).text


# --- сборка мира -----------------------------------------------------------------------------------------------------

def _staff_session(name: str = "Кадровик Узлов") -> ff.Session:
    """Сотрудник с правом `staff.view` (ФИО у него — ссылка на карточку сотрудника)."""
    user = support.make_with_permissions("staff.view", full_name=name)
    return ff.Session(user, support.logged_in(user))


def _session(user) -> ff.Session:
    return ff.Session(user, support.logged_in(user))


def _publish(session, *recipients, text: str = "Текст новой записи", kind: str = "post", **extra):
    data = {"kind": kind, "text": text, "to": [f"p{person.pk}" for person in recipients], **extra}
    return session.client.post("/feed/posts/", data, **HX)


def _comment(session, post, text: str = "Новый комментарий"):
    return session.client.post(f"/feed/{post.pk}/comments/", {"text": text}, **HX)


def _like(session, post):
    return session.client.post(f"/feed/{post.pk}/like/", **HX)


def _edit(session, post, recipients, text: str = "Правленый текст"):
    return session.client.post(f"/feed/{post.pk}/edit/",
                               {"text": text, "to": [f"p{person.pk}" for person in recipients]}, **HX)


def _comment_row(post):
    return support.model("core.Comment").objects.filter(object_ref=f"feed.post:{post.pk}").order_by("-pk").first()


def _add_recipient(post, user) -> None:
    support.model("feed.Recipient").objects.create(post=post, kind="user", user=user, via="to",
                                                   published_at=post.published_at)


def _run(capture, action):
    """Действие, затем рассылка после фиксации; слой `publish` — шпион без отправки. Возвращает шпиона."""
    with ff.layer_spy(passthrough=False) as spy:
        with capture(execute=True):
            response = action()
    assert response.status_code == 200, f"действие закончилось кодом {response.status_code}"
    return spy


def _events(spy) -> list[dict]:
    """Различные сообщения `feed.event` (одно и то же сообщение уходит во все группы)."""
    seen, result = set(), []
    for _, message in spy.calls:
        if isinstance(message, dict) and message.get("type") == "feed.event":
            fingerprint = json.dumps(message, sort_keys=True, default=str)
            if fingerprint not in seen:
                seen.add(fingerprint)
                result.append(message)
    return result


def _event(spy, action: str | None = None) -> dict:
    found = [m for m in _events(spy) if action is None or m["action"] == action]
    assert len(found) == 1, f"ожидалось одно сообщение feed.event ({action}), получено {len(found)}"
    return found[0]


def _badge_messages(spy, user) -> list[str]:
    """Фрагменты числа «Ленты» (`notify.html`), ушедшие в группу колокольчика сотрудника."""
    return [m["html"] for m in spy.by_group.get(f"notify.u.{user.pk}", []) if m.get("type") == "notify.html"]


def _badge(spy, user):
    htmls = _badge_messages(spy, user)
    assert htmls, f"сотруднику {user.pk} число «Ленты» не отправлено"
    fragment = ws_fragments(htmls[-1]).get("menu-badge-feed")
    assert fragment is not None, "в сообщении `notify.html` нет `#menu-badge-feed`"
    return fragment


class Stage:
    """Автор, читатель, модератор, сотрудник с `staff.view`; обычная запись, важная и событие — всё адресовано четверым."""

    def __init__(self, *, probe: bool = False):
        self.author = ff.as_writer(full_name="Автор Авторов")
        self.reader = ff.as_plain(full_name="<b>Злой</b> Читатель" if probe else "Читатель Читателев")
        self.moderator = ff.as_moderator(full_name="Модератор Модераторов")
        self.staff = _staff_session()
        self.people = [self.reader.user, self.moderator.user, self.staff.user]
        self.plain = ff.make_post(self.author.user, to=self.people,
                                  text=PROBE_TEXT if probe else "Обычная запись")
        self.important = ff.make_important(self.author.user, to=self.people, text="Важное объявление")
        self.event = ff.make_event(self.author.user, start=timezone.now() + timedelta(days=3), to=self.people,
                                   title="<i>Собрание</i>" if probe else "Собрание", place="Зал 1")

    def battery(self, capture) -> dict[str, dict]:
        """Все действия с кадрами; результат — «действие → сообщение слоя» (удаления в набор не входят)."""
        reader, author = self.reader, self.author
        result = {}
        spy = _run(capture, lambda: _comment(reader, self.plain, PROBE_TEXT))
        result["comment"] = _event(spy, "comment")
        row = _comment_row(self.plain)
        self.comment_id = row.pk
        spy = _run(capture, lambda: reader.client.post(
            f"/feed/comments/{row.pk}/edit/", {"text": "Исправленный " + PROBE_TEXT}, **HX))
        result["comment_edit"] = _event(spy, "comment_edit")
        spy = _run(capture, lambda: _edit(author, self.plain, self.people, PROBE_TEXT))
        result["post"] = _event(spy, "post")
        spy = _run(capture, lambda: _like(reader, self.plain))
        result["like"] = _event(spy, "like")
        spy = _run(capture, lambda: reader.client.post(f"/feed/comments/{row.pk}/like/", **HX))
        result["comment_like"] = _event(spy, "comment_like")
        spy = _run(capture, lambda: reader.client.post(f"/feed/{self.important.pk}/read/", **HX))
        result["read"] = _event(spy, "read")
        spy = _run(capture, lambda: reader.client.post(
            f"/feed/{self.event.pk}/answer/", {"answer": "go"}, **HX))
        result["answer"] = _event(spy, "answer")
        return result


# --- сообщение слоя ------------------------------------------------------------------------------------------------

def test_layer_message_is_feed_event_with_post_action_owner_moderators_staff_viewers_variants(
        django_capture_on_commit_callbacks):
    """FR-627: сообщение слоя — `feed.event` с номером записи, `action`, `owner` (автор объекта), списками `moderators`
    и `staff_viewers` и словарём `variants` «класс → фрагмент»; у комментария — свой автор и номер."""
    stage = Stage()
    spy = _run(django_capture_on_commit_callbacks, lambda: _comment(stage.reader, stage.plain))
    message = _event(spy)
    assert message["type"] == "feed.event"
    assert message["post"] == stage.plain.pk and message["action"] == "comment"
    assert message["owner"] == stage.reader.user.pk, "владелец — автор комментария"
    assert message["comment"] == _comment_row(stage.plain).pk
    assert isinstance(message["moderators"], list) and all(isinstance(i, int) for i in message["moderators"])
    assert isinstance(message["staff_viewers"], list) and all(isinstance(i, int) for i in message["staff_viewers"])
    assert isinstance(message["variants"], dict) and message["variants"]
    assert all(isinstance(variant, str) and isinstance(html, str) and html.strip() for variant, html in message["variants"].items())
    assert set(message) == {"type", "post", "action", "owner", "comment", "moderators", "staff_viewers", "variants"}, \
        "в сообщении не `new` ключа `meta` нет"


def test_meta_only_in_new_message_and_variants_empty_only_in_new_message(django_capture_on_commit_callbacks):
    """FR-627: `meta` (вид, автор, упомянутые, время публикации) есть только у `new`, и только у него пустой `variants`;
    у остальных действий — `meta` нет и фрагменты есть."""
    stage = Stage()
    mentioned = stage.reader.user
    spy = _run(django_capture_on_commit_callbacks, lambda: _publish(
        stage.author, stage.reader.user, text=f"Новая запись для @[{mentioned.pk}]"))
    created = _event(spy, "new")
    post = support.model("feed.Post").objects.exclude(pk__in=[stage.plain.pk, stage.important.pk, stage.event.pk]).get()
    assert created["variants"] == {}, "у `new` фрагментов нет: сами записи не вставляются"
    assert set(created["meta"]) == {"kind", "author", "mentioned", "published_at"}
    assert created["meta"]["kind"] == "post" and created["meta"]["author"] == stage.author.user.pk
    assert created["meta"]["mentioned"] == [mentioned.pk]
    assert created["post"] == post.pk and created["comment"] is None
    from datetime import datetime
    assert datetime.fromisoformat(created["meta"]["published_at"]) == post.published_at
    for action, message in Stage().battery(django_capture_on_commit_callbacks).items():
        assert "meta" not in message, f"{action}: `meta` только у `new`"
        assert message["variants"], f"{action}: пустой `variants` только у `new`"


def test_comment_action_messages_carry_comment_id(django_capture_on_commit_callbacks):
    """FR-627: у `comment`, `comment_edit`, `comment_delete`, `comment_like` в сообщении номер комментария; у прочих
    действий `comment` — `None`."""
    capture = django_capture_on_commit_callbacks
    stage = Stage()
    messages = stage.battery(capture)
    for action in ("comment", "comment_edit", "comment_like"):
        assert messages[action]["comment"] == stage.comment_id, action
    for action in ("post", "like", "read", "answer"):
        assert messages[action]["comment"] is None, action
    spy = _run(capture, lambda: stage.reader.client.post(f"/feed/comments/{stage.comment_id}/delete/", **HX))
    assert _event(spy, "comment_delete")["comment"] == stage.comment_id
    spy = _run(capture, lambda: stage.author.client.post(f"/feed/{stage.plain.pk}/delete/", **HX))
    assert _event(spy, "delete")["comment"] is None


# --- классы получателей --------------------------------------------------------------------------------------------

def test_variant_keys_are_role_and_link_staff_pairs_at_most_six(django_capture_on_commit_callbacks):
    """FR-627: ключ варианта — `<роль>:<0|1>`, роль — `reader`, `author`, `moderator`, признак — ссылка на карточки
    сотрудников; ключей не больше шести."""
    stage = Stage()
    for action, message in stage.battery(django_capture_on_commit_callbacks).items():
        classes = set(message["variants"])
        assert classes and len(classes) <= 6, f"{action}: {classes}"
        assert all(VARIANT_CLASS.match(variant) for variant in classes), f"{action}: {classes}"
    spy = _run(django_capture_on_commit_callbacks, lambda: _comment(stage.reader, stage.plain))
    assert set(_event(spy)["variants"]) == {"author:0", "reader:0", "moderator:0", "reader:1"}


def test_variants_hold_only_classes_present_among_recipients(django_capture_on_commit_callbacks):
    """FR-627: в `variants` только классы, которые есть среди получателей: сначала автор комментария и читатель, потом
    добавлен модератор, потом сотрудник с `staff.view`."""
    capture = django_capture_on_commit_callbacks
    author, commenter = ff.as_writer(full_name="Автор Авторов"), ff.as_plain(full_name="Комментатор Ку")
    moderator, staff = ff.as_moderator(full_name="Модератор Модераторов"), _staff_session()
    post = ff.make_post(author.user, to=[commenter.user])
    spy = _run(capture, lambda: _comment(commenter, post))
    assert set(_event(spy, "comment")["variants"]) == {"author:0", "reader:0"}
    _add_recipient(post, moderator.user)
    spy = _run(capture, lambda: _comment(commenter, post))
    assert set(_event(spy, "comment")["variants"]) == {"author:0", "reader:0", "moderator:0"}
    _add_recipient(post, staff.user)
    spy = _run(capture, lambda: _comment(commenter, post))
    assert set(_event(spy, "comment")["variants"]) == {"author:0", "reader:0", "moderator:0", "reader:1"}


def test_variants_have_no_personal_like_read_or_going_state(django_capture_on_commit_callbacks):
    """FR-627: личное состояние («Нравится» ✓, «Прочитано», «Пойду») во фрагмент не входит: отметка читателя не
    превращается в `aria-pressed="true"`, кнопки «Прочитано» в кадре нет; общие числа на месте."""
    capture = django_capture_on_commit_callbacks
    stage = Stage()
    ff.like(stage.plain, stage.reader.user)
    support.model("feed.ReadMark").objects.create(post=stage.important, user=stage.reader.user,
                                                  read_at=timezone.now())
    support.model("feed.EventAnswer").objects.create(post=stage.event, user=stage.reader.user, answer="go",
                                                     answered_at=timezone.now())
    messages = {
        "post": _event(_run(capture, lambda: _edit(stage.author, stage.plain, stage.people)), "post"),
        "read": _event(_run(capture, lambda: stage.moderator.client.post(
            f"/feed/{stage.important.pk}/read/", **HX)), "read"),
        "answer": _event(_run(capture, lambda: stage.moderator.client.post(
            f"/feed/{stage.event.pk}/answer/", {"answer": "no"}, **HX)), "answer"),
    }
    for action, message in messages.items():
        for variant, html in message["variants"].items():
            assert 'aria-pressed="true"' not in html, f"{action}/{variant}: личное состояние «Нравится» в кадре"
            assert not _find(html, "button", data_action="read"), f"{action}/{variant}: личная кнопка «Прочитано» в кадре"
    event_html = messages["answer"]["variants"]["reader:0"]
    assert _find(event_html, data_feed_answers_count="go") and _find(event_html, data_feed_answers_count="no")
    assert _text(messages["post"]["variants"]["reader:0"]), "общая часть записи на месте"


def test_moderators_are_feed_moderate_holders_among_recipients_by_personal_and_unit_roles(
        django_capture_on_commit_callbacks):
    """FR-628: `moderators` — получатели с правом «Модерировать ленту» по личным ролям и по ролям узлов; держатель
    права, которому запись не адресована, и обычный читатель не входят."""
    from tests import support_org as org

    capture = django_capture_on_commit_callbacks
    Permission = support.model("core.Permission")
    Permission.objects.get_or_create(code="feed.moderate", defaults={"title": ff.TITLES_007["feed.moderate"]})
    moderator_role = factories.make_role(permissions=("feed.moderate",))
    unit = org.make_unit("Отдел модерации")
    unit_moderator = support.make_employee(full_name="Узловой Модератор")
    org.make_member(unit_moderator, unit)
    org.make_unit_role(unit, moderator_role)
    personal = support.make_employee(roles=[moderator_role], full_name="Личный Модератор")
    outsider = support.make_employee(roles=[moderator_role], full_name="Не Адресат")
    reader, author = ff.as_plain(full_name="Читатель Читателев"), ff.as_writer(full_name="Автор Авторов")
    post = ff.make_post(author.user, to=[unit, personal, reader.user])
    spy = _run(capture, lambda: _comment(reader, post))
    message = _event(spy, "comment")
    assert set(message["moderators"]) == {unit_moderator.pk, personal.pk}
    assert outsider.pk not in message["moderators"]
    assert reader.user.pk not in message["moderators"] and author.user.pk not in message["moderators"]


def test_revoked_moderator_right_makes_next_frame_reader_variant(django_capture_on_commit_callbacks):
    """FR-628: право модератора снято ролями ядра — следующая рассылка уже не числит его модератором и не даёт ему
    варианта `moderator`."""
    from django.core.cache import cache

    from apps.core.services import permissions, roles

    capture = django_capture_on_commit_callbacks
    author, reader, moderator = ff.as_writer(full_name="Автор Авторов"), ff.as_plain(full_name="Читатель Читателев"), \
        ff.as_moderator(full_name="Модератор Модераторов")
    post = ff.make_post(author.user, to=[reader.user, moderator.user])
    spy = _run(capture, lambda: _comment(reader, post, "Первый"))
    first = _event(spy, "comment")
    assert first["moderators"] == [moderator.user.pk] and "moderator:0" in first["variants"]

    role = moderator.user.roles.get()
    roles.update_role(role, role.name, [], actor=support.make_admin())
    cache.delete(permissions._key(moderator.user.pk))
    spy = _run(capture, lambda: _comment(reader, post, "Второй"))
    second = _event(spy, "comment")
    assert second["moderators"] == []
    assert not [variant for variant in second["variants"] if variant.startswith("moderator:")], "у бывшего модератора вариант `moderator`"


def test_staff_viewers_are_recipients_with_staff_view_or_accounts_manage_at_broadcast(
        django_capture_on_commit_callbacks):
    """FR-627, FR-628: `staff_viewers` — получатели с `staff.view` или `accounts.manage` на момент рассылки; не
    получатель с таким правом не входит; после снятия права следующая рассылка его не числит."""
    from django.core.cache import cache

    from apps.core.services import permissions

    capture = django_capture_on_commit_callbacks
    viewer = support.make_with_permissions("staff.view", full_name="Смотрящий Один")
    manager = support.make_with_permissions("accounts.manage", full_name="Смотрящий Два")
    outsider = support.make_with_permissions("staff.view", full_name="Не Адресат")
    author, reader = ff.as_writer(full_name="Автор Авторов"), ff.as_plain(full_name="Читатель Читателев")
    post = ff.make_post(author.user, to=[viewer, manager, reader.user])
    spy = _run(capture, lambda: _comment(reader, post, "Первый"))
    first = _event(spy, "comment")
    assert set(first["staff_viewers"]) == {viewer.pk, manager.pk}
    assert outsider.pk not in first["staff_viewers"]
    assert "reader:1" in first["variants"] and "reader:0" in first["variants"]

    viewer.roles.clear()
    cache.delete(permissions._key(viewer.pk))
    spy = _run(capture, lambda: _comment(reader, post, "Второй"))
    assert set(_event(spy, "comment")["staff_viewers"]) == {manager.pk}


# --- содержимое вариантов ------------------------------------------------------------------------------------------

def test_reader_variant_has_no_edit_delete_menu_and_no_lists(django_capture_on_commit_callbacks):
    """FR-627, FR-628: у варианта читателя нет меню «Править» и «Удалить» комментария, нет ссылок на списки прочитавших
    и ответивших."""
    capture = django_capture_on_commit_callbacks
    stage = Stage()
    messages = stage.battery(capture)
    reader_comment = messages["comment_edit"]["variants"]["reader:0"]
    assert _find(reader_comment, id=f"c{stage.comment_id}"), "вариант — сам комментарий"
    assert not _find(reader_comment, "button", data_action="comment-edit")
    assert not _find(reader_comment, "button", data_action="comment-delete")
    reader_read = messages["read"]["variants"]["reader:0"]
    assert not _find(reader_read, "a", href=f"/feed/{stage.important.pk}/reads/"), "список прочитавших у читателя"
    assert not re.search(r"Прочитали\s+\d+\s+из", _text(reader_read))
    reader_answer = messages["answer"]["variants"]["reader:0"]
    assert not _find(reader_answer, "a", data_feed_answers_link=True), "список ответивших у читателя"


def test_author_variant_has_edit_delete_menu_and_reads_count_moderator_variant_has_delete(
        django_capture_on_commit_callbacks):
    """FR-627: автор комментария видит «Править» и «Удалить», модератор — только «Удалить»; у автора и модератора
    важной записи — «Прочитали N из M» (M — адресаты без автора) со ссылкой на список."""
    capture = django_capture_on_commit_callbacks
    stage = Stage()
    messages = stage.battery(capture)
    variants = messages["comment_edit"]["variants"]
    author_comment = variants["author:0"]
    assert _find(author_comment, "button", data_action="comment-edit")
    assert _find(author_comment, "button", data_action="comment-delete")
    moderator_comment = variants["moderator:0"]
    assert _find(moderator_comment, "button", data_action="comment-delete")
    assert not _find(moderator_comment, "button", data_action="comment-edit"), "модератор чужой комментарий не правит"
    read = messages["read"]
    assert read["owner"] == stage.author.user.pk
    for variant in ("author:0", "moderator:0"):
        html = read["variants"][variant]
        assert re.search(r"Прочитали\s+1\s+из\s+3", _text(html)), f"{variant}: {_text(html)!r}"
        assert _find(html, "a", href=f"/feed/{stage.important.pk}/reads/"), f"{variant}: ссылки на список нет"


def test_link_staff_variant_shows_name_as_staff_link_other_variant_as_plain_text(django_capture_on_commit_callbacks):
    """FR-627: вариант `…:1` показывает ФИО автора ссылкой `/staff/<id>/`, вариант `…:0` — обычным текстом без ссылки."""
    capture = django_capture_on_commit_callbacks
    stage = Stage()
    spy = _run(capture, lambda: _comment(stage.reader, stage.plain, "Комментарий со ссылкой"))
    variants = _event(spy, "comment")["variants"]
    commenter = stage.reader.user
    href = f"/staff/{commenter.pk}/"
    linked = variants["reader:1"]
    assert commenter.full_name in _text(linked)
    assert _find(linked, "a", href=href), "ссылки на карточку сотрудника в варианте `reader:1` нет"
    plain = variants["reader:0"]
    assert commenter.full_name in _text(plain)
    assert not _find(plain, "a", href=href), "ссылка на карточку в варианте без права"
    assert not [a for a in _find(plain, "a") if a.get("href", "").startswith("/staff/")]


# --- безопасность кадров -------------------------------------------------------------------------------------------

def test_frame_has_no_csrfmiddlewaretoken_and_no_forms(django_capture_on_commit_callbacks):
    """FR-627, NFR-605: в кадрах нет `csrfmiddlewaretoken` и форм (токен личный, а один рендер уходит многим)."""
    stage = Stage()
    for action, message in stage.battery(django_capture_on_commit_callbacks).items():
        for variant, html in message["variants"].items():
            assert "csrfmiddlewaretoken" not in html, f"{action}/{variant}"
            assert "<form" not in html.lower(), f"{action}/{variant}"
            assert not _find(html, "form"), f"{action}/{variant}"


def test_frame_action_buttons_are_hx_post_without_form(django_capture_on_commit_callbacks):
    """FR-627: кнопки действий в кадре — `hx-post` без формы (токен добавляет `htmx-glue.js`): «Удалить» комментария,
    «Нравится» записи, «Пойду»/«Не смогу»."""
    stage = Stage()
    messages = stage.battery(django_capture_on_commit_callbacks)
    author_comment = messages["comment_edit"]["variants"]["author:0"]
    delete = _find(author_comment, "button", data_action="comment-delete")
    assert delete and delete[0].get("hx-post") == f"/feed/comments/{stage.comment_id}/delete/"
    likers = messages["like"]["variants"]["reader:0"]
    like = _find(likers, "button", data_feed_like=True)
    assert like and like[0].get("hx-post") == f"/feed/{stage.plain.pk}/like/", "кнопка «Нравится» без `hx-post`"
    for answer in _find(messages["answer"]["variants"]["reader:0"], "button", data_action="answer"):
        assert answer.get("hx-post") == f"/feed/{stage.event.pk}/answer/"
    for message in messages.values():
        for html in message["variants"].values():
            for button in _find(html, "button", hx_post=True):
                assert button["hx-post"].startswith("/feed/"), button
            assert not _find(html, "form")


def test_frame_escapes_script_bold_javascript_link_and_img_onerror_probe(django_capture_on_commit_callbacks):
    """NFR-605: скрипт, жирный, ссылка `javascript:` и `<img onerror>` в тексте записи и комментария, в ФИО автора и в
    названии события приходят в кадре экранированными: исходной разметки в кадре нет, тега `script`, атрибутов `on…`
    и ссылок `javascript:` нет, а исходный текст виден как текст."""
    stage = Stage(probe=True)
    messages = stage.battery(django_capture_on_commit_callbacks)
    raw_probes = ("<script>alert(1)</script>", "<b>жирный</b>", "<img src=x", "<b>Злой</b>", "<i>Собрание</i>",
                  'href="javascript:')
    for action, message in messages.items():
        for variant, html in message["variants"].items():
            for probe in raw_probes:
                assert probe not in html, f"{action}/{variant}: разметка {probe!r} не экранирована"
            for tag, attrs in _dom(html).nodes:
                assert tag != "script", f"{action}/{variant}: тег script"
                assert not [name for name in attrs if name.startswith("on")], f"{action}/{variant}: {attrs}"
                assert not attrs.get("href", "").lower().startswith("javascript:"), f"{action}/{variant}: {attrs}"
                assert attrs.get("src") != "x", f"{action}/{variant}: чужая картинка {attrs}"
    assert "<script>alert(1)</script>" in _text(messages["post"]["variants"]["reader:0"]), "текст записи пропал"
    comment_html = messages["comment_edit"]["variants"]["reader:0"]
    assert "<script>alert(1)</script>" in _text(comment_html), "текст комментария пропал"
    assert "<b>Злой</b>" in _text(comment_html), "ФИО автора должно быть текстом"
    answer_text = _text(messages["answer"]["variants"]["reader:0"])
    assert "<i>Собрание</i>" in answer_text, "название события должно быть текстом"


def test_frame_fragments_have_no_style_or_on_event_attributes(django_capture_on_commit_callbacks):
    """NFR-605: во фрагментах кадров (варианты и число «Ленты») нет `style=` и атрибутов `on…=`, нет `<script`."""
    capture = django_capture_on_commit_callbacks
    stage = Stage()
    messages = stage.battery(capture)
    spy = _run(capture, lambda: _publish(stage.author, stage.reader.user, text="Ещё запись"))
    htmls = [html for message in messages.values() for html in message["variants"].values()]
    htmls += _badge_messages(spy, stage.reader.user)
    assert htmls
    for html in htmls:
        assert "<script" not in html.lower()
        for tag, attrs in _dom(html).nodes:
            assert "style" not in attrs, f"<{tag}> со style"
            assert not [name for name in attrs if name.startswith("on")], f"<{tag}> с {attrs}"
    assert not re.search(r"\sstyle\s*=", "".join(htmls), re.I)
    assert not re.search(r"\son[a-z]+\s*=", "".join(htmls), re.I)


# --- сбой слоя `publish` -------------------------------------------------------------------------------------------

def test_publish_with_layer_down_saves_post_and_answers_faster_than_3_seconds(django_capture_on_commit_callbacks):
    """NFR-614, FR-628: слой `publish` недоступен (каждая отправка падает после 0,2 с, как зависший порт): запись и
    уведомления сохранены, ответ быстрее 3 с — сбой слоя не задерживает действие."""
    author = ff.as_writer(full_name="Автор Авторов")
    people = [ff.as_plain(full_name=f"Получатель Номер{i}") for i in range(6)]
    started = time.monotonic()
    with ff.layer_down(delay=0.2):
        with django_capture_on_commit_callbacks(execute=True):
            response = _publish(author, *[person.user for person in people], text="Запись при сбое слоя")
    elapsed = time.monotonic() - started
    assert response.status_code == 200
    assert support.model("feed.Post").objects.filter(author=author.user, text="Запись при сбое слоя").exists()
    assert elapsed < 3.0, f"публикация при сбое слоя заняла {elapsed:.2f} с"


def test_comment_with_layer_down_is_saved(django_capture_on_commit_callbacks):
    """NFR-614, FR-628: комментарий при недоступном слое сохранён и ответ успешен; в журнале сбой рассылки не роняет
    запрос."""
    author, reader = ff.as_writer(full_name="Автор Авторов"), ff.as_plain(full_name="Читатель Читателев")
    post = ff.make_post(author.user, to=[reader.user])
    with ff.layer_down():
        with django_capture_on_commit_callbacks(execute=True):
            response = _comment(reader, post, "Комментарий при сбое слоя")
    assert response.status_code == 200
    saved = support.model("core.Comment").objects.filter(object_ref=f"feed.post:{post.pk}")
    assert [row.text for row in saved] == ["Комментарий при сбое слоя"]
    assert support.model("feed.FeedComment").objects.filter(post=post).count() == 1


def test_layer_down_writes_warning_to_application_log(django_capture_on_commit_callbacks, caplog):
    """NFR-614: недоступный слой — предупреждение в журнале приложения (`apps.feed.services.live`), без исключения; текст
    записи в журнал не попадает."""
    author, reader = ff.as_writer(full_name="Автор Авторов"), ff.as_plain(full_name="Читатель Читателев")
    post = ff.make_post(author.user, to=[reader.user])
    with caplog.at_level(logging.WARNING):
        with ff.layer_down():
            with django_capture_on_commit_callbacks(execute=True):
                response = _comment(reader, post, "Текст который не должен попасть в журнал")
    assert response.status_code == 200
    warnings = [r for r in caplog.records if r.name == "apps.feed.services.live" and r.levelno == logging.WARNING]
    assert warnings, "в журнале нет предупреждения `apps.feed.services.live`"
    assert not any("не должен попасть" in record.getMessage() for record in caplog.records)


# --- число «Ленты» -------------------------------------------------------------------------------------------------

def test_feed_count_frame_after_publish_is_notify_html_menu_badge_feed_oob_on_notify_socket(
        django_capture_on_commit_callbacks):
    """FR-626, FR-627: после публикации адресату уходит второе сообщение — `notify.html` в группу `notify.u.<id>` с
    готовым фрагментом `#menu-badge-feed` (`hx-swap-oob="true"`, `data-count`, `data-menu-live-badge`, без
    `data-menu-badge`); постороннему — ничего."""
    author, reader, stranger = ff.as_writer(full_name="Автор Авторов"), ff.as_plain(full_name="Адресат Адресатов"), \
        ff.as_plain(full_name="Посторонний Лиц")
    spy = _run(django_capture_on_commit_callbacks, lambda: _publish(author, reader.user))
    badge = _badge(spy, reader.user)
    assert badge.attrs["hx-swap-oob"] == "true"
    assert badge.attrs["data-count"] == "1" and badge.text.strip() == "1"
    assert "data-menu-live-badge" in badge.attrs
    assert "data-menu-badge" not in badge.attrs
    assert "d-none" not in badge.attrs.get("class", "").split()
    assert _badge_messages(spy, stranger.user) == [], "постороннему число отправлено"
    message = [m for m in spy.by_group[f"notify.u.{reader.user.pk}"] if m.get("type") == "notify.html"][0]
    assert set(message) == {"type", "html"}


def test_feed_count_frame_after_deleting_unread_post(django_capture_on_commit_callbacks):
    """FR-626, FR-627: после удаления непрочитанной записи её видевшим уходит новое число: было 2 — стало 1, затем 0
    (узел скрыт классом `d-none`); не видевшему — ничего."""
    capture = django_capture_on_commit_callbacks
    author, reader, stranger = ff.as_writer(full_name="Автор Авторов"), ff.as_plain(full_name="Читатель Читателев"), \
        ff.as_plain(full_name="Посторонний Лиц")
    first = ff.make_post(author.user, to=[reader.user])
    second = ff.make_post(author.user, to=[reader.user])
    spy = _run(capture, lambda: author.client.post(f"/feed/{first.pk}/delete/", **HX))
    assert _badge(spy, reader.user).attrs["data-count"] == "1"
    assert _badge_messages(spy, stranger.user) == []
    spy = _run(capture, lambda: author.client.post(f"/feed/{second.pk}/delete/", **HX))
    zero = _badge(spy, reader.user)
    assert zero.attrs["data-count"] == "0"
    assert "d-none" in zero.attrs.get("class", "").split()


def test_feed_count_frame_after_widening_recipients_by_edit(django_capture_on_commit_callbacks):
    """FR-626, FR-627: правка расширила «Кому» — новому адресату уходит число «Ленты» (1); посторонний его не получает."""
    capture = django_capture_on_commit_callbacks
    author, old, added, stranger = ff.as_writer(full_name="Автор Авторов"), ff.as_plain(full_name="Прежний Адресат"), \
        ff.as_plain(full_name="Добавленный Адресат"), ff.as_plain(full_name="Посторонний Лиц")
    post = ff.make_post(author.user, to=[old.user])
    spy = _run(capture, lambda: _edit(author, post, [old.user, added.user]))
    assert _badge(spy, added.user).attrs["data-count"] == "1"
    assert _badge_messages(spy, stranger.user) == []


def test_feed_count_frame_after_mention_in_comment(django_capture_on_commit_callbacks):
    """FR-626, FR-627: упомянутый в комментарии становится адресатом записи и получает число «Ленты» (1); посторонний —
    нет."""
    capture = django_capture_on_commit_callbacks
    author, addressee = ff.as_writer(full_name="Автор Авторов"), ff.as_plain(full_name="Адресат Адресатов")
    mentioned, stranger = ff.as_plain(full_name="Упомянутый Узлов"), ff.as_plain(full_name="Посторонний Лиц")
    post = ff.make_post(author.user, to=[addressee.user])
    spy = _run(capture, lambda: _comment(addressee, post, f"Смотри, @[{mentioned.user.pk}]"))
    assert _badge(spy, mentioned.user).attrs["data-count"] == "1"
    assert _badge_messages(spy, stranger.user) == []
