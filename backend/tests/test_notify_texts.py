"""T-4108: тексты уведомлений на портале, в письме, в Telegram, MAX и Web Push (FR-316, FR-317, NFR-307, NFR-311).

Сценарии 1-3 и 12 спеки среза 004. Тексты записи на портале (виды заявок, безопасности, «Канал отвязан») — дословно
CONTRACT-004 § 15.1; внешние тексты (Telegram, MAX, Web Push, тема письма) — § 15.2; тема в тексте — не длиннее 100
знаков по символам (§ 4.3); «Вход с нового устройства» — время по Москве (§ 3.5, решение 17 задач); письмо — § 10.
Код среза на уровне модуля не импортируется: имена берутся внутри тестов (CONTRACT-004, шапка).
"""
import html
import json
import logging
import re
import secrets
import types
from datetime import datetime, timedelta, timezone as dt_timezone
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import pytest
from django.db import transaction
from django.utils import timezone

from tests import support
from tests import support_notify as notify_support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

# дословные тексты § 15.1 и § 15.2
EXTERNAL = {
    "servicedesk.new_in_queue": "Новая заявка в вашей очереди",
    "servicedesk.assigned": "Вам назначена заявка",
    "servicedesk.requester_replied": "Заявитель ответил по вашей заявке",
    "servicedesk.reply_failed": "Ответ заявителю не ушёл",
}
BUTTON = "Открыть уведомления"
MARKER = "МаркерТемы"
MARKUP_SUBJECT = f"<b>{MARKER}</b> & <i>курсив</i>"


# --- помощники только этого файла ---------------------------------------------------------------------

def _kind(code: str):
    from apps.notify.services import kinds
    return kinds.get(code)


def _employee():
    return support.make_employee()


def _scene(subject: str | None = None, *, requester_name: str = "", requester_email: str | None = None):
    """Очередь с одним сотрудником-ответственным; заявка без ответственного (`new`) и заявка в работе у него.

    Сотрудник состоит в узле-очереди, поэтому видит обе заявки (`access.can_work`, § 4.3)."""
    unit = org.make_unit(f"Очередь {secrets.token_hex(3)}")
    sd.make_queue(unit)
    assignee = _employee()
    org.make_member(assignee, unit)
    requester = sd.make_requester(requester_email, full_name=requester_name)
    ticket_new = sd.make_ticket(queue=unit, requester=requester, **({"subject": subject} if subject else {}))
    ticket_work = sd.make_ticket(queue=unit, requester=requester, kind="in_progress", assignee=assignee,
                                 assigned_once=True, **({"subject": subject} if subject else {}))
    return types.SimpleNamespace(unit=unit, assignee=assignee, new=ticket_new, work=ticket_work,
                                 requester=requester)


def _created_data(ticket, *, actor_id=None) -> dict:
    return {"number": ticket.number, "queue_id": ticket.queue_id, "assignee_before_id": None,
            "assignee_after_id": ticket.assignee_id, "actor_id": actor_id, "channel": "mail"}


def _assigned_data(ticket, *, actor_id=None) -> dict:
    return {"number": ticket.number, "queue_id": ticket.queue_id, "assignee_before_id": None,
            "assignee_after_id": ticket.assignee_id, "actor_id": actor_id}


def _replied_data(ticket) -> dict:
    return {"number": ticket.number, "queue_id": ticket.queue_id, "assignee_before_id": ticket.assignee_id,
            "assignee_after_id": ticket.assignee_id, "actor_id": None, "via": "appended",
            "author_kind": "requester", "entry_id": 1}


def _build_assigned(scene) -> list:
    return _kind("servicedesk.assigned").build("servicedesk.assignee_changed", _assigned_data(scene.work))


def _build_new_in_queue(scene) -> list:
    return _kind("servicedesk.new_in_queue").build("servicedesk.ticket_created", _created_data(scene.new))


def _build_replied(scene) -> list:
    return _kind("servicedesk.requester_replied").build("servicedesk.reply_received", _replied_data(scene.work))


def _notification(user, kind_code: str, text: str, url: str = "/tickets/1/", object_ref: str = ""):
    return model("notify.Notification").objects.create(user=user, kind=kind_code, text=text, url=url,
                                                       object_ref=object_ref)


