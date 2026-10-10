"""T-4111: письмо по уведомлению через срок — проверки при отправке, пересечение обходов, тема, тело и журнал почты
(FR-316, FR-327, FR-333, FR-345, NFR-303, NFR-306). Сценарии 1, 3 (письмо), 11 спеки среза 004.

Письмо ставит `mail.send_due()` (обход `notify_tick`) через `send_rendered` почтового модуля; доставку выполняет
`SimpleWorker` (`support_mail.deliver`), заголовки читает Mailpit. Сотрудник — прямой участник очереди, вид —
`servicedesk.new_in_queue` (канал «Почта» включён по умолчанию, тихих часов нет: режим `none`). Срок письма сдвигается
прямой записью `due_at` (очередь и Valkey живут по настоящему времени) либо часами `clock`; обход — `run_tick()`.
Имена кода среза 004 (`apps.notify…`, `Draft`) импортируются внутри тестов: сбор проходит до появления кода.
Правила — tests/CONTRACT-004.md (§ 6.9, 6.10, 7.3, 10, решения A5, E10, E13, E25; дополнение 6 раздела 17).
"""
import email.utils
import inspect
import logging
import re
import secrets
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.utils import timezone

from tests import support
from tests import support_notify as notify
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model
from tests.support_mail import break_smtp, deliver, mail_jobs

pytestmark = pytest.mark.django_db

NEW_IN_QUEUE = "servicedesk.new_in_queue"
EXTERNAL_TEXT = "Новая заявка в вашей очереди"
PORTAL_NAME = "Портал ИТ-отдела"
MOSCOW = ZoneInfo("Europe/Moscow")


# --- помощники только этого файла -------------------------------------------------------------------------

class World:
    """Очередь, её участник (получатель), заявка без ответственного."""

    def __init__(self, queue, user, ticket):
        self.queue, self.user, self.ticket = queue, user, ticket


def _prefs(user, *, mode: str = "none", **over):
    """Строка `UserNotifySettings`: по умолчанию «Без тихих часов» (письмо не зависит от часов хоста)."""
    return model("notify.UserNotifySettings").objects.update_or_create(
        user=user, defaults={"quiet_mode": mode, **over})[0]


def _world(*, mode: str = "none", **prefs_over) -> World:
    model("core.PortalSettings").objects.update(name=PORTAL_NAME)
    queue = sd.make_queue(org.make_unit(f"Очередь {secrets.token_hex(3)}"))
    user = support.make_employee()
    org.make_member(user, queue.unit)
    _prefs(user, mode=mode, **prefs_over)
    return World(queue, user, _ticket(queue))


def _ticket(queue):
    return sd.make_ticket(queue=queue, subject=f"Принтер не печатает {secrets.token_hex(3)}")


def _text(ticket) -> str:
    return f"Новая заявка #{ticket.number} в очереди «{ticket.queue.name}»: {ticket.subject}"


def _notify(world: World, capture, *, ticket=None, user=None):
    """Уведомление вида «Новая заявка в моей очереди» (`dispatch.create`) и его доставка `email` в состоянии `waiting`."""
    from apps.core.extensions import Draft
    from apps.notify.services import dispatch

    ticket = ticket or world.ticket
    user = user or world.user
    draft = Draft(user_id=user.pk, text=_text(ticket), url=f"/tickets/{ticket.number}/",
                  object_ref=f"servicedesk.ticket:{ticket.pk}")
    with capture(execute=True):
        ids = dispatch.create(NEW_IN_QUEUE, [draft])
    note = model("notify.Notification").objects.get(pk=ids[0])
    deliveries = list(model("notify.Delivery").objects.filter(notification=note))
    assert [(d.channel, d.state) for d in deliveries] == [("email", "waiting")], "ждали одну доставку email waiting"
    return note, deliveries[0]


