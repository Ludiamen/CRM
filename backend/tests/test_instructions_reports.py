"""Срез 010 «Поручения»: отчёты и части (T-10105; FR-706, 707, 723).

`apps.instructions.services.reports` и маршруты отчётов — CONTRACT-010, 6.2, 7, 10.1. Код среза импортируется
внутри тестов: сбор проходит до появления моделей и служб.
"""
import datetime

import pytest
from django.utils import timezone

from tests import support, support_org
from tests import support_instructions as ins

pytestmark = pytest.mark.django_db


def reports():
    from apps.instructions.services import reports as module
    return module


def _err(call):
    from apps.instructions.texts import InstructionsError

    with pytest.raises(InstructionsError) as caught:
        call()
    return caught.value


def _people():
    tree = support_org.make_tree({"Отдел": {"Группа": {}}})
    head = ins.head_of(tree["Отдел"])
    assignee = support.make_employee()
    support_org.make_member(assignee, tree["Группа"])
    controller = ins.staff_user()
    coexecutor = ins.staff_user()
    row = ins.make_instruction(author=head, controller=controller, assignee=assignee)
    ins.add_coexecutor(row, coexecutor)
    due = ins.add_report_date(row, ins._today() + datetime.timedelta(days=3))
    return row, head, controller, assignee, coexecutor, due


def _audit(code, row):
    return support.model("core.AuditEvent").objects.filter(action=code, object_id=str(row.pk)).exists()


def test_submit_to_date_sets_review_cancels_reminders_and_writes_audit():
    """FR-706, FR-710: отчёт к дате — текст обязателен, дата переходит в «на проверке», напоминания этой даты
    снимаются, журнал `instructions.report_submitted` без текста."""
    row, head, controller, assignee, coexecutor, due = _people()
    reminder = support.model("instructions.InstructionReminder").objects.create(
        instruction=row, date=due, user=assignee, kind="report", stage="r3",
        moment=ins._today() + datetime.timedelta(days=1))

    report = reports().submit(assignee, row, date=due, text="Сделано")
    assert report.instruction_id == row.pk and report.date_id == due.pk
    assert report.author_id == assignee.pk and report.decision == "pending"
    due.refresh_from_db()
    assert due.state == "review"
    reminder.refresh_from_db()
    assert reminder.state == "cancelled"
    assert _audit("instructions.report_submitted", row)


def test_text_is_required_and_limited():
    """FR-706: пустой текст — `report_empty`, длиннее 10 000 — `report_long`; отказ у поля `text`."""
    row, head, controller, assignee, coexecutor, due = _people()
    err = _err(lambda: reports().submit(assignee, row, date=due, text=""))
    assert (err.code, err.field) == ("report_empty", "text")
    err = _err(lambda: reports().submit(assignee, row, date=due, text="я" * 10_001))
    assert (err.code, err.field) == ("report_long", "text")


def test_only_assignee_reports_and_not_after_close():
    """FR-706, FR-707: сводный отчёт пишет ответственный (`report_forbidden` у соисполнителя и руководителя);
    после снятия с контроля — `report_closed`."""
    row, head, controller, assignee, coexecutor, due = _people()
    for actor in (coexecutor, head, controller):
        err = _err(lambda actor=actor: reports().submit(actor, row, date=due, text="Отчёт"))
        assert (err.code, err.field) == ("report_forbidden", "text")
    row.closed_at = timezone.now()
    row.save(update_fields=["closed_at"])
    err = _err(lambda: reports().submit(assignee, row, date=due, text="Отчёт"))
    assert (err.code, err.field) == ("report_closed", "text")


def test_report_date_unknown_and_files_limit():
    """FR-706: чужая отчётная дата — `report_date_unknown`; больше 10 файлов — `report_limit` у поля `file`."""
    row, head, controller, assignee, coexecutor, due = _people()
    other = ins.make_instruction()
    foreign = ins.add_report_date(other, ins._today() + datetime.timedelta(days=2))
    err = _err(lambda: reports().submit(assignee, row, date=foreign, text="Отчёт"))
    assert (err.code, err.field) == ("report_date_unknown", "date")
    err = _err(lambda: reports().submit(assignee, row, date=due, text="Отчёт", files=tuple(range(11))))
    assert (err.code, err.field) == ("report_limit", "file")


def test_final_report_is_one_row_and_resubmits_after_return():
    """FR-706, FR-707: итоговый отчёт к сроку (`date` пусто) один на автора; после возврата повторная отправка
    обновляет его, а не плодит строки."""
    row, head, controller, assignee, coexecutor, due = _people()
    first = reports().submit(assignee, row, text="Итог")
    assert first.date_id is None
    reports().decide(controller, first, accept=False, comment="Доработать")
    second = reports().submit(assignee, row, text="Итог доработан")
    assert second.pk == first.pk
    assert support.model("instructions.InstructionReport").objects.filter(
        instruction=row, date=None, author=assignee).count() == 1
    second.refresh_from_db()
    assert second.text == "Итог доработан" and second.decision == "pending"


