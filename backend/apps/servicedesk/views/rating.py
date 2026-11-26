"""Открытая страница оценки заявителя (SPEC-012, FR-770; PLAN-012)."""
from django.core.cache import cache

from apps.core.services import audit
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from ..models import TicketRating
from ..services import rating

ERROR_TEXT = "Код не подходит или время оценки истекло"
LIMIT_TEXT = "Слишком много попыток. Попробуйте позже"
SESSION_KEY = "servicedesk_rating"


@require_http_methods(["GET", "POST"])
def rating_page(request):
    """`/rate/?ticket=N` — номер заявки, код принимается только POST."""
    try:
        number = int(request.GET.get("ticket") or request.POST.get("ticket") or 0)
    except (TypeError, ValueError):
        number = 0
    if request.method == "GET":
        return render(request, "servicedesk/rating/page.html", {"number": number})

    ip = request.META.get("REMOTE_ADDR") or getattr(request, "client_ip", "") or "unknown"
    key = f"{rating.CACHE_PREFIX}{ip}:{number}"
    attempts = cache.get(key, 0)
    if attempts >= rating.RATE_LIMIT:
        return _failure(request, LIMIT_TEXT, 429, number, "rating_rate_limited")

    code = request.POST.get("code", "")
    verified = rating.verify_code(number, code) if code else None
    if verified is None and not code:
        stored = request.session.get(SESSION_KEY, {})
        rating_id = stored.get("rating_id") if isinstance(stored, dict) else None
        verified = (TicketRating.objects.filter(pk=rating_id, ticket__number=number,
                                                 is_current=True).first() if rating_id else None)
        if verified is not None and rating.is_expired(verified):
            verified = None
    if verified is None:
        cache.set(key, attempts + 1, rating.RATE_WINDOW_SECONDS)
        return _failure(request, ERROR_TEXT, 400, number, "rating_code")

    score = request.POST.get("score")
    try:
        rating.submit(verified, score)
    except ValueError:
        return _failure(request, ERROR_TEXT, 400, number, "rating_code")
    request.session[SESSION_KEY] = {"rating_id": verified.pk, "expires": verified.expires_at.isoformat()}
    request.session.set_expiry(rating.RATE_WINDOW_SECONDS)
    audit.record("servicedesk.rating_received", actor=None, object_type="ticket",
                 object_id=str(verified.ticket.number),
                 after={"score": verified.score, "cycle": verified.cycle_number}, ip=ip)
    return render(request, "servicedesk/rating/page.html", {"number": number, "success": True})


def _failure(request, message, status, number, code):
    return render(
        request,
        "servicedesk/rating/page.html",
        {"number": number, "error": message, "error_code": code},
        status=status,
    )
