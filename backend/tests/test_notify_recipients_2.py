"""T-4107: получатели «Заявитель ответил» и «Ответ заявителю не ушёл», доступ, учётные записи (FR-308, FR-309,
FR-311, FR-312, FR-314, FR-315, FR-345). Сценарии 2, 3 и 1 спеки среза 004.

Виды берутся из `kinds.catalog()`, получатели считает `kind.build(event, data)` (контракт 4.3; данные событий — 4.2),
запись и доставки — `dispatch.create` и `dispatch.on_event` (6.7). Исходящее письмо и недоставка идут настоящими
путями среза 003 (`replies.reply`, событие `mail.failed`). Имена кода среза 004 импортируются внутри тестов.
"""
import importlib
import logging
import secrets
import types
from email import policy
import email

import pytest
from django.utils import timezone

from tests import factories, support, support_servicedesk as sd
from tests import support_org as org
from tests import support_notify as notify
from tests.support import model

pytestmark = pytest.mark.django_db

DOMAIN = "corp.test"
MAILBOX = "tickets@stand.test"
REQUESTER_REPLIED = "servicedesk.requester_replied"
REPLY_FAILED = "servicedesk.reply_failed"
NEW_IN_QUEUE = "servicedesk.new_in_queue"
ASSIGNED = "servicedesk.assigned"
SD_CODES = (NEW_IN_QUEUE, ASSIGNED, REQUESTER_REPLIED, REPLY_FAILED)


# --- помощники только этого файла -------------------------------------------------------------------

def _kinds():
    return importlib.import_module("apps.notify.services.kinds")


def _dispatch():
    return importlib.import_module("apps.notify.services.dispatch")


def _kind(code: str):
    """Вид из `kinds.catalog()` по коду (контракт 4.3)."""
    by_code = {kind.code: kind for kind in _kinds().catalog()}
    assert code in by_code, f"в каталоге нет вида {code}"
    return by_code[code]


def _member(unit, *, state: str = "active", mark: str = ""):
    user = support.make_employee(state=state)
    org.make_member(user, unit, mark=mark)
    return user


def _world(*, assignee: bool = True, kind: str | None = None, queue_name: str | None = None):
    """Очередь, два прямых участника (`worker`, `colleague`) и заявка; ответственный — `worker` или никого."""
    unit = org.make_unit(queue_name or f"Очередь {secrets.token_hex(3)}")
    queue = sd.make_queue(unit)
    worker, colleague = _member(unit), _member(unit)
    kind = kind or ("in_progress" if assignee else "new")
    over = {"closed_at": timezone.now()} if kind == "closed" else {}
    ticket = sd.make_ticket(queue=queue, kind=kind, assignee=worker if assignee else None,
                            assigned_once=assignee, **over)
    return types.SimpleNamespace(unit=unit, queue=queue, ticket=ticket, worker=worker, colleague=colleague)


def _ref(ticket) -> str:
    return f"servicedesk.ticket:{ticket.pk}"


def _url(ticket) -> str:
    return f"/tickets/{ticket.number}/"


def _reply_data(ticket, *, via: str = "appended", author_kind: str = "requester", entry_id: int | None = None) -> dict:
    """Данные `servicedesk.reply_received` (контракт 4.2): оба поля ответственного — текущий ответственный."""
    return {"number": ticket.number, "queue_id": ticket.queue_id, "assignee_before_id": ticket.assignee_id,
            "assignee_after_id": ticket.assignee_id, "actor_id": None, "via": via, "author_kind": author_kind,
            "entry_id": entry_id}


def _not_sent_data(ticket, reason: str, *, author_id: int) -> dict:
    """Данные `servicedesk.reply_not_sent` (контракт 4.2): `actor_id=None` задаёт помощник события."""
    return {"number": ticket.number, "entry_id": 1, "reason": reason, "author_id": author_id, "actor_id": None}


def _created_data(ticket, *, actor_id=None, channel: str = "mail") -> dict:
    return {"number": ticket.number, "queue_id": ticket.queue_id, "assignee_before_id": None,
            "assignee_after_id": ticket.assignee_id, "actor_id": actor_id, "channel": channel}


