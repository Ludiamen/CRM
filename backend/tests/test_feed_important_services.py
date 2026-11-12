"""T-7216: сервисные проверки сроков и публикации важного (CONTRACT-007 §§5.3–5.4).

Рассылки, файлы и правка срока здесь не проверяются.
"""

from datetime import date, datetime, timedelta, timezone as dt_timezone
from types import SimpleNamespace

import pytest

from tests import support, support_org
from tests import support_feed as feed

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("term,today,expected", [
    ("day", date(2026, 10, 10), (2026, 10, 12)),
    ("day", date(2026, 12, 31), (2027, 1, 2)),
    ("week", date(2026, 10, 10), (2026, 10, 18)),
    ("week", date(2026, 12, 28), (2027, 1, 5)),
    ("month", date(2026, 1, 31), (2026, 3, 1)),
    ("month", date(2028, 1, 31), (2028, 3, 1)),
    ("month", date(2026, 3, 31), (2026, 5, 1)),
    ("month", date(2026, 10, 10), (2026, 11, 11)),
    ("month", date(2026, 12, 15), (2027, 1, 16)),
])
def test_until_calendar_terms_end_at_moscow_midnight_after_last_day(term, today, expected):
    from apps.feed.services import important

    result = important.until(term, None, today)
    assert result == feed.moscow(*expected)
    assert result.tzinfo.key == "Europe/Moscow"
    assert (result.hour, result.minute, result.second, result.microsecond) == (0, 0, 0, 0)


@pytest.mark.parametrize("given,expected", [
    (date(2026, 10, 11), (2026, 10, 12)),
    (date(2026, 12, 31), (2027, 1, 1)),
    (date(2027, 10, 10), (2027, 10, 11)),
])
def test_until_date_accepts_tomorrow_through_one_year_inclusively(given, expected):
    from apps.feed.services import important

    assert important.until("date", given, date(2026, 10, 10)) == feed.moscow(*expected)


@pytest.mark.parametrize("given,code", [
    (date(2026, 10, 9), "date_passed"),
    (date(2026, 10, 10), "date_passed"),
    (date(2027, 10, 11), "term_too_far"),
    (date(2027, 11, 10), "term_too_far"),
])
def test_until_date_rejects_past_today_and_over_year_with_exact_errors(given, code):
    from apps.feed.services import important
    from apps.feed.services.errors import FeedError

    with pytest.raises(FeedError) as caught:
        important.until("date", given, date(2026, 10, 10))
    assert (caught.value.code, caught.value.field, caught.value.params) == (code, "term", {})


def _mark(post, *people):
    for person in people:
        support.model("feed.ReadMark").objects.create(
            post=post, user=person, read_at=feed.moscow(2026, 10, 10, 18, 30))


def test_stats_deduplicates_current_unit_person_and_mention_audience_without_author():
    from apps.feed.services import important

    author = support.make_employee()
    first, second, outsider = [support.make_employee() for _ in range(3)]
    parent = support_org.make_unit("Родительский отдел")
    child = support_org.make_unit("Дочерний отдел", parent=parent)
    support_org.make_member(first, child)
    support_org.make_member(second, parent)
    post = feed.make_important(author, to=(parent, first, author), mentions=(first,))
    _mark(post, first, author, outsider)

    result = important.stats(post)
    assert (result.read, result.total) == (1, 2)
    # Аудитория текущая: после выхода из отдела прежнее прочтение не считается.
    support.model("org.Membership").objects.filter(user=second).delete()
    result = important.stats(post)
    assert (result.read, result.total) == (1, 1)


def test_stats_excludes_blocked_dismissed_and_removed_active_but_includes_invited():
    from apps.feed.services import important

    author = support.make_employee()
    active = support.make_employee()
    invited = support.make_employee(state="invited")
    blocked = support.make_employee(state="blocked")
    dismissed = support.make_employee(state="dismissed")
    removed = support.make_employee()
    post = feed.make_important(author, to=(active, invited, blocked, dismissed, removed, author))
    _mark(post, active, invited, blocked, dismissed, removed, author)
    support.model("feed.Recipient").objects.filter(post=post, user=removed).delete()

    result = important.stats(post)
    assert (result.read, result.total) == (2, 2)


