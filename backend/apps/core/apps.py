from django.apps import AppConfig


class CoreConfig(AppConfig):
    name = "apps.core"
    label = "core"
    verbose_name = "Ядро портала"

    def ready(self):
        # сигналы сброса кэша прав
        from apps.core.services import permissions  # noqa: F401
