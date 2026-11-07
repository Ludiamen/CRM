"""Модели ленты (срез 007; PLAN-007, «Модель данных» → «Приложение `feed`»)."""
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import F, Q


class Post(models.Model):
    class Kind(models.TextChoices):
        POST = "post", "Сообщение"
        IMPORTANT = "important", "Важное"
        EVENT = "event", "Событие"

    author = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=16, choices=Kind.choices)
    text = models.TextField(blank=True, default="")
    to_all = models.BooleanField(default=False)
    published_at = models.DateTimeField()
    edited_at = models.DateTimeField(null=True, blank=True)
    important_until = models.DateTimeField(null=True, blank=True)
    event_title = models.CharField(max_length=200, null=True, blank=True)
    event_place = models.CharField(max_length=200, null=True, blank=True)
    event_start = models.DateTimeField(null=True, blank=True)
    event_end = models.DateTimeField(null=True, blank=True)
    remind_at = models.DateTimeField(null=True, blank=True)
    reminded_for_start = models.DateTimeField(null=True, blank=True)
    search = SearchVectorField(null=True)

    class Meta:
        default_permissions = ()
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind="important", important_until__isnull=False)
                    | (~Q(kind="important") & Q(important_until__isnull=True))
                ),
                name="feed_post_important_iff_until",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        kind="event",
                        event_title__isnull=False,
                        event_place__isnull=False,
                        event_start__isnull=False,
                        event_end__isnull=False,
                        event_end__gt=F("event_start"),
                    )
                    & ~Q(event_title="")
                    & ~Q(event_place="")
                    | (
                        ~Q(kind="event")
                        & Q(
                            event_title__isnull=True,
                            event_place__isnull=True,
                            event_start__isnull=True,
                            event_end__isnull=True,
                        )
                    )
                ),
                name="feed_post_event_fields",
            ),
        ]
        indexes = [
            models.Index(fields=["-published_at", "-id"], name="feed_post_published"),
            models.Index(fields=["author", "-published_at", "-id"], name="feed_post_author_pub"),
            models.Index(
                fields=["-published_at", "-id"],
                condition=Q(kind="important"),
                name="feed_post_important_pub",
            ),
            models.Index(
                fields=["-published_at", "-id"],
                condition=Q(kind="event"),
                name="feed_post_event_pub",
            ),
            models.Index(
                fields=["important_until"],
                condition=Q(kind="important"),
                name="feed_post_important_until",
            ),
            models.Index(
                fields=["remind_at"],
                condition=Q(remind_at__isnull=False),
                name="feed_post_remind_at",
            ),
            GinIndex(fields=["search"], name="feed_post_search_gin"),
        ]


class Recipient(models.Model):
    class Kind(models.TextChoices):
        UNIT = "unit", "Подразделение"
        USER = "user", "Сотрудник"

    class Via(models.TextChoices):
        TO = "to", "Кому"
        MENTION = "mention", "Упоминание"

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="recipients")
    kind = models.CharField(max_length=8, choices=Kind.choices)
    unit_id = models.PositiveIntegerField(null=True, blank=True)
    user = models.ForeignKey("core.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    via = models.CharField(max_length=8, choices=Via.choices)
    published_at = models.DateTimeField()

    class Meta:
        default_permissions = ()
        constraints = [
            models.CheckConstraint(
                condition=(
                    Q(kind="unit", unit_id__isnull=False, user__isnull=True)
                    | Q(kind="user", unit_id__isnull=True, user__isnull=False)
                ),
                name="feed_recipient_one_target",
            ),
            models.UniqueConstraint(
                fields=["post", "unit_id"],
                condition=Q(unit_id__isnull=False),
                name="feed_recipient_post_unit_uniq",
            ),
            models.UniqueConstraint(
                fields=["post", "user", "via"],
                condition=Q(user__isnull=False),
                name="feed_recipient_post_user_via_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["unit_id", "-published_at", "-post"],
                condition=Q(unit_id__isnull=False),
                name="feed_recipient_unit_pub",
            ),
            models.Index(
                fields=["user", "-published_at", "-post"],
                condition=Q(user__isnull=False),
                name="feed_recipient_user_pub",
            ),
            models.Index(
                fields=["user", "-published_at", "-post"],
                condition=Q(via="mention"),
                name="feed_recipient_mention",
            ),
        ]


class FeedComment(models.Model):
    comment = models.OneToOneField("core.Comment", on_delete=models.CASCADE, primary_key=True, related_name="+")
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="feed_comments")
    edited_at = models.DateTimeField(null=True, blank=True)
    search = SearchVectorField(null=True)

    class Meta:
        default_permissions = ()
        indexes = [
            models.Index(fields=["post"], name="feed_feedcomment_post"),
            GinIndex(fields=["search"], name="feed_feedcomment_search_gin"),
        ]


class PostLike(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="likes")
    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField()

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="feed_postlike_post_user_uniq")]
        indexes = [models.Index(fields=["post", "-created_at"], name="feed_postlike_post_created")]


class CommentLike(models.Model):
    comment = models.ForeignKey("core.Comment", on_delete=models.CASCADE, related_name="+")
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="comment_likes")
    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField()

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["comment", "user"], name="feed_commentlike_comment_user_uniq")]
        indexes = [models.Index(fields=["comment", "-created_at"], name="feed_commentlike_comment_time")]


class ReadMark(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="read_marks")
    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="+")
    read_at = models.DateTimeField()

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="feed_readmark_post_user_uniq")]


class EventAnswer(models.Model):
    class Answer(models.TextChoices):
        GO = "go", "Пойду"
        NO = "no", "Не смогу"

    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="event_answers")
    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="+")
    answer = models.CharField(max_length=4, choices=Answer.choices)
    answered_at = models.DateTimeField()

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="feed_eventanswer_post_user_uniq")]


class Shown(models.Model):
    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="+")
    post = models.ForeignKey(Post, on_delete=models.CASCADE, related_name="shown")
    shown_at = models.DateTimeField()

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["user", "post"], name="feed_shown_user_post_uniq")]


class FeedFile(models.Model):
    post = models.ForeignKey(Post, on_delete=models.CASCADE, null=True, blank=True, related_name="files")
    comment = models.ForeignKey("core.Comment", on_delete=models.CASCADE, null=True, blank=True, related_name="+")
    file = models.OneToOneField("core.StoredFile", on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=255)
    thumb = models.CharField(max_length=255, blank=True, default="")
    uploaded_by = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField()

    class Meta:
        default_permissions = ()
        constraints = [
            models.CheckConstraint(
                condition=Q(comment__isnull=True) | Q(post__isnull=False),
                name="feed_feedfile_comment_needs_post",
            ),
        ]
        indexes = [
            models.Index(fields=["post", "comment"], name="feed_feedfile_post_comment"),
            models.Index(
                fields=["uploaded_by", "uploaded_at"],
                condition=Q(post__isnull=True),
                name="feed_feedfile_unbound",
            ),
        ]


class FeedSettings(models.Model):
    retention_years = models.PositiveSmallIntegerField(default=3)
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey("core.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")

    class Meta:
        default_permissions = ()
        constraints = [
            models.CheckConstraint(
                condition=Q(retention_years__gte=1, retention_years__lte=10),
                name="feed_feedsettings_years_1_10",
            ),
        ]
