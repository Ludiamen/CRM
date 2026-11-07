"""Адреса раздела «Лента» (срез 007)."""
from django.urls import path

from apps.feed.views import comments, events, files, home, important, likes, pickers, posts, settings

app_name = "feed"

urlpatterns = [
    path("feed/posts/", posts.publish, name="publish"),
    path("feed/pick/", pickers.pick, name="pick"),
    path("feed/files/", files.upload_file, name="files"),
    path("feed/files/<int:file_id>/delete/", files.delete_file, name="file_delete"),
    path("feed/files/<int:file_id>/", files.download_file, name="file"),
    path("feed/files/<int:file_id>/thumb/", files.thumb_file, name="thumb"),
    path("feed/more/", home.more, name="more"),
    path("feed/new/", home.new, name="new"),
    path("feed/<int:post_id>/", posts.card, name="card"),
    path("feed/<int:post_id>/edit/", posts.edit_post, name="edit"),
    path("feed/<int:post_id>/delete/", posts.delete_post, name="delete"),
    path("feed/<int:post_id>/to/", posts.to, name="to"),
    path("feed/<int:post_id>/read/", important.read, name="read"),
    path("feed/<int:post_id>/reads/", important.reads, name="reads"),
    path("feed/<int:post_id>/answer/", events.answer, name="answer"),
    path("feed/<int:post_id>/answers/", events.answers, name="answers"),
    path("feed/<int:post_id>/comments/", comments.comments_view, name="comments"),
    path("feed/<int:post_id>/like/", likes.toggle_post_like, name="like"),
    path("feed/<int:post_id>/likes/", likes.post_likers, name="likes"),
    path("feed/comments/<int:comment_id>/like/", likes.toggle_comment_like, name="comment_like"),
    path("feed/comments/<int:comment_id>/likes/", likes.comment_likers, name="comment_likes"),
    path("feed/comments/<int:comment_id>/edit/", comments.edit_comment, name="comment_edit"),
    path("feed/comments/<int:comment_id>/delete/", comments.delete_comment, name="comment_delete"),
    path("settings/feed/", settings.settings_page, name="settings"),
]
