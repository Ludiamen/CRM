"""Статьи и заявки: привязка и отвязка, «Статья из решения», подбор статьи, части карточки заявки (PLAN-005, «Связь с
заявками и карточка заявки»; CONTRACT-005, 4.3, 10.5, 11.8).

Представления тонкие: проверки делает `services.links`. Отказ службы на POST — 200 с сообщением (не 4xx), нет права —
403, нет статьи или заявки (или заявка не видна) — 404. Части карточки возвращают фрагмент без оболочки: оболочку
`<div data-card-part data-part-kind>` рисует сервис-деск; ответ НХ на привязку и отвязку собирает её сам, тем же
текстом, чтобы `hx-swap="outerHTML"` подменял часть целиком.
"""
import re

from django.contrib.auth.decorators import login_required
from django.contrib.postgres.search import SearchQuery, SearchRank
from django.db.models import F
from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_GET, require_POST

from apps.core.extensions import TicketCardPart
from apps.core.views.common import flash, is_fragment, render_page

from ..models import Article, TicketLink
from ..services import ArticleError, access, links

ORDER = 10
PICK_LIMIT = 10
MAX_QUERY = 200
MAX_WORDS = 8
MAX_NUMBER = 2_147_483_647
WORD = re.compile(r"\w+")
CONFIG = "russian"

ALREADY_CREATED = "Черновик по этой заявке уже создан"
REFUSALS = {"not_closed_with_resolution": "Заявка не закрыта с решением"}


def _require_edit(user) -> None:
    """Право «Редактирование» проверяется первым, до разбора полей (раздел 17 п. 60)."""
    if not access.can_edit(user):
        raise PermissionDenied


def _number(value) -> int:
    """Целое положительное из поля формы; иное — `Http404` (такой статьи или заявки нет)."""
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise Http404("Нет такого номера") from None
    if not 0 < number <= MAX_NUMBER:
        raise Http404("Нет такого номера")
    return number


def _wrap(key: str, kind: str, html: str):
    """Оболочка части — как у сервис-деска (`_card_parts`)."""
    return format_html('<div data-card-part="{}" data-part-kind="{}">{}</div>', key, kind, mark_safe(html))


def _fragment(request, html) -> HttpResponse:
    response = HttpResponse(html)
    response["Vary"] = "HX-Request"
    return response


# --- части карточки заявки ---------------------------------------------------------------------------------

def _section_context(request, number: int) -> dict:
    user = request.user
    rows = (TicketLink.objects.filter(ticket_number=number, article__in=access.visible_articles(user))
            .select_related("article", "linked_by").order_by("linked_at", "id"))
    return {"ticket_number": number, "rows": list(rows), "can_edit": access.can_edit(user)}


def render_section(request, ref) -> str | None:
    """Раздел «Статьи»: без права «Редактирование» и без видимых связей — части нет."""
    context = _section_context(request, ref.number)
    if not context["can_edit"] and not context["rows"]:
        return None
    return render_to_string("knowledge/_card_articles.html", context, request=request)


def render_from_ticket(request, ref) -> str | None:
    """Кнопка «Статья из решения»: закрытая заявка с решением и право «Редактирование»."""
    if not (ref.closed and ref.has_resolution and access.can_edit(request.user)):
        return None
    return render_to_string("knowledge/_card_from_ticket.html", {"ticket_number": ref.number}, request=request)


def render_link_tool(request, ref) -> str | None:
    """Инструмент «Ссылка на статью» под полем внутреннего комментария — всем, кто видит заявку."""
    return render_to_string("knowledge/_card_link_tool.html", {}, request=request)


def ticket_card_parts() -> list[TicketCardPart]:
    """Запись точки `ticket_card_parts`: раздел, кнопка закрытой заявки и инструмент комментария."""
    return [
        TicketCardPart(key="kb-articles", kind="section", order=ORDER, render=render_section),
        TicketCardPart(key="kb-from-ticket", kind="closed_action", order=ORDER, render=render_from_ticket),
        TicketCardPart(key="kb-link-tool", kind="comment_tool", order=ORDER, render=render_link_tool),
    ]


