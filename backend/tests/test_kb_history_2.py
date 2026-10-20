"""T-5106: просмотр версии, восстановление версии, удаление версии (FR-411, FR-412, FR-414, FR-431, FR-449).
Сценарии 1 и 5 спеки среза 005: страницы `/kb/<id>/versions/<N>/`, `…/restore/`, `…/delete/`, службы `versions.restore`
и `versions.delete`, журнал `knowledge.version_deleted`, событие шины `knowledge.article_changed` при восстановлении.

Код среза 005 на уровне модуля не импортируется: имена берутся внутри тестов (CONTRACT-005, шапка). Разметку разбирает
`html.parser`; зацепки — раздел 11.6 контракта, тексты — раздел 12.
"""
import re
from html.parser import HTMLParser
from typing import NamedTuple

import pytest
from django.core.exceptions import PermissionDenied
from django.http import Http404

from tests import support
from tests import support_kb as kb
from tests.support import model

pytestmark = pytest.mark.django_db

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}
VERSION_DELETED = "knowledge.version_deleted"


# --- помощники только этого файла ---------------------------------------------------------------------

class _Page(HTMLParser):
    """Элементы страницы: тег, атрибуты, текст вместе с вложенными."""

    def __init__(self):
        super().__init__()
        self.elements = []
        self._stack = []

    def handle_starttag(self, tag, attrs):
        element = {"tag": tag, "attrs": {k: (v if v is not None else "") for k, v in attrs}, "parts": []}
        self.elements.append(element)
        if tag not in _VOID:
            self._stack.append(element)

    def handle_endtag(self, tag):
        if tag in _VOID:
            return
        while self._stack:
            if self._stack.pop()["tag"] == tag:
                break

    def handle_data(self, data):
        for element in self._stack:
            element["parts"].append(data)


def _parse(response) -> _Page:
    page = _Page()
    page.feed(response.content.decode("utf-8", "replace"))
    return page


