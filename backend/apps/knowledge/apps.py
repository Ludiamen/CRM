from django.apps import AppConfig
from django.apps import apps as django_apps


class KnowledgeConfig(AppConfig):
    name = "apps.knowledge"
    label = "knowledge"
    verbose_name = "База знаний"

    def ready(self):
        from apps.core import events
        from apps.knowledge.extensions import register_all
        from apps.knowledge.services import subscriptions

        register_all()
        # Виды `knowledge.*` регистрируются позже `NotifyConfig.ready()` (решение 3 задач): события новых видов
        # подписываются здесь, повторная подписка шиной игнорируется (CONTRACT-005, раздел 17 п. 75).
        if django_apps.is_installed("apps.notify"):
            from apps.notify.services import dispatch

            dispatch.subscribe_all()
        # Увольнение снимает только подписки сотрудника (PLAN-005, «Хранение и увольнение»).
        events.subscribe("core.user_dismissed", subscriptions.on_user_dismissed)
