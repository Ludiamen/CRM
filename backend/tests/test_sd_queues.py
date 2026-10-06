"""T-3102: очереди и настройки сервис-деска (FR-213, FR-221, FR-225, FR-231, FR-250, FR-251, FR-274, FR-275,
FR-290). Сценарии 9 и 10 спеки среза 003.

Службы `queues`, `settings`, `dictionaries` и удаление узла `org` (точка `unit_usage`) вызываются настоящими
функциями (CONTRACT-003 §§ 3.2, 4, 6.4, 6.5, 6.6); страницы — по путям § 12.6 и зацепкам § 13.7. Имена кода среза
003 импортируются внутри тестов: сбор проходит до появления кода.
"""
import json
import re
from html import unescape
from html.parser import HTMLParser

import pytest

from tests import factories, support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

CORP = "corp.test"
MAILBOX = "zayavki@portal.test"
IP = "198.51.100.88"

REASON_TICKETS = "к узлу привязаны заявки сервис-деска"
REASON_QUEUE = "узел — очередь сервис-деска: сначала снимите отметку"


# --- помощники файла --------------------------------------------------------------------------------

def _events(action: str) -> list:
    return list(model("core.AuditEvent").objects.filter(action=action).order_by("id"))


def _default_queue(domains=(CORP,)):
    """Очередь по умолчанию и домены (через ORM, без журнала); возвращает узел."""
    queue = sd.make_queue()
    sd.configure_servicedesk(domains=list(domains), default_queue=queue)
    return queue.unit


def _tag(html: str, name: str, attr: str) -> str:
    """Первый открывающий тег `<name ... attr ...>` целиком или пустая строка."""
    found = re.search(rf"<{name}\b[^>]*{re.escape(attr)}[^>]*>", html)
    return found.group(0) if found else ""


def _inner(html: str, attr: str) -> str | None:
    """Содержимое первого элемента с атрибутом `attr` (элементы без вложенных одноимённых тегов)."""
    found = re.search(rf"<(\w+)\b[^>]*{re.escape(attr)}[^>]*>(.*?)</\1>", html, re.S)
    return " ".join(unescape(re.sub("<[^>]+>", " ", found.group(2))).split()) if found else None


def _window(html: str, attr: str, size: int = 1500) -> str:
    """Текст страницы от первого вхождения `attr` на `size` знаков (для элементов с вложенной разметкой)."""
    start = html.find(attr)
    if start < 0:
        return ""
    return " ".join(unescape(re.sub("<[^>]+>", " ", html[start:start + size])).split())


class _Element(HTMLParser):
    """Первый элемент с атрибутом `attr` (подстрока открывающего тега): текст вне вложенных элементов с атрибутом `skip`
    и ссылки `href` всех вложенных `<a>`."""

    def __init__(self, attr: str, skip: str = ""):
        super().__init__()
        self.attr, self.skip = attr, skip
        self.name = None      # имя тега найденного элемента
        self.depth = 0        # вложенность одноимённых тегов внутри найденного
        self.skip_name, self.skip_depth = None, 0
        self.found, self.done = False, False
        self.chunks, self.hrefs = [], []

    def handle_starttag(self, tag, attrs):
        if self.done:
            return
        raw = " ".join(k if v is None else f'{k}="{v}"' for k, v in attrs)
        if not self.found:
            if self.attr in raw:
                self.found, self.name, self.depth = True, tag, 1
            return
        if tag == self.name:
            self.depth += 1
        if self.skip_name:
            if tag == self.skip_name:
                self.skip_depth += 1
        elif self.skip and self.skip in raw:
            self.skip_name, self.skip_depth = tag, 1
        if tag == "a" and dict(attrs).get("href"):
            self.hrefs.append(dict(attrs)["href"])

    def handle_endtag(self, tag):
        if self.done or not self.found:
            return
        if self.skip_name and tag == self.skip_name:
            self.skip_depth -= 1
            if self.skip_depth == 0:
                self.skip_name = None
        if tag == self.name:
            self.depth -= 1
            if self.depth == 0:
                self.done = True

    def handle_data(self, data):
        if self.found and not self.done and not self.skip_name:
            self.chunks.append(data)


def _element(html: str, attr: str, skip: str = ""):
    """Разбор HTML: (текст элемента с атрибутом `attr` без вложенных `skip`, ссылки `href` внутри него)."""
    parser = _Element(attr, skip)
    parser.feed(html)
    parser.close()
    return " ".join(unescape(" ".join(parser.chunks)).split()), parser.hrefs


def _has_alert(html: str) -> bool:
    return 'role="alert"' in html or "role='alert'" in html


def _settings_form(**over) -> dict:
    data = {
        "domains": CORP, "default_priority": model("servicedesk.Priority").objects.get(name="Средняя").pk,
        "autoclose_days": 7, "reopen_days": 7, "form_hourly_limit": 10, "retention_years": 3,
        "inbound_retention_days": 30,
    }
    data.update(over)
    return data


def _inbound_mail(protected_root, *, from_addr: str, subject: str = "Не работает принтер", **over):
    """Строка входящего письма и его файл `protected/inbound/<id>.eml` (его читает разбор)."""
    raw = sd.build_mail(from_addr=from_addr, to=[MAILBOX], subject=subject, text="Помогите, пожалуйста.")
    row = sd.make_inbound(from_email=from_addr, subject=subject, size=len(raw), **over)
    folder = protected_root / "inbound"
    folder.mkdir(exist_ok=True)
    (folder / f"{row.pk}.eml").write_bytes(raw)
    return row


def is_russian(text: str, code: str) -> bool:
    return text != code and bool(re.search("[А-Яа-яЁё]", text))


# --- отметка очереди (FR-231) -----------------------------------------------------------------------

def test_mark_any_unit_as_queue_writes_journal_event():
    """FR-231: отметить очередью можно любой узел (отдел, команда, вложенный); журнал `queue.marked` с узлом после,
    повторная отметка — `already_queue`; `queues.is_queue` и `marked_units` видят отметку."""
    from apps.servicedesk.services import ServiceDeskError, queues

    admin = support.make_admin()
    department = org.make_unit(kind="department")
    team = org.make_unit(kind="team", parent=department)
    org.make_member(support.make_employee(), team)  # узел с участником — тоже годится
    assert not queues.is_queue(department.pk)
    for unit in (department, team):
        queue = queues.mark(unit.pk, actor=admin, ip=IP)
        assert queue.unit_id == unit.pk
        assert queues.is_queue(unit.pk)
        event = _events("queue.marked")[-1]
        assert (event.object_type, event.object_id, event.actor_id) == ("queue", str(unit.pk), admin.pk)
        assert event.before == {} and event.after == {"unit": unit.name, "unit_id": unit.pk}
    assert {u.id for u in queues.marked_units()} == {department.pk, team.pk}
    assert model("servicedesk.Queue").objects.count() == 2
    with pytest.raises(ServiceDeskError) as refused:
        queues.mark(team.pk, actor=admin)
    assert refused.value.code == "already_queue"
    assert len(_events("queue.marked")) == 2 and model("servicedesk.Queue").objects.count() == 2


