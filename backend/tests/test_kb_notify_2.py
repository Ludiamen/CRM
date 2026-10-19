"""T-5122: уведомления базы знаний — тексты, обрезка, ссылка, подписка на рубрику, `still_relevant`
(FR-434, FR-435, FR-436, FR-437). Сценарии 5 и 6 спеки среза 005.

Тексты `Draft.text` и `external_text` трёх видов (раздел 7.2 контракта, дословно), обрезка заголовка, названия рубрики и
имени до 100 знаков, предел 300, `object_ref` и ссылка, внешние каналы без заголовка статьи, подписка на рубрику
(кнопка, только на себя, увольнение, удаление рубрики). Код среза на уровне модуля не импортируется: имена берутся
внутри тестов (шапка CONTRACT-005).
"""
import html as html_lib
import importlib
import inspect
import logging
from datetime import timedelta
from html.parser import HTMLParser
from types import SimpleNamespace

import pytest
from django.utils import timezone

from tests import support
from tests import support_kb as kb
from tests.support import model

pytestmark = pytest.mark.django_db

COMMENT = "knowledge.comment_on_my_article"
CHANGED = "knowledge.my_article_changed"
SUBSCRIPTION = "knowledge.rubric_subscription"
KB_KINDS = (COMMENT, CHANGED, SUBSCRIPTION)
EXTERNAL = {COMMENT: "Новый комментарий к вашей статье", CHANGED: "Вашу статью изменили",
            SUBSCRIPTION: "Новая статья в рубрике по подписке"}
BUTTON = "Открыть уведомления"
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- помощники только этого файла ------------------------------------------------------------------------

def _kind(code: str):
    return importlib.import_module("apps.notify.services.kinds").get(code)


def _articles():
    return importlib.import_module("apps.knowledge.services.articles")


def _cut(text: str) -> str:
    """Правило обрезки контракта 7.2: длиннее 100 знаков — первые 99 и «…»."""
    return text if len(text) <= 100 else text[:99] + "…"


def _chars(length: int, start: int = 0x430) -> str:
    """Строка из `length` русских строчных знаков (повтор алфавита, без пробелов)."""
    return "".join(chr(start + i % 32) for i in range(length))


class _Scene(SimpleNamespace):
    """Автор статьи, тот, кто изменил, подписчик, рубрика, статья и комментарий."""


def _scene(*, title: str = "Настройка VPN", rubric_name: str = "Сети", editor_name: str = "Пётр Петров",
           parent_name: str | None = None) -> _Scene:
    """Опубликованная статья в рубрике; подписчик подписан на рубрику (или на её родителя, если он задан)."""
    parent = kb.make_rubric(parent_name) if parent_name else None
    rubric = kb.make_rubric(rubric_name, parent=parent)
    author = support.make_employee(full_name="Анна Автор")
    kb.grant(author, "knowledge.edit")
    editor = support.make_employee(full_name=editor_name)
    kb.grant(editor, "knowledge.edit")
    fan = support.make_employee(full_name="Семён Подписчик")
    kb.subscribe(fan, parent or rubric)
    article = kb.make_published(title=title, rubric=rubric, author=author)
    comment = kb.make_comment(article, author=editor, text="Комментарий")
    return _Scene(author=author, editor=editor, fan=fan, rubric=rubric, parent=parent, article=article,
                  comment=comment)


def _data(scene, event: str, actor) -> dict:
    """Данные события шины по разделу 7.1 контракта."""
    if event == "knowledge.comment_added":
        return {"article_id": scene.article.pk, "comment_id": scene.comment.pk, "actor_id": actor.pk}
    return {"article_id": scene.article.pk, "actor_id": actor.pk, "rubric_id": scene.rubric.pk}


def _drafts(scene, code: str, event: str | None = None) -> list:
    """Черновики вида на событие: комментарий — от редактора; изменение и подписка — от редактора."""
    event = event or _kind(code).events[0]
    return _kind(code).build(event, _data(scene, event, scene.editor))


def _draft(scene, code: str, event: str | None = None):
    drafts = _drafts(scene, code, event)
    assert len(drafts) == 1, (code, event, drafts)
    return drafts[0]


def _recipient(scene, code: str):
    return {COMMENT: scene.author, CHANGED: scene.author, SUBSCRIPTION: scene.fan}[code]