def _find(page, tag=None, **attrs) -> list:
    """Элементы с такими атрибутами (`data_field="body"` — `data-field`); у каждого `el["text"]`."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for element in page.elements:
        if tag is not None and element["tag"] != tag:
            continue
        if all(element["attrs"].get(name) == value for name, value in wanted.items()):
            element["text"] = " ".join(" ".join(element["parts"]).split())
            found.append(element)
    return found


def _has(page, attr: str) -> list:
    """Элементы, у которых есть атрибут `attr` (любое значение), например `data-kb-pdn`."""
    return [e for e in page.elements if attr in e["attrs"]]


def _alerts(page, code) -> list:
    return [e for e in _find(page, data_code=code) if e["attrs"].get("role") == "alert"]


class World(NamedTuple):
    article: object
    author: object
    r1: object
    r2: object


def _world(*, versions: int = 2, published: bool = True) -> World:
    """Статья с версиями 1…`versions`: версия 1 — рубрика «Сети», тег «впн»; версия 2 — рубрика «Почта», тег «почта»;
    версия 3 — рубрика «Почта», тег «третий». Текущая — последняя."""
    author = kb.as_editor()
    r1, r2 = kb.make_rubric("Сети"), kb.make_rubric("Почта")
    article = kb.make_article(
        title="Исходный заголовок", text="строка один\nстрока два", rubric=r1, tags=("впн",), author=author.user,
        state="published" if published else "draft")
    if versions >= 2:
        kb.add_version(article, author=author.user, title="Новый заголовок", text="другой текст", rubric=r2,
                       tags=("почта",), comment="правка")
    if versions >= 3:
        kb.add_version(article, author=author.user, title="Третий заголовок", text="третий текст", tags=("третий",),
                       comment="ещё правка")
    article.refresh_from_db()
    return World(article, author, r1, r2)


def _versions(article):
    return model("knowledge.ArticleVersion").objects.filter(article=article)


def _snap(version) -> dict:
    return {f: getattr(version, f) for f in (
        "pk", "number", "author_id", "created_at", "comment", "title", "text", "html", "rubric_id", "rubric_name",
        "tags")}


def _all_snaps(article) -> dict:
    return {v.number: _snap(v) for v in _versions(article)}


def _fresh(article):
    return model("knowledge.Article").objects.get(pk=article.pk)


def _journal(action, article=None):
    qs = model("core.AuditEvent").objects.filter(action=action)
    if article is not None:
        qs = qs.filter(object_id=str(article.pk))
    return list(qs.order_by("id"))


def _version_url(article, number, tail="") -> str:
    return f"/kb/{article.pk}/versions/{number}/{tail}"


# --- просмотр версии -------------------------------------------------------------------------------

def test_version_view_shows_stored_html_title_rubric_and_tags_without_rendering():
    """FR-411: просмотр версии показывает готовый `html` версии (не рендер текста), заголовок, рубрику и теги самой
    версии, а не текущей статьи; страница видна читателю без прав (раздел 10.3, 11.6)."""
    world = _world()
    # сохранённый html не соответствует тексту: рендер текста дал бы заголовок «Заголовок версии»
    _versions(world.article).filter(number=1).update(text="# Заголовок версии", html="<p>готовый-маркер</p>")
    reader = kb.as_reader()

    response = reader.client.get(_version_url(world.article, 1))

    assert response.status_code == 200
    page = _parse(response)
    assert _find(page, data_kb_page="version")
    title = _find(page, data_field="title")
    assert title and "Исходный заголовок" in title[0]["text"] and "Новый заголовок" not in title[0]["text"]
    body = _find(page, data_field="body")
    assert body and "готовый-маркер" in body[0]["text"] and "Заголовок версии" not in body[0]["text"]
    rubric = _find(page, data_field="rubric")
    assert rubric and "Сети" in rubric[0]["text"] and "Почта" not in rubric[0]["text"]
    assert {t["attrs"]["data-tag"] for t in _find(page, "a") if "data-tag" in t["attrs"]} == {"впн"}


def test_version_view_buttons_follow_can_change_trash_state_and_current_version_rules():
    """FR-412, FR-449: «Восстановить эту версию» — при `can_change`, статья не в корзине, версия не текущая; «Удалить
    версию» — только управляющему, версия не текущая (раздел 11.6)."""
    world = _world(versions=3)
    article = world.article
    manager, editor, reader = kb.as_manager(), kb.as_editor(), kb.as_reader()

    def buttons(session, number, art=article):
        response = session.client.get(_version_url(art, number))
        assert response.status_code == 200, response.status_code
        page = _parse(response)
        restore = bool(_find(page, "form", data_form="kb-version-restore")) and bool(
            _find(page, "button", data_action="kb-restore-version"))
        delete = bool(_find(page, "form", data_form="kb-version-delete")) and bool(
            _find(page, "button", data_action="kb-delete-version"))
        return restore, delete

    assert buttons(manager, 1) == (True, True)
    assert buttons(editor, 1) == (True, False)
    assert buttons(reader, 1) == (False, False)
    assert buttons(manager, 3) == (False, False)  # текущая версия: ни восстановить, ни удалить
    assert buttons(editor, 3) == (False, False)

    trashed = kb.make_trashed(title="Корзинная", author=world.author.user)
    kb.add_version(trashed, author=world.author.user, text="второй", comment="правка")
    trashed.refresh_from_db()
    # статья в корзине (п. 34 раздела 17): ни «Восстановить эту версию», ни «Удалить версию» — даже управляющему
    assert buttons(manager, 1, trashed) == (False, False)
    # не-управляющему страница версии статьи в корзине — 410 (контракт 10.3)
    assert editor.client.get(_version_url(trashed, 1)).status_code == 410


# --- восстановление версии -------------------------------------------------------------------------

def test_restore_creates_new_version_with_comment_restored_from_version_n_and_fields_of_old(
        django_capture_on_commit_callbacks, bus_spy):
    """FR-412: восстановление создаёт новую версию с заголовком, текстом, рубрикой и тегами выбранной, комментарием
    «Восстановлено из версии N», автором — восстановившим; статья получает те же поля; у опубликованной — событие
    `knowledge.article_changed`; ответ — 302 на `/kb/<id>/` и флеш «Версия восстановлена»."""
    world = _world()
    article = world.article
    bus_spy.listen("knowledge.article_changed")
    restorer = kb.as_editor()
    old = _versions(article).get(number=1)

    with django_capture_on_commit_callbacks(execute=True):
        response = restorer.client.post(_version_url(article, 1, "restore/"), follow=True)

    assert response.redirect_chain and response.redirect_chain[-1][0].split("?")[0] == f"/kb/{article.pk}/"
    flash = [e["text"] for e in _find(_parse(response), role="status")]
    assert any("Версия восстановлена" in text for text in flash), flash
    article = _fresh(article)
    assert article.version_no == 3 and article.state == "published"
    assert (article.title, article.text, article.rubric_id) == (old.title, old.text, world.r1.pk)
    assert sorted(article.tags.values_list("name", flat=True)) == ["впн"]
    assert article.updated_by_id == restorer.user.pk
    new = _versions(article).get(number=3)
    assert new.comment == "Восстановлено из версии 1"
    assert (new.title, new.text, new.rubric_id, new.rubric_name, new.tags) == (
        old.title, old.text, world.r1.pk, "Сети", ["впн"])
    assert new.author_id == restorer.user.pk
    published = bus_spy.calls("knowledge.article_changed")
    assert len(published) == 1
    assert set(published[0]) == {"article_id", "actor_id", "rubric_id"}
    assert (published[0]["article_id"], published[0]["actor_id"], published[0]["rubric_id"]) == (
        article.pk, restorer.user.pk, world.r1.pk)


def test_restore_leaves_earlier_versions_unchanged():
    """FR-412, FR-414: после восстановления версии 1 версии 1 и 2 те же строки с теми же значениями (номера, авторы,
    время, комментарии, снимки), прибавилась ровно одна — номер 3."""
    world = _world()
    before = _all_snaps(world.article)
    assert set(before) == {1, 2}

    response = kb.as_editor().client.post(_version_url(world.article, 1, "restore/"))

    assert response.status_code == 302
    after = _all_snaps(world.article)
    assert set(after) == {1, 2, 3}
    assert {n: after[n] for n in (1, 2)} == before


def test_restore_with_deleted_rubric_in_version_keeps_current_rubric():
    """FR-412: рубрики версии больше нет (`rubric` пусто) — статья остаётся в текущей рубрике, рубрика не
    воссоздаётся; заголовок, текст и теги берутся из версии."""
    world = _world()
    Rubric = model("knowledge.Rubric")
    world.r1.delete()  # версия 1: `rubric` -> NULL (SET_NULL), `rubric_name` остаётся
    assert _versions(world.article).get(number=1).rubric_id is None
    rubrics = Rubric.objects.count()

    response = kb.as_editor().client.post(_version_url(world.article, 1, "restore/"))

    assert response.status_code == 302
    article = _fresh(world.article)
    assert article.version_no == 3
    assert article.rubric_id == world.r2.pk
    assert (article.title, article.text) == ("Исходный заголовок", "строка один\nстрока два")
    assert sorted(article.tags.values_list("name", flat=True)) == ["впн"]
    new = _versions(article).get(number=3)
    assert (new.rubric_id, new.rubric_name) == (world.r2.pk, "Почта")
    assert Rubric.objects.count() == rubrics
    assert not Rubric.objects.filter(name="Сети").exists()


def test_restore_of_published_article_with_personal_data_asks_confirmation_and_passes_with_confirm():
    """FR-412, FR-431: версия с адресом почты в опубликованной статье — без `confirm_pdn` ответ 200 с `[data-kb-pdn]`,
    найденным в списке и кнопкой «Сохранить всё равно» (`confirm_pdn=1`), в базе ничего не меняется; с `confirm_pdn=1`
    восстановление проходит."""
    author = kb.as_editor()
    address = kb.email_of()
    article = kb.make_published(title="С адресом", text="Пишите на " + address, author=author.user)
    kb.add_version(article, author=author.user, text="чистый текст", comment="вычистили")
    article.refresh_from_db()
    before = _all_snaps(article)
    editor = kb.as_editor()

    response = editor.client.post(_version_url(article, 1, "restore/"))

    assert response.status_code == 200
    page = _parse(response)
    assert _has(page, "data-kb-pdn")
    assert any(address in item["text"] for item in _find(page, "li") if "data-pdn-item" in item["attrs"])
    confirm = _find(page, "button", data_action="kb-pdn-confirm")
    assert confirm and confirm[0]["attrs"].get("name") == "confirm_pdn" and confirm[0]["attrs"].get("value") == "1"
    assert "Сохранить всё равно" in confirm[0]["text"]
    assert _find(page, "button", data_action="kb-pdn-back")
    assert _fresh(article).version_no == 2 and _all_snaps(article) == before

    response = editor.client.post(_version_url(article, 1, "restore/"), {"confirm_pdn": "1"})

    assert response.status_code == 302
    article = _fresh(article)
    assert article.version_no == 3 and article.text == "Пишите на " + address
    assert _versions(article).get(number=3).comment == "Восстановлено из версии 1"


def test_restore_of_content_equal_to_current_says_no_changes(django_capture_on_commit_callbacks, bus_spy):
    """FR-412: версия, равная по заголовку, тексту, рубрике и тегам текущей, — «Изменений нет» (200,
    `[data-kb-notice="no-changes"]`), новой версии нет, события нет."""
    world = _world()
    article = world.article
    kb.add_version(article, author=world.author.user, title="Исходный заголовок", text="строка один\nстрока два",
                   rubric=world.r1, tags=("впн",), comment="вернули как было")
    article.refresh_from_db()
    assert article.version_no == 3
    before = _all_snaps(article)
    bus_spy.listen("knowledge.article_changed")

    with django_capture_on_commit_callbacks(execute=True):
        response = kb.as_editor().client.post(_version_url(article, 1, "restore/"))

    assert response.status_code == 200
    page = _parse(response)
    notice = _find(page, data_kb_notice="no-changes")
    assert notice and "Изменений нет" in notice[0]["text"]
    assert _fresh(article).version_no == 3
    assert _all_snaps(article) == before
    assert bus_spy.calls("knowledge.article_changed") == []


def test_restore_of_trash_article_gives_200_article_deleted():
    """FR-412: любой POST над статьёй в корзине — 200 «Статья удалена» (`[role=alert][data-code="article_gone"]`), от
    имени любого сотрудника (читатель, редактор, управляющий); статья и версии не меняются."""
    author = kb.as_editor()
    article = kb.make_trashed(title="В корзине", text="первый", author=author.user)
    kb.add_version(article, author=author.user, text="второй", comment="правка")
    article.refresh_from_db()
    before = _all_snaps(article)
    assert article.state == "trash"

    for session in (kb.as_reader(), kb.as_editor(), kb.as_manager()):
        response = session.client.post(_version_url(article, 1, "restore/"))
        assert response.status_code == 200, response.status_code
        alerts = _alerts(_parse(response), "article_gone")
        assert alerts and "Статья удалена" in alerts[0]["text"]

    response = kb.as_reader().client.post(_version_url(article, 1, "restore/"), headers={"HX-Request": "true"})
    assert response.status_code == 200 and _alerts(_parse(response), "article_gone")
    article = _fresh(article)
    assert article.state == "trash" and article.version_no == 2
    assert _all_snaps(article) == before


def test_restore_without_edit_right_is_forbidden_by_direct_post():
    """FR-412: читатель без права «Редактирование базы знаний» прямым POST получает 403 (на обычный запрос и на
    HTMX), служба `versions.restore` отвечает `PermissionDenied`; в базе ничего не меняется."""
    from apps.knowledge.services import versions

    world = _world()
    before = _all_snaps(world.article)
    reader = kb.as_reader()

    assert reader.client.post(_version_url(world.article, 1, "restore/")).status_code == 403
    assert reader.client.post(_version_url(world.article, 1, "restore/"),
                              headers={"HX-Request": "true"}).status_code == 403
    with pytest.raises(PermissionDenied):
        versions.restore(reader.user, world.article.pk, 1)
    article = _fresh(world.article)
    assert article.version_no == 2 and article.title == "Новый заголовок"
    assert _all_snaps(article) == before


def test_reader_without_edit_right_sees_history_and_compare_but_no_restore_or_edit_buttons():
    """FR-411, FR-412: читатель видит историю (версии по номеру вниз, форма сравнения) и сравнение, но на странице
    версии нет кнопки восстановления, на странице статьи — кнопки «Править», а правка по адресу — 403."""
    world = _world(versions=3)
    article = world.article
    reader = kb.as_reader()

    history = reader.client.get(f"/kb/{article.pk}/history/")
    assert history.status_code == 200
    page = _parse(history)
    assert _find(page, "form", data_form="kb-compare")
    rows = [e["attrs"]["data-version"] for e in page.elements if e["tag"] == "tr" and "data-version" in e["attrs"]]
    assert rows == ["3", "2", "1"]
    assert not _find(page, data_form="kb-version-restore") and not _find(page, data_action="kb-restore-version")

    compare = reader.client.get(f"/kb/{article.pk}/compare/?v=1&v=3")
    assert compare.status_code == 200 and _find(_parse(compare), data_kb_page="compare")
    assert _has(_parse(compare), "data-kb-diff")

    version = reader.client.get(_version_url(article, 1))
    assert version.status_code == 200
    version_page = _parse(version)
    assert not _find(version_page, data_form="kb-version-restore")
    assert not _find(version_page, data_action="kb-restore-version")

    article_page = reader.client.get(f"/kb/{article.pk}/")
    assert article_page.status_code == 200
    assert not _find(_parse(article_page), data_action="kb-edit")
    assert reader.client.get(f"/kb/{article.pk}/edit/").status_code == 403


# --- удаление версии -------------------------------------------------------------------------------

def test_delete_version_by_manager_removes_it_and_keeps_numbers_of_others():
    """FR-449: управляющий удаляет версию 2 из трёх (302 на `/kb/<id>/history/`, флеш «Версия удалена»): строки версий
    1 и 3 те же с теми же номерами, `version_no` прежний, номер 2 не используется повторно — следующее сохранение
    создаёт версию 4."""
    from apps.knowledge.services import articles

    world = _world(versions=3)
    article = world.article
    before = _all_snaps(article)
    manager = kb.as_manager()

    response = manager.client.post(_version_url(article, 2, "delete/"), follow=True)

    assert response.redirect_chain and response.redirect_chain[-1][0].split("?")[0] == f"/kb/{article.pk}/history/"
    flash = [e["text"] for e in _find(_parse(response), role="status")]
    assert any("Версия удалена" in text for text in flash), flash
    after = _all_snaps(article)
    assert set(after) == {1, 3}
    assert after[1] == before[1] and after[3] == before[3]
    assert _fresh(article).version_no == 3

    form = articles.ArticleForm(title="Четвёртый заголовок", text="четвёртый текст", rubric_id=article.rubric_id,
                                tags="третий")
    result = articles.save(world.author.user, article.pk, 3, form)
    assert result.kind == "saved" and result.version.number == 4
    assert set(_all_snaps(article)) == {1, 3, 4} and _fresh(article).version_no == 4


def test_delete_version_writes_journal_with_version_number_and_article_number_and_title():
    """FR-449: журнал `knowledge.version_deleted`: тип `knowledge.article`, объект — номер статьи, актор — управляющий,
    `before` = `number` (номер статьи), `title`, `version` (номер удалённой версии), `after` пуст; одна запись."""
    world = _world(versions=3)
    article = world.article
    manager = kb.as_manager()
    assert _journal(VERSION_DELETED) == []

    response = manager.client.post(_version_url(article, 2, "delete/"))

    assert response.status_code == 302
    events = _journal(VERSION_DELETED)
    assert len(events) == 1
    event = events[0]
    assert (event.object_type, event.object_id, event.actor_id) == ("knowledge.article", str(article.pk), manager.user.pk)
    assert event.before == {"number": article.pk, "title": article.title, "version": 2}
    assert event.after == {}


def test_delete_current_version_is_refused():
    """FR-449: текущую версию удалить нельзя: 200 `[role=alert][data-code="current_version"]` «Текущую версию удалить
    нельзя», служба — `VersionError` с кодом `current_version`; версия на месте, журнала нет."""
    from apps.knowledge.services import VersionError, versions

    world = _world(versions=3)
    article = world.article
    manager = kb.as_manager()
    before = _all_snaps(article)

    response = manager.client.post(_version_url(article, 3, "delete/"))

    assert response.status_code == 200
    alerts = _alerts(_parse(response), "current_version")
    assert alerts and "Текущую версию удалить нельзя" in alerts[0]["text"]
    with pytest.raises(VersionError) as caught:
        versions.delete(manager.user, article.pk, 3)
    assert caught.value.code == "current_version"
    assert _all_snaps(article) == before and _fresh(article).version_no == 3
    assert _journal(VERSION_DELETED) == []


def test_delete_version_without_manage_right_is_forbidden_and_button_is_absent():
    """FR-449: редактор (право править) и читатель получают 403 на прямой POST удаления версии, службе — `PermissionDenied`;
    кнопки «Удалить версию» у них на странице версии нет, у управляющего — есть; версии и журнал не меняются."""
    from apps.knowledge.services import versions

    world = _world(versions=3)
    article = world.article
    before = _all_snaps(article)
    editor, reader, manager = kb.as_editor(), kb.as_reader(), kb.as_manager()

    for session in (editor, reader):
        assert session.client.post(_version_url(article, 1, "delete/")).status_code == 403
        assert session.client.post(_version_url(article, 1, "delete/"),
                                   headers={"HX-Request": "true"}).status_code == 403
        page = _parse(session.client.get(_version_url(article, 1)))
        assert not _find(page, data_form="kb-version-delete") and not _find(page, data_action="kb-delete-version")
        with pytest.raises(PermissionDenied):
            versions.delete(session.user, article.pk, 1)

    page = _parse(manager.client.get(_version_url(article, 1)))
    assert _find(page, "form", data_form="kb-version-delete") and _find(page, "button", data_action="kb-delete-version")
    assert _all_snaps(article) == before
    assert _journal(VERSION_DELETED) == []


def test_link_to_deleted_version_gives_404():
    """FR-449: после удаления версии 2 страница версии, её восстановление и повторное удаление дают 404 — тот же ответ,
    что у несуществующего номера, без данных удалённой версии в теле."""
    world = _world(versions=3)
    article = world.article
    manager, reader = kb.as_manager(), kb.as_reader()
    assert manager.client.post(_version_url(article, 2, "delete/")).status_code == 302

    missing = reader.client.get(_version_url(article, 99))
    assert missing.status_code == 404
    for session in (reader, manager):
        response = session.client.get(_version_url(article, 2))
        assert response.status_code == 404
        body = response.content.decode("utf-8", "replace")
        assert "Новый заголовок" not in body and "другой текст" not in body
    assert manager.client.post(_version_url(article, 2, "restore/")).status_code == 404
    assert manager.client.post(_version_url(article, 2, "delete/")).status_code == 404
    from apps.knowledge.services import versions

    with pytest.raises(Http404):
        versions.restore(manager.user, article.pk, 2)
    assert _fresh(article).version_no == 3 and set(_all_snaps(article)) == {1, 3}


# --- версии не правятся --------------------------------------------------------------------------------

def test_version_content_is_immutable_no_route_edits_stored_version():
    """FR-414: у сохранённой версии нет маршрута правки: под `/kb/<id>/versions/` ровно три адреса (просмотр,
    `restore/`, `delete/`); на адрес версии PUT, PATCH, DELETE и POST — 405, на `restore/` и `delete/` GET — 405; строки
    версий не меняются."""
    world = _world()
    article = world.article
    manager = kb.as_manager()
    before = _all_snaps(article)

    pattern = re.compile(r"^kb/<int:\w+>/versions/<int:\w+>/(restore/|delete/)?$")
    routes = [route for route, _ in support.all_routes() if "versions" in route]
    assert routes and all(pattern.match(route) for route in routes), routes
    assert {pattern.match(route).group(1) or "" for route in routes} == {"", "restore/", "delete/"}

    url = _version_url(article, 1)
    for method in ("put", "patch", "delete", "post"):
        client_call = getattr(manager.client, method)
        response = client_call(url, {"title": "Подмена", "text": "подмена"}, content_type="application/x-www-form-urlencoded")
        assert response.status_code == 405, (method, response.status_code)
    for tail in ("restore/", "delete/"):
        assert manager.client.get(_version_url(article, 1, tail)).status_code == 405
    assert _all_snaps(article) == before and _fresh(article).version_no == 2
