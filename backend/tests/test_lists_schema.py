"""T-6103: списки и поля — раздел, настройка списка, поля по типам, порядок, срок, права, удаление (FR-501…FR-504,
FR-506…FR-509, FR-511, FR-513, FR-529, FR-542, FR-546). Сценарии 1 и 14 спеки среза 006: управляющий создаёт список,
настраивает поля и права, удаляет пустой список.

Имена кода среза 006 импортируются внутри тестов; разметку разбирает `html.parser`, элементы ищутся по зацепкам
`data-*` (CONTRACT-006, раздел 11). Отказы формы — 200 с `[data-error][data-code]` или `[role=alert][data-code]`
(раздел 10.1); тексты — литералы раздела 12. Журнал читается из `core.AuditEvent` (раздел 8)."""
import functools
from html.parser import HTMLParser

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from tests import factories, support
from tests import support_lists as ls
from tests import support_org as org

pytestmark = pytest.mark.django_db

HX = {"HTTP_HX_REQUEST": "true"}
_VOID = {"input", "br", "img", "meta", "link", "hr", "area", "base", "col", "embed", "source", "track", "wbr"}
TYPES = ("string", "text", "number", "money", "date", "datetime", "bool", "choice", "person", "unit", "record", "file")
TYPE_LABELS = {"string": "Строка", "number": "Число", "money": "Деньги", "date": "Дата", "bool": "Да/нет",
               "text": "Многострочный текст", "datetime": "Дата и время"}

# свойства по типам (план, «Значения по типам», абзац «Свойства по типам»; FR-508)
NOT_FOR = {"bool", "file"}
ALLOWED = {
    "required": set(TYPES) - NOT_FOR,
    "multiple": {"person", "unit", "record", "choice", "file"},
    "default": {"string", "number", "money", "date", "bool", "choice"},
    "unique": {"string", "number"},
    "deadline": {"date"},
}


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


@functools.lru_cache(maxsize=32)
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


def alert(response, code: str):
    """Общий отказ: статус 200 и один `[role=alert][data-code=code]`; возвращает элемент."""
    assert response.status_code == 200, response.status_code
    found = find(response, role="alert", data_code=code)
    assert len(found) == 1, (code, [(e.attrs.get("data-code"), e.text) for e in find(response, role="alert")])
    return found[0]


def models():
    return (support.model("lists.List"), support.model("lists.Field"), support.model("lists.Access"),
            support.model("lists.Record"))


def events(*actions: str) -> list:
    return list(support.model("core.AuditEvent").objects.filter(action__in=actions).order_by("id"))


def settings_url(lst, tail: str = "") -> str:
    return f"/lists/{lst.pk}/settings/{tail}"


def fields_url(lst, tail: str = "") -> str:
    return f"/lists/{lst.pk}/settings/fields/{tail}"


def post_field(client, lst, **data):
    """POST формы добавления поля; `name` и `type` — обязательные ключи."""
    return client.post(fields_url(lst, "new/"), data)


def field_of(lst, name: str):
    return support.model("lists.Field").objects.get(list=lst, name=name)


def grid_codes(response, attr: str, tag: str | None = None) -> list[str]:
    """Значения зацепки `attr` по порядку в разметке."""
    html_attr = attr.replace("_", "-")
    return [el.attrs[html_attr] for el in find(response, tag, **{attr: True})]


# --- главная и создание списка -----------------------------------------------------------------------------

def test_home_after_clear_seed_shows_explanation_and_create_button_to_manager():
    """FR-501, FR-503, FR-546: без стартовых данных (`clear_seed()` первым шагом, решение 35) главная управляющего
    показывает `[data-empty-state="lists"]` с текстом `home_empty` и кнопку `a[data-action="lists-create"]` на
    `/lists/new/`; сотрудник без прав на списки раздела не видит (404)."""
    ls.clear_seed()
    List = support.model("lists.List")
    assert List.objects.count() == 0
    manager = ls.as_manager()

    page = manager.client.get("/lists/")
    assert page.status_code == 200
    empty = find(page, data_empty_state="lists")
    assert len(empty) == 1
    assert ("Списков пока нет. Список — это ваш реестр: оборудование, лицензии, договоры. Создайте первый"
            in empty[0].text)
    create = find(page, "a", data_action="lists-create")
    assert len(create) == 1 and create[0].attrs["href"] == "/lists/new/" and "Создать список" in create[0].text
    assert find(page, "li", data_list_id=True) == []

    plain = support.logged_in(support.make_employee())
    assert plain.get("/lists/").status_code == 404


def test_create_list_opens_settings_with_tabs_main_fields_access_and_system_title():
    """FR-502, FR-503, FR-504: POST `/lists/new/` создаёт список и ведёт на `/lists/<id>/settings/`; страница настройки
    — `nav[data-lists-tabs]` с вкладками «Основное», «Поля», «Права» (текущая — `aria-current="page"`); у нового списка
    в сетке полей только системное «Название» (`tr[data-field-code="title"][data-system]`), строк `Field` нет."""
    List, Field, Access, _ = models()
    manager = ls.as_manager()

    created = manager.client.post("/lists/new/", {"name": "Реестр техники", "description": "Всё железо"})
    lst = List.objects.get(name="Реестр техники")
    assert created.status_code == 302 and created["Location"] == settings_url(lst)
    assert (lst.description, lst.next_number, lst.next_field_no) == ("Всё железо", 1, 1)

    tabs = {"main": ("Основное", settings_url(lst)), "fields": ("Поля", fields_url(lst)),
            "access": ("Права", settings_url(lst, "access/"))}
    for current, url in (("main", settings_url(lst)), ("fields", fields_url(lst)),
                         ("access", settings_url(lst, "access/"))):
        page = manager.client.get(url)
        assert page.status_code == 200, url
        nav = find(page, "nav", data_lists_tabs=True)
        assert len(nav) == 1
        for tab, (title, href) in tabs.items():
            link = [el for el in find(page, "a", data_tab=tab) if _inside(el, nav[0])]
            assert len(link) == 1 and title in link[0].text and link[0].attrs["href"] == href, (url, tab)
            assert (link[0].attrs.get("aria-current") == "page") is (tab == current), (url, tab)

    page = manager.client.get(fields_url(lst))
    grid = find(page, data_lists_fields_grid=True)
    assert len(grid) == 1
    rows = [el for el in find(page, "tr", data_field_code=True) if _inside(el, grid[0])]
    assert [row.attrs["data-field-code"] for row in rows] == ["title"]
    assert "data-system" in rows[0].attrs
    assert [el for el in find(page, "button") + find(page, "a", data_action=True)
            if _inside(el, rows[0]) and "data-action" in el.attrs] == []
    assert Field.objects.filter(list=lst).count() == 0 and not Field.objects.filter(code="title").exists()
    assert Access.objects.filter(list=lst).count() == 0


