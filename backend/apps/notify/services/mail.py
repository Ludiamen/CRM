"""Публичный интерфейс уведомлений: письма (PLAN-004, «Письма»; CONTRACT-004, 6.10 и раздел 10).

Письма идут почтовым модулем через `send_rendered` с префиксом шаблона `notify.`; тело собирает рендерер `render`
из базы в момент отправки. Контекст письма — только номер доставки: текст и тема заявки в данные задания не попадают.
"""
import logging
from email.utils import make_msgid, parseaddr

from django.conf import settings
from django.db import transaction
from django.template import Context, loader
from django.utils import timezone

from apps.core.extensions import MailRenderer, Rendered
from apps.core.services import portal_settings
from apps.integrations.mail import services as mail_services

from ..models import Delivery, Notification
from . import dispatch, kinds, prefs, quiet
from .errors import NotifyError

log = logging.getLogger(__name__)

TEMPLATES = ("notify.item", "notify.digest")
UNAVAILABLE = "Уведомление больше недоступно."
_FORMS = ("уведомление", "уведомления", "уведомлений")


def plural(count: int) -> str:
    """Форма слова «уведомление» по числу (CONTRACT-004, 15.6): 1 уведомление, 2 уведомления, 5 уведомлений."""
    if 11 <= count % 100 <= 14:
        return _FORMS[2]
    if count % 10 == 1:
        return _FORMS[0]
    if 2 <= count % 10 <= 4:
        return _FORMS[1]
    return _FORMS[2]


def _base() -> str:
    """`PORTAL_URL` без завершающего «/»."""
    return settings.PORTAL_URL.rstrip("/")


def _text_of(template: str, values: dict) -> str:
    """Текст шаблона `templates/notify/mail/notify_<вид>.txt` без экранирования."""
    name = f"notify/mail/notify_{template.partition('.')[2]}.txt"
    return loader.get_template(name).template.render(Context(values, autoescape=False))


def _common() -> dict:
    return {"portal_name": portal_settings.get().name, "list_url": f"{_base()}/notifications/",
            "settings_url": f"{_base()}/me/notifications/"}


def render(message, context: dict) -> Rendered:
    """Тело письма по `context["delivery"]`: данные берутся из базы в момент вызова; нет доставки или уведомления —
    нейтральный текст со ссылкой на «Уведомления»."""
    template = message.template
    if template not in TEMPLATES:
        raise ValueError(f"нет шаблона письма уведомлений: {template}")
    values = _common()
    delivery = (Delivery.objects.select_related("notification", "digest")
                .filter(pk=context.get("delivery")).first())
    if delivery is not None and template == "notify.item" and delivery.notification is not None:
        note = delivery.notification
        values.update(text=note.text, open_url=f"{_base()}/notifications/{note.pk}/open/")
        return Rendered(body=_text_of(template, values), attachments=[])
    if delivery is not None and template == "notify.digest" and delivery.digest is not None:
        notes = (Notification.objects
                 .filter(pk__in=delivery.digest.notification_ids, deliveries__channel=Delivery.Channel.EMAIL,
                         deliveries__state=Delivery.State.DIGESTED)
                 .order_by("created_at", "id"))
        rows = [{"text": note.text, "url": f"{_base()}/notifications/{note.pk}/open/"} for note in notes]
        if rows:
            values.update(count=len(rows), word=plural(len(rows)), rows=rows)
            return Rendered(body=_text_of(template, values), attachments=[])
    return Rendered(body=_text_of("notify.unavailable", values), attachments=[])


def renderers() -> list[MailRenderer]:
    """Точка `mail_renderers`: один рендерер на префикс `notify.`."""
    return [MailRenderer(prefix="notify.", render=render)]


def message_id_for(delivery_id: int) -> str:
    """`Message-ID` из номера доставки с доменом адреса `SMTP_FROM`; двойную постановку он не отсекает."""
    address = parseaddr(settings.DEFAULT_FROM_EMAIL)[1]
    domain = address.rpartition("@")[2] if "@" in address else None
    return make_msgid(idstring=f"notify.{delivery_id}", domain=domain or None)


def _queue(template: str, to: str, subject: str, delivery_id: int) -> int:
    message = mail_services.send_rendered(
        template, to, subject=subject, cc=[], reply_to="", message_id=message_id_for(delivery_id), references="",
        auto_submitted="auto-generated", related_ref=f"notify.delivery:{delivery_id}", attachments=[],
        context={"delivery": delivery_id})
    return message.pk


def queue_item(delivery) -> int:
    """Ставит письмо `notify.item`; тема — внешний текст вида, без номера и темы заявки. Возвращает номер письма."""
    note = delivery.notification
    return _queue("notify.item", note.user.email, kinds.get(note.kind).external_text, delivery.pk)


def queue_digest(delivery) -> int:
    """Ставит письмо `notify.digest`; тема — «За нерабочее время: N уведомлений». Возвращает номер письма."""
    digest = delivery.digest
    count = digest.count_email
    return _queue("notify.digest", digest.user.email, f"За нерабочее время: {count} {plural(count)}", delivery.pk)


def _skip(row, reason: str) -> None:
    row.state, row.reason, row.due_at = Delivery.State.SKIPPED, reason, None
    row.save(update_fields=["state", "reason", "due_at"])


def _process(row, now) -> None:
    """Проверки FR-327 по порядку; затем письмо, пропуск или отложение до сводки."""
    note, user = row.notification, row.notification.user
    if user.state == "blocked":
        return _skip(row, "user_blocked")
    if user.state == "dismissed":
        return _skip(row, "user_dismissed")
    if note.read_at is not None:
        return _skip(row, "read")
    try:
        kind = kinds.get(note.kind)
    except NotifyError:
        return _skip(row, "not_relevant")
    if not kind.still_relevant(note.user_id, note.object_ref):
        return _skip(row, "not_relevant")
    if "email" not in prefs.channels_for(note.user_id, kind):
        return _skip(row, "channel_off")
    if not quiet.is_working(prefs.row_of(note.user_id), now):
        row.state, row.due_at = Delivery.State.HELD, None
        row.save(update_fields=["state", "due_at"])
        dispatch.plan_digest(note.user_id)
        return None
    row.mail_id = queue_item(row)
    row.state, row.attempts = Delivery.State.SENT, 1
    row.log = [*row.log, {"at": now.isoformat(), "outcome": "ok"}]
    row.save(update_fields=["mail_id", "state", "attempts", "log"])
    return None


def send_due() -> int:
    """Письма доставкам `email` с наступившим сроком; возвращает число обработанных доставок. Каждая — в своей
    транзакции под `select_for_update(skip_locked=True)`; состояние перепроверяется под замком."""
    handled = 0
    while True:  # каждая обработанная доставка выходит из `waiting`, поэтому цикл конечен
        with transaction.atomic():
            now = timezone.now()
            row = (Delivery.objects.select_for_update(skip_locked=True, of=("self",))
                   .select_related("notification__user")
                   .filter(state=Delivery.State.WAITING, channel=Delivery.Channel.EMAIL, due_at__lte=now,
                           notification__isnull=False)
                   .order_by("due_at", "id").first())
            if row is None:
                break
            _process(row, now)
        handled += 1
    return handled
