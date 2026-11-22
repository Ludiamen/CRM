from django.apps import AppConfig


class TasksConfig(AppConfig):
    name = "apps.tasks"
    label = "tasks"
    verbose_name = "Задачи"

    def ready(self):
        from apps.tasks.extensions import register_all

        register_all()