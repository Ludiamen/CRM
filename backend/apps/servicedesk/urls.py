"""Маршруты разделов «Заявки», карточки, открытой формы, настроек, справочников, заявителей и загрузки, «Входящие письма» (PLAN-003, «Где живёт код»; «Контракты»).

Объявлены все маршруты среза сразу (T-3230); следующие задачи заменяют только тела представлений в своих модулях
(до того модули-заглушки отвечают 404). Имена маршрутов — `sd-` и имя функции с дефисами; шаблоны и представления
пишут адреса строкой. `tickets/new/` стоит до `tickets/<int:number>/`; `sample.csv` и `sample.xlsx` — до
`import/<int:import_id>/`.
"""
from django.urls import path

from .views import (dictionaries, files, inbound, public_form, requesters, settings, ticket_card, ticket_new,
                    tickets_list)

urlpatterns = [
    # открытая форма
    path("request/", public_form.request_form, name="sd-request-form"),
    path("request/done/", public_form.request_done, name="sd-request-done"),
    # список
    path("tickets/", tickets_list.ticket_list, name="sd-ticket-list"),
    path("tickets/count/", tickets_list.ticket_count, name="sd-ticket-count"),
    path("tickets/bulk/", tickets_list.ticket_bulk, name="sd-ticket-bulk"),
    # заявка от исполнителя
    path("tickets/new/", ticket_new.ticket_new, name="sd-ticket-new"),
    path("tickets/new/requester/", ticket_new.requester_fields, name="sd-requester-fields"),
    path("tickets/new/queue/", ticket_new.queue_fields, name="sd-queue-fields"),
    # карточка и действия
    path("tickets/<int:number>/", ticket_card.ticket_card, name="sd-ticket-card"),
    path("tickets/<int:number>/take/", ticket_card.ticket_take, name="sd-ticket-take"),
    path("tickets/<int:number>/assignees/", ticket_card.ticket_assignees, name="sd-ticket-assignees"),
    path("tickets/<int:number>/assign/", ticket_card.ticket_assign, name="sd-ticket-assign"),
    path("tickets/<int:number>/transfer/", ticket_card.ticket_transfer, name="sd-ticket-transfer"),
    path("tickets/<int:number>/category/", ticket_card.ticket_category, name="sd-ticket-category"),
    path("tickets/<int:number>/fields/", ticket_card.ticket_fields, name="sd-ticket-fields"),
    path("tickets/<int:number>/status/", ticket_card.ticket_status, name="sd-ticket-status"),
    path("tickets/<int:number>/reply/", ticket_card.ticket_reply, name="sd-ticket-reply"),
    path("tickets/<int:number>/reply/<int:entry_id>/resend/", ticket_card.ticket_resend, name="sd-ticket-resend"),
    path("tickets/<int:number>/comment/", ticket_card.ticket_comment, name="sd-ticket-comment"),
    path("tickets/<int:number>/close/", ticket_card.ticket_close, name="sd-ticket-close"),
    path("tickets/<int:number>/reopen/", ticket_card.ticket_reopen, name="sd-ticket-reopen"),
    path("tickets/<int:number>/participants/<int:participant_id>/remove/", ticket_card.participant_remove,
         name="sd-participant-remove"),
    path("tickets/<int:number>/files/<uuid:file_id>/", files.file_download, name="sd-file-download"),
    path("tickets/<int:number>/mail/<int:inbound_id>.eml", files.source_mail, name="sd-source-mail"),
    # настройки и справочники
    path("servicedesk/", settings.settings_page, name="sd-settings-page"),
    path("servicedesk/queues/", settings.queues_page, name="sd-queues-page"),
    path("servicedesk/dictionaries/<slug:kind>/", dictionaries.dictionary_list, name="sd-dictionary-list"),
    path("servicedesk/dictionaries/<slug:kind>/new/", dictionaries.dictionary_new, name="sd-dictionary-new"),
    path("servicedesk/dictionaries/<slug:kind>/<int:item_id>/edit/", dictionaries.dictionary_edit,
         name="sd-dictionary-edit"),
    path("servicedesk/dictionaries/<slug:kind>/<int:item_id>/archive/", dictionaries.dictionary_archive,
         name="sd-dictionary-archive"),
    path("servicedesk/dictionaries/<slug:kind>/<int:item_id>/restore/", dictionaries.dictionary_restore,
         name="sd-dictionary-restore"),
    path("servicedesk/dictionaries/<slug:kind>/<int:item_id>/delete/", dictionaries.dictionary_delete,
         name="sd-dictionary-delete"),
    # заявители и загрузка таблицы
    path("servicedesk/requesters/", requesters.requester_list, name="sd-requester-list"),
    path("servicedesk/requesters/import/", requesters.import_start, name="sd-import-start"),
    path("servicedesk/requesters/import/sample.csv", requesters.import_sample_csv, name="sd-import-sample-csv"),
    path("servicedesk/requesters/import/sample.xlsx", requesters.import_sample_xlsx, name="sd-import-sample-xlsx"),
    path("servicedesk/requesters/import/<int:import_id>/", requesters.import_preview, name="sd-import-preview"),
    path("servicedesk/requesters/<int:requester_id>/edit/", requesters.requester_edit, name="sd-requester-edit"),
    path("servicedesk/requesters/<int:requester_id>/delete/", requesters.requester_delete,
         name="sd-requester-delete"),
    # входящие письма
    path("servicedesk/inbound/", inbound.inbound_list, name="sd-inbound-list"),
    path("servicedesk/inbound/<int:inbound_id>/retry/", inbound.inbound_retry, name="sd-inbound-retry"),
]
