"""T-5119: карточка заявки и база знаний — публичная служба `servicedesk`, части карточки, раздел «Статьи», привязка
и отвязка статей, подбор статьи (FR-427, FR-429, FR-432, FR-433). Сценарии 3 и 8 спеки.

Что проверяется: `servicedesk.services.public` (`TicketBrief`, `ticket_brief`, `briefs`); вызов записей точки
`ticket_card_parts` из карточки (снимок разметки среза 003, сбой части, «модуль выключен», граница импортов);
раздел «Статьи» (место в разметке, видимость по состоянию статьи и роли, «кто и когда привязал»); POST `/kb/links/` и
`/kb/links/<id>/delete/` (права, 403/404, повтор, журнал не пишется); подбор статьи `/kb/pick/`.
Код среза на уровне модуля не импортируется: имена берутся внутри тестов (CONTRACT-005, шапка).

Снимок `tests/fixtures/ticket_card_slice003.html` снят с карточки до правки `_card.html` (З22, CONTRACT-005 4.3):
сборку входных данных и нормализацию делают `slice003_cards` и `normalize_markup` этого файла — по ним же файл
пересоздаётся (временным тестом-записью, которого в наборе нет).
"""
import ast
import difflib
import logging
import re
from datetime import datetime
from html.parser import HTMLParser
from pathlib import Path

import pytest

from tests import support
from tests import support_kb as kb
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import HX, model

pytestmark = pytest.mark.django_db

SNAPSHOT = Path(__file__).resolve().parent / "fixtures" / "ticket_card_slice003.html"
SNAPSHOT_MARKER = "<!-- snapshot:{} -->"
BOOM_TEXT = "текст-исключения-не-для-журнала"


class CardPartBoom(Exception):
    """Исключение части карточки, которую тест регистрирует в точке."""


