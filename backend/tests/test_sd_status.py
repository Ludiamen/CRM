"""T-3110: статусы, переходы и отсчёт автозакрытия (FR-206, FR-208, FR-209, FR-250). Сценарии 3 и 5 спеки.

Переходы по FR-208 (создание, первое назначение, ответ с флажком и без, письма заявителя и участника,
внутренний комментарий, закрытие и открытие заново), событие ленты «статус: было → стало» при каждой смене,
ручная смена (список `manual_statuses`, отказ `bad_status` и прямому запросу), поле `waiting_since`
(вход в вид «ждёт ответа», переход внутри вида, выход, постановка письма ответа в очередь, карантин).
Код среза на уровне модуля не импортируется: имена берутся внутри тестов (CONTRACT-003, шапка).
"""
import importlib
import re
from datetime import timedelta

import pytest
from django.utils import timezone

from tests import factories, support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

SECOND = timedelta(seconds=1)


# --- помощники только этого файла ------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.servicedesk.services.{name}")


def _errors():
    return importlib.import_module("apps.servicedesk.services").ServiceDeskError


def _actor():
    """Сотрудник с правом `servicedesk.all`: видит все заявки и участник любой очереди (раздел 6.4)."""
    return support.make_with_permissions("servicedesk.all")


def _default(kind: str):
    return model("servicedesk.Status").objects.get(kind=kind, is_default=True)


def _custom(kind: str, name: str, actor, *, default: bool = False):
    """Свой статус вида `kind` через `dictionaries.create`; `default=True` — переносит отметку «по умолчанию»."""
    dictionaries = _svc("dictionaries")
    status = dictionaries.create("status", name=name, kind=kind, actor=actor)
    if default:
        status = dictionaries.update(status, name=status.name, is_default=True, actor=actor)
    return status


def _ticket(kind: str = "new", **over):
    return sd.make_ticket(queue=over.pop("queue", None) or sd.make_queue(), kind=kind, **over)


def _waiting_ticket(**over):
    """Заявка в виде `waiting` с отсчётом, начатым два часа назад."""
    ticket = _ticket("waiting", **over)
    sd.backdate(ticket, "waiting_since", hours=2)
    return ticket


def _status_events(ticket) -> list[dict]:
    """`data` событий ленты `status_changed` заявки по порядку записи."""
    entries = model("servicedesk.TicketEntry").objects.filter(ticket=ticket, kind="event", event="status_changed")
    return [entry.data for entry in entries.order_by("id")]


def _fresh(ticket):
    ticket.refresh_from_db()
    return ticket


def _requester_letter(ticket, capture, **kwargs):
    tickets = _svc("tickets")
    with capture(execute=True):
        return tickets.add_incoming(ticket, author_email=ticket.requester_email, text="Ответ заявителя", **kwargs)


def _reply(ticket, actor, capture, *, wait: bool, **kwargs):
    replies = _svc("replies")
    with capture(execute=True):
        return replies.reply(ticket, text="Ответ исполнителя", wait_flag=wait, actor=actor, **kwargs)


def _manual(ticket, status, actor, capture):
    tickets = _svc("tickets")
    with capture(execute=True):
        return tickets.set_status_manual(ticket, status, actor=actor)


def _status_form_option_ids(response) -> set[int]:
    """Значения `option` в `form[data-form="ticket-status"] select[name=status]` (CONTRACT-003 § 13.3)."""
    html = response.content.decode("utf-8", "replace")
    form = re.search(r'<form\b[^>]*\bdata-form="ticket-status"[^>]*>(.*?)</form>', html, re.S)
    assert form, "в карточке нет form[data-form=ticket-status]"
    select = re.search(r'<select\b[^>]*\bname="status"[^>]*>(.*?)</select>', form.group(1), re.S)
    assert select, "в форме статуса нет select[name=status]"
    return {int(value) for value in re.findall(r'<option\b[^>]*\bvalue="(\d+)"', select.group(1))}


# --- создание и первое назначение (FR-208) -------------------------------------------------------------

