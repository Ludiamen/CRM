"""T-3122: заявка от исполнителя (FR-203, FR-228, FR-229, FR-230, FR-254). Сценарий 7 спеки среза 003.

Службы — `apps.servicedesk.services.executor` (CONTRACT-003 § 6.20) и `requesters` (§ 6.22); маршруты — § 12.3
(`/tickets/new/`, `/tickets/new/requester/`, `/tickets/new/queue/`); зацепки — § 13.2, 13.3, 13.6; тексты — § 14.
Код среза на уровне модуля не импортируется. Заявки создаются через маршрут или службу, а не фабрикой
`make_ticket`. Фикстуру `clock` берёт только один тест (час суток, решение Opus A1 и дополнение 8 раздела 16);
задание письма он читает (`job.meta`), но не исполняет. Помощники разметки и данных держатся внутри файла.
"""
import datetime
from html.parser import HTMLParser
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from tests import factories, support, support_org, support_servicedesk as sd
from tests.support import HX, model
from tests.support_mail import mail_jobs

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
CONSENT = "Отправляя заявку, вы согласны на обработку ваших персональных данных"


# --- разбор разметки ---------------------------------------------------------------------------------------

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


def doc_of(response) -> _Doc:
    return _Doc(response.content.decode("utf-8", "replace"))


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


def options(doc, name: str) -> list:
    """`option` выбора `select[name=<name>]`: список `(значение, выбран, текст)`."""
    selects = find(doc, "select", {"name": name})
    assert selects, f"нет select[name={name}]"
    return [(o.attrs.get("value", ""), "selected" in o.attrs, o.text)
            for o in doc.elements if o.tag == "option" and inside(o, selects[0])]


def selected_values(doc, name: str) -> list:
    return [value for value, chosen, _ in options(doc, name) if chosen]


def input_of(doc, name: str, kind: str | None = None):
    found = [e for e in find(doc, "input", {"name": name}) if kind is None or e.attrs.get("type") == kind]
    assert found, f"нет input[name={name}]"
    return found[0]


def alert_text(doc) -> str:
    return " ".join(el.text for el in find(doc, None, {"role": "alert"}))


def status_text(doc) -> str:
    return " ".join(el.text for el in find(doc, None, {"role": "status"}))


# --- данные теста -------------------------------------------------------------------------------------------

def new_email() -> str:
    return "ivan." + factories.new_email("req").split("@")[0].lower() + "@corp.test"


def unique_subject() -> str:
    return "Звонок " + factories.new_password()[:10]


def fresh(user):
    """Свежий объект пользователя: результат `access.scope` лежит в атрибуте объекта (контракт 6.3)."""
    return model("core.User").objects.get(pk=user.pk)


def source_named(name: str):
    return model("servicedesk.Source").objects.get(system_code="", name_key=support_org.name_key(name))


def priority_named(name: str):
    return model("servicedesk.Priority").objects.get(name_key=support_org.name_key(name))


def client_unit(name: str, **extra):
    return model("servicedesk.ClientUnit").objects.create(name=name, name_key=support_org.name_key(name), **extra)


def desk():
    """Две очереди (первая — по умолчанию), домен `corp.test`, по категории в каждой очереди."""
    queue_a, queue_b = sd.make_queue(), sd.make_queue()
    sd.configure_servicedesk(domains=["corp.test"], default_queue=queue_a)
    return SimpleNamespace(a=queue_a, b=queue_b, cat_a=sd.make_category(queue=queue_a),
                           cat_b=sd.make_category(queue=queue_b))


def member_of(queue, **extra):
    """Сотрудник — участник очереди (узла работы)."""
    user = support.make_employee(**extra)
    support_org.make_member(user, queue.unit)
    return user


def all_holder():
    """Держатель «Все заявки» без узла работы."""
    return support.make_with_permissions("servicedesk.all")


def qid(queue) -> int:
    return queue.unit_id if hasattr(queue, "unit_id") else queue.pk


def form_data(category, queue, /, **over) -> dict:
    data = {"email": new_email(), "name": "", "client_unit": "", "category": category.pk, "queue": qid(queue),
            "priority": "", "source": source_named("Телефон").pk, "subject": unique_subject(),
            "text": "Заявитель позвонил: не работает принтер"}
    data.update(over)
    return data


def post_new(user, data, *, files=(), hx=False, capture=None):
    """POST `/tickets/new/` от имени `user`; письма и шина — внутри `capture` (после фиксации)."""
    client = support.logged_in(user)
    payload = dict(data)
    if files:
        payload["files"] = list(files)
    extra = HX if hx else {}
    if capture is None:
        return client, client.post("/tickets/new/", payload, **extra)
    with capture(execute=True):
        return client, client.post("/tickets/new/", payload, **extra)


def tickets_count() -> int:
    return model("servicedesk.Ticket").objects.count()


def ticket_by(subject: str):
    return model("servicedesk.Ticket").objects.get(subject=subject)


def journal(action: str, number: int) -> list:
    return list(model("core.AuditEvent").objects.filter(
        action=action, object_type="ticket", object_id=str(number)).order_by("id"))


