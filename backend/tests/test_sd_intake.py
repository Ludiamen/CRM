"""T-3107: разбор письма — проверки и связь с заявкой (FR-212…FR-217, FR-220, FR-251, NFR-209).

Сценарии 1, 3 и 11 спеки среза 003. Письмо кладётся в базу строкой `InboundMail` и файлом
`protected/inbound/<id>.eml` (помощники этого файла), разбор — `intake.process(id)` внутри
`django_capture_on_commit_callbacks(execute=True)`. Имена кода среза 003 импортируются внутри
тестов: сбор проходит до появления кода. Правила — tests/CONTRACT-003.md (§ 3.5, 6.14, 6.16, 13.8, 16).
"""
import email
import secrets
from email import policy
from html.parser import HTMLParser

import pytest
from django.utils import timezone

from tests import factories, support, support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

MAILBOX = "tickets@stand.test"
SMTP_FROM = "portal@corp.test"
DOMAIN = "corp.test"
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}

LABELS = {  # InboundMail.Outcome -> подпись (CONTRACT-003 § 2.2)
    "created": "создана заявка", "appended": "добавлено в заявку", "reopened": "открыта заново",
    "rejected_domain": "отклонено: чужой домен",
    "rejected_self": "отклонено: письмо с адреса ящика заявок", "auto": "автоматическое письмо",
    "waiting_setup": "ждёт настройки очереди по умолчанию", "parse_error": "ошибка разбора",
}


class _Boom(Exception):
    """Ошибка шага разбора; текст исключения — метка, которой не должно быть в `last_error`."""


# --- помощники только этого файла ------------------------------------------------------------------

def _prepare(settings, *, domains=(DOMAIN,), queue=True):
    """Ящик, адрес отправки портала, домены и (по желанию) очередь по умолчанию; возвращает `Queue`."""
    settings.SERVICEDESK_MAILBOX = MAILBOX
    settings.DEFAULT_FROM_EMAIL = SMTP_FROM
    queue_row = sd.make_queue()
    sd.configure_servicedesk(domains=list(domains), default_queue=queue_row if queue else None)
    return queue_row


def _mail(from_addr, **kwargs) -> bytes:
    kwargs.setdefault("text", "Текст письма")
    return sd.build_mail(from_addr=from_addr, **kwargs)


def _raw(from_line: bytes, subject: str = "Subject") -> bytes:
    """Письмо со своей строкой `From` (без адреса, адрес без домена): `build_mail` такого не собирает."""
    return (b"From: " + from_line + b"\r\nSubject: " + subject.encode("ascii", "ignore")
            + b"\r\nMessage-ID: <raw-" + factories.new_email("m").encode() + b">\r\n\r\nText\r\n")


def _store(raw: bytes, protected_root, **over):
    """Строка `InboundMail` и файл письма: `make_inbound` файла не создаёт."""
    message = email.message_from_bytes(raw, policy=policy.default)
    fields = {"from_email": "", "subject": "", "message_id": str(message["Message-ID"] or "")}
    fields.update(over)
    inbound = sd.make_inbound(size=len(raw), **fields)
    folder = protected_root / "inbound"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{inbound.pk}.eml").write_bytes(raw)
    return inbound


def _process(inbound, capture):
    from apps.servicedesk.services import intake

    with capture(execute=True):
        return intake.process(inbound.pk)


def _run(raw, protected_root, capture, **over):
    """Положить письмо и разобрать; возвращает (итог `process`, свежая строка `InboundMail`)."""
    inbound = _store(raw, protected_root, **over)
    result = _process(inbound, capture)
    inbound.refresh_from_db()
    return result, inbound


def _counts():
    return (model("servicedesk.Ticket").objects.count(), model("servicedesk.TicketEntry").objects.count(),
            model("mail.MailMessage").objects.count())


def _open_ticket(queue_row, requester_email=None, **over):
    """Открытая заявка с первым письмом заявителя; возвращает (заявка, запись заявителя)."""
    requester = sd.make_requester(requester_email or f"req-{secrets.token_hex(3)}@{DOMAIN}")
    ticket = sd.make_ticket(queue=queue_row, requester=requester, **over)
    sd.make_entry(ticket, "incoming", text="Первое письмо")
    ticket.refresh_from_db()
    return ticket, requester


def _incoming(ticket):
    return list(ticket.entries.filter(kind="incoming").order_by("at", "id"))


def _subject(ticket, text="Ответ") -> str:
    return f"[#{ticket.number}] {text}"


