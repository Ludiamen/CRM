"""T-5117: защита от ПДн — шаблоны и поиск в статье (FR-428, FR-431). Сценарии 1 и 6 спеки среза 005.

Шаблоны почты и телефона (простой и кириллический адрес, `+7` с пробелами и скобками, `8` с дефисами, `8` и 10 цифр
подряд; не находятся: точки, 10 цифр без `+7` и `8`, телефон, разорванный переводом строки), `pdn.find` по Markdown
(код пропускается, `mailto:`, заголовок, склейка с заголовком и ячейками, повторы и предел 20), предупреждение при
публикации (служба и страницы: список, две кнопки, ничего не сохранено) и публикация с подтверждением. Код среза на
уровне модуля не импортируется: имена берутся внутри тестов (CONTRACT-005, шапка). Адреса и телефоны собираются из
частей (решение 17 задач).
"""
import importlib
from html.parser import HTMLParser

import pytest

from tests import support_kb as kb
from tests.support import model

pytestmark = pytest.mark.django_db


# --- помощники только этого файла ------------------------------------------------------------------------

def _pdn():
    return importlib.import_module("apps.knowledge.services.pdn")


def _articles():
    return importlib.import_module("apps.knowledge.services.articles")


def _phone(prefix: str = "+7", *groups: str, sep: str = " ") -> str:
    """Телефон из частей: `prefix` и группы цифр через `sep`."""
    groups = groups or ("900", "123", "45", "67")
    return prefix + sep + sep.join(groups)


def _journal() -> list:
    return list(model("core.AuditEvent").objects.filter(action__startswith="knowledge.").order_by("id"))


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.parent, self.children = tag, parent, []
        self.attrs = {k: (v if v is not None else "") for k, v in attrs}

    def walk(self):
        for child in self.children:
            if isinstance(child, _Node):
                yield child
                yield from child.walk()

    def text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                collect(child) if isinstance(child, _Node) else parts.append(child)

        collect(self)
        return " ".join("".join(parts).split())


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", [], None)
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
        while node is not self.root:
            if node.tag == tag:
                self.cur = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def _tree(response) -> _Node:
    parser = _Tree()
    parser.feed(response.content.decode("utf-8"))
    return parser.root


def _find(scope, tag=None, **attrs) -> list:
    wanted = {k.rstrip("_").replace("_", "-"): v for k, v in attrs.items()}
    return [n for n in scope.walk()
            if (tag is None or n.tag == tag)
            and all(name in n.attrs and (value is True or n.attrs[name] == value) for name, value in wanted.items())]


def _assert_pdn_block(response, expected: list) -> None:
    """Предупреждение ПДн (CONTRACT-005, 11.3): `[data-kb-pdn]`, `li[data-pdn-item]`, две кнопки, без `role`."""
    assert response.status_code == 200
    (block,) = _find(_tree(response), data_kb_pdn=True)
    assert [n.text() for n in _find(block, "li", data_pdn_item=True)] == expected
    assert _find(block, "button", data_action="kb-pdn-back")
    (confirm,) = _find(block, "button", data_action="kb-pdn-confirm")
    assert confirm.attrs.get("type") == "submit"
    assert confirm.attrs.get("name") == "confirm_pdn" and confirm.attrs.get("value") == "1"
    assert "role" not in block.attrs


def _assert_nothing_saved(article, *, version_no: int, text: str) -> None:
    article.refresh_from_db()
    assert article.state == "draft" and article.published_at is None
    assert article.version_no == version_no and article.text == text
    assert article.versions.count() == version_no
    assert _journal() == [], "при предупреждении журнал не пишется"


# --- 1. шаблоны ------------------------------------------------------------------------------------------

def test_email_pattern_finds_plain_and_cyrillic_rf_zone():
    """FR-428: почта находится простая и в кириллической зоне `.рф`; найденное — подстрока как есть, по порядку."""
    plain = kb.email_of("ivanov", "example.test")
    cyrillic = kb.email_of("petrov", "пример.рф")
    found = _pdn().find("", f"Пишите на {plain} или на {cyrillic} в рабочее время")
    assert found == [plain, cyrillic]
    assert _pdn().find("", "Просто текст про почту и собаку без адреса") == []


def test_phone_pattern_finds_plus7_with_spaces_and_brackets():
    """FR-428: `+7` и ещё 10 цифр с пробелами и скобками между ними — найден целиком."""
    phone = _phone("+7", "(900)", "123", "45", "67")
    found = _pdn().find("", f"Звонить по номеру {phone} с девяти до шести")
    assert found == [phone]


def test_phone_pattern_finds_8_with_dashes():
    """FR-428: `8` и 10 цифр через дефисы — найден целиком."""
    phone = _phone("8", "900", "123", "45", "67", sep="-")
    assert _pdn().find("", f"Номер: {phone}.") == [phone]


