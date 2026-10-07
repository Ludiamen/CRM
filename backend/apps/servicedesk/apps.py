from django.apps import AppConfig


class ServicedeskConfig(AppConfig):
    name = "apps.servicedesk"
    label = "servicedesk"
    verbose_name = "Сервис-деск"

    def ready(self):
        from apps.servicedesk.extensions import register_all
        from apps.servicedesk.services import events

        register_all()
        events.register()
