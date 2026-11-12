"""T-7260: чистые проверки разметки reset-формы публикации (без JS/браузера).

Фиксирует только структуру шаблонов, которую использует патч `feed.js`
(узкое исключение для OOB reset-формы `#feed-form`):

1. `feed/_form.html` при `form_oob=True` рендерит ровно одну
   `form#feed-form[data-feed-form]` с `hx-swap-oob="true"` — контракт
   OOB outerHTML-замены после успешной публикации.
2. Свежая форма (контекст успешной публикации без данных) рендерит таблетку
   `all` по умолчанию, а не остаточную таблетку адресата `unit`.
3. `feed/_publish_response.html` включает reset-форму вместе с элементами
   записи (`_post`).

Это НЕ проверка JS-события: решение о допуске/отмене swap принимает `feed.js`
на `htmx:oobBeforeSwap`; здесь закрепляется только ожидаемая структура ответа.
Код среза на уровне модуля не импортируется; БД/Valkey не используются.
"""
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

import pytest
from django.template import Context, Template


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


class _Attr:
    """Простой держатель атрибутов (имитация объектов контекста без ORM)."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


def _form_context(**overrides) -> dict:
    """Контекст формы в форме успешной публикации (`form_context(user, oob=True)`): без данных,
    адресат по умолчанию — «Всем»."""
    context = {
        "form_values": {
            "text": "", "until": "", "event_title": "", "event_place": "",
            "event_start": "", "event_end": "", "kind": "post", "term": "day",
        },
        "form_kinds": (("post", "Сообщение"), ("important", "Важное"), ("event", "Событие")),
        "form_terms": (("day", "День"), ("week", "Неделя"), ("month", "Месяц"), ("date", "До даты")),
        "form_can_all": True,
        "form_pills": [{"value": "all", "label": "Всем"}],
        "form_mentioned": [],
        "form_files": [],
        "form_mention_names": "{}",
        "form_until": "",
        "form_errors": {},
        "pdn_found": False,
        "form_oob": False,
    }
    context.update(overrides)
    return context


def _item(pk=7):
    """Элемент записи для `feed/_post.html` (вид `post`, без комментариев/файлов/лайков)."""
    post = _Attr(
        pk=pk,
        author_id=1,
        author=_Attr(full_name="Автор", state="active"),
        published_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
        edited_at=None,
        kind="post",
    )
    card = _Attr(
        recipients=_Attr(items=["Всем"], more=None),
        files=[],
        liked=False,
        likes=[],
        like_count=0,
        comment_count=0,
    )
    return _Attr(
        post=post,
        card=card,
        photo_url=None,
        body_html="Текст записи",
        comments=[],
        can_edit=False,
        can_delete=False,
    )


def _publish_response_context(**overrides) -> dict:
    """Контекст `feed/_publish_response.html`: reset-форма + одна запись."""
    context = _form_context(form_oob=True)
    context.update({
        "posts": [_item(7)],
        "link_staff": False,
        "is_moderator": False,
        "opened": datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc),
    })
    context.update(overrides)
    return context


# --- (1) OOB reset-форма --------------------------------------------------------------------------------------------


def test_oob_form_renders_single_feed_form_with_hx_swap_oob():
    """Контракт OOB outerHTML-замены: ровно одна `form#feed-form[data-feed-form]` с `hx-swap-oob="true"`."""
    html = _render("feed/_form.html", _form_context(form_oob=True))
    doc = _tree(html)
    forms = doc.find("form", id="feed-form")
    assert len(forms) == 1, f"ожидалась одна form#feed-form, найдено {len(forms)}"
    form = forms[0]
    assert "data-feed-form" in form.attrs, "у формы публикации нет маркера data-feed-form"
    assert form.attrs.get("hx-swap-oob") == "true", "reset-форма не помечена hx-swap-oob=\"true\""


def test_plain_form_without_oob_has_no_hx_swap_oob():
    """Без `form_oob` (обычная форма) атрибут `hx-swap-oob` отсутствует."""
    html = _render("feed/_form.html", _form_context(form_oob=False))
    doc = _tree(html)
    form = doc.first("form", id="feed-form")
    assert form is not None, "форма публикации не найдена"
    assert "hx-swap-oob" not in form.attrs, "обычная форма не должна нести hx-swap-oob"


# --- (2) fresh-форма: таблетка `all` по умолчанию -----------------------------------------------------------------


def test_fresh_form_renders_default_all_pill_not_leftover_unit():
    """Свежая форма (после успешной публикации, без данных) рендерит таблетку `all`, а не остаточную `unit`."""
    html = _render("feed/_form.html", _form_context(form_oob=True))
    doc = _tree(html)
    form = doc.first("form", id="feed-form")
    assert form is not None, "форма публикации не найдена"
    pills = form.find("span", data_to_pill=True)
    values = [pill.attrs.get("data-to-pill") for pill in pills]
    assert values == ["all"], f"ожидалась одна таблетка all, получено {values}"


# --- (3) `_publish_response.html` — reset-форма рядом с записью ----------------------------------------------------


def test_publish_response_includes_reset_form_alongside_post_items():
    """Ответ успешной публикации содержит reset-форму (`hx-swap-oob`) и элемент записи `_post`."""
    html = _render("feed/_publish_response.html", _publish_response_context())
    doc = _tree(html)
    forms = doc.find("form", id="feed-form")
    assert len(forms) == 1, f"ожидалась одна form#feed-form, найдено {len(forms)}"
    assert forms[0].attrs.get("hx-swap-oob") == "true", "reset-форма в ответе публикации без hx-swap-oob"
    article = doc.first("article", id="feed-post-7")
    assert article is not None, "ответ публикации не содержит запись"
    assert article.parent.tag == "li", "запись должна быть обёрнута в li (hx-target #feed-list afterbegin)"