class _El:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.kids = tag, attrs, parent, []

    def walk(self):
        yield self
        for kid in self.kids:
            if isinstance(kid, _El):
                yield from kid.walk()

    def text(self) -> str:
        return " ".join(" ".join(k if isinstance(k, str) else k.text() for k in self.kids).split())

    def find_all(self, tag=None, **want):
        wanted = {key.replace("_", "-"): value for key, value in want.items()}
        return [el for el in self.walk()
                if (tag is None or el.tag == tag)
                and all(n in el.attrs and (v is True or el.attrs[n] == str(v)) for n, v in wanted.items())]


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
        el = self.cur
        while el is not None and el.tag != tag:
            el = el.parent
        if el is not None and el.parent is not None:
            self.cur = el.parent

    def handle_data(self, data):
        self.cur.kids.append(data)


def _tree(html: str) -> _El:
    builder = _Builder()
    builder.feed(html)
    return builder.root


def _manage_client():
    return support.logged_in(support.make_with_permissions("servicedesk.manage"))


def _inbound_rows(client) -> dict:
    response = client.get("/servicedesk/inbound/")
    assert response.status_code == 200
    root = _tree(response.content.decode())
    return {int(row.attrs["data-id"]): row for row in root.find_all("tr", data_inbound=True)}


# --- проверки FR-214: ящик, автоматическое, домен -------------------------------------------------

def test_mail_from_mailbox_address_rejected_with_own_outcome(settings, protected_root, django_capture_on_commit_callbacks):
    """FR-214, FR-216: письмо с адреса ящика — итог `rejected_self` (не чужой домен: домен ящика вне списка),
    заявки и подтверждения нет, в существующую заявку по номеру не дописано."""
    queue_row = _prepare(settings)
    ticket, requester = _open_ticket(queue_row)
    before = _counts()
    raw = _mail("Tickets@Stand.Test", subject=_subject(ticket), to=[MAILBOX])
    result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email=MAILBOX)
    assert result == "rejected_self"
    assert (inbound.outcome, inbound.status) == ("rejected_self", "processed")
    assert inbound.ticket_id is None and inbound.processed_at is not None
    assert _counts() == before
    assert len(_incoming(ticket)) == 1


def test_mail_from_smtp_from_address_rejected_like_mailbox(settings, protected_root, django_capture_on_commit_callbacks):
    """FR-214: письмо с адреса отправки портала (`DEFAULT_FROM_EMAIL`) — тот же итог `rejected_self`."""
    queue_row = _prepare(settings)
    ticket, _requester = _open_ticket(queue_row)
    before = _counts()
    raw = _mail("Portal@Corp.Test", subject=_subject(ticket))
    result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email=SMTP_FROM)
    assert result == "rejected_self"
    assert (inbound.outcome, inbound.status) == ("rejected_self", "processed")
    assert _counts() == before


def test_auto_submitted_precedence_and_empty_return_path_are_automatic_no_ticket_no_append_no_confirmation(
        settings, protected_root, django_capture_on_commit_callbacks):
    """FR-216, FR-220: `Auto-Submitted` не `no`, `Precedence` bulk/junk/list, `Return-Path: <>` — итог `auto`;
    заявка не создана, в заявку по номеру не дописано, подтверждения нет."""
    queue_row = _prepare(settings)
    ticket, requester = _open_ticket(queue_row)
    variants = [{"Auto-Submitted": "auto-replied"}, {"Auto-Submitted": "Auto-Generated; reason=x"},
                {"Precedence": "bulk"}, {"Precedence": "junk"}, {"Precedence": "LIST"}, {"Return-Path": "<>"}]
    for headers in variants:
        before = _counts()
        raw = _mail(requester.email, subject=_subject(ticket), headers=headers)
        result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email=requester.email)
        assert result == "auto", headers
        assert (inbound.outcome, inbound.status) == ("auto", "processed"), headers
        assert inbound.ticket_id is None
        assert _counts() == before, headers
    assert len(_incoming(ticket)) == 1


def test_auto_submitted_no_is_not_automatic(settings, protected_root, django_capture_on_commit_callbacks):
    """FR-216: `Auto-Submitted: no` (в любом регистре, с хвостом после «;») письмо автоматическим не делает:
    создана заявка."""
    _prepare(settings)
    for index, value in enumerate(["no", "NO", "No; comment"]):
        sender = f"human{index}@{DOMAIN}"
        before = model("servicedesk.Ticket").objects.count()
        raw = _mail(sender, subject="Нужна помощь", headers={"Auto-Submitted": value})
        result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email=sender)
        assert result == "created", value
        assert inbound.outcome == "created" and inbound.ticket_id is not None
        assert model("servicedesk.Ticket").objects.count() == before + 1


