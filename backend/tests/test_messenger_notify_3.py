"""T-8116c: внешние тексты, письмо через 15 минут, тихие часы, открытая беседа, ссылка и портал (FR-663, FR-664,
FR-665, FR-666, FR-671, NFR-705).

Источники: PLAN-008 «Уведомления» (постоянный внешний текст двух видов без ФИО, названий и отрывков; портал сразу,
письмо по `email_delay_minutes` = 15; тихие часы держат почту и копят до сводки с началом рабочего дня; открытие
беседы и `read` гасят уведомления чата; ссылка `/messenger/chats/<id>/#m<id>`; номера сообщения вид не получает —
«сообщение живо» проверяется ссылкой; сотрудник отключает почту и внешние каналы, портал приходит всегда), TASKS-008
T-8116c; CONTRACT-008: 5.2 (`messages.send`), 5.3 (`notify_rules`, `read.mark`, `unread.counts`), 7.1 (внешний
текст), 7.2 (черновик, ссылка, `object_ref`), 7.3 (почта, тихие часы, сводка, портал), 10.2 (`read/`, `delete/`),
13.3 (тексты интерфейса); ADR-0011 п. 2, 4, 6, 9.

Проверки идут путями среза: сообщение отправляет `apps.messenger.services.messages.send`, уведомления и доставки
читаются из `notify.Notification`/`notify.Delivery`; письмо и сводку ставит обход `notify` (`run_tick`), внешние
каналы отправляются подменёнными адаптерами (`fake_bot_send`, `webpush_capture`). Код среза на уровне модуля не
импортируется (CONTRACT-008, «Правила для всех тестов среза»). Секретов и ПДн нет: адреса и телефоны не создаются.

Допущения писателя (см. отчёт T-8116c): 1) «письмо через 15 минут, если не прочитано» проверяется данными — обход
`notify` после срока ставит письмо непрочитанному и пропускает прочитанному с причиной `read`, таймера среза нет;
2) тихие часы задаются «своими часами» (понедельник 09:00–18:00), чтобы проверка не зависела от календаря стенда;
3) сводка уходит с началом ближайшего рабочего времени и содержит накопленное уведомление; 4) у отключённых каналов
строк `notify.Delivery` не создаётся вовсе, портал — строка `notify.Notification`; 5) после удаления чата уведомление
остаётся в истории портала, а ссылка отвечает тем же 404, что несуществующий чат.
"""
from datetime import date, datetime, time, timedelta
from html import escape
from zoneinfo import ZoneInfo

import pytest
from django.conf import settings as django_settings
from django.utils import timezone

from tests import support
from tests import support_messenger as messenger
from tests import support_notify as notify
from tests.support import model

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
MON = date(2026, 6, 15)  # понедельник
MESSAGE_KIND, MENTION_KIND = "messenger.message", "messenger.mention"
# внешний текст видов (CONTRACT-008, 7.1): код вида -> постоянный текст для Telegram, MAX и Web Push
EXTERNAL = {row[0]: row[7] for row in messenger.MESSENGER_KINDS}
CHANNELS = ("telegram", "max", "webpush")
BUTTON = "Открыть уведомления"


# --- помощники только этого файла (общие помощники среза не правятся) ------------------------------------------

def at(day: date, hour: int = 0, minute: int = 0, second: int = 0) -> datetime:
    """Момент по Москве."""
    return datetime(day.year, day.month, day.day, hour, minute, second, tzinfo=MSK)


def _user(value):
    """Сотрудник из `Session` или самого пользователя."""
    return value.user if isinstance(value, messenger.Session) else value


def _employee(name: str):
    return messenger.make_user(full_name=name)


def _send(chat, author, text: str):
    """`messages.send(chat, author, text)` — путь службы со всей транзакцией, включая уведомления."""
    from apps.messenger.services import messages

    return messages.send(chat, _user(author), text)


