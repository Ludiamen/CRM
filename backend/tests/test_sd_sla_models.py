"""Красные серверные тесты моделей и ограничений SLA (T-11101, CONTRACT-011)."""
from datetime import date, time, timedelta

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from tests import support
from tests import support_servicedesk as sd

pytestmark = pytest.mark.django_db


def _model(name):
    """Получить модель только во время теста, не ломая раннюю коллекцию."""
    return support.model(f"servicedesk.{name}")


def _assert_db_reject(create):
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            create()


def test_sla_models_have_no_default_permissions():
    for name in ("SlaLevel", "SlaBinding", "AnswerTemplate", "SlaCycle", "SlaNotice", "SlaDigest"):
        assert _model(name)._meta.default_permissions == ()


def test_sla_models_have_russian_verbose_names():
    expected = {
        "SlaLevel": ("уровень SLA", "уровни SLA"),
        "SlaBinding": ("привязка уровня SLA", "привязки уровней SLA"),
        "AnswerTemplate": ("шаблон ответа", "шаблоны ответов"),
        "SlaCycle": ("цикл SLA", "циклы SLA"),
        "SlaNotice": ("уведомление SLA", "уведомления SLA"),
        "SlaDigest": ("сводка SLA", "сводки SLA"),
    }
    for name, verbose_names in expected.items():
        model = _model(name)
        assert (model._meta.verbose_name, model._meta.verbose_name_plural) == verbose_names


def test_sla_level_numeric_ranges_and_reaction_order():
    Level = _model("SlaLevel")
    valid = dict(title="Рабочий", reaction_minutes=5, solution_minutes=43200)
    for field, values in {
        "priority": (-1, 100),
        "reaction_minutes": (4, 43201),
        "solution_minutes": (4, 43201),
    }.items():
        for value in values:
            values_for_object = {**valid, field: value}
            obj = Level(**values_for_object)
            with pytest.raises(ValidationError):
                obj.full_clean()

    obj = Level(**{**valid, "reaction_minutes": 241, "solution_minutes": 240})
    with pytest.raises(ValidationError):
        obj.full_clean()


def test_sla_level_workdays_and_interval_constraints():
    Level = _model("SlaLevel")
    valid = dict(title="Расписание", reaction_minutes=5, solution_minutes=43200)
    for values in ({"workdays": [7]}, {"workdays": [-1]}, {"workdays": []},
                   {"day_start": time(18), "day_end": time(9)}):
        obj = Level(**valid, **values)
        with pytest.raises(ValidationError):
            obj.full_clean()

    # Круглосуточный режим допускает равные/пустые границы интервала.
    obj = Level(**valid, all_day=True, day_start=time(18), day_end=time(9))
    obj.full_clean()


def test_sla_binding_has_one_target_and_unique_category_or_priority():
    level = sd.make_level()
    category = sd.make_category()
    Priority = _model("Priority")
    priority = Priority.objects.order_by("pk").first()
    Binding = _model("SlaBinding")

    with pytest.raises(ValidationError):
        Binding(level=level, kind="category", category=category, priority=priority).full_clean()
    with pytest.raises(ValidationError):
        Binding(level=level, kind="priority").full_clean()

    sd.bind_level(level, category=category)
    _assert_db_reject(lambda: sd.bind_level(level, category=category))
    sd.bind_level(level, priority=priority)
    _assert_db_reject(lambda: sd.bind_level(level, priority=priority))


def test_answer_template_title_and_text_lengths():
    Answer = _model("AnswerTemplate")
    assert Answer._meta.get_field("title").max_length == 100
    assert Answer._meta.get_field("text").max_length == 10_000

def test_personal_answer_template_has_no_category_and_common_may_have_one():
    Answer = _model("AnswerTemplate")
    category = sd.make_category()
    _assert_db_reject(lambda: Answer.objects.create(
        owner=support.make_employee(), title="Личный", text="Текст", category=category))
    Answer.objects.create(title="Общий", text="Текст", category=category)


