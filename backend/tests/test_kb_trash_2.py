"""T-5108: удаление навсегда, ночная очистка корзины и срок корзины (FR-416, FR-417, FR-420, FR-448, NFR-410).
Сценарии корзины и срока спеки среза 005.

Ручное удаление (`articles.purge`, кнопка «Удалить навсегда»), ночное задание `knowledge.tasks.purge_trash`
(порции по 100, замок строки `SKIP LOCKED`, повторная проверка под замком, сбой одной статьи, теги без статей под
исключительным замком), расписание `config/cron.py`, страница `/kb/settings/` и служба `settings`.
Гонки проверяются без потоков (раздел 16 CONTRACT-005): последовательно, по SQL и подменой «между выборкой и замком».
Код среза на уровне модуля не импортируется: имена берутся внутри тестов.
"""
import ast
import re
from datetime import datetime, timedelta
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import pytest

from tests import support
from tests import support_kb as kb
from tests.support import BACKEND_DIR, model

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 3, 10, 12, 0, tzinfo=ZoneInfo("UTC"))
PURGED = "knowledge.article_purged"
TERM_CHANGED = "knowledge.trash_days_changed"
GONE = "Статья удалена"
RANGE_TEXT = "Срок корзины — от 7 до 365 суток"


# --- помощники только этого файла ------------------------------------------------------------------------------

def _articles():
    from apps.knowledge.services import articles
    return articles


def _retention():
    from apps.knowledge.services import retention
    return retention


def _settings_service():
    from apps.knowledge.services import settings as knowledge_settings
    return knowledge_settings


def _age(article, days: int) -> None:
    """Статья пробыла в корзине `days` суток к моменту `NOW` (прямая запись `deleted_at`, как команда стенда)."""
    model("knowledge.Article").objects.filter(pk=article.pk).update(deleted_at=NOW - timedelta(days=days))
    article.refresh_from_db()


def _trashed(days: int, *, was: str = "published", **over):
    article = kb.make_trashed(was=was, **over)
    _age(article, days)
    return article


def _exists(article) -> bool:
    return model("knowledge.Article").objects.filter(pk=article.pk).exists()


def _events(action: str):
    return list(model("core.AuditEvent").objects.filter(action=action).order_by("id"))


def _state(article) -> str:
    return model("knowledge.Article").objects.get(pk=article.pk).state


class _Page(HTMLParser):
    """Начальные теги страницы: имя, атрибуты и текст до следующего тега."""

    def __init__(self, html: str):
        super().__init__()
        self.tags: list[dict] = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        self.tags.append({"tag": tag, "attrs": dict(attrs), "text": ""})

    def handle_data(self, data):
        if self.tags:
            self.tags[-1]["text"] += data

    def find(self, tag: str | None = None, **attrs) -> list[dict]:
        wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
        return [t for t in self.tags if (tag is None or t["tag"] == tag)
                and all(t["attrs"].get(name) == value for name, value in wanted.items())]


def _page(response) -> _Page:
    return _Page(response.content.decode())


def _cron_entries() -> list[dict]:
    """Вызовы `register(...)` в `config/cron.py` (разбор дерева): полный путь функции, очередь, cron, имя, предел."""
    tree = ast.parse((BACKEND_DIR / "config" / "cron.py").read_text(encoding="utf-8"))
    aliases = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module and not node.level:
            for alias in node.names:
                aliases[alias.asname or alias.name] = f"{node.module}.{alias.name}"
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "register":
            first = node.args[0] if node.args else None
            options = {kw.arg: kw.value.value for kw in node.keywords if isinstance(kw.value, ast.Constant)}
            target = aliases.get(first.id, first.id) if isinstance(first, ast.Name) else None
            found.append({"target": target, "queue": options.get("queue_name"), "cron": options.get("cron"),
                          "name": options.get("name"), "timeout": options.get("job_timeout")})
    return found


