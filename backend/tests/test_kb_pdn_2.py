"""T-5118: защита от ПДн — предупреждения и маскирование (FR-428, FR-431). Сценарии 2, 10, 11, 14, 15 спеки среза 005.

Предупреждение при сохранении опубликованной статьи, при публикации черновика и при восстановлении версии в
опубликованную; черновик без публикации не предупреждает; адрес в коде не вызывает предупреждения, тот же адрес вне
кода вызывает; найденное в журнал не пишется. Затем `pdn.mask_plain` (тема заявки) и `pdn.mask_resolution` (решение:
ограждения из обратных кавычек и `~`, участки в обратных кавычках, отступ в 4 пробела, `\\r\\n`). Код среза на уровне
модуля не импортируется (CONTRACT-005, шапка). Адреса и телефоны собираются из частей (решение 17 задач).
"""
import importlib
from html.parser import HTMLParser

import pytest

from tests import support_kb as kb
from tests.support import model

pytestmark = pytest.mark.django_db

HIDDEN = "[скрыто]"
EMAIL = kb.email_of("ivanov", "example.test")
PHONE = kb.phone_of("+7", "912", "345", "67", "89")  # «+7 912-345-67-89»
GIT = kb.email_of("git", "github.com")


# --- помощники только этого файла --------------------------------------------------------------------------

def _pdn():
    return importlib.import_module("apps.knowledge.services.pdn")


_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.parent, self.children = tag, parent, []
        self.attrs = {k: (v if v is not None else "") for k, v in attrs}

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                collect(child) if isinstance(child, Node) else parts.append(child)

        collect(self)
        return " ".join("".join(parts).split())


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
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
        while node is not self.root:
            if node.tag == tag:
                self.cur = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def _tree(response) -> Node:
    parser = _Tree()
    parser.feed(response.content.decode("utf-8"))
    return parser.root


def _find(scope, tag=None, **attrs) -> list:
    wanted = {k.rstrip("_").replace("_", "-"): v for k, v in attrs.items()}
    result = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            result.append(node)
    return result


def _warning(response, items: set, confirm_label: str, *, action: str | None = None) -> None:
    """Блок предупреждения (11.3): список найденного, две кнопки; без `role` и `data-warning`."""
    assert response.status_code == 200
    tree = _tree(response)
    (block,) = _find(tree, data_kb_pdn=True)
    assert {node.text() for node in _find(block, "li", data_pdn_item=True)} == items
    (back,) = _find(block, "button", data_action="kb-pdn-back")
    assert "Вернуться к правке" in back.text()
    (confirm,) = _find(block, "button", data_action="kb-pdn-confirm")
    assert confirm.attrs.get("type") == "submit"
    assert confirm.attrs.get("name") == "confirm_pdn" and confirm.attrs.get("value") == "1"
    assert confirm.text() == confirm_label
    assert "role" not in block.attrs and "data-warning" not in block.attrs
    if action is not None:
        hidden = [n for n in _find(tree, "input", name="action") if n.attrs.get("type") == "hidden"]
        assert [n.attrs.get("value") for n in hidden] == [action]
        # п. 22 раздела 17: скрытое поле лежит внутри формы статьи и не лежит внутри [data-kb-pdn]
        ancestors, node = [], hidden[0].parent
        while node is not None:
            ancestors.append(node)
            node = node.parent
        assert any(a.tag == "form" and a.attrs.get("data-form") == "kb-article" for a in ancestors)
        assert block not in ancestors


def _no_warning(response) -> None:
    assert not _find(_tree(response), data_kb_pdn=True), "предупреждения быть не должно"


def _edit_data(article, **over) -> dict:
    article.refresh_from_db()
    data = {"title": article.title, "text": article.text, "rubric": article.rubric_id,
            "tags": ", ".join(article.tags.order_by("name").values_list("name", flat=True)), "comment": "",
            "base_version": article.version_no, "confirm_pdn": "", "action": "save"}
    data.update(over)
    return data


