"""T-7114: `remind_at` события и задание напоминаний (FR-606, FR-618, FR-619, NFR-610). Сценарий 3 спеки среза 007
(пп. 4, 5, 7, 8, 12, 13).

Задание выполняется синхронно: `support_feed.run_reminders(now)` (решение 5), публикация и правка — службами
`posts.publish` и `posts.edit` с параметром `now` (CONTRACT-007, 5.3). Время в SQL — параметром (решение 59),
поэтому «сейчас» задаётся и фикстурой `clock`, и аргументом. Подмены сбоев и гонок — раздел 5.8 контракта: создание
уведомления (`apps.notify.services.dispatch.create`), логгер `apps.feed.tasks`, `act_between_select_and_lock`.
Код среза импортируется внутри функций.
"""
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from tests import support
from tests import support_feed as fd
from tests.support import model

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
HOUR = timedelta(hours=1)
REMINDER = "feed.event_reminder"


# --- помощники только этого файла ---------------------------------------------------------------------

def stamp(moment: datetime) -> str:
    return moment.astimezone(MSK).strftime("%Y-%m-%dT%H:%M")


def minute(moment: datetime) -> datetime:
    return moment.replace(second=0, microsecond=0)


def event_data(start, end=None, **over) -> dict:
    data = {"kind": "event", "text": "Описание события", "event_title": "Переезд серверной",
            "event_place": "Корпус 2, ауд. 101", "event_start": stamp(start),
            "event_end": stamp(end or start + 2 * HOUR)}
    data.update(over)
    return data


def publish(author, start, participants=(), *, now, **over):
    from apps.feed.services import posts

    data = event_data(start, **over)
    data["to"] = [f"p{user.pk}" for user in participants]
    return posts.publish(author, data, now=now)


def edit(author, post, *, now, **over):
    """Правка службой: те же поля, что у публикации, адресаты — прежние (раздел 10.2 контракта)."""
    from apps.feed.services import posts

    saved = [f"u{r.unit_id}" if r.kind == "unit" else f"p{r.user_id}"
             for r in model("feed.Recipient").objects.filter(post=post, via="to").order_by("pk")]
    post.refresh_from_db()
    data = event_data(post.event_start, post.event_end, text=post.text, event_title=post.event_title,
                      event_place=post.event_place)
    data.update(over)
    data["to"] = saved
    posts.edit(author, post.pk, data, now=now)
    post.refresh_from_db()
    return post


def reminders_of(user, post=None):
    rows = model("notify.Notification").objects.filter(user=user, kind=REMINDER)
    return rows.filter(object_ref=f"feed.post:{post.pk}") if post else rows


def total_notifications() -> int:
    return model("notify.Notification").objects.count()


def failed_count(result) -> int:
    failed = result.failed
    return len(failed) if hasattr(failed, "__len__") else failed


def raw_event(author, start, remind_at, *, reminded_for_start=None, title="Событие"):
    return model("feed.Post").objects.create(
        author=author, kind="event", text="", published_at=timezone.now(), event_title=title, event_place="Место",
        event_start=start, event_end=start + HOUR, remind_at=remind_at, reminded_for_start=reminded_for_start)


def failing_create(monkeypatch, bad_ref: str) -> list:
    """`dispatch.create` падает для черновиков с `object_ref == bad_ref`, для прочих зовёт настоящую; возвращает
    список вызовов с этим `object_ref`."""
    from apps.notify.services import dispatch

    real, hits = dispatch.create, []

    def fake(kind_code, drafts):
        drafts = list(drafts)
        if any(draft.object_ref == bad_ref for draft in drafts):
            hits.append(bad_ref)
            raise RuntimeError("сбой уведомления (подмена теста)")
        return real(kind_code, drafts)

    monkeypatch.setattr(dispatch, "create", fake)
    return hits


# --- remind_at при публикации ---------------------------------------------------------------------------