def _lock_index(sqls, kind: str, name: str) -> int | None:
    """Номер первого запроса, где взят замок `kind` (`exclusive` или `shared`) с ключом `name`."""
    for number, sql in enumerate(sqls):
        if any(lock.kind == kind and lock.key == name for lock in kb.advisory_locks([sql])):
            return number
    return None


def _first_index(sqls, pattern: str) -> int | None:
    for number, sql in enumerate(sqls):
        if re.search(pattern, sql, re.I):
            return number
    return None


def _last_index(sqls, pattern: str) -> int | None:
    found = [number for number, sql in enumerate(sqls) if re.search(pattern, sql, re.I)]
    return found[-1] if found else None


# --- удаление навсегда -----------------------------------------------------------------------------------------

def test_purge_deletes_article_versions_core_comments_articlefile_storedfile_and_ticket_links(
        clock, protected_root, django_capture_on_commit_callbacks):
    """FR-416: `purge` удаляет статью, её версии, комментарии ядра, строки `ArticleFile` и `StoredFile`, связи с
    заявками; соседняя статья (в том числе с номером, начинающимся так же) и её данные остаются нетронутыми."""
    clock.set(NOW)
    manager = kb.as_manager()
    article = kb.make_trashed(title="Удаляемая статья")
    kb.add_version(article, text="Вторая версия")
    kb.make_comment(article, text="Первый комментарий")
    kb.make_comment(article, text="Второй комментарий")
    attached = kb.attach_file(article, "схема.png", write=True)
    kb.link_ticket(article, 101)
    kb.link_ticket(article, 102, from_resolution=True)
    neighbour = kb.make_published(title="Соседняя статья")
    kb.add_version(neighbour, text="Правка соседней")
    kb.make_comment(neighbour, text="Комментарий соседа")
    neighbour_file = kb.attach_file(neighbour, "соседняя.png", write=True)
    kb.link_ticket(neighbour, 103)

    with django_capture_on_commit_callbacks(execute=True):
        _articles().purge(article, manager.user)

    assert not _exists(article)
    assert not model("knowledge.ArticleVersion").objects.filter(article_id=article.pk).exists()
    assert not model("core.Comment").objects.filter(object_ref=f"knowledge.article:{article.pk}").exists()
    assert not model("knowledge.ArticleFile").objects.filter(pk=attached.pk).exists()
    assert not model("core.StoredFile").objects.filter(pk=attached.file_id).exists()
    assert not model("knowledge.TicketLink").objects.filter(article_id=article.pk).exists()
    assert _exists(neighbour)
    assert model("knowledge.ArticleVersion").objects.filter(article_id=neighbour.pk).count() == 2
    assert model("core.Comment").objects.filter(object_ref=f"knowledge.article:{neighbour.pk}").count() == 1
    assert model("knowledge.ArticleFile").objects.filter(pk=neighbour_file.pk).exists()
    assert model("core.StoredFile").objects.filter(pk=neighbour_file.file_id).exists()
    assert model("knowledge.TicketLink").objects.filter(article_id=neighbour.pk).count() == 1


def test_purge_erases_files_from_disk_only_after_commit(clock, protected_root, django_capture_on_commit_callbacks):
    """FR-416: файл статьи стирается с диска только после фиксации транзакции (`on_commit`): до неё строки уже
    удалены, а файл ещё на месте; после — файла нет, соседний файл цел."""
    from apps.core.services import files

    clock.set(NOW)
    manager = kb.as_manager()
    article = kb.make_trashed()
    attached = kb.attach_file(article, "схема.png", write=True)
    path = files.attachment_path(attached.file)
    other = kb.attach_file(kb.make_published(), "другая.png", write=True)
    other_path = files.attachment_path(other.file)
    assert path.exists() and other_path.exists()

    with django_capture_on_commit_callbacks(execute=True):
        _articles().purge(article, manager.user)
        assert not _exists(article), "строки удалены в транзакции"
        assert path.exists(), "файл стёрт до фиксации транзакции"
    assert not path.exists(), "после фиксации файл должен быть стёрт"
    assert other_path.exists()


