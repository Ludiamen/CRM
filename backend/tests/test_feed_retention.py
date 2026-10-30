"""T-7115: ночное задание срока хранения (FR-621, FR-626, FR-632, FR-633, FR-638, FR-639, NFR-610). Сценарий 12 спеки
среза 007.

Задание выполняется синхронно: `support_feed.run_retention(now)` и службы `apps.feed.services.retention`
(CONTRACT-007, 5.5, 5.8). «Сейчас» задаётся аргументом `now` (решения 5 и 59 задач): все даты данных считаются от
константы `NOW`, а не от часов машины. Диск и эскизы стираются после фиксации — проверка через
`django_capture_on_commit_callbacks` (решение 6, п. г). Пачки — оба признака решения 9: шпион `purge_batch` и три
выборки с `LIMIT 1000` в `capture_sql`. Журнал — `core.AuditEvent` (раздел 8.1). Код среза импортируется внутри
функций.
"""
import json
import pathlib
import re
from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from django.conf import settings as django_settings

from tests import support
from tests import support_feed as fd
from tests.support import model

pytestmark = pytest.mark.django_db

NOW = datetime(2026, 10, 30, 12, 0, tzinfo=dt_timezone.utc)
BOUNDARY = datetime(2023, 10, 30, 12, 0, tzinfo=dt_timezone.utc)   # NOW - 3 года (срок по умолчанию)
OLD = BOUNDARY - timedelta(days=1)
YOUNG = BOUNDARY + timedelta(days=1)
DAY = timedelta(days=1)
ACTION = "feed.retention_purged"


def journal():
    return list(model("core.AuditEvent").objects.filter(action=ACTION).order_by("pk"))


def set_years(years: int) -> None:
    model("feed.FeedSettings").objects.update_or_create(pk=1, defaults={"retention_years": years})


def exists(label: str, **filters) -> bool:
    return model(label).objects.filter(**filters).exists()


def stored_paths(feed_file) -> list[pathlib.Path]:
    """Путь оригинала (по состоянию) и эскиза файла ленты на диске."""
    from apps.core.services import files

    paths = [pathlib.Path(files.attachment_path(feed_file.file))]
    if feed_file.thumb:
        paths.append(pathlib.Path(django_settings.PROTECTED_ROOT) / feed_file.thumb)
    return paths


def purge_spy(monkeypatch) -> list:
    from apps.feed.services import retention

    real, calls = retention.purge_batch, []

    def spy(*args, **kwargs):
        ids = args[0] if args else kwargs["ids"]
        calls.append(len(list(ids)))
        return real(*args, **kwargs)

    monkeypatch.setattr(retention, "purge_batch", spy)
    return calls


# --- граница срока ------------------------------------------------------------------------------------

def test_post_older_than_term_by_one_day_is_deleted_with_comments_likes_of_post_and_comments_read_marks_answers_shown_and_recipients():
    author, reader, other = support.make_employee(), support.make_employee(), support.make_employee()
    event = fd.make_event(author, start=OLD + DAY, to=[reader], published_at=OLD)
    important = fd.make_important(author, to=[reader], published_at=OLD)
    young = fd.make_post(author, to=[reader], published_at=YOUNG)
    comment = fd.comment(event, reader, created_at=OLD + timedelta(hours=1))
    young_comment = fd.comment(young, reader)
    fd.like(event, other)
    fd.like(comment, other)
    model("feed.EventAnswer").objects.create(post=event, user=reader, answer="go", answered_at=OLD)
    model("feed.ReadMark").objects.create(post=important, user=reader, read_at=OLD)
    model("feed.Shown").objects.create(user=reader, post=event, shown_at=OLD)
    gone = [event.pk, important.pk]
    assert fd.run_retention(NOW) == 2
    for label in ("feed.Post", "feed.PostLike", "feed.CommentLike", "feed.ReadMark", "feed.EventAnswer", "feed.Shown",
                  "feed.Recipient", "feed.FeedComment"):
        field = "pk" if label == "feed.Post" else "post_id"
        assert not model(label).objects.filter(**{f"{field}__in": gone}).exists(), label
    assert not exists("core.Comment", object_ref__in=[f"feed.post:{pk}" for pk in gone])
    assert not exists("core.Comment", pk=comment.pk)
    assert exists("feed.Post", pk=young.pk) and exists("core.Comment", pk=young_comment.pk)
    assert exists("feed.Recipient", post_id=young.pk)