def test_unmark_queue_with_open_tickets_refused_with_reason():
    """FR-231, сценарий 9.3: открытые заявки видов «новая», «в работе», «ждёт ответа заявителя» не дают снять отметку:
    `queue_has_open_tickets`, отметка и заявки на месте, события нет."""
    from apps.servicedesk.services import ServiceDeskError, queues

    admin = support.make_admin()
    _default_queue()
    for kind in ("new", "in_progress", "waiting"):
        queue = sd.make_queue()
        ticket = sd.make_ticket(queue=queue, kind=kind)
        with pytest.raises(ServiceDeskError) as refused:
            queues.unmark(queue.unit_id, actor=admin)
        assert refused.value.code == "queue_has_open_tickets", kind
        assert refused.value.message
        assert queues.is_queue(queue.unit_id)
        assert model("servicedesk.Ticket").objects.get(pk=ticket.pk).queue_id == queue.unit_id
    assert _events("queue.unmarked") == []


def test_unmark_queue_without_open_tickets_passes():
    """FR-231, сценарий 9.3: у очереди без заявок отметка снимается; журнал `queue.unmarked` с узлом до; узел остаётся."""
    from apps.servicedesk.services import queues

    admin = support.make_admin()
    _default_queue()
    queue = sd.make_queue()
    moved = queues.unmark(queue.unit_id, actor=admin, ip=IP)
    assert moved == []
    assert not queues.is_queue(queue.unit_id)
    assert not model("servicedesk.Queue").objects.filter(unit_id=queue.unit_id).exists()
    assert model("org.Unit").objects.filter(pk=queue.unit_id).exists()
    event = _events("queue.unmarked")[-1]
    assert (event.object_type, event.object_id, event.actor_id) == ("queue", str(queue.unit_id), admin.pk)
    assert event.before == {"unit": queue.unit.name, "unit_id": queue.unit_id} and event.after == {}


def test_unmark_queue_with_only_closed_tickets_passes_and_reopen_goes_to_default_queue(django_capture_on_commit_callbacks):
    """FR-231 (FR-251, FR-252): закрытые заявки снятию не мешают и остаются в узле; открытая заново уходит в очередь по
    умолчанию, в ленте событие «очередь: было → стало» с причиной `queue_unmarked`."""
    from django.utils import timezone

    from apps.servicedesk.services import closing, queues

    admin = support.make_admin()
    default = _default_queue()
    queue = sd.make_queue()
    ticket = sd.make_ticket(queue=queue, kind="closed", closed_at=timezone.now())
    queues.unmark(queue.unit_id, actor=admin)
    ticket = model("servicedesk.Ticket").objects.get(pk=ticket.pk)
    assert ticket.queue_id == queue.unit_id and ticket.kind == "closed"
    with django_capture_on_commit_callbacks(execute=True):
        closing.reopen(ticket, actor=admin)
    ticket = model("servicedesk.Ticket").objects.get(pk=ticket.pk)
    assert ticket.queue_id == default.pk and ticket.kind == "in_progress"
    changes = list(ticket.entries.filter(kind="event", event="queue_changed"))
    assert len(changes) == 1
    data = changes[0].data
    assert (data["from_id"], data["to_id"], data["reason"]) == (queue.unit_id, default.pk, "queue_unmarked")
    assert data["from"] == queue.unit.name and data["to"] == default.name


def test_unmark_moves_categories_to_default_queue_and_clears_non_participant_default_assignee():
    """FR-231: категории снимаемой очереди переходят в очередь по умолчанию, ответственный по умолчанию, не участник
    очереди по умолчанию, снимается; журнал `sd_dictionary.updated` на каждую категорию (только изменённое); чужие
    категории и «Другое» не тронуты."""
    from apps.servicedesk.services import queues

    admin = support.make_admin()
    default = _default_queue()
    queue = sd.make_queue()
    assignee = support.make_employee()
    org.make_member(assignee, queue.unit)
    with_assignee = sd.make_category(queue=queue, default_assignee=assignee)
    without = sd.make_category(queue=queue)
    elsewhere = sd.make_category(queue=sd.make_queue())
    other = model("servicedesk.Category").objects.get(is_system=True)

    moved = queues.unmark(queue.unit_id, actor=admin)
    assert {c.pk for c in moved} == {with_assignee.pk, without.pk}
    Category = model("servicedesk.Category")
    first = Category.objects.get(pk=with_assignee.pk)
    assert first.queue_id == default.pk and first.default_assignee_id is None
    assert Category.objects.get(pk=without.pk).queue_id == default.pk
    assert Category.objects.get(pk=elsewhere.pk).queue_id == elsewhere.queue_id
    assert Category.objects.get(pk=other.pk).queue_id is None

    updated = {e.object_id: e for e in _events("sd_dictionary.updated")}
    assert set(updated) == {f"categories:{with_assignee.pk}", f"categories:{without.pk}"}
    event = updated[f"categories:{with_assignee.pk}"]
    assert event.object_type == "sd_dictionary" and event.actor_id == admin.pk
    assert event.before == {"queue": queue.unit.name, "default_assignee": assignee.full_name}
    assert event.after == {"dictionary": "category", "name": with_assignee.name, "queue": default.name,
                           "default_assignee": ""}
    assert updated[f"categories:{without.pk}"].before == {"queue": queue.unit.name}
    assert len(_events("queue.unmarked")) == 1


