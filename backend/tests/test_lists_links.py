"""T-6113: связи — «Закреплённое», подразделение и роль, ссылки между записями, подсказки выбора (FR-507, FR-509,
FR-511, FR-514, FR-525, FR-526, FR-527, FR-546). Сценарии 6, 13 и 14 спеки.

Раздел «Закреплённое» читается со страниц `/me/` и `/staff/<id>/` и из `links.pinned`; отказы ядра при удалении узла и
роли — службами `structure.delete_unit` и `roles.delete_role` (по точкам `unit_usage` и `role_usage`); «Ссылаются на эту
запись» и показ значения-ссылки — карточкой записи; подсказки — адресами `/lists/<id>/pick/`, `/lists/people/`,
`/lists/units/`. Код среза на уровне модуля не импортируется (CONTRACT-006, шапка).

Допущения писателя (см. отчёт): `data-pick-id` записи — `Record.pk`; строка «Закреплённого» — по одной на пару
«запись, поле»; тест `unit_usage` не ставит одну запись с узлом в двух полях (считается ли она один раз — контракт не
говорит); список названий в правах не проверяется на повтор одного списка в «Читают» и «Правят».
"""
import logging
from html.parser import HTMLParser
from urllib.parse import quote

import pytest

from tests import factories, support
from tests import support_lists as ll
from tests import support_org as org
from tests.support import HX
from tests.support_lists import Session

pytestmark = pytest.mark.django_db

UNIT_PHRASE = "подразделение указано в {n} записях списков"
ACCESS_PHRASE = "указано в правах списков: {names}"


# --- разбор разметки (помощник только этого файла) -----------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}
        self.parent = parent
        self.children = []

    def walk(self):
        for child in self.children:
            if isinstance(child, _Node):
                yield child
                yield from child.walk()

    def text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                if isinstance(child, _Node):
                    collect(child)
                else:
                    parts.append(child)

        collect(self)
        return " ".join("".join(parts).split())


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__()
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
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def _html(response) -> str:
    return response.content.decode("utf-8")


def _tree(response) -> _Node:
    parser = _Parser()
    parser.feed(_html(response))
    return parser.root


