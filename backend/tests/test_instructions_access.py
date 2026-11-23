"""Срез 010 «Поручения»: права и видимость (T-10102; FR-702, 703, 719, 721, 722).

`apps.instructions.services.access` — правила из CONTRACT-010, раздел 4; служба `instructions.reassign` и
подписка `core.user_dismissed` — FR-722. Код среза импортируется внутри тестов: сбор проходит до появления
моделей и служб.
"""
import datetime

import pytest

from tests import support, support_org
from tests import support_instructions as ins

pytestmark = pytest.mark.django_db


def access():
    from apps.instructions.services import access as module
    return module


def services():
    from apps.instructions.services import instructions as module
    return module


def _tree():
    return support_org.make_tree({"Отдел": {"Группа": {"team:Дежурные": {}}}, "Чужой": {}})


def test_can_assign_head_deputy_and_nested_only():
    """FR-702: ставить поручение может руководитель или заместитель узла сотрудника и вложенных; рядовой
    участник, чужой руководитель и сотрудник без `instructions.assign` — нет (CONTRACT-010, 4)."""
    tree = _tree()
    inside = support.make_employee()
    support_org.make_member(inside, tree["Группа"])
    nested = support.make_employee()
    support_org.make_member(nested, tree["Дежурные"])
    outside = support.make_employee()
    support_org.make_member(outside, tree["Чужой"])
    head = ins.head_of(tree["Отдел"])
    deputy = ins.deputy_of(tree["Отдел"])
    ordinary = support.make_employee()
    support_org.make_member(ordinary, tree["Отдел"])
    head_without_right = support.make_employee()
    support_org.make_member(head_without_right, tree["Отдел"], mark="head")

    for viewer in (head, deputy):
        assert access().can_assign(viewer, inside)
        assert access().can_assign(viewer, nested)
        assert not access().can_assign(viewer, outside)
    assert not access().can_assign(ordinary, inside)
    assert not access().can_assign(head_without_right, inside)


def test_visible_participants_and_managers_of_both_chains():
    """FR-721: видят автор, контролёр, исполнитель, соисполнитель и руководители/заместители цепочки узлов
    исполнителя и постановщика; посторонний — нет; администратор чужих — нет."""
    tree = _tree()
    head = ins.head_of(tree["Отдел"])
    assignee = support.make_employee()
    support_org.make_member(assignee, tree["Группа"])
    controller = ins.staff_user()
    coexecutor = ins.staff_user()
    row = ins.make_instruction(author=head, controller=controller, assignee=assignee)
    ins.add_coexecutor(row, coexecutor)

    for viewer in (head, controller, assignee, coexecutor):
        assert access().visible(viewer, row)
    outsider_head = ins.head_of(tree["Чужой"])
    assert not access().visible(outsider_head, row)
    assert not access().visible(support.make_admin(), row)


def test_admin_sees_own_instruction_and_managers_are_read_only():
    """FR-721 (решения спеки 3, 11): администратор портала видит своё поручение; руководитель цепочки видит
    карточку, но не принимает и не возвращает отчёт — это делает только контролёр."""
    tree = _tree()
    admin = support.make_admin()
    own = ins.make_instruction(author=admin, controller=admin, assignee=admin)
    assert access().visible(admin, own)

    head = ins.head_of(tree["Отдел"])
    assignee = support.make_employee()
    support_org.make_member(assignee, tree["Группа"])
    controller = ins.staff_user()
    row = ins.make_instruction(author=head, controller=controller, assignee=assignee)
    report = _report(row, assignee)
    assert access().visible(head, row)
    assert not access().can_decide(head, row)
    assert not access().can_report(head, row)
    assert access().can_decide(controller, row)


def _report(instruction, author, date=None):
    return support.model("instructions.InstructionReport").objects.create(
        instruction=instruction, date=date, author=author, text="Отчёт")