def _state(article) -> tuple:
    """Всё, что менять предупреждение не должно: поля статьи, число версий, число записей журнала."""
    article.refresh_from_db()
    return (article.state, article.version_no, article.title, article.text, article.updated_by_id,
            article.updated_at, article.versions.count(),
            model("core.AuditEvent").objects.filter(action__startswith="knowledge.").count())


# --- 1. предупреждение и «всё равно» (FR-431) -----------------------------------------------------------------

def test_save_published_with_pdn_warns_and_save_anyway_passes(django_capture_on_commit_callbacks):
    """FR-431: сохранение опубликованной с адресом и телефоном — предупреждение со списком, ничего не записано;
    «Сохранить всё равно» (`confirm_pdn=1`) сохраняет."""
    editor = kb.as_editor()
    article = kb.make_published(author=editor.user, text="Прежний текст")
    new_text = f"Почта: {EMAIL}, тел: {PHONE}."
    before = _state(article)
    response = editor.client.post(f"/kb/{article.pk}/edit/", _edit_data(article, text=new_text, action="save"))
    _warning(response, {EMAIL, PHONE}, "Сохранить всё равно", action="save")
    assert new_text in " ".join(n.text() for n in _find(_tree(response), "textarea", name="text")), \
        "введённый текст остаётся в форме"
    assert _state(article) == before, "предупреждение ничего не пишет: ни версии, ни полей, ни журнала"
    with django_capture_on_commit_callbacks(execute=True):
        confirmed = editor.client.post(
            f"/kb/{article.pk}/edit/", _edit_data(article, text=new_text, action="save", confirm_pdn="1"))
    assert confirmed.status_code == 302 and confirmed["Location"] == f"/kb/{article.pk}/"
    article.refresh_from_db()
    assert (article.version_no, article.text, article.state) == (2, new_text, "published")
    assert article.versions.filter(number=2, text=new_text).exists()


def test_restore_version_into_published_with_pdn_warns(django_capture_on_commit_callbacks):
    """FR-431: восстановление версии с адресом в опубликованную статью — предупреждение; с подтверждением — новая
    версия «Восстановлено из версии 1»."""
    editor = kb.as_editor()
    old_text = f"Старая запись: {EMAIL}."
    article = kb.make_published(author=editor.user, text=old_text)
    kb.add_version(article, author=editor.user, text="Чистый текст без данных")
    before = _state(article)
    assert before[1] == 2
    url = f"/kb/{article.pk}/versions/1/restore/"
    response = editor.client.post(url, {})
    _warning(response, {EMAIL}, "Сохранить всё равно")
    assert _state(article) == before, "предупреждение не меняет статью и не пишет версию"
    with django_capture_on_commit_callbacks(execute=True):
        confirmed = editor.client.post(url, {"confirm_pdn": "1"})
    assert confirmed.status_code == 302 and confirmed["Location"] == f"/kb/{article.pk}/"
    article.refresh_from_db()
    assert (article.version_no, article.text) == (3, old_text)
    (restored,) = article.versions.filter(number=3)
    assert restored.comment == "Восстановлено из версии 1" and restored.text == old_text


def test_draft_save_without_publishing_has_no_warning():
    """FR-431: сохранение черновика без публикации (и первое сохранение новой статьи) не предупреждает, хотя адрес
    в тексте есть."""
    editor = kb.as_editor()
    draft = kb.make_draft(author=editor.user, text="Черновик")
    text = f"Контакт: {EMAIL}, {PHONE}"
    response = editor.client.post(f"/kb/{draft.pk}/edit/", _edit_data(draft, text=text, action="save"))
    assert response.status_code == 302 and response["Location"] == f"/kb/{draft.pk}/"
    draft.refresh_from_db()
    assert (draft.state, draft.version_no, draft.text) == ("draft", 2, text)
    created = editor.client.post("/kb/new/", {
        "title": "Новый черновик с данными", "text": text, "rubric": kb.general_rubric().pk, "tags": "", "comment": ""})
    assert created.status_code == 302
    new = model("knowledge.Article").objects.get(title="Новый черновик с данными")
    assert (new.state, new.version_no, new.text) == ("draft", 1, text)
    articles = importlib.import_module("apps.knowledge.services.articles")
    form = articles.ArticleForm(title=draft.title, text=text + " ещё", rubric_id=draft.rubric_id, tags="")
    result = articles.save(editor.user, draft.pk, 2, form)
    assert result.kind == "saved" and result.pdn == []