def test_retention_deletes_post_and_comment_files_of_all_scan_states_with_stored_files_and_disk_and_thumbs_after_commit(
        protected_root, django_capture_on_commit_callbacks):
    author, reader = support.make_employee(), support.make_employee()
    post = fd.make_post(author, to=[reader], published_at=OLD)
    comment = fd.comment(post, reader, created_at=OLD)
    attached = [
        fd.attach(post, "чистый.png", status="clean", write=True, thumb=True),
        fd.attach(post, "проверяется.txt", status="pending", write=True),
        fd.attach(post, "карантин.txt", status="quarantine", write=True),
        fd.attach(comment, "комментарий.png", status="clean", write=True, thumb=True),
    ]
    paths = [path for feed_file in attached for path in stored_paths(feed_file)]
    stored_ids = [feed_file.file_id for feed_file in attached]
    assert len(paths) == 6 and all(path.exists() for path in paths)
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        assert fd.run_retention(NOW) == 1
    assert callbacks, "стирание диска должно стоять после фиксации"
    assert all(path.exists() for path in paths)   # до фиксации файлы на месте
    assert not model("feed.FeedFile").objects.filter(pk__in=[f.pk for f in attached]).exists()
    assert not model("core.StoredFile").objects.filter(pk__in=stored_ids).exists()
    for callback in callbacks:
        callback()
    assert not any(path.exists() for path in paths)


def test_post_one_day_younger_than_term_is_kept():
    author = support.make_employee()
    post = fd.make_post(author, to="all", published_at=YOUNG)
    assert fd.run_retention(NOW) == 0
    assert exists("feed.Post", pk=post.pk)


def test_term_boundary_replaces_year_and_february_29_becomes_february_28():
    from apps.feed.services import retention

    assert retention.boundary(NOW, 3) == BOUNDARY
    assert retention.boundary(NOW, 1) == datetime(2025, 10, 30, 12, 0, tzinfo=dt_timezone.utc)
    assert retention.boundary(NOW, 10) == datetime(2016, 10, 30, 12, 0, tzinfo=dt_timezone.utc)
    leap = datetime(2028, 2, 29, 10, 30, tzinfo=dt_timezone.utc)
    assert retention.boundary(leap, 1) == datetime(2027, 2, 28, 10, 30, tzinfo=dt_timezone.utc)
    assert retention.boundary(leap, 3) == datetime(2025, 2, 28, 10, 30, tzinfo=dt_timezone.utc)
    assert retention.boundary(leap, 4) == datetime(2024, 2, 29, 10, 30, tzinfo=dt_timezone.utc)


def test_retention_uses_years_from_feed_settings():
    author = support.make_employee()
    thirteen_months = fd.make_post(author, to="all", published_at=NOW - timedelta(days=396))
    eleven_months = fd.make_post(author, to="all", published_at=NOW - timedelta(days=335))
    four_years = fd.make_post(author, to="all", published_at=NOW - timedelta(days=4 * 365))
    set_years(5)
    assert fd.run_retention(NOW) == 0
    set_years(1)
    assert fd.run_retention(NOW) == 2
    assert exists("feed.Post", pk=eleven_months.pk)
    assert not exists("feed.Post", pk=thirteen_months.pk) and not exists("feed.Post", pk=four_years.pk)


def test_edit_and_new_comments_do_not_extend_post_term():
    author, reader = support.make_employee(), support.make_employee()
    post = fd.make_post(author, to=[reader], published_at=OLD, edited_at=NOW - DAY)
    fd.comment(post, reader, created_at=NOW - timedelta(hours=1))
    assert fd.run_retention(NOW) == 1
    assert not exists("feed.Post", pk=post.pk)
    assert not exists("core.Comment", object_ref=f"feed.post:{post.pk}")


def test_posts_of_fired_employees_are_deleted_by_same_term():
    fired = support.make_employee()
    old = fd.make_post(fired, to="all", published_at=OLD)
    young = fd.make_post(fired, to="all", published_at=YOUNG)
    model("core.User").objects.filter(pk=fired.pk).update(state="dismissed")
    assert fd.run_retention(NOW) == 1
    assert not exists("feed.Post", pk=old.pk) and exists("feed.Post", pk=young.pk)


# --- журнал -------------------------------------------------------------------------------------------

