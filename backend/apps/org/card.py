"""Точка ядра `card_sections`: разделы «Профиля» карточки сотрудника от `org` (PLAN-002, «Карточка сотрудника»; FR-113, FR-115…117, FR-122, FR-123, FR-127).

Функция получает смотрящего и сотрудника и возвращает разделы с путями шаблонов `org/…`; ядро их только включает
(`CardSection.template`) и не знает о `org`. Читается постоянное число запросов: узлы человека, дерево руководителей,
подчинённые и роли по источникам не растут с числом узлов, ролей и подчинённых.
"""
from apps.core import extensions
from apps.core.models import UserState
from apps.core.services import permissions
from apps.org.models import Membership
from apps.org.services import structure


def _heads_text(items) -> tuple[str, bool]:
    """Текст поля «Руководитель»: один узел — имена через «, »; несколько — «Сеть: Иванов; Поддержка: Петров»."""
    if not any(item.heads for item in items):
        return "", True
    if len(items) == 1:
        return ", ".join(head.full_name for head in items[0].heads), False
    parts = [f"{item.unit.name}: " + (", ".join(head.full_name for head in item.heads) or "не назначен")
             for item in items]
    return "; ".join(parts), False


def card_sections(viewer, person) -> list[extensions.CardSection]:
    """Подразделения, руководитель, подчинённые, роли по источникам и «Уволить»/«Вернуть на работу» (FR-123: по праву)."""
    dismissed = person.state == UserState.DISMISSED
    units = structure.units_of(person)
    heads_text, heads_empty = _heads_text(structure.heads_of(person))
    sections = [
        extensions.CardSection("units", "profile", 10, "org/_card_units.html", {"units_text": ", ".join(u.name for u in units)}),
        extensions.CardSection("head", "profile", 20, "org/_card_head.html",
                               {"heads_text": heads_text, "heads_empty": heads_empty}),
    ]
    if Membership.objects.filter(user=person, mark=Membership.Mark.HEAD).exists():
        sections.append(extensions.CardSection("subordinates", "profile", 30, "org/_card_subordinates.html",
                                               {"subordinates": structure.subordinates_of(person)}))
    if not dismissed and permissions.has_permission(viewer, "accounts.manage"):
        groups = permissions.roles_by_source(person)
        sections.append(extensions.CardSection(
            "roles", "profile", 40, "org/_card_roles.html",
            {"groups": [{"label": label, "roles": roles, "personal": label == "лично",
                         "unit": label.removeprefix("от подразделения ")} for label, roles in groups]}))
    if permissions.has_permission(viewer, "org.manage"):
        sections.append(extensions.CardSection("dismissal", "profile", 50, "org/_card_dismissal.html",
                                               {"dismissed": dismissed}))
    return sections