def test_mailbox_check_precedes_automatic_check(settings, protected_root, django_capture_on_commit_callbacks):
    """FR-214, FR-216: автоматическое письмо с адреса ящика — `rejected_self`, а не `auto` (сценарий 11.8)."""
    _prepare(settings)
    raw = _mail(MAILBOX, subject="Недоставлено", headers={"Auto-Submitted": "auto-generated"})
    result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email=MAILBOX)
    assert result == "rejected_self"
    assert inbound.outcome == "rejected_self"
    assert model("servicedesk.Ticket").objects.count() == 0


def test_automatic_foreign_domain_mail_gets_automatic_outcome_not_foreign(settings, protected_root,
                                                                         django_capture_on_commit_callbacks):
    """FR-214, FR-216: автоматическое письмо чужого домена — `auto`, а не `rejected_domain` (сценарий 11.8)."""
    _prepare(settings)
    raw = _mail("daemon@foreign.example", subject="Автоответ", headers={"Auto-Submitted": "auto-replied"})
    result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email="daemon@foreign.example")
    assert result == "auto"
    assert (inbound.outcome, inbound.status) == ("auto", "processed")
    assert model("servicedesk.Ticket").objects.count() == 0


def test_foreign_domain_rejected_no_ticket_no_reply_no_append(settings, protected_root, django_capture_on_commit_callbacks):
    """FR-215, FR-220: чужой домен — итог `rejected_domain`, заявки нет, ответа нет, в заявку по номеру и по
    `In-Reply-To` не дописано."""
    queue_row = _prepare(settings)
    ticket, _requester = _open_ticket(queue_row)
    outgoing = model("mail.MailMessage").objects.create(
        to=ticket.requester_email, template="ticket.reply", subject=_subject(ticket),
        message_id="<portal-1@stand.test>", related_ref=f"ticket:{ticket.pk}")
    before = _counts()
    for kwargs in ({"subject": _subject(ticket)}, {"subject": "Re: без номера", "in_reply_to": outgoing.message_id}):
        raw = _mail("stranger@foreign.example", **kwargs)
        result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email="stranger@foreign.example")
        assert result == "rejected_domain", kwargs
        assert (inbound.outcome, inbound.status) == ("rejected_domain", "processed")
        assert inbound.ticket_id is None
    assert _counts() == before
    assert len(_incoming(ticket)) == 1


def test_empty_domain_list_rejects_all_mail(settings, protected_root, django_capture_on_commit_callbacks):
    """FR-213, FR-215: пока список доменов пуст, любое письмо — `rejected_domain`, даже при выбранной очереди."""
    _prepare(settings, domains=())
    before = _counts()
    sender = f"anyone@{DOMAIN}"
    result, inbound = _run(_mail(sender, subject="Привет"), protected_root, django_capture_on_commit_callbacks,
                           from_email=sender)
    assert result == "rejected_domain"
    assert (inbound.outcome, inbound.status) == ("rejected_domain", "processed")
    assert _counts() == before


def test_reply_from_domain_removed_from_list_rejected_not_appended(settings, protected_root,
                                                                  django_capture_on_commit_callbacks):
    """FR-213, FR-215: ответ заявителя дописывается, пока домен в списке; после удаления домена из списка тот же
    заявитель в ту же заявку не дописывается: `rejected_domain`."""
    queue_row = _prepare(settings)
    ticket, requester = _open_ticket(queue_row, f"owner@{DOMAIN}")
    first = _mail(requester.email, subject=_subject(ticket, "Первый ответ"))
    result, _inbound = _run(first, protected_root, django_capture_on_commit_callbacks, from_email=requester.email)
    assert result == "appended"
    assert len(_incoming(ticket)) == 2
    sd.configure_servicedesk(domains=["other.test"])
    before = _counts()
    second = _mail(requester.email, subject=_subject(ticket, "Второй ответ"))
    result, inbound = _run(second, protected_root, django_capture_on_commit_callbacks, from_email=requester.email)
    assert result == "rejected_domain"
    assert inbound.outcome == "rejected_domain" and inbound.ticket_id is None
    assert _counts() == before
    assert len(_incoming(ticket)) == 2


def test_from_without_address_or_domain_treated_as_foreign(settings, protected_root, django_capture_on_commit_callbacks):
    """FR-214, FR-215: `From` без адреса и адрес без домена — как чужой домен: `rejected_domain`, без ошибки разбора."""
    _prepare(settings)
    variants = [_raw(b"=?utf-8?b?0KLQvtC70YzQutC+INC40LzRjw==?="), _raw(b"user@")]
    for raw in variants:
        before = _counts()
        result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks)
        assert result == "rejected_domain", raw
        assert (inbound.outcome, inbound.status) == ("rejected_domain", "processed")
        assert _counts() == before


