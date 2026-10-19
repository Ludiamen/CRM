"""T-5104: статья — сохранение опубликованной, цепочка шагов, гонки (FR-408, FR-410, FR-413, FR-447, NFR-411).

Сценарии 1 и 3 спеки. Службы `articles.save` и `articles.publish`, страница правки `/kb/<id>/edit/`: версия при
сохранении, «Изменений нет», векторы поиска, событие `knowledge.article_changed`, отказы цепочки шагов плана
(корзина, право, рубрика, устаревшая версия), «гонки» без потоков (последовательные вызовы, ограничения базы,
SQL по помощникам `support_kb`; поправка Opus к решению 18 задач, раздел 16 контракта). Код среза 005 на уровне
модуля не импортируется: имена берутся внутри тестов (шапка CONTRACT-005).
"""
import importlib
from html.parser import HTMLParser

import pytest
from django.contrib.postgres.search import SearchQuery
from django.db import IntegrityError, transaction
from django.utils import timezone

from tests import support
from tests import support_kb as kb

pytestmark = pytest.mark.django_db

HX = {"HX-Request": "true"}
TYPED = "Мой несохранённый текст правки"


# --- помощники файла ------------------------------------------------------------------------------------

def _articles():
    return importlib.import_module("apps.knowledge.services.articles")


def _services():
    return importlib.import_module("apps.knowledge.services")


def _tag_names(article) -> str:
    return ", ".join(sorted(article.tags.values_list("name", flat=True)))


def _form(article, **over):
    """`ArticleForm` с текущими значениями статьи; `over` меняет поля."""
    values = dict(title=article.title, text=article.text, rubric_id=article.rubric_id, tags=_tag_names(article),
                  comment="")
    values.update(over)
    return _articles().ArticleForm(**values)


def _data(article, **over) -> dict:
    """Поля формы правки (раздел 10.2) с текущими значениями статьи; `over` меняет поля."""
    data = {"title": article.title, "text": article.text, "rubric": article.rubric_id, "tags": _tag_names(article),
            "comment": "", "base_version": article.version_no, "confirm_pdn": "", "action": "save"}
    data.update(over)
    return data


def _versions(article):
    return support.model("knowledge.ArticleVersion").objects.filter(article=article)


def _fresh(article):
    return type(article).objects.get(pk=article.pk)


def _editor(**extra):
    user = support.make_employee(**extra)
    kb.grant(user, "knowledge.edit")
    return user


class _Collect(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: list = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, {name: (value or "") for name, value in attrs}))


def _find(body: str, tag: str | None = None, **attrs) -> list:
    """Атрибуты всех тегов `tag` разметки, у которых есть заданные атрибуты (`data_code` -> `data-code`)."""
    parser = _Collect()
    parser.feed(body)
    want = {name.replace("_", "-"): value for name, value in attrs.items()}
    return [found for name, found in parser.tags
            if (tag is None or name == tag) and all(found.get(k) == v for k, v in want.items())]


def _edit(client, article, hx: bool = False, **over):
    """POST формы правки; тело ответа — вторым значением."""
    response = client.post(f"/kb/{article.pk}/edit/", _data(article, **over), headers=HX if hx else {})
    return response, response.content.decode()


def _refused(call):
    """Вызов, который должен дать отказ формы `KnowledgeError`; возвращает исключение."""
    with pytest.raises(_services().KnowledgeError) as caught:
        call()
    return caught.value


def _article_lock_sqls(article, user, form):
    articles = _articles()
    return kb.sql_of(articles.save, user, article.pk, article.version_no, form)


def _first(sqls, predicate) -> int:
    for number, sql in enumerate(sqls):
        if predicate(sql):
            return number
    raise AssertionError("в перечне запросов нет нужного")


# --- сохранение опубликованной: версия, «Изменений нет», векторы, событие ------------------------------