# --- разбор разметки (помощник только этого файла) -------------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = {k: (v if v is not None else "") for k, v in attrs}
        self.parent = parent
        self.children = []

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                if isinstance(child, Node):
                    collect(child)
                else:
                    parts.append(child)

        collect(self)
        return " ".join("".join(parts).split())

    def inside(self, other) -> bool:
        node = self.parent
        while node is not None:
            if node is other:
                return True
            node = node.parent
        return False

    def next_element(self):
        """Следующий элемент-сосед (текстовые узлы пропускаются)."""
        siblings = [c for c in self.parent.children if isinstance(c, Node)]
        index = next(i for i, c in enumerate(siblings) if c is self)
        return siblings[index + 1] if index + 1 < len(siblings) else None


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__()
        self.root = Node("#root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in _VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def tree(response_or_html) -> Node:
    html = response_or_html if isinstance(response_or_html, str) else response_or_html.content.decode("utf-8")
    parser = _Tree()
    parser.feed(html)
    return parser.root


def q(scope, tag=None, **attrs) -> list:
    """Потомки `scope` по тегу и атрибутам; имя атрибута с дефисом — через `_` (`data_field="state"`)."""
    wanted = {name.rstrip("_").replace("_", "-"): value for name, value in attrs.items()}

    def match(node) -> bool:
        if tag is not None and node.tag != tag:
            return False
        for name, expected in wanted.items():
            if name not in node.attrs:
                return False
            if expected is not True and node.attrs[name] != expected:
                return False
        return True

    return [node for node in scope.walk() if match(node)]


def q1(scope, tag=None, **attrs):
    found = q(scope, tag, **attrs)
    assert len(found) == 1, f"ожидали один элемент {tag or ''}{attrs}, нашли {len(found)}"
    return found[0]


# --- данные теста ---------------------------------------------------------------------------------------

def _queue_and_ticket(*, closed: bool = False, **over):
    """Очередь и заявка в ней; закрытая — с видом `closed` и решением."""
    queue = sd.make_queue()
    if closed:
        over.setdefault("resolution", "Заменили картридж и обновили драйвер")
        ticket = sd.make_ticket(queue=queue, kind="closed", **over)
    else:
        ticket = sd.make_ticket(queue=queue, **over)
    return queue, ticket


def _member(session, queue):
    """Сотрудник становится участником очереди: он видит её заявки."""
    org.make_member(session.user, queue.unit)
    return session


def _editor(queue, **extra):
    return _member(kb.as_editor(**extra), queue)


def _reader(queue, **extra):
    return _member(kb.as_reader(**extra), queue)


def _manager(queue, **extra):
    return _member(kb.as_manager(**extra), queue)


def _page(client, number):
    response = client.get(f"/tickets/{number}/")
    assert response.status_code == 200, f"карточка #{number}: {response.status_code}"
    return tree(response)


def _part(root, code="kb-articles"):
    """Оболочка части карточки по ключу записи или `None`."""
    found = q(root, "div", data_card_part=code)
    assert len(found) <= 1, f"оболочек {code}: {len(found)}"
    return found[0] if found else None


def _article_rows(root) -> dict:
    """Строки раздела «Статьи»: `{номер статьи: li}`."""
    part = _part(root)
    if part is None:
        return {}
    return {int(li.attrs["data-article-id"]): li for li in q(part, "li", data_link_id=True)}


def _stored_file(ticket, entry, name, *, status="clean"):
    """Принятое вложение заявки: файл `clean`, `owner=None`, строка `Attachment`."""
    StoredFile, Attachment = model("core.StoredFile"), model("servicedesk.Attachment")
    stored = StoredFile.objects.create(purpose="attachment", owner=None, size=5, sha256="0" * 64,
                                       content_type="text/plain", status=status)
    Attachment.objects.create(ticket=ticket, entry=entry, file=stored, name=name, size=5,
                              created_at=stored.created_at)
    return stored


def _links(article=None):
    TicketLink = model("knowledge.TicketLink")
    qs = TicketLink.objects.all()
    return qs.filter(article=article) if article is not None else qs


def _post_link(client, article, ticket, *, hx: bool = True):
    return client.post("/kb/links/", {"article": article.pk, "ticket": ticket.number}, **(HX if hx else {}))


def _post_unlink(client, link, *, hx: bool = True):
    return client.post(f"/kb/links/{link.pk}/delete/", **(HX if hx else {}))


# --- снимок разметки среза 003 (З22) -----------------------------------------------------------------------

def normalize_markup(html: str) -> str:
    """Нормализация без номера заявки и времени: значения `csrfmiddlewaretoken` пусты, каждая цепочка цифр — `0`
    (номера, идентификаторы, отметки времени), пробелы по краям строк убраны, пустые строки выброшены."""
    html = re.sub(r'(name="csrfmiddlewaretoken"\s+value=")[^"]*', r"\1", html)
    html = re.sub(r"\d+", "0", html)
    return "\n".join(line.strip() for line in html.splitlines() if line.strip())


def slice003_cards(clock) -> dict:
    """Карточки открытой и закрытой заявки (НХ-ответ: слайдер) в нормализованном виде.

    Входные данные заданы целиком: часы, названия, ФИО и адрес заявителя — снимок не зависит от запуска."""
    clock.set(kb.moscow(2026, 3, 10, 12, 0))
    unit = org.make_unit("Отдел поддержки")
    queue = sd.make_queue(unit)
    viewer = support.make_employee(full_name="Смотрящий Тестович")
    org.make_member(viewer, unit)
    requester = sd.make_requester(kb.email_of("zayavitel"), full_name="Заявитель Тестов")
    opened = sd.make_ticket(queue=queue, requester=requester, number=9001, subject="Не работает принтер")
    closed = sd.make_ticket(queue=queue, requester=requester, number=9002, kind="closed",
                            subject="Не работает сканер", resolution="Заменили картридж")
    client = support.logged_in(viewer)
    cards = {}
    for name, ticket in (("open", opened), ("closed", closed)):
        response = client.get(f"/tickets/{ticket.number}/", **HX)
        assert response.status_code == 200
        cards[name] = normalize_markup(response.content.decode("utf-8"))
    return cards


def _snapshot_part(name: str) -> str:
    text = SNAPSHOT.read_text(encoding="utf-8")
    parts = re.split(r"<!-- snapshot:(\w+) -->\n", text)
    # parts: ["", имя, текст, имя, текст, ...]
    found = dict(zip(parts[1::2], parts[2::2]))
    assert name in found, f"в снимке нет раздела {name}"
    return found[name].strip()


# --- servicedesk.services.public --------------------------------------------------------------------------

def test_ticket_brief_returns_number_subject_state_and_resolution_for_visible_ticket():
    """FR-427, FR-429: `ticket_brief(user, number)` отдаёт номер, тему, состояние и решение видимой заявки;
    `closed_with_resolution` — заявка закрыта и решение не пусто после `strip()`."""
    from apps.servicedesk.services import public

    queue = sd.make_queue()
    user = support.make_employee()
    org.make_member(user, queue.unit)
    closed = sd.make_ticket(queue=queue, kind="closed", subject="Не печатает принтер",
                            resolution="Заменили картридж")
    blank = sd.make_ticket(queue=queue, kind="closed", resolution="   \n ")
    opened = sd.make_ticket(queue=queue, subject="Новая заявка")

    brief = public.ticket_brief(user, closed.number)
    assert isinstance(brief, public.TicketBrief)
    assert brief.number == closed.number
    assert brief.subject == "Не печатает принтер"
    assert brief.state == closed.status.name
    assert brief.closed_with_resolution is True
    assert brief.resolution == "Заменили картридж"

    assert public.ticket_brief(user, blank.number).closed_with_resolution is False, "пробелы — не решение"
    open_brief = public.ticket_brief(user, opened.number)
    assert open_brief.closed_with_resolution is False
    assert open_brief.state == opened.status.name
    assert open_brief.resolution == ""


def test_ticket_brief_returns_none_for_invisible_ticket():
    """FR-429: невидимая и несуществующая заявка — `None`; видимость — по `access.visible_tickets`."""
    from apps.servicedesk.services import public

    queue, ticket = _queue_and_ticket(closed=True)
    outsider = support.make_employee()
    insider = support.make_employee()
    org.make_member(insider, queue.unit)

    assert public.ticket_brief(outsider, ticket.number) is None
    assert public.ticket_brief(insider, 987654) is None
    assert public.ticket_brief(insider, ticket.number) is not None


def test_ticket_brief_has_no_requester_address_or_correspondence_fields():
    """FR-427: поля `TicketBrief` — ровно пять; ни адреса и имени заявителя, ни переписки, ни вложений."""
    from apps.servicedesk.services import public

    assert public.TicketBrief._fields == ("number", "subject", "state", "closed_with_resolution", "resolution")
    requester = sd.make_requester(kb.email_of("zayavitel"), full_name="Заявитель Секретович")
    queue, ticket = _queue_and_ticket(closed=True, requester=requester)
    sd.make_entry(ticket, "incoming", text="Письмо заявителя про принтер")
    user = support.make_employee()
    org.make_member(user, queue.unit)

    brief = public.ticket_brief(user, ticket.number)
    flat = " | ".join(str(value) for value in brief)
    assert requester.email not in flat
    assert "Секретович" not in flat
    assert "Письмо заявителя" not in flat


def test_briefs_returns_only_visible_tickets_in_one_query(django_assert_num_queries):
    """FR-429: `briefs(user, numbers)` — словарь только видимых заявок одним запросом; пустой список — без запроса."""
    from apps.servicedesk.services import access, public

    queue, first = _queue_and_ticket(subject="Первая")
    second = sd.make_ticket(queue=queue, subject="Вторая", kind="closed", resolution="Готово")
    hidden = sd.make_ticket(queue=sd.make_queue(), subject="Чужая")
    user = support.make_employee()
    org.make_member(user, queue.unit)
    access.scope(user)  # доступ считается один раз на объект пользователя: в подсчёт запросов он не входит

    numbers = [first.number, second.number, hidden.number, 987654]
    with django_assert_num_queries(1):
        result = public.briefs(user, numbers)
    assert sorted(result) == sorted([first.number, second.number])
    assert result[first.number].subject == "Первая"
    assert result[second.number].closed_with_resolution is True
    assert hidden.number not in result and 987654 not in result

    with django_assert_num_queries(0):
        assert public.briefs(user, []) == {}


# --- вызов частей карточки -------------------------------------------------------------------------------

def test_card_without_kb_records_in_ticket_card_parts_matches_slice003_markup(clock):
    """FR-432, FR-433: точка `ticket_card_parts` пуста — карточка открытой и закрытой заявки совпадает со снимком
    среза 003 (`tests/fixtures/ticket_card_slice003.html`): ни оболочек частей, ни пробелов от них."""
    from apps.core import extensions

    with kb.without_registrations("ticket_card_parts"):
        assert extensions.registered("ticket_card_parts") == []
        cards = slice003_cards(clock)

    for name in ("open", "closed"):
        expected = _snapshot_part(name)
        assert "data-card-part" not in cards[name]
        if cards[name] != expected:
            diff = "\n".join(list(difflib.unified_diff(expected.splitlines(), cards[name].splitlines(),
                                                       "снимок", "карточка", lineterm="", n=1))[:40])
            pytest.fail(f"карточка ({name}) без частей не совпала со снимком среза 003:\n{diff}")


def test_card_with_module_disabled_has_no_articles_section_and_no_kb_buttons():
    """FR-433: «модуль выключен» — нет раздела «Статьи», кнопок «Статья из решения», «Привязать статью», «Ссылка на
    статью»; карточка закрытой и открытой заявки работает. С модулем те же три части у редактора есть."""
    queue, closed = _queue_and_ticket(closed=True)
    opened = sd.make_ticket(queue=queue)
    session = _editor(queue)

    with_module = _page(session.client, closed.number)
    for code in ("kb-articles", "kb-from-ticket", "kb-link-tool"):
        assert _part(with_module, code) is not None, f"с включённым модулем нет части {code}"

    with kb.without_knowledge():
        for ticket in (closed, opened):
            response = session.client.get(f"/tickets/{ticket.number}/")
            assert response.status_code == 200
            root = tree(response)
            assert len(q(root, data_ticket_card=True)) == 1
            assert q(root, data_card_part=True) == []
            assert q(root, data_section="kb-articles") == []
            for action in ("kb-from-ticket", "kb-link-add", "kb-link-tool", "kb-unlink"):
                assert q(root, data_action=action) == [], action
            assert q(root, "form", data_form="kb-link") == []
            body = response.content.decode("utf-8")
            for text in ("Статья из решения", "Привязать статью", "Ссылка на статью"):
                assert text not in body, text
            assert len(q(root, "form", data_form="ticket-comment")) == 1
        closed_root = tree(session.client.get(f"/tickets/{closed.number}/"))
        assert len(q(closed_root, data_action="ticket-reopen")) == 1


def test_card_part_raising_exception_is_logged_and_card_renders_without_that_part(caplog):
    """FR-432: исключение записи пишется в журнал приложения (логгер `apps.servicedesk`, уровень ERROR: ключ записи
    и класс исключения, без текста исключения), карточка рисуется без этой части; прочие части остаются."""
    from apps.core import extensions
    from apps.core.extensions import TicketCardPart

    def render(request, ref):
        raise CardPartBoom(BOOM_TEXT)

    def provide():
        return [TicketCardPart(key="boom-part", kind="section", order=5, render=render)]

    queue, ticket = _queue_and_ticket()
    session = _editor(queue)
    extensions.register("ticket_card_parts", provide)
    try:
        with caplog.at_level(logging.ERROR, logger="apps.servicedesk"):
            response = session.client.get(f"/tickets/{ticket.number}/")
    finally:
        extensions._registry["ticket_card_parts"].remove(provide)

    assert response.status_code == 200
    root = tree(response)
    assert len(q(root, data_ticket_card=True)) == 1
    assert q(root, data_card_part="boom-part") == [], "часть с исключением не выводится"
    assert _part(root) is not None, "остальные части карточки на месте"
    # п. 45 раздела 17: одна запись ERROR логгера `apps.servicedesk`; в `getMessage()` ключ части и имя класса
    records = [r for r in caplog.records if r.levelno == logging.ERROR and r.name == "apps.servicedesk"]
    assert len(records) == 1, [r.getMessage() for r in caplog.records]
    assert "boom-part" in records[0].getMessage() and "CardPartBoom" in records[0].getMessage(), \
        records[0].getMessage()
    assert all(BOOM_TEXT not in r.getMessage() for r in caplog.records), "текст исключения в журнал не пишется"
    assert BOOM_TEXT not in response.content.decode("utf-8")


def test_servicedesk_package_does_not_import_knowledge():
    """FR-432: пакет `apps/servicedesk` не импортирует `apps.knowledge` и `apps.search` (инвариант «модуль-приложение»);
    разбор `ast`: обычные и относительные импорты, строки `import_module(...)`."""
    root = Path(__file__).resolve().parents[1] / "apps" / "servicedesk"
    assert root.is_dir(), root
    banned = ("apps.knowledge", "apps.search")
    offenders = []
    for path in sorted(root.rglob("*.py")):
        module = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(module):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                base = node.module or ""
                names = [base] + [f"{base}.{alias.name}" for alias in node.names]
                if node.level and base.split(".")[0] in ("knowledge", "search"):
                    names.append("apps." + base)
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                names = [node.value] if re.fullmatch(r"apps\.(knowledge|search)(\.[\w.]+)?", node.value) else []
            if any(name == b or name.startswith(b + ".") for name in names for b in banned):
                offenders.append(f"{path.relative_to(root.parent.parent)}:{getattr(node, 'lineno', '?')}")
    assert not offenders, offenders


# --- раздел «Статьи» ---------------------------------------------------------------------------------------

def test_articles_section_follows_attachments_block_and_shown_for_ticket_without_attachments():
    """FR-429, FR-432: оболочка `kb-articles` — в `[data-card-fields]` сразу после блока «Вложения»; у заявки без
    вложений раздел всё равно есть; `data-section="attachments"` остаётся ровно один и не у «Статей»."""
    queue, with_files = _queue_and_ticket()
    entry = sd.make_entry(with_files, "comment", text="Файл во вложении")
    _stored_file(with_files, entry, "схема.txt")
    without_files = sd.make_ticket(queue=queue)
    session = _editor(queue)

    root = _page(session.client, with_files.number)
    fields = q1(root, data_card_fields=True)
    wrapper = q1(fields, "div", data_card_part="kb-articles")
    assert wrapper.attrs["data-part-kind"] == "section"
    attachments = q1(root, data_section="attachments")
    assert attachments.inside(fields) and not wrapper.inside(attachments) and not attachments.inside(wrapper)
    assert attachments.next_element() is wrapper, "раздел «Статьи» стоит сразу после блока «Вложения»"
    inner = q1(wrapper, "section", data_section="kb-articles")
    assert "card-section" in inner.attrs.get("class", "").split()

    root = _page(session.client, without_files.number)
    assert q(root, data_section="attachments") == []
    fields = q1(root, data_card_fields=True)
    wrapper = q1(fields, "div", data_card_part="kb-articles")
    assert wrapper.inside(fields)
    assert q1(wrapper, "section", data_section="kb-articles") is not None


def test_section_shows_published_linked_article_to_everyone_who_sees_ticket():
    """FR-429: опубликованная связанная статья видна всем, кто видит заявку (читатель, редактор, управляющий);
    не видящему заявку карточка недоступна (404). Кнопка «Отвязать» — только при праве «Редактирование»."""
    queue, ticket = _queue_and_ticket()
    article = kb.make_published(title="Как настроить принтер")
    link = kb.link_ticket(article, ticket.number)
    viewers = {"reader": _reader(queue), "editor": _editor(queue), "manager": _manager(queue)}

    for role, session in viewers.items():
        root = _page(session.client, ticket.number)
        rows = _article_rows(root)
        assert list(rows) == [article.pk], role
        row = rows[article.pk]
        assert row.attrs["data-link-id"] == str(link.pk)
        title = q1(row, "a", data_field="title")
        assert title.text() == "Как настроить принтер"
        assert f"/kb/{article.pk}/" in title.attrs["href"]
        # п. 44 раздела 17: `[data-field="state"]` бывает только у черновика; у опубликованной статьи его нет
        assert q(row, data_field="state") == [], role
        unlink = q(row, "button", data_action="kb-unlink")
        assert bool(unlink) == (role != "reader"), role

    outsider = kb.as_reader()
    assert outsider.client.get(f"/tickets/{ticket.number}/").status_code == 404


def test_section_shows_draft_linked_article_only_to_author_and_manager():
    """FR-429: связанный черновик виден автору (с правом) и управляющему — с пометкой «черновик»; другому редактору и
    читателю — нет; у читателя без видимых связей части нет (З9), у редактора раздел с формой выводится всегда."""
    queue, ticket = _queue_and_ticket()
    author = _editor(queue)
    draft = kb.make_draft(title="Черновик про принтер", author=author.user)
    kb.link_ticket(draft, ticket.number, user=author.user)

    root = _page(author.client, ticket.number)
    row = _article_rows(root)[draft.pk]
    assert "черновик" in q1(row, data_field="state").text().lower()

    root = _page(_manager(queue).client, ticket.number)
    assert draft.pk in _article_rows(root)
    assert "черновик" in q1(_article_rows(root)[draft.pk], data_field="state").text().lower()

    root = _page(_editor(queue).client, ticket.number)
    assert _part(root) is not None and q1(root, "form", data_form="kb-link") is not None
    assert _article_rows(root) == {}, "чужой черновик другому редактору не показывается"

    root = _page(_reader(queue).client, ticket.number)
    assert _part(root) is None, "читателю без видимых связей части нет"
    assert "Черновик про принтер" not in str(root.text())


def test_section_hides_trashed_linked_article_from_everyone_and_restore_brings_it_back():
    """FR-429: пока статья в корзине, связь скрыта у всех (и у управляющего); возврат из корзины возвращает её
    с той же связью. Корзина и возврат — по маршрутам `/kb/<id>/trash/` и `/kb/<id>/restore/`."""
    queue, ticket = _queue_and_ticket()
    article = kb.make_published(title="Принтер: замена картриджа")
    link = kb.link_ticket(article, ticket.number)
    manager = _manager(queue)
    reader = _reader(queue)
    editor = _editor(queue)
    assert article.pk in _article_rows(_page(reader.client, ticket.number))

    response = manager.client.post(f"/kb/{article.pk}/trash/")
    assert response.status_code < 400, response.status_code
    assert model("knowledge.Article").objects.get(pk=article.pk).state == "trash"
    for session in (reader, editor, manager):
        assert article.pk not in _article_rows(_page(session.client, ticket.number))
    assert _links(article).filter(pk=link.pk).exists(), "в корзине связь не удаляется"

    response = manager.client.post(f"/kb/{article.pk}/restore/")
    assert response.status_code < 400, response.status_code
    for session in (reader, editor, manager):
        rows = _article_rows(_page(session.client, ticket.number))
        assert rows[article.pk].attrs["data-link-id"] == str(link.pk)


def test_section_shows_who_linked_and_when(clock):
    """FR-429: рядом со статьёй — кто привязал (`[data-field="linked-by"]`) и когда (`time[data-at]`, время по Москве)."""
    clock.set(kb.moscow(2026, 10, 19, 14, 30))
    queue, ticket = _queue_and_ticket()
    linker = support.make_employee(full_name="Привязкин Пётр")
    kb.grant(linker, "knowledge.edit")
    org.make_member(linker, queue.unit)
    article = kb.make_published(title="Статья про принтер")
    link = kb.link_ticket(article, ticket.number, user=linker)
    reader = _reader(queue, full_name="Смотрящий Иван")

    row = _article_rows(_page(reader.client, ticket.number))[article.pk]
    who = q1(row, data_field="linked-by")
    assert "Привязкин Пётр" in who.text()
    assert "Смотрящий" not in who.text()
    moment = q1(row, "time", data_at=True)
    assert datetime.fromisoformat(moment.attrs["data-at"]) == link.linked_at
    assert kb.moscow_text(link.linked_at) == "19.10.2026 14:30"
    assert "19.10.2026 14:30" in moment.text()


# --- привязка и отвязка ------------------------------------------------------------------------------------

def test_link_post_by_editor_creates_link_visible_on_both_sides():
    """FR-429: POST `/kb/links/` редактором создаёт связь (кто и когда); НХ — фрагмент раздела «Статьи», обычный
    запрос — 302 на карточку; связь видна в карточке и в `[data-kb-tickets]` страницы статьи; повтор — без ошибки."""
    queue, ticket = _queue_and_ticket(subject="Не печатает принтер")
    other = sd.make_ticket(queue=queue, subject="Другая заявка")
    article = kb.make_published(title="Принтер не печатает")
    session = _editor(queue)

    response = _post_link(session.client, article, ticket)
    assert response.status_code == 200
    fragment = tree(response)
    wrapper = q1(fragment, "div", data_card_part="kb-articles")
    assert [int(li.attrs["data-article-id"]) for li in q(wrapper, "li", data_link_id=True)] == [article.pk]
    link = _links(article).get()
    assert link.ticket_number == ticket.number
    assert link.linked_by == session.user
    assert link.linked_at is not None and link.from_resolution is False

    assert article.pk in _article_rows(_page(session.client, ticket.number))
    page = tree(session.client.get(f"/kb/{article.pk}/"))
    rows = q(q1(page, data_kb_tickets=True), "li", data_ticket_number=True)
    assert [row.attrs["data-ticket-number"] for row in rows] == [str(ticket.number)]
    assert rows[0].text().startswith(f"#{ticket.number}") and "Не печатает принтер" in rows[0].text()
    assert q1(rows[0], "a").attrs["href"] == f"/tickets/{ticket.number}/"

    again = _post_link(session.client, article, ticket)
    assert again.status_code == 200
    assert [int(li.attrs["data-article-id"]) for li in
            q(q1(tree(again), "div", data_card_part="kb-articles"), "li", data_link_id=True)] == [article.pk]
    assert _links(article).count() == 1

    plain = _post_link(session.client, article, other, hx=False)
    assert plain.status_code == 302 and plain["Location"] == f"/tickets/{other.number}/"
    repeat = _post_link(session.client, article, other, hx=False)
    assert repeat.status_code == 302 and repeat["Location"] == f"/tickets/{other.number}/"
    assert _links(article).count() == 2


def test_link_post_denied_without_edit_right_or_without_ticket_visibility():
    """FR-429: читатель, видящий заявку, получает 403; редактор, не видящий заявку, — 404; аноним — 302 на вход.
    Связей не создаётся ни в одном случае."""
    queue, ticket = _queue_and_ticket()
    article = kb.make_published()
    reader = _reader(queue)
    stranger = kb.as_editor()  # право есть, заявку не видит

    assert _post_link(reader.client, article, ticket).status_code == 403
    assert _post_link(reader.client, article, ticket, hx=False).status_code == 403
    assert _post_link(stranger.client, article, ticket).status_code == 404
    anonymous = support.make_client()
    response = _post_link(anonymous, article, ticket, hx=False)
    assert response.status_code == 302 and response["Location"].startswith("/login/")
    assert _links().count() == 0


def test_unlink_post_removes_link_on_both_sides_and_keeps_article():
    """FR-429: POST `/kb/links/<id>/delete/` редактором убирает связь с обеих сторон; статья остаётся опубликованной,
    другие связи — на месте; повторное удаление — 404 (связи нет)."""
    queue, ticket = _queue_and_ticket()
    other = sd.make_ticket(queue=queue)
    article = kb.make_published(title="Статья остаётся")
    first = kb.link_ticket(article, ticket.number)
    kb.link_ticket(article, other.number)
    session = _editor(queue)

    response = _post_unlink(session.client, first)
    assert response.status_code == 200
    wrapper = q1(tree(response), "div", data_card_part="kb-articles")
    assert q(wrapper, "li", data_link_id=True) == []
    assert not _links(article).filter(pk=first.pk).exists()
    assert _links(article).filter(ticket_number=other.number).count() == 1
    assert model("knowledge.Article").objects.get(pk=article.pk).state == "published"

    assert article.pk not in _article_rows(_page(session.client, ticket.number))
    assert article.pk in _article_rows(_page(session.client, other.number))
    page = tree(session.client.get(f"/kb/{article.pk}/"))
    assert q(page, "li", data_ticket_number=str(ticket.number)) == []
    assert len(q(page, "li", data_ticket_number=str(other.number))) == 1

    assert _post_unlink(session.client, first).status_code == 404


def test_unlink_post_denied_without_edit_right_or_without_ticket_visibility():
    """FR-429: отвязка — читателю 403, редактору без видимости заявки 404, анониму 302 на вход; связь остаётся."""
    queue, ticket = _queue_and_ticket()
    article = kb.make_published()
    link = kb.link_ticket(article, ticket.number)
    reader = _reader(queue)
    stranger = kb.as_editor()

    assert _post_unlink(reader.client, link).status_code == 403
    assert _post_unlink(stranger.client, link).status_code == 404
    response = _post_unlink(support.make_client(), link, hx=False)
    assert response.status_code == 302 and response["Location"].startswith("/login/")
    assert _links(article).filter(pk=link.pk).exists()


def test_link_post_for_draft_article_returns_404():
    """FR-429: привязать можно только опубликованную статью: черновик (даже автору и управляющему), статья в корзине,
    несуществующая статья и несуществующая заявка дают 404 и не создают связь."""
    queue, ticket = _queue_and_ticket()
    author = _editor(queue)
    manager = _manager(queue)
    draft = kb.make_draft(author=author.user)
    trashed = kb.make_trashed()
    published = kb.make_published()

    assert _post_link(author.client, draft, ticket).status_code == 404
    assert _post_link(manager.client, draft, ticket).status_code == 404
    assert _post_link(manager.client, trashed, ticket).status_code == 404
    ghost = type("Ghost", (), {"pk": 987654})()
    assert _post_link(author.client, ghost, ticket).status_code == 404
    missing_ticket = type("Ghost", (), {"number": 987654})()
    assert _post_link(author.client, published, missing_ticket).status_code == 404
    assert _links().count() == 0


def test_link_and_unlink_write_no_audit_record():
    """FR-429: привязка и отвязка в журнал не пишутся (связь хранит «кто и когда» сама)."""
    queue, ticket = _queue_and_ticket()
    article = kb.make_published()
    session = _editor(queue)
    before = support.audit_actions()

    assert _post_link(session.client, article, ticket).status_code == 200
    link = _links(article).get()
    assert _post_unlink(session.client, link).status_code == 200

    assert support.audit_actions() == before
    assert not [a for a in support.audit_actions() if a.startswith("knowledge.")]


# --- подбор статьи -----------------------------------------------------------------------------------------

def test_pick_suggests_up_to_ten_published_titles_only():
    """FR-429: `/kb/pick/` отдаёт не больше десяти `li[data-article-id]` опубликованных статей с `data-title` и полным
    `data-url`; черновик и статья в корзине не выдаются; с `ticket` у строки кнопка привязки, без него её нет;
    короткий запрос — пустой список; доступно любому вошедшему."""
    queue, ticket = _queue_and_ticket()
    published = [kb.make_published(title=f"Принтер модель {number}") for number in range(12)]
    draft = kb.make_draft(title="Принтер черновик")
    trashed = kb.make_trashed(title="Принтер в корзине")
    ids = {article.pk for article in published}
    editor = _editor(queue)

    response = editor.client.get("/kb/pick/", {"q": "принтер", "ticket": ticket.number})
    assert response.status_code == 200
    rows = q(q1(tree(response), "ul", data_kb_pick_results=True), "li", data_article_id=True)
    assert len(rows) == 10
    shown = {int(row.attrs["data-article-id"]) for row in rows}
    assert shown <= ids and len(shown) == 10
    assert draft.pk not in shown and trashed.pk not in shown
    for row in rows:
        article_id = row.attrs["data-article-id"]
        assert row.attrs["data-title"].startswith("Принтер модель")
        assert row.attrs["data-url"].startswith("http") and row.attrs["data-url"].endswith(f"/kb/{article_id}/")
        button = q1(row, "button", data_action="kb-link-add")
        assert button.attrs["data-article-id"] == article_id

    reader = kb.as_reader()
    response = reader.client.get("/kb/pick/", {"q": "принтер"})
    assert response.status_code == 200
    rows = q(q1(tree(response), "ul", data_kb_pick_results=True), "li", data_article_id=True)
    assert rows and len(rows) <= 10
    assert all(q(row, "button", data_action="kb-link-add") == [] for row in rows)
    assert all(row.attrs["data-url"].endswith(f"/kb/{row.attrs['data-article-id']}/") for row in rows)

    response = reader.client.get("/kb/pick/", {"q": "п"})
    assert response.status_code == 200
    assert q(q1(tree(response), "ul", data_kb_pick_results=True), "li", data_article_id=True) == []
