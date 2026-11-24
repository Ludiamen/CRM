"""Красные тесты журнала и русско-московского интерфейса среза 011 (T-11106).

Службы уровней, шаблонов и отчётов появляются на Этапе 3. Импорты кода
приложения намеренно находятся внутри тестов: файл должен собираться заранее.
"""
import re

import pytest
from django.utils import timezone

from tests import support


pytestmark = pytest.mark.django_db


def _events(action):
    AuditEvent = support.model("core.AuditEvent")
    return AuditEvent.objects.filter(action=action).order_by("id")


def test_sla_audit_labels_register_level_and_binding_actions():
    from apps.servicedesk import audit_labels

    actions = audit_labels.audit_labels()["actions"]
    assert {
        "servicedesk.sla_level_created": "Уровень обслуживания создан",
        "servicedesk.sla_level_changed": "Уровень обслуживания изменён",
        "servicedesk.sla_level_archived": "Уровень обслуживания архивирован",
        "servicedesk.binding_changed": "Привязка уровня изменена",
    }.items() <= actions.items()


def test_sla_audit_labels_register_answer_and_report_actions():
    from apps.servicedesk import audit_labels

    actions = audit_labels.audit_labels()["actions"]
    assert {
        "servicedesk.answer_created": "Шаблон ответа создан",
        "servicedesk.answer_changed": "Шаблон ответа изменён",
        "servicedesk.answer_archived": "Шаблон ответа архивирован",
        "servicedesk.report_exported": "Отчёт выгружен",
    }.items() <= actions.items()


def test_sla_level_create_and_update_are_audited_with_actor_and_time():
    from apps.servicedesk.services import sla

    actor = support.make_employee()
    started = timezone.now()
    level = sla.create_level(
        title="Критичный уровень", priority=1, reaction_minutes=30,
        solution_minutes=240, actor=actor,
    )
    created = _events("servicedesk.sla_level_created").get(object_id=str(level.pk))
    assert created.actor_id == actor.pk
    assert created.at >= started

    changed_after = timezone.now()
    sla.update_level(level, title="Критичный уровень изменён", actor=actor)
    changed = _events("servicedesk.sla_level_changed").get(object_id=str(level.pk))
    assert changed.actor_id == actor.pk
    assert changed.at >= changed_after


def test_archiving_sla_level_is_audited():
    from apps.servicedesk.services import sla

    actor = support.make_employee()
    level = sla.create_level(title="Архивируемый уровень", actor=actor)
    sla.archive_level(level, actor=actor)

    event = _events("servicedesk.sla_level_archived").get(object_id=str(level.pk))
    assert event.actor_id == actor.pk
    assert event.at.tzinfo is not None


def test_answer_template_create_update_and_archive_are_audited():
    from apps.servicedesk.services import answers

    actor = support.make_employee()
    template = answers.create(
        title="Шаблон ответа", text="Текст ответа", owner=actor, actor=actor,
    )
    assert _events("servicedesk.answer_created").get(object_id=str(template.pk)).actor_id == actor.pk

    answers.update(template, title="Изменённый шаблон", text="Новый текст", actor=actor)
    assert _events("servicedesk.answer_changed").get(object_id=str(template.pk)).actor_id == actor.pk

    answers.archive(template, actor=actor)
    assert _events("servicedesk.answer_archived").get(object_id=str(template.pk)).actor_id == actor.pk


def test_report_export_is_audited_with_actor():
    from apps.servicedesk.services import reports

    from tests import support_org as org

    actor = support.make_with_permissions("servicedesk.reports")
    unit = org.make_unit()
    org.make_member(actor, unit, mark="head")
    reports.export(actor, {"period": "day"})

    event = _events("servicedesk.report_exported").latest("id")
    assert event.actor_id == actor.pk


def test_assignee_skipped_and_sla_close_fields_have_russian_audit_labels():
    from apps.servicedesk import audit_labels

    labels = audit_labels.audit_labels()
    assert labels["actions"]["ticket.assignee_skipped"] == "Ответственный по уровню не назначен"
    assert {
        "cycle": "номер цикла",
        "level": "уровень обслуживания",
        "reaction_due": "срок реакции",
        "solution_due": "срок решения",
        "verdicts": "вердикты сроков",
    }.items() <= labels["fields"].items()


def test_sla_report_and_answer_pages_are_russian_and_show_moscow_time(client, settings):
    from tests import support_servicedesk as sd

    from tests import support_org as org

    actor = support.make_with_permissions(
        "servicedesk.sla", "servicedesk.reports", "servicedesk.answers",
    )
    unit = org.make_unit()
    org.make_member(actor, unit, mark="head")  # область отчёта — управляемый узел (FR-749)
    sd.make_queue(unit=unit)  # очередь делает пункт «Заявки» видимым: участник сервис-деска
    client = support.logged_in(actor)
    settings.TIME_ZONE = "Europe/Moscow"
    sd.make_level(title="Уровень для русской страницы")
    sd.make_answer(owner=actor, title="Шаблон для русской страницы")
    date_pattern = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")

    paths = (
        "/servicedesk/sla/",
        "/servicedesk/reports/?period=day",
        "/servicedesk/answers/",
    )
    for path in paths:
        response = client.get(path)
        text = response.content.decode("utf-8")
        assert response.status_code == 200, path
        assert re.search(r"[А-Яа-яЁё]", text), path
        assert date_pattern.search(text) or "Москва" in text, path
