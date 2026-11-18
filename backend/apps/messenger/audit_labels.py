"""Подписи журнала мессенджера (срез 008, T-8221; CONTRACT-008, 8.2).

Точка `audit_labels` ядра: действия и типы объектов `messenger.*`, ключи «было / стало». Часть `values` пуста —
служба пишет «включён»/«выключен» и числа по-русски сама. Модели модуль не импортирует.
"""


def audit_labels() -> dict:
    """Подписи действий, полей и видов объектов мессенджера в журнале (FR-671, NFR-708)."""
    return {
        "actions": {
            "messenger.chat_deleted": "Групповой чат удалён",
            "messenger.department_chat_deleted": "Чат отдела удалён администратором",
            "messenger.unit_chat_deleted": "Чат удалён вместе с подразделением",
            "messenger.general_changed": "Общий чат включён или выключен",
            "messenger.retention_changed": "Срок хранения сообщений изменён",
            "messenger.retention_purged": "Сообщения удалены по сроку",
        },
        "fields": {
            "chat_title": "название чата",
            "chat_members": "участников",
            "chat_created_at": "создан",
            "unit_id": "номер подразделения",
            "years": "срок хранения, лет",
            "messages": "Удалено по сроку, сообщений",
        },
        "object_types": {"messenger.chat": "чат мессенджера", "messenger.settings": "настройки мессенджера"},
        "values": {},
    }