def test_parts_by_coexecutor_survive_return():
    """FR-723: соисполнитель добавляет часть к дате до сводного отчёта; контролёр видит части с авторами; возврат
    сводного отчёта части не удаляет."""
    row, head, controller, assignee, coexecutor, due = _people()
    part = reports().add_part(coexecutor, row, due, text="Моя часть")
    assert part.date_id == due.pk and part.author_id == coexecutor.pk
    assert _audit("instructions.part_added", row)

    report = reports().submit(assignee, row, date=due, text="Сводный отчёт")
    reports().decide(controller, report, accept=False, comment="Переделать")
    assert support.model("instructions.InstructionReportPart").objects.filter(date=due).count() == 1


def test_part_forbidden_after_submit_and_duplicate():
    """FR-723: часть добавляется только до сводного отчёта (`part_forbidden`) и один раз на автора
    (`part_duplicate`)."""
    row, head, controller, assignee, coexecutor, due = _people()
    reports().add_part(coexecutor, row, due, text="Первая")
    err = _err(lambda: reports().add_part(coexecutor, row, due, text="Вторая"))
    assert (err.code, err.field) == ("part_duplicate", "text")

    row2, head2, controller2, assignee2, coexecutor2, due2 = _people()
    reports().submit(assignee2, row2, date=due2, text="Сводный")
    err = _err(lambda: reports().add_part(coexecutor2, row2, due2, text="Поздно"))
    assert (err.code, err.field) == ("part_forbidden", "text")
    err = _err(lambda: reports().add_part(assignee2, row2, due2, text="Не моё"))
    assert (err.code, err.field) == ("part_forbidden", "text")


def test_decide_only_controller_and_state_checked():
    """FR-706: решение — только контролёр (`decision_forbidden`); уже рассмотренный отчёт — `decision_state`."""
    row, head, controller, assignee, coexecutor, due = _people()
    report = reports().submit(assignee, row, date=due, text="Отчёт")
    for actor in (head, assignee):
        err = _err(lambda actor=actor: reports().decide(actor, report, accept=True))
        assert (err.code, err.field) == ("decision_forbidden", "comment")
    accepted = reports().decide(controller, report, accept=True)
    assert accepted.decision == "accepted"
    err = _err(lambda: reports().decide(controller, report, accept=True))
    assert (err.code, err.field) == ("decision_state", "comment")


def test_accept_closes_date_and_return_requires_comment():
    """FR-706, FR-717: принятие закрывает дату (`accepted`, `closed_at`); возврат требует комментарий
    (`return_comment_required`), дата — `returned`; журнал решений."""
    row, head, controller, assignee, coexecutor, due = _people()
    report = reports().submit(assignee, row, date=due, text="Отчёт")
    err = _err(lambda: reports().decide(controller, report, accept=False, comment=""))
    assert (err.code, err.field) == ("return_comment_required", "comment")
    returned = reports().decide(controller, report, accept=False, comment="Нужны детали")
    due.refresh_from_db()
    assert returned.decision == "returned" and due.state == "returned"
    assert _audit("instructions.report_returned", row)

    report2 = reports().submit(assignee, row, date=due, text="Доработано")
    reports().decide(controller, report2, accept=True)
    due.refresh_from_db()
    assert due.state == "accepted" and due.closed_at is not None
    assert _audit("instructions.report_accepted", row)


def test_accept_closes_date_and_moves_status_to_next_date():
    """FR-706, FR-717: принятие промежуточного отчёта закрывает дату и возвращает поручение к следующей дате."""
    from apps.instructions.services import dates as dates_service

    row, head, controller, assignee, coexecutor, due = _people()
    next_due = ins.add_report_date(row, ins._today() + datetime.timedelta(days=10), position=1)
    report = reports().submit(assignee, row, date=due, text="Первый")
    reports().decide(controller, report, accept=True)
    due.refresh_from_db()
    assert due.state == "accepted"
    assert dates_service.next_open(row).pk == next_due.pk


def test_report_pages_success_and_refusal(client):
    """CONTRACT-010, 6.2: обычный POST отчёта — 302 на карточку; пустой текст — 200 с
    `[data-error="text"][data-code="report_empty"]`; решение контролёра — 302."""
    row, head, controller, assignee, coexecutor, due = _people()
    client.force_login(assignee)
    bad = client.post(f"/instructions/{row.pk}/reports/", {"date": due.pk, "text": ""})
    assert bad.status_code == 200
    assert b'data-error="text"' in bad.content and b'data-code="report_empty"' in bad.content

    good = client.post(f"/instructions/{row.pk}/reports/", {"date": due.pk, "text": "Отчёт"})
    report = support.model("instructions.InstructionReport").objects.get(instruction=row, date=due)
    assert good.status_code == 302 and good["Location"] == f"/instructions/{row.pk}/"

    client.force_login(controller)
    accepted = client.post(f"/instructions/reports/{report.pk}/accept/", {})
    assert accepted.status_code == 302
    report.refresh_from_db()
    assert report.decision == "accepted"