def test_purge_with_missing_disk_file_is_not_an_error(clock, protected_root, django_capture_on_commit_callbacks,
                                                     caplog):
    """FR-416: файла на диске уже нет — это не ошибка: удаление проходит, строки удалены, записи уровня ERROR в
    журнале приложения нет, а имени файла в записях нет."""
    clock.set(NOW)
    manager = kb.as_manager()
    article = kb.make_trashed()
    name = "пропавший-файл-7731.png"
    attached = kb.attach_file(article, name, write=False)
    number = article.pk
    with caplog.at_level("DEBUG"):
        with django_capture_on_commit_callbacks(execute=True):
            _articles().purge(article, manager.user)

    assert not _exists(article)
    assert not model("core.StoredFile").objects.filter(pk=attached.file_id).exists()
    errors = [r for r in caplog.records if r.levelname in ("ERROR", "CRITICAL") and r.name.startswith("apps.")]
    assert not errors, [r.getMessage() for r in errors]
    assert all(name not in r.getMessage() for r in caplog.records)
    # решение 8 раздела 17: ровно одна запись WARNING логгера службы статей, с номером статьи, без имени и пути
    warnings = [r for r in caplog.records
                if r.name == "apps.knowledge.services.articles" and r.levelname == "WARNING"]
    assert len(warnings) == 1, [r.getMessage() for r in caplog.records]
    assert str(number) in warnings[0].getMessage()
    assert "/" not in warnings[0].getMessage().replace(str(number), ""), "в записи не должно быть пути файла"


def test_manual_purge_writes_journal_with_number_and_title_and_manual_mark(clock, protected_root,
                                                                           django_capture_on_commit_callbacks):
    """FR-416: кнопка «Удалить навсегда» (`POST /kb/<id>/purge/`) ведёт на `/kb/trash/` с сообщением, а в журнал
    пишется `knowledge.article_purged` с номером, заголовком и `by_term=false`, исполнитель — управляющий."""
    clock.set(NOW)
    manager = kb.as_manager()
    article = kb.make_trashed(title="Старая инструкция")
    number = article.pk

    with django_capture_on_commit_callbacks(execute=True):
        response = manager.client.post(f"/kb/{number}/purge/", follow=True)

    assert response.redirect_chain and response.redirect_chain[0][0] == "/kb/trash/"
    assert "Статья удалена навсегда" in response.content.decode()
    assert not _exists(article)
    events = _events(PURGED)
    assert len(events) == 1
    event = events[0]
    assert event.actor_id == manager.user.pk
    assert (event.object_type, event.object_id) == ("knowledge.article", str(number))
    assert event.before == {"number": number, "title": "Старая инструкция", "by_term": False}
    assert event.after == {}


def test_manual_purge_requires_manage_right(clock, protected_root, django_capture_on_commit_callbacks):
    """FR-416: удалять навсегда может только управляющий. Над статьёй НЕ в корзине читателю и «редактору» — 403;
    над статьёй В КОРЗИНЕ — 200 с `[role=alert][data-code="article_gone"]` «Статья удалена» (порядок отказов:
    корзина, затем право; раздел 17, п. 5 и 10). Статья и журнал не меняются; управляющему удаление удаётся."""
    clock.set(NOW)
    live = kb.make_published()
    article = kb.make_trashed()
    for session in (kb.as_reader(), kb.as_editor()):
        with django_capture_on_commit_callbacks(execute=True):
            response = session.client.post(f"/kb/{live.pk}/purge/")
        assert response.status_code == 403
        assert _exists(live) and _state(live) == "published"

        with django_capture_on_commit_callbacks(execute=True):
            response = session.client.post(f"/kb/{article.pk}/purge/")
        assert response.status_code == 200
        assert GONE in response.content.decode()
        assert _page(response).find(role="alert", data_code="article_gone"), "нужен [role=alert][data-code=article_gone]"
        assert _exists(article)
        assert _state(article) == "trash"
        assert not _events(PURGED)

    manager = kb.as_manager()
    with django_capture_on_commit_callbacks(execute=True):
        response = manager.client.post(f"/kb/{article.pk}/purge/")
    assert response.status_code == 302
    assert not _exists(article)


