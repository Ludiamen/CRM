"""T-7311 (партия 1): изолированные unit-тесты запасных ходов нагрузки T-7304.

Проверяют без базы и стенда (моки вместо SQL/очереди/слоя):
A — рассылка `live.publish_event` уходит заданием очереди `notify` (`enqueue_publish`), сбой постановки
    не ломает действие (предупреждение в журнал);
B — `publish_event` не дублирует снятие получателей и прав (`_recipient_users`/`_moderators_and_staff`
    по одному разу), права читаются одним `permissions_of` на получателя;
C — кэш числа «Ленты» на 5 с (`unread.count(use_cache=True)`) с инвалидацией (`invalidate_counts`,
    `mark_shown`); прямой вызов и вызов с явным `now` не кэшируются.

Интеграционное поведение (кадры через очередь, порядок, личные группы) проверяют серверные тесты
`test_feed_live*`, `test_feed_consumers*` (обновлены: фан-аут выполняется `run_jobs("notify")`).
"""
import logging
from unittest import mock

import pytest
from django.test import override_settings

from apps.feed.services import live, unread


@pytest.fixture(autouse=True)
def valkey_clean():
    """Переопределяем autouse-фикстуру conftest: изолированные тесты не трогают Valkey/БД."""
    yield None


LOC_MEM = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache", "LOCATION": "t7311"}}


# --- A: рассылка заданием очереди notify ----------------------------------------------------------------------

def test_enqueue_publish_puts_publish_event_job_on_notify_queue():
    """A: `enqueue_publish` ставит `tasks.publish_event` в очередь `notify` с аргументами действия."""
    from apps.feed import tasks

    queue = mock.MagicMock()
    with mock.patch.object(live.django_rq, "get_queue", return_value=queue) as get_queue:
        live.enqueue_publish(42, "comment", comment_id=7, owner_id=3)
    get_queue.assert_called_once_with("notify")
    queue.enqueue.assert_called_once()
    args, kwargs = queue.enqueue.call_args
    assert args[0] is tasks.publish_event
    assert args[1] == 42 and args[2] == "comment"
    assert kwargs["comment_id"] == 7 and kwargs["owner_id"] == 3
    assert kwargs["recipients"] is None


def test_enqueue_publish_serialises_recipients_as_sorted_list():
    """A: готовое множество получателей (удаление записи) уходит в задание отсортированным списком."""
    queue = mock.MagicMock()
    with mock.patch.object(live.django_rq, "get_queue", return_value=queue):
        live.enqueue_publish(9, "delete", recipients=frozenset({5, 1, 3}), owner_id=2)
    _args, kwargs = queue.enqueue.call_args
    assert kwargs["recipients"] == [1, 3, 5]


def test_enqueue_publish_swallows_queue_failure_with_warning(caplog):
    """A: сбой постановки (Valkey недоступен) не ломает действие — предупреждение в журнал, без исключения."""
    with mock.patch.object(live.django_rq, "get_queue", side_effect=ConnectionError("valkey down")):
        with caplog.at_level(logging.WARNING):
            live.enqueue_publish(1, "new")   # не raises
    warnings = [r for r in caplog.records
                if r.name == "apps.feed.services.live" and r.levelno == logging.WARNING]
    assert warnings, "сбой постановки не записан в журнал"


def test_publish_event_task_calls_live_publish_event_with_frozenset_recipients():
    """A: задание `tasks.publish_event` зовёт `live.publish_event`, восстанавливая множество получателей."""
    from apps.feed import tasks

    with mock.patch.object(live, "publish_event", return_value="ok") as publish:
        result = tasks.publish_event(11, "delete", comment_id=None, recipients=[4, 6], owner_id=2)
    assert result == "ok"
    publish.assert_called_once_with(11, "delete", comment_id=None,
                                    recipients=frozenset({4, 6}), owner_id=2)


# --- B: без дублей получателей и прав -------------------------------------------------------------------------

def test_publish_event_resolves_recipients_and_rights_once():
    """B: за одну рассылку `_recipient_users` и `_moderators_and_staff` зовутся по одному разу (без дублей)."""
    post = mock.MagicMock(pk=5, author_id=1, kind="post", text="", published_at=mock.MagicMock())
    audience = frozenset({1, 2})
    users = {1: object(), 2: object()}
    with mock.patch.object(live, "get_channel_layer", return_value=mock.MagicMock()), \
         mock.patch("apps.feed.models.Post.objects.get", return_value=post), \
         mock.patch.object(live.visibility, "audience", return_value=audience), \
         mock.patch.object(live, "_recipient_users", return_value=users) as rec, \
         mock.patch.object(live, "_moderators_and_staff",
                           return_value=(frozenset(), frozenset())) as mods, \
         mock.patch.object(live, "_render_variants", return_value={"reader:0": "x"}) as render, \
         mock.patch.object(live, "async_to_sync", lambda coro: (lambda *a, **k: None)), \
         mock.patch.object(live, "_push_counts"):
        live.publish_event(5, "post")
    assert rec.call_count == 1, "получатели снимаются один раз"
    assert mods.call_count == 1, "права/модераторы считаются один раз"
    # `users` и права передаются в рендер и в сообщение — повторно не запрашиваются
    assert render.call_count == 1


