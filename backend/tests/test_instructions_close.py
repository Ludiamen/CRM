"""Срез 010 «Поручения»: снятие с контроля (T-10106; FR-707).

`apps.instructions.services.instructions.close` и маршрут `/instructions/<id>/close/` — CONTRACT-010, 4, 6.2,
10.1. Код среза импортируется внутри тестов: сбор проходит до появления моделей и служб.
"""
import datetime

import pytest
from django.utils import timezone

from tests import support, support_org
from tests import support_instructions as ins

pytestmark = pytest.mark.django_db


def instructions():
    from apps.instructions.services import instructions as module
    return module


def _err(call):
    from apps.instructions.texts import InstructionsError

    with pytest.raises(InstructionsError) as caught:
        call()
    return caught.value


def _setup():
    tree = support_org.make_tree({"Отдел": {"Группа": {}}})
    head = ins.head_of(tree["Отдел"])
    assignee = ins.staff_user()
    support_org.make_member(assignee, tree["Группа"])
    controller = ins.staff_user()
    row = ins.make_instruction(author=head, controller=controller, assignee=assignee)
    return row, head, controller, assignee


def _accepted_final(row):
    return support.model("instructions.InstructionReport").objects.create(
        instruction=row, date=None, author=row.assignee, text="Итог", decision="accepted")


def test_close_sets_closed_at_cancels_pending_and_audits():
    """FR-707: снятие ставит `closed_at`, снимает `pending`-напоминания, пишет журнал `instructions.closed`;
    `pending`-перенос блокирует снятие (проверяется ниже)."""
    row, head, controller, assignee = _setup()
    _accepted_final(row)
    due = ins.add_report_date(row, ins._today() + datetime.timedelta(days=5))
    reminder = support.model("instructions.InstructionReminder").objects.create(
        instruction=row, date=due, user=assignee, kind="report", stage="r1",
        moment=timezone.now() + datetime.timedelta(hours=1), state="pending")
    closed = instructions().close(controller, row)
    assert closed.closed_at is not None
    reminder.refresh_from_db()
    assert reminder.state == "cancelled"
    assert support.model("core.AuditEvent").objects.filter(
        action="instructions.closed", object_id=str(row.pk)).exists()


def test_close_forbidden_for_non_controller():
    """FR-707: снять с контроля может только контролёр (`close_forbidden`), даже постановщик — нет."""
    row, head, controller, assignee = _setup()
    _accepted_final(row)
    for actor in (head, assignee):
        err = _err(lambda actor=actor: instructions().close(actor, row))
        assert (err.code, err.field) == ("close_forbidden", "confirm")


def test_close_requires_accepted_final_report():
    """FR-707: без принятого итогового отчёта — `close_no_report`; отправленный, но не принятый — тоже."""
    row, head, controller, assignee = _setup()
    err = _err(lambda: instructions().close(controller, row))
    assert (err.code, err.field) == ("close_no_report", "confirm")
    support.model("instructions.InstructionReport").objects.create(
        instruction=row, date=None, author=assignee, text="Итог", decision="pending")
    err = _err(lambda: instructions().close(controller, row))
    assert (err.code, err.field) == ("close_no_report", "confirm")


def test_close_blocked_by_pending_transfer():
    """FR-707, FR-708: при `pending`-переносе снятие отклоняется (`close_transfer_pending`)."""
    row, head, controller, assignee = _setup()
    _accepted_final(row)
    support.model("instructions.InstructionTransfer").objects.create(
        instruction=row, old_deadline=row.deadline,
        new_deadline=row.deadline + datetime.timedelta(days=5), reason="Причина",
        requested_by=assignee, state="pending")
    err = _err(lambda: instructions().close(controller, row))
    assert (err.code, err.field) == ("close_transfer_pending", "confirm")


def test_closed_instruction_refuses_reports_and_transfers():
    """FR-707, FR-708: после снятия отчёты и переносы не принимаются."""
    from apps.instructions.services import reports as reports_service
    from apps.instructions.services import transfers as transfers_service

    row, head, controller, assignee = _setup()
    _accepted_final(row)
    instructions().close(controller, row)
    due = ins.add_report_date(row, ins._today() + datetime.timedelta(days=1))
    err = _err(lambda: reports_service.submit(assignee, row, date=due, text="Поздно"))
    assert (err.code, err.field) == ("report_closed", "text")
    err = _err(lambda: transfers_service.request(assignee, row,
                                                 new_deadline=row.deadline + datetime.timedelta(days=3),
                                                 reason="Поздно"))
    assert (err.code, err.field) == ("transfer_closed", "reason")


def test_close_page_two_steps_and_access(client):
    """CONTRACT-010, 6.2: без `confirm` — второй шаг `[data-instructions-confirm]`; с `confirm=1` — 302;
    не контролёру — 403."""
    row, head, controller, assignee = _setup()
    _accepted_final(row)

    assert support.logged_in(head).post(f"/instructions/{row.pk}/close/",
                                       {"confirm": "1"}).status_code == 403

    controller_client = support.logged_in(controller)
    first = controller_client.post(f"/instructions/{row.pk}/close/", {})
    assert first.status_code == 200 and b"data-instructions-confirm" in first.content
    second = controller_client.post(f"/instructions/{row.pk}/close/", {"confirm": "1"})
    row.refresh_from_db()
    assert second.status_code == 302 and row.closed_at is not None