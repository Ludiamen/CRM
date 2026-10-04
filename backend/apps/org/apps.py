from django.apps import AppConfig


class OrgConfig(AppConfig):
    name = "apps.org"
    label = "org"
    verbose_name = "Оргструктура"

    def ready(self):
        from apps.org.extensions import register_all

        register_all()
