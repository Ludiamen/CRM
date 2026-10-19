"""T-5124: журнал базы знаний — двенадцать действий, исполнитель, «было / стало», подписи, отсутствие текстов,
только дописывание (FR-438, NFR-407). Сценарии 1, 3, 4, 5, 6, 7 спеки среза 005.

Каждое действие совершает настоящая служба `knowledge`; запись читается из `core.AuditEvent` (раздел 8.1 контракта):
код, `object_type`, `object_id`, исполнитель, `before` и `after`. Тип `number` — целое (раздел 17, решение 1).
Код среза на уровне модуля не импортируется: имена берутся внутри тестов (CONTRACT-005, шапка).
"""
import ast
import json
import re
from datetime import timedelta
from pathlib import Path

import pytest
from django.db import ProgrammingError, connection, transaction
from django.utils import timezone

from tests import support
from tests import support_kb as kb
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

CODES = (
    "knowledge.article_created", "knowledge.article_published", "knowledge.article_trashed",
    "knowledge.article_restored", "knowledge.article_purged", "knowledge.version_deleted",
    "knowledge.comment_deleted", "knowledge.rubric_created", "knowledge.rubric_renamed", "knowledge.rubric_moved",
    "knowledge.rubric_deleted", "knowledge.trash_days_changed",
)
ALLOWED_FIELDS = {"number", "title", "version", "name", "path", "days", "by_term"}
# ключи `before` и `after` по действиям (раздел 8.1)
FIELDS_BY_ACTION = {
    "knowledge.article_created": ((), ("number", "title", "version")),
    "knowledge.article_published": ((), ("number", "title", "version")),
    "knowledge.article_trashed": ((), ("number", "title")),
    "knowledge.article_restored": ((), ("number", "title")),
    "knowledge.article_purged": (("number", "title", "by_term"), ()),
    "knowledge.version_deleted": (("number", "title", "version"), ()),
    "knowledge.comment_deleted": (("number", "title"), ()),
    "knowledge.rubric_created": ((), ("name", "path")),
    "knowledge.rubric_renamed": (("name", "path"), ("name", "path")),
    "knowledge.rubric_moved": (("name", "path"), ("name", "path")),
    "knowledge.rubric_deleted": (("name", "path"), ()),
    "knowledge.trash_days_changed": (("days",), ("days",)),
}
ACTION_TITLES = {
    "knowledge.article_created": "Статья создана",
    "knowledge.article_published": "Статья опубликована",
    "knowledge.article_trashed": "Статья перенесена в корзину",
    "knowledge.article_restored": "Статья возвращена из корзины",
    "knowledge.article_purged": "Статья удалена навсегда",
    "knowledge.version_deleted": "Версия статьи удалена",
    "knowledge.comment_deleted": "Чужой комментарий удалён",
    "knowledge.rubric_created": "Рубрика создана",
    "knowledge.rubric_renamed": "Рубрика переименована",
    "knowledge.rubric_moved": "Рубрика перенесена",
    "knowledge.rubric_deleted": "Рубрика удалена",
    "knowledge.trash_days_changed": "Срок корзины изменён",
}
FIELD_TITLES = {
    "number": "номер", "name": "название", "title": "заголовок", "version": "номер версии", "path": "путь",
    "days": "срок, дней", "by_term": "по сроку",
}
OBJECT_TITLES = {"knowledge.article": "статья", "knowledge.rubric": "рубрика"}

TEXT_MARK = "уникальный-текст-статьи-для-проверки-журнала"
COMMENT_MARK = "уникальный-текст-комментария-для-проверки-журнала"
FILE_MARK = "приватное-имя-вложения"
VERSION_NOTE_MARK = "уникальная-пометка-к-правке"


# --- помощники только этого файла ------------------------------------------------------------------------

def _form(title: str = "Заголовок статьи журнала", text: str = TEXT_MARK, rubric=None, tags: str = "",
          comment: str = ""):
    from apps.knowledge.services import articles

    return articles.ArticleForm(title=title, text=text, rubric_id=(rubric or kb.general_rubric()).pk, tags=tags,
                                comment=comment)