def test_retention_writes_one_journal_record_retention_purged_with_posts_count_and_no_text():
    author = support.make_employee()
    for index in range(3):
        fd.make_post(author, to="all", text=f"Служебный текст записи {index}", published_at=OLD - timedelta(hours=index))
    fd.make_post(author, to="all", published_at=YOUNG)
    assert fd.run_retention(NOW) == 3
    rows = journal()
    assert len(rows) == 1
    row = rows[0]
    assert (row.object_type, row.object_id, row.actor_id) == ("feed.settings", "1", None)
    assert row.after == {"posts": 3} and not row.before
    assert "Служебный текст" not in json.dumps([row.before, row.after], ensure_ascii=False)


def test_retention_without_old_posts_writes_no_journal_record():
    author = support.make_employee()
    fd.make_post(author, to="all", published_at=YOUNG)
    assert fd.run_retention(NOW) == 0
    assert journal() == []


def test_repeated_retention_run_deletes_nothing_writes_no_journal_and_raises_no_error():
    author = support.make_employee()
    fd.make_post(author, to="all", published_at=OLD)
    fd.make_post(author, to="all", published_at=OLD - DAY)
    survivor = fd.make_post(author, to="all", published_at=YOUNG)
    assert fd.run_retention(NOW) == 2
    assert fd.run_retention(NOW) == 0
    assert len(journal()) == 1 and journal()[0].after == {"posts": 2}
    assert exists("feed.Post", pk=survivor.pk) and model("feed.Post").objects.count() == 1


# --- пачки и гонки ------------------------------------------------------------------------------------

def test_2500_old_posts_are_deleted_in_three_batches_of_1000_by_batch_spy_and_limit_1000_selects_and_journal_posts_is_2500(
        monkeypatch):
    author = support.make_employee()
    Post = model("feed.Post")
    Post.objects.bulk_create([
        Post(author=author, kind="post", text="", to_all=True, published_at=OLD - timedelta(seconds=index))
        for index in range(2500)])
    survivor = fd.make_post(author, to="all", published_at=YOUNG)
    calls = purge_spy(monkeypatch)
    with fd.capture_sql() as sqls:
        assert fd.run_retention(NOW) == 2500
    assert calls == [1000, 1000, 500]
    selects = [sql for sql in sqls if sql.lstrip().upper().startswith("SELECT") and "feed_post" in sql
               and re.search(r"\bLIMIT 1000\b", sql)]
    assert len(selects) == 3
    assert [row.after for row in journal()] == [{"posts": 2500}]
    assert list(Post.objects.values_list("pk", flat=True)) == [survivor.pk]


def test_post_deleted_between_batch_selection_and_delete_is_skipped_without_error_and_not_counted_in_journal_posts(
        monkeypatch):
    author = support.make_employee()
    posts = [fd.make_post(author, to="all", published_at=OLD - timedelta(hours=index)) for index in range(3)]
    Post = model("feed.Post")
    done = []

    def delete_first(ids):
        if ids and not done:
            done.append(ids[0])
            Post.objects.filter(pk=ids[0]).delete()

    issued = fd.act_between_select_and_lock(monkeypatch, "retention", delete_first)
    assert fd.run_retention(NOW) == 2
    assert issued and sorted(issued[0]) == sorted(post.pk for post in posts)
    assert len(done) == 1 and Post.objects.count() == 0
    assert [row.after for row in journal()] == [{"posts": 2}]


# --- показы и непривязанные файлы ---------------------------------------------------------------------

def test_shown_rows_of_posts_published_over_31_days_ago_are_deleted_and_younger_kept_by_post_published_at():
    author, reader = support.make_employee(), support.make_employee()
    old_post = fd.make_post(author, to=[reader], published_at=NOW - timedelta(days=31, hours=1))
    young_post = fd.make_post(author, to=[reader], published_at=NOW - timedelta(days=30))
    Shown = model("feed.Shown")
    Shown.objects.create(user=reader, post=old_post, shown_at=NOW)            # показ свежий, запись старая
    Shown.objects.create(user=reader, post=young_post, shown_at=NOW - timedelta(days=60))   # показ старый, запись нет
    assert fd.run_retention(NOW) == 0   # записи в пределах срока хранения
    assert not Shown.objects.filter(post=old_post).exists()
    assert Shown.objects.filter(post=young_post).exists()
    assert exists("feed.Post", pk=old_post.pk) and exists("feed.Post", pk=young_post.pk)


