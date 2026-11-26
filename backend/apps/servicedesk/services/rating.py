"""Оценка заявителя по ссылке без входа (SPEC-012, FR-769…772; PLAN-012).

Контракт этапа 1: код Crockford base32, хеш, срок 7 дней, POST-проверка и состояние текущего цикла.
Реализация — T-12210…T-12212.
"""
import hashlib
import secrets

from datetime import timedelta

from django.db import IntegrityError, transaction
from django.utils import timezone

from ..models import SlaCycle, Ticket, TicketEntry, TicketRating

CODE_LENGTH = 12
CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
RATING_TTL_DAYS = 7
RATE_LIMIT = 5
RATE_WINDOW_SECONDS = 15 * 60
CACHE_PREFIX = "servicedesk:rating:"


def generate_code() -> str:
    """12 знаков Crockford base32 — не меньше 60 бит энтропии."""
    return "".join(secrets.choice(CODE_ALPHABET) for _ in range(CODE_LENGTH))


def normalize_code(value: str) -> str:
    """Код без пробелов и дефисов, заглавными; `O`/`I`/`L` → `0`/`1` (Crockford)."""
    text = "".join(ch for ch in (value or "").upper() if ch.isalnum())
    return text.replace("O", "0").replace("I", "1").replace("L", "1")


def hash_code(code: str) -> str:
    """SHA-256 от нормализованного кода: в базе нет исходного кода."""
    return hashlib.sha256(normalize_code(code).encode("ascii")).hexdigest()


def create_link(ticket, *, closed_at, now=None):
    """Создать ссылку оценки при ручном закрытии; `None`, если ответа исполнителя не было."""
    now = now or timezone.now()
    cycle = (SlaCycle.objects.filter(ticket=ticket, is_current=True).first())
    if cycle is not None:
        cycle_number = cycle.number
        started = cycle.cycle_started_at
        level_id, level_title = cycle.level_id, cycle.level_title
        has_reply = cycle.first_response_at is not None
    else:
        # Заявка без уровня SLA: оценивается тоже, цикл считаем по закрытиям и последнему открытию заново.
        last = (TicketRating.objects.filter(ticket=ticket).order_by("-cycle_number")
                .values_list("cycle_number", flat=True).first())
        cycle_number = (last or 0) + 1
        started = ticket.sla_cycle_started_at or ticket.created_at
        reopen = (TicketEntry.objects.filter(ticket=ticket, event="reopened")
                  .order_by("-at", "-id").first())
        if reopen is not None:
            started = reopen.at
        level_id, level_title = None, ""
        has_reply = False
    has_reply = has_reply or TicketEntry.objects.filter(
        ticket=ticket, kind=TicketEntry.Kind.REPLY, author__isnull=False,
        at__gte=started, at__lte=closed_at,
    ).exists()
    if not has_reply:
        return None
    expires_at = closed_at + timedelta(days=RATING_TTL_DAYS)
    values = {
        "ticket": ticket,
        "cycle_number": cycle_number,
        "closed_at_snapshot": closed_at,
        "expires_at": expires_at,
        "is_current": True,
        "queue_id": ticket.queue_id,
        "queue_name": getattr(ticket.queue, "name", ""),
        "category_id": ticket.category_id,
        "category_name": getattr(ticket.category, "name", ""),
        "assignee_id": ticket.assignee_id,
        "assignee_name": getattr(ticket.assignee, "full_name", ""),
        "level_id": level_id,
        "level_title": level_title,
        "created_at": now,
    }
    for _ in range(3):
        code = generate_code()
        values["token_hash"] = hash_code(code)
        try:
            with transaction.atomic():
                TicketRating.objects.filter(ticket=ticket, is_current=True).update(is_current=False)
                rating = TicketRating.objects.create(**values)
            rating.test_code = code
            return rating
        except IntegrityError:
            continue
    raise RuntimeError("не удалось создать ссылку оценки")


def verify_code(ticket_number: int, code: str):
    """Найти действующую ссылку по номеру и коду; `None` при ошибке, истечении или снятой оценке."""
    if not code:
        return None
    rating = (TicketRating.objects.filter(ticket__number=ticket_number, is_current=True,
                                          token_hash=hash_code(code)).first())
    if rating is None or is_expired(rating):
        return None
    return rating


def submit(rating, score: int, *, now=None):
    """Поставить или изменить оценку 1–5 до конца срока."""
    now = now or timezone.now()
    try:
        score = int(score)
    except (TypeError, ValueError):
        raise ValueError("оценка должна быть от 1 до 5")
    if score not in range(1, 6) or not rating.is_current or rating.expires_at <= now:
        raise ValueError("оценка недоступна")
    rating.score = score
    rating.rated_at = now
    rating.save(update_fields=["score", "rated_at", "updated_at"])
    return rating


def on_reopen(ticket) -> None:
    """Погасить текущую ссылку и снять оценку с отчёта; история остаётся."""
    TicketRating.objects.filter(ticket=ticket, is_current=True).update(is_current=False)


def is_expired(rating, *, now=None) -> bool:
    """Истёк ли срок ссылки."""
    return rating.expires_at <= (now or timezone.now())
