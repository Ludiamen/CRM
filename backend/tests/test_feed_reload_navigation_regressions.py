"""Навигация при более 50 новых записях и сохранение загрузки плашки (FR-627)."""

from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from django.template import Context, Template


@pytest.fixture(autouse=True)
def valkey_clean(request):
    """Рендер шаблонов без обращения к БД и Valkey."""
    yield None


_TEMPLATES = Path(__file__).resolve().parent.parent / 'templates'
_FILTERED_URL = '/?f=mentions&author=42&from=2026-01-02&to=2026-03-04'


class _Links(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.banner = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        if tag == 'div' and attributes.get('id') == 'feed-new':
            self.banner.append(attributes)
        if tag == 'a':
            self.current = {'attrs': attributes, 'text': ''}
            self.links.append(self.current)

    def handle_data(self, data):
        if self.current is not None:
            self.current['text'] += data

    def handle_endtag(self, tag):
        if tag == 'a':
            self.current = None


def _render(name, context):
    source = (_TEMPLATES / 'feed' / name).read_text(encoding='utf-8')
    html = Template(source).render(Context(context))
    parser = _Links()
    parser.feed(html)
    return parser


def _response(has_more):
    return _render('_new_response.html', {
        'posts': [], 'important': [], 'badge_oob': False, 'newest': None,
        'has_more': has_more, 'reload_url': _FILTERED_URL,
    })


def _reload_links(document):
    return [link for link in document.links if 'data-feed-reload' in link['attrs']]


def _one_reload():
    links = _reload_links(_response(True))
    assert len(links) == 1, 'ожидалась одна ссылка перезагрузки'
    return links[0]


@pytest.mark.parametrize('attribute', ['hx-get', 'hx-target', 'hx-swap'])
def test_show_all_is_not_intercepted_by_htmx(attribute):
    assert attribute not in _one_reload()['attrs'], 'ссылка перезагрузки не должна перехватываться HTMX'


def test_show_all_preserves_filter_query_in_href():
    href = urlsplit(_one_reload()['attrs']['href'])
    assert href.path == '/'
    assert parse_qs(href.query) == {
        'f': ['mentions'], 'author': ['42'], 'from': ['2026-01-02'], 'to': ['2026-03-04'],
    }


def test_show_all_preserves_hook_label_and_css():
    link = _one_reload()
    assert 'data-feed-reload' in link['attrs']
    assert link['text'].strip() == 'Показать все'
    assert set(link['attrs']['class'].split()) == {'btn', 'btn-outline-primary'}


def test_no_show_all_link_without_more_results():
    assert _reload_links(_response(False)) == []


def test_banner_load_remains_htmx_and_oob():
    document = _render('_new_banner.html', {'count': 1, 'link': 'f=mentions&author=42'})
    assert len(document.banner) == 1
    assert document.banner[0].get('hx-swap-oob') == 'true'
    links = [link for link in document.links if 'data-feed-new-load' in link['attrs']]
    assert len(links) == 1
    attrs = links[0]['attrs']
    assert urlsplit(attrs['href']).path == '/feed/new/'
    assert attrs['hx-get'] == attrs['href']
    assert parse_qs(urlsplit(attrs['hx-get']).query) == {'f': ['mentions'], 'author': ['42']}
