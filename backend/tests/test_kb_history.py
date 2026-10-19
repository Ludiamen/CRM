"""T-5105: история версий и сравнение версий статьи (FR-411, FR-449). Сценарии 3 и 7 спеки среза 005.

Страницы `/kb/<id>/history/` и `/kb/<id>/compare/?v=N&v=M` (CONTRACT-005, 10.3, 11.6, 12.1): список версий по номеру
вниз, пометка «уволен», флажки и ссылки на просмотр, видимость (период черновика, корзина, чужой черновик),
построчное сравнение (`+`, `−`, экранирование, поля «было / стало», свёртка контекста, предел 2 000 изменений),
подсказки «Отметьте две версии» и «Версия удалена». Код среза на уровне модуля не импортируется.
"""
import re
from html.parser import HTMLParser

import pytest
from django.utils import timezone

from tests import support, support_kb as kb

pytestmark = pytest.mark.django_db

_VOID = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source",
                   "track", "wbr"})


# --- разбор разметки: маленькое дерево, чтобы искать по зацепкам `data-*` ---------------------------------

class _Node:
    def __init__(self, tag, attrs, parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, attrs, parent, []

    def walk(self):
        yield self
        for child in self.children:
            if isinstance(child, _Node):
                yield from child.walk()

    def find(self, tag=None, **attrs):
        """Потомки по тегу и атрибутам; значение `True` — атрибут есть, любое; `class_` — токен класса."""
        found = []
        for node in self.walk():
            if node is self:
                continue
            if tag and node.tag != tag:
                continue
            ok = True
            for name, want in attrs.items():
                name = name.replace("_", "-") if name != "class_" else "class"
                have = node.attrs.get(name)
                if want is True:
                    ok = ok and have is not None
                elif name == "class":
                    ok = ok and want in (have or "").split()
                else:
                    ok = ok and have == want
            if ok:
                found.append(node)
        return found

    def text(self, skip=()):
        parts = []

        def collect(node):
            for child in node.children:
                if isinstance(child, _Node):
                    if child.tag not in skip and child.tag not in ("script", "style"):
                        collect(child)
                else:
                    parts.append(child)
        collect(self)
        return " ".join("".join(parts).split())


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {})
        self._cur = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, {name: ("" if value is None else value) for name, value in attrs}, self._cur)
        self._cur.children.append(node)
        if tag not in _VOID:
            self._cur = node

    def handle_startendtag(self, tag, attrs):
        self._cur.children.append(_Node(tag, {n: ("" if v is None else v) for n, v in attrs}, self._cur))

    def handle_endtag(self, tag):
        node = self._cur
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self._cur = node.parent

    def handle_data(self, data):
        self._cur.children.append(data)


def _dom(response) -> _Node:
    builder = _Builder()
    builder.feed(response.content.decode())
    return builder.root


def _get(client, path):
    return client.get(path)


def _history(client, article):
    return _get(client, f"/kb/{article.pk}/history/")


def _compare(client, article, *numbers, raw: str | None = None):
    query = raw if raw is not None else "&".join(f"v={n}" for n in numbers)
    return _get(client, f"/kb/{article.pk}/compare/?{query}")


def _rows(dom) -> dict[int, _Node]:
    return {int(row.attrs["data-version"]): row for row in dom.find("tr", data_version=True)}


def _row_numbers(dom) -> list[int]:
    return [int(row.attrs["data-version"]) for row in dom.find("tr", data_version=True)]


def _marked(dom, kind: str) -> list[str]:
    """Тексты строк `kb-diff-add` / `kb-diff-del` без знака в начале («+ » или «− »)."""
    mark = "+" if kind == "add" else "−"
    out = []
    for node in dom.find("div", class_=f"kb-diff-{kind}"):
        text = node.text()
        assert text.startswith(mark), (kind, text)
        out.append(text[len(mark):].strip())
    return out


def _field_sides(dom, name: str) -> dict[str, str]:
    rows = dom.find(data_kb_diff_field=name)
    assert len(rows) == 1, f"строка поля {name!r}: найдено {len(rows)}"
    sides = {}
    for side in ("before", "after"):
        found = rows[0].find(data_side=side)
        assert len(found) == 1, f"{name}: сторона {side!r}: найдено {len(found)}"
        sides[side] = found[0].text()
    return sides


