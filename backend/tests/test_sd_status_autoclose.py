"""T-3111: автозакрытие заявок вида «ждёт ответа заявителя» (FR-206, FR-208, FR-209, FR-250). Сценарий 6 спеки.

Имена кода среза 003 (`apps.servicedesk…`) импортируются внутри тестов: сбор проходит до появления кода.
Правила — tests/CONTRACT-003.md (§ 2.1, 3.4, 6.1, 6.7, 6.10, 6.11, 7.1, 7.3, 9.2, 9.3, 10). Время — `backdate` на
`waiting_since` (решение 5 задач): сдвиг «с запасом в минуты», чтобы граница срока не зависела от длительности теста;
точная граница проверяется через `autoclose_one(..., now=...)`.
"""
import re
from datetime import timedelta

import pytest
from django.utils import timezone

from tests import support, support_org
from tests.support import model
from tests.support_servicedesk import (backdate, configure_servicedesk, make_participant, make_queue,
                                       make_requester, make_ticket, mail_text, ticket_mails)

pytestmark = pytest.mark.django_db

WAITING_NAME = "Ждёт ответа заявителя"
AUTOCLOSED_NAME = "Закрыта автоматически"


# --- помощники файла ---------------------------------------------------------------------------------

def _waiting(queue, *, days: int = 7, minutes: int = 5, hours: int = 0, **over):
    """Заявка вида «ждёт ответа»: `waiting_since` — «сейчас», сдвинутое назад (7 суток и 5 минут по умолчанию)."""
    ticket = make_ticket(queue=queue, kind="waiting", waiting_since=timezone.now(), **over)
    backdate(ticket, "waiting_since", days=days, hours=hours, minutes=minutes)
    return ticket


def _fresh(ticket):
    return type(ticket).objects.get(pk=ticket.pk)


def _closing():
    from apps.servicedesk.services import closing
    return closing


def _run_batch(**kwargs):
    """Порция автозакрытия; письма и обработчики шины идут после фиксации."""
    return _closing().autoclose_batch(**kwargs)


def _audit(action, ticket):
    return list(model("core.AuditEvent").objects.filter(action=action, object_id=str(ticket.number)).order_by("id"))


def _events(ticket, code):
    return list(model("servicedesk.TicketEntry").objects.filter(ticket=ticket, kind="event", event=code).order_by("id"))


def _autoclosed_status():
    return model("servicedesk.Status").objects.get(system_code="autoclosed")


def _maintenance_jobs():
    import django_rq
    return [j for j in django_rq.get_queue("maintenance").jobs if j.func_name == "apps.servicedesk.tasks.autoclose"]


# --- тесты -------------------------------------------------------------------------------------------

def test_autoclose_on_seventh_day_sets_system_status_closed_at_and_empty_closed_by(django_capture_on_commit_callbacks):
    """FR-206, FR-250: на седьмые сутки заявка вида waiting закрыта системным статусом «Закрыта автоматически»:
    kind closed, closed_at «сейчас», closed_by пусто, отсчёт снят; лента: «статус: было → стало» (reason autoclose)
    и событие autoclosed (status, status_id, days); журнал ticket.autoclosed без автора, ticket.updated нет."""
    queue = make_queue()
    ticket = _waiting(queue)
    started = timezone.now()
    with django_capture_on_commit_callbacks(execute=True):
        batch = _run_batch()
    assert batch.done == 1
    ticket = _fresh(ticket)
    system = _autoclosed_status()
    assert ticket.status_id == system.pk
    assert ticket.kind == "closed"
    assert ticket.closed_by is None
    assert ticket.closed_at is not None and started - timedelta(minutes=1) <= ticket.closed_at <= timezone.now()
    assert ticket.waiting_since is None

    changed = _events(ticket, "status_changed")
    assert len(changed) == 1
    data = changed[0].data
    assert data["before"] == WAITING_NAME and data["after"] == AUTOCLOSED_NAME
    assert data["after_id"] == system.pk and data["reason"] == "autoclose"
    closed = _events(ticket, "autoclosed")
    assert len(closed) == 1
    assert closed[0].data["status"] == AUTOCLOSED_NAME and closed[0].data["status_id"] == system.pk
    assert closed[0].data["days"] == 7

    journal = _audit("ticket.autoclosed", ticket)
    assert len(journal) == 1
    assert journal[0].actor is None and journal[0].object_type == "ticket"
    assert journal[0].before["status"] == WAITING_NAME and journal[0].after["status"] == AUTOCLOSED_NAME
    assert _audit("ticket.updated", ticket) == []