def _reopened_data(ticket, *, via: str = "mail", actor_id=None) -> dict:
    return {"number": ticket.number, "queue_id": ticket.queue_id, "via": via, "actor_id": actor_id,
            "assignee_id": ticket.assignee_id}


def _notes(user, code: str | None = None) -> list:
    rows = model("notify.Notification").objects.filter(user=user)
    if code is not None:
        rows = rows.filter(kind=code)
    return list(rows.order_by("id"))


def _users(drafts) -> list[int]:
    return sorted(draft.user_id for draft in drafts)


def _no_subscriber_errors(caplog) -> None:
    """Правило шапки контракта (решение 24 задач): в журнале шины нет записей уровня ERROR."""
    errors = [r for r in caplog.records if r.name == "apps.core.events" and r.levelno >= logging.ERROR]
    assert errors == [], "сбой подписчика шины: " + "; ".join(r.getMessage() for r in errors)


def _event(name: str, **data):
    return _dispatch().on_event(name, **data)


# --- письма: разбор входящего письма (как в test_sd_intake.py) --------------------------------------------

def _prepare_mail(settings, queue):
    settings.SERVICEDESK_MAILBOX = MAILBOX
    settings.DEFAULT_FROM_EMAIL = "portal@corp.test"
    sd.configure_servicedesk(domains=[DOMAIN], default_queue=queue)


def _store(raw: bytes, protected_root, **over):
    message = email.message_from_bytes(raw, policy=policy.default)
    fields = {"from_email": "", "subject": "", "message_id": str(message["Message-ID"] or "")}
    fields.update(over)
    inbound = sd.make_inbound(size=len(raw), **fields)
    folder = protected_root / "inbound"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{inbound.pk}.eml").write_bytes(raw)
    return inbound


def _mail_reopens(world, settings, protected_root, capture) -> str:
    """Письмо заявителя в закрытую заявку: разбор `intake.process`; возвращает итог разбора."""
    from apps.servicedesk.services import intake

    _prepare_mail(settings, world.queue)
    sender = world.ticket.requester_email
    raw = sd.build_mail(from_addr=sender, subject=f"[#{world.ticket.number}] Опять", text="Проблема вернулась")
    inbound = _store(raw, protected_root, from_email=sender)
    with capture(execute=True):
        return intake.process(inbound.pk)


def _closed_world(*, assignee: bool):
    """Закрытая заявка в очереди с заявителем из корпоративного домена."""
    world = _world(assignee=assignee, kind="closed")
    requester = sd.make_requester(f"shut-{secrets.token_hex(3)}@{DOMAIN}")
    type(world.ticket).objects.filter(pk=world.ticket.pk).update(
        requester=requester, requester_email=requester.email)
    world.ticket.refresh_from_db()
    return world


# --- «Заявитель ответил» (FR-311) -------------------------------------------------------------------------

def test_reply_from_requester_notifies_assignee(django_capture_on_commit_callbacks, caplog):
    """FR-311: письмо заявителя в открытую заявку — одна запись ответственному, текст, ссылка и объект по 15.1 и 4.3."""
    world = _world()
    tickets = importlib.import_module("apps.servicedesk.services.tickets")
    with django_capture_on_commit_callbacks(execute=True):
        entry = tickets.add_incoming(world.ticket, author_email=world.ticket.requester_email, text="Нужна помощь")
    (note,) = _notes(world.worker)
    assert note.kind == REQUESTER_REPLIED
    assert note.text == f"Заявитель ответил в заявке #{world.ticket.number}: {world.ticket.subject}"
    assert note.url == _url(world.ticket) and note.object_ref == _ref(world.ticket)
    assert _notes(world.colleague) == [], "прямой участник очереди без ответственности записи не получает"
    assert entry.kind == "incoming"
    _no_subscriber_errors(caplog)


