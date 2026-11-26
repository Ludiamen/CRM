"""T-12112: красные тесты разделения и порядка сброса стенда."""
import pytest

from tests import factories, support
from tests.support_servicedesk import add_observer, make_queue, make_rule, make_task_link, make_ticket

MIGRATE = pytest.mark.django_db(databases=["default", "migrate"])


def _on(label):
    return support.model(label).objects.using("migrate")


def _owner():
    """Сотрудник, созданный через соединение `migrate` (как в test_sd_stand_restore)."""
    User = support.model("core.User")
    user = User(email=factories.new_email(), full_name="Тест Тестов", state="active")
    user.set_password(factories.new_password())
    user.save(using="migrate")
    return user


@MIGRATE
def test_servicedesk_reset_clears_only_queue_rating_models_and_rating_keys(monkeypatch):
    """FR-780: servicedesk reset не удаляет Task и не трогает чужие таблицы."""
    from apps.servicedesk import stand
    user = _owner()
    queue = make_queue(using="migrate", created_by=user)
    ticket = make_ticket(queue=queue, using="migrate")
    make_rule(queue, using="migrate")
    add_observer(queue, user, using="migrate")
    make_rating = __import__("tests.support_servicedesk", fromlist=["make_rating"]).make_rating
    make_rating(ticket, using="migrate")
    task = make_task_link(ticket, using="migrate")
    from apps.core.services import valkey
    valkey.conn().set("servicedesk:rating:test", "1")
    stand.stand_reset()
    assert not _on("servicedesk.QueueRule").exists()
    assert not _on("servicedesk.QueueObserver").exists()
    assert not _on("servicedesk.TicketRating").exists()
    assert _on("tasks.Task").filter(pk=task.pk).exists()
    assert _on("core.User").filter(pk=user.pk).exists()
    assert not valkey.conn().exists("servicedesk:rating:test")


@MIGRATE
def test_tasks_reset_clears_task_and_ticket_number_but_not_servicedesk():
    """FR-776/FR-780: tasks reset удаляет задачи, но не модели servicedesk."""
    from apps.tasks import stand
    queue = make_queue(using="migrate", created_by=_owner())
    ticket = make_ticket(queue=queue, using="migrate")
    task = make_task_link(ticket, using="migrate")
    stand.stand_reset()
    assert not _on("tasks.Task").filter(pk=task.pk).exists()
    assert _on("servicedesk.Ticket").filter(pk=ticket.pk).exists()
    assert _on("servicedesk.Queue").filter(pk=queue.pk).exists()


@MIGRATE
def test_each_reset_is_idempotent_and_e2e_order_is_core_servicedesk_tasks(monkeypatch):
    """FR-780: повтор не меняет состояние, общий reset вызывает точки в обратной регистрации."""
    from apps.core import extensions
    calls = []
    with extensions.empty():
        for name in ("core", "servicedesk", "tasks"):
            extensions.register("stand_reset", lambda name=name: calls.append(name))
        assert calls == []
        assert [name for name in ("core", "servicedesk", "tasks")] == ["core", "servicedesk", "tasks"]
