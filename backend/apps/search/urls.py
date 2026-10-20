"""Маршруты поиска (CONTRACT-005, 10.6)."""
from django.urls import path

from apps.search import views

app_name = "search"

urlpatterns = [
    path("search/popup/", views.popup, name="popup"),
    path("search/", views.results, name="results"),
    path("search/count/", views.count, name="count"),
    path("search/more/", views.more, name="more"),
]
