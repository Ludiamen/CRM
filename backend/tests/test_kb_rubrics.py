"""T-5110: рубрики базы знаний — создание, названия, права, журнал (FR-406, FR-418, FR-419, FR-438, NFR-408).
Сценарии спеки среза 005 о рубриках: управляющий ведёт дерево, читатель и редактор его не трогают.

Имена кода среза 005 импортируются внутри тестов; разметку разбирает `html.parser`, элементы ищутся по зацепкам
`data-*` (CONTRACT-005, раздел 11.7). Отказы формы — 200 с `[data-error][data-code]` (раздел 10.1)."""
import functools
import json
from html.parser import HTMLParser

import pytest
from django.db import IntegrityError, transaction

from tests import support
from tests import support_kb as kb

pytestmark = pytest.mark.django_db

NEW = "/kb/rubrics/new/"
LIST = "/kb/rubrics/"
_VOID = {"input", "br", "img", "meta", "link", "hr", "area", "base", "col", "embed", "source", "track", "wbr"}


# --- разбор разметки и вызовы (только для этого файла) -----------------------------------------------------

class _El:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.raw = tag, attrs, parent, ""

    @property
    def text(self) -> str:
        return " ".join(self.raw.split())


class _Doc(HTMLParser):
    def __init__(self, html: str):
        super().__init__(convert_charrefs=True)
        self.elements, self._stack = [], []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        el = _El(tag, {k: (v if v is not None else "") for k, v in attrs}, self._stack[-1] if self._stack else None)
        self.elements.append(el)
        if tag not in _VOID:
            self._stack.append(el)

    def handle_startendtag(self, tag, attrs):
        self.elements.append(_El(tag, {k: (v if v is not None else "") for k, v in attrs},
                                 self._stack[-1] if self._stack else None))

    def handle_endtag(self, tag):
        for i in range(len(self._stack) - 1, -1, -1):
            if self._stack[i].tag == tag:
                del self._stack[i:]
                break

    def handle_data(self, data):
        for el in self._stack:
            el.raw += data


def _inside(el, ancestor) -> bool:
    node = el.parent
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent
    return False


@functools.lru_cache(maxsize=16)
def _elements(html: str) -> tuple:
    """Разбор один на текст страницы: узлы разных вызовов `find` сравниваются по `is` (`_inside`)."""
    return tuple(_Doc(html).elements)


def find(response_or_html, tag: str | None = None, **attrs) -> list:
    """Элементы по тегу и атрибутам (`data_code="x"` → `data-code="x"`; `True` — атрибут есть)."""
    html = response_or_html if isinstance(response_or_html, str) else response_or_html.content.decode()
    want = {k.replace("_", "-"): v for k, v in attrs.items()}
    return [el for el in _elements(html)
            if (tag is None or el.tag == tag)
            and all((k in el.attrs) if v is True else el.attrs.get(k) == v for k, v in want.items())]


def refusal(response, field: str, code: str):
    """Отказ у поля: статус 200 и один `[data-error=field][data-code=code]`; возвращает элемент."""
    assert response.status_code == 200, response.status_code
    found = find(response, data_error=field, data_code=code)
    assert len(found) == 1, (field, code, [(e.attrs.get("data-error"), e.attrs.get("data-code")) for e in
                                           find(response, data_error=True)])
    return found[0]


def post_new(client, name: str, parent=None, **extra):
    return client.post(NEW, {"name": name, "parent": "" if parent is None else str(parent.pk)}, **extra)


def Rubric():
    return support.model("knowledge.Rubric")


def events(*actions: str) -> list:
    return list(support.model("core.AuditEvent").objects.filter(action__in=actions).order_by("id"))


def flash(client, response) -> str:
    """Сообщение `[role=status]` на странице назначения редиректа."""
    assert response.status_code == 302, response.status_code
    page = client.get(response["Location"])
    return " ".join(e.text for e in find(page, role="status"))


# --- права и маршруты --------------------------------------------------------------------------------------