def test_sla_cycle_unique_keys_and_one_current_cycle():
    ticket = sd.make_ticket()
    level = sd.make_level()
    first = sd.make_cycle(ticket, level=level, number=1)
    Cycle = _model("SlaCycle")
    started = first.cycle_started_at + timedelta(minutes=1)
    _assert_db_reject(lambda: Cycle.objects.create(
        ticket=ticket, number=1, is_current=False, level=level, level_title=level.title,
        queue=ticket.queue, queue_name="", category=None, category_name="", assignee=None,
        assignee_name="", cycle_started_at=started, reaction_due=started, solution_due=started,
    ))
    _assert_db_reject(lambda: Cycle.objects.create(
        ticket=ticket, number=2, is_current=False, level=level, level_title=level.title,
        queue=ticket.queue, queue_name="", category=None, category_name="", assignee=None,
        assignee_name="", cycle_started_at=first.cycle_started_at, reaction_due=started,
        solution_due=started,
    ))
    _assert_db_reject(lambda: Cycle.objects.create(
        ticket=ticket, number=2, is_current=True, level=level, level_title=level.title,
        queue=ticket.queue, queue_name="", category=None, category_name="", assignee=None,
        assignee_name="", cycle_started_at=started, reaction_due=started, solution_due=started,
    ))


def test_archived_sla_level_is_not_selected_for_new_ticket():
    level = sd.make_level(archived=True)
    category = sd.make_category()
    sd.bind_level(level, category=category)
    from apps.servicedesk.services import sla

    ticket = sd.make_ticket(category=category)
    assert sla.apply_level_to_ticket(ticket) is None


def test_sla_notice_key_is_unique():
    cycle = sd.make_cycle(sd.make_ticket(), level=sd.make_level())
    user = support.make_employee()
    Notice = _model("SlaNotice")
    values = dict(cycle=cycle, deadline="reaction", kind="due_soon",
                  due_at=cycle.reaction_due, recipient=user)
    Notice.objects.create(**values)
    _assert_db_reject(lambda: Notice.objects.create(**values))


def test_sla_digest_recipient_day_is_unique():
    Digest = _model("SlaDigest")
    user = support.make_employee()
    values = dict(recipient=user, day=date.today())
    Digest.objects.create(**values)
    _assert_db_reject(lambda: Digest.objects.create(**values))


def test_sla_reminder_hours_are_between_one_and_24():
    Settings = _model("ServiceDeskSettings")
    settings = Settings.objects.get(pk=1)
    for value in (1, 24):
        settings.sla_reminder_hours = value
        settings.save()
    settings.sla_reminder_hours = 0
    _assert_db_reject(settings.save)
    settings.sla_reminder_hours = 25
    _assert_db_reject(settings.save)


def test_ticket_sla_fields_are_nullable_and_ticket_with_time_indexes_is_creatable():
    Ticket = _model("Ticket")
    for name in ("sla", "sla_cycle_started_at", "sla_reaction_due", "sla_solution_due",
                 "sla_first_response_at"):
        field = Ticket._meta.get_field(name)
        assert field.null, name
    ticket = sd.make_ticket()
    assert ticket.sla is None
    assert Ticket.objects.filter(pk=ticket.pk).exists()


def test_sla_cycle_schedule_defaults_to_empty_dict_and_notice_due_at_is_required():
    Cycle, Notice = _model("SlaCycle"), _model("SlaNotice")
    assert Cycle._meta.get_field("schedule").default() == {}
    assert not Notice._meta.get_field("due_at").null
    cycle = sd.make_cycle(sd.make_ticket(), level=sd.make_level())
    with pytest.raises((IntegrityError, ValidationError, TypeError)):
        Notice.objects.create(cycle=cycle, deadline="reaction", kind="due_soon",
                              recipient=support.make_employee())