def confirmation_of(ticket):
    """Единственное письмо-подтверждение заявки и контекст его задания: `(MailMessage, dict)`."""
    messages = [m for m in sd.ticket_mails(ticket) if m.template == "ticket.confirmation"]
    assert len(messages) == 1, f"писем-подтверждений: {len(messages)}"
    jobs = [j for j in mail_jobs() if j.meta.get("context", {}).get("ticket_id") == ticket.pk]
    assert len(jobs) == 1, f"заданий подтверждения: {len(jobs)}"
    return messages[0], jobs[0].meta["context"]


def assert_field_refused(response, field: str, code: str, before: int):
    """Отказ поля: 200, `[data-error=<поле>]` с кодом, у поля общего `[role=alert]` в форме нет, заявок не прибавилось."""
    assert response.status_code == 200, f"{code}: статус {response.status_code}"
    doc = doc_of(response)
    assert find(doc, None, {"data-error": field, "data-code": code}), f"нет [data-error={field}][data-code={code}]"
    forms = find(doc, "form", {"data-form": "ticket-new"})
    assert forms, "после отказа форма заявки исполнителя должна остаться"
    assert not [e for e in find(doc, None, {"role": "alert"}) if inside(e, forms[0])], (
        f"{code}: у отказа поля общего [role=alert] быть не должно")
    assert tickets_count() == before, f"{code}: заявка создана"


def assert_alert_refused(response, code: str, before: int):
    """Общий отказ без поля: 200, `[role=alert]` и элемент с `data-code`, `[data-error]` нет, заявок не прибавилось."""
    assert response.status_code == 200, f"{code}: статус {response.status_code}"
    doc = doc_of(response)
    assert find(doc, None, {"role": "alert", "data-code": code}), (
        f"{code}: нет [role=alert] с data-code={code} у того же элемента")
    assert not find(doc, None, {"data-error": True}), f"{code}: общий отказ не должен писаться у поля"
    assert tickets_count() == before, f"{code}: заявка создана"


# --- кнопка «Новая заявка» и форма (FR-228) --------------------------------------------------------------------

def test_new_button_visible_to_queue_member():
    """FR-228: участнику очереди в списке видна кнопка `a[data-action="ticket-new"][href="/tickets/new/"]`,
    `executor.can_start` истинно, `/tickets/new/` отдаёт форму `form[data-form="ticket-new"]` со всеми полями §13.6
    (источник — только ручные, критичность — из настроек), у запроса НХ — фрагмент без `<html`."""
    from apps.servicedesk.services import executor

    d = desk()
    user = member_of(d.a)
    assert executor.can_start(fresh(user)) is True
    client = support.logged_in(user)
    listing = client.get("/tickets/")
    assert listing.status_code == 200
    assert find(doc_of(listing), "a", {"data-action": "ticket-new", "href": "/tickets/new/"})

    page = client.get("/tickets/new/")
    assert page.status_code == 200
    doc = doc_of(page)
    forms = find(doc, "form", {"data-form": "ticket-new"})
    assert len(forms) == 1 and forms[0].attrs.get("method", "").lower() == "post"
    assert forms[0].attrs.get("enctype") == "multipart/form-data"
    for name in ("email", "subject"):
        assert input_of(doc, name)
    assert find(doc, "textarea", {"name": "text"})
    assert input_of(doc, "files", "file") is not None and "multiple" in input_of(doc, "files", "file").attrs
    for name in ("category", "priority", "source"):
        assert find(doc, "select", {"name": name}), f"нет select[name={name}]"
    assert find(doc, None, {"data-requester-fields": True}) and find(doc, None, {"data-queue-fields": True})
    assert find(doc, "button", {"type": "submit"})
    fragment = client.get("/tickets/new/", **HX)
    assert fragment.status_code == 200 and b"<html" not in fragment.content
    assert find(doc_of(fragment), "form", {"data-form": "ticket-new"})


def test_new_button_visible_to_all_tickets_holder_without_queue_node():
    """FR-228, FR-233: держатель `servicedesk.all` без узла-очереди видит кнопку «Новая заявка», получает форму и
    может взять заявку себе в любой очереди (`can_start`, `can_take`)."""
    from apps.servicedesk.services import executor

    d = desk()
    holder = all_holder()
    assert executor.can_start(fresh(holder)) is True
    assert executor.can_take(fresh(holder), qid(d.a)) is True and executor.can_take(fresh(holder), qid(d.b)) is True
    client = support.logged_in(holder)
    listing = client.get("/tickets/")
    assert listing.status_code == 200
    assert find(doc_of(listing), "a", {"data-action": "ticket-new", "href": "/tickets/new/"})
    page = client.get("/tickets/new/")
    assert page.status_code == 200 and find(doc_of(page), "form", {"data-form": "ticket-new"})


def test_new_button_absent_and_route_403_for_non_member():
    """FR-228, FR-234, FR-236: сотрудник, который лишь ответственный по заявке чужой очереди, видит список без
    кнопки, а `/tickets/new/` отдаёт 403 и на GET, и на POST; заявка не создаётся, `can_start` ложно."""
    from apps.servicedesk.services import executor

    d = desk()
    outsider = support.make_employee()
    sd.make_ticket(queue=d.b, assignee=outsider)
    assert executor.can_start(fresh(outsider)) is False
    client = support.logged_in(outsider)
    listing = client.get("/tickets/")
    assert listing.status_code == 200
    assert not find(doc_of(listing), "a", {"data-action": "ticket-new"})
    before = tickets_count()
    assert client.get("/tickets/new/").status_code == 403
    assert client.post("/tickets/new/", form_data(d.cat_b, d.b)).status_code == 403
    assert tickets_count() == before


