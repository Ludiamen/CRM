"""T-3105: общее создание заявки (FR-201…205, FR-219, FR-227, FR-238, FR-254, FR-261). Сценарии 1, 2, 7, 13 спеки.

Служба — `apps.servicedesk.services.tickets.create` (CONTRACT-003 § 6.7, план «Создание заявки — общее для трёх
каналов»); журнал — § 9.2, лента — § 9.3, письма — § 10, зацепки карточки — § 13.3. Заявки создаются службой, а не
фабрикой `make_ticket` (она ходит мимо службы). Три теста нерабочего времени берут `clock` (решение Opus A1): код
читает час суток. Помощники файла (страница, письма, календарь) держатся внутри файла.
"""
import datetime
import re
from datetime import date, time
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests import factories, support, support_org, support_servicedesk as sd
from tests.support import model
from tests.support_mail import mail_jobs

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
TOTAL_KEYS = ("holidays_on_weekdays", "moved_days_off", "moved_workdays", "short_days", "work_days")
SEQUENCE_DB = pytest.mark.django_db(databases=["default", "migrate"])


# --- помощники файла: настройка, создание, чтение ---------------------------------------------------------

def tickets_module():
    from apps.servicedesk.services import tickets

    return tickets


def setup_desk():
    """Очередь по умолчанию и список доменов: приём открыт."""
    queue = sd.make_queue()
    sd.configure_servicedesk(domains=["corp.test"], default_queue=queue)
    return queue


def client_unit(name: str):
    """Подразделение заявителя (справочник `ClientUnit`); `name_key` модель пересчитывает сама (§ 2.1)."""
    return model("servicedesk.ClientUnit").objects.create(name=name, name_key=support_org.name_key(name))


def status_of(kind: str):
    return model("servicedesk.Status").objects.get(kind=kind, is_default=True)


def manual_source():
    return model("servicedesk.Source").objects.get(system_code="", name_key=support_org.name_key("Телефон"))


def priority_named(name: str):
    return model("servicedesk.Priority").objects.get(name_key=support_org.name_key(name))


def new_email() -> str:
    return factories.new_email("req").lower()


def new_ticket(channel=None, **kw):
    """`tickets.create` с обязательными аргументами по умолчанию; для письма — со строкой входящего письма."""
    tickets = tickets_module()
    channel = channel or tickets.MAIL
    kw.setdefault("subject", "Не печатает принтер")
    kw.setdefault("text", "Принтер на втором этаже не печатает")
    kw.setdefault("requester_email", new_email())
    if channel == tickets.MAIL:
        kw.setdefault("inbound_id", sd.make_inbound().pk)
    if channel == tickets.STAFF:
        kw.setdefault("source", manual_source())
        kw.setdefault("created_by", support.make_employee())
    return tickets.create(channel=channel, **kw)


def admin_all():
    """Сотрудник с правом «Все заявки»: видит и ведёт любую заявку."""
    return support.make_with_permissions("servicedesk.all")


def journal(action: str, number: int) -> list:
    return list(model("core.AuditEvent").objects.filter(
        action=action, object_type="ticket", object_id=str(number)).order_by("id"))


def feed_events(ticket, event: str) -> list:
    return list(ticket.entries.filter(kind="event", event=event).order_by("id"))


def confirmation_of(created):
    """Письмо-подтверждение заявки и контекст его задания (`job.meta["context"]`): `(MailMessage, dict)`."""
    ticket = created.ticket
    messages = [m for m in sd.ticket_mails(ticket) if m.template == "ticket.confirmation"]
    assert len(messages) == 1, f"писем-подтверждений: {len(messages)}"
    jobs = [j for j in mail_jobs() if j.meta.get("context", {}).get("ticket_id") == ticket.pk]
    assert len(jobs) == 1, f"заданий подтверждения: {len(jobs)}"
    return messages[0], jobs[0].meta["context"]


def confirmation_text(created) -> str:
    message, context = confirmation_of(created)
    return sd.mail_text(message, context)


