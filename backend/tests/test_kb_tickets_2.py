"""T-5120: «Статья из решения», «Ссылка на статью» и связанные заявки на странице статьи (FR-427, FR-428, FR-429,
FR-430, FR-432, FR-448). Сценарии связи с заявками спеки среза 005.

Кнопка и служба `links.from_ticket` (закрытая заявка с решением, права, видимость, заголовок, чистка ПДн, связь,
версия 1, журнал, повторное нажатие, замок), подсказка `/kb/pick/` и инструмент «Ссылка на статью» в форме
внутреннего комментария, список связанных заявок на странице статьи, обезличивание заявки и удаление статьи навсегда.
Гонки — без потоков (раздел 16 CONTRACT-005): последовательные вызовы и проверка замка по SQL. Код среза на уровне
модуля не импортируется: имена берутся внутри тестов (шапка CONTRACT-005). Вставку текста в поле делает `kb-link.js`
в браузере, её проверяет приёмка T-5143; здесь — разметка инструмента и данные подсказки.
"""
import json
import secrets
from html.parser import HTMLParser

import pytest
from django.utils import timezone

from tests import support, support_org as org, support_servicedesk as sd
from tests import support_kb as kb
from tests.support import HX, model

pytestmark = pytest.mark.django_db

ALREADY_CREATED = "Черновик по этой заявке уже создан"
NOT_CLOSED = "not_closed_with_resolution"
RESOLUTION = "Заменили патч-корд и перезагрузили коммутатор"
HIDDEN = "[скрыто]"


# --- разбор разметки (помощник только этого файла; образец — test_sd_card.py) -------------------------------------

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

    def ancestor(self, tag: str, css: str = ""):
        node = self.parent
        while node is not None:
            if node.tag == tag and (not css or css in node.attrs.get("class", "").split()):
                return node
            node = node.parent
        return None


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


def tree(response) -> Node:
    parser = _Tree()
    parser.feed(response.content.decode("utf-8"))
    return parser.root


