"""T-7215 follow-up: retry-форма и HTTP обычного сообщения, без будущих служб."""
import json

import pytest
from django.utils.html import escape

from tests import support
from tests import support_feed as feed
from tests.test_feed_posts import _find, _refusals, _tree

pytestmark = pytest.mark.django_db
HX = {"HX-Request": "true"}


@pytest.mark.parametrize("hx", [False, True], ids=["ordinary", "hx"])
def test_retry_mentions_restore_only_active_names_and_readonly_pills(hx):
    """Ни пришедший JSON, ни invited/blocked/dismissed/unknown не обещают mention-адресата."""
    writer = feed.as_writer()
    people = {state: support.make_employee(totp=False, state=state, full_name=f"Коллега {state}")
              for state in ("active", "invited", "blocked", "dismissed")}
    missing = 999999999
    typed = "Проверить " + " ".join(f"@[{person.pk}]" for person in people.values()) + f" @[{missing}]"
    response = writer.client.post("/feed/posts/", {
        "kind": "post", "text": typed, "to": [],
        "data-mention-names": json.dumps({str(missing): "Подменённое имя"}),
    }, headers=HX if hx else {})
    assert response.status_code == 200
    assert _refusals(response) == [("to", "no_recipients", "Выберите, кому адресована запись")]
    (form,) = _find(_tree(response), "form", id="feed-form")
    (area,) = _find(form, "textarea", name="text")
    assert area.raw_text() == typed
    assert json.loads(area.attrs["data-mention-names"]) == {
        str(people["active"].pk): people["active"].full_name,
    }
    (pill,) = _find(form, data_mentioned=True)
    assert pill.attrs["data-to-pill"] == f"m{people['active'].pk}"
    assert pill.text() == f"{people['active'].full_name} — упомянут"
    assert not _find(pill, "input", name="to")
    assert not _find(pill, "button", data_action="to-remove")
    assert not _find(form, "input", name="to"), "retry не возвращает default «Всем» вместо пустого ввода"
    assert support.model("feed.Post").objects.count() == 0


def test_hx_pdn_warning_keeps_form_values_then_confirmation_creates_one_post_and_clears_oob():
    writer = feed.as_writer()
    colleague = support.make_employee(totp=False)
    address = feed.email_of("hx.followup", "example.org")
    hostile = '<script>alert(1)</script><img src=x onerror="alert(2)">'
    typed = f"{hostile} Почта {address}"
    data = {"kind": "post", "text": typed, "to": [f"p{colleague.pk}"]}
    response = writer.client.post("/feed/posts/", data, headers=HX)
    assert response.status_code == 200
    assert response["HX-Retarget"] == "#feed-form"
    assert response["HX-Reswap"] == "outerHTML"
    body = response.content.decode()
    root = _tree(response)
    assert "<html" not in body.lower()
    assert not _find(root, "article") and not _find(root, "ol", id="feed-list")
    (form,) = _find(root, "form", id="feed-form")
    assert "hx-swap-oob" not in form.attrs
    assert _find(form, "textarea", name="text")[0].raw_text() == typed
    assert [node.attrs["value"] for node in _find(form, "input", name="to")] == [f"p{colleague.pk}"]
    (warning,) = _find(form, data_feed_pdn=True)
    assert [item.text() for item in _find(warning, "li", data_feed_pdn_item=True)] == [address]
    assert _find(warning, "button", data_action="pdn-fix")
    assert _find(warning, "button", name="pdn_confirmed", value="1")
    assert hostile not in body and str(escape(hostile)) in body
    assert not _find(root, "script") and not _find(root, "img")
    Post = support.model("feed.Post")
    assert Post.objects.count() == 0

    confirmed = writer.client.post("/feed/posts/", {**data, "pdn_confirmed": "1"}, headers=HX)
    assert confirmed.status_code == 200
    assert "HX-Retarget" not in confirmed and "HX-Reswap" not in confirmed
    assert Post.objects.count() == 1
    post = Post.objects.get()
    assert post.text == typed and post.author_id == writer.user.pk
    root = _tree(confirmed)
    (form,) = _find(root, "form", id="feed-form")
    assert form.attrs["hx-swap-oob"] == "true"
    assert _find(form, "textarea", name="text")[0].raw_text().strip() == ""
    assert not _find(form, data_feed_pdn=True)
    (article,) = _find(root, "article", data_post_id=str(post.pk))
    assert article.parent.tag == "li"
    assert address in article.text()


@pytest.mark.parametrize("typed", ["\x00", "\x00 \t\n \x00"], ids=["nul-only", "nul-whitespace"])
def test_ordinary_nul_blank_is_empty_text_without_post(typed):
    writer = feed.as_writer()
    response = writer.client.post("/feed/posts/", {"kind": "post", "text": typed, "to": ["all"]})
    assert response.status_code == 200
    assert _refusals(response) == [("text", "empty_text", "Напишите текст")]
    (form,) = _find(_tree(response), "form", id="feed-form")
    assert _find(form, "textarea", name="text")[0].raw_text() == typed.replace("\x00", "")
    assert support.model("feed.Post").objects.count() == 0


def test_ordinary_nul_with_text_is_cleaned_before_service_and_saved(monkeypatch):
    from apps.feed.services import posts

    original = posts.publish
    seen = []

    def publish(user, data, **kwargs):
        seen.append(data["text"])
        return original(user, data, **kwargs)

    monkeypatch.setattr(posts, "publish", publish)
    writer = feed.as_writer()
    response = writer.client.post("/feed/posts/", {"kind": "post", "text": "При\x00вет\x00", "to": ["all"]})
    assert response.status_code == 302 and response["Location"] == "/"
    assert seen == ["Привет"]
    post = support.model("feed.Post").objects.get()
    assert post.text == "Привет"


@pytest.mark.parametrize("hx", [False, True], ids=["ordinary", "hx"])
@pytest.mark.parametrize("field,extra,expected", [
    ("term", {"term": ""}, [("term", "term_required", "Выберите срок")]),
    ("until", {"term": "date", "until": ""}, [("until", "invalid_until", "Укажите корректную дату")]),
    ("until", {"term": "date", "until": "2026-02-30"}, [("until", "invalid_until", "Укажите корректную дату")]),
])
def test_http_important_red_when_not_yet_wired(hx, field, extra, expected):
    """HTTP-публикация вида «Важное» ещё не подключена к форме.

    Ожидание: POST обычный и HTMX возвращают 200, отказ у нужного поля,
    форма сохраняет введённый текст, публикации не создаётся.
    """
    writer = feed.as_writer()
    text = "Важное сообщение"
    data = {"kind": "important", "text": text, "to": ["all"], **extra}
    response = writer.client.post("/feed/posts/", data, headers=HX if hx else {})
    assert response.status_code == 200, \
        "HTTP-публикация вида «Важное» ещё не подключена к форме: ожидается 200 с формой отказа"
    assert _refusals(response) == expected
    (form,) = _find(_tree(response), "form", id="feed-form")
    assert _find(form, "textarea", name="text")[0].raw_text() == text
    assert support.model("feed.Post").objects.count() == 0
    assert support.model("feed.Recipient").objects.count() == 0
