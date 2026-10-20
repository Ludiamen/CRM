"""Маршруты базы знаний (срез 005). Имена — контракт 10.x; задачи круга б3 добавляют свои строки точечно."""
from django.urls import path

from apps.knowledge.views import files as file_views
from apps.knowledge.views import comments as comment_views
from apps.knowledge.views import links as link_views

app_name = "knowledge"

urlpatterns = [
    # Файлы статьи (T-5210)
    path("kb/<int:article_id>/files/", file_views.file_attach, name="file_attach"),
    path("kb/<int:article_id>/files/<int:number>/", file_views.file_download, name="file_download"),
    path("kb/<int:article_id>/files/<int:number>/delete/", file_views.file_delete, name="file_delete"),
    path("kb/<int:article_id>/images/<int:number>/", file_views.image, name="image"),
    # Комментарии (T-5211)
    path("kb/<int:article_id>/comments/", comment_views.comment_add, name="comment_add"),
    path("kb/comments/<int:comment_id>/delete/", comment_views.comment_delete, name="comment_delete"),
    # Связь с заявками и подбор статьи (T-5212)
    path("kb/pick/", link_views.pick, name="pick"),
    path("kb/links/", link_views.link_add, name="link_add"),
    path("kb/links/<int:link_id>/delete/", link_views.link_delete, name="link_delete"),
    path("kb/from-ticket/<int:number>/", link_views.from_ticket, name="from_ticket"),
]
