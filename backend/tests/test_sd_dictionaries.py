"""T-3103: справочники сервис-деска (FR-206, FR-207, FR-260, FR-269…273). Сценарий 9 спеки среза 003.

Службы — `apps.servicedesk.services.dictionaries` (CONTRACT-003 § 6.5), маршруты — § 12.6, зацепки — § 13.7,
журнал — § 9.2, отказы — § 6.2 (только по `code`; из текстов — слово «архив» у `in_use`, решение B1-1).
"""
import importlib
from html.parser import HTMLParser

import pytest
from django.db import IntegrityError, transaction

from tests import support, support_org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

IP = "198.51.100.9"
_VOID = {"input", "br", "img", "hr", "meta", "link", "area", "base", "col", "source", "wbr"}

# вид справочника службы -> (метка модели, вид в пути маршрута)
KINDS = {
    "category": ("Category", "categories"),
    "priority": ("Priority", "priorities"),
    "complexity": ("Complexity", "complexities"),
    "status": ("Status", "statuses"),
    "source": ("Source", "sources"),
    "client_unit": ("ClientUnit", "client-units"),
}
KIND_LABELS = {"new": "новая", "in_progress": "в работе", "waiting": "ждёт ответа заявителя", "closed": "закрыта"}


# --- разбор разметки (помощник только этого файла) ---------------------------------------------

