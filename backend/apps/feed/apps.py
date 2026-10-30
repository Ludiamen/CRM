from django.apps import AppConfig


class FeedConfig(AppConfig):
    name = "apps.feed"
    label = "feed"
    verbose_name = "Живая лента"

    def ready(self):
        from apps.feed.extensions import register_all

        register_all()
