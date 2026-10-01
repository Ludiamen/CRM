"""Одноразовые ссылки активации и восстановления (T-213, FR-008…012, FR-031…033).

Код — 256 случайных бит. В базе: SHA-256 (поиск) и Fernet (показ администратору и
отправка). В адресе письма код стоит во фрагменте (`#…`), на сервер он приходит
только телом POST-запроса. Неверная, просроченная, использованная и погашенная
ссылки неотличимы: обмен возвращает просто None.
"""
from datetime import timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from apps.core.models import LinkPurpose, OneTimeLink, UserState
from apps.integrations.mail import services as mail

from . import audit, crypto, valkey

LIFETIME = {LinkPurpose.ACTIVATION: timedelta(hours=72), LinkPurpose.RESET: timedelta(hours=1)}
PATHS = {LinkPurpose.ACTIVATION: "/activate/", LinkPurpose.RESET: "/password/reset/"}
# Запросы восстановления: не больше 3 писем в час на адрес и 10 в час с одного IP
RESET_PER_EMAIL_PER_HOUR = 3
RESET_PER_IP_PER_HOUR = 10


def url_for(purpose: str, code: str) -> str:
    """Адрес из письма: код во фрагменте."""
    return f"{settings.PORTAL_URL}{PATHS[purpose]}#{code}"


def _live(qs):
    return qs.filter(used_at__isnull=True, revoked_at__isnull=True, expires_at__gt=timezone.now())


def revoke(user, purpose: str | None = None) -> int:
    """Гасит действующие ссылки (код стирается). Блокировка записи гасит обе."""
    qs = OneTimeLink.objects.filter(user=user, used_at__isnull=True, revoked_at__isnull=True)
    if purpose:
        qs = qs.filter(purpose=purpose)
    return qs.update(revoked_at=timezone.now(), code_encrypted="")


def issue(user, purpose: str, *, created_by=None) -> tuple[OneTimeLink, str]:
    """Новая ссылка; прежняя той же цели гаснет. Возвращает (ссылка, открытый код)."""
    with transaction.atomic():
        revoke(user, purpose)
        code = crypto.new_link_code()
        link = OneTimeLink.objects.create(
            user=user, purpose=purpose, token_hash=crypto.link_token_hash(code),
            code_encrypted=crypto.encrypt(code), expires_at=timezone.now() + LIFETIME[purpose],
            created_by=created_by,
        )
    return link, code


def exchange(code: str, purpose: str) -> OneTimeLink | None:
    """Находит действующую ссылку по коду из тела запроса; иначе None (причина не раскрывается)."""
    code = (code or "").strip()
    if not code:
        return None
    link = OneTimeLink.objects.select_related("user").filter(
        token_hash=crypto.link_token_hash(code), purpose=purpose).first()
    if link is None or link.used_at or link.revoked_at or link.expires_at <= timezone.now():
        return None
    wanted = UserState.INVITED if purpose == LinkPurpose.ACTIVATION else UserState.ACTIVE
    if link.user.state != wanted:
        return None
    return link


def get_live(link_id) -> OneTimeLink | None:
    """Ссылка по номеру из сессии мастера: жива ли она ещё."""
    return _live(OneTimeLink.objects.select_related("user").filter(pk=link_id)).first()


def consume(link: OneTimeLink) -> None:
    """Ссылка использована: код стирается."""
    OneTimeLink.objects.filter(pk=link.pk).update(used_at=timezone.now(), code_encrypted="")


def current_activation_link(user) -> OneTimeLink | None:
    return _live(OneTimeLink.objects.filter(user=user, purpose=LinkPurpose.ACTIVATION)).order_by("-id").first()


def reveal(link: OneTimeLink, *, actor, ip=None) -> str | None:
    """Показ ссылки активации администратору: расшифровка пишется в журнал (кода в журнале нет)."""
    link = _live(OneTimeLink.objects.filter(pk=link.pk)).first()
    if link is None or not link.code_encrypted:
        return None
    code = crypto.decrypt(link.code_encrypted).decode()
    audit.record("link.revealed", actor=actor, object_type="link", object_id=link.pk, ip=ip)
    return code


def invitation_url(code: str) -> str:
    return url_for(LinkPurpose.ACTIVATION, code)


def send_invitation(user, *, created_by=None, ip=None) -> OneTimeLink:
    """Выпускает ссылку активации, ставит письмо-приглашение и пишет событие (FR-008, FR-010)."""
    link, code = issue(user, LinkPurpose.ACTIVATION, created_by=created_by)
    mail.send("invitation", user.email, {"link": invitation_url(code), "full_name": user.full_name,
                                         "expires_at": link.expires_at}, related_user=user)
    audit.record("invitation.sent", actor=created_by, object_type="user", object_id=user.pk,
                 after={"expires_at": link.expires_at.isoformat()}, ip=ip)
    return link


def _reset_allowed(email_hash: str, ip: str) -> bool:
    """Считает запрос восстановления; False, если предел часа превышен (ответ при этом прежний)."""
    conn = valkey.conn()
    allowed = True
    for key, limit in ((f"forgot:email:{email_hash}", RESET_PER_EMAIL_PER_HOUR), (f"forgot:ip:{ip}", RESET_PER_IP_PER_HOUR)):
        count = conn.incr(key)
        if count == 1:
            conn.expire(key, 3600)
        if count > limit:
            allowed = False
    return allowed


def request_password_reset(email: str, *, ip: str) -> None:
    """Запрос «Забыли пароль?»: письмо только активной записи; ответ вызывающего всегда один и тот же."""
    from apps.core.models import User

    email = (email or "").strip()
    if not email or not _reset_allowed(crypto.keyed_hash(email), ip or ""):
        return
    user = User.objects.filter(email__iexact=email).first()
    audit.record("password.reset_requested", object_type="user", object_id=user.pk if user else "", ip=ip)
    if user is None or user.state != UserState.ACTIVE:
        return
    link, code = issue(user, LinkPurpose.RESET)
    mail.send("password_reset", user.email, {"link": url_for(LinkPurpose.RESET, code), "full_name": user.full_name,
                                             "expires_at": link.expires_at}, related_user=user)