def _delivery(notification, channel: str):
    """Доставка, которой пора уходить: `waiting`, срок в прошлом."""
    now = timezone.now()
    return model("notify.Delivery").objects.create(
        notification=notification, channel=channel, state="waiting", due_at=now - timedelta(seconds=5),
        enqueued_at=now)


def _bind(user, channel: str):
    return model("notify.ChatBinding").objects.create(user=user, channel=channel, chat_id=f"c{secrets.token_hex(4)}")


def _body(message_id: int, delivery_id: int) -> list[str]:
    """Строки тела письма (рендерер читает базу, § 10.1)."""
    from apps.notify.services import mail as notify_mail
    message = model("mail.MailMessage").objects.get(pk=message_id)
    return notify_mail.render(message, {"delivery": delivery_id}).body.rstrip("\n").splitlines()


def _portal_name() -> str:
    model("core.PortalSettings").objects.update(name="Портал ИТ-отдела")
    return model("core.PortalSettings").objects.get().name


class _Rows(HTMLParser):
    """Тексты `[data-field="text"]` внутри `li[data-notification="<id>"]` и теги, вложенные в этот элемент."""

    VOID = {"br", "img", "input", "hr", "meta", "link"}

    def __init__(self):
        super().__init__()
        self.text: dict[str, str] = {}
        self.inner: dict[str, list[str]] = {}
        self._li = None
        self._cap = None
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        values = dict(attrs)
        if tag == "li" and "data-notification" in values:
            self._li = values["data-notification"]
        if self._cap is not None:
            self.inner[self._cap].append(tag)
            if tag not in self.VOID:
                self._depth += 1
        elif self._li is not None and values.get("data-field") == "text":
            self._cap, self._depth = self._li, 0
            self.text[self._cap] = ""
            self.inner[self._cap] = []

    def handle_endtag(self, tag):
        if self._cap is not None:
            if self._depth == 0:
                self._cap = None
            else:
                self._depth -= 1
        elif tag == "li":
            self._li = None

    def handle_data(self, data):
        if self._cap is not None:
            self.text[self._cap] += data


def _rows(content: bytes) -> _Rows:
    parser = _Rows()
    parser.feed(content.decode("utf-8"))
    return parser


# --- тексты на портале (FR-316) -------------------------------------------------------------------------

def test_text_new_in_queue_with_number_queue_name_and_subject():
    """FR-316: «Новая заявка #N в очереди «Очередь»: Тема», получатель — участник очереди, ссылка на заявку."""
    unit = org.make_unit(f"Очередь {secrets.token_hex(3)}")
    sd.make_queue(unit)
    member = _employee()
    org.make_member(member, unit)
    ticket = sd.make_ticket(queue=unit, subject="Не печатает принтер")

    drafts = _kind("servicedesk.new_in_queue").build("servicedesk.ticket_created", _created_data(ticket))

    assert [(d.user_id, d.text, d.url, d.object_ref) for d in drafts] == [
        (member.pk, f"Новая заявка #{ticket.number} в очереди «{unit.name}»: Не печатает принтер",
         f"/tickets/{ticket.number}/", f"servicedesk.ticket:{ticket.pk}")]


def test_text_assigned_with_number_and_subject():
    """FR-316: «Вам назначена заявка #N: Тема» — ответственному, не тому, кто назначил."""
    scene = _scene("Сбой VPN")
    actor = _employee()
    org.make_member(actor, scene.unit)

    drafts = _kind("servicedesk.assigned").build(
        "servicedesk.assignee_changed", _assigned_data(scene.work, actor_id=actor.pk))

    assert [(d.user_id, d.text, d.url) for d in drafts] == [
        (scene.assignee.pk, f"Вам назначена заявка #{scene.work.number}: Сбой VPN", f"/tickets/{scene.work.number}/")]


def test_text_requester_replied_with_number_and_subject():
    """FR-316: «Заявитель ответил в заявке #N: Тема» — ответственному."""
    scene = _scene("Ответ по счёту")

    drafts = _build_replied(scene)

    assert [(d.user_id, d.text, d.url) for d in drafts] == [
        (scene.assignee.pk, f"Заявитель ответил в заявке #{scene.work.number}: Ответ по счёту",
         f"/tickets/{scene.work.number}/")]