def seed_year(year: int, days: dict | None = None):
    """Загруженный год календаря напрямую в базе (как в test_calendar): `days` — {дата: вид `SpecialDay`}."""
    by = support.make_employee()
    now = timezone.now()
    model("org.CalendarYear").objects.create(
        year=year, loaded_at=now, loaded_by=by, file_name=f"cal{year}.csv", totals={k: 0 for k in TOTAL_KEYS})
    SpecialDay = model("org.SpecialDay")
    SpecialDay.objects.bulk_create([
        SpecialDay(date=d, kind=kind, origin="file", changed_by=by, changed_at=now) for d, kind in (days or {}).items()])


def at_msk(clock, year, month, day, hour=0, minute=0):
    clock.set(datetime.datetime(year, month, day, hour, minute, tzinfo=MSK))


# --- разбор страницы --------------------------------------------------------------------------------------

_VOID = {"meta", "link", "input", "br", "hr", "img", "source", "area", "base", "col", "embed", "param", "track", "wbr"}


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


def find(doc, tag=None, attrs=None) -> list:
    wanted = attrs or {}
    return [el for el in doc.elements
            if (tag is None or el.tag == tag) and all(k in el.attrs and (v is True or el.attrs[k] == v)
                                                     for k, v in wanted.items())]


def inside(el, ancestor) -> bool:
    node = el.parent
    while node is not None:
        if node is ancestor:
            return True
        node = node.parent
    return False


def card(user, number: int) -> _Doc:
    response = support.logged_in(user).get(f"/tickets/{number}/")
    assert response.status_code == 200, f"карточка #{number}: {response.status_code}"
    return _Doc(response.content.decode())


# --- FR-201: номер -----------------------------------------------------------------------------------------

@SEQUENCE_DB
def test_ticket_number_from_sequence_starts_at_one_and_grows():
    """FR-201: номер из последовательности базы: после сброса (1, не выдан) заявки получают 1, 2, 3; `next_number`
    выдаёт следующий одним запросом `nextval('servicedesk_ticket_number')`."""
    tickets = tickets_module()
    setup_desk()
    sd.set_sequence(1, is_called=False)
    assert sd.sequence_state() == (1, False)
    numbers = [new_ticket().ticket.number for _ in range(3)]
    assert numbers == [1, 2, 3]
    assert sd.sequence_state() == (3, True)
    with CaptureQueriesContext(connection) as queries:
        assert tickets.next_number() == 4
    assert len(queries) == 1 and "nextval('servicedesk_ticket_number')" in queries[0]["sql"]
    assert sd.sequence_state() == (4, True)


@SEQUENCE_DB
def test_ticket_number_not_reused_after_rollback_gap_allowed():
    """FR-201: номер при откате транзакции пропадает и не переиспользуется (пропуск в нумерации допустим)."""
    setup_desk()
    sd.set_sequence(1, is_called=False)
    assert new_ticket().ticket.number == 1
    with pytest.raises(RuntimeError):
        with transaction.atomic():
            lost = new_ticket().ticket.number
            raise RuntimeError("откат")
    assert lost == 2
    assert not model("servicedesk.Ticket").objects.filter(number=lost).exists()
    following = new_ticket().ticket.number
    assert following > lost
    assert sorted(model("servicedesk.Ticket").objects.values_list("number", flat=True)) == [1, following]


def test_ticket_number_unchanged_on_close_transfer_and_category_change():
    """FR-201: номер не меняется при передаче в другую очередь, смене категории и закрытии."""
    from apps.servicedesk.services import closing, transfer

    setup_desk()
    admin = admin_all()
    first_queue, second_queue, third_queue = sd.make_queue(), sd.make_queue(), sd.make_queue()
    first_category = sd.make_category(queue=first_queue)
    third_category = sd.make_category(queue=third_queue)
    ticket = new_ticket(category=first_category).ticket
    number = ticket.number

    def current():
        return model("servicedesk.Ticket").objects.get(pk=ticket.pk)

    transfer.transfer(ticket, second_queue.unit_id, reason="", actor=admin)
    assert current().queue_id == second_queue.unit_id and current().number == number
    transfer.change_category(current(), third_category, confirmed=True, actor=admin)
    assert current().category_id == third_category.pk and current().queue_id == third_queue.unit_id
    assert current().number == number
    closing.close(current(), status_of("closed"), "Решено", actor=admin)
    assert current().kind == "closed" and current().number == number


