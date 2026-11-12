"""Service-only T-7214 checks; HTTP, files and dispatch belong to later tasks."""

from datetime import datetime, timezone as dt_timezone
from types import SimpleNamespace

import pytest
from django.db import connection

from tests import support
from tests import support_feed as ff

pytestmark = pytest.mark.django_db


def _employee(name="Сотрудник Тестов", **extra):
    return support.make_employee(full_name=name, **extra)


def test_vectors_update_post_and_feed_comment_without_indexing_mention_ids():
    from apps.feed.services import search

    author = _employee()
    post = ff.make_post(author, text="Проверяемый текст @[123]")
    search.vectors(post_ids=[post.pk])
    post.refresh_from_db()
    assert post.search is not None
    assert "123" not in str(post.search)

    comment = support.model("core.Comment").objects.create(
        object_ref=f"feed.post:{post.pk}", author=author, text="Комментарий @[123]"
    )
    feed_comment = support.model("feed.FeedComment").objects.create(comment=comment, post=post)
    search.vectors(comment_ids=[feed_comment.pk])
    feed_comment.refresh_from_db()
    assert feed_comment.search is not None
    assert "123" not in str(feed_comment.search)


def test_vectors_use_parameter_ids_only_for_requested_tables_and_skip_empty_updates():
    from apps.feed.services import search

    calls = []

    def capture(execute, sql, params, many, context):
        calls.append((sql, params))
        return execute(sql, params, many, context)

    with connection.execute_wrapper(capture):
        search.vectors()
        assert calls == []
        search.vectors(post_ids=[701, 701])
    assert len(calls) == 1
    sql, params = calls[0]
    assert "UPDATE feed_post" in sql
    assert "UPDATE feed_feedcomment" not in sql
    assert params == [[701]]
    assert "701" not in sql
    calls.clear()
    with connection.execute_wrapper(capture):
        search.vectors(comment_ids=[802, 802])
    assert len(calls) == 1
    sql, params = calls[0]
    assert "UPDATE feed_feedcomment" in sql
    assert "UPDATE feed_post" not in sql
    assert params == [[802]]
    assert "802" not in sql


def test_vectors_keep_event_title_and_place_at_a_text_at_b_and_comment_text():
    from apps.feed.services import search

    author = _employee()
    mentioned = _employee("Упомянутый Тестов")
    start = datetime(2026, 12, 20, 9, 0, tzinfo=dt_timezone.utc)
    event = ff.make_event(author, start=start, title="Пожарная тревога", place="Главный корпус",
                          text=f"Эвакуация сотрудников @[{mentioned.pk}]")
    with connection.cursor() as cursor:
        cursor.execute("UPDATE feed_post SET search = NULL WHERE id = %s", [event.pk])
    search.vectors(post_ids=[event.pk])

    def weights(post_id, word):
        found = set()
        with connection.cursor() as cursor:
            for weight in "ABCD":
                cursor.execute(
                    "SELECT search @@ to_tsquery('russian', %s) FROM feed_post WHERE id = %s",
                    [f"{word}:{weight}", post_id],
                )
                if cursor.fetchone()[0]:
                    found.add(weight)
        return found

    assert weights(event.pk, "пожарная") == {"A"}
    assert weights(event.pk, "корпус") == {"A"}
    assert weights(event.pk, "эвакуация") == {"B"}
    assert weights(event.pk, "сотрудников") == {"B"}
    assert weights(event.pk, str(mentioned.pk)) == set()

    comment = support.model("core.Comment").objects.create(
        object_ref=f"feed.post:{event.pk}", author=author, text="Заменили патч-корд @[987654321]"
    )
    feed_comment = support.model("feed.FeedComment").objects.create(comment=comment, post=event)
    search.vectors(comment_ids=[feed_comment.pk])
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT search @@ to_tsquery('russian', %s) FROM feed_feedcomment WHERE comment_id = %s",
            ["корд", feed_comment.pk],
        )
        assert cursor.fetchone()[0]
        cursor.execute(
            "SELECT search @@ to_tsquery('russian', %s) FROM feed_feedcomment WHERE comment_id = %s",
            ["987654321", feed_comment.pk],
        )
        assert not cursor.fetchone()[0]


def test_parse_requires_recipient_and_accepts_active_and_invited_people_with_deduplication():
    from apps.feed.services import recipients, visibility
    from apps.feed.services.errors import FeedError

    author = ff.as_plain().user
    viewer = visibility.viewer(author)
    with pytest.raises(FeedError) as error:
        recipients.parse(viewer, [])
    assert (error.value.code, error.value.field) == ("no_recipients", "to")

    active = _employee("Активный Адресат")
    invited = _employee("Приглашённый Адресат", state="invited")
    targets = recipients.parse(viewer, [f"p{active.pk}", f"p{invited.pk}", f"p{active.pk}"])
    assert targets.user_ids == (active.pk, invited.pk)
    assert targets.to_all is False


