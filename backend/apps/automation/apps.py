from django.apps import AppConfig


class AutomationConfig(AppConfig):
    name = "apps.automation"
    label = "automation"
    verbose_name = "Автоматизация"

    def ready(self):
        from apps.automation import action_registry, audit_labels, menu, notify_kinds, stand, subscriptions
        from apps.core import extensions

        extensions.register("automation_actions", action_registry.actions)
        extensions.register("audit_labels", audit_labels.audit_labels)
        extensions.register("menu_items", menu.menu_items)
        extensions.register("notification_kinds", notify_kinds.notification_kinds)
        extensions.register("stand_reset", stand.stand_reset)
        subscriptions.register()