def test_created_without_assignee_status_is_new(django_capture_on_commit_callbacks):
    """FR-208: заявка, созданная без ответственного, получает статус «новая» по умолчанию (вид new)."""
    tickets = _svc("tickets")
    queue = sd.make_queue()
    sd.configure_servicedesk(domains=["example.test"], default_queue=queue)
    with django_capture_on_commit_callbacks(execute=True):
        created = tickets.create(channel=tickets.MAIL, subject="Не печатает принтер", text="Помогите",
                                 requester_email=factories.new_email("req"))
    ticket = _fresh(created.ticket)
    assert ticket.assignee_id is None and ticket.assigned_once is False
    assert ticket.kind == "new"
    assert ticket.status_id == _default("new").pk
    assert ticket.waiting_since is None


def test_first_assignee_moves_new_to_default_in_work_status(django_capture_on_commit_callbacks):
    """FR-208: первый ответственный (назначили или взял себе) переводит «новая» в статус по умолчанию вида «в работе»."""
    assignment = _svc("assignment")
    actor = _actor()
    _custom("in_progress", "На согласовании", actor)  # не по умолчанию: берётся именно отмеченный
    default_in_work = _default("in_progress")
    new_status = _default("new")
    assigned, taken = _ticket("new"), _ticket("new")
    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.assign(assigned, actor, actor=actor) is True
    with django_capture_on_commit_callbacks(execute=True):
        assert assignment.take(taken, actor=actor) is True
    for ticket in (assigned, taken):
        _fresh(ticket)
        assert ticket.assignee_id == actor.pk and ticket.assigned_once is True
        assert ticket.kind == "in_progress" and ticket.status_id == default_in_work.pk
        events = _status_events(ticket)
        assert len(events) == 1
        assert events[0]["reason"] == "assigned"
        assert (events[0]["before_id"], events[0]["after_id"]) == (new_status.pk, default_in_work.pk)
        assert (events[0]["before"], events[0]["after"]) == (new_status.name, default_in_work.name)


# --- ответ исполнителя (FR-208, FR-250) ----------------------------------------------------------------

def test_reply_with_flag_moves_to_default_waiting_status(django_capture_on_commit_callbacks):
    """FR-208: ответ с флажком «Ждём ответа» из любого открытого вида — в статус по умолчанию вида «ждёт ответа»."""
    actor = _actor()
    own_default = _custom("waiting", "Ждём письма", actor, default=True)  # отметка перенесена на свой статус
    assert _default("waiting").pk == own_default.pk
    for kind in ("new", "in_progress"):
        ticket = _ticket(kind)
        before = ticket.status
        _reply(ticket, actor, django_capture_on_commit_callbacks, wait=True)
        _fresh(ticket)
        assert ticket.kind == "waiting" and ticket.status_id == own_default.pk
        assert ticket.last_message_from == "staff"
        events = _status_events(ticket)
        assert len(events) == 1 and events[0]["reason"] == "reply"
        assert (events[0]["before_id"], events[0]["after_id"]) == (before.pk, own_default.pk)


def test_reply_without_flag_from_new_or_waiting_moves_to_default_in_work_and_stops_countdown(
        django_capture_on_commit_callbacks):
    """FR-208, FR-250: ответ без флажка из «новая» и «ждёт ответа» — в «в работе» по умолчанию; отсчёт прекращается."""
    actor = _actor()
    in_work = _default("in_progress")
    from_new = _ticket("new")
    from_waiting = _waiting_ticket()
    assert from_waiting.waiting_since is not None
    for ticket in (from_new, from_waiting):
        before = ticket.status
        _reply(ticket, actor, django_capture_on_commit_callbacks, wait=False)
        _fresh(ticket)
        assert ticket.kind == "in_progress" and ticket.status_id == in_work.pk
        assert ticket.waiting_since is None
        events = _status_events(ticket)
        assert len(events) == 1 and events[0]["reason"] == "reply"
        assert (events[0]["before_id"], events[0]["after_id"]) == (before.pk, in_work.pk)


