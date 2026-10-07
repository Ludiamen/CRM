"""T-3121: открытая форма `/request/` (FR-203, FR-213, FR-222…227, FR-238, FR-255, NFR-205). Сценарий 2 спеки.

Служба — `apps.servicedesk.services.form` (CONTRACT-003 § 6.19), маршруты — § 12.1, зацепки — § 13.6, тексты — § 14.1–14.2,
ключ порога в Valkey — § 7.4, подмена Valkey — § 3.5 (одна точка: `apps.core.services.valkey.conn`). Настройки Django
(`SERVICEDESK_MAILBOX`, `TRUSTED_PROXIES`) тест меняет фикстурой `settings` (дополнение 5 раздела 16). Порог — настоящий
Valkey; время — `timezone.now()`; помощники страницы и чтения держатся внутри файла.
"""
import logging
import re
import time
from html.parser import HTMLParser

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from tests import support, support_org, support_servicedesk as sd
from tests.support import model
from tests.support_mail import mail_jobs

pytestmark = pytest.mark.django_db

MAILBOX = "tickets@stand.test"
IP = "198.51.100.31"
SESSION_KEY = "servicedesk_form_done"
CLOSED_TEXT = "Приём заявок через форму сейчас закрыт"
RATE_TEXT = "С вашего адреса отправлено слишком много заявок за час"
MB = 1024 * 1024


@pytest.fixture(autouse=True)
def mailbox_address(settings):
    """Адрес ящика заявок берётся из настроек Django (CONTRACT-003 § 6.6, `mailbox_address`)."""
    settings.SERVICEDESK_MAILBOX = MAILBOX


# --- помощники файла: настройка, запросы, чтение ----------------------------------------------------------

def form_module():
    from apps.servicedesk.services import form

    return form


def open_desk(domains=("corp.test",)):
    """Приём открыт: домены и очередь по умолчанию; категория формы со своей очередью. -> (очередь по умолчанию, категория)."""
    default_queue = sd.make_queue()
    sd.configure_servicedesk(domains=list(domains), default_queue=default_queue)
    return default_queue, sd.make_category("Принтеры", on_form=True)


def client_unit(name: str, *, archived: bool = False):
    return model("servicedesk.ClientUnit").objects.create(
        name=name, name_key=support_org.name_key(name), archived=archived)


def valid_data(category, /, **over) -> dict:
    """Поля формы (CONTRACT-003 § 12.1); значение `None` убирает ключ (как не отмеченный флажок)."""
    data = {"email": "anna.petrova@corp.test", "name": "Анна Петрова", "client_unit": "", "category": str(category.pk),
            "subject": "Не печатает принтер", "text": "Принтер на втором этаже не печатает", "consent": "on"}
    data.update(over)
    return {k: v for k, v in data.items() if v is not None}


def submit(client, data: dict, files=(), **extra):
    payload = dict(data)
    if files:
        payload["files"] = list(files)
    return client.post("/request/", payload, **extra)


def upload(name: str, content: bytes) -> SimpleUploadedFile:
    return SimpleUploadedFile(name, content, content_type="application/octet-stream")


def tickets_count() -> int:
    return model("servicedesk.Ticket").objects.count()


def journal(action: str, number: int) -> list:
    return list(model("core.AuditEvent").objects.filter(
        action=action, object_type="ticket", object_id=str(number)).order_by("id"))


def feed_events(ticket, event: str) -> list:
    return list(ticket.entries.filter(kind="event", event=event).order_by("id"))


def hits_key(ip: str) -> str:
    return f"servicedesk:form:{ip}"


def valkey():
    from apps.core.services import valkey as module

    return module


def hits(ip: str) -> int:
    return valkey().conn().zcard(hits_key(ip))


def text_of(value) -> str:
    return value.decode() if isinstance(value, bytes) else value


def set_limit(limit: int) -> None:
    sd.configure_servicedesk(form_hourly_limit=limit)


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


def doc_of(response) -> _Doc:
    return _Doc(response.content.decode())


def open_page(client=None) -> _Doc:
    response = (client or support.make_client(ip=IP)).get("/request/")
    assert response.status_code == 200, f"/request/: {response.status_code}"
    return doc_of(response)


def the_form(doc):
    forms = find(doc, "form", {"data-form": "request"})
    assert len(forms) == 1, "на странице нет формы form[data-form=request]"
    return forms[0]


def errors_of(doc) -> dict:
    """Ошибки полей: `[data-error=<поле>]` -> его `data-code` (CONTRACT-003 § 13.1, § 13.6)."""
    return {el.attrs["data-error"]: el.attrs.get("data-code") for el in find(doc, attrs={"data-error": True})}


def alerts_of(doc) -> list:
    return find(doc, attrs={"role": "alert"})


def refused_field(response, field: str, code: str, *, text: str | None = None) -> _Doc:
    """Страница с ошибкой одного поля: 200, `[data-error=<поле>][data-code=<код>]`, общего `[role=alert]` нет."""
    assert response.status_code == 200, f"ожидали страницу формы с ошибкой, получили {response.status_code}"
    doc = doc_of(response)
    errors = errors_of(doc)
    assert errors.get(field) == code, f"поле {field}: ждали {code}, ошибки страницы {errors}"
    assert not alerts_of(doc), "у отказа поля общего [role=alert] нет (CONTRACT-003 § 13.6)"
    if text is not None:
        assert text in find(doc, attrs={"data-error": field})[0].text
    return doc