def test_remind_at_on_publish_is_start_minus_hour_when_start_is_hour_or_more_ahead(clock):
    from apps.feed.services import events

    now = timezone.now()
    author, participant = support.make_employee(), support.make_employee()
    start = minute(now) + timedelta(days=1)
    post = publish(author, start, [participant], now=now)
    assert post.remind_at == start - HOUR and post.reminded_for_start is None
    two_hours = publish(author, minute(now) + 2 * HOUR, [participant], now=now)
    assert two_hours.remind_at == minute(now) + HOUR
    assert events.remind_at(now + HOUR, now) == now
    assert events.remind_at(now + 90 * timedelta(minutes=1), now) == now + timedelta(minutes=30)
    assert events.remind_at(now + HOUR - timedelta(seconds=1), now) is None


def test_event_published_30_minutes_before_start_has_no_remind_at_and_gets_no_reminder(clock):
    now = timezone.now()
    author, participant = support.make_employee(), support.make_employee()
    start = minute(now) + timedelta(minutes=30)
    post = publish(author, start, [participant], now=now)
    assert post.remind_at is None
    for moment in (now, start - timedelta(minutes=1), start + timedelta(minutes=1)):
        assert fd.run_reminders(moment).reminded == 0
    assert reminders_of(participant).count() == 0 and reminders_of(author).count() == 0


def test_event_next_day_gets_one_event_reminder_in_minute_of_remind_at_and_none_before(clock):
    now = timezone.now()
    author, participant = support.make_employee(), support.make_employee()
    post = fd.make_event(author, start=minute(now) + timedelta(days=1), to=[participant])
    due = post.remind_at
    assert due == post.event_start - HOUR
    assert fd.run_reminders(due - timedelta(minutes=1)).reminded == 0
    assert reminders_of(participant).count() == 0
    assert fd.run_reminders(due).reminded == 1
    note = reminders_of(participant, post).get()
    assert note.text == "Через час: «Событие», Корпус 1"
    assert (note.url, note.object_ref) == (f"/feed/{post.pk}/", f"feed.post:{post.pk}")
    fd.run_reminders(due + timedelta(minutes=1))
    assert reminders_of(participant).count() == 1


def test_reminder_goes_to_audience_minus_answered_no_plus_author_always(clock):
    now = timezone.now()
    author = support.make_employee()
    silent, going, declining = support.make_employee(), support.make_employee(), support.make_employee()
    post = fd.make_event(author, start=minute(now) + timedelta(days=1), to=[silent, going, declining])
    Answer = model("feed.EventAnswer")
    Answer.objects.create(post=post, user=going, answer="go", answered_at=now)
    Answer.objects.create(post=post, user=declining, answer="no", answered_at=now)
    fd.run_reminders(post.remind_at)
    assert reminders_of(silent, post).count() == 1
    assert reminders_of(going, post).count() == 1
    assert reminders_of(declining, post).count() == 0
    assert reminders_of(author, post).count() == 1   # автор получает напоминание всегда


def test_employee_not_seeing_event_gets_no_reminder(clock):
    now = timezone.now()
    author, participant, outsider = support.make_employee(), support.make_employee(), support.make_employee()
    post = fd.make_event(author, start=minute(now) + timedelta(days=1), to=[participant])
    fd.run_reminders(post.remind_at)
    assert reminders_of(participant, post).count() == 1
    assert reminders_of(outsider).count() == 0


# --- пересчёт remind_at при правке ----------------------------------------------------------------------

def test_start_moved_to_14_sets_remind_at_13_and_reminder_comes_at_13_not_9(clock):
    now = timezone.now()
    author, participant = support.make_employee(), support.make_employee()
    old_start = minute(now) + timedelta(days=1)
    post = fd.make_event(author, start=old_start, to=[participant])
    new_start = old_start + timedelta(hours=4)
    post = edit(author, post, now=now, event_start=stamp(new_start), event_end=stamp(new_start + 2 * HOUR))
    assert post.event_start == new_start and post.remind_at == new_start - HOUR
    assert fd.run_reminders(old_start - HOUR).reminded == 0   # прежний срок («в 9:00») напоминания не даёт
    assert reminders_of(participant).count() == 0
    assert fd.run_reminders(new_start - HOUR).reminded == 1   # новый срок («в 13:00»)
    assert reminders_of(participant, post).count() == 1