def test_reply_without_flag_in_work_keeps_own_status(django_capture_on_commit_callbacks):
    """FR-208: ответ без флажка в заявке вида «в работе» оставляет её в своём статусе; смены нет, события нет."""
    actor = _actor()
    own = _custom("in_progress", "На согласовании", actor)
    ticket = _ticket("in_progress", status=own)
    _reply(ticket, actor, django_capture_on_commit_callbacks, wait=False)
    _fresh(ticket)
    assert ticket.status_id == own.pk and ticket.kind == "in_progress"
    assert ticket.waiting_since is None
    assert ticket.last_message_from == "staff"
    assert _status_events(ticket) == []


# --- письма заявителя и участника, комментарий (FR-208) --------------------------------------------------

def test_requester_or_participant_letter_in_waiting_moves_to_in_work(django_capture_on_commit_callbacks):
    """FR-208, FR-250: письмо заявителя или участника в заявку «ждёт ответа» — «в работе» по умолчанию, отсчёт снят."""
    tickets = _svc("tickets")
    in_work = _default("in_progress")
    by_requester = _waiting_ticket()
    by_participant = _waiting_ticket()
    participant = sd.make_participant(by_participant)
    before = {t.pk: t.status_id for t in (by_requester, by_participant)}
    with django_capture_on_commit_callbacks(execute=True):
        tickets.add_incoming(by_requester, author_email=by_requester.requester_email, text="Заявитель отвечает")
    with django_capture_on_commit_callbacks(execute=True):
        tickets.add_incoming(by_participant, author_email=participant.email, author_name="Участник",
                             text="Участник отвечает")
    for ticket in (by_requester, by_participant):
        _fresh(ticket)
        assert ticket.kind == "in_progress" and ticket.status_id == in_work.pk
        assert ticket.waiting_since is None
        assert ticket.last_message_from == "requester"
        events = _status_events(ticket)
        assert len(events) == 1 and events[0]["reason"] == "letter"
        assert (events[0]["before_id"], events[0]["after_id"]) == (before[ticket.pk], in_work.pk)


def test_requester_letter_in_new_or_in_work_keeps_status(django_capture_on_commit_callbacks):
    """FR-208: письмо заявителя в заявку «новая» или «в работе» статус не меняет (свой статус вида сохраняется)."""
    actor = _actor()
    own = _custom("in_progress", "На согласовании", actor)
    for ticket in (_ticket("new"), _ticket("in_progress", status=own)):
        before = ticket.status_id
        _requester_letter(ticket, django_capture_on_commit_callbacks)
        _fresh(ticket)
        assert ticket.status_id == before
        assert ticket.last_message_from == "requester"
        assert ticket.waiting_since is None
        assert _status_events(ticket) == []


def test_internal_comment_changes_no_status_and_no_waiting_since(django_capture_on_commit_callbacks):
    """FR-208, FR-250: внутренний комментарий не меняет ни статус, ни `waiting_since`, ни событий статуса."""
    replies = _svc("replies")
    actor = _actor()
    waiting = _waiting_ticket()
    marked = waiting.waiting_since
    others = [_ticket("new"), _ticket("in_progress"), waiting]
    for ticket in others:
        status_before = ticket.status_id
        with django_capture_on_commit_callbacks(execute=True):
            replies.comment(ticket, text="Заметка для своих", actor=actor)
        _fresh(ticket)
        assert ticket.status_id == status_before
        assert _status_events(ticket) == []
    assert waiting.waiting_since == marked
    assert others[0].waiting_since is None and others[1].waiting_since is None


# --- закрытие, открытие, лента (FR-208) ---------------------------------------------------------------