def _editor_and_versions(texts, *, comments=None, **first):
    """Опубликованная статья с версиями по списку текстов; возвращает (статья, автор)."""
    author = support.make_employee(full_name="Анна Авторова")
    kb.grant(author, "knowledge.edit")
    article = kb.make_published(author=author, text=texts[0], **first)
    for index, text in enumerate(texts[1:], start=2):
        kb.add_version(article, author=author, text=text, comment=(comments or {}).get(index, ""))
    return article, author


# --- история ----------------------------------------------------------------------------------------

def test_history_lists_versions_descending_with_number_author_time_and_comment(clock):
    """FR-411: версии по номеру вниз; у каждой номер, автор, время по Москве и комментарий к правке."""
    reader = kb.as_reader()
    first_author = support.make_employee(full_name="Борис Первый")
    second_author = support.make_employee(full_name="Вера Вторая")
    kb.utc_midnight(clock)
    article = kb.make_published(author=first_author, title="История статьи", text="один", comment="первая запись")
    clock.advance(minutes=40)
    kb.add_version(article, author=second_author, text="два", comment="поправил команду")
    clock.advance(minutes=40)
    kb.add_version(article, author=first_author, text="три", comment="")
    response = _history(reader.client, article)
    assert response.status_code == 200
    dom = _dom(response)
    assert dom.find(data_kb_page="history")
    assert _row_numbers(dom) == [3, 2, 1]
    rows = _rows(dom)
    expected = {1: ("Борис Первый", "10.03.2026 03:00", "первая запись"),
                2: ("Вера Вторая", "10.03.2026 03:40", "поправил команду"),
                3: ("Борис Первый", "10.03.2026 04:20", "")}
    for number, (author, moment, comment) in expected.items():
        row = rows[number]
        assert author in row.find(data_field="author")[0].text()
        stamps = row.find("time", data_at=True)
        assert [s.text() for s in stamps] == [moment], number
        assert row.find(data_field="comment")[0].text() == comment
        assert str(number) in row.find("input", name="v")[0].attrs["value"]


def test_history_marks_dismissed_author_with_fired_label():
    """FR-411: уволенный автор версии — «ФИО (уволен)» в `span[data-dismissed="true"]`, у действующего пометки нет."""
    reader = kb.as_reader()
    gone = support.make_employee(full_name="Иван Уволенов", state="dismissed")
    active = support.make_employee(full_name="Пётр Действующий")
    article = kb.make_published(author=gone, text="один")
    kb.add_version(article, author=active, text="два", comment="правка")
    dom = _dom(_history(reader.client, article))
    rows = _rows(dom)
    marks = rows[1].find("span", data_dismissed="true")
    assert len(marks) == 1
    assert "Иван Уволенов" in marks[0].text() and "(уволен)" in marks[0].text()
    assert "Пётр Действующий" in rows[2].find(data_field="author")[0].text()
    assert not rows[2].find("span", data_dismissed="true")
    assert "(уволен)" not in rows[2].text()


def test_history_has_checkboxes_and_each_version_links_to_its_view():
    """FR-411: форма сравнения (GET на compare), флажок `v` у каждой версии, ссылка на просмотр версии, кнопка."""
    reader = kb.as_reader()
    article, _ = _editor_and_versions(["один", "два", "три"])
    dom = _dom(_history(reader.client, article))
    forms = dom.find("form", data_form="kb-compare")
    assert len(forms) == 1
    assert forms[0].attrs.get("method", "").lower() == "get"
    assert forms[0].attrs.get("action") == f"/kb/{article.pk}/compare/"
    buttons = forms[0].find("button", data_action="kb-compare")
    assert len(buttons) == 1 and "Сравнить выбранные версии" in buttons[0].text()
    rows = _rows(dom)
    assert sorted(rows) == [1, 2, 3]
    for number, row in rows.items():
        boxes = row.find("input", name="v")
        assert len(boxes) == 1 and boxes[0].attrs.get("type") == "checkbox"
        assert boxes[0].attrs.get("value") == str(number)
        links = row.find("a", data_action="kb-version-open")
        assert len(links) == 1
        assert links[0].attrs.get("href") == f"/kb/{article.pk}/versions/{number}/"
    assert all(forms[0].find("tr", data_version=str(n)) for n in (1, 2, 3))