def test_unmark_keeps_default_assignee_who_participates_in_default_queue():
    """FR-231: ответственный по умолчанию, который участник и очереди по умолчанию, у категории остаётся."""
    from apps.servicedesk.services import queues

    admin = support.make_admin()
    default = _default_queue()
    queue = sd.make_queue()
    both = support.make_employee()
    org.make_member(both, queue.unit)
    org.make_member(both, default)  # совместитель
    category = sd.make_category(queue=queue, default_assignee=both)
    queues.unmark(queue.unit_id, actor=admin)
    category = model("servicedesk.Category").objects.get(pk=category.pk)
    assert category.queue_id == default.pk and category.default_assignee_id == both.pk
    event = _events("sd_dictionary.updated")[-1]
    assert event.before == {"queue": queue.unit.name} and event.after["queue"] == default.name
    assert "default_assignee" not in event.after or event.after["default_assignee"] == both.full_name


def test_unmark_dialog_names_affected_categories_and_journal_gets_update_per_category():
    """FR-231, сценарий 9.3: `unmark_preview` и диалог `/servicedesk/queues/?unmark=<id>` называют число открытых заявок и
    категории, которые перейдут в очередь по умолчанию (по одному `[data-consequence]`), ничего не меняя; снятие без
    `confirm=1` — отказ; с ним — `queue.unmarked` и `sd_dictionary.updated` на каждую категорию."""
    from apps.servicedesk.services import ServiceDeskError, queues

    admin = support.make_admin()
    _default_queue()
    busy = sd.make_queue()
    for _ in range(7):
        sd.make_ticket(queue=busy, kind="new")
    sd.make_category(queue=busy)
    free = sd.make_queue()
    cats = [sd.make_category(queue=free, order=1), sd.make_category(queue=free, order=2)]

    preview = queues.unmark_preview(busy.unit_id)
    assert preview.open_tickets == 7 and len(preview.categories) == 1
    preview = queues.unmark_preview(free.unit_id)
    assert preview.open_tickets == 0 and [c.pk for c in preview.categories] == [c.pk for c in cats]
    with pytest.raises(ServiceDeskError) as refused:
        queues.unmark_preview(org.make_unit().pk)
    assert refused.value.code == "not_queue"

    client = support.logged_in(admin, ip=IP)
    page = client.get(f"/servicedesk/queues/?unmark={busy.unit_id}")
    html = page.content.decode()
    assert page.status_code == 200 and 'data-dialog="queue-unmark"' in html
    dialog, _ = _element(html, 'data-dialog="queue-unmark"', skip="data-consequence")
    for name in [busy.unit.name, *model("servicedesk.Category").objects.filter(queue_id=busy.unit_id).values_list("name", flat=True)]:
        dialog = dialog.replace(name, " ")
    assert re.search(r"(?<![\w-])7(?![\w-])", dialog), dialog
    assert len(re.findall(r"data-consequence", html)) == 1
    fragment = client.get(f"/servicedesk/queues/?unmark={free.unit_id}", **support.HX).content.decode()
    assert 'data-dialog="queue-unmark"' in fragment and "<html" not in fragment.lower()
    assert len(re.findall(r"data-consequence", fragment)) == 2
    assert all(c.name in fragment for c in cats)
    free_text, _ = _element(fragment, 'data-dialog="queue-unmark"', skip="data-consequence")
    for name in [free.unit.name, *(c.name for c in cats)]:
        free_text = free_text.replace(name, " ")
    assert not re.search(r"(?<![\w-])7(?![\w-])", free_text), free_text
    hidden = _tag(fragment, "input", 'name="confirm"')
    assert 'type="hidden"' in hidden and 'value="1"' in hidden
    assert queues.is_queue(free.unit_id) and _events("queue.unmarked") == []
    assert client.get(f"/servicedesk/queues/?unmark={org.make_unit().pk}").status_code == 404

    without_confirm = client.post("/servicedesk/queues/", {"action": "unmark", "unit": free.unit_id})
    assert without_confirm.status_code == 200 and _has_alert(without_confirm.content.decode())
    assert queues.is_queue(free.unit_id)
    done = client.post("/servicedesk/queues/", {"action": "unmark", "unit": free.unit_id, "confirm": "1"})
    assert done.status_code == 302 and done["Location"].endswith("/servicedesk/queues/")
    assert not queues.is_queue(free.unit_id)
    assert len(_events("queue.unmarked")) == 1
    assert {e.object_id for e in _events("sd_dictionary.updated")} == {f"categories:{c.pk}" for c in cats}


def test_default_queue_cannot_be_unmarked_and_is_chosen_only_among_marked():
    """FR-231: очередь по умолчанию выбирается среди отмеченных (`not_queue` иначе), с отметки не снимается
    (`queue_is_default`, раньше отказа об открытых заявках), после выбора другой — снимается; страница очередей
    показывает отметки и «по умолчанию»."""
    from apps.servicedesk.services import ServiceDeskError, queues

    admin = support.make_admin()
    first, second = sd.make_queue(), sd.make_queue()
    plain = org.make_unit()
    with pytest.raises(ServiceDeskError) as refused:
        queues.set_default(plain.pk, actor=admin)
    assert refused.value.code == "not_queue"
    queues.set_default(first.unit_id, actor=admin)
    assert queues.default_unit_id() == first.unit_id
    sd.make_ticket(queue=first, kind="new")
    with pytest.raises(ServiceDeskError) as refused:
        queues.unmark(first.unit_id, actor=admin)
    assert refused.value.code == "queue_is_default"
    with pytest.raises(ServiceDeskError) as refused:
        queues.unmark(plain.pk, actor=admin)
    assert refused.value.code == "not_queue"
    assert queues.is_queue(first.unit_id) and queues.default_unit_id() == first.unit_id

    client = support.logged_in(admin, ip=IP)
    html = client.get("/servicedesk/queues/").content.decode()
    assert "data-unit-tree" in html
    first_li = _tag(html, "li", f'data-unit-id="{first.unit_id}"')
    assert 'data-queue="true"' in first_li and 'data-default="true"' in first_li
    second_li = _tag(html, "li", f'data-unit-id="{second.unit_id}"')
    assert 'data-queue="true"' in second_li and 'data-default="false"' in second_li
    assert 'data-queue="false"' in _tag(html, "li", f'data-unit-id="{plain.pk}"')
    assert re.search(r"data-default-mark[^>]*>\s*по умолчанию", html)
    rejected = client.post("/servicedesk/queues/", {"action": "default", "unit": plain.pk})
    assert rejected.status_code == 200 and _has_alert(rejected.content.decode())
    assert queues.default_unit_id() == first.unit_id
    chosen = client.post("/servicedesk/queues/", {"action": "default", "unit": second.unit_id})
    assert chosen.status_code == 302
    assert queues.default_unit_id() == second.unit_id
    sd_tickets = model("servicedesk.Ticket").objects.filter(queue_id=first.unit_id, kind="new")
    sd_tickets.update(kind="closed")
    queues.unmark(first.unit_id, actor=admin)
    assert not queues.is_queue(first.unit_id)