def test_close_and_reopen_rows_use_chosen_and_default_statuses(django_capture_on_commit_callbacks):
    """FR-208: закрытие — выбранный статус вида «закрыта» (не обязательно по умолчанию); открытие заново — «в работе» по умолчанию."""
    closing = _svc("closing")
    actor = _actor()
    chosen = _custom("closed", "Отклонена", actor)
    default_closed = _default("closed")
    in_work = _default("in_progress")
    for status in (chosen, default_closed):
        ticket = _ticket("in_progress")
        with django_capture_on_commit_callbacks(execute=True):
            closing.close(ticket, status, "Готово", actor=actor)
        _fresh(ticket)
        assert ticket.kind == "closed" and ticket.status_id == status.pk
        with django_capture_on_commit_callbacks(execute=True):
            closing.reopen(ticket, actor=actor)
        _fresh(ticket)
        assert ticket.kind == "in_progress" and ticket.status_id == in_work.pk
        close_event, reopen_event = _status_events(ticket)
        assert close_event["reason"] == "close"
        assert (close_event["before_id"], close_event["after_id"]) == (in_work.pk, status.pk)
        assert reopen_event["reason"] == "reopen"
        assert (reopen_event["before_id"], reopen_event["after_id"]) == (status.pk, in_work.pk)


def test_every_status_change_writes_feed_event_was_became(django_capture_on_commit_callbacks):
    """FR-208: каждая смена статуса — событие ленты «было → стало», при всех семи причинах, в том числе при закрытии,
    автозакрытии и открытии заново (plan.md:721-722; решение C1 отменено)."""
    assignment, closing = _svc("assignment"), _svc("closing")
    actor = _actor()
    chosen = _custom("closed", "Отклонена", actor)
    ticket = _ticket("new")
    capture = django_capture_on_commit_callbacks
    with capture(execute=True):
        assignment.assign(ticket, actor, actor=actor)
    _reply(ticket, actor, capture, wait=True)
    _requester_letter(ticket, capture)
    _manual(ticket, _default("waiting"), actor, capture)
    with capture(execute=True):
        closing.close(ticket, chosen, "Готово", actor=actor)
    with capture(execute=True):
        closing.reopen(ticket, actor=actor)
    stale = _waiting_ticket()
    sd.backdate(stale, "waiting_since", days=8)
    with capture(execute=True):
        assert closing.autoclose_one(stale.pk) is True

    events = _status_events(ticket)
    assert [e["reason"] for e in events] == ["assigned", "reply", "letter", "manual", "close", "reopen"]
    assert events[0]["before_id"] == _default("new").pk and events[-1]["after_id"] == _default("in_progress").pk
    for earlier, later in zip(events, events[1:]):
        assert earlier["after_id"] == later["before_id"] and earlier["after"] == later["before"]
    assert all(e["before"] != e["after"] for e in events)
    assert _fresh(ticket).status.name == events[-1]["after"]

    auto = model("servicedesk.Status").objects.get(system_code="autoclosed")
    (auto_event,) = _status_events(stale)
    assert auto_event["reason"] == "autoclose"
    assert (auto_event["before_id"], auto_event["after_id"]) == (_default("waiting").pk, auto.pk)
    assert auto_event["after"] == auto.name

    page = support.logged_in(actor).get(f"/tickets/{ticket.number}/")
    assert page.status_code == 200
    html = page.content.decode("utf-8", "replace")
    rows = re.findall(r'<li\b[^>]*\bdata-event="status_changed"[^>]*>(.*?)</li>', html, re.S)
    assert len(rows) == len(events)
    texts = [" ".join(re.sub(r"<[^>]+>", " ", row).split()) for row in rows]
    for event, text in zip(events, texts):
        assert event["before"] in text and event["after"] in text and "→" in text, (event, text)


# --- ручная смена (FR-206, FR-209) ----------------------------------------------------------------------

