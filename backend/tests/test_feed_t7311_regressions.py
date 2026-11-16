"""T-7311 (партия 1): regression-тесты запасных ходов нагрузки T-7304 (решение владельца 2026-11-15).

План «Риски» (specs/007-feed/plan.md, строки про время ответа публикации и число «Ленты») прямо
предусматривает эти ходы при p95 публикации выше 500 мс:
A — рассылка `live.publish_event` уходит заданием очереди `notify` после фиксации: публикация/
    комментарий/отметка отвечают без фан-аута, его выполняет worker-notify; порядок и семантика
    личных групп сохранены; сбой постановки не ломает действие (предупреждение в журнал);
C — число «Ленты» (`unread.count`) кэшируется на 5 с на пути оболочки/меню и сбрасывается при показе.

Действия — обычные запросы по путям плана; рассылка после фиксации выполняется `run_jobs("notify")`
(как в обновлённых `test_feed_live*`). Код среза на уровне модуля не импортируется, кроме служб,
которые проверяются напрямую (`unread`, `live`).
"""
import logging
from datetime import timedelta

import django_rq
import pytest
from django.utils import timezone

from tests import support
from tests import support_feed as ff
from tests.support import HX
from tests.support_notify import run_jobs

pytestmark = pytest.mark.django_db

PUBLISH_JOB = "apps.feed.tasks.publish_event"


def _writer(name="Автор Авторов"):
    return ff.as_writer(full_name=name)


def _plain(name="Читатель Читателев"):
    return ff.as_plain(full_name=name)


def _publish_jobs():
    """Задания фан-аута ленты в очереди `notify`."""
    return [job for job in django_rq.get_queue("notify").jobs if job.func_name == PUBLISH_JOB]


# --- A: рассылка уходит заданием очереди notify, не инлайн ----------------------------------------------------

def test_publish_enqueues_notify_job_and_does_not_fan_out_inline(django_capture_on_commit_callbacks):
    """A: публикация отвечает без фан-аута — задание стоит в очереди `notify`, сообщений слоя ещё нет;
    фан-аут выполняет worker (`run_jobs`), кадр уходит в личную группу адресата."""
    author, reader = _writer(), _plain("Адресат Адресатов")
    with ff.layer_spy(passthrough=False) as spy:
        with django_capture_on_commit_callbacks(execute=True):
            response = author.client.post("/feed/posts/",
                                          {"kind": "post", "text": "Запись", "to": [f"p{reader.user.pk}"]}, **HX)
            assert response.status_code == 200
        feed_events = [m for _, m in spy.calls if isinstance(m, dict) and m.get("type") == "feed.event"]
        assert feed_events == [], "фан-аут ленты не должен выполняться инлайн в запросе"
        assert _publish_jobs(), "рассылка поставлена заданием очереди notify"
        run_jobs("notify")
    post = support.model("feed.Post").objects.get(author=author.user)
    groups = {group for group in spy.by_group if group.startswith("feed.u.")}
    assert groups == {f"feed.u.{author.user.pk}", f"feed.u.{reader.user.pk}"}
    message = spy.by_group[f"feed.u.{reader.user.pk}"][0]
    assert (message["type"], message["post"], message["action"]) == ("feed.event", post.pk, "new")


def test_comment_and_like_also_enqueue_notify_jobs(django_capture_on_commit_callbacks):
    """A: комментарий и отметка «Нравится» тоже уходят заданием очереди, а не инлайн."""
    author, reader = _writer(), _plain("Комментатор Ку")
    post = ff.make_post(author.user, to=[reader.user])
    with django_capture_on_commit_callbacks(execute=True):
        assert reader.client.post(f"/feed/{post.pk}/comments/", {"text": "Живой"}, **HX).status_code == 200
    assert _publish_jobs(), "комментарий поставил задание рассылки"
    run_jobs("notify")
    with django_capture_on_commit_callbacks(execute=True):
        assert reader.client.post(f"/feed/{post.pk}/like/", **HX).status_code == 200
    assert _publish_jobs(), "отметка поставила задание рассылки"


def test_enqueue_failure_keeps_action_and_logs_warning(django_capture_on_commit_callbacks, caplog, monkeypatch):
    """A: сбой постановки (Valkey недоступен) не ломает действие — запись сохранена, ответ успешен,
    в журнале `apps.feed.services.live` предупреждение."""
    author, reader = _writer(), _plain("Адресат Адресатов")

    def broken(*args, **kwargs):
        raise ConnectionError("valkey недоступен (подмена теста)")

    monkeypatch.setattr("apps.feed.services.live.django_rq.get_queue", broken)
    with caplog.at_level(logging.WARNING):
        with django_capture_on_commit_callbacks(execute=True):
            response = author.client.post("/feed/posts/",
                                          {"kind": "post", "text": "Запись при сбое очереди",
                                           "to": [f"p{reader.user.pk}"]}, **HX)
    assert response.status_code == 200
    assert support.model("feed.Post").objects.filter(author=author.user, text="Запись при сбое очереди").exists()
    warnings = [r for r in caplog.records
                if r.name == "apps.feed.services.live" and r.levelno == logging.WARNING]
    assert warnings, "сбой постановки не записан в журнал"


def test_two_actions_keep_event_order_in_the_queue(django_capture_on_commit_callbacks):
    """A: два действия подряд — задания выполняются по порядку, кадры приходят в порядке действий."""
    author, reader = _writer(), _plain("Зритель Узлов")
    post = ff.make_post(author.user, to=[reader.user])
    with ff.layer_spy(passthrough=False) as spy:
        with django_capture_on_commit_callbacks(execute=True):
            author.client.post(f"/feed/{post.pk}/comments/", {"text": "Первый"}, **HX)
        with django_capture_on_commit_callbacks(execute=True):
            author.client.post(f"/feed/{post.pk}/comments/", {"text": "Второй"}, **HX)
        run_jobs("notify")
    comments = [m for m in spy.by_group.get(f"feed.u.{reader.user.pk}", []) if m.get("action") == "comment"]
    assert len(comments) == 2, "оба комментария разосланы"


# --- C: кэш числа «Ленты» на 5 с ------------------------------------------------------------------------------

def test_unread_count_cache_dedupes_repeated_reads_and_resets_on_shown():
    """C: повторное чтение числа в пределах TTL не идёт в SQL; показ записи сбрасывает кэш."""
    from apps.feed.services import unread

    author = support.make_employee()
    viewer = support.make_employee()
    posts = [ff.make_post(author, to=("all",), published_at=timezone.now() - timedelta(minutes=i + 1))
             for i in range(3)]

    def selects(pairs):
        return [sql for sql, _ in pairs if "feed_post" in sql and sql.lstrip().upper().startswith("SELECT")]

    with ff.queries_with_params() as first:
        assert unread.count(viewer, use_cache=True) == 3
    with ff.queries_with_params() as second:
        assert unread.count(viewer, use_cache=True) == 3
    assert selects(first), "первое чтение считает число в SQL"
    assert not selects(second), "второе чтение в пределах TTL берётся из кэша"

    unread.mark_shown(viewer, [posts[0].pk])
    with ff.queries_with_params() as third:
        assert unread.count(viewer, use_cache=True) == 2
    assert selects(third), "после показа кэш сброшен и число пересчитано"