def test_purge_does_not_delete_tag_rows(clock, protected_root, django_capture_on_commit_callbacks):
    """FR-416: при удалении навсегда строки тегов остаются (их чистит только ночное задание), связь статьи с
    тегами исчезает вместе со статьёй."""
    clock.set(NOW)
    manager = kb.as_manager()
    article = kb.make_trashed(tags=("впн-проба", "сеть-проба"))
    through = model("knowledge.Article").tags.through
    assert through.objects.filter(article_id=article.pk).count() == 2

    with django_capture_on_commit_callbacks(execute=True):
        _articles().purge(article, manager.user)

    assert not _exists(article)
    assert model("knowledge.Tag").objects.filter(name__in=("впн-проба", "сеть-проба")).count() == 2
    assert not through.objects.filter(article_id=article.pk).exists()


# --- ночная очистка --------------------------------------------------------------------------------------------

def test_nightly_purges_article_in_trash_91_days_and_keeps_one_in_trash_89_days(clock, protected_root):
    """FR-417, FR-448: при сроке 90 суток статья, пробывшая в корзине 91 сутки, удаляется навсегда, а пробывшая 89
    суток остаётся в корзине; опубликованная статья с давним `updated_at` не удаляется по сроку."""
    clock.set(NOW)
    old = _trashed(91)
    fresh = _trashed(89)
    published = kb.make_published()
    model("knowledge.Article").objects.filter(pk=published.pk).update(updated_at=NOW - timedelta(days=400))

    kb.run_purge()

    assert not _exists(old)
    assert _exists(fresh) and _state(fresh) == "trash"
    assert _exists(published) and _state(published) == "published"


def test_nightly_purge_writes_journal_entry_marked_by_term(clock, protected_root):
    """FR-417: очистка по сроку пишет `knowledge.article_purged` без исполнителя, с номером, заголовком и
    `by_term=true`; на оставшуюся статью записи нет."""
    clock.set(NOW)
    old = _trashed(91, title="Давно удалённая")
    fresh = _trashed(89)

    kb.run_purge()

    events = _events(PURGED)
    assert len(events) == 1
    event = events[0]
    assert event.actor_id is None
    assert (event.object_type, event.object_id) == ("knowledge.article", str(old.pk))
    assert event.before == {"number": old.pk, "title": "Давно удалённая", "by_term": True}
    assert event.after == {}
    assert _exists(fresh)


def test_nightly_uses_term_from_settings_changed_to_30_days(clock, protected_root):
    """FR-417: срок берётся из настройки: при 30 сутках удаляются статьи, пробывшие 31 и 60 суток, а пробывшая 29
    суток остаётся (при прежних 90 остались бы все три)."""
    clock.set(NOW)
    model("knowledge.KnowledgeSettings").objects.filter(pk=1).update(trash_days=30)
    a31, a60, a29 = _trashed(31), _trashed(60), _trashed(29)

    kb.run_purge()

    assert not _exists(a31) and not _exists(a60)
    assert _exists(a29) and _state(a29) == "trash"