def test_manager_creates_renames_moves_rubric_by_separate_urls():
    """FR-418: управляющий создаёт, переименовывает и переносит рубрику тремя отдельными адресами; успех — 302 на
    `/kb/rubrics/` и флеш на странице; состояние базы меняется ровно этим действием."""
    manager = kb.as_manager()
    general, other = kb.general_rubric(), kb.make_rubric("Почта")

    created = post_new(manager.client, "Сети", general)
    assert created.status_code == 302 and created["Location"] == LIST
    assert "Рубрика создана" in flash(manager.client, created)
    rubric = Rubric().objects.get(name="Сети")
    assert (rubric.parent_id, rubric.depth, rubric.is_default) == (general.pk, 2, False)

    renamed = manager.client.post(f"/kb/rubrics/{rubric.pk}/rename/", {"name": "Сети и связь"})
    assert renamed.status_code == 302 and renamed["Location"] == LIST
    assert "Рубрика переименована" in flash(manager.client, renamed)
    rubric.refresh_from_db()
    assert (rubric.name, rubric.parent_id, rubric.depth) == ("Сети и связь", general.pk, 2)

    moved = manager.client.post(f"/kb/rubrics/{rubric.pk}/move/", {"parent": str(other.pk)})
    assert moved.status_code == 302 and moved["Location"] == LIST
    assert "Рубрика перенесена" in flash(manager.client, moved)
    rubric.refresh_from_db()
    assert (rubric.name, rubric.parent_id, rubric.depth) == ("Сети и связь", other.pk, 2)

    back = manager.client.post(f"/kb/rubrics/{rubric.pk}/move/", {"parent": ""})
    assert back.status_code == 302
    rubric.refresh_from_db()
    assert (rubric.parent_id, rubric.depth) == (None, 1)
    assert Rubric().objects.filter(pk=rubric.pk).count() == 1


def test_non_manager_denied_rubric_urls_and_management_page():
    """FR-418, FR-406: без права «Управление базой знаний» (читатель, редактор) страница рубрик и все POST рубрик —
    403, в базе ничего не меняется; без входа — 302; управляющему страница открыта (`[data-kb-rubrics]`)."""
    target = kb.make_rubric("Сети")
    before = list(Rubric().objects.order_by("pk").values_list("pk", "name", "parent_id", "depth"))
    posts = [(NEW, {"name": "Новая", "parent": ""}), (f"/kb/rubrics/{target.pk}/rename/", {"name": "Другое"}),
             (f"/kb/rubrics/{target.pk}/move/", {"parent": str(kb.general_rubric().pk)}),
             (f"/kb/rubrics/{target.pk}/delete/", {})]
    for session in (kb.as_reader(), kb.as_editor()):
        assert session.client.get(LIST).status_code == 403
        for url, data in posts:
            assert session.client.post(url, data).status_code == 403, url
    assert list(Rubric().objects.order_by("pk").values_list("pk", "name", "parent_id", "depth")) == before
    assert events("knowledge.rubric_created", "knowledge.rubric_renamed", "knowledge.rubric_moved",
                  "knowledge.rubric_deleted") == []

    anonymous = support.make_client()
    assert anonymous.get(LIST).status_code == 302
    assert anonymous.post(NEW, {"name": "Новая", "parent": ""}).status_code == 302
    assert Rubric().objects.count() == len(before)

    page = kb.as_manager().client.get(LIST)
    assert page.status_code == 200 and find(page, data_kb_rubrics=True)


# --- глубина -----------------------------------------------------------------------------------------------

def test_three_level_tree_created():
    """FR-418: дерево из трёх уровней создаётся; `depth` — глубина родителя плюс один, страница показывает глубину;
    создание идёт под замком `knowledge.rubrics` (параметром)."""
    from apps.knowledge.services import rubrics

    manager = kb.as_manager()
    assert post_new(manager.client, "Уровень один").status_code == 302
    first = Rubric().objects.get(name="Уровень один")
    assert post_new(manager.client, "Уровень два", first).status_code == 302
    second = Rubric().objects.get(name="Уровень два")
    assert post_new(manager.client, "Уровень три", second).status_code == 302
    third = Rubric().objects.get(name="Уровень три")
    assert [(r.parent_id, r.depth) for r in (first, second, third)] == [(None, 1), (first.pk, 2), (second.pk, 3)]

    page = manager.client.get(LIST)
    depth_by_id = {el.attrs["data-rubric-id"]: el.attrs.get("data-depth") for el in find(page, "li", data_rubric_id=True)}
    assert [depth_by_id[str(r.pk)] for r in (first, second, third)] == ["1", "2", "3"]

    sqls = kb.sql_of(rubrics.create, manager.user, "Ещё одна", None)
    assert kb.AdvisoryLock("exclusive", "knowledge.rubrics") in kb.advisory_locks(sqls)