def test_new_list_has_no_access_rows_and_writes_list_created():
    """FR-503, FR-513: у нового списка нет строк `Access` (наборы «Читают» и «Правят» пусты); журнал — одно событие
    `lists.list_created` (`object_type` `lists.list`, `object_id` — id списка, исполнитель — управляющий, `after` —
    `name` и `description`); читающий по ролям список без наборов не видит (404), управляющий видит."""
    List, _, Access, _ = models()
    manager = ls.as_manager()
    before_ids = set(support.model("core.AuditEvent").objects.values_list("pk", flat=True))

    assert manager.client.post("/lists/new/", {"name": "Договоры подряда", "description": "С подрядчиками"}
                               ).status_code == 302
    lst = List.objects.get(name="Договоры подряда")
    assert Access.objects.filter(list=lst).count() == 0

    created = [e for e in events("lists.list_created") if e.pk not in before_ids]
    assert len(created) == 1
    event = created[0]
    assert (event.object_type, event.object_id, event.actor_id) == ("lists.list", str(lst.pk), manager.user.pk)
    assert not event.before
    assert event.after == {"name": "Договоры подряда", "description": "С подрядчиками"}

    assert manager.client.get(f"/lists/{lst.pk}/").status_code == 200
    outsider = support.logged_in(support.make_employee(roles=[factories.make_role()]))
    assert outsider.get(f"/lists/{lst.pk}/").status_code == 404


def test_list_name_100_and_description_500_accepted_name_101_empty_and_description_501_rejected_at_field():
    """FR-502, FR-546: название 100 знаков и описание 500 принимаются; название 101 — отказ `too_long` у поля `name`
    («Предел: 100 знаков»), описание 501 — у поля `description` («Предел: 500 знаков»), введённое остаётся в форме;
    пустое название — отказ `required` у поля `name` («Обязательное поле»); отказанные списки не создаются."""
    from apps.lists.services import schema
    from apps.lists.services.errors import ListsError

    List = support.model("lists.List")
    manager = ls.as_manager()
    name_100, name_101, text_500, text_501 = "а" * 100, "б" * 101, "в" * 500, "г" * 501
    count = List.objects.count()

    ok = manager.client.post("/lists/new/", {"name": name_100, "description": text_500})
    assert ok.status_code == 302
    saved = List.objects.get(name=name_100)
    assert saved.description == text_500 and List.objects.count() == count + 1

    long_name = manager.client.post("/lists/new/", {"name": name_101, "description": "ok"})
    assert "Предел: 100 знаков" in refusal(long_name, "name", "too_long").text
    assert find(long_name, "input", name="name")[0].attrs.get("value") == name_101
    long_text = manager.client.post("/lists/new/", {"name": "Короткое", "description": text_501})
    assert "Предел: 500 знаков" in refusal(long_text, "description", "too_long").text
    empty = manager.client.post("/lists/new/", {"name": "", "description": "ok"})
    assert "Обязательное поле" in refusal(empty, "name", "required").text
    assert List.objects.count() == count + 1 and not List.objects.filter(name__in=[name_101, "Короткое"]).exists()

    for kwargs, field, code in (({"name": name_101, "description": ""}, "name", "too_long"),
                                ({"name": "Служебный", "description": text_501}, "description", "too_long")):
        with pytest.raises(ListsError) as caught:
            schema.create_list(actor=manager.user, **kwargs)
        assert (caught.value.code, caught.value.field) == (code, field)
    assert List.objects.count() == count + 1


def test_list_name_in_other_case_rejected_at_field_and_lower_name_integrity_error_gives_same_error():
    """FR-502: название без учёта регистра уникально: «EQUIPMENT it» при существующем «Equipment IT» — отказ
    `name_taken` у поля `name` («Список с таким названием уже есть») и на странице, и в службе; ограничение базы
    `Lower(name)` даёт `IntegrityError` при прямой вставке (вторая линия, раздел 2.2; названия латиницей, чтобы
    результат не зависел от локали базы)."""
    from apps.lists.services import schema
    from apps.lists.services.errors import ListsError

    List = support.model("lists.List")
    manager = ls.as_manager()
    ls.make_list("Equipment IT")
    count = List.objects.count()

    again = manager.client.post("/lists/new/", {"name": "EQUIPMENT it", "description": ""})
    assert "Список с таким названием уже есть" in refusal(again, "name", "name_taken").text
    with pytest.raises(ListsError) as caught:
        schema.create_list(name="equipment it", description="", actor=manager.user)
    assert (caught.value.code, caught.value.field) == ("name_taken", "name")
    assert caught.value.message == "Список с таким названием уже есть"
    assert List.objects.count() == count

    with pytest.raises(IntegrityError), transaction.atomic():
        ls.make_list("eQuIpMeNt iT")
    assert List.objects.count() == count and List.objects.filter(name__iexact="equipment it").count() == 1

    same = manager.client.post("/lists/new/", {"name": "Equipment IT", "description": ""})
    refusal(same, "name", "name_taken")


def test_rename_and_description_change_write_list_changed_with_before_after():
    """FR-503: переименование и смена описания на `/lists/<id>/settings/` — 302 на тот же адрес и событие
    `lists.list_changed` (`object_type` `lists.list`) с изменёнными ключами в `before` и `after`: только `name`, только
    `description`, оба сразу; значение «Было» остаётся в `before`, «Стало» — в `after`."""
    List = support.model("lists.List")
    manager = ls.as_manager()
    lst = ls.make_list("Старое имя", description="Было")
    url = settings_url(lst)

    renamed = manager.client.post(url, {"name": "Новое имя", "description": "Было"})
    assert renamed.status_code == 302 and renamed["Location"] == url
    described = manager.client.post(url, {"name": "Новое имя", "description": "Стало"})
    assert described.status_code == 302 and described["Location"] == url
    both = manager.client.post(url, {"name": "Третье имя", "description": "Совсем другое"})
    assert both.status_code == 302

    lst.refresh_from_db()
    assert (lst.name, lst.description) == ("Третье имя", "Совсем другое")
    changed = events("lists.list_changed")
    assert len(changed) == 3
    assert all((e.object_type, e.object_id, e.actor_id) == ("lists.list", str(lst.pk), manager.user.pk)
               for e in changed)
    assert (changed[0].before, changed[0].after) == ({"name": "Старое имя"}, {"name": "Новое имя"})
    assert (changed[1].before, changed[1].after) == ({"description": "Было"}, {"description": "Стало"})
    assert (changed[2].before, changed[2].after) == ({"name": "Новое имя", "description": "Стало"},
                                                     {"name": "Третье имя", "description": "Совсем другое"})
    assert List.objects.filter(pk=lst.pk).count() == 1


