"""T-3126: страница «Заявители» и запись заявителя (FR-261, FR-267, FR-268). Сценарий 10 спеки среза 003.

Служба `requesters` (CONTRACT-003 § 6.22), создание записи через `tickets.create` (§ 6.7), загрузка таблицы
(§ 6.23) вызываются настоящими функциями; страницы — по путям § 12.6 и зацепкам § 13.8. Имена кода среза 003
импортируются внутри тестов: сбор проходит до появления кода.
"""
import json
import re
import secrets
from html.parser import HTMLParser

import pytest
from django.db import IntegrityError, transaction
from django.test import Client
from django.utils import timezone

from tests import factories, support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

CORP = "corp.test"
IP = "198.51.100.77"
LIST = "/servicedesk/requesters/"


# --- помощники файла --------------------------------------------------------------------------------

def _manager():
    """Сотрудник с правом «Настройка сервис-деска»."""
    return support.make_with_permissions("servicedesk.manage")


def _without_manage():
    """Сотрудник с правом «Все заявки», но без «Настройки сервис-деска»."""
    return support.make_with_permissions("servicedesk.all")


def _unit(name: str, *, archived: bool = False):
    """Подразделение заявителя (справочник `ClientUnit`)."""
    return model("servicedesk.ClientUnit").objects.create(
        name=name, name_key=org.name_key(name), archived=archived)


def _setup():
    """Домен и очередь по умолчанию (через ORM); возвращает очередь."""
    queue = sd.make_queue()
    sd.configure_servicedesk(domains=[CORP], default_queue=queue)
    return queue


def _address(prefix: str = "req") -> str:
    return f"{prefix}-{secrets.token_hex(4)}@{CORP}"


def _events(action: str) -> list:
    return list(model("core.AuditEvent").objects.filter(action=action).order_by("id"))


def _new_ticket(channel=None, **kw):
    """`tickets.create` с обязательными аргументами по умолчанию."""
    from apps.servicedesk.services import tickets

    channel = channel or tickets.FORM
    kw.setdefault("subject", "Не печатает принтер")
    kw.setdefault("text", "Принтер на втором этаже не печатает")
    kw.setdefault("requester_email", _address())
    if channel == tickets.FORM:
        kw.setdefault("consent_at", timezone.now())
    if channel == tickets.MAIL:
        kw.setdefault("inbound_id", sd.make_inbound().pk)
    if channel == tickets.STAFF:
        kw.setdefault("source", model("servicedesk.Source").objects.get(
            system_code="", name_key=org.name_key("Телефон")))
        kw.setdefault("created_by", support.make_employee())
    return tickets.create(channel=channel, **kw)


def _requester_of(email: str):
    return model("servicedesk.Requester").objects.get(email=email.lower())


class _Rows(HTMLParser):
    """Строки `tr[data-requester]`: номер, ячейки `[data-cell]` (текст) и ссылки `a[data-action]` (`href`)."""

    def __init__(self):
        super().__init__()
        self.rows, self.row, self.cell = [], None, None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "tr" and "data-requester" in attrs:
            self.row = {"id": attrs.get("data-id"), "cells": {}, "actions": {}}
            self.rows.append(self.row)
            return
        if self.row is None:
            return
        if self.cell and tag == self.cell["tag"]:
            self.cell["depth"] += 1
        elif "data-cell" in attrs and self.cell is None:
            self.cell = {"tag": tag, "name": attrs["data-cell"], "depth": 1, "chunks": []}
        if tag == "a" and attrs.get("data-action"):
            self.row["actions"][attrs["data-action"]] = attrs.get("href", "")

    def handle_endtag(self, tag):
        if self.row is None:
            return
        if self.cell and tag == self.cell["tag"]:
            self.cell["depth"] -= 1
            if self.cell["depth"] == 0:
                self.row["cells"][self.cell["name"]] = " ".join("".join(self.cell["chunks"]).split())
                self.cell = None
        elif tag == "tr" and self.cell is None:
            self.row = None

    def handle_data(self, data):
        if self.cell:
            self.cell["chunks"].append(data)


def _rows(html: str) -> list[dict]:
    parser = _Rows()
    parser.feed(html)
    parser.close()
    return parser.rows


