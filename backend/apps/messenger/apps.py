from django.apps import AppConfig


class MessengerConfig(AppConfig):
    name = "apps.messenger"
    label = "messenger"
    verbose_name = "Мессенджер"

    def ready(self):
        from apps.core import events
        from apps.messenger.extensions import register_all
        from apps.messenger.services import department, unread

        register_all()
        # Удаление подразделения: чат отдела исчезает вместе с узлом после фиксации (T-8205, CONTRACT-008 3.5).
        events.subscribe("unit.deleted", department.on_unit_deleted)
        # Перевод, приём и увольнение меняют видимость чатов: числа непрочитанного затронутых сбрасываются.
        events.subscribe("access.changed", unread.on_access_changed)