# --- FR-202: поля -----------------------------------------------------------------------------------------

def test_ticket_fields_set_on_creation():
    """FR-202: все поля новой заявки; первый элемент ленты — входящее письмо; журнал `ticket.created`
    (§ 9.2): у письма без `ip` и без исполнителя, у формы с `ip`."""
    tickets = tickets_module()
    setup_desk()
    queue = sd.make_queue()
    category = sd.make_category("Принтеры", queue=queue)
    unit = client_unit("Бухгалтерия")
    mixed = "Ivan.Petrov@Corp.Test"
    inbound = sd.make_inbound()
    created = new_ticket(requester_email=mixed, requester_name="Иван Петров", subject="Не печатает\nпринтер",
                         text="Текст заявки", category=category, client_unit_id=unit.pk, inbound_id=inbound.pk)
    ticket = created.ticket
    assert ticket.number >= 1
    assert ticket.subject == "Не печатает принтер"
    assert ticket.requester_email == mixed.lower() and ticket.requester_name == "Иван Петров"
    assert ticket.requester.email == mixed.lower() and ticket.requester.origin == "ticket"
    assert ticket.client_unit_id == unit.pk
    assert ticket.category_id == category.pk and ticket.queue_id == queue.unit_id
    assert ticket.priority.name == "Средняя" and ticket.complexity is None
    assert ticket.status.name == "Новая" and ticket.kind == "new"
    assert ticket.source.system_code == "mail"
    assert ticket.assignee is None and ticket.assigned_once is False
    assert abs(timezone.now() - ticket.created_at) < datetime.timedelta(minutes=1)
    assert ticket.closed_at is None and ticket.closed_by is None and ticket.resolution == ""
    assert ticket.previous is None and ticket.consent_at is None and ticket.anonymized_at is None
    assert ticket.last_message_from == "requester"
    entry = created.entry
    assert entry.ticket_id == ticket.pk and entry.kind == "incoming" and entry.text == "Текст заявки"
    assert entry.author_email == mixed.lower() and entry.author_name == "Иван Петров"
    assert entry.inbound_id == inbound.pk
    assert ticket.last_message_at == entry.at
    assert ticket.entries.filter(kind="incoming").count() == 1
    events = journal("ticket.created", ticket.number)
    assert len(events) == 1
    event = events[0]
    assert event.actor is None and event.ip is None and event.before == {}
    assert event.after == {"number": ticket.number, "channel": "mail", "queue": queue.unit.name,
                           "queue_id": queue.unit_id, "category": "Принтеры", "priority": "Средняя",
                           "source": "Почта"}

    form_created = new_ticket(tickets.FORM, category=category, consent_at=timezone.now(), ip="203.0.113.7")
    form_event = journal("ticket.created", form_created.ticket.number)[0]
    assert form_event.ip == "203.0.113.7" and form_event.actor is None
    assert form_event.after["channel"] == "form" and form_event.after["source"] == "Форма"
    assert form_created.ticket.source.system_code == "form"


# --- FR-203: критичность ----------------------------------------------------------------------------------

def test_default_severity_medium_from_settings_and_follows_change():
    """FR-203: новая заявка получает критичность по умолчанию «Средняя»; смена настройки действует на следующие
    заявки и не трогает прежние."""
    from apps.servicedesk.services import settings as sd_settings

    setup_desk()
    first = new_ticket().ticket
    assert first.priority.name == "Средняя"
    high = priority_named("Высокая")
    sd_settings.update(actor=support.make_employee(), default_priority=high)
    second = new_ticket().ticket
    assert second.priority_id == high.pk
    first.refresh_from_db()
    assert first.priority.name == "Средняя"