# --- подстановка по адресу (FR-229) -----------------------------------------------------------------------------

def test_requester_lookup_post_fills_name_and_department_for_known_address():
    """FR-229: POST адреса известного заявителя даёт фрагмент `[data-requester-fields]` с ФИО и выбранным
    подразделением; запись находится и по адресу в другом регистре с пробелами; архивное подразделение записи
    в подсказку не подставляется."""
    from apps.servicedesk.services import requesters

    d = desk()
    unit = client_unit("Бухгалтерия")
    known = new_email()
    sd.make_requester(known, full_name="Петров Иван Сергеевич", client_unit=unit)
    client = support.logged_in(member_of(d.a))
    for sent in (known, f"  {known.upper()} "):
        response = client.post("/tickets/new/requester/", {"email": sent}, **HX)
        assert response.status_code == 200 and b"<html" not in response.content
        doc = doc_of(response)
        assert find(doc, None, {"data-requester-fields": True})
        assert input_of(doc, "name").attrs.get("value") == "Петров Иван Сергеевич"
        assert selected_values(doc, "client_unit") == [str(unit.pk)]
    hint = requesters.lookup(known)
    assert hint.found is True and hint.name == "Петров Иван Сергеевич" and hint.client_unit_id == unit.pk

    archived = client_unit("Старый отдел")
    other = new_email()
    sd.make_requester(other, full_name="Сидорова Анна", client_unit=archived)
    model("servicedesk.ClientUnit").objects.filter(pk=archived.pk).update(archived=True)
    hint = requesters.lookup(other)
    assert hint.client_unit_id is None
    assert hint.found is True and hint.name == "Сидорова Анна"
    doc = doc_of(client.post("/tickets/new/requester/", {"email": other}, **HX))
    assert input_of(doc, "name").attrs.get("value") == "Сидорова Анна"
    assert str(archived.pk) not in selected_values(doc, "client_unit")


def test_requester_lookup_empty_for_unknown_incomplete_or_foreign_address():
    """FR-229, FR-268: неизвестный, неполный (в том числе начало настоящего адреса) и чужой по домену адрес — всегда
    200 и пустые ФИО и подразделение; поиск идёт по одному полному корпоративному адресу, без подсказок."""
    from apps.servicedesk.services import requesters

    d = desk()
    unit = client_unit("Склад")
    sd.make_requester("petrov@corp.test", full_name="Петров Пётр", client_unit=unit)
    sd.make_requester("petrov@other.test", full_name="Чужой Петров", client_unit=unit)
    client = support.logged_in(member_of(d.a))
    cases = ("nobody@corp.test", "petrov", "petr", "petrov@", "@corp.test", "petrov@corp", "petrov@other.test",
             "not an address", "")
    for sent in cases:
        response = client.post("/tickets/new/requester/", {"email": sent}, **HX)
        assert response.status_code == 200, sent
        doc = doc_of(response)
        assert find(doc, None, {"data-requester-fields": True}), sent
        assert input_of(doc, "name").attrs.get("value", "") == "", sent
        assert selected_values(doc, "client_unit") in ([], [""]), sent
        hint = requesters.lookup(sent)
        assert hint.found is False and hint.name == "" and hint.client_unit_id is None, sent


def test_requester_lookup_address_in_body_not_in_url_no_suggestions():
    """FR-229, FR-268: адрес идёт в теле запроса: у поля формы `hx-post="/tickets/new/requester/"`, цель
    `[data-requester-fields]`, срабатывание `change`; путь запроса адреса не содержит; в ответе нет чужих
    заявителей и списков (`datalist`); адрес в строке запроса (GET) ФИО не подставляет."""
    d = desk()
    known = new_email()
    sd.make_requester(known, full_name="Громов Артём")
    for name, address in (("Андреев Антон", "anton@corp.test"), ("Анохина Анна", "anna@corp.test")):
        sd.make_requester(address, full_name=name)
    client = support.logged_in(member_of(d.a))
    page = doc_of(client.get("/tickets/new/"))
    field = input_of(page, "email")
    assert field.attrs.get("hx-post") == "/tickets/new/requester/"
    assert "[data-requester-fields]" in field.attrs.get("hx-target", "")
    assert field.attrs.get("hx-trigger", "").startswith("change")
    assert not field.attrs.get("hx-get") and not field.attrs.get("list")

    response = client.post("/tickets/new/requester/", {"email": known}, **HX)
    assert known not in response.wsgi_request.get_full_path() and "?" not in response.wsgi_request.get_full_path()
    assert "Громов Артём" in response.content.decode()
    partial = client.post("/tickets/new/requester/", {"email": "an"}, **HX)
    body = partial.content.decode()
    assert partial.status_code == 200
    for leaked in ("anton@corp.test", "anna@corp.test", "Андреев Антон", "Анохина Анна"):
        assert leaked not in body
    assert "<datalist" not in body
    via_url = client.get(f"/tickets/new/requester/?email={known}", **HX)
    assert via_url.status_code == 405
    assert "Громов Артём" not in via_url.content.decode()


