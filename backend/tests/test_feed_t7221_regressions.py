"""T-7221: форма правки, права меню и исчезновение записи перед замком."""
import pytest
from django.http import Http404

from tests import support_feed as fd
from tests.support import HX
from tests.test_feed_edit_2 import _world, q, tree

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("hx", [False, True])
def test_comment_edit_form_has_files_and_a_resolvable_save_target(hx):
    w = _world()
    comment = fd.comment(w.post, w.viewer.user)
    attached = fd.attach(comment, name="схема.txt")
    url = f"/feed/comments/{comment.pk}/edit/"
    response = w.viewer.client.get(url, **(HX if hx else {}))
    assert response.status_code == 200
    root = tree(response)
    form, = q(root, "form", data_form="feed-comment-edit")
    assert form.attrs["hx-post"] == url
    assert form.attrs["hx-swap"] == "outerHTML"
    assert q(root, id=form.attrs["hx-target"][1:])
    remove, = q(form, "input", name="remove", value=str(attached.pk))
    assert remove.attrs["type"] == "checkbox"
    assert "checked" not in remove.attrs


@pytest.mark.parametrize("raw_text,code", [("", "empty_text"), ("Мой адрес test@example.org", None)])
@pytest.mark.parametrize("hx", [False, True])
def test_comment_edit_refusal_keeps_files_remove_and_text(raw_text, code, hx):
    w = _world()
    comment = fd.comment(w.post, w.viewer.user)
    attached = fd.attach(comment, name="старый.txt")
    ready = fd.attach(None, uploaded_by=w.viewer.user, name="новый.txt")
    response = w.viewer.client.post(f"/feed/comments/{comment.pk}/edit/", {
        "text": raw_text, "files": [str(ready.pk)], "remove": [str(attached.pk), "999999999"],
    }, **(HX if hx else {}))
    assert response.status_code == 200
    root = tree(response)
    form, = q(root, "form", data_form="feed-comment-edit")
    assert q(form, "textarea", name="text")[0].text() == raw_text
    assert q(form, "input", name="files", value=str(ready.pk))
    assert q(form, "input", name="remove", value=str(attached.pk), checked=True)
    assert q(form, "input", name="remove", value="999999999", type="hidden")
    if code:
        assert q(form, data_error="text", data_code=code)
    else:
        assert q(form, "button", name="pdn_confirmed", value="1")
    if hx:
        assert response["HX-Retarget"] == "#feed-comment-edit"
        assert not q(root, "html")
    attached.refresh_from_db()
    ready.refresh_from_db()
    assert attached.comment_id == comment.pk
    assert ready.comment_id is None


@pytest.mark.parametrize("operation", ["edit", "delete"])
def test_comment_mutation_returns_404_if_post_disappears_before_lock(monkeypatch, operation):
    from apps.feed.models import Post
    from apps.feed.services import comments

    w = _world()
    comment = fd.comment(w.post, w.viewer.user)

    class Gone:
        def get(self, **kwargs):
            raise Post.DoesNotExist

    monkeypatch.setattr(Post.objects, "select_for_update", lambda: Gone())
    with pytest.raises(Http404):
        if operation == "edit":
            comments.edit(w.viewer.user, comment.pk, "Изменённый текст")
        else:
            comments.delete(w.viewer.user, comment.pk)


@pytest.mark.parametrize("surface", ["home", "card", "comments"])
def test_menus_show_author_and_moderator_rights_on_each_surface(surface):
    w = _world()
    comment = fd.comment(w.post, w.viewer.user)
    urls = {"home": "/", "card": f"/feed/{w.post.pk}/", "comments": f"/feed/{w.post.pk}/comments/"}
    for session, edit_post, delete_post, edit_comment, delete_comment in (
        (w.author, True, True, False, False),
        (w.viewer, False, False, True, True),
        (w.moderator, False, True, False, True),
        (w.other, False, False, False, False),
    ):
        response = session.client.get(urls[surface])
        assert response.status_code == 200
        root = tree(response)
        row, = q(root, id=f"c{comment.pk}")
        assert bool(q(row, "button", data_action="comment-edit")) == edit_comment
        assert bool(q(row, "button", data_action="comment-delete")) == delete_comment
        assert not q(row, "dialog")
        if surface == "comments":
            continue
        post, = q(root, id=f"feed-post-{w.post.pk}")
        assert bool(q(post, "button", data_action="post-edit")) == edit_post
        assert bool(q(post, "button", data_action="post-delete")) == delete_post
        if delete_post:
            dialog, = q(post, "dialog", data_feed_confirm=True)
            assert "open" not in dialog.attrs
            assert q(dialog, "button", type="button", value="cancel")
            assert q(dialog, "form", data_form="feed-post-delete")