def _marks(*sessions) -> str:
    """Маркеры упоминаний людей: `@[u<id>]` через пробел (CONTRACT-008, 5.2)."""
    return " ".join(f"@[u{_user(session).pk}]" for session in sessions)


def _notes(user=None, kind: str | None = None):
    """Уведомления мессенджера; `user` — `Session` или `core.User`."""
    rows = model("notify.Notification").objects.filter(kind__startswith="messenger.")
    if user is not None:
        rows = rows.filter(user=_user(user))
    if kind is not None:
        rows = rows.filter(kind=kind)
    return rows


def _note(user, kind: str):
    return _notes(user, kind).get()


def _prefs(user, mode: str = "none", **extra):
    """Строка `notify.UserNotifySettings`; по умолчанию «Без тихих часов» (письмо не зависит от часов хоста)."""
    return model("notify.UserNotifySettings").objects.update_or_create(
        user=_user(user), defaults={"quiet_mode": mode, **extra})[0]


def _delivery(note, channel: str):
    """Доставка внешнего канала, готовая к отправке (срок в прошлом), как в тестах ленты."""
    now = timezone.now()
    return model("notify.Delivery").objects.create(
        notification=note, channel=channel, state="waiting", due_at=now - timedelta(seconds=5), enqueued_at=now)


def _binding(user, channel: str) -> str:
    """Привязка бота сотрудника: `chat_id` для подменённого адаптера Telegram или MAX."""
    row, _ = model("notify.ChatBinding").objects.get_or_create(
        user=_user(user), channel=channel, defaults={"chat_id": f"c{_user(user).pk}{channel}"})
    return row.chat_id


def _webpush_ready(user):
    """Ключи браузера и подписка Web Push сотрудника."""
    pair = notify.browser_keys()
    subscription = notify.subscribe(_user(user), keys=pair)
    return pair, subscription


def _counts(user) -> dict:
    from apps.messenger.services import unread

    return unread.counts(_user(user))


def _letters(template: str = "notify.item"):
    return model("mail.MailMessage").objects.filter(template=template)


# --- внешний текст (FR-664, NFR-705) ----------------------------------------------------------------------------

def test_external_text_has_no_names_or_message_text_in_telegram_max_and_push(bots_on, webpush_on):
    """FR-664, NFR-705: в Telegram, MAX и Web Push у обоих видов уходит только постоянный внешний текст и ссылка —
    без ФИО автора и упомянутого, названия чата и отрывка сообщения, хотя в портальном тексте они есть; клиенты
    получают ровно каталог 7.1 («Новое сообщение в чате», «Вас упомянули в чате»)."""
    from apps.notify.services import delivery as dlv

    author = _employee("Анна Авторова")
    mentioned = _employee("Алиса Упомянутая")
    other = _employee("Борис Обычный")
    chat = messenger.group(author, [mentioned, other], title="Тайная Беседа")
    body = "секретный план на завтра"
    _send(chat, author, f"{body} {_marks(mentioned)}")

    mention_note = _note(mentioned, MENTION_KIND)
    message_note = _note(other, MESSAGE_KIND)
    for note in (mention_note, message_note):
        assert "Анна Авторова" in note.text and "Тайная Беседа" in note.text, note.text
        assert body not in note.text, "в уведомление попал отрывок сообщения"

    leaks = ("Анна", "Авторова", "Алиса", "Упомянутая", "Борис", "Обычный", "Тайная", "Беседа", body)
    base = django_settings.PORTAL_URL.rstrip("/")
    for note in (mention_note, message_note):
        external = EXTERNAL[note.kind]
        for leak in leaks:
            assert leak not in external, (note.kind, leak)
        for channel in CHANNELS:
            row = _delivery(note, channel)
            assert dlv.external_text(row) == external, (note.kind, channel)
            if channel == "webpush":
                pair, subscription = _webpush_ready(note.user)
                with notify.webpush_capture() as capture:
                    assert dlv.send_delivery(row.pk) == "sent"
                assert [request.url for request in capture.requests] == [subscription.endpoint]
                payload = capture.decrypt(capture.requests[0], pair)
                assert payload == {"title": external, "url": "/notifications/", "tag": f"n-{note.pk}"}
                sent = str(payload)
            else:
                chat_id = _binding(note.user, channel)
                with notify.fake_bot_send(channel) as fake:
                    assert dlv.send_delivery(row.pk) == "sent"
                assert fake.calls == [(chat_id, escape(external), (BUTTON, base + "/notifications/"))], (
                    note.kind, channel)
                sent = str(fake.calls)
            for leak in leaks:
                assert leak not in sent, (note.kind, channel, leak)