def test_stats_to_all_tracks_current_audience_and_empty_personal_audience():
    from apps.feed.services import important, visibility

    author = support.make_employee()
    active = support.make_employee()
    invited = support.make_employee(state="invited")
    blocked = support.make_employee(state="blocked")
    dismissed = support.make_employee(state="dismissed")
    post = feed.make_important(author, to=("all",))
    _mark(post, author, active, invited, blocked, dismissed)
    expected_ids = visibility.audience(post) - {author.pk}
    result = important.stats(post)
    assert (result.read, result.total) == (2, len(expected_ids))
    newcomer = support.make_employee()
    result = important.stats(post)
    assert (result.read, result.total) == (2, len(expected_ids) + 1)
    _mark(post, newcomer)
    assert important.stats(post).read == 3
    empty = feed.make_important(author, to=(author,))
    _mark(empty, author)
    result = important.stats(empty)
    assert (result.read, result.total) == (0, 0)


@pytest.mark.parametrize("hour,minute", [(0, 0), (21, 30)])
def test_publish_important_uses_one_clock_and_moscow_date_for_deadline(monkeypatch, hour, minute):
    from apps.feed.services import posts

    author, recipient, mentioned = [support.make_employee() for _ in range(3)]
    now = datetime(2026, 10, 9, hour, minute, tzinfo=dt_timezone.utc)
    calls = []

    def clock():
        calls.append(now)
        return now

    monkeypatch.setattr(posts, "timezone", SimpleNamespace(now=clock))
    post = posts.publish(author, {"kind": "important", "text": f"Публикация @[{mentioned.pk}]",
                                  "to": [f"p{recipient.pk}"], "term": "day"})
    assert calls == [now]
    assert post.kind == "important" and post.published_at == now
    assert post.important_until == feed.moscow(2026, 10, 11 if hour == 0 else 12)
    assert post.search is not None and str(mentioned.pk) not in str(post.search)
    rows = support.model("feed.Recipient").objects.filter(post=post)
    assert {(row.user_id, row.via, row.published_at) for row in rows} == {
        (recipient.pk, "to", now), (mentioned.pk, "mention", now)}


@pytest.mark.parametrize("given,code", [("2026-10-09", "date_passed"),
                                      ("2026-10-10", "date_passed"),
                                      ("2027-10-11", "term_too_far")])
def test_publish_important_date_refusal_leaves_no_rows(given, code):
    from apps.feed.services import posts
    from apps.feed.services.errors import FeedError

    author, recipient = support.make_employee(), support.make_employee()
    with pytest.raises(FeedError) as caught:
        posts.publish(author, {"kind": "important", "text": "Важное сообщение", "term": "date",
                               "until": given, "to": [f"p{recipient.pk}"]},
                      now=feed.moscow(2026, 10, 10, 15))
    assert (caught.value.code, caught.value.field, caught.value.params) == (code, "term", {})
    assert support.model("feed.Post").objects.count() == 0
    assert support.model("feed.Recipient").objects.count() == 0


def test_publish_important_date_and_pdn_confirmation_preserve_text():
    from apps.feed.services import posts
    from apps.feed.services.errors import PdnFound

    author, recipient = support.make_employee(), support.make_employee()
    phone = feed.phone_of()
    data = {"kind": "important", "text": f"Телефон {phone}", "term": "date", "until": "2027-10-10",
            "to": [f"p{recipient.pk}"]}
    now = feed.moscow(2026, 10, 10, 15)
    with pytest.raises(PdnFound) as caught:
        posts.publish(author, data, now=now)
    assert caught.value.found == [phone]
    assert support.model("feed.Post").objects.count() == 0
    assert support.model("feed.Recipient").objects.count() == 0
    post = posts.publish(author, {**data, "pdn_confirmed": "1"}, now=now)
    assert post.text == data["text"]
    assert post.important_until == feed.moscow(2027, 10, 11)