def test_autoclose_sends_autoclosed_letter_to_requester_and_participants(django_capture_on_commit_callbacks):
    """FR-250: письмо ticket.autoclosed ушло заявителю, в копии — неснятые участники (снятый и заявитель — нет);
    Auto-Submitted auto-generated; в тексте номер и сроки из настроек на момент отправки."""
    queue = make_queue()
    configure_servicedesk(autoclose_days=5, reopen_days=11)
    requester = make_requester(email="client-autoclose@client.test")
    ticket = _waiting(queue, days=5, requester=requester, number=4821)
    active = make_participant(ticket, "copy-active@client.test")
    removed = make_participant(ticket, "copy-removed@client.test", removed_by=support.make_employee())
    with django_capture_on_commit_callbacks(execute=True):
        assert _run_batch().done == 1
    mails = [m for m in ticket_mails(_fresh(ticket)) if m.template == "ticket.autoclosed"]
    assert len(mails) == 1
    mail = mails[0]
    assert mail.to == requester.email
    copies = [a.strip() for a in mail.cc.split(",") if a.strip()]
    assert copies == [active.email]
    assert removed.email not in copies and requester.email not in copies
    assert mail.auto_submitted == "auto-generated"
    assert mail.subject.startswith("[#4821]")
    text = mail_text(mail)
    # числа привязаны к фразам § 10.4: «ответа <autoclose_days> дней… в течение <reopen_days> дней»
    assert re.search(r"ответа\s+5\s+дн", text) and re.search(r"в\s+течение\s+11\s+дн", text)


def test_autoclose_not_on_sixth_day_and_not_after_requester_letter(django_capture_on_commit_callbacks):
    """FR-208, FR-250: заявка на шестые сутки не закрывается; заявка старше срока, но после письма заявителя
    (вид уже «в работе», отсчёт снят), проверкой не закрывается; писем «закрыта автоматически» нет."""
    queue = make_queue()
    sixth = _waiting(queue, days=6, hours=23)
    answered = _waiting(queue, days=8)
    with django_capture_on_commit_callbacks(execute=True):
        from apps.servicedesk.services import tickets
        tickets.add_incoming(answered, author_email=answered.requester_email, text="Ответ заявителя")
    answered = _fresh(answered)
    assert answered.kind == "in_progress" and answered.waiting_since is None

    with django_capture_on_commit_callbacks(execute=True):
        batch = _run_batch()
    assert batch.done == 0
    sixth, answered = _fresh(sixth), _fresh(answered)
    assert sixth.kind == "waiting" and sixth.closed_at is None and sixth.waiting_since is not None
    assert answered.kind == "in_progress" and answered.closed_at is None
    for ticket in (sixth, answered):
        assert _events(ticket, "autoclosed") == []
        assert _audit("ticket.autoclosed", ticket) == []
        assert [m for m in ticket_mails(ticket) if m.template == "ticket.autoclosed"] == []


def test_autoclose_skips_in_work_kind_of_any_age(django_capture_on_commit_callbacks):
    """FR-250: заявки вида «в работе» и «новая» не закрываются, как бы ни были стары (в том числе с давним
    остатком waiting_since): закрывается только контрольная заявка вида waiting."""
    queue = make_queue()
    in_work = make_ticket(queue=queue, kind="in_progress")
    in_work_stale = make_ticket(queue=queue, kind="in_progress", waiting_since=timezone.now())
    new = make_ticket(queue=queue, kind="new")
    for ticket in (in_work, in_work_stale, new):
        backdate(ticket, "created_at", days=400)
        backdate(ticket, "last_message_at", days=400)
    backdate(in_work_stale, "waiting_since", days=90)
    control = _waiting(queue)
    with django_capture_on_commit_callbacks(execute=True):
        batch = _run_batch()
    assert batch.done == 1
    assert _fresh(control).kind == "closed"
    for ticket in (in_work, in_work_stale, new):
        fresh = _fresh(ticket)
        assert fresh.kind == ticket.kind and fresh.status_id == ticket.status_id and fresh.closed_at is None
        assert _audit("ticket.autoclosed", fresh) == []


