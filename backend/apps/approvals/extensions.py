"""Точки расширения согласований (PLAN-014, «Точки расширения»).

`approval_subjects` регистрируют `servicedesk` и `tasks`; `approvals` читает их. `task_card_parts`
регистрирует это приложение, `tasks` рисует части. `automation_actions` получает действие
`start_approval`.
"""
from dataclasses import dataclass
from typing import Callable

from django.http import HttpRequest


@dataclass(frozen=True)
class ApprovalSubject:
    """Субъект согласования: загрузка, блокировка, краткая справка и права без импорта модели."""

    type: str
    title: str
    load: Callable[[int], object | None]
    lock: Callable[[int], object | None]
    brief: Callable[[object], dict]
    can_view: Callable[[object, object], bool]
    can_work: Callable[[object, object], bool]
    url: Callable[[object], str]


def register_all() -> None:
    """Регистрации приложения в точках ядра."""
    from apps.core import extensions

    from . import action, card

    extensions.register("automation_actions", action.actions)
    extensions.register("ticket_card_parts", card.ticket_card_parts)
    extensions.register("task_card_parts", card.task_card_parts)


def subjects() -> dict:
    """Субъекты согласования, зарегистрированные сервис-деском и задачами."""
    from apps.core import extensions

    found = {}
    for factory in extensions.registered("approval_subjects"):
        made = factory()
        if isinstance(made, (list, tuple)):
            for subject in made:
                found[subject.type] = subject
        else:
            found[made.type] = made
    return found
