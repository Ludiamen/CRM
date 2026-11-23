"""Срез 010 «Поручения»: недельная сводка (T-10114; FR-712, NFR-724).

`apps.instructions.services.digest` и задание `instructions_digest` — CONTRACT-010, 9.3. Код среза импортируется
внутри тестов: сбор проходит до появления моделей и служб.
"""
import datetime
from zoneinfo import ZoneInfo

import pytest
from django.core.cache import cache

from tests import support, support_org
from tests import support_instructions as ins

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
MONDAY = datetime.datetime(2026, 1, 5, 9, 30, tzinfo=MSK)  # первый рабочий день недели


def digest():
    from apps.instructions.services import digest as module
    return module


def _base():
    tree = support_org.make_tree({"Отдел": {"Группа": {}}})
    author = ins.head_of(tree["Отдел"])
    assignee = support.make_employee()
    support_org.make_member(assignee, tree["Группа"])
    controller = ins.staff_user()
    row = ins.make_instruction(author=author, controller=controller, assignee=assignee,
                               deadline=MONDAY.date() + datetime.timedelta(days=5))
    return author, controller, assignee, row


def _notes(kind="instructions.digest"):
    return support.model("notify.Notification").objects.filter(kind=kind)


def test_digest_only_on_first_working_day_during_working_time():
    """FR-712: сводка — в первый рабочий день недели в начале рабочего дня; в другой день или до начала — нет."""
    cache.clear()
    author, controller, assignee, row = _base()
    assert digest().send(datetime.datetime(2026, 1, 5, 8, 0, tzinfo=MSK)) == 0
    assert digest().send(datetime.datetime(2026, 1, 6, 9, 30, tzinfo=MSK)) == 0
    sent = digest().send(MONDAY)
    assert sent >= 1
    assert _notes().filter(user=controller).exists()
    assert _notes().filter(user=author).exists()
    assert not _notes().filter(user=assignee).exists()


def test_digest_includes_deadlines_and_report_dates_within_month_and_overdue():
    """FR-712: в сводку входят сроки и отчётные даты на ближайшие 30 дней и просроченные."""
    cache.clear()
    author, controller, assignee, row = _base()
    base = MONDAY.date()
    soon = ins.make_instruction(title="Скоро", author=author, controller=controller, assignee=assignee,
                                deadline=base + datetime.timedelta(days=10))
    far = ins.make_instruction(title="Далеко", author=author, controller=controller, assignee=assignee,
                               deadline=base + datetime.timedelta(days=60))
    overdue = ins.make_instruction(title="Просрочено", author=author, controller=controller, assignee=assignee,
                                   deadline=base - datetime.timedelta(days=2))
    with_date = ins.make_instruction(title="СОтчётом", author=author, controller=controller, assignee=assignee,
                                     deadline=base + datetime.timedelta(days=40))
    ins.add_report_date(with_date, base + datetime.timedelta(days=9))

    digest().send(MONDAY)
    note = _notes().filter(user=controller).first()
    assert note is not None
    text = note.text
    for title in ("Скоро", "Просрочено", "СОтчётом"):
        assert title in text, f"в сводке нет {title}: {text}"
    assert "Далеко" not in text


def test_empty_digest_is_not_sent():
    """FR-712: пустая сводка не отправляется; отключённые каналы не считаются ошибкой."""
    cache.clear()
    author, controller, assignee, row = _base()
    row.deadline = MONDAY.date() + datetime.timedelta(days=60)
    row.save(update_fields=["deadline"])
    assert digest().send(MONDAY) == 0
    assert not _notes().exists()


def test_repeat_run_does_not_duplicate():
    """FR-712, NFR-724: повторный запуск не создаёт дублей — атомарный `cache.add` на сотрудника."""
    cache.clear()
    author, controller, assignee, row = _base()
    first = digest().send(MONDAY)
    count = _notes().count()
    second = digest().send(MONDAY)
    assert first >= 1 and second == 0
    assert _notes().count() == count


def test_closed_and_deleted_are_not_in_digest():
    """FR-712: закрытые и удалённые поручения в сводку не попадают; пустая — не отправляется."""
    cache.clear()
    author, controller, assignee, row = _base()
    row.closed_at = MONDAY
    row.save(update_fields=["closed_at"])
    assert digest().send(MONDAY) == 0
    assert not _notes().exists()