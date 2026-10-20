"""T-5107: корзина статей — удаление, скрытие, старая ссылка, список, возврат (FR-415, FR-416, FR-447, FR-449).

Сценарии «Корзина» спеки: «в корзину» управляющим, векторы поиска, журнал и тишина уведомлений, скрытие статьи
отовсюду, страница «Статья удалена» (410) и показ управляющему, список `/kb/trash/`, «Вернуть» и подтверждения.
Код среза на уровне модуля не импортируется: имена берутся внутри тестов (CONTRACT-005, шапка).
"""
import logging
from html.parser import HTMLParser

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from tests import support
from tests import support_kb as kb
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import HX

pytestmark = pytest.mark.django_db

GONE = "Статья удалена"


# --- разбор разметки (помощник только этого файла) ------------------------------------------------------

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


def q1(scope, tag=None, **attrs):
    found = q(scope, tag, **attrs)
    assert len(found) == 1, f"ожидали один элемент {tag or ''}{attrs}, нашли {len(found)}"
    return found[0]


def ids_in(scope) -> list[int]:
    """Номера статей из `li[data-article-id]` и `tr[data-article-id]` внутри `scope`, в порядке разметки."""
    return [int(node.attrs["data-article-id"]) for node in scope.walk()
            if node.tag in ("li", "tr") and "data-article-id" in node.attrs]


# --- данные теста ---------------------------------------------------------------------------------------

def _svc(name: str):
    import importlib

    return importlib.import_module(f"apps.knowledge.services.{name}")


def _get(session, path, **extra):
    return session.client.get(path, **extra)


def _page(session, path, **extra):
    response = _get(session, path, **extra)
    assert response.status_code == 200, f"{path}: {response.status_code}"
    return tree(response), response.content.decode("utf-8")


def _post(session, path, data=None, **extra):
    return session.client.post(path, data or {}, **extra)


def _audit(action: str, article):
    return list(support.model("core.AuditEvent").objects.filter(action=action, object_id=str(article.pk)))


def _watchers(rubric):
    """Подписчик рубрики и автор статьи: ошибочное уведомление при «в корзину» и «вернуть» дошло бы до них."""
    watcher = kb.as_reader(full_name="Подписчик Рубрикин")
    kb.subscribe(watcher.user, rubric)
    return watcher


def _quiet_check(bus_spy, notifications_before: int, caplog):
    Notification = support.model("notify.Notification")
    assert Notification.objects.count() == notifications_before, "корзина и возврат уведомлений не создают"
    assert bus_spy.all() == [], f"событий шины нет, получили {bus_spy.all()}"
    errors = [r for r in caplog.records if r.name == "apps.core.events" and r.levelno >= logging.ERROR]
    assert errors == [], "в журнале приложения нет ошибок подписчиков"


# --- FR-415: в корзину ----------------------------------------------------------------------------------

def test_trash_by_manager_stores_state_before_trash_and_deleted_by_and_at(clock):
    """FR-415: «в корзину» запоминает состояние до удаления (опубликована или черновик), `deleted_at` и
    `deleted_by`; повторное нажатие — «Статья удалена», поля не меняются."""
    manager = kb.as_manager(full_name="Управляющий Базов")
    published = kb.make_published(title="Опубликованная к удалению")
    draft = kb.make_draft(title="Черновик к удалению")
    clock.advance(minutes=5)
    moment = timezone.now()

    response = _post(manager, f"/kb/{published.pk}/trash/", follow=True)
    assert response.status_code == 200
    assert response.redirect_chain and response.redirect_chain[0][0] == f"/kb/{published.pk}/"
    assert "Статья перенесена в корзину" in response.content.decode("utf-8")
    published.refresh_from_db()
    assert (published.state, published.state_before_trash) == ("trash", "published")
    assert published.deleted_at == moment and published.deleted_by == manager.user

    result = _svc("articles").trash(manager.user, draft.pk)
    assert result.pk == draft.pk
    draft.refresh_from_db()
    assert (draft.state, draft.state_before_trash) == ("trash", "draft")
    assert draft.deleted_at == moment and draft.deleted_by == manager.user

    clock.advance(minutes=10)
    again = _post(manager, f"/kb/{published.pk}/trash/")
    assert again.status_code == 200 and GONE in again.content.decode("utf-8")
    assert q1(tree(again), role="alert", data_code="article_gone") is not None
    published.refresh_from_db()
    assert published.deleted_at == moment and published.state_before_trash == "published"
    with pytest.raises(_svc("access").ArticleGone):
        _svc("articles").trash(manager.user, published.pk)


