from django.apps import AppConfig


class NotifyConfig(AppConfig):
    name = "apps.notify"
    label = "notify"
    verbose_name = "Уведомления"

    def ready(self):
        from apps.notify.extensions import register_all

        register_all()
        self.check_kinds()

    def check_kinds(self) -> None:
        """Проверка каталога видов при запуске: повтор кода останавливает запуск (CONTRACT-004 § 3.2, § 6.3)."""
        from apps.notify.services import kinds

        kinds.check()