def test_requester_lookup_forbidden_for_non_member():
    """FR-228, FR-229: не участнику очередей `/tickets/new/requester/` (POST) и `/tickets/new/queue/` (GET) дают 403,
    одинаково для известного и неизвестного адреса; ФИО записи в ответе нет."""
    d = desk()
    known = new_email()
    sd.make_requester(known, full_name="Громов Артём")
    outsider = support.make_employee()
    sd.make_ticket(queue=d.b, assignee=outsider)
    client = support.logged_in(outsider)
    known_answer = client.post("/tickets/new/requester/", {"email": known}, **HX)
    unknown_answer = client.post("/tickets/new/requester/", {"email": "nobody@corp.test"}, **HX)
    assert known_answer.status_code == 403 and unknown_answer.status_code == 403
    assert "Громов Артём" not in known_answer.content.decode()
    assert client.get(f"/tickets/new/queue/?category={d.cat_b.pk}", **HX).status_code == 403


def test_lookup_fields_editable_and_department_change_updates_record():
    """FR-229, RB1-14: подставленные ФИО и подразделение можно изменить: заявка получает то, что ввёл исполнитель;
    подразделение пишется и в запись заявителя (пустое значение стирает его там), непустое ФИО записи не
    перезаписывается."""
    d = desk()
    old_unit, new_unit = client_unit("Склад"), client_unit("Логистика")
    address = new_email()
    record = sd.make_requester(address, full_name="Петров Иван", client_unit=old_unit)
    user = member_of(d.a)
    subject = unique_subject()
    _, response = post_new(user, form_data(d.cat_a, d.a, email=address, name="Иван Петров-Сидоров",
                                           client_unit=new_unit.pk, subject=subject))
    assert response.status_code == 302
    ticket = ticket_by(subject)
    assert ticket.requester_name == "Иван Петров-Сидоров" and ticket.client_unit_id == new_unit.pk
    record.refresh_from_db()
    assert record.client_unit_id == new_unit.pk and record.full_name == "Петров Иван"

    subject = unique_subject()
    _, response = post_new(user, form_data(d.cat_a, d.a, email=address, client_unit="", subject=subject))
    assert response.status_code == 302
    ticket = ticket_by(subject)
    assert ticket.client_unit_id is None and ticket.requester_name == "Петров Иван"
    record.refresh_from_db()
    assert record.client_unit_id is None


# --- «Взять себе» (FR-228, FR-230) ---------------------------------------------------------------------------------

def _take_state(doc):
    box = input_of(doc, "take", "checkbox")
    return "checked" in box.attrs, "disabled" in box.attrs


def test_take_to_self_fragment_enabled_only_for_member_of_selected_queue():
    """FR-228, сценарий 7.5: фрагмент `/tickets/new/queue/` при очереди, где заводящий участник, даёт флажок «Взять
    себе» включённым и доступным; при чужой очереди — без `checked` и с `disabled`; выбранная очередь — из запроса."""
    from apps.servicedesk.services import executor

    d = desk()
    user = member_of(d.a)
    assert executor.can_take(fresh(user), qid(d.a)) is True and executor.can_take(fresh(user), qid(d.b)) is False
    client = support.logged_in(user)
    own = client.get(f"/tickets/new/queue/?category={d.cat_b.pk}&queue={qid(d.a)}", **HX)
    assert own.status_code == 200 and b"<html" not in own.content
    own_doc = doc_of(own)
    assert find(own_doc, None, {"data-queue-fields": True})
    assert selected_values(own_doc, "queue") == [str(qid(d.a))]
    assert _take_state(own_doc) == (True, False)
    foreign = doc_of(client.get(f"/tickets/new/queue/?category={d.cat_a.pk}&queue={qid(d.b)}", **HX))
    assert selected_values(foreign, "queue") == [str(qid(d.b))]
    assert _take_state(foreign) == (False, True)


def test_take_to_self_enabled_for_all_tickets_holder_in_any_queue():
    """FR-228, FR-233, сценарий 7.9: у держателя «Все заявки» флажок «Взять себе» включён и доступен в любой
    очереди, хотя узла работы у него нет."""
    d = desk()
    client = support.logged_in(all_holder())
    for queue in (d.a, d.b):
        doc = doc_of(client.get(f"/tickets/new/queue/?category={d.cat_a.pk}&queue={qid(queue)}", **HX))
        assert selected_values(doc, "queue") == [str(qid(queue))]
        assert _take_state(doc) == (True, False), qid(queue)


def test_post_take_to_self_by_non_member_creates_without_assignee_or_with_category_default(
        django_capture_on_commit_callbacks):
    """FR-228, сценарий 7.5, B1-6: `take` у не участника выбранной очереди молча игнорируется: заявка создаётся без
    ответственного (статус «новая»), а при ответственном по умолчанию категории — с ним (статус «в работе»);
    подтверждение одно, письма «взята в работу» нет."""
    d = desk()
    user = member_of(d.a)
    subject = unique_subject()
    _, response = post_new(user, form_data(d.cat_b, d.b, subject=subject, take="1"),
                           capture=django_capture_on_commit_callbacks)
    assert response.status_code == 302
    ticket = ticket_by(subject)
    assert ticket.queue_id == qid(d.b) and ticket.assignee_id is None
    assert ticket.kind == "new" and ticket.assigned_once is False
    assert [m.template for m in sd.ticket_mails(ticket)] == ["ticket.confirmation"]

    person = member_of(d.b)
    category = sd.make_category(queue=d.b, default_assignee=person)
    subject = unique_subject()
    _, response = post_new(user, form_data(category, d.b, subject=subject, take="1"),
                           capture=django_capture_on_commit_callbacks)
    assert response.status_code == 302
    ticket = ticket_by(subject)
    assert ticket.assignee_id == person.pk and ticket.kind == "in_progress" and ticket.assigned_once is True
    assert [m.template for m in sd.ticket_mails(ticket)] == ["ticket.confirmation"]


