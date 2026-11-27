from django.apps import AppConfig


class ApprovalsConfig(AppConfig):
    name = "apps.approvals"
    label = "approvals"
    verbose_name = "Согласования"

    def ready(self):
        from apps.approvals import extensions, audit_labels, menu, notify_kinds, stand, subscriptions

        extensions.register_all()
        subscriptions.register()
        from apps.core import extensions as core_extensions

        core_extensions.register("menu_items", menu.menu_items)
        core_extensions.register("audit_labels", audit_labels.audit_labels)
        core_extensions.register("notification_kinds", notify_kinds.notification_kinds)
        core_extensions.register("stand_reset", stand.stand_reset)