def test_cyrillic_domain_matched_via_xn_and_unconvertible_domain_foreign(settings, protected_root,
                                                                        django_capture_on_commit_callbacks):
    """FR-214, FR-215: отправитель с кириллическим доменом сверяется с `xn--…` списка (`пример.рф` = `xn--e1afmkfd.xn--p1ai`);
    домен, не приводимый к `xn--…` (метка длиннее 63 знаков), считается чужим, даже если он есть в списке."""
    long_domain = "a" * 64 + ".ru"
    _prepare(settings, domains=("xn--e1afmkfd.xn--p1ai", long_domain))
    raw = _mail("Иван <ivan@пример.рф>", subject="Кириллица")
    result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email="ivan@пример.рф")
    assert result == "created"
    ticket = inbound.ticket
    assert ticket is not None and ticket.requester_email.endswith("@пример.рф")
    before = _counts()
    long_raw = _raw(f"user@{long_domain}".encode())
    result, inbound = _run(long_raw, protected_root, django_capture_on_commit_callbacks)
    assert result == "rejected_domain"
    assert inbound.status == "processed" and inbound.ticket_id is None
    assert _counts() == before


def test_waiting_setup_without_default_queue_then_parsed_after_setup(settings, protected_root,
                                                                    django_capture_on_commit_callbacks):
    """FR-213, FR-220: без очереди по умолчанию письмо корпоративного домена ждёт (`status` и итог `waiting_setup`),
    чужой домен отклоняется как прежде; после `queues.set_default` задание разбора доводит письмо до заявки."""
    import django_rq
    from apps.servicedesk.services import queues

    _prepare(settings, queue=False)
    sender = f"waiter@{DOMAIN}"
    result, waiting = _run(_mail(sender, subject="Жду очередь"), protected_root, django_capture_on_commit_callbacks,
                           from_email=sender)
    assert result == "waiting_setup"
    assert (waiting.outcome, waiting.status) == ("waiting_setup", "waiting_setup")
    assert waiting.ticket_id is None
    result, foreign = _run(_mail("x@foreign.example", subject="Чужое"), protected_root,
                           django_capture_on_commit_callbacks, from_email="x@foreign.example")
    assert result == "rejected_domain"
    assert model("servicedesk.Ticket").objects.count() == 0

    target = sd.make_queue()
    with django_capture_on_commit_callbacks(execute=True):
        queues.set_default(target.unit_id, actor=support.make_admin())
    jobs = [job for job in django_rq.get_queue("inbox").jobs
            if job.func_name == "apps.servicedesk.tasks.process_inbound" and job.args == (waiting.pk,)]
    assert len(jobs) == 1
    with django_capture_on_commit_callbacks(execute=True):
        jobs[0].perform()
    waiting.refresh_from_db()
    assert (waiting.outcome, waiting.status) == ("created", "processed")
    assert waiting.ticket is not None and waiting.ticket.queue_id == target.unit_id
    assert model("servicedesk.Ticket").objects.count() == 1


# --- связь с заявкой (FR-214) ---------------------------------------------------------------------

def test_ticket_number_in_subject_beats_in_reply_to_headers(settings, protected_root, django_capture_on_commit_callbacks):
    """FR-214: номер `[#N]` в теме главнее `In-Reply-To` и `References` (сценарий 11.9): письмо дописано в заявку по
    номеру, в заявку по заголовку — нет."""
    queue_row = _prepare(settings)
    requester = sd.make_requester(f"both@{DOMAIN}")
    first = sd.make_ticket(queue=queue_row, requester=requester)
    second = sd.make_ticket(queue=queue_row, requester=requester)
    for ticket in (first, second):
        sd.make_entry(ticket, "incoming", text="Первое")
    model("mail.MailMessage").objects.create(
        to=requester.email, template="ticket.reply", subject=_subject(second), message_id="<by-header@stand.test>",
        related_ref=f"ticket:{second.pk}")
    raw = _mail(requester.email, subject=_subject(first), in_reply_to="<by-header@stand.test>",
                references="<by-header@stand.test>")
    result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email=requester.email)
    assert result == "appended"
    assert inbound.ticket_id == first.pk
    assert len(_incoming(first)) == 2 and len(_incoming(second)) == 1


