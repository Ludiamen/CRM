"""T-7260: DOM-target регрессии ленты (FR-611, FR-627, NFR-605).

Проверяет два DOM-исправления:
1. `feed/_form_comment.html` содержит локальный `[data-feed-pick-list="mention"]`.
2. `feed/body.html` и `feed/card.html` содержат ровно один `#feed-synced` снаружи `#feed-live`.

Код среза на уровне модуля не импортируется.
"""
from html.parser import HTMLParser
from pathlib import Path

import pytest
from django.template import Context, Template
from django.utils import timezone


@pytest.fixture(autouse=True)
def valkey_clean(request):
    """Этот файл не использует БД/Valkey: шаблоны рендерятся без стенда."""
    yield None


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

BASE_DIR = Path(__file__).resolve().parent.parent


class _Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.children = []

    def walk(self):
        for child in self.children:
            if isinstance(child, _Node):
                yield child
                yield from child.walk()

    def find(self, tag=None, **attrs):
        wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
        found = []
        for node in self.walk():
            if tag is not None and node.tag != tag:
                continue
            ok = True
            for name, value in wanted.items():
                if value is True:
                    if name not in node.attrs:
                        ok = False
                        break
                elif value is False:
                    if name in node.attrs:
                        ok = False
                        break
                elif node.attrs.get(name) != value:
                    ok = False
                    break
            if ok:
                found.append(node)
        return found

    def first(self, tag=None, **attrs):
        found = self.find(tag, **attrs)
        return found[0] if found else None

    def is_inside(self, ancestor):
        node = self.parent
        while node is not None:
            if node is ancestor:
                return True
            node = node.parent
        return False


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = _Node("#root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in _VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(_Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def _tree(html: str) -> _Node:
    parser = _Tree()
    parser.feed(html)
    return parser.root


def _render(template_name: str, context: dict) -> str:
    """Рендерит шаблон напрямую, без context-процессоров (не требует БД)."""
    source = (BASE_DIR / "templates" / template_name).read_text(encoding="utf-8")
    return Template(source).render(Context(context))


def _post(pk=7):
    class _Post:
        pass

    post = _Post()
    post.pk = pk
    return post


def _comment(pk=11):
    class _Comment:
        pass

    c = _Comment()
    c.pk = pk
    return c


def _flt(f="all"):
    class _Flt:
        pass

    flt = _Flt()
    flt.f = f
    return flt


# --- (A) форма комментария ----------------------------------------------------------------------------------------


def test_comment_form_renders_single_mention_pick_list():
    """FR-611: у формы комментария есть ровно один локальный список упоминаний."""
    html = _render(
        "feed/_form_comment.html",
        {"post": _post(7), "text": "", "errors": {}, "pdn_found": False},
    )
    doc = _tree(html)
    form = doc.first("form", data_feed_comment_form=True)
    assert form is not None, "форма комментария не найдена"
    lists = form.find("div", data_feed_pick_list=True)
    assert len(lists) == 1, f"ожидался 1 pick-list, найдено {len(lists)}"
    assert lists[0].attrs.get("data-feed-pick-list") == "mention", "pick-list не mention"
    textarea = form.first("textarea", data_feed_picker="mention")
    assert textarea is not None, "textarea без data-feed-picker=mention"


def test_comment_form_has_no_to_pick_list():
    """FR-611: в форме комментария нет списка адресатов 'to'."""
    html = _render(
        "feed/_form_comment.html",
        {"post": _post(7), "text": "", "errors": {}, "pdn_found": False},
    )
    doc = _tree(html)
    form = doc.first("form", data_feed_comment_form=True)
    assert form.first("div", data_feed_pick_list="to") is None


def test_comment_form_pick_list_is_local_to_each_form():
    """FR-611: несколько форм комментариев на странице не делят список."""
    source = (
        '{% load static %}'
        '{% include "feed/_form_comment.html" with post=post1 text="" %}'
        '{% include "feed/_form_comment.html" with post=post2 text="" %}'
    )
    html = Template(source).render(Context({"post1": _post(7), "post2": _post(9)}))
    doc = _tree(html)
    forms = doc.find("form", data_feed_comment_form=True)
    assert len(forms) == 2
    for form in forms:
        lists = form.find("div", data_feed_pick_list="mention")
        assert len(lists) == 1, "у каждой формы должен быть свой mention pick-list"
        assert lists[0].is_inside(form)


# --- (B) #feed-synced на страницах с WS ----------------------------------------------------------------------------


@pytest.mark.parametrize("layout", ["layouts/fragment.html", "base.html"])
def test_home_page_has_feed_synced_target_outside_feed_live(layout):
    """FR-627: на главной ровно один #feed-synced снаружи #feed-live."""
    html = _render(
        "feed/body.html",
        {
            "layout": layout,
            "ws_url": "/ws/feed/",
            "opened": timezone.now(),
            "filter_options": [],
            "filter_values": {},
            "date_from": "",
            "date_to": "",
            "flt": _flt("all"),
            "posts": [],
            "important": None,
            "filtered": False,
        },
    )
    doc = _tree(html)
    live = doc.first(id="feed-live")
    synced = doc.first(id="feed-synced")
    assert live is not None, "нет #feed-live"
    assert synced is not None, "нет #feed-synced"
    assert not synced.is_inside(live), "#feed-synced не должен быть внутри #feed-live"
    assert len(doc.find(id="feed-synced")) == 1, "#feed-synced должен быть один"


@pytest.mark.parametrize("layout", ["layouts/fragment.html", "base.html"])
def test_card_page_has_feed_synced_target_outside_feed_live(layout):
    """FR-627: на карточке записи ровно один #feed-synced снаружи #feed-live."""
    html = _render(
        "feed/card.html",
        {
            "layout": layout,
            "ws_url": "/ws/feed/?post=7",
            "opened": timezone.now(),
            "posts": [],
        },
    )
    doc = _tree(html)
    live = doc.first(id="feed-live")
    synced = doc.first(id="feed-synced")
    assert live is not None
    assert synced is not None
    assert not synced.is_inside(live)
    assert len(doc.find(id="feed-synced")) == 1


@pytest.mark.parametrize(
    "template,context",
    [
        ("feed/form.html", {}),
        (
            "feed/form_edit.html",
            {"post": _post(7), "comment": _comment(11)},
        ),
        (
            "feed/form_comment_edit.html",
            {"post": _post(7), "comment": _comment(11)},
        ),
    ],
)
def test_non_feed_pages_have_no_feed_synced_target(template, context):
    """FR-627: на страницах без WS-target не появляется лишний #feed-synced."""
    ctx = {"layout": "layouts/fragment.html"}
    ctx.update(context)
    html = _render(template, ctx)
    doc = _tree(html)
    assert doc.first(id="feed-synced") is None
    assert doc.first(id="feed-live") is None


def test_home_page_feed_synced_survives_feed_live_innerhtml_swap():
    """FR-627: #feed-synced снаружи #feed-live, поэтому innerHTML-замена содержимого #feed-live его не трогает."""
    html = _render(
        "feed/body.html",
        {
            "layout": "layouts/fragment.html",
            "ws_url": "/ws/feed/",
            "opened": timezone.now(),
            "filter_options": [],
            "filter_values": {},
            "date_from": "",
            "date_to": "",
            "flt": _flt("all"),
            "posts": [],
            "important": None,
            "filtered": False,
        },
    )
    doc = _tree(html)
    live = doc.first(id="feed-live")
    synced = doc.first(id="feed-synced")
    assert live is not None and synced is not None
    # имитируем innerHTML-своп: родитель live и synced должен быть общим
    assert live.parent is synced.parent, "#feed-synced должен быть соседним с #feed-live"
    # synced расположен после live в DOM-порядке
    siblings = live.parent.children
    live_index = next(i for i, n in enumerate(siblings) if isinstance(n, _Node) and n is live)
    synced_index = next(i for i, n in enumerate(siblings) if isinstance(n, _Node) and n is synced)
    assert synced_index > live_index, "#feed-synced должен идти после #feed-live"