def test_text_mail_not_delivered_has_only_number():
    """FR-316: «Письмо по заявке #N не доставлено» — только номер, темы в тексте нет."""
    scene = _scene("Тема не для текста")
    data = {"number": scene.work.number, "queue_id": scene.work.queue_id, "assignee_before_id": scene.assignee.pk,
            "assignee_after_id": scene.assignee.pk, "actor_id": None, "mail_kind": "reply", "entry_id": None}

    drafts = _kind("servicedesk.reply_failed").build("servicedesk.mail_failed", data)

    assert [(d.user_id, d.text) for d in drafts] == [
        (scene.assignee.pk, f"Письмо по заявке #{scene.work.number} не доставлено")]
    assert "Тема не для текста" not in drafts[0].text


def _reply_not_sent(scene, reason: str) -> list:
    author = _employee()
    data = {"number": scene.work.number, "entry_id": 1, "reason": reason, "author_id": author.pk, "actor_id": None}
    return _kind("servicedesk.reply_failed").build("servicedesk.reply_not_sent", data)


def test_text_reply_not_sent_quarantine():
    """FR-316: «Ответ по заявке #N не отправлен: вложение в карантине» — ответственному, без темы."""
    scene = _scene("Тема карантина")

    drafts = _reply_not_sent(scene, "quarantine")

    assert [(d.user_id, d.text) for d in drafts] == [
        (scene.assignee.pk, f"Ответ по заявке #{scene.work.number} не отправлен: вложение в карантине")]


def test_text_reply_not_sent_encrypted_archive():
    """FR-316: «Ответ по заявке #N не отправлен: вложение — архив с паролем» — ответственному, без темы."""
    scene = _scene("Тема архива")

    drafts = _reply_not_sent(scene, "encrypted")

    assert [(d.user_id, d.text) for d in drafts] == [
        (scene.assignee.pk, f"Ответ по заявке #{scene.work.number} не отправлен: вложение — архив с паролем")]


def test_text_channel_unbound_for_telegram_and_for_max(caplog, django_capture_on_commit_callbacks):
    """FR-316: «Telegram отвязан: бот недоступен» и «MAX отвязан: бот недоступен», ссылка — «Мои уведомления»."""
    from apps.notify.services import binding

    user = _employee()
    Notification = model("notify.Notification")
    expected = {"telegram": "Telegram отвязан: бот недоступен", "max": "MAX отвязан: бот недоступен"}
    for channel, text in expected.items():
        _bind(user, channel)
        with caplog.at_level(logging.ERROR, logger="apps.core.events"):
            with django_capture_on_commit_callbacks(execute=True):
                with transaction.atomic():
                    assert binding.unbind(user, channel, reason="bot_unavailable") is True
        note = Notification.objects.filter(user=user, kind="notify.channel_unbound").order_by("-id").first()
        assert (note.text, note.url) == (text, "/me/notifications/")
    assert Notification.objects.filter(user=user, kind="notify.channel_unbound").count() == 2
    assert not [r for r in caplog.records if r.name == "apps.core.events" and r.levelno >= logging.ERROR]


def test_text_new_device_has_browser_and_time():
    """FR-316, NFR-307: «Вход с нового устройства (<браузер>, ДД.ММ.ГГГГ ЧЧ:ММ)»; платформы в тексте нет."""
    user = _employee()
    at = datetime(2026, 10, 10, 11, 5, tzinfo=dt_timezone.utc)

    drafts = _kind("core.new_device").build(
        "core.new_device", {"user_id": user.pk, "browser": "Chrome 126", "platform": "Windows 11", "at": at})

    assert [(d.user_id, d.text, d.url, d.object_ref) for d in drafts] == [
        (user.pk, "Вход с нового устройства (Chrome 126, 10.10.2026 14:05)", "/me/security/", "")]
    assert "Windows" not in drafts[0].text


def test_text_password_changed():
    """FR-316: «Пароль изменён» — самому сотруднику, ссылка на безопасность профиля."""
    user = _employee()

    drafts = _kind("core.password_changed").build("core.password_changed", {"user_id": user.pk, "actor_id": user.pk})

    assert [(d.user_id, d.text, d.url, d.object_ref) for d in drafts] == [
        (user.pk, "Пароль изменён", "/me/security/", "")]