def refused_alert(response, code: str, *, text: str | None = None) -> _Doc:
    """Общий отказ без поля (порог, вложения, закрытый приём): 200 и `[role=alert][data-code=<код>]`."""
    assert response.status_code == 200, f"ожидали страницу формы с отказом, получили {response.status_code}"
    doc = doc_of(response)
    alerts = alerts_of(doc)
    assert len(alerts) == 1, f"[role=alert] на странице: {len(alerts)}"
    assert alerts[0].attrs.get("data-code") == code
    if text is not None:
        assert text in alerts[0].text
    return doc


def confirmation_of(ticket):
    """Письмо-подтверждение заявки и контекст его задания: `(MailMessage, dict)`."""
    messages = [m for m in sd.ticket_mails(ticket) if m.template == "ticket.confirmation"]
    assert len(messages) == 1, f"писем-подтверждений: {len(messages)}"
    jobs = [j for j in mail_jobs() if j.meta.get("context", {}).get("ticket_id") == ticket.pk]
    assert len(jobs) == 1, f"заданий подтверждения: {len(jobs)}"
    return messages[0], jobs[0].meta["context"]


def only_ticket():
    rows = list(model("servicedesk.Ticket").objects.all())
    assert len(rows) == 1, f"заявок: {len(rows)}"
    return rows[0]


def options_of(doc, select_name: str) -> list:
    """Варианты выбора `select[name=...]` формы: список `(value, подпись)` по порядку."""
    form = the_form(doc)
    selects = [s for s in find(doc, "select", {"name": select_name}) if inside(s, form)]
    assert len(selects) == 1, f"в форме нет select[name={select_name}]"
    return [(o.attrs.get("value", o.text), o.text) for o in find(doc, "option") if inside(o, selects[0])]


# --- FR-222: страница и её поля ---------------------------------------------------------------------------

def test_request_page_opens_without_login_and_without_menu():
    """FR-222: `/request/` открывается без входа полным документом без левого меню (нет `#main-menu`), с
    `<meta name="viewport">`, `<html lang="ru">`, заголовком страницы и формой `form[data-form=request]`."""
    open_desk()
    response = support.make_client(ip=IP).get("/request/")
    assert response.status_code == 200
    doc = doc_of(response)
    assert not find(doc, attrs={"id": "main-menu"}), "на странице формы нет левого меню"
    assert find(doc, "meta", {"name": "viewport"})
    assert find(doc, "html", {"lang": "ru"})
    titles = find(doc, "title")
    assert titles and titles[0].text, "у страницы есть заголовок"
    the_form(doc)
    assert not find(doc, attrs={"data-closed-notice": True})


def test_form_has_required_fields_and_consent_checkbox():
    """FR-222: в форме поля email, name, client_unit, category, subject, text, files (multiple), флажок согласия с
    `[data-consent-text]` («персональных данных»), кнопка отправки, токен CSRF, метод post и multipart; `required`
    у обязательных; капчи нет (NFR-205)."""
    open_desk()
    doc = open_page()
    form = the_form(doc)
    assert form.attrs.get("method", "").lower() == "post"
    assert form.attrs.get("enctype") == "multipart/form-data"

    def one(tag, **attrs):
        found = [el for el in find(doc, tag, attrs) if inside(el, form)]
        assert len(found) == 1, f"в форме {tag}{attrs}: {len(found)}"
        return found[0]

    assert one("input", name="csrfmiddlewaretoken").attrs.get("value")
    for el in (one("input", name="email"), one("input", name="name"),
               one("input", name="subject"), one("textarea", name="text"),
               one("input", type="checkbox", name="consent")):
        assert "required" in el.attrs, f"у обязательного поля {el.attrs.get('name')} нет required"
    one("select", name="client_unit")
    one("select", name="category")
    files = one("input", type="file", name="files")
    assert "multiple" in files.attrs
    consent_text = [el for el in find(doc, attrs={"data-consent-text": True}) if inside(el, form)]
    assert len(consent_text) == 1 and "персональных данных" in consent_text[0].text
    assert [b for b in find(doc, "button", {"type": "submit"}) if inside(b, form)]
    assert "captcha" not in doc_html_lower(doc)


def doc_html_lower(doc) -> str:
    """Имена, классы и идентификаторы элементов формы строчными: по ним ищется капча."""
    parts = []
    for el in doc.elements:
        parts.append(el.tag)
        parts.extend(str(v) for v in el.attrs.values())
    return " ".join(parts).lower()


def test_department_list_unarchived_plus_not_in_list():
    """FR-222: `select[name=client_unit]` — первым «Нет в списке» (`value=""`), затем неархивные подразделения по названию;
    архивное не предлагается."""
    open_desk()
    sales = client_unit("Склад")
    audit = client_unit("Аудит")
    accounting = client_unit("Бухгалтерия")
    client_unit("Закрытый отдел", archived=True)
    options = options_of(open_page(), "client_unit")
    assert options[0] == ("", "Нет в списке")
    assert options[1:] == [(str(audit.pk), "Аудит"), (str(accounting.pk), "Бухгалтерия"), (str(sales.pk), "Склад")]


def test_category_list_shown_on_form_only_in_order_with_other():
    """FR-222: в `select[name=category]` только категории с «показывать на форме», не архивные, по порядку; «Другое»
    среди них (порядок 100 — последняя)."""
    open_desk()
    third = sd.make_category("Третья", on_form=True, order=30)
    first = sd.make_category("Первая", on_form=True, order=10)
    second = sd.make_category("Вторая", on_form=True, order=20)
    sd.make_category("Не для формы", on_form=False, order=5)
    sd.make_category("Архивная", on_form=True, order=6, archived=True)
    other = model("servicedesk.Category").objects.get(is_system=True)
    options = [(value, label) for value, label in options_of(open_page(), "category") if value != ""]
    assert options[-4:] == [(str(first.pk), "Первая"), (str(second.pk), "Вторая"), (str(third.pk), "Третья"),
                            (str(other.pk), other.name)]
    names = [label for _, label in options]
    assert "Не для формы" not in names and "Архивная" not in names
    assert "Принтеры" in names, "категория формы из настройки стенда тоже предлагается"