def test_reply_from_copy_participant_notifies_assignee(django_capture_on_commit_callbacks, caplog):
    """FR-311: письмо участника из копии — тоже «Заявитель ответил» ответственному (`author_kind="participant"`)."""
    world = _world()
    cc_address = f"cc-{secrets.token_hex(3)}@{DOMAIN}"
    sd.make_participant(world.ticket, cc_address)
    tickets = importlib.import_module("apps.servicedesk.services.tickets")
    with django_capture_on_commit_callbacks(execute=True):
        tickets.add_incoming(world.ticket, author_email=cc_address, text="Добавлю от себя")
    (note,) = _notes(world.worker)
    assert note.kind == REQUESTER_REPLIED and note.object_ref == _ref(world.ticket)
    assert note.text == f"Заявитель ответил в заявке #{world.ticket.number}: {world.ticket.subject}"
    assert _notes(world.colleague) == []
    _no_subscriber_errors(caplog)


def test_reply_reopening_closed_ticket_notifies_assignee():
    """FR-311: данные `reply_received` с `via="reopened"` дают то же, что `appended`; открытие письмом целиком — в тестах ниже."""
    world = _world()
    kind = _kind(REQUESTER_REPLIED)
    for via in ("appended", "reopened"):
        drafts = kind.build("servicedesk.reply_received", _reply_data(world.ticket, via=via, entry_id=7))
        assert _users(drafts) == [world.worker.pk], via
        (draft,) = drafts
        assert draft.url == _url(world.ticket) and draft.object_ref == _ref(world.ticket)
        assert draft.text == f"Заявитель ответил в заявке #{world.ticket.number}: {world.ticket.subject}"


def test_reply_to_ticket_without_assignee_gives_no_requester_replied():
    """FR-311: у заявки без ответственного «Заявитель ответил» нет; с ответственным (контроль) — один черновик."""
    world = _world(assignee=False)
    kind = _kind(REQUESTER_REPLIED)
    for via in ("appended", "reopened"):
        assert kind.build("servicedesk.reply_received", _reply_data(world.ticket, via=via)) == [], via
    type(world.ticket).objects.filter(pk=world.ticket.pk).update(assignee=world.worker, kind="in_progress")
    world.ticket.refresh_from_db()
    drafts = kind.build("servicedesk.reply_received", _reply_data(world.ticket))
    assert _users(drafts) == [world.worker.pk], "контроль: с ответственным черновик есть"


def test_mail_reopen_with_assignee_gives_only_requester_replied(
        settings, protected_root, django_capture_on_commit_callbacks, caplog):
    """FR-309, FR-311: письмо открыло закрытую заявку, ответственный остался — только «Заявитель ответил» ему."""
    world = _closed_world(assignee=True)
    assert _mail_reopens(world, settings, protected_root, django_capture_on_commit_callbacks) == "reopened"
    world.ticket.refresh_from_db()
    assert world.ticket.kind == "in_progress" and world.ticket.assignee_id == world.worker.pk
    (note,) = _notes(world.worker)
    assert note.kind == REQUESTER_REPLIED and note.url == _url(world.ticket)
    assert _notes(world.colleague) == [], "«Новой заявки в очереди» нет: ответственный остался"
    assert model("notify.Notification").objects.filter(kind=NEW_IN_QUEUE).count() == 0
    _no_subscriber_errors(caplog)


def test_mail_reopen_without_assignee_gives_only_new_in_queue(
        settings, protected_root, django_capture_on_commit_callbacks, caplog):
    """FR-309, FR-311: письмо открыло закрытую заявку без ответственного — «Новая заявка» прямым участникам, ответов нет."""
    world = _closed_world(assignee=False)
    assert _mail_reopens(world, settings, protected_root, django_capture_on_commit_callbacks) == "reopened"
    world.ticket.refresh_from_db()
    assert world.ticket.kind == "in_progress" and world.ticket.assignee_id is None
    for person in (world.worker, world.colleague):
        (note,) = _notes(person)
        assert note.kind == NEW_IN_QUEUE and note.url == _url(world.ticket) and note.object_ref == _ref(world.ticket)
    assert model("notify.Notification").objects.filter(kind=REQUESTER_REPLIED).count() == 0
    _no_subscriber_errors(caplog)


