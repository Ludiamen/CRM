from django.apps import AppConfig


class InstructionsConfig(AppConfig):
    name = "apps.instructions"
    label = "instructions"
    verbose_name = "Поручения"

    def ready(self):
        from apps.core import events
        from apps.instructions.extensions import register_all
        from apps.instructions.services.instructions import reassign

        register_all()
        events.subscribe("core.user_dismissed", reassign)