def _alert_codes(html: str) -> list[str]:
    """Значения `data-code` у тегов с `role="alert"`."""
    codes = []
    for tag in re.findall(r"<[^>]+>", html):
        if re.search(r"""role=["']alert["']""", tag):
            found = re.search(r'data-code="([^"]*)"', tag)
            if found:
                codes.append(found.group(1))
    return codes


def _has_alert(html: str) -> bool:
    return bool(re.search(r"""role=["']alert["']""", html))


def _get(client: Client, **params):
    response = client.get(LIST, params)
    assert response.status_code == 200, f"страница заявителей: {response.status_code}"
    return response.content.decode()


def _no_personal_data(event, *values: str) -> None:
    """В событии журнала нет адреса, ФИО и подобных значений (FR-289)."""
    text = json.dumps([event.before, event.after], ensure_ascii=False).lower()
    for value in values:
        assert value.lower() not in text, f"в журнале есть значение {value!r}"


# --- страница: колонки, поиск, фильтр, пагинация (FR-267) ---------------------------------------------

def test_requesters_page_columns():
    """FR-267: пять колонок строки, зацепки действий, фильтр и пустое состояние; строки — по адресу."""
    client = support.logged_in(_manager(), ip=IP)
    empty = _get(client)
    assert 'data-empty-state="requesters"' in empty and not _rows(empty)
    unit = _unit("Бухгалтерия")
    full = sd.make_requester("Ivan.Ivanov@corp.test", full_name="Иванов Иван", client_unit=unit, origin="table")
    bare = sd.make_requester("bare@corp.test", origin="ticket")
    sd.make_ticket(requester=full)
    sd.make_ticket(requester=full)

    html = _get(client)
    rows = _rows(html)
    assert 'data-empty-state="requesters"' not in html
    assert [row["id"] for row in rows] == [str(bare.pk), str(full.pk)], "строки идут по адресу"
    by_id = {row["id"]: row for row in rows}
    cells = by_id[str(full.pk)]["cells"]
    assert set(cells) >= {"email", "name", "client-unit", "origin", "tickets-count"}
    assert cells["email"] == "ivan.ivanov@corp.test"
    assert cells["name"] == "Иванов Иван"
    assert cells["client-unit"] == "Бухгалтерия"
    assert cells["origin"] == "таблица"
    assert cells["tickets-count"] == "2"
    bare_cells = by_id[str(bare.pk)]["cells"]
    assert bare_cells["email"] == "bare@corp.test"
    assert bare_cells["origin"] == "заявка"
    assert bare_cells["tickets-count"] == "0"
    for row in rows:
        assert row["actions"].get("requester-edit") == f"/servicedesk/requesters/{row['id']}/edit/"
        assert row["actions"].get("requester-delete") == f"/servicedesk/requesters/{row['id']}/delete/"
    assert re.search(r'<form\b[^>]*data-form="requesters-filter"', html)
    assert re.search(r'<input\b[^>]*name="q"', html)
    assert re.search(r'<select\b[^>]*name="client_unit"', html)


def test_requesters_ticket_count_excludes_anonymized():
    """FR-267: число заявок — без обезличенных (`Count` заявок без `anonymized_at`)."""
    from apps.servicedesk.services import requesters

    record = sd.make_requester(full_name="Счётов Иван")
    sd.make_ticket(requester=record)
    sd.make_ticket(requester=record)
    sd.make_ticket(requester=record, kind="closed", anonymized_at=timezone.now())

    page = requesters.page()
    row = next(row for row in page.rows if row.requester.pk == record.pk)
    assert row.tickets_count == 2
    client = support.logged_in(_manager(), ip=IP)
    shown = next(r for r in _rows(_get(client)) if r["id"] == str(record.pk))
    assert shown["cells"]["tickets-count"] == "2"


def test_search_by_address_case_insensitive():
    """FR-267: поиск по адресу — без учёта регистра, по части и по полному адресу."""
    from apps.servicedesk.services import requesters

    wanted = sd.make_requester("ivanov.petr@corp.test", full_name="Первый")
    other = sd.make_requester("sidorov@corp.test", full_name="Второй")
    client = support.logged_in(_manager(), ip=IP)

    for query in ("IVANOV.PETR", "Ivanov.Petr@Corp.Test", "ivanov"):
        found = [row.requester.pk for row in requesters.page(query=query).rows]
        assert found == [wanted.pk], f"запрос {query!r}: {found}"
        shown = {row["id"] for row in _rows(_get(client, q=query))}
        assert shown == {str(wanted.pk)}, f"страница, запрос {query!r}: {shown}"
    assert str(other.pk) not in {row["id"] for row in _rows(_get(client, q="IVANOV"))}
    assert [row.requester.pk for row in requesters.page(query="SIDOROV").rows] == [other.pk]


