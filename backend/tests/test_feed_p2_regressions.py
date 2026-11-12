"""T-7260: серверные регрессии фиксов P2 приёмки среза 007 (browser-gate, триаж 106 — G4/G11/G13; разбор G10/G12).

- G4 (FR-614): перенос прочитанной важной записи из блока в ленту не выбрасывает карточку за границу
  видимой страницы — фикc в `static/feed/feed.js` (обработчик `htmx:beforeSwap`). Логика переноса
  прогоняется изолированным harness `tests/harness_feed_read_move.js` (node, без браузера);
  здесь — статический guard фикса. Вторая половина G4 (истёкшая запись в ленте) и G13 — правки потока
  e2e-тестов, обоснованные в отчёте патии.
- G11 (FR-633/FR-634, CONTRACT-007 12.6): у «чистой» картинки с эскизом видно и имя файла — сценарий 10
  п. 1 спеки ждёт имена у прикреплённых файлов независимо от того, успела ли проверка закончиться
  (быстрый ClamAV: состояние уже `clean` при том же запросе).
- G10/G12 (FR-602/FR-626/FR-638, CONTRACT-007 10.2:656-657): первая страница ленты — 20 записей;
  состаренная запись может не попасть на неё — контракт доходит до неё кнопкой «Ещё записи» и карточкой.
  Ожидание «все N на первой странице» (e2e f08 п. 9 / f12) пагинации контракта противоречит — вывод
  для владельца в отчёте патии, e2e не менялись.

Шаблоны рендерятся напрямую (без БД); один тест с БД (метка `django_db`) повторяет приёмы
test_feed_page.py. Код среза на уровне модуля не импортируется.
"""
from datetime import timedelta
from html.parser import HTMLParser
from pathlib import Path

import pytest
import redis
from django.conf import settings
from django.utils import timezone
from zoneinfo import ZoneInfo

from tests import support
from tests import support_feed as feed


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

BASE_DIR = Path(__file__).resolve().parent.parent


@pytest.fixture(autouse=True)
def valkey_clean(request):
    """Тесты без БД не ходят в Valkey; тест с меткой `django_db` чистит его перед собой (как весь файл)."""
    if "django_db" in request.keywords:
        client = redis.Redis.from_url(settings.VALKEY_URL)
        client.flushdb()
        yield client
        client.close()
    else:
        yield None


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
            if all(name in node.attrs and (value is True or node.attrs[name] == value)
                   for name, value in wanted.items()):
                found.append(node)
        return found

    def first(self, tag=None, **attrs):
        found = self.find(tag, **attrs)
        return found[0] if found else None

    def text(self) -> str:
        return " ".join(part.strip() for part in _texts(self) if part.strip()).strip()


def _texts(node):
    for child in node.children:
        if isinstance(child, str):
            yield child
        else:
            yield from _texts(child)


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


def _tree(response) -> _Node:
    html = response if isinstance(response, str) else response.content.decode("utf-8")
    parser = _Tree()
    parser.feed(html)
    return parser.root


def _render(template_name: str, context: dict) -> str:
    """Рендерит шаблон напрямую, без context-процессоров (не требует БД)."""
    source = (BASE_DIR / "templates" / template_name).read_text(encoding="utf-8")
    from django.template import Context, Template

    return Template(source).render(Context(context))


class _Attr:
    """Простой держатель атрибутов (имитация объектов контекста без ORM)."""

    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


# --- G11: имя файла видно у «чистой» картинки с эскизом -------------------------------------------------------------


def _feed_file(pk=11, name="экран3e884d.png", status="clean", thumb="attachments/thumbs/11.webp", size=1024):
    return _Attr(pk=pk, name=name, thumb=thumb, file=_Attr(status=status, size=size))


def test_files_pill_clean_image_shows_name_beside_thumbnail():
    """G11 (FR-633, 12.6): «чистая» картинка с эскизом — `a > img` по контракту и имя файла видимым текстом.

    Быстрая проверка ClamAV успевает закончиться до отклика публикации: таблетка сразу в состоянии
    `clean`, и имя должно оставаться видимым (сценарий 10 п. 1 спеки: «их имена»), иначе приёмка,
    фильтрующая таблетки по тексту имени, не находит файл.
    """
    doc = _tree(_render("feed/_files.html", {"file": _feed_file()}))
    pill = doc.first("span", data_feed_file="11")
    assert pill is not None, "таблетка файла не отрисована"
    assert pill.attrs.get("data-file-state") == "clean"
    link = pill.first("a", href="/feed/files/11/")
    assert link is not None, "нет ссылки на оригинал (12.6)"
    assert link.first("img", src="/feed/files/11/thumb/") is not None, "нет эскиза (12.6)"
    assert "экран3e884d.png" in pill.text(), "имя файла не видно рядом с эскизом"


def test_files_pill_pending_and_quarantine_keep_name_and_no_link():
    """G11 (12.6): «проверяется» и «карантин» — имя и пометка, без ссылки (прежнее поведение)."""
    doc = _tree(_render("feed/_files.html", {"file": _feed_file(status="pending", thumb="")}))
    pill = doc.first("span", data_feed_file="11")
    assert "экран3e884d.png" in pill.text() and "проверяется" in pill.text()
    assert pill.first("a") is None
    doc = _tree(_render("feed/_files.html", {"file": _feed_file(status="quarantine", thumb="")}))
    pill = doc.first("span", data_feed_file="11")
    assert "экран3e884d.png" in pill.text() and "карантин" in pill.text()
    assert pill.first("a") is None


