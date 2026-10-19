"""Модели базы знаний: Rubric, Tag, Article, ArticleVersion, ArticleFile, TicketLink, RubricSubscription, KnowledgeSettings (PLAN-005, «Модель данных»).

Внешние ключи на модели ядра заданы строками, с `related_name="+"`: обратных связей к ядру нет.
Номер заявки в `TicketLink` и `Article.from_ticket` — число без внешнего ключа (инвариант «модуль-приложение»).
"""
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone


def now():
    """Время по умолчанию берётся при каждом обращении (подмена времени в тестах)."""
    return timezone.now()


class Rubric(models.Model):
    """Рубрика: дерево до трёх уровней; «Общее» (`is_default`) создаёт миграция данных."""

    name = models.CharField("название", max_length=100)
    parent = models.ForeignKey("self", on_delete=models.PROTECT, null=True, blank=True, related_name="children")
    depth = models.PositiveSmallIntegerField("уровень")
    is_default = models.BooleanField("рубрика по умолчанию", default=False)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                Lower("name"), "parent", nulls_distinct=False, name="knowledge_rubric_parent_name_ci_uniq"),
            models.UniqueConstraint(
                fields=["is_default"], condition=Q(is_default=True), name="knowledge_rubric_single_default"),
            models.CheckConstraint(condition=Q(depth__gte=1, depth__lte=3), name="knowledge_rubric_depth_1_3"),
        ]


class Tag(models.Model):
    """Тег: название строчными, приводит служба."""

    name = models.CharField("название", max_length=40, unique=True)

    class Meta:
        default_permissions = ()


class Article(models.Model):
    """Статья: Markdown, готовый HTML, чистый текст для индекса и два вектора поиска."""

    class State(models.TextChoices):
        DRAFT = "draft", "черновик"
        PUBLISHED = "published", "опубликована"
        TRASH = "trash", "в корзине"

    title = models.CharField("заголовок", max_length=200)
    text = models.TextField("текст (Markdown)")
    html = models.TextField("готовый вывод")
    plain = models.TextField("чистый текст для индекса")
    rubric = models.ForeignKey(Rubric, on_delete=models.PROTECT)
    tags = models.ManyToManyField(Tag, blank=True)
    state = models.CharField("состояние", max_length=16, choices=State.choices, default=State.DRAFT)
    state_before_trash = models.CharField("состояние до корзины", max_length=16, blank=True)
    author = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField("создана", default=now)
    updated_by = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    updated_at = models.DateTimeField("последнее сохранение", default=now)
    version_no = models.PositiveIntegerField("номер текущей версии", default=1)
    published_at = models.DateTimeField("первая публикация", null=True, blank=True)
    deleted_at = models.DateTimeField("удалена в корзину", null=True, blank=True)
    deleted_by = models.ForeignKey("core.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    from_ticket = models.PositiveIntegerField("из решения заявки", null=True, blank=True)
    search_full = SearchVectorField(null=True, blank=True)
    search_head = SearchVectorField(null=True, blank=True)

    class Meta:
        default_permissions = ()
        indexes = [
            GinIndex(fields=["search_full"], name="knowledge_article_sfull_gin"),
            GinIndex(fields=["search_head"], name="knowledge_article_shead_gin"),
            models.Index(fields=["state", "-updated_at"], name="knowledge_article_state_upd"),
            models.Index(fields=["rubric", "state"], name="knowledge_article_rubric_st"),
            models.Index(fields=["author", "state"], name="knowledge_article_author_st"),
            models.Index(fields=["state", "deleted_at"], name="knowledge_article_state_del"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(state="trash", deleted_at__isnull=False)
                | (~Q(state="trash") & Q(deleted_at__isnull=True)),
                name="knowledge_article_trash_has_deleted_at"),
        ]


class ArticleVersion(models.Model):
    """Версия статьи: снимок на момент сохранения; номера не переиспользуются."""

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="versions")
    number = models.PositiveIntegerField("номер")
    author = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField("создана", default=now)
    comment = models.CharField("комментарий", max_length=200, blank=True)
    title = models.CharField("заголовок", max_length=200)
    text = models.TextField("текст")
    html = models.TextField("готовый вывод")
    rubric = models.ForeignKey(Rubric, on_delete=models.SET_NULL, null=True, related_name="+")
    rubric_name = models.CharField("название рубрики на момент сохранения", max_length=100)
    tags = models.JSONField("теги", default=list)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["article", "number"], name="knowledge_articleversion_article_number_uniq"),
        ]
        indexes = [models.Index(fields=["article", "-number"], name="knowledge_artversion_art_num")]


class ArticleFile(models.Model):
    """Вложение статьи: файл ядра и признаки картинки."""

    class ImageFormat(models.TextChoices):
        PNG = "png", "PNG"
        JPEG = "jpeg", "JPEG"
        GIF = "gif", "GIF"
        WEBP = "webp", "WebP"

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="files")
    file = models.OneToOneField("core.StoredFile", on_delete=models.PROTECT, related_name="+")
    name = models.CharField("имя при загрузке", max_length=255)
    image_format = models.CharField("формат картинки", max_length=8, choices=ImageFormat.choices, blank=True)
    uploaded_by = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField("загружен", default=now)

    class Meta:
        default_permissions = ()
        indexes = [models.Index(fields=["article", "uploaded_at"], name="knowledge_artfile_art_upl")]


class TicketLink(models.Model):
    """Связь статьи с заявкой по номеру (без внешнего ключа на `servicedesk`)."""

    article = models.ForeignKey(Article, on_delete=models.CASCADE, related_name="ticket_links")
    ticket_number = models.PositiveIntegerField("номер заявки")
    linked_by = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    linked_at = models.DateTimeField("привязана", default=now)
    from_resolution = models.BooleanField("из решения заявки", default=False)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["article", "ticket_number"], name="knowledge_ticketlink_article_ticket_uniq"),
        ]
        indexes = [models.Index(fields=["ticket_number"], name="knowledge_ticketlink_ticket")]


class RubricSubscription(models.Model):
    """Подписка сотрудника на рубрику."""

    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="+")
    rubric = models.ForeignKey(Rubric, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField("создана", default=now)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["user", "rubric"], name="knowledge_rubricsubscription_user_rubric_uniq"),
        ]


class KnowledgeSettings(models.Model):
    """Настройки базы знаний: одна строка, pk=1 (создаёт миграция данных); границы срока проверяет служба."""

    trash_days = models.PositiveSmallIntegerField("срок хранения корзины, дней", default=90)

    class Meta:
        default_permissions = ()