def test_save_of_published_article_creates_version_2_with_author_time_and_comment_visible_to_all(clock):
    """FR-408, FR-410: сохранение опубликованной статьи — версия 2 с автором правки, временем и комментарием;
    версия 1 не меняется; история и текст видны читателю без прав."""
    articles = _articles()
    author, editor = _editor(), _editor()
    reader = kb.as_reader()
    article = kb.make_published(author=author, title="Принтер", text="сканер документов", tags=("vpn",))
    first_published = article.published_at
    moment = kb.moscow(2026, 3, 10, 14, 35)
    clock.set(moment)

    result = articles.save(editor, article.pk, 1, _form(article, text="Новый текст инструкции",
                                                        comment="Уточнил шаги"))

    assert result.kind == "saved"
    version = result.version
    assert (version.number, version.author, version.comment) == (2, editor, "Уточнил шаги")
    assert version.created_at == moment
    assert (version.title, version.text, version.rubric_name) == ("Принтер", "Новый текст инструкции",
                                                                  article.rubric.name)
    assert version.rubric_id == article.rubric_id and sorted(version.tags) == ["vpn"]
    assert "Новый текст инструкции" in version.html
    stored = _fresh(article)
    assert stored.version_no == 2 and stored.state == "published"
    assert (stored.updated_by, stored.updated_at) == (editor, moment)
    assert stored.text == "Новый текст инструкции" and "Новый текст инструкции" in stored.html
    assert "Новый текст инструкции" in stored.plain
    assert stored.published_at == first_published
    old = _versions(article).get(number=1)
    assert old.text == "сканер документов" and old.comment == ""
    assert _versions(article).count() == 2

    history = reader.client.get(f"/kb/{article.pk}/history/")
    assert history.status_code == 200 and "Уточнил шаги" in history.content.decode()
    page = reader.client.get(f"/kb/{article.pk}/")
    assert page.status_code == 200 and "Новый текст инструкции" in page.content.decode()


def test_save_without_changes_says_no_changes_and_creates_no_version(bus, django_capture_on_commit_callbacks):
    """FR-410: те же заголовок, текст, рубрика и теги — «Изменений нет», версии нет, событий нет; комментарий
    к правке сравнению не мешает (план, шаг 5)."""
    articles = _articles()
    session = kb.as_editor()
    article = kb.make_published(title="Принтер", text="сканер документов", tags=("vpn", "wifi"))
    bus.listen("knowledge.article_changed")

    with django_capture_on_commit_callbacks(execute=True):
        result = articles.save(session.user, article.pk, 1, _form(article, comment="без правок"))
    assert result.kind == "no_changes" and result.version is None
    stored = _fresh(article)
    assert (stored.version_no, stored.updated_by_id, stored.updated_at) == (1, article.updated_by_id,
                                                                            article.updated_at)
    assert _versions(article).count() == 1
    assert bus.calls("knowledge.article_changed") == []

    with django_capture_on_commit_callbacks(execute=True):
        response, body = _edit(session.client, article)
    assert response.status_code == 200
    assert _find(body, data_kb_notice="no-changes") and "Изменений нет" in body
    assert _versions(article).count() == 1 and _fresh(article).version_no == 1
    assert bus.calls("knowledge.article_changed") == []


def test_save_with_crlf_line_endings_only_is_no_change():
    """FR-410: перевод строк браузера `\\r\\n` (и `\\r`) не даёт ложной версии; настоящая правка с `\\r\\n`
    сохраняется с переводами `\\n`."""
    articles = _articles()
    session = kb.as_editor()
    article = kb.make_published(text="строка один\nстрока два\nстрока три")

    for crlf in ("строка один\r\nстрока два\r\nстрока три", "строка один\rстрока два\rстрока три"):
        result = articles.save(session.user, article.pk, 1, _form(article, text=crlf))
        assert result.kind == "no_changes" and result.version is None
    response, body = _edit(session.client, article, text="строка один\r\nстрока два\r\nстрока три")
    assert response.status_code == 200 and _find(body, data_kb_notice="no-changes")
    assert _versions(article).count() == 1 and _fresh(article).version_no == 1

    result = articles.save(session.user, article.pk, 1, _form(article, text="строка один\r\nСТРОКА ДВА\r\nстрока три"))
    assert result.kind == "saved" and result.version.number == 2
    assert _fresh(article).text == "строка один\nСТРОКА ДВА\nстрока три"
    assert "\r" not in result.version.text


