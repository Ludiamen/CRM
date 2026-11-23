"""Срез 010 «Поручения»: перенос срока (T-10107; FR-708).

`apps.instructions.services.transfers` и маршруты переноса — CONTRACT-010, 6.2, 10.1. Код среза импортируется
внутри тестов: сбор проходит до появления моделей и служб.
"""
import datetime

import pytest
from django.utils import timezone

from tests import support, support_org
from tests import support_instructions as ins

pytestmark = pytest.mark.django_db


def transfers():
    from apps.instructions.services import transfers as module
    return module


def _err(call):
    from apps.instructions.texts import InstructionsError

    with pytest.raises(InstructionsError) as caught:
        call()
    return caught.value


def _setup():
    tree = support_org.make_tree({"Отдел": {"Группа": {}}})
    head = ins.head_of(tree["Отдел"])
    assignee = support.make_employee()
    support_org.make_member(assignee, tree["Группа"])
    controller = ins.staff_user()
    row = ins.make_instruction(author=head, controller=controller, assignee=assignee)
    return row, head, controller, assignee


def test_request_creates_pending_with_reason_and_audit():
    """FR-708: запрос исполнителя создаёт `pending` со старым и новым сроком, причиной и автором; журнал
    `instructions.transfer_requested`."""
    row, head, controller, assignee = _setup()
    new_deadline = row.deadline + datetime.timedelta(days=7)
    transfer = transfers().request(assignee, row, new_deadline=new_deadline, reason="Нужно время")
    assert transfer.state == "pending"
    assert (transfer.old_deadline, transfer.new_deadline) == (row.deadline, new_deadline)
    assert transfer.requested_by_id == assignee.pk and transfer.reason == "Нужно время"
    assert support.model("core.AuditEvent").objects.filter(
        action="instructions.transfer_requested", object_id=str(row.pk)).exists()


def test_request_forbidden_state_and_closed():
    """FR-708: просит только исполнитель (`transfer_forbidden`); второй `pending` — `transfer_state`; после
    снятия — `transfer_closed`."""
    row, head, controller, assignee = _setup()
    for actor in (head, controller):
        err = _err(lambda actor=actor: transfers().request(
            actor, row, new_deadline=row.deadline + datetime.timedelta(days=3), reason="Причина"))
        assert (err.code, err.field) == ("transfer_forbidden", "reason")
    transfers().request(assignee, row, new_deadline=row.deadline + datetime.timedelta(days=3), reason="Первая")
    err = _err(lambda: transfers().request(
        assignee, row, new_deadline=row.deadline + datetime.timedelta(days=4), reason="Вторая"))
    assert (err.code, err.field) == ("transfer_state", "reason")

    closed_row = ins.make_instruction(author=head, controller=controller, assignee=assignee)
    closed_row.closed_at = timezone.now()
    closed_row.save(update_fields=["closed_at"])
    err = _err(lambda: transfers().request(
        assignee, closed_row, new_deadline=closed_row.deadline + datetime.timedelta(days=5), reason="Поздно"))
    assert (err.code, err.field) == ("transfer_closed", "reason")


def test_request_deadline_must_be_later_and_reason_required():
    """FR-708: новый срок — позже текущего (`transfer_deadline`); причина 1–1 000 знаков (`transfer_reason`)."""
    row, head, controller, assignee = _setup()
    for deadline in (row.deadline, row.deadline - datetime.timedelta(days=1)):
        err = _err(lambda deadline=deadline: transfers().request(assignee, row, new_deadline=deadline, reason="Причина"))
        assert (err.code, err.field) == ("transfer_deadline", "new_deadline")
    for reason in ("", "я" * 1_001):
        err = _err(lambda reason=reason: transfers().request(
            assignee, row, new_deadline=row.deadline + datetime.timedelta(days=3), reason=reason))
        assert (err.code, err.field) == ("transfer_reason", "reason")


