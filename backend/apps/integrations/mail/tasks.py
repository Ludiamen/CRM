"""Задание RQ «отправить письмо» (T-230, FR-044, FR-052…055, NFR-003).

Работает в рабочем процессе (`rq worker --with-scheduler … mail`). Каждая попытка
пишет `MailAttempt`; ошибка поднимается дальше, и RQ ставит повтор по плану.
После последней неудачи обработчик `on_failure` ставит статус `failed`. Смена
статуса письма пишется в журнал событий (`mail.status_changed`).
"""
import os
from datetime import datetime

import django
from django.apps import apps as _apps

if not _apps.ready:  # рабочий процесс rq сам Django не поднимает
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    django.setup()

from django.conf import settings  # noqa: E402
from django.core.mail import EmailMessage, get_connection  # noqa: E402
from django.db import close_old_connections, connection  # noqa: E402
from django.template.loader import render_to_string  # noqa: E402
from django.utils import timezone  # noqa: E402

from .models import MailAttempt, MailMessage, MailStatus  # noqa: E402

# Письма уходят только по SMTP из окружения; настройка EMAIL_BACKEND (в тестах Django подменяет её на
# память процесса) здесь не читается, иначе письмо «отправлялось» бы никуда.
SMTP_BACKEND = "django.core.mail.backends.smtp.EmailBackend"
MAX_ERROR_LENGTH = 500
TEMPLATE_HEADER = "X-Portal-Template"
LINK_PURPOSE = {"invitation": "activation", "password_reset": "reset"}
TIME_KEYS = ("at", "expires_at")


class LinkGone(Exception):
    """Ссылка для письма уже недействительна: отправлять нечего, повторять незачем."""


def _fresh_connection() -> None:
    """В долгом рабочем процессе соединение с базой могло протухнуть (в транзакции теста не трогаем)."""
    if not connection.in_atomic_block:
        close_old_connections()


def safe_error(exc: BaseException) -> str:
    """Текст ошибки для журнала доставки: без секретов, не длиннее 500 знаков."""
    text = f"{type(exc).__name__}: {exc}"
    for secret in (settings.EMAIL_HOST_PASSWORD,):
        if secret:
            text = text.replace(secret, "***")
    return text[:MAX_ERROR_LENGTH]


def _record_status(message: MailMessage, old: str, new: str) -> None:
    from apps.core.services import audit

    audit.record("mail.status_changed", object_type="mail", object_id=message.pk,
                 before={"status": old}, after={"status": new, "attempts": message.attempts})


def build_context(message: MailMessage, public: dict) -> dict:
    """Контекст письма: данные из задания плюс то, что берётся из базы (название портала, ссылка)."""
    from apps.core.services import crypto, links, portal_settings

    context = dict(public)
    for key in TIME_KEYS:
        if isinstance(context.get(key), str):
            context[key] = datetime.fromisoformat(context[key])
    context["portal_name"] = portal_settings.get().name
    context["portal_url"] = settings.PORTAL_URL
    purpose = LINK_PURPOSE.get(message.template)
    if purpose:
        link = links.current_link(message.related_user, purpose) if message.related_user_id else None
        if link is None or not link.code_encrypted:
            raise LinkGone
        context["link"] = links.url_for(purpose, crypto.decrypt(link.code_encrypted).decode())
        context["expires_at"] = link.expires_at
    return context


def deliver_message(message_id: int) -> None:
    """Одна попытка доставки письма `message_id`."""
    from rq import get_current_job

    _fresh_connection()
    message = MailMessage.objects.select_related("related_user").filter(pk=message_id).first()
    if message is None or message.status != MailStatus.QUEUED:
        return
    job = get_current_job()
    public = (job.meta.get("context") if job is not None else None) or {}
    try:
        context = build_context(message, public)
        body = render_to_string(f"mail/{message.template}.txt", context)
        EmailMessage(
            subject=message.subject, body=body, from_email=settings.DEFAULT_FROM_EMAIL, to=[message.to],
            headers={TEMPLATE_HEADER: message.template}, connection=get_connection(SMTP_BACKEND),
        ).send(fail_silently=False)
    except LinkGone:
        _finish(message, ok=False, error="Ссылка в письме уже недействительна: письмо не отправлено.",
                final=MailStatus.FAILED)
        return
    except Exception as exc:  # noqa: BLE001 — любая ошибка обмена: записать попытку и дать RQ повторить
        _finish(message, ok=False, error=safe_error(exc))
        raise
    _finish(message, ok=True, final=MailStatus.SENT)


def _finish(message: MailMessage, *, ok: bool, error: str = "", final: str | None = None) -> None:
    """Записывает попытку; при `final` меняет статус письма и пишет событие."""
    now = timezone.now()
    MailAttempt.objects.create(message=message, at=now, ok=ok, error=error)
    message.attempts += 1
    message.last_error = error
    fields = ["attempts", "last_error"]
    old = message.status
    if final and final != old:
        message.status = final
        fields.append("status")
        if final == MailStatus.SENT:
            message.sent_at = now
            fields.append("sent_at")
    message.save(update_fields=fields)
    if final and final != old:
        _record_status(message, old, final)


def on_failure(job, connection_, exc_type, exc_value, traceback) -> None:
    """Обработчик RQ: вызывается после каждой неудачи, а `failed` ставит только после последней."""
    if job.retries_left:  # впереди ещё повторы
        return
    _fresh_connection()
    message = MailMessage.objects.filter(pk=job.args[0]).first()
    if message is None or message.status != MailStatus.QUEUED:
        return
    old = message.status
    message.status = MailStatus.FAILED
    message.save(update_fields=["status"])
    _record_status(message, old, MailStatus.FAILED)