def test_trash_empties_search_vectors():
    """FR-415, FR-447: у статьи в корзине `search_head` и `search_full` пусты (`NULL`), черновик остаётся пустым."""
    from django.contrib.postgres.search import SearchQuery

    Article = support.model("knowledge.Article")
    manager = kb.as_manager()
    published = kb.make_published(title="Колокольчик найденный", text="лазурный рассвет")
    draft = kb.make_draft(title="Колокольчик черновой")
    assert published.search_head is not None and published.search_full is not None
    assert draft.search_head is None and draft.search_full is None
    query = SearchQuery("лазурный", config="russian")
    assert Article.objects.filter(pk=published.pk, search_full=query).exists()

    _post(manager, f"/kb/{published.pk}/trash/")
    _svc("articles").trash(manager.user, draft.pk)

    for article in (published, draft):
        article.refresh_from_db()
        assert article.state == "trash"
        assert article.search_head is None and article.search_full is None
    assert not Article.objects.filter(pk=published.pk, search_full=query).exists()


def test_trash_writes_journal_entry_and_sends_no_notifications(bus_spy, caplog, django_capture_on_commit_callbacks):
    """FR-415: журнал `knowledge.article_trashed` (номер и заголовок, исполнитель — управляющий); уведомлений
    нет и событий шины нет (FR-435), даже у подписчика рубрики."""
    Notification = support.model("notify.Notification")
    rubric = kb.make_rubric("Сети корзины")
    manager = kb.as_manager()
    watcher = _watchers(rubric)
    published = kb.make_published(title="Журнал корзины", rubric=rubric)
    draft = kb.make_draft(title="Журнал корзины черновик", rubric=rubric)
    bus_spy.listen("knowledge.article_published", "knowledge.article_changed", "knowledge.comment_added")
    before = Notification.objects.count()
    caplog.clear()

    with django_capture_on_commit_callbacks(execute=True):
        _post(manager, f"/kb/{published.pk}/trash/")
        _svc("articles").trash(manager.user, draft.pk)

    for article in (published, draft):
        events = _audit("knowledge.article_trashed", article)
        assert len(events) == 1, f"одна запись журнала на статью {article.pk}"
        event = events[0]
        assert event.actor == manager.user
        assert event.object_type == "knowledge.article"
        assert event.before == {}
        assert event.after == {"number": article.pk, "title": article.title}
    assert not Notification.objects.filter(user=watcher.user).exists()
    _quiet_check(bus_spy, before, caplog)


def test_trash_requires_manage_right_edit_right_is_not_enough_and_button_is_absent():
    """FR-415: «в корзину» — только право `knowledge.manage`: у редактора и читателя отказ 403, статья цела,
    записи журнала нет, кнопки на странице нет; у управляющего кнопка есть; без входа — на страницу входа."""
    from django.core.exceptions import PermissionDenied

    article = kb.make_published(title="Права корзины")
    editor, reader, manager = kb.as_editor(), kb.as_reader(), kb.as_manager()
    anonymous = support.make_client()

    for who in (editor, reader):
        response = _post(who, f"/kb/{article.pk}/trash/")
        assert response.status_code == 403
        assert _post(who, f"/kb/{article.pk}/trash/", headers={"HX-Request": "true"}).status_code == 403
        with pytest.raises(PermissionDenied):
            _svc("articles").trash(who.user, article.pk)
    response = anonymous.post(f"/kb/{article.pk}/trash/")
    assert response.status_code == 302 and response["Location"].startswith("/login/")
    article.refresh_from_db()
    assert article.state == "published" and article.deleted_at is None and article.deleted_by is None
    assert _audit("knowledge.article_trashed", article) == []

    editor_page, _ = _page(editor, f"/kb/{article.pk}/")
    assert q(editor_page, "a", data_action="kb-edit"), "у редактора право править есть"
    assert q(editor_page, "form", data_form="kb-trash") == [], "кнопки «В корзину» у редактора нет"
    reader_page, _ = _page(reader, f"/kb/{article.pk}/")
    assert q(reader_page, "form", data_form="kb-trash") == []
    manager_page, _ = _page(manager, f"/kb/{article.pk}/")
    assert len(q(manager_page, "form", data_form="kb-trash")) == 1