def test_text_second_factor_reset():
    """FR-316: «Второй фактор сброшен» — сотруднику, у которого сбросили; действие системы (`actor_id=None`) допустимо."""
    user = _employee()

    drafts = _kind("core.second_factor_reset").build(
        "core.second_factor_reset", {"user_id": user.pk, "actor_id": None})

    assert [(d.user_id, d.text, d.url, d.object_ref) for d in drafts] == [
        (user.pk, "Второй фактор сброшен", "/me/security/", "")]


def test_portal_and_email_body_carry_the_same_text():
    """FR-316: текст в списке портала, в `Notification.text`, в ответе `build` и в теле письма — один и тот же."""
    from apps.notify.services import dispatch
    from apps.notify.services import mail as notify_mail

    scene = _scene("Общий текст")
    drafts = _build_assigned(scene)
    assert len(drafts) == 1
    ids = dispatch.create("servicedesk.assigned", drafts)
    note = model("notify.Notification").objects.get(pk=ids[0])
    delivery, _ = model("notify.Delivery").objects.get_or_create(
        notification=note, channel="email",
        defaults={"state": "waiting", "due_at": timezone.now() - timedelta(seconds=5)})

    message_id = notify_mail.queue_item(delivery)
    mail_lines = _body(message_id, delivery.pk)
    page = support.logged_in(scene.assignee).get("/notifications/")

    assert page.status_code == 200
    assert note.text == drafts[0].text
    assert _rows(page.content).text[str(note.pk)].strip() == drafts[0].text
    assert mail_lines[2] == drafts[0].text


# --- внешние тексты (FR-317) ----------------------------------------------------------------------------

def test_external_texts_of_four_sd_kinds_are_verbatim():
    """FR-317: `external_text` четырёх видов заявок дословно по § 15.2, и тот же текст отдаёт служба `delivery`;
    у сводки — «У вас N новых уведомлений» с согласованием по правилу 15.6 (решение 14 задач)."""
    from apps.notify.services import delivery as dlv

    user = _employee()
    for code, text in EXTERNAL.items():
        assert _kind(code).external_text == text
        note = _notification(user, code, f"#1 тема {code}")
        assert dlv.external_text(_delivery(note, "telegram")) == text

    digest = model("notify.Digest").objects.create(user=user, count_message=1, count_email=1, notification_ids=[])
    row = _delivery_for_digest(digest, "telegram")
    forms = {1: "У вас 1 новое уведомление", 2: "У вас 2 новых уведомления", 4: "У вас 4 новых уведомления",
             5: "У вас 5 новых уведомлений", 11: "У вас 11 новых уведомлений", 12: "У вас 12 новых уведомлений",
             14: "У вас 14 новых уведомлений", 20: "У вас 20 новых уведомлений", 21: "У вас 21 новое уведомление",
             22: "У вас 22 новых уведомления", 25: "У вас 25 новых уведомлений", 101: "У вас 101 новое уведомление",
             111: "У вас 111 новых уведомлений"}
    for count, expected in forms.items():
        model("notify.Digest").objects.filter(pk=digest.pk).update(count_message=count)
        assert dlv.external_text(model("notify.Delivery").objects.get(pk=row.pk)) == expected


def _delivery_for_digest(digest, channel: str):
    return model("notify.Delivery").objects.create(
        digest=digest, channel=channel, state="waiting", due_at=timezone.now() - timedelta(seconds=5),
        enqueued_at=timezone.now())


def test_telegram_max_and_web_push_carry_only_external_text_and_notifications_link(bots_on, webpush_on):
    """FR-317: сообщение бота — экранированный внешний текст и кнопка на страницу уведомлений; нагрузка Web Push —
    заголовок, ссылка на `/notifications/` и метка; номера и темы заявки в них нет."""
    from django.conf import settings
    from apps.notify.services import delivery as dlv

    scene = _scene("Тема для проверки каналов")
    user = scene.assignee
    chats = {channel: _bind(user, channel).chat_id for channel in ("telegram", "max")}
    pair = notify_support.browser_keys()
    sub = notify_support.subscribe(user, keys=pair)
    link = settings.PORTAL_URL.rstrip("/") + "/notifications/"
    assert dlv.BUTTON_LABEL == BUTTON

    for code, ext in EXTERNAL.items():
        note = _notification(user, code, f"#{scene.work.number} {scene.work.subject}")
        for channel in ("telegram", "max"):
            row = _delivery(note, channel)
            with notify_support.fake_bot_send(channel) as fake:
                assert dlv.send_delivery(row.pk) == "sent"
            assert fake.calls == [(chats[channel], html.escape(ext), (BUTTON, link))]
        row = _delivery(note, "webpush")
        with notify_support.webpush_capture() as capture:
            assert dlv.send_delivery(row.pk) == "sent"
        assert [r.url for r in capture.requests] == [sub.endpoint]
        assert capture.decrypt(capture.requests[0], pair) == {
            "title": ext, "url": "/notifications/", "tag": f"n-{note.pk}"}