def test_nightly_processes_articles_in_ascending_number_in_batches_of_100(clock, protected_root, monkeypatch):
    """FR-417: `next_batch(after_id, cutoff)` отдаёт до 100 номеров по возрастанию, следующая порция идёт после
    последнего обработанного; ночной обход берёт порции по 100, пока не кончатся, и не трогает статьи с
    несозревшим сроком."""
    clock.set(NOW)
    author = kb.as_editor().user  # один автор на все статьи: не заводить сотрудника на каждую из 208
    fresh = [_trashed(10, was="draft", author=author) for _ in range(3)]
    expired = [_trashed(91, was="draft", author=author) for _ in range(205)]
    ids = sorted(article.pk for article in expired)
    cutoff = NOW - timedelta(days=90)
    retention = _retention()

    assert retention.next_batch(0, cutoff) == ids[:100]
    assert retention.next_batch(ids[99], cutoff) == ids[100:200]
    assert retention.next_batch(ids[199], cutoff) == ids[200:]
    assert retention.next_batch(ids[-1], cutoff) == []

    batches = kb.act_between_batch_and_lock(monkeypatch, lambda batch: None)
    calls = kb.fail_purge_for(monkeypatch, [])
    kb.run_purge()

    non_empty = [batch for batch in batches if batch]
    assert [len(batch) for batch in non_empty] == [100, 100, 5]
    assert [number for batch in non_empty for number in batch] == ids
    assert calls == ids, "статьи удалены по возрастанию номера"
    assert not model("knowledge.Article").objects.filter(pk__in=ids).exists()
    assert model("knowledge.Article").objects.filter(pk__in=[a.pk for a in fresh]).count() == 3


def test_nightly_skips_article_locked_by_another_transaction_skip_locked(clock, protected_root):
    """FR-417, NFR-410: каждая статья выбирается запросом `SELECT … FOR UPDATE SKIP LOCKED`, поэтому статья,
    занятая другой транзакцией, пропускается, а не ждёт (проверка по SQL: второго соединения в тестах нет)."""
    clock.set(NOW)
    article = _trashed(91)
    table = model("knowledge.Article")._meta.db_table
    retention = _retention()

    sqls = kb.sql_of(retention.purge_trash)

    kb.assert_skip_locked(sqls, table)
    assert not _exists(article)


def test_nightly_rechecks_state_and_term_under_lock_before_purge(clock, protected_root, monkeypatch,
                                                                django_capture_on_commit_callbacks):
    """NFR-410: между выборкой порции и замком строки одну статью вернули из корзины, у другой сдвинули срок;
    под замком состояние и срок проверяются заново, поэтому удаляется только третья, а две первые пропущены."""
    clock.set(NOW)
    returned, renewed, expired = _trashed(91), _trashed(91), _trashed(91)
    Article = model("knowledge.Article")

    def act(batch):
        Article.objects.filter(pk=returned.pk).update(state="published", state_before_trash="", deleted_at=None,
                                                      deleted_by=None)
        Article.objects.filter(pk=renewed.pk).update(deleted_at=NOW)

    batches = kb.act_between_batch_and_lock(monkeypatch, act)
    calls = kb.fail_purge_for(monkeypatch, [])
    with django_capture_on_commit_callbacks(execute=True):
        result = _retention().purge_trash()

    assert sorted(batches[0]) == sorted([returned.pk, renewed.pk, expired.pk])
    assert calls == [expired.pk], "purge вызван только для статьи с вышедшим сроком"
    assert (result.purged, result.skipped, list(result.failed)) == (1, 2, [])
    assert not _exists(expired)
    assert _exists(returned) and _state(returned) == "published"
    assert _exists(renewed) and _state(renewed) == "trash"
    assert [e.object_id for e in _events(PURGED)] == [str(expired.pk)]


def test_nightly_rerun_creates_no_second_journal_entry_and_does_not_fail(clock, protected_root):
    """NFR-410: повторный запуск не находит удалённых статей, не падает и не пишет вторую запись журнала."""
    clock.set(NOW)
    old = _trashed(91)
    fresh = _trashed(89)

    kb.run_purge()
    assert len(_events(PURGED)) == 1
    again = _retention().purge_trash()
    kb.run_purge()

    assert (again.purged, again.skipped, list(again.failed)) == (0, 0, [])
    assert len(_events(PURGED)) == 1
    assert not _exists(old)
    assert _exists(fresh)