# --- системное «Название» и добавление поля ------------------------------------------------------------------

def test_system_title_is_not_field_row_has_code_title_and_cannot_be_deleted_hidden_or_retyped():
    """FR-504: «Название» — не строка `Field` (кода `title` в таблице полей нет, даже когда есть другие поля); в сетке
    полей — строка `tr[data-field-code="title"][data-system]` без кнопок; удалить, скрыть, сменить тип по адресам
    `…/fields/title/…` нельзя — 404 и в базе ничего не меняется."""
    _, Field, _, _ = models()
    manager = ls.as_manager()
    lst = ls.make_list()
    other = ls.add_field(lst, "string", "Серийный номер")

    page = manager.client.get(fields_url(lst))
    assert page.status_code == 200
    rows = {row.attrs["data-field-code"]: row for row in find(page, "tr", data_field_code=True)}
    assert set(rows) == {"title", other.code}
    assert "data-system" in rows["title"].attrs and "data-system" not in rows[other.code].attrs
    assert [el for el in find(page, "button") + find(page, "a") if _inside(el, rows["title"])
            and "data-action" in el.attrs] == []
    assert [el for el in find(page, "button", data_action=True) if _inside(el, rows[other.code])]

    assert not Field.objects.filter(list=lst, code="title").exists()
    before = list(Field.objects.filter(list=lst).values_list("code", "name", "type", "hidden"))
    assert manager.client.get(fields_url(lst, "title/")).status_code == 404
    for tail, data in (("title/delete/", {}), ("title/hide/", {}), ("title/", {"name": "Название", "type": "text"}),
                       ("title/up/", {}), ("title/down/", {})):
        assert manager.client.post(fields_url(lst, tail), data).status_code == 404, tail
    assert list(Field.objects.filter(list=lst).values_list("code", "name", "type", "hidden")) == before
    assert events("lists.field_deleted", "lists.field_hidden", "lists.field_changed") == []


def test_field_name_unique_in_list_case_insensitive_100_accepted_101_rejected_and_hint_200_accepted_201_rejected():
    """FR-506, FR-546: название поля уникально в списке без учёта регистра — «iP» при «IP» отказ `field_name_taken` у
    поля `name`; в другом списке такое же название допустимо; название 100 знаков принимается, 101 — `too_long`
    («Предел: 100 знаков»); подсказка 200 знаков принимается, 201 — `too_long` у поля `hint` («Предел: 200 знаков»);
    отказанные поля не создаются (названия латиницей: результат не зависит от локали базы)."""
    _, Field, _, _ = models()
    manager = ls.as_manager()
    lst, other = ls.make_list(), ls.make_list()
    assert post_field(manager.client, lst, name="IP", type="string").status_code == 302

    dup = post_field(manager.client, lst, name="iP", type="string")
    assert "Поле с таким названием уже есть" in refusal(dup, "name", "field_name_taken").text
    assert Field.objects.filter(list=lst).count() == 1
    assert post_field(manager.client, other, name="iP", type="string").status_code == 302

    name_100, name_101 = "a" * 100, "b" * 101
    assert post_field(manager.client, lst, name=name_100, type="string").status_code == 302
    assert Field.objects.filter(list=lst, name=name_100).count() == 1
    long_name = post_field(manager.client, lst, name=name_101, type="string")
    assert "Предел: 100 знаков" in refusal(long_name, "name", "too_long").text
    assert find(long_name, "input", name="name")[0].attrs.get("value") == name_101
    assert not Field.objects.filter(list=lst, name=name_101).exists()

    assert post_field(manager.client, lst, name="With hint", type="string", hint="h" * 200).status_code == 302
    assert Field.objects.get(list=lst, name="With hint").hint == "h" * 200
    long_hint = post_field(manager.client, lst, name="Hint too long", type="string", hint="h" * 201)
    assert "Предел: 200 знаков" in refusal(long_hint, "hint", "too_long").text
    assert not Field.objects.filter(list=lst, name="Hint too long").exists()
    assert Field.objects.filter(list=lst).count() == 3


def test_51st_field_rejected_counting_hidden_fields():
    """FR-506: у списка до 50 полей, скрытые считаются: 49 видимых и одно скрытое — 51-е поле отказ `fields_limit`
    («Не больше 50 полей») и в службе, и на странице (общий `[role=alert]`); при 48 видимых и одном скрытом 50-е поле
    добавляется."""
    from apps.lists.services import schema
    from apps.lists.services.errors import ListsError

    _, Field, _, _ = models()
    manager = ls.as_manager()
    full = ls.make_list()
    for i in range(49):
        ls.add_field(full, "string", f"Видимое {i}")
    ls.add_field(full, "string", "Скрытое", hidden=True)
    assert Field.objects.filter(list=full).count() == 50

    with pytest.raises(ListsError) as caught:
        schema.add_field(full, name="Лишнее", type="string", actor=manager.user)
    assert caught.value.code == "fields_limit"
    page = post_field(manager.client, full, name="Лишнее", type="string")
    assert "Не больше 50 полей" in alert(page, "fields_limit").text
    assert Field.objects.filter(list=full).count() == 50 and not Field.objects.filter(name="Лишнее").exists()

    room = ls.make_list()
    for i in range(48):
        ls.add_field(room, "string", f"Видимое {i}")
    ls.add_field(room, "string", "Скрытое", hidden=True)
    added = schema.add_field(room, name="Пятидесятое", type="string", actor=manager.user)
    assert added.pk and Field.objects.filter(list=room).count() == 50


def test_field_code_f_next_field_no_not_reused_after_delete_and_reserved_or_invalid_codes_rejected():
    """FR-506: поле, созданное вручную, получает код `f<next_field_no>` (f1, f2, f3…), счётчик растёт и после удаления
    поля не возвращается (после удаления f2 следующее поле — f3, `next_field_no` равен 4); коды `title`, `number`,
    `new`, `order`, не по `^[a-z][a-z0-9_]*$` и длиннее 40 знаков отклоняются проверкой модели (`full_clean`),
    допустимые коды проходят."""
    _, Field, _, _ = models()
    from apps.lists.services import schema

    manager = ls.as_manager()
    lst = ls.make_list()
    first = schema.add_field(lst, name="Первое", type="string", actor=manager.user)
    second = schema.add_field(lst, name="Второе", type="string", actor=manager.user)
    assert (first.code, second.code) == ("f1", "f2")
    schema.delete_field(second, actor=manager.user)
    third = schema.add_field(lst, name="Третье", type="string", actor=manager.user)
    assert third.code == "f3"
    lst.refresh_from_db()
    assert lst.next_field_no == 4
    assert list(Field.objects.filter(list=lst).order_by("order").values_list("code", flat=True)) == ["f1", "f3"]

    def check(code: str) -> None:
        # Проверяется только поле `code` (К-13): прочие поля (`settings` с `{}`, `hint` и т. п.) исключены, чтобы
        # «пусто» у них не давало ошибку на верной реализации.
        others = [f.name for f in Field._meta.concrete_fields if f.name != "code"]
        Field(list=lst, code=code, name="Проба", type="string", order=1).full_clean(
            exclude=others, validate_unique=False, validate_constraints=False)

    for bad in ("title", "number", "new", "order", "Title", "9x", "a-b", "a b", "", "a" * 41, "_x"):
        with pytest.raises(ValidationError) as caught:
            check(bad)
        assert "code" in caught.value.message_dict, bad
    for good in ("a", "x_1", "f12", "inventory_number", "a" * 40, "numbers", "newer"):
        check(good)