def test_assignee_own_outgoing_reply_gives_no_notification(
        django_capture_on_commit_callbacks, bus_spy, caplog):
    """FR-315: ответ, отправленный самим ответственным, не `reply_received` и не даёт записей никому."""
    world = _world()
    bus_spy.listen("servicedesk.reply_received")
    replies = importlib.import_module("apps.servicedesk.services.replies")
    with django_capture_on_commit_callbacks(execute=True):
        entry = replies.reply(world.ticket, text="Ответ исполнителя", actor=world.worker)
    assert entry.kind == "reply", "ответ создан"
    assert bus_spy.calls("servicedesk.reply_received") == []
    assert model("notify.Notification").objects.count() == 0
    _no_subscriber_errors(caplog)


# --- «Ответ заявителю не ушёл» (FR-312) ---------------------------------------------------------------------

def test_reply_not_sent_quarantine_notifies_assignee():
    """FR-312: вложение ответа в карантине — «Ответ заявителю не ушёл» ответственному, текст по причине (15.1)."""
    world = _world()
    drafts = _kind(REPLY_FAILED).build(
        "servicedesk.reply_not_sent", _not_sent_data(world.ticket, "quarantine", author_id=world.colleague.pk))
    assert _users(drafts) == [world.worker.pk]
    (draft,) = drafts
    assert draft.text == f"Ответ по заявке #{world.ticket.number} не отправлен: вложение в карантине"
    assert draft.url == _url(world.ticket) and draft.object_ref == _ref(world.ticket)


def test_reply_not_sent_encrypted_archive_notifies_assignee():
    """FR-312: вложение — архив с паролем — то же, текст «…: вложение — архив с паролем»."""
    world = _world()
    drafts = _kind(REPLY_FAILED).build(
        "servicedesk.reply_not_sent", _not_sent_data(world.ticket, "encrypted", author_id=world.colleague.pk))
    assert _users(drafts) == [world.worker.pk]
    (draft,) = drafts
    assert draft.text == f"Ответ по заявке #{world.ticket.number} не отправлен: вложение — архив с паролем"
    assert draft.url == _url(world.ticket) and draft.object_ref == _ref(world.ticket)


def test_reply_not_sent_ticket_closed_gives_no_notification():
    """FR-312: заявка закрыта, пока шла проверка вложений, — уведомления нет; при карантине (контроль) оно есть."""
    world = _world()
    kind = _kind(REPLY_FAILED)
    assert kind.build("servicedesk.reply_not_sent",
                      _not_sent_data(world.ticket, "ticket_closed", author_id=world.colleague.pk)) == []
    control = kind.build("servicedesk.reply_not_sent",
                         _not_sent_data(world.ticket, "quarantine", author_id=world.colleague.pk))
    assert _users(control) == [world.worker.pk]
    assert kind.build("servicedesk.ticket_closed", {
        "number": world.ticket.number, "queue_id": world.ticket.queue_id, "assignee_before_id": world.worker.pk,
        "assignee_after_id": world.worker.pk, "actor_id": world.colleague.pk}) == [], "закрытие вид не обслуживает"


def test_reply_not_sent_notifies_assignee_even_if_author_is_someone_else_because_actor_is_none():
    """FR-312, FR-315: `actor_id=None` — уведомление получает ответственный, даже когда автор ответа он сам или коллега."""
    world = _world()
    kind = _kind(REPLY_FAILED)
    for author in (world.colleague, world.worker):
        drafts = kind.build("servicedesk.reply_not_sent",
                            _not_sent_data(world.ticket, "quarantine", author_id=author.pk))
        assert _users(drafts) == [world.worker.pk], f"автор {author.pk}"
    assert _users(kind.build("servicedesk.reply_not_sent",
                             _not_sent_data(world.ticket, "encrypted", author_id=world.worker.pk))) == [world.worker.pk]


_MAIL_KINDS = ("confirmation", "assigned", "reply", "closed", "reopened", "autoclosed")


def _fail_mail(ticket, mail_kind: str):
    """Письмо заявки с недоставкой: событие почтового модуля `mail.failed` (`related_ref="ticket:<pk>"`, решение E8)."""
    from apps.core import events

    message = model("mail.MailMessage").objects.create(
        to=ticket.requester_email, template=f"ticket.{mail_kind}", subject=ticket.subject, status="failed",
        related_ref=f"ticket:{ticket.pk}")
    events.publish("mail.failed", mail_id=message.pk, related_ref=message.related_ref)
    return message


