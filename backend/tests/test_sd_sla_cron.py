"""T-11111: задания SLA и ежедневная сводка (FR-743...745, NFR-732, NFR-734).

Тесты написаны до тела ``apps.servicedesk.tasks.sla_tick`` /
``sla_digest``. Поэтому задания импортируются только внутри тестов: сборка
файла остаётся возможной до появления реализации.
"""
import ast
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from tests import support, support_org
from tests import support_servicedesk as sd


pytestmark = pytest.mark.django_db
MSK = ZoneInfo("Europe/Moscow")


def _scene(*, started_at=None, assignee=None, level=None, **cycle_fields):
    """Очередь, исполнитель и заявка с текущим циклом SLA."""
    unit = support_org.make_unit()
    assignee = assignee or support.make_employee()
    support_org.make_member(assignee, unit)
    queue = sd.make_queue(unit=unit)
    ticket = sd.make_ticket(queue=queue, assignee=assignee)
    level = level or sd.make_level(all_day=True, reaction_minutes=60, solution_minutes=240)
    cycle = sd.make_cycle(ticket, level=level, assignee=assignee,
                          cycle_started_at=started_at, **cycle_fields)
    return unit, queue, assignee, ticket, cycle


def _cron_calls():
    source = (Path(__file__).resolve().parents[1] / "config" / "cron.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    constants = {node.targets[0].id: node.value.value for node in ast.walk(tree)
                 if isinstance(node, ast.Assign) and len(node.targets) == 1
                 and isinstance(node.targets[0], ast.Name) and isinstance(node.value, ast.Constant)}

    def value(node):
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, ast.Name):
            return constants.get(node.id)
        return None

    result = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name) or node.func.id != "register":
            continue
        values = {arg.arg: value(arg.value) for arg in node.keywords if arg.arg}
        if "name" in values:
            result[values["name"]] = values
    return result


def test_sla_cron_entries_have_required_schedule_queue_and_timeout():
    """FR-743/744: tick идёт каждые пять минут, digest — на десятой минуте часа,
    оба задания находятся в maintenance и имеют предел выполнения 300 секунд."""
    jobs = _cron_calls()
    assert (jobs["servicedesk_sla_tick"]["cron"], jobs["servicedesk_sla_tick"]["queue_name"],
            jobs["servicedesk_sla_tick"]["job_timeout"]) == ("*/5 * * * *", "maintenance", 300)
    assert (jobs["servicedesk_sla_digest"]["cron"], jobs["servicedesk_sla_digest"]["queue_name"],
            jobs["servicedesk_sla_digest"]["job_timeout"]) == ("10 * * * *", "maintenance", 300)


def test_sla_tick_takes_lock_and_busy_second_pass_does_nothing(monkeypatch):
    """NFR-734: второй тик, встретивший занятый ``sla:tick``, не создаёт
    уведомлений и не обрабатывает сроки."""
    from apps.servicedesk import tasks

    _, _, assignee, _, cycle = _scene()
    now = timezone.now()
    cycle.reaction_due = now - timedelta(minutes=1)
    cycle.save(update_fields=["reaction_due"])
    lock = {"free": True}
    monkeypatch.setattr(tasks.cache, "add", lambda key, *args, **kwargs:
                        lock.pop("free", False) if key == "sla:tick" else True)
    tasks.sla_tick(now=now)
    before = sd.notice_rows(recipient=assignee)
    tasks.sla_tick(now=now)
    assert sd.notice_rows(recipient=assignee) == before


def test_sla_tick_restart_before_notice_creation_leaves_one_notice(monkeypatch):
    """NFR-732: падение до фиксации уведомления и повторный запуск дают одну
    запись ``SlaNotice``."""
    from apps.notify.services import dispatch
    from apps.servicedesk import tasks

    _, _, assignee, _, cycle = _scene()
    now = timezone.now()
    cycle.reaction_due = now - timedelta(minutes=1)
    cycle.save(update_fields=["reaction_due"])
    original = dispatch.create
    monkeypatch.setattr(dispatch, "create", lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("restart")))
    with pytest.raises(RuntimeError):
        tasks.sla_tick(now=now)
    monkeypatch.setattr(dispatch, "create", original)
    tasks.sla_tick(now=now)
    assert len(sd.notice_rows(recipient=assignee)) == 1