def test_literal_fields_new_and_order_urls_are_not_taken_for_field_code():
    """FR-506: литеральные адреса `settings/fields/new/` и `settings/fields/order/` не путаются с
    `settings/fields/<код>/`: GET `…/new/` — страница формы добавления (200, `form[data-lists-field-form]`), POST
    `…/new/` создаёт поле с кодом `f1`, POST `…/order/` меняет порядок (302; НХ — 204); поле с кодом `zzz`, которого
    нет, — 404."""
    _, Field, _, _ = models()
    manager = ls.as_manager()
    lst = ls.make_list()

    page = manager.client.get(fields_url(lst, "new/"))
    assert page.status_code == 200 and find(page, "form", data_lists_field_form=True)
    assert manager.client.get(fields_url(lst, "zzz/")).status_code == 404

    assert post_field(manager.client, lst, name="Первое", type="string").status_code == 302
    assert post_field(manager.client, lst, name="Второе", type="string").status_code == 302
    assert list(Field.objects.filter(list=lst).order_by("order").values_list("code", flat=True)) == ["f1", "f2"]
    assert not Field.objects.filter(code__in=["new", "order"]).exists()

    ordered = manager.client.post(fields_url(lst, "order/"), {"codes": ["f2", "f1"]})
    assert ordered.status_code == 302
    assert list(Field.objects.filter(list=lst).order_by("order").values_list("code", flat=True)) == ["f2", "f1"]
    ordered = manager.client.post(fields_url(lst, "order/"), {"codes": ["f1", "f2"]}, **HX)
    assert ordered.status_code == 204
    assert list(Field.objects.filter(list=lst).order_by("order").values_list("code", flat=True)) == ["f1", "f2"]
    assert manager.client.get(fields_url(lst, "f1/")).status_code == 200


# --- свойства по типам -------------------------------------------------------------------------------------

def test_service_rejects_property_not_of_its_type_for_each_of_12_types():
    """FR-508: `schema.add_field` отклоняет свойство не своего типа — `ListsError("property_not_allowed",
    field=<свойство>)` — по каждому из пяти свойств («обязательное», «несколько значений», значение по умолчанию,
    «уникальное», «срок») у каждого из 12 типов, где оно недоступно; поле не создаётся; допустимые сочетания
    (обязательное, несколько значений, «уникальное», «срок») принимаются."""
    from apps.lists.services import schema
    from apps.lists.services.errors import ListsError

    _, Field, _, _ = models()
    manager = ls.as_manager()
    lst = ls.make_list()
    values = {"required": True, "multiple": True, "default": "x", "unique": True, "deadline": True}
    refused = accepted = 0
    for field_type in TYPES:
        extra = {"target": lst} if field_type == "record" else {}
        for prop, value in values.items():
            name = f"{field_type}-{prop}"
            if field_type in ALLOWED[prop]:
                if prop == "default":
                    continue
                schema.add_field(lst, name=name, type=field_type, actor=manager.user, **{prop: value}, **extra)
                accepted += 1
                assert Field.objects.filter(list=lst, name=name).count() == 1, name
                continue
            with pytest.raises(ListsError) as caught:
                schema.add_field(lst, name=name, type=field_type, actor=manager.user, **{prop: value}, **extra)
            assert (caught.value.code, caught.value.field) == ("property_not_allowed", prop), (field_type, prop)
            assert not Field.objects.filter(list=lst, name=name).exists(), name
            refused += 1
    assert refused == sum(len(set(TYPES) - ALLOWED[prop]) for prop in values)
    assert accepted == sum(len(ALLOWED[prop]) for prop in values if prop != "default")


def test_field_form_shows_only_properties_of_its_type_and_file_has_no_required():
    """FR-508: форма поля `form[data-lists-field-form]` показывает только свойства своего типа (`[data-prop]`:
    «обязательное», «несколько значений», значение по умолчанию, «уникальное», валюта, целевой список, «срок»);
    недоступных типу свойств в разметке нет; у «файл» и «да/нет» нет «обязательного» (нет и `input[name=required]`);
    порогов нет у всех типов, кроме «даты»."""
    manager = ls.as_manager()
    lst = ls.make_list()
    expected = {
        "string": {"required", "default", "unique"}, "text": {"required"}, "number": {"required", "default", "unique"},
        "money": {"required", "default", "currency"}, "date": {"required", "default", "deadline"},
        "datetime": {"required"}, "bool": {"default"}, "choice": {"required", "multiple", "default"},
        "person": {"required", "multiple"}, "unit": {"required", "multiple"},
        "record": {"required", "multiple", "target"}, "file": {"multiple"},
    }
    restricted = {"required", "multiple", "unique", "default", "currency", "target", "deadline"}
    for field_type in TYPES:
        field = ls.add_field(lst, field_type, f"Поле {field_type}", choices=("Да", "Нет") if field_type == "choice"
                             else (), target=lst if field_type == "record" else None)
        page = manager.client.get(fields_url(lst, f"{field.code}/"))
        assert page.status_code == 200, field_type
        form = find(page, "form", data_lists_field_form=True)
        assert len(form) == 1, field_type
        shown = {el.attrs["data-prop"] for el in find(page, data_prop=True) if _inside(el, form[0])}
        assert shown & restricted == expected[field_type], (field_type, shown)
        if field_type != "date":
            assert "thresholds" not in shown, field_type
        if field_type in ("file", "bool"):
            assert not [el for el in find(page, name="required") if _inside(el, form[0])], field_type


