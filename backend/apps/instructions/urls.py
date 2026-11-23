"""Адреса раздела «Поручения» (срез 010; CONTRACT-010).

T-10007: каркас — реестр, фрагмент реестра и настройки. Остальные адреса контракта добавляют T-10203…T-10217.
"""
from django.urls import path

from apps.instructions.views import actions, files, pages, reports, settings, transfers

app_name = "instructions"

urlpatterns = [
    path("instructions/", pages.registry, name="registry"),
    path("instructions/list/", pages.list_fragment, name="list_fragment"),
    path("instructions/discipline/", pages.discipline, name="discipline"),
    path("instructions/discipline.xlsx", pages.discipline_excel, name="discipline_excel"),
    path("instructions/files/", files.upload, name="files"),
    path("instructions/files/<uuid:file_id>/", files.download, name="file"),
    path("instructions/new/", actions.new_page, name="new"),
    path("instructions/<int:instruction_id>/", actions.detail, name="card"),
    path("instructions/<int:instruction_id>/reports/", reports.submit, name="reports"),
    path("instructions/<int:instruction_id>/parts/", reports.add_part, name="parts"),
    path("instructions/reports/<int:report_id>/accept/", reports.accept, name="report_accept"),
    path("instructions/reports/<int:report_id>/return/", reports.return_report, name="report_return"),
    path("instructions/<int:instruction_id>/ladder/", actions.ladder, name="ladder"),
    path("instructions/<int:instruction_id>/tasks/", actions.task_link, name="task_link"),
    path("instructions/<int:instruction_id>/close/", actions.close, name="close"),
    path("instructions/<int:instruction_id>/transfers/", transfers.request, name="transfers"),
    path("instructions/transfers/<int:transfer_id>/approve/", transfers.approve, name="transfer_approve"),
    path("instructions/transfers/<int:transfer_id>/reject/", transfers.reject, name="transfer_reject"),
    path("settings/instructions/", settings.settings_page, name="settings"),
    path("settings/instructions/basis/", settings.basis_page, name="basis"),
    path("settings/instructions/basis/<int:kind_id>/", settings.edit_basis, name="basis_edit"),
    path("settings/instructions/basis/<int:kind_id>/delete/", settings.delete_basis, name="basis_delete"),
]