def test_reminded_event_moved_two_hours_later_gets_second_reminder_hour_before_new_start(clock):
    now = timezone.now()
    author, participant = support.make_employee(), support.make_employee()
    start = minute(now) + timedelta(days=1)
    post = fd.make_event(author, start=start, to=[participant])
    fd.run_reminders(start - HOUR)
    post.refresh_from_db()
    assert post.reminded_for_start == start and reminders_of(participant, post).count() == 1
    edit_at = start - HOUR + timedelta(minutes=1)
    clock.set(edit_at)
    new_start = start + 2 * HOUR
    post = edit(author, post, now=edit_at, event_start=stamp(new_start), event_end=stamp(new_start + 2 * HOUR))
    assert post.remind_at == new_start - HOUR
    assert fd.run_reminders(new_start - HOUR - timedelta(minutes=1)).reminded == 0
    assert reminders_of(participant, post).count() == 1
    assert fd.run_reminders(new_start - HOUR).reminded == 1
    assert reminders_of(participant, post).count() == 2
    post.refresh_from_db()
    assert post.reminded_for_start == new_start and post.remind_at is None


def test_reminded_event_moved_30_minutes_later_gets_no_second_reminder(clock):
    now = timezone.now()
    author, participant = support.make_employee(), support.make_employee()
    start = minute(now) + timedelta(days=1)
    post = fd.make_event(author, start=start, to=[participant])
    fd.run_reminders(start - HOUR)
    edit_at = start - HOUR + timedelta(minutes=1)
    clock.set(edit_at)
    new_start = start + timedelta(minutes=30)
    post = edit(author, post, now=edit_at, event_start=stamp(new_start), event_end=stamp(new_start + 2 * HOUR))
    assert post.remind_at is None and post.reminded_for_start == start
    for moment in (start - timedelta(minutes=10), new_start - HOUR, start + timedelta(minutes=10)):
        assert fd.run_reminders(moment).reminded == 0
    assert reminders_of(participant, post).count() == 1


def test_new_start_closer_than_hour_clears_remind_at(clock):
    now = timezone.now()
    author, participant = support.make_employee(), support.make_employee()
    post = fd.make_event(author, start=minute(now) + timedelta(days=1), to=[participant])
    assert post.remind_at is not None
    new_start = minute(now) + timedelta(minutes=30)
    post = edit(author, post, now=now, event_start=stamp(new_start), event_end=stamp(new_start + 2 * HOUR))
    assert post.event_start == new_start and post.remind_at is None
    assert fd.run_reminders(new_start - timedelta(minutes=1)).reminded == 0
    assert reminders_of(participant).count() == 0


def test_editing_only_event_title_or_description_keeps_remind_at_and_creates_no_notifications(clock):
    now = timezone.now()
    author, participant = support.make_employee(), support.make_employee()
    post = fd.make_event(author, start=minute(now) + timedelta(days=1), to=[participant])
    before_remind, notified = post.remind_at, total_notifications()
    post = edit(author, post, now=now, event_title="Новое название")
    post = edit(author, post, now=now, text="Новое описание")
    assert (post.event_title, post.text) == ("Новое название", "Новое описание")
    assert post.remind_at == before_remind and post.reminded_for_start is None
    assert total_notifications() == notified


# --- задание: фиксация, выбор, повторы, сбои --------------------------------------------------------------

def test_reminder_notification_and_reminded_mark_are_committed_together_or_not_at_all(clock, monkeypatch):
    now = timezone.now()
    author, participant = support.make_employee(), support.make_employee()
    post = fd.make_event(author, start=minute(now) + timedelta(days=1), to=[participant])
    due, start = post.remind_at, post.event_start
    failing_create(monkeypatch, f"feed.post:{post.pk}")
    result = fd.run_reminders(due)
    assert failed_count(result) == 1 and result.reminded == 0
    post.refresh_from_db()
    assert reminders_of(participant).count() == 0 and reminders_of(author).count() == 0
    assert post.reminded_for_start is None and post.remind_at == due   # отметки нет: откат вместе с уведомлением
    monkeypatch.undo()
    assert fd.run_reminders(due).reminded == 1
    post.refresh_from_db()
    assert reminders_of(participant, post).count() == 1 and reminders_of(author, post).count() == 1
    assert post.reminded_for_start == start and post.remind_at is None   # и то и другое — вместе