def _due(delivery) -> None:
    """Срок письма наступил: `due_at` на минуту в прошлом (решение 3 задач: прямая запись в поле)."""
    sd.backdate(delivery, "due_at", minutes=16)
    assert delivery.due_at < timezone.now()


def _fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


def _mails():
    """Письма `notify.item` по возрастанию номера."""
    return list(model("mail.MailMessage").objects.filter(template="notify.item").order_by("id"))


def _body(delivery) -> str:
    from apps.notify.services import mail as notify_mail

    message = model("mail.MailMessage").objects.get(pk=_fresh(delivery).mail_id)
    return notify_mail.render(message, {"delivery": delivery.pk}).body


def _lines(body: str) -> list[str]:
    return body.rstrip("\n").splitlines()


def _url(path: str) -> str:
    from django.conf import settings

    return settings.PORTAL_URL.rstrip("/") + path


def _mails_to(mailpit, address: str) -> list[dict]:
    """Письма Mailpit на адрес: полное письмо плюс `_headers` (имена строчными, значения — списки)."""
    found = []
    for short in mailpit.messages():
        if any(a["Address"].lower() == address.lower() for a in short["To"]):
            full = mailpit.message(short["ID"])
            raw = mailpit._request("GET", f"/api/v1/message/{short['ID']}/headers")
            full["_headers"] = {k.lower(): v for k, v in raw.items()}
            found.append(full)
    return found


def _delivered(mailpit, address: str) -> dict:
    """Доставляет очередь `mail` и возвращает единственное письмо на адрес."""
    deliver()
    mails = _mails_to(mailpit, address)
    assert len(mails) == 1, f"в Mailpit {len(mails)} писем на адрес вместо одного"
    return mails[0]


def _no_subscriber_errors(caplog) -> None:
    """Правило решения 24 задач: сбоев подписчиков в журнале приложения нет."""
    bad = [r for r in caplog.records if r.name == "apps.core.events" and r.levelno >= logging.ERROR]
    assert not bad, "шина записала сбой подписчика"


# --- одно письмо, текст, срок ----------------------------------------------------------------------------

def test_unread_after_delay_sends_exactly_one_email(mailpit, caplog, django_capture_on_commit_callbacks):
    """FR-327: непрочитанное уведомление через срок даёт одно письмо на рабочий адрес; повторный обход второго не ставит."""
    caplog.set_level(logging.INFO)
    world = _world()
    note, delivery = _notify(world, django_capture_on_commit_callbacks)
    assert not _mails(), "письмо поставлено при создании уведомления"
    _due(delivery)
    notify.run_tick()
    delivery = _fresh(delivery)
    assert (delivery.state, delivery.reason, delivery.attempts) == ("sent", "", 1)
    assert delivery.mail_id is not None
    assert [m.pk for m in _mails()] == [delivery.mail_id]
    assert delivery.log and delivery.log[-1]["outcome"] == "ok"
    notify.run_tick()
    assert [m.pk for m in _mails()] == [delivery.mail_id], "повторный обход поставил второе письмо"
    letter = _delivered(mailpit, world.user.email)
    assert note.text in letter["Text"]
    assert _fresh(note).read_at is None, "письмо не должно отмечать уведомление прочитанным"
    _no_subscriber_errors(caplog)


def test_email_body_has_text_and_link_of_notification(mailpit, django_capture_on_commit_callbacks):
    """FR-316, FR-327: в теле письма полный текст уведомления (с номером и темой заявки) и ссылка на открытие уведомления."""
    world = _world()
    note, delivery = _notify(world, django_capture_on_commit_callbacks)
    _due(delivery)
    notify.run_tick()
    link = _url(f"/notifications/{note.pk}/open/")
    lines = _lines(_body(delivery))
    assert note.text in lines
    assert f"Открыть: {link}" in lines
    letter = _delivered(mailpit, world.user.email)
    assert note.text in letter["Text"] and link in letter["Text"]
    assert str(world.ticket.number) in letter["Text"] and world.ticket.subject in letter["Text"]