def test_link_by_in_reply_to_and_references_to_outgoing_and_inbound_ids(settings, protected_root,
                                                                       django_capture_on_commit_callbacks):
    """FR-214: без номера письмо связывается по `In-Reply-To` с `MailMessage.message_id` письма заявки и по `References`
    с `message_id` входящего письма, привязанного к заявке; не привязанное входящее письмо связи не даёт."""
    queue_row = _prepare(settings)
    ticket_a, requester_a = _open_ticket(queue_row, f"a-owner@{DOMAIN}")
    ticket_b, requester_b = _open_ticket(queue_row, f"b-owner@{DOMAIN}")
    model("mail.MailMessage").objects.create(
        to=requester_a.email, template="ticket.reply", subject=_subject(ticket_a), message_id="<out-a@stand.test>",
        related_ref=f"ticket:{ticket_a.pk}")
    sd.make_inbound(ticket=ticket_b, status="processed", message_id="<in-b@client.test>")
    loose = sd.make_inbound(status="processed", message_id="<loose@client.test>")
    assert loose.ticket_id is None

    raw = _mail(requester_a.email, subject="Re: без номера", in_reply_to="<out-a@stand.test>")
    result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email=requester_a.email)
    assert (result, inbound.ticket_id) == ("appended", ticket_a.pk)

    raw = _mail(requester_b.email, subject="Re: без номера", references="<old@x.test> <in-b@client.test>")
    result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email=requester_b.email)
    assert (result, inbound.ticket_id) == ("appended", ticket_b.pk)

    raw = _mail(requester_b.email, subject="Re: без номера", in_reply_to="<loose@client.test>")
    result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email=requester_b.email)
    assert result == "created"
    assert inbound.ticket_id not in (ticket_a.pk, ticket_b.pk)
    assert len(_incoming(ticket_a)) == 2 and len(_incoming(ticket_b)) == 2


def test_in_reply_to_with_extra_text_extracted_by_regex(settings, protected_root, django_capture_on_commit_callbacks):
    """FR-214: в `In-Reply-To` бывает посторонний текст — идентификатор берётся выражением `<[^<>\\s]+>`."""
    queue_row = _prepare(settings)
    ticket, requester = _open_ticket(queue_row)
    model("mail.MailMessage").objects.create(
        to=requester.email, template="ticket.reply", subject=_subject(ticket), message_id="<out-extra@stand.test>",
        related_ref=f"ticket:{ticket.pk}")
    raw = _mail(requester.email, subject="Re: без номера",
                in_reply_to="Your message of Mon <out-extra@stand.test> by Ivan")
    result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email=requester.email)
    assert (result, inbound.ticket_id) == ("appended", ticket.pk)
    assert len(_incoming(ticket)) == 2


def test_sender_requester_or_participant_appended_to_open_ticket(settings, protected_root,
                                                                django_capture_on_commit_callbacks):
    """FR-214, FR-220: письмо заявителя и неснятого участника дописывается в открытую заявку (элемент `incoming` со
    ссылкой на исходное письмо, `at` — время получения), `last_message_from` — `requester`, новой заявки и
    подтверждения нет."""
    queue_row = _prepare(settings)
    ticket, requester = _open_ticket(queue_row)
    participant = sd.make_participant(ticket, f"partner@{DOMAIN}", name="Партнёр")
    for sender in (requester.email, participant.email):
        before = _counts()
        raw = _mail(sender, subject=_subject(ticket), text=f"Дополнение от {sender}")
        result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email=sender)
        assert result == "appended", sender
        assert (inbound.outcome, inbound.status, inbound.ticket_id) == ("appended", "processed", ticket.pk)
        assert _counts() == (before[0], before[1] + 1, before[2])
        entry = inbound.entries.get()
        assert entry.kind == "incoming" and entry.ticket_id == ticket.pk
        assert entry.author_email == sender and entry.inbound_id == inbound.pk
        assert entry.at == inbound.received_at
    ticket.refresh_from_db()
    assert ticket.last_message_from == "requester"
    assert len(_incoming(ticket)) == 3
    assert model("servicedesk.Ticket").objects.count() == 1


def test_stranger_corporate_sender_with_ticket_number_creates_new_ticket(settings, protected_root,
                                                                        django_capture_on_commit_callbacks):
    """FR-214: корпоративный адрес, не заявитель и не участник, с номером чужой заявки — новая заявка в очереди по
    умолчанию (подтверждение — ему), в чужую заявку ничего не дописано (сценарий 11.4)."""
    queue_row = _prepare(settings)
    ticket, _requester = _open_ticket(queue_row)
    stranger = f"stranger@{DOMAIN}"
    raw = _mail(stranger, subject=_subject(ticket, "Хочу в чужую заявку"))
    result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email=stranger)
    assert result == "created"
    created = inbound.ticket
    assert created.pk != ticket.pk and created.requester_email == stranger
    assert created.queue_id == queue_row.unit_id
    assert len(_incoming(ticket)) == 1
    mails = sd.ticket_mails(created)
    assert [m.template for m in mails] == ["ticket.confirmation"] and mails[0].to == stranger
    assert sd.ticket_mails(ticket) == []