def test_fourth_level_refused_not_deeper_than_three_levels():
    """FR-418: родитель на третьем уровне — отказ `too_deep` у поля `parent` («Не глубже трёх уровней»); рубрика не
    создаётся, журнал пуст; служба отдаёт `KnowledgeError(code="too_deep", field="parent")`."""
    from apps.knowledge.services import KnowledgeError, rubrics

    manager = kb.as_manager()
    tree = kb.rubric_tree({"А": {"Б": {"В": {}}}})
    count = Rubric().objects.count()

    response = post_new(manager.client, "Г", tree["В"])
    assert "Не глубже трёх уровней" in refusal(response, "parent", "too_deep").text
    assert Rubric().objects.count() == count and not Rubric().objects.filter(name="Г").exists()

    with pytest.raises(KnowledgeError) as caught:
        rubrics.create(manager.user, "Г", tree["В"].pk)
    assert (caught.value.code, caught.value.field) == ("too_deep", "parent")
    assert Rubric().objects.count() == count
    assert events("knowledge.rubric_created") == []

    # родитель, которого больше нет: отказ `parent_missing` у поля `parent` («Выбранной рубрики больше нет»)
    gone_id = Rubric().objects.order_by("-pk").first().pk + 1000
    missing = manager.client.post(NEW, {"name": "Д", "parent": str(gone_id)})
    assert "Выбранной рубрики больше нет" in refusal(missing, "parent", "parent_missing").text
    with pytest.raises(KnowledgeError) as caught:
        rubrics.create(manager.user, "Д", gone_id)
    assert (caught.value.code, caught.value.field) == ("parent_missing", "parent")
    assert Rubric().objects.count() == count and events("knowledge.rubric_created") == []

    assert post_new(manager.client, "Г", tree["Б"]).status_code == 302  # на втором уровне родитель ещё допустим
    assert Rubric().objects.get(name="Г").depth == 3


# --- название ----------------------------------------------------------------------------------------------

def test_name_100_accepted_101_refused_input_kept():
    """FR-418: название до 100 знаков принимается, 101 — отказ `name_too_long` у поля `name`; введённое остаётся в
    поле формы; в базе ничего не меняется."""
    manager = kb.as_manager()
    long_name, over_name = "а" * 100, "б" * 101

    assert post_new(manager.client, long_name).status_code == 302
    assert Rubric().objects.filter(name=long_name).count() == 1
    count = Rubric().objects.count()

    response = post_new(manager.client, over_name)
    assert "Название не длиннее 100 знаков" in refusal(response, "name", "name_too_long").text
    assert Rubric().objects.count() == count
    forms = find(response, "form", data_form="kb-rubric-new")
    assert forms, "нет формы kb-rubric-new"
    inputs = [el for el in find(response, "input", name="name") if _inside(el, forms[0])]
    assert inputs and inputs[0].attrs.get("value") == over_name


def test_name_trimmed_and_empty_refused():
    """FR-418: пробелы по краям отрезаются (в базе и в журнале — название без них); пустое и из одних пробелов —
    отказ `name_empty` у поля `name` без записи в базу и журнал."""
    manager = kb.as_manager()
    assert post_new(manager.client, "  Сети \t").status_code == 302
    rubric = Rubric().objects.get(name="Сети")
    created, = events("knowledge.rubric_created")
    assert created.after["name"] == "Сети"

    count = Rubric().objects.count()
    for blank in ("", "   ", " \t "):
        response = post_new(manager.client, blank)
        assert "Введите название рубрики" in refusal(response, "name", "name_empty").text
    renamed = manager.client.post(f"/kb/rubrics/{rubric.pk}/rename/", {"name": "   "})
    refusal(renamed, "name", "name_empty")
    rubric.refresh_from_db()
    assert rubric.name == "Сети" and Rubric().objects.count() == count
    assert len(events("knowledge.rubric_created")) == 1 and events("knowledge.rubric_renamed") == []


