"""T-7216 часть 2: regression-тесты HTTP/HTMX для mark_read, списков прочитавших и opened (R3–R6)."""
from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from django.utils import timezone

from tests import support
from tests import support_feed as feed
from tests.support import HX
from tests.test_feed_important import q, q1, tree

pytestmark = pytest.mark.django_db


def _imp(doc, post):
    return q1(doc, None, id=f"feed-post-{post.pk}-imp")


def test_mark_read_on_non_important_post_returns_403_without_crash():
    """R4: неважная запись не даёт TypeError/500, отклоняется до сравнения срока."""
    author = feed.as_writer()
    reader = feed.as_plain()
    post = feed.make_post(author.user, "post", to=(reader.user,))

    plain = reader.client.post(f"/feed/{post.pk}/read/")
    hx = reader.client.post(f"/feed/{post.pk}/read/", **HX)

    assert plain.status_code == 403
    assert hx.status_code == 403
    assert support.model("feed.ReadMark").objects.filter(post=post, user=reader.user).count() == 0


def test_important_block_shows_until_text_with_date():
    """R5: в блоке важного обязательная строка «Важное, важно до <дата>»."""
    author = feed.as_writer()
    reader = feed.as_plain()
    until = feed.moscow(2026, 12, 31)
    post = feed.make_important(author.user, until=until, to=("all",))

    doc = tree(reader.client.get("/"))
    imp = _imp(doc, post)
    assert "Важное, важно до" in imp.text()
    assert "31.12.2026" in imp.text()


def test_reads_fragment_has_contract_ul_structure():
    """R5: GET /reads/ — фрагмент с ul[data-feed-list="reads"] и li read/unread; invited входит в список."""
    author = feed.as_writer()
    reader = feed.as_plain()
    invited = support.make_employee(state="invited")
    post = feed.make_important(author.user, to=(reader.user, invited))
    support.model("feed.ReadMark").objects.create(post=post, user=reader.user,
                                                   read_at=feed.moscow(2026, 10, 10, 18, 30))
    support.model("feed.ReadMark").objects.create(post=post, user=invited,
                                                   read_at=feed.moscow(2026, 10, 10, 19, 0))

    response = author.client.get(f"/feed/{post.pk}/reads/")
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "<html" not in body.lower()
    root = tree(response)
    q1(root, "ul", data_feed_list="reads")
    read_part = q1(root, None, data_feed_reads="read")
    unread_part = q1(root, None, data_feed_reads="unread")
    assert reader.user.full_name in read_part.text()
    assert invited.full_name in read_part.text()
    assert "Нет прочитавших" not in read_part.text()


def test_card_and_body_have_iso_opened_attribute():
    """R6: card.html и body.html передают opened в ISO-формате, парсящемся fromisoformat."""
    author = feed.as_writer()
    reader = feed.as_plain()
    post = feed.make_important(author.user, to=(reader.user,))

    for path in ("/", f"/feed/{post.pk}/"):
        response = reader.client.get(path)
        doc = tree(response)
        live = q1(doc, None, id="feed-live")
        opened = datetime.fromisoformat(live.attrs["data-opened"])
        assert opened.tzinfo is not None


def test_read_hx_response_keeps_active_important_visible():
    """R6: после Прочитано активная запись не показывается «было важным» — opened согласовано."""
    author = feed.as_writer()
    reader = feed.as_plain()
    now = timezone.now()
    post = feed.make_important(author.user, until=now + timedelta(days=7), to=(reader.user,))

    response = reader.client.post(f"/feed/{post.pk}/read/", **HX)
    assert response.status_code == 200
    body = response.content.decode("utf-8")
    assert "было важным" not in body
    assert "Важное, важно до" in body
    assert support.model("feed.ReadMark").objects.filter(post=post, user=reader.user).count() == 1


def test_read_button_targets_real_element_not_feed_modal():
    """R5: кнопка Прочитано и ссылка Списки не используют несуществующий #feed-modal."""
    author = feed.as_writer()
    reader = feed.as_plain()
    post = feed.make_important(author.user, to=(reader.user,))

    reader_doc = tree(reader.client.get("/"))
    reader_imp = _imp(reader_doc, post)
    button = q1(reader_imp, "button", data_action="read")
    assert button.attrs.get("hx-target") != "#feed-modal"
    assert button.attrs.get("hx-target") is not None

    author_doc = tree(author.client.get(f"/feed/{post.pk}/"))
    author_imp = _imp(author_doc, post)
    link = q1(author_imp, "a", href=f"/feed/{post.pk}/reads/")
    assert link.attrs.get("hx-target") != "#feed-modal"