def test_manual_status_list_has_only_in_work_and_waiting_kinds_not_archived():
    """FR-209: список ручной смены — неархивные статусы видов «в работе» и «ждёт ответа», по `order`; в карточке — то же."""
    dictionaries = _svc("dictionaries")
    actor = _actor()
    in_work_own = _custom("in_progress", "Согласование", actor)
    waiting_own = _custom("waiting", "Ждём поставщика", actor)
    archived = _custom("in_progress", "Устаревший", actor)
    dictionaries.archive(archived, actor=actor)
    new_own = _custom("new", "Черновик", actor)
    closed_own = _custom("closed", "Отклонена", actor)

    listed = list(dictionaries.manual_statuses())
    ids = {status.pk for status in listed}
    assert {_default("in_progress").pk, _default("waiting").pk, in_work_own.pk, waiting_own.pk} <= ids
    excluded = {_default("new").pk, _default("closed").pk, archived.pk, new_own.pk, closed_own.pk}
    assert not (ids & excluded)
    assert {status.kind for status in listed} == {"in_progress", "waiting"}
    assert all(not status.archived for status in listed)
    assert [status.order for status in listed] == sorted(status.order for status in listed)

    ticket = _ticket("in_progress")
    page = support.logged_in(actor).get(f"/tickets/{ticket.number}/")
    assert page.status_code == 200
    assert _status_form_option_ids(page) == ids


def test_manual_change_between_in_work_and_waiting_kinds_works(django_capture_on_commit_callbacks):
    """FR-206, FR-209: ручная смена между видами «в работе» и «ждёт ответа» — работает; событие ленты и журнал `ticket.updated`."""
    actor = _actor()
    waiting_status = _default("waiting")
    in_work = _default("in_progress")
    ticket = _ticket("in_progress")
    assert _manual(ticket, waiting_status, actor, django_capture_on_commit_callbacks) is True
    _fresh(ticket)
    assert ticket.kind == "waiting" and ticket.status_id == waiting_status.pk
    assert ticket.waiting_since is not None
    assert _manual(ticket, in_work, actor, django_capture_on_commit_callbacks) is True
    _fresh(ticket)
    assert ticket.kind == "in_progress" and ticket.status_id == in_work.pk
    assert ticket.waiting_since is None
    events = _status_events(ticket)
    assert [e["reason"] for e in events] == ["manual", "manual"]
    assert (events[0]["before_id"], events[0]["after_id"]) == (in_work.pk, waiting_status.pk)
    assert (events[1]["before_id"], events[1]["after_id"]) == (waiting_status.pk, in_work.pk)
    journal = model("core.AuditEvent").objects.filter(action="ticket.updated", object_id=str(ticket.number),
                                                       actor=actor).order_by("id")
    assert [(row.before.get("status"), row.after.get("status")) for row in journal] == [
        (in_work.name, waiting_status.name), (waiting_status.name, in_work.name)]
    # тот же статус: ничего не меняется и не пишется
    assert _manual(ticket, in_work, actor, django_capture_on_commit_callbacks) is False
    assert len(_status_events(ticket)) == 2

    # то же из карточки: маршрут действия, не имя маршрута
    other = _ticket("in_progress")
    response = support.logged_in(actor).post(f"/tickets/{other.number}/status/", {"status": waiting_status.pk})
    assert response.status_code == 302
    assert _fresh(other).status_id == waiting_status.pk


def test_manual_change_to_new_or_closed_kind_refused_even_direct_request(django_capture_on_commit_callbacks):
    """FR-209: в вид «новая» и «закрыта» вручную нельзя (и на архивный): `bad_status` у службы и у прямого запроса."""
    actor = _actor()
    dictionaries = _svc("dictionaries")
    archived = _custom("in_progress", "Устаревший", actor)
    dictionaries.archive(archived, actor=actor)
    refused = [_default("new"), _custom("new", "Черновик", actor), _default("closed"),
               _custom("closed", "Отклонена", actor), archived]
    ticket = _ticket("in_progress")
    start = ticket.status_id
    for status in refused:
        with pytest.raises(_errors()) as caught:
            _manual(ticket, status, actor, django_capture_on_commit_callbacks)
        assert caught.value.code == "bad_status"
        assert _fresh(ticket).status_id == start
    assert _status_events(ticket) == []

    client = support.logged_in(actor)
    for status in refused:
        response = client.post(f"/tickets/{ticket.number}/status/", {"status": status.pk})
        assert response.status_code == 200
        assert 'role="alert"' in response.content.decode("utf-8", "replace")
        assert _fresh(ticket).status_id == start
    assert _status_events(ticket) == []