def test_take_to_self_makes_assignee_in_progress_and_single_confirmation_with_name(
        django_capture_on_commit_callbacks):
    """FR-230, FR-253, FR-255, сценарий 7.2: «Взять себе» делает исполнителя ответственным, статус «в работе»; письмо
    одно — подтверждение со строкой «Исполнитель: Имя Фамилия» (правило C5); `ticket.assigned` в журнале с `before`
    `{"assignee": "", "assignee_id": None}`, событие ленты `assignee_changed` (дополнение 7 раздела 16)."""
    d = desk()
    user = member_of(d.a, full_name="Петров Иван Сергеевич")
    subject = unique_subject()
    _, response = post_new(user, form_data(d.cat_a, d.a, subject=subject, take="1"),
                           capture=django_capture_on_commit_callbacks)
    assert response.status_code == 302
    ticket = ticket_by(subject)
    assert ticket.assignee_id == user.pk and ticket.kind == "in_progress" and ticket.assigned_once is True
    assert ticket.status.kind == "in_progress"

    assert [m.template for m in sd.ticket_mails(ticket)] == ["ticket.confirmation"]
    message, context = confirmation_of(ticket)
    assert "Исполнитель: Иван Петров" in " ".join(sd.mail_text(message, context).split())

    events = list(ticket.entries.filter(kind="event", event="assignee_changed"))
    assert len(events) == 1
    assert events[0].data["before"] == "" and events[0].data["after"] == user.full_name
    assert events[0].data["before_id"] is None and events[0].data["after_id"] == user.pk
    assigned = journal("ticket.assigned", ticket.number)
    assert len(assigned) == 1 and assigned[0].actor == user
    assert assigned[0].before == {"assignee": "", "assignee_id": None}
    assert assigned[0].after == {"assignee": user.full_name, "assignee_id": user.pk}
    assert len(journal("ticket.created", ticket.number)) == 1


# --- категория и очередь (FR-228) ------------------------------------------------------------------------------------

def test_category_substitutes_queue_and_queue_can_be_changed_to_any_marked(django_capture_on_commit_callbacks):
    """FR-228, сценарий 7.4: категория подставляет свою очередь (у «Другое» — очередь по умолчанию), в выборе очереди
    только отмеченные узлы; исполнитель меняет очередь на любую отмеченную, и заявка уходит именно туда."""
    from apps.servicedesk.services import executor
    from apps.servicedesk.services.errors import ServiceDeskError

    d = desk()
    unmarked = support_org.make_unit()
    other = model("servicedesk.Category").objects.get(is_system=True)
    assert executor.queue_for_category(d.cat_b.pk) == qid(d.b)
    assert executor.queue_for_category(other.pk) == qid(d.a)
    archived = sd.make_category(queue=d.b, archived=True)
    with pytest.raises(ServiceDeskError) as caught:
        executor.queue_for_category(archived.pk)
    assert caught.value.code == "archived_value"

    user = member_of(d.a)
    client = support.logged_in(user)
    by_category = doc_of(client.get(f"/tickets/new/queue/?category={d.cat_b.pk}", **HX))
    assert selected_values(by_category, "queue") == [str(qid(d.b))]
    offered = {value for value, _, _ in options(by_category, "queue") if value}
    assert {str(qid(d.a)), str(qid(d.b))} <= offered and str(unmarked.pk) not in offered
    by_other = doc_of(client.get(f"/tickets/new/queue/?category={other.pk}", **HX))
    assert selected_values(by_other, "queue") == [str(qid(d.a))]
    changed = doc_of(client.get(f"/tickets/new/queue/?category={d.cat_b.pk}&queue={qid(d.a)}", **HX))
    assert selected_values(changed, "queue") == [str(qid(d.a))]

    for category, queue in ((d.cat_b, d.b), (d.cat_b, d.a)):
        subject = unique_subject()
        _, response = post_new(user, form_data(category, queue, subject=subject),
                               capture=django_capture_on_commit_callbacks)
        assert response.status_code == 302
        assert ticket_by(subject).queue_id == qid(queue) and ticket_by(subject).category_id == category.pk

    model("servicedesk.ServiceDeskSettings").objects.update(default_queue=None)
    with pytest.raises(ServiceDeskError) as caught:
        executor.queue_for_category(other.pk)
    assert caught.value.code == "no_queue"


# --- отказы (FR-228) ---------------------------------------------------------------------------------------------------