def test_search_by_name_yo_ye_insensitive():
    """FR-267: поиск по ФИО — без учёта регистра и «е/ё» (как `accounts.pickable`)."""
    from apps.servicedesk.services import requesters

    with_yo = sd.make_requester(full_name="Фёдор Семёнов")
    with_ye = sd.make_requester(full_name="Федор Петров")
    unrelated = sd.make_requester(full_name="Анна Кузнецова")
    client = support.logged_in(_manager(), ip=IP)

    def found(query):
        return {row.requester.pk for row in requesters.page(query=query).rows}

    assert found("федор") == {with_yo.pk, with_ye.pk}
    assert found("ФЁДОР") == {with_yo.pk, with_ye.pk}
    assert found("семенов") == {with_yo.pk}
    assert found("СЕМЁНОВ") == {with_yo.pk}
    assert found("петров") == {with_ye.pk}
    assert unrelated.pk not in found("федор")
    shown = {row["id"] for row in _rows(_get(client, q="ФЕДОР"))}
    assert shown == {str(with_yo.pk), str(with_ye.pk)}


def test_filter_by_client_unit():
    """FR-267: фильтр по подразделению — только записи с этим подразделением."""
    from apps.servicedesk.services import requesters

    first, second = _unit("Отдел продаж"), _unit("Склад")
    in_first = sd.make_requester("a-first@corp.test", client_unit=first)
    in_second = sd.make_requester("b-second@corp.test", client_unit=second)
    without = sd.make_requester("c-none@corp.test")
    client = support.logged_in(_manager(), ip=IP)

    assert [r.requester.pk for r in requesters.page(client_unit_id=first.pk).rows] == [in_first.pk]
    assert [r.requester.pk for r in requesters.page(client_unit_id=second.pk).rows] == [in_second.pk]
    assert {r.requester.pk for r in requesters.page().rows} == {in_first.pk, in_second.pk, without.pk}
    shown = [row["id"] for row in _rows(_get(client, client_unit=first.pk))]
    assert shown == [str(in_first.pk)]
    both = [row["id"] for row in _rows(_get(client, client_unit=second.pk, q="b-second"))]
    assert both == [str(in_second.pk)]


def test_page_has_50_rows():
    """FR-267: на странице 50 строк, остальные — на следующей; `has_next` и `page`."""
    from apps.servicedesk.services import requesters

    created = [sd.make_requester(f"r{index:02d}@corp.test") for index in range(51)]
    ordered = [str(record.pk) for record in created]
    assert requesters.PAGE_SIZE == 50

    first = requesters.page(number=1)
    assert len(first.rows) == 50 and first.has_next is True and first.page == 1
    second = requesters.page(number=2)
    assert len(second.rows) == 1 and second.has_next is False and second.page == 2
    assert [str(r.requester.pk) for r in first.rows] == ordered[:50]
    assert [str(r.requester.pk) for r in second.rows] == ordered[50:]

    client = support.logged_in(_manager(), ip=IP)
    assert [row["id"] for row in _rows(_get(client))] == ordered[:50]
    assert [row["id"] for row in _rows(_get(client, page=2))] == ordered[50:]


def test_page_links_keep_search_with_special_characters():
    """FR-267: ссылки «Назад» и «Дальше» кодируют строку поиска — `&`, `#`, `+` и пробелы не теряются."""
    from html import unescape
    from urllib.parse import parse_qs, urlsplit

    query = "Ромашка & Ко #1+2"
    created = [sd.make_requester(f"r{index:02d}@{CORP}", full_name=query) for index in range(51)]
    sd.make_requester(f"other@{CORP}", full_name="Другой заявитель")
    ordered = [str(record.pk) for record in created]
    client = support.logged_in(_manager(), ip=IP)

    first = _get(client, q=query)
    assert [row["id"] for row in _rows(first)] == ordered[:50]
    next_href = unescape(re.search(r'<a data-page-next href="([^"]+)"', first).group(1))
    assert urlsplit(next_href).path == LIST
    assert parse_qs(urlsplit(next_href).query) == {"q": [query], "page": ["2"]}

    second = client.get(next_href)
    assert second.status_code == 200
    html = second.content.decode()
    assert [row["id"] for row in _rows(html)] == ordered[50:]
    prev_href = unescape(re.search(r'<a data-page-prev href="([^"]+)"', html).group(1))
    assert parse_qs(urlsplit(prev_href).query) == {"q": [query], "page": ["1"]}


