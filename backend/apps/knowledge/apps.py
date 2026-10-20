from django.apps import AppConfig


class KnowledgeConfig(AppConfig):
    name = "apps.knowledge"
    label = "knowledge"
    verbose_name = "База знаний"

    def ready(self):
        from apps.core import events
        from apps.knowledge.extensions import register_all
        from apps.knowledge.services import subscriptions

        register_all()
        # Увольнение снимает только подписки сотрудника (PLAN-005, «Хранение и увольнение»).
        events.subscribe("core.user_dismissed", subscriptions.on_user_dismissed)
