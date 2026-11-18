"""Виды уведомлений мессенджера (срез 008, T-8217; CONTRACT-008, 7.1–7.2).

PLAN-008 «Уведомления». Два вида после видов ленты: «Новое сообщение в чате» (order 80, склейка по чату) и
«Упомянул вас в чате» (order 81). Каналы по умолчанию — портал и почта; внешний текст постоянный, без ФИО и
названия чата (NFR-705). `still_relevant` считается по данным: чат виден и есть непрочитанные.
"""
from apps.core.extensions import NotificationKind

MODULE = "Мессенджер"
MESSAGE_CODE = "messenger.message"
MENTION_CODE = "messenger.mention"


def notification_kinds() -> list:
    """Записи точки `notification_kinds`: два вида мессенджера (порядок 80/81)."""
    from apps.messenger.services import notify_rules

    return [
        NotificationKind(
            code=MESSAGE_CODE,
            title="Новое сообщение в чате",
            module=MODULE,
            order=80,
            default_channels=("portal", "email"),
            external_text="Новое сообщение в чате",
            still_relevant=notify_rules.still_relevant,
            coalesce=True,
            coalesce_text=notify_rules.message_coalesce_text,
        ),
        NotificationKind(
            code=MENTION_CODE,
            title="Упомянул вас в чате",
            module=MODULE,
            order=81,
            default_channels=("portal", "email"),
            external_text="Вас упомянули в чате",
            still_relevant=notify_rules.still_relevant,
        ),
    ]