def test_publish_important_rolls_back_all_rows_when_vector_update_fails(monkeypatch):
    from apps.feed.services import posts

    author, recipient, mentioned = [support.make_employee() for _ in range(3)]

    def fail_vector(**kwargs):
        raise RuntimeError("vector update failed")

    monkeypatch.setattr(posts.search, "vectors", fail_vector)
    with pytest.raises(RuntimeError, match="vector update failed"):
        posts.publish(author, {"kind": "important", "text": f"Важное @[{mentioned.pk}]", "term": "week",
                               "to": [f"p{recipient.pk}"]}, now=feed.moscow(2026, 10, 10, 15))
    assert support.model("feed.Post").objects.count() == 0
    assert support.model("feed.Recipient").objects.count() == 0


@pytest.mark.parametrize("term", [None, "", " ", "unknown", "year"])
def test_until_term_required_for_missing_empty_or_unknown_term(term):
    from apps.feed.services import important
    from apps.feed.services.errors import FeedError

    with pytest.raises(FeedError) as caught:
        important.until(term, None, date(2026, 10, 10))
    assert (caught.value.code, caught.value.field, caught.value.params) == ("term_required", "term", {})


@pytest.mark.parametrize("until", ["", " ", "bad", "2026-02-30", "2026-13-01", "01/10/2026"])
def test_publish_important_date_invalid_until_leaves_no_rows(until):
    from apps.feed.services import posts
    from apps.feed.services.errors import FeedError

    author, recipient = support.make_employee(), support.make_employee()
    with pytest.raises(FeedError) as caught:
        posts.publish(author, {"kind": "important", "text": "Важное сообщение", "term": "date",
                               "until": until, "to": [f"p{recipient.pk}"]},
                      now=feed.moscow(2026, 10, 10, 15))
    assert (caught.value.code, caught.value.field, caught.value.params) == ("invalid_until", "until", {})
    assert support.model("feed.Post").objects.count() == 0
    assert support.model("feed.Recipient").objects.count() == 0


def test_publish_important_date_missing_until_key_is_invalid_until():
    from apps.feed.services import posts
    from apps.feed.services.errors import FeedError

    author, recipient = support.make_employee(), support.make_employee()
    data = {"kind": "important", "text": "Важное сообщение", "term": "date", "to": [f"p{recipient.pk}"]}
    with pytest.raises(FeedError) as caught:
        posts.publish(author, data, now=feed.moscow(2026, 10, 10, 15))
    assert (caught.value.code, caught.value.field, caught.value.params) == ("invalid_until", "until", {})
    assert support.model("feed.Post").objects.count() == 0
    assert support.model("feed.Recipient").objects.count() == 0


@pytest.mark.parametrize("term", ["day", "week", "month"])
@pytest.mark.parametrize("until", ["", "bad", "2026-02-30"])
def test_until_calendar_terms_ignore_bad_until(term, until):
    from apps.feed.services import posts

    author, recipient = support.make_employee(), support.make_employee()
    post = posts.publish(author, {"kind": "important", "text": "Важное сообщение", "term": term,
                                  "until": until, "to": [f"p{recipient.pk}"]},
                         now=feed.moscow(2026, 10, 10, 15))
    assert post.kind == "important"
    assert post.important_until is not None


def test_until_leap_year_feb_29_boundary():
    from apps.feed.services import important
    from apps.feed.services.errors import FeedError

    today = date(2024, 2, 29)
    assert important.until("date", date(2025, 2, 28), today) == feed.moscow(2025, 3, 1)
    with pytest.raises(FeedError) as caught:
        important.until("date", date(2025, 3, 1), today)
    assert (caught.value.code, caught.value.field, caught.value.params) == ("term_too_far", "term", {})


def test_publish_important_uses_moscow_date_not_utc_for_year_boundary():
    from apps.feed.services import posts

    author, recipient = support.make_employee(), support.make_employee()
    # 2024-02-29 21:00 UTC == 2024-03-01 00:00 Europe/Moscow
    now = datetime(2024, 2, 29, 21, 0, tzinfo=dt_timezone.utc)
    post = posts.publish(author, {"kind": "important", "text": "Важное сообщение", "term": "date",
                                  "until": "2025-03-01", "to": [f"p{recipient.pk}"]},
                         now=now)
    assert post.important_until == feed.moscow(2025, 3, 2)


