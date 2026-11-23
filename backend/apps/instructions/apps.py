from django.apps import AppConfig


class InstructionsConfig(AppConfig):
    name = "apps.instructions"
    label = "instructions"
    verbose_name = "Поручения"

    def ready(self):
        from apps.instructions.extensions import register_all

        register_all()