def test_default_queue_change_moves_category_other_to_it():
    """FR-231, FR-269, сценарий 9.2: смена очереди по умолчанию пишет `queue.default_changed` (было → стало); заявка с
    категорией «Другое» идёт в текущую очередь по умолчанию, собственной очереди у «Другое» нет; повтор — тихо."""
    from apps.servicedesk.services import queues, tickets

    admin = support.make_admin()
    sd.configure_servicedesk(domains=[CORP])
    one, two = sd.make_queue(), sd.make_queue()
    other = model("servicedesk.Category").objects.get(is_system=True)
    assert other.queue_id is None and queues.default_unit_id() is None

    queues.set_default(one.unit_id, actor=admin, ip=IP)
    first = _events("queue.default_changed")[-1]
    assert (first.object_type, first.object_id, first.actor_id) == ("queue", str(one.unit_id), admin.pk)
    assert first.after == {"unit": one.unit.name, "unit_id": one.unit_id}
    assert not first.before.get("unit_id")
    assert model("servicedesk.ServiceDeskSettings").objects.get(pk=1).default_queue_id == one.unit_id
    created = tickets.create(channel=tickets.MAIL, subject="Тема", text="Текст", requester_email=f"a@{CORP}",
                             category=other)
    assert created.ticket.queue_id == one.unit_id

    queues.set_default(two.unit_id, actor=admin)
    second = _events("queue.default_changed")[-1]
    assert second.object_id == str(two.unit_id)
    assert second.before == {"unit": one.unit.name, "unit_id": one.unit_id}
    assert second.after == {"unit": two.unit.name, "unit_id": two.unit_id}
    created = tickets.create(channel=tickets.MAIL, subject="Тема 2", text="Текст", requester_email=f"b@{CORP}",
                             category=other)
    assert created.ticket.queue_id == two.unit_id
    assert model("servicedesk.Category").objects.get(pk=other.pk).queue_id is None
    count = len(_events("queue.default_changed"))
    queues.set_default(two.unit_id, actor=admin)
    assert len(_events("queue.default_changed")) == count


# --- удаление узла (FR-231, дополнение к FR-107 среза 002) ------------------------------------------

def test_delete_unit_with_tickets_including_only_closed_refused_with_reason():
    """FR-231, сценарий 9.10: узел с заявками (в том числе только закрытыми) не удаляется: `OrgError(code="in_use")` с
    причиной «к узлу привязаны заявки сервис-деска»; узел остаётся, `unit.deleted` не пишется; причина про заявки
    важнее причины про очередь."""
    from django.utils import timezone

    from apps.org.services import structure
    from apps.org.services.errors import OrgError
    from apps.servicedesk.services import queues

    admin = support.make_admin()
    closed_only = org.make_unit()
    sd.make_ticket(queue=closed_only, kind="closed", closed_at=timezone.now())
    open_unit = org.make_unit()
    sd.make_ticket(queue=open_unit, kind="new")
    marked = sd.make_queue()
    sd.make_ticket(queue=marked, kind="closed", closed_at=timezone.now())
    for unit in (closed_only, open_unit, marked.unit):
        assert queues.unit_usage(unit.pk) == REASON_TICKETS
        with pytest.raises(OrgError) as refused:
            structure.delete_unit(unit, actor=admin, ip=IP)
        assert refused.value.code == "in_use"
        assert REASON_TICKETS in refused.value.message
        assert model("org.Unit").objects.filter(pk=unit.pk).exists()
    assert not model("core.AuditEvent").objects.filter(action="unit.deleted").exists()


def test_delete_queue_unit_without_tickets_refused_unmark_first():
    """FR-231: узел-очередь без заявок не удаляется, пока отмечен: причина «узел — очередь сервис-деска: сначала снимите
    отметку»; после снятия отметки удаляется."""
    from apps.org.services import structure
    from apps.org.services.errors import OrgError
    from apps.servicedesk.services import queues

    admin = support.make_admin()
    _default_queue()
    queue = sd.make_queue()
    assert queues.unit_usage(queue.unit_id) == REASON_QUEUE
    with pytest.raises(OrgError) as refused:
        structure.delete_unit(queue.unit, actor=admin)
    assert refused.value.code == "in_use" and REASON_QUEUE in refused.value.message
    assert model("org.Unit").objects.filter(pk=queue.unit_id).exists() and queues.is_queue(queue.unit_id)
    assert not model("core.AuditEvent").objects.filter(action="unit.deleted").exists()
    queues.unmark(queue.unit_id, actor=admin)
    assert queues.unit_usage(queue.unit_id) is None
    structure.delete_unit(queue.unit, actor=admin)
    assert not model("org.Unit").objects.filter(pk=queue.unit_id).exists()


def test_delete_empty_unit_passes_and_protect_guards_ticket_queue_and_queue_unit():
    """FR-231: пустой узел без заявок и отметки удаляется (`unit.deleted`); второй рубеж — `PROTECT` у `Ticket.queue` и
    `Queue.unit`: удаление узла в обход службы поднимает `ProtectedError`."""
    from django.db.models import ProtectedError

    from apps.org.services import structure
    from apps.servicedesk.services import queues

    admin = support.make_admin()
    empty = org.make_unit()
    assert queues.unit_usage(empty.pk) is None
    structure.delete_unit(empty, actor=admin)
    assert not model("org.Unit").objects.filter(pk=empty.pk).exists()
    assert model("core.AuditEvent").objects.filter(action="unit.deleted", object_id=str(empty.pk)).exists()

    with_ticket = org.make_unit()
    sd.make_ticket(queue=with_ticket)
    marked = sd.make_queue()
    Unit = model("org.Unit")
    for unit in (with_ticket, marked.unit):
        with pytest.raises(ProtectedError):
            Unit.objects.filter(pk=unit.pk).delete()
        with pytest.raises(ProtectedError):
            Unit.objects.get(pk=unit.pk).delete()
        assert Unit.objects.filter(pk=unit.pk).exists()


# --- домены (FR-274) --------------------------------------------------------------------------------