def test_external_texts_contain_no_number_subject_name_or_address():
    """FR-317: во внешнем тексте нет номера заявки, темы, имени и адреса заявителя, хотя в `Notification.text` они есть."""
    from apps.notify.services import delivery as dlv

    scene = _scene("Секретная тема заказа", requester_name="Иванова Мария Петровна",
                   requester_email="maria.ivanova@client.test")
    user = scene.assignee
    for code, expected in EXTERNAL.items():
        note = _notification(
            user, code,
            f"#{scene.work.number} {scene.work.subject} {scene.requester.full_name} {scene.requester.email}")
        for channel in ("telegram", "max", "webpush"):
            ext = dlv.external_text(_delivery(note, channel))
            assert ext == expected
            assert str(scene.work.number) not in ext
            assert "Секретная" not in ext and "Иванова" not in ext and "Мария" not in ext
            assert "@" not in ext and "client.test" not in ext
            assert not re.search(r"\d", ext)


# --- тема: 100 знаков (FR-316) --------------------------------------------------------------------------

def _texts(subject: str) -> dict:
    """Тексты трёх видов заявок с этой темой: `{код: текст}` (все получатели вида получают один текст)."""
    scene = _scene(subject)
    result = {}
    for code, drafts in (("servicedesk.new_in_queue", _build_new_in_queue(scene)),
                         ("servicedesk.assigned", _build_assigned(scene)),
                         ("servicedesk.requester_replied", _build_replied(scene))):
        assert drafts, code
        assert len({d.text for d in drafts}) == 1
        result[code] = drafts[0].text
    return result


def test_subject_of_100_chars_kept_whole():
    """FR-316: тема из 100 знаков входит в текст целиком, без многоточия."""
    subject = "".join(chr(0x430 + i % 32) for i in range(100))
    assert len(subject) == 100

    for code, text in _texts(subject).items():
        assert text.endswith(f": {subject}"), code
        assert "…" not in text, code


def test_subject_of_101_chars_becomes_99_chars_and_ellipsis():
    """FR-316: тема из 101 знака — первые 99 знаков и «…»."""
    subject = "".join(chr(0x430 + i % 32) for i in range(101))
    assert len(subject) == 101

    for code, text in _texts(subject).items():
        assert text.endswith(f": {subject[:99]}…"), code
        assert subject[:100] not in text, code


def test_subject_truncation_counts_characters_not_bytes_for_multibyte_text():
    """FR-316: счёт идёт по символам, а не по байтам: 100 четырёхбайтных знаков целы, 101 — первые 99 и «…»."""
    whole = "😀" * 100
    for code, text in _texts(whole).items():
        assert text.endswith(f": {whole}"), code
        assert "…" not in text, code

    mixed = "я" * 50 + "😀" * 51
    assert len(mixed) == 101
    for code, text in _texts(mixed).items():
        assert text.endswith(f": {mixed[:99]}…"), code


# --- время «Вход с нового устройства» (NFR-307) ---------------------------------------------------------