def test_phone_pattern_finds_89123456789_without_separators():
    """FR-428: `8` и 10 цифр подряд без разделителей — находится."""
    phone = "8" + "912" + "345" + "67" + "89"
    assert _pdn().find("", f"Телефон {phone} дежурного") == [phone]


def test_phone_with_dots_not_found():
    """FR-428: телефон с точками между цифрами не находится (точки шаблоном не допускаются)."""
    dotted_plus = _phone("+7", "900", "123", "45", "67", sep=".")
    dotted_eight = _phone("8", "900", "123", "45", "67", sep=".")
    assert _pdn().find("", f"Номера {dotted_plus} и {dotted_eight} с точками") == []


def test_ten_digits_without_prefix_and_inn_not_found():
    """FR-428: 10 цифр без `+7` и `8` (ИНН, короткий номер) не находятся; `8` и 9 цифр — тоже."""
    inn = "77" + "07" + "08" + "38" + "93"
    ten = "900" + "123" + "45" + "67"
    short = "8" + "001" + "234" + "567"
    assert _pdn().find("", f"ИНН {inn}, номер без кода {ten}, короткий {short}") == []


def test_phone_split_by_newline_not_found():
    """FR-428: телефон, разорванный переводом строки, не находится (перевод строки не разделитель шаблона)."""
    broken = "+7 900 123\n45 67"
    assert _pdn().find("", f"Номер дежурного {broken}") == []
    assert _pdn().find("", "+7 900 123\n\n45 67") == []


# --- 2. поиск в статье ------------------------------------------------------------------------------------

def test_find_skips_fenced_code_block_and_inline_code():
    """FR-428, FR-431: адрес и телефон в ограждённом блоке, блоке с отступом и во встроенном коде пропускаются."""
    in_fence = kb.email_of("fence", "example.test")
    in_tilde = kb.email_of("tilde", "example.test")
    in_inline = _phone("8", "900", "111", "22", "33", sep="-")
    in_indent = kb.email_of("indent", "example.test")
    outside = kb.email_of("outside", "example.test")
    text = (f"Начало\n\n```\n{in_fence}\n```\n\n~~~\n{in_tilde}\n~~~\n\nвстроенный `{in_inline}` код\n\n"
            f"    {in_indent}\n\nСнаружи {outside}\n")
    found = _pdn().find("", text)
    assert found == [outside]


def test_find_finds_mailto_link_address():
    """FR-431: адрес из ссылки `mailto:` находится, хотя в видимом тексте ссылки его нет."""
    address = kb.email_of("mailto", "example.test")
    found = _pdn().find("", f"Пишите [в поддержку](mailto:{address}) без других слов")
    assert found == [address]


def test_find_checks_title():
    """FR-431: заголовок статьи проверяется целиком — адрес и телефон в нём находятся, текст при этом чист."""
    address = kb.email_of("title", "example.test")
    phone = _phone("8", "900", "222", "33", "44", sep="-")
    assert _pdn().find(f"Контакт {address}", "Текст без данных") == [address]
    assert _pdn().find(f"Звонить {phone}", "Текст без данных") == [phone]
    assert _pdn().find("Обычный заголовок", "Текст без данных") == []


def test_find_address_right_after_heading_not_glued_to_it():
    """FR-431: адрес сразу после заголовка не склеивается с его словом («Контактыivan@…» — не находка)."""
    address = kb.email_of("ivan", "example.test")
    assert _pdn().find("", f"# Контакты\n{address}\n") == [address]
    assert _pdn().find("Контакты", address) == [address], "заголовок статьи и текст тоже не склеиваются"


def test_find_address_in_table_cell_found():
    """FR-431: адреса в ячейках таблицы находятся каждый сам по себе, соседние ячейки не склеиваются."""
    first = kb.email_of("cell1", "example.test")
    second = kb.email_of("cell2", "example.test")
    text = f"| Контакт | {first} |\n|---|---|\n| Имя | {second} |\n"
    assert _pdn().find("", text) == [first, second]


def test_find_returns_unique_items_at_most_20():
    """FR-431: найденное — без повторов, в порядке первого вхождения, не больше 20 строк."""
    items = [kb.email_of(f"user{n}", "example.test") for n in range(25)]
    text = "\n\n".join([items[0], items[1], items[0], *items, items[3]])
    found = _pdn().find("", text)
    assert found == items[:20]
    assert len(set(found)) == len(found) == 20
    twice = kb.email_of("twice", "example.test")
    assert _pdn().find(twice, f"{twice}\n\n{twice}") == [twice], "заголовок и текст с одним адресом — одна строка"


# --- 3. публикация и предупреждение -----------------------------------------------------------------------

