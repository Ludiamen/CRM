"""Адреса раздела «Поручения» (срез 010; CONTRACT-010).

T-10007: каркас — реестр, фрагмент реестра и настройки. Остальные адреса контракта добавляют T-10203…T-10217.
"""
from django.urls import path

from apps.instructions.views import pages

app_name = "instructions"

urlpatterns = [
    path("instructions/", pages.registry, name="registry"),
    path("instructions/list/", pages.list_fragment, name="list_fragment"),
    path("settings/instructions/", pages.settings_page, name="settings"),
]