"""T-5121: виды уведомлений базы знаний — каталог, available, получатели (FR-433, FR-434, FR-435, FR-437).
Сценарии 5 и 6 спеки среза 005.

Три вида модуля «База знаний» в каталоге `notify` (раздел 7.2 контракта), таблица «Мои уведомления», получатели
`build` при настоящих действиях служб (`articles.add_comment`, `articles.save`, `articles.publish`), склейка
непрочитанных. Код среза на уровне модуля не импортируется: имена берутся внутри тестов (шапка CONTRACT-005).
"""
import importlib
import logging
from html.parser import HTMLParser

import pytest
from django.core.cache import cache
from django.utils import timezone

from tests import support
from tests import support_kb as kb
from tests.support import model

pytestmark = pytest.mark.django_db

COMMENT = "knowledge.comment_on_my_article"
CHANGED = "knowledge.my_article_changed"
SUBSCRIPTION = "knowledge.rubric_subscription"
KB_KINDS = (COMMENT, CHANGED, SUBSCRIPTION)
TITLES = {COMMENT: "Новый комментарий к моей статье", CHANGED: "Мою статью изменили",
          SUBSCRIPTION: "Статья в рубрике по подписке"}
ORDERS = {COMMENT: 50, CHANGED: 51, SUBSCRIPTION: 52}
EVENTS = {COMMENT: ("knowledge.comment_added",), CHANGED: ("knowledge.article_changed",),
          SUBSCRIPTION: ("knowledge.article_published", "knowledge.article_changed")}
KB_EVENTS = ("knowledge.article_published", "knowledge.article_changed", "knowledge.comment_added")
URL = "/me/notifications/"


# --- помощники файла --------------------------------------------------------------------------------------

def _kinds():
    return importlib.import_module("apps.notify.services.kinds")


def _prefs():
    return importlib.import_module("apps.notify.services.prefs")


def _articles():
    return importlib.import_module("apps.knowledge.services.articles")


def _kb_catalog() -> list:
    """Виды базы знаний из каталога `notify` в порядке каталога."""
    return [kind for kind in _kinds().catalog() if kind.code.startswith("knowledge.")]


def _kind(code: str):
    return {kind.code: kind for kind in _kb_catalog()}[code]


def _notes(kind: str | None = None, user=None):
    notes = model("notify.Notification").objects.filter(kind__startswith="knowledge.")
    if kind is not None:
        notes = notes.filter(kind=kind)
    if user is not None:
        notes = notes.filter(user=user)
    return notes


def _got() -> list:
    """Все уведомления базы знаний: пары (номер получателя, вид), по возрастанию."""
    return sorted(_notes().values_list("user_id", "kind"))


def _want(*pairs) -> list:
    """Ожидаемое для `_got`: пары (сотрудник, вид)."""
    return sorted((user.pk, code) for user, code in pairs)


def _no_bus_errors(caplog) -> None:
    """Решение 19 задач: сбоев подписчиков шины в журнале приложения нет."""
    bad = [r for r in caplog.records if r.name == "apps.core.events" and r.levelno >= logging.ERROR]
    assert not bad, [r.getMessage() for r in bad]


def _form(article, **over):
    """`ArticleForm` с текущими значениями статьи; `over` меняет поля."""
    tags = ", ".join(sorted(article.tags.values_list("name", flat=True)))
    values = dict(title=article.title, text=article.text, rubric_id=article.rubric_id, tags=tags, comment="")
    values.update(over)
    return _articles().ArticleForm(**values)


def _fresh(article):
    return type(article).objects.get(pk=article.pk)


def _save(user, article, commit, text: str = "Новый текст правки"):
    """Сохранение статьи пользователем; обработчики шины идут после фиксации."""
    article = _fresh(article)
    with commit(execute=True):
        result = _articles().save(user, article.pk, article.version_no, _form(article, text=text))
    assert result.kind == "saved", result.kind
    return result


def _publish(user, article, commit):
    article = _fresh(article)
    with commit(execute=True):
        _articles().publish(user, article.pk, article.version_no)
    assert _fresh(article).state == "published"