# --- правка и удаление (FR-267) ----------------------------------------------------------------------

def test_edit_name_and_client_unit_saved():
    """FR-267: ФИО и подразделение сохраняются; ФИО до 255 знаков, архивное подразделение не принимается."""
    from apps.servicedesk.services import ServiceDeskError, requesters

    admin = _manager()
    old, new, archived = _unit("Прежнее"), _unit("Новое"), _unit("Закрытое", archived=True)
    record = sd.make_requester(full_name="Иванов", client_unit=old, origin="table")

    assert requesters.update(record, name="Иванов Иван", client_unit_id=new.pk, actor=admin, ip=IP) is True
    record.refresh_from_db()
    assert record.full_name == "Иванов Иван" and record.client_unit_id == new.pk
    assert requesters.update(record, name="Я" * 255, client_unit_id=new.pk, actor=admin, ip=IP) is True
    record.refresh_from_db()
    assert record.full_name == "Я" * 255
    with pytest.raises(ServiceDeskError) as too_long:
        requesters.update(record, name="Я" * 256, client_unit_id=new.pk, actor=admin, ip=IP)
    assert too_long.value.code == "requester_name_too_long"
    with pytest.raises(ServiceDeskError) as in_archive:
        requesters.update(record, name="Иванов Иван", client_unit_id=archived.pk, actor=admin, ip=IP)
    assert in_archive.value.code == "archived_value"
    record.refresh_from_db()
    assert record.full_name == "Я" * 255 and record.client_unit_id == new.pk

    client = support.logged_in(admin, ip=IP)
    url = f"/servicedesk/requesters/{record.pk}/edit/"
    form = client.get(url, **support.HX)
    assert form.status_code == 200
    html = form.content.decode()
    assert re.search(r'<form\b[^>]*data-form="requester"', html)
    assert re.search(r'<input\b[^>]*name="name"', html)
    assert re.search(r'<select\b[^>]*name="client_unit"[^>]*>\s*<option\b[^>]*value=""', html)

    saved = client.post(url, {"name": "Петров Пётр", "client_unit": old.pk})
    assert saved.status_code == 302 and saved["Location"].endswith(LIST)
    record.refresh_from_db()
    assert record.full_name == "Петров Пётр" and record.client_unit_id == old.pk
    cleared = client.post(url, {"name": "Петров Пётр", "client_unit": ""})
    assert cleared.status_code == 302 and cleared["Location"].endswith(LIST)
    record.refresh_from_db()
    assert record.client_unit_id is None and record.full_name == "Петров Пётр"

    refused = client.post(url, {"name": "Я" * 256, "client_unit": old.pk})
    assert refused.status_code == 200 and "requester_name_too_long" in _alert_codes(refused.content.decode())
    in_archive_post = client.post(url, {"name": "Петров Пётр", "client_unit": archived.pk})
    assert in_archive_post.status_code == 200 and "archived_value" in _alert_codes(in_archive_post.content.decode())
    record.refresh_from_db()
    assert record.full_name == "Петров Пётр" and record.client_unit_id is None
    assert client.get(f"/servicedesk/requesters/{record.pk + 10_000}/edit/").status_code == 404