def test_files_pill_clean_without_thumb_shows_name_size_and_download():
    """G11 (12.6, К70): «чистый» без эскиза — имя, размер и «Скачать» (прежнее поведение)."""
    doc = _tree(_render("feed/_files.html", {"file": _feed_file(status="clean", thumb="", name="документb97a3d.pdf")}))
    pill = doc.first("span", data_feed_file="11")
    assert "документb97a3d.pdf" in pill.text()
    assert pill.first("span", data_file_size=True) is not None, "нет размера (К70)"
    assert pill.first("a", href="/feed/files/11/") is not None, "нет «Скачать»"


# --- G4: перенос прочитанной записи — статический guard фикса -------------------------------------------------------


def test_feed_js_read_move_keeps_card_at_any_page_position():
    """G4 (FR-614): обработчик переноса не выбрасывает карточку за границу видимой страницы.

    Логика переноса проверяется изолированным harness `tests/harness_feed_read_move.js`
    (настоящий `feed.js`, DOM-заглушка, синтетическое событие htmx 2.0.11): карточка старше
    последней строки, новее первой и единственная в пустой ленте обязана встать в `#feed-list`.
    Здесь — guard: прежние условия отбрасывания вернуться не должны.
    """
    source = (BASE_DIR / "static" / "feed" / "feed.js").read_text(encoding="utf-8")
    start = source.index("htmx:beforeSwap")
    end = source.index("function state(form)")
    handler = source[start:end]
    assert "at > newest || at < oldest" not in handler, "карточку вне времени страницы снова отбрасывают"
    assert "!cards.length" not in handler, "перенос в пустую ленту снова запрещён"
    assert "list.appendChild(row)" in handler, "нет вставки единственной строки в пустую ленту"
    assert (BASE_DIR / "tests" / "harness_feed_read_move.js").exists(), "пропал изолированный harness переноса"


# --- G10/G12: пагинация контракта и состаренная запись --------------------------------------------------------------


@pytest.mark.django_db
def test_aged_post_beyond_first_page_is_reachable_by_more_link_and_card():
    """G10/G12 (FR-602/FR-626/FR-638, CONTRACT-007 10.2:656-657): первая страница — 20 записей от новых
    к старым; состаренная запись не обязана попадать на неё: контракт доходит до неё кнопкой
    «Ещё записи», фильтром периода публикации и карточкой, удаления нет. Ожидание e2e «все N записей
    на первой странице» пагинации контракта противоречит (вывод для владельца — отчёт патии T7260-p2-fix)."""
    author = feed.as_writer()
    reader = feed.as_plain()
    now = timezone.now()
    fresh = [feed.make_post(author.user, "post", to=("all",), text=f"Свежая {index}",
                            published_at=now - timedelta(minutes=40 - 2 * index)) for index in range(20)]
    aged = feed.make_post(author.user, "post", to=("all",), text="Состаренная почти три года",
                          published_at=now - timedelta(days=3 * 365))

    doc = _tree(reader.client.get("/"))
    first = [int(node.attrs["data-post-id"]) for node in doc.find("article", data_post_id=True)]
    assert len(first) == 20, f"первая страница — {len(first)} записей, контракт ждёт 20 (10.2:656)"
    assert all(post.pk in first for post in fresh)
    assert aged.pk not in first, "состаренная запись не на первой странице — это норма пагинации"

    more = doc.first(data_feed_more=True)
    assert more is not None, "нет кнопки «Ещё записи»"
    assert more.attrs.get("hx-get", "").startswith("/feed/more/")
    second = _tree(reader.client.get(more.attrs["hx-get"], **support.HX))
    rest = [int(node.attrs["data-post-id"]) for node in second.find("article", data_post_id=True)]
    assert aged.pk in rest, "состаренной записи нет на следующей странице (10.2:657)"

    # фильтр периода публикации выводит состаренную запись на первую страницу (FR-635, К64)
    day = aged.published_at.astimezone(ZoneInfo("Europe/Moscow")).date()
    filtered = _tree(reader.client.get(f"/?from={day.isoformat()}&to={day.isoformat()}"))
    ids = [int(node.attrs["data-post-id"]) for node in filtered.find("article", data_post_id=True)]
    assert ids == [aged.pk], "фильтр периода не выводит состаренную запись на первую страницу"

    assert reader.client.get(f"/feed/{aged.pk}/").status_code == 200, "карточка состаренной записи не жива (FR-638)"


# --- G13: уникальность проверки события в e2e (загрязнение сессии admin_page) ---------------------------------------


def test_f15_event_pdn_negative_check_uses_unique_title():
    """G13: негативная проверка «события нет в ленте» адресуется уникальным названием этого теста.

    Слово «пишите» без маркера встречается в легально опубликованных (с подтверждением) записях и
    комментариях прежних тестов того же admin_page (test_f15_pdn.py:156) — прежняя проверка ловила их.
    Продукт здесь верен: ПДн в названии события даёт предупреждение (серверный
    test_feed_pdn.py::test_pdn_in_event_title_or_place_shows_warning), публикация без подтверждения нет.
    """
    source = (BASE_DIR / "tests" / "e2e" / "test_f15_pdn.py").read_text(encoding="utf-8")
    assert 'not_to_contain_text("пишите")' not in source, "проверка снова использует неуникальное слово"
    assert 'not_to_contain_text(f"Собрание {word}, пишите")' in source, "нет проверки уникальным названием"