def test_form_has_no_severity_choice_staff_ticket_chooses_it():
    """FR-203: на открытой форме выбора критичности нет и заявка получает значение по умолчанию; у заявки исполнителя
    критичность выбирается при создании (в форме `/tickets/new/` выбрана критичность по умолчанию)."""
    tickets = tickets_module()
    setup_desk()
    response = support.make_client().get("/request/")
    assert response.status_code == 200
    doc = _Doc(response.content.decode())
    forms = find(doc, "form", {"data-form": "request"})
    assert len(forms) == 1
    names = {el.attrs.get("name") for el in doc.elements
             if el.tag in ("input", "select", "textarea") and inside(el, forms[0])}
    assert {"email", "subject", "text"} <= names
    assert not names & {"priority", "source", "complexity"}
    assert new_ticket(tickets.FORM, consent_at=timezone.now()).ticket.priority.name == "Средняя"

    admin = admin_all()
    page = _Doc(support.logged_in(admin).get("/tickets/new/").content.decode())
    staff_form = find(page, "form", {"data-form": "ticket-new"})[0]
    selects = [el for el in find(page, "select", {"name": "priority"}) if inside(el, staff_form)]
    assert len(selects) == 1
    selected = [el for el in find(page, "option") if el.parent is selects[0] and "selected" in el.attrs]
    assert [el.text for el in selected] == ["Средняя"]
    high = priority_named("Высокая")
    ticket = new_ticket(tickets.STAFF, category=sd.make_category(), priority=high).ticket
    assert ticket.priority_id == high.pk


# --- FR-204, FR-261: подразделение -----------------------------------------------------------------------

def test_department_from_form_when_chosen():
    """FR-204: выбранное на форме подразделение идёт в заявку."""
    tickets = tickets_module()
    setup_desk()
    unit = client_unit("Склад")
    created = new_ticket(tickets.FORM, client_unit_id=unit.pk, consent_at=timezone.now())
    assert created.ticket.client_unit_id == unit.pk


def test_department_from_requester_record_when_not_in_list():
    """FR-204, FR-261: «Нет в списке» на форме и письмо — подразделение записи заявителя; запись не меняется."""
    tickets = tickets_module()
    setup_desk()
    unit = client_unit("Отдел кадров")
    requester = sd.make_requester(new_email(), client_unit=unit)
    form = new_ticket(tickets.FORM, requester_email=requester.email, client_unit_id=None, consent_at=timezone.now())
    assert form.ticket.client_unit_id == unit.pk
    mail = new_ticket(tickets.MAIL, requester_email=requester.email)
    assert mail.ticket.client_unit_id == unit.pk
    requester.refresh_from_db()
    assert requester.client_unit_id == unit.pk


def test_department_empty_when_neither_form_nor_record():
    """FR-204: нет выбора на форме и в записи пусто — подразделение заявки пусто (его укажет исполнитель)."""
    tickets = tickets_module()
    setup_desk()
    mail = new_ticket(tickets.MAIL)
    form = new_ticket(tickets.FORM, client_unit_id=None, consent_at=timezone.now())
    for created in (mail, form):
        assert created.ticket.client_unit_id is None
        assert created.ticket.requester.client_unit_id is None


def test_form_department_written_to_record_only_when_empty():
    """FR-204, FR-261: подразделение с формы запоминается за адресом, если в записи оно пусто (новая запись и
    существующая без подразделения)."""
    tickets = tickets_module()
    setup_desk()
    unit = client_unit("Юристы")
    fresh = new_ticket(tickets.FORM, client_unit_id=unit.pk, consent_at=timezone.now())
    assert fresh.ticket.client_unit_id == unit.pk and fresh.ticket.requester.client_unit_id == unit.pk
    other = client_unit("Охрана")
    empty_record = sd.make_requester(new_email())
    assert empty_record.client_unit_id is None
    created = new_ticket(tickets.FORM, requester_email=empty_record.email, client_unit_id=other.pk,
                         consent_at=timezone.now())
    empty_record.refresh_from_db()
    assert created.ticket.client_unit_id == other.pk and empty_record.client_unit_id == other.pk


def test_form_department_does_not_overwrite_record_ticket_keeps_form_value():
    """FR-204, FR-261: форма не перезаписывает записанное подразделение; на заявке остаётся выбор с формы."""
    tickets = tickets_module()
    setup_desk()
    recorded, chosen = client_unit("Склад"), client_unit("Закупки")
    requester = sd.make_requester(new_email(), client_unit=recorded)
    created = new_ticket(tickets.FORM, requester_email=requester.email, client_unit_id=chosen.pk,
                         consent_at=timezone.now())
    requester.refresh_from_db()
    assert created.ticket.client_unit_id == chosen.pk
    assert requester.client_unit_id == recorded.pk