def test_default_value_only_for_six_types_and_date_today_stored_as_today_true():
    """FR-508: значение по умолчанию принимают шесть типов и хранят в форме раздела 2.2: строка — строкой, число —
    канонической строкой («12,5» → «12.5»), деньги — строкой с двумя знаками («1234,5» → «1234.50»), дата — `{"today":
    true}` («today») или `"YYYY-MM-DD"`, да/нет — `true`, список значений — `[id]`; у остальных шести типов — отказ
    `property_not_allowed` у поля `default`, поле не создаётся."""
    _, Field, _, _ = models()
    manager = ls.as_manager()
    lst = ls.make_list()
    cases = [("string", "abc", "abc"), ("number", "12,5", "12.5"), ("money", "1234,5", "1234.50"),
             ("date", "today", {"today": True}), ("date", "14.03.2025", "2025-03-14"), ("bool", "on", True)]
    for i, (field_type, raw, stored) in enumerate(cases):
        name = f"По умолчанию {i}"
        assert post_field(manager.client, lst, name=name, type=field_type, default=raw).status_code == 302, name
        field = field_of(lst, name)
        assert field.default == stored and type(field.default) is type(stored), (field_type, field.default)

    choice = ls.add_field(lst, "choice", "Выбор", choices=("Первое", "Второе"))
    picked = ls.choice_id(choice, "Второе")
    edited = manager.client.post(fields_url(lst, f"{choice.code}/"),
                                 {"name": "Выбор", "type": "choice", "default": str(picked)})
    assert edited.status_code == 302
    choice.refresh_from_db()
    assert choice.default == [picked]

    count = Field.objects.filter(list=lst).count()
    for field_type in ("text", "datetime", "person", "unit", "record", "file"):
        extra = {"target": str(lst.pk)} if field_type == "record" else {}
        refused = post_field(manager.client, lst, name=f"Без умолчания {field_type}", type=field_type, default="x",
                             **extra)
        refusal(refused, "default", "property_not_allowed")
    assert Field.objects.filter(list=lst).count() == count


def test_money_currency_rub_by_default_usd_and_eur_accepted_other_code_rejected():
    """FR-507: у «денег» валюта `RUB` по умолчанию (`settings["currency"]`), `USD` и `EUR` принимаются, иной код —
    отказ `currency_bad` у поля `currency` («Валюта: RUB, USD или EUR»), и в службе тоже; поле не создаётся."""
    from apps.lists.services import schema
    from apps.lists.services.errors import ListsError

    _, Field, _, _ = models()
    manager = ls.as_manager()
    lst = ls.make_list()
    assert post_field(manager.client, lst, name="Без валюты", type="money").status_code == 302
    assert field_of(lst, "Без валюты").settings["currency"] == "RUB"
    for code in ("USD", "EUR", "RUB"):
        assert post_field(manager.client, lst, name=f"В {code}", type="money", currency=code).status_code == 302
        assert field_of(lst, f"В {code}").settings["currency"] == code

    bad = post_field(manager.client, lst, name="В фунтах", type="money", currency="GBP")
    assert "Валюта: RUB, USD или EUR" in refusal(bad, "currency", "currency_bad").text
    with pytest.raises(ListsError) as caught:
        schema.add_field(lst, name="В иенах", type="money", currency="JPY", actor=manager.user)
    assert (caught.value.code, caught.value.field) == ("currency_bad", "currency")
    assert not Field.objects.filter(list=lst, name__in=["В фунтах", "В иенах"]).exists()
    assert schema.add_field(lst, name="По умолчанию", type="money", actor=manager.user).settings["currency"] == "RUB"


def test_record_field_without_target_rejected_and_target_own_list_allowed():
    """FR-507, FR-511: поле «запись другого списка» без списка — отказ `target_required` у поля `target` («Выберите
    список») на странице и в службе; целью может быть и сам список (302, `Field.target_id` — его id); база держит
    ограничение `lists_field_target_iff_record` в обе стороны (тип `record` без цели и цель у не-`record`)."""
    from apps.lists.services import schema
    from apps.lists.services.errors import ListsError

    _, Field, _, _ = models()
    manager = ls.as_manager()
    lst, other = ls.make_list(), ls.make_list()

    missing = post_field(manager.client, lst, name="Ссылка", type="record")
    assert "Выберите список" in refusal(missing, "target", "target_required").text
    with pytest.raises(ListsError) as caught:
        schema.add_field(lst, name="Ссылка", type="record", actor=manager.user)
    assert (caught.value.code, caught.value.field) == ("target_required", "target")
    assert Field.objects.filter(list=lst).count() == 0

    assert post_field(manager.client, lst, name="Родитель", type="record", target=str(lst.pk)).status_code == 302
    assert post_field(manager.client, lst, name="Другой", type="record", target=str(other.pk)).status_code == 302
    assert field_of(lst, "Родитель").target_id == lst.pk and field_of(lst, "Другой").target_id == other.pk

    with pytest.raises(IntegrityError), transaction.atomic():
        ls.add_field(lst, "record", "Без цели")
    with pytest.raises(IntegrityError), transaction.atomic():
        ls.add_field(lst, "string", "С целью", target=other)
    assert Field.objects.filter(list=lst).count() == 2


# --- порядок полей ------------------------------------------------------------------------------------------

def test_fields_of_six_types_appear_in_add_order_with_order_last_plus_one():
    """FR-506, FR-507, FR-508, FR-529: шесть полей (строка, число, деньги, дата со сроком, да/нет, текст) получают
    коды f1…f6 и `order` 1…6 по порядку добавления, сетка полей показывает их в этом порядке после «Названия»; после
    удаления f3 новое поле получает `order` «последний + 1» (7) и код f7; журнал — по событию `lists.field_created` на
    каждое добавление (`type` — подпись типа, `field` — название, `list` — название списка)."""
    _, Field, _, _ = models()
    from apps.lists.services import schema

    manager = ls.as_manager()
    lst = ls.make_list("Реестр")
    plan = [("Строка", "string", {}), ("Число", "number", {}), ("Сумма", "money", {}),
            ("Срок", "date", {"deadline": "on", "thresholds": ["30", "7"]}), ("Флаг", "bool", {}),
            ("Заметка", "text", {})]
    for name, field_type, extra in plan:
        assert post_field(manager.client, lst, name=name, type=field_type, **extra).status_code == 302, name
    rows = list(Field.objects.filter(list=lst).order_by("order").values_list("code", "name", "type", "order"))
    assert rows == [(f"f{i}", name, field_type, i) for i, (name, field_type, _) in enumerate(plan, start=1)]
    assert field_of(lst, "Сумма").settings["currency"] == "RUB"
    deadline = field_of(lst, "Срок").settings
    assert deadline["deadline"] is True and sorted(deadline["thresholds"]) == [7, 30]

    schema.delete_field(Field.objects.get(list=lst, code="f3"), actor=manager.user)
    assert post_field(manager.client, lst, name="Позже", type="datetime").status_code == 302
    last = field_of(lst, "Позже")
    assert (last.code, last.order) == ("f7", 7)

    page = manager.client.get(fields_url(lst))
    codes = [el.attrs["data-field-code"] for el in find(page, "tr", data_field_code=True)]
    assert codes == ["title", "f1", "f2", "f4", "f5", "f6", "f7"]

    created = events("lists.field_created")
    assert len(created) == 7
    first = created[0]
    assert (first.object_type, first.actor_id) == ("lists.field", manager.user.pk)
    assert first.object_id == str(Field.objects.get(list=lst, code="f1").pk)
    assert (first.after["list"], first.after["field"], first.after["type"]) == ("Реестр", "Строка", "Строка")
    assert created[3].after["type"] == "Дата"