def test_trashed_article_is_hidden_from_home_rubric_tag_page_and_new_and_changed():
    """FR-415: статья в корзине выпадает из главной («Новые и изменённые», дерево рубрик, черновики), страницы
    рубрики и страницы тега — у самого управляющего; до удаления она там была."""
    rubric = kb.make_rubric("Рубрика скрытия")
    tag_name = "скрытый-тег"
    manager = kb.as_manager()
    author = kb.as_editor()
    control = kb.make_published(title="Остаётся на месте", rubric=rubric, tags=[tag_name])
    victim = kb.make_published(title="Уходит в корзину", rubric=rubric, tags=[tag_name])
    draft = kb.make_draft(title="Черновик уходит", rubric=rubric, tags=[tag_name], author=author.user)

    def snapshot():
        home, _ = _page(manager, "/kb/")
        listed = {
            "new": ids_in(q1(home, data_kb_new_and_changed=True)),
            "drafts": ids_in(q1(home, data_kb_all_drafts=True)) if q(home, data_kb_all_drafts=True) else [],
            "rubric": ids_in(q1(_page(manager, f"/kb/rubrics/{rubric.pk}/")[0], data_kb_list=True)),
            "tag": ids_in(q1(_page(manager, "/kb/tags/?name=" + tag_name)[0], data_kb_list=True)),
        }
        mine, _ = _page(author, "/kb/")
        listed["mine"] = ids_in(q1(mine, data_kb_my_drafts=True)) if q(mine, data_kb_my_drafts=True) else []
        row = next(li for li in q(q1(home, data_kb_tree=True), "li") if li.attrs.get("data-rubric-id") == str(rubric.pk))
        listed["count"] = q1(row, data_field="count").text()
        return listed

    before = snapshot()
    assert {control.pk, victim.pk} <= set(before["new"]) and victim.pk in before["rubric"]
    assert victim.pk in before["tag"] and draft.pk in before["drafts"] and draft.pk in before["mine"]
    assert before["count"].startswith("2 ")

    _post(manager, f"/kb/{victim.pk}/trash/")
    _post(manager, f"/kb/{draft.pk}/trash/")
    after = snapshot()
    for name in ("new", "drafts", "rubric", "tag", "mine"):
        assert victim.pk not in after[name] and draft.pk not in after[name], f"статья в корзине осталась в «{name}»"
    assert control.pk in after["new"] and control.pk in after["rubric"] and control.pk in after["tag"]
    assert after["count"] == "1 статья", "число в дереве считает только опубликованные не из корзины"


def test_trashed_article_is_absent_from_search_and_from_pick_for_link():
    """FR-415: статьи в корзине нет в поиске (`/search/`, группа «Статьи») и в списке выбора для привязки
    `/kb/pick/`; такая же опубликованная статья находится."""
    word = "мерцалка"
    reader, manager = kb.as_reader(), kb.as_manager()
    control = kb.make_published(title=f"Найденная {word}")
    victim = kb.make_published(title=f"Удалённая {word}")

    def found():
        page, _ = _page(reader, f"/search/?q={word}")
        groups = q(page, "section", data_search_group="articles")
        rows = [a.attrs["href"] for g in groups for li in q(g, "li", data_search_row=True) for a in q(li, "a")]
        pick, _ = _page(reader, f"/kb/pick/?q={word}")
        picked = ids_in(q1(pick, "ul", data_kb_pick_results=True))
        return rows, picked

    rows, picked = found()
    assert f"/kb/{victim.pk}/" in rows and victim.pk in picked, "до удаления статья находится"
    _post(manager, f"/kb/{victim.pk}/trash/")
    rows, picked = found()
    assert f"/kb/{control.pk}/" in rows and control.pk in picked
    assert f"/kb/{victim.pk}/" not in rows and victim.pk not in picked


