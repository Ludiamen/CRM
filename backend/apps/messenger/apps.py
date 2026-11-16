from django.apps import AppConfig


class MessengerConfig(AppConfig):
    name = "apps.messenger"
    label = "messenger"
    verbose_name = "Мессенджер"

    def ready(self):
        from apps.messenger.extensions import register_all

        register_all()