def test_reminder_selection_sql_takes_one_due_unreminded_future_event_for_update_skip_locked(clock):
    from apps.feed.services import reminders

    now = timezone.now()
    author = support.make_employee()
    start = now + timedelta(days=1)
    first = raw_event(author, start, now - timedelta(minutes=10), title="первое")
    second = raw_event(author, start, now - timedelta(minutes=5), title="второе")
    raw_event(author, start, now + timedelta(minutes=10), title="срок впереди")
    raw_event(author, now - timedelta(minutes=1), now - 2 * HOUR, title="уже началось")
    raw_event(author, start, now - timedelta(minutes=3), reminded_for_start=start, title="уже напомнено")
    moved = raw_event(author, start, now - timedelta(minutes=1), reminded_for_start=start - timedelta(hours=5),
                      title="перенесено после напоминания")
    assert reminders.select_due(now, []) == first.pk
    assert reminders.select_due(now, [first.pk]) == second.pk
    assert reminders.select_due(now, [first.pk, second.pk]) == moved.pk
    assert reminders.select_due(now, [first.pk, second.pk, moved.pk]) is None
    with fd.capture_sql() as sqls:
        reminders.select_due(now, [])
    sql = fd.assert_skip_locked(sqls, "feed_post")
    flat = " ".join(sql.split())
    assert re.search(r"remind_at\"?\s*<=", flat) and re.search(r"event_start\"?\s*>", flat)
    assert re.search(r"IS DISTINCT FROM", flat, re.I) and re.search(r"ORDER BY[^;]*remind_at", flat, re.I)
    assert re.search(r"LIMIT 1\b", flat) and "now()" not in flat.lower()
    with fd.queries_with_params() as pairs:
        reminders.select_due(now, [first.pk])
    raw = [(text, params) for text, params in pairs if "SKIP LOCKED" in text.upper() and "feed_post" in text]
    assert len(raw) == 1 and "%s" in raw[0][0] and re.search(r"<>\s*ALL\s*\(\s*%s\s*\)", raw[0][0])


def test_two_reminder_runs_in_a_row_create_one_notification(clock):
    now = timezone.now()
    author, participant = support.make_employee(), support.make_employee()
    post = fd.make_event(author, start=minute(now) + timedelta(days=1), to=[participant])
    assert fd.run_reminders(post.remind_at).reminded == 1
    assert fd.run_reminders(post.remind_at).reminded == 0
    assert reminders_of(participant, post).count() == 1 and reminders_of(author, post).count() == 1


def test_repeated_reminder_run_with_nothing_due_does_nothing_without_error(clock):
    now = timezone.now()
    author, participant = support.make_employee(), support.make_employee()
    fd.make_event(author, start=minute(now) + timedelta(days=1), to=[participant])   # срок ещё впереди
    before = total_notifications()
    for _ in range(2):
        result = fd.run_reminders(now)
        assert result.reminded == 0 and failed_count(result) == 0
    assert total_notifications() == before


def test_event_deleted_after_selection_is_skipped_without_error(clock, monkeypatch):
    now = timezone.now()
    author, participant = support.make_employee(), support.make_employee()
    post = fd.make_event(author, start=minute(now) + timedelta(days=1), to=[participant])
    Post = model("feed.Post")
    issued = fd.act_between_select_and_lock(monkeypatch, "reminders",
                                            lambda post_id: Post.objects.filter(pk=post_id).delete())
    pk = post.pk
    result = fd.run_reminders(post.remind_at)
    assert issued and issued[0] == pk
    assert result.reminded == 0 and failed_count(result) == 0
    assert not Post.objects.filter(pk=pk).exists()
    assert reminders_of(participant).count() == 0 and reminders_of(author).count() == 0


def three_events(now, author, participant):
    start = minute(now) + timedelta(days=1)
    bad = fd.make_event(author, start=start, to=[participant], title="Название сбойного события",
                        text="Описание сбойного события")
    others = [fd.make_event(author, start=start + timedelta(minutes=5 * (i + 1)), to=[participant],
                            title=f"Событие {i}") for i in range(2)]
    # сбойное — первое по `remind_at`
    model("feed.Post").objects.filter(pk=bad.pk).update(remind_at=bad.remind_at - timedelta(minutes=30))
    bad.refresh_from_db()
    return bad, others