def test_manual_new_to_in_work_without_assignee_allowed(django_capture_on_commit_callbacks):
    """FR-209: из «новая» в «в работе» вручную можно и без ответственного; письма «взята в работу» нет."""
    actor = _actor()
    in_work = _default("in_progress")
    ticket = _ticket("new")
    assert ticket.assignee_id is None
    assert _manual(ticket, in_work, actor, django_capture_on_commit_callbacks) is True
    _fresh(ticket)
    assert ticket.kind == "in_progress" and ticket.status_id == in_work.pk
    assert ticket.assignee_id is None and ticket.assigned_once is False
    assert sd.ticket_mails(ticket) == []
    (event,) = _status_events(ticket)
    assert event["reason"] == "manual" and event["after_id"] == in_work.pk


def test_custom_status_of_in_work_kind_behaves_as_in_work(django_capture_on_commit_callbacks):
    """FR-206, FR-209: свой статус вида «в работе» ведёт себя как «в работе»: ручной выбор, письма и ответы его не меняют,
    ответ с флажком уводит в «ждёт ответа», из своего «ждёт ответа» письмо возвращает в «в работе» по умолчанию."""
    actor = _actor()
    capture = django_capture_on_commit_callbacks
    own = _custom("in_progress", "На согласовании", actor)
    own_waiting = _custom("waiting", "Ждём поставщика", actor)

    ticket = _ticket("new")
    assert _manual(ticket, own, actor, capture) is True
    _fresh(ticket)
    assert ticket.kind == "in_progress" and ticket.status_id == own.pk
    page = support.logged_in(actor).get(f"/tickets/{ticket.number}/")
    assert re.search(r'<[^>]*\bdata-ticket-card\b[^>]*\bdata-kind="in_progress"|'
                     r'<[^>]*\bdata-kind="in_progress"[^>]*\bdata-ticket-card\b', page.content.decode("utf-8"))

    _requester_letter(ticket, capture)
    _reply(ticket, actor, capture, wait=False)
    _fresh(ticket)
    assert ticket.status_id == own.pk and ticket.kind == "in_progress"
    assert [e["reason"] for e in _status_events(ticket)] == ["manual"]

    _reply(ticket, actor, capture, wait=True)
    _fresh(ticket)
    assert ticket.kind == "waiting" and ticket.status_id == _default("waiting").pk

    waiting_own = _ticket("waiting", status=own_waiting)
    sd.backdate(waiting_own, "waiting_since", hours=1)
    _requester_letter(waiting_own, capture)
    _fresh(waiting_own)
    assert waiting_own.kind == "in_progress" and waiting_own.status_id == _default("in_progress").pk
    assert waiting_own.waiting_since is None


# --- отсчёт автозакрытия: поле `waiting_since` (FR-209, FR-250, FR-208) ----------------------------------

def test_manual_change_to_waiting_sends_no_letter_and_sets_waiting_since(django_capture_on_commit_callbacks):
    """FR-209, FR-250: ручная смена на «ждёт ответа» писем не отправляет, а `waiting_since` ставит сразу."""
    actor = _actor()
    MailMessage = model("mail.MailMessage")
    ticket = _ticket("in_progress")
    mails_before = MailMessage.objects.count()
    started = timezone.now()
    _manual(ticket, _default("waiting"), actor, django_capture_on_commit_callbacks)
    finished = timezone.now()
    _fresh(ticket)
    assert ticket.kind == "waiting"
    assert ticket.waiting_since is not None and started - SECOND <= ticket.waiting_since <= finished + SECOND
    assert sd.ticket_mails(ticket) == []
    assert MailMessage.objects.count() == mails_before