def test_new_device_time_is_europe_moscow():
    """NFR-307, FR-316: время в тексте — по Москве (UTC+3, без перехода на летнее время), формат ДД.ММ.ГГГГ ЧЧ:ММ;
    смена даты при переводе, момент в чужом часовом поясе."""
    user = _employee()
    cases = [
        (datetime(2026, 10, 10, 11, 5, tzinfo=dt_timezone.utc), "10.10.2026 14:05"),
        (datetime(2026, 10, 10, 21, 30, tzinfo=dt_timezone.utc), "11.10.2026 00:30"),
        (datetime(2026, 12, 31, 21, 30, tzinfo=dt_timezone.utc), "01.01.2027 00:30"),
        (datetime(2026, 7, 1, 9, 0, tzinfo=dt_timezone.utc), "01.07.2026 12:00"),
        (datetime(2026, 10, 10, 9, 5, tzinfo=ZoneInfo("America/New_York")), "10.10.2026 16:05"),
    ]
    for at, moscow in cases:
        drafts = _kind("core.new_device").build(
            "core.new_device", {"user_id": user.pk, "browser": "Firefox 128", "platform": "Linux", "at": at})
        assert [d.text for d in drafts] == [f"Вход с нового устройства (Firefox 128, {moscow})"], at


# --- разметка в теме (NFR-311) --------------------------------------------------------------------------

def test_subject_markup_shown_as_text_on_portal_pages():
    """NFR-311: разметка в теме заявки показана текстом на странице уведомлений и в панели колокольчика."""
    scene = _scene(MARKUP_SUBJECT)
    draft = _build_assigned(scene)[0]
    note = _notification(scene.assignee, "servicedesk.assigned", draft.text, draft.url)
    assert MARKUP_SUBJECT in note.text
    web = support.logged_in(scene.assignee)

    for path in ("/notifications/", "/notifications/bell/"):
        response = web.get(path)
        assert response.status_code == 200, path
        body = response.content.decode("utf-8")
        assert f"<b>{MARKER}</b>" not in body, path
        assert f"&lt;b&gt;{MARKER}&lt;/b&gt;" in body, path
        rows = _rows(response.content)
        assert rows.text[str(note.pk)].strip() == note.text, path
        assert set(rows.inner[str(note.pk)]) <= {"a"}, path


def test_subject_markup_in_email_is_plain_text_not_markup():
    """NFR-311, FR-316: письмо — простой текст: разметка темы стоит в теле как есть, без экранирования и без `&lt;`."""
    from apps.notify.services import mail as notify_mail

    scene = _scene(MARKUP_SUBJECT)
    draft = _build_assigned(scene)[0]
    note = _notification(scene.assignee, "servicedesk.assigned", draft.text, draft.url)
    row = _delivery(note, "email")

    message_id = notify_mail.queue_item(row)
    lines = _body(message_id, row.pk)

    assert lines[2] == note.text
    assert f"<b>{MARKER}</b> & <i>курсив</i>" in lines[2]
    assert not any("&lt;" in line or "&amp;" in line or "&gt;" in line for line in lines)
    assert MARKER not in model("mail.MailMessage").objects.get(pk=message_id).subject


def test_subject_markup_never_reaches_bot_message_and_dynamic_parts_are_html_escaped(bots_on):
    """NFR-311, FR-317: тема с разметкой не попадает в сообщение бота; динамическая часть (внешний текст вида с `<b>&`)
    уходит экранированной: `&lt;b&gt;&amp;`."""
    from apps.core import extensions
    from apps.core.extensions import NotificationKind
    from apps.notify.services import delivery as dlv

    scene = _scene(MARKUP_SUBJECT)
    user = scene.assignee
    chats = {channel: _bind(user, channel).chat_id for channel in ("telegram", "max")}
    draft = _build_assigned(scene)[0]
    note = _notification(user, "servicedesk.assigned", draft.text, draft.url)
    for channel in ("telegram", "max"):
        row = _delivery(note, channel)
        with notify_support.fake_bot_send(channel) as fake:
            assert dlv.send_delivery(row.pk) == "sent"
        assert fake.calls[0][0] == chats[channel]
        assert fake.calls[0][1] == html.escape(EXTERNAL["servicedesk.assigned"])
        assert MARKER not in fake.calls[0][1] and "<" not in fake.calls[0][1]

    kind = NotificationKind(code="test.markup", title="Проверка разметки", module="Тест", external_text="<b>&",
                            default_channels=("portal", "telegram", "max"))
    with extensions.empty():
        notify_support.register_kind(kind)
        probe = _notification(user, "test.markup", "Текст для портала", "/me/notifications/")
        for channel in ("telegram", "max"):
            row = _delivery(probe, channel)
            with notify_support.fake_bot_send(channel) as fake:
                assert dlv.send_delivery(row.pk) == "sent"
            assert fake.calls[0][1] == "&lt;b&gt;&amp;"