def test_email_not_sent_before_due(clock, django_capture_on_commit_callbacks):
    """FR-327: до срока письма нет; в срок — есть (срок по умолчанию 15 минут)."""
    world = _world()
    note, delivery = _notify(world, django_capture_on_commit_callbacks)
    assert delivery.due_at == note.created_at + timedelta(minutes=15)
    clock.advance(minutes=14)
    notify.run_tick()
    delivery = _fresh(delivery)
    assert (delivery.state, delivery.mail_id) == ("waiting", None)
    assert not _mails()
    clock.advance(minutes=1, seconds=1)
    notify.run_tick()
    assert _fresh(delivery).state == "sent" and len(_mails()) == 1


def test_delay_from_settings_30_minutes(clock, django_capture_on_commit_callbacks):
    """FR-327: срок письма — `email_delay_minutes` настроек администратора: при 30 минутах письма нет через 29 и есть через 30."""
    model("notify.NotifySettings").objects.filter(pk=1).update(email_delay_minutes=30)
    world = _world()
    note, delivery = _notify(world, django_capture_on_commit_callbacks)
    assert delivery.due_at == note.created_at + timedelta(minutes=30)
    clock.advance(minutes=29)
    notify.run_tick()
    assert _fresh(delivery).state == "waiting" and not _mails()
    clock.advance(minutes=1, seconds=1)
    notify.run_tick()
    assert _fresh(delivery).state == "sent" and len(_mails()) == 1


def test_email_sent_within_one_minute_after_due(mailpit, django_capture_on_commit_callbacks):
    """NFR-303: после наступления срока один обход ставит письмо, доставка проходит не позже минуты от срока."""
    world = _world()
    _, delivery = _notify(world, django_capture_on_commit_callbacks)
    delivery.due_at = timezone.now() - timedelta(seconds=5)
    model("notify.Delivery").objects.filter(pk=delivery.pk).update(due_at=delivery.due_at)
    tick = notify.run_tick()
    assert tick["emails"] == 1, "один обход после срока не отправил письмо"
    deliver()
    message = _fresh(_mails()[0])
    assert message.status == "sent" and message.sent_at is not None
    assert message.sent_at - delivery.due_at <= timedelta(seconds=60)
    assert len(_mails_to(mailpit, world.user.email)) == 1


# --- проверки при отправке --------------------------------------------------------------------------------

def _skipped(delivery, reason: str) -> None:
    delivery = _fresh(delivery)
    assert (delivery.state, delivery.reason) == ("skipped", reason)
    assert delivery.mail_id is None
    assert not _mails(), "письмо поставлено при пропуске"


def test_read_notification_skipped_with_reason(django_capture_on_commit_callbacks):
    """FR-327: прочитанное до срока уведомление — письма нет, доставка `skipped` с причиной `read`."""
    from apps.notify.services import reading

    world = _world()
    note, delivery = _notify(world, django_capture_on_commit_callbacks)
    with django_capture_on_commit_callbacks(execute=True):
        assert reading.read(world.user, note.pk) is True
    _due(delivery)
    notify.run_tick()
    _skipped(delivery, "read")


def test_opened_ticket_card_skips_email(django_capture_on_commit_callbacks):
    """FR-327: открытая карточка заявки отмечает её уведомления прочитанными — письма по ней нет, по другой заявке есть."""
    world = _world()
    other_ticket = _ticket(world.queue)
    note, delivery = _notify(world, django_capture_on_commit_callbacks)
    other_note, other_delivery = _notify(world, django_capture_on_commit_callbacks, ticket=other_ticket)
    client = support.logged_in(world.user)
    with django_capture_on_commit_callbacks(execute=True):
        assert client.get(f"/tickets/{world.ticket.number}/").status_code == 200
    assert _fresh(note).read_at is not None and _fresh(other_note).read_at is None
    _due(delivery)
    _due(other_delivery)
    notify.run_tick()
    _skipped_one = _fresh(delivery)
    assert (_skipped_one.state, _skipped_one.reason, _skipped_one.mail_id) == ("skipped", "read", None)
    sent_one = _fresh(other_delivery)
    assert sent_one.state == "sent" and [m.pk for m in _mails()] == [sent_one.mail_id]