def _events(action: str, object_id=None) -> list:
    query = model("core.AuditEvent").objects.filter(action=action)
    if object_id is not None:
        query = query.filter(object_id=str(object_id))
    return list(query.order_by("id"))


def _one(action: str, object_id=None):
    found = _events(action, object_id)
    assert len(found) == 1, f"{action}: записей {len(found)}, ожидалась одна"
    return found[0]


def _all_kb_events() -> list:
    return list(model("core.AuditEvent").objects.filter(action__startswith="knowledge.").order_by("id"))


def _everything() -> dict:
    """Совершает по настоящей службе все двенадцать действий; возвращает участников и объекты."""
    from apps.knowledge.services import articles, rubrics, settings as kb_settings, versions

    author, manager, reader = kb.as_editor(), kb.as_manager(), kb.as_reader()
    created = articles.create(author.user, _form(comment=VERSION_NOTE_MARK))
    articles.publish(manager.user, created.pk, 1)
    articles.save(author.user, created.pk, 1, _form(title="Новый заголовок журнала", text=TEXT_MARK + " правка"))
    kb.attach_file(created, FILE_MARK + ".png")
    foreign = kb.make_comment(created, reader.user, COMMENT_MARK)
    articles.delete_comment(manager.user, foreign.pk)
    versions.delete(manager.user, created.pk, 1)
    articles.trash(manager.user, created.pk)
    articles.restore(manager.user, created.pk)
    articles.trash(manager.user, created.pk)
    manual = model("knowledge.Article").objects.get(pk=created.pk)
    articles.purge(manual, manager.user, by_term=False)
    expired = kb.make_trashed(title="Просроченная статья журнала", text=TEXT_MARK)
    model("knowledge.Article").objects.filter(pk=expired.pk).update(deleted_at=timezone.now() - timedelta(days=100))
    kb.run_purge()
    root = rubrics.create(manager.user, "Сети", kb.general_rubric().pk)
    other = rubrics.create(manager.user, "Почта", None)
    rubrics.rename(manager.user, root.pk, "Сети и связь")
    rubrics.move(manager.user, root.pk, other.pk)
    rubrics.delete(manager.user, root.pk)
    kb_settings.update(manager.user, 30)
    return {"author": author, "manager": manager, "reader": reader, "article": created, "expired": expired,
            "root": root, "other": other}


# --- действия над статьёй ---------------------------------------------------------------------------------

def test_creating_article_writes_article_created_with_author_actor():
    """FR-438: первое сохранение — одна запись `knowledge.article_created`: исполнитель — автор, объект —
    `knowledge.article` с номером статьи, `before` пуст, в `after` номер, заголовок и версия 1."""
    from apps.knowledge.services import articles

    author = kb.as_editor()
    article = articles.create(author.user, _form(title="Как настроить принтер"))
    event = _one("knowledge.article_created", article.pk)
    assert event.actor == author.user
    assert event.object_type == "knowledge.article" and event.object_id == str(article.pk)
    assert event.before == {}
    assert set(event.after) == {"number", "title", "version"}
    assert int(event.after["number"]) == article.pk
    assert event.after["title"] == "Как настроить принтер" and event.after["version"] == 1


def test_publishing_writes_article_published_with_publisher_actor():
    """FR-438: публикация — запись `knowledge.article_published`, исполнитель — тот, кто опубликовал (не автор);
    в `after` номер, заголовок и номер текущей версии."""
    from apps.knowledge.services import articles

    manager = kb.as_manager()
    draft = kb.make_draft(title="Черновик к публикации")
    kb.add_version(draft, text="вторая версия")
    result = articles.publish(manager.user, draft.pk, 2)
    assert result.article.state == "published"
    event = _one("knowledge.article_published", draft.pk)
    assert event.actor == manager.user and event.actor != draft.author
    assert event.object_type == "knowledge.article"
    assert event.before == {}
    assert set(event.after) == {"number", "title", "version"}
    assert int(event.after["number"]) == draft.pk and event.after["title"] == "Черновик к публикации"
    assert event.after["version"] == 2