def test_trashed_article_is_hidden_from_ticket_card_section_comments_and_files(protected_root):
    """FR-415: у статьи в корзине скрыты связь в разделе «Статьи» карточки заявки, комментарии и вложения:
    читателю не видны, добавить комментарий или файл нельзя («Статья удалена»), строки в базе остаются."""
    Comment, ArticleFile = support.model("core.Comment"), support.model("knowledge.ArticleFile")
    queue = sd.make_queue()
    editor = kb.as_editor()
    reader = kb.as_reader()
    manager = kb.as_manager()
    for who in (editor, reader):
        org.make_member(who.user, queue.unit)
    ticket = sd.make_ticket(queue=queue, subject="Заявка для связи со статьёй")
    article = kb.make_published(title="Связанная и удаляемая")
    kb.link_ticket(article, ticket.number, user=manager.user)
    kb.make_comment(article, author=manager.user, text="Комментарий до корзины")
    stored = kb.attach_file(article, "схема-корзины.png", write=True)

    card, _ = _page(editor, f"/tickets/{ticket.number}/")
    part = q1(card, "div", data_card_part="kb-articles")
    assert article.pk in ids_in(part), "до удаления связь в карточке есть"
    _, before_html = _page(reader, f"/kb/{article.pk}/")
    assert "Комментарий до корзины" in before_html and "схема-корзины.png" in before_html

    _post(manager, f"/kb/{article.pk}/trash/")

    card, card_html = _page(editor, f"/tickets/{ticket.number}/")
    assert article.pk not in ids_in(q1(card, "div", data_card_part="kb-articles"))
    assert article.title not in card_html
    gone = _get(reader, f"/kb/{article.pk}/")
    assert gone.status_code == 410
    body = gone.content.decode("utf-8")
    assert "Комментарий до корзины" not in body and "схема-корзины.png" not in body

    comments_before = Comment.objects.filter(object_ref=f"knowledge.article:{article.pk}").count()
    answer = _post(reader, f"/kb/{article.pk}/comments/", {"text": "Новый после корзины"})
    assert answer.status_code == 200 and GONE in answer.content.decode("utf-8")
    assert q1(tree(answer), role="alert", data_code="article_gone") is not None
    assert Comment.objects.filter(object_ref=f"knowledge.article:{article.pk}").count() == comments_before
    upload = SimpleUploadedFile("новый.txt", b"plain text body", content_type="text/plain")
    answer = _post(editor, f"/kb/{article.pk}/files/", {"file": upload})
    assert answer.status_code == 200 and GONE in answer.content.decode("utf-8")
    assert q1(tree(answer), role="alert", data_code="article_gone") is not None
    assert list(ArticleFile.objects.filter(article=article)) == [stored], "новых файлов нет, прежний на месте"
    assert Comment.objects.filter(object_ref=f"knowledge.article:{article.pk}", text="Комментарий до корзины").exists()


# --- FR-415: старая ссылка -----------------------------------------------------------------------------

def test_old_link_for_non_manager_gives_410_article_deleted_without_title_and_text():
    """FR-415: по старой ссылке не-управляющему — 410 и страница «Статья удалена» без заголовка и текста (для
    опубликованной и для черновика, у читателя, редактора и автора); без входа — страница входа."""
    reader, editor, author = kb.as_reader(), kb.as_editor(), kb.as_editor()
    published = kb.make_trashed(was="published", title="Заголовок скрытой опубликованной",
                                text="Текст скрытой опубликованной", author=author.user)
    draft = kb.make_trashed(was="draft", title="Заголовок скрытого черновика",
                            text="Текст скрытого черновика", author=author.user)
    for article in (published, draft):
        for who in (reader, editor, author):
            response = _get(who, f"/kb/{article.pk}/")
            assert response.status_code == 410, f"{who.user.pk}: {response.status_code}"
            html = response.content.decode("utf-8")
            root = tree(html)
            assert q(root, data_kb_page="gone"), "корень страницы 410 — data-kb-page=gone"
            assert GONE in html
            assert article.title not in html and article.text not in html
            assert q(root, "article", data_article_id=True) == []
    anonymous = support.make_client().get(f"/kb/{published.pk}/")
    assert anonymous.status_code == 302 and anonymous["Location"].startswith("/login/")


def test_get_of_all_article_page_urls_history_versions_edit_of_trash_article_gives_410_to_non_manager():
    """FR-415: все адреса страниц статьи (чтение, правка, история, сравнение, просмотр версии) для статьи в
    корзине дают не-управляющему 410 без заголовка и текста; управляющему — страницы (правка — на страницу
    статьи)."""
    reader, editor, manager = kb.as_reader(), kb.as_editor(), kb.as_manager()
    article = kb.make_trashed(was="published", title="Заголовок всех адресов", text="Текст всех адресов")
    kb.add_version(article, text="Текст всех адресов, версия два")
    pages = kb.article_pages(article)

    for who in (reader, editor):
        for path in pages:
            response = _get(who, path)
            assert response.status_code == 410, f"{path}: {response.status_code}"
            html = response.content.decode("utf-8")
            assert GONE in html and article.title not in html and "Текст всех адресов" not in html
    for path in pages:
        response = _get(manager, path)
        if path.endswith("/edit/"):
            assert response.status_code == 302 and response["Location"] == f"/kb/{article.pk}/"
        else:
            assert response.status_code == 200, f"{path}: {response.status_code}"