def test_staff_department_always_written_to_record():
    """FR-261: подразделение заявки исполнителя пишется в запись заявителя всегда: заменяет прежнее, а пустое
    значение стирает (решение Opus RB1-14)."""
    tickets = tickets_module()
    setup_desk()
    old, new = client_unit("Склад"), client_unit("Закупки")
    category = sd.make_category()
    requester = sd.make_requester(new_email(), client_unit=old)
    replaced = new_ticket(tickets.STAFF, requester_email=requester.email, category=category, client_unit_id=new.pk)
    requester.refresh_from_db()
    assert replaced.ticket.client_unit_id == new.pk and requester.client_unit_id == new.pk
    cleared = new_ticket(tickets.STAFF, requester_email=requester.email, category=category, client_unit_id=None)
    requester.refresh_from_db()
    assert cleared.ticket.client_unit_id is None and requester.client_unit_id is None


# --- FR-219: ФИО заявителя ---------------------------------------------------------------------------------

def test_requester_name_from_mail_header():
    """FR-219: ФИО заявки берётся из имени в заголовке письма; пустое ФИО записи заполняется им, непустое из
    письма не перезаписывается."""
    tickets = tickets_module()
    setup_desk()
    with_record = sd.make_requester(new_email(), full_name="Запись Заявителя")
    named = new_ticket(tickets.MAIL, requester_email=with_record.email, requester_name="Иван Петров")
    with_record.refresh_from_db()
    assert named.ticket.requester_name == "Иван Петров"
    assert with_record.full_name == "Запись Заявителя"
    empty_record = sd.make_requester(new_email())
    filled = new_ticket(tickets.MAIL, requester_email=empty_record.email, requester_name="Мария Орлова")
    empty_record.refresh_from_db()
    assert filled.ticket.requester_name == "Мария Орлова" and empty_record.full_name == "Мария Орлова"


def test_requester_name_from_record_when_header_has_none():
    """FR-219: в заголовке имени нет — ФИО берётся из записи заявителя."""
    tickets = tickets_module()
    setup_desk()
    requester = sd.make_requester(new_email(), full_name="Запись Заявителя")
    created = new_ticket(tickets.MAIL, requester_email=requester.email, requester_name="")
    assert created.ticket.requester_name == "Запись Заявителя"


def test_requester_name_empty_and_interface_shows_address(django_capture_on_commit_callbacks):
    """FR-219: ни в письме, ни в записи ФИО нет — оно пусто, а карточка и подтверждение показывают адрес."""
    tickets = tickets_module()
    setup_desk()
    address = new_email()
    with django_capture_on_commit_callbacks(execute=True):
        created = new_ticket(tickets.MAIL, requester_email=address, requester_name="")
    ticket = created.ticket
    assert ticket.requester_name == "" and ticket.requester.full_name == ""
    doc = card(admin_all(), ticket.number)
    name_cells = find(doc, None, {"data-field": "requester-name"})
    assert name_cells and all(el.attrs.get("data-empty") == "true" for el in name_cells)
    shown = " ".join(el.text for el in find(doc, None, {"data-field": "requester-email"})
                     + find(doc, None, {"data-field": "requester"}))
    assert address in shown
    assert f"Здравствуйте, {address}!" in confirmation_text(created)


# --- FR-238: ответственный по умолчанию -------------------------------------------------------------------

def test_category_default_assignee_set_when_queue_member_status_in_progress_assigned_once(
        django_capture_on_commit_callbacks):
    """FR-238, FR-202: ответственный по умолчанию категории назначается при создании, если он участник очереди:
    `assigned_once`, статус «в работе», событие ленты и журнала `ticket.assigned`; в подтверждении назван
    исполнитель, отдельного письма «взята в работу» нет."""
    tickets = tickets_module()
    queue = setup_desk()
    person = support.make_employee(full_name="Петров Иван Сергеевич")
    support_org.make_member(person, queue.unit)
    category = sd.make_category(queue=queue, default_assignee=person)
    with django_capture_on_commit_callbacks(execute=True):
        created = new_ticket(tickets.FORM, category=category, consent_at=timezone.now())
    ticket = created.ticket
    assert ticket.assignee_id == person.pk and ticket.assigned_once is True
    assert ticket.kind == "in_progress" and ticket.status_id == status_of("in_progress").pk
    changed = feed_events(ticket, "assignee_changed")
    assert len(changed) == 1
    assert changed[0].data == {"before": "", "after": person.full_name, "before_id": None, "after_id": person.pk}
    assigned = journal("ticket.assigned", ticket.number)
    assert len(assigned) == 1 and assigned[0].actor is None
    assert assigned[0].before == {"assignee": "", "assignee_id": None}
    assert assigned[0].after == {"assignee": person.full_name, "assignee_id": person.pk}
    assert [m.template for m in sd.ticket_mails(ticket)] == ["ticket.confirmation"]
    assert "Исполнитель: Иван Петров." in confirmation_text(created)


