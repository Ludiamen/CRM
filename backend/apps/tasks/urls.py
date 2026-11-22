"""Адреса раздела «Задачи» (срез 009; CONTRACT-009, 6.2)."""
from django.urls import path

from apps.tasks.views import actions, comments, files, pages, plan, reminders, settings

app_name = "tasks"

urlpatterns = [
    path("tasks/", pages.list_page, name="list"),
    path("tasks/list/", pages.list_fragment, name="list_fragment"),
    path("tasks/board/status/", pages.board_status, name="board_status"),
    path("tasks/board/deadline/", pages.board_deadline, name="board_deadline"),
    path("tasks/board/plan/", pages.board_plan, name="board_plan"),
    path("tasks/board/category/", pages.board_category, name="board_category"),
    path("tasks/new/", pages.new_page, name="new"),
    path("tasks/", actions.create, name="create"),
    path("tasks/<int:task_id>/", pages.card_page, name="card"),
    path("tasks/<int:task_id>/", actions.update, name="update"),
    path("tasks/<int:task_id>/status/", actions.change_status, name="status"),
    path("tasks/<int:task_id>/move/", actions.move, name="move"),
    path("tasks/<int:task_id>/delete/", actions.delete, name="delete"),
    path("tasks/<int:task_id>/comments/", comments.add, name="comments"),
    path("tasks/comments/<int:comment_id>/edit/", comments.edit, name="comment_edit"),
    path("tasks/comments/<int:comment_id>/delete/", comments.remove, name="comment_delete"),
    path("tasks/files/", files.upload, name="files"),
    path("tasks/files/<uuid:file_id>/", files.download, name="file"),
    path("tasks/<int:task_id>/remind/", reminders.remind, name="remind"),
    path("tasks/reminders/<int:reminder_id>/postpone/", reminders.postpone, name="postpone"),
    path("tasks/plan/columns/", plan.add_column, name="plan_columns"),
    path("tasks/plan/columns/<int:column_id>/", plan.edit_column, name="plan_column"),
    path("tasks/plan/columns/<int:column_id>/delete/", plan.delete_column, name="plan_column_delete"),
    path("settings/tasks/", settings.settings_page, name="settings"),
    path("settings/tasks/categories/", settings.categories_page, name="categories"),
    path("settings/tasks/categories/<int:category_id>/", settings.edit_category, name="category"),
    path("settings/tasks/categories/<int:category_id>/delete/", settings.delete_category, name="category_delete"),
]
