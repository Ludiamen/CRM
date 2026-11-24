"""T-11105: очередь, карточка и страницы SLA (FR-741, FR-742, FR-757).

Тесты намеренно обращаются к ещё не реализованным представлениям среза 011.
Заглушки маршрутов могут отвечать 404; права и данные при этом создаются
полностью, чтобы после реализации проверялось именно наблюдаемое поведение.
"""
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from tests import support
from tests import support_org as org
from tests import support_servicedesk as sd


pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")


def _member(queue, *permissions):
    user = support.make_with_permissions(*permissions)
    org.make_member(user, queue.unit)
    return user


def _body(response):
    return response.content.decode("utf-8", "replace")


def _numbers(response):
    import re

    return {int(number) for number in re.findall(r'data-ticket=["\'](\d+)', _body(response))}


def _ticket_with_cycle(queue, *, level=None, kind="new", reaction_due=None, solution_due=None, **cycle):
    level = level or sd.make_level(all_day=True)
    now = timezone.now()
    reaction_due = reaction_due or now + timedelta(hours=1)
    solution_due = solution_due or now + timedelta(hours=4)
    ticket = sd.make_ticket(queue=queue, kind=kind, sla=level,
                            sla_reaction_due=reaction_due, sla_solution_due=solution_due)
    sd.make_cycle(ticket, level=level, reaction_due=reaction_due, solution_due=solution_due, **cycle)
    return ticket


def test_sla_levels_page_requires_permission():
    holder = support.make_with_permissions("servicedesk.sla")
    nobody = support.make_employee()
    assert support.logged_in(holder).get("/servicedesk/sla/").status_code == 200
    assert support.logged_in(nobody).get("/servicedesk/sla/").status_code == 403


def test_sla_levels_page_separates_and_marks_archived_levels():
    holder = support.make_with_permissions("servicedesk.sla")
    active = sd.make_level(title="Действующий уровень")
    archived = sd.make_level(title="Архивный уровень", archived=True)

    response = support.logged_in(holder).get("/servicedesk/sla/")
    html = _body(response)
    assert response.status_code == 200
    assert f'data-sla-id="{active.pk}"' in html
    assert f'data-sla-id="{archived.pk}"' in html
    assert "Архивный уровень" in html
    assert "архив" in html.lower()


def test_due_overdue_includes_ticket_with_late_reaction():
    queue = sd.make_queue()
    user = _member(queue, "servicedesk.all")
    now = timezone.now()
    ticket = _ticket_with_cycle(queue, reaction_due=now - timedelta(hours=2),
                                solution_due=now + timedelta(hours=2))

    response = support.logged_in(user).get("/tickets/", {"due": "overdue", "preset": "all"})
    assert response.status_code == 200
    assert ticket.number in _numbers(response)


def test_due_overdue_includes_closed_ticket_late_for_solution():
    queue = sd.make_queue()
    user = _member(queue, "servicedesk.all")
    now = timezone.now()
    ticket = _ticket_with_cycle(
        queue, kind="closed", reaction_due=now - timedelta(hours=5),
        solution_due=now - timedelta(hours=3), closed_at=now - timedelta(hours=1),
        reaction_met=True, solution_met=False,
    )

    response = support.logged_in(user).get("/tickets/", {"due": "overdue", "preset": "all"})
    assert response.status_code == 200
    assert ticket.number in _numbers(response)


def test_due_today_uses_moscow_date_and_excludes_tomorrow():
    queue = sd.make_queue()
    user = _member(queue, "servicedesk.all")
    today = timezone.now().astimezone(MSK).date()
    today_due = datetime.combine(today, time(12), tzinfo=MSK)
    tomorrow_due = today_due + timedelta(days=1)
    today_ticket = _ticket_with_cycle(queue, reaction_due=today_due,
                                      solution_due=today_due + timedelta(hours=2))
    tomorrow_ticket = _ticket_with_cycle(queue, reaction_due=tomorrow_due,
                                         solution_due=tomorrow_due + timedelta(hours=2))

    response = support.logged_in(user).get("/tickets/", {"due": "today", "preset": "all"})
    assert response.status_code == 200
    assert today_ticket.number in _numbers(response)
    assert tomorrow_ticket.number not in _numbers(response)