def q(scope, tag=None, **attrs) -> list:
    """Потомки по тегу и атрибутам; имя атрибута с дефисом — через `_` (`data_form="kb-link"`)."""
    wanted = {name.rstrip("_").replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            found.append(node)
    return found


def q1(scope, tag=None, **attrs):
    found = q(scope, tag, **attrs)
    assert len(found) == 1, f"ожидали один элемент {tag or ''}{attrs}, нашли {len(found)}"
    return found[0]


def order_of(root, node) -> int:
    for index, item in enumerate(root.walk()):
        if item is node:
            return index
    raise AssertionError("элемент не найден в документе")


# --- данные теста ---------------------------------------------------------------------------------------------------

def _links():
    from apps.knowledge.services import links
    return links


def _session(queue, *codes: str) -> kb.Session:
    """Сотрудник — участник очереди (заявки её узла он видит) с правами базы знаний `codes`."""
    user = support.make_employee()
    if codes:
        kb.grant(user, *codes)
    org.make_member(user, queue.unit)
    return kb.Session(user, support.logged_in(user))


def _editor(queue) -> kb.Session:
    return _session(queue, "knowledge.edit")


def _closed(queue, *, resolution: str = RESOLUTION, **over):
    """Закрытая заявка; без `resolution` — как закрытая автоматически (решения нет)."""
    return sd.make_ticket(queue=queue, kind="closed", closed_at=timezone.now(), resolution=resolution, **over)


def _card(session, number: int):
    response = session.client.get(f"/tickets/{number}/")
    assert response.status_code == 200, f"карточка заявки: {response.status_code}"
    return response, tree(response)


def _press(session, number: int, **extra):
    return session.client.post(f"/kb/from-ticket/{number}/", **extra)


def _articles_of(number: int) -> list:
    return list(model("knowledge.Article").objects.filter(from_ticket=number).order_by("id"))


def _article_count() -> int:
    return model("knowledge.Article").objects.count()


def _journal(action: str) -> list:
    return list(model("core.AuditEvent").objects.filter(action=action).order_by("id"))


def _statuses(root) -> str:
    return " ".join(node.text() for node in q(root, None, role="status"))


def _alert_codes(root) -> list[str]:
    return [node.attrs.get("data-code", "") for node in q(root, None, role="alert")]


def _created_draft(session, number: int):
    """Нажатие кнопки: 302 на редактор и единственный черновик по заявке."""
    response = _press(session, number)
    assert response.status_code == 302, f"«Статья из решения»: {response.status_code}"
    (article,) = _articles_of(number)
    return response, article


def _boundary(years: int = 3):
    now = timezone.now()
    try:
        return now.replace(year=now.year - years)
    except ValueError:
        return now.replace(year=now.year - years, day=28)


def _old_closed(queue, **over):
    """Закрытая заявка, у которой срок хранения (3 года, SPEC-003 FR-290) вышел два дня назад."""
    ticket = _closed(queue, **over)
    sd.backdate(ticket, "closed_at", days=(timezone.now() - _boundary()).days + 2)
    return ticket


# --- кнопка «Статья из решения» -------------------------------------------------------------------------------------

def test_from_resolution_button_shown_for_closed_ticket_with_resolution_to_editor():
    """FR-427, FR-432: у закрытой заявки с решением редактор видит `form[data-form=kb-from-ticket]` с кнопкой
    «Статья из решения» рядом с «Открыть заново» (в `div.card-actions`), в оболочке `closed_action` (раздел 11.8)."""
    queue = sd.make_queue()
    editor = _editor(queue)
    ticket = _closed(queue)
    _response, root = _card(editor, ticket.number)
    part = q1(root, None, data_card_part="kb-from-ticket")
    assert part.attrs.get("data-part-kind") == "closed_action"
    form = q1(part, "form", data_form="kb-from-ticket")
    button = q1(form, "button", data_action="kb-from-ticket")
    assert button.text() == "Статья из решения"
    assert form.attrs.get("hx-post") == f"/kb/from-ticket/{ticket.number}/"
    reopen = q1(root, "button", data_action="ticket-reopen")
    actions = reopen.ancestor("div", "card-actions")
    assert actions is not None and part.inside(actions), "кнопка стоит в блоке действий закрытой заявки"


def test_from_resolution_button_absent_for_open_ticket_and_post_is_refused():
    """FR-427: у открытой заявки кнопки нет; прямой POST — отказ `not_closed_with_resolution` (200), статьи нет."""
    queue = sd.make_queue()
    editor = _editor(queue)
    ticket = sd.make_ticket(queue=queue, resolution=RESOLUTION)
    _response, root = _card(editor, ticket.number)
    assert not q(root, None, data_card_part="kb-from-ticket") and not q(root, "button", data_action="kb-from-ticket")
    before = _article_count()
    response = _press(editor, ticket.number)
    assert response.status_code == 200, f"отказ службы на POST — 200, получили {response.status_code}"
    assert NOT_CLOSED in _alert_codes(tree(response))
    assert _article_count() == before and not model("knowledge.TicketLink").objects.filter(
        ticket_number=ticket.number).exists()


def test_from_resolution_button_absent_for_auto_closed_ticket_and_post_is_refused():
    """FR-427: у закрытой автоматически заявки (решения нет, пустое или из пробелов) кнопки нет, POST — отказ."""
    queue = sd.make_queue()
    editor = _editor(queue)
    for resolution in ("", "  \n "):
        ticket = _closed(queue, resolution=resolution)
        _response, root = _card(editor, ticket.number)
        assert not q(root, None, data_card_part="kb-from-ticket") and "Статья из решения" not in root.text()
        before = _article_count()
        response = _press(editor, ticket.number)
        assert response.status_code == 200 and NOT_CLOSED in _alert_codes(tree(response))
        assert _article_count() == before and not _articles_of(ticket.number)


def test_from_resolution_button_absent_and_post_denied_without_edit_right():
    """FR-427, FR-429: сотрудник видит заявку, но права «Редактирование базы знаний» нет — кнопки нет, POST — 403."""
    queue = sd.make_queue()
    reader = _session(queue)
    ticket = _closed(queue)
    _response, root = _card(reader, ticket.number)
    assert not q(root, None, data_card_part="kb-from-ticket") and not q(root, "button", data_action="kb-from-ticket")
    before = _article_count()
    response = _press(reader, ticket.number)
    assert response.status_code == 403, f"нет права — 403, получили {response.status_code}"
    assert _article_count() == before


def test_from_resolution_post_for_invisible_ticket_returns_404():
    """FR-427, FR-409: заявку редактор не видит — 404, как у несуществующей; статьи нет, данных заявки в ответе нет;
    тот же POST того, кто заявку видит, создаёт черновик."""
    queue = sd.make_queue()
    ticket = _closed(queue, subject="Тема закрытой заявки другого отдела")
    outsider = _editor(sd.make_queue())
    before = _article_count()
    response = _press(outsider, ticket.number)
    missing = _press(outsider, ticket.number + 100_000)
    assert response.status_code == 404 and missing.status_code == 404
    assert "Тема закрытой заявки" not in response.content.decode("utf-8")
    assert _article_count() == before and not _articles_of(ticket.number)
    insider = _editor(queue)
    assert _press(insider, ticket.number).status_code == 302 and len(_articles_of(ticket.number)) == 1


# --- что создаётся --------------------------------------------------------------------------------------------------

def test_from_resolution_creates_draft_with_subject_title_resolution_text_and_default_rubric():
    """FR-427: черновик — заголовок «тема заявки», текст — решение, рубрика «Общее», автор — нажавший."""
    queue = sd.make_queue()
    editor = _editor(queue)
    ticket = _closed(queue, subject="Не работает сеть в кабинете 12")
    _response, article = _created_draft(editor, ticket.number)
    assert article.state == "draft" and article.published_at is None
    assert article.title == "Не работает сеть в кабинете 12"
    assert article.text == RESOLUTION
    assert article.rubric == kb.general_rubric() and article.rubric.is_default
    assert article.author == editor.user and article.updated_by == editor.user
    assert article.version_no == 1 and article.from_ticket == ticket.number


def test_from_resolution_creates_from_resolution_link_and_version_one_with_comment():
    """FR-427, FR-429: статья сразу связана с заявкой (`from_resolution=True`, привязал нажавший); версия 1 — с
    комментарием «Создано из заявки #N», и она единственная."""
    queue = sd.make_queue()
    editor = _editor(queue)
    ticket = _closed(queue)
    _response, article = _created_draft(editor, ticket.number)
    (link,) = model("knowledge.TicketLink").objects.filter(article=article)
    assert link.ticket_number == ticket.number and link.from_resolution is True and link.linked_by == editor.user
    (version,) = model("knowledge.ArticleVersion").objects.filter(article=article)
    assert version.number == 1 and version.comment == f"Создано из заявки #{ticket.number}"
    assert (version.title, version.text, version.author) == (article.title, article.text, editor.user)


def test_from_resolution_masks_email_and_phone_in_subject_and_resolution():
    """FR-427, FR-428: адрес почты и телефон в теме и решении заменяются на «[скрыто]»; строка внутри ограждения
    кода в решении остаётся как была (шаблоны и исключение кода — FR-428)."""
    queue = sd.make_queue()
    editor = _editor(queue)
    email, phone = kb.email_of("petrov", "example.test"), kb.phone_of()
    fenced = f"git config user.email {kb.email_of('git', 'example.test')}"
    resolution = f"Написали на {email}, звонить {phone}\n```\n{fenced}\n```\n"
    ticket = _closed(queue, subject=f"Почта {email}", resolution=resolution)
    _response, article = _created_draft(editor, ticket.number)
    assert article.title == f"Почта {HIDDEN}"
    lines = article.text.splitlines()
    assert lines[0] == f"Написали на {HIDDEN}, звонить {HIDDEN}"
    assert fenced in article.text, "в блоке кода ничего не скрывается"
    assert email not in article.text and phone not in article.text and phone not in article.plain
    (version,) = model("knowledge.ArticleVersion").objects.filter(article=article)
    assert version.title == article.title and version.text == article.text and email not in version.text


def test_from_resolution_title_is_truncated_to_200_chars():
    """FR-427: заголовок обрезается до 200 знаков (тема до 255): первые 200 знаков темы."""
    queue = sd.make_queue()
    editor = _editor(queue)
    subject = "".join(chr(0x0410 + i % 26) for i in range(230))
    ticket = _closed(queue, subject=subject)
    _response, article = _created_draft(editor, ticket.number)
    assert len(article.title) == 200 and article.title == subject[:200]


def test_from_resolution_draft_has_no_requester_address_or_correspondence():
    """FR-427, FR-432: в черновике нет адреса и имени заявителя и текстов переписки (письмо заявителя, ответ,
    внутренний комментарий) — ни в статье, ни в версии, ни в связи."""
    queue = sd.make_queue()
    editor = _editor(queue)
    requester_email = kb.email_of("zayavitel", "example.test")
    requester = sd.make_requester(requester_email, full_name="Заявитель Ивановский")
    ticket = _closed(queue, requester=requester)
    marks = [f"письмо-{secrets.token_hex(4)}", f"ответ-{secrets.token_hex(4)}", f"заметка-{secrets.token_hex(4)}"]
    sd.make_entry(ticket, "incoming", text=marks[0])
    sd.make_entry(ticket, "reply", author=editor.user, text=marks[1])
    sd.make_entry(ticket, "comment", author=editor.user, text=marks[2])
    _response, article = _created_draft(editor, ticket.number)
    snapshot = {"article": {f.name: str(getattr(article, f.attname)) for f in article._meta.concrete_fields}}
    for item in model("knowledge.ArticleVersion").objects.filter(article=article):
        snapshot[f"version{item.number}"] = {f.name: str(getattr(item, f.attname)) for f in item._meta.concrete_fields}
    for item in model("knowledge.TicketLink").objects.filter(article=article):
        snapshot[f"link{item.pk}"] = {f.name: str(getattr(item, f.attname)) for f in item._meta.concrete_fields}
    blob = json.dumps(snapshot, ensure_ascii=False)
    for forbidden in (requester_email, "Заявитель Ивановский", *marks):
        assert forbidden not in blob, f"в черновике не должно быть «{forbidden}»"


def test_from_resolution_writes_article_created_audit_and_redirects_to_editor():
    """FR-427, FR-438: журнал `knowledge.article_created` (автор — нажавший, `after`: `number`, `title`, `version`=1);
    ответ — 302 на `/kb/<id>/edit/`, у НХ — 200 без тела с `HX-Redirect` на тот же адрес."""
    queue = sd.make_queue()
    editor = _editor(queue)
    ticket = _closed(queue)
    response, article = _created_draft(editor, ticket.number)
    assert response["Location"] == f"/kb/{article.pk}/edit/"
    (entry,) = _journal("knowledge.article_created")
    assert entry.actor == editor.user
    assert (entry.object_type, entry.object_id) == ("knowledge.article", str(article.pk))
    assert entry.before == {} and set(entry.after) == {"number", "title", "version"}
    assert int(entry.after["number"]) == article.pk and entry.after["title"] == article.title
    assert entry.after["version"] == 1
    again = _press(editor, ticket.number, **HX)
    assert again.status_code == 200 and again.content == b"" and again["HX-Redirect"] == f"/kb/{article.pk}/edit/"


def test_from_resolution_repeat_opens_same_draft_with_already_created_message():
    """FR-427: повторное нажатие открывает тот же черновик (тот же адрес редактора) с сообщением «Черновик по этой
    заявке уже создан»; второй статьи, связи, версии и записи журнала нет."""
    queue = sd.make_queue()
    editor = _editor(queue)
    ticket = _closed(queue)
    first, article = _created_draft(editor, ticket.number)
    first_page = editor.client.get(first["Location"])
    assert first_page.status_code == 200 and ALREADY_CREATED not in _statuses(tree(first_page))
    second = _press(editor, ticket.number)
    assert second.status_code == 302 and second["Location"] == first["Location"]
    page = editor.client.get(second["Location"])
    assert page.status_code == 200 and ALREADY_CREATED in _statuses(tree(page))
    assert [a.pk for a in _articles_of(ticket.number)] == [article.pk]
    assert model("knowledge.TicketLink").objects.filter(ticket_number=ticket.number).count() == 1
    assert model("knowledge.ArticleVersion").objects.filter(article=article).count() == 1
    assert len(_journal("knowledge.article_created")) == 1


def test_from_resolution_two_simultaneous_presses_create_one_draft():
    """FR-427: два нажатия, которые пересеклись бы во времени, дают один черновик: проверка и создание идут под
    замком `knowledge.from_ticket:<номер>:<сотрудник>` до записи статьи (раздел 16); второй вызов возвращает тот же
    черновик (`created=False`); другой редактор получает свой черновик."""
    queue = sd.make_queue()
    editor, other = _editor(queue), _editor(queue)
    ticket = _closed(queue)
    links = _links()
    with kb.capture_sql() as sqls:
        first = links.from_ticket(editor.user, ticket.number)
    assert first.created is True and first.article.from_ticket == ticket.number
    locks = kb.advisory_locks(sqls)
    assert kb.AdvisoryLock("exclusive", f"knowledge.from_ticket:{ticket.number}:{editor.user.pk}") in locks
    table = model("knowledge.Article")._meta.db_table
    lock_at = next(i for i, sql in enumerate(sqls) if "pg_advisory_xact_lock" in sql)
    insert_at = next(i for i, sql in enumerate(sqls) if sql.lstrip().upper().startswith("INSERT") and table in sql)
    assert lock_at < insert_at, "замок берётся раньше записи статьи"
    second = links.from_ticket(editor.user, ticket.number)
    assert second.created is False and second.article.pk == first.article.pk
    assert len(_articles_of(ticket.number)) == 1
    third = links.from_ticket(other.user, ticket.number)
    assert third.created is True and third.article.pk != first.article.pk and third.article.author == other.user


def test_from_resolution_after_publishing_previous_draft_creates_new_draft():
    """FR-427: связанный «черновик» — только черновик: после публикации прежнего нажатие создаёт новый черновик
    (вторую статью и вторую связь `from_resolution`)."""
    queue = sd.make_queue()
    editor = _editor(queue)
    ticket = _closed(queue)
    _response, first = _created_draft(editor, ticket.number)
    model("knowledge.Article").objects.filter(pk=first.pk).update(state="published", published_at=timezone.now())
    response = _press(editor, ticket.number)
    assert response.status_code == 302
    articles = _articles_of(ticket.number)
    assert len(articles) == 2 and articles[1].pk != first.pk and articles[1].state == "draft"
    assert response["Location"] == f"/kb/{articles[1].pk}/edit/"
    assert model("knowledge.TicketLink").objects.filter(ticket_number=ticket.number, from_resolution=True).count() == 2


def test_from_resolution_for_anonymized_ticket_keeps_resolution_text():
    """FR-427: у заявки, у которой прошёл срок обезличивания, решение остаётся (SPEC-003 FR-290), кнопка работает:
    черновик получает тему и текст решения."""
    queue = sd.make_queue()
    editor = _editor(queue)
    ticket = _closed(queue, subject="Заменить картридж в принтере")
    model("servicedesk.Ticket").objects.filter(pk=ticket.pk).update(
        anonymized_at=timezone.now(), requester=None, requester_email="обезличено", requester_name="обезличено")
    _response, root = _card(editor, ticket.number)
    assert q(root, "button", data_action="kb-from-ticket"), "у обезличенной заявки кнопка есть"
    _response, article = _created_draft(editor, ticket.number)
    assert article.title == "Заменить картридж в принтере" and article.text == RESOLUTION


# --- «Ссылка на статью» ---------------------------------------------------------------------------------------------

def test_pick_hint_is_available_to_any_logged_in_employee_without_edit_right():
    """FR-430: подсказка `/kb/pick/?q=` доступна любому вошедшему без права «Редактирование»: до 10 `li` с
    `data-article-id`, `data-title`, `data-url` (полный адрес) только опубликованных статей; черновик и корзина не
    выдаются; короткий запрос — пустой список; кнопки привязки без `ticket` нет."""
    reader = kb.as_reader()
    word = "Мониторинг"
    published = kb.make_published(title=f"{word} серверов")
    kb.make_draft(title=f"{word} черновика")
    kb.make_trashed(title=f"{word} корзины")
    response = reader.client.get("/kb/pick/", {"q": word})
    assert response.status_code == 200, f"подсказка для читателя: {response.status_code}"
    results = q1(tree(response), "ul", data_kb_pick_results=True)
    rows = q(results, "li", data_article_id=True)
    assert [row.attrs["data-article-id"] for row in rows] == [str(published.pk)]
    assert rows[0].attrs["data-title"] == published.title
    base = response.wsgi_request.build_absolute_uri("/").rstrip("/")
    assert rows[0].attrs["data-url"] == f"{base}/kb/{published.pk}/"
    assert not q(results, "button", data_action="kb-link-add")
    short = reader.client.get("/kb/pick/", {"q": "М"})
    assert short.status_code == 200 and not q(tree(short), "li", data_article_id=True)


def test_comment_tool_inserts_title_colon_absolute_url_as_plain_text():
    """FR-430, FR-432: в форме внутреннего комментария под полем — оболочка `kb-link-tool` с кнопкой «Ссылка на
    статью», полем `pick` и списком; строка подсказки даёт `data-title` и полный `data-url`, из которых инструмент
    собирает «Заголовок: <адрес>» простым текстом (сама вставка — `kb-link.js`, приёмка T-5143)."""
    queue = sd.make_queue()
    editor = _editor(queue)
    ticket = sd.make_ticket(queue=queue)
    article = kb.make_published(title="Инструкция по подключению принтера")
    _response, root = _card(editor, ticket.number)
    part = q1(root, None, data_card_part="kb-link-tool")
    assert part.attrs.get("data-part-kind") == "comment_tool"
    form = q1(root, "form", data_form="ticket-comment")
    assert part.inside(form)
    assert order_of(root, part) > order_of(root, q1(form, "textarea", name="text")), "инструмент — под полем текста"
    assert q1(part, "button", data_action="kb-link-tool").text() == "Ссылка на статью"
    assert q1(part, "input", type="search", name="pick") is not None
    assert q1(part, "ul", data_kb_pick_results=True) is not None
    pick = editor.client.get("/kb/pick/", {"q": "принтера"})
    rows = q(tree(pick), "li", data_article_id=True)
    assert [row.attrs["data-article-id"] for row in rows] == [str(article.pk)]
    inserted = f"{rows[0].attrs['data-title']}: {rows[0].attrs['data-url']}"
    base = pick.wsgi_request.build_absolute_uri("/").rstrip("/")
    assert inserted == f"{article.title}: {base}/kb/{article.pk}/"
    # п. 24 раздела 17: инструмент виден и читателю без права «Редактирование», внутри формы комментария
    reader = _session(queue)
    _response, reader_root = _card(reader, ticket.number)
    reader_part = q1(reader_root, None, data_card_part="kb-link-tool")
    assert reader_part is not None, "читателю инструмент «Ссылка на статью» виден"
    assert reader_part.inside(q1(reader_root, "form", data_form="ticket-comment"))


def test_comment_with_inserted_article_link_stays_ordinary_feed_record():
    """FR-430: комментарий со вставленной ссылкой — обычная запись ленты: текст сохранён как есть, в ленте простой
    текст без ссылки, связей и записей журнала базы знаний комментарий не создаёт."""
    queue = sd.make_queue()
    editor = _editor(queue)
    ticket = sd.make_ticket(queue=queue)
    article = kb.make_published(title="Настройка VPN на ноутбуке")
    text = f"{article.title}: http://testserver/kb/{article.pk}/"
    response = editor.client.post(f"/tickets/{ticket.number}/comment/", {"text": text})
    assert response.status_code == 302
    (entry,) = model("servicedesk.TicketEntry").objects.filter(ticket=ticket, kind="comment")
    assert entry.text == text and entry.author == editor.user
    _response, root = _card(editor, ticket.number)
    shown = [node for node in q(root, None, data_entry_text=True) if text in node.text()]
    assert len(shown) == 1 and not q(shown[0], "a"), "ссылка в ленте — простой текст"
    assert not model("knowledge.TicketLink").objects.exists()
    assert not model("core.AuditEvent").objects.filter(action__startswith="knowledge.").exists()


# --- связанные заявки на странице статьи ----------------------------------------------------------------------------

def test_article_page_lists_only_tickets_visible_to_viewer():
    """FR-429: на странице статьи `[data-kb-tickets]` — только заявки, которые видит смотрящий («#N Тема», ссылка
    `/tickets/<N>/`); чужая заявка и её тема не показываются; видящий обе получает обе, по порядку привязки."""
    mine_queue, other_queue = sd.make_queue(), sd.make_queue()
    mine = sd.make_ticket(queue=mine_queue, subject="Принтер на втором этаже")
    other = sd.make_ticket(queue=other_queue, subject="Закупка серверов отдела")
    article = kb.make_published()
    kb.link_ticket(article, mine.number)
    kb.link_ticket(article, other.number)
    viewer = _session(mine_queue)
    response = viewer.client.get(f"/kb/{article.pk}/")
    assert response.status_code == 200
    block = q1(tree(response), None, data_kb_tickets=True)
    rows = q(block, "li", data_ticket_number=True)
    assert [row.attrs["data-ticket-number"] for row in rows] == [str(mine.number)]
    link = q1(rows[0], "a")
    assert link.attrs["href"] == f"/tickets/{mine.number}/" and link.text() == f"#{mine.number} Принтер на втором этаже"
    assert "Закупка серверов" not in response.content.decode("utf-8")
    holder = support.make_with_permissions("servicedesk.all")
    page = support.logged_in(holder).client.get(f"/kb/{article.pk}/")
    both = q(q1(tree(page), None, data_kb_tickets=True), "li", data_ticket_number=True)
    assert [row.attrs["data-ticket-number"] for row in both] == [str(mine.number), str(other.number)]
    views = _links().tickets_for(viewer.user, article)
    assert [view.brief.number for view in views] == [mine.number]


def test_article_page_hides_linked_tickets_list_for_trashed_article_even_from_manager():
    """FR-429, FR-415: у статьи в корзине список связанных заявок скрыт и у управляющего (связь возвращается
    вместе со статьёй); служба отдаёт пустой список."""
    queue = sd.make_queue()
    ticket = sd.make_ticket(queue=queue, subject="Заявка со скрытой связью")
    manager = _session(queue, "knowledge.manage")
    article = kb.make_trashed()
    kb.link_ticket(article, ticket.number)
    response = manager.client.get(f"/kb/{article.pk}/")
    assert response.status_code == 200, f"управляющий видит статью в корзине: {response.status_code}"
    root = tree(response)
    assert not q(root, None, data_kb_tickets=True)
    assert "Заявка со скрытой связью" not in response.content.decode("utf-8")
    assert _links().tickets_for(manager.user, article) == []


# --- обезличивание заявки и удаление статьи -------------------------------------------------------------------------

def test_ticket_anonymization_by_term_keeps_link_number_and_subject(django_capture_on_commit_callbacks):
    """FR-429, FR-448: обезличивание заявки по сроку не удаляет связь: номер и тема остаются, в списке статьи
    по-прежнему «#N Тема»."""
    from apps.servicedesk.services import retention

    queue = sd.make_queue()
    ticket = _old_closed(queue, subject="Замена монитора в бухгалтерии")
    article = kb.make_published()
    kb.link_ticket(article, ticket.number)
    with django_capture_on_commit_callbacks(execute=True):
        assert retention.anonymize_one(ticket.pk) is True
    ticket.refresh_from_db()
    assert ticket.anonymized_at is not None and ticket.subject == "Замена монитора в бухгалтерии"
    assert model("knowledge.TicketLink").objects.filter(article=article, ticket_number=ticket.number).count() == 1
    viewer = _session(queue)
    response = viewer.client.get(f"/kb/{article.pk}/")
    assert response.status_code == 200
    (row,) = q(q1(tree(response), None, data_kb_tickets=True), "li", data_ticket_number=True)
    assert row.attrs["data-ticket-number"] == str(ticket.number)
    assert q1(row, "a").text() == f"#{ticket.number} Замена монитора в бухгалтерии"


def test_ticket_anonymization_job_leaves_articles_versions_comments_and_files_untouched(
        django_capture_on_commit_callbacks, protected_root):
    """FR-448: ночное обезличивание заявок (порция задания) не трогает статьи, версии, комментарии и файлы статей."""
    from apps.core.services import files
    from apps.servicedesk.services import retention

    queue = sd.make_queue()
    ticket = _old_closed(queue)
    article = kb.make_published(text="Текст статьи про заявку")
    kb.add_version(article, text="Правка статьи", comment="правка")
    kb.link_ticket(article, ticket.number)
    comment = kb.make_comment(article, text="Комментарий к статье")
    attached = kb.attach_file(article, "схема.png", write=True)
    path = files.attachment_path(attached.file)
    body = path.read_bytes()

    def state() -> dict:
        row = model("knowledge.Article").objects.get(pk=article.pk)
        return {
            "article": [str(getattr(row, f.attname)) for f in row._meta.concrete_fields],
            "versions": list(model("knowledge.ArticleVersion").objects.filter(article=article).order_by("number")
                             .values_list("number", "title", "text", "html", "comment")),
            "comments": list(model("core.Comment").objects.filter(object_ref=f"knowledge.article:{article.pk}")
                             .values_list("pk", "text", "author_id")),
            "files": list(model("knowledge.ArticleFile").objects.filter(article=article)
                          .values_list("pk", "name", "file__status", "file__sha256")),
        }

    before = state()
    assert before["comments"][0][0] == comment.pk
    with django_capture_on_commit_callbacks(execute=True):
        batch = retention.anonymize_batch(size=50)
    assert batch.done >= 1
    ticket.refresh_from_db()
    assert ticket.anonymized_at is not None, "заявка обезличена заданием"
    assert state() == before
    assert path.exists() and path.read_bytes() == body, "файл статьи на диске не тронут"


def test_purging_article_forever_deletes_its_ticket_links(django_capture_on_commit_callbacks):
    """FR-429: удаление статьи навсегда удаляет её связи с заявками; сами заявки остаются."""
    from apps.knowledge.services import articles

    queue = sd.make_queue()
    first, second = sd.make_ticket(queue=queue), sd.make_ticket(queue=queue)
    article = kb.make_trashed()
    survivor = kb.make_published()
    for number in (first.number, second.number):
        kb.link_ticket(article, number)
    kb.link_ticket(survivor, first.number)
    manager = kb.as_manager()
    with django_capture_on_commit_callbacks(execute=True):
        articles.purge(article, manager.user)
    TicketLink = model("knowledge.TicketLink")
    assert not TicketLink.objects.filter(article_id=article.pk).exists()
    assert not model("knowledge.Article").objects.filter(pk=article.pk).exists()
    assert TicketLink.objects.filter(article=survivor, ticket_number=first.number).count() == 1, "чужая связь цела"
    assert model("servicedesk.Ticket").objects.filter(pk__in=[first.pk, second.pk]).count() == 2