# --- письмо через 15 минут (FR-663) -----------------------------------------------------------------------------

def test_email_sent_after_fifteen_minutes_if_unread(clock, django_capture_on_commit_callbacks):
    """FR-663: портал сразу, письмо — через `email_delay_minutes` (15) и только непрочитанному; прочитавший беседу
    до срока письма не получает (причина `read`), письмо не отмечает уведомление прочитанным, тема — внешний текст
    вида без названия чата и ФИО."""
    clock.set(at(MON, 10, 0))
    author = _employee("Автор Письма")
    reader = _employee("Прочитавший Участник")
    sleeper = _employee("Непрочитавший Участник")
    for member in (reader, sleeper):
        _prefs(member)
    chat = messenger.group(author, [reader, sleeper], title="Беседа Письма")

    _send(chat, author, "Проверьте, пожалуйста")
    note = _note(sleeper, MESSAGE_KIND)
    delivery = note.deliveries.get(channel="email")
    assert note.read_at is None and delivery.state == "waiting"
    assert delivery.due_at == note.created_at + timedelta(minutes=15), "срок письма не 15 минут"

    with django_capture_on_commit_callbacks(execute=True):
        assert reader.client.get(f"/messenger/chats/{chat.pk}/").status_code == 200
    assert _note(reader, MESSAGE_KIND).read_at is not None, "открытие беседы не погасило уведомление"

    clock.advance(minutes=14)
    notify.run_tick()
    delivery.refresh_from_db()
    assert delivery.state == "waiting" and delivery.mail_id is None, "письмо ушло раньше срока"
    assert not _letters().exists()

    clock.advance(minutes=1, seconds=1)
    notify.run_tick()
    delivery.refresh_from_db()
    assert (delivery.state, delivery.attempts) == ("sent", 1)
    assert delivery.mail_id is not None
    letter = model("mail.MailMessage").objects.get(pk=delivery.mail_id)
    assert letter.template == "notify.item" and letter.to == sleeper.user.email
    assert letter.subject == EXTERNAL[MESSAGE_KIND], f"тема письма: {letter.subject!r}"
    note.refresh_from_db()
    assert note.read_at is None, "письмо отметило уведомление прочитанным"

    read_delivery = model("notify.Delivery").objects.get(notification=_note(reader, MESSAGE_KIND), channel="email")
    assert (read_delivery.state, read_delivery.reason) == ("skipped", "read"), "прочитавшему ушло письмо"
    assert _letters().count() == 1


# --- тихие часы и утренняя сводка (FR-663) ----------------------------------------------------------------------

