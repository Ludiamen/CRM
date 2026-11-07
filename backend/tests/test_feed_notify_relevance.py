"""T-7224: актуальность ссылок перед письмом и сводкой (FR-630, FR-632)."""

import pytest

from tests import support
from tests import support_feed as ff

pytestmark = pytest.mark.django_db


@pytest.fixture
def record():
    author = support.make_employee()
    recipient = support.make_employee()
    post = ff.make_post(author, to=[recipient])
    comment = ff.comment(post, author)
    return recipient, post, comment


@pytest.mark.parametrize("template", [
    "", "other.post:{p}", "feed.post:", "feed.post:abc", "feed.post:-1",
    "feed.post:+{p}", "feed.post: {p}", "feed.post:{p}\n",
    "feed.post:{p}:c", "feed.post:{p}:cabc", "feed.post:{p}:c-1",
    "feed.post:{p}:c+{c}", "feed.post:{p}:comment:{c}",
    "feed.post:{p}:c{c}:extra", "prefix:feed.post:{p}",
])
def test_malformed_reference_is_not_relevant(record, template):
    from apps.feed.notify_kinds import still_relevant

    recipient, post, comment = record
    assert still_relevant(recipient.pk, template.format(p=post.pk, c=comment.pk)) is False


def test_oversized_id_reference_is_not_relevant(record):
    from apps.feed.notify_kinds import still_relevant

    recipient, post, comment = record
    huge = "9" * 5000
    assert still_relevant(recipient.pk, f"feed.post:{huge}") is False
    assert still_relevant(recipient.pk, f"feed.post:{post.pk}:c{huge}") is False
    assert still_relevant(recipient.pk, f"feed.post:{huge}:c{comment.pk}") is False


def test_bigint_boundary_id_reference_is_not_relevant(record):
    from apps.feed.notify_kinds import still_relevant

    recipient, post, comment = record
    assert still_relevant(recipient.pk, f"feed.post:{2**63 - 1}") is False
    assert still_relevant(recipient.pk, f"feed.post:{post.pk}:c{2**63 - 1}") is False
    assert still_relevant(recipient.pk, f"feed.post:{2**63}") is False
    assert still_relevant(recipient.pk, f"feed.post:{post.pk}:c{2**63}") is False


def test_non_string_reference_is_not_relevant(record):
    from apps.feed.notify_kinds import still_relevant

    recipient, _, _ = record
    assert still_relevant(recipient.pk, None) is False
    assert still_relevant(recipient.pk, 7) is False


@pytest.mark.parametrize("with_comment", [False, True])
def test_visible_reference_is_relevant(record, with_comment):
    from apps.feed.notify_kinds import still_relevant

    recipient, post, comment = record
    ref = f"feed.post:{post.pk}" + (f":c{comment.pk}" if with_comment else "")
    assert still_relevant(recipient.pk, ref) is True


@pytest.mark.parametrize("with_comment", [False, True])
def test_hidden_reference_is_not_relevant(record, with_comment):
    from apps.feed.notify_kinds import still_relevant

    _, post, comment = record
    outsider = support.make_employee()
    ref = f"feed.post:{post.pk}" + (f":c{comment.pk}" if with_comment else "")
    assert still_relevant(outsider.pk, ref) is False


@pytest.mark.parametrize("with_comment", [False, True])
def test_deleted_post_is_not_relevant(record, with_comment):
    from apps.feed.notify_kinds import still_relevant

    recipient, post, comment = record
    ref = f"feed.post:{post.pk}" + (f":c{comment.pk}" if with_comment else "")
    post.delete()
    assert still_relevant(recipient.pk, ref) is False


def test_deleted_comment_is_not_relevant(record):
    from apps.feed.notify_kinds import still_relevant

    recipient, post, comment = record
    ref = f"feed.post:{post.pk}:c{comment.pk}"
    comment.delete()
    assert still_relevant(recipient.pk, ref) is False


def test_comment_of_another_post_is_not_relevant(record):
    from apps.feed.notify_kinds import still_relevant

    recipient, post, comment = record
    other_post = ff.make_post(post.author, to=[recipient])
    assert still_relevant(recipient.pk, f"feed.post:{other_post.pk}:c{comment.pk}") is False


def test_core_comment_without_feed_link_is_not_relevant(record):
    from apps.feed.models import FeedComment
    from apps.feed.notify_kinds import still_relevant

    recipient, post, comment = record
    FeedComment.objects.filter(comment_id=comment.pk).delete()
    assert still_relevant(recipient.pk, f"feed.post:{post.pk}:c{comment.pk}") is False


def test_all_eight_kinds_use_relevance_hook(record):
    from apps.feed.notify_kinds import kinds, still_relevant

    recipient, post, comment = record
    registered = kinds()
    assert {kind.code for kind in registered} == set(ff.FEED_CODES)
    for kind in registered:
        assert kind.still_relevant is still_relevant
        assert kind.still_relevant(recipient.pk, f"feed.post:{post.pk}:c{comment.pk}") is True
        assert kind.still_relevant(recipient.pk, "invalid") is False
