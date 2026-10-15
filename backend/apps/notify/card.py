"""Раздел «Мои уведомления» карточки сотрудника (точка ядра `card_sections`; PLAN-004, «Личные настройки»;
CONTRACT-004, 14.3, дополнение 21 (е)): только у владельца карточки, во вкладке «Профиль»."""
from apps.core import extensions


def card_sections(viewer, person) -> list[extensions.CardSection]:
    """Ссылка на `/me/notifications/`; чужая карточка раздела не получает."""
    if viewer.pk != person.pk:
        return []
    return [extensions.CardSection("notifications", "profile", 60, "notify/me/_card_section.html")]