def test_domains_lowercased_split_by_comma_and_newline_xn_accepted():
    """FR-274: домены — строка через запятую или с новой строки (или список), обрезка, строчные, кириллический домен в
    виде `xn--…`, готовый `xn--…` принимается как есть; `update` сохраняет список и пишет журнал."""
    from apps.servicedesk.services import settings as sd_settings

    admin = support.make_admin()
    assert sd_settings.parse_domains("Corp.Test, Example.RU\n  third.org ,\n\n,") == [
        "corp.test", "example.ru", "third.org"]
    assert sd_settings.parse_domains(["Corp.Test", " A.Example.Org "]) == ["corp.test", "a.example.org"]
    assert sd_settings.parse_domains("Пример.РФ") == ["xn--e1afmkfd.xn--p1ai"]
    assert sd_settings.parse_domains("xn--e1afmkfd.xn--p1ai") == ["xn--e1afmkfd.xn--p1ai"]
    assert sd_settings.parse_domains("") == []
    updated = sd_settings.update(actor=admin, ip=IP, domains="Corp.Test\nПример.РФ, mail.example.org")
    assert updated.domains == ["corp.test", "xn--e1afmkfd.xn--p1ai", "mail.example.org"]
    assert sd_settings.get().domains == updated.domains
    assert sd_settings.accepts_domain("CORP.test") and sd_settings.accepts_domain("пример.рф")
    assert not sd_settings.accepts_domain("other.test")
    event = _events("servicedesk.settings_changed")[-1]
    assert (event.object_type, event.object_id) == ("servicedesk", "1")
    assert event.before == {"domains": []} and event.after == {"domains": updated.domains}


def test_domains_duplicates_removed():
    """FR-274: дубликаты убираются с сохранением порядка первых вхождений (в том числе с другим регистром и
    кириллический и `xn--` вид одного домена)."""
    from apps.servicedesk.services import settings as sd_settings

    assert sd_settings.parse_domains("a.test, B.test, A.TEST,\nb.test, c.test, a.test") == ["a.test", "b.test", "c.test"]
    assert sd_settings.parse_domains("пример.рф, xn--e1afmkfd.xn--p1ai, ПРИМЕР.РФ") == ["xn--e1afmkfd.xn--p1ai"]
    updated = sd_settings.update(actor=support.make_admin(), domains="x.test, X.test, y.test")
    assert updated.domains == ["x.test", "y.test"]


def test_domains_invalid_form_refused():
    """FR-274: домен не вида «метки через точку» — `bad_domain`: «_», дефис в начале или конце метки, пустая метка,
    одна метка, пробел внутри, длиннее 253 знаков, метка в 64 знака (дополнение 13); список не меняется, журнала нет; страница настроек отвечает 200 с
    `[role=alert]`."""
    from apps.servicedesk.services import ServiceDeskError, settings as sd_settings

    admin = support.make_admin()
    sd_settings.update(actor=admin, domains=CORP)
    too_long = ".".join(["a" * 50] * 5) + ".test"
    assert len(too_long) > 253
    long_label = "a" * 64 + ".test"  # метка в 64 знака: не кодируется в IDNA (дополнение 13)
    for bad in ("bad_domain.test", "-start.test", "end-.test", "a..test", "localhost", "exa mple.test", too_long,
                long_label):
        with pytest.raises(ServiceDeskError) as refused:
            sd_settings.parse_domains(bad)
        assert refused.value.code == "bad_domain", bad
        with pytest.raises(ServiceDeskError) as refused:
            sd_settings.update(actor=admin, domains=f"good.test, {bad}")
        assert refused.value.code == "bad_domain", bad
    assert sd_settings.get().domains == [CORP]
    assert len(_events("servicedesk.settings_changed")) == 1

    client = support.logged_in(admin, ip=IP)
    page = client.post("/servicedesk/", _settings_form(domains="bad_domain.test"))
    assert page.status_code == 200 and _has_alert(page.content.decode())
    assert sd_settings.get().domains == [CORP]


# --- сроки и пределы (FR-221, FR-225, FR-250, FR-251, FR-290, FR-274) -------------------------------

def test_initial_terms_and_limits_defaults_7_7_10_3_30_and_ranges_validated():
    """FR-274, FR-221, FR-225, FR-250, FR-251, FR-290: начальные значения 7, 7, 10, 3, 30; границы 1–90, 1–90, 1–1000,
    1–10, 1–365 (граница принимается, за границей — `out_of_range`, значение не меняется); страница показывает значения
    в полях формы настроек; сохранение со страницы — 302, выход за границу — 200 с `[role=alert]`."""
    from apps.servicedesk.services import ServiceDeskError, settings as sd_settings

    admin = support.make_admin()
    current = sd_settings.get()
    assert (current.autoclose_days, current.reopen_days, current.form_hourly_limit, current.retention_years,
            current.inbound_retention_days) == (7, 7, 10, 3, 30)
    client = support.logged_in(admin, ip=IP)
    html = client.get("/servicedesk/").content.decode()
    assert _tag(html, "form", 'data-form="servicedesk-settings"')
    for name, value in (("autoclose_days", 7), ("reopen_days", 7), ("form_hourly_limit", 10), ("retention_years", 3),
                        ("inbound_retention_days", 30)):
        assert f'value="{value}"' in _tag(html, "input", f'name="{name}"'), name
    assert _tag(html, "textarea", 'name="domains"') and _tag(html, "select", 'name="default_priority"')

    limits = {"autoclose_days": (1, 90), "reopen_days": (1, 90), "form_hourly_limit": (1, 1000),
              "retention_years": (1, 10), "inbound_retention_days": (1, 365)}
    for field, (low, high) in limits.items():
        for ok in (low, high):
            assert getattr(sd_settings.update(actor=admin, **{field: ok}), field) == ok
        for bad in (low - 1, high + 1):
            with pytest.raises(ServiceDeskError) as refused:
                sd_settings.update(actor=admin, **{field: bad})
            assert refused.value.code == "out_of_range", (field, bad)
            assert getattr(sd_settings.get(), field) == high
    ok = client.post("/servicedesk/", _settings_form(autoclose_days=14))
    assert ok.status_code == 302 and ok["Location"].endswith("/servicedesk/")
    assert sd_settings.get().autoclose_days == 14
    bad = client.post("/servicedesk/", _settings_form(autoclose_days=91))
    assert bad.status_code == 200 and _has_alert(bad.content.decode())
    assert sd_settings.get().autoclose_days == 14