def test_draft_period_versions_are_visible_to_every_reader_after_publication():
    """FR-411 (сценарий 16): версии периода черновика видны любому сотруднику после публикации."""
    author_session = kb.as_editor()
    reader = kb.as_reader()
    draft = kb.make_draft(author=author_session.user, text="черновик один")
    kb.add_version(draft, author=author_session.user, text="черновик два", comment="правка до публикации")
    assert _history(reader.client, draft).status_code == 404
    support.model("knowledge.Article").objects.filter(pk=draft.pk).update(
        state="published", published_at=timezone.now())
    draft.refresh_from_db()
    kb.set_vectors(draft)
    response = _history(reader.client, draft)
    assert response.status_code == 200
    dom = _dom(response)
    assert _row_numbers(dom) == [2, 1]
    assert dom.find("tr", data_version="2")[0].find(data_field="comment")[0].text() == "правка до публикации"


def test_history_of_trash_article_is_visible_only_to_manager():
    """FR-411: у статьи в корзине история и сравнение видны только управляющему, остальным 410 без данных."""
    manager = kb.as_manager()
    article = kb.make_trashed(title="Заголовок из корзины", text="один")
    kb.add_version(article, text="два", comment="правка в корзине")
    ok = _history(manager.client, article)
    assert ok.status_code == 200
    assert _row_numbers(_dom(ok)) == [2, 1]
    assert _compare(manager.client, article, 1, 2).status_code == 200
    for other in (kb.as_editor(), kb.as_reader()):
        for response in (_history(other.client, article), _compare(other.client, article, 1, 2)):
            assert response.status_code == 410
            body = response.content.decode()
            assert "Статья удалена" in body
            assert "Заголовок из корзины" not in body and "правка в корзине" not in body
            assert not _dom(response).find("tr", data_version=True)


def test_history_and_compare_of_foreign_draft_give_404_for_non_manager():
    """FR-411: чужой черновик для сотрудника без управления — 404, как у несуществующей статьи; управляющему виден."""
    owner = kb.as_editor()
    stranger = kb.as_editor()
    manager = kb.as_manager()
    draft = kb.make_draft(author=owner.user, title="Чужой черновик для проверки", text="один")
    kb.add_version(draft, author=owner.user, text="два", comment="правка черновика")
    assert _get(stranger.client, "/kb/987654321/history/").status_code == 404
    for response in (_history(stranger.client, draft), _compare(stranger.client, draft, 1, 2)):
        assert response.status_code == 404
        body = response.content.decode()
        assert "Чужой черновик для проверки" not in body and "правка черновика" not in body
    assert _history(owner.client, draft).status_code == 200
    assert _history(manager.client, draft).status_code == 200
    assert _compare(manager.client, draft, 1, 2).status_code == 200


# --- сравнение --------------------------------------------------------------------------------------

def test_compare_marks_added_lines_with_plus_and_removed_lines_with_minus():
    """FR-411 (сценарий 3): добавленное — `kb-diff-add` со знаком «+», удалённое — `kb-diff-del` с «−» и `<del>`."""
    reader = kb.as_reader()
    article, _ = _editor_and_versions(["первая\nвторая\nтретья", "первая\nвторая изменена\nтретья\nчетвёртая"])
    response = _compare(reader.client, article, 1, 2)
    assert response.status_code == 200
    dom = _dom(response)
    assert dom.find(data_kb_page="compare") and dom.find(data_kb_diff=True)
    assert not dom.find(data_kb_hint=True)
    assert _marked(dom, "del") == ["вторая"]
    assert _marked(dom, "add") == ["вторая изменена", "четвёртая"]
    deleted = dom.find("div", class_="kb-diff-del")[0]
    assert [d.text() for d in deleted.find("del")] == ["вторая"]


def test_compare_escapes_html_in_text_lines():
    """FR-411: текст строк экранирован — и в удалённых, и в добавленных строках."""
    reader = kb.as_reader()
    old_line = "<img src=x onerror=alert(2)>"
    new_line = "<script>alert(1)</script> и <b>жирный</b>"
    article, _ = _editor_and_versions([old_line, new_line])
    response = _compare(reader.client, article, 1, 2)
    assert response.status_code == 200
    body = response.content.decode()
    assert "<script>alert(1)</script>" not in body and "<b>жирный</b>" not in body
    assert "<img src=x" not in body
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in body
    assert "&lt;img src=x onerror=alert(2)&gt;" in body
    dom = _dom(response)
    assert _marked(dom, "del") == [old_line]
    assert _marked(dom, "add") == [new_line]