def test_non_corporate_address_refused():
    """FR-228, сценарий 7.3: адрес неверного формата, чужого домена и длиннее 254 знаков — отказ `bad_email` у поля
    `email` с текстом «Укажите рабочую почту на корпоративном домене», заявка и запись заявителя не создаются;
    `requesters.normalize_email` отдаёт строчный адрес без пробелов или поднимает `bad_email`."""
    from apps.servicedesk.services import requesters
    from apps.servicedesk.services.errors import ServiceDeskError

    d = desk()
    user = member_of(d.a)
    before, records = tickets_count(), model("servicedesk.Requester").objects.count()
    for bad in ("ivanov@other.test", "ivanov", "ivanov@", "a" * 250 + "@corp.test"):
        _, response = post_new(user, form_data(d.cat_a, d.a, email=bad))
        assert_field_refused(response, "email", "bad_email", before)
        shown = " ".join(e.text for e in find(doc_of(response), None, {"data-error": "email"}))
        assert "Укажите рабочую почту на корпоративном домене" in shown
        assert model("servicedesk.Requester").objects.count() == records
    assert requesters.normalize_email("  Ivanov@Corp.Test ") == "ivanov@corp.test"
    for bad in ("ivanov@other.test", "ivanov"):
        with pytest.raises(ServiceDeskError) as caught:
            requesters.normalize_email(bad)
        assert caught.value.code == "bad_email"


def test_empty_domain_list_refuses_creation():
    """FR-228, FR-213, сценарий 7.3: пока список доменов пуст, заявку не завести и исполнителю: `intake_closed`
    общим `[role=alert]` (не у поля), в том числе при верном адресе; заявка и запись не создаются."""
    from apps.servicedesk.services import executor
    from apps.servicedesk.services.errors import ServiceDeskError

    d = desk()
    sd.configure_servicedesk(domains=[])
    user = member_of(d.a)
    before, records = tickets_count(), model("servicedesk.Requester").objects.count()
    _, response = post_new(user, form_data(d.cat_a, d.a))
    assert_alert_refused(response, "intake_closed", before)
    assert model("servicedesk.Requester").objects.count() == records
    with pytest.raises(ServiceDeskError) as caught:
        executor.create(actor=fresh(user), email=new_email(), category_id=d.cat_a.pk, queue_id=qid(d.a),
                        source_id=source_named("Телефон").pk, subject="Тема", text="Текст")
    assert caught.value.code == "intake_closed"


def test_required_fields_refused_and_name_optional():
    """FR-228, FR-219: тема, описание, категория и очередь обязательны, длины ограничены (тема — 255, описание —
    50 000, ФИО — 255); каждый отказ — у своего поля с кодом, заявка не создаётся; ФИО необязательно: заявка с пустым
    ФИО создаётся, а тема в 255 знаков проходит."""
    d = desk()
    user = member_of(d.a)
    before = tickets_count()
    cases = (
        ("subject", "subject_required", {"subject": ""}),
        ("subject", "subject_too_long", {"subject": "т" * 256}),
        ("text", "description_required", {"text": ""}),
        ("text", "description_too_long", {"text": "о" * 50001}),
        ("category", "category_required", {"category": ""}),
        ("queue", "queue_required", {"queue": ""}),
        ("name", "requester_name_too_long", {"name": "ф" * 256}),
    )
    for field, code, over in cases:
        _, response = post_new(user, form_data(d.cat_a, d.a, **over))
        assert_field_refused(response, field, code, before)
    subject = "т" * 255
    _, response = post_new(user, form_data(d.cat_a, d.a, name="", subject=subject))
    assert response.status_code == 302
    ticket = ticket_by(subject)
    assert ticket.requester_name == "" and ticket.subject == subject
    assert tickets_count() == before + 1


def test_queue_must_be_marked_and_other_values_unarchived():
    """FR-228: очередь — только отмеченный узел (`not_queue` у поля `queue`, в том числе для нечислового значения);
    архивные категория, подразделение и критичность — `archived_value` общим `[role=alert]` без поля (12.3);
    заявка не создаётся."""
    d = desk()
    user = member_of(d.a)
    before = tickets_count()
    unmarked = support_org.make_unit()
    _, response = post_new(user, form_data(d.cat_a, unmarked))
    assert_field_refused(response, "queue", "not_queue", before)
    _, response = post_new(user, form_data(d.cat_a, d.a, queue="abc"))
    assert_field_refused(response, "queue", "not_queue", before)

    archived_category = sd.make_category(queue=d.a, archived=True)
    archived_unit = client_unit("Закрытый отдел", archived=True)
    archived_priority = model("servicedesk.Priority").objects.create(
        name="Срочная", name_key=support_org.name_key("Срочная"), order=40, archived=True)
    for over, category in (({}, archived_category), ({"client_unit": archived_unit.pk}, d.cat_a),
                           ({"priority": archived_priority.pk}, d.cat_a)):
        _, response = post_new(user, form_data(category, d.a, **over))
        assert_alert_refused(response, "archived_value", before)
    _, response = post_new(user, form_data(d.cat_a, d.a))
    assert response.status_code == 302 and tickets_count() == before + 1


def test_manual_source_only_non_system_and_unarchived():
    """FR-228: источник — только ручной неархивный: в `select[name=source]` нет «Почта», «Форма» и архивных; системный,
    архивный или пустой источник — `source_required` у поля `source` (а не `archived_value`); «Телефон» и «Лично»
    проходят."""
    from apps.servicedesk.services import dictionaries

    d = desk()
    user = member_of(d.a)
    Source = model("servicedesk.Source")
    old = Source.objects.create(name="Старый канал", name_key=support_org.name_key("Старый канал"),
                                system_code="", order=50, archived=True)
    client = support.logged_in(user)
    doc = doc_of(client.get("/tickets/new/"))
    offered = {value for value, _, _ in options(doc, "source") if value}
    expected = {str(s.pk) for s in Source.objects.filter(system_code="", archived=False)}
    assert offered == expected and str(old.pk) not in offered
    assert {s.pk for s in dictionaries.manual_sources()} == {int(v) for v in expected}
    assert str(source_named("Телефон").pk) in offered and str(source_named("Лично").pk) in offered

    before = tickets_count()
    for refused in (Source.objects.get(system_code="mail").pk, Source.objects.get(system_code="form").pk,
                    old.pk, ""):
        _, response = post_new(user, form_data(d.cat_a, d.a, source=refused))
        assert_field_refused(response, "source", "source_required", before)
    for allowed in ("Телефон", "Лично"):
        _, response = post_new(user, form_data(d.cat_a, d.a, source=source_named(allowed).pk))
        assert response.status_code == 302
    assert tickets_count() == before + 2