# --- привязка и отвязка ------------------------------------------------------------------------------------

def _section_response(request, number: int) -> HttpResponse:
    """Ответ НХ на привязку и отвязку: раздел «Статьи» в оболочке; обычный запрос — переход на карточку."""
    if not is_fragment(request):
        return redirect(f"/tickets/{number}/")
    html = render_to_string("knowledge/_card_articles.html", _section_context(request, number), request=request)
    return _fragment(request, _wrap("kb-articles", "section", html))


@login_required
@require_POST
def link_add(request):
    """POST `/kb/links/` (`article`, `ticket`): привязать опубликованную статью к видимой заявке."""
    _require_edit(request.user)
    article_id, number = _number(request.POST.get("article")), _number(request.POST.get("ticket"))
    links.link(request.user, article_id, number)
    return _section_response(request, number)


@login_required
@require_POST
def link_delete(request, link_id):
    """POST `/kb/links/<id>/delete/`: отвязать статью от заявки."""
    _require_edit(request.user)
    number = TicketLink.objects.filter(pk=link_id).values_list("ticket_number", flat=True).first()
    links.unlink(request.user, link_id)
    return _section_response(request, number)


# --- «Статья из решения» -----------------------------------------------------------------------------------

@login_required
@require_POST
def from_ticket(request, number):
    """POST `/kb/from-ticket/<N>/`: черновик из решения закрытой заявки и переход в редактор; повторное нажатие
    открывает прежний черновик с сообщением."""
    try:
        result = links.from_ticket(request.user, number)
    except ArticleError as refusal:
        context = {"code": refusal.code, "message": REFUSALS.get(refusal.code, refusal.code)}
        if is_fragment(request):
            html = render_to_string("knowledge/_from_ticket_refused.html", context, request=request)
            return _fragment(request, _wrap("kb-from-ticket", "closed_action", html))
        return render_page(request, "knowledge/from_ticket_page.html", context)
    if not result.created:
        flash(request, ALREADY_CREATED)
    target = f"/kb/{result.article.pk}/edit/"
    if is_fragment(request):
        response = HttpResponse(status=200)
        response["HX-Redirect"] = target
        return response
    return redirect(target)


# --- подбор статьи -----------------------------------------------------------------------------------------

def _raw_query(text: str) -> str:
    """Строка `to_tsquery` по правилам разбора поиска: слова `\\w+` строчными, не короче 2 знаков, первые 8."""
    words = [w for w in WORD.findall(text.lower()) if len(w) >= 2][:MAX_WORDS]
    return " & ".join(f"{w}:*" for w in words)


def pick_articles(text: str) -> list[Article]:
    """До 10 опубликованных статей, у которых все слова запроса есть в заголовке и тегах (малый вектор поиска
    группы «Статьи»); запрос уходит в базу параметром."""
    text = text.strip()
    if len(text) < 2 or len(text) > MAX_QUERY:
        return []
    raw = _raw_query(text)
    if not raw:
        return []
    query = SearchQuery(raw, config=CONFIG, search_type="raw")
    return list(Article.objects.filter(state=Article.State.PUBLISHED, search_head__isnull=False, search_head=query)
                .annotate(rank=SearchRank(F("search_head"), query, cover_density=True))
                .order_by("-rank", "-updated_at", "-id")[:PICK_LIMIT])


@login_required
@require_GET
def pick(request):
    """GET `/kb/pick/?q=&ticket=`: подсказка статей; с `ticket` — строки с кнопкой привязки, без — для вставки ссылки.
    Права не нужны, запрос не сохраняется."""
    ticket = request.GET.get("ticket", "").strip()
    context = {
        "articles": [{"pk": a.pk, "title": a.title, "url": request.build_absolute_uri(f"/kb/{a.pk}/")}
                     for a in pick_articles(request.GET.get("q", ""))],
        "ticket": int(ticket) if ticket.isdigit() and 0 < int(ticket) <= MAX_NUMBER else None,
    }
    response = render(request, "knowledge/_pick_results.html", context)
    response["Vary"] = "HX-Request"
    return response