def test_delete_requester_without_tickets_with_confirmation():
    """FR-267: запись без заявок удаляется только с подтверждением; журнал без адреса и ФИО."""
    admin = _manager()
    record = sd.make_requester("to-delete@corp.test", full_name="Удалёнов Иван", origin="ticket")
    number = record.pk
    client = support.logged_in(admin, ip=IP)
    url = f"/servicedesk/requesters/{number}/delete/"

    dialog = client.get(url, **support.HX)
    assert dialog.status_code == 200
    html = dialog.content.decode()
    assert re.search(r'data-dialog="requester-delete"', html)
    assert re.search(r'role="dialog"', html) and re.search(r'aria-modal="true"', html)
    assert html.count("<form") == 1
    assert re.search(r'<form\b[^>]*action="/servicedesk/requesters/%d/delete/"' % number, html)
    assert re.search(r'<input\b(?=[^>]*name="confirm")(?=[^>]*value="1")(?=[^>]*type="hidden")[^>]*>', html)
    assert len(re.findall(r'<button\b[^>]*type="submit"', html)) == 1
    assert model("servicedesk.Requester").objects.filter(pk=number).exists()

    unconfirmed = client.post(url, {})
    assert unconfirmed.status_code == 200
    assert _has_alert(unconfirmed.content.decode()) and "Подтвердите действие" in unconfirmed.content.decode()
    assert model("servicedesk.Requester").objects.filter(pk=number).exists()
    assert not _events("requester.deleted")

    done = client.post(url, {"confirm": "1"})
    assert done.status_code == 302 and done["Location"].endswith(LIST)
    assert not model("servicedesk.Requester").objects.filter(pk=number).exists()
    events = _events("requester.deleted")
    assert len(events) == 1
    event = events[0]
    assert (event.object_type, event.object_id, event.actor_id) == ("requester", str(number), admin.pk)
    assert event.before == {"origin": "ticket"} and event.after == {}
    _no_personal_data(event, "to-delete", "Удалёнов", "Иван")


def test_delete_requester_with_tickets_refused():
    """FR-267: у записи есть заявки — удаление отказано (`requester_has_tickets`), ничего не меняется."""
    from apps.servicedesk.services import ServiceDeskError, requesters

    admin = _manager()
    record = sd.make_requester("has-tickets@corp.test", full_name="Заявкин Пётр")
    ticket = sd.make_ticket(requester=record)
    with pytest.raises(ServiceDeskError) as refused:
        requesters.delete(record, actor=admin, ip=IP)
    assert refused.value.code == "requester_has_tickets"

    client = support.logged_in(admin, ip=IP)
    response = client.post(f"/servicedesk/requesters/{record.pk}/delete/", {"confirm": "1"})
    assert response.status_code == 200
    html = response.content.decode()
    assert _has_alert(html) and "requester_has_tickets" in _alert_codes(html)
    assert model("servicedesk.Requester").objects.filter(pk=record.pk).exists()
    assert model("servicedesk.Ticket").objects.filter(pk=ticket.pk, requester_id=record.pk).exists()
    assert not _events("requester.deleted")


# --- запись заявителя (FR-261) -----------------------------------------------------------------------

def test_requester_address_unique_case_insensitive():
    """FR-261: адрес записи уникален без учёта регистра (повтор в другом регистре — `IntegrityError`)."""
    sd.make_requester("user.one@corp.test")
    Requester = model("servicedesk.Requester")
    with pytest.raises(IntegrityError), transaction.atomic():
        Requester.objects.create(email="User.One@Corp.Test", created_at=timezone.now())
    with pytest.raises(IntegrityError), transaction.atomic():
        Requester.objects.create(email="user.one@corp.test", created_at=timezone.now())
    assert Requester.objects.filter(email__iexact="user.one@corp.test").count() == 1

    _setup()
    first = _new_ticket(requester_email="Same.Person@Corp.Test").ticket
    second = _new_ticket(requester_email="SAME.person@corp.test").ticket
    assert first.requester_id == second.requester_id
    assert Requester.objects.filter(email__iexact="same.person@corp.test").count() == 1


def test_requester_is_not_portal_account():
    """FR-261: заявитель не учётная запись: пользователя с его адресом нет, войти он не может."""
    _setup()
    email = _address("portal")
    _new_ticket(requester_email=email)
    record = _requester_of(email)
    User = model("core.User")
    assert not User.objects.filter(email__iexact=email).exists()
    related = {f.related_model for f in model("servicedesk.Requester")._meta.get_fields()
               if f.is_relation and f.concrete}
    assert User not in related, "запись заявителя не должна ссылаться на учётную запись"
    assert not hasattr(record, "password") and not hasattr(record, "user")

    password = factories.new_password()
    as_requester = support.post_password(support.make_client(), email, password)
    as_unknown = support.post_password(support.make_client(), _address("nobody"), password)
    assert as_requester.status_code == as_unknown.status_code
    assert not (as_requester.status_code == 302 and as_requester["Location"].endswith("/login/code/"))
    assert support.same_failure(as_requester, as_unknown)