class _El:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.kids = tag, attrs, parent, []

    def walk(self):
        yield self
        for kid in self.kids:
            if isinstance(kid, _El):
                yield from kid.walk()

    def text(self) -> str:
        parts = [kid if isinstance(kid, str) else kid.text() for kid in self.kids]
        return " ".join(" ".join(parts).split())

    def find_all(self, tag=None, **want):
        """Элементы (в том числе сам) с тегом `tag` и атрибутами `want` (`data_x` -> `data-x`; True — любое значение)."""
        wanted = {key.replace("_", "-"): value for key, value in want.items()}
        found = []
        for el in self.walk():
            if tag is not None and el.tag != tag:
                continue
            if all(name in el.attrs and (value is True or el.attrs[name] == str(value)) for name, value in wanted.items()):
                found.append(el)
        return found


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _El("#root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        el = _El(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.kids.append(el)
        if tag not in _VOID:
            self.cur = el

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(_El(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.kids.append(data)


def dom(response) -> _El:
    builder = _Builder()
    builder.feed(response.content.decode("utf-8", "replace") if hasattr(response, "content") else response)
    return builder.root


def alert_text(response) -> str:
    return " ".join(el.text() for el in dom(response).find_all(None, role="alert")).lower()


def dict_rows(response, kind: str) -> dict:
    """Строки таблицы справочника `kind`: `{id: tr}` по зацепкам § 13.7."""
    tables = dom(response).find_all("table", data_dictionary=kind)
    assert len(tables) == 1, f"нет таблицы table[data-dictionary={kind!r}]"
    return {int(tr.attrs["data-id"]): tr for tr in tables[0].find_all("tr", data_dictionary_row=True)}


def cell(row, name: str):
    found = row.find_all(None, data_cell=name)
    return found[0] if found else None


# --- помощники данных и вызовов ---------------------------------------------------------------

def svc():
    return importlib.import_module("apps.servicedesk.services.dictionaries")


def sd_error():
    return importlib.import_module("apps.servicedesk.services").ServiceDeskError


def cls(kind: str):
    return model(f"servicedesk.{KINDS[kind][0]}")


def admin():
    """«Администратор портала»: `servicedesk.manage` и `servicedesk.all` (CONTRACT-003 § 3.3)."""
    return support.make_admin()


def route(kind: str, *parts) -> str:
    tail = "".join(f"{p}/" for p in parts)
    return f"/servicedesk/dictionaries/{KINDS[kind][1]}/{tail}"


def refused(code: str, func, *args, **kwargs):
    """Вызов службы должен отказать `ServiceDeskError` с этим `code`; возвращает ошибку."""
    with pytest.raises(sd_error()) as caught:
        func(*args, **kwargs)
    assert caught.value.code == code, f"ждали {code!r}, получили {caught.value.code!r}"
    return caught.value


def by_name(kind: str, name: str):
    return cls(kind).objects.get(name_key=support_org.name_key(name))


def extra_for(kind: str, *, queue_id=None, status_kind: str = "in_progress") -> dict:
    """Обязательные `extra` создания: у категории — очередь, у статуса — вид."""
    if kind == "category":
        return {"queue_id": queue_id if queue_id is not None else sd.make_queue().unit_id}
    if kind == "status":
        return {"kind": status_kind}
    return {}


def make_value(kind: str, name: str, actor, **over):
    """Значение справочника через службу; для вида без `order` порядок не передаётся."""
    extra = extra_for(kind, queue_id=over.pop("queue_id", None), status_kind=over.pop("status_kind", "in_progress"))
    extra.update(over)
    return svc().create(kind, name=name, actor=actor, **extra)


def audit(action: str | None = None, *, object_id: str | None = None, prefix: str | None = None) -> list:
    qs = model("core.AuditEvent").objects.all()
    if action:
        qs = qs.filter(action=action)
    if prefix:
        qs = qs.filter(action__startswith=prefix)
    if object_id is not None:
        qs = qs.filter(object_id=object_id)
    return list(qs.order_by("id"))


def object_id_of(kind: str, obj) -> str:
    return f"{KINDS[kind][1]}:{obj.pk}"


# --- начальные данные миграции -------------------------------------------------------------------

def test_initial_statuses_with_kinds_and_default_marks():
    """FR-206, FR-207: шесть начальных статусов с видами, отметками «по умолчанию», `system_code` и порядком (§ 2.2);
    в списке справочника — подписи видов и «по умолчанию» (§ 13.7); `default_status(kind)` отдаёт отмеченный."""
    Status = cls("status")
    got = [(s.name, s.kind, s.is_default, s.system_code, s.order, s.archived)
           for s in Status.objects.order_by("order", "name")]
    assert got == [
        ("Новая", "new", True, "", 10, False),
        ("В работе", "in_progress", True, "", 20, False),
        ("Ждёт ответа заявителя", "waiting", True, "", 30, False),
        ("Решена", "closed", True, "", 40, False),
        ("Не может быть решена", "closed", False, "", 50, False),
        ("Закрыта автоматически", "closed", False, "autoclosed", 60, False),
    ]
    for kind, name in (("new", "Новая"), ("in_progress", "В работе"), ("waiting", "Ждёт ответа заявителя"),
                       ("closed", "Решена")):
        assert svc().default_status(kind).name == name
    page = support.logged_in(admin()).get(route("status"))
    assert page.status_code == 200
    rows = dict_rows(page, "status")
    for status in Status.objects.all():
        row = rows[status.pk]
        assert cell(row, "kind").text() == KIND_LABELS[status.kind]
        assert ("по умолчанию" in cell(row, "default").text()) is status.is_default


def test_initial_criticalities_low_medium_high_with_default():
    """FR-270: критичности «Низкая», «Средняя», «Высокая» (10/20/30); «по умолчанию» — «Средняя» в настройках."""
    Priority = cls("priority")
    got = [(p.name, p.order, p.archived, p.name_key) for p in Priority.objects.order_by("order")]
    assert got == [("Низкая", 10, False, "низкая"), ("Средняя", 20, False, "средняя"),
                   ("Высокая", 30, False, "высокая")]
    settings_row = model("servicedesk.ServiceDeskSettings").objects.get(pk=1)
    assert settings_row.default_priority.name == "Средняя"
    assert [p.name for p in svc().offered("priority")] == ["Низкая", "Средняя", "Высокая"]


def test_initial_complexity_levels_easy_medium_high():
    """FR-271: уровни сложности «Лёгкий», «Средний», «Высокий» (10/20/30), у «Лёгкий» `name_key="легкий"`."""
    got = [(c.name, c.order, c.archived, c.name_key) for c in cls("complexity").objects.order_by("order")]
    assert got == [("Лёгкий", 10, False, "легкий"), ("Средний", 20, False, "средний"),
                   ("Высокий", 30, False, "высокий")]
    assert [c.name for c in svc().offered("complexity")] == ["Лёгкий", "Средний", "Высокий"]


def test_initial_sources_mail_form_system_phone_in_person_manual():
    """FR-272: источники «Почта» (`mail`), «Форма» (`form`) системные; «Телефон» и «Лично» ручные (§ 2.2)."""
    got = [(s.name, s.system_code, s.order, s.archived) for s in cls("source").objects.order_by("order")]
    assert got == [("Почта", "mail", 10, False), ("Форма", "form", 20, False), ("Телефон", "", 30, False),
                   ("Лично", "", 40, False)]
    assert [s.name for s in svc().offered("source")] == ["Почта", "Форма", "Телефон", "Лично"]


def test_initial_category_other_default_queue_shown_on_form():
    """FR-269: начальная категория «Другое» — системная, на форме, без своей очереди (`order=100`); открытая
    форма `/request/` предлагает её в `select[name=category]` (§ 13.6)."""
    Category = cls("category")
    assert Category.objects.count() == 1
    other = Category.objects.get()
    assert (other.name, other.is_system, other.on_form, other.queue_id, other.order, other.archived,
            other.default_assignee_id) == ("Другое", True, True, None, 100, False, None)
    assert [c.pk for c in svc().offered("category")] == [other.pk]
    sd.configure_servicedesk(domains=["corp.test"], default_queue=sd.make_queue())
    page = support.make_client().get("/request/")
    assert page.status_code == 200
    selects = dom(page).find_all("select", name="category")
    assert len(selects) == 1
    options = {o.attrs.get("value"): o.text() for o in selects[0].find_all("option")}
    assert options.get(str(other.pk)) == "Другое"


# --- общие правила: название, уникальность, удаление, архив -----------------------------------------

def test_name_required_and_unique_case_yo_and_spaces_insensitive_in_every_dictionary():
    """FR-206, FR-260, FR-269…272: в каждом из шести справочников название обязательно (`name_required`), не длиннее
    100 знаков (у `ClientUnit` — 150, `name_too_long`) и уникально по `name_key` без регистра, пробелов и «ё»
    (`name_taken`); то же название в другом справочнике допустимо; `name_key` заполняет служба."""
    actor = admin()
    queue = sd.make_queue()
    for kind in svc().KINDS:
        Model = cls(kind)
        limit = 150 if kind == "client_unit" else 100
        before = Model.objects.count()
        for blank in ("", "   ", " \t "):
            refused("name_required", svc().create, kind, name=blank, actor=actor, **extra_for(kind, queue_id=queue.unit_id))
        refused("name_too_long", svc().create, kind, name="я" * (limit + 1), actor=actor,
                **extra_for(kind, queue_id=queue.unit_id))
        assert Model.objects.count() == before
        longest = svc().create(kind, name="я" * limit, actor=actor, **extra_for(kind, queue_id=queue.unit_id))
        assert longest.name_key == "я" * limit
        first = svc().create(kind, name="  Тёмный   Ёж  ", actor=actor, **extra_for(kind, queue_id=queue.unit_id))
        assert first.name_key == support_org.name_key("Тёмный Ёж") == "темный еж"
        count = Model.objects.count()
        for clash in ("тёмный ёж", "ТЕМНЫЙ ЕЖ", "  темный   еж ", "Тёмный Ёж"):
            refused("name_taken", svc().create, kind, name=clash, actor=actor, **extra_for(kind, queue_id=queue.unit_id))
        assert Model.objects.count() == count
        other = svc().create(kind, name="Светлый Лис", actor=actor, **extra_for(kind, queue_id=queue.unit_id))
        refused("name_taken", svc().update, other, name="тёмный  ёж", actor=actor)
        refused("name_required", svc().update, other, name="  ", actor=actor)
        refused("name_too_long", svc().update, other, name="я" * (limit + 1), actor=actor)
        assert Model.objects.get(pk=other.pk).name == "Светлый Лис"
        # свою запись можно переименовать в тот же ключ (регистр, «е»/«ё»): это не другая запись
        renamed = svc().update(first, name="ТЁМНЫЙ ЕЖ", actor=actor)
        assert renamed.name == "ТЁМНЫЙ ЕЖ" and renamed.name_key == "темный еж"
    # уникальность — в пределах справочника: те же названия прошли во всех шести видах
    assert sum(cls(k).objects.filter(name_key="темный еж").count() for k in svc().KINDS) == 6
    # служба: набор видов и модель вида; неизвестный вид — KeyError
    assert tuple(svc().KINDS) == ("category", "priority", "complexity", "status", "source", "client_unit")
    assert svc().model_of("status") is cls("status")
    with pytest.raises(KeyError):
        svc().model_of("unknown")
    # встроенное значение: «Легкий» (без «ё») совпадает с начальным «Лёгкий»
    refused("name_taken", svc().create, "complexity", name="Легкий", actor=actor)


def test_delete_unused_value_passes():
    """FR-273: значение, которого нет в заявках, удаляется; журнал `sd_dictionary.deleted` с названием в `before`
    (§ 9.2); диалог и подтверждение на маршруте `/servicedesk/dictionaries/<вид>/<id>/delete/` (§ 12.6)."""
    actor = admin()
    for kind, name in (("priority", "Срочная"), ("complexity", "Сложный"), ("source", "Визит"),
                       ("status", "Ждёт запчасть"), ("category", "Печать")):
        obj = make_value(kind, name, actor)
        assert svc().is_used(obj) is False
        pk, key = obj.pk, object_id_of(kind, obj)  # до delete: Django обнуляет obj.pk
        svc().delete(obj, actor=actor, ip=IP)
        assert not cls(kind).objects.filter(pk=pk).exists()
        (event,) = audit("sd_dictionary.deleted", object_id=key)
        assert (event.object_type, event.actor_id, event.ip) == ("sd_dictionary", actor.pk, IP)
        assert event.before == {"dictionary": kind, "name": name}
        assert event.after == {}
    # маршрут: диалог ничего не меняет, без `confirm=1` — отказ, с ним — удаление и переход на список
    target = make_value("complexity", "Редкий", actor)
    client = support.logged_in(actor)
    dialog = client.get(route("complexity", target.pk, "delete"))
    assert dialog.status_code == 200
    assert dom(dialog).find_all(None, data_dialog="dictionary-delete")
    assert dom(dialog).find_all("input", type="hidden", name="confirm", value="1")
    assert cls("complexity").objects.filter(pk=target.pk).exists()
    no_confirm = client.post(route("complexity", target.pk, "delete"), {})
    assert no_confirm.status_code == 200 and dom(no_confirm).find_all(None, role="alert")
    assert cls("complexity").objects.filter(pk=target.pk).exists()
    done = client.post(route("complexity", target.pk, "delete"), {"confirm": "1"})
    assert done.status_code == 302 and done["Location"].endswith(route("complexity"))
    assert not cls("complexity").objects.filter(pk=target.pk).exists()


def test_delete_used_value_refused_with_archive_offer():
    """FR-273: значение, которое есть в заявках, не удаляется — отказ `in_use` со словом «архив» (предложение убрать
    в архив); строка и журнал не меняются; на маршруте — `[role=alert]` и кнопка архива; архив после отказа проходит."""
    actor = admin()
    queue = sd.make_queue()
    ticket_field = {"priority": "priority", "complexity": "complexity", "source": "source", "status": "status",
                    "category": "category"}
    for kind, name in (("priority", "Срочная"), ("complexity", "Сложный"), ("source", "Визит"),
                       ("status", "Ждёт запчасть"), ("category", "Печать")):
        obj = make_value(kind, name, actor, queue_id=queue.unit_id)
        sd.make_ticket(queue=queue, **{ticket_field[kind]: obj})
        assert svc().is_used(obj) is True
        error = refused("in_use", svc().delete, obj, actor=actor)
        assert "архив" in error.message.lower()
        assert cls(kind).objects.filter(pk=obj.pk).exists()
        assert audit("sd_dictionary.deleted", object_id=object_id_of(kind, obj)) == []
    used = by_name("priority", "Срочная")
    client = support.logged_in(actor)
    response = client.post(route("priority", used.pk, "delete"), {"confirm": "1"})
    assert response.status_code == 200
    assert "архив" in alert_text(response)
    assert dom(response).find_all(None, data_action="dictionary-archive")
    assert cls("priority").objects.filter(pk=used.pk).exists()
    svc().archive(used, actor=actor)
    assert cls("priority").objects.get(pk=used.pk).archived is True


def test_archived_value_not_offered_in_choice_but_shown_in_old_ticket():
    """FR-273: архивное значение не предлагается в выборе (`offered`), но в старой заявке остаётся и показано в
    карточке `/tickets/<номер>/` (`[data-field=priority|category]`)."""
    actor = admin()
    queue = sd.make_queue()
    priority = make_value("priority", "Авария", actor)
    category = make_value("category", "Сеть", actor, queue_id=queue.unit_id)
    ticket = sd.make_ticket(queue=queue, priority=priority, category=category)
    assert priority in svc().offered("priority") and category in svc().offered("category")
    svc().archive(priority, actor=actor)
    svc().archive(category, actor=actor)
    assert priority.pk not in [p.pk for p in svc().offered("priority")]
    assert category.pk not in [c.pk for c in svc().offered("category")]
    ticket = model("servicedesk.Ticket").objects.get(pk=ticket.pk)
    assert (ticket.priority_id, ticket.category_id) == (priority.pk, category.pk)
    page = support.logged_in(actor).get(f"/tickets/{ticket.number}/")
    assert page.status_code == 200
    root = dom(page)
    assert "Авария" in root.find_all(None, data_field="priority")[0].text()
    assert "Сеть" in root.find_all(None, data_field="category")[0].text()


def test_archived_value_shown_in_list_filter_with_archive_mark():
    """FR-273: архивное значение — в списке справочника с `[data-archived-mark]` «в архиве» и `data-archived="true"`,
    в фильтре `/tickets/` (`select[name=priority]`) — с пометкой «в архиве»; возврат из архива снимает метку и
    пишет `sd_dictionary.restored`; возврат не архивного — тихо ничего."""
    actor = admin()
    archived = make_value("priority", "Авария", actor)
    active = make_value("priority", "Плановая", actor)
    svc().archive(archived, actor=actor, ip=IP)
    client = support.logged_in(actor)
    rows = dict_rows(client.get(route("priority")), "priority")
    assert rows[archived.pk].attrs["data-archived"] == "true"
    assert [m.text() for m in rows[archived.pk].find_all(None, data_archived_mark=True)] == ["в архиве"]
    assert rows[active.pk].attrs["data-archived"] == "false"
    assert rows[active.pk].find_all(None, data_archived_mark=True) == []
    flt = dom(client.get("/tickets/")).find_all("form", id="tickets-filter")
    assert len(flt) == 1
    options = {o.attrs.get("value"): o.text() for o in flt[0].find_all("select", name="priority")[0].find_all("option")}
    assert "в архиве" in options[str(archived.pk)] and "Авария" in options[str(archived.pk)]
    assert "в архиве" not in options[str(active.pk)]
    (event,) = audit("sd_dictionary.archived", object_id=object_id_of("priority", archived))
    assert event.before == {}
    assert event.after == {"dictionary": "priority", "name": "Авария"} and event.ip == IP
    svc().restore(archived, actor=actor)
    assert cls("priority").objects.get(pk=archived.pk).archived is False
    (restored,) = audit("sd_dictionary.restored", object_id=object_id_of("priority", archived))
    assert restored.after == {"dictionary": "priority", "name": "Авария"}
    svc().restore(archived, actor=actor)
    assert len(audit("sd_dictionary.restored", object_id=object_id_of("priority", archived))) == 1


# --- статусы ---------------------------------------------------------------------------------------

def test_status_kind_set_on_creation_and_not_changeable():
    """FR-206: вид статуса задаётся при создании и не меняется (`update(kind=…)` — `TypeError`); новый статус не
    архивный, не системный и не по умолчанию; `is_system` и `system_code` не принимаются; журнал `created`
    с `status_kind` и `is_default` (§ 9.2)."""
    actor = admin()
    status = svc().create("status", name="Ждёт запчасть", kind="waiting", order=35, actor=actor, ip=IP)
    assert (status.kind, status.is_default, status.archived, status.system_code, status.order) == (
        "waiting", False, False, "", 35)
    with pytest.raises(TypeError):
        svc().update(status, name="Ждёт запчасть", kind="closed", actor=actor)
    with pytest.raises(TypeError):
        svc().create("status", name="Иной", kind="new", is_system=True, actor=actor)
    with pytest.raises(TypeError):
        svc().create("status", name="Иной", kind="new", system_code="autoclosed", actor=actor)
    assert cls("status").objects.get(pk=status.pk).kind == "waiting"
    assert not cls("status").objects.filter(name="Иной").exists()
    renamed = svc().update(status, name="Ждёт детали", actor=actor)
    assert renamed.kind == "waiting" and renamed.name == "Ждёт детали"
    (event,) = audit("sd_dictionary.created", object_id=object_id_of("status", status))
    assert event.object_type == "sd_dictionary" and event.actor_id == actor.pk and event.ip == IP
    assert event.before == {}
    assert event.after["dictionary"] == "status" and event.after["name"] == "Ждёт запчасть"
    assert event.after["order"] == 35 and event.after["status_kind"] == "waiting"
    assert event.after["is_default"] is False


def test_new_status_of_in_work_kind_treated_as_in_work_and_offered_for_manual_change():
    """FR-206, FR-209: новый статус вида «в работе» — в списке ручной смены (`manual_statuses`, по `order`), не в
    форме закрытия; заявка с ним остаётся открытой и видна в карточке в `select[name=status]` (§ 13.3); смена на него
    службой `tickets.set_status_manual` проходит; статусы видов `new` и `closed` в ручную смену не попадают."""
    actor = admin()
    queue = sd.make_queue()
    parts = svc().create("status", name="Ждёт запчасть", kind="in_progress", order=25, actor=actor)
    svc().create("status", name="Новая особая", kind="new", order=5, actor=actor)
    svc().create("status", name="Решена особо", kind="closed", order=45, actor=actor)
    names = [s.name for s in svc().manual_statuses()]
    assert names == ["В работе", "Ждёт запчасть", "Ждёт ответа заявителя"]
    assert parts.pk not in [s.pk for s in svc().closing_statuses()]
    ticket = sd.make_ticket(queue=queue, kind="in_progress", status=svc().default_status("in_progress"))
    page = support.logged_in(actor).get(f"/tickets/{ticket.number}/")
    forms = dom(page).find_all("form", data_form="ticket-status")
    assert len(forms) == 1
    options = {o.attrs.get("value"): o.text() for o in forms[0].find_all("select", name="status")[0].find_all("option")}
    assert options.get(str(parts.pk)) == "Ждёт запчасть"
    tickets_service = importlib.import_module("apps.servicedesk.services.tickets")
    tickets_service.set_status_manual(ticket, parts, actor=actor)
    ticket = model("servicedesk.Ticket").objects.get(pk=ticket.pk)
    assert (ticket.status_id, ticket.kind) == (parts.pk, "in_progress")


def test_default_mark_moves_within_kind_in_one_transaction():
    """FR-206: отметка «по умолчанию» переносится внутри вида в одной транзакции (откат вызывающей транзакции
    возвращает обе отметки); `is_default=False` у отмеченного не снимает отметку; ограничение базы — один
    `is_default` на вид; другие виды не затрагиваются; журнал `updated` с «было/стало» по «по умолчанию»."""
    actor = admin()
    solved = by_name("status", "Решена")
    cannot = by_name("status", "Не может быть решена")
    assert solved.is_default and not cannot.is_default

    class Boom(Exception):
        pass

    with pytest.raises(Boom):
        with transaction.atomic():
            svc().update(cannot, name=cannot.name, is_default=True, actor=actor)
            raise Boom
    assert [s.name for s in cls("status").objects.filter(kind="closed", is_default=True)] == ["Решена"]

    cannot = cls("status").objects.get(pk=cannot.pk)
    svc().update(cannot, name=cannot.name, is_default=True, actor=actor, ip=IP)
    assert [s.name for s in cls("status").objects.filter(kind="closed", is_default=True)] == ["Не может быть решена"]
    assert svc().default_status("closed").pk == cannot.pk
    assert cls("status").objects.get(name="Новая").is_default is True
    assert cls("status").objects.get(name="В работе").is_default is True
    updated = audit("sd_dictionary.updated", object_id=object_id_of("status", cannot))
    assert len(updated) == 1
    assert updated[0].before.get("is_default") is False and updated[0].after.get("is_default") is True
    assert updated[0].after.get("dictionary") == "status" and updated[0].after.get("name") == "Не может быть решена"
    # дополнение 4: во всём журнале ровно одно событие (откат попытки с Boom журнал тоже откатил),
    # у статуса, потерявшего отметку, событий нет
    assert len(audit("sd_dictionary.updated")) == 1
    assert audit(object_id=object_id_of("status", solved)) == []
    # снять отметку, не отметив другой, нельзя: отметка остаётся
    svc().update(cls("status").objects.get(pk=cannot.pk), name=cannot.name, is_default=False, actor=actor)
    assert cls("status").objects.get(pk=cannot.pk).is_default is True
    # без изменений журнал не пишется
    count = len(audit(prefix="sd_dictionary."))
    svc().update(cls("status").objects.get(pk=cannot.pk), name=cannot.name, actor=actor)
    assert len(audit(prefix="sd_dictionary.")) == count
    # второй рубеж — ограничение базы
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            cls("status").objects.filter(pk=solved.pk).update(is_default=True)


def test_default_status_cannot_be_archived_or_deleted():
    """FR-206: статус по умолчанию своего вида (вид `closed`, где действующих статусов несколько) нельзя убрать в
    архив и удалить — `default_protected`; маршрут архива отвечает 200 со списком и `[role=alert]`."""
    actor = admin()
    solved = by_name("status", "Решена")
    assert solved.is_default
    refused("default_protected", svc().archive, solved, actor=actor)
    refused("default_protected", svc().delete, solved, actor=actor)
    assert cls("status").objects.get(pk=solved.pk).archived is False
    response = support.logged_in(actor).post(route("status", solved.pk, "archive"), {})
    assert response.status_code == 200 and dom(response).find_all(None, role="alert")
    assert cls("status").objects.get(pk=solved.pk).archived is False
    assert audit("sd_dictionary.archived") == [] and audit("sd_dictionary.deleted") == []


def test_last_active_status_of_kind_cannot_be_archived():
    """FR-206: единственный действующий статус вида (он же по умолчанию) — `last_active` раньше `default_protected`
    и при архиве, и при удалении; если другой действующий статус вида есть, архив проходит; последний после этого
    снова защищён; маршрут — 200 с `[role=alert]`."""
    actor = admin()
    new = by_name("status", "Новая")
    refused("last_active", svc().archive, new, actor=actor)
    refused("last_active", svc().delete, new, actor=actor)
    response = support.logged_in(actor).post(route("status", new.pk, "archive"), {})
    assert response.status_code == 200 and dom(response).find_all(None, role="alert")
    assert cls("status").objects.get(pk=new.pk).archived is False
    # вид `in_progress`: второй статус отмечаем по умолчанию, прежний (не отмеченный теперь) уходит в архив
    working = by_name("status", "В работе")
    extra = svc().create("status", name="Ждёт запчасть", kind="in_progress", actor=actor)
    svc().update(extra, name=extra.name, is_default=True, actor=actor)
    svc().archive(cls("status").objects.get(pk=working.pk), actor=actor)
    assert cls("status").objects.get(pk=working.pk).archived is True
    last = cls("status").objects.get(pk=extra.pk)
    assert last.is_default
    refused("last_active", svc().archive, last, actor=actor)
    refused("last_active", svc().delete, last, actor=actor)
    assert cls("status").objects.get(pk=extra.pk).archived is False


def test_system_auto_closed_status_renamed_but_not_archived_or_deleted_and_any_status_renamable():
    """FR-206: системный «Закрыта автоматически» переименовывается (код `autoclosed` остаётся), но в архив и под
    удаление не идёт — `system_protected`; переименовать можно любой статус; в списке — `[data-system-mark]`
    «системное»; маршрут правки — 302, архива — 200 с `[role=alert]`."""
    actor = admin()
    auto = cls("status").objects.get(system_code="autoclosed")
    refused("system_protected", svc().archive, auto, actor=actor)
    refused("system_protected", svc().delete, auto, actor=actor)
    renamed = svc().update(auto, name="Закрыта по сроку", actor=actor, ip=IP)
    assert renamed.name == "Закрыта по сроку" and renamed.system_code == "autoclosed" and renamed.kind == "closed"
    (event,) = audit("sd_dictionary.updated", object_id=object_id_of("status", auto))
    assert event.before["name"] == "Закрыта автоматически" and event.after["name"] == "Закрыта по сроку"
    for status in cls("status").objects.exclude(pk=auto.pk):
        old = status.name
        svc().update(status, name=f"{old} (новое)", actor=actor)
        assert cls("status").objects.get(pk=status.pk).name == f"{old} (новое)"
    client = support.logged_in(actor)
    edit = client.post(route("status", auto.pk, "edit"), {"name": "Закрыта сама", "order": "60"})
    assert edit.status_code == 302
    assert cls("status").objects.get(pk=auto.pk).name == "Закрыта сама"
    row = dict_rows(client.get(route("status")), "status")[auto.pk]
    assert [m.text() for m in row.find_all(None, data_system_mark=True)] == ["системное"]
    blocked = client.post(route("status", auto.pk, "archive"), {})
    assert blocked.status_code == 200 and dom(blocked).find_all(None, role="alert")
    assert cls("status").objects.get(pk=auto.pk).archived is False


# --- источники и категории -------------------------------------------------------------------------

def test_system_sources_mail_and_form_not_in_manual_choice_not_archived_not_deleted_but_renamable():
    """FR-272: системные «Почта» и «Форма» не в ручном выборе (`manual_sources`), не архивируются и не удаляются
    (`system_protected`), но переименовываются (`system_code` остаётся); новый ручной источник — в ручном выборе,
    архивный — нет."""
    actor = admin()
    assert [s.name for s in svc().manual_sources()] == ["Телефон", "Лично"]
    for code, name in (("mail", "Почта"), ("form", "Форма")):
        source = cls("source").objects.get(system_code=code)
        assert source.name == name
        refused("system_protected", svc().archive, source, actor=actor)
        refused("system_protected", svc().delete, source, actor=actor)
        renamed = svc().update(source, name=f"{name} портала", actor=actor)
        assert renamed.system_code == code and renamed.archived is False
        assert cls("source").objects.get(pk=source.pk).name == f"{name} портала"
    visit = svc().create("source", name="Визит", order=50, actor=actor)
    assert visit.system_code == ""
    assert [s.name for s in svc().manual_sources()] == ["Телефон", "Лично", "Визит"]
    svc().archive(visit, actor=actor)
    assert [s.name for s in svc().manual_sources()] == ["Телефон", "Лично"]
    assert {s.system_code for s in svc().offered("source")} == {"mail", "form", ""}
    with pytest.raises(TypeError):
        svc().create("source", name="Иной", system_code="mail", actor=actor)


def test_category_other_not_deleted_not_archived_and_has_no_own_queue():
    """FR-269: «Другое» не удаляется и не архивируется (`system_protected`), переименовывается, своей очереди не
    имеет и очередь ей не задаётся (`queue_id` не принимается — `TypeError`, допущение: § 6.5 говорит «не
    принимается»); создать системную категорию через `create` нельзя; категория без очереди — `queue_not_marked`."""
    actor = admin()
    other = cls("category").objects.get(is_system=True)
    refused("system_protected", svc().archive, other, actor=actor)
    refused("system_protected", svc().delete, other, actor=actor)
    queue = sd.make_queue()
    with pytest.raises(TypeError):
        svc().update(other, name="Другое", queue_id=queue.unit_id, actor=actor)
    renamed = svc().update(other, name="Прочее", actor=actor)
    assert renamed.name == "Прочее"
    other = cls("category").objects.get(pk=other.pk)
    assert (other.queue_id, other.is_system, other.archived, other.on_form) == (None, True, False, True)
    with pytest.raises(TypeError):
        svc().create("category", name="Своя системная", queue_id=queue.unit_id, is_system=True, actor=actor)
    refused("queue_not_marked", svc().create, "category", name="Без очереди", queue_id=None, actor=actor)
    assert cls("category").objects.filter(is_system=True).count() == 1


def test_category_queue_only_marked_unit():
    """FR-269: очередью категории может быть только отмеченный узел (`queue_not_marked` для неотмеченного узла и
    `None`, при создании и при правке); отказ ничего не пишет; маршруты `new/` — 200 с `[role=alert]` и 302."""
    actor = admin()
    queue = sd.make_queue()
    plain_unit = support_org.make_unit()
    before = cls("category").objects.count()
    refused("queue_not_marked", svc().create, "category", name="Печать", queue_id=plain_unit.pk, actor=actor)
    refused("queue_not_marked", svc().create, "category", name="Печать", queue_id=None, actor=actor)
    assert cls("category").objects.count() == before
    category = svc().create("category", name="Печать", queue_id=queue.unit_id, actor=actor, ip=IP)
    assert category.queue_id == queue.unit_id and category.is_system is False
    other_queue = sd.make_queue()
    refused("queue_not_marked", svc().update, category, name="Печать", queue_id=plain_unit.pk, actor=actor)
    assert cls("category").objects.get(pk=category.pk).queue_id == queue.unit_id
    moved = svc().update(category, name="Печать", queue_id=other_queue.unit_id, actor=actor)
    assert moved.queue_id == other_queue.unit_id
    client = support.logged_in(actor)
    bad = client.post(route("category", "new"), {"name": "Сканеры", "order": "5", "queue": str(plain_unit.pk),
                                                  "default_assignee": ""})
    assert bad.status_code == 200 and dom(bad).find_all(None, role="alert")
    assert not cls("category").objects.filter(name="Сканеры").exists()
    good = client.post(route("category", "new"), {"name": "Сканеры", "order": "5", "queue": str(queue.unit_id),
                                                   "default_assignee": "", "on_form": "1"})
    assert good.status_code == 302 and good["Location"].endswith(route("category"))
    scanners = cls("category").objects.get(name="Сканеры")
    assert (scanners.queue_id, scanners.on_form) == (queue.unit_id, True)


def test_category_default_assignee_only_queue_participant_else_refused():
    """FR-269: ответственный по умолчанию — только участник очереди категории на момент сохранения
    (`assignee_not_participant`, при создании и правке; сценарий 9.4); участник и держатель `servicedesk.all`
    принимаются; пустой ответственный допустим; маршрут `new/` — 200 с `[role=alert]` и 302; журнал несёт имя."""
    actor = admin()
    queue = sd.make_queue()
    member = support.make_employee(full_name="Участник Очереди")
    outsider = support.make_employee(full_name="Посторонний Человек")
    support_org.make_member(member, queue.unit)
    holder = support.make_with_permissions("servicedesk.all", full_name="Держатель Всех")
    before = cls("category").objects.count()
    refused("assignee_not_participant", svc().create, "category", name="Печать", queue_id=queue.unit_id,
            default_assignee=outsider, actor=actor)
    assert cls("category").objects.count() == before
    category = svc().create("category", name="Печать", queue_id=queue.unit_id, default_assignee=member, on_form=True,
                            actor=actor)
    assert category.default_assignee_id == member.pk
    (created,) = audit("sd_dictionary.created", object_id=object_id_of("category", category))
    assert created.after["default_assignee"] == "Участник Очереди" and created.after["on_form"] is True
    assert created.after["dictionary"] == "category" and created.after["name"] == "Печать"
    refused("assignee_not_participant", svc().update, category, name="Печать", default_assignee=outsider, actor=actor)
    assert cls("category").objects.get(pk=category.pk).default_assignee_id == member.pk
    accepted = svc().update(category, name="Печать", default_assignee=holder, actor=actor)
    assert accepted.default_assignee_id == holder.pk
    cleared = svc().update(accepted, name="Печать", default_assignee=None, actor=actor)
    assert cls("category").objects.get(pk=cleared.pk).default_assignee_id is None
    client = support.logged_in(actor)
    bad = client.post(route("category", "new"), {"name": "Сканеры", "order": "5", "queue": str(queue.unit_id),
                                                  "default_assignee": str(outsider.pk)})
    assert bad.status_code == 200 and dom(bad).find_all(None, role="alert")
    assert not cls("category").objects.filter(name="Сканеры").exists()
    good = client.post(route("category", "new"), {"name": "Сканеры", "order": "5", "queue": str(queue.unit_id),
                                                   "default_assignee": str(member.pk)})
    assert good.status_code == 302
    assert cls("category").objects.get(name="Сканеры").default_assignee_id == member.pk


def test_default_criticality_cannot_be_archived_or_deleted():
    """FR-270: критичность по умолчанию (поле настроек) нельзя убрать в архив и удалить — `default_protected`, и она
    считается «используемой» (`is_used`); после смены критичности по умолчанию прежнюю можно, новую — нельзя."""
    actor = admin()
    medium = by_name("priority", "Средняя")
    high = by_name("priority", "Высокая")
    assert svc().is_used(medium) is True and svc().is_used(high) is False
    refused("default_protected", svc().archive, medium, actor=actor)
    refused("default_protected", svc().delete, medium, actor=actor)
    assert cls("priority").objects.get(pk=medium.pk).archived is False
    sd.configure_servicedesk(default_priority=high)
    refused("default_protected", svc().archive, high, actor=actor)
    refused("default_protected", svc().delete, high, actor=actor)
    assert svc().is_used(medium) is False
    svc().archive(medium, actor=actor)
    assert cls("priority").objects.get(pk=medium.pk).archived is True
    pk = medium.pk  # до delete: Django обнуляет pk
    svc().delete(medium, actor=actor)
    assert not cls("priority").objects.filter(pk=pk).exists()


# --- подразделения-клиенты --------------------------------------------------------------------------

def test_client_units_unique_without_case_archived_not_offered_flat_list():
    """FR-260: подразделения-клиенты уникальны по `name_key` (регистр, «ё», пробелы), в том числе против архивных;
    архивные не предлагаются; список плоский, по названию, без `order` (ни поля, ни ячейки `order`)."""
    actor = admin()
    assert cls("client_unit").objects.count() == 0
    assert "order" not in [f.name for f in cls("client_unit")._meta.get_fields()]
    for name in ("Гамма", "Алфа", "Бета"):
        svc().create("client_unit", name=name, actor=actor)
    elka = svc().create("client_unit", name="Отдел Ёлка", actor=actor)
    for clash in ("отдел елка", "  ОТДЕЛ   ЕЛКА ", "Отдел Ёлка"):
        refused("name_taken", svc().create, "client_unit", name=clash, actor=actor)
    svc().archive(elka, actor=actor)
    refused("name_taken", svc().create, "client_unit", name="отдел елка", actor=actor)
    assert [u.name for u in svc().offered("client_unit")] == ["Алфа", "Бета", "Гамма"]
    page = support.logged_in(actor).get(route("client_unit"))
    assert page.status_code == 200
    table = dom(page).find_all("table", data_dictionary="client_unit")
    assert len(table) == 1 and table[0].find_all(None, data_cell="order") == []
    rows = dict_rows(page, "client_unit")
    assert rows[elka.pk].attrs["data-archived"] == "true"
    assert [m.text() for m in rows[elka.pk].find_all(None, data_archived_mark=True)] == ["в архиве"]
    assert len(rows) == 4


def test_client_unit_delete_only_when_unused_by_tickets_and_requester_records():
    """FR-260, FR-273: подразделение-клиент удаляется, только если его нет ни в заявках, ни в записях заявителей;
    иначе `in_use` со словом «архив»; `is_used` проверяет оба источника; журнал `client_unit.deleted`."""
    actor = admin()
    queue = sd.make_queue()
    in_ticket = svc().create("client_unit", name="В заявке", actor=actor)
    in_record = svc().create("client_unit", name="В записи заявителя", actor=actor)
    free = svc().create("client_unit", name="Свободное", actor=actor)
    sd.make_ticket(queue=queue, client_unit=in_ticket)
    sd.make_requester(client_unit=in_record)
    assert (svc().is_used(in_ticket), svc().is_used(in_record), svc().is_used(free)) == (True, True, False)
    for used in (in_ticket, in_record):
        error = refused("in_use", svc().delete, used, actor=actor)
        assert "архив" in error.message.lower()
        assert cls("client_unit").objects.filter(pk=used.pk).exists()
    pk, key = free.pk, object_id_of("client_unit", free)  # до delete: Django обнуляет pk
    svc().delete(free, actor=actor, ip=IP)
    assert not cls("client_unit").objects.filter(pk=pk).exists()
    (event,) = audit("client_unit.deleted", object_id=key)
    assert event.object_type == "sd_dictionary" and event.before == {"name": "Свободное"} and event.after == {}
    svc().archive(in_record, actor=actor)
    assert cls("client_unit").objects.get(pk=in_record.pk).archived is True


def test_client_unit_add_rename_archive_journaled():
    """FR-260: добавление, переименование, архив, возврат и удаление подразделения-клиента пишут события
    `client_unit.*` (`object_type="sd_dictionary"`, `object_id="client-units:<id>"`, § 9.2); переименование без
    изменений ничего не пишет."""
    actor = admin()
    unit = svc().create("client_unit", name="Бухгалтерия", actor=actor, ip=IP)
    key = object_id_of("client_unit", unit)
    assert key == f"client-units:{unit.pk}"
    (created,) = audit("client_unit.created", object_id=key)
    assert (created.object_type, created.actor_id, created.ip) == ("sd_dictionary", actor.pk, IP)
    assert created.before == {} and created.after == {"name": "Бухгалтерия"}
    svc().update(unit, name="Бухгалтерия", actor=actor)
    assert audit("client_unit.updated", object_id=key) == []
    svc().update(unit, name="Финансы", actor=actor, ip=IP)
    (updated,) = audit("client_unit.updated", object_id=key)
    assert updated.before == {"name": "Бухгалтерия"} and updated.after == {"name": "Финансы"}
    assert updated.object_type == "sd_dictionary" and updated.actor_id == actor.pk
    svc().archive(unit, actor=actor)
    (archived,) = audit("client_unit.archived", object_id=key)
    assert archived.before == {} and archived.after == {"name": "Финансы"}
    svc().restore(unit, actor=actor)
    (restored,) = audit("client_unit.restored", object_id=key)
    assert restored.before == {} and restored.after == {"name": "Финансы"}
    svc().delete(unit, actor=actor)
    (deleted,) = audit("client_unit.deleted", object_id=key)
    assert deleted.before == {"name": "Финансы"} and deleted.after == {}
    assert audit(prefix="sd_dictionary.") == []