def test_default_criticality_setting_saved_and_used_for_new_ticket():
    """FR-274: критичность по умолчанию сохраняется в настройках (журнал было → стало по названию); новая заявка из
    письма получает её; архивная критичность по умолчанию — `archived_value`, настройка не меняется."""
    from apps.servicedesk.services import ServiceDeskError, settings as sd_settings, tickets

    admin = support.make_admin()
    default = _default_queue()
    Priority = model("servicedesk.Priority")
    assert sd_settings.get().default_priority.name == "Средняя"
    high, low = Priority.objects.get(name="Высокая"), Priority.objects.get(name="Низкая")
    updated = sd_settings.update(actor=admin, default_priority=high)
    assert updated.default_priority_id == high.pk
    event = _events("servicedesk.settings_changed")[-1]
    assert event.before == {"default_priority": "Средняя"} and event.after == {"default_priority": "Высокая"}
    created = tickets.create(channel=tickets.MAIL, subject="Тема", text="Текст", requester_email=f"a@{CORP}")
    assert created.ticket.priority_id == high.pk and created.ticket.queue_id == default.pk

    Priority.objects.filter(pk=low.pk).update(archived=True)
    with pytest.raises(ServiceDeskError) as refused:
        sd_settings.update(actor=admin, default_priority=Priority.objects.get(pk=low.pk))
    assert refused.value.code == "archived_value"
    assert sd_settings.get().default_priority_id == high.pk


def test_mailbox_address_readonly_in_settings(settings):
    """FR-274 (FR-210): адрес ящика берётся из `SERVICEDESK_MAILBOX` и показан текстом без `input`; через службу и форму
    он не меняется, очередь по умолчанию меняет только `queues.set_default`; предупреждение `IMAP_SECURITY=none` — только
    при режиме `none`."""
    from apps.servicedesk.services import queues, settings as sd_settings

    settings.SERVICEDESK_MAILBOX = MAILBOX
    settings.IMAP_SECURITY = "ssl"
    admin = support.make_admin()
    client = support.logged_in(admin, ip=IP)
    html = client.get("/servicedesk/").content.decode()
    assert sd_settings.mailbox_address() == MAILBOX
    assert MAILBOX in (_inner(html, 'data-field="mailbox-address"') or "")
    assert not re.search(r"<input\b[^>]*" + re.escape(MAILBOX), html)
    assert not re.search(r"<input\b[^>]*name=\"(mailbox|mailbox_address|default_queue)\"", html)
    assert "не задана" in (_inner(html, 'data-field="default-queue"') or "")
    assert "data-warning=\"imap-security\"" not in html
    for mode in ("starttls", "ssl"):
        settings.IMAP_SECURITY = mode
        assert 'data-warning="imap-security"' not in client.get("/servicedesk/").content.decode()
    settings.IMAP_SECURITY = "none"
    warned = client.get("/servicedesk/").content.decode()
    assert "IMAP_SECURITY=none" in (_inner(warned, 'data-warning="imap-security"') or "")

    unit = sd.make_queue().unit
    posted = client.post("/servicedesk/", _settings_form(mailbox_address="evil@x.test", mailbox="evil@x.test",
                                                         default_queue=unit.pk))
    assert posted.status_code == 302
    assert sd_settings.mailbox_address() == MAILBOX
    assert model("servicedesk.ServiceDeskSettings").objects.get(pk=1).default_queue_id is None
    for key in ("mailbox_address", "default_queue"):
        with pytest.raises(TypeError):
            sd_settings.update(actor=admin, **{key: unit if key == "default_queue" else "evil@x.test"})
    queues.set_default(unit.pk, actor=admin)
    shown = client.get("/servicedesk/").content.decode()
    assert unit.name in (_inner(shown, 'data-field="default-queue"') or "")


# --- «закрыто по умолчанию» и ожидание настройки (FR-213, FR-231) -----------------------------------

def test_fresh_install_no_queues_no_domains_mail_and_form_not_accepted(protected_root, django_capture_on_commit_callbacks):
    """FR-213, FR-231, FR-274, сценарий 9.1: на новой установке очередей нет, список доменов пуст, очереди по умолчанию
    нет, есть категория «Другое»; сервис-деск «не настроен», форма закрыта, письмо отклоняется как чужой домен и
    заявок не создаёт; одних доменов или одной очереди по умолчанию мало."""
    from apps.servicedesk.services import form, intake, queues, settings as sd_settings

    row = model("servicedesk.ServiceDeskSettings").objects.get(pk=1)
    assert row.domains == [] and row.default_queue_id is None and row.default_priority.name == "Средняя"
    assert model("servicedesk.Queue").objects.count() == 0 and queues.marked_units() == []
    other = model("servicedesk.Category").objects.get(is_system=True)
    assert other.queue_id is None and other.on_form
    assert not sd_settings.is_configured() and not form.is_open()
    client = support.logged_in(support.make_admin(), ip=IP)
    tree = client.get("/servicedesk/queues/").content.decode()
    assert 'data-queue="true"' not in tree and 'data-default="true"' not in tree
    assert "не задана" in (_inner(client.get("/servicedesk/").content.decode(), 'data-field="default-queue"') or "")

    mail = _inbound_mail(protected_root, from_addr=f"user@{CORP}")
    with django_capture_on_commit_callbacks(execute=True):
        assert intake.process(mail.pk) == "rejected_domain"
    mail.refresh_from_db()
    assert mail.outcome == "rejected_domain" and mail.ticket_id is None
    assert model("servicedesk.Ticket").objects.count() == 0

    sd.configure_servicedesk(domains=[CORP])
    assert not sd_settings.is_configured() and not form.is_open()
    sd.configure_servicedesk(domains=[])
    queue = sd.make_queue()
    sd.configure_servicedesk(default_queue=queue)
    assert not sd_settings.is_configured() and not form.is_open()
    sd.configure_servicedesk(domains=[CORP])
    assert sd_settings.is_configured() and form.is_open()


