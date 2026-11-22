"""Адреса раздела «Задачи» (срез 009; CONTRACT-009, 6.2).

T-9009: каркас — список, фрагмент списка и настройки с правом `settings.portal`. Остальные адреса контракта
(доски, карточка, действия, файлы, напоминания, колонки плана, справочник категорий) добавляют T-9203…T-9217.
"""
from django.urls import path

from apps.tasks.views import pages, settings

app_name = "tasks"

urlpatterns = [
    path("tasks/", pages.list_page, name="list"),
    path("tasks/list/", pages.list_fragment, name="list_fragment"),
    path("settings/tasks/", settings.settings_page, name="settings"),
    path("settings/tasks/categories/", settings.categories_page, name="categories"),
]
