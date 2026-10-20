"""Виды уведомлений базы знаний (PLAN-005, «Уведомления базы знаний»; CONTRACT-005, § 7.2, § 17 п. 51).

Каждый вид сам решает, кому и о чём уведомлять (FR-434, FR-435). Данные события несут только идентификаторы:
заголовок, рубрика и имя читаются из базы. Статья в момент события опубликована, её видят все, поэтому право
получателя не проверяется; уволенных отбрасывает `notify` (`RECIPIENT_STATES`). Все три вида склеиваются (`coalesce`).
"""
import re

from django.contrib.auth import get_user_model

from apps.core.extensions import Draft, NotificationKind
from apps.core.services import permissions

from .models import Article, Rubric, RubricSubscription

COMMENT_ON_MY_ARTICLE = "knowledge.comment_on_my_article"
MY_ARTICLE_CHANGED = "knowledge.my_article_changed"
RUBRIC_SUBSCRIPTION = "knowledge.rubric_subscription"

TEXT_LIMIT = 100
OBJECT_PREFIX = "knowledge.article:"
_REF = re.compile(r"knowledge\.article:([0-9]{1,18})")
MODULE = "База знаний"
CHANNELS = ("portal", "email")


def _cut(text: str) -> str:
    """Часть текста уведомления: больше 100 знаков (по символам) — первые 99 и «…»."""
    text = text or ""
    return text if len(text) <= TEXT_LIMIT else text[:TEXT_LIMIT - 1] + "…"


def _article(data: dict):
    """Опубликованная статья из данных события; нет статьи или она не опубликована — `None`."""
    article_id = data.get("article_id")
    if article_id is None:
        return None
    return Article.objects.filter(pk=article_id, state=Article.State.PUBLISHED).first()


def _draft(user_id: int, article, text: str, *, anchor: str = "") -> Draft:
    return Draft(user_id=user_id, text=text, url=f"/kb/{article.pk}/{anchor}", object_ref=f"{OBJECT_PREFIX}{article.pk}")


def _comment_on_my_article(event: str, data: dict) -> list[Draft]:
    if event != "knowledge.comment_added":
        return []
    article = _article(data)
    if article is None or article.author_id == data.get("actor_id"):
        return []
    text = f"Новый комментарий к вашей статье «{_cut(article.title)}»"
    return [_draft(article.author_id, article, text, anchor="#comments")]


def _my_article_changed(event: str, data: dict) -> list[Draft]:
    if event != "knowledge.article_changed":
        return []
    article = _article(data)
    actor_id = data.get("actor_id")
    if article is None or article.author_id == actor_id:
        return []
    actor = get_user_model().objects.filter(pk=actor_id).first()
    name = _cut(actor.full_name) if actor is not None else ""
    text = f"Вашу статью «{_cut(article.title)}» изменил {name}"
    return [_draft(article.author_id, article, text)]


def _rubric_subscription(event: str, data: dict) -> list[Draft]:
    if event not in ("knowledge.article_published", "knowledge.article_changed"):
        return []
    article = _article(data)
    if article is None:
        return []
    chain, rubric = [], Rubric.objects.filter(pk=article.rubric_id).first()
    while rubric is not None:
        chain.append(rubric)
        rubric = Rubric.objects.filter(pk=rubric.parent_id).first() if rubric.parent_id else None
    by_id = {rubric.pk: rubric for rubric in chain}
    skip = {data.get("actor_id")}
    if event == "knowledge.article_changed":
        skip.add(article.author_id)
    # Ближайшая к статье подписка получателя — самая глубокая рубрика цепочки (раздел 17 п. 51).
    nearest: dict[int, Rubric] = {}
    for user_id, rubric_id in RubricSubscription.objects.filter(rubric_id__in=by_id).values_list("user_id", "rubric_id"):
        if user_id in skip:
            continue
        rubric = by_id[rubric_id]
        if user_id not in nearest or rubric.depth > nearest[user_id].depth:
            nearest[user_id] = rubric
    title = _cut(article.title)
    return [_draft(user_id, article, f"Статья в рубрике «{_cut(nearest[user_id].name)}»: {title}")
            for user_id in sorted(nearest)]


def _is_author(user) -> bool:
    return Article.objects.filter(author_id=user.pk).exists()


def _author_kind_available(user) -> bool:
    """Строка «моя статья»: есть `knowledge.edit` или `knowledge.manage` либо автор хотя бы одной статьи."""
    return (permissions.has_permission(user, "knowledge.edit") or permissions.has_permission(user, "knowledge.manage")
            or _is_author(user))


def _subscription_available(user) -> bool:
    return True


def _still_relevant(user_id: int, object_ref: str) -> bool:
    """Статья существует и опубликована, получатель не уволен."""
    match = _REF.fullmatch(object_ref or "")
    if match is None:
        return False
    user = get_user_model().objects.filter(pk=user_id).first()
    if user is None or user.state == "dismissed":
        return False
    return Article.objects.filter(pk=int(match.group(1)), state=Article.State.PUBLISHED).exists()


def notification_kinds() -> list[NotificationKind]:
    """Функция точки `notification_kinds`: три вида базы знаний, свежие объекты при каждом вызове."""
    return [
        NotificationKind(
            code=COMMENT_ON_MY_ARTICLE, title="Новый комментарий к моей статье", module=MODULE,
            events=("knowledge.comment_added",), build=_comment_on_my_article,
            external_text="Новый комментарий к вашей статье", default_channels=CHANNELS,
            available=_author_kind_available, still_relevant=_still_relevant, order=50, coalesce=True),
        NotificationKind(
            code=MY_ARTICLE_CHANGED, title="Мою статью изменили", module=MODULE,
            events=("knowledge.article_changed",), build=_my_article_changed,
            external_text="Вашу статью изменили", default_channels=CHANNELS,
            available=_author_kind_available, still_relevant=_still_relevant, order=51, coalesce=True),
        NotificationKind(
            code=RUBRIC_SUBSCRIPTION, title="Статья в рубрике по подписке", module=MODULE,
            events=("knowledge.article_published", "knowledge.article_changed"), build=_rubric_subscription,
            external_text="Новая статья в рубрике по подписке", default_channels=CHANNELS,
            available=_subscription_available, still_relevant=_still_relevant, order=52, coalesce=True),
    ]