def test_domain_removed_from_list_rejects_reply_in_existing_ticket_as_foreign_domain(protected_root,
                                                                                      django_capture_on_commit_callbacks):
    """FR-213: проверка домена действует и для ответа в существующую заявку: пока домен в списке, письмо дописывается;
    после удаления домена из списка письмо отклоняется как чужой домен, лента заявки не растёт, новой заявки нет."""
    from apps.servicedesk.services import intake, settings as sd_settings

    admin = support.make_admin()
    queue = _default_queue(domains=(CORP, "other.test"))
    requester = sd.make_requester(f"client@{CORP}")
    ticket = sd.make_ticket(queue=queue, requester=requester, kind="in_progress")
    Entry = model("servicedesk.TicketEntry")
    tickets_before = model("servicedesk.Ticket").objects.count()
    subject = f"Re: [#{ticket.number}] Тема"

    first = _inbound_mail(protected_root, from_addr=requester.email, subject=subject)
    with django_capture_on_commit_callbacks(execute=True):
        assert intake.process(first.pk) == "appended"
    assert Entry.objects.filter(ticket=ticket, kind="incoming").count() == 1

    sd_settings.update(actor=admin, domains="other.test")
    assert not sd_settings.accepts_domain(CORP) and sd_settings.accepts_domain("other.test")
    second = _inbound_mail(protected_root, from_addr=requester.email, subject=subject)
    with django_capture_on_commit_callbacks(execute=True):
        assert intake.process(second.pk) == "rejected_domain"
    second.refresh_from_db()
    assert second.outcome == "rejected_domain" and second.ticket_id is None
    assert Entry.objects.filter(ticket=ticket, kind="incoming").count() == 1
    assert model("servicedesk.Ticket").objects.count() == tickets_before


def test_waiting_mail_without_default_queue_not_rejected_and_form_closed(protected_root,
                                                                         django_capture_on_commit_callbacks):
    """FR-213, FR-231: пока очереди по умолчанию нет, письмо из корпоративного домена не отклоняется, а ждёт
    (`waiting_setup`), заявки нет; письмо чужого домена всё равно отклоняется; форма закрыта."""
    from apps.servicedesk.services import form, intake

    sd.configure_servicedesk(domains=[CORP])
    sd.make_queue()  # очередь есть, но не по умолчанию
    assert not form.is_open()
    waiting = _inbound_mail(protected_root, from_addr=f"user@{CORP}")
    foreign = _inbound_mail(protected_root, from_addr="someone@elsewhere.test")
    with django_capture_on_commit_callbacks(execute=True):
        assert intake.process(waiting.pk) == "waiting_setup"
        assert intake.process(foreign.pk) == "rejected_domain"
    waiting.refresh_from_db()
    foreign.refresh_from_db()
    assert waiting.status == "waiting_setup" and waiting.outcome == "waiting_setup" and waiting.ticket_id is None
    assert foreign.outcome == "rejected_domain"
    assert model("servicedesk.Ticket").objects.count() == 0


def test_choosing_default_queue_enqueues_parsing_of_waiting_setup_mails_after_commit(django_capture_on_commit_callbacks):
    """FR-231, FR-213: выбор очереди по умолчанию ставит разбор каждого письма в состоянии `waiting_setup` в очередь
    `inbox` только после фиксации; письма в других состояниях не ставятся; повторный выбор той же очереди — ничего."""
    import django_rq

    from apps.servicedesk.services import queues

    admin = support.make_admin()
    sd.configure_servicedesk(domains=[CORP])
    queue = sd.make_queue()
    waiting = [sd.make_inbound(status="waiting_setup", outcome="waiting_setup") for _ in range(2)]
    sd.make_inbound(status="processed", outcome="created")
    sd.make_inbound(status="received")
    sd.make_inbound(status="error", outcome="parse_error")
    jobs = django_rq.get_queue("inbox")
    assert jobs.count == 0

    with django_capture_on_commit_callbacks(execute=True):
        queues.set_default(queue.unit_id, actor=admin)
        assert jobs.count == 0  # до фиксации в очереди пусто
    assert sorted(job.args for job in jobs.jobs) == sorted((row.pk,) for row in waiting)
    assert {job.func_name for job in jobs.jobs} == {"apps.servicedesk.tasks.process_inbound"}
    assert {job.timeout for job in jobs.jobs} == {300}

    with django_capture_on_commit_callbacks(execute=True):
        queues.set_default(queue.unit_id, actor=admin)
    assert jobs.count == 2


# --- права и напоминание (FR-275) -------------------------------------------------------------------

def test_manage_right_required_on_every_settings_route_403():
    """FR-275, сценарий 9.8: без права «Настройка сервис-деска» каждый маршрут настроек, очередей, справочников,
    заявителей и входящих отвечает 403 (одинаково для существующего и несуществующего номера, и для держателя только
    «Все заявки»); без входа — 302 на вход; держатель права открывает страницы-списки."""
    category = model("servicedesk.Category").objects.get(is_system=True)
    requester = sd.make_requester()
    inbound = sd.make_inbound()
    missing = 999999
    routes = [("get", "/servicedesk/"), ("post", "/servicedesk/"),
              ("get", "/servicedesk/queues/"), ("post", "/servicedesk/queues/"),
              ("get", "/servicedesk/requesters/"), ("get", "/servicedesk/requesters/import/"),
              ("post", "/servicedesk/requesters/import/"), ("get", "/servicedesk/requesters/import/sample.csv"),
              ("get", "/servicedesk/requesters/import/sample.xlsx"), ("get", f"/servicedesk/requesters/import/{missing}/"),
              ("post", f"/servicedesk/requesters/import/{missing}/"), ("get", "/servicedesk/inbound/")]
    for kind in ("categories", "priorities", "complexities", "statuses", "sources", "client-units"):
        base = f"/servicedesk/dictionaries/{kind}/"
        routes += [("get", base), ("get", f"{base}new/"), ("post", f"{base}new/")]
        for number in (category.pk, missing):
            routes += [("get", f"{base}{number}/edit/"), ("post", f"{base}{number}/edit/"),
                       ("post", f"{base}{number}/archive/"), ("post", f"{base}{number}/restore/"),
                       ("get", f"{base}{number}/delete/"), ("post", f"{base}{number}/delete/")]
    for number in (requester.pk, missing):
        base = f"/servicedesk/requesters/{number}/"
        routes += [("get", f"{base}edit/"), ("post", f"{base}edit/"), ("get", f"{base}delete/"),
                   ("post", f"{base}delete/")]
    for number in (inbound.pk, missing):
        routes.append(("post", f"/servicedesk/inbound/{number}/retry/"))

    outsiders = [support.make_employee(), support.make_with_permissions("servicedesk.all")]
    for user in outsiders:
        client = support.logged_in(user, ip=IP)
        for method, path in routes:
            response = getattr(client, method)(path)
            assert response.status_code == 403, (method, path, response.status_code)
    anonymous = support.make_client(ip=IP)
    for method, path in routes:
        response = getattr(anonymous, method)(path)
        assert response.status_code == 302 and "/login/" in response["Location"], (method, path)

    holder = support.logged_in(support.make_with_permissions("servicedesk.manage"), ip=IP)
    for path in ("/servicedesk/", "/servicedesk/queues/", "/servicedesk/dictionaries/categories/",
                 "/servicedesk/requesters/", "/servicedesk/inbound/"):
        assert holder.get(path).status_code == 200, path