def test_git_address_in_code_gives_no_warning_same_outside_code_warns():
    """FR-428, FR-431 (сценарий 14): `git@github.com` в блоке и в строке кода — публикация без предупреждения; тот
    же адрес вне кода — предупреждение со списком."""
    editor = kb.as_editor()
    in_code = (f"Клонирование:\n\n```\ngit clone {GIT}:org/repo.git\n```\n\n"
               f"Или команда `ssh {GIT}` в строке.")
    outside = f"Клонирование:\n\nИли команда ssh {GIT} в строке."
    coded = kb.make_draft(author=editor.user, text=in_code)
    response = editor.client.post(f"/kb/{coded.pk}/publish/", {"base_version": 1, "confirm_pdn": ""})
    assert response.status_code == 302, "адрес в коде предупреждения не даёт"
    coded.refresh_from_db()
    assert (coded.state, coded.version_no) == ("published", 1)
    bare = kb.make_draft(author=editor.user, text=outside)
    before = _state(bare)
    response = editor.client.post(f"/kb/{bare.pk}/publish/", {"base_version": 1, "confirm_pdn": ""})
    _warning(response, {GIT}, "Опубликовать всё равно")
    assert _state(bare) == before and before[0] == "draft"


def test_found_pdn_not_written_to_journal(django_capture_on_commit_callbacks):
    """FR-431: найденное в журнал не пишется — ни на предупреждении, ни после подтверждения (в журнале номер,
    заголовок и номер версии, текста нет)."""
    editor = kb.as_editor()
    article = kb.make_published(author=editor.user, text="Было")
    text = f"Связь: {EMAIL} и {PHONE}"
    events = model("core.AuditEvent").objects
    mark = events.count()
    editor.client.post(f"/kb/{article.pk}/edit/", _edit_data(article, text=text))
    assert events.count() == mark, "предупреждение не пишет в журнал"
    draft = kb.make_draft(author=editor.user, text=text)
    mark = events.count()
    editor.client.post(f"/kb/{draft.pk}/publish/", {"base_version": 1, "confirm_pdn": ""})
    assert events.count() == mark
    with django_capture_on_commit_callbacks(execute=True):
        editor.client.post(f"/kb/{article.pk}/edit/", _edit_data(article, text=text, confirm_pdn="1"))
        editor.client.post(f"/kb/{draft.pk}/publish/", {"base_version": 1, "confirm_pdn": "1"})
    draft.refresh_from_db()
    assert draft.state == "published"
    for entry in events.all():
        dump = repr((entry.before, entry.after, entry.object_id))
        assert EMAIL not in dump and PHONE not in dump, f"ПДн в журнале: {entry.action}"
    assert events.filter(action="knowledge.article_published").count() == 1


# --- 2. mask_plain: тема заявки (FR-428) ------------------------------------------------------------------------

def test_mask_plain_hides_email_and_phone_in_subject():
    """FR-428: в теме заявки адрес и телефон заменены на «[скрыто]», остальное без изменений; тема — простой текст,
    поэтому прячется и найденное в обратных кавычках."""
    pdn = _pdn()
    assert pdn.mask_plain(f"Сбой у {EMAIL}, звонить {PHONE}") == f"Сбой у {HIDDEN}, звонить {HIDDEN}"
    assert pdn.mask_plain(f"Тема `{EMAIL}` в кавычках") == f"Тема `{HIDDEN}` в кавычках"
    assert pdn.mask_plain("Принтер не печатает") == "Принтер не печатает"