def test_source_and_created_by_in_card_and_audit(django_capture_on_commit_callbacks):
    """FR-228, FR-288, сценарий 7.6: в карточке источник — выбранный («Лично»), автор первого элемента `incoming`
    ленты — создавший исполнитель (`[data-author]`, `staff`, ФИО целиком); в журнале `ticket.created` — исполнитель
    как автор, канал `staff`, источник, `created_by` и `created_by_id`."""
    d = desk()
    user = member_of(d.a, full_name="Орлов Павел Андреевич")
    subject = unique_subject()
    _, response = post_new(user, form_data(d.cat_a, d.a, subject=subject, source=source_named("Лично").pk),
                           capture=django_capture_on_commit_callbacks)
    assert response.status_code == 302
    ticket = ticket_by(subject)
    assert ticket.source.name == "Лично"
    page = support.logged_in(user).get(f"/tickets/{ticket.number}/")
    assert page.status_code == 200
    doc = doc_of(page)
    source = find(doc, None, {"data-field": "source"})
    assert source and "Лично" in source[0].text
    incoming = [li for li in find(doc, "li", {"data-kind": "incoming"})]
    assert len(incoming) == 1
    authors = [e for e in find(doc, None, {"data-author": True}) if inside(e, incoming[0])]
    assert authors and authors[0].attrs.get("data-author-kind") == "staff" and user.full_name in authors[0].text

    events = journal("ticket.created", ticket.number)
    assert len(events) == 1 and events[0].actor == user
    after = events[0].after
    assert after["channel"] == "staff" and after["source"] == "Лично"
    assert after["created_by"] == user.full_name and after["created_by_id"] == user.pk
    assert after["queue_id"] == qid(d.a) and after["number"] == ticket.number


def test_criticality_default_from_settings_and_changeable():
    """FR-203, FR-228, сценарий 7.10: в форме выбрана критичность по умолчанию из настроек (после смены настройки —
    новая, не зашитая «Средняя»); без выбора заявка получает её; выбранная исполнителем критичность сохраняется."""
    d = desk()
    high, low = priority_named("Высокая"), priority_named("Низкая")
    user = member_of(d.a)
    sd.configure_servicedesk(default_priority=high)
    client = support.logged_in(user)
    doc = doc_of(client.get("/tickets/new/"))
    assert selected_values(doc, "priority") == [str(high.pk)]
    assert {value for value, _, _ in options(doc, "priority")} >= {str(low.pk), str(high.pk)}

    subject = unique_subject()
    _, response = post_new(user, form_data(d.cat_a, d.a, subject=subject, priority=""))
    assert response.status_code == 302 and ticket_by(subject).priority_id == high.pk
    subject = unique_subject()
    _, response = post_new(user, form_data(d.cat_a, d.a, subject=subject, priority=low.pk))
    assert response.status_code == 302 and ticket_by(subject).priority_id == low.pk
    assert journal("ticket.created", ticket_by(subject).number)[0].after["priority"] == "Низкая"


# --- подтверждение заявителю (FR-230, FR-254) -----------------------------------------------------------------------------

def test_confirmation_has_consent_line_and_no_off_hours_phrase(clock, django_capture_on_commit_callbacks):
    """FR-230, FR-254, сценарий 7.11: подтверждение заявки исполнителя содержит ту же строку о согласии на обработку
    ПДн и просьбу ответить на письмо; фразы о нерабочем времени нет ни в рабочий час, ни ночью (`after_hours` —
    `None`); заголовок `Auto-Submitted: auto-generated`. Здесь разрешён `clock` (решение A1), задание только читается."""
    from apps.servicedesk.services import executor

    d = desk()
    user = member_of(d.a)
    for moment in ((2026, 3, 10, 11, 0), (2026, 3, 10, 2, 0)):
        clock.set(datetime.datetime(*moment, tzinfo=MSK))
        with django_capture_on_commit_callbacks(execute=True):
            result = executor.create(actor=fresh(user), email=new_email(), category_id=d.cat_a.pk,
                                     queue_id=qid(d.a), source_id=source_named("Телефон").pk,
                                     subject=unique_subject(), text="Звонок с просьбой")
        assert result.created.after_hours is None, moment
        message, context = confirmation_of(result.created.ticket)
        assert context["after_hours"] is None, moment
        text = " ".join(sd.mail_text(message, context).split())
        assert CONSENT in text and "ответьте на это письмо" in text, moment
        assert "нерабочее время" not in text and "в ближайшее рабочее время" not in text, moment
        assert message.auto_submitted == "auto-generated"


