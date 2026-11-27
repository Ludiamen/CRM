"""Красные контракты доступа к правилам (T-13006; FR-812–814)."""
import pytest

from tests import support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support_automation import make_rule

pytestmark = pytest.mark.django_db


def test_queue_manager_sees_only_own_queue_rules():
    from apps.automation.services import access

    queue = sd.make_queue()
    manager = support.make_employee()
    org.make_member(manager, queue.unit, mark="head")
    own = make_rule(manager, scope="queue", queue=queue.unit)
    other = make_rule(support.make_employee(), scope="queue", queue=sd.make_queue().unit)
    visible = set(access.visible_rules(manager).values_list("pk", flat=True))
    assert own.pk in visible
    assert other.pk not in visible


def test_task_author_does_not_see_ticket_rules():
    """FR-813: автор задачи видит только свои правила задач, но не правила заявок."""
    from apps.automation.services import access
    from tests.support_automation import make_rule

    author = support.make_with_permissions("tasks.use")
    own = make_rule(author, subject_type="task", scope="task_author", trigger="task_created")
    foreign = make_rule(author, subject_type="ticket", scope="global", trigger="ticket_created")
    visible = set(access.visible_rules(author).values_list("pk", flat=True))
    assert own.pk in visible and foreign.pk not in visible