def test_mail_failed_notifies_assignee_for_each_mail_kind(bus_spy, django_capture_on_commit_callbacks, caplog):
    """FR-312: недоставка письма любого вида (шесть шаблонов) — «Письмо по заявке #N не доставлено» ответственному."""
    world = _world()
    bus_spy.listen("servicedesk.mail_failed")

    with django_capture_on_commit_callbacks(execute=True):
        for mail_kind in _MAIL_KINDS:
            _fail_mail(world.ticket, mail_kind)
    published = bus_spy.calls("servicedesk.mail_failed")
    assert sorted(call["mail_kind"] for call in published) == sorted(_MAIL_KINDS)
    assert {call["number"] for call in published} == {world.ticket.number}
    assert all(call["actor_id"] is None for call in published)
    notes = _notes(world.worker, REPLY_FAILED)
    assert len(notes) == len(_MAIL_KINDS)
    for note in notes:
        assert note.text == f"Письмо по заявке #{world.ticket.number} не доставлено"
        assert note.url == _url(world.ticket) and note.object_ref == _ref(world.ticket)
    assert _notes(world.colleague) == []
    _no_subscriber_errors(caplog)


def test_mail_failed_without_assignee_gives_no_notification(bus_spy, django_capture_on_commit_callbacks, caplog):
    """FR-312: у заявки без ответственного недоставка записей не даёт (событие при этом опубликовано)."""
    world = _world(assignee=False)
    bus_spy.listen("servicedesk.mail_failed")
    with django_capture_on_commit_callbacks(execute=True):
        _fail_mail(world.ticket, "reply")
    assert [call["number"] for call in bus_spy.calls("servicedesk.mail_failed")] == [world.ticket.number]
    assert model("notify.Notification").objects.count() == 0
    _no_subscriber_errors(caplog)


def test_reply_not_sent_without_assignee_gives_no_notification():
    """FR-312: «ответ не отправлен» по заявке без ответственного — черновиков нет; с ответственным (контроль) — один."""
    world = _world(assignee=False)
    kind = _kind(REPLY_FAILED)
    for reason in ("quarantine", "encrypted"):
        assert kind.build("servicedesk.reply_not_sent",
                          _not_sent_data(world.ticket, reason, author_id=world.colleague.pk)) == [], reason
    type(world.ticket).objects.filter(pk=world.ticket.pk).update(assignee=world.worker, kind="in_progress")
    world.ticket.refresh_from_db()
    assert _users(kind.build("servicedesk.reply_not_sent",
                             _not_sent_data(world.ticket, "quarantine", author_id=world.colleague.pk))) == [world.worker.pk]


# --- доступ к заявке (FR-314) -----------------------------------------------------------------------------

def test_employee_without_access_to_ticket_gets_no_notification():
    """FR-314: прямой участник чужой очереди (данные события называют её, заявка в базе в другой) записи не получает."""
    world = _world(assignee=False)
    other_unit = org.make_unit(f"Чужая очередь {secrets.token_hex(3)}")
    other_queue = sd.make_queue(other_unit)
    outsider = _member(other_unit)
    kind = _kind(NEW_IN_QUEUE)
    consistent = kind.build("servicedesk.ticket_created", _created_data(world.ticket))
    assert _users(consistent) == sorted([world.worker.pk, world.colleague.pk]), "контроль: участники очереди заявки"
    diverged = _created_data(world.ticket)
    diverged["queue_id"] = other_queue.unit_id
    recipients = _users(kind.build("servicedesk.ticket_created", diverged))
    assert outsider.pk not in recipients, "доступ к заявке есть только у тех, кто её видит (can_work)"
    # то же через диспетчер: запись у постороннего не создаётся
    _event("servicedesk.ticket_created", **diverged)
    assert _notes(outsider) == []


