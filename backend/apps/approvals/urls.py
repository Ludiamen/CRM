"""Адреса согласований (PLAN-014, «Маршруты и контракты»)."""
from django.urls import path

from .views import my, routes, templates

app_name = "approvals"

urlpatterns = [
    path("approvals/", templates.templates_list, name="templates"),
    path("approvals/templates/new/", templates.template_new, name="template_new"),
    path("approvals/templates/<int:pk>/edit/", templates.template_edit, name="template_edit"),
    path("approvals/templates/<int:pk>/toggle/", templates.template_toggle, name="template_toggle"),
    path("approvals/my/", my.my, name="my"),
    path("approvals/routes/<int:pk>/", routes.route_page, name="route"),
    path("approvals/start/", routes.start_view, name="start"),
    path("approvals/routes/<int:pk>/cancel/", routes.cancel_view, name="cancel"),
    path("approvals/assignments/<int:pk>/decide/", routes.decide_view, name="decide"),
]