def test_moving_to_trash_writes_article_trashed_with_manager_actor():
    """FR-438: перенос в корзину — запись `knowledge.article_trashed`, исполнитель — управляющий; `before` пуст,
    в `after` только номер и заголовок."""
    from apps.knowledge.services import articles

    manager = kb.as_manager()
    article = kb.make_published(title="Устаревшая статья")
    articles.trash(manager.user, article.pk)
    event = _one("knowledge.article_trashed", article.pk)
    assert event.actor == manager.user and event.object_type == "knowledge.article"
    assert event.before == {}
    assert set(event.after) == {"number", "title"}
    assert int(event.after["number"]) == article.pk and event.after["title"] == "Устаревшая статья"


def test_restore_from_trash_writes_article_restored():
    """FR-438: возврат из корзины — запись `knowledge.article_restored` с исполнителем-управляющим; `before` пуст,
    в `after` номер и заголовок; статья вернулась в прежнее состояние."""
    from apps.knowledge.services import articles

    manager = kb.as_manager()
    article = kb.make_trashed(title="Статья из корзины")
    articles.restore(manager.user, article.pk)
    article.refresh_from_db()
    assert article.state == "published"
    event = _one("knowledge.article_restored", article.pk)
    assert event.actor == manager.user and event.object_type == "knowledge.article"
    assert event.before == {}
    assert set(event.after) == {"number", "title"}
    assert int(event.after["number"]) == article.pk and event.after["title"] == "Статья из корзины"
    assert _events("knowledge.article_trashed", article.pk) == [], "возврат не пишет запись о корзине"


def test_manual_purge_writes_article_purged_with_manager_actor_and_by_term_false(
        django_capture_on_commit_callbacks):
    """FR-438: ручное удаление навсегда — запись `knowledge.article_purged`: исполнитель — управляющий,
    `before` — номер, заголовок и `by_term` ровно `False`, `after` пуст, номер удалённой статьи в `object_id`."""
    from apps.knowledge.services import articles

    manager = kb.as_manager()
    article = kb.make_trashed(title="Удаляемая вручную")
    number = article.pk
    with django_capture_on_commit_callbacks(execute=True):
        articles.purge(article, manager.user, by_term=False)
    assert not model("knowledge.Article").objects.filter(pk=number).exists()
    event = _one("knowledge.article_purged", number)
    assert event.actor == manager.user and event.object_type == "knowledge.article"
    assert set(event.before) == {"number", "title", "by_term"}
    assert int(event.before["number"]) == number and event.before["title"] == "Удаляемая вручную"
    assert event.before["by_term"] is False
    assert event.after == {}


def test_purge_by_term_writes_article_purged_with_empty_actor_and_by_term_true(
        django_capture_on_commit_callbacks):
    """FR-438: удаление по сроку (ночная очистка) — запись `knowledge.article_purged` без исполнителя (система),
    `before.by_term` ровно `True`; свежая статья в корзине не удаляется и записи не получает."""
    article = kb.make_trashed(title="Просрочена по сроку")
    fresh = kb.make_trashed(title="Ещё в сроке")
    number = article.pk
    model("knowledge.Article").objects.filter(pk=number).update(deleted_at=timezone.now() - timedelta(days=100))
    with django_capture_on_commit_callbacks(execute=True):
        kb.run_purge()
    assert not model("knowledge.Article").objects.filter(pk=number).exists()
    event = _one("knowledge.article_purged", number)
    assert event.actor is None and event.object_type == "knowledge.article"
    assert set(event.before) == {"number", "title", "by_term"}
    assert int(event.before["number"]) == number and event.before["title"] == "Просрочена по сроку"
    assert event.before["by_term"] is True
    assert event.after == {}
    assert _events("knowledge.article_purged", fresh.pk) == []