def test_form_has_no_criticality_choice_and_ticket_gets_default(django_capture_on_commit_callbacks):
    """FR-222, FR-203: на форме нет выбора критичности, источника и сложности; присланное поле `priority` игнорируется,
    заявка получает критичность по умолчанию из настроек, источник — системный «Форма»."""
    _, category = open_desk()
    doc = open_page()
    form = the_form(doc)
    for name in ("priority", "criticality", "source", "complexity"):
        assert not [el for el in doc.elements if el.attrs.get("name") == name and inside(el, form)], name
    Priority = model("servicedesk.Priority")
    high = Priority.objects.get(name_key=support_org.name_key("Высокая"))
    low = Priority.objects.get(name_key=support_org.name_key("Низкая"))
    sd.configure_servicedesk(default_priority=high)
    with django_capture_on_commit_callbacks(execute=True):
        response = submit(support.make_client(ip=IP), valid_data(category, priority=str(low.pk)))
    assert response.status_code == 302
    ticket = only_ticket()
    assert ticket.priority_id == high.pk, "критичность — по умолчанию из настроек, а не присланная"
    assert ticket.source.system_code == "form"


# --- FR-213, FR-222: закрытое состояние -------------------------------------------------------------------

def test_closed_page_without_domains_or_default_queue_names_mailbox():
    """FR-213, FR-222: пока список доменов пуст или нет очереди по умолчанию, вместо формы `[data-closed-notice=request]`
    с текстом `form.closed_text()` и адресом ящика заявок; формы на странице нет."""
    form = form_module()
    queue = sd.make_queue()
    assert form.is_open() is False, "свежая установка: приём закрыт"
    cases = [("нет доменов и очереди", [], None), ("нет доменов", [], queue.unit),
             ("нет очереди по умолчанию", ["corp.test"], None)]
    Settings = model("servicedesk.ServiceDeskSettings")
    for title, domains, default in cases:
        Settings.objects.filter(pk=1).update(domains=domains, default_queue=default)
        assert form.is_open() is False, title
        response = support.make_client(ip=IP).get("/request/")
        assert response.status_code == 200, title
        doc = doc_of(response)
        notices = find(doc, attrs={"data-closed-notice": "request"})
        assert len(notices) == 1, title
        assert form.closed_text() in notices[0].text, title
        assert CLOSED_TEXT in notices[0].text and MAILBOX in notices[0].text, title
        assert not find(doc, "form", {"data-form": "request"}), title
        assert not find(doc, attrs={"id": "main-menu"})
    sd.configure_servicedesk(domains=["corp.test"], default_queue=queue)
    assert form.is_open() is True
    assert not find(open_page(), attrs={"data-closed-notice": True})


def test_post_when_closed_rejected_with_same_text():
    """FR-213, FR-222: POST в закрытом состоянии отклоняется тем же текстом, что показывает GET: 200 и `[role=alert]`
    `data-code=intake_closed` с адресом ящика; заявки и записи заявителя нет."""
    category = sd.make_category("Принтеры", on_form=True)
    client = support.make_client(ip=IP)
    notice = find(doc_of(client.get("/request/")), attrs={"data-closed-notice": "request"})[0]
    response = submit(client, valid_data(category))
    doc = refused_alert(response, "intake_closed", text=CLOSED_TEXT)
    assert MAILBOX in alerts_of(doc)[0].text
    assert form_module().closed_text() in alerts_of(doc)[0].text and form_module().closed_text() in notice.text
    assert tickets_count() == 0 and model("servicedesk.Requester").objects.count() == 0
    assert hits(IP) == 0


# --- FR-222, FR-223, FR-227: создание и страница «готово» -------------------------------------------------

def test_valid_post_creates_form_ticket_in_category_queue_with_consent_mark_and_confirmation(
        django_capture_on_commit_callbacks):
    """FR-222, FR-223, FR-227: верная форма — 302 на `/request/done/`, адрес в сессии, заявка канала «форма» в очереди
    категории с отметкой согласия, запись заявителя, журнал `ticket.created` с `ip`, одно подтверждение заявителю."""
    _, category = open_desk()
    unit = client_unit("Бухгалтерия")
    client = support.make_client(ip=IP)
    before = timezone.now()
    with django_capture_on_commit_callbacks(execute=True):
        response = submit(client, valid_data(category, email="Anna.Petrova@CORP.test", client_unit=str(unit.pk)))
    assert response.status_code == 302 and response["Location"].endswith("/request/done/")
    assert client.session[SESSION_KEY] == "anna.petrova@corp.test"
    ticket = only_ticket()
    assert ticket.queue_id == category.queue_id and ticket.category_id == category.pk
    assert ticket.source.system_code == "form"
    assert ticket.kind == "new" and ticket.assignee_id is None
    assert ticket.requester_email == "anna.petrova@corp.test" and ticket.requester_name == "Анна Петрова"
    assert ticket.client_unit_id == unit.pk
    assert ticket.subject == "Не печатает принтер"
    assert ticket.consent_at is not None and before <= ticket.consent_at <= timezone.now()
    entries = list(ticket.entries.filter(kind="incoming"))
    assert len(entries) == 1 and entries[0].text == "Принтер на втором этаже не печатает"
    assert entries[0].author_email == "anna.petrova@corp.test"
    requester = model("servicedesk.Requester").objects.get(email="anna.petrova@corp.test")
    assert ticket.requester_id == requester.pk and requester.origin == "ticket"
    created = journal("ticket.created", ticket.number)
    assert len(created) == 1 and created[0].actor is None and created[0].ip == IP
    assert created[0].after["channel"] == "form" and created[0].after["queue_id"] == category.queue_id
    assert created[0].after["category"] == category.name and created[0].after["source"] == "Форма"
    message, _ = confirmation_of(ticket)
    assert message.to == "anna.petrova@corp.test"
    assert hits(IP) == 1, "порог учёл ровно одну принятую отправку"


