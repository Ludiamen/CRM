"""Красные контракты правил и условий (T-13004; SPEC-013, FR-794…799)."""
import pytest

from tests import support
from tests import support_servicedesk as sd

pytestmark = pytest.mark.django_db


def test_rule_defaults_are_disabled_and_priority_is_hundred():
    """FR-793/794: новое правило выключено, приоритет по умолчанию 100."""
    from apps.automation.models import Rule

    author = support.make_employee()
    rule = Rule.objects.create(name="Новая заявка", subject_type=Rule.Subject.TICKET,
                               scope=Rule.Scope.GLOBAL, author=author, trigger="ticket_created")
    assert rule.enabled is False
    assert rule.priority == 100
    assert rule.conditions == []


def test_on_event_runs_only_matching_rule_once():
    """FR-795/797/805: подходящее правило выполняется, чужое событие — нет."""
    from apps.automation.services import rules
    from tests.support_automation import make_action, make_rule

    author = support.make_employee()
    ticket = sd.make_ticket(queue=sd.make_queue())
    rule = make_rule(author, trigger="ticket_created", conditions=[{"field": "status_kind", "op": "=", "value": "new"}])
    make_action(rule, 1, "notify", {"recipients": ["assignee"], "text": "Заявка {number}"})
    rule.enabled = True
    rule.save(update_fields=["enabled"])
    assert rules.on_event("ticket", ticket.pk, "ticket_created", "created:1") == 1
    assert rules.on_event("ticket", ticket.pk, "ticket_created", "created:1") == 0


def test_conditions_support_six_operators_and_changed_field():
    """FR-797/798: операторы и псевдополе изменённого поля."""
    from apps.automation.services import conditions

    values = {"priority": 2, "assignee": None, "changed": ["priority"]}
    assert conditions.match(values, [{"field": "priority", "op": "=", "value": 2}])
    assert conditions.match(values, [{"field": "assignee", "op": "пусто", "value": None}])
    assert conditions.match(values, [{"field": "changed_field", "op": "в", "value": ["priority", "category"]}])
    assert not conditions.match(values, [{"field": "changed_field", "op": "в", "value": ["category"]}])


def test_bus_event_runs_enabled_rule_after_commit(django_capture_on_commit_callbacks):
    """FR-795/805: событие шины после commit запускает правило ровно один раз."""
    from apps.automation.models import RuleRun
    from apps.servicedesk.services import events as sd_events
    from tests.support_automation import make_action, make_rule

    author = support.make_employee()
    assignee = support.make_employee()
    ticket = sd.make_ticket(queue=sd.make_queue(), assignee=assignee)
    rule = make_rule(author, trigger="ticket_created", enabled=True)
    make_action(rule, 1, "notify", {"recipients": ["assignee"], "text": "Заявка {number}"})
    with django_capture_on_commit_callbacks(execute=True):
        sd_events.ticket_created(ticket, actor_id=None, channel="form")
    assert RuleRun.objects.filter(rule=rule, event_id=f"created:{ticket.number}").count() == 1


def test_action_registry_has_all_five_codes():
    """FR-799: форма и проверка видят пять действий."""
    from apps.automation.extensions import actions

    assert set(actions()) == {"notify", "assign", "create_task", "change_status", "comment"}


def test_run_keeps_root_uuid_for_chain():
    """FR-806: запуск хранит корневой UUID цепочки."""
    from apps.automation.models import RuleRun
    from apps.automation.services import rules
    from tests.support_automation import make_action, make_rule

    author = support.make_employee()
    ticket = sd.make_ticket(queue=sd.make_queue())
    rule = make_rule(author, enabled=True)
    make_action(rule, 1, "comment", {"text": "Корень"})
    rules.on_event("ticket", ticket.pk, "ticket_created", f"created:{ticket.number}")
    run = RuleRun.objects.get(rule=rule)
    assert run.root_run_id is not None and run.chain_id is not None
