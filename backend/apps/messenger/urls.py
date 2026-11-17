"""Адреса раздела «Мессенджер» (срез 008).

Каркас T-8001: список пуст, включение адресов не меняет поведения портала; адреса добавляет Этап 3.
T-8203: страница «Написать» (`/messenger/?to=`), поиск людей и создание личного диалога.
"""
from django.urls import path

from apps.messenger.views import chats, settings

app_name = "messenger"

urlpatterns = [
    # Литеральные пути раньше путей с номерами (CONTRACT-008, 10.1)
    path("messenger/", chats.write, name="home"),
    path("messenger/people/", chats.people, name="people"),
    path("messenger/chats/", chats.create, name="chats"),
    path("messenger/chats/<int:chat_id>/members/", chats.members_change, name="members"),
    path("messenger/chats/<int:chat_id>/leave/", chats.leave, name="leave"),
    path("messenger/chats/<int:chat_id>/delete/", chats.delete, name="delete"),
    path("settings/messenger/", settings.settings_page, name="settings"),
]