def test_save_with_tags_in_other_order_or_case_only_is_no_change():
    """FR-410: теги в другом порядке или регистре, с лишними пробелами и повтором — тот же набор, версии нет;
    другой набор — версия со снимком тегов."""
    articles = _articles()
    session = kb.as_editor()
    article = kb.make_published(tags=("vpn", "wifi"))

    result = articles.save(session.user, article.pk, 1, _form(article, tags="  WiFi ,VPN,  vpn "))
    assert result.kind == "no_changes" and result.version is None
    assert _versions(article).count() == 1
    assert sorted(article.tags.values_list("name", flat=True)) == ["vpn", "wifi"]

    result = articles.save(session.user, article.pk, 1, _form(article, tags="WiFi, VPN, Принтер"))
    assert result.kind == "saved" and result.version.number == 2
    assert sorted(result.version.tags) == ["vpn", "wifi", "принтер"]
    assert sorted(_fresh(article).tags.values_list("name", flat=True)) == ["vpn", "wifi", "принтер"]


def test_save_of_published_article_recomputes_search_vectors():
    """FR-447: при сохранении опубликованной статьи векторы пересчитываются (заголовок и теги — в `search_head`,
    текст — в `search_full`); у черновика остаются пустыми."""
    articles = _articles()
    Article = support.model("knowledge.Article")
    user = _editor()
    article = kb.make_published(title="Принтер", text="сканер документов", tags=("vpn",))

    def hit(column: str, word: str) -> bool:
        return Article.objects.filter(pk=article.pk, **{column: SearchQuery(word, config="russian")}).exists()

    assert hit("search_full", "сканер") and hit("search_head", "принтер")

    result = articles.save(user, article.pk, 1, _form(article, title="Картридж", text="заправка тонер",
                                                      tags="vpn, wifi"))
    assert result.kind == "saved"
    assert hit("search_head", "картридж") and hit("search_head", "wifi")
    assert hit("search_full", "картридж") and hit("search_full", "тонер") and hit("search_full", "wifi")
    assert not hit("search_head", "принтер") and not hit("search_full", "принтер")
    assert not hit("search_full", "сканер")
    assert not hit("search_head", "тонер")

    draft = kb.make_draft(title="Черновик", text="пока не нашли", author=user)
    assert articles.save(user, draft.pk, 1, _form(draft, text="черновик со словом тонер")).kind == "saved"
    stored = _fresh(draft)
    assert stored.version_no == 2 and stored.search_full is None and stored.search_head is None


def test_article_changed_event_is_published_only_for_published_article_not_for_draft(
        bus, django_capture_on_commit_callbacks):
    """FR-408: `knowledge.article_changed` после фиксации — только у опубликованной (ключи ровно по плану);
    черновик версию получает, события нет; «Изменений нет» события не даёт."""
    articles = _articles()
    editor = _editor()
    bus.listen("knowledge.article_changed")
    draft = kb.make_draft(text="черновик", author=editor)
    published = kb.make_published(text="опубликована")

    with django_capture_on_commit_callbacks(execute=True):
        result = articles.save(editor, draft.pk, 1, _form(draft, text="черновик, правка"))
    assert result.kind == "saved" and result.version.number == 2
    assert bus.calls("knowledge.article_changed") == []

    with django_capture_on_commit_callbacks(execute=True):
        result = articles.save(editor, published.pk, 1, _form(published, text="опубликована, правка"))
    assert result.kind == "saved"
    calls = bus.calls("knowledge.article_changed")
    assert len(calls) == 1
    assert set(calls[0]) == {"article_id", "actor_id", "rubric_id"}
    assert calls[0] == {"article_id": published.pk, "actor_id": editor.pk, "rubric_id": published.rubric_id}

    with django_capture_on_commit_callbacks(execute=True):
        assert articles.save(editor, published.pk, 2, _form(_fresh(published))).kind == "no_changes"
    assert len(bus.calls("knowledge.article_changed")) == 1


# --- цепочка шагов: корзина, право, рубрика --------------------------------------------------------------