def test_nightly_skips_article_restored_in_the_meantime(clock, protected_root, monkeypatch):
    """NFR-410: статью, которую успели вернуть из корзины, очистка пропускает: она остаётся опубликованной со
    своими версиями, комментариями и вложением, записи об удалении нет."""
    clock.set(NOW)
    article = _trashed(91)
    kb.make_comment(article, text="Остаётся")
    kb.attach_file(article, "остаётся.png", write=False)

    def restore(batch):
        model("knowledge.Article").objects.filter(pk=article.pk).update(
            state="published", state_before_trash="", deleted_at=None, deleted_by=None)

    kb.act_between_batch_and_lock(monkeypatch, restore)
    calls = kb.fail_purge_for(monkeypatch, [])
    kb.run_purge()

    assert calls == []
    assert _exists(article) and _state(article) == "published"
    assert model("knowledge.ArticleVersion").objects.filter(article_id=article.pk).count() == 1
    assert model("core.Comment").objects.filter(object_ref=f"knowledge.article:{article.pk}").count() == 1
    assert model("knowledge.ArticleFile").objects.filter(article_id=article.pk).count() == 1
    assert not _events(PURGED)


def test_nightly_failure_of_one_article_does_not_stop_the_loop_and_job_fails_at_the_end(clock, protected_root,
                                                                                         monkeypatch):
    """FR-417, NFR-410: сбой удаления средней статьи не останавливает обход: первая и третья удалены, а задание
    после обхода завершается `PurgeFailed` с номером упавшей; упавшая цела и без записи в журнале."""
    clock.set(NOW)
    first, broken, last = _trashed(91), _trashed(91), _trashed(91)
    retention = _retention()
    calls = kb.fail_purge_for(monkeypatch, [broken.pk])

    with pytest.raises(retention.PurgeFailed) as raised:
        kb.run_purge()

    assert isinstance(raised.value, RuntimeError)
    assert list(raised.value.numbers) == [broken.pk]
    assert calls == sorted([first.pk, broken.pk, last.pk])
    assert not _exists(first) and not _exists(last)
    assert _exists(broken) and _state(broken) == "trash"
    assert sorted(e.object_id for e in _events(PURGED)) == sorted([str(first.pk), str(last.pk)])


def test_nightly_failure_is_logged_with_article_number_and_exception_class(clock, protected_root, monkeypatch, caplog):
    """FR-417: сбой статьи пишется в журнал приложения (`apps.knowledge.services.retention`, ERROR) с номером
    статьи и классом исключения, без текста исключения."""
    class PurgeBoom(Exception):
        pass

    marker = "сообщение-для-проверки-9042"
    clock.set(NOW)
    broken = _trashed(91)
    retention = _retention()
    kb.fail_purge_for(monkeypatch, [broken.pk], exc=PurgeBoom(marker))

    with caplog.at_level("ERROR", logger="apps.knowledge.services.retention"):
        with pytest.raises(retention.PurgeFailed):
            kb.run_purge()

    records = [r for r in caplog.records if r.name == "apps.knowledge.services.retention" and r.levelname == "ERROR"]
    assert records, "сбой не записан в журнал приложения"
    assert any(str(broken.pk) in r.getMessage() and "PurgeBoom" in r.getMessage() for r in records), \
        [r.getMessage() for r in records]
    assert marker not in caplog.text, "текст исключения попал в журнал"


def test_nightly_deletes_tags_without_any_article_and_keeps_tags_in_use(clock, protected_root):
    """FR-417, FR-420: после обхода удаляются теги без единой статьи (в том числе остались без статей после
    очистки), а теги опубликованной статьи и статьи в корзине с несозревшим сроком остаются."""
    clock.set(NOW)
    orphan = kb.make_tag("тег-сирота")
    kb.make_published(tags=("тег-живой",))
    _trashed(10, tags=("тег-в-корзине",))
    _trashed(91, tags=("тег-только-удалённой",))

    kb.run_purge()

    names = set(model("knowledge.Tag").objects.values_list("name", flat=True))
    assert "тег-сирота" not in names and not model("knowledge.Tag").objects.filter(pk=orphan.pk).exists()
    assert "тег-только-удалённой" not in names
    assert {"тег-живой", "тег-в-корзине"} <= names


