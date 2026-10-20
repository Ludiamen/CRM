"""Связь статей с заявками (PLAN-005, «Связь с заявками и карточка заявки»; FR-427, FR-429, FR-432; CONTRACT-005, 5.6).

Сервис-деск вызывается только через `apps.servicedesk.services.public` и только если приложение установлено
(`apps.is_installed("apps.servicedesk")`); без него связей и справок нет. Привязка и отвязка в журнал не пишутся
(FR-438): связь хранит «кто и когда» сама. «Статья из решения» идёт одной транзакцией под замком
`knowledge.from_ticket:<номер>:<сотрудник>`.
"""
from typing import NamedTuple

from django.apps import apps
from django.core.exceptions import PermissionDenied
from django.db import connection, transaction
from django.http import Http404

from ..models import Article, Rubric, TicketLink
from . import ArticleError, access, articles, pdn

MAX_NUMBER = 2_147_483_647
FROM_TICKET_LOCK = "knowledge.from_ticket:{number}:{user_id}"


class FromTicketResult(NamedTuple):
    """Итог «Статьи из решения»: черновик и признак «создан сейчас» (`False` — открыт прежний)."""

    article: Article
    created: bool


class TicketLinkView(NamedTuple):
    """Связь вместе со справкой о заявке (`TicketBrief`) — для страницы статьи."""

    link: TicketLink
    brief: object


def _public():
    """Публичная служба сервис-деска или `None`, если приложение не установлено."""
    if not apps.is_installed("apps.servicedesk"):
        return None
    from apps.servicedesk.services import public
    return public


def _brief(user, number: int):
    """Справка о заявке, которую видит `user`; нет службы, нет заявки или она не видна — `Http404`."""
    public = _public()
    brief = public.ticket_brief(user, number) if public is not None else None
    if brief is None:
        raise Http404("Заявки нет")
    return brief


def _require_edit(user) -> None:
    if not access.can_edit(user):
        raise PermissionDenied


def link(user, article_id: int, ticket_number: int) -> TicketLink:
    """Привязывает опубликованную статью к видимой заявке; повтор возвращает существующую связь."""
    _require_edit(user)
    article = Article.objects.filter(pk=article_id, state=Article.State.PUBLISHED).first()
    if article is None:
        raise Http404("Статьи нет")
    _brief(user, ticket_number)
    with transaction.atomic():
        row, _created = TicketLink.objects.get_or_create(
            article=article, ticket_number=ticket_number, defaults={"linked_by": user})
    return row


def unlink(user, link_id: int) -> None:
    """Снимает связь; заявку смотрящий обязан видеть; связи нет — `Http404`."""
    _require_edit(user)
    row = TicketLink.objects.filter(pk=link_id).first()
    if row is None:
        raise Http404("Связи нет")
    _brief(user, row.ticket_number)
    row.delete()


def from_ticket(user, number: int) -> FromTicketResult:
    """Черновик статьи из решения закрытой заявки (FR-427, FR-428).

    Тема и решение проходят маску ПДн; данных заявителя, адресов и переписки в `TicketBrief` нет. Если у сотрудника уже
    есть черновик из этой заявки, он и возвращается (`created=False`).
    """
    _require_edit(user)
    if not 0 < number <= MAX_NUMBER:
        raise Http404("Заявки нет")
    with transaction.atomic():
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                           [FROM_TICKET_LOCK.format(number=number, user_id=user.pk)])
        brief = _brief(user, number)  # справка снята под замком: решение не устареет
        if not brief.closed_with_resolution:
            raise ArticleError("not_closed_with_resolution")
        existing = (Article.objects.filter(
            from_ticket=number, author=user, state=Article.State.DRAFT,
            ticket_links__ticket_number=number, ticket_links__from_resolution=True)
            .order_by("id").first())
        if existing is not None:
            return FromTicketResult(existing, False)
        rubric = Rubric.objects.filter(is_default=True).first()
        form = articles.ArticleForm(title=pdn.mask_plain(brief.subject)[:200],
                                    text=pdn.mask_resolution(brief.resolution),
                                    rubric_id=rubric.pk if rubric else None, tags="",
                                    comment=f"Создано из заявки #{number}")
        article = articles.create(user, form, from_ticket=number)
        TicketLink.objects.create(article=article, ticket_number=number, linked_by=user, from_resolution=True)
    return FromTicketResult(article, True)


def tickets_for(user, article: Article) -> list[TicketLinkView]:
    """Заявки, связанные со статьёй и видимые `user`, в порядке привязки; статья в корзине и модуль без
    сервис-деска дают пустой список."""
    public = _public()
    if public is None or article.state == Article.State.TRASH:
        return []
    rows = list(TicketLink.objects.filter(article=article).order_by("linked_at", "id"))
    briefs = public.briefs(user, [row.ticket_number for row in rows])
    return [TicketLinkView(row, briefs[row.ticket_number]) for row in rows if row.ticket_number in briefs]