def test_up_down_arrows_and_order_post_change_order_of_form_card_and_default_columns():
    """FR-506: стрелка «вверх» (`…/<код>/up/`) и «вниз» (`…/down/`) — 302 на вкладку «Поля» — и POST `…/fields/order/`
    (НХ — 204) меняют порядок полей в форме записи (`[data-lists-field]`), карточке (`[data-lists-value]`) и столбцах
    таблицы по умолчанию (`th[data-sort]`); порядок со скрытым полем: `codes` — все коды, без `title`; чужой,
    пропущенный (скрытое поле) код или `title` — отказ `bad_order` без изменений."""
    from apps.lists.services import schema
    from apps.lists.services.errors import ListsError

    _, Field, _, _ = models()
    manager = ls.as_manager()
    lst = ls.make_list()
    fields = [ls.add_field(lst, "string", name, show_in_table=True) for name in ("Первое", "Второе", "Третье")]
    record = ls.make_record(lst, "Запись", {"f1": "a", "f2": "b", "f3": "c"})
    codes = ["f1", "f2", "f3"]

    def seen() -> dict:
        pick = lambda page, attr, tag=None: [c for c in grid_codes(page, attr, tag) if c in codes]  # noqa: E731
        form = manager.client.get(f"/lists/{lst.pk}/add/")
        card = manager.client.get(f"/lists/{lst.pk}/{record.number}/")
        grid = manager.client.get(f"/lists/{lst.pk}/")
        assert form.status_code == card.status_code == grid.status_code == 200
        return {"form": pick(form, "data_lists_field"), "card": pick(card, "data_lists_value"),
                "columns": pick(grid, "data_sort", "th"),
                "order": list(Field.objects.filter(list=lst).order_by("order").values_list("code", flat=True))}

    start = seen()
    assert all(value == codes for value in start.values()), start

    up = manager.client.post(fields_url(lst, "f2/up/"))
    assert up.status_code == 302 and up["Location"] == fields_url(lst)
    moved = ["f2", "f1", "f3"]
    assert all(value == moved for value in seen().values()), seen()

    down = manager.client.post(fields_url(lst, "f2/down/"))
    assert down.status_code == 302 and down["Location"] == fields_url(lst)
    assert all(value == codes for value in seen().values()), seen()

    ordered = manager.client.post(fields_url(lst, "order/"), {"codes": ["f3", "f1", "f2"]}, **HX)
    assert ordered.status_code == 204
    assert all(value == ["f3", "f1", "f2"] for value in seen().values()), seen()

    hidden = ls.add_field(lst, "string", "Скрытое", hidden=True)
    ids_before = list(Field.objects.filter(list=lst).order_by("order").values_list("code", flat=True))
    assert ids_before == ["f3", "f1", "f2", hidden.code]
    for bad in (["f3", "f1", "f2"], ["title", "f3", "f1", "f2", hidden.code], ["f3", "f1", "f2", hidden.code, "zzz"]):
        with pytest.raises(ListsError) as caught:
            schema.set_order(lst, bad, actor=manager.user)
        assert caught.value.code == "bad_order", bad
        refused = manager.client.post(fields_url(lst, "order/"), {"codes": bad}, **HX)
        assert "Порядок полей изменился, обновите страницу" in alert(refused, "bad_order").text
    assert list(Field.objects.filter(list=lst).order_by("order").values_list("code", flat=True)) == ids_before
    schema.set_order(lst, ["f1", hidden.code, "f2", "f3"], actor=manager.user)
    assert list(Field.objects.filter(list=lst).order_by("order").values_list("code", flat=True)) == [
        "f1", hidden.code, "f2", "f3"]
    assert len(fields) == 3


def test_new_field_required_in_list_with_records_rejected_fill_all_records_first():
    """FR-509, FR-546: новое поле «обязательное» в списке с записями (в том числе только в архиве) — отказ
    `required_new_with_records` у поля `required` («Сначала заполните поле у всех записей») на странице и в службе;
    поле не создаётся; без `required` оно создаётся, в пустом списке `required` допустим сразу."""
    from apps.lists.services import schema
    from apps.lists.services.errors import ListsError

    _, Field, _, _ = models()
    manager = ls.as_manager()
    live, archived, empty = ls.make_list(), ls.make_list(), ls.make_list()
    ls.make_record(live, "Живая")
    ls.make_record(archived, "В архиве", archived=True)

    for lst in (live, archived):
        refused = post_field(manager.client, lst, name="Обязательное", type="string", required="on")
        assert "Сначала заполните поле у всех записей" in refusal(
            refused, "required", "required_new_with_records").text
        with pytest.raises(ListsError) as caught:
            schema.add_field(lst, name="Обязательное", type="string", required=True, actor=manager.user)
        assert (caught.value.code, caught.value.field) == ("required_new_with_records", "required")
        assert Field.objects.filter(list=lst).count() == 0

    assert post_field(manager.client, live, name="Необязательное", type="string").status_code == 302
    assert field_of(live, "Необязательное").required is False
    assert post_field(manager.client, empty, name="Обязательное", type="string", required="on").status_code == 302
    assert field_of(empty, "Обязательное").required is True


# --- срок ---------------------------------------------------------------------------------------------------