def test_removed_participant_mail_creates_new_ticket(settings, protected_root, django_capture_on_commit_callbacks):
    """FR-217, FR-214: письмо участника, которого убрали из заявки, в неё не дописывается — создана новая заявка."""
    queue_row = _prepare(settings)
    ticket, _requester = _open_ticket(queue_row)
    removed = sd.make_participant(ticket, f"removed@{DOMAIN}", removed_by=support.make_admin())
    raw = _mail(removed.email, subject=_subject(ticket, "Я всё ещё хочу писать"))
    result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email=removed.email)
    assert result == "created"
    assert inbound.ticket.pk != ticket.pk and inbound.ticket.requester_email == removed.email
    assert len(_incoming(ticket)) == 1
    removed.refresh_from_db()
    assert removed.removed_at is not None


def test_nonexistent_ticket_number_creates_new_ticket_in_default_queue(settings, protected_root,
                                                                      django_capture_on_commit_callbacks):
    """FR-214: номер несуществующей заявки (и номер больше 2147483647) — новая заявка в очереди по умолчанию
    (сценарий 11.10)."""
    queue_row = _prepare(settings)
    sender = f"person@{DOMAIN}"
    for subject in ("[#987654] Старый номер", "[#99999999999] Слишком большой номер"):
        raw = _mail(sender, subject=subject)
        result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email=sender)
        assert result == "created", subject
        assert inbound.ticket.queue_id == queue_row.unit_id
        assert inbound.ticket.number not in (987654, 99999999999)
    assert model("servicedesk.Ticket").objects.count() == 2


def test_reply_to_waiting_ticket_returns_status_to_in_progress(settings, protected_root,
                                                              django_capture_on_commit_callbacks):
    """FR-214, FR-220: письмо заявителя в заявке «ждёт ответа заявителя» дописывается, статус — «в работе» по
    умолчанию, отсчёт снят, в ленте событие «статус: было → стало» с причиной `letter`."""
    queue_row = _prepare(settings)
    ticket, requester = _open_ticket(queue_row, kind="waiting", waiting_since=timezone.now())
    assert ticket.kind == "waiting"
    raw = _mail(requester.email, subject=_subject(ticket, "Вот ответ"))
    result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email=requester.email)
    assert result == "appended"
    ticket.refresh_from_db()
    assert ticket.kind == "in_progress" and ticket.status.is_default and ticket.status.kind == "in_progress"
    assert ticket.waiting_since is None
    events = ticket.entries.filter(kind="event", event="status_changed")
    assert [e.data.get("reason") for e in events] == ["letter"]
    assert len(_incoming(ticket)) == 2


def test_closed_ticket_stranger_sender_creates_new_ticket_closed_stays(settings, protected_root,
                                                                      django_capture_on_commit_callbacks):
    """FR-251, FR-214: письмо постороннего корпоративного адреса с номером закрытой заявки не открывает её: создана
    новая заявка, закрытая остаётся закрытой, письма «открыта заново» нет."""
    queue_row = _prepare(settings)
    ticket, _requester = _open_ticket(queue_row, kind="closed", closed_at=timezone.now())
    assert ticket.kind == "closed"
    stranger = f"outsider@{DOMAIN}"
    raw = _mail(stranger, subject=_subject(ticket, "Можно открыть?"))
    result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email=stranger)
    assert result == "created"
    assert inbound.ticket.pk != ticket.pk and inbound.ticket.previous_id is None
    ticket.refresh_from_db()
    assert ticket.kind == "closed" and ticket.closed_at is not None
    assert len(_incoming(ticket)) == 1
    assert sd.ticket_mails(ticket) == []


# --- участники из копии (FR-217) ------------------------------------------------------------------