def test_new_ticket_got_assignee_skips_email(django_capture_on_commit_callbacks):
    """FR-327: у «Новая заявка в моей очереди» появился ответственный — `still_relevant` ложно: `skipped`, причина `not_relevant`."""
    world = _world()
    note, delivery = _notify(world, django_capture_on_commit_callbacks)
    assignee = support.make_employee()
    org.make_member(assignee, world.queue.unit)
    model("servicedesk.Ticket").objects.filter(pk=world.ticket.pk).update(assignee=assignee)
    _due(delivery)
    notify.run_tick()
    _skipped(delivery, "not_relevant")


def test_lost_access_skips_email(django_capture_on_commit_callbacks):
    """FR-327: сотрудник перестал быть участником очереди до срока — письма нет, `skipped`, причина `not_relevant`."""
    world = _world()
    note, delivery = _notify(world, django_capture_on_commit_callbacks)
    model("org.Membership").objects.filter(user=world.user, unit=world.queue.unit).delete()
    assert not model("org.Membership").objects.filter(user=world.user, unit=world.queue.unit).exists()
    _due(delivery)
    notify.run_tick()
    _skipped(delivery, "not_relevant")


def test_blocked_user_skips_email(django_capture_on_commit_callbacks):
    """FR-327, FR-345: учётную запись заблокировали до срока — письмо не уходит, `skipped`, причина `user_blocked`."""
    world = _world()
    note, delivery = _notify(world, django_capture_on_commit_callbacks)
    model("core.User").objects.filter(pk=world.user.pk).update(state="blocked")
    _due(delivery)
    notify.run_tick()
    _skipped(delivery, "user_blocked")
    assert _fresh(note).read_at is None


def test_email_channel_turned_off_skips_email(django_capture_on_commit_callbacks):
    """FR-327: канал «Почта» у вида выключили до срока — письма нет, `skipped`, причина `channel_off`."""
    world = _world()
    note, delivery = _notify(world, django_capture_on_commit_callbacks)
    _prefs(world.user, matrix={NEW_IN_QUEUE: ["push"]})
    _due(delivery)
    notify.run_tick()
    _skipped(delivery, "channel_off")


def test_skipped_notification_stays_on_portal(django_capture_on_commit_callbacks):
    """FR-327: пропущенное письмо не удаляет уведомление: оно непрочитано, в счётчике и в списке «Уведомления»."""
    from apps.notify.services import reading

    world = _world()
    note, delivery = _notify(world, django_capture_on_commit_callbacks)
    model("servicedesk.Ticket").objects.filter(pk=world.ticket.pk).update(assignee=support.make_employee())
    _due(delivery)
    notify.run_tick()
    _skipped(delivery, "not_relevant")
    assert model("notify.Notification").objects.filter(pk=note.pk, read_at=None).exists()
    assert reading.unread_count(world.user.pk) == 1
    response = support.logged_in(world.user).get("/notifications/")
    assert response.status_code == 200
    html = response.content.decode()
    assert re.search(rf'<li[^>]*data-notification="{note.pk}"[^>]*data-unread="1"|'
                     rf'<li[^>]*data-unread="1"[^>]*data-notification="{note.pk}"', html)