def _q(scope, tag=None, **attrs) -> list:
    """Потомки по тегу и атрибутам; в имени атрибута `_` означает дефис; значение `True` — «атрибут есть»."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    return [node for node in scope.walk()
            if (tag is None or node.tag == tag)
            and all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items())]


def _squash(text: str) -> str:
    """Текст без пробелов: форма «Название — Список — Поле» не зависит от пробелов вокруг тире и ссылок."""
    return "".join(text.split())


def _model(label: str):
    return support.model(label)


def _fresh(user):
    """Сотрудник из базы без `_lists_scope` (область прав живёт на объекте пользователя)."""
    from django.core.cache import cache

    from apps.core.services import permissions

    cache.delete(permissions._key(user.pk))
    return _model("core.User").objects.get(pk=user.pk)


def _staff_view_role():
    return factories.make_role(permissions=("staff.view",))


def _pinned_items(response) -> list:
    """Строки `li[data-pinned-record]` внутри `#lists-pinned[data-lists-pinned]`; раздела нет — пустой список."""
    blocks = _q(_tree(response), id="lists-pinned", data_lists_pinned=True)
    if not blocks:
        return []
    return _q(blocks[0], "li", data_pinned_record=True)


def _item_for(items, title):
    found = [item for item in items if _squash(title) in _squash(item.text())]
    assert len(found) == 1, f"строк с «{title}»: {len(found)}"
    return found[0]


def _own_page(person):
    return Session(person, support.logged_in(person)).client.get("/me/")


def _card_page(viewer: Session, person):
    return viewer.client.get(f"/staff/{person.pk}/", **HX)


def _person_pairs(rows) -> set:
    return {(row.record.pk, row.list.pk, row.field.pk, row.link) for row in rows}


# --- мир «Закреплённого» ---------------------------------------------------------------------------------

def _pin_world():
    """Сотрудник `person`, два списка, в каждом поле «сотрудник» с ним в одной записи; в списке Б у записи есть ещё
    строковое поле с отличительным значением (его в разделе быть не должно)."""
    person = support.make_employee(full_name="Закреплённый Сотрудник")
    other = support.make_employee()
    author = support.make_employee()
    list_a = ll.make_list("Оборудование З", created_by=author)
    field_a = ll.add_field(list_a, "person", "Ответственный")
    list_b = ll.make_list("Лицензии З", created_by=author)
    field_b = ll.add_field(list_b, "person", "Владелец", multiple=True)
    plain_b = ll.add_field(list_b, "string", "Условный номер")
    record_a = ll.make_record(list_a, "Ноутбук Альфа", {field_a.code: [person.pk]}, created_by=author)
    record_b = ll.make_record(list_b, "Лицензия Бета", {field_b.code: [other.pk, person.pk], plain_b.code: "ИНВ-ЗАКРЫТО-5"},
                              created_by=author)
    return {"person": person, "other": other, "author": author, "list_a": list_a, "field_a": field_a,
            "list_b": list_b, "field_b": field_b, "record_a": record_a, "record_b": record_b, "plain_b": plain_b}


# --- «Закреплённое» (FR-525) --------------------------------------------------------------------------------

def test_pinned_section_is_card_section_on_profile_tab_with_order_70_and_lists_pinned_anchor():
    """FR-525: функция `apps.lists.card.card_sections` зарегистрирована в точке `card_sections`; для сотрудника со
    строками она возвращает один раздел `lists-pinned`, вкладка `profile`, порядок 70, шаблон
    `lists/_card_pinned.html`, в контексте `rows`; разделы карточки ядра содержат его на вкладке «Профиль»; на
    странице `/me/` есть `#lists-pinned[data-lists-pinned]`."""
    from apps.core import extensions
    from apps.core.views import me
    from apps.lists import card

    w = _pin_world()
    assert card.card_sections in extensions.registered("card_sections")
    sections = card.card_sections(w["person"], w["person"])
    assert len(sections) == 1
    section = sections[0]
    assert (section.key, section.tab, section.order, section.template) == (
        "lists-pinned", "profile", 70, "lists/_card_pinned.html")
    assert len(section.context["rows"]) == 2
    profile = me.card_sections(w["person"], w["person"])["profile"]
    assert [item.key for item in profile if item.key == "lists-pinned"] == ["lists-pinned"]
    response = _own_page(w["person"])
    assert response.status_code == 200
    assert len(_q(_tree(response), id="lists-pinned", data_lists_pinned=True)) == 1


def test_pinned_section_lists_not_archived_records_of_all_lists_as_title_list_and_field():
    """FR-525: строки — записи не в архиве из всех списков, где сотрудник указан в видимом поле «сотрудник» (в том
    числе в многозначном рядом с другим человеком); строка «Название — Список — Поле»; архивная запись, запись без
    него и запись, где он указан в поле другого типа, строк не дают."""
    w = _pin_world()
    person, other, author = w["person"], w["other"], w["author"]
    ll.make_record(w["list_a"], "Ноутбук в архиве", {w["field_a"].code: [person.pk]}, created_by=author, archived=True)
    ll.make_record(w["list_a"], "Ноутбук чужой", {w["field_a"].code: [other.pk]}, created_by=author)
    list_c = ll.make_list("Договоры З", created_by=author)
    choice_field = ll.add_field(list_c, "choice", "Статус", choices=("Новый",))
    ll.make_record(list_c, "Договор с совпавшим числом", {choice_field.code: [person.pk]}, created_by=author)
    # один сотрудник в двух видимых полях одной записи — две строки, на пару «запись, поле» (CONTRACT-006, 15.3)
    list_d = ll.make_list("Кабинеты З", created_by=author)
    keeper = ll.add_field(list_d, "person", "Хранитель")
    deputy = ll.add_field(list_d, "person", "Заместитель")
    record_d = ll.make_record(list_d, "Кабинет Гамма", {keeper.code: [person.pk], deputy.code: [person.pk]},
                              created_by=author)
    response = _own_page(person)
    items = _pinned_items(response)
    assert len(items) == 4, [item.text() for item in items]
    texts = {_squash(item.text()) for item in items}
    assert any(_squash("Ноутбук Альфа — Оборудование З — Ответственный") in text for text in texts), texts
    assert any(_squash("Лицензия Бета — Лицензии З — Владелец") in text for text in texts), texts
    assert any(_squash("Кабинет Гамма — Кабинеты З — Хранитель") in text for text in texts), texts
    assert any(_squash("Кабинет Гамма — Кабинеты З — Заместитель") in text for text in texts), texts
    body = _html(response)
    for absent in ("Ноутбук в архиве", "Ноутбук чужой", "Договор с совпавшим числом"):
        assert absent not in body
    from apps.lists.services import links

    rows = links.pinned(person, person)
    assert len(rows) == 4
    assert {(row.record.pk, row.list.pk, row.field.pk) for row in rows} == {
        (w["record_a"].pk, w["list_a"].pk, w["field_a"].pk), (w["record_b"].pk, w["list_b"].pk, w["field_b"].pk),
        (record_d.pk, list_d.pk, keeper.pk), (record_d.pk, list_d.pk, deputy.pk)}


def test_own_card_without_list_right_shows_all_rows_without_links_and_other_record_data():
    """FR-525: сотрудник без права на списки видит в своей карточке все строки (название записи и список), но без
    перехода в карточку записи и без других данных записи; `PinnedRow.link` ложен."""
    from apps.lists.services import links

    w = _pin_world()
    person = w["person"]
    rows = links.pinned(person, person)
    assert _person_pairs(rows) == {
        (w["record_a"].pk, w["list_a"].pk, w["field_a"].pk, False),
        (w["record_b"].pk, w["list_b"].pk, w["field_b"].pk, False)}
    response = _own_page(person)
    items = _pinned_items(response)
    assert len(items) == 2
    for title, list_name in (("Ноутбук Альфа", "Оборудование З"), ("Лицензия Бета", "Лицензии З")):
        text = _squash(_item_for(items, title).text())
        assert _squash(list_name) in text
    for item in items:
        assert not [a for a in _q(item, "a") if a.attrs.get("href", "").startswith("/lists/")]
    body = _html(response)
    assert "ИНВ-ЗАКРЫТО-5" not in body
    for record in (w["record_a"], w["record_b"]):
        assert f"/lists/{record.list_id}/{record.number}/" not in body


def test_own_card_links_only_rows_of_lists_employee_reads():
    """FR-525: сам сотрудник видит все строки; ссылка на запись — только у списков, которые он читает; у остальных
    название и список без перехода."""
    from apps.lists.services import links

    w = _pin_world()
    person = w["person"]
    role = factories.make_role()
    ll.grant_list(w["list_a"], role, "read")
    person.roles.add(role)
    viewer = _fresh(person)
    assert _person_pairs(links.pinned(viewer, viewer)) == {
        (w["record_a"].pk, w["list_a"].pk, w["field_a"].pk, True),
        (w["record_b"].pk, w["list_b"].pk, w["field_b"].pk, False)}
    items = _pinned_items(_own_page(person))
    assert len(items) == 2
    record_a, record_b = w["record_a"], w["record_b"]
    hrefs_a = [a.attrs.get("href") for a in _q(_item_for(items, "Ноутбук Альфа"), "a")]
    assert f"/lists/{record_a.list_id}/{record_a.number}/" in hrefs_a
    row_b = _item_for(items, "Лицензия Бета")
    assert not [a for a in _q(row_b, "a") if a.attrs.get("href", "").startswith("/lists/")]
    assert "ИНВ-ЗАКРЫТО-5" not in row_b.text()


def test_colleague_reading_list_sees_its_rows_with_links_and_no_rows_of_unread_lists():
    """FR-525: коллега, который читает список А и вправе открыть карточку, видит строки списка А со ссылкой и не видит
    строк списка Б (ни названия записи, ни списка); коллега без права на списки раздела не видит."""
    from apps.lists.services import links

    w = _pin_world()
    person = w["person"]
    reader = ll.as_reader(w["list_a"], roles=[_staff_view_role()])
    assert _person_pairs(links.pinned(_fresh(reader.user), person)) == {
        (w["record_a"].pk, w["list_a"].pk, w["field_a"].pk, True)}
    response = _card_page(reader, person)
    assert response.status_code == 200
    items = _pinned_items(response)
    assert len(items) == 1
    record_a = w["record_a"]
    assert f"/lists/{record_a.list_id}/{record_a.number}/" in [a.attrs.get("href") for a in _q(items[0], "a")]
    assert "Ноутбук Альфа" in _html(response)
    body = _html(response)
    for absent in ("Лицензия Бета", "Лицензии З", "ИНВ-ЗАКРЫТО-5"):
        assert absent not in body
    outsider_user = support.make_employee(roles=[_staff_view_role()])
    outsider = Session(outsider_user, support.logged_in(outsider_user))
    assert links.pinned(_fresh(outsider_user), person) == []
    assert not _pinned_items(_card_page(outsider, person))


def test_pinned_section_is_shown_for_dismissed_employee():
    """FR-525: у уволенного сотрудника раздел показывается так же (видно, что забрать): строки есть, ссылки — у
    смотрящего, который читает списки; значения полей в записях остаются."""
    from apps.lists.services import links

    w = _pin_world()
    person = w["person"]
    person.state = "dismissed"
    person.save(update_fields=["state"])
    manager = ll.as_manager(roles=[_staff_view_role()])
    viewer = _fresh(manager.user)
    assert _person_pairs(links.pinned(viewer, _fresh(person))) == {
        (w["record_a"].pk, w["list_a"].pk, w["field_a"].pk, True),
        (w["record_b"].pk, w["list_b"].pk, w["field_b"].pk, True)}
    response = _card_page(manager, person)
    assert response.status_code == 200
    items = _pinned_items(response)
    assert len(items) == 2
    Record = _model("lists.Record")
    stored_a = Record.objects.get(pk=w["record_a"].pk).values
    stored_b = Record.objects.get(pk=w["record_b"].pk).values
    assert stored_a[w["field_a"].code] == [person.pk]
    assert set(stored_b[w["field_b"].code]) == {w["other"].pk, person.pk}


def test_hidden_person_field_gives_no_pinned_rows():
    """FR-509, FR-525: скрытое поле «сотрудник» в «Закреплённом» не участвует; видимое поле того же списка с этим
    сотрудником даёт строку; без видимых строк раздела нет."""
    from apps.lists.card import card_sections
    from apps.lists.services import links

    person = support.make_employee()
    author = support.make_employee()
    lst = ll.make_list("Реестр скрытых", created_by=author)
    hidden = ll.add_field(lst, "person", "Прежний ответственный", hidden=True)
    visible = ll.add_field(lst, "person", "Ответственный")
    ll.make_record(lst, "Запись по скрытому", {hidden.code: [person.pk]}, created_by=author)
    assert links.pinned(person, person) == []
    assert card_sections(person, person) == []
    assert not _pinned_items(_own_page(person))
    shown = ll.make_record(lst, "Запись по видимому", {visible.code: [person.pk]}, created_by=author)
    rows = links.pinned(person, person)
    assert [(row.record.pk, row.field.pk) for row in rows] == [(shown.pk, visible.pk)]
    body = _html(_own_page(person))
    assert "Запись по видимому" in body and "Запись по скрытому" not in body


def test_no_pinned_rows_means_no_section():
    """FR-525: нет строк — раздела нет: `card_sections` возвращает `[]`, `links.pinned` — пустой список, на `/me/` нет
    `#lists-pinned`; архивная запись и запись, где указан другой сотрудник, строк не дают."""
    from apps.core import extensions
    from apps.lists import card
    from apps.lists.services import links

    person = support.make_employee()
    other = support.make_employee()
    author = support.make_employee()
    lst = ll.make_list("Реестр без строк", created_by=author)
    field = ll.add_field(lst, "person", "Ответственный")
    ll.make_record(lst, "Архивная запись", {field.code: [person.pk]}, created_by=author, archived=True)
    ll.make_record(lst, "Чужая запись", {field.code: [other.pk]}, created_by=author)
    assert card.card_sections in extensions.registered("card_sections")
    assert links.pinned(person, person) == []
    assert card.card_sections(person, person) == []
    response = _own_page(person)
    assert response.status_code == 200
    assert not _q(_tree(response), id="lists-pinned")
    assert "Архивная запись" not in _html(response)


def test_colleague_who_lost_read_right_no_longer_sees_rows_of_that_list():
    """FR-525: пока коллега читает список, строки списка в карточке есть; после снятия права (строка `Access`
    удалена) со следующего запроса строк и раздела нет."""
    from apps.lists.services import links

    w = _pin_world()
    person = w["person"]
    reader = ll.as_reader(w["list_a"], roles=[_staff_view_role()])
    assert len(_pinned_items(_card_page(reader, person))) == 1
    _model("lists.Access").objects.filter(list=w["list_a"]).delete()
    response = _card_page(reader, person)
    assert response.status_code == 200
    assert _pinned_items(response) == []
    assert "Ноутбук Альфа" not in _html(response)
    assert links.pinned(_fresh(reader.user), person) == []


# --- подразделение и роль (FR-526, FR-546) --------------------------------------------------------------

def _unit_world():
    """Узел `unit`; записи с ним: видимое поле, скрытое поле, запись в архиве (три записи, по одному полю), плюс
    запись со значением-совпадением в поле другого типа (не считается)."""
    unit = org.make_unit()
    author = support.make_employee()
    list_one = ll.make_list("Склад У", created_by=author)
    visible = ll.add_field(list_one, "unit", "Место")
    list_two = ll.make_list("Кабинеты У", created_by=author)
    hidden = ll.add_field(list_two, "unit", "Прежнее место", hidden=True)
    ll.make_record(list_one, "Запись с видимым узлом", {visible.code: [unit.pk]}, created_by=author)
    ll.make_record(list_two, "Запись со скрытым узлом", {hidden.code: [unit.pk]}, created_by=author)
    ll.make_record(list_one, "Запись в архиве с узлом", {visible.code: [unit.pk]}, created_by=author, archived=True)
    choice_field = ll.add_field(list_one, "choice", "Статус", choices=("Новый",))
    ll.make_record(list_one, "Запись с чужим совпадением", {choice_field.code: [unit.pk]}, created_by=author)
    return unit


def _access_lists(unit=None, role=None):
    """Два списка «Бета» (создан первым) и «Альфа» с набором прав на узел или роль; названия идут не в порядке создания."""
    beta, alpha = ll.make_list("Бета"), ll.make_list("Альфа")
    for lst, level in ((beta, "read"), (alpha, "edit")):
        ll.grant_list(lst, unit or role, level)
    return beta, alpha


def test_unit_usage_counts_records_including_archived_and_hidden_unit_fields():
    """FR-526, FR-509: фраза `unit_usage` — «подразделение указано в N записях списков», где N — записи с узлом в
    видимом поле, в скрытом поле и в архиве (по одной записи на поле; запись с тем же числом в поле другого типа не
    считается); перечня записей и списков в фразе нет; у неиспользуемого узла — `None`."""
    from apps.lists.services import links

    unit = _unit_world()
    # запись с тем же узлом в двух полях (видимом и скрытом) считается один раз (CONTRACT-006, 15.3)
    list_three = ll.make_list("Подсобки У")
    near = ll.add_field(list_three, "unit", "Ближнее место")
    far = ll.add_field(list_three, "unit", "Дальнее место", hidden=True)
    ll.make_record(list_three, "Запись с узлом в двух полях", {near.code: [unit.pk], far.code: [unit.pk]})
    phrase = links.unit_usage(unit.pk)
    assert phrase == UNIT_PHRASE.format(n=4), phrase
    for title in ("Запись с видимым узлом", "Запись со скрытым узлом", "Склад У", "Кабинеты У"):
        assert title not in phrase
    assert links.unit_usage(org.make_unit().pk) is None


def test_unit_usage_with_access_rows_adds_list_names_after_semicolon_and_no_record_list():
    """FR-526, FR-546: если узел ещё и в наборах прав списков, к фразе о записях через «; » добавляется «указано в
    правах списков: <названия по алфавиту через «, »>»; перечня записей в тексте нет; без записей — одна фраза о
    правах."""
    from apps.lists.services import links

    unit = _unit_world()
    _access_lists(unit=unit)
    phrase = links.unit_usage(unit.pk)
    expected = UNIT_PHRASE.format(n=3) + "; " + ACCESS_PHRASE.format(names="Альфа, Бета")
    assert phrase == expected, phrase
    assert "Запись с видимым узлом" not in phrase
    only_access = org.make_unit()
    _access_lists_for = ll.make_list("Гамма")
    ll.grant_list(_access_lists_for, only_access, "read")
    assert links.unit_usage(only_access.pk) == ACCESS_PHRASE.format(names="Гамма")


def test_unit_delete_with_records_is_refused_by_core_with_count_and_without_record_list():
    """FR-526, FR-546: удаление узла, указанного в записях, отказывает ядром: `OrgError` с кодом `in_use` и текстом
    «Узел нельзя удалить: подразделение указано в N записях списков.»; узел остаётся, события `unit.deleted` нет,
    названий записей в тексте нет."""
    from apps.org.services import structure
    from apps.org.services.errors import OrgError

    unit = _unit_world()
    admin = support.make_admin()
    with pytest.raises(OrgError) as refused:
        structure.delete_unit(unit, actor=admin)
    assert refused.value.code == "in_use"
    assert refused.value.message == "Узел нельзя удалить: " + UNIT_PHRASE.format(n=3) + "."
    assert "Запись с видимым узлом" not in refused.value.message
    assert _model("org.Unit").objects.filter(pk=unit.pk).exists()
    assert not _model("core.AuditEvent").objects.filter(action="unit.deleted").exists()


def test_unit_delete_with_only_access_rows_is_refused_with_list_names():
    """FR-526, FR-546: узел только в наборах прав (записей с ним нет) не удаляется: «Узел нельзя удалить: указано в
    правах списков: Альфа, Бета.»; после снятия строк прав узел удаляется."""
    from apps.org.services import structure
    from apps.org.services.errors import OrgError

    unit = org.make_unit()
    _access_lists(unit=unit)
    admin = support.make_admin()
    with pytest.raises(OrgError) as refused:
        structure.delete_unit(unit, actor=admin)
    assert refused.value.code == "in_use"
    assert refused.value.message == "Узел нельзя удалить: " + ACCESS_PHRASE.format(names="Альфа, Бета") + "."
    assert _model("org.Unit").objects.filter(pk=unit.pk).exists()
    assert not _model("core.AuditEvent").objects.filter(action="unit.deleted").exists()
    _model("lists.Access").objects.filter(unit_id=unit.pk).delete()
    structure.delete_unit(unit, actor=admin)
    assert not _model("org.Unit").objects.filter(pk=unit.pk).exists()


def test_role_usage_returns_cannot_delete_phrase_with_access_list_names():
    """FR-526, FR-546: фраза `role_usage` — «Нельзя удалить: указано в правах списков: Альфа, Бета.» (названия по
    алфавиту); у роли, которой нет в наборах прав, — `None`."""
    from apps.lists.services import links

    role = factories.make_role()
    _access_lists(role=role)
    assert links.role_usage(role) == "Нельзя удалить: " + ACCESS_PHRASE.format(names="Альфа, Бета") + "."
    assert links.role_usage(factories.make_role()) is None


def test_role_delete_when_role_is_in_access_set_is_refused_with_list_names():
    """FR-526, FR-546: удаление роли из набора прав отказывает `RoleError` с готовой фразой `role_usage`; роль
    остаётся, события `role.deleted` нет; без строк прав роль удаляется."""
    from apps.core.services import roles

    role = factories.make_role()
    _access_lists(role=role)
    admin = support.make_admin()
    with pytest.raises(roles.RoleError) as refused:
        roles.delete_role(role, actor=admin)
    assert str(refused.value) == "Нельзя удалить: " + ACCESS_PHRASE.format(names="Альфа, Бета") + "."
    assert _model("core.Role").objects.filter(pk=role.pk).exists()
    assert not _model("core.AuditEvent").objects.filter(action="role.deleted").exists()
    _model("lists.Access").objects.filter(role=role).delete()
    roles.delete_role(role, actor=admin)
    assert not _model("core.Role").objects.filter(pk=role.pk).exists()


def test_access_role_foreign_key_protects_role_from_delete():
    """FR-526: вторая линия — внешний ключ `Access.role` с PROTECT: удаление роли в обход службы поднимает
    `ProtectedError`, роль и строка прав остаются."""
    from django.db import transaction
    from django.db.models import ProtectedError

    role = factories.make_role()
    lst = ll.make_list()
    access = ll.grant_list(lst, role, "read")
    with pytest.raises(ProtectedError):
        with transaction.atomic():
            role.delete()
    with pytest.raises(ProtectedError):
        with transaction.atomic():
            _model("core.Role").objects.filter(pk=role.pk).delete()
    assert _model("core.Role").objects.filter(pk=role.pk).exists()
    assert _model("lists.Access").objects.filter(pk=access.pk).exists()


# --- ссылки между записями (FR-527) -----------------------------------------------------------------------

def _ref_world():
    """Запись `target` в списке Т и ссылающиеся на неё: в списке Т (само на себя), в списке Б (видимое поле, одно и
    несколько значений), в списке В (скрытое поле); не ссылаются: запись Б на другую запись и запись Б с этим числом
    в поле «сотрудник»."""
    author = support.make_employee()
    target_list = ll.make_list("Серверы Т", created_by=author)
    same = ll.add_field(target_list, "record", "Связанный сервер", target=target_list)
    target = ll.make_record(target_list, "Целевой сервер", created_by=author)
    spare = ll.make_record(target_list, "Другой сервер", created_by=author)
    same_ref = ll.make_record(target_list, "Сервер ссылается сам", {same.code: [target.pk]}, created_by=author)
    list_b = ll.make_list("Заявки на работы Б", created_by=author)
    visible = ll.add_field(list_b, "record", "Сервер", target=target_list, multiple=True)
    person = ll.add_field(list_b, "person", "Исполнитель")
    ref_b = ll.make_record(list_b, "Работа по серверу", {visible.code: [target.pk]}, created_by=author)
    ref_b_multi = ll.make_record(list_b, "Работа по двум серверам", {visible.code: [spare.pk, target.pk]},
                                 created_by=author)
    ll.make_record(list_b, "Работа по другому серверу", {visible.code: [spare.pk]}, created_by=author)
    ll.make_record(list_b, "Работа с совпавшим числом", {person.code: [target.pk]}, created_by=author)
    list_c = ll.make_list("Закрытый реестр В", created_by=author)
    hidden = ll.add_field(list_c, "record", "Прежний сервер", target=target_list, hidden=True)
    ref_c = ll.make_record(list_c, "Скрытая ссылка на сервер", {hidden.code: [target.pk]}, created_by=author)
    return {"target": target, "target_list": target_list, "list_b": list_b, "list_c": list_c, "same_ref": same_ref,
            "ref_b": ref_b, "ref_b_multi": ref_b_multi, "ref_c": ref_c, "visible": visible}


def _ref_items(response) -> list:
    return _q(_tree(response), "li", data_record_ref=True)


def test_referrers_include_record_fields_of_other_and_same_list_including_hidden_fields():
    """FR-527, FR-509: `links.referrers` без фильтра чтения и у управляющего — записи полей «запись другого списка» с
    целью-списком записи: другого списка, этого же, из скрытого поля, из многозначного поля; записи с другим
    значением и с этим числом в поле другого типа не входят; `hidden` равен нулю; в карточке есть строки
    `li[data-record-ref="<id списка>:<номер>"]`."""
    from apps.lists.services import links

    w = _ref_world()
    expected = {w["same_ref"].pk, w["ref_b"].pk, w["ref_b_multi"].pk, w["ref_c"].pk}
    everyone = links.referrers(w["target"], None)
    assert {r.pk for r in everyone.rows} == expected and everyone.hidden == 0
    manager = ll.as_manager()
    seen = links.referrers(w["target"], _fresh(manager.user))
    assert {r.pk for r in seen.rows} == expected and seen.hidden == 0
    response = manager.client.get(f"/lists/{w['target_list'].pk}/{w['target'].number}/")
    assert response.status_code == 200
    refs = {item.attrs["data-record-ref"] for item in _ref_items(response)}
    assert refs == {f"{r.list_id}:{r.number}" for r in (w["same_ref"], w["ref_b"], w["ref_b_multi"], w["ref_c"])}
    assert len(_q(_tree(response), data_lists_referrers=True)) == 1


def test_referrers_show_only_readable_lists_and_mark_archived_referrer():
    """FR-527: смотрящий, который читает списки Т и Б, получает ссылающиеся записи только из них, число остальных —
    в `hidden`; запись в архиве показана с пометкой «в архиве»; название записи нечитаемого списка в карточке не
    выводится."""
    from apps.lists.services import links

    w = _ref_world()
    reader = ll.as_reader(w["target_list"])
    ll.grant_list(w["list_b"], reader.user.roles.get(), "read")
    ll.archive(w["ref_b"])
    seen = links.referrers(w["target"], _fresh(reader.user))
    assert {r.pk for r in seen.rows} == {w["same_ref"].pk, w["ref_b"].pk, w["ref_b_multi"].pk}
    assert seen.hidden == 1
    response = reader.client.get(f"/lists/{w['target_list'].pk}/{w['target'].number}/")
    assert response.status_code == 200
    items = {item.attrs["data-record-ref"]: item for item in _ref_items(response)}
    assert set(items) == {f"{r.list_id}:{r.number}" for r in (w["same_ref"], w["ref_b"], w["ref_b_multi"])}
    archived_item = items[f"{w['ref_b'].list_id}:{w['ref_b'].number}"]
    marks = _q(archived_item, data_lists_archived=True)
    assert marks and "в архиве" in marks[0].text()
    for key in (f"{w['same_ref'].list_id}:{w['same_ref'].number}", f"{w['ref_b_multi'].list_id}:{w['ref_b_multi'].number}"):
        assert not _q(items[key], data_lists_archived=True)
    body = _html(response)
    assert "Скрытая ссылка на сервер" not in body and "Закрытый реестр В" not in body


def test_record_value_of_unreadable_list_is_shown_as_unavailable_record_without_title_and_link():
    """FR-527: значение поля-ссылки на запись списка, которого смотрящий не читает, — «запись недоступного списка»
    (`[data-lists-unavailable]`) без названия записи и списка и без перехода."""
    author = support.make_employee()
    closed = ll.make_list("Закрытый реестр Т", created_by=author)
    closed_record = ll.make_record(closed, "Закрытая запись ТТ", created_by=author)
    open_list = ll.make_list("Открытый реестр С", created_by=author)
    link_field = ll.add_field(open_list, "record", "Связь", target=closed)
    holder = ll.make_record(open_list, "Запись со связью", {link_field.code: [closed_record.pk]}, created_by=author)
    reader = ll.as_reader(open_list)
    response = reader.client.get(f"/lists/{open_list.pk}/{holder.number}/")
    assert response.status_code == 200
    nodes = _q(_tree(response), data_lists_value=link_field.code)
    assert len(nodes) == 1
    node = nodes[0]
    assert _q(node, data_lists_unavailable=True)
    assert "недоступного списка" in node.text()
    assert "Закрытая запись ТТ" not in node.text() and "Закрытый реестр Т" not in node.text()
    assert not [a for a in _q(node, "a")]
    body = _html(response)
    assert "Закрытая запись ТТ" not in body and "Закрытый реестр Т" not in body
    assert f"/lists/{closed.pk}/" not in body


def test_history_value_of_unreadable_list_is_shown_as_unavailable_record_to_reader_and_by_name_to_manager():
    """FR-514, FR-527 (SC «0 записей… в истории»): строка истории хранит «Название — №N» глазами автора; читающему
    список A, но не целевой список поля-ссылки, в карточке и на странице истории значение показывается как «запись
    недоступного списка» (`[data-lists-unavailable]`) без названия; управляющему — с названием. Строка `Change` не
    меняется (найдено зелёной приёмкой T-6260, `test_l13`)."""
    from apps.lists.services import history

    author = support.make_employee()
    closed = ll.make_list("Закрытый реестр И", created_by=author)
    closed_record = ll.make_record(closed, "Тайная запись ИИ", created_by=author)
    open_list = ll.make_list("Открытый реестр И", created_by=author)
    link_field = ll.add_field(open_list, "record", "Связь", target=closed)
    holder = ll.make_record(open_list, "Запись с историей", {link_field.code: [closed_record.pk]}, created_by=author)
    shown = f"Тайная запись ИИ — №{closed_record.number}"
    change = history.write(holder, "changed", [{"field": link_field.code, "name": link_field.name, "before": "",
                                                 "after": shown}], author)
    reader = ll.as_reader(open_list)
    for path, headers in ((f"/lists/{open_list.pk}/{holder.number}/", {}),
                          (f"/lists/{open_list.pk}/{holder.number}/history/", {}),
                          (f"/lists/{open_list.pk}/{holder.number}/history/", HX)):
        response = reader.client.get(path, **headers)
        assert response.status_code == 200, path
        rows = [node for node in _q(_tree(response), data_change_field=link_field.code)]
        assert len(rows) == 1, path
        assert _q(rows[0], data_lists_unavailable=True) and "недоступного списка" in rows[0].text(), path
        assert "Тайная запись ИИ" not in _html(response), path
    manager = ll.as_manager()
    response = manager.client.get(f"/lists/{open_list.pk}/{holder.number}/history/")
    rows = _q(_tree(response), data_change_field=link_field.code)
    assert len(rows) == 1 and shown in rows[0].text() and not _q(rows[0], data_lists_unavailable=True)
    change.refresh_from_db()
    assert change.changes[0]["after"] == shown


def test_record_value_pointing_to_archived_record_is_marked_in_archive():
    """FR-527: значение-ссылка на запись в архиве показывается с пометкой «в архиве» (и названием «Название —
    №N», если список читается); значение-ссылка на живую запись пометки не имеет."""
    author = support.make_employee()
    target_list = ll.make_list("Договоры Т", created_by=author)
    old = ll.make_record(target_list, "Старый договор", created_by=author, archived=True)
    live = ll.make_record(target_list, "Действующий договор", created_by=author)
    holder_list = ll.make_list("Лицензии С", created_by=author)
    link_field = ll.add_field(holder_list, "record", "Договор", target=target_list)
    with_old = ll.make_record(holder_list, "Лицензия по старому", {link_field.code: [old.pk]}, created_by=author)
    with_live = ll.make_record(holder_list, "Лицензия по действующему", {link_field.code: [live.pk]}, created_by=author)
    reader = ll.as_reader(holder_list)
    ll.grant_list(target_list, reader.user.roles.get(), "read")

    def value_node(record):
        response = reader.client.get(f"/lists/{holder_list.pk}/{record.number}/")
        assert response.status_code == 200
        nodes = _q(_tree(response), data_lists_value=link_field.code)
        assert len(nodes) == 1
        return nodes[0]

    archived_node = value_node(with_old)
    marks = _q(archived_node, data_lists_archived=True)
    assert marks and "в архиве" in marks[0].text()
    assert _squash(f"Старый договор — №{old.number}") in _squash(archived_node.text())
    assert _q(archived_node, "a", href=f"/lists/{target_list.pk}/{old.number}/"), "у записи в архиве ссылка есть (11.1)"
    live_node = value_node(with_live)
    assert not _q(live_node, data_lists_archived=True)
    assert _squash(f"Действующий договор — №{live.number}") in _squash(live_node.text())


# --- подсказки выбора (FR-507, FR-511, FR-514) --------------------------------------------------------------

def _pick_ids(response) -> list:
    lists = _q(_tree(response), "ul", data_lists_pick=True)
    assert len(lists) == 1
    return [int(li.attrs["data-pick-id"]) for li in _q(lists[0], "li", data_pick_id=True)]


def test_pick_finds_up_to_20_not_archived_records_by_title_or_number_as_title_and_number():
    """FR-511: подсказка `/lists/<id целевого>/pick/?q=` — записи этого списка не в архиве по названию или по
    номеру, не больше 20, строка «Название — №N»; записи в архиве и записи другого списка не выдаются."""
    author = support.make_employee()
    target = ll.make_list("Принтеры Т", created_by=author)
    matching = [ll.make_record(target, "Принтер Альфа", created_by=author) for _ in range(25)]
    for _ in range(3):
        ll.make_record(target, "Принтер из архива", created_by=author, archived=True)
    other_list = ll.make_list("Чужие принтеры", created_by=author)
    ll.make_record(other_list, "Принтер Чужой", created_by=author)
    reader = ll.as_reader(target)
    response = reader.client.get(f"/lists/{target.pk}/pick/?q=" + quote("Принтер"))
    assert response.status_code == 200
    ids = _pick_ids(response)
    assert len(ids) == 20 and len(set(ids)) == 20
    assert set(ids) <= {r.pk for r in matching}
    body = _html(response)
    assert "Принтер из архива" not in body and "Принтер Чужой" not in body
    first = _q(_tree(response), "li", data_pick_id=str(ids[0]))[0]
    number = _model("lists.Record").objects.get(pk=ids[0]).number
    assert _squash(f"Принтер Альфа — №{number}") in _squash(first.text())
    # поиск по номеру: название без цифр, поэтому совпасть может только номер
    small = ll.make_list("Мониторы Т", created_by=author)
    ll.make_record(small, "Монитор один", created_by=author)
    ll.make_record(small, "Монитор два", created_by=author)
    wanted = ll.make_record(small, "Коммутатор", created_by=author)
    archived = ll.make_record(small, "Архивный номер", created_by=author, archived=True)
    small_reader = ll.as_reader(small)
    found = _pick_ids(small_reader.client.get(f"/lists/{small.pk}/pick/?q={wanted.number}"))
    assert wanted.pk in found
    text = _squash(_q(_tree(small_reader.client.get(f"/lists/{small.pk}/pick/?q={wanted.number}")),
                      "li", data_pick_id=str(wanted.pk))[0].text())
    assert _squash(f"Коммутатор — №{wanted.number}") in text
    assert archived.pk not in _pick_ids(small_reader.client.get(f"/lists/{small.pk}/pick/?q={archived.number}"))


def test_pick_for_unreadable_target_list_gives_404():
    """FR-511: подсказка записей целевого списка, который смотрящий не читает, — 404 без данных (как у
    несуществующего списка); тот, кто читает только другой список, и сотрудник без прав получают то же."""
    author = support.make_employee()
    target = ll.make_list("Закрытые принтеры Т", created_by=author)
    ll.make_record(target, "Принтер закрытый", created_by=author)
    own = ll.make_list("Свой список")
    reader = ll.as_reader(own)
    nobody_user = support.make_employee()
    nobody = Session(nobody_user, support.logged_in(nobody_user))
    missing = 2_000_000_000
    for client in (reader.client, nobody.client):
        for path in (f"/lists/{target.pk}/pick/?q=" + quote("Принтер"), f"/lists/{missing}/pick/?q=" + quote("Принтер")):
            response = client.get(path)
            assert response.status_code == 404, path
            assert "Принтер закрытый" not in _html(response)


def test_people_and_units_pickers_return_up_to_20_rows_and_units_match_name_or_path():
    """FR-507, FR-514: подсказка людей и подсказка узлов — до 20 строк `li[data-pick-id]`; узел ищется по названию
    и по пути (запрос по названию родителя находит и вложенный узел); строка узла содержит путь словами от корня
    через « / »; `org.structure.all_units()` отдаёт все узлы по `path`."""
    from apps.org.services import structure

    lst = ll.make_list()
    editor = ll.as_editor(lst)
    people = [support.make_employee(full_name=f"Пикерский Сотрудник {i}") for i in range(25)]
    response = editor.client.get("/lists/people/?q=" + quote("Пикерский"))
    assert response.status_code == 200
    ids = _pick_ids(response)
    assert len(ids) == 20 and set(ids) <= {p.pk for p in people}
    person_rows = _q(_tree(response), "li", data_pick_id=True)
    assert person_rows and all("@" not in row.text() for row in person_rows), "строка сотрудника — без почты (10.2)"
    people_html = _html(response)
    assert all(p.email not in people_html for p in people if p.email)
    parent = org.make_unit("Корпус-Север")
    child = org.make_unit("Серверная", parent=parent)
    root = org.root_unit()
    response = editor.client.get("/lists/units/?q=" + quote("Серверная"))
    assert response.status_code == 200
    assert child.pk in _pick_ids(response)
    row = _q(_tree(response), "li", data_pick_id=str(child.pk))[0]
    assert f"{root.name} / Корпус-Север / Серверная" in row.text()
    by_path = _pick_ids(editor.client.get("/lists/units/?q=" + quote("Корпус-Север")))
    assert child.pk in by_path and parent.pk in by_path
    many = [org.make_unit(f"Пункт-{i}") for i in range(25)]
    ids = _pick_ids(editor.client.get("/lists/units/?q=" + quote("Пункт-")))
    assert len(ids) == 20 and set(ids) <= {u.pk for u in many}
    everything = structure.all_units()
    expected = [pk for _path, pk in sorted(_model("org.Unit").objects.values_list("path", "id"))]
    assert [unit.id for unit in everything] == expected
    assert {parent.pk, child.pk} <= {unit.id for unit in everything}


# --- подписка шины (FR-525) ---------------------------------------------------------------------------------

def test_user_dismissed_removes_user_views_of_dismissed_and_keeps_records(caplog, django_capture_on_commit_callbacks):
    """FR-525: событие `core.user_dismissed` (настоящее `accounts.dismiss`) удаляет выбор столбцов уволенного
    (`UserView`), выбор других остаётся; записи, где он указан, не меняются; в журнале шины нет ошибок
    подписчиков; прямой вызов `links.on_user_dismissed(user_id=…)` тоже удаляет строки."""
    from apps.core.services import accounts
    from apps.lists.services import links

    leaving, staying, direct = (support.make_employee() for _ in range(3))
    author = support.make_employee()
    lst = ll.make_list("Реестр увольнения", created_by=author)
    person_field = ll.add_field(lst, "person", "Ответственный")
    record = ll.make_record(lst, "Запись уволенного", {person_field.code: [leaving.pk]}, created_by=author)
    UserView = _model("lists.UserView")
    for user in (leaving, staying, direct):
        UserView.objects.create(user=user, list=lst, columns=["title"])
    with caplog.at_level(logging.INFO):
        with django_capture_on_commit_callbacks(execute=True):
            accounts.dismiss(leaving, actor=support.make_admin())
    assert not UserView.objects.filter(user=leaving).exists()
    assert UserView.objects.filter(user=staying).exists() and UserView.objects.filter(user=direct).exists()
    kept = _model("lists.Record").objects.get(pk=record.pk)
    assert kept.values == {person_field.code: [leaving.pk]} and not kept.archived
    bad = [r for r in caplog.records if r.name == "apps.core.events" and r.levelno >= logging.ERROR]
    assert not bad, [r.getMessage() for r in bad]
    links.on_user_dismissed(user_id=direct.pk, actor_id=None)
    assert not UserView.objects.filter(user=direct).exists()
    assert UserView.objects.filter(user=staying).exists()
