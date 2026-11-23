"""Срез 010 «Поручения»: журнал и история (T-10117; FR-718, NFR-727).

`apps.instructions.audit_labels` и записи `core.AuditEvent` — CONTRACT-010, раздел 10. Код среза импортируется
внутри тестов: сбор проходит до появления моделей и служб.
"""
import datetime

import pytest
from django.utils import timezone

from tests import support, support_org
from tests import support_instructions as ins

pytestmark = pytest.mark.django_db

ACTIONS = {
    "instructions.created", "instructions.changed", "instructions.report_submitted",
    "instructions.report_accepted", "instructions.report_returned", "instructions.part_added",
    "instructions.transfer_requested", "instructions.transfer_decided", "instructions.closed",
    "instructions.reassigned", "instructions.retention_changed", "instructions.retention_purged",
    "instructions.reminder_failed",
}


def labels():
    from apps.instructions import audit_labels as module
    return module


def _base():
    tree = support_org.make_tree({"Отдел": {"Группа": {}}})
    head = ins.head_of(tree["Отдел"])
    assignee = ins.staff_user()
    support_org.make_member(assignee, tree["Группа"])
    controller = ins.staff_user()
    row = ins.make_instruction(author=head, controller=controller, assignee=assignee)
    return head, controller, assignee, row


def _events(action, row):
    return support.model("core.AuditEvent").objects.filter(action=action, object_id=str(row.pk))


def test_audit_labels_cover_every_code_and_object_type():
    """FR-718: подписи журнала — все коды среза, поля, типы объектов и значения."""
    data = labels().audit_labels()
    assert ACTIONS <= set(data["actions"])
    assert {"title", "text", "basis", "deadline", "controller", "assignee", "members", "periodicity",
            "years", "instructions"} <= set(data["fields"])
    assert {"instructions.instruction", "instructions.report", "instructions.transfer",
            "instructions.settings", "instructions.basis"} <= set(data["object_types"])
    assert isinstance(data["values"], dict)
    assert all(value for value in data["actions"].values())


def test_created_changed_closed_and_reassigned_events():
    """FR-718: создание, правка, снятие и смена контролёра пишутся в журнал."""
    from apps.org.services import people

    head, controller, assignee, row = _base()
    assert _events("instructions.created", row).exists()

    from apps.instructions.services import instructions as service

    service.update(head, row, title="Новое название", controller=ins.staff_user())
    changed = _events("instructions.changed", row).last()
    assert changed is not None and changed.before["title"] != changed.after["title"]

    new_controller = row.controller
    support.model("instructions.InstructionReport").objects.create(
        instruction=row, date=None, author=assignee, text="Итог", decision="accepted")
    service.close(new_controller, row)
    assert _events("instructions.closed", row).exists()

    other = ins.make_instruction(author=head, controller=ins.staff_user(), assignee=assignee)
    people.dismiss(other.controller, actor=support.make_admin())
    assert _events("instructions.reassigned", other).exists()


def test_report_and_part_events_do_not_store_text():
    """FR-718: отправка отчёта и добавление части — без текста; возврат хранит комментарий (причину)."""
    head, controller, assignee, row = _base()
    due = ins.add_report_date(row, ins._today() + datetime.timedelta(days=3))
    from apps.instructions.services import reports as service

    report = service.submit(assignee, row, date=due, text="Секретный текст отчёта")
    submitted = _events("instructions.report_submitted", row).last()
    assert submitted is not None
    assert "Секретный текст" not in str(submitted.after) and "Секретный текст" not in str(submitted.before)

    service.add_part(assignee, row, due, text="Секретная часть")
    part = _events("instructions.part_added", row).last()
    assert part is not None and "Секретная часть" not in str(part.after)

    service.decide(controller, report, accept=False, comment="Нужны детали")
    returned = _events("instructions.report_returned", row).last()
    assert returned is not None and "Нужны детали" in str(returned.after)


def test_transfer_events_store_deadlines_and_reason():
    """FR-718: запрос переноса хранит старый и новый срок и причину; решение — кто и когда."""
    head, controller, assignee, row = _base()
    from apps.instructions.services import transfers as service

    transfer = service.request(assignee, row, new_deadline=row.deadline + datetime.timedelta(days=5),
                               reason="Нужно время")
    requested = _events("instructions.transfer_requested", row).last()
    assert requested is not None and "Нужно время" in str(requested.after)
    service.decide(controller, transfer, approve=True, comment="Согласовано")
    decided = _events("instructions.transfer_decided", row).last()
    assert decided is not None and "Согласовано" in str(decided.after)


def test_history_page_shows_created_and_changed(client):
    """FR-718, CONTRACT-010, 6.3: история карточки — `[data-history]` с записями журнала."""
    head, controller, assignee, row = _base()
    from apps.instructions.services import instructions as service

    service.update(head, row, title="Изменённое поручение")
    support.login(client, assignee)
    page = client.get(f"/instructions/{row.pk}/")
    html = page.content.decode()
    assert page.status_code == 200 and "data-history" in html
    assert "Поручение создано" in html and "Поручение изменено" in html
    assert "Изменённое поручение" in html