from django.apps import AppConfig


class ListsConfig(AppConfig):
    name = "apps.lists"
    label = "lists"
    verbose_name = "Списки"

    def ready(self):
        from apps.lists.extensions import register_all

        register_all()