def test_publish_with_pdn_returns_warning_with_list_and_two_buttons_nothing_saved(bus, django_capture_on_commit_callbacks):
    """FR-431: «Опубликовать» без подтверждения при найденном — предупреждение (список и две кнопки), в базе, журнале и шине пусто."""
    editor = kb.as_editor()
    address = kb.email_of("warn", "example.test")
    phone = _phone("8", "900", "333", "44", "55", sep="-")
    old = "Старый текст без данных"
    draft = kb.make_draft(author=editor.user, text=old)
    bus.listen("knowledge.article_published", "knowledge.article_changed")
    # служба: публикация без формы — по тексту черновика
    other = kb.make_draft(author=editor.user, text=f"Связь: {address}")
    with django_capture_on_commit_callbacks(execute=True):
        result = _articles().publish(editor.user, other.pk, 1)
    assert result.kind == "pdn_warning" and result.pdn == [address] and result.version is None
    _assert_nothing_saved(other, version_no=1, text=f"Связь: {address}")
    # страница публикации черновика
    with django_capture_on_commit_callbacks(execute=True):
        response = editor.client.post(f"/kb/{other.pk}/publish/", {"base_version": 1, "confirm_pdn": ""})
    _assert_pdn_block(response, [address])
    _assert_nothing_saved(other, version_no=1, text=f"Связь: {address}")
    # форма правки с кнопкой «Опубликовать»: изменённый текст не сохраняется, версии 2 нет
    new_text = f"Новый текст: {address} и {phone}"
    with django_capture_on_commit_callbacks(execute=True):
        response = editor.client.post(f"/kb/{draft.pk}/edit/", {
            "title": draft.title, "text": new_text, "rubric": draft.rubric_id, "tags": "", "comment": "",
            "base_version": 1, "confirm_pdn": "", "action": "publish"})
    _assert_pdn_block(response, [address, phone])
    assert new_text in response.content.decode("utf-8"), "введённый текст остаётся в форме"
    _assert_nothing_saved(draft, version_no=1, text=old)
    assert bus.calls("knowledge.article_published") == [] and bus.calls("knowledge.article_changed") == []


def test_publish_with_confirm_pdn_passes(bus, django_capture_on_commit_callbacks):
    """FR-431: с `confirm_pdn` публикация проходит: состояние, `published_at`, журнал и событие, как без ПДн; найденное в журнал не пишется."""
    editor = kb.as_editor()
    address = kb.email_of("confirm", "example.test")
    draft = kb.make_draft(author=editor.user, text=f"Связь: {address}")
    bus.listen("knowledge.article_published")
    with django_capture_on_commit_callbacks(execute=True):
        response = editor.client.post(f"/kb/{draft.pk}/publish/", {"base_version": 1, "confirm_pdn": "1"})
    assert response.status_code == 302 and response["Location"] == f"/kb/{draft.pk}/"
    draft.refresh_from_db()
    assert draft.state == "published" and draft.published_at is not None and draft.version_no == 1
    assert len(bus.calls("knowledge.article_published")) == 1
    (entry,) = _journal()
    assert entry.action == "knowledge.article_published"
    assert address not in str(entry.before) + str(entry.after)
    # служба: форма с подтверждением — новая версия и публикация
    second = kb.make_draft(author=editor.user, text="Текст до")
    articles = _articles()
    form = articles.ArticleForm(title=second.title, text=f"Текст после {address}", rubric_id=second.rubric_id, tags="")
    with django_capture_on_commit_callbacks(execute=True):
        result = articles.publish(editor.user, second.pk, 1, form=form, confirm_pdn=True)
    assert result.kind == "saved" and result.pdn == [] and result.version is not None
    second.refresh_from_db()
    assert second.state == "published" and second.version_no == 2 and second.text == f"Текст после {address}"


def test_publish_title_with_pdn_warns(django_capture_on_commit_callbacks):
    """FR-431: ПДн только в заголовке (текст чист) тоже даёт предупреждение; найденное — подстрока заголовка."""
    editor = kb.as_editor()
    address = kb.email_of("header", "example.test")
    clean = "Чистый текст без данных"
    draft = kb.make_draft(author=editor.user, title=f"Контакт {address}", text=clean)
    result = _articles().publish(editor.user, draft.pk, 1)
    assert result.kind == "pdn_warning" and result.pdn == [address]
    _assert_nothing_saved(draft, version_no=1, text=clean)
    with django_capture_on_commit_callbacks(execute=True):
        response = editor.client.post(f"/kb/{draft.pk}/publish/", {"base_version": 1, "confirm_pdn": ""})
    _assert_pdn_block(response, [address])
    _assert_nothing_saved(draft, version_no=1, text=clean)
    # заголовок, введённый в форме при публикации
    other = kb.make_draft(author=editor.user, text=clean)
    phone = _phone("+7", "900", "444", "55", "66")
    response = editor.client.post(f"/kb/{other.pk}/edit/", {
        "title": f"Звонок {phone}", "text": clean, "rubric": other.rubric_id, "tags": "", "comment": "",
        "base_version": 1, "confirm_pdn": "", "action": "publish"})
    _assert_pdn_block(response, [phone])
    _assert_nothing_saved(other, version_no=1, text=clean)
    assert model("knowledge.Article").objects.get(pk=other.pk).title != f"Звонок {phone}"