def test_home_notice_for_manage_holder_until_configured():
    """FR-275: пока сервис-деск не настроен (нет доменов или очереди по умолчанию), держатель права «Настройка
    сервис-деска» видит на главной напоминание `[data-notice="servicedesk-setup"]` с текстом и ссылкой на `/servicedesk/`;
    у остальных его нет; после настройки напоминание исчезает."""
    holder = support.make_with_permissions("servicedesk.manage")
    other = support.make_with_permissions("servicedesk.all")
    plain = support.make_employee()
    text = "Сервис-деск не настроен: укажите домены и очередь по умолчанию"

    page = support.logged_in(holder, ip=IP).get("/").content.decode()
    assert "data-home-notices" in page
    notice = _tag(page, "[a-z]+", 'data-notice="servicedesk-setup"')
    assert notice and 'role="status"' in notice
    assert text in _window(page, 'data-notice="servicedesk-setup"')
    _, links = _element(page, 'data-notice="servicedesk-setup"')
    assert "/servicedesk/" in links, links
    for user in (other, plain):
        assert 'data-notice="servicedesk-setup"' not in support.logged_in(user, ip=IP).get("/").content.decode()

    sd.configure_servicedesk(domains=[CORP])  # домены есть, очереди по умолчанию нет — всё ещё не настроено
    assert 'data-notice="servicedesk-setup"' in support.logged_in(holder, ip=IP).get("/").content.decode()
    _default_queue()
    assert 'data-notice="servicedesk-setup"' not in support.logged_in(holder, ip=IP).get("/").content.decode()


# --- журнал «было → стало» по-русски (FR-231, FR-274, сценарий 9.9) ---------------------------------

def test_changes_of_queues_dictionaries_and_settings_journaled_was_became_in_russian():
    """FR-231, FR-274, сценарий 9.9: каждое изменение очередей, справочников и настроек даёт событие журнала нужного
    кода и вида объекта; названия событий, видов объекта, полей и значений — по-русски (`audit_labels`); страница
    `/audit/` показывает «было» и «стало» без латинских ключей."""
    from apps.core.services import audit_labels, audit_search
    from apps.servicedesk.services import dictionaries, queues, settings as sd_settings

    admin = support.make_admin()
    first, second, third = sd.make_queue().unit, sd.make_queue().unit, sd.make_queue().unit
    queues.set_default(first.pk, actor=admin)
    queues.unmark(second.pk, actor=admin)
    queues.mark(second.pk, actor=admin)
    category = dictionaries.create("category", name="Печать", queue_id=third.pk, actor=admin)
    dictionaries.update(category, name="Печать и сканы", order=5, actor=admin)
    dictionaries.archive(category, actor=admin)
    dictionaries.restore(category, actor=admin)
    dictionaries.delete(category, actor=admin)
    department = dictionaries.create("client_unit", name="Бухгалтерия", actor=admin)
    dictionaries.update(department, name="Бухгалтерия и учёт", actor=admin)
    dictionaries.archive(department, actor=admin)
    dictionaries.restore(department, actor=admin)
    dictionaries.delete(department, actor=admin)
    sd_settings.update(actor=admin, autoclose_days=14, domains="corp.test, example.org")

    codes = ("queue.marked", "queue.unmarked", "queue.default_changed", "sd_dictionary.created",
             "sd_dictionary.updated", "sd_dictionary.archived", "sd_dictionary.restored", "sd_dictionary.deleted",
             "client_unit.created", "client_unit.updated", "client_unit.archived", "client_unit.restored",
             "client_unit.deleted", "servicedesk.settings_changed")
    kinds = {"queue": "queue", "sd_dictionary": "sd_dictionary", "client_unit": "sd_dictionary",
             "servicedesk": "servicedesk"}
    titles = dict(audit_search.known_actions())
    keys = set()
    for code in codes:
        events = _events(code)
        assert events, code
        assert is_russian(titles.get(code, code), code), (code, titles.get(code))
        for event in events:
            assert event.object_type == kinds[code.split(".")[0]], code
            assert event.actor_id == admin.pk and isinstance(event.object_id, str) and event.object_id
            keys |= set(event.before) | set(event.after)
    assert audit_labels.object_title("queue") == "очередь"
    assert audit_labels.object_title("sd_dictionary") == "справочник"
    assert audit_labels.object_title("servicedesk") == "сервис-деск"
    for key in sorted(keys):
        assert is_russian(audit_labels.label(key), key), f"поле {key} не переведено: {audit_labels.label(key)!r}"
    assert audit_labels.label("autoclose_days") == "срок автозакрытия, дней"
    assert audit_labels.label("domains") == "домены"
    for value in ("category", "priority", "complexity", "status", "source"):
        assert is_russian(audit_labels.text("dictionary", value), value), value

    settings_event = _events("servicedesk.settings_changed")[-1]
    assert set(settings_event.before) == set(settings_event.after) == {"autoclose_days", "domains"}
    assert settings_event.before["autoclose_days"] == 7 and settings_event.after["autoclose_days"] == 14
    assert settings_event.after["domains"] == ["corp.test", "example.org"]

    client = support.logged_in(admin, ip=IP)

    def cell_text(html: str) -> str:
        return " ".join(unescape(re.sub("<[^>]+>", " ", html)).split())

    for code in codes:
        page = client.get(f"/audit/?action={code}&sort=at").content.decode()
        rows = {int(pk): body for pk, body in re.findall(r'<tr data-event-id="(\d+)"[^>]*>(.*?)</tr>', page, re.S)}
        events = {e.pk: e for e in _events(code)}
        assert set(rows) == set(events), code
        for pk, event in events.items():
            cells = [cell_text(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", rows[pk], re.S)]
            assert cells[2].startswith(titles[code]), (code, cells[2])
            for index, side in ((4, "before"), (5, "after")):
                for name, value in audit_labels.side_pairs(event, side):
                    assert f"{name}: {value}" in cells[index], (code, side, name, value, cells[index])
                for key in getattr(event, side):
                    assert not re.search(rf"(?<![\w.]){re.escape(key)}(?![\w.])", cells[index]), (code, key)
            if code == "servicedesk.settings_changed":
                assert "срок автозакрытия, дней: 7" in cells[4] and "срок автозакрытия, дней: 14" in cells[5]