def test_deleting_version_writes_version_deleted_with_version_number():
    """FR-438: удаление версии — запись `knowledge.version_deleted` над статьёй: управляющий, в `before` номер,
    заголовок и номер удалённой версии, `after` пуст; текста версии в записи нет."""
    from apps.knowledge.services import versions

    manager = kb.as_manager()
    article = kb.make_published(title="Статья с версиями", text="первая версия " + TEXT_MARK)
    kb.add_version(article, text="вторая версия")
    kb.add_version(article, text="третья версия")
    versions.delete(manager.user, article.pk, 2)
    event = _one("knowledge.version_deleted", article.pk)
    assert event.actor == manager.user and event.object_type == "knowledge.article"
    assert set(event.before) == {"number", "title", "version"}
    assert int(event.before["number"]) == article.pk and event.before["title"] == "Статья с версиями"
    assert event.before["version"] == 2
    assert event.after == {}
    assert TEXT_MARK not in json.dumps([event.before, event.after], ensure_ascii=False)


def test_deleting_foreign_comment_writes_comment_deleted_without_comment_text():
    """FR-438: удаление чужого комментария управляющим — запись `knowledge.comment_deleted` с номером и заголовком
    статьи и без текста комментария; удаление своего комментария записи не даёт."""
    from apps.knowledge.services import articles

    manager = kb.as_manager()
    article = kb.make_published(title="Статья с комментариями")
    foreign = kb.make_comment(article, kb.as_reader().user, COMMENT_MARK)
    own = kb.make_comment(article, manager.user, COMMENT_MARK + " свой")
    articles.delete_comment(manager.user, foreign.pk)
    event = _one("knowledge.comment_deleted", article.pk)
    assert event.actor == manager.user and event.object_type == "knowledge.article"
    assert set(event.before) == {"number", "title"}
    assert int(event.before["number"]) == article.pk and event.before["title"] == "Статья с комментариями"
    assert event.after == {}
    assert COMMENT_MARK not in json.dumps([event.before, event.after], ensure_ascii=False)
    articles.delete_comment(manager.user, own.pk)
    assert len(_events("knowledge.comment_deleted", article.pk)) == 1


# --- рубрики и срок корзины -------------------------------------------------------------------------------

def test_rubric_create_rename_move_delete_write_four_distinct_actions():
    """FR-438: четыре действия над рубрикой дают четыре разные записи (`rubric_created`, `rubric_renamed`,
    `rubric_moved`, `rubric_deleted`) с типом `knowledge.rubric`, номером рубрики, названием и путём «было / стало»."""
    from apps.knowledge.services import rubrics

    manager = kb.as_manager()
    general = kb.general_rubric()
    parent = rubrics.create(manager.user, "Почта", None)
    rubric = rubrics.create(manager.user, "Сети", general.pk)
    created = _one("knowledge.rubric_created", rubric.pk)
    assert created.actor == manager.user and created.object_type == "knowledge.rubric"
    assert created.before == {} and created.after == {"name": "Сети", "path": f"{general.name} / Сети"}

    rubrics.rename(manager.user, rubric.pk, "Сети и связь")
    renamed = _one("knowledge.rubric_renamed", rubric.pk)
    assert renamed.actor == manager.user and renamed.object_type == "knowledge.rubric"
    assert renamed.before == {"name": "Сети", "path": f"{general.name} / Сети"}
    assert renamed.after == {"name": "Сети и связь", "path": f"{general.name} / Сети и связь"}

    rubrics.move(manager.user, rubric.pk, parent.pk)
    moved = _one("knowledge.rubric_moved", rubric.pk)
    assert moved.actor == manager.user and moved.object_type == "knowledge.rubric"
    assert moved.before == {"name": "Сети и связь", "path": f"{general.name} / Сети и связь"}
    assert moved.after == {"name": "Сети и связь", "path": "Почта / Сети и связь"}

    rubrics.delete(manager.user, rubric.pk)
    deleted = _one("knowledge.rubric_deleted", rubric.pk)
    assert deleted.actor == manager.user and deleted.object_type == "knowledge.rubric"
    assert deleted.before == {"name": "Сети и связь", "path": "Почта / Сети и связь"} and deleted.after == {}
    assert len({created.pk, renamed.pk, moved.pk, deleted.pk}) == 4