def test_duplicate_name_among_siblings_case_insensitive_refused():
    """FR-418: название уникально среди соседей без учёта регистра и пробелов по краям («VPN» и «vpn» — одно);
    отказ `name_duplicate` у поля `name`, как обычным POST, так и из HTMX (фрагмент), службой — `KnowledgeError`."""
    from apps.knowledge.services import KnowledgeError, rubrics

    manager = kb.as_manager()
    parent = kb.make_rubric("Сети")
    kb.make_rubric("VPN", parent=parent)
    count = Rubric().objects.count()

    for variant in ("vpn", "Vpn", " VPN "):
        response = post_new(manager.client, variant, parent)
        text = refusal(response, "name", "name_duplicate").text
        assert "Рубрика с таким названием уже есть на этом уровне" in text
    htmx = post_new(manager.client, "vPn", parent, **support.HX)
    refusal(htmx, "name", "name_duplicate")
    with pytest.raises(KnowledgeError) as caught:
        rubrics.create(manager.user, "vpn", parent.pk)
    assert (caught.value.code, caught.value.field) == ("name_duplicate", "name")
    assert Rubric().objects.count() == count and events("knowledge.rubric_created") == []

    cyrillic = kb.make_rubric("Почта", parent=parent)
    assert cyrillic.pk
    refusal(post_new(manager.client, "ПОЧТА", parent), "name", "name_duplicate")


def test_same_name_in_different_branches_allowed():
    """FR-418: одинаковое название в разных ветках (у разных родителей) допустимо; «соседи» — только дети одного
    родителя."""
    manager = kb.as_manager()
    left, right = kb.make_rubric("Левая"), kb.make_rubric("Правая")
    for parent in (left, right):
        assert post_new(manager.client, "Настройка", parent).status_code == 302
    child = Rubric().objects.filter(name="Настройка")
    assert sorted(child.values_list("parent_id", flat=True)) == sorted([left.pk, right.pk])
    deeper = kb.make_rubric("Вложенная", parent=left)
    assert post_new(manager.client, "Настройка", deeper).status_code == 302
    assert Rubric().objects.filter(name="Настройка").count() == 3


def test_same_name_among_root_rubrics_refused():
    """FR-418: среди корневых рубрик название тоже уникально без учёта регистра (в том числе с «Общее», родитель
    пуст); на уровне базы — то же (`NULL` не считается различным)."""
    manager = kb.as_manager()
    response = post_new(manager.client, "общее")
    refusal(response, "name", "name_duplicate")
    kb.make_rubric("Сети")
    refusal(post_new(manager.client, "СЕТИ"), "name", "name_duplicate")
    refusal(post_new(manager.client, " сети "), "name", "name_duplicate")
    assert Rubric().objects.filter(name__iexact="общее").count() == 1
    assert Rubric().objects.filter(name__iexact="сети").count() == 1


def test_rename_to_sibling_name_other_case_refused():
    """FR-418: переименование в название соседа в другом регистре — отказ `name_duplicate` у поля `name`; рубрика и
    журнал не меняются; у корневой рубрики сосед — другая корневая."""
    from apps.knowledge.services import KnowledgeError, rubrics

    manager = kb.as_manager()
    parent = kb.make_rubric("Сети")
    first, second = kb.make_rubric("Wi-Fi", parent=parent), kb.make_rubric("Маршрутизаторы", parent=parent)
    response = manager.client.post(f"/kb/rubrics/{second.pk}/rename/", {"name": "WI-FI"})
    refusal(response, "name", "name_duplicate")
    with pytest.raises(KnowledgeError) as caught:
        rubrics.rename(manager.user, second.pk, "wi-fi")
    assert (caught.value.code, caught.value.field) == ("name_duplicate", "name")
    root = kb.make_rubric("Почта")
    refusal(manager.client.post(f"/kb/rubrics/{root.pk}/rename/", {"name": "сети"}), "name", "name_duplicate")
    for rubric, name in ((second, "Маршрутизаторы"), (first, "Wi-Fi"), (root, "Почта")):
        rubric.refresh_from_db()
        assert rubric.name == name
    assert events("knowledge.rubric_renamed") == []