def test_autoclose_days_setting_read_on_each_run(django_capture_on_commit_callbacks):
    """FR-250: срок автозакрытия читается из настроек при каждом запуске задания: при сроке 7 заявка четырёх
    суток цела, после смены срока на 3 тот же запуск закрывает её, а заявку двух суток — нет."""
    queue = make_queue()
    older = _waiting(queue, days=4, minutes=5)
    younger = _waiting(queue, days=2, minutes=5)
    from apps.servicedesk import tasks
    configure_servicedesk(autoclose_days=7)
    with django_capture_on_commit_callbacks(execute=True):
        tasks.autoclose()
    assert _fresh(older).kind == "waiting" and _fresh(younger).kind == "waiting"

    configure_servicedesk(autoclose_days=3)
    with django_capture_on_commit_callbacks(execute=True):
        tasks.autoclose()
    assert _fresh(older).kind == "closed" and _fresh(older).status_id == _autoclosed_status().pk
    assert _fresh(younger).kind == "waiting"
    assert _events(_fresh(older), "autoclosed")[0].data["days"] == 3


def test_autoclose_after_manual_waiting_change_without_letter(django_capture_on_commit_callbacks):
    """FR-209, FR-250: исполнитель вручную перевёл заявку на «ждёт ответа» — письма нет, отсчёт пошёл;
    через 7 суток без писем заявка закрыта автоматически, единственное письмо — «закрыта автоматически»."""
    from apps.servicedesk.services import tickets
    queue = make_queue()
    actor = support.make_employee()
    support_org.make_member(actor, queue.unit)
    ticket = make_ticket(queue=queue, kind="in_progress")
    waiting_status = model("servicedesk.Status").objects.get(kind="waiting", is_default=True)
    with django_capture_on_commit_callbacks(execute=True):
        assert tickets.set_status_manual(ticket, waiting_status, actor=actor) is True
    ticket = _fresh(ticket)
    assert ticket.kind == "waiting" and ticket.waiting_since is not None
    assert ticket_mails(ticket) == []

    backdate(ticket, "waiting_since", days=7, minutes=5)
    with django_capture_on_commit_callbacks(execute=True):
        assert _run_batch().done == 1
    ticket = _fresh(ticket)
    assert ticket.kind == "closed" and ticket.status_id == _autoclosed_status().pk and ticket.closed_by is None
    assert [m.template for m in ticket_mails(ticket)] == ["ticket.autoclosed"]


def test_autoclose_recheck_under_lock_skips_ticket_with_letter_between_select_and_close(
        django_capture_on_commit_callbacks):
    """FR-250: повторная проверка под замком: заявку отобрали устаревшей (идентификатор уже в руках), а между отбором
    и закрытием пришло письмо заявителя — autoclose_one возвращает False и ничего не пишет; границу срока задаёт
    `now`: ровно 7 суток после waiting_since — закрыть, на секунду меньше — нет."""
    closing = _closing()
    queue = make_queue()
    selected = _waiting(queue, days=8)
    stale = _fresh(selected)
    assert stale.kind == "waiting"
    with django_capture_on_commit_callbacks(execute=True):
        from apps.servicedesk.services import tickets
        tickets.add_incoming(selected, author_email=selected.requester_email, text="Пришло между отбором и закрытием")
    with django_capture_on_commit_callbacks(execute=True):
        assert closing.autoclose_one(stale.pk) is False
    selected = _fresh(selected)
    assert selected.kind == "in_progress" and selected.closed_at is None
    assert _events(selected, "autoclosed") == [] and _audit("ticket.autoclosed", selected) == []
    assert [m for m in ticket_mails(selected) if m.template == "ticket.autoclosed"] == []

    edge = make_ticket(queue=queue, kind="waiting", waiting_since=timezone.now())
    start = edge.waiting_since
    with django_capture_on_commit_callbacks(execute=True):
        assert closing.autoclose_one(edge.pk, now=start + timedelta(days=7) - timedelta(seconds=1)) is False
    assert _fresh(edge).kind == "waiting"
    with django_capture_on_commit_callbacks(execute=True):
        assert closing.autoclose_one(edge.pk, now=start + timedelta(days=7)) is True
    edge = _fresh(edge)
    assert edge.kind == "closed" and edge.status_id == _autoclosed_status().pk and edge.closed_by is None
    assert edge.closed_at == start + timedelta(days=7)  # § 6.11: closed_at = now