def test_edit_fields_only_author_and_not_closed():
    """FR-700, FR-703: поля меняет автор, пока поручение не снято с контроля; контролёр без авторства — нет;
    смена контролёра — тоже правка автора."""
    tree = _tree()
    head = ins.head_of(tree["Отдел"])
    assignee = support.make_employee()
    support_org.make_member(assignee, tree["Группа"])
    row = ins.make_instruction(author=head, controller=ins.staff_user(), assignee=assignee)
    assert access().can_edit_fields(head, row)
    assert not access().can_edit_fields(row.controller, row)
    row.closed_at = _now()
    row.save(update_fields=["closed_at"])
    assert not access().can_edit_fields(head, row)


def _now():
    from django.utils import timezone

    return timezone.now()


def test_report_and_part_rights():
    """FR-706, FR-723: сводный отчёт отправляет ответственный; соисполнитель добавляет часть до сводного
    отчёта; после отправки части к дате не добавляются."""
    tree = _tree()
    head = ins.head_of(tree["Отдел"])
    assignee = support.make_employee()
    support_org.make_member(assignee, tree["Группа"])
    coexecutor = ins.staff_user()
    row = ins.make_instruction(author=head, assignee=assignee)
    ins.add_coexecutor(row, coexecutor)
    due = ins.add_report_date(row, ins._today() + datetime.timedelta(days=3))

    assert access().can_report(assignee, row, due)
    assert not access().can_report(coexecutor, row, due)
    assert access().can_add_part(coexecutor, row, due)
    _report(row, assignee, date=due)
    due.state = "review"
    due.save(update_fields=["state"])
    assert not access().can_add_part(coexecutor, row, due)
    assert not access().can_report(assignee, row, due)


def test_transfer_request_and_decision_rights():
    """FR-708: перенос просит ответственный исполнитель, решают постановщик или контролёр; после снятия с
    контроля переносы не оформляются."""
    tree = _tree()
    head = ins.head_of(tree["Отдел"])
    assignee = support.make_employee()
    support_org.make_member(assignee, tree["Группа"])
    controller = ins.staff_user()
    row = ins.make_instruction(author=head, controller=controller, assignee=assignee)
    assert access().can_request_transfer(assignee, row)
    assert not access().can_request_transfer(head, row)
    assert access().can_decide_transfer(controller, row)
    assert access().can_decide_transfer(head, row)
    assert not access().can_decide_transfer(assignee, row)
    row.closed_at = _now()
    assert not access().can_request_transfer(assignee, row)
    assert not access().can_decide_transfer(controller, row)


def test_close_requires_controller_and_accepted_final_report():
    """FR-707: снять с контроля может только контролёр, только при принятом итоговом отчёте и без
    pending-переноса."""
    tree = _tree()
    head = ins.head_of(tree["Отдел"])
    assignee = support.make_employee()
    support_org.make_member(assignee, tree["Группа"])
    controller = ins.staff_user()
    row = ins.make_instruction(author=head, controller=controller, assignee=assignee)
    assert not access().can_close(controller, row)
    assert not access().can_close(head, row)
    assert not access().can_close(assignee, row)

    report = _report(row, assignee)
    report.decision = "accepted"
    report.save(update_fields=["decision"])
    assert access().can_close(controller, row)

    pending = support.model("instructions.InstructionTransfer").objects.create(
        instruction=row, old_deadline=row.deadline,
        new_deadline=row.deadline + datetime.timedelta(days=5), reason="Причина", requested_by=assignee)
    assert not access().can_close(controller, row)
    pending.delete()
    assert access().can_close(controller, row)


def test_blocked_sees_but_does_not_act():
    """FR-722: блокировка лишает действий, но не видимости."""
    tree = _tree()
    head = ins.head_of(tree["Отдел"])
    assignee = support.make_employee(state="blocked")
    support_org.make_member(assignee, tree["Группа"])
    row = ins.make_instruction(author=head, assignee=assignee)
    assert access().visible(assignee, row)
    assert not access().can_report(assignee, row)
    assert not access().can_request_transfer(assignee, row)