def test_parse_checks_post_all_and_rejects_unknown_target():
    from apps.feed.services import recipients, visibility
    from apps.feed.services.errors import FeedError

    plain = visibility.viewer(ff.as_plain().user)
    with pytest.raises(FeedError) as error:
        recipients.parse(plain, ["all"])
    assert error.value.code == "post_all_denied"

    with pytest.raises(FeedError) as error:
        recipients.parse(plain, ["p999999999"])
    assert error.value.code == "recipient_invalid"

    writer = visibility.viewer(ff.as_writer().user)
    assert recipients.parse(writer, ["all"]) == recipients.Targets(True, (), ())

    for state in ("blocked", "dismissed"):
        inactive = _employee(f"Недействующий {state}", state=state)
        with pytest.raises(FeedError) as error:
            recipients.parse(plain, [f"p{inactive.pk}"])
        assert (error.value.code, error.value.field) == ("recipient_invalid", "to")


def test_parse_validates_units_only_when_org_is_available_and_deduplicates_them():
    from apps.feed.services import recipients, visibility
    from apps.feed.services.errors import FeedError
    from tests import support_org as org

    viewer = visibility.viewer(ff.as_plain().user)
    unit = org.make_unit("Подразделение Получателей")
    assert recipients.parse(viewer, [f"u{unit.pk}", f"u{unit.pk}"]) == \
        recipients.Targets(False, (unit.pk,), ())
    with pytest.raises(FeedError) as error:
        recipients.parse(viewer, ["u999999999"])
    assert error.value.code == "recipient_invalid"
    with ff.without_org():
        with pytest.raises(FeedError) as error:
            recipients.parse(viewer, [f"u{unit.pk}"])
    assert error.value.code == "recipient_invalid"


def test_parse_limits_to_fifty_to_recipients_but_not_mentions():
    from apps.feed.services import recipients, visibility
    from apps.feed.services.errors import FeedError

    viewer = visibility.viewer(ff.as_plain().user)
    people = [_employee(f"Сотрудник {index}") for index in range(51)]
    exactly_fifty = recipients.parse(viewer, [f"p{person.pk}" for person in people[:50]])
    assert len(exactly_fifty.user_ids) == 50
    with pytest.raises(FeedError) as error:
        recipients.parse(viewer, [f"p{person.pk}" for person in people])
    assert error.value.code == "too_many_recipients"
    writer = visibility.viewer(ff.as_writer().user)
    assert len(recipients.parse(writer, ["all", *[f"p{person.pk}" for person in people[:49]]]).user_ids) == 49
    with pytest.raises(FeedError) as error:
        recipients.parse(writer, ["all", *[f"p{person.pk}" for person in people[:50]]])
    assert error.value.code == "too_many_recipients"


def test_parse_preserves_saved_targets_even_when_they_are_no_longer_valid_or_allowed():
    from apps.feed.services import recipients, visibility
    from apps.feed.services.errors import FeedError

    viewer = visibility.viewer(ff.as_plain().user)
    targets = recipients.parse(viewer, ["u900000001", "all"], saved=["u900000001", "all"])
    assert targets == recipients.Targets(True, (900000001,), ())
    with pytest.raises(FeedError) as error:
        recipients.parse(viewer, ["all"], saved=["u900000001", "all"])
    assert (error.value.code, error.value.field) == ("only_add_recipients", "to")


def test_publish_creates_post_and_recipients_and_mention_and_vector_atomically():
    from apps.feed.services import posts

    author = _employee("Автор Тестов")
    recipient = _employee("Адресат Тестов")
    mention = _employee("Упомянутый Тестов")
    now = datetime(2026, 11, 1, 9, 30, tzinfo=dt_timezone.utc)
    post = posts.publish(author, {"kind": "post", "text": f"Текст @[{mention.pk}]",
                                  "to": [f"p{recipient.pk}"]}, now=now)

    assert post.author_id == author.pk
    assert post.kind == "post"
    assert post.published_at == now
    assert post.search is not None
    rows = list(support.model("feed.Recipient").objects.filter(post=post).order_by("via", "user_id"))
    assert {(row.user_id, row.via, row.published_at) for row in rows} == {
        (recipient.pk, "to", now), (mention.pk, "mention", now)
    }