def test_origin_ticket_for_record_created_by_first_ticket():
    """FR-261: первая заявка создаёт запись с отметкой «заявка»; следующие запись не пересоздают."""
    _setup()
    email = _address("first")
    first = _new_ticket(requester_email=email.upper()).ticket
    Requester = model("servicedesk.Requester")
    record = Requester.objects.get(email=email)
    assert record.origin == "ticket" and first.requester_id == record.pk
    created = [e for e in _events("requester.created") if e.object_id == str(record.pk)]
    assert len(created) == 1 and created[0].after["origin"] == "ticket"
    _no_personal_data(created[0], email.split("@")[0])

    second = _new_ticket(requester_email=email).ticket
    assert second.requester_id == record.pk
    assert Requester.objects.filter(email=email).count() == 1
    assert [e for e in _events("requester.created") if e.object_id == str(record.pk)] == created

    table = sd.make_requester(_address("table"), origin="table")
    _new_ticket(requester_email=table.email)
    table.refresh_from_db()
    assert table.origin == "table", "запись из таблицы заявка не перекрашивает"


def test_form_remembers_client_unit_only_if_record_empty():
    """FR-261: подразделение с формы записывается в запись, только если в записи оно пусто."""
    from apps.servicedesk.services import tickets

    _setup()
    first, second = _unit("Первое"), _unit("Второе")
    email = _address("memo")
    one = _new_ticket(tickets.FORM, requester_email=email, client_unit_id=first.pk).ticket
    record = _requester_of(email)
    assert record.client_unit_id == first.pk and one.client_unit_id == first.pk, "новая запись запоминает выбор"

    empty = sd.make_requester(_address("empty"), client_unit=None)
    filled = _new_ticket(tickets.FORM, requester_email=empty.email, client_unit_id=second.pk).ticket
    empty.refresh_from_db()
    assert empty.client_unit_id == second.pk and filled.client_unit_id == second.pk, "пустая запись заполняется"

    kept = _new_ticket(tickets.FORM, requester_email=email, client_unit_id=second.pk).ticket
    record.refresh_from_db()
    assert record.client_unit_id == first.pk, "уже записанное подразделение форма не перезаписывает"
    assert kept.client_unit_id == second.pk


def test_form_with_other_unit_does_not_change_record_ticket_keeps_form_unit():
    """FR-261: на форме выбрано другое подразделение — запись прежняя, на заявке остаётся выбор формы."""
    from apps.servicedesk.services import tickets

    _setup()
    recorded, chosen = _unit("В записи"), _unit("На форме")
    record = sd.make_requester(_address("other"), client_unit=recorded, origin="table")
    created = _new_ticket(tickets.FORM, requester_email=record.email, client_unit_id=chosen.pk).ticket

    record.refresh_from_db()
    assert record.client_unit_id == recorded.pk
    created.refresh_from_db()
    assert created.client_unit_id == chosen.pk
    assert created.requester_id == record.pk
    updated = [e for e in _events("requester.updated") if e.object_id == str(record.pk)]
    assert not updated, "запись не менялась — журнала правки нет"


def test_executor_edit_then_import_replaces_unit_always():
    """FR-261: правка исполнителя и загрузка таблицы заменяют подразделение записи всегда."""
    from apps.servicedesk.services import requester_import, tickets

    _setup()
    first, second, third, fourth = _unit("Один"), _unit("Два"), _unit("Три"), _unit("Четыре")
    executor = _without_manage()
    admin = _manager()
    email = _address("replace")
    _new_ticket(tickets.FORM, requester_email=email, client_unit_id=first.pk)
    record = _requester_of(email)
    assert record.client_unit_id == first.pk

    staff = _new_ticket(tickets.STAFF, requester_email=email, client_unit_id=second.pk, created_by=executor).ticket
    record.refresh_from_db()
    assert record.client_unit_id == second.pk and staff.client_unit_id == second.pk, "исполнитель заменяет всегда"

    tickets.update_fields(staff, actor=executor, ip=IP, client_unit_id=third.pk)
    record.refresh_from_db()
    staff.refresh_from_db()
    assert record.client_unit_id == third.pk and staff.client_unit_id == third.pk

    content = ("Почта;Фамилия;Имя;Подразделение\r\n"
               f"{email};Заменов;Иван;{fourth.name}\r\n").encode("utf-8-sig")
    item = requester_import.make_preview(content, file_name="requesters.csv", actor=admin, ip=IP)
    done = requester_import.confirm(item, actor=admin, ip=IP)
    assert done.state == "done" and done.summary["errors"] == 0
    record.refresh_from_db()
    staff.refresh_from_db()
    assert record.client_unit_id == fourth.pk, "загрузка заменяет подразделение записи"
    assert staff.client_unit_id == third.pk, "на заявке остаётся её собственное значение"