def test_save_of_trash_article_gives_200_article_deleted_and_keeps_text_in_form():
    """FR-413, NFR-411: статья ушла в корзину, пока открыта форма, — 200 «Статья удалена» от имени любого
    сотрудника (в том числе читателя), введённый текст остаётся, в базе ничего не меняется."""
    articles = _articles()
    article = kb.make_trashed(was="published", text="исходный текст")
    for session in (kb.as_editor(), kb.as_reader(), kb.as_manager()):
        response, body = _edit(session.client, article, text=TYPED)
        assert response.status_code == 200
        assert _find(body, role="alert", data_code="article_gone") and "Статья удалена" in body
        assert TYPED in body
    response, body = _edit(kb.as_editor().client, article, hx=True, text=TYPED)
    assert response.status_code == 200 and "Статья удалена" in body and TYPED in body
    assert _find(body, "form", data_form="kb-article")
    stored = _fresh(article)
    assert (stored.state, stored.text, stored.version_no) == ("trash", "исходный текст", 1)
    assert _versions(article).count() == 1

    from apps.knowledge.services import access

    editor = _editor()
    with pytest.raises(access.ArticleGone):
        articles.save(editor, article.pk, 1, _form(article, text=TYPED))
    assert not issubclass(access.ArticleGone, _services().KnowledgeError)
    assert _versions(article).count() == 1 and _fresh(article).text == "исходный текст"


def test_save_without_edit_right_is_refused_by_chain_step_two():
    """FR-413: шаг 2 — нет права править: 403 (чужой черновик у не-управляющего — 404); шаг идёт раньше проверки
    рубрики и версии; в базе ничего не меняется."""
    from django.core.exceptions import PermissionDenied
    from django.http import Http404

    articles = _articles()
    article = kb.make_published(text="исходный текст")
    reader = kb.as_reader()
    editor = _editor()

    response, _body = _edit(reader.client, article, text=TYPED)
    assert response.status_code == 403
    response, _body = _edit(reader.client, article, hx=True, text=TYPED)
    assert response.status_code == 403
    with pytest.raises(PermissionDenied):
        articles.save(reader.user, article.pk, 1, _form(article, text=TYPED))
    with pytest.raises(PermissionDenied):
        articles.save(reader.user, article.pk, 99, _form(article, text=TYPED, rubric_id=2_000_000_000))
    assert _versions(article).count() == 1 and _fresh(article).text == "исходный текст"

    foreign_draft = kb.make_draft(text="чужой черновик")
    with pytest.raises(Http404):
        articles.save(editor, foreign_draft.pk, 1, _form(foreign_draft, text=TYPED))
    assert _versions(foreign_draft).count() == 1 and _fresh(foreign_draft).text == "чужой черновик"


def test_save_with_deleted_rubric_is_refused_at_rubric_field_and_form_text_stays():
    """FR-413: выбранную в форме рубрику удалили — отказ у поля рубрики (`rubric_missing`), текст формы остаётся,
    версии нет; шаг рубрики идёт раньше проверки устаревшей версии."""
    articles = _articles()
    session = kb.as_editor()
    kept = kb.make_rubric("Сети")
    chosen = kb.make_rubric("Почта")
    article = kb.make_published(rubric=kept, text="исходный текст")
    stale = kb.make_published(rubric=kept, text="устарела")
    chosen_pk = chosen.pk
    chosen.delete()

    error = _refused(lambda: articles.save(session.user, article.pk, 1, _form(article, text=TYPED, rubric_id=chosen_pk)))
    assert (error.code, error.field) == ("rubric_missing", "rubric")
    kb.add_version(stale, text="устарела, правка другого")
    error = _refused(lambda: articles.save(session.user, stale.pk, 1, _form(stale, text=TYPED, rubric_id=chosen_pk)))
    assert (error.code, error.field) == ("rubric_missing", "rubric")

    response, body = _edit(session.client, article, text=TYPED, rubric=chosen_pk)
    assert response.status_code == 200
    assert _find(body, data_error="rubric", data_code="rubric_missing")
    assert TYPED in body
    stored = _fresh(article)
    assert (stored.text, stored.version_no, stored.rubric_id) == ("исходный текст", 1, kept.pk)
    assert _versions(article).count() == 1


def test_save_after_rubric_of_article_was_moved_succeeds():
    """FR-413: перенос выбранной в форме рубрики под другой родитель правке не мешает; версия хранит имя рубрики."""
    articles = _articles()
    rubrics = importlib.import_module("apps.knowledge.services.rubrics")
    manager = support.make_employee()
    kb.grant(manager, "knowledge.manage")
    session = kb.as_editor()
    tree = kb.rubric_tree({"Сети": {"VPN": {}}, "Офис": {}})
    article = kb.make_published(text="исходный текст")
    second = kb.make_published(text="вторая")

    rubrics.move(manager, tree["VPN"].pk, tree["Офис"].pk)

    result = articles.save(session.user, article.pk, 1, _form(article, text="после переноса", rubric_id=tree["VPN"].pk))
    assert result.kind == "saved" and result.version.number == 2
    stored = _fresh(article)
    assert stored.rubric_id == tree["VPN"].pk and stored.text == "после переноса"
    assert result.version.rubric_id == tree["VPN"].pk and result.version.rubric_name == "VPN"

    response, _body = _edit(session.client, second, text="тоже после переноса", rubric=tree["VPN"].pk)
    assert response.status_code == 302 and response["Location"] == f"/kb/{second.pk}/"
    assert _fresh(second).rubric_id == tree["VPN"].pk and _fresh(second).version_no == 2