def test_sla_tick_restart_during_dispatch_keeps_one_notice(monkeypatch):
    """NFR-732: перезапуск на границе транзакции доставки не дублирует
    ``SlaNotice``."""
    from apps.notify.services import dispatch
    from apps.servicedesk import tasks

    _, _, assignee, _, cycle = _scene()
    now = timezone.now()
    cycle.reaction_due = now - timedelta(minutes=1)
    cycle.save(update_fields=["reaction_due"])
    original = dispatch.create
    calls = {"count": 0}

    def fail_once(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise RuntimeError("worker stopped during transaction")
        return original(*args, **kwargs)

    monkeypatch.setattr(dispatch, "create", fail_once)
    with pytest.raises(RuntimeError):
        tasks.sla_tick(now=now)
    tasks.sla_tick(now=now)
    assert len(sd.notice_rows(recipient=assignee)) == 1


def test_sla_tick_restart_after_creation_keeps_one_notice():
    """NFR-732: обычный повтор после успешного тика оставляет одну запись
    уведомления на срок и получателя."""
    from apps.servicedesk import tasks

    _, _, assignee, _, cycle = _scene()
    now = timezone.now()
    cycle.reaction_due = now - timedelta(minutes=1)
    cycle.save(update_fields=["reaction_due"])
    tasks.sla_tick(now=now)
    tasks.sla_tick(now=now + timedelta(minutes=5))
    assert len(sd.notice_rows(recipient=assignee)) == 1


def test_sla_digest_is_sent_in_first_hour_after_calendar_day_start():
    """FR-744: рабочая сводка отправляется в первый час после
    ``WorkCalendar.day_start``."""
    from apps.servicedesk import tasks

    unit, _, _, _, _ = _scene()
    head = support.make_employee()
    support_org.make_member(head, unit, mark="head")
    calendar = support.model("org.WorkCalendar").objects.get()
    calendar.day_start = time(9, 0)
    calendar.save(update_fields=["day_start"])
    now = datetime(2026, 11, 24, 9, 30, tzinfo=MSK)
    assert tasks.sla_digest(now=now) == 1
    assert support.model("servicedesk.SlaDigest").objects.filter(recipient=head, day=date(2026, 11, 24)).exists()


def test_sla_digest_is_not_sent_on_weekend_or_outside_first_hour():
    """FR-744: сводка не отправляется в выходной и за пределами окна
    первого рабочего часа."""
    from apps.servicedesk import tasks

    unit, _, _, _, _ = _scene()
    head = support.make_employee()
    support_org.make_member(head, unit, mark="head")
    assert tasks.sla_digest(now=datetime(2026, 11, 22, 9, 30, tzinfo=MSK)) == 0
    assert tasks.sla_digest(now=datetime(2026, 11, 24, 11, 1, tzinfo=MSK)) == 0
    assert not support.model("servicedesk.SlaDigest").objects.filter(recipient=head).exists()


def test_sla_digest_is_unique_per_recipient_and_day():
    """FR-745/NFR-732: повторная сводка в один день не создаёт второй
    ``SlaDigest`` для получателя."""
    from apps.servicedesk import tasks

    unit, _, _, _, _ = _scene()
    head = support.make_employee()
    support_org.make_member(head, unit, mark="head")
    now = datetime(2026, 11, 24, 9, 10, tzinfo=MSK)
    tasks.sla_digest(now=now)
    tasks.sla_digest(now=now + timedelta(minutes=10))
    assert support.model("servicedesk.SlaDigest").objects.filter(recipient=head, day=date(2026, 11, 24)).count() == 1


def test_sla_digest_contains_overdue_today_and_week_sections():
    """FR-744: текст сводки содержит разделы «Просроченные», «Срок
    сегодня» и «Срок на неделе»."""
    from apps.notify.models import Notification
    from apps.servicedesk import tasks

    unit, _, _, ticket, cycle = _scene()
    head = support.make_employee()
    support_org.make_member(head, unit, mark="head")
    now = datetime(2026, 11, 24, 9, 10, tzinfo=MSK)
    cycle.reaction_due = now - timedelta(days=1)
    cycle.solution_due = now + timedelta(hours=2)
    cycle.save(update_fields=["reaction_due", "solution_due"])
    tasks.sla_digest(now=now)
    note = Notification.objects.get(user=head, kind="servicedesk.sla_digest")
    assert all(section in note.text for section in ("Просроченные", "Срок сегодня", "Срок на неделе"))
    assert str(ticket.number) in note.text


def test_repeated_sla_digest_same_day_creates_no_new_notification():
    """FR-745/NFR-732: повторный запуск сводки в тот же день не создаёт
    новых уведомлений."""
    from apps.notify.models import Notification
    from apps.servicedesk import tasks

    unit, _, _, _, _ = _scene()
    head = support.make_employee()
    support_org.make_member(head, unit, mark="head")
    now = datetime(2026, 11, 24, 9, 10, tzinfo=MSK)
    tasks.sla_digest(now=now)
    first = Notification.objects.filter(user=head, kind="servicedesk.sla_digest").count()
    tasks.sla_digest(now=now + timedelta(hours=1))
    assert Notification.objects.filter(user=head, kind="servicedesk.sla_digest").count() == first
