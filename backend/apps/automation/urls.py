from django.urls import path

from . import views

urlpatterns = [
    path("automation/", views.rules_list, name="automation-list"),
    path("automation/new/", views.rule_new, name="automation-new"),
    path("automation/<int:pk>/edit/", views.rule_edit, name="automation-edit"),
    path("automation/<int:pk>/toggle/", views.rule_toggle, name="automation-toggle"),
    path("automation/runs/", views.runs, name="automation-runs"),
]