def test_trash_days_change_writes_was_and_became_days_in_before_and_after():
    """FR-438: смена срока корзины — запись `knowledge.trash_days_changed` с видом объекта `knowledge.article` и
    пустым `object_id`: `before.days` — прежний срок (90), `after.days` — новый; исполнитель — управляющий."""
    from apps.knowledge.services import settings as kb_settings

    manager = kb.as_manager()
    kb_settings.update(manager.user, 30)
    event = _one("knowledge.trash_days_changed")
    assert event.actor == manager.user
    assert event.object_type == "knowledge.article" and event.object_id == ""
    assert event.before == {"days": 90} and event.after == {"days": 30}
    assert isinstance(event.before["days"], int) and isinstance(event.after["days"], int)


# --- состав записей ---------------------------------------------------------------------------------------

def test_audit_before_after_use_only_number_title_version_name_path_days_and_by_term_keys():
    """FR-438, NFR-407: после всех двенадцати действий в записях среза нет ключей, кроме `number`, `title`, `version`,
    `name`, `path`, `days`, `by_term`; набор ключей каждого действия — как в таблице раздела 8.1 контракта;
    значения ключей ядром не скрыты."""
    _everything()
    events = _all_kb_events()
    assert {event.action for event in events} == set(CODES), "не все двенадцать действий записаны"
    seen: set = set()
    for event in events:
        for side in (event.before, event.after):
            seen |= set(side)
        before_fields, after_fields = FIELDS_BY_ACTION[event.action]
        assert set(event.before) == set(before_fields), (event.action, event.before)
        assert set(event.after) == set(after_fields), (event.action, event.after)
        for value in list(event.before.values()) + list(event.after.values()):
            assert value != "***", event.action
    assert seen <= ALLOWED_FIELDS and seen, seen


def test_audit_labels_cover_all_actions_object_types_and_fields():
    """FR-438: точка `audit_labels` среза даёт русские подписи двенадцати действий, двух видов объекта и семи полей
    (`number` и `name` — те же, что у сервис-деска), словарь значений пуст; общий словарь ядра их видит."""
    from apps.core.services import audit_labels as core_labels
    from apps.core.services import audit_search
    from apps.knowledge import audit_labels as own

    data = own.audit_labels()
    assert set(data) == {"actions", "fields", "object_types", "values"}
    assert data["actions"] == ACTION_TITLES
    assert data["object_types"] == OBJECT_TITLES
    assert {name: data["fields"].get(name) for name in FIELD_TITLES} == FIELD_TITLES
    assert data["values"] == {}
    cyrillic = re.compile("[а-яА-ЯёЁ]")
    for title in list(data["actions"].values()) + list(data["fields"].values()) + list(data["object_types"].values()):
        assert cyrillic.search(title), title
    titles = dict(audit_search.known_actions())
    for action, title in ACTION_TITLES.items():
        assert titles.get(action) == title, action
    for kind, title in OBJECT_TITLES.items():
        assert core_labels.object_title(kind) == title, kind
    for name, title in FIELD_TITLES.items():
        assert core_labels.label(name) == title, name
    for field in ALLOWED_FIELDS:
        assert core_labels.label(field) in FIELD_TITLES.values(), field


def test_audit_records_have_no_article_text_comment_text_or_attachment_names():
    """FR-438: в записях журнала нет текста статьи, текста комментария, пометки к правке и имён вложений —
    только номер и заголовок; в записи нет и ключей `text`, `comment`, `file`, `html`."""
    _everything()
    events = _all_kb_events()
    assert len(events) >= len(CODES)
    dump = json.dumps([[event.object_type, event.object_id, event.before, event.after] for event in events],
                      ensure_ascii=False)
    for marker in (TEXT_MARK, COMMENT_MARK, FILE_MARK, VERSION_NOTE_MARK):
        assert marker not in dump, marker
    for event in events:
        for side in (event.before, event.after):
            assert not set(side) & {"text", "comment", "file", "files", "html", "plain", "tags", "author"}, event.action


