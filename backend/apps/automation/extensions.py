"""Точки расширения движка автоматизации (PLAN-013, «Точки расширения»).

Приложения `servicedesk` и `tasks` регистрируют дескрипторы в четырёх точках ядра:
`automation_subjects`, `automation_triggers`, `automation_actions`, `automation_recipients`.
Ядро не импортирует приложения, а `automation` не импортирует их напрямую.
"""
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class Subject:
    """Субъект правила: загрузка, права и значения полей условий."""

    type: str
    title: str
    load: Callable[[int], object | None]
    can_view: Callable[[object, object], bool]
    can_work: Callable[[object, object], bool]
    values: Callable[[object], dict]
    queue_id: Callable[[object], int | None]
    author_id: Callable[[object], int | None]
    assign: Callable | None = None
    create_task: Callable | None = None
    change_status: Callable | None = None
    comment: Callable | None = None
    validate_condition: Callable | None = None
    validate_scope: Callable | None = None
    threshold_tick: Callable | None = None


@dataclass(frozen=True)
class Trigger:
    """Событие субъекта: код правила, код события шины и доступные поля условий."""

    subject_type: str
    code: str
    title: str
    event: str
    fields: tuple[str, ...]


@dataclass(frozen=True)
class Action:
    """Действие правила: схема параметров и обработчик."""

    code: str
    title: str
    params: dict
    handler: Callable


@dataclass(frozen=True)
class Recipient:
    """Получатель уведомления: субъект, код, заголовок и разрешение списка сотрудников."""

    subject_type: str
    code: str
    title: str
    resolve: Callable[[object, object], list[int]]


def _registered(point: str) -> list:
    from apps.core import extensions

    result = []
    for factory in extensions.registered(point):
        made = factory()
        if isinstance(made, (list, tuple)):
            result.extend(made)
        else:
            result.append(made)
    return result


def subjects() -> dict[str, Subject]:
    return {subject.type: subject for subject in _registered("automation_subjects")}


def triggers(subject_type: str | None = None) -> dict[str, Trigger]:
    found = _registered("automation_triggers")
    return {trigger.code: trigger for trigger in found if subject_type is None or trigger.subject_type == subject_type}


def actions() -> dict[str, Action]:
    return {action.code: action for action in _registered("automation_actions")}


def recipients(subject_type: str | None = None) -> dict[str, Recipient]:
    found = _registered("automation_recipients")
    return {recipient.code: recipient for recipient in found
            if subject_type is None or recipient.subject_type == subject_type}