def test_category_default_assignee_dropped_when_no_longer_member(django_capture_on_commit_callbacks):
    """FR-238: ответственный по умолчанию перестал быть участником очереди — заявка создаётся без ответственного
    (статус «новая», `assigned_once` ложен, события назначения нет, в подтверждении исполнителя нет)."""
    from apps.org.services import membership

    tickets = tickets_module()
    queue = setup_desk()
    person = support.make_employee(full_name="Петров Иван Сергеевич")
    support_org.make_member(person, queue.unit)
    category = sd.make_category(queue=queue, default_assignee=person)
    membership.remove_member(person, queue.unit, actor=support.make_admin())
    with django_capture_on_commit_callbacks(execute=True):
        created = new_ticket(tickets.FORM, category=category, consent_at=timezone.now())
    ticket = created.ticket
    assert ticket.assignee is None and ticket.assigned_once is False
    assert ticket.kind == "new" and ticket.status_id == status_of("new").pk
    assert not feed_events(ticket, "assignee_changed")
    assert not journal("ticket.assigned", ticket.number)
    assert "Исполнитель:" not in confirmation_text(created)


def test_mail_without_category_gets_no_default_assignee(django_capture_on_commit_callbacks):
    """FR-238: письмо без категории ответственного по умолчанию не получает и уходит в очередь по умолчанию."""
    tickets = tickets_module()
    default_queue = setup_desk()
    person = support.make_employee(full_name="Петров Иван Сергеевич")
    support_org.make_member(person, default_queue.unit)
    sd.make_category(queue=default_queue, default_assignee=person)
    with django_capture_on_commit_callbacks(execute=True):
        created = new_ticket(tickets.MAIL, category=None)
    ticket = created.ticket
    assert ticket.category is None and ticket.queue_id == default_queue.unit_id
    assert ticket.assignee is None and ticket.assigned_once is False and ticket.kind == "new"
    assert not journal("ticket.assigned", ticket.number)
    assert "Исполнитель:" not in confirmation_text(created)


# --- FR-227: согласие --------------------------------------------------------------------------------------

def test_form_consent_timestamp_saved_mail_and_staff_ticket_have_none():
    """FR-227: у заявки с формы сохраняется время согласия (в карточке — дата и время по Москве), у письма и заявки
    исполнителя отметки нет."""
    tickets = tickets_module()
    setup_desk()
    moment = datetime.datetime(2026, 3, 10, 12, 30, tzinfo=datetime.timezone.utc)
    form = new_ticket(tickets.FORM, consent_at=moment).ticket
    mail = new_ticket(tickets.MAIL).ticket
    staff = new_ticket(tickets.STAFF, category=sd.make_category()).ticket
    assert form.consent_at == moment
    assert mail.consent_at is None and staff.consent_at is None
    admin = admin_all()
    shown = find(card(admin, form.number), None, {"data-field": "consent"})
    assert len(shown) == 1 and "10.03.2026 15:30" in shown[0].text
    assert not find(card(admin, mail.number), None, {"data-field": "consent"})
    assert not find(card(admin, staff.number), None, {"data-field": "consent"})


# --- FR-205: продолжение -----------------------------------------------------------------------------------

