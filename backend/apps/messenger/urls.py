"""Адреса раздела «Мессенджер» (срез 008).

Каркас T-8001: список пуст, включение адресов не меняет поведения портала; адреса добавляет Этап 3.
T-8203: страница «Написать» (`/messenger/?to=`), поиск людей и создание личного диалога.
"""
from django.urls import path

from apps.messenger.views import chats, files, mentions, messages, notifications, pages, settings

app_name = "messenger"

urlpatterns = [
    # Литеральные пути раньше путей с номерами (CONTRACT-008, 10.1)
    path("messenger/", pages.page, name="home"),
    path("messenger/list/", pages.list_fragment, name="list"),
    path("messenger/notifications/", notifications.notifications, name="notifications"),
    path("messenger/people/", chats.people, name="people"),
    path("messenger/mentions/", mentions.suggest, name="mentions"),
    path("messenger/chats/", chats.create, name="chats"),
    path("messenger/chats/<int:chat_id>/", pages.chat, name="chat"),
    path("messenger/chats/<int:chat_id>/messages/", messages.messages_view, name="messages"),
    path("messenger/chats/<int:chat_id>/read/", chats.mark_read, name="read"),
    path("messenger/chats/<int:chat_id>/search/", messages.chat_search, name="chat_search"),
    path("messenger/files/", files.upload, name="files"),
    path("messenger/files/<int:file_id>/delete/", files.remove, name="file_delete"),
    path("messenger/files/<int:file_id>/", files.download, name="file"),
    path("messenger/files/<int:file_id>/thumb/", files.thumb, name="thumb"),
    path("messenger/messages/<int:message_id>/edit/", messages.edit, name="message_edit"),
    path("messenger/messages/<int:message_id>/delete/", messages.delete, name="message_delete"),
    path("messenger/chats/<int:chat_id>/members/", chats.members_change, name="members"),
    path("messenger/chats/<int:chat_id>/leave/", chats.leave, name="leave"),
    path("messenger/chats/<int:chat_id>/delete/", chats.delete, name="delete"),
    path("settings/messenger/", settings.settings_page, name="settings"),
]