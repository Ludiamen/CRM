"""Маршруты разделов «Структура», «Календарь» и загрузок (PLAN-002, «Где живёт код»; «Контракты»).

Объявлены все маршруты среза сразу (T-2230a); следующие задачи заменяют только тела представлений.
`sample.csv` и `sample.xlsx` стоят до `import/<int:import_id>/`; день календаря — `<str:day>`
(ГГГГ-ММ-ДД разбирает представление, неверная дата — 404).
"""
from django.urls import path

from .views import calendar, members, people, staff_import, structure, structure_forms

urlpatterns = [
    # структура
    path("structure/", structure.structure_home, name="structure"),
    path("structure/new/", structure_forms.unit_new, name="unit-new"),
    path("structure/import/", staff_import.import_start, name="staff-import"),
    path("structure/import/sample.csv", staff_import.sample_csv, name="staff-import-sample-csv"),
    path("structure/import/sample.xlsx", staff_import.sample_xlsx, name="staff-import-sample-xlsx"),
    path("structure/import/<int:import_id>/", staff_import.import_preview, name="staff-import-preview"),
    path("structure/people/<int:user_id>/dismiss/", people.dismiss, name="person-dismiss"),
    path("structure/people/<int:user_id>/rehire/", people.rehire, name="person-rehire"),
    path("structure/<int:unit_id>/", structure.unit_card, name="unit"),
    path("structure/<int:unit_id>/edit/", structure_forms.unit_edit, name="unit-edit"),
    path("structure/<int:unit_id>/delete/", structure_forms.unit_delete, name="unit-delete"),
    path("structure/<int:unit_id>/candidates/", members.candidates, name="unit-candidates"),
    path("structure/<int:unit_id>/members/", members.members_add, name="unit-members"),
    path("structure/<int:unit_id>/members/<int:user_id>/transfer/", members.member_transfer,
         name="unit-member-transfer"),
    path("structure/<int:unit_id>/members/<int:user_id>/remove/", members.member_remove, name="unit-member-remove"),
    path("structure/<int:unit_id>/marks/", members.marks, name="unit-marks"),
    path("structure/<int:unit_id>/roles/", members.unit_roles, name="unit-roles"),
    # календарь
    path("calendar/", calendar.calendar_year, name="calendar"),
    path("calendar/settings/", calendar.calendar_settings, name="calendar-settings"),
    path("calendar/upload/", calendar.calendar_upload, name="calendar-upload"),
    path("calendar/upload/<int:upload_id>/", calendar.calendar_upload_preview, name="calendar-upload-preview"),
    path("calendar/days/<str:day>/", calendar.calendar_day, name="calendar-day"),
]