def test_done_page_shows_address_without_number_taken_from_session_and_removed(django_capture_on_commit_callbacks):
    """FR-223: `/request/done/` — «Заявка принята. Подтверждение с номером придёт на <адрес>» (`[data-request-done]`,
    `[data-done-email]`), номера заявки на странице нет; адрес берётся из сессии и сразу удаляется, второе открытие и
    открытие без отправки ведут на `/request/`."""
    _, category = open_desk()
    client = support.make_client(ip=IP)
    assert client.get("/request/done/").status_code == 302
    with django_capture_on_commit_callbacks(execute=True):
        submit(client, valid_data(category, email="anna.petrova@corp.test"))
    number = only_ticket().number
    response = client.get("/request/done/")
    assert response.status_code == 200
    doc = doc_of(response)
    done = find(doc, attrs={"data-request-done": True})
    assert len(done) == 1
    assert "Заявка принята. Подтверждение с номером придёт на" in done[0].text
    emails = find(doc, attrs={"data-done-email": True})
    assert len(emails) == 1 and emails[0].text == "anna.petrova@corp.test"
    assert not re.search(rf"(?<![\w.@-]){number}(?![\w.@-])", done[0].text.replace("anna.petrova@corp.test", "")), \
        "номер заявки на странице не показывается"
    assert SESSION_KEY not in client.session
    second = client.get("/request/done/")
    assert second.status_code == 302 and second["Location"].endswith("/request/")
    assert not second["Location"].endswith("/done/")
    stranger = support.make_client(ip="198.51.100.32").get("/request/done/")
    assert stranger.status_code == 302 and stranger["Location"].endswith("/request/")


# --- FR-222: отказы полей ---------------------------------------------------------------------------------

def test_invalid_address_and_foreign_domain_refused(django_capture_on_commit_callbacks):
    """FR-222: адрес не годен по формату, домен не из списка или адрес длиннее 254 знаков — `[data-error=email]` с
    `data-code=bad_email` и текстом «Укажите рабочую почту на корпоративном домене», введённые значения сохранены,
    заявки нет; кириллический домен из списка принимается (дополнение 17)."""
    _, category = open_desk(domains=("corp.test", "xn--e1afmkfd.xn--p1ai"))
    client = support.make_client(ip=IP)
    bad = ["not-an-email", "user@", "user@other.test", "user@sub.corp.test", "user@corp.test.evil.test",
           "a" * 250 + "@corp.test", "user@xn--e1afmkfd.xn--p1ai.evil.test"]
    for address in bad:
        response = submit(client, valid_data(category, email=address, subject="Тема для проверки"))
        doc = refused_field(response, "email", "bad_email", text="рабочую почту на корпоративном домене")
        assert set(errors_of(doc)) == {"email"}, address
        form = the_form(doc)
        values = {el.attrs.get("name"): el.attrs.get("value") for el in find(doc, "input") if inside(el, form)}
        assert values["email"] == address and values["name"] == "Анна Петрова", "введённые значения сохранены"
        assert [t for t in find(doc, "input", {"name": "subject"})][0].attrs["value"] == "Тема для проверки"
        assert tickets_count() == 0, address
    with django_capture_on_commit_callbacks(execute=True):
        response = submit(client, valid_data(category, email="ivan@пример.рф"))
    assert response.status_code == 302
    assert only_ticket().requester_email == "ivan@пример.рф", "адрес хранится строчными как введён"


def test_required_fields_and_length_limits_refused(django_capture_on_commit_callbacks):
    """FR-222: пустые ФИО, тема, описание и значения длиннее пределов (ФИО и тема 255, описание 50 000) отказываются
    на своём поле с кодом § 6.2, заявки нет; ровно на пределе форма принимается."""
    _, category = open_desk()
    client = support.make_client(ip=IP)
    cases = [("name", {"name": ""}, "requester_name_required"),
             ("name", {"name": "Я" * 256}, "requester_name_too_long"),
             ("subject", {"subject": ""}, "subject_required"),
             ("subject", {"subject": "Т" * 256}, "subject_too_long"),
             ("text", {"text": ""}, "description_required"),
             ("text", {"text": "О" * 50001}, "description_too_long")]
    for field, over, code in cases:
        doc = refused_field(submit(client, valid_data(category, **over)), field, code)
        assert set(errors_of(doc)) == {field}, f"{code}: ошибки {errors_of(doc)}"
        assert tickets_count() == 0, code
    with django_capture_on_commit_callbacks(execute=True):
        response = submit(client, valid_data(category, name="Я" * 255, subject="Т" * 255, text="О" * 50000))
    assert response.status_code == 302 and tickets_count() == 1
    ticket = only_ticket()
    assert len(ticket.subject) == 255 and len(ticket.requester_name) == 255