def test_old_link_for_manager_shows_article_with_trash_mark_buttons_text_and_images_but_no_comments_files_and_tickets():
    """FR-415: управляющему по старой ссылке — статья с пометкой «в корзине», кнопками «Вернуть» и «Удалить
    навсегда», с текстом и картинками, но без комментариев, списка вложений и связанных заявок."""
    manager = kb.as_manager()
    ticket = sd.make_ticket(queue=sd.make_queue(), subject="Тема связанной заявки корзины")
    article = kb.make_published(title="Видна управляющему", text="Текст виден управляющему")
    stored = kb.attach_file(article, "картинка.png")
    image_src = f"/kb/{article.pk}/images/{stored.pk}/"
    article.html = f'<p>Текст виден управляющему</p><img src="{image_src}" alt="">'
    article.save()
    kb.make_comment(article, text="Скрытый комментарий корзины")
    kb.link_ticket(article, ticket.number)
    _post(manager, f"/kb/{article.pk}/trash/")

    root, html = _page(manager, f"/kb/{article.pk}/")
    card = q1(root, "article", data_article_id=str(article.pk))
    assert card.attrs["data-article-state"] == "trash"
    assert q1(card, "h1", data_field="title").text() == article.title
    body = q1(card, data_field="body")
    assert "Текст виден управляющему" in body.text()
    assert [img.attrs["src"] for img in q(body, "img")] == [image_src]
    assert "В корзине" in q1(root, data_kb_trash_mark=True).text()
    restore = q1(root, "form", data_form="kb-restore")
    purge = q1(root, "form", data_form="kb-purge")
    assert "Вернуть" in restore.text() and "Удалить навсегда" in purge.text()
    assert q(root, "section", data_kb_comments=True) == [] and q(root, data_kb_comments=True) == []
    assert q(root, data_kb_files=True) == [] and q(root, data_kb_tickets=True) == []
    assert "Скрытый комментарий корзины" not in html and "картинка.png" not in html
    assert f"/tickets/{ticket.number}/" not in html


def test_unknown_article_number_gives_404_not_410():
    """FR-415: несуществующий номер статьи — всегда 404, не 410 (у читателя, редактора и управляющего), на всех
    адресах страниц; служба доступа поднимает `Http404`, а не `ArticleGone`."""
    from django.http import Http404

    Article = support.model("knowledge.Article")
    missing = (Article.objects.order_by("-pk").values_list("pk", flat=True).first() or 0) + 1000
    sessions = (kb.as_reader(), kb.as_editor(), kb.as_manager())
    paths = (f"/kb/{missing}/", f"/kb/{missing}/edit/", f"/kb/{missing}/history/",
             f"/kb/{missing}/compare/?v=1&v=2", f"/kb/{missing}/versions/1/")
    for who in sessions:
        for path in paths:
            assert _get(who, path).status_code == 404, path
    for who in sessions:
        with pytest.raises(Http404):
            _svc("access").get_for(who.user, missing)


def test_files_and_images_of_trash_article_give_404_to_non_manager(protected_root):
    """FR-415: файлы и картинки статьи в корзине не-управляющему — ответ несуществующего (404, без выдачи
    файла); управляющему выдаются."""
    reader, editor, manager = kb.as_reader(), kb.as_editor(), kb.as_manager()
    article = kb.make_published(title="Статья с файлами в корзине")
    attached = kb.attach_file(article, "схема.png", write=True)
    plain = kb.attach_file(article, "описание.txt", data=b"plain text body", write=True)
    _post(manager, f"/kb/{article.pk}/trash/")
    paths = (f"/kb/{article.pk}/files/{attached.pk}/", f"/kb/{article.pk}/files/{plain.pk}/",
             f"/kb/{article.pk}/images/{attached.pk}/")
    for who in (reader, editor):
        for path in paths:
            response = _get(who, path)
            assert response.status_code == 404, f"{path}: {response.status_code}"
            assert "X-Accel-Redirect" not in response and "X-KB-Placeholder" not in response
    for path in paths:
        assert _get(manager, path).status_code == 200, path


# --- FR-416: страница корзины ---------------------------------------------------------------------------

