"""T-7260: доступная цель HTMX и полная страница отказа правки записи (FR-620, FR-612)."""
import pytest

from tests import support_feed as fd
from tests.support import HX
from tests.test_feed_edit import _plain_post, _saved, q, tree

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("hx", [False, True])
def test_edit_get_has_one_save_target_containing_the_form(hx):
    author, _, post = _plain_post()
    response = author.client.get(f"/feed/{post.pk}/edit/", **(HX if hx else {}))
    assert response.status_code == 200
    root = tree(response)
    form, = q(root, "form", data_form="feed-post-edit")
    target, = q(root, id=form.attrs["hx-target"][1:])
    assert form in list(target.walk())
    assert form.attrs["hx-swap"] == "outerHTML"


@pytest.mark.parametrize("hx", [False, True])
def test_edit_get_loads_external_feed_assets(hx):
    author, _, post = _plain_post()
    response = author.client.get(f"/feed/{post.pk}/edit/", **(HX if hx else {}))
    root = tree(response)
    script, = q(root, "script", src="/static/feed/feed.js", defer=True)
    stylesheet, = q(root, "link", href="/static/feed/feed.css", rel="stylesheet")
    assert script and stylesheet


def _refusal_text(kind):
    return "я" * 10001 if kind == "invalid" else f"Свяжитесь: {fd.email_of()}"


def _assert_preserved(response, post, raw_text, kind):
    assert response.status_code == 200
    root = tree(response)
    form, = q(root, "form", data_form="feed-post-edit")
    assert q(form, "textarea", name="text")[0].text() == raw_text
    assert sorted(node.attrs["value"] for node in q(form, "input", name="to")) == sorted(_saved(post))
    if kind == "invalid":
        assert q(form, data_error="text", data_code="too_long")
    else:
        assert q(form, "button", name="pdn_confirmed", value="1")
    post.refresh_from_db()
    assert post.text == "Старый текст"
    return root, form


@pytest.mark.parametrize("kind", ["invalid", "pdn"])
def test_ordinary_edit_refusal_is_full_page_and_preserves_input(kind):
    author, _, post = _plain_post()
    raw_text = _refusal_text(kind)
    response = author.client.post(f"/feed/{post.pk}/edit/", {"text": raw_text, "to": _saved(post)})
    root, form = _assert_preserved(response, post, raw_text, kind)
    assert q(root, "html")
    assert q(root, "main", id="content")
    target, = q(root, id=form.attrs["hx-target"][1:])
    assert form in list(target.walk())
    assert "HX-Retarget" not in response
    assert "HX-Reswap" not in response


@pytest.mark.parametrize("kind", ["invalid", "pdn"])
def test_hx_refusal_retargets_inner_form_leaving_save_wrapper_for_retry(kind):
    author, _, post = _plain_post()
    url = f"/feed/{post.pk}/edit/"
    initial = tree(author.client.get(url, **HX))
    original, = q(initial, "form", data_form="feed-post-edit")
    target, = q(initial, id=original.attrs["hx-target"][1:])
    raw_text = _refusal_text(kind)
    response = author.client.post(url, {"text": raw_text, "to": _saved(post)}, **HX)
    root, replacement = _assert_preserved(response, post, raw_text, kind)
    assert not q(root, "html")
    assert response["HX-Retarget"] == "#" + original.attrs["id"]
    assert response["HX-Reswap"] == "outerHTML"
    assert replacement.attrs["hx-target"] == original.attrs["hx-target"]
    assert not q(root, id=target.attrs["id"])
    # Модель outerHTML inner-form swap: внешний target остаётся единственным.
    parent = original.parent
    parent.children[parent.children.index(original)] = replacement
    replacement.parent = parent
    assert q(initial, id=target.attrs["id"]) == [target]
    assert q(target, "form", data_form="feed-post-edit") == [replacement]
    retry_text = "Исправленный текст" if kind == "invalid" else raw_text
    data = {"text": retry_text, "to": _saved(post)}
    if kind == "pdn":
        data["pdn_confirmed"] = "1"
    retry = author.client.post(url, data, **HX)
    assert retry.status_code == 200
    article, = q(tree(retry), "article", id=target.attrs["id"])
    assert retry_text in article.text()
    post.refresh_from_db()
    assert post.text == retry_text
