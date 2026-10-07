"""Публичный интерфейс модуля почты (T-230, PLAN-001, «Исходящая почта», ADR-0005).

`send(template, to, context, *, related_user=None)`:
1. создаёт `MailMessage(status="queued")`; тема письма сохраняется, тело — нет;
2. после фиксации транзакции (очередь django-rq в режиме `on_db_commit`) ставит задание RQ в очередь `mail`:
   в задание уходит единственный позиционный аргумент — номер письма. Коды ссылок
   в очередь и в Valkey не попадают: ссылку активации или восстановления задание
   само достаёт из базы (расшифровывает `OneTimeLink.code_encrypted`).
   Остальное содержимое (имя, время, браузер…) едет в `job.meta` без секретов.
3. повторы — `Retry(max=11, interval=[60, 300, 900, 3600] + [10800] * 7)`:
   1, 5, 15, 60 минут, затем семь раз по 3 часа (≈ 22 ч 20 мин). Паузы работают
   только при запуске рабочего процесса с планировщиком.

Сам обмен с SMTP — в `tasks.py`.
"""
from datetime import date, datetime, timedelta

from apps.core import extensions

from .models import MailAttempt, MailMessage, MailStatus

QUEUE = "mail"
RETRY_MAX = 11
RETRY_INTERVALS = [60, 300, 900, 3600] + [10800] * 7
# пока задание не выполнено, его служебные данные нужны не дольше суток после последней попытки
FAILED_JOB_TTL = 7 * 24 * 3600
FINISHED_JOB_TTL = 60

# Шесть писем среза и их темы (в теме — название портала из настроек)
SUBJECTS = dict([
    ("invitation", "Приглашение в портал «{name}»"),
    ("password_reset", "Восстановление пароля в портале «{name}»"),
    ("account_locked", "Вход в портал «{name}» временно заблокирован"),
    ("new_device", "Вход в портал «{name}» с нового устройства"),
    ("second_factor_reset", "Второй фактор входа в портал «{name}» сброшен"),
    ("password_changed", "Пароль в портале «{name}» изменён"),
])
# Значение адреса получателя и вложений у обезличенного письма (то же слово у `servicedesk`: `ANONYMIZED`)
ANONYMIZED = "обезличено"
# Ключи контекста, которые в очередь не попадают никогда (их задание берёт из базы)
SECRET_CONTEXT = frozenset({"link", "code", "password", "token"})


def _portable(value):
    """Значение контекста в виде, который переживёт очередь (JSON)."""
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, timedelta):
        return value.total_seconds()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def public_context(context: dict) -> dict:
    """Контекст без секретов и в переносимом виде."""
    return {key: _portable(value) for key, value in (context or {}).items() if key not in SECRET_CONTEXT}


def render_subject(template: str) -> str:
    from apps.core.services import portal_settings

    return SUBJECTS[template].format(name=portal_settings.get().name)


def enqueue(message_id: int, meta: dict):
    """Ставит задание в очередь `mail` (после фиксации транзакции): первая попытка сразу, дальше — по плану повторов."""
    import django_rq
    from rq import Callback, Retry

    from . import tasks

    # режим on_db_commit: задание попадает в очередь только после фиксации транзакции вызывающего
    queue = django_rq.get_queue(QUEUE, commit_mode="on_db_commit")
    return queue.enqueue(
        tasks.deliver_message, message_id,
        retry=Retry(max=RETRY_MAX, interval=RETRY_INTERVALS),
        on_failure=Callback(tasks.on_failure),
        meta=meta, failure_ttl=FAILED_JOB_TTL, result_ttl=FINISHED_JOB_TTL,
    )


def send(template: str, to: str, context: dict, *, related_user=None) -> MailMessage:
    """Ставит письмо в очередь; возвращает `MailMessage` (статус `queued`)."""
    if template not in SUBJECTS:
        raise ValueError(f"неизвестный шаблон письма: {template}")
    message = MailMessage.objects.create(
        to=to, template=template, subject=render_subject(template), status=MailStatus.QUEUED,
        related_user=related_user)
    enqueue(message.pk, {"context": public_context(context)})
    return message


def renderer_for(template: str):
    """Рендерер письма приложения по префиксу шаблона или `None` (прежние шесть писем среза)."""
    for func in extensions.registered("mail_renderers"):
        for renderer in func():
            if template.startswith(renderer.prefix):
                return renderer
    return None


def send_rendered(template: str, to: str, *, subject: str, cc: list[str], reply_to: str, message_id: str,
                  references: str, auto_submitted: str, related_ref: str, attachments: list[str],
                  context: dict) -> MailMessage:
    """Ставит в очередь письмо приложения (заявки): тело соберёт рендерер своего префикса в момент отправки."""
    if renderer_for(template) is None:
        raise ValueError(f"нет рендерера для шаблона письма: {template}")
    message = MailMessage.objects.create(
        to=to, template=template, subject=subject, status=MailStatus.QUEUED, cc=", ".join(cc),
        reply_to=reply_to, message_id=message_id, references=references, auto_submitted=auto_submitted,
        related_ref=related_ref, attachments=[str(item) for item in attachments])
    enqueue(message.pk, {"context": public_context(context)})
    return message


def anonymize_related(related_ref: str) -> int:
    """Обезличивает письма по `related_ref`: получатель, копии, вложения, тексты ошибок; возвращает число писем."""
    qs = MailMessage.objects.filter(related_ref=related_ref)
    ids = list(qs.values_list("pk", flat=True))
    MailAttempt.objects.filter(message_id__in=ids).update(error="")
    return qs.update(to=ANONYMIZED, cc="", attachments=[], last_error="")


def last_message(user, template: str) -> MailMessage | None:
    """Последнее письмо записи по шаблону (карточка сотрудника показывает его состояние, FR-009)."""
    return MailMessage.objects.filter(related_user=user, template=template).order_by("-id").first()


def delivery_log(*, page_size: int = 50, page=None):
    """Журнал доставки для администратора (FR-053): письма по убыванию с попытками, без тел писем."""
    from django.core.paginator import Paginator

    qs = MailMessage.objects.prefetch_related("attempt_log").order_by("-id")
    return Paginator(qs, page_size).get_page(page)
