"""Срез 010 «Поручения»: уведомления (T-10113; FR-711, NFR-723).

`apps.instructions.notify_kinds` и `services.notify_rules` — CONTRACT-010, раздел 9. Код среза импортируется
внутри тестов: сбор проходит до появления моделей и служб.
"""
import pytest
from django.utils import timezone

from tests import support, support_org
from tests import support_instructions as ins

pytestmark = pytest.mark.django_db

CODES = (
    "instructions.assigned", "instructions.deadline", "instructions.report_due",
    "instructions.report_overdue", "instructions.overdue", "instructions.report_submitted",
    "instructions.report_accepted", "instructions.report_returned", "instructions.transfer",
    "instructions.digest",
)


def kinds():
    from apps.instructions import notify_kinds as module
    return module


def rules():
    from apps.instructions.services import notify_rules as module
    return module


def _base():
    tree = support_org.make_tree({"Отдел": {"Группа": {}}})
    author = ins.head_of(tree["Отдел"])
    assignee = support.make_employee()
    support_org.make_member(assignee, tree["Группа"])
    controller = ins.staff_user()
    coexecutor = ins.staff_user()
    row = ins.make_instruction(author=author, controller=controller, assignee=assignee)
    ins.add_coexecutor(row, coexecutor)
    return author, controller, assignee, coexecutor, row


def _ref(row):
    return f"instructions.instruction:{row.pk}"


def test_ten_kinds_order_module_channels_and_external_text():
    """FR-711, NFR-723: десять видов с `order` 220–229, модуль «Поручения», каналы портал и почта, внешний текст
    без названия и основания."""
    rows = kinds().notification_kinds()
    assert [kind.code for kind in rows] == list(CODES)
    assert [kind.order for kind in rows] == list(range(220, 230))
    assert {kind.module for kind in rows} == {"Поручения"}
    for kind in rows:
        assert kind.default_channels == ("portal", "email"), kind.code
        assert kind.external_text and kind.title


def test_available_requires_instructions_use():
    """FR-711: виды показываются сотруднику с `instructions.use` и не показываются без него."""
    staff = ins.staff_user()
    plain = support.make_employee()
    rows = kinds().notification_kinds()
    assert len(rows) == 10, f"видов {len(rows)}"
    for kind in rows:
        assert kind.available(staff) is True, kind.code
        assert kind.available(plain) is False, kind.code


def test_recipients_for_deadline_report_and_overdue_events():
    """FR-711: лестница и отчёты — исполнителю и соисполнителям; просрочка отчёта — контролёру и автору;
    просрочка срока — всем участникам; пришедший отчёт — контролёру и автору."""
    author, controller, assignee, coexecutor, row = _base()
    for event, expected in (
            ("assigned", {assignee.pk: "instructions.assigned", coexecutor.pk: "instructions.assigned"}),
            ("deadline", {assignee.pk: "instructions.deadline", coexecutor.pk: "instructions.deadline"}),
            ("report_due", {assignee.pk: "instructions.report_due", coexecutor.pk: "instructions.report_due"}),
            ("report_overdue", {controller.pk: "instructions.report_overdue",
                                author.pk: "instructions.report_overdue"}),
            ("overdue", {assignee.pk: "instructions.overdue", coexecutor.pk: "instructions.overdue",
                         controller.pk: "instructions.overdue", author.pk: "instructions.overdue"})):
        assert rules().recipients(row, event) == expected, event


def test_recipients_for_report_decisions_and_transfer():
    """FR-711, FR-708: решения по отчёту — исполнителю и соисполнителям; перенос — контролёру и автору, решение —
    исполнителю; сводка — контролёру и автору."""
    author, controller, assignee, coexecutor, row = _base()
    for event, actor, expected in (
            ("report_submitted", assignee, {controller.pk: "instructions.report_submitted",
                                            author.pk: "instructions.report_submitted"}),
            ("report_accepted", controller, {assignee.pk: "instructions.report_accepted",
                                             coexecutor.pk: "instructions.report_accepted"}),
            ("report_returned", controller, {assignee.pk: "instructions.report_returned",
                                             coexecutor.pk: "instructions.report_returned"}),
            ("transfer_requested", assignee, {controller.pk: "instructions.transfer",
                                              author.pk: "instructions.transfer"}),
            ("transfer_decided", controller, {assignee.pk: "instructions.transfer"}),
            ("digest", None, {controller.pk: "instructions.digest", author.pk: "instructions.digest"})):
        assert rules().recipients(row, event, actor=actor) == expected, event


def test_own_action_and_role_merges_produce_one_message():
    """FR-711: свои действия уведомлений не создают; при совмещении ролей человек получает одно сообщение с
    приоритетом."""
    author, controller, assignee, coexecutor, row = _base()
    assert rules().recipients(row, "assigned", actor=assignee) == {coexecutor.pk: "instructions.assigned"}

    row.assignee = controller
    row.save(update_fields=["assignee"])
    overdue = rules().recipients(row, "overdue")
    assert overdue[controller.pk] == "instructions.overdue"
    assert list(overdue.values()).count("instructions.overdue") == len(overdue)

    row.controller = author
    row.save(update_fields=["controller"])
    submitted = rules().recipients(row, "report_submitted", actor=assignee)
    assert set(submitted) == {author.pk}


def test_still_relevant_false_for_closed_and_deleted():
    """FR-711: уведомление теряет смысл, когда поручение закрыто или удалено."""
    author, controller, assignee, coexecutor, row = _base()
    assigned = next(kind for kind in kinds().notification_kinds() if kind.code == "instructions.assigned")
    assert assigned.still_relevant(assignee.pk, _ref(row)) is True

    row.closed_at = timezone.now()
    row.save(update_fields=["closed_at"])
    assert assigned.still_relevant(assignee.pk, _ref(row)) is False

    row.closed_at = None
    row.deleted_at = timezone.now()
    row.save(update_fields=["closed_at", "deleted_at"])
    assert assigned.still_relevant(assignee.pk, _ref(row)) is False


def test_foreign_recipient_does_not_receive_task_notifications():
    """FR-711, FR-721: посторонний не получает уведомлений по чужому поручению."""
    author, controller, assignee, coexecutor, row = _base()
    outsider = support.make_employee()
    for event in ("assigned", "deadline", "report_due", "overdue", "report_submitted", "digest"):
        assert outsider.pk not in rules().recipients(row, event), event