def _notification(user, code: str, draft):
    """Запись `Notification` с текстом, ссылкой и `object_ref` черновика (без доставок)."""
    return model("notify.Notification").objects.create(
        user=user, kind=code, text=draft.text, url=draft.url, object_ref=draft.object_ref)


def _delivery(note, channel: str):
    now = timezone.now()
    return model("notify.Delivery").objects.create(
        notification=note, channel=channel, state="waiting", due_at=now - timedelta(seconds=5), enqueued_at=now)


class _Dom(HTMLParser):
    """Плоский разбор разметки: узел — тег, атрибуты, текст внутри."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes: list = []
        self._stack: list = []

    def _open(self, tag, attrs):
        node = SimpleNamespace(tag=tag, attrs={k: (v if v is not None else "") for k, v in attrs}, parts=[])
        self.nodes.append(node)
        return node

    def handle_starttag(self, tag, attrs):
        node = self._open(tag, attrs)
        if tag not in VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self._open(tag, attrs)

    def handle_endtag(self, tag):
        if any(n.tag == tag for n in self._stack):
            while self._stack:
                if self._stack.pop().tag == tag:
                    break

    def handle_data(self, data):
        for node in self._stack:
            node.parts.append(data)


def _subscribe_buttons(response) -> list:
    parser = _Dom()
    parser.feed(response.content.decode())
    parser.close()
    return [n for n in parser.nodes if n.tag == "button" and n.attrs.get("data-action") == "kb-subscribe"]


def _state(response) -> tuple:
    """(`data-subscribed`, подпись кнопки) — кнопка на странице или во фрагменте ровно одна."""
    buttons = _subscribe_buttons(response)
    assert len(buttons) == 1, f"кнопок kb-subscribe: {len(buttons)}"
    return buttons[0].attrs.get("data-subscribed"), "".join(buttons[0].parts).strip()


def _subs(user=None, rubric=None):
    rows = model("knowledge.RubricSubscription").objects.all()
    if user is not None:
        rows = rows.filter(user=user)
    if rubric is not None:
        rows = rows.filter(rubric=rubric)
    return rows


# --- still_relevant (FR-435) ------------------------------------------------------------------------------

def test_still_relevant_true_for_existing_published_article_and_active_recipient():
    """FR-435: статья существует, опубликована, получатель не уволен — `still_relevant` истинно у всех трёх видов,
    даже если у получателя нет права редактирования (право автора не проверяется)."""
    author = support.make_employee()
    article = kb.make_published(author=author)
    ref = f"knowledge.article:{article.pk}"
    reader = support.make_employee()
    blocked = support.make_employee(state="blocked")  # контракт, раздел 17, п. 27: заблокированный получатель — истина

    for code in KB_KINDS:
        assert _kind(code).still_relevant(author.pk, ref) is True, code
        assert _kind(code).still_relevant(reader.pk, ref) is True, code
        assert _kind(code).still_relevant(blocked.pk, ref) is True, code


def test_still_relevant_false_when_article_deleted_unpublished_or_recipient_dismissed():
    """FR-435: ложь, если статьи нет, она не опубликована (черновик, корзина), получатель уволен или `object_ref` не вида
    `knowledge.article:<id>`; один и тот же получатель и опубликованная статья дают истину (проверка отличия)."""
    user = support.make_employee()
    published = kb.make_published(author=user)
    good_ref = f"knowledge.article:{published.pk}"
    draft_ref = f"knowledge.article:{kb.make_draft(author=user).pk}"
    trash_ref = f"knowledge.article:{kb.make_trashed(author=user).pk}"
    gone = kb.make_published(author=user)
    gone_ref = f"knowledge.article:{gone.pk}"
    gone_pk = gone.pk
    gone.delete()
    missing_ref = f"knowledge.article:{gone_pk + 100000}"
    dismissed = support.make_employee(state="dismissed")

    for code in KB_KINDS:
        still = _kind(code).still_relevant
        assert still(user.pk, good_ref) is True, code
        for ref in (draft_ref, trash_ref, gone_ref, missing_ref):
            assert still(user.pk, ref) is False, (code, ref)
        assert still(dismissed.pk, good_ref) is False, code
        for ref in ("", "knowledge.article:", "knowledge.article:abc", "servicedesk.ticket:" + str(published.pk),
                    "article:" + str(published.pk)):
            assert still(user.pk, ref) is False, (code, ref)


# --- тексты на портале и в письме (FR-436) -----------------------------------------------------------------

def _portal_and_mail(note) -> list[str]:
    """Строки письма по доставке `email` (рендерер читает базу); текст портала — `note.text`."""
    from apps.notify.services import mail as notify_mail

    now = timezone.now()
    delivery, _ = model("notify.Delivery").objects.get_or_create(
        notification=note, channel="email",
        defaults={"state": "waiting", "due_at": now - timedelta(seconds=5), "enqueued_at": now})
    message_id = notify_mail.queue_item(delivery)
    message = model("mail.MailMessage").objects.get(pk=message_id)
    return notify_mail.render(message, {"delivery": delivery.pk}).body.rstrip("\n").splitlines()


def _check_portal_and_mail(code: str, draft, expected: str) -> None:
    """Текст черновика, записи уведомления (портал) и тела письма — один и тот же и дословный."""
    from apps.notify.services import dispatch

    assert draft.text == expected
    ids = dispatch.create(code, [draft])
    note = model("notify.Notification").objects.get(pk=ids[0])
    assert note.text == expected
    assert expected in _portal_and_mail(note)


def test_portal_and_mail_texts_for_comment_kind_match_fr436_verbatim():
    """FR-436: «Новый комментарий к вашей статье «{заголовок}»» — текст черновика, записи портала и письма."""
    scene = _scene(title="Настройка VPN")
    draft = _draft(scene, COMMENT)
    assert draft.user_id == scene.author.pk
    _check_portal_and_mail(COMMENT, draft, "Новый комментарий к вашей статье «Настройка VPN»")


def test_portal_and_mail_texts_for_changed_kind_match_fr436_verbatim():
    """FR-436: «Вашу статью «{заголовок}» изменил {Имя Фамилия}» — имя того, кто сохранил (не автора)."""
    scene = _scene(title="Настройка VPN", editor_name="Пётр Петров")
    draft = _draft(scene, CHANGED)
    assert draft.user_id == scene.author.pk
    _check_portal_and_mail(CHANGED, draft, "Вашу статью «Настройка VPN» изменил Пётр Петров")


def test_portal_and_mail_texts_for_rubric_subscription_kind_match_fr436_verbatim():
    """FR-436: «Статья в рубрике «{рубрика}»: {заголовок}» — одинаков для публикации и изменения; рубрика — самой
    статьи, а не подписанного предка (подписка на «Инфраструктура», статья в «Сети»)."""
    scene = _scene(title="Настройка VPN", rubric_name="Сети", parent_name="Инфраструктура")
    expected = "Статья в рубрике «Сети»: Настройка VPN"

    published = _draft(scene, SUBSCRIPTION, "knowledge.article_published")
    assert published.user_id == scene.fan.pk
    _check_portal_and_mail(SUBSCRIPTION, published, expected)

    changed = _draft(scene, SUBSCRIPTION, "knowledge.article_changed")
    assert changed.user_id == scene.fan.pk
    assert changed.text == expected
    assert "Инфраструктура" not in changed.text


# --- внешние каналы (FR-436) --------------------------------------------------------------------------------

def test_external_channels_text_for_all_three_kinds_has_no_article_title():
    """FR-436: `external_text` трёх видов — дословно по разделу 7.2; службы доставки Telegram, MAX и Web Push отдают
    его же, а заголовка статьи, названия рубрики и имени сохранившего в нём нет, хотя в `Notification.text` они есть."""
    from apps.notify.services import delivery as dlv

    title, rubric_name, editor_name = "УникальныйЗаголовокСтатьи", "УникальнаяРубрика", "Виктор Уникальный"
    scene = _scene(title=title, rubric_name=rubric_name, editor_name=editor_name)

    for code in KB_KINDS:
        assert _kind(code).external_text == EXTERNAL[code], code
        draft = _draft(scene, code)
        note = _notification(_recipient(scene, code), code, draft)
        assert title in note.text
        for channel in ("telegram", "max", "webpush"):
            ext = dlv.external_text(_delivery(note, channel))
            assert ext == EXTERNAL[code], (code, channel)
            for marker in (title, rubric_name, "Виктор", "Уникальный", "«", "»"):
                assert marker not in ext, (code, channel, marker)


def test_external_channels_carry_only_event_text_and_link(bots_on, webpush_on):
    """FR-436: сообщение бота — экранированный внешний текст и кнопка на страницу уведомлений; нагрузка Web Push —
    внешний текст и ссылка `/notifications/`; ни заголовка статьи, ни рубрики, ни имени в них нет."""
    from django.conf import settings

    from apps.notify.services import delivery as dlv
    from tests import support_notify as notify_support

    title, rubric_name, editor_name = "УникальныйЗаголовокСтатьи", "УникальнаяРубрика", "Виктор Уникальный"
    scene = _scene(title=title, rubric_name=rubric_name, editor_name=editor_name)
    link = settings.PORTAL_URL.rstrip("/") + "/notifications/"
    assert dlv.BUTTON_LABEL == BUTTON
    pair = notify_support.browser_keys()
    subs: dict = {}

    for code in KB_KINDS:
        user = _recipient(scene, code)
        chats = {channel: model("notify.ChatBinding").objects.get_or_create(
            user=user, channel=channel, defaults={"chat_id": f"c{user.pk}{channel}"})[0].chat_id
            for channel in ("telegram", "max")}
        if user.pk not in subs:
            subs[user.pk] = notify_support.subscribe(user, keys=pair)
        sub = subs[user.pk]
        note = _notification(user, code, _draft(scene, code))
        for channel in ("telegram", "max"):
            row = _delivery(note, channel)
            with notify_support.fake_bot_send(channel) as fake:
                assert dlv.send_delivery(row.pk) == "sent"
            assert fake.calls == [(chats[channel], html_lib.escape(EXTERNAL[code]), (BUTTON, link))], (code, channel)
        row = _delivery(note, "webpush")
        with notify_support.webpush_capture() as capture:
            assert dlv.send_delivery(row.pk) == "sent"
        assert [r.url for r in capture.requests] == [sub.endpoint], code
        payload = capture.decrypt(capture.requests[0], pair)
        assert payload == {"title": EXTERNAL[code], "url": "/notifications/", "tag": f"n-{note.pk}"}, code
        assert title not in str(payload) and rubric_name not in str(payload) and "Виктор" not in str(payload)


# --- обрезка (FR-436) ---------------------------------------------------------------------------------------

def test_title_of_200_chars_is_cut_to_100_with_ellipsis_in_text():
    """FR-436: заголовок из 200 знаков входит в текст всех трёх видов первыми 99 знаками и «…» (итого 100); ровно 100
    знаков — без изменений, 101 — обрезается (граница правила)."""
    for length in (200, 101, 100):
        rubric_name = f"Сети {length}"  # название корневой рубрики уникально (knowledge_rubric_parent_name_ci_uniq)
        expectations = {COMMENT: "Новый комментарий к вашей статье «{}»",
                        CHANGED: "Вашу статью «{}» изменил Пётр Петров",
                        SUBSCRIPTION: f"Статья в рубрике «{rubric_name}»: {{}}"}
        title = _chars(length)
        scene = _scene(title=title, rubric_name=rubric_name, editor_name="Пётр Петров")
        shown = title[:99] + "…" if length > 100 else title
        assert len(shown) == 100
        for code, pattern in expectations.items():
            assert _draft(scene, code).text == pattern.format(shown), (length, code)


def test_rubric_name_of_100_chars_is_cut_to_100_with_ellipsis_in_text():
    """FR-436: название рубрики из 100 знаков (предел службы `rubrics`) — по правилу контракта 7.2 «ровно 100 — без
    изменений»: входит целиком, без «…»; в тексте вида по подписке оно ровно одно и не длиннее 100 знаков. Имя теста
    говорит «обрезается», но название длиннее 100 знаков создать нельзя (`name_too_long`) — вопрос в отчёте."""
    name = _chars(100, 0x410)
    assert len(name) == 100
    scene = _scene(title="Настройка VPN", rubric_name=name)
    text = _draft(scene, SUBSCRIPTION).text
    assert text == f"Статья в рубрике «{name}»: Настройка VPN"
    assert "…" not in text
    assert _cut(name) == name


def test_editor_name_of_255_chars_is_cut_to_100_with_ellipsis_in_text():
    """FR-436: имя сохранившего из 255 знаков входит в текст «Мою статью изменили» первыми 99 знаками и «…»; полного
    имени в тексте нет."""
    name = _chars(255, 0x410)
    assert len(name) == 255
    scene = _scene(title="Настройка VPN", editor_name=name)
    text = _draft(scene, CHANGED).text
    assert text == f"Вашу статью «Настройка VPN» изменил {name[:99]}…"
    assert name not in text and name[:100] not in text


def test_notification_text_never_exceeds_300_chars_for_longest_title_rubric_and_name():
    """FR-436: при заголовке 200, рубрике 100 и имени 255 знаков текст каждого вида не длиннее 300 знаков, и запись
    `Notification` создаётся (`dispatch.create`) без отказа."""
    from apps.notify.services import dispatch

    scene = _scene(title=_chars(200), rubric_name=_chars(100, 0x410), editor_name=_chars(255, 0x410))
    for code in KB_KINDS:
        drafts = _drafts(scene, code)
        assert len(drafts) == 1, code
        assert 0 < len(drafts[0].text) <= 300, (code, len(drafts[0].text))
        ids = dispatch.create(code, drafts)
        assert len(ids) == 1, code
        note = model("notify.Notification").objects.get(pk=ids[0])
        assert note.text == drafts[0].text and len(note.text) <= 300


# --- object_ref и ссылка (FR-434) --------------------------------------------------------------------------

def test_notification_object_ref_and_link_point_to_article_and_comment_anchor():
    """FR-434: `object_ref = knowledge.article:<id>` у всех трёх видов; ссылка `/kb/<id>/`, у нового комментария —
    `/kb/<id>/#comments`; то же попадает в запись `Notification`."""
    from apps.notify.services import dispatch

    scene = _scene()
    pk = scene.article.pk
    expected = {COMMENT: f"/kb/{pk}/#comments", CHANGED: f"/kb/{pk}/", SUBSCRIPTION: f"/kb/{pk}/"}
    for code in KB_KINDS:
        draft = _draft(scene, code)
        assert draft.object_ref == f"knowledge.article:{pk}", code
        assert draft.url == expected[code], code
        ids = dispatch.create(code, [draft])
        note = model("notify.Notification").objects.get(pk=ids[0])
        assert (note.object_ref, note.url) == (f"knowledge.article:{pk}", expected[code]), code
    published = _draft(scene, SUBSCRIPTION, "knowledge.article_published")
    assert (published.object_ref, published.url) == (f"knowledge.article:{pk}", f"/kb/{pk}/")


# --- подписка на рубрику (FR-437) ---------------------------------------------------------------------------

def test_subscribe_button_switches_to_unsubscribe_and_back():
    """FR-437: на странице рубрики кнопка «Подписаться» (`data-subscribed="false"`); после POST — «Отписаться»
    (`true`) и строка подписки; повторный POST снимает её и возвращает «Подписаться». Право не нужно."""
    reader = kb.as_reader()
    rubric = kb.make_rubric("Сети")
    page_path, action = f"/kb/rubrics/{rubric.pk}/", f"/kb/rubrics/{rubric.pk}/subscribe/"

    assert _state(reader.client.get(page_path)) == ("false", "Подписаться")
    assert not _subs(reader.user, rubric).exists()

    first = reader.client.post(action, headers={"HX-Request": "true"})
    assert first.status_code == 200
    assert _state(first) == ("true", "Отписаться")
    assert _subs(reader.user, rubric).count() == 1
    assert _state(reader.client.get(page_path)) == ("true", "Отписаться")

    second = reader.client.post(action, headers={"HX-Request": "true"})
    assert _state(second) == ("false", "Подписаться")
    assert not _subs(reader.user, rubric).exists()
    assert _state(reader.client.get(page_path)) == ("false", "Подписаться")


def test_subscription_is_created_and_removed_only_for_the_employee_himself():
    """FR-437: `subscriptions.toggle(user, rubric_id)` создаёт и снимает подписку только у самого сотрудника и
    возвращает `True`/`False`; чужого пользователя функция не принимает; поле `user` в POST ничего не меняет."""
    subscriptions = importlib.import_module("apps.knowledge.services.subscriptions")
    rubric = kb.make_rubric("Сети")
    me, other = support.make_employee(), support.make_employee()
    kb.subscribe(other, rubric)

    assert list(inspect.signature(subscriptions.toggle).parameters) == ["user", "rubric_id"]
    assert subscriptions.toggle(me, rubric.pk) is True
    assert _subs(me, rubric).count() == 1 and _subs(other, rubric).count() == 1
    assert subscriptions.toggle(me, rubric.pk) is False
    assert not _subs(me, rubric).exists()
    assert _subs(other, rubric).count() == 1

    session = kb.as_reader()
    response = session.client.post(f"/kb/rubrics/{rubric.pk}/subscribe/", {"user": other.pk, "user_id": other.pk})
    assert response.status_code == 302
    assert _subs(session.user, rubric).count() == 1
    assert _subs(other, rubric).count() == 1
    assert _subs(rubric=rubric).count() == 2


def test_other_employee_cannot_see_or_change_someones_subscription():
    """FR-437: подписку владельца видит и меняет только он: у постороннего на странице рубрики «Подписаться», его
    нажатие создаёт его собственную подписку и не трогает чужую; имени владельца на странице нет."""
    rubric = kb.make_rubric("Сети")
    owner = kb.as_reader(full_name="Хозяин Подписки")
    stranger = kb.as_reader(full_name="Посторонний Человек")
    kb.subscribe(owner.user, rubric)
    page_path, action = f"/kb/rubrics/{rubric.pk}/", f"/kb/rubrics/{rubric.pk}/subscribe/"

    assert _state(owner.client.get(page_path)) == ("true", "Отписаться")
    page = stranger.client.get(page_path)
    assert _state(page) == ("false", "Подписаться")
    assert "Хозяин" not in page.content.decode()

    stranger.client.post(action)
    assert _subs(owner.user, rubric).count() == 1
    assert _subs(stranger.user, rubric).count() == 1
    stranger.client.post(action)
    assert _subs(owner.user, rubric).count() == 1
    assert not _subs(stranger.user, rubric).exists()
    assert _state(owner.client.get(page_path)) == ("true", "Отписаться")


def test_dismissal_event_deletes_dismissed_employee_subscriptions(caplog, django_capture_on_commit_callbacks):
    """FR-437: событие ядра `core.user_dismissed` (настоящее `accounts.dismiss`) удаляет подписки уволенного, подписки
    других остаются; в журнале шины нет ошибок подписчиков; прямой вызов `on_user_dismissed(user_id=…)` — тоже."""
    from apps.core.services import accounts

    subscriptions = importlib.import_module("apps.knowledge.services.subscriptions")
    first, second = kb.make_rubric("Сети"), kb.make_rubric("Почта")
    leaving, staying, direct = (support.make_employee() for _ in range(3))
    for rubric in (first, second):
        kb.subscribe(leaving, rubric)
        kb.subscribe(staying, rubric)
    kb.subscribe(direct, first)

    with caplog.at_level(logging.INFO):
        with django_capture_on_commit_callbacks(execute=True):
            accounts.dismiss(leaving, actor=support.make_admin())
    assert not _subs(leaving).exists()
    assert _subs(staying).count() == 2 and _subs(direct).count() == 1
    bad = [r for r in caplog.records if r.name == "apps.core.events" and r.levelno >= logging.ERROR]
    assert not bad, [r.getMessage() for r in bad]

    subscriptions.on_user_dismissed(user_id=direct.pk, actor_id=None)
    assert not _subs(direct).exists()
    assert _subs(staying).count() == 2


def test_rubric_deletion_cascades_subscriptions():
    """FR-437: удаление пустой рубрики (`rubrics.delete`) убирает её подписки каскадом; подписки на другие рубрики
    остаются."""
    rubrics = importlib.import_module("apps.knowledge.services.rubrics")
    doomed, kept = kb.make_rubric("Удаляемая"), kb.make_rubric("Остающаяся")
    fans = [support.make_employee() for _ in range(2)]
    for fan in fans:
        kb.subscribe(fan, doomed)
        kb.subscribe(fan, kept)
    assert _subs(rubric=doomed).count() == 2

    rubrics.delete(kb.as_manager().user, doomed.pk)

    assert not model("knowledge.Rubric").objects.filter(pk=doomed.pk).exists()
    assert not _subs(rubric=doomed).exists()
    assert _subs(rubric=kept).count() == 2