# --- устаревшая версия ----------------------------------------------------------------------------------

def _stale_setup():
    """Статья, которую после открытия формы Анной сохранил Борис (версия 2, 14:35 по Москве)."""
    articles = _articles()
    anna = kb.as_editor(full_name="Анна Первая")
    boris = _editor(full_name="Борис Редакторов")
    article = kb.make_published(text="исходный текст")
    assert articles.save(boris, article.pk, 1, _form(article, text="правка Бориса")).kind == "saved"
    moment = kb.moscow(2026, 3, 10, 14, 35)
    support.model("knowledge.Article").objects.filter(pk=article.pk).update(updated_at=moment)
    return anna, boris, article, moment


def test_save_with_stale_base_version_is_refused_with_who_and_when_and_compare_link():
    """FR-413: `base_version` отстаёт — отказ `stale_version` с кто, когда и ссылкой на сравнение версий."""
    articles = _articles()
    anna, boris, article, moment = _stale_setup()

    error = _refused(lambda: articles.save(anna.user, article.pk, 1, _form(article, text=TYPED)))
    assert isinstance(error, _services().VersionConflict)
    assert (error.code, error.field) == ("stale_version", "")
    assert error.who == "Борис Редакторов" and error.when == moment
    assert (error.current_version, error.base_version) == (2, 1)

    response, body = _edit(anna.client, article, base_version=1, text=TYPED)
    assert response.status_code == 200
    assert _find(body, role="alert", data_code="stale_version")
    assert "Статью уже изменил Борис Редакторов в 14:35" in body
    links = _find(body, "a", data_action="kb-compare-link")
    assert len(links) == 1 and links[0]["href"] == f"/kb/{article.pk}/compare/?v=1&v=2"
    assert "Сравнить версии" in body


def test_rejected_stale_save_keeps_typed_text_and_does_not_overwrite_newer_version():
    """FR-413, NFR-411: отклонённое сохранение оставляет введённый текст в форме, скрытое поле получает текущий
    номер, чужая версия не затёрта и новой версии нет."""
    anna, _boris, article, _moment = _stale_setup()

    response, body = _edit(anna.client, article, base_version=1, text=TYPED, comment="моя правка")
    assert response.status_code == 200
    assert TYPED in body
    hidden = _find(body, "input", name="base_version")
    assert len(hidden) == 1 and hidden[0]["value"] == "2"
    stored = _fresh(article)
    assert (stored.text, stored.version_no) == ("правка Бориса", 2)
    assert _versions(article).count() == 2
    assert not _versions(article).filter(text=TYPED).exists()

    response, body = _edit(anna.client, article, hx=True, base_version=1, text=TYPED)
    assert response.status_code == 200 and TYPED in body and _find(body, "form", data_form="kb-article")
    assert _fresh(article).version_no == 2 and _versions(article).count() == 2


def test_retry_after_rejection_with_updated_hidden_base_version_creates_next_version():
    """FR-413: повторное сохранение с обновлённым скрытым `base_version` проходит и создаёт следующую версию,
    версия чужой правки остаётся в истории."""
    anna, boris, article, _moment = _stale_setup()

    response, body = _edit(anna.client, article, base_version=1, text=TYPED)
    assert response.status_code == 200
    base = _find(body, "input", name="base_version")[0]["value"]

    response = anna.client.post(f"/kb/{article.pk}/edit/", _data(article, base_version=base, text=TYPED))
    assert response.status_code == 302 and response["Location"] == f"/kb/{article.pk}/"
    stored = _fresh(article)
    assert (stored.version_no, stored.text, stored.updated_by_id) == (3, TYPED, anna.user.pk)
    third = _versions(article).get(number=3)
    assert (third.author_id, third.text) == (anna.user.pk, TYPED)
    second = _versions(article).get(number=2)
    assert (second.author_id, second.text) == (boris.pk, "правка Бориса")
    assert sorted(_versions(article).values_list("number", flat=True)) == [1, 2, 3]