def test_compare_shows_title_change_as_separate_before_after_line():
    """FR-411: смена заголовка — отдельная строка «было / стало»; неизменённые рубрика и теги строк не дают."""
    reader = kb.as_reader()
    article, _ = _editor_and_versions(["тот же текст", "тот же текст"], title="Старый заголовок")
    kb.add_version(article, title="Новый заголовок", comment="переименовал")
    dom = _dom(_compare(reader.client, article, 1, 3))
    sides = _field_sides(dom, "title")
    assert "Старый заголовок" in sides["before"] and "Старый заголовок" not in sides["after"]
    assert "Новый заголовок" in sides["after"] and "Новый заголовок" not in sides["before"]
    assert not dom.find(data_kb_diff_field="rubric") and not dom.find(data_kb_diff_field="tags")
    assert not _marked(dom, "add") and not _marked(dom, "del")


def test_compare_shows_rubric_by_snapshot_name_even_if_rubric_renamed_or_deleted():
    """FR-411: рубрика в сравнении — по снимку `rubric_name`: переименование и удаление рубрики на него не влияют."""
    reader = kb.as_reader()
    Rubric = support.model("knowledge.Rubric")
    old_rubric = kb.make_rubric("Сети")
    new_rubric = kb.make_rubric("Почта")
    article, _ = _editor_and_versions(["текст"], rubric=old_rubric)
    kb.add_version(article, rubric=new_rubric, comment="перенёс в почту")
    Rubric.objects.filter(pk=old_rubric.pk).update(name="Сети переименованные")
    Rubric.objects.filter(pk=new_rubric.pk).update(name="Почта переименованная")

    def check():
        dom = _dom(_compare(reader.client, article, 1, 2))
        sides = _field_sides(dom, "rubric")
        assert "Сети" in sides["before"] and "переименованн" not in sides["before"]
        assert "Почта" in sides["after"] and "переименованн" not in sides["after"]
        assert not dom.find(data_kb_diff_field="title") and not dom.find(data_kb_diff_field="tags")

    check()
    old_rubric.delete()
    check()


def test_compare_shows_tag_change_as_separate_before_after_line():
    """FR-411: смена тегов — отдельная строка «было / стало» со всеми тегами каждой версии."""
    reader = kb.as_reader()
    article, _ = _editor_and_versions(["текст"], tags=("vpn", "сеть"))
    kb.add_version(article, tags=("vpn", "wifi"), comment="сменил теги")
    dom = _dom(_compare(reader.client, article, 1, 2))
    sides = _field_sides(dom, "tags")
    assert "vpn" in sides["before"] and "сеть" in sides["before"] and "wifi" not in sides["before"]
    assert "vpn" in sides["after"] and "wifi" in sides["after"] and "сеть" not in sides["after"]
    assert not dom.find(data_kb_diff_field="title") and not dom.find(data_kb_diff_field="rubric")


def test_compare_treats_higher_version_number_as_after_regardless_of_parameter_order():
    """FR-411: старший номер — «стало» при любом порядке параметров `v`."""
    reader = kb.as_reader()
    article, _ = _editor_and_versions(["красный\nобщая", "синий\nобщая", "зелёный\nобщая"], title="Заголовок 1")
    kb.add_version(article, title="Заголовок 4", comment="четвёртая")
    shapes = []
    for order in ((1, 4), (4, 1)):
        dom = _dom(_compare(reader.client, article, *order))
        sides = _field_sides(dom, "title")
        assert "Заголовок 1" in sides["before"] and "Заголовок 4" in sides["after"], order
        shapes.append((_marked(dom, "del"), _marked(dom, "add")))
    assert shapes[0] == shapes[1]
    assert shapes[0] == (["красный"], ["зелёный"])