def test_cc_corporate_addresses_become_participants_excluding_mailbox_smtp_from_requester_duplicates(
        settings, protected_root, django_capture_on_commit_callbacks):
    """FR-217: участниками новой заявки становятся корпоративные адреса из всех заголовков `Cc`, без адреса ящика,
    `DEFAULT_FROM_EMAIL`, заявителя и повторов; имя берётся из заголовка."""
    _prepare(settings)
    settings.SERVICEDESK_MAILBOX = f"tickets@{DOMAIN}"
    requester = f"owner@{DOMAIN}"
    raw = _mail(requester, subject="Копия", cc=[f"Мария <maria@{DOMAIN}>", f"tickets@{DOMAIN}", SMTP_FROM,
                                                f"Owner@{DOMAIN}", f"Maria@{DOMAIN.upper()}", "outsider@other.example"],
                headers={"Cc": [f"pavel@{DOMAIN}", f"nikolay@{DOMAIN}"]})
    result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email=requester)
    assert result == "created"
    rows = list(inbound.ticket.participants.order_by("id"))
    assert sorted(p.email for p in rows) == sorted([f"maria@{DOMAIN}", f"pavel@{DOMAIN}", f"nikolay@{DOMAIN}"])
    assert {p.email: p.name for p in rows}[f"maria@{DOMAIN}"] == "Мария"
    assert all(p.removed_at is None for p in rows)


def test_cc_foreign_domain_not_participant_and_to_addresses_not_participants(settings, protected_root,
                                                                            django_capture_on_commit_callbacks):
    """FR-217: адрес чужого домена в `Cc` участником не становится; адреса из `To` (кроме ящика) — тоже."""
    _prepare(settings)
    requester = f"owner2@{DOMAIN}"
    raw = _mail(requester, subject="Копия 2", to=[MAILBOX, f"colleague@{DOMAIN}"],
                cc=[f"ok@{DOMAIN}", "bad@other.example"])
    result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email=requester)
    assert result == "created"
    assert [p.email for p in inbound.ticket.participants.all()] == [f"ok@{DOMAIN}"]


# --- ошибки, повтор, список «Входящие письма» -----------------------------------------------------

def test_error_on_any_step_rolls_back_marks_parse_error_last_error_step_and_class_only(
        settings, protected_root, django_capture_on_commit_callbacks, monkeypatch):
    """NFR-209, FR-220: ошибка любого шага (`parse`, `checks`, `link`, `ticket`, `attachments`, `finish`) откатывает
    разбор; строка получает `status=error`, итог `parse_error`, `attempts` 1 и `last_error` «<шаг>: <класс>» без
    текста исключения; исходное исключение поднимается; повтор без сбоя создаёт ровно одну заявку; страница
    «Входящие письма» показывает шаг и кнопку «Разобрать снова»."""
    from apps.servicedesk.services import intake

    _prepare(settings)
    client = _manage_client()
    marker = "СЕКРЕТНАЯ-метка-исключения"

    def raising(*args, **kwargs):
        raise _Boom(marker)

    steps = ["parse", "checks", "link", "ticket", "attachments", "finish"]
    assert set(steps) <= set(intake.STEPS)
    for index, step in enumerate(steps):
        sender = f"step{index}@{DOMAIN}"
        raw = _mail(sender, subject=f"Шаг {step}")
        inbound = _store(raw, protected_root, from_email=sender)
        before = _counts()
        with monkeypatch.context() as patch:
            patch.setitem(intake.STEPS, step, raising)
            with pytest.raises(_Boom):
                _process(inbound, django_capture_on_commit_callbacks)
        inbound.refresh_from_db()
        assert inbound.status == "error" and inbound.outcome == "parse_error", step
        assert inbound.attempts == 1, step
        assert inbound.last_error == f"{step}: _Boom", step
        assert marker not in inbound.last_error
        assert inbound.ticket_id is None and not inbound.entries.exists()
        assert _counts() == before, step
        if step == "ticket":
            row = _inbound_rows(client)[inbound.pk]
            reason = row.find_all(data_error_reason=True)
            assert len(reason) == 1 and f"{step}: _Boom" in reason[0].text()
            assert marker not in row.text()
            assert row.find_all("form", data_form="inbound-retry", action=f"/servicedesk/inbound/{inbound.pk}/retry/")
        # повтор без сбоя доводит письмо до одной заявки
        assert _process(inbound, django_capture_on_commit_callbacks) == "created", step
        inbound.refresh_from_db()
        assert (inbound.status, inbound.outcome) == ("processed", "created")
        assert model("servicedesk.Ticket").objects.count() == index + 1


def test_repeated_parse_job_creates_single_ticket(settings, protected_root, django_capture_on_commit_callbacks):
    """NFR-209: повторный разбор уже обработанного письма ничего не делает (`None`): заявка и элемент ленты одни."""
    _prepare(settings)
    sender = f"once@{DOMAIN}"
    result, inbound = _run(_mail(sender, subject="Один раз"), protected_root, django_capture_on_commit_callbacks,
                           from_email=sender)
    assert result == "created"
    counts = _counts()
    assert _process(inbound, django_capture_on_commit_callbacks) is None
    assert _process(inbound, django_capture_on_commit_callbacks) is None
    assert _counts() == counts
    assert model("servicedesk.Ticket").objects.count() == 1
    assert inbound.ticket.entries.filter(kind="incoming").count() == 1
    inbound.refresh_from_db()
    assert (inbound.outcome, inbound.status) == ("created", "processed")