def test_employee_who_left_queue_before_event_gets_no_new_in_queue():
    """FR-314, FR-308: вышедший из узла до события «Новой заявки в очереди» не получает; оставшийся участник — получает."""
    world = _world(assignee=False)
    model("org.Membership").objects.filter(user=world.colleague, unit=world.unit).delete()
    ids = _event("servicedesk.ticket_created", **_created_data(world.ticket))
    assert len(ids) == 1
    assert [n.user_id for n in _notes(world.worker)] == [world.worker.pk]
    assert _notes(world.worker)[0].kind == NEW_IN_QUEUE
    assert _notes(world.colleague) == []
    drafts = _kind(NEW_IN_QUEUE).build("servicedesk.ticket_created", _created_data(world.ticket))
    assert _users(drafts) == [world.worker.pk]


def test_access_lost_after_notification_keeps_record_and_link_gives_not_found(django_capture_on_commit_callbacks):
    """FR-314: доступ пропал позже — запись в списке остаётся, ссылка ведёт на отказ, как у несуществующей заявки."""
    world = _world(assignee=False)
    with django_capture_on_commit_callbacks(execute=True):
        ids = _event("servicedesk.ticket_created", **_created_data(world.ticket))
    (note,) = _notes(world.colleague)
    assert note.pk in ids and note.url == _url(world.ticket)
    model("org.Membership").objects.filter(user=world.colleague, unit=world.unit).delete()
    client = support.logged_in(world.colleague)
    opened = client.get(f"/notifications/{note.pk}/open/")
    assert opened.status_code == 302 and opened["Location"].endswith(_url(world.ticket))
    assert client.get(_url(world.ticket)).status_code == 404
    assert client.get(f"/tickets/{world.ticket.number + 100000}/").status_code == 404, "как у несуществующей заявки"
    assert model("notify.Notification").objects.filter(pk=note.pk, user=world.colleague).exists()


# --- состояния учётной записи (FR-345) --------------------------------------------------------------------

def test_dismissed_employee_gets_no_record():
    """FR-345: уволенный записи не получает: ни из `build`, ни из `dispatch.create`; активный (контроль) получает."""
    world = _world()
    dismissed = _member(world.unit, state="dismissed")
    kind = _kind(REQUESTER_REPLIED)
    type(world.ticket).objects.filter(pk=world.ticket.pk).update(assignee=dismissed)
    world.ticket.refresh_from_db()
    assert kind.build("servicedesk.reply_received", _reply_data(world.ticket)) == []
    from apps.core.extensions import Draft

    def draft(user):
        return Draft(user_id=user.pk, text="Проверка", url=_url(world.ticket), object_ref=_ref(world.ticket))

    ids = _dispatch().create(REQUESTER_REPLIED, [draft(dismissed), draft(world.worker)])
    assert len(ids) == 1
    assert _notes(dismissed) == [] and len(_notes(world.worker)) == 1


def test_invited_employee_who_never_logged_in_gets_no_record():
    """FR-345: приглашённый, не входивший, записи не получает; он не входит в `direct_members` узла."""
    world = _world(assignee=False)
    invited = _member(world.unit, state="invited")
    structure = importlib.import_module("apps.org.services.structure")
    assert invited.pk not in [p.id for p in structure.direct_members(world.unit.pk)]
    assert world.worker.pk in [p.id for p in structure.direct_members(world.unit.pk)]
    from apps.core.extensions import Draft

    def draft(user):
        return Draft(user_id=user.pk, text="Проверка", url=_url(world.ticket), object_ref=_ref(world.ticket))

    ids = _dispatch().create(NEW_IN_QUEUE, [draft(invited), draft(world.worker)])
    assert len(ids) == 1
    assert _notes(invited) == [] and len(_notes(world.worker)) == 1
    ids = _event("servicedesk.ticket_created", **_created_data(world.ticket))
    assert len(ids) == 2 and _notes(invited) == []


def test_blocked_employee_gets_portal_record_without_external_deliveries(
        webpush_on, django_capture_on_commit_callbacks):
    """FR-345: заблокированный получает запись на портале, но ни одной доставки; активный (контроль) — с письмом."""
    world = _world(assignee=False)
    blocked = _member(world.unit, state="blocked")
    structure = importlib.import_module("apps.org.services.structure")
    assert blocked.pk in [p.id for p in structure.direct_members(world.unit.pk)]
    notify.subscribe(blocked)
    notify.subscribe(world.worker)
    with django_capture_on_commit_callbacks(execute=True):
        ids = _event("servicedesk.ticket_created", **_created_data(world.ticket))
    assert len(ids) == 3
    (note,) = _notes(blocked, NEW_IN_QUEUE)
    assert note.url == _url(world.ticket) and note.read_at is None
    assert note.deliveries.count() == 0, "заблокированному доставок нет"
    (active_note,) = _notes(world.worker, NEW_IN_QUEUE)
    assert active_note.deliveries.filter(channel="email").exists(), "контроль: активному письмо создано"
    assert not model("notify.Delivery").objects.filter(notification__user=blocked).exists()


