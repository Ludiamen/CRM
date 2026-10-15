"""Политика паролей, смена и восстановление (T-216, FR-026, FR-027, FR-029, FR-033, NFR-005).

Политика берётся из настроек безопасности при каждой проверке; изменение политики
прежние пароли задним числом не сбрасывает. Пароли хранятся только хешем argon2;
в журнал и письма пароли не попадают.
"""
from datetime import timedelta

from django.contrib.auth.hashers import check_password
from django.db import transaction
from django.utils import timezone

from apps.core import events
from apps.core.models import PasswordHistory
from apps.integrations.mail import services as mail

from . import audit, security_settings, sessions


class PolicyError(Exception):
    """Пароль не прошёл политику: `messages` — по одному на невыполненное требование."""

    def __init__(self, messages: list[str]):
        super().__init__(" ".join(messages))
        self.messages = messages


class BadCurrentPassword(Exception):
    """Текущий пароль при смене введён неверно."""


def policy_errors(user, password: str) -> list[str]:
    row = security_settings.get()
    errors = []
    if len(password or "") < row.password_min_length:
        errors.append(f"Пароль должен содержать не меньше {row.password_min_length} символов.")
    if password and user is not None and user.pk is not None:
        recent = list(PasswordHistory.objects.filter(user=user).order_by("-created_at", "-id")
                      .values_list("password_hash", flat=True)[:row.password_history])
        if user.password:
            recent.append(user.password)  # текущий пароль тоже входит в «последние»
        if any(check_password(password, encoded) for encoded in dict.fromkeys(recent)):
            errors.append(f"Пароль совпадает с одним из последних {row.password_history} паролей: придумайте новый.")
    return errors


def validate(user, password: str) -> None:
    errors = policy_errors(user, password)
    if errors:
        raise PolicyError(errors)


def _store(user, password: str) -> None:
    """Сохраняет новый пароль и запоминает хеш; хранятся последние `password_history` паролей."""
    row = security_settings.get()
    user.set_password(password)
    user.save(update_fields=["password"])
    PasswordHistory.objects.create(user=user, password_hash=user.password, created_at=timezone.now())
    stale = PasswordHistory.objects.filter(user=user).order_by("-created_at", "-id").values_list("pk", flat=True)[row.password_history:]
    PasswordHistory.objects.filter(pk__in=list(stale)).delete()


def set_initial_password(user, password: str) -> None:
    """Пароль при активации: по политике, без письма (человек только что его задал)."""
    with transaction.atomic():
        validate(user, password)
        _store(user, password)


def change_password(user, current_password: str, new_password: str, *, request, ip=None) -> None:
    """Смена пароля в «Безопасности» (FR-029, сценарий 16).

    Неверный текущий пароль считается неудачей, как неверный пароль при входе (FR-025);
    остальные сессии закрываются, текущая остаётся; на почту уходит письмо о смене.
    """
    from . import login

    if not user.check_password(current_password or ""):
        login.register_other_failure(user, ip=ip, step="change_password")
        raise BadCurrentPassword
    with transaction.atomic():
        validate(user, new_password)
        _store(user, new_password)
        sessions.close_all(user, except_key=request.session.session_key)
        sessions.keep_after_password_change(request, user)
        audit.record("password.changed", actor=user, object_type="user", object_id=user.pk,
                     after={"changed": True}, ip=ip)
        mail.send("password_changed", user.email, {"full_name": user.full_name}, related_user=user)
        events.publish("core.password_changed", user_id=user.pk, actor_id=user.pk)


def reset_password(user, new_password: str, *, link=None, ip=None) -> None:
    """Новый пароль после восстановления (FR-033): сессии закрываются, письмо о смене уходит.

    Второй фактор не отменяется: вход по-прежнему требует код.
    """
    from . import links

    with transaction.atomic():
        validate(user, new_password)
        _store(user, new_password)
        if link is not None:
            links.consume(link)
        closed = sessions.close_all(user)
        audit.record("password.changed", actor=user, object_type="user", object_id=user.pk,
                     after={"changed": True, "via": "reset"}, ip=ip)
        audit.record("sessions.closed", actor=user, object_type="user", object_id=user.pk,
                     after={"closed": closed}, ip=ip)
        mail.send("password_changed", user.email, {"full_name": user.full_name}, related_user=user)
        events.publish("core.password_changed", user_id=user.pk, actor_id=user.pk)


def changed_at(user):
    """Когда пароль задан в последний раз."""
    last = PasswordHistory.objects.filter(user=user).order_by("-created_at", "-id").values_list("created_at", flat=True).first()
    return last or user.activated_at or user.created_at


def must_change(user, row=None) -> bool:
    """Срок действия пароля истёк (только если он включён настройкой)."""
    row = row or security_settings.get()
    if row.password_max_age_days is None:
        return False
    return timezone.now() - changed_at(user) > timedelta(days=row.password_max_age_days)