def test_quiet_hours_hold_email_and_send_digest_at_workday_start(clock):
    """FR-663, ADR-0011 п. 6: вечером вне «своих часов» письмо по сроку не уходит, а откладывается (`held`) до сводки;
    срок сводки — начало ближайшего рабочего времени; утром сводка содержит накопленное уведомление, письмо уходит
    одно, исходная доставка становится `digested`, уведомление остаётся на портале непрочитанным."""
    clock.set(at(MON, 20, 0))
    author = _employee("Автор Вечера")
    member = _employee("Вечерний Читатель")
    row = _prefs(member, "own", own_days=[0], own_start=time(9, 0), own_end=time(18, 0))
    chat = messenger.group(author, [member], title="Вечерняя Беседа")

    _send(chat, author, "Сообщение после работы")
    note = _note(member, MESSAGE_KIND)
    delivery = note.deliveries.get(channel="email")
    assert delivery.state == "waiting"
    assert delivery.due_at == note.created_at + timedelta(minutes=15)

    clock.advance(minutes=16)  # срок письма наступил, но тихие часы ещё идут
    notify.run_tick()
    delivery.refresh_from_db()
    row.refresh_from_db()
    assert (delivery.state, delivery.due_at) == ("held", None), "в тихие часы письмо не отложено"
    assert row.digest_due_at == at(MON + timedelta(days=1), 9, 0), "срок сводки сдвинулся"
    assert not _letters().exists(), "письмо ушло в тихие часы"

    clock.set(at(MON + timedelta(days=1), 9, 0, 5))
    tick = notify.run_tick()
    assert tick["digests"] == 1, "с началом рабочего дня сводка не собрана"
    digest = model("notify.Digest").objects.get(user=member.user)
    assert digest.notification_ids == [note.pk]
    letter = model("mail.MailMessage").objects.get(template="notify.digest")
    assert letter.to == member.user.email
    assert letter.subject == "За нерабочее время: 1 уведомление", f"тема сводки: {letter.subject!r}"
    delivery.refresh_from_db()
    assert delivery.state == "digested", "накопленная доставка не ушла в сводку"
    note.refresh_from_db()
    assert note.read_at is None, "уведомление пропало с портала"
    row.refresh_from_db()
    assert row.digest_due_at is None


# --- открытая беседа (FR-666) -----------------------------------------------------------------------------------

def test_message_in_open_chat_not_unread_in_flow(clock, django_capture_on_commit_callbacks):
    """FR-666, сценарий 9 п. 6: сообщение, пришедшее в открытую беседу, после `read` клиента не остаётся ни в числе
    непрочитанных, ни в непрочитанном потоке уведомлений; у закрытой беседы уведомление остаётся непрочитанным и число
    чата растёт. Уведомление создаёт настоящая отправка, а не прямая запись."""
    clock.set(at(MON, 9, 0))
    author = _employee("Автор Открытой")
    reader = _employee("Читатель Открытой")
    closed = _employee("Читатель Закрытой")
    chat = messenger.group(author, [reader, closed], title="Открытая Беседа")
    with django_capture_on_commit_callbacks(execute=True):
        assert reader.client.get(f"/messenger/chats/{chat.pk}/").status_code == 200

    clock.advance(minutes=1)
    sent = author.client.post(f"/messenger/chats/{chat.pk}/messages/", {"text": "Пришло в открытую беседу"})
    assert sent.status_code == 302, f"отправка: {sent.status_code}"
    ref = f"messenger.chat:{chat.pk}"
    note = model("notify.Notification").objects.get(user=reader.user, object_ref=ref)
    assert note.read_at is None, "портал должен сначала показать уведомление непрочитанным"
    assert _counts(reader).get(chat.pk) == 1

    clock.advance(minutes=1)
    with django_capture_on_commit_callbacks(execute=True):
        marked = reader.client.post(f"/messenger/chats/{chat.pk}/read/",
                                    {"at": (at(MON, 9, 2)).isoformat()})
    assert marked.status_code == 302, f"отметка прочтения: {marked.status_code}"
    note.refresh_from_db()
    assert note.read_at is not None, "уведомление открытой беседы осталось непрочитанным"
    assert _counts(reader).get(chat.pk, 0) == 0, "сообщение осталось непрочитанным у открытой беседы"
    assert not model("notify.Notification").objects.filter(
        user=reader.user, read_at__isnull=True, object_ref=ref).exists(), "уведомление осталось в потоке"

    closed_note = model("notify.Notification").objects.get(user=closed.user, object_ref=ref)
    assert closed_note.read_at is None, "у закрытой беседы уведомление прочитано без открытия"
    assert _counts(closed).get(chat.pk) == 1