def test_nightly_keeps_tag_that_is_being_bound_concurrently_thanks_to_shared_lock(clock, protected_root):
    """FR-417, FR-420: тег, который сейчас привязывается, не исчезнет: сохранение статьи с тегами берёт замок
    `knowledge.tags` разделяемым до привязки, а очистка тегов — исключительным в конце, после удаления статей
    и до удаления строк тегов (проверка по SQL: второго соединения в тестах нет)."""
    from apps.knowledge.services.articles import ArticleForm

    clock.set(NOW)
    editor = kb.as_editor()
    draft = kb.make_draft(author=editor.user)
    form = ArticleForm(title="Новое название", text="Новый текст", rubric_id=kb.general_rubric().pk,
                       tags="привязка-а, привязка-б", comment="")
    through = model("knowledge.Article").tags.through._meta.db_table

    save_sqls = kb.sql_of(_articles().save, editor.user, draft.pk, draft.version_no, form)

    shared = _lock_index(save_sqls, "shared", "knowledge.tags")
    insert = _first_index(save_sqls, rf'INSERT INTO "?{through}"?')
    assert shared is not None, kb.advisory_locks(save_sqls)
    assert insert is not None and shared < insert, "замок взят позже привязки тегов"
    assert _lock_index(save_sqls, "exclusive", "knowledge.tags") is None

    kb.make_tag("тег-без-статей")
    _trashed(91)
    article_table = model("knowledge.Article")._meta.db_table
    tag_table = model("knowledge.Tag")._meta.db_table
    purge_sqls = kb.sql_of(_retention().purge_trash)

    exclusive = _lock_index(purge_sqls, "exclusive", "knowledge.tags")
    last_article_delete = _last_index(purge_sqls, rf'DELETE FROM "?{article_table}"?(\s|$)')
    tag_delete = _first_index(purge_sqls, rf'DELETE FROM "?{tag_table}"?(\s|$)')
    assert exclusive is not None, kb.advisory_locks(purge_sqls)
    assert last_article_delete is not None and tag_delete is not None
    assert last_article_delete < exclusive < tag_delete
    assert model("knowledge.Tag").objects.filter(name__in=("привязка-а", "привязка-б")).count() == 2


def test_nightly_is_scheduled_at_2345_utc_on_maintenance_queue_with_job_timeout_600():
    """FR-417: `config/cron.py` регистрирует `purge_trash` (функция `apps.knowledge.tasks.purge_trash`): очередь
    `maintenance`, `cron="45 23 * * *"` по UTC (02:45 по Москве), `job_timeout=600`."""
    msk = datetime(2026, 3, 10, 23, 45, tzinfo=ZoneInfo("UTC")).astimezone(ZoneInfo("Europe/Moscow"))
    assert (msk.hour, msk.minute) == (2, 45)
    found = [e for e in _cron_entries() if e["name"] == "purge_trash"]
    assert len(found) == 1, f"записей purge_trash в config/cron.py: {len(found)}"
    entry = found[0]
    assert entry["target"] == "apps.knowledge.tasks.purge_trash"
    assert entry["queue"] == "maintenance"
    assert entry["cron"] == "45 23 * * *"
    assert entry["timeout"] == 600


# --- срок корзины ----------------------------------------------------------------------------------------------