def test_due_in_quiet_hours_becomes_held_with_digest_due_at(clock, django_capture_on_commit_callbacks):
    """FR-327: срок письма пришёлся на тихие часы — письма нет, доставка `held` без срока, `digest_due_at` — начало рабочего времени."""
    clock.set(datetime(2026, 10, 14, 3, 0, tzinfo=MOSCOW))
    world = _world(mode="own", own_days=[0, 1, 2, 3, 4, 5, 6], own_start=time(9, 0), own_end=time(18, 0))
    note, delivery = _notify(world, django_capture_on_commit_callbacks)
    clock.advance(minutes=15, seconds=1)
    notify.run_tick()
    delivery = _fresh(delivery)
    assert (delivery.state, delivery.due_at, delivery.reason, delivery.mail_id) == ("held", None, "", None)
    assert not _mails()
    expected = datetime(2026, 10, 14, 9, 0, tzinfo=MOSCOW)
    assert model("notify.UserNotifySettings").objects.get(user=world.user).digest_due_at == expected


# --- идемпотентность и очередь ----------------------------------------------------------------------------

def test_two_sequential_ticks_send_one_email(mailpit, django_capture_on_commit_callbacks):
    """NFR-306, FR-333: два обхода подряд — одно письмо и одно письмо в Mailpit."""
    world = _world()
    _, delivery = _notify(world, django_capture_on_commit_callbacks)
    _due(delivery)
    first = notify.run_tick()
    second = notify.run_tick()
    assert first["emails"] == 1
    assert len(_mails()) == 1 and _fresh(delivery).state == "sent"
    assert second["emails"] == 0
    letter = _delivered(mailpit, world.user.email)
    assert letter["_headers"]["x-portal-template"] == ["notify.item"]


def test_overlapping_ticks_send_one_email(django_capture_on_commit_callbacks):
    """NFR-306, FR-333: два `send_due()` дают одно письмо; выбор доставок идёт под `FOR UPDATE SKIP LOCKED`
    (решения E10, E25: имя неточно — проверяются повтор и запрос, а не настоящее пересечение)."""
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    from apps.notify.services import mail as notify_mail

    world = _world()
    _, delivery = _notify(world, django_capture_on_commit_callbacks)
    _due(delivery)
    with CaptureQueriesContext(connection) as queries:
        with django_capture_on_commit_callbacks(execute=True):
            first = notify_mail.send_due()
        with django_capture_on_commit_callbacks(execute=True):
            second = notify_mail.send_due()
    assert (first, second) == (1, 0)
    assert len(_mails()) == 1
    assert _fresh(delivery).state == "sent"
    assert any(re.search(r"FOR UPDATE\b.*\bSKIP LOCKED", item["sql"], re.S | re.I) for item in queries.captured_queries), \
        "в запросе выбора доставок нет FOR UPDATE SKIP LOCKED"


def test_mail_job_enqueued_only_after_commit(django_capture_on_commit_callbacks):
    """FR-333: задание почты встаёт в очередь `mail` только после фиксации транзакции (правило § 7.3)."""
    from django.db import transaction

    from apps.notify.services import mail as notify_mail

    world = _world()
    _, delivery = _notify(world, django_capture_on_commit_callbacks)
    _due(delivery)
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            assert notify_mail.send_due() == 1
            assert mail_jobs() == [], "задание почты поставлено до фиксации"
        assert mail_jobs() == [], "задание почты поставлено до выхода из внешней транзакции"
    message = _mails()[0]
    assert [job.args for job in mail_jobs()] == [(message.pk,)]
    assert notify.queued() == [], "письмо не должно идти заданием очереди notify"