def test_confirmation_has_no_cc_participants(django_capture_on_commit_callbacks):
    """FR-230: подтверждение заявки исполнителя идёт только заявителю, копии нет — даже если у заявки уже есть
    участники из копии (`recipients`: копия подтверждения пуста)."""
    from apps.servicedesk.services import executor, letters

    d = desk()
    user = member_of(d.a)
    address = new_email()
    with django_capture_on_commit_callbacks(execute=True):
        result = executor.create(actor=fresh(user), email=address, category_id=d.cat_a.pk, queue_id=qid(d.a),
                                 source_id=source_named("Телефон").pk, subject=unique_subject(), text="Звонок")
    ticket = result.created.ticket
    messages = [m for m in sd.ticket_mails(ticket) if m.template == "ticket.confirmation"]
    assert len(messages) == 1 and messages[0].to == address and messages[0].cc == ""
    sd.make_participant(ticket, "copy@corp.test", name="Копия")
    to, cc = letters.recipients(ticket, "ticket.confirmation")
    assert to == address and list(cc) == []


# --- переход после создания (FR-228) ----------------------------------------------------------------------------------------

def test_non_member_redirected_to_list_with_created_message(django_capture_on_commit_callbacks):
    """FR-228, FR-236, FR-239, сценарий 7.8: заявка в очереди, где исполнитель не участник, ему не видна: 302 на
    `/tickets/`, на странице `[role=status]` «Заявка #N создана в очереди «…»», карточка по номеру — 404; для
    запроса НХ — 200 с `HX-Redirect` на `/tickets/`; `visible` службы ложно."""
    from apps.servicedesk.services import executor

    d = desk()
    user = member_of(d.a)
    subject = unique_subject()
    client, response = post_new(user, form_data(d.cat_b, d.b, subject=subject),
                                capture=django_capture_on_commit_callbacks)
    assert response.status_code == 302 and response["Location"] == "/tickets/"
    ticket = ticket_by(subject)
    listing = client.get("/tickets/")
    assert f"Заявка #{ticket.number} создана в очереди «{d.b.unit.name}»" in status_text(doc_of(listing))
    assert client.get(f"/tickets/{ticket.number}/").status_code == 404

    _, hx_response = post_new(user, form_data(d.cat_b, d.b), hx=True, capture=django_capture_on_commit_callbacks)
    assert hx_response.status_code == 200 and hx_response["HX-Redirect"] == "/tickets/"
    result = executor.create(actor=fresh(user), email=new_email(), category_id=d.cat_b.pk, queue_id=qid(d.b),
                             source_id=source_named("Телефон").pk, subject=unique_subject(), text="Звонок")
    assert result.visible is False


def test_member_with_visible_ticket_redirected_to_card(django_capture_on_commit_callbacks):
    """FR-228, сценарий 7.1: видимая исполнителю заявка (его очередь; держатель «Все заявки» видит любую) —
    302 на `/tickets/<номер>/`, для запроса НХ — `HX-Redirect` туда же; `visible` службы истинно, карточка открывается."""
    from apps.servicedesk.services import executor

    d = desk()
    for user, queue, category in ((member_of(d.a), d.a, d.cat_a), (all_holder(), d.b, d.cat_b)):
        subject = unique_subject()
        client, response = post_new(user, form_data(category, queue, subject=subject),
                                    capture=django_capture_on_commit_callbacks)
        ticket = ticket_by(subject)
        assert response.status_code == 302 and response["Location"] == f"/tickets/{ticket.number}/"
        assert client.get(response["Location"]).status_code == 200
        subject = unique_subject()
        _, hx_response = post_new(user, form_data(category, queue, subject=subject), hx=True,
                                  capture=django_capture_on_commit_callbacks)
        assert hx_response.status_code == 200
        assert hx_response["HX-Redirect"] == f"/tickets/{ticket_by(subject).number}/"
        result = executor.create(actor=fresh(user), email=new_email(), category_id=category.pk, queue_id=qid(queue),
                                 source_id=source_named("Телефон").pk, subject=unique_subject(), text="Звонок")
        assert result.visible is True


# --- вложения (FR-228) ------------------------------------------------------------------------------------------------------------

def test_attachments_with_unacceptable_file_refuse_creation():
    """FR-228, FR-285: исполняемый файл — отказ `file_rejected` общим `[role=alert]` («не принят» и имя файла), больше
    10 файлов — `too_many_files`; заявка, запись заявителя и сохранённые файлы не создаются."""
    d = desk()
    user = member_of(d.a)
    StoredFile = model("core.StoredFile")
    before, records, stored = tickets_count(), model("servicedesk.Requester").objects.count(), StoredFile.objects.count()
    bad = SimpleUploadedFile("run.exe", sd.sample("exe_pe.bin"), content_type="application/octet-stream")
    good = SimpleUploadedFile("note.txt", b"hello", content_type="text/plain")
    _, response = post_new(user, form_data(d.cat_a, d.a), files=[good, bad])
    assert_alert_refused(response, "file_rejected", before)
    text = alert_text(doc_of(response))
    assert "не принят" in text and "run.exe" in text

    many = [SimpleUploadedFile(f"f{n}.txt", b"x", content_type="text/plain") for n in range(11)]
    _, response = post_new(user, form_data(d.cat_a, d.a), files=many)
    assert_alert_refused(response, "too_many_files", before)
    assert model("servicedesk.Requester").objects.count() == records
    assert StoredFile.objects.count() == stored