# --- «гонки» без потоков ---------------------------------------------------------------------------------

def test_two_concurrent_saves_from_same_base_version_give_exactly_one_version_per_number():
    """FR-413: два сохранения с одной базовой версии — версия 2 одна: второй вызов получает отказ; уникальность
    (`article`, `number`) держит база; сохранение идёт под `FOR UPDATE` строки статьи и общим замком тегов."""
    articles = _articles()
    Version = support.model("knowledge.ArticleVersion")
    Article = support.model("knowledge.Article")
    first, second = _editor(), _editor()
    article = kb.make_published(text="исходный текст")

    assert articles.save(first, article.pk, 1, _form(article, text="правка первого")).kind == "saved"
    error = _refused(lambda: articles.save(second, article.pk, 1, _form(article, text="правка второго")))
    assert error.code == "stale_version"
    assert list(_versions(article).order_by("number").values_list("number", flat=True)) == [1, 2]
    assert _versions(article).get(number=2).text == "правка первого" and _fresh(article).text == "правка первого"

    with pytest.raises(IntegrityError), transaction.atomic():
        Version.objects.create(article=article, number=2, author=second, created_at=timezone.now(), comment="",
                               title="дубль", text="дубль", html="", rubric=article.rubric,
                               rubric_name=article.rubric.name, tags=[])
    assert _versions(article).count() == 2

    article = _fresh(article)
    sqls = _article_lock_sqls(article, first, _form(article, text="правка третья"))
    kb.assert_for_update(sqls, Article._meta.db_table)
    lock_at = _first(sqls, lambda sql: "FOR UPDATE" in sql.upper() and Article._meta.db_table in sql)
    insert_at = _first(sqls, lambda sql: sql.lstrip().upper().startswith("INSERT") and Version._meta.db_table in sql)
    shared_at = _first(sqls, lambda sql: "pg_advisory_xact_lock_shared" in sql)
    assert lock_at < shared_at < insert_at
    assert any(lock.kind == "shared" and lock.key == "knowledge.tags" for lock in kb.advisory_locks(sqls))
    assert _fresh(article).version_no == 3 and _versions(article).count() == 3


def test_rubric_delete_concurrent_with_save_gives_field_refusal_not_server_error():
    """FR-413: удаление рубрики между проверкой и записью исключено блокировкой строки рубрики (`FOR UPDATE`
    до записи версии); удалённая раньше рубрика — отказ у поля, а не ошибка сервера."""
    articles = _articles()
    rubrics = importlib.import_module("apps.knowledge.services.rubrics")
    Rubric = support.model("knowledge.Rubric")
    Version = support.model("knowledge.ArticleVersion")
    session = kb.as_editor()
    manager = support.make_employee()
    kb.grant(manager, "knowledge.manage")
    target = kb.make_rubric("Сети")
    other = kb.make_rubric("Почта")
    article = kb.make_published(text="исходный текст")
    busy = kb.make_published(rubric=target, text="в рубрике")

    sqls = kb.sql_of(articles.save, session.user, article.pk, 1, _form(article, text="правка", rubric_id=target.pk))
    kb.assert_for_update(sqls, Rubric._meta.db_table)
    rubric_lock = _first(sqls, lambda sql: "FOR UPDATE" in sql.upper() and Rubric._meta.db_table in sql)
    insert_at = _first(sqls, lambda sql: sql.lstrip().upper().startswith("INSERT") and Version._meta.db_table in sql)
    assert rubric_lock < insert_at
    assert _fresh(article).rubric_id == target.pk

    error = _refused(lambda: rubrics.delete(manager, target.pk))
    assert error.code == "not_empty"

    gone_pk = other.pk
    rubrics.delete(manager, gone_pk)
    for hx in (False, True):
        response, body = _edit(session.client, busy, hx=hx, text=TYPED, rubric=gone_pk)
        assert response.status_code == 200
        assert _find(body, data_error="rubric", data_code="rubric_missing") and TYPED in body
    assert _fresh(busy).version_no == 1 and _versions(busy).count() == 1