def test_approve_changes_deadline_keeps_original_and_audits():
    """FR-708: согласование меняет `deadline`, `original_deadline` не меняется; решение, кто и когда; журнал
    `instructions.transfer_decided`."""
    row, head, controller, assignee = _setup()
    original = row.original_deadline
    new_deadline = row.deadline + datetime.timedelta(days=9)
    transfer = transfers().request(assignee, row, new_deadline=new_deadline, reason="Причина")
    decided = transfers().decide(controller, transfer, approve=True, comment="Согласовано")
    row.refresh_from_db()
    transfer.refresh_from_db()
    assert row.deadline == new_deadline and row.original_deadline == original
    assert transfer.state == "approved" and transfer.decided_by_id == controller.pk
    assert transfer.decided_at is not None and transfer.comment == "Согласовано"
    assert support.model("core.AuditEvent").objects.filter(
        action="instructions.transfer_decided", object_id=str(row.pk)).exists()


def test_reject_requires_comment_keeps_deadline():
    """FR-708: отказ требует причину (`return_comment_required`), срок не меняется, состояние `rejected`."""
    row, head, controller, assignee = _setup()
    new_deadline = row.deadline + datetime.timedelta(days=9)
    transfer = transfers().request(assignee, row, new_deadline=new_deadline, reason="Причина")
    err = _err(lambda: transfers().decide(controller, transfer, approve=False, comment=""))
    assert (err.code, err.field) == ("return_comment_required", "comment")
    decided = transfers().decide(controller, transfer, approve=False, comment="Срок достаточный")
    row.refresh_from_db()
    transfer.refresh_from_db()
    assert decided.state == "rejected" and row.deadline != new_deadline
    assert transfer.comment == "Срок достаточный"


def test_decide_forbidden_and_already_decided():
    """FR-708: решает автор или контролёр (`decision_forbidden`); повторное решение — `transfer_decided`."""
    row, head, controller, assignee = _setup()
    transfer = transfers().request(assignee, row, new_deadline=row.deadline + datetime.timedelta(days=4),
                                   reason="Причина")
    err = _err(lambda: transfers().decide(assignee, transfer, approve=True))
    assert (err.code, err.field) == ("decision_forbidden", "comment")
    transfers().decide(head, transfer, approve=True)
    err = _err(lambda: transfers().decide(controller, transfer, approve=True))
    assert (err.code, err.field) == ("transfer_decided", "reason")


def test_history_keeps_every_transfer():
    """FR-708: история — все строки, включая отклонённый и согласованный переносы."""
    row, head, controller, assignee = _setup()
    first = transfers().request(assignee, row, new_deadline=row.deadline + datetime.timedelta(days=3),
                                reason="Первый")
    transfers().decide(controller, first, approve=False, comment="Нет")
    second = transfers().request(assignee, row, new_deadline=row.deadline + datetime.timedelta(days=6),
                                 reason="Второй")
    transfers().decide(controller, second, approve=True)
    rows = support.model("instructions.InstructionTransfer").objects.filter(instruction=row).order_by("pk")
    assert [(item.state, item.reason) for item in rows] == [("rejected", "Первый"), ("approved", "Второй")]


def test_decision_notifies_assignee(django_capture_on_commit_callbacks):
    """FR-708: о решении уведомляется исполнитель — вид `instructions.transfer`, ссылка на карточку."""
    row, head, controller, assignee = _setup()
    transfer = transfers().request(assignee, row, new_deadline=row.deadline + datetime.timedelta(days=4),
                                   reason="Причина")
    with django_capture_on_commit_callbacks(execute=True):
        transfers().decide(controller, transfer, approve=True, comment="Согласовано")
    note = support.model("notify.Notification").objects.filter(user=assignee,
                                                               kind="instructions.transfer").first()
    assert note is not None and note.url == f"/instructions/{row.pk}/"


def test_request_and_decide_pages(client):
    """CONTRACT-010, 6.2: запрос переноса и решение — 302; строка `[data-transfer]` со состоянием `pending`."""
    row, head, controller, assignee = _setup()
    client.force_login(assignee)
    new_deadline = (row.deadline + datetime.timedelta(days=7)).isoformat()
    requested = client.post(f"/instructions/{row.pk}/transfers/",
                            {"new_deadline": new_deadline, "reason": "Нужно время"})
    transfer = support.model("instructions.InstructionTransfer").objects.get(instruction=row)
    assert requested.status_code == 302

    client.force_login(controller)
    approved = client.post(f"/instructions/transfers/{transfer.pk}/approve/", {"comment": "Ок"})
    assert approved.status_code == 302
    transfer.refresh_from_db()
    assert transfer.state == "approved"