def test_trash_page_lists_title_rubric_deletion_date_and_who_deleted_newest_first(clock):
    """FR-416: `/kb/trash/` — заголовок, рубрика, дата удаления (по Москве) и кто удалил; новые удаления сверху;
    пустая корзина — «Корзина пуста»."""
    manager = kb.as_manager()
    empty, _ = _page(manager, "/kb/trash/")
    assert q1(empty, data_kb_page="trash") is not None
    assert q(empty, data_empty_state="kb-trash") and "Корзина пуста" in tree(_get(manager, "/kb/trash/")).text()

    rubric = kb.make_rubric("Рубрика корзины")
    first_by = support.make_employee(full_name="Первый Удаливший")
    second_by = support.make_employee(full_name="Второй Удаливший")
    author = kb.as_editor().user
    clock.advance(minutes=1)
    older = kb.make_trashed(title="Удалена раньше", rubric=rubric, author=author, deleted_by=first_by)
    clock.advance(hours=3)
    newer = kb.make_trashed(title="Удалена позже", author=author, deleted_by=second_by)

    manager = kb.as_manager()  # после сдвига часов на 3 ч прежняя сессия простаивает — вход заново
    root, _ = _page(manager, "/kb/trash/")
    assert q(root, data_empty_state="kb-trash") == []
    table = q1(root, data_kb_trash_list=True)
    rows = q(table, "tr", data_article_id=True)
    assert [int(r.attrs["data-article-id"]) for r in rows] == [newer.pk, older.pk]
    for row, article, who, rubric_name in ((rows[0], newer, second_by, kb.general_rubric().name),
                                           (rows[1], older, first_by, rubric.name)):
        assert q1(row, "a", data_field="title").text() == article.title
        assert rubric_name in q1(row, data_field="rubric").text()
        assert q1(row, "time", data_at=True).text() == kb.moscow_text(article.deleted_at)
        assert who.full_name in q1(row, data_field="deleted-by").text()


def test_trash_page_shows_50_per_page_and_next_page_by_offset(clock):
    """FR-416: корзина — по 50 строк, «Показать ещё» ведёт на следующую порцию по `?offset=` (без потери и
    повтора); кнопки нет, когда порция последняя."""
    manager = kb.as_manager()
    author = kb.as_editor().user
    made = []
    for index in range(51):
        clock.advance(minutes=1)
        made.append(kb.make_trashed(title=f"Удалена {index:02}", author=author, deleted_by=manager.user))
    newest_first = [a.pk for a in reversed(made)]

    root, _ = _page(manager, "/kb/trash/")
    assert ids_in(q1(root, data_kb_trash_list=True)) == newest_first[:50]
    more = q1(root, "button", data_action="more")
    assert more.attrs["data-next-offset"] == "50"
    assert "/kb/trash/" in more.attrs["hx-get"] and "offset=50" in more.attrs["hx-get"]

    response = _get(manager, "/kb/trash/?offset=50", **HX)
    assert response.status_code == 200
    fragment = tree(response)
    assert ids_in(fragment) == newest_first[50:]
    assert q(fragment, "button", data_action="more") == []
    assert q(fragment, "html") == [], "ответ на запрос HTMX — фрагмент без <html>"


def test_trash_page_is_forbidden_without_manage_right():
    """FR-416: корзина — только управляющему: редактору и читателю 403, без входа — страница входа."""
    article = kb.make_trashed(title="Только для управляющего")
    for who in (kb.as_reader(), kb.as_editor()):
        response = _get(who, "/kb/trash/")
        assert response.status_code == 403
        assert article.title not in response.content.decode("utf-8")
    anonymous = support.make_client().get("/kb/trash/")
    assert anonymous.status_code == 302 and anonymous["Location"].startswith("/login/")
    assert _get(kb.as_manager(), "/kb/trash/").status_code == 200


# --- FR-416: возврат ------------------------------------------------------------------------------------

def test_restore_returns_article_to_state_before_trash_published_or_draft_with_same_rubric_and_url():
    """FR-416: «Вернуть» возвращает статью в состояние до корзины (опубликована или черновик), в прежнюю
    рубрику, по прежнему адресу; поля удаления очищены."""
    rubric = kb.make_rubric("Рубрика возврата")
    manager, reader = kb.as_manager(), kb.as_reader()
    author = kb.as_editor()
    published = kb.make_trashed(was="published", title="Вернуть опубликованную", rubric=rubric, author=author.user)
    draft = kb.make_trashed(was="draft", title="Вернуть черновик", rubric=rubric, author=author.user)

    response = _post(manager, f"/kb/{published.pk}/restore/", follow=True)
    assert response.redirect_chain[0][0] == f"/kb/{published.pk}/"
    assert "Статья возвращена из корзины" in response.content.decode("utf-8")
    result = _svc("articles").restore(manager.user, draft.pk)
    assert result.pk == draft.pk

    for article, state in ((published, "published"), (draft, "draft")):
        article.refresh_from_db()
        assert article.state == state
        assert article.state_before_trash == "" and article.deleted_at is None and article.deleted_by is None
        assert article.rubric == rubric
    root, _ = _page(reader, f"/kb/{published.pk}/")
    assert q1(root, "article", data_article_id=str(published.pk)).attrs["data-article-state"] == "published"
    assert _get(reader, f"/kb/{draft.pk}/").status_code == 404, "черновик читателю по-прежнему не виден"
    root, _ = _page(author, f"/kb/{draft.pk}/")
    assert q1(root, "article", data_article_id=str(draft.pk)).attrs["data-article-state"] == "draft"


