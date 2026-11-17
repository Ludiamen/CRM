"""Адреса раздела «Мессенджер» (срез 008).

Каркас T-8001: список пуст, включение адресов не меняет поведения портала; адреса добавляет Этап 3.
T-8203: страница «Написать» (`/messenger/?to=`), поиск людей и создание личного диалога.
"""
from django.urls import path

from apps.messenger.views import chats

app_name = "messenger"

urlpatterns = [
    # Литеральные пути раньше путей с номерами (CONTRACT-008, 10.1)
    path("messenger/", chats.write, name="home"),
    path("messenger/people/", chats.people, name="people"),
    path("messenger/chats/", chats.create, name="chats"),
]