def test_card_data_counts_invited_in_current_audience_and_read_marks():
    """R3: invited-адресат входит в текущую аудиторию и учитывается в прочтениях."""
    from apps.feed.services import page

    author = support.make_employee()
    active = support.make_employee()
    invited = support.make_employee(state="invited")
    post = feed.make_important(author, to=(active, invited))
    _mark(post, active, invited)

    card = page._card_data([post], author)[post.pk]
    assert card.read_count == 2
    assert card.read_total == 2
    # Автор не входит в аудиторию и не отмечает свою запись.
    assert card.read is False
    reader_card = page._card_data([post], active)[post.pk]
    assert reader_card.read is True


def test_card_data_excludes_moved_dismissed_from_read_count_and_total():
    """R3: активный прочитавший, затем исключённый из адресатов/переведённый, не входит в N/M."""
    from apps.feed.services import page
    from tests import support_org

    author = support.make_employee()
    unit = support_org.make_unit("Отдел теста")
    active = support.make_employee()
    support_org.make_member(active, unit)
    dismissed = support.make_employee()
    support_org.make_member(dismissed, unit)
    post = feed.make_important(author, to=(unit,))
    _mark(post, active, dismissed)

    card = page._card_data([post], author)[post.pk]
    assert card.read_count == 2
    assert card.read_total == 2

    # Переводим active в другой узел — он выходит из подразделения-адресата.
    other = support_org.make_unit("Другой отдел")
    support_org.make_member(active, other)
    support.model("org.Membership").objects.filter(user=active, unit=unit).delete()
    # Увольняем dismissed.
    dismissed.state = "dismissed"
    dismissed.dismissed_at = feed.moscow(2026, 10, 10, 12, 0)
    dismissed.save(update_fields=["state", "dismissed_at"])

    card = page._card_data([post], author)[post.pk]
    assert card.read_count == 0
    assert card.read_total == 0


def test_card_data_agrees_with_important_stats():
    """R3: page._card_data и important.stats используют одну и ту же текущую аудиторию."""
    from apps.feed.services import important, page

    author = support.make_employee()
    active = support.make_employee()
    invited = support.make_employee(state="invited")
    blocked = support.make_employee(state="blocked")
    post = feed.make_important(author, to=(active, invited, blocked))
    _mark(post, active, invited, blocked)

    card = page._card_data([post], author)[post.pk]
    stats = important.stats(post)
    assert (card.read_count, card.read_total) == (stats.read, stats.total) == (2, 2)


def test_card_data_batches_distinct_unit_audiences_with_constant_queries():
    """R3: 1/3/20 разных отделов не увеличивают число запросов; N/M остаются раздельными."""
    from apps.feed.services import important, page

    author = support.make_employee()
    posts = []
    for index in range(20):
        unit = support_org.make_unit()
        child = support_org.make_unit(parent=unit)
        members = [support.make_employee() for _ in range(1 + index % 3)]
        for member in members:
            support_org.make_member(member, child)
        # Один человек адресован и напрямую, и через вложенный отдел.
        post = feed.make_important(author, to=(unit, members[0]))
        _mark(post, *members[:index % len(members)], author)
        posts.append(post)

    counts = {}
    for count in (1, 3, 20):
        with feed.queries_with_params() as pairs:
            cards = page._card_data(posts[:count], author)
        counts[count] = (
            len(pairs),
            sum('"org_unit"' in sql.lower() for sql, _ in pairs),
            sum('"org_membership"' in sql.lower() for sql, _ in pairs),
        )
        for index, post in enumerate(posts[:count]):
            stats = important.stats(post)
            card = cards[post.pk]
            total = 1 + index % 3
            assert (card.read_count, card.read_total) == (stats.read, stats.total) == (index % total, total)
    assert counts[1] == counts[3] == counts[20], counts