def test_restore_of_published_article_recomputes_search_vectors_and_draft_stays_empty():
    """FR-416, FR-447: после возврата опубликованной статьи векторы поиска считаются заново (заголовок — в
    `search_head`, текст — только в `search_full`); у вернувшегося черновика остаются пустыми."""
    from django.contrib.postgres.search import SearchQuery

    Article = support.model("knowledge.Article")
    manager = kb.as_manager()
    published = kb.make_trashed(was="published", title="Вектор возвращённой", text="лазурный рассвет над сетью")
    draft = kb.make_trashed(was="draft", title="Вектор возвращённого черновика", text="лазурный закат")
    for article in (published, draft):
        assert article.search_head is None and article.search_full is None

    _post(manager, f"/kb/{published.pk}/restore/")
    _post(manager, f"/kb/{draft.pk}/restore/")

    published.refresh_from_db()
    draft.refresh_from_db()
    assert published.search_head is not None and published.search_full is not None
    in_title = SearchQuery("возвращённой", config="russian")
    in_body = SearchQuery("лазурный", config="russian")
    assert Article.objects.filter(pk=published.pk, search_head=in_title).exists()
    assert Article.objects.filter(pk=published.pk, search_full=in_body).exists()
    assert not Article.objects.filter(pk=published.pk, search_head=in_body).exists()
    assert draft.state == "draft" and draft.search_head is None and draft.search_full is None


def test_restore_brings_back_comments_files_and_ticket_links():
    """FR-416, FR-415: после «в корзину» и «вернуть» комментарии, вложения и связи с заявками на месте и снова
    показаны читателю; пока статья в корзине, их читатель не видит."""
    Comment = support.model("core.Comment")
    ArticleFile = support.model("knowledge.ArticleFile")
    TicketLink = support.model("knowledge.TicketLink")
    queue = sd.make_queue()
    manager = kb.as_manager()
    reader = kb.as_reader()
    org.make_member(reader.user, queue.unit)
    ticket = sd.make_ticket(queue=queue, subject="Заявка возвращаемой статьи")
    article = kb.make_published(title="Возвращаемая с содержимым")
    kb.make_comment(article, author=manager.user, text="Комментарий переживает корзину")
    attached = kb.attach_file(article, "схема-возврата.png")
    kb.link_ticket(article, ticket.number, user=manager.user)

    _post(manager, f"/kb/{article.pk}/trash/")
    assert _get(reader, f"/kb/{article.pk}/").status_code == 410
    assert Comment.objects.filter(object_ref=f"knowledge.article:{article.pk}").count() == 1
    assert ArticleFile.objects.filter(article=article).count() == 1
    assert TicketLink.objects.filter(article=article).count() == 1

    _post(manager, f"/kb/{article.pk}/restore/")

    assert Comment.objects.filter(object_ref=f"knowledge.article:{article.pk}").count() == 1
    assert list(ArticleFile.objects.filter(article=article)) == [attached]
    assert TicketLink.objects.filter(article=article, ticket_number=ticket.number).count() == 1
    root, html = _page(reader, f"/kb/{article.pk}/")
    comments = q1(root, "section", data_kb_comments=True)
    assert "Комментарий переживает корзину" in comments.text()
    files = q1(root, data_kb_files=True)
    assert "схема-возврата.png" in files.text()
    tickets = q1(root, data_kb_tickets=True)
    assert [li.attrs["data-ticket-number"] for li in q(tickets, "li", data_ticket_number=True)] == [str(ticket.number)]