def test_autoclose_processes_in_batches_of_fifty(django_capture_on_commit_callbacks):
    """FR-250: порция — не больше 50 заявок по (waiting_since, id); следующую порцию ставит задание в очередь
    maintenance (аргументы по ключам: limit 50 и after — курсор последней отобранной), а не цикл в одной порции;
    выполнение поставленного задания закрывает остаток, новых порций нет."""
    from apps.servicedesk import tasks
    queue = make_queue()
    requester = make_requester()
    tickets = []
    for index in range(52):
        tickets.append(_waiting(queue, days=8, minutes=index, requester=requester))
    expected = sorted(tickets, key=lambda t: (t.waiting_since, t.pk))
    first_fifty, rest = expected[:50], expected[50:]
    with django_capture_on_commit_callbacks(execute=True):
        tasks.autoclose()
    assert {t.pk for t in tickets if _fresh(t).kind == "closed"} == {t.pk for t in first_fifty}
    assert all(_fresh(t).kind == "waiting" for t in rest)
    jobs = _maintenance_jobs()
    assert len(jobs) == 1
    job = jobs[0]
    assert job.timeout == 600
    assert job.kwargs["limit"] == 50
    assert tuple(job.kwargs["after"]) == (first_fifty[-1].waiting_since, first_fifty[-1].pk)

    with django_capture_on_commit_callbacks(execute=True):
        job.perform()
    assert all(_fresh(t).kind == "closed" for t in tickets)
    assert len(_maintenance_jobs()) == 1  # прежнее задание; новой порции после неполной нет

    # поля Batch напрямую (§ 6.1, 6.11): новые 52 заявки, порция 50, затем остаток по курсору
    again = [_waiting(queue, days=8, minutes=index, requester=requester) for index in range(52)]
    order = sorted(again, key=lambda t: (t.waiting_since, t.pk))
    with django_capture_on_commit_callbacks(execute=True):
        first = _closing().autoclose_batch(limit=50)
    assert first.done == 50 and first.more is True
    assert tuple(first.last) == (order[49].waiting_since, order[49].pk)
    assert {t.pk for t in again if _fresh(t).kind == "closed"} == {t.pk for t in order[:50]}
    with django_capture_on_commit_callbacks(execute=True):
        second = _closing().autoclose_batch(limit=50, after=first.last)
    assert second.done == 2 and second.more is False
    assert all(_fresh(t).kind == "closed" for t in again)


def test_autoclose_not_counted_from_unsent_reply_with_quarantine(
        django_capture_on_commit_callbacks, monkeypatch, protected_root):
    """FR-250 (сценарий 6.10): ответ с флажком не ушёл из-за вложения в карантине (настоящий путь `replies.reply`
    + `scan_found`) — заявка вида waiting без отсчёта (waiting_since пусто), как бы стара ни была: автозакрытие её
    не трогает ни в состоянии «ждут файлы», ни после проверки файлов (закрывается лишь контрольная заявка)."""
    from apps.servicedesk.services import attachments, replies
    queue = make_queue()
    staff = support.make_with_permissions("servicedesk.all")
    support_org.scan_found(monkeypatch, "Eicar-Signature")
    unsent = make_ticket(queue=queue, kind="in_progress")
    part = attachments.Part(name="заметка.txt", data=support_org.eicar_bytes())
    with django_capture_on_commit_callbacks(execute=True):
        entry = replies.reply(unsent, text="Пришлите файл", parts=(part,), wait_flag=True, actor=staff)
    entry.refresh_from_db()
    assert entry.send_state == "waiting_files"
    unsent = _fresh(unsent)
    assert unsent.kind == "waiting" and unsent.waiting_since is None
    assert ticket_mails(unsent) == []
    backdate(unsent, "created_at", days=60)
    backdate(unsent, "last_message_at", days=40)
    control = _waiting(queue)

    with django_capture_on_commit_callbacks(execute=True):
        batch = _run_batch()
    assert batch.done == 1
    assert _fresh(control).kind == "closed"
    unsent = _fresh(unsent)
    assert unsent.kind == "waiting" and unsent.waiting_since is None and unsent.closed_at is None

    with django_capture_on_commit_callbacks(execute=True):
        support_org.run_files_worker()
    entry.refresh_from_db()
    assert entry.send_state == "not_sent"
    unsent = _fresh(unsent)
    assert unsent.kind == "waiting" and unsent.waiting_since is None
    assert ticket_mails(unsent) == []
    again = _waiting(queue)
    with django_capture_on_commit_callbacks(execute=True):
        batch = _run_batch()
    assert batch.done == 1
    assert _fresh(again).kind == "closed"
    unsent = _fresh(unsent)
    assert unsent.kind == "waiting" and unsent.waiting_since is None and unsent.closed_at is None
    assert _events(unsent, "autoclosed") == [] and _audit("ticket.autoclosed", unsent) == []
    assert ticket_mails(unsent) == []
