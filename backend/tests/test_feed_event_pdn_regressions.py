"""Регрессии публикации события с ПДн в его полях и сохранёнными загрузками."""

from collections import defaultdict
from datetime import timedelta
from zoneinfo import ZoneInfo

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from tests import support, support_feed as feed
from tests.support import HX

pytestmark = pytest.mark.django_db

MOSCOW = ZoneInfo("Europe/Moscow")


def _email():
    return feed.email_of("event", "example.org")


def _phone():
    return feed.phone_of("+7", "912", "345", "67", "89")


def _event_data(**overrides):
    start = (timezone.now() + timedelta(days=3)).astimezone(MOSCOW)
    start = start.replace(minute=0, second=0, microsecond=0)
    data = {
        "kind": "event",
        "text": "",
        "event_title": "Техническая встреча",
        "event_place": "Корпус 2",
        "event_start": start.strftime("%Y-%m-%dT%H:%M"),
        "event_end": (start + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M"),
        "to": ["all"],
    }
    data.update(overrides)
    return data


def _upload(writer, name="Схема.txt"):
    response = writer.client.post(
        "/feed/files/",
        {"scope": "post", "file": SimpleUploadedFile(name, b"Synthetic attachment\n",
                                                          content_type="text/plain")},
        **HX,
    )
    assert response.status_code == 200
    return support.model("feed.FeedFile").objects.get(
        pk=_feed_pill_id(response.content.decode("utf-8"))
    )


def _feed_pill_id(html):
    from tests.test_feed_pdn import q, tree

    pills = q(tree(html), None, data_feed_file=True)
    assert len(pills) == 1
    return pills[0].attrs["data-feed-file"]


def _warning_form(response, found):
    from tests.test_feed_pdn import q, tree

    root = tree(response)
    warning, = q(root, None, data_feed_pdn=True)
    assert [node.text() for node in q(warning, "li", data_feed_pdn_item=True)] == [found]
    assert q(warning, "button", data_action="pdn-fix")
    assert q(warning, "button", name="pdn_confirmed", value="1")
    form, = q(root, "form", data_feed_form=True)
    return form


def _returned_form_controls(form):
    from tests.test_feed_pdn import q

    controls = defaultdict(list)
    for node in q(form, "input"):
        name = node.attrs.get("name")
        if not name or "disabled" in node.attrs:
            continue
        kind = node.attrs.get("type", "text")
        if kind in ("radio", "checkbox") and "checked" not in node.attrs:
            continue
        if kind not in ("submit", "button", "file"):
            controls[name].append(node.attrs.get("value", ""))
    for node in q(form, "textarea"):
        controls[node.attrs["name"]] = [node.raw_text()]
    return dict(controls)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_title", "Встреча: "),
        ("event_place", "Место: "),
    ],
)
@pytest.mark.parametrize("contact", ["email", "phone"])
def test_event_title_and_place_pdns_show_warning_without_persisting(
    field, value, contact, monkeypatch
):
    writer = feed.as_writer()
    found = _email() if contact == "email" else _phone()
    notifications = []
    monkeypatch.setattr(
        "apps.notify.services.dispatch.create",
        lambda *args, **kwargs: notifications.append((args, kwargs)),
    )

    response = writer.client.post(
        "/feed/posts/", _event_data(**{field: value + found})
    )

    assert response.status_code == 200
    form = _warning_form(response, found)
    from tests.test_feed_pdn import q

    assert q(form, "input", name=field, value=value + found)
    if response.headers.get("HX-Retarget"):
        assert response.headers["HX-Retarget"] == "#feed-form"
        assert response.headers["HX-Reswap"] == "outerHTML"
    Post = support.model("feed.Post")
    Recipient = support.model("feed.Recipient")
    assert Post.objects.count() == 0
    assert Recipient.objects.count() == 0
    assert notifications == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_title", "Встреча: "),
        ("event_place", "Место: "),
    ],
)
def test_event_pdns_are_allowed_after_confirmation(field, value):
    writer = feed.as_writer()
    found = _email()
    response = writer.client.post(
        "/feed/posts/",
        _event_data(**{field: value + found}, pdn_confirmed="1"),
    )

    assert response.status_code == 302
    post = support.model("feed.Post").objects.get()
    assert getattr(post, field) == value + found