def test_web_push_payload_has_only_external_text_never_subject_markup(webpush_on):
    """NFR-311, FR-317: нагрузка Web Push — ровно заголовок (внешний текст), ссылка `/notifications/` и метка;
    ни темы, ни разметки, ни номера заявки в ней нет."""
    from apps.notify.services import delivery as dlv

    scene = _scene(MARKUP_SUBJECT)
    user = scene.assignee
    pair = notify_support.browser_keys()
    notify_support.subscribe(user, keys=pair)
    draft = _build_assigned(scene)[0]
    note = _notification(user, "servicedesk.assigned", draft.text, draft.url)
    row = _delivery(note, "webpush")

    with notify_support.webpush_capture() as capture:
        assert dlv.send_delivery(row.pk) == "sent"

    payload = capture.decrypt(capture.requests[0], pair)
    assert payload == {"title": EXTERNAL["servicedesk.assigned"], "url": "/notifications/", "tag": f"n-{note.pk}"}
    dumped = json.dumps(payload, ensure_ascii=False)
    assert MARKER not in dumped and "<" not in dumped and str(scene.work.number) not in payload["title"]


# --- письмо (FR-316) ------------------------------------------------------------------------------------

def test_email_for_employee_has_portal_name_text_and_link_without_secrets(settings):
    """FR-316: тело письма — название портала, полный текст, ссылка на открытие и ссылка на настройки (§ 10.2);
    паролей, кодов и ссылок входа нет."""
    from apps.notify.services import mail as notify_mail

    name = _portal_name()
    scene = _scene("Тело письма")
    draft = _build_assigned(scene)[0]
    note = _notification(scene.assignee, "servicedesk.assigned", draft.text, draft.url)
    row = _delivery(note, "email")
    base = settings.PORTAL_URL.rstrip("/")

    message_id = notify_mail.queue_item(row)
    lines = _body(message_id, row.pk)

    assert lines == [name, "", note.text, "", f"Открыть: {base}/notifications/{note.pk}/open/", "",
                     f"Настроить уведомления: {base}/me/notifications/"]
    text = "\n".join(lines)
    assert re.findall(r"https?://\S+", text) == [f"{base}/notifications/{note.pk}/open/", f"{base}/me/notifications/"]
    assert not re.search(r"(?i)token|password|парол|/activate|/recover", text)


def test_email_subject_has_no_ticket_number_or_subject():
    """FR-316: тема письма — внешний текст вида; номера и темы заявки в ней нет (в теле они есть)."""
    from apps.notify.services import mail as notify_mail

    scene = _scene("Тема только в теле")
    draft = _build_assigned(scene)[0]
    note = _notification(scene.assignee, "servicedesk.assigned", draft.text, draft.url)
    row = _delivery(note, "email")

    message_id = notify_mail.queue_item(row)
    message = model("mail.MailMessage").objects.get(pk=message_id)

    assert message.subject == EXTERNAL["servicedesk.assigned"]
    assert str(scene.work.number) not in message.subject and "Тема только в теле" not in message.subject
    assert message.template == "notify.item"


def test_email_for_deleted_notification_says_notification_no_longer_available(settings):
    """FR-316: если уведомление к моменту отправки удалено, письмо — нейтральный текст «Уведомление больше недоступно»
    и ссылка на список; тема остаётся прежней."""
    from apps.notify.services import mail as notify_mail

    name = _portal_name()
    scene = _scene("Будет удалено")
    draft = _build_assigned(scene)[0]
    note = _notification(scene.assignee, "servicedesk.assigned", draft.text, draft.url)
    row = _delivery(note, "email")
    message_id = notify_mail.queue_item(row)
    delivery_id = row.pk
    subject_before = model("mail.MailMessage").objects.get(pk=message_id).subject

    note.delete()
    lines = _body(message_id, delivery_id)

    assert lines == [name, "", "Уведомление больше недоступно.", "",
                     f"Все уведомления: {settings.PORTAL_URL.rstrip('/')}/notifications/"]
    assert model("mail.MailMessage").objects.get(pk=message_id).subject == subject_before == EXTERNAL[
        "servicedesk.assigned"]