def test_dismissed_controller_returns_to_author_with_audit(django_capture_on_commit_callbacks):
    """FR-722: при увольнении контролёра контроль возвращается постановщику, в журнале — `instructions.reassigned`;
    подписка `core.user_dismissed` включена (CONTRACT-010, 3)."""
    from apps.org.services import people

    author = ins.staff_user()
    controller = ins.staff_user()
    row = ins.make_instruction(author=author, controller=controller, assignee=author)
    admin = support.make_admin()
    with django_capture_on_commit_callbacks(execute=True):
        people.dismiss(controller, actor=admin)
    row.refresh_from_db()
    assert row.controller_id == author.pk
    events = support.model("core.AuditEvent").objects.filter(action="instructions.reassigned",
                                                             object_id=str(row.pk))
    assert events.exists()


def test_dismissed_assignee_waits_for_new_appointment(django_capture_on_commit_callbacks):
    """FR-722: при увольнении исполнителя постановщик назначает нового до действий; до назначения поручение
    остаётся видимым автору, действия исполнителя запрещены."""
    from apps.org.services import people

    tree = _tree()
    author = ins.head_of(tree["Отдел"])
    assignee = ins.staff_user()
    support_org.make_member(assignee, tree["Группа"])
    row = ins.make_instruction(author=author, assignee=assignee)
    with django_capture_on_commit_callbacks(execute=True):
        people.dismiss(assignee, actor=support.make_admin())
    row.refresh_from_db()
    assert row.assignee_id == assignee.pk
    assert access().visible(author, row)
    assert not access().can_report(row.assignee, row)
    replacement = ins.staff_user()
    support_org.make_member(replacement, tree["Группа"])
    services().update(author, row, assignee=replacement)
    row.refresh_from_db()
    assert row.assignee_id == replacement.pk
    assert access().can_report(replacement, row)


def test_moved_employee_leaves_previous_manager_view():
    """FR-721 (сценарий 11.3): после перевода сотрудника в другой узел прежний руководитель поручение больше не
    видит; состав считается на момент просмотра."""
    tree = _tree()
    head = ins.head_of(tree["Отдел"])
    person = support.make_employee()
    membership = support_org.make_member(person, tree["Группа"])
    row = ins.make_instruction(author=ins.staff_user(), controller=ins.staff_user(), assignee=person)
    assert access().visible(head, row)
    membership.unit = tree["Чужой"]
    membership.save(update_fields=["unit"])
    assert not access().visible(head, row)


def test_card_404_for_stranger_and_admin_403_for_visible_forbidden(client):
    """FR-719: чужим и администратору чужих поручений — 404 как несуществующего; видимому, но без права —
    403 (снятие с контроля руководителем)."""
    tree = _tree()
    head = ins.head_of(tree["Отдел"])
    assignee = ins.staff_user()
    support_org.make_member(assignee, tree["Группа"])
    controller = ins.staff_user()
    row = ins.make_instruction(author=head, controller=controller, assignee=assignee)

    assert support.logged_in(assignee).get(f"/instructions/{row.pk}/").status_code == 200

    stranger_client = support.logged_in(ins.head_of(tree["Чужой"]))
    stranger = stranger_client.get(f"/instructions/{row.pk}/")
    missing = stranger_client.get("/instructions/999999/")
    assert stranger.status_code == missing.status_code == 404
    assert support.same_failure(stranger, missing)

    admin_response = support.logged_in(support.make_admin()).get(f"/instructions/{row.pk}/")
    assert admin_response.status_code == 404
    assert support.same_failure(admin_response, missing)

    assert support.logged_in(head).post(f"/instructions/{row.pk}/close/", {"confirm": "1"}).status_code == 403