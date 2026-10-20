"""Маршруты базы знаний (срез 005). Имена — контракт 10.x; задачи круга б3 добавляют свои строки точечно."""
from django.urls import path

from apps.knowledge.views import files as file_views
from apps.knowledge.views import comments as comment_views
from apps.knowledge.views import links as link_views
from apps.knowledge.views import articles as article_views
from apps.knowledge.views import history as history_views
from apps.knowledge.views import management as management_views
from apps.knowledge.views import navigation as navigation_views

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
    # Страницы статьи, редактор, история и корзина над одной статьёй (T-5214)
    path("kb/new/", article_views.new, name="new"),
    path("kb/preview/", article_views.preview, name="preview"),
    path("kb/<int:article_id>/", article_views.article, name="article"),
    path("kb/<int:article_id>/edit/", article_views.edit, name="edit"),
    path("kb/<int:article_id>/publish/", article_views.publish, name="publish"),
    path("kb/<int:article_id>/trash/", article_views.article_trash, name="article_trash"),
    path("kb/<int:article_id>/restore/", article_views.article_restore, name="article_restore"),
    path("kb/<int:article_id>/purge/", article_views.article_purge, name="article_purge"),
    path("kb/<int:article_id>/history/", history_views.history, name="history"),
    path("kb/<int:article_id>/compare/", history_views.compare, name="compare"),
    path("kb/<int:article_id>/versions/<int:number>/", history_views.version, name="version"),
    path("kb/<int:article_id>/versions/<int:number>/restore/", history_views.version_restore, name="version_restore"),
    path("kb/<int:article_id>/versions/<int:number>/delete/", history_views.version_delete, name="version_delete"),
    # Главная, рубрики, теги, корзина, срок корзины (T-5218)
    path("kb/", navigation_views.home, name="home"),
    path("kb/rubrics/", management_views.rubrics_page, name="rubrics"),
    path("kb/rubrics/new/", management_views.rubric_new, name="rubric_new"),
    path("kb/rubrics/<int:rubric_id>/", navigation_views.rubric_page, name="rubric_page"),
    path("kb/rubrics/<int:rubric_id>/rename/", management_views.rubric_rename, name="rubric_rename"),
    path("kb/rubrics/<int:rubric_id>/move/", management_views.rubric_move, name="rubric_move"),
    path("kb/rubrics/<int:rubric_id>/delete/", management_views.rubric_delete, name="rubric_delete"),
    path("kb/rubrics/<int:rubric_id>/subscribe/", navigation_views.rubric_subscribe, name="rubric_subscribe"),
    path("kb/tags/", navigation_views.tag_page, name="tag_page"),
    path("kb/tags/suggest/", navigation_views.tag_suggest, name="tag_suggest"),
    path("kb/trash/", management_views.trash_list, name="trash_list"),
    path("kb/settings/", management_views.settings, name="settings"),
]
