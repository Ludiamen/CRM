"""Минутное задание отложенных действий автоматизации (PLAN-013, T-13034)."""
from apps.automation.services import tick


def automation_tick() -> int:
    return tick.run_due()


def tasks_automation_tick() -> int:
    """Пороги задач через зарегистрированные субъекты; `tasks` автоматизация не импортирует."""
    from apps.automation.extensions import subjects

    return sum(subject.threshold_tick() for subject in subjects().values() if subject.threshold_tick is not None)