# --- права (FR-268) ----------------------------------------------------------------------------------

def test_page_and_menu_403_without_manage_right():
    """FR-268: без права «Настройка сервис-деска» страницы нет (403), вход не выполнен — 302, пункта меню нет."""
    from apps.core.services import permissions

    sd.make_requester(full_name="Закрытов Иван")
    plain = _without_manage()
    admin = _manager()
    client = support.logged_in(plain, ip=IP)
    for params in ({}, {"q": "Закрытов"}, {"page": 2}):
        assert client.get(LIST, params).status_code == 403, f"параметры {params}"
    assert client.get(LIST, **support.HX).status_code == 403

    anonymous = support.make_client().get(LIST)
    assert anonymous.status_code == 302 and "/login" in anonymous["Location"]

    plain_urls = [item["url"] for item in permissions.menu_for(plain)]
    assert not [url for url in plain_urls if url.startswith("/servicedesk/")]
    admin_urls = [item["url"] for item in permissions.menu_for(admin)]
    assert [url for url in admin_urls if url.startswith("/servicedesk/")], "у держателя права пункт виден"
    assert support.logged_in(admin, ip=IP).get(LIST).status_code == 200
    tickets_page = client.get("/tickets/")
    assert tickets_page.status_code == 200
    assert 'href="/servicedesk/' not in tickets_page.content.decode()


def test_requester_edit_and_delete_403_without_manage_right():
    """FR-268: правка и удаление записи без права — 403 и для существующей, и для несуществующей; данные целы."""
    record = sd.make_requester(full_name="Неприкосновенный", client_unit=_unit("Своё"))
    missing = record.pk + 10_000
    client = support.logged_in(_without_manage(), ip=IP)
    for number in (record.pk, missing):
        edit, delete = f"/servicedesk/requesters/{number}/edit/", f"/servicedesk/requesters/{number}/delete/"
        assert client.get(edit).status_code == 403, edit
        assert client.get(edit, **support.HX).status_code == 403, edit
        assert client.post(edit, {"name": "Взломанов", "client_unit": ""}).status_code == 403, edit
        assert client.get(delete).status_code == 403, delete
        assert client.post(delete, {"confirm": "1"}).status_code == 403, delete
    record.refresh_from_db()
    assert record.full_name == "Неприкосновенный" and record.client_unit is not None
    assert not _events("requester.updated") and not _events("requester.deleted")
    anonymous = support.make_client()
    assert anonymous.get(f"/servicedesk/requesters/{record.pk}/edit/").status_code == 302
    assert anonymous.post(f"/servicedesk/requesters/{record.pk}/delete/", {"confirm": "1"}).status_code == 302
    assert model("servicedesk.Requester").objects.filter(pk=record.pk).exists()


def test_requester_data_not_visible_outside_accessible_tickets():
    """FR-268: без права настройки данные заявителя видны только в доступных заявках."""
    mine, foreign = sd.make_queue(), sd.make_queue()
    sd.configure_servicedesk(domains=[CORP], default_queue=mine)
    user = support.make_employee()
    org.make_member(user, mine.unit)
    own_requester = sd.make_requester("own.person@corp.test", full_name="Своёв Алексей")
    foreign_requester = sd.make_requester("foreign.person@corp.test", full_name="Чужеродов Глеб")
    table_only = sd.make_requester("table.person@corp.test", full_name="Табличнов Дмитрий", origin="table")
    own = sd.make_ticket(queue=mine, requester=own_requester)
    other = sd.make_ticket(queue=foreign, requester=foreign_requester)
    client = support.logged_in(user, ip=IP)

    assert client.get(LIST).status_code == 403
    assert client.get(LIST, {"q": "Чужеродов"}).status_code == 403
    card = client.get(f"/tickets/{own.number}/")
    assert card.status_code == 200
    card_html = card.content.decode()
    assert own_requester.email in card_html or own_requester.full_name in card_html
    hidden = client.get(f"/tickets/{other.number}/")
    assert hidden.status_code == 404
    listing = client.get("/tickets/", {"preset": "all"})
    assert listing.status_code == 200
    for response in (hidden, listing):
        html = response.content.decode()
        for value in (foreign_requester.email, "Чужеродов", table_only.email, "Табличнов"):
            assert value not in html, f"в ответе есть чужие данные {value!r}"
    assert f"/tickets/{own.number}/" in listing.content.decode()