def test_db_constraint_rejects_duplicate_siblings_nulls_not_distinct():
    """FR-418: ограничение базы — страховка: прямая запись второй рубрики с тем же названием (без учёта регистра)
    у того же родителя, в том числе у корневых (`NULL` не различается), — `IntegrityError`; у другого родителя можно."""
    kb.make_rubric("VPN")
    with pytest.raises(IntegrityError), transaction.atomic():
        kb.make_rubric("vpn")
    parent, other = kb.make_rubric("Сети"), kb.make_rubric("Почта")
    kb.make_rubric("Wi-Fi", parent=parent)
    with pytest.raises(IntegrityError), transaction.atomic():
        kb.make_rubric("WI-FI", parent=parent)
    kb.make_rubric("Wi-Fi", parent=other)  # у другого родителя то же название допустимо
    kb.make_rubric("vpn", parent=parent)  # и корневое «VPN» не мешает вложенному
    assert Rubric().objects.filter(name__iexact="vpn").count() == 2


def test_rubrics_ordered_by_name_case_insensitive():
    """FR-418: порядок рубрик среди соседей — по названию без учёта регистра (`Lower(name)`): `tree()` и страница
    управления дают одну очерёдность."""
    from apps.knowledge.services import rubrics

    parent = kb.make_rubric("Раздел")
    made = {name: kb.make_rubric(name, parent=parent) for name in ("Бета", "альфа", "Гамма", "дельта")}
    expected = ["альфа", "Бета", "Гамма", "дельта"]

    def children(nodes):
        for node in nodes:
            if node.rubric.pk == parent.pk:
                return [child.rubric.name for child in node.children]
            found = children(node.children)
            if found is not None:
                return found
        return None

    assert children(rubrics.tree()) == expected

    page = kb.as_manager().client.get(LIST)
    shown = {el.attrs["data-rubric-id"]: el for el in find(page, "li", data_rubric_id=True)}
    order = [el for el in find(page, "li", data_rubric_id=True) if el.attrs["data-rubric-id"] in
             {str(r.pk) for r in made.values()}]
    names = []
    for li in order:
        field = [e for e in find(page, data_field="name") if _inside(e, li)]
        names.append(field[0].text)
    assert names == expected and len(shown) >= 5


# --- удаление пустой рубрики и журнал -----------------------------------------------------------------------

def test_delete_empty_rubric_writes_journal():
    """FR-419, FR-438: пустая рубрика удаляется (302 на `/kb/rubrics/`, флеш «Рубрика удалена»); журнал —
    `knowledge.rubric_deleted` с номером удалённой, названием и путём в `before`, пустым `after` и управляющим."""
    manager = kb.as_manager()
    parent = kb.make_rubric("Сети")
    victim = kb.make_rubric("Старая", parent=parent)
    pk = victim.pk

    response = manager.client.post(f"/kb/rubrics/{pk}/delete/")
    assert response.status_code == 302 and response["Location"] == LIST
    assert "Рубрика удалена" in flash(manager.client, response)
    assert not Rubric().objects.filter(pk=pk).exists() and Rubric().objects.filter(pk=parent.pk).exists()
    event, = events("knowledge.rubric_deleted")
    assert (event.object_type, event.object_id, event.actor_id) == ("knowledge.rubric", str(pk), manager.user.pk)
    assert event.before == {"name": "Старая", "path": "Сети / Старая"} and event.after == {}


def test_journal_create_rename_move_with_path_without_article_text():
    """FR-438: создание, переименование и перенос пишут `knowledge.rubric_created|renamed|moved` с названием и путём
    («Общее / Сети»), номером рубрики и управляющим; текста статьи рубрики в журнале нет."""
    manager = kb.as_manager()
    general, other = kb.general_rubric(), kb.make_rubric("Почта")
    assert post_new(manager.client, "Сети", general).status_code == 302
    rubric = Rubric().objects.get(name="Сети")
    article = kb.make_published(rubric=rubric, title="Уникальный заголовок статьи", text="Уникальный текст статьи")
    manager.client.post(f"/kb/rubrics/{rubric.pk}/rename/", {"name": "Сети и связь"})
    manager.client.post(f"/kb/rubrics/{rubric.pk}/move/", {"parent": str(other.pk)})

    created, = events("knowledge.rubric_created")
    renamed, = events("knowledge.rubric_renamed")
    moved, = events("knowledge.rubric_moved")
    for event in (created, renamed, moved):
        assert (event.object_type, event.object_id, event.actor_id) == ("knowledge.rubric", str(rubric.pk),
                                                                        manager.user.pk)
    assert created.before == {} and created.after == {"name": "Сети", "path": "Общее / Сети"}
    assert renamed.before == {"name": "Сети", "path": "Общее / Сети"}
    assert renamed.after == {"name": "Сети и связь", "path": "Общее / Сети и связь"}
    assert moved.before == {"name": "Сети и связь", "path": "Общее / Сети и связь"}
    assert moved.after == {"name": "Сети и связь", "path": "Почта / Сети и связь"}

    dump = json.dumps([[e.before, e.after] for e in events("knowledge.rubric_created", "knowledge.rubric_renamed",
                                                           "knowledge.rubric_moved")], ensure_ascii=False)
    assert article.title not in dump and article.text not in dump