def test_change_within_waiting_kind_keeps_waiting_since(django_capture_on_commit_callbacks):
    """FR-209, FR-250: переход между статусами одного вида «ждёт ответа» отсчёт не сбрасывает; событие статуса пишется."""
    actor = _actor()
    second = _custom("waiting", "Ждём поставщика", actor)
    ticket = _waiting_ticket()
    marked = ticket.waiting_since
    first = ticket.status
    assert _manual(ticket, second, actor, django_capture_on_commit_callbacks) is True
    _fresh(ticket)
    assert ticket.status_id == second.pk and ticket.kind == "waiting"
    assert ticket.waiting_since == marked
    (event,) = _status_events(ticket)
    assert (event["before_id"], event["after_id"], event["reason"]) == (first.pk, second.pk, "manual")


def test_leaving_waiting_kind_clears_waiting_since(django_capture_on_commit_callbacks):
    """FR-208, FR-250: выход из вида «ждёт ответа» (ручная смена, письмо, ответ без флажка, закрытие) снимает `waiting_since`."""
    actor = _actor()
    capture = django_capture_on_commit_callbacks
    closing = _svc("closing")
    by_manual, by_letter, by_reply, by_close = (_waiting_ticket() for _ in range(4))
    assert all(t.waiting_since is not None for t in (by_manual, by_letter, by_reply, by_close))
    _manual(by_manual, _default("in_progress"), actor, capture)
    _requester_letter(by_letter, capture)
    _reply(by_reply, actor, capture, wait=False)
    with capture(execute=True):
        closing.close(by_close, _default("closed"), "Решено", actor=actor)
    for ticket in (by_manual, by_letter, by_reply, by_close):
        _fresh(ticket)
        assert ticket.kind != "waiting"
        assert ticket.waiting_since is None
    assert by_close.kind == "closed" and by_close.closed_at is not None


def test_reply_with_flag_sets_waiting_since_at_queueing_of_letter(django_capture_on_commit_callbacks):
    """FR-250: ответ с флажком — `waiting_since` ставится в момент постановки письма в очередь: рядом с отметкой самого
    письма (`MailMessage.created_at`), а не с часами хоста; повторный ответ с флажком в виде «ждёт ответа» переставляет отсчёт."""
    actor = _actor()
    ticket = _ticket("in_progress")
    started = timezone.now()
    entry = _reply(ticket, actor, django_capture_on_commit_callbacks, wait=True)
    finished = timezone.now()
    _fresh(ticket)
    entry.refresh_from_db()
    assert entry.send_state == "queued" and ticket.kind == "waiting"
    (mail,) = sd.ticket_mails(ticket)
    assert ticket.waiting_since is not None
    assert abs(ticket.waiting_since - mail.created_at) <= 5 * SECOND
    assert started - SECOND <= ticket.waiting_since <= finished + SECOND

    again = _waiting_ticket()
    assert timezone.now() - again.waiting_since >= timedelta(hours=1)
    _reply(again, actor, django_capture_on_commit_callbacks, wait=True)
    _fresh(again)
    (second_mail,) = sd.ticket_mails(again)
    assert again.kind == "waiting"
    assert abs(again.waiting_since - second_mail.created_at) <= 5 * SECOND


def test_reply_with_flag_and_quarantine_leaves_waiting_since_empty(
        django_capture_on_commit_callbacks, monkeypatch, protected_root):
    """FR-250: если ответ не ушёл (вложение в карантине), отсчёт не начинается: `waiting_since` пуст, письма нет."""
    attachments = _svc("attachments")
    actor = _actor()
    sd.scan_found(monkeypatch, "Eicar-Signature")
    ticket = _ticket("in_progress")
    part = attachments.Part(name="заметка.txt", data=org.eicar_bytes())
    entry = _reply(ticket, actor, django_capture_on_commit_callbacks, wait=True, parts=[part])
    _fresh(ticket)
    entry.refresh_from_db()
    assert entry.send_state == "waiting_files"
    assert ticket.waiting_since is None and sd.ticket_mails(ticket) == []

    with django_capture_on_commit_callbacks(execute=True):
        org.run_files_worker()
    entry.refresh_from_db()
    _fresh(ticket)
    assert entry.send_state == "not_sent"
    assert ticket.waiting_since is None
    assert sd.ticket_mails(ticket) == []