def test_failing_event_is_logged_by_post_id_without_text_other_reminders_are_sent_and_job_does_not_fail(
        clock, monkeypatch, caplog):
    now = timezone.now()
    author, participant = support.make_employee(), support.make_employee()
    bad, others = three_events(now, author, participant)
    failing_create(monkeypatch, f"feed.post:{bad.pk}")
    with caplog.at_level(logging.DEBUG):
        result = fd.run_reminders(max(post.remind_at for post in others))   # без исключения наружу
    assert result.reminded == 2 and failed_count(result) == 1
    for post in others:
        assert reminders_of(participant, post).count() == 1 and reminders_of(author, post).count() == 1
    assert reminders_of(participant, bad).count() == 0
    bad.refresh_from_db()
    assert bad.reminded_for_start is None
    formatter = logging.Formatter()
    logged = "\n".join(formatter.format(r) for r in caplog.records if r.name == "apps.feed.tasks")
    assert str(bad.pk) in logged
    assert "Название сбойного события" not in logged and "Описание сбойного события" not in logged


def test_failing_event_id_is_excluded_from_selection_as_sql_parameter_until_end_of_run(clock, monkeypatch):
    now = timezone.now()
    author, participant = support.make_employee(), support.make_employee()
    bad, others = three_events(now, author, participant)
    hits = failing_create(monkeypatch, f"feed.post:{bad.pk}")
    with fd.queries_with_params() as pairs:
        result = fd.run_reminders(max(post.remind_at for post in others))
    assert result.reminded == 2
    assert len(hits) == 1   # сбойное событие в этом запуске больше не выбирается
    selects = [(text, params) for text, params in pairs if "SKIP LOCKED" in text.upper() and "feed_post" in text]
    assert len(selects) >= 3
    for text, params in selects:
        assert re.search(r"<>\s*ALL\s*\(\s*%s\s*\)", text) and "now()" not in text.lower()

    def lists_of(params):
        return [p for p in params if isinstance(p, (list, tuple, set))]

    assert not any(bad.pk in group for group in lists_of(selects[0][1]))
    assert any(bad.pk in group for text, params in selects[1:] for group in lists_of(params))


def test_event_started_while_job_was_idle_gets_no_reminder(clock):
    now = timezone.now()
    author, participant = support.make_employee(), support.make_employee()
    start = minute(now) + 2 * HOUR
    post = fd.make_event(author, start=start, to=[participant])
    assert post.remind_at == start - HOUR
    for moment in (start + timedelta(minutes=5), start + timedelta(minutes=10)):
        assert fd.run_reminders(moment).reminded == 0
    assert reminders_of(participant).count() == 0 and reminders_of(author).count() == 0


def test_reschedule_exactly_one_hour_later_sends_no_second_reminder(clock):
    now = timezone.now()
    author, participant = support.make_employee(), support.make_employee()
    start = minute(now) + timedelta(days=1)
    post = fd.make_event(author, start=start, to=[participant])
    fd.run_reminders(start - HOUR)
    edit_at = start - HOUR + timedelta(minutes=1)
    clock.set(edit_at)
    new_start = start + HOUR   # ровно на час позже прежнего начала: условие «строго больше»
    post = edit(author, post, now=edit_at, event_start=stamp(new_start), event_end=stamp(new_start + 2 * HOUR))
    assert post.remind_at is None
    for moment in (start, new_start - timedelta(minutes=1), new_start - HOUR + timedelta(minutes=1)):
        assert fd.run_reminders(moment).reminded == 0
    assert reminders_of(participant, post).count() == 1


def test_one_run_reminds_at_most_200_events_and_next_run_takes_the_rest(clock):
    now = timezone.now()
    author = support.make_employee()
    start = minute(now) + timedelta(days=1)
    Post = model("feed.Post")
    Post.objects.bulk_create([
        Post(author=author, kind="event", text="", published_at=now, event_title=f"Событие {i}", event_place="Место",
             event_start=start, event_end=start + HOUR, remind_at=start - HOUR) for i in range(201)])
    first = fd.run_reminders(start - HOUR)
    assert first.reminded == 200
    assert Post.objects.filter(reminded_for_start__isnull=False).count() == 200
    assert reminders_of(author).count() == 200
    second = fd.run_reminders(start - HOUR)
    assert second.reminded == 1
    assert Post.objects.filter(reminded_for_start__isnull=False).count() == 201
    assert reminders_of(author).count() == 201