def test_text_edit_subscription_ticket_link_and_search_write_no_audit():
    """FR-438: правка текста опубликованной статьи, подписка на рубрику, привязка и отвязка заявки, комментарий и
    поисковый запрос не добавляют записей `knowledge.*` в журнал."""
    from apps.knowledge.services import articles, links, subscriptions

    editor, reader = kb.as_editor(), kb.as_reader()
    article = kb.make_published(title="Статья без записей журнала", author=editor.user)
    queue = sd.make_queue()
    org.make_member(editor.user, queue.unit)
    ticket = sd.make_ticket(queue=queue)
    before = [event.pk for event in _all_kb_events()]

    result = articles.save(editor.user, article.pk, 1, _form(title=article.title, text="Новый текст статьи"))
    assert result.kind == "saved" and result.article.version_no == 2, "правка должна сохраниться как версия 2"
    assert subscriptions.toggle(reader.user, article.rubric_id) is True
    assert subscriptions.toggle(reader.user, article.rubric_id) is False
    link = links.link(editor.user, article.pk, ticket.number)
    links.unlink(editor.user, link.pk)
    articles.add_comment(reader.user, article.pk, "Комментарий читателя")
    assert reader.client.get("/search/", {"q": "статья"}).status_code == 200
    assert reader.client.get("/search/popup/", {"q": "статья"}).status_code == 200

    assert [event.pk for event in _all_kb_events()] == before


def test_audit_is_append_only_and_no_cron_job_cleans_it(django_capture_on_commit_callbacks):
    """NFR-407, FR-438: записи среза не правятся и не удаляются (у роли приложения нет UPDATE, DELETE, TRUNCATE);
    ночная очистка корзины не трогает журнал; в расписании `config/cron.py` нет задания, чистящего журнал; код
    `knowledge` не правит и не удаляет `AuditEvent`."""
    Event = model("core.AuditEvent")
    _everything()
    ids = sorted(event.pk for event in _all_kb_events())
    assert ids
    columns = ("id", "action", "object_type", "object_id", "before", "after", "actor_id")
    snapshot = list(Event.objects.filter(id__in=ids).order_by("id").values_list(*columns))
    codes = list(CODES)

    with connection.cursor() as cur:
        cur.execute("SELECT has_table_privilege('crm_app', 'core_auditevent', 'UPDATE'), "
                    "has_table_privilege('crm_app', 'core_auditevent', 'DELETE'), "
                    "has_table_privilege('crm_app', 'core_auditevent', 'TRUNCATE')")
        assert cur.fetchone() == (False, False, False)
    with pytest.raises(ProgrammingError), transaction.atomic():
        Event.objects.filter(action__in=codes).update(action="tampered")
    with pytest.raises(ProgrammingError), transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("DELETE FROM core_auditevent WHERE action = ANY(%s)", [codes])
    with django_capture_on_commit_callbacks(execute=True):
        kb.run_purge()
    assert list(Event.objects.filter(id__in=ids).order_by("id").values_list(*columns)) == snapshot

    cron = ast.parse((support.BACKEND_DIR / "config" / "cron.py").read_text(encoding="utf-8"))
    registered = []
    for node in ast.walk(cron):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "register":
            names = [kw.value.value for kw in node.keywords if kw.arg == "name" and isinstance(kw.value, ast.Constant)]
            registered += names + [a.id for a in node.args if isinstance(a, ast.Name)]
    assert registered, "в расписании нет ни одного задания"
    assert not [name for name in registered if "audit" in name.lower()], registered

    sources = [p for p in Path(support.BACKEND_DIR / "apps" / "knowledge").rglob("*.py") if "migrations" not in p.parts]
    assert sources, "нет кода apps/knowledge"
    for path in sources:
        for line in path.read_text(encoding="utf-8").splitlines():
            assert not (re.search(r"auditevent", line, re.I)
                        and re.search(r"\.delete\(|_raw_delete|truncate|\.update\(", line, re.I)), (
                f"{path}: правка журнала: {line.strip()}")
