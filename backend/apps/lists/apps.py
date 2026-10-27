from django.apps import AppConfig


class ListsConfig(AppConfig):
    name = "apps.lists"
    label = "lists"
    verbose_name = "Списки"

    def ready(self):
        from apps.core import events
        from apps.lists.extensions import register_all
        from apps.lists.services import links

        register_all()
        # Увольнение снимает только выбор столбцов сотрудника; записи, где он указан, остаются (FR-525).
        events.subscribe("core.user_dismissed", links.on_user_dismissed)