def test_due_combines_with_my_queues_preset():
    queue = sd.make_queue()
    foreign = sd.make_queue()
    user = _member(queue, "servicedesk.all")
    now = timezone.now()
    mine = _ticket_with_cycle(queue, reaction_due=now - timedelta(hours=1))
    other = _ticket_with_cycle(foreign, reaction_due=now - timedelta(hours=1))

    response = support.logged_in(user).get("/tickets/", {"due": "overdue", "preset": "my_queues"})
    assert response.status_code == 200
    assert mine.number in _numbers(response)
    assert other.number not in _numbers(response)


def test_unknown_due_is_same_as_empty_due():
    queue = sd.make_queue()
    user = _member(queue, "servicedesk.all")
    ticket = sd.make_ticket(queue=queue)
    client = support.logged_in(user)

    plain = client.get("/tickets/", {"preset": "all"})
    unknown = client.get("/tickets/", {"preset": "all", "due": "not-a-filter"})
    assert plain.status_code == 200 == unknown.status_code
    assert _numbers(plain) == _numbers(unknown)


def test_overdue_count_matches_overdue_list():
    queue = sd.make_queue()
    user = _member(queue, "servicedesk.all")
    now = timezone.now()
    wanted = _ticket_with_cycle(queue, reaction_due=now - timedelta(hours=1))
    sd.make_ticket(queue=queue)
    client = support.logged_in(user)

    listing = client.get("/tickets/", {"due": "overdue", "preset": "all"})
    count = client.get("/tickets/count/", {"due": "overdue", "preset": "all"})
    assert listing.status_code == count.status_code == 200
    assert wanted.number in _numbers(listing)
    assert f'data-total="{len(_numbers(listing))}"' in _body(count)


def test_card_shows_sla_level_deadlines_facts_and_verdicts():
    queue = sd.make_queue()
    user = _member(queue, "servicedesk.all")
    now = timezone.now()
    level = sd.make_level(title="Критичный SLA", all_day=True)
    ticket = _ticket_with_cycle(
        queue, level=level, reaction_due=now - timedelta(hours=2),
        solution_due=now + timedelta(hours=2), first_response_at=now - timedelta(hours=1),
        reaction_met=False, solution_met=True, reaction_minutes=120,
    )

    response = support.logged_in(user).get(f"/tickets/{ticket.number}/")
    html = _body(response)
    assert response.status_code == 200
    assert 'data-sla' in html
    for field in ("level", "reaction-due", "solution-due", "reaction-fact",
                  "solution-fact", "reaction-verdict", "solution-verdict"):
        assert f'data-sla-{field}' in html or f'data-field="{field}"' in html
    assert level.title in html


def test_card_without_level_says_deadline_not_set():
    queue = sd.make_queue()
    user = _member(queue, "servicedesk.all")
    ticket = sd.make_ticket(queue=queue)

    response = support.logged_in(user).get(f"/tickets/{ticket.number}/")
    html = _body(response)
    assert response.status_code == 200
    assert "Срок не задан" in html
    assert 'data-empty="true"' in html


def test_foreign_answer_is_404_and_level_without_permission_is_403():
    queue = sd.make_queue()
    viewer = _member(queue, "servicedesk.all", "servicedesk.answers")
    owner = support.make_employee()
    answer = sd.make_answer(owner=owner)
    level = sd.make_level()

    client = support.logged_in(viewer)
    assert client.get(f"/servicedesk/answers/{answer.pk}/").status_code == 404
    assert client.get(f"/servicedesk/sla/{level.pk}/").status_code == 403


def test_sla_levels_and_report_have_viewport_and_narrow_layout_hooks():
    queue = sd.make_queue()
    manager = _member(queue, "servicedesk.sla", "servicedesk.reports")
    support.model("org.Membership").objects.filter(user=manager, unit=queue.unit).update(mark="head")
    client = support.logged_in(manager)

    levels = client.get("/servicedesk/sla/")
    report = client.get("/servicedesk/reports/", {"period": "month"})
    for response in (levels, report):
        html = _body(response)
        assert response.status_code == 200
        assert 'name="viewport"' in html and "width=device-width" in html
        assert "container" in html or "responsive" in html or "w-100" in html