def _comment(user, article, commit, text: str = "Хороший текст"):
    with commit(execute=True):
        return _articles().add_comment(user, article.pk, text)


def _drop_cache(user) -> None:
    from apps.core.services import permissions

    cache.delete(permissions._key(user.pk))


def _read_all() -> None:
    """«Прочитано»: `read_at` не пусто (контракт 4.1)."""
    _notes().update(read_at=timezone.now())


# --- разбор разметки страницы «Мои уведомления» ---------------------------------------------------------------

_VOID = {"meta", "link", "input", "br", "hr", "img", "source", "area", "base", "col", "embed", "param", "track", "wbr"}


class _El:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.raw = tag, attrs, parent, ""

    @property
    def text(self) -> str:
        return " ".join(self.raw.split())


class _Doc(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.elements, self._stack = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        el = _El(tag, {k: (v if v is not None else "") for k, v in attrs}, self._stack[-1] if self._stack else None)
        self.elements.append(el)
        if tag not in _VOID:
            self._stack.append(el)

    def handle_startendtag(self, tag, attrs):
        self.elements.append(_El(tag, {k: (v if v is not None else "") for k, v in attrs},
                                 self._stack[-1] if self._stack else None))

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                break

    def handle_data(self, data):
        for el in self._stack:
            el.raw += data


def _inside(el, ancestor) -> bool:
    node = el.parent
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent
    return False


def _find(doc, tag=None, attrs=None, *, within=None) -> list:
    wanted = attrs or {}
    found = [el for el in doc.elements
             if (tag is None or el.tag == tag) and all(k in el.attrs and (v is True or el.attrs[k] == v)
                                                      for k, v in wanted.items())]
    return [el for el in found if _inside(el, within)] if within is not None else found


def _one(doc, tag=None, attrs=None, *, within=None):
    found = _find(doc, tag, attrs, within=within)
    assert len(found) == 1, f"ожидали один элемент {tag or '*'}{attrs}, нашли {len(found)}"
    return found[0]


# --- каталог (FR-434, FR-433) ----------------------------------------------------------------------------------

def test_catalog_contains_three_knowledge_kinds_with_codes_titles_and_module():
    """FR-434: в каталоге три вида модуля «База знаний» с кодами и названиями раздела 7.2, по порядку 50, 51, 52;
    они стоят после видов сервис-деска и до видов ядра и `notify`."""
    kinds = _kb_catalog()
    assert [kind.code for kind in kinds] == list(KB_KINDS)
    for kind in kinds:
        assert kind.module == "База знаний", kind.code
        assert kind.title == TITLES[kind.code], kind.code
        assert kind.order == ORDERS[kind.code], kind.code
    codes = [kind.code for kind in _kinds().catalog()]
    first, last = codes.index(COMMENT), codes.index(SUBSCRIPTION)
    assert last == first + 2, "три вида каталога идут подряд"
    assert all(code.startswith("servicedesk.") for code in codes[:first]), "до видов базы знаний — сервис-деск"
    assert codes[last + 1:] and all(not code.startswith(("servicedesk.", "knowledge.")) for code in codes[last + 1:])
    assert {kind.code for kind in _kinds().catalog()}.issuperset(
        {"core.new_device", "core.password_changed", "core.second_factor_reset", "notify.channel_unbound"})


def test_knowledge_kinds_events_and_coalesce_flag_match_plan_table():
    """FR-434, FR-435: `events` и `coalesce=True` каждого вида — как в таблице плана; `mandatory` ложно;
    `for_event` отдаёт виды по событию в порядке каталога."""
    for kind in _kb_catalog():
        assert tuple(kind.events) == EVENTS[kind.code], kind.code
        assert kind.coalesce is True, kind.code
        assert kind.mandatory is False, kind.code
    kinds = _kinds()
    assert [k.code for k in kinds.for_event("knowledge.comment_added")] == [COMMENT]
    assert [k.code for k in kinds.for_event("knowledge.article_changed")] == [CHANGED, SUBSCRIPTION]
    assert [k.code for k in kinds.for_event("knowledge.article_published")] == [SUBSCRIPTION]
    assert set(KB_EVENTS) <= set(kinds.event_names())


def test_knowledge_kinds_default_channels_are_portal_and_email():
    """FR-434: начальные каналы всех трёх видов — «На портале» и «Почта»; в таблице у сотрудника включены они,
    а `push`, Telegram и MAX выключены."""
    for kind in _kb_catalog():
        assert tuple(kind.default_channels) == ("portal", "email"), kind.code
    editor = kb.as_editor().user
    rows = {row.kind.code: dict(row.cells) for row in _prefs().effective(editor).rows}
    for code in KB_KINDS:
        assert rows[code] == {"portal": True, "email": True, "push": False, "telegram": False, "max": False}, code
        assert _prefs().channels_for(editor.pk, _kind(code)) == ["email"], code


def test_admin_can_change_knowledge_kinds_default_channels_by_data():
    """FR-434: значения по умолчанию задаёт администратор данными (`NotifySettings.defaults`): новые каналы
    действуют у сотрудника, не сохранявшего таблицу."""
    editor = kb.as_editor().user
    model("notify.NotifySettings").objects.update_or_create(
        pk=1, defaults={"defaults": {COMMENT: ["push"], CHANGED: ["email", "max"], SUBSCRIPTION: []}})
    rows = {row.kind.code: dict(row.cells) for row in _prefs().effective(editor).rows}
    assert rows[COMMENT] == {"portal": True, "email": False, "push": True, "telegram": False, "max": False}
    assert rows[CHANGED] == {"portal": True, "email": True, "push": False, "telegram": False, "max": True}
    assert rows[SUBSCRIPTION] == {"portal": True, "email": False, "push": False, "telegram": False, "max": False}
    assert _prefs().channels_for(editor.pk, _kind(COMMENT)) == ["push"]
    assert _prefs().channels_for(editor.pk, _kind(CHANGED)) == ["email", "max"]
    assert _prefs().channels_for(editor.pk, _kind(SUBSCRIPTION)) == []
    assert _prefs().row_of(editor.pk) is None, "строка личных настроек не создана"


def test_knowledge_kinds_not_registered_when_module_disabled(django_capture_on_commit_callbacks, caplog):
    """FR-433: при выключенном модуле видов `knowledge` в каталоге нет, событий они не ждут, таблица сотрудника без
    их строк, а событие модуля уведомлений не создаёт; после выхода из блока виды на месте."""
    author, commenter = kb.as_editor().user, support.make_employee()
    article = kb.make_published(author=author)
    comment = kb.make_comment(article, commenter)
    kinds = _kinds()
    with kb.without_knowledge():
        assert [kind for kind in kinds.catalog() if kind.code.startswith("knowledge.")] == []
        assert kinds.for_event("knowledge.comment_added") == []
        assert not any(name.startswith("knowledge.") for name in kinds.event_names())
        assert not [row for row in _prefs().effective(author).rows if row.kind.code.startswith("knowledge.")]
        from apps.core import events

        with django_capture_on_commit_callbacks(execute=True):
            events.publish("knowledge.comment_added", article_id=article.pk, comment_id=comment.pk,
                           actor_id=commenter.pk)
        assert _got() == []
        _no_bus_errors(caplog)
    assert [kind.code for kind in _kb_catalog()] == list(KB_KINDS)


# --- available и таблица «Мои уведомления» (FR-434) -------------------------------------------------------------

def test_available_for_comment_and_changed_kinds_with_edit_right():
    """FR-434: с правом `knowledge.edit` виды «Новый комментарий» и «Мою статью изменили» доступны (статей у
    сотрудника нет); строки таблицы — три."""
    user = kb.as_editor().user
    assert not support.model("knowledge.Article").objects.filter(author=user).exists()
    assert _kind(COMMENT).available(user)
    assert _kind(CHANGED).available(user)
    assert _kind(SUBSCRIPTION).available(user)
    shown = [row.kind.code for row in _prefs().effective(user).rows if row.kind.code.startswith("knowledge.")]
    assert shown == list(KB_KINDS)


def test_available_for_comment_and_changed_kinds_with_manage_right():
    """FR-434: управление включает всё, что даёт редактирование: с правом `knowledge.manage` (без `edit`) виды
    «Новый комментарий» и «Мою статью изменили» доступны."""
    user = kb.as_manager().user
    assert not support.model("knowledge.Article").objects.filter(author=user).exists()
    assert _kind(COMMENT).available(user)
    assert _kind(CHANGED).available(user)
    shown = [row.kind.code for row in _prefs().effective(user).rows if row.kind.code.startswith("knowledge.")]
    assert shown == list(KB_KINDS)


def test_available_for_comment_and_changed_kinds_for_author_of_any_article():
    """FR-434: без прав, но автору хотя бы одной статьи оба вида доступны; до появления статьи — нет."""
    user = kb.as_reader().user
    assert not _kind(COMMENT).available(user)
    assert not _kind(CHANGED).available(user)
    kb.make_published(author=user)
    assert _kind(COMMENT).available(user)
    assert _kind(CHANGED).available(user)
    shown = [row.kind.code for row in _prefs().effective(user).rows if row.kind.code.startswith("knowledge.")]
    assert shown == list(KB_KINDS)


def test_available_subscription_kind_for_every_employee_and_others_hidden_without_rights():
    """FR-434: «Статья в рубрике по подписке» доступна любому сотруднику; без прав и без своих статей двух других
    видов нет ни в `available`, ни в строках таблицы."""
    user = kb.as_reader().user
    kb.make_published()                                 # чужая статья: автором она не делает
    assert _kind(SUBSCRIPTION).available(user)
    assert not _kind(COMMENT).available(user)
    assert not _kind(CHANGED).available(user)
    shown = [row.kind.code for row in _prefs().effective(user).rows if row.kind.code.startswith("knowledge.")]
    assert shown == [SUBSCRIPTION]


def test_my_notifications_table_shows_three_kinds_with_per_channel_switches_except_portal():
    """FR-434: на странице «Мои уведомления» три строки вида с названием и модулем «База знаний»; «На портале» —
    заблокированный отмеченный флажок без `name`, у «Почты» и «Push в браузере» есть флажки `cell` вида
    `<код>:<канал>`; по умолчанию «Почта» отмечена, `push` — нет."""
    client = kb.as_editor().client
    response = client.get(URL)
    assert response.status_code == 200
    doc = _Doc(response.content.decode("utf-8", "replace"))
    table = _one(doc, "table", {"data-notify-table": True})
    rows = [row for row in _find(doc, "tr", {"data-notify-kind": True}, within=table)
            if row.attrs["data-notify-kind"].startswith("knowledge.")]
    assert [row.attrs["data-notify-kind"] for row in rows] == list(KB_KINDS)
    for row in rows:
        code = row.attrs["data-notify-kind"]
        assert _one(doc, None, {"data-field": "title"}, within=row).text == TITLES[code]
        assert _one(doc, None, {"data-field": "module"}, within=row).text == "База знаний"
        cells = _find(doc, "td", {"data-channel": True}, within=row)
        assert [c.attrs["data-channel"] for c in cells] == ["portal", "email", "push", "telegram", "max"], code
        portal = _one(doc, "td", {"data-channel": "portal"}, within=row)
        assert portal.attrs.get("data-locked") == "1", code
        box = _one(doc, "input", {"type": "checkbox"}, within=portal)
        assert "checked" in box.attrs and "disabled" in box.attrs and "name" not in box.attrs, code
        for channel, checked in (("email", True), ("push", False)):
            cell = _one(doc, "td", {"data-channel": channel}, within=row)
            box = _one(doc, "input", {"type": "checkbox", "name": "cell"}, within=cell)
            assert box.attrs["value"] == f"{code}:{channel}", code
            assert ("checked" in box.attrs) is checked, f"{code}:{channel}"


# --- получатели при настоящих действиях (FR-435) ----------------------------------------------------------------

def test_comment_notifies_article_author(django_capture_on_commit_callbacks, caplog):
    """FR-434, FR-435: комментарий другого сотрудника — уведомление `comment_on_my_article` автору опубликованной
    статьи; ссылка с якорем комментариев, `object_ref` статьи; больше никому."""
    author, other_editor = kb.as_editor().user, kb.as_editor().user
    commenter = support.make_employee()
    article = kb.make_published(author=author)
    _comment(commenter, article, django_capture_on_commit_callbacks)
    assert _got() == _want((author, COMMENT))
    note = _notes(COMMENT, author).get()
    assert note.object_ref == f"knowledge.article:{article.pk}"
    assert note.url == f"/kb/{article.pk}/#comments"
    assert note.read_at is None and other_editor.pk not in set(_notes().values_list("user_id", flat=True))
    _no_bus_errors(caplog)


def test_comment_by_author_himself_does_not_notify_him(django_capture_on_commit_callbacks, caplog):
    """FR-435: действия самого получателя его не уведомляют: автор комментирует свою статью — уведомлений нет."""
    author = kb.as_editor().user
    article = kb.make_published(author=author)
    _comment(author, article, django_capture_on_commit_callbacks)
    assert _got() == []
    assert model("core.Comment").objects.filter(object_ref=f"knowledge.article:{article.pk}").count() == 1
    _no_bus_errors(caplog)


def test_comment_on_draft_notifies_nobody(django_capture_on_commit_callbacks, caplog):
    """FR-435: черновик не уведомляет никого: комментарий к черновику служба не принимает (404), а событие
    о комментарии к черновику уведомления не создаёт."""
    from django.http import Http404

    from apps.core import events

    author, commenter = kb.as_editor().user, support.make_employee()
    draft = kb.make_draft(author=author)
    with pytest.raises(Http404):
        _comment(commenter, draft, django_capture_on_commit_callbacks)
    comment = kb.make_comment(draft, commenter)
    with django_capture_on_commit_callbacks(execute=True):
        events.publish("knowledge.comment_added", article_id=draft.pk, comment_id=comment.pk, actor_id=commenter.pk)
    assert _got() == []
    _no_bus_errors(caplog)


def test_change_of_published_article_by_other_notifies_author_with_editor_name(
        django_capture_on_commit_callbacks, caplog):
    """FR-434, FR-435: опубликованную статью сохранил другой сотрудник — автор получает `my_article_changed` с
    названием статьи и именем сохранившего; ссылка на статью без якоря; сохранивший не уведомлён."""
    author = kb.as_editor().user
    editor = kb.as_editor(full_name="Пётр Сидоров").user
    article = kb.make_published(author=author, title="Настройка принтера")
    _save(editor, article, django_capture_on_commit_callbacks)
    assert _got() == _want((author, CHANGED))
    note = _notes(CHANGED, author).get()
    assert note.text == "Вашу статью «Настройка принтера» изменил Пётр Сидоров"
    assert note.url == f"/kb/{article.pk}/" and note.object_ref == f"knowledge.article:{article.pk}"
    _no_bus_errors(caplog)


def test_change_of_published_article_by_author_himself_does_not_notify_him(
        django_capture_on_commit_callbacks, caplog):
    """FR-435: автор сам сохранил свою опубликованную статью — ему уведомления нет, подписчику рубрики — есть
    (контрольный получатель: событие дошло до `notify`)."""
    author, subscriber = kb.as_editor().user, support.make_employee()
    article = kb.make_published(author=author)
    kb.subscribe(subscriber, article.rubric)
    _save(author, article, django_capture_on_commit_callbacks)
    assert _got() == _want((subscriber, SUBSCRIPTION))
    _no_bus_errors(caplog)


def test_editing_draft_notifies_nobody(bus_spy, django_capture_on_commit_callbacks, caplog):
    """FR-435: правка черновика не уведомляет никого — ни автора, ни подписчиков рубрики; события шины нет."""
    author, manager, subscriber = kb.as_editor().user, kb.as_manager().user, support.make_employee()
    draft = kb.make_draft(author=author)
    kb.subscribe(subscriber, draft.rubric)
    bus_spy.listen(*KB_EVENTS)
    _save(manager, draft, django_capture_on_commit_callbacks)
    _save(author, draft, django_capture_on_commit_callbacks, text="Ещё правка")
    assert bus_spy.all() == []
    assert _got() == []
    _no_bus_errors(caplog)


def test_restore_from_trash_and_purge_publish_no_notifications(bus_spy, django_capture_on_commit_callbacks, caplog):
    """FR-435: удаление в корзину, возврат и удаление навсегда событий не публикуют и никого не уведомляют
    (ни автора, ни подписчика рубрики)."""
    author, manager, subscriber = kb.as_editor().user, kb.as_manager().user, support.make_employee()
    article = kb.make_published(author=author)
    kb.subscribe(subscriber, article.rubric)
    bus_spy.listen(*KB_EVENTS)
    articles = _articles()
    with django_capture_on_commit_callbacks(execute=True):
        articles.trash(manager, article.pk)
    with django_capture_on_commit_callbacks(execute=True):
        articles.restore(manager, article.pk)
    assert _fresh(article).state == "published"
    with django_capture_on_commit_callbacks(execute=True):
        articles.trash(manager, article.pk)
    with django_capture_on_commit_callbacks(execute=True):
        articles.purge(_fresh(article), manager)
    assert not type(article).objects.filter(pk=article.pk).exists()
    assert bus_spy.all() == []
    assert _got() == []
    _no_bus_errors(caplog)


def test_author_who_is_also_subscriber_gets_single_my_article_changed(django_capture_on_commit_callbacks, caplog):
    """FR-435, FR-437: автор, подписанный на рубрику своей статьи, при правке другим получает одно уведомление —
    `my_article_changed` (по приоритету), а не два."""
    author, editor = kb.as_editor().user, kb.as_editor().user
    article = kb.make_published(author=author)
    kb.subscribe(author, article.rubric)
    _save(editor, article, django_capture_on_commit_callbacks)
    assert _got() == _want((author, CHANGED))
    _no_bus_errors(caplog)


def test_subscription_on_rubric_and_on_subrubric_gives_one_notification(django_capture_on_commit_callbacks, caplog):
    """FR-435, FR-437: подписка на рубрику и на её подрубрику даёт подписчику одно уведомление
    `rubric_subscription` при публикации статьи в подрубрике."""
    tree = kb.rubric_tree({"Сети": {"VPN": {}}})
    author, manager, subscriber = kb.as_editor().user, kb.as_manager().user, support.make_employee()
    draft = kb.make_draft(author=author, rubric=tree["VPN"])
    kb.subscribe(subscriber, tree["Сети"])
    kb.subscribe(subscriber, tree["VPN"])
    _publish(manager, draft, django_capture_on_commit_callbacks)
    assert _got() == _want((subscriber, SUBSCRIPTION))
    _no_bus_errors(caplog)


def test_publish_notifies_rubric_subscriber_but_not_the_actor(django_capture_on_commit_callbacks, caplog):
    """FR-434, FR-435, FR-437: публикация уведомляет подписчика рубрики статьи, но не того, кто опубликовал, даже
    если он сам подписан; текст — по рубрике самой статьи."""
    rubric = kb.make_rubric("Почта")
    author, manager, subscriber = kb.as_editor().user, kb.as_manager().user, support.make_employee()
    draft = kb.make_draft(author=author, rubric=rubric, title="Как настроить ящик")
    kb.subscribe(subscriber, rubric)
    kb.subscribe(manager, rubric)
    _publish(manager, draft, django_capture_on_commit_callbacks)
    assert _got() == _want((subscriber, SUBSCRIPTION))
    note = _notes(SUBSCRIPTION, subscriber).get()
    assert note.object_ref == f"knowledge.article:{draft.pk}" and note.url == f"/kb/{draft.pk}/"
    assert "Почта" in note.text and "Как настроить ящик" in note.text
    _no_bus_errors(caplog)


def test_change_of_published_article_notifies_subscriber_of_ancestor_rubric_but_not_author_via_subscription(
        django_capture_on_commit_callbacks, caplog):
    """FR-434, FR-435: правка опубликованной статьи в подрубрике уведомляет подписчика рубрики-предка
    (`rubric_subscription`); автор, подписанный на ту же рубрику-предка, получает только `my_article_changed`;
    сохранивший не получает ничего."""
    tree = kb.rubric_tree({"Сети": {"VPN": {}}})
    author, editor, subscriber = kb.as_editor().user, kb.as_editor().user, support.make_employee()
    article = kb.make_published(author=author, rubric=tree["VPN"])
    kb.subscribe(author, tree["Сети"])
    kb.subscribe(subscriber, tree["Сети"])
    kb.subscribe(editor, tree["Сети"])
    _save(editor, article, django_capture_on_commit_callbacks)
    assert _got() == _want((author, CHANGED), (subscriber, SUBSCRIPTION))
    _no_bus_errors(caplog)


def test_publish_notifies_author_only_through_own_subscription(django_capture_on_commit_callbacks, caplog):
    """FR-435: при публикации автора уведомляет только его собственная подписка на рубрику; вид «Мою статью
    изменили» на публикацию не срабатывает."""
    rubric = kb.make_rubric("Принтеры")
    author, manager = kb.as_editor().user, kb.as_manager().user
    first = kb.make_draft(author=author, rubric=rubric)
    _publish(manager, first, django_capture_on_commit_callbacks)
    assert _got() == [], "автор не подписан: уведомления нет"
    kb.subscribe(author, rubric)
    second = kb.make_draft(author=author, rubric=rubric)
    _publish(manager, second, django_capture_on_commit_callbacks)
    assert _got() == _want((author, SUBSCRIPTION))
    assert _notes(SUBSCRIPTION, author).get().object_ref == f"knowledge.article:{second.pk}"
    _no_bus_errors(caplog)


def test_dismissed_author_is_not_notified(django_capture_on_commit_callbacks, caplog):
    """FR-435: уволенный автор уведомления не получает; у статьи активного автора тот же комментарий уведомляет."""
    commenter = support.make_employee()
    dismissed = support.make_employee(state="dismissed")
    gone = kb.make_published(author=dismissed)
    active = kb.as_editor().user
    live = kb.make_published(author=active)
    _comment(commenter, gone, django_capture_on_commit_callbacks)
    assert _got() == []
    _comment(commenter, live, django_capture_on_commit_callbacks)
    assert _got() == _want((active, COMMENT))
    _no_bus_errors(caplog)


def test_author_who_lost_edit_right_is_still_notified(django_capture_on_commit_callbacks, caplog):
    """FR-435: автор, потерявший право «Редактирование базы знаний», уведомление получает (право автора не
    проверяется); вид для него по-прежнему доступен как для автора статьи."""
    author = kb.as_editor().user
    article = kb.make_published(author=author)
    author.roles.clear()
    _drop_cache(author)
    assert _kind(COMMENT).available(author)
    commenter = support.make_employee()
    _comment(commenter, article, django_capture_on_commit_callbacks)
    assert _got() == _want((author, COMMENT))
    _no_bus_errors(caplog)


def test_second_comment_not_notified_while_first_unread_and_new_one_after_reading(
        django_capture_on_commit_callbacks, caplog):
    """FR-435: пока у автора есть непрочитанное уведомление того же вида об этой статье, второй комментарий нового
    не создаёт; после прочтения следующий комментарий создаёт новое; по другой статье — отдельное."""
    author = kb.as_editor().user
    first_commenter, second_commenter = support.make_employee(), support.make_employee()
    article, other = kb.make_published(author=author), kb.make_published(author=author)
    _comment(first_commenter, article, django_capture_on_commit_callbacks)
    _comment(second_commenter, article, django_capture_on_commit_callbacks)
    assert _got() == _want((author, COMMENT))
    _comment(second_commenter, other, django_capture_on_commit_callbacks)
    assert len(_got()) == 2, "другая статья — отдельное уведомление"
    _read_all()
    _comment(first_commenter, article, django_capture_on_commit_callbacks)
    assert _notes(COMMENT, author).filter(object_ref=f"knowledge.article:{article.pk}").count() == 2
    assert _notes(COMMENT, author).filter(object_ref=f"knowledge.article:{article.pk}", read_at=None).count() == 1
    _no_bus_errors(caplog)
