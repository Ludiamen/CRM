"""Права и видимость статей: единственное место решений (PLAN-005, «Права и видимость»; FR-405…FR-409).

Представления, службы записи и поставщики поиска зовут только эти функции. Права читает `permissions.has_permission`
(кэш прав ядра).
"""
from django.db.models import Q
from django.http import Http404

from apps.core.services import permissions

from ..models import Article


class ArticleGone(Exception):
    """Статья в корзине: страница отвечает 410, POST-действие — 200 с «Статья удалена» (не `KnowledgeError`)."""


def can_manage(user) -> bool:
    """Право «Управление базой знаний»."""
    return permissions.has_permission(user, "knowledge.manage")


def can_edit(user) -> bool:
    """Право «Редактирование» или «Управление» (управление включает редактирование)."""
    return permissions.has_permission(user, "knowledge.edit") or can_manage(user)


def visible_articles(user):
    """Статьи, которые видит сотрудник: опубликованные; свои черновики при `can_edit`; все черновики при `can_manage`.

    Статьи в корзине не входят ни у кого.
    """
    if can_manage(user):
        return Article.objects.exclude(state=Article.State.TRASH)
    condition = Q(state=Article.State.PUBLISHED)
    if can_edit(user):
        condition |= Q(state=Article.State.DRAFT, author_id=user.pk)
    return Article.objects.filter(condition)


def is_visible(user, article: Article) -> bool:
    """Видна ли статья из памяти (то же правило, что у `visible_articles`; корзина не видна)."""
    if article.state == Article.State.PUBLISHED:
        return True
    if article.state == Article.State.DRAFT:
        return can_manage(user) or (can_edit(user) and article.author_id == user.pk)
    return False


def get_for(user, article_id: int) -> Article:
    """Статья для показа: нет или не видна — `Http404`; в корзине — управляющему статья, остальным `ArticleGone`."""
    article = Article.objects.filter(pk=article_id).first()
    if article is None:
        raise Http404("Статьи нет")
    if article.state == Article.State.TRASH:
        if can_manage(user):
            return article
        raise ArticleGone
    if not is_visible(user, article):
        raise Http404("Статьи нет")
    return article


def can_change(user, article: Article) -> bool:
    """Править может: черновик — автор с правом редактирования или управляющий; опубликованную — любой с правом
    редактирования; статью в корзине — никто (возвращает её только «Вернуть»)."""
    if article.state == Article.State.PUBLISHED:
        return can_edit(user)
    if article.state == Article.State.DRAFT:
        return can_manage(user) or (can_edit(user) and article.author_id == user.pk)
    return False


def can_publish(user, article: Article) -> bool:
    """Признак показа кнопки «Опубликовать»: только черновик и тот, кто может его менять (службу не заменяет)."""
    return article.state == Article.State.DRAFT and can_change(user, article)