def test_missing_consent_refused():
    """FR-222: без галочки согласия — `[data-error=consent]` с `data-code=consent_required`, заявки и записи заявителя
    нет, остальные введённые значения сохранены."""
    _, category = open_desk()
    response = submit(support.make_client(ip=IP), valid_data(category, consent=None))
    doc = refused_field(response, "consent", "consent_required")
    assert set(errors_of(doc)) == {"consent"}
    assert find(doc, "input", {"name": "email"})[0].attrs["value"] == "anna.petrova@corp.test"
    assert tickets_count() == 0 and model("servicedesk.Requester").objects.count() == 0
    assert hits(IP) == 0


def test_category_or_department_not_offered_refused():
    """FR-222: категория не из предлагаемых (архивная, без отметки «на форме», несуществующая, не выбрана) и
    подразделение не из предлагаемых (архивное, несуществующее) отказываются на своём поле; «Нет в списке» допустимо."""
    _, category = open_desk()
    client = support.make_client(ip=IP)
    archived = sd.make_category("Архивная", on_form=True, archived=True)
    hidden = sd.make_category("Скрытая", on_form=False)
    for value in (str(archived.pk), str(hidden.pk), "999999", ""):
        doc = refused_field(submit(client, valid_data(category, category=value)), "category", "category_not_offered")
        assert set(errors_of(doc)) == {"category"}, value
    old_unit = client_unit("Старый отдел", archived=True)
    for value in (str(old_unit.pk), "999999"):
        doc = refused_field(submit(client, valid_data(category, client_unit=value)), "client_unit", "unit_not_offered")
        assert set(errors_of(doc)) == {"client_unit"}, value
    assert tickets_count() == 0 and hits(IP) == 0


# --- FR-222: подразделение и ответственный ----------------------------------------------------------------

def test_not_in_list_department_taken_from_requester_record_or_empty(django_capture_on_commit_callbacks):
    """FR-222: «Нет в списке» — подразделение заявки берётся из записи заявителя, а без записи или без подразделения в
    ней остаётся пустым; запись не меняется."""
    _, category = open_desk()
    unit = client_unit("Бухгалтерия")
    sd.make_requester("known@corp.test", full_name="Иван Известный", client_unit=unit)
    sd.make_requester("nounit@corp.test", full_name="Без Отдела")
    client = support.make_client(ip=IP)
    with django_capture_on_commit_callbacks(execute=True):
        for email in ("known@corp.test", "nounit@corp.test", "fresh@corp.test"):
            assert submit(client, valid_data(category, email=email, client_unit="")).status_code == 302
    Ticket, Requester = model("servicedesk.Ticket"), model("servicedesk.Requester")
    assert Ticket.objects.get(requester_email="known@corp.test").client_unit_id == unit.pk
    assert Ticket.objects.get(requester_email="nounit@corp.test").client_unit_id is None
    assert Ticket.objects.get(requester_email="fresh@corp.test").client_unit_id is None
    assert Requester.objects.get(email="known@corp.test").client_unit_id == unit.pk
    assert Requester.objects.get(email="nounit@corp.test").client_unit_id is None
    assert Requester.objects.get(email="fresh@corp.test").client_unit_id is None


def test_form_department_fills_empty_record_and_keeps_existing_one(django_capture_on_commit_callbacks):
    """FR-222: выбранное на форме подразделение попадает в заявку всегда, а в запись заявителя — только если там пусто
    (непустое не перезаписывается; то же у ФИО записи)."""
    _, category = open_desk()
    chosen = client_unit("Склад")
    old = client_unit("Бухгалтерия")
    sd.make_requester("empty@corp.test", client_unit=None)
    sd.make_requester("filled@corp.test", full_name="Старое Имя", client_unit=old)
    client = support.make_client(ip=IP)
    with django_capture_on_commit_callbacks(execute=True):
        assert submit(client, valid_data(category, email="empty@corp.test", client_unit=str(chosen.pk))).status_code == 302
        assert submit(client, valid_data(category, email="filled@corp.test", name="Введённое Имя",
                                         client_unit=str(chosen.pk))).status_code == 302
    Ticket, Requester = model("servicedesk.Ticket"), model("servicedesk.Requester")
    assert Ticket.objects.get(requester_email="empty@corp.test").client_unit_id == chosen.pk
    assert Requester.objects.get(email="empty@corp.test").client_unit_id == chosen.pk
    filled = Ticket.objects.get(requester_email="filled@corp.test")
    assert filled.client_unit_id == chosen.pk and filled.requester_name == "Введённое Имя"
    record = Requester.objects.get(email="filled@corp.test")
    assert record.client_unit_id == old.pk and record.full_name == "Старое Имя"