def test_moderators_and_staff_reads_permissions_once_per_user():
    """B: `_moderators_and_staff` читает права каждого получателя одним `permissions_of` (не двумя)."""
    from apps.core.services import permissions

    users = {
        1: mock.MagicMock(pk=1),   # модератор
        2: mock.MagicMock(pk=2),   # staff.view
        3: mock.MagicMock(pk=3),   # обычный читатель
    }
    grants = {
        1: frozenset({"feed.moderate"}),
        2: frozenset({"staff.view"}),
        3: frozenset(),
    }
    with mock.patch.object(permissions, "permissions_of", side_effect=lambda user: grants[user.pk]) as perms:
        moderators, staff = live._moderators_and_staff(users)
    assert perms.call_count == len(users), "по одному чтению прав на получателя"
    assert moderators == frozenset({1})
    assert staff == frozenset({2})


# --- C: кэш числа «Ленты» на 5 с ------------------------------------------------------------------------------

def _fake_cursor(value: int):
    """Подмена `connection.cursor()`: контекст-менеджер, `fetchone()` → `(value,)`.

    Возвращает `(фабрика, cursor, executed)`; `executed` — список SQL, переданных в `execute`
    (чтобы отличить SELECT числа от INSERT показа)."""
    cursor = mock.MagicMock()
    cursor.fetchone.return_value = (value,)
    executed: list[str] = []
    cursor.execute.side_effect = lambda sql, params=None: executed.append(str(sql))
    cm = mock.MagicMock()
    cm.__enter__.return_value = cursor
    factory = mock.MagicMock(return_value=cm)
    return factory, cursor, executed


def _count_queries(executed) -> int:
    return sum(1 for sql in executed if "SELECT count" in sql)


@override_settings(CACHES=LOC_MEM)
def test_count_with_cache_hits_sql_once_within_ttl():
    """C: `count(use_cache=True)` без явного `now` кэшируется — второй вызов не идёт в SQL."""
    from django.core.cache import cache

    cache.clear()
    user = mock.MagicMock(pk=7, state="active")
    factory, cursor, executed = _fake_cursor(3)
    with mock.patch.object(unread, "_unit_chain", return_value=frozenset()), \
         mock.patch.object(unread.connection, "cursor", factory):
        first = unread.count(user, use_cache=True)
        second = unread.count(user, use_cache=True)
    assert (first, second) == (3, 3)
    assert _count_queries(executed) == 1, "в пределах TTL число берётся из кэша"


@override_settings(CACHES=LOC_MEM)
def test_count_without_cache_flag_always_recomputes():
    """C: прямой вызов `count(user)` (без `use_cache`) не кэшируется — каждый раз SQL."""
    from django.core.cache import cache

    cache.clear()
    user = mock.MagicMock(pk=8, state="active")
    factory, cursor, executed = _fake_cursor(2)
    with mock.patch.object(unread, "_unit_chain", return_value=frozenset()), \
         mock.patch.object(unread.connection, "cursor", factory):
        unread.count(user)
        unread.count(user)
    assert _count_queries(executed) == 2, "служебный вызов не кэшируется"


@override_settings(CACHES=LOC_MEM)
def test_count_with_explicit_now_is_not_cached():
    """C: вызов с явным `now` (замеры, тесты с часами) не кэшируется даже с `use_cache=True`."""
    from django.core.cache import cache
    from django.utils import timezone

    cache.clear()
    user = mock.MagicMock(pk=9, state="active")
    factory, cursor, executed = _fake_cursor(4)
    with mock.patch.object(unread, "_unit_chain", return_value=frozenset()), \
         mock.patch.object(unread.connection, "cursor", factory):
        unread.count(user, now=timezone.now(), use_cache=True)
        unread.count(user, now=timezone.now(), use_cache=True)
    assert _count_queries(executed) == 2, "с явным now кэш не используется"


@override_settings(CACHES=LOC_MEM)
def test_invalidate_counts_forces_recompute_for_user():
    """C: `invalidate_counts([user])` сбрасывает кэш числа — следующий вызов снова идёт в SQL."""
    from django.core.cache import cache

    cache.clear()
    user = mock.MagicMock(pk=10, state="active")
    factory, cursor, executed = _fake_cursor(1)
    with mock.patch.object(unread, "_unit_chain", return_value=frozenset()), \
         mock.patch.object(unread.connection, "cursor", factory):
        unread.count(user, use_cache=True)
        unread.invalidate_counts([user.pk])
        unread.count(user, use_cache=True)
    assert _count_queries(executed) == 2, "после инвалидации число пересчитано"


@override_settings(CACHES=LOC_MEM)
def test_mark_shown_invalidates_count_cache_for_user():
    """C: показ записи (`mark_shown`) сбрасывает кэш числа сотрудника."""
    from django.core.cache import cache

    cache.clear()
    user = mock.MagicMock(pk=11, state="active")
    factory, cursor, executed = _fake_cursor(5)
    with mock.patch.object(unread, "_unit_chain", return_value=frozenset()), \
         mock.patch.object(unread.connection, "cursor", factory):
        unread.count(user, use_cache=True)
        unread.mark_shown(user, [1, 2, 3])
        unread.count(user, use_cache=True)
    assert _count_queries(executed) == 2, "после показа число пересчитано"