def test_send_rendered_called_with_required_arguments(monkeypatch, settings, mailpit, django_capture_on_commit_callbacks):
    """FR-316, FR-333: `send_rendered` получает шаблон, адрес, внешний текст в теме, пустые копии, `Message-ID` из номера
    доставки, `auto-generated`, `related_ref` и контекст из номера; заголовки в Mailpit те же."""
    from apps.integrations.mail import services as mail_services
    original = mail_services.send_rendered
    calls = []

    def recording(*args, **kwargs):
        calls.append(inspect.signature(original).bind(*args, **kwargs).arguments)
        return original(*args, **kwargs)

    monkeypatch.setattr(mail_services, "send_rendered", recording)
    world = _world()
    _, delivery = _notify(world, django_capture_on_commit_callbacks)
    _due(delivery)
    notify.run_tick()
    assert len(calls) == 1
    given = calls[0]
    domain = email.utils.parseaddr(settings.DEFAULT_FROM_EMAIL)[1].rpartition("@")[2]
    assert given["template"] == "notify.item" and given["to"] == world.user.email
    assert given["subject"] == EXTERNAL_TEXT
    assert given["cc"] == [] and given["reply_to"] == "" and given["references"] == ""
    assert given["auto_submitted"] == "auto-generated"
    assert given["related_ref"] == f"notify.delivery:{delivery.pk}"
    assert given["attachments"] == []
    assert given["context"] == {"delivery": delivery.pk}
    message_id = given["message_id"]
    assert message_id.startswith("<") and message_id.endswith(f".notify.{delivery.pk}@{domain}>")
    message = _mails()[0]
    assert message.message_id == message_id and _fresh(delivery).mail_id == message.pk
    letter = _delivered(mailpit, world.user.email)
    assert letter["_headers"]["auto-submitted"] == ["auto-generated"]
    assert letter["_headers"]["x-portal-template"] == ["notify.item"]
    assert letter["_headers"]["message-id"] == [message_id]
    assert [a["Address"] for a in letter["To"]] == [world.user.email] and not letter["Cc"]


def test_subject_is_external_text_without_ticket_number_and_title(mailpit, django_capture_on_commit_callbacks):
    """FR-316: тема письма — внешний текст вида; ни номера, ни темы заявки в ней нет (журнал почты хранит темы)."""
    world = _world()
    note, delivery = _notify(world, django_capture_on_commit_callbacks)
    _due(delivery)
    notify.run_tick()
    message = _mails()[0]
    assert message.subject == EXTERNAL_TEXT
    assert str(world.ticket.number) not in message.subject and world.ticket.subject not in message.subject
    letter = _delivered(mailpit, world.user.email)
    assert letter["Subject"] == EXTERNAL_TEXT
    assert world.ticket.subject in letter["Text"], "полный текст с темой заявки должен быть в теле"


def test_job_context_contains_only_delivery_number(django_capture_on_commit_callbacks):
    """FR-316: в данных задания почты (Valkey) контекст — только номер доставки; текста и темы заявки нет."""
    world = _world()
    note, delivery = _notify(world, django_capture_on_commit_callbacks)
    _due(delivery)
    notify.run_tick()
    delivery = _fresh(delivery)
    jobs = [job for job in mail_jobs() if job.args == (delivery.mail_id,)]
    assert len(jobs) == 1
    assert jobs[0].meta["context"] == {"delivery": delivery.pk}
    dumped = repr(jobs[0].meta)
    assert world.ticket.subject not in dumped and str(note.text) not in dumped


# --- рендерер: текст из базы в момент отправки --------------------------------------------------------------

def test_renderer_reads_text_from_database_at_send_time(mailpit, django_capture_on_commit_callbacks):
    """FR-316: тело письма собирается из базы при отправке: текст, изменённый после постановки, попадает в письмо."""
    world = _world()
    note, delivery = _notify(world, django_capture_on_commit_callbacks)
    old_text = note.text
    _due(delivery)
    notify.run_tick()
    new_text = f"Новая заявка в очереди: текст после правки {secrets.token_hex(3)}"
    model("notify.Notification").objects.filter(pk=note.pk).update(text=new_text)
    lines = _lines(_body(delivery))
    assert new_text in lines and old_text not in lines
    letter = _delivered(mailpit, world.user.email)
    assert new_text in letter["Text"] and old_text not in letter["Text"]