# --- ссылка и удалённый чат (FR-663, FR-671) ---------------------------------------------------------------------

def test_notification_links_to_chat_message_and_deleted_chat_gives_404(clock):
    """FR-663, FR-671: ссылка уведомления — `/messenger/chats/<id>/#m<id>`, у участника открывает беседу, у
    постороннего и после удаления чата отвечает тем же 404, что несуществующий чат; уведомление остаётся в истории
    портала со своей ссылкой."""
    clock.set(at(MON, 12, 0))
    author = _employee("Автор Ссылки")
    member = _employee("Читатель Ссылки")
    outsider = _employee("Посторонний Ссылки")
    chat = messenger.group(author, [member], title="Беседа Ссылки")
    message = _send(chat, author, "Ссылка на сообщение")

    note = _note(member, MESSAGE_KIND)
    link = f"/messenger/chats/{chat.pk}/#m{message.pk}"
    assert note.url == link, f"ссылка уведомления: {note.url!r}"
    assert note.object_ref == f"messenger.chat:{chat.pk}"

    opened = member.client.get(note.url)
    assert opened.status_code == 200, f"ссылка участника: {opened.status_code}"
    assert f'id="m{message.pk}"' in opened.content.decode(), "в беседе нет сообщения по ссылке"

    foreign = outsider.client.get(note.url)
    assert foreign.status_code == 404, f"ссылка постороннего: {foreign.status_code}"
    assert support.same_failure(foreign, outsider.client.get("/messenger/chats/999999/")), (
        "чужой чат отвечает иначе, чем несуществующий")

    deleted = author.client.post(f"/messenger/chats/{chat.pk}/delete/", {"confirm": "1"})
    assert deleted.status_code == 302, f"удаление чата: {deleted.status_code}"

    gone = member.client.get(note.url)
    assert gone.status_code == 404, f"ссылка удалённого чата: {gone.status_code}"
    assert support.same_failure(gone, member.client.get("/messenger/chats/999999/")), (
        "удалённый чат отвечает иначе, чем несуществующий")
    note.refresh_from_db()
    assert note.url == link, "ссылка уведомления изменилась после удаления чата"


# --- портал всегда (FR-665) -------------------------------------------------------------------------------------

def test_portal_always_on_even_with_all_channels_off(clock):
    """FR-665, ADR-0011 п. 4: при выключенных почте и внешних каналах у обоих видов портал всё равно получает
    уведомления — строки `notify.Notification` есть и непрочитаны, строк внешних доставок нет; в действующей таблице
    ячейка «портал» включена, «почта» выключена."""
    from apps.notify.services import prefs

    clock.set(at(MON, 11, 0))
    author = _employee("Автор Тихого")
    member = _employee("Тихий Читатель")
    mentioned = _employee("Тихий Упомянутый")
    empty = {MESSAGE_KIND: [], MENTION_KIND: []}
    for person in (member, mentioned):
        model("notify.UserNotifySettings").objects.create(user=person.user, matrix=empty, quiet_mode="none")
    chat = messenger.group(author, [member, mentioned], title="Тихая Беседа")
    _send(chat, author, f"Тихо {_marks(mentioned)}")

    mine = _note(member, MESSAGE_KIND)
    mention = _note(mentioned, MENTION_KIND)
    for note in (mine, mention):
        assert note.read_at is None, "портал не показал уведомление"
    assert not model("notify.Delivery").objects.filter(notification__in=[mine, mention]).exists(), (
        "при выключенных каналах созданы внешние доставки")

    table = prefs.effective(member.user)
    for code in (MESSAGE_KIND, MENTION_KIND):
        cells = next(row.cells for row in table.rows if row.kind.code == code)
        assert cells["portal"] is True, f"{code}: портал выключен"
        assert cells["email"] is False, f"{code}: почта осталась включённой"
        assert not any(cells[channel] for channel in ("push", "telegram", "max")), f"{code}: внешний канал включён"