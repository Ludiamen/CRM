"""T-6108b: карточка записи и безопасный вывод (FR-504, FR-516, FR-546, NFR-506). Сценарии 2 и 5 спеки.

Карточка `/lists/<id>/<n>/`: адрес по номеру, «Запись удалена» у несуществующей записи, состав карточки (видимые
значения, файлы, связанные заявки, «Ссылаются на эту запись», история; скрытое поле не видно — решение владельца
2026-10-25), пометки «в архиве» и «уволен», кнопки по праву; значения, названия и сообщения об отказах выводятся
экранированными, многострочный текст — с `<br>` после экранирования. Код среза на уровне модуля не импортируется
(CONTRACT-006, шапка): модели берутся через `support.model`, зацепки — раздел 11 контракта.
"""
import re
from html.parser import HTMLParser

import pytest

from tests import factories, support, support_servicedesk as sd
from tests import support_lists as lists

pytestmark = pytest.mark.django_db

GONE = "Запись удалена"

# --- разбор разметки (помощник только этого файла; образец — test_lists_unique.py) ----------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}
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
    """Потомки `scope` по тегу и атрибутам; имя с дефисом пишется через `_`."""
    wanted = {name.replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            found.append(node)
    return found


def raw(response) -> str:
    return response.content.decode("utf-8")


# --- данные теста -----------------------------------------------------------------------------------------

def _card(session, lst, number, suffix=""):
    return session.client.get(f"/lists/{lst.pk}/{number}/{suffix}")


def _reader_with(lst, *permissions, extra_lists=()):
    """Читающий `lst` (и `extra_lists`) с правами `permissions` через свою роль; вошёл."""
    role = factories.make_role(permissions=permissions)
    for each in (lst, *extra_lists):
        lists.grant_list(each, role, "read")
    user = support.make_employee(roles=[role])
    return lists.Session(user, support.logged_in(user))


def _actions(response) -> set:
    """Значения `data-action` кнопок и ссылок карточки среди пяти действий записи (раздел 11.5)."""
    names = {"record-edit", "record-archive", "record-restore", "record-label", "record-purge"}
    found = set()
    for node in tree(response).walk():
        if node.tag in ("a", "button") and node.attrs.get("data-action") in names:
            found.add(node.attrs["data-action"])
    return found


def _escaped(marker: str) -> tuple[str, str]:
    """Сырая вставка `<b>marker</b>` и её экранированный вид в ответе."""
    return f"<b>{marker}</b>", f"&lt;b&gt;{marker}&lt;/b&gt;"


def _no_injected_nodes(root, markers):
    """В дереве страницы нет тегов, созданных из вставленной разметки (`b`, `img`, `i`, содержащих маркер)."""
    for node in root.walk():
        if node.tag in ("b", "i", "img", "script"):
            joined = node.text() + " " + " ".join(node.attrs.values())
            for marker in markers:
                assert marker not in joined, f"разметка со вставкой стала элементом <{node.tag}>: {marker}"


# --- тесты ----------------------------------------------------------------------------------------------

def test_card_url_by_number_does_not_change_after_record_and_list_rename():
    """FR-504, FR-516: адрес карточки строится по номеру записи: после переименования записи и списка тот же
    `/lists/<id>/<n>/` открывается, показывает новое название, а ссылка названия в таблице ведёт на тот же адрес."""
    lst = lists.make_list("Оборудование старое")
    lists.add_field(lst, "string", "Модель", show_in_table=True)
    session = lists.as_reader(lst)
    record = lists.make_record(lst, "Принтер старое", {"f1": "HP-1"})
    address = f"/lists/{lst.pk}/{record.number}/"

    before = session.client.get(address)
    assert before.status_code == 200
    assert q(tree(before), None, data_lists_record=True)
    assert "Принтер старое" in raw(before)
    row = q(tree(session.client.get(f"/lists/{lst.pk}/")), "tr", data_record_number=str(record.number))
    assert row and q(row[0], "a", data_field="title")[0].attrs["href"] == address

    record.title = "Принтер новое"
    record.save(update_fields=["title"])
    lst.name = "Оборудование новое"
    lst.save(update_fields=["name"])

    after = session.client.get(address)
    assert after.status_code == 200
    assert q(tree(after), None, data_lists_record=True)
    assert "Принтер новое" in raw(after) and "Принтер старое" not in raw(after)
    row = q(tree(session.client.get(f"/lists/{lst.pk}/")), "tr", data_record_number=str(record.number))
    assert row and q(row[0], "a", data_field="title")[0].attrs["href"] == address
    assert record.number == 1


def test_card_of_missing_record_with_number_below_next_number_is_404_record_deleted():
    """FR-504, FR-546: номер меньше `next_number`, а строки нет (запись удалена навсегда) — 404 со страницей
    `[data-lists-page="gone"]` и текстом «Запись удалена»; номер не меньше `next_number` — обычный 404 без этого
    текста; номер удалённой записи не переиспользуется (следующая запись получает свой номер)."""
    lst = lists.make_list()
    session = lists.as_reader(lst)
    first, second, third = (lists.make_record(lst, f"Запись {n}") for n in (1, 2, 3))
    support.model("lists.Record").objects.filter(pk=second.pk).delete()
    lst.refresh_from_db()
    assert lst.next_number == 4

    gone = _card(session, lst, second.number)
    assert gone.status_code == 404
    assert GONE in raw(gone)
    assert q(tree(gone), None, data_lists_page="gone")
    assert "Запись 2" not in raw(gone)

    for number in (lst.next_number, 99):
        never = _card(session, lst, number)
        assert never.status_code == 404
        assert GONE not in raw(never), f"номер {number} не выдавался, «Запись удалена» не к месту"
        assert not q(tree(never), None, data_lists_page="gone")

    assert _card(session, lst, first.number).status_code == 200
    assert _card(session, lst, third.number).status_code == 200
    newer = lists.make_record(lst, "Запись 4")
    assert newer.number == 4


def test_card_shows_visible_field_values_but_not_hidden_ones_files_related_tickets_referrers_and_history():
    """FR-516: карточка показывает значения видимых полей `[data-lists-value]`, файлы (чистый — со ссылкой,
    «проверяется» — без), «Связанные заявки» (только видимые смотрящему), «Ссылаются на эту запись» и место
    истории; значение и узел скрытого поля в ответе отсутствуют (решение владельца 2026-10-25)."""
    lst = lists.make_list("Оборудование")
    shown = lists.add_field(lst, "string", "Инвентарный номер")
    hidden = lists.add_field(lst, "string", "Служебная метка", hidden=True)
    clean_field = lists.add_field(lst, "file", "Акт")
    pending_field = lists.add_field(lst, "file", "Фото")
    referring = lists.make_list("Лицензии")
    link_field = lists.add_field(referring, "record", "Оборудование", target=lst)
    viewer = _reader_with(lst, extra_lists=(referring,))
    author = support.make_employee()
    record = lists.make_record(
        lst, "Ноутбук", {shown.code: "ИН-777", hidden.code: "метка-скрыта-9"}, created_by=author)
    clean = lists.attach_file(record, clean_field, "акт-приёмки.pdf", status="clean")
    lists.attach_file(record, pending_field, "фото-стойки.png", status="pending")
    support.model("lists.Change").objects.create(record=record, kind="created", changes=[], actor=author)
    owner = lists.make_record(referring, "Лицензия на ноутбук", {link_field.code: [record.pk]}, created_by=author)
    # заявку смотрящий видит как ответственный; чужая заявка в другой очереди ему не видна
    mine = sd.make_ticket(queue=sd.make_queue(), subject="Замена картриджа", assignee=viewer.user)
    foreign = sd.make_ticket(queue=sd.make_queue(), subject="Закупка серверов отдела")
    TicketLink = support.model("lists.TicketLink")
    TicketLink.objects.create(record=record, ticket_number=mine.number)
    TicketLink.objects.create(record=record, ticket_number=foreign.number)

    response = _card(viewer, lst, record.number)

    assert response.status_code == 200
    root = tree(response)
    card = q(root, None, data_lists_record=True)[0]
    value = q(card, None, data_lists_value=shown.code)
    assert value and "ИН-777" in value[0].text()
    assert not q(root, None, data_lists_value=hidden.code), "узел значения скрытого поля"
    assert "метка-скрыта-9" not in raw(response), "значение скрытого поля в карточке"

    files = q(root, None, data_lists_files=clean_field.code)
    assert files, "нет блока файлов поля «Акт»"
    # контракт (11.7) не говорит, чей id в `data-file-id`: строки `RecordFile` или `StoredFile` — принимаются оба
    row = [n for n in q(files[0], "li", data_file_id=True)
           if n.attrs["data-file-id"] in (str(clean.pk), str(clean.file_id))]
    assert row, "нет строки файла с id файла записи"
    assert row[0].attrs["data-scan"] == "clean" and "акт-приёмки.pdf" in row[0].text()
    assert q(row[0], "a", data_action="file-download")
    pending_block = q(root, None, data_lists_files=pending_field.code)
    assert pending_block
    waiting = q(pending_block[0], "li", data_scan="pending")
    assert waiting and "проверяется" in waiting[0].text()
    assert not q(waiting[0], "a", data_action="file-download"), "у непроверенного файла нет ссылки"

    refs = q(root, None, data_lists_referrers=True)
    assert refs, "нет блока «Ссылаются на эту запись»"
    ref_rows = q(refs[0], "li", data_record_ref=f"{referring.pk}:{owner.number}")
    assert ref_rows and "Лицензия на ноутбук" in ref_rows[0].text()

    tickets = q(root, None, data_lists_related_tickets=True)
    assert tickets, "нет блока «Связанные заявки»"
    ticket_rows = q(tickets[0], "li", data_ticket_number=str(mine.number))
    assert ticket_rows
    assert f"#{mine.number} Замена картриджа" in ticket_rows[0].text()
    assert mine.status.name in ticket_rows[0].text()
    assert not q(tickets[0], "li", data_ticket_number=str(foreign.number)), "невидимая заявка в карточке"
    assert foreign.subject not in raw(response)

    assert q(root, None, data_lists_history=True), "нет места истории"


def test_card_of_archived_record_shows_archived_mark():
    """FR-516: карточка записи в архиве показывает пометку `[data-lists-archived]` «в архиве»; у записи не в
    архиве пометки нет."""
    lst = lists.make_list()
    session = lists.as_reader(lst)
    live = lists.make_record(lst, "Живая")
    old = lists.make_record(lst, "Старая", archived=True)

    archived_page = _card(session, lst, old.number)
    live_page = _card(session, lst, live.number)

    assert archived_page.status_code == 200 and live_page.status_code == 200
    marks = q(tree(archived_page), None, data_lists_archived=True)
    assert marks and "в архиве" in marks[0].text()
    assert not q(tree(live_page), None, data_lists_archived=True)


def test_card_shows_dismissed_person_value_with_dismissed_mark():
    """FR-516: уволенный в значении поля «сотрудник» показан ФИО с пометкой «(уволен)» (`span[data-dismissed]`);
    действующий сотрудник — без пометки."""
    lst = lists.make_list()
    gone = lists.add_field(lst, "person", "Бывший владелец")
    active = lists.add_field(lst, "person", "Владелец")
    session = lists.as_reader(lst)
    dismissed_user = support.make_employee(state="dismissed", full_name="Петров Пётр Сергеевич")
    active_user = support.make_employee(full_name="Иванова Анна Павловна")
    record = lists.make_record(lst, "Ноутбук", {gone.code: [dismissed_user.pk], active.code: [active_user.pk]})

    response = _card(session, lst, record.number)

    assert response.status_code == 200
    root = tree(response)
    first = q(root, None, data_lists_value=gone.code)
    assert first
    marks = q(first[0], "span", data_dismissed="true")
    assert marks and "Петров Пётр Сергеевич" in marks[0].text() and "(уволен)" in marks[0].text()
    second = q(root, None, data_lists_value=active.code)
    assert second and "Иванова Анна Павловна" in second[0].text()
    assert not q(second[0], None, data_dismissed=True)
    assert "(уволен)" not in second[0].text()


def test_card_buttons_edit_archive_label_by_right_and_purge_only_for_manager_on_archived_record():
    """FR-516: читающему — только «Этикетка»; правящему — «Править» и «В архив» (у записи в архиве вместо «В архив»
    «Вернуть»); «Удалить навсегда» (`record-purge` с диалогом подтверждения) — только управляющему и только у записи
    в архиве."""
    lst = lists.make_list()
    live = lists.make_record(lst, "Живая")
    old = lists.make_record(lst, "Старая", archived=True)
    reader, editor, manager = lists.as_reader(lst), lists.as_editor(lst), lists.as_manager()
    base = f"/lists/{lst.pk}"

    for rec in (live, old):
        assert _actions(_card(reader, lst, rec.number)) == {"record-label"}, f"читающий, запись {rec.number}"

    editor_live = _card(editor, lst, live.number)
    assert _actions(editor_live) == {"record-edit", "record-archive", "record-label"}
    links = {n.attrs["data-action"]: n for n in tree(editor_live).walk()
             if n.tag == "a" and n.attrs.get("data-action") in ("record-edit", "record-label")}
    assert links["record-edit"].attrs["href"] == f"{base}/{live.number}/edit/"
    assert links["record-label"].attrs["href"] == f"{base}/{live.number}/label/"

    # у записи в архиве про «Править» контракт молчит: проверяется остальное
    editor_old = _card(editor, lst, old.number)
    assert _actions(editor_old) - {"record-edit"} == {"record-restore", "record-label"}

    manager_live = _card(manager, lst, live.number)
    assert _actions(manager_live) == {"record-edit", "record-archive", "record-label"}
    manager_old = _card(manager, lst, old.number)
    assert _actions(manager_old) - {"record-edit"} == {"record-restore", "record-label", "record-purge"}
    assert q(tree(manager_old), "dialog", data_lists_confirm=True), "нет диалога подтверждения удаления"


def test_markup_in_list_field_value_and_record_names_is_escaped_on_card_form_and_table():
    """NFR-506: название и описание списка, название записи и значение поля с разметкой выводятся экранированными
    на главной, в таблице, карточке и форме правки: в ответе нет сырой вставки, в разметке нет созданных из неё
    элементов."""
    lst_marker, desc_marker, title_marker, value_marker = "zq7f3k-list", "zq7f3k-desc", "zq7f3k-title", "zq7f3k-val"
    lst = lists.make_list(_escaped(lst_marker)[0], description=_escaped(desc_marker)[0])
    field = lists.add_field(lst, "string", "Модель", show_in_table=True)
    editor = lists.as_editor(lst)
    record = lists.make_record(lst, _escaped(title_marker)[0], {field.code: _escaped(value_marker)[0]},
                               created_by=editor.user)
    markers = (lst_marker, desc_marker, title_marker, value_marker)
    pages = {
        "home": ("/lists/", (lst_marker, desc_marker)),
        "table": (f"/lists/{lst.pk}/", (title_marker, value_marker)),
        "card": (f"/lists/{lst.pk}/{record.number}/", (title_marker, value_marker)),
        "form": (f"/lists/{lst.pk}/{record.number}/edit/", (title_marker, value_marker)),
    }

    for name, (path, expected) in pages.items():
        response = editor.client.get(path)
        assert response.status_code == 200, name
        body = raw(response)
        for marker in markers:
            assert _escaped(marker)[0] not in body, f"{name}: сырая вставка {marker}"
        for marker in expected:
            assert _escaped(marker)[1] in body, f"{name}: нет экранированного {marker}"
        _no_injected_nodes(tree(response), markers)


def test_markup_in_refusal_message_is_escaped():
    """NFR-506, FR-546: имена из сообщений об отказах экранируются: «Запись уже изменил {who}» с ФИО из разметки и
    «Нельзя удалить: на список ссылается поле {field} списка {list}» с названиями из разметки."""
    who_marker, list_marker, field_marker = "zq7f3k-who", "zq7f3k-lst", "zq7f3k-fld"
    # 1) конфликт версий: ФИО сохранившего с разметкой
    lst = lists.make_list()
    field = lists.add_field(lst, "string", "Модель")
    editor = lists.as_editor(lst)
    saver = support.make_employee(full_name=f"{_escaped(who_marker)[0]} Иванов")
    record = lists.make_record(lst, "Запись", {field.code: "a"}, created_by=saver, updated_by=saver, version=2)

    response = editor.client.post(
        f"/lists/{lst.pk}/{record.number}/edit/", {"title": "Запись", field.code: "b", "base_version": 1})

    assert response.status_code == 200
    alerts = q(tree(response), None, role="alert", data_code="version_conflict")
    assert alerts and "Запись уже изменил" in alerts[0].text()
    assert _escaped(who_marker)[0] not in raw(response)
    assert _escaped(who_marker)[1] in raw(response)
    _no_injected_nodes(tree(response), (who_marker,))

    # 2) отказ удаления списка: названия ссылающегося списка и поля с разметкой
    target = lists.make_list("Цель")
    referring = lists.make_list(_escaped(list_marker)[0])
    lists.add_field(referring, "record", _escaped(field_marker)[0], target=target)
    manager = lists.as_manager()

    refused = manager.client.post(f"/lists/{target.pk}/delete/")

    assert refused.status_code == 200
    alert = q(tree(refused), None, role="alert", data_code="list_referenced")
    assert alert, "нет отказа list_referenced"
    for marker in (list_marker, field_marker):
        assert _escaped(marker)[0] not in raw(refused), f"сырая вставка {marker}"
        assert _escaped(marker)[1] in raw(refused), f"нет экранированного {marker}"
    _no_injected_nodes(tree(refused), (list_marker, field_marker))
    assert support.model("lists.List").objects.filter(pk=target.pk).exists()


def test_multiline_value_is_escaped_then_line_breaks_become_br():
    """NFR-506: значение «многострочный текст» с разметкой в карточке — сначала экранирование, потом переносы строк
    в `<br>`: вставка видна текстом, а переносы стали `<br>` внутри `[data-lists-value]`."""
    marker = "zq7f3k-ml"
    lst = lists.make_list()
    field = lists.add_field(lst, "text", "Описание")
    session = lists.as_reader(lst)
    record = lists.make_record(lst, "Запись", {field.code: f"{_escaped(marker)[0]}\nвторая строка\nтретья"})

    response = _card(session, lst, record.number)

    assert response.status_code == 200
    body = raw(response)
    assert _escaped(marker)[0] not in body
    assert re.search(re.escape(_escaped(marker)[1]) + r"<br\s*/?>\s*вторая строка<br\s*/?>\s*третья", body), \
        "после экранирования переносы строк должны стать <br>"
    value = q(tree(response), None, data_lists_value=field.code)
    assert value
    assert len(q(value[0], "br")) == 2
    _no_injected_nodes(value[0], (marker,))
    assert marker in value[0].text()