def test_unattached_feed_files_older_than_24_hours_are_deleted_with_stored_file_and_disk_and_younger_kept(
        protected_root, django_capture_on_commit_callbacks):
    author, uploader = support.make_employee(), support.make_employee()
    kept_post = fd.make_post(author, to="all", published_at=YOUNG)
    FeedFile = model("feed.FeedFile")
    stale_clean = fd.attach(None, "старый.png", status="clean", uploaded_by=uploader, write=True)
    stale_pending = fd.attach(None, "старый-проверяется.txt", status="pending", uploaded_by=uploader, write=True)
    fresh = fd.attach(None, "свежий.png", status="clean", uploaded_by=uploader, write=True)
    bound = fd.attach(kept_post, "привязанный.png", status="clean", write=True)
    FeedFile.objects.filter(pk__in=[stale_clean.pk, stale_pending.pk]).update(uploaded_at=NOW - timedelta(hours=25))
    FeedFile.objects.filter(pk=fresh.pk).update(uploaded_at=NOW - timedelta(hours=23))
    FeedFile.objects.filter(pk=bound.pk).update(uploaded_at=NOW - timedelta(hours=48))
    stale_paths = [path for item in (stale_clean, stale_pending) for path in stored_paths(item)]
    kept_paths = [path for item in (fresh, bound) for path in stored_paths(item)]
    with django_capture_on_commit_callbacks(execute=True):
        assert fd.run_retention(NOW) == 0
    assert not FeedFile.objects.filter(pk__in=[stale_clean.pk, stale_pending.pk]).exists()
    assert not model("core.StoredFile").objects.filter(pk__in=[stale_clean.file_id, stale_pending.file_id]).exists()
    assert not any(path.exists() for path in stale_paths)
    assert FeedFile.objects.filter(pk__in=[fresh.pk, bound.pk]).count() == 2
    assert all(path.exists() for path in kept_paths)
    assert journal() == []   # чистка непривязанных в число удалённых записей не входит


def test_portal_notification_of_post_deleted_by_term_remains_and_its_link_is_404():
    author = support.make_employee()
    reader = fd.as_plain()
    post = fd.make_post(author, to=[reader.user], published_at=OLD)
    note = model("notify.Notification").objects.create(
        user=reader.user, kind="feed.for_you", text="Запись для вас", url=f"/feed/{post.pk}/",
        object_ref=f"feed.post:{post.pk}")
    assert reader.client.get(f"/feed/{post.pk}/").status_code == 200
    assert fd.run_retention(NOW) == 1
    assert model("notify.Notification").objects.filter(pk=note.pk, read_at__isnull=True).exists()
    assert reader.client.get(note.url).status_code == 404


# --- без VACUUM и порядок шагов -----------------------------------------------------------------------

def test_retention_job_runs_no_vacuum():
    author, reader = support.make_employee(), support.make_employee()
    fd.make_post(author, to=[reader], published_at=OLD)
    with fd.capture_sql() as sqls:
        fd.run_retention(NOW)
    assert sqls and not [sql for sql in sqls if "VACUUM" in sql.upper()]


def test_retention_steps_run_in_order_shown_cleanup_then_post_batches_then_unattached_files_by_sql_order(
        protected_root):
    author, reader, uploader = support.make_employee(), support.make_employee(), support.make_employee()
    shown_post = fd.make_post(author, to=[reader], published_at=NOW - timedelta(days=40))
    model("feed.Shown").objects.create(user=reader, post=shown_post, shown_at=NOW - timedelta(days=39))
    fd.make_post(author, to=[reader], published_at=OLD)
    stale = fd.attach(None, "старый.png", status="clean", uploaded_by=uploader, write=True)
    model("feed.FeedFile").objects.filter(pk=stale.pk).update(uploaded_at=NOW - timedelta(hours=30))
    with fd.capture_sql() as sqls:
        fd.run_retention(NOW)

    def first(predicate):
        for index, sql in enumerate(sqls):
            if predicate(sql):
                return index
        raise AssertionError("нужный запрос шага не найден")

    shown = first(lambda sql: re.search(r'DELETE\s+FROM\s+"?feed_shown"?', sql, re.I) is not None)
    batch = first(lambda sql: sql.lstrip().upper().startswith("SELECT") and "feed_post" in sql
                  and re.search(r"\bLIMIT 1000\b", sql) is not None)
    unattached = first(lambda sql: "feed_feedfile" in sql and re.search(r'post_id"?\s+IS NULL', sql) is not None)
    assert shown < batch < unattached