@pytest.mark.parametrize(
    ("field", "contact"),
    [("event_title", "email"), ("event_place", "phone")],
)
@pytest.mark.parametrize("hx", [False, True])
def test_uploaded_file_survives_event_pdn_warning_and_returned_form_confirmation(
    protected_root, field, contact, hx
):
    writer = feed.as_writer()
    uploaded = _upload(writer)
    found = _email() if contact == "email" else _phone()
    text = "Описание события без контактов"
    data = _event_data(text=text, **{field: f"Поле события: {found}"}, files=[str(uploaded.pk)])
    response = writer.client.post("/feed/posts/", data, **(HX if hx else {}))

    assert response.status_code == 200
    form = _warning_form(response, found)
    from tests.test_feed_pdn import q

    (pill,) = q(form, None, data_feed_file=str(uploaded.pk))
    assert "Схема.txt" in pill.text()
    (hidden,) = q(pill, "input", type="hidden", name="files", value=str(uploaded.pk))
    assert hidden
    if hx:
        assert response.headers["HX-Retarget"] == "#feed-form"
        assert response.headers["HX-Reswap"] == "outerHTML"

    retry_data = _returned_form_controls(form)
    assert retry_data["files"] == [str(uploaded.pk)]
    retry_data["pdn_confirmed"] = ["1"]
    retry = writer.client.post("/feed/posts/", retry_data, **(HX if hx else {}))

    assert retry.status_code == (200 if hx else 302)
    if hx:
        from tests.test_feed_pdn import tree

        assert q(tree(retry), "article", data_post_id=True)
    Post = support.model("feed.Post")
    post = Post.objects.get()
    uploaded.refresh_from_db()
    assert uploaded.post_id == post.pk
    assert uploaded.comment_id is None


@pytest.mark.parametrize("bad_kind", ["foreign", "attached_elsewhere", "missing"])
@pytest.mark.parametrize("hx", [False, True])
def test_publish_rejection_does_not_restore_or_disclose_forged_file_ids(protected_root, bad_kind, hx):
    writer = feed.as_writer()
    owned = feed.attach(None, "Свой файл.txt", uploaded_by=writer.user)
    forbidden = None
    if bad_kind == "foreign":
        other = feed.as_writer()
        forbidden = feed.attach(None, "Чужой файл — закрытые данные.txt", uploaded_by=other.user)
    elif bad_kind == "attached_elsewhere":
        other_post = feed.make_post(writer.user, to=(writer.user,), text="Другая запись")
        forbidden = feed.attach(other_post, "Уже привязанный файл.txt", uploaded_by=writer.user)
    bad_id = str(forbidden.pk) if forbidden is not None else "999999999"
    response = writer.client.post(
        "/feed/posts/",
        _event_data(text="Обычный текст", files=[str(owned.pk), bad_id], pdn_confirmed="1"),
        **(HX if hx else {}),
    )

    assert response.status_code == 200
    from tests.test_feed_pdn import q, tree

    root = tree(response)
    form, = q(root, "form", data_feed_form=True)
    assert q(form, None, data_error="files", data_code="file_missing")
    assert [node.attrs["value"] for node in q(form, "input", name="files")] == [str(owned.pk)]
    assert not q(form, data_feed_file=bad_id)
    if forbidden is not None:
        assert forbidden.name not in root.text()
    owned.refresh_from_db()
    assert owned.post_id is None


@pytest.mark.parametrize("kind", ["post", "important"])
def test_non_event_kinds_ignore_pdns_in_unowned_event_fields(kind):
    writer = feed.as_writer()
    data = {
        "kind": kind,
        "text": "Обычный текст без контактов",
        "to": ["all"],
        "event_title": "Контакт " + _email(),
        "event_place": "Контакт " + _phone(),
    }
    if kind == "important":
        data["term"] = "day"

    response = writer.client.post("/feed/posts/", data)

    assert response.status_code == 302
    post = support.model("feed.Post").objects.get()
    assert post.kind == kind