def test_ticket_search_does_not_reach_requester_table():
    """FR-268: поиск заявок не заходит в таблицу заявителей (запись без заявок не находится ни у кого)."""
    from apps.servicedesk.services import search, tickets

    default = _setup()
    elsewhere = sd.make_queue()
    member = support.make_employee()
    org.make_member(member, default.unit)
    holder = _without_manage()
    table_only = sd.make_requester("tablichnov.dmitriy@corp.test", full_name="Табличнов Дмитрий", origin="table")
    own = _new_ticket(tickets.MAIL, requester_email=_address("own"), requester_name="Уникумов Борис").ticket
    foreign = _new_ticket(tickets.MAIL, requester_email=_address("foreign"), requester_name="Чужеродов Глеб").ticket
    model("servicedesk.Ticket").objects.filter(pk=foreign.pk).update(queue=elsewhere.unit)

    def numbers(user, query):
        return [t.number for t in search.search(user, query, 50).tickets]

    assert numbers(member, "Уникумов") == [own.number], "свою заявку находит по ФИО заявителя"
    assert numbers(member, "Чужеродов") == [], "чужую заявку поиск не показывает"
    assert numbers(holder, "Чужеродов") == [foreign.number], "держатель «Все заявки» видит и чужую"
    for user in (member, holder):
        assert numbers(user, "Табличнов") == []
        assert numbers(user, "tablichnov.dmitriy@corp.test") == []
    assert table_only.tickets.count() == 0

    client = support.logged_in(member, ip=IP)
    html = client.get("/tickets/", {"preset": "all", "q": "Чужеродов"}).content.decode()
    assert f"/tickets/{foreign.number}/" not in html
    html = client.get("/tickets/", {"preset": "all", "q": "Уникумов"}).content.decode()
    assert f"/tickets/{own.number}/" in html


# --- журнал (FR-267, FR-261) -------------------------------------------------------------------------

def test_edit_unit_audit_was_became_name_only_changed():
    """FR-267, FR-261: журнал правки — подразделение «было и стало» (названия), ФИО только «изменено»."""
    from apps.servicedesk.services import requesters

    admin = _manager()
    old, new = _unit("Бухгалтерия"), _unit("Склад")
    record = sd.make_requester("journal.person@corp.test", full_name="Журналов Иван", client_unit=old,
                               origin="table")

    assert requesters.update(record, name="Журналов Пётр", client_unit_id=new.pk, actor=admin, ip=IP) is True
    events = _events("requester.updated")
    assert len(events) == 1
    event = events[0]
    assert (event.object_type, event.object_id, event.actor_id) == ("requester", str(record.pk), admin.pk)
    assert event.before == {"client_unit": "Бухгалтерия"}
    assert event.after == {"client_unit": "Склад", "name_changed": True}
    _no_personal_data(event, "journal.person", "Журналов", "Иван", "Пётр")

    assert requesters.update(record, name="Журналов Сергей", client_unit_id=new.pk, actor=admin, ip=IP) is True
    name_only = _events("requester.updated")[-1]
    assert len(_events("requester.updated")) == 2
    assert "client_unit" not in name_only.before and "client_unit" not in name_only.after
    assert name_only.after == {"name_changed": True}
    _no_personal_data(name_only, "Сергей", "Журналов")

    assert requesters.update(record, name="Журналов Сергей", client_unit_id=new.pk, actor=admin, ip=IP) is False
    assert len(_events("requester.updated")) == 2, "ничего не изменилось — журнала нет"

    assert requesters.update(record, name="Журналов Сергей", client_unit_id=None, actor=admin, ip=IP) is True
    assert len(_events("requester.updated")) == 3
    cleared = _events("requester.updated")[-1]
    assert cleared.before == {"client_unit": "Склад"}
    assert cleared.after == {"client_unit": ""}