def test_continuation_links_both_ways_and_event_in_previous_ticket():
    """FR-205: заявка-продолжение ссылается на закрытую прежнюю, а в ленте прежней — событие «продолжение»;
    карточки показывают ссылки в обе стороны."""
    from apps.servicedesk.services import closing

    setup_desk()
    admin = admin_all()
    old = new_ticket(category=sd.make_category()).ticket
    closing.close(old, status_of("closed"), "Решено", actor=admin)
    old.refresh_from_db()
    created = new_ticket(requester_email=old.requester_email, previous=old, category=sd.make_category())
    new = created.ticket
    assert new.previous_id == old.pk
    assert list(old.continuations.values_list("pk", flat=True)) == [new.pk]
    continued = feed_events(old, "continued")
    assert len(continued) == 1 and continued[0].data == {"number": new.number}
    forward = find(card(admin, new.number), "a", {"data-field": "previous", "href": f"/tickets/{old.number}/"})
    assert len(forward) == 1 and f"#{old.number}" in forward[0].text
    back = find(card(admin, old.number), "a", {"data-field": "continuation", "href": f"/tickets/{new.number}/"})
    assert len(back) == 1 and f"#{new.number}" in back[0].text


def test_continuation_link_hidden_from_user_without_access_to_target():
    """FR-205: права на прежнюю заявку не расширяются: тому, кто не видит целевую заявку, ссылка не показывается
    (остаётся текст без ссылки)."""
    from apps.servicedesk.services import closing

    setup_desk()
    admin = admin_all()
    queue_old, queue_new = sd.make_queue(), sd.make_queue()
    old = new_ticket(category=sd.make_category(queue=queue_old)).ticket
    closing.close(old, status_of("closed"), "Решено", actor=admin)
    old.refresh_from_db()
    new = new_ticket(requester_email=old.requester_email, previous=old,
                     category=sd.make_category(queue=queue_new)).ticket
    only_new, only_old = support.make_employee(), support.make_employee()
    support_org.make_member(only_new, queue_new.unit)
    support_org.make_member(only_old, queue_old.unit)

    doc = card(only_new, new.number)
    assert not find(doc, "a", {"href": f"/tickets/{old.number}/"})
    assert any(re.search(rf"#{old.number}(?!\d)", el.text) for el in find(doc, None, {"data-field": "previous"}))
    doc = card(only_old, old.number)
    assert not find(doc, "a", {"href": f"/tickets/{new.number}/"})
    assert any(re.search(rf"#{new.number}(?!\d)", el.text) for el in find(doc, None, {"data-field": "continuation"}))
    # у того, кто видит обе заявки, ссылки есть
    assert find(card(admin, new.number), "a", {"data-field": "previous", "href": f"/tickets/{old.number}/"})


# --- FR-254: нерабочее время (здесь разрешён `clock`, решение Opus A1) ---------------------------------------

def test_after_hours_phrase_at_night_and_on_holiday_with_next_working_start(
        clock, django_capture_on_commit_callbacks):
    """FR-254: заявка из письма или формы ночью, в праздник и вечером получает фразу о нерабочем времени с датой и
    временем ближайшего рабочего начала по Москве; `after_hours` из службы уходит в контекст задания письма."""
    tickets = tickets_module()
    setup_desk()
    seed_year(2026, {date(2026, 3, 11): "holiday"})
    cases = (
        (tickets.MAIL, (2026, 3, 10, 2, 0), "10.03.2026 09:00"),    # вторник, 02:00
        (tickets.FORM, (2026, 3, 11, 12, 0), "12.03.2026 09:00"),   # среда — праздник
        (tickets.MAIL, (2026, 3, 13, 19, 0), "16.03.2026 09:00"),   # пятница, 19:00 — после конца дня
    )
    for channel, moment, expected in cases:
        at_msk(clock, *moment)
        extra = {"consent_at": timezone.now()} if channel == tickets.FORM else {}
        with django_capture_on_commit_callbacks(execute=True):
            created = new_ticket(channel, **extra)
        assert created.after_hours == expected, (channel, moment)
        message, context = confirmation_of(created)
        assert context["after_hours"] == expected
        assert f"Заявка поступила в нерабочее время, мы рассмотрим её с {expected}" in sd.mail_text(message, context)