# --- `still_relevant` (FR-314) ----------------------------------------------------------------------------

def _relevant(user, ticket) -> dict:
    return {code: _kind(code).still_relevant(user.pk, _ref(ticket)) for code in SD_CODES}


def test_still_relevant_true_when_user_sees_ticket_without_assignee_and_not_closed():
    """FR-314: участник очереди, заявка без ответственного и не закрыта — все четыре вида актуальны."""
    world = _world(assignee=False)
    assert _relevant(world.colleague, world.ticket) == {code: True for code in SD_CODES}


def test_still_relevant_of_new_in_queue_false_when_assignee_appeared_or_ticket_closed_while_other_sd_kinds_stay_true():
    """FR-314: у «Новой заявки в моей очереди» ответственный или закрытие снимают актуальность, у остальных — нет."""
    world = _world(assignee=False)
    stay = {code: True for code in SD_CODES}
    assert _relevant(world.colleague, world.ticket) == stay
    type(world.ticket).objects.filter(pk=world.ticket.pk).update(assignee=world.worker, kind="in_progress")
    assert _relevant(world.colleague, world.ticket) == {**stay, NEW_IN_QUEUE: False}
    type(world.ticket).objects.filter(pk=world.ticket.pk).update(
        assignee=None, kind="closed", closed_at=timezone.now())
    assert _relevant(world.colleague, world.ticket) == {**stay, NEW_IN_QUEUE: False}
    assert _kind(NEW_IN_QUEUE).still_relevant(world.colleague.pk, "") is False, "пустая ссылка"
    assert _kind(NEW_IN_QUEUE).still_relevant(world.colleague.pk, "core.user:1") is False, "чужой модуль"
    assert _kind(REPLY_FAILED).still_relevant(world.colleague.pk, f"servicedesk.ticket:{world.ticket.pk + 99999}") is False


def test_still_relevant_false_when_user_lost_access_using_fresh_scope():
    """FR-314: доступ по праву «Все заявки» снят без сброса кэша прав — свежий `scope` это учитывает; члена узла — тоже."""
    unit = org.make_unit(f"Очередь {secrets.token_hex(3)}")
    queue = sd.make_queue(unit)
    ticket = sd.make_ticket(queue=queue, kind="in_progress", assignee=None)
    holder = support.make_with_permissions("servicedesk.all")
    permissions = importlib.import_module("apps.core.services.permissions")
    assert "servicedesk.all" in permissions.permissions_of(holder), "кэш прав прогрет"
    assert _relevant(holder, ticket) == {code: True for code in SD_CODES}
    holder.roles.clear()
    assert "servicedesk.all" in permissions.permissions_of(holder), "предусловие теста: кэш прав ещё старый"
    assert _relevant(holder, ticket) == {code: False for code in SD_CODES}
    member = _member(unit)
    assert _relevant(member, ticket)[ASSIGNED] is True
    model("org.Membership").objects.filter(user=member, unit=unit).delete()
    assert _relevant(member, ticket) == {code: False for code in SD_CODES}


def test_still_relevant_false_for_dismissed_user():
    """FR-314: уволенный — ни один вид сервис-деска не актуален; пока он работал (контроль) — актуальны."""
    world = _world(assignee=False)
    assert _relevant(world.colleague, world.ticket) == {code: True for code in SD_CODES}
    type(world.colleague).objects.filter(pk=world.colleague.pk).update(state="dismissed")
    assert _relevant(world.colleague, world.ticket) == {code: False for code in SD_CODES}
    assert _kind(NEW_IN_QUEUE).still_relevant(10 ** 9, _ref(world.ticket)) is False, "пользователя нет"