def test_deadline_form_offers_30_and_7_saves_thresholds_and_allows_several_deadline_fields():
    """FR-529: форма нового поля «дата» предлагает пороги только 30 и 7 (`input[name=thresholds]`, подстановка при
    первом включении «срока» — решение Opus S1-Q5);
    «срок» с порогами сохраняется (`settings["deadline"]` истинно, `settings["thresholds"]` — заданные числа, порядок
    не проверяется); сроком можно пометить несколько полей-дат одного списка; пороги 1 и 365 принимаются; в журнал
    `lists.field_created` пороги попадают ключом `thresholds`."""
    from apps.lists.services import schema

    manager = ls.as_manager()
    lst = ls.make_list()
    # Решение Opus (S1-Q5, 11.2): «30 и 7» подставляются только при первом включении «срока» в форме, сохранённое
    # поле показывает свои пороги; на повторный показ формы тест не опирается. Сервер отдаёт форму нового поля
    # `?type=date` (10.2) со свойством «срок»; входы порогов, если уже выведены, заполнены только значениями 30 и 7
    # (первые два, третий пуст). Само включение «срока» и подстановку проверяет приёмка.
    page = manager.client.get(fields_url(lst, "new/?type=date"))
    assert page.status_code == 200
    assert len(find(page, data_prop="deadline")) == 1
    offered = [el.attrs.get("value") for el in find(page, "input", name="thresholds") if el.attrs.get("value")]
    assert offered in ([], ["30", "7"]), offered

    assert post_field(manager.client, lst, name="Окончание", type="date", deadline="on",
                      thresholds=["30", "7"]).status_code == 302
    assert post_field(manager.client, lst, name="Поверка", type="date", deadline="on",
                      thresholds=["14", "", ""]).status_code == 302
    assert post_field(manager.client, lst, name="Границы", type="date", deadline="on",
                      thresholds=["1", "365"]).status_code == 302
    first, second, bounds = field_of(lst, "Окончание"), field_of(lst, "Поверка"), field_of(lst, "Границы")
    assert all(f.settings["deadline"] is True for f in (first, second, bounds))
    assert sorted(first.settings["thresholds"]) == [7, 30]
    assert sorted(second.settings["thresholds"]) == [14]
    assert sorted(bounds.settings["thresholds"]) == [1, 365]

    service = schema.add_field(lst, name="Через службу", type="date", deadline=True, thresholds=(30, 7, 1),
                               actor=manager.user)
    assert service.settings["deadline"] is True and sorted(service.settings["thresholds"]) == [1, 7, 30]
    created = events("lists.field_created")
    by_name = {e.after["field"]: e for e in created}
    assert "thresholds" in by_name["Окончание"].after
    assert "30" in str(by_name["Окончание"].after["thresholds"]) and "7" in str(by_name["Окончание"].after["thresholds"])


def test_deadline_thresholds_0_366_fourth_and_repeat_rejected():
    """FR-529: порог — целое от 1 до 365, не больше трёх, без повторов: 0, 366, четвёртый порог, повтор и не число —
    отказ `thresholds_bad` у поля `thresholds` («Порог — целое число от 1 до 365, не больше трёх порогов, без
    повторов») на странице и в службе; поле не создаётся."""
    from apps.lists.services import schema
    from apps.lists.services.errors import ListsError

    _, Field, _, _ = models()
    manager = ls.as_manager()
    lst = ls.make_list()
    text = "Порог — целое число от 1 до 365, не больше трёх порогов, без повторов"
    bad_sets = [["0"], ["366"], ["30", "7", "3", "1"], ["30", "30"], ["abc"], ["-5"], ["7", "7", "30"]]
    for i, values in enumerate(bad_sets):
        refused = post_field(manager.client, lst, name=f"Плохое {i}", type="date", deadline="on", thresholds=values)
        assert text in refusal(refused, "thresholds", "thresholds_bad").text, values
        assert not Field.objects.filter(list=lst, name=f"Плохое {i}").exists(), values
    service_bad = [(0,), (366,), (30, 7, 3, 1), (30, 30)]
    for i, values in enumerate(service_bad):
        with pytest.raises(ListsError) as caught:
            schema.add_field(lst, name=f"Служба {i}", type="date", deadline=True, thresholds=values,
                             actor=manager.user)
        assert (caught.value.code, caught.value.field) == ("thresholds_bad", "thresholds"), values
    assert Field.objects.filter(list=lst).count() == 0
    assert post_field(manager.client, lst, name="Три порога", type="date", deadline="on",
                      thresholds=["90", "30", "7"]).status_code == 302
    assert sorted(field_of(lst, "Три порога").settings["thresholds"]) == [7, 30, 90]


# --- права списка --------------------------------------------------------------------------------------------

def test_access_tab_saves_unit_to_read_and_role_to_edit_and_child_unit_members_and_edit_role_read():
    """FR-513: вкладка «Права» (`…/settings/access/`) сохраняет подразделение в «Читают» и роль в «Правят» (строки
    `Access`, 302 на тот же адрес, `li[data-subject]` в `[data-lists-access]`); сотрудник вложенного подразделения читает
    (200, но правки нет — 403), роль «Правят» читает и правит; посторонний — 404; после снятия подразделения
    читавший теряет доступ; журнал `lists.access_changed` с названиями в `readers` и `editors`."""
    _, _, Access, _ = models()
    manager = ls.as_manager()
    lst = ls.make_list("Лицензии отдела")
    parent_unit = org.make_unit("Отдел сопровождения")
    child_unit = org.make_unit("Группа первой линии", parent=parent_unit)
    edit_role = factories.make_role()
    member = support.make_employee()
    org.make_member(member, child_unit)
    member_client = support.logged_in(member)
    editor = support.make_employee(roles=[edit_role])
    editor_client = support.logged_in(editor)
    stranger = support.logged_in(support.make_employee())

    for client in (member_client, editor_client, stranger):
        assert client.get(f"/lists/{lst.pk}/").status_code == 404

    saved = manager.client.post(settings_url(lst, "access/"), {
        "readers": [f"unit:{parent_unit.pk}"], "editors": [f"role:{edit_role.pk}"]})
    assert saved.status_code == 302 and saved["Location"] == settings_url(lst, "access/")
    rows = sorted(Access.objects.filter(list=lst).values_list("level", "role_id", "unit_id"),
                  key=lambda row: row[0])
    assert rows == [("edit", edit_role.pk, None), ("read", None, parent_unit.pk)]

    page = manager.client.get(settings_url(lst, "access/"))
    read_box = find(page, data_lists_access="read")
    edit_box = find(page, data_lists_access="edit")
    assert len(read_box) == len(edit_box) == 1
    assert [el for el in find(page, "li", data_subject=f"unit:{parent_unit.pk}") if _inside(el, read_box[0])]
    assert [el for el in find(page, "li", data_subject=f"role:{edit_role.pk}") if _inside(el, edit_box[0])]

    assert member_client.get(f"/lists/{lst.pk}/").status_code == 200
    assert member_client.get(f"/lists/{lst.pk}/add/").status_code == 403
    assert member_client.get(settings_url(lst)).status_code == 403
    assert editor_client.get(f"/lists/{lst.pk}/").status_code == 200
    assert editor_client.get(f"/lists/{lst.pk}/add/").status_code == 200
    assert stranger.get(f"/lists/{lst.pk}/").status_code == 404

    changed = events("lists.access_changed")
    assert len(changed) == 1
    event = changed[0]
    assert (event.object_type, event.object_id, event.actor_id) == ("lists.list", str(lst.pk), manager.user.pk)
    assert event.after["readers"] == parent_unit.name and event.after["editors"] == edit_role.name
    assert not event.before.get("readers") and not event.before.get("editors")

    removed = manager.client.post(settings_url(lst, "access/"), {"editors": [f"role:{edit_role.pk}"]})
    assert removed.status_code == 302
    assert Access.objects.filter(list=lst, level="read").count() == 0
    assert member_client.get(f"/lists/{lst.pk}/").status_code == 404
    assert editor_client.get(f"/lists/{lst.pk}/").status_code == 200
    assert len(events("lists.access_changed")) == 2