def test_default_assignee_of_category_gives_in_progress_and_single_confirmation(
        django_capture_on_commit_callbacks, bus_spy):
    """FR-222, FR-238, FR-255: у категории ответственный по умолчанию — участник очереди: заявка «в работе» с ним,
    событие ленты и журнал `ticket.assigned`, одно подтверждение с его именем и без письма «взята в работу», в шину
    уходит только `ticket_created`; не участник очереди — заявка без ответственного."""
    bus_spy.listen("servicedesk.ticket_created", "servicedesk.assignee_changed")
    open_desk()
    queue = sd.make_queue()
    person = support.make_employee(full_name="Петров Иван Сергеевич")
    support_org.make_member(person, queue.unit)
    category = sd.make_category("С ответственным", queue=queue, default_assignee=person, on_form=True)
    outsider = support.make_employee(full_name="Сидоров Пётр Павлович")
    stray = sd.make_category("Без участия", queue=sd.make_queue(), default_assignee=outsider, on_form=True)
    client = support.make_client(ip=IP)
    with django_capture_on_commit_callbacks(execute=True):
        assert submit(client, valid_data(category)).status_code == 302
    Ticket = model("servicedesk.Ticket")
    ticket = Ticket.objects.get(category=category)
    assert ticket.queue_id == queue.unit_id and ticket.assignee_id == person.pk and ticket.assigned_once is True
    assert ticket.kind == "in_progress"
    changed = feed_events(ticket, "assignee_changed")
    assert len(changed) == 1 and changed[0].data["after_id"] == person.pk and changed[0].data["before_id"] is None
    assigned = journal("ticket.assigned", ticket.number)
    assert len(assigned) == 1 and assigned[0].actor is None
    assert assigned[0].before == {"assignee": "", "assignee_id": None}
    assert [m.template for m in sd.ticket_mails(ticket)] == ["ticket.confirmation"]
    message, context = confirmation_of(ticket)
    assert "Иван Петров" in sd.mail_text(message, context)
    assert [d["number"] for d in bus_spy.calls("servicedesk.ticket_created")] == [ticket.number]
    assert not bus_spy.calls("servicedesk.assignee_changed")
    with django_capture_on_commit_callbacks(execute=True):
        assert submit(client, valid_data(stray, email="other@corp.test")).status_code == 302
    unassigned = Ticket.objects.get(category=stray)
    assert unassigned.assignee_id is None and unassigned.kind == "new" and unassigned.assigned_once is False
    assert not feed_events(unassigned, "assignee_changed") and not journal("ticket.assigned", unassigned.number)
    assert [m.template for m in sd.ticket_mails(unassigned)] == ["ticket.confirmation"]


# --- FR-222: вложения -------------------------------------------------------------------------------------

def test_file_count_total_size_and_unacceptable_file_refuse_whole_form(protected_root, django_capture_on_commit_callbacks):
    """FR-222: больше 10 файлов, сумма больше 50 МБ, файл больше 20 МБ, исполняемый по содержимому и архив с паролем
    отказывают всю форму (`[role=alert]` с кодом § 6.2, заявки, записи заявителя и файлов нет, порог не тратится);
    десять годных файлов принимаются."""
    _, category = open_desk()
    client = support.make_client(ip=IP)
    small = [upload(f"f{i}.txt", b"data") for i in range(11)]
    refused_alert(submit(client, valid_data(category), small), "too_many_files")
    big = [upload(f"part{i}.bin", b"\0" * (19 * MB)) for i in range(3)]
    refused_alert(submit(client, valid_data(category), big), "total_too_big")
    doc = refused_alert(submit(client, valid_data(category), [upload("huge.bin", b"\0" * (20 * MB + 1))]),
                        "file_rejected", text="не принят")
    assert "huge.bin" in alerts_of(doc)[0].text and "больше 20 МБ" in alerts_of(doc)[0].text
    doc = refused_alert(submit(client, valid_data(category), [upload("ok.txt", b"ok"), upload("report.txt", sd.sample("exe_pe.bin"))]),
                        "file_rejected", text="не принят")
    assert "report.txt" in alerts_of(doc)[0].text and "исполняемый файл" in alerts_of(doc)[0].text
    doc = refused_alert(submit(client, valid_data(category), [upload("archive.zip", sd.sample("enc_zip_zipcrypto.zip"))]),
                        "file_rejected", text="не принят")
    assert "archive.zip" in alerts_of(doc)[0].text and "архив с паролем" in alerts_of(doc)[0].text
    assert tickets_count() == 0 and model("servicedesk.Requester").objects.count() == 0
    assert model("servicedesk.Attachment").objects.count() == 0 and model("core.StoredFile").objects.count() == 0
    assert hits(IP) == 0, "отказ вложений идёт раньше порога: отметки нет"
    assert SESSION_KEY not in client.session
    good = [upload(f"g{i}.txt", f"data {i}".encode()) for i in range(10)]
    with django_capture_on_commit_callbacks(execute=True):
        response = submit(client, valid_data(category), good)
    assert response.status_code == 302
    attachments = list(model("servicedesk.Attachment").objects.filter(ticket=only_ticket()))
    assert len(attachments) == 10 and all(a.rejected == "" and a.file_id for a in attachments)
    assert {a.file.status for a in attachments} == {"pending"}


# --- FR-224: одинаковый ответ -----------------------------------------------------------------------------

def test_same_response_for_known_and_unknown_address_and_no_prefill(django_capture_on_commit_callbacks):
    """FR-224: ответ формы не зависит от того, есть ли адрес среди заявителей, и ничего не подставляет: страницы с
    ошибкой совпадают (без адреса и токена), имя и подразделение не подставлены, успешные ответы одинаковы."""
    _, category = open_desk()
    unit = client_unit("Бухгалтерия")
    sd.make_requester("known@corp.test", full_name="Иван Известный", client_unit=unit)

    def normalized(response, email: str) -> str:
        body = response.content.decode().replace(email, "ADDR")
        for token in {el.attrs["value"] for el in find(doc_of(response), "input", {"name": "csrfmiddlewaretoken"})
                      if el.attrs.get("value")}:
            body = body.replace(token, "TOKEN")
        return body

    refusal = {"name": "Тест", "subject": "Тема", "consent": None}
    known = submit(support.make_client(ip=IP), valid_data(category, email="known@corp.test", **refusal))
    unknown = submit(support.make_client(ip=IP), valid_data(category, email="unknown@corp.test", **refusal))
    assert known.status_code == unknown.status_code == 200
    assert normalized(known, "known@corp.test") == normalized(unknown, "unknown@corp.test")
    doc = doc_of(known)
    assert find(doc, "input", {"name": "name"})[0].attrs["value"] == "Тест", "имя из записи не подставляется"
    assert "Иван Известный" not in known.content.decode()
    chosen = [o for o in find(doc, "option") if "selected" in o.attrs]
    assert all(o.attrs.get("value", "") != str(unit.pk) for o in chosen), "подразделение из записи не подставляется"
    assert errors_of(doc) == errors_of(doc_of(unknown))
    with django_capture_on_commit_callbacks(execute=True):
        client_known, client_unknown = support.make_client(ip=IP), support.make_client(ip="198.51.100.33")
        ok_known = submit(client_known, valid_data(category, email="known@corp.test"))
        ok_unknown = submit(client_unknown, valid_data(category, email="unknown@corp.test"))
    assert ok_known.status_code == ok_unknown.status_code == 302
    assert ok_known["Location"] == ok_unknown["Location"]
    assert normalized(client_known.get("/request/done/"), "known@corp.test") == \
        normalized(client_unknown.get("/request/done/"), "unknown@corp.test")