def test_restore_writes_journal_entry_and_sends_no_notifications(bus_spy, caplog, django_capture_on_commit_callbacks):
    """FR-416: журнал `knowledge.article_restored` (номер и заголовок, исполнитель — управляющий); уведомлений и
    событий шины нет (FR-435), подписчик рубрики ничего не получает."""
    Notification = support.model("notify.Notification")
    rubric = kb.make_rubric("Рубрика тишины")
    manager = kb.as_manager()
    watcher = _watchers(rubric)
    published = kb.make_trashed(was="published", title="Возврат без шума", rubric=rubric)
    draft = kb.make_trashed(was="draft", title="Возврат черновика без шума", rubric=rubric)
    bus_spy.listen("knowledge.article_published", "knowledge.article_changed", "knowledge.comment_added")
    before = Notification.objects.count()
    caplog.clear()

    with django_capture_on_commit_callbacks(execute=True):
        _post(manager, f"/kb/{published.pk}/restore/")
        _svc("articles").restore(manager.user, draft.pk)

    for article in (published, draft):
        events = _audit("knowledge.article_restored", article)
        assert len(events) == 1
        event = events[0]
        assert event.actor == manager.user and event.object_type == "knowledge.article"
        assert event.before == {} and event.after == {"number": article.pk, "title": article.title}
    assert not Notification.objects.filter(user=watcher.user).exists()
    _quiet_check(bus_spy, before, caplog)


def test_restore_requires_manage_right():
    """FR-416: «Вернуть» — только управляющему: у читателя и редактора отказ 403 на опубликованной статье, а над
    статьёй в корзине — 200 `[role=alert][data-code="article_gone"]` (`ArticleGone`, раздел 17 п. 5); статья
    в корзине остаётся в корзине без записи журнала; у управляющего «вернуть» не из корзины — отказ
    `not_in_trash`."""
    from django.core.exceptions import PermissionDenied

    reader, editor, manager = kb.as_reader(), kb.as_editor(), kb.as_manager()
    live = kb.make_published(title="Не из корзины")
    trashed = kb.make_trashed(was="published", title="В корзине ждёт управляющего")

    for who in (reader, editor):
        assert _post(who, f"/kb/{live.pk}/restore/").status_code == 403
        answer = _post(who, f"/kb/{trashed.pk}/restore/")
        # раздел 17, п. 5: над статьёй в корзине — порядок «корзина, затем право»: 200 и article_gone
        assert answer.status_code == 200
        assert GONE in answer.content.decode("utf-8")
        assert q1(tree(answer), role="alert", data_code="article_gone") is not None
        with pytest.raises(_svc("access").ArticleGone):
            _svc("articles").restore(who.user, trashed.pk)
        with pytest.raises(PermissionDenied):
            _svc("articles").restore(who.user, live.pk)
    anonymous = support.make_client().post(f"/kb/{trashed.pk}/restore/")
    assert anonymous.status_code == 302 and anonymous["Location"].startswith("/login/")
    trashed.refresh_from_db()
    assert trashed.state == "trash" and trashed.deleted_at is not None
    assert _audit("knowledge.article_restored", trashed) == []

    answer = _post(manager, f"/kb/{live.pk}/restore/")
    assert answer.status_code == 200
    assert q1(tree(answer), role="alert", data_code="not_in_trash") is not None
    with pytest.raises(__import__("apps.knowledge.services", fromlist=["ArticleError"]).ArticleError) as raised:
        _svc("articles").restore(manager.user, live.pk)
    assert raised.value.code == "not_in_trash"
    live.refresh_from_db()
    assert live.state == "published"


# --- FR-415, FR-416, FR-449: подтверждения --------------------------------------------------------------

def test_trash_purge_and_version_delete_forms_require_confirmation():
    """FR-415, FR-416, FR-449: формы «в корзину», «удалить навсегда» и «удалить версию» несут `hx-confirm` с
    текстом подтверждения (раздел 12.3 контракта); форма «Вернуть» подтверждения не требует."""
    manager = kb.as_manager()
    live = kb.make_published(title="Подтверждение корзины")
    trashed = kb.make_trashed(was="published", title="Подтверждение удаления навсегда")
    versioned = kb.make_published(title="Подтверждение удаления версии")
    kb.add_version(versioned, text="Вторая версия текста")

    root, _ = _page(manager, f"/kb/{live.pk}/")
    assert q1(root, "form", data_form="kb-trash").attrs.get("hx-confirm") == "Перенести статью в корзину?"
    root, _ = _page(manager, f"/kb/{trashed.pk}/")
    assert q1(root, "form", data_form="kb-purge").attrs.get("hx-confirm") == "Удалить статью навсегда? Это нельзя отменить."
    assert not q1(root, "form", data_form="kb-restore").attrs.get("hx-confirm")
    root, _ = _page(manager, f"/kb/{versioned.pk}/versions/1/")
    assert q1(root, "form", data_form="kb-version-delete").attrs.get("hx-confirm") == "Удалить версию 1?"