def test_renderer_neutral_text_when_notification_deleted(mailpit, django_capture_on_commit_callbacks):
    """FR-316: уведомление удалено до отправки — нейтральный текст и ссылка на «Уведомления»; тема прежняя."""
    from apps.notify.services import mail as notify_mail

    world = _world()
    note, delivery = _notify(world, django_capture_on_commit_callbacks)
    _due(delivery)
    notify.run_tick()
    message = _mails()[0]
    delivery_id = delivery.pk
    model("notify.Notification").objects.filter(pk=note.pk).delete()
    assert not model("notify.Delivery").objects.filter(pk=delivery_id).exists()
    body = notify_mail.render(message, {"delivery": delivery_id}).body
    assert _lines(body) == [PORTAL_NAME, "", "Уведомление больше недоступно.", "",
                            f"Все уведомления: {_url('/notifications/')}"]
    assert _fresh(message).subject == EXTERNAL_TEXT
    letter = _delivered(mailpit, world.user.email)
    assert letter["Subject"] == EXTERNAL_TEXT and "Уведомление больше недоступно" in letter["Text"]
    assert world.ticket.subject not in letter["Text"]


def test_email_body_has_portal_name_and_settings_link_and_no_secrets(django_capture_on_commit_callbacks):
    """FR-316: тело письма — ровно семь строк § 10.2: название портала, текст, ссылка, ссылка «Настроить уведомления»; паролей и ссылок входа нет."""
    world = _world()
    note, delivery = _notify(world, django_capture_on_commit_callbacks)
    _due(delivery)
    notify.run_tick()
    body = _body(delivery)
    assert _lines(body) == [PORTAL_NAME, "", note.text, "",
                            f"Открыть: {_url(f'/notifications/{note.pk}/open/')}", "",
                            f"Настроить уведомления: {_url('/me/notifications/')}"]
    for forbidden in (world.user.test_password, "/login", "/password", "reset"):
        assert forbidden not in body


# --- журнал почты --------------------------------------------------------------------------------------------

def test_email_appears_in_mail_delivery_journal(django_capture_on_commit_callbacks):
    """FR-333: письмо уведомления видно в журнале доставки почты: статус `sent`, одна удачная попытка."""
    from apps.integrations.mail import services as mail_services

    world = _world()
    _, delivery = _notify(world, django_capture_on_commit_callbacks)
    _due(delivery)
    notify.run_tick()
    deliver()
    delivery = _fresh(delivery)
    journal = {m.pk: m for m in mail_services.delivery_log().object_list}
    assert delivery.mail_id in journal
    entry = journal[delivery.mail_id]
    assert (entry.status, entry.template, entry.to) == ("sent", "notify.item", world.user.email)
    assert [attempt.ok for attempt in entry.attempt_log.all()] == [True]


def test_smtp_failure_visible_in_mail_journal_while_delivery_sent(settings, mailpit, django_capture_on_commit_callbacks):
    """FR-333: сбой SMTP виден в журнале почты (попытка не удалась), а доставка остаётся `sent` (решение A5)."""
    from apps.integrations.mail import services as mail_services

    world = _world()
    _, delivery = _notify(world, django_capture_on_commit_callbacks)
    _due(delivery)
    notify.run_tick()
    break_smtp(settings)
    deliver()
    delivery = _fresh(delivery)
    assert (delivery.state, delivery.reason, delivery.attempts) == ("sent", "", 1)
    message = _fresh(_mails()[0])
    assert message.status == "queued" and message.attempts == 1 and message.last_error
    entry = {m.pk: m for m in mail_services.delivery_log().object_list}[delivery.mail_id]
    assert [attempt.ok for attempt in entry.attempt_log.all()] == [False]
    assert not _mails_to(mailpit, world.user.email)
    notify.run_tick()
    assert len(_mails()) == 1 and _fresh(delivery).state == "sent", "обход не должен повторять письмо, не дошедшее по SMTP"