def test_after_hours_phrase_absent_in_working_time_and_for_staff_ticket(clock, django_capture_on_commit_callbacks):
    """FR-254: в рабочее время фразы нет; у заявки исполнителя её нет и ночью (`after_hours` — `None`)."""
    tickets = tickets_module()
    setup_desk()
    at_msk(clock, 2026, 3, 10, 11, 0)                 # вторник, рабочее время
    with django_capture_on_commit_callbacks(execute=True):
        working = new_ticket(tickets.MAIL)
    assert working.after_hours is None
    message, context = confirmation_of(working)
    assert context["after_hours"] is None
    assert "нерабочее время" not in sd.mail_text(message, context)

    at_msk(clock, 2026, 3, 10, 2, 0)                  # вторник, ночь
    with django_capture_on_commit_callbacks(execute=True):
        staff = new_ticket(tickets.STAFF, category=sd.make_category())
    assert staff.after_hours is None
    message, context = confirmation_of(staff)
    assert context["after_hours"] is None
    assert "нерабочее время" not in sd.mail_text(message, context)


def test_after_hours_phrase_unloaded_year_saturday_calendar_change_and_none_date(
        clock, django_capture_on_commit_callbacks):
    """FR-254: год календаря не загружен, суббота — действуют рабочие дни недели, фраза есть; после смены недели
    календаря новые заявки считаются по новым настройкам; если рабочего дня нет 400 суток вперёд, даты нет
    (`after_hours == ""`: «…мы рассмотрим её в ближайшее рабочее время», без даты — дополнение 6 раздела 16)."""
    from apps.org.services import calendar as calendar_service

    tickets = tickets_module()
    setup_desk()
    assert not model("org.CalendarYear").objects.filter(year=2026).exists()
    at_msk(clock, 2026, 3, 7, 14, 0)                  # суббота; год 2026 не загружен
    with django_capture_on_commit_callbacks(execute=True):
        saturday = new_ticket(tickets.MAIL)
    assert saturday.after_hours == "09.03.2026 09:00"
    message, context = confirmation_of(saturday)
    assert "мы рассмотрим её с 09.03.2026 09:00" in sd.mail_text(message, context)

    calendar_service.update_settings(work_weekdays=range(7), day_start=time(9, 0), day_end=time(18, 0),
                                     actor=support.make_admin())
    with django_capture_on_commit_callbacks(execute=True):
        after_change = new_ticket(tickets.MAIL)
    assert after_change.after_hours is None
    message, context = confirmation_of(after_change)
    assert context["after_hours"] is None and "нерабочее время" not in sd.mail_text(message, context)

    # ни одного рабочего дня больше чем на 400 суток вперёд: все дни — праздники в загруженных 2028 и 2029 годах
    start, end = date(2028, 3, 8), date(2029, 6, 1)
    days = {start + datetime.timedelta(days=n): "holiday" for n in range((end - start).days + 1)}
    seed_year(2028, {d: k for d, k in days.items() if d.year == 2028})
    seed_year(2029, {d: k for d, k in days.items() if d.year == 2029})
    at_msk(clock, 2028, 3, 8, 12, 0)
    with django_capture_on_commit_callbacks(execute=True):
        nowhere = new_ticket(tickets.MAIL)
    assert nowhere.after_hours == ""
    message, context = confirmation_of(nowhere)
    assert context["after_hours"] == ""
    text = sd.mail_text(message, context)
    assert "Заявка поступила в нерабочее время, мы рассмотрим её в ближайшее рабочее время." in text
    assert "мы рассмотрим её с " not in text


# --- FR-261, FR-204: замок записи заявителя ----------------------------------------------------------------

def test_requester_record_locked_with_select_for_update():
    """FR-261, FR-204: запись заявителя ищется под `select_for_update` (ночное обезличивание может удалять запись) —
    и когда записи ещё нет (её создаёт заявка), и когда она есть."""
    setup_desk()
    table = model("servicedesk.Requester")._meta.db_table
    existing = sd.make_requester(new_email())
    for address in (new_email(), existing.email):
        with CaptureQueriesContext(connection) as queries:
            created = new_ticket(requester_email=address)
        locking = [q["sql"] for q in queries if "FOR UPDATE" in q["sql"].upper() and f'"{table}"' in q["sql"]]
        assert locking, f"нет запроса FOR UPDATE по таблице {table} (адрес {address})"
        assert created.ticket.requester.email == address