def test_journal_records_rubric_name_and_actor_only():
    """FR-438: в записях о рубриках — только название и путь (ключи `name`, `path`), кто сделал и номер рубрики;
    ни номера или заголовка статьи, ни текста, ни ФИО."""
    manager = kb.as_manager()
    parent = kb.make_rubric("Сети")
    kb.make_published(rubric=parent, title="Заголовок статьи рубрики", text="Текст статьи рубрики")
    assert post_new(manager.client, "Новая", parent).status_code == 302
    child = Rubric().objects.get(name="Новая")
    manager.client.post(f"/kb/rubrics/{child.pk}/rename/", {"name": "Новая два"})
    manager.client.post(f"/kb/rubrics/{child.pk}/move/", {"parent": ""})
    manager.client.post(f"/kb/rubrics/{child.pk}/delete/")

    written = events("knowledge.rubric_created", "knowledge.rubric_renamed", "knowledge.rubric_moved",
                     "knowledge.rubric_deleted")
    assert [e.action for e in written] == ["knowledge.rubric_created", "knowledge.rubric_renamed",
                                           "knowledge.rubric_moved", "knowledge.rubric_deleted"]
    for event in written:
        assert event.actor_id == manager.user.pk and event.object_type == "knowledge.rubric"
        assert event.object_id == str(child.pk)
        assert set(event.before) | set(event.after) <= {"name", "path"}, (event.action, event.before, event.after)
        assert set(event.before) <= {"name", "path"} and set(event.after) <= {"name", "path"}
    dump = json.dumps([[e.before, e.after] for e in written], ensure_ascii=False)
    for text in ("Заголовок статьи рубрики", "Текст статьи рубрики", str(manager.user.email)):
        assert text not in dump


# --- ввод только параметром ---------------------------------------------------------------------------------

def test_name_with_quote_percent_underscore_backslash_semicolon_dashes_is_plain_text_and_percent_is_not_wildcard_among_siblings():
    """FR-418, NFR-408: название с кавычками, `%`, `_`, обратной чертой, `;` и `--` — обычный текст: хранится как
    введено, показывается на странице как текст; `%` и `_` не шаблон среди соседей (проверка дубля не принимает
    «ab%» за шаблон), а различие регистра по-прежнему даёт дубль."""
    manager = kb.as_manager()
    nasty = "O'Re\"illy 100% a_b \\ ; -- DROP"
    assert post_new(manager.client, nasty).status_code == 302
    rubric = Rubric().objects.get(name=nasty)
    created, = events("knowledge.rubric_created")
    assert created.after["name"] == nasty
    page = manager.client.get(LIST)
    li, = [el for el in find(page, "li", data_rubric_id=str(rubric.pk))]
    shown = [e for e in find(page, data_field="name") if _inside(e, li)]
    assert shown and shown[0].text == nasty
    assert Rubric().objects.filter(pk=rubric.pk).exists() and Rubric().objects.count() >= 2

    assert post_new(manager.client, "ab%").status_code == 302
    for other in ("abX", "abXYZ", "Ab"):
        assert post_new(manager.client, other).status_code == 302, other  # `%` не шаблон «любые знаки»
    refusal(post_new(manager.client, "AB%"), "name", "name_duplicate")

    assert post_new(manager.client, "a_c").status_code == 302
    assert post_new(manager.client, "axc").status_code == 302  # `_` не шаблон «один знак»
    refusal(post_new(manager.client, "A_C"), "name", "name_duplicate")
    assert post_new(manager.client, "x\\y").status_code == 302
    assert post_new(manager.client, "x\\\\y").status_code == 302
    assert Rubric().objects.filter(name__in=["x\\y", "x\\\\y"]).count() == 2