# --- FR-225, NFR-205: порог -------------------------------------------------------------------------------

def test_rate_limit_refuses_over_threshold_with_mailbox_address(django_capture_on_commit_callbacks):
    """FR-225, NFR-205: с одного адреса не больше порога заявок в час; превышение — 200 с `[role=alert]`
    `data-code=rate_limited`, текстом с адресом ящика, заявки нет, отметка отклонённой удалена; другой адрес не задет."""
    _, category = open_desk()
    set_limit(2)
    client = support.make_client(ip=IP)
    with django_capture_on_commit_callbacks(execute=True):
        for _ in range(2):
            assert submit(client, valid_data(category)).status_code == 302
    assert tickets_count() == 2 and hits(IP) == 2
    response = submit(client, valid_data(category))
    doc = refused_alert(response, "rate_limited", text=RATE_TEXT)
    assert MAILBOX in alerts_of(doc)[0].text
    assert tickets_count() == 2 and hits(IP) == 2, "отметка отклонённой формы удалена"
    with django_capture_on_commit_callbacks(execute=True):
        assert submit(support.make_client(ip="198.51.100.77"), valid_data(category)).status_code == 302
    assert tickets_count() == 3


def test_rate_limit_sliding_window_lua_script():
    """FR-225, NFR-205: `register_hit` — упорядоченное множество `servicedesk:form:<ip>`: отметка `"<время>:<суффикс>"` с
    оценкой-временем, записи старше часа убираются, превышение порога удаляет отметку и даёт `False`, ключ живёт час."""
    form = form_module()
    ip = "198.51.100.40"
    key = hits_key(ip)
    conn = valkey().conn()
    now = time.time()
    conn.zadd(key, {"old:x": now - 3601, "mid:y": now - 3500})
    set_limit(3)
    assert form.register_hit(ip) is True
    assert conn.zscore(key, "old:x") is None, "запись старше часа убрана"
    assert conn.zscore(key, "mid:y") is not None, "запись внутри часа остаётся"
    members = [text_of(m) for m in conn.zrange(key, 0, -1)]
    new = [m for m in members if m != "mid:y"]
    assert len(members) == 2 and len(new) == 1
    stamp_text, colon, suffix = new[0].partition(":")
    assert colon and suffix, new[0]
    stamp = float(stamp_text)
    assert abs(stamp - time.time()) < 60 and abs(conn.zscore(key, new[0]) - stamp) < 1
    assert 3500 < conn.ttl(key) <= 3600
    assert form.register_hit(ip) is True and conn.zcard(key) == 3
    assert form.register_hit(ip) is False and conn.zcard(key) == 3, "превышение: отметка удалена"
    assert form.register_hit(ip) is False and conn.zcard(key) == 3
    other = "2001:db8::7"
    assert form.register_hit(other) is True and conn.zcard(hits_key(other)) == 1, "ключ IPv6 — адрес строкой как есть"


def test_rate_limit_default_ten_per_hour_and_threshold_read_from_settings():
    """FR-225: по умолчанию порог — десять заявок в час; порог читается из настроек при каждом вызове."""
    form = form_module()
    assert model("servicedesk.ServiceDeskSettings").objects.get(pk=1).form_hourly_limit == 10
    ip = "198.51.100.41"
    assert [form.register_hit(ip) for _ in range(10)] == [True] * 10
    assert form.register_hit(ip) is False and hits(ip) == 10
    set_limit(12)
    assert form.register_hit(ip) is True and form.register_hit(ip) is True
    assert form.register_hit(ip) is False and hits(ip) == 12
    set_limit(1)
    assert form.register_hit(ip) is False and hits(ip) == 12


def test_rate_limit_client_ip_behind_trusted_proxy(settings, django_capture_on_commit_callbacks):
    """FR-225: адрес клиента — `request.client_ip` по `TRUSTED_PROXIES`: от доверенного прокси берётся адрес из
    `X-Forwarded-For`, от чужого заголовок игнорируется; порог считается по этому адресу, он же пишется в журнал."""
    _, category = open_desk()
    set_limit(1)
    settings.TRUSTED_PROXIES = ["10.9.9.9"]
    proxy = support.make_client(ip="10.9.9.9")
    with django_capture_on_commit_callbacks(execute=True):
        first = submit(proxy, valid_data(category), HTTP_X_FORWARDED_FOR="203.0.113.55")
        second = submit(proxy, valid_data(category), HTTP_X_FORWARDED_FOR="203.0.113.56")
    assert first.status_code == 302 and second.status_code == 302, "разные клиенты за прокси не мешают друг другу"
    assert hits("203.0.113.55") == 1 and hits("203.0.113.56") == 1 and hits("10.9.9.9") == 0
    refused_alert(submit(proxy, valid_data(category), HTTP_X_FORWARDED_FOR="203.0.113.55"), "rate_limited")
    first_ticket = model("servicedesk.Ticket").objects.order_by("id").first()
    assert journal("ticket.created", first_ticket.number)[0].ip == "203.0.113.55"
    with django_capture_on_commit_callbacks(execute=True):
        stranger = submit(support.make_client(ip="198.51.100.77"), valid_data(category),
                          HTTP_X_FORWARDED_FOR="203.0.113.99")
    assert stranger.status_code == 302
    assert hits("198.51.100.77") == 1 and hits("203.0.113.99") == 0, "от недоверенного адреса заголовку не верим"