def test_publish_rolls_back_post_and_every_recipient_when_vector_update_fails(monkeypatch):
    from apps.feed.services import posts

    author = _employee("Автор отката")
    recipient = _employee("Адресат отката")
    mention = _employee("Упоминание отката")
    Post = support.model("feed.Post")
    Recipient = support.model("feed.Recipient")
    post_count = Post.objects.count()
    recipient_count = Recipient.objects.count()

    def fail_vector(**kwargs):
        raise RuntimeError("vector update failed")

    monkeypatch.setattr(posts.search, "vectors", fail_vector)
    with pytest.raises(RuntimeError, match="vector update failed"):
        posts.publish(author, {"kind": "post", "text": f"Текст @[{mention.pk}]",
                               "to": [f"p{recipient.pk}"]})
    assert (Post.objects.count(), Recipient.objects.count()) == (post_count, recipient_count)


def test_publish_accepts_exactly_10000_chars_and_rejects_10001_with_contract_error():
    from apps.feed.services import posts
    from apps.feed.services.errors import FeedError

    author = _employee("Автор границ текста")
    recipient = _employee("Адресат границ текста")
    accepted = posts.publish(author, {"kind": "post", "text": "x" * 10_000,
                                      "to": [f"p{recipient.pk}"]})
    assert len(accepted.text) == 10_000

    with pytest.raises(FeedError) as error:
        posts.publish(author, {"kind": "post", "text": "x" * 10_001,
                               "to": [f"p{recipient.pk}"]})
    assert (error.value.code, error.value.field, error.value.params) == \
        ("too_long", "text", {"limit": "10000"})


def test_publish_uses_one_default_clock_value_for_post_and_all_recipient_rows(monkeypatch):
    from apps.feed.services import posts

    author = _employee("Автор времени")
    recipient = _employee("Адресат времени")
    mention = _employee("Упоминание времени")
    expected = datetime(2026, 11, 1, 9, 30, tzinfo=dt_timezone.utc)
    calls = []

    def clock():
        calls.append(expected)
        return expected

    monkeypatch.setattr(posts, "timezone", SimpleNamespace(now=clock))
    post = posts.publish(author, {"kind": "post", "text": f"Текст @[{mention.pk}]",
                                  "to": [f"p{recipient.pk}"]})
    rows = list(support.model("feed.Recipient").objects.filter(post=post))
    assert calls == [expected]
    assert post.published_at == expected
    assert {row.published_at for row in rows} == {expected}


def test_publish_rejects_invalid_event_fields_and_invalid_text_without_rows():
    from apps.feed.services import posts
    from apps.feed.services.errors import FeedError

    author = _employee()
    recipient = _employee("Адресат проверки полей")
    with pytest.raises(FeedError) as event_error:
        posts.publish(author, {"kind": "event", "text": "Проверка полей события",
                               "to": [f"p{recipient.pk}"]})
    assert (event_error.value.code, event_error.value.field, event_error.value.params) == (
        "event_title_required", "event_title", {})
    with pytest.raises(FeedError) as text_error:
        posts.publish(author, {"kind": "post", "text": "   ", "to": [f"p{recipient.pk}"]})
    assert (text_error.value.code, text_error.value.field, text_error.value.params) == (
        "empty_text", "text", {})
    assert support.model("feed.Post").objects.count() == 0
    assert support.model("feed.Recipient").objects.count() == 0


def test_find_plain_returns_unique_email_and_phone_matches_with_limit():
    from apps.feed.services import pdn

    email = ff.email_of()
    phone = ff.phone_of()
    found = pdn.find_plain(f"Адрес {email} и телефон {phone}", f"Повтор {email}")
    assert len(found) == 2
    assert set(found) == {email, phone}

    addresses = [ff.email_of(local=f"person{index}") for index in range(21)]
    assert len(pdn.find_plain(" ".join(addresses))) == 20


def test_publish_raises_pdn_warning_before_creating_any_rows():
    from apps.feed.services import posts
    from apps.feed.services.errors import PdnFound

    author = _employee()
    recipient = _employee("Адресат Тестов")
    phone = ff.phone_of()
    with pytest.raises(PdnFound) as warning:
        posts.publish(author, {"kind": "post", "text": f"Напишите по телефону {phone}",
                               "to": [f"p{recipient.pk}"]})
    assert warning.value.found == [phone]
    assert support.model("feed.Post").objects.count() == 0
    assert support.model("feed.Recipient").objects.count() == 0


def test_publish_with_contract_pdn_confirmation_persists_found_pii():
    from apps.feed.services import posts

    author = _employee("Автор подтверждённого ПДн")
    recipient = _employee("Адресат подтверждённого ПДн")
    phone = ff.phone_of()
    post = posts.publish(author, {"kind": "post", "text": f"Телефон {phone}",
                                  "to": [f"p{recipient.pk}"], "pdn_confirmed": "1"})
    assert post.text == f"Телефон {phone}"
    assert support.model("feed.Recipient").objects.filter(post=post, via="to", user=recipient).exists()