def test_mask_plain_hides_both_phone_forms_keeps_ten_digit_number():
    """FR-428 (сценарий 15): «8 (912) 345-67-89» и «+7-912-345-67-89» (и слитно) скрыты, число из 10 цифр без `+7`
    и `8` остаётся."""
    pdn = _pdn()
    eight = "8 (" + "912" + ") " + "345-67-89"
    plus = "+7" + "-912-345-67-89"
    solid = "8" + "9123456789"
    number = "7707" + "083893"
    assert pdn.mask_plain(f"Звоните {eight}, {plus}, {solid}; ИНН {number}") == \
        f"Звоните {HIDDEN}, {HIDDEN}, {HIDDEN}; ИНН {number}"


# --- 3. mask_resolution: решение — будущий текст статьи (FR-428) --------------------------------------------------

def test_mask_resolution_hides_email_and_phone_outside_code():
    """FR-428 (сценарий 2): в решении вне кода адрес и телефон заменены на «[скрыто]», остальной текст без изменений."""
    pdn = _pdn()
    text = f"Напишите на {EMAIL}\n\nили позвоните {PHONE}\n\nНомер 7707{'083893'} остаётся."
    assert pdn.mask_resolution(text) == \
        f"Напишите на {HIDDEN}\n\nили позвоните {HIDDEN}\n\nНомер 7707083893 остаётся."


def test_mask_resolution_leaves_backtick_fenced_lines_untouched():
    """FR-428: строки внутри ограждения из трёх обратных кавычек не меняются, вне — скрываются."""
    pdn = _pdn()
    text = (f"До: {EMAIL}\n```\ngit clone {GIT}:org/repo.git\nтел {PHONE}\n```\nПосле: {EMAIL}")
    expected = (f"До: {HIDDEN}\n```\ngit clone {GIT}:org/repo.git\nтел {PHONE}\n```\nПосле: {HIDDEN}")
    assert pdn.mask_resolution(text) == expected


def test_mask_resolution_leaves_tilde_fenced_lines_untouched():
    """FR-428: то же для ограждения из трёх `~`."""
    pdn = _pdn()
    text = (f"До: {EMAIL}\n~~~\ngit clone {GIT}:org/repo.git\nтел {PHONE}\n~~~\nПосле: {PHONE}")
    expected = (f"До: {HIDDEN}\n~~~\ngit clone {GIT}:org/repo.git\nтел {PHONE}\n~~~\nПосле: {HIDDEN}")
    assert pdn.mask_resolution(text) == expected


def test_mask_resolution_leaves_inline_backtick_spans_untouched():
    """FR-428: участки в обратных кавычках на остальных строках не меняются, всё вне них на той же строке скрыто."""
    pdn = _pdn()
    text = f"Команда `ssh {GIT}` и почта {EMAIL}, ещё `{PHONE}` и {PHONE}."
    expected = f"Команда `ssh {GIT}` и почта {HIDDEN}, ещё `{PHONE}` и {HIDDEN}."
    assert pdn.mask_resolution(text) == expected


def test_mask_resolution_masks_four_space_indented_text():
    """FR-428, план: отступ в 4 пробела кодом не считается — такая строка скрывается (строже правила, а не мягче)."""
    pdn = _pdn()
    text = f"Абзац.\n\n    ssh {EMAIL}\n    тел {PHONE}\n\nКонец."
    assert pdn.mask_resolution(text) == f"Абзац.\n\n    ssh {HIDDEN}\n    тел {HIDDEN}\n\nКонец."


def test_mask_resolution_crlf_becomes_lf_and_phone_split_by_crlf_is_not_hidden_like_lf():
    """FR-428: `\\r\\n` приводится к `\\n`; телефон, разорванный переводом строки, не скрывается — как и при `\\n`
    (и как его не находит `find`)."""
    pdn = _pdn()
    split = "+7 (912) 345" + "\r\n" + "67-89 конец"
    crlf = f"Почта {EMAIL}\r\nтел {PHONE}\r\nномер {split}"
    result = pdn.mask_resolution(crlf)
    assert "\r" not in result
    assert result == f"Почта {HIDDEN}\nтел {HIDDEN}\nномер +7 (912) 345\n67-89 конец"
    assert result == pdn.mask_resolution(crlf.replace("\r\n", "\n"))
    assert pdn.mask_plain(split) == "+7 (912) 345\n67-89 конец"
    assert pdn.find("", split) == []