# --- удаление списка -----------------------------------------------------------------------------------------

def test_delete_list_with_records_or_only_archived_records_rejected_and_button_unavailable_with_reason():
    """FR-503, FR-546: список с записью, и с одной только записью в архиве, не удаляется: `can_delete_list` даёт
    `list_has_records`, POST `/lists/<id>/delete/` — 200 с `[role=alert][data-code="list_has_records"]`
    («Нельзя удалить: есть записи»), `schema.delete_list` — `ListsError`; на странице настройки
    `button[data-action="list-delete"]` с `disabled` и пояснение `[data-lists-delete-reason]` с этим текстом; у пустого
    списка кнопка доступна, пояснения нет; в журнале `lists.list_deleted` нет."""
    from apps.lists.services import schema
    from apps.lists.services.errors import ListsError

    List = support.model("lists.List")
    manager = ls.as_manager()
    live, archived, empty = ls.make_list(), ls.make_list(), ls.make_list()
    ls.make_record(live, "Живая")
    ls.make_record(archived, "В архиве", archived=True)
    text = "Нельзя удалить: есть записи"

    for lst in (live, archived):
        refused = schema.can_delete_list(lst)
        assert refused is not None and refused.code == "list_has_records"
        page = manager.client.get(settings_url(lst))
        assert page.status_code == 200
        button = find(page, "button", data_action="list-delete")
        assert len(button) == 1 and "disabled" in button[0].attrs
        reason = find(page, data_lists_delete_reason=True)
        assert len(reason) == 1 and text in reason[0].text
        assert text in alert(manager.client.post(f"/lists/{lst.pk}/delete/"), "list_has_records").text
        with pytest.raises(ListsError) as caught:
            schema.delete_list(lst, actor=manager.user)
        assert caught.value.code == "list_has_records"
        assert List.objects.filter(pk=lst.pk).exists()

    assert schema.can_delete_list(empty) is None
    page = manager.client.get(settings_url(empty))
    button = find(page, "button", data_action="list-delete")
    assert len(button) == 1 and "disabled" not in button[0].attrs
    assert find(page, data_lists_delete_reason=True) == []
    assert events("lists.list_deleted") == []


def test_delete_list_referenced_by_other_list_field_rejected_and_self_reference_does_not_block():
    """FR-503, FR-511, FR-546: список, на который ссылается поле другого списка, не удаляется: `list_referenced`
    («Нельзя удалить: на список ссылается поле <поле> списка <список>» — первое такое поле по названию списка и поля),
    на странице — общий отказ и пояснение у кнопки; поле этого же списка на себя удалению не мешает (302 на
    `/lists/`, список и его поля удалены)."""
    from apps.lists.services import schema

    List, Field, _, _ = models()
    manager = ls.as_manager()
    target = ls.make_list("Целевой")
    beta, alpha = ls.make_list("Бета"), ls.make_list("Альфа")
    ls.add_field(beta, "record", "Яблоко", target=target)
    ls.add_field(beta, "record", "Арбуз", target=target)
    ls.add_field(alpha, "record", "Ягода", target=target)
    text = "Нельзя удалить: на список ссылается поле Ягода списка Альфа"

    refused = schema.can_delete_list(target)
    assert refused is not None and refused.code == "list_referenced" and refused.message == text
    page = manager.client.get(settings_url(target))
    reason = find(page, data_lists_delete_reason=True)
    assert len(reason) == 1 and text in reason[0].text
    assert "disabled" in find(page, "button", data_action="list-delete")[0].attrs
    assert text in alert(manager.client.post(f"/lists/{target.pk}/delete/"), "list_referenced").text
    assert List.objects.filter(pk=target.pk).exists() and Field.objects.filter(target=target).count() == 3

    ls.add_field(alpha, "string", "Прочее")
    Field.objects.filter(list=alpha, name="Ягода").delete()
    Field.objects.filter(list=beta, name="Арбуз").delete()
    again = schema.can_delete_list(target)
    assert again.message == "Нельзя удалить: на список ссылается поле Яблоко списка Бета"

    selfish = ls.make_list("Сам на себя")
    ls.add_field(selfish, "record", "Родитель", target=selfish)
    assert schema.can_delete_list(selfish) is None
    deleted = manager.client.post(f"/lists/{selfish.pk}/delete/")
    assert deleted.status_code == 302 and deleted["Location"] == "/lists/"
    assert not List.objects.filter(pk=selfish.pk).exists() and not Field.objects.filter(list_id=selfish.pk).exists()


def test_delete_empty_manual_or_seeded_list_takes_exclusive_lock_and_for_update_and_writes_list_deleted():
    """FR-503, FR-542: удаление пустого списка берёт исключительный замок списка (`pg_advisory_xact_lock(hashtext(
    'lists.list'), id % 2147483648)`) раньше `SELECT … FOR UPDATE` строки `lists_list` и пишет `lists.list_deleted`
    (`before` — `name`); так же удаляется созданный вручную и стартовый список (по адресу — 302 на `/lists/`, поля
    уходят вместе со списком)."""
    from apps.lists.services import schema

    List, Field, _, _ = models()
    manager = ls.as_manager()
    manual = ls.make_list("Пустой вручную")
    ls.add_field(manual, "string", "Поле")
    name, pk = manual.name, manual.pk

    sqls = ls.sql_of(schema.delete_list, manual, actor=manager.user)
    assert ls.ListLock("exclusive", ls.list_no(pk)) in ls.list_locks(sqls)
    lock_at = next(i for i, sql in enumerate(sqls) if ls.list_locks([sql]))
    locked_row = sqls.index(ls.assert_for_update(sqls, "lists_list"))
    assert lock_at < locked_row
    assert not List.objects.filter(pk=pk).exists() and not Field.objects.filter(list_id=pk).exists()
    deleted = events("lists.list_deleted")
    assert len(deleted) == 1
    assert (deleted[0].object_type, deleted[0].object_id, deleted[0].actor_id) == (
        "lists.list", str(pk), manager.user.pk)
    assert deleted[0].before == {"name": name}

    seeded = List.objects.get(code="contracts")
    seeded_name, seeded_id = seeded.name, seeded.pk
    assert Field.objects.filter(list=seeded).exists() and schema.can_delete_list(seeded) is None
    response = manager.client.post(f"/lists/{seeded_id}/delete/")
    assert response.status_code == 302 and response["Location"] == "/lists/"
    assert not List.objects.filter(pk=seeded_id).exists() and not Field.objects.filter(list_id=seeded_id).exists()
    assert [e.before for e in events("lists.list_deleted")] == [{"name": name}, {"name": seeded_name}]