def test_settings_term_6_and_366_days_are_refused_with_limits_shown(clock):
    """FR-417: срок 6 и 366 суток отклоняется: страница отвечает 200 с `[data-error="trash_days"]
    [data-code="out_of_range"]`, текстом пределов и введённым значением; служба поднимает
    `SettingsError("out_of_range")` у поля `trash_days`; срок и журнал не меняются."""
    clock.set(NOW)
    manager = kb.as_manager()
    for value in (6, 366):
        response = manager.client.post("/kb/settings/", {"trash_days": str(value)})
        assert response.status_code == 200
        page = _page(response)
        assert page.find(data_error="trash_days", data_code="out_of_range"), "нет сообщения об отказе у поля"
        assert RANGE_TEXT in response.content.decode()
        fields = page.find("input", name="trash_days")
        assert fields and fields[0]["attrs"].get("value") == str(value), "введённое значение не сохранилось"
        with pytest.raises(Exception) as raised:
            _settings_service().update(manager.user, value)
        assert type(raised.value).__name__ == "SettingsError"
        assert (raised.value.code, raised.value.field) == ("out_of_range", "trash_days")
    assert _settings_service().get().trash_days == 90
    assert not _events(TERM_CHANGED)


def test_settings_term_7_and_365_days_are_accepted(clock):
    """FR-417: границы 7 и 365 принимаются: страница отвечает 302 на `/kb/settings/` с сообщением «Срок корзины
    сохранён», значение записано."""
    clock.set(NOW)
    manager = kb.as_manager()
    for value in (7, 365):
        response = manager.client.post("/kb/settings/", {"trash_days": str(value)}, follow=True)
        assert response.redirect_chain and response.redirect_chain[0][0] == "/kb/settings/"
        assert response.status_code == 200
        assert "Срок корзины сохранён" in response.content.decode()
        assert _settings_service().get().trash_days == value


def test_settings_default_term_is_90_days(clock):
    """FR-417: по умолчанию срок корзины 90 суток: служба `get` отдаёт строку `pk=1` со 90, создаёт её, если
    строки нет, а страница показывает 90 в поле `trash_days`."""
    clock.set(NOW)
    assert _settings_service().get().trash_days == 90
    model("knowledge.KnowledgeSettings").objects.all().delete()
    created = _settings_service().get()
    assert (created.pk, created.trash_days) == (1, 90)
    response = kb.as_manager().client.get("/kb/settings/")
    assert response.status_code == 200
    fields = _page(response).find("input", name="trash_days")
    assert fields and fields[0]["attrs"].get("type") == "number" and fields[0]["attrs"].get("value") == "90"


def test_settings_change_writes_journal_entry_was_became(clock):
    """FR-417: смена срока пишет `knowledge.trash_days_changed` (`knowledge.article`, пустой номер, исполнитель —
    управляющий) с `before={"days": 90}` и `after={"days": 30}`; то же значение повторно записи не даёт."""
    clock.set(NOW)
    manager = kb.as_manager()

    response = manager.client.post("/kb/settings/", {"trash_days": "30"})

    assert response.status_code == 302
    events = _events(TERM_CHANGED)
    assert len(events) == 1
    event = events[0]
    assert event.actor_id == manager.user.pk
    assert (event.object_type, event.object_id) == ("knowledge.article", "")
    assert event.before == {"days": 90}
    assert event.after == {"days": 30}
    _settings_service().update(manager.user, 30)
    assert len(_events(TERM_CHANGED)) == 1
    assert _settings_service().get().trash_days == 30


def test_settings_page_requires_manage_right(clock):
    """FR-417: страница срока доступна только управляющему: читатель и «редактор» получают 403 и на показ, и на
    сохранение, срок не меняется; управляющему страница открывается."""
    clock.set(NOW)
    for session in (kb.as_reader(), kb.as_editor()):
        assert session.client.get("/kb/settings/").status_code == 403
        assert session.client.post("/kb/settings/", {"trash_days": "30"}).status_code == 403
    assert _settings_service().get().trash_days == 90
    assert not _events(TERM_CHANGED)
    assert kb.as_manager().client.get("/kb/settings/").status_code == 200