def test_compare_with_one_or_four_marked_versions_shows_mark_two_versions_hint_and_no_diff():
    """FR-411 (сценарий 4): одна или четыре отметки — подсказка «Отметьте две версии» и разницы нет."""
    reader = kb.as_reader()
    article, _ = _editor_and_versions(["один", "два", "три", "четыре"], title="Заголовок")
    for numbers in ((1,), (1, 2, 3, 4)):
        response = _compare(reader.client, article, *numbers)
        assert response.status_code == 200, numbers
        dom = _dom(response)
        assert dom.find(data_kb_page="compare")
        hints = dom.find(data_kb_hint="pick-two")
        assert len(hints) == 1 and "Отметьте две версии" in hints[0].text(), numbers
        assert not dom.find(data_kb_diff=True), numbers
        assert not dom.find("div", class_="kb-diff-add") and not dom.find("div", class_="kb-diff-del"), numbers


def test_compare_collapses_unchanged_lines_to_three_context_lines_inside_details():
    """FR-411: неизменённые участки свёрнуты до 3 строк контекста; скрытые строки — в `details[data-kb-fold]`."""
    reader = kb.as_reader()
    lines = [f"строка {n:02d}" for n in range(1, 31)]
    changed = list(lines)
    changed[14] = "ЗАМЕНА"
    article, _ = _editor_and_versions(["\n".join(lines), "\n".join(changed)])
    dom = _dom(_compare(reader.client, article, 1, 2))
    folds = dom.find("details", data_kb_fold=True)
    assert len(folds) == 2
    assert _marked(dom, "del") == ["строка 15"] and _marked(dom, "add") == ["ЗАМЕНА"]
    pattern = re.compile(r"строка (\d\d)")
    hidden = [sorted(int(n) for n in pattern.findall(fold.text(skip=("summary",)))) for fold in folds]
    assert hidden == [list(range(1, 12)), list(range(19, 31))]
    for fold, numbers in zip(folds, hidden):
        summary = fold.find("summary")
        assert len(summary) == 1
        match = re.fullmatch(r"Показать (\d+) строк", summary[0].text())
        assert match and int(match.group(1)) == len(numbers)
    page = dom.find(data_kb_diff=True)[0]
    shown = sorted(int(n) for n in pattern.findall(page.text(skip=("details",))))
    assert shown == [12, 13, 14, 15, 16, 17, 18]


def test_compare_over_2000_changed_lines_shows_first_2000_and_remainder_message():
    """FR-411: больше 2 000 изменённых строк — первые 2 000 и «Ещё N изменений не показано»."""
    reader = kb.as_reader()
    added = [f"добавлено {n:04d}" for n in range(1, 2101)]
    article, _ = _editor_and_versions(["основа", "\n".join(["основа"] + added)])
    response = _compare(reader.client, article, 1, 2)
    assert response.status_code == 200
    dom = _dom(response)
    shown = _marked(dom, "add")
    assert shown == added[:2000]
    assert not _marked(dom, "del")
    more = dom.find(data_kb_diff_more=True)
    assert len(more) == 1 and "Ещё 100 изменений не показано" in more[0].text()
    short, _ = _editor_and_versions(["основа", "\n".join(["основа"] + added[:2000])])
    assert not _dom(_compare(reader.client, short, 1, 2)).find(data_kb_diff_more=True)


def test_compare_with_deleted_version_shows_version_deleted_hint():
    """FR-411, FR-449: одной из версий нет (удалена) — подсказка «Версия удалена» и разницы нет; в истории её нет."""
    reader = kb.as_reader()
    article, _ = _editor_and_versions(["один", "два", "три"])
    support.model("knowledge.ArticleVersion").objects.filter(article=article, number=2).delete()
    for numbers in ((1, 2), (2, 3), (3, 9)):
        response = _compare(reader.client, article, *numbers)
        assert response.status_code == 200, numbers
        dom = _dom(response)
        hints = dom.find(data_kb_hint="deleted")
        assert len(hints) == 1 and "Версия удалена" in hints[0].text(), numbers
        assert not dom.find(data_kb_diff=True) and not dom.find(data_kb_hint="pick-two"), numbers
    article.refresh_from_db()
    assert article.version_no == 3
    assert _row_numbers(_dom(_history(reader.client, article))) == [3, 1]
    control = _dom(_compare(reader.client, article, 1, 3))
    assert control.find(data_kb_diff=True) and not control.find(data_kb_hint=True)
