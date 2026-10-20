from django.apps import AppConfig


class SearchConfig(AppConfig):
    name = "apps.search"
    label = "search"
    verbose_name = "Поиск"

    def ready(self):
        from apps.search.extensions import register_all

        register_all()