def test_inbox_outcomes_for_each_result_and_source_mail_linked_to_entry_and_ticket(
        settings, protected_root, django_capture_on_commit_callbacks, monkeypatch):
    """FR-220, FR-212: после разбора каждое из восьми итогов видно на странице «Входящие письма» (`data-outcome`,
    `data-status`, подпись, ссылка «#N» у итога с заявкой); исходное письмо связано с элементом ленты и заявкой."""
    from apps.servicedesk.services import intake

    queue_row = _prepare(settings, queue=False)
    waiting_sender = f"queued@{DOMAIN}"
    _res, waiting = _run(_mail(waiting_sender, subject="Ждёт"), protected_root, django_capture_on_commit_callbacks,
                         from_email=waiting_sender)
    assert waiting.outcome == "waiting_setup"
    sd.configure_servicedesk(default_queue=queue_row)

    open_ticket, open_requester = _open_ticket(queue_row, f"open@{DOMAIN}")
    closed_ticket, closed_requester = _open_ticket(queue_row, f"shut@{DOMAIN}", kind="closed", closed_at=timezone.now())
    new_sender = f"fresh@{DOMAIN}"
    cases = {
        "created": (_mail(new_sender, subject="Новая"), new_sender),
        "appended": (_mail(open_requester.email, subject=_subject(open_ticket)), open_requester.email),
        "reopened": (_mail(closed_requester.email, subject=_subject(closed_ticket, "Опять")), closed_requester.email),
        "rejected_domain": (_mail("x@foreign.example", subject="Чужой"), "x@foreign.example"),
        "rejected_self": (_mail(MAILBOX, subject="Сам себе"), MAILBOX),
        "auto": (_mail(new_sender, subject="Авто", headers={"Auto-Submitted": "auto-replied"}), new_sender),
    }
    done = {"waiting_setup": waiting}
    for outcome, (raw, sender) in cases.items():
        result, inbound = _run(raw, protected_root, django_capture_on_commit_callbacks, from_email=sender,
                               subject=outcome)
        assert result == outcome and inbound.outcome == outcome
        done[outcome] = inbound
    broken_sender = f"broken@{DOMAIN}"
    broken = _store(_mail(broken_sender, subject="Сломается"), protected_root, from_email=broken_sender)

    def raising(*args, **kwargs):
        raise _Boom("x")

    with monkeypatch.context() as patch:
        patch.setitem(intake.STEPS, "ticket", raising)
        with pytest.raises(_Boom):
            _process(broken, django_capture_on_commit_callbacks)
    broken.refresh_from_db()
    done["parse_error"] = broken
    assert set(done) == set(LABELS)

    # связи исходного письма
    for outcome in ("created", "appended", "reopened"):
        inbound = done[outcome]
        entry = inbound.entries.get()
        assert inbound.ticket_id is not None and inbound.processed_at is not None
        assert entry.kind == "incoming" and entry.ticket_id == inbound.ticket_id
        assert entry.inbound_id == inbound.pk and entry.at == inbound.received_at
    assert done["appended"].ticket_id == open_ticket.pk and done["reopened"].ticket_id == closed_ticket.pk
    closed_ticket.refresh_from_db()
    assert closed_ticket.kind == "in_progress"
    for outcome in ("rejected_domain", "rejected_self", "auto", "waiting_setup", "parse_error"):
        assert done[outcome].ticket_id is None and not done[outcome].entries.exists(), outcome

    # страница «Входящие письма»
    rows = _inbound_rows(_manage_client())
    for outcome, inbound in done.items():
        row = rows[inbound.pk]
        assert row.attrs["data-outcome"] == outcome
        assert row.attrs["data-status"] == inbound.status
        cell = row.find_all(None, data_cell="outcome")
        assert len(cell) == 1 and LABELS[outcome] in cell[0].text(), outcome
        links = row.find_all("a", data_ticket_link=True)
        if inbound.ticket_id:
            assert [(a.attrs["href"], a.text()) for a in links] == [
                (f"/tickets/{inbound.ticket.number}/", f"#{inbound.ticket.number}")], outcome
        else:
            assert links == [], outcome
    assert done["waiting_setup"].status == "waiting_setup" and done["parse_error"].status == "error"
