"""Задания рассылки мессенджера в очереди `notify` (срез 008, T-8212).

`publish_event` вызывает `services.live.publish`; очередь `notify` выбирает TASKS-008 (решение 11): рассылка
живых кадров идёт вне запроса, как у ленты. Ошибки внутри рассылки ловит служба и пишет предупреждение.
"""


def publish_event(chat_id: int, message_id=None, action: str = "new", owner_id=None, recipients=None) -> None:
    """Разослать кадр беседы: `live.publish` с теми же аргументами (FR-661)."""
    from apps.messenger.services import live

    live.publish(chat_id, action, message_id, owner=owner_id, recipients=recipients)