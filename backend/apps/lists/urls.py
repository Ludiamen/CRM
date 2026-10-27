"""Адреса раздела «Списки» (срез 006; PLAN-006, «Контракты»; CONTRACT-006, раздел 10, решение 60, 15.6 S2-Б).

Плоский `urlpatterns`, подключён в `config/urls.py` под `lists/`; имена маршрутов — по последнему слову пути. Адреса
следующих задач заведены заглушкой `home.pending` (404 после `@login_required`): в третьем аргументе `path()` стоит
номер задачи, которая заменяет строку настоящим представлением. Литеральные пути — раньше путей с номерами и кодом.
"""
from django.urls import path

from apps.lists.views import home, pickers, records, settings

app_name = "lists"

urlpatterns = [
    # Раздел и настройка (T-6214a)
    path("", home.home, name="home"),
    path("new/", settings.new, name="new"),
    # Подсказки: литеральные пути раньше `<int:list_id>/` (T-6214a — люди и узлы; T-6218 — заявки)
    path("people/", pickers.people, name="people"),
    path("units/", pickers.units, name="units"),
    path("ticket-pick/", home.pending, {"task": "T-6218"}, name="ticket_pick"),
    path("ticket-links/", home.pending, {"task": "T-6218"}, name="ticket_links"),
    path("ticket-links/<int:link_id>/delete/", home.pending, {"task": "T-6218"}, name="ticket_link_delete"),
    # Настройка списка: вкладки «Основное» и «Права» — T-6214a, «Поля» — T-6214b; `new/` и `order/` раньше `<код>/`
    path("<int:list_id>/settings/", settings.main, name="settings"),
    path("<int:list_id>/settings/fields/", settings.fields, name="fields"),
    path("<int:list_id>/settings/fields/new/", settings.field_new, name="field_new"),
    path("<int:list_id>/settings/fields/order/", settings.field_order, name="field_order"),
    path("<int:list_id>/settings/fields/<str:code>/", settings.field_edit, name="field_edit"),
    path("<int:list_id>/settings/fields/<str:code>/hide/", settings.field_hide, name="field_hide"),
    path("<int:list_id>/settings/fields/<str:code>/show/", settings.field_show, name="field_show"),
    path("<int:list_id>/settings/fields/<str:code>/delete/", settings.field_delete, name="field_delete"),
    path("<int:list_id>/settings/fields/<str:code>/up/", settings.field_up, name="field_up"),
    path("<int:list_id>/settings/fields/<str:code>/down/", settings.field_down, name="field_down"),
    path("<int:list_id>/settings/fields/<str:code>/choices/", settings.field_choices, name="field_choices"),
    path("<int:list_id>/settings/access/", settings.access_tab, name="access"),
    path("<int:list_id>/delete/", settings.delete, name="delete"),
    # Таблица (T-6216; выгрузка — T-6220)
    path("<int:list_id>/", home.pending, {"task": "T-6216"}, name="grid"),
    path("<int:list_id>/columns/", home.pending, {"task": "T-6216"}, name="columns"),
    path("<int:list_id>/filter-values/<str:code>/", home.pending, {"task": "T-6216"}, name="filter_values"),
    path("<int:list_id>/export/", home.pending, {"task": "T-6220"}, name="export"),
    path("<int:list_id>/bulk-archive/", home.pending, {"task": "T-6216"}, name="bulk_archive"),
    path("<int:list_id>/labels/", home.pending, {"task": "T-6223"}, name="labels"),
    # Запись (T-6215), файлы (T-6222), этикетка (T-6223)
    path("<int:list_id>/add/", records.add, name="add"),
    path("<int:list_id>/<int:number>/", records.record, name="record"),
    path("<int:list_id>/<int:number>/edit/", records.edit, name="edit"),
    path("<int:list_id>/<int:number>/history/", records.history, name="history"),
    path("<int:list_id>/<int:number>/archive/", records.archive, name="archive"),
    path("<int:list_id>/<int:number>/restore/", records.restore, name="restore"),
    path("<int:list_id>/<int:number>/purge/", records.purge, name="purge"),
    path("<int:list_id>/<int:number>/files/", home.pending, {"task": "T-6222"}, name="files"),
    path("<int:list_id>/<int:number>/files/<int:file_id>/", home.pending, {"task": "T-6222"}, name="file"),
    path("<int:list_id>/<int:number>/files/<int:file_id>/delete/", home.pending, {"task": "T-6222"},
         name="file_delete"),
    path("<int:list_id>/<int:number>/label/", home.pending, {"task": "T-6223"}, name="label"),
    # Загрузка из таблицы и образец (T-6221)
    path("<int:list_id>/import/", home.pending, {"task": "T-6221"}, name="import"),
    path("<int:list_id>/import/<int:job>/", home.pending, {"task": "T-6221"}, name="import_job"),
    path("<int:list_id>/import/<int:job>/confirm/", home.pending, {"task": "T-6221"}, name="import_confirm"),
    path("<int:list_id>/sample/", home.pending, {"task": "T-6221"}, name="sample"),
    # Подбор записи для поля-ссылки (T-6215)
    path("<int:list_id>/pick/", pickers.record, name="pick"),
]