def test_rate_limit_counts_only_accepted_forms(django_capture_on_commit_callbacks):
    """FR-225: порог считает только принятые формы: отказы по полям, вложениям и закрытому приёму отметок не оставляют,
    отметку даёт только созданная заявка."""
    _, category = open_desk()
    set_limit(1)
    client = support.make_client(ip=IP)
    refused_field(submit(client, valid_data(category, email="bad")), "email", "bad_email")
    refused_field(submit(client, valid_data(category, consent=None)), "consent", "consent_required")
    refused_alert(submit(client, valid_data(category), [upload(f"f{i}.txt", b"x") for i in range(11)]), "too_many_files")
    refused_alert(submit(client, valid_data(category), [upload("run.txt", sd.sample("exe_pe.bin"))]), "file_rejected")
    assert hits(IP) == 0 and tickets_count() == 0
    with django_capture_on_commit_callbacks(execute=True):
        assert submit(client, valid_data(category)).status_code == 302
    assert hits(IP) == 1
    refused_alert(submit(client, valid_data(category)), "rate_limited")
    assert tickets_count() == 1 and hits(IP) == 1


def test_valkey_down_form_works_without_limit_and_logs_warning(monkeypatch, caplog, django_capture_on_commit_callbacks):
    """FR-225, NFR-205: недоступный Valkey у порога — форма работает без порога (заявка создана, 302) и пишет
    предупреждение (`WARNING`) в лог; `register_hit` при этом отвечает `True`."""
    import redis

    _, category = open_desk()
    calls = []

    def down(*args, **kwargs):
        calls.append(1)
        raise redis.exceptions.ConnectionError("valkey is down")

    monkeypatch.setattr(valkey(), "conn", down)
    caplog.set_level(logging.WARNING)
    caplog.clear()
    assert form_module().register_hit("198.51.100.50") is True
    assert [r for r in caplog.records if r.levelno >= logging.WARNING], "предупреждение в лог"
    caplog.clear()
    with django_capture_on_commit_callbacks(execute=True):
        response = submit(support.make_client(ip=IP), valid_data(category))
    assert response.status_code == 302 and tickets_count() == 1
    assert calls, "порог обращался к Valkey через apps.core.services.valkey.conn"
    assert [r for r in caplog.records if r.levelno == logging.WARNING], "предупреждение в лог при отправке формы"


# --- FR-226, FR-222: вход и вошедшие ----------------------------------------------------------------------

def test_login_page_has_request_link_from_login_links():
    """FR-226: на странице входа ссылка `a[data-login-link][href="/request/"]` «Подать заявку в ИТ-отдел» из точки
    `login_links`; сама точка отдаёт один элемент с этим адресом и названием; ссылка есть и пока приём закрыт."""
    assert form_module().login_links() == [{"url": "/request/", "title": "Подать заявку в ИТ-отдел"}]
    response = support.make_client(ip=IP).get("/login/")
    assert response.status_code == 200
    links = find(doc_of(response), "a", {"data-login-link": True, "href": "/request/"})
    assert len(links) == 1 and links[0].text == "Подать заявку в ИТ-отдел"
    open_desk()
    links = find(doc_of(support.make_client(ip=IP).get("/login/")), "a", {"data-login-link": True, "href": "/request/"})
    assert len(links) == 1


def test_logged_in_user_sees_form_as_guest_with_csrf_and_no_captcha(django_capture_on_commit_callbacks):
    """FR-222, NFR-205: вошедший сотрудник видит ту же форму, что гость (меню нет), с токеном CSRF и без капчи; POST без
    токена отклоняется, с токеном принимается — и у гостя, и у вошедшего."""
    _, category = open_desk()
    user = support.make_employee()
    for who, address, client in (("гость", "guest@corp.test", support.make_client(ip=IP, enforce_csrf_checks=True)),
                                 ("вошедший", "staff@corp.test", support.logged_in(user))):
        client.handler.enforce_csrf_checks = True
        doc = open_page(client)
        form = the_form(doc)
        assert not find(doc, attrs={"id": "main-menu"}), who
        tokens = [el for el in find(doc, "input", {"name": "csrfmiddlewaretoken"}) if inside(el, form)]
        assert len(tokens) == 1 and tokens[0].attrs["value"], who
        assert "captcha" not in doc_html_lower(doc), who
        assert submit(client, valid_data(category, email=address)).status_code == 403, who
        assert tickets_count() == (0 if who == "гость" else 1)
        with django_capture_on_commit_callbacks(execute=True):
            response = submit(client, valid_data(category, email=address,
                                                  csrfmiddlewaretoken=tokens[0].attrs["value"]))
        assert response.status_code == 302 and response["Location"].endswith("/request/done/"), who
    assert tickets_count() == 2
