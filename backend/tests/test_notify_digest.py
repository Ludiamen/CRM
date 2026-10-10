"""T-4112: сводка накопленного за тихие часы — письмо и одно сообщение (FR-327, FR-330, FR-331, FR-345).

Сценарии 7 и 3 спеки среза 004. Сводку собирает `digest.build(user_id)` (его ставит обход `notify_tick`, когда
`digest_due_at` наступил): письмо «За нерабочее время: N уведомлений» (шаблон `notify.digest`) и одно сообщение
«У вас N новых уведомлений» в первый по порядку канал Telegram, MAX, Web Push, у которого есть `held`
(CONTRACT-004, 6.11, 10.1, 10.2, 15.6, решение E20). Виды — настоящие (`servicedesk.new_in_queue`, `core.password_changed`):
сводка перепроверяет `still_relevant` через каталог. Накопленное (`held`) и срок сводки задаются прямой записью в
базе, кроме двух тестов, где письмо уходит в `held` самим `mail.send_due` (FR-327). Режим «Свои часы» (09:00-18:00
ежедневно) не зависит от календаря среза 002. Код среза 004 на уровне модуля не импортируется: имена берутся внутри
тестов (CONTRACT-004, шапка).
"""
import email.utils
import html
import re
import secrets
import types
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.db import transaction
from django.utils import timezone

from tests import support
from tests import support_notify as notify
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
# проверено скриптом: 2026-10-12 — понедельник, 2026-10-13 — вторник
MON, TUE = date(2026, 10, 12), date(2026, 10, 13)
NEW = "servicedesk.new_in_queue"
MANDATORY = "core.password_changed"
BUTTON = "Открыть уведомления"
EVERY_DAY = list(range(7))

# дословные формы § 15.6 (число -> слово темы письма; число -> текст сообщения)
SUBJECT_WORD = {1: "уведомление", 2: "уведомления", 4: "уведомления", 5: "уведомлений", 11: "уведомлений",
                12: "уведомлений", 14: "уведомлений", 20: "уведомлений", 21: "уведомление", 22: "уведомления",
                25: "уведомлений", 101: "уведомление", 111: "уведомлений"}
MESSAGE_TEXT = {1: "У вас 1 новое уведомление", 2: "У вас 2 новых уведомления", 4: "У вас 4 новых уведомления",
                5: "У вас 5 новых уведомлений", 11: "У вас 11 новых уведомлений", 12: "У вас 12 новых уведомлений",
                14: "У вас 14 новых уведомлений", 20: "У вас 20 новых уведомлений", 21: "У вас 21 новое уведомление",
                22: "У вас 22 новых уведомления", 25: "У вас 25 новых уведомлений", 101: "У вас 101 новое уведомление",
                111: "У вас 111 новых уведомлений"}


# --- помощники только этого файла -------------------------------------------------------------------------

def at(day: date, hour: int = 0, minute: int = 0) -> datetime:
    """Момент по Москве."""
    return datetime(day.year, day.month, day.day, hour, minute, tzinfo=MSK)


def _scene(user=None, *, state: str = "active", mode: str = "own", digest_due_at=None):
    """Сотрудник — прямой участник новой очереди; строка настроек: «Свои часы» 09:00-18:00 каждый день."""
    unit = org.make_unit(f"Очередь {secrets.token_hex(3)}")
    sd.make_queue(unit)
    user = user or support.make_employee(state=state)
    member = org.make_member(user, unit)
    row = None
    if mode is not None:
        row, _ = model("notify.UserNotifySettings").objects.update_or_create(
            user=user, defaults={"quiet_mode": mode, "own_days": EVERY_DAY, "own_start": time(9, 0),
                                 "own_end": time(18, 0), "digest_due_at": digest_due_at})
    return types.SimpleNamespace(user=user, unit=unit, member=member, requester=sd.make_requester(), row=row)


def _ticket(scene, **over):
    return sd.make_ticket(queue=scene.unit, requester=scene.requester, **over)


def _note(scene, text: str | None = None, *, kind: str = NEW, read: bool = False, age: int = 0, ticket=None):
    """Уведомление сотрудника по заявке (`object_ref` — как у видов заявок); `created_at` — под часами теста."""
    if kind == NEW:
        ticket = ticket or _ticket(scene)
        ref, url = f"servicedesk.ticket:{ticket.pk}", f"/tickets/{ticket.number}/"
    else:
        ref, url = "", "/me/security/"
    now = timezone.now()
    return model("notify.Notification").objects.create(
        user=scene.user, kind=kind, text=text or f"Новая заявка {ticket.number}", url=url, object_ref=ref,
        created_at=now - timedelta(minutes=age), read_at=now if read else None)


def _held(note, *channels):
    """Накоплено в тихие часы: доставки `held` без срока."""
    Delivery = model("notify.Delivery")
    return {channel: Delivery.objects.create(notification=note, channel=channel, state="held", due_at=None)
            for channel in channels}


def _fresh(row):
    return type(row).objects.get(pk=row.pk)


def _bind(user, channel: str):
    return model("notify.ChatBinding").objects.create(user=user, channel=channel, chat_id=f"c{user.pk}{channel[:2]}")


def _build(user, capture):
    """`digest.build` внутри транзакции и «после фиксации» (CONTRACT-004, 7.3)."""
    from apps.notify.services import digest
    with capture(execute=True):
        with transaction.atomic():
            return digest.build(user.pk)


def _rows(digest) -> dict:
    return {row.channel: row for row in model("notify.Delivery").objects.filter(digest=digest)}


def _body(delivery) -> list[str]:
    """Строки тела письма сводки (рендерер читает базу, 10.1)."""
    from apps.notify.services import mail as notify_mail
    message = model("mail.MailMessage").objects.get(pk=delivery.mail_id)
    return notify_mail.render(message, {"delivery": delivery.pk}).body.rstrip("\n").splitlines()


def _portal_name() -> str:
    model("core.PortalSettings").objects.update(name="Портал ИТ-отдела")
    return model("core.PortalSettings").objects.get().name


def _digest_letters(user):
    return model("mail.MailMessage").objects.filter(to=user.email, template="notify.digest")


# --- сборка: письмо ----------------------------------------------------------------------------------------

def test_tick_enqueues_digest_build_only_for_due_users(clock, django_capture_on_commit_callbacks):
    """FR-330: обход ставит `build_digest(user_id)` только тем, у кого `digest_due_at` наступил; у остальных (срок
    впереди, срока нет) задания нет; сводку собирает выполненное задание."""
    from apps.notify import tasks
    clock.set(at(TUE, 10, 0))
    due = _scene(digest_due_at=at(TUE, 9, 0))
    later = _scene(digest_due_at=at(TUE, 18, 30))
    nothing = _scene()
    for scene in (due, later, nothing):
        _held(_note(scene), "telegram")

    with django_capture_on_commit_callbacks(execute=True):   # в тесте всё идёт внутри транзакции: постановка — после фиксации
        tick = tasks.notify_tick()

    jobs = notify.queued("build_digest")
    assert [job.args for job in jobs] == [(due.user.pk,)]
    assert tick["digests"] == 1 and jobs[0].timeout == 120
    notify.run_jobs()
    Digest = model("notify.Digest")
    assert Digest.objects.filter(user=due.user).count() == 1
    assert not Digest.objects.filter(user__in=[later.user, nothing.user]).exists()
    assert _fresh(due.row).digest_due_at is None
    assert _fresh(later.row).digest_due_at == at(TUE, 18, 30)


def test_seven_accumulated_three_read_gives_one_email_for_four(clock, django_capture_on_commit_callbacks):
    """FR-330: накоплено семь, три прочитаны на портале — одно письмо на четыре; прочитанные `skipped` `read`."""
    clock.set(at(TUE, 9, 0))
    scene = _scene(digest_due_at=at(TUE, 9, 0))
    notes = [_note(scene, f"Заявка номер {i}", read=i < 3, age=60 - i) for i in range(7)]
    rows = [_held(note, "email")["email"] for note in notes]

    digest = _build(scene.user, django_capture_on_commit_callbacks)

    assert digest is not None and digest.count_email == 4
    assert sorted(digest.notification_ids) == sorted(note.pk for note in notes[3:])
    letter = _rows(digest)["email"]
    assert letter.state == "sent" and letter.mail_id is not None
    assert _digest_letters(scene.user).count() == 1
    assert model("mail.MailMessage").objects.get(pk=letter.mail_id).subject == "За нерабочее время: 4 уведомления"
    states = [_fresh(row) for row in rows]
    assert [(row.state, row.reason) for row in states[:3]] == [("skipped", "read")] * 3
    assert [(row.state, row.reason) for row in states[3:]] == [("digested", "")] * 4


def test_digest_email_lists_text_and_link_per_notification(clock, settings, django_capture_on_commit_callbacks):
    """FR-330: тело письма — название портала, заголовок списка, по строке «текст — ссылка» на каждое уведомление в
    порядке `(created_at, id)`, ссылки на все уведомления и на настройки (10.2)."""
    name = _portal_name()
    clock.set(at(TUE, 9, 0))
    scene = _scene(digest_due_at=at(TUE, 9, 0))
    third = _note(scene, "Принтер не печатает", age=10)    # создана первой по номеру, но самая поздняя по времени
    first = _note(scene, "Не работает VPN", age=30)
    second = _note(scene, "Нужен доступ к папке", age=20)
    for note in (third, first, second):
        _held(note, "email")

    digest = _build(scene.user, django_capture_on_commit_callbacks)

    base = settings.PORTAL_URL.rstrip("/")
    expected = [name, "", "За нерабочее время: 3 уведомления:"]
    expected += [f"{note.text} — {base}/notifications/{note.pk}/open/" for note in (first, second, third)]
    expected += ["", f"Все уведомления: {base}/notifications/", f"Настроить уведомления: {base}/me/notifications/"]
    assert _body(_rows(digest)["email"]) == expected


def test_digest_message_for_four_goes_to_telegram_only(clock, settings, bots_on, django_capture_on_commit_callbacks):
    """FR-330: накоплено пять, одно прочитано — сообщение одно, «У вас 4 новых уведомления» с кнопкой на страницу
    уведомлений, только в Telegram; MAX не получает ничего, хотя у него тоже есть `held` и привязка."""
    from apps.notify.services import delivery as dlv
    clock.set(at(TUE, 9, 0))
    scene = _scene(digest_due_at=at(TUE, 9, 0))
    chats = {channel: _bind(scene.user, channel).chat_id for channel in ("telegram", "max")}
    held = [_held(_note(scene, f"Заявка {i}", read=i == 0), "email", "telegram", "max") for i in range(5)]

    digest = _build(scene.user, django_capture_on_commit_callbacks)

    rows = _rows(digest)
    assert set(rows) == {"email", "telegram"} and digest.count_message == 4 and digest.count_email == 4
    assert rows["telegram"].state == "waiting" and rows["telegram"].due_at == timezone.now()
    assert [job.args for job in notify.queued()] == [(rows["telegram"].pk,)]
    with notify.fake_bot_send("telegram") as telegram, notify.fake_bot_send("max") as max_bot:
        notify.run_jobs()
    button = (BUTTON, settings.PORTAL_URL.rstrip("/") + "/notifications/")
    assert telegram.calls == [(chats["telegram"], html.escape("У вас 4 новых уведомления"), button)]
    assert max_bot.calls == []
    # доп. 14: доставки MAX непрочитанных заменены сводкой (`digested`), у прочитанного — `skipped` `read`
    assert [(_fresh(pair["max"]).state, _fresh(pair["max"]).reason) for pair in held[1:]] == [("digested", "")] * 4
    assert (_fresh(held[0]["max"]).state, _fresh(held[0]["max"]).reason) == ("skipped", "read")
    assert _fresh(rows["telegram"]).state == "sent" and dlv.external_text(rows["telegram"]) == MESSAGE_TEXT[4]


def test_digest_email_subject_declension_by_count():
    """FR-330: тема письма «За нерабочее время: N <уведомление|уведомления|уведомлений>» и текст сообщения
    «У вас N новых …» склоняются по § 15.6: формы 1, 2-4, 5-20, граничные 11-14, 21, 22, 25, 101, 111."""
    from apps.notify.services import delivery as dlv
    from apps.notify.services import mail as notify_mail
    user = support.make_employee()
    Digest, Delivery, Message = model("notify.Digest"), model("notify.Delivery"), model("mail.MailMessage")
    for count, word in SUBJECT_WORD.items():
        digest = Digest.objects.create(user=user, count_email=count, count_message=count)
        letter = Delivery.objects.create(digest=digest, channel="email", state="waiting", due_at=timezone.now())
        mail_id = notify_mail.queue_digest(letter)
        assert Message.objects.get(pk=mail_id).subject == f"За нерабочее время: {count} {word}", count
        chat = Delivery.objects.create(digest=digest, channel="telegram", state="waiting", due_at=timezone.now())
        assert dlv.external_text(chat) == MESSAGE_TEXT[count], count


def test_digest_email_delivery_is_digest_email_with_mail_id(clock, settings, django_capture_on_commit_callbacks):
    """FR-330: доставка письма сводки — `Delivery(digest, email)` без уведомления, `sent`, с номером письма почтового
    модуля (шаблон `notify.digest`), `attempts=1`; `related_ref` и `Message-ID` — по номеру этой доставки (10.1)."""
    clock.set(at(TUE, 9, 0))
    scene = _scene(digest_due_at=at(TUE, 9, 0))
    for i in range(2):
        _held(_note(scene, f"Заявка {i}"), "email")

    digest = _build(scene.user, django_capture_on_commit_callbacks)

    letter = _rows(digest)["email"]
    assert (letter.notification_id, letter.digest_id, letter.state, letter.attempts) == (None, digest.pk, "sent", 1)
    message = model("mail.MailMessage").objects.get(pk=letter.mail_id)
    assert (message.template, message.to, message.auto_submitted) == ("notify.digest", scene.user.email,
                                                                    "auto-generated")
    assert message.related_ref == f"notify.delivery:{letter.pk}"
    domain = email.utils.parseaddr(settings.DEFAULT_FROM_EMAIL)[1].split("@")[1]
    assert re.fullmatch(rf"<.+\.notify\.{letter.pk}@{re.escape(domain)}>", message.message_id)


def test_held_email_due_in_quiet_hours_goes_into_digest_email(clock, django_capture_on_commit_callbacks):
    """FR-327, FR-330: письмо, срок которого пришёл на тихие часы, обход переводит в `held` и ставит срок сводки
    (начало рабочего времени); утром оно уходит в письме сводки, а не отдельным письмом."""
    from apps.core.extensions import Draft
    from apps.notify.services import dispatch
    scene = _scene()
    ticket = _ticket(scene)
    clock.set(at(MON, 17, 50))   # срок письма — 18:05, это уже тихие часы
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            ids = dispatch.create(NEW, [Draft(user_id=scene.user.pk, text="Новая заявка в очереди", url=f"/tickets/{ticket.number}/",
                                              object_ref=f"servicedesk.ticket:{ticket.pk}")])
    letter = model("notify.Delivery").objects.get(notification_id=ids[0], channel="email")
    assert letter.state == "waiting" and letter.due_at == at(MON, 18, 5)

    clock.set(at(MON, 18, 10))
    notify.run_tick()

    letter = _fresh(letter)
    assert (letter.state, letter.due_at, letter.mail_id) == ("held", None, None)
    assert _fresh(scene.row).digest_due_at == at(TUE, 9, 0)
    assert not model("mail.MailMessage").objects.filter(to=scene.user.email).exists()

    clock.set(at(TUE, 9, 0))
    tick = notify.run_tick()

    assert tick["digests"] == 1
    digest = model("notify.Digest").objects.get(user=scene.user)
    assert digest.count_email == 1 and digest.notification_ids == ids
    assert _fresh(letter).state == "digested"
    summary = _rows(digest)["email"]
    assert summary.state == "sent"
    assert model("mail.MailMessage").objects.get(pk=summary.mail_id).subject == "За нерабочее время: 1 уведомление"
    assert model("mail.MailMessage").objects.filter(to=scene.user.email).count() == 1


def test_email_due_in_working_time_not_in_digest_email(clock):
    """FR-330: письмо, срок которого наступил в рабочее время, уходит отдельно по сроку и в сводку не входит; в
    письме сводки — только накопленное `held`."""
    from apps.core.extensions import Draft
    from apps.notify.services import dispatch
    clock.set(at(MON, 10, 0))
    scene = _scene(digest_due_at=at(MON, 9, 0))
    ticket = _ticket(scene)
    ids = dispatch.create(NEW, [Draft(user_id=scene.user.pk, text="Письмо по сроку", url=f"/tickets/{ticket.number}/",
                                      object_ref=f"servicedesk.ticket:{ticket.pk}")])
    accumulated = _note(scene, "Накоплено за ночь", age=600)
    _held(accumulated, "email")

    clock.advance(minutes=16)   # 10:16: срок письма (10:15) наступил в рабочее время
    notify.run_tick()

    single = model("notify.Delivery").objects.get(notification_id=ids[0], channel="email")
    assert single.state == "sent" and single.mail_id is not None
    digest = model("notify.Digest").objects.get(user=scene.user)
    assert digest.notification_ids == [accumulated.pk] and digest.count_email == 1
    templates = sorted(model("mail.MailMessage").objects.filter(to=scene.user.email).values_list("template", flat=True))
    assert templates == ["notify.digest", "notify.item"]
    assert not any("Письмо по сроку" in line for line in _body(_rows(digest)["email"]))


def test_all_read_before_start_gives_no_digest(clock, django_capture_on_commit_callbacks):
    """FR-330: если всё накопленное прочитано до начала рабочего времени, сводки нет: ни `Digest`, ни письма, ни
    сообщения; доставки — `skipped` `read`."""
    clock.set(at(TUE, 9, 0))
    scene = _scene(digest_due_at=at(TUE, 9, 0))
    rows = [_held(_note(scene, f"Заявка {i}", read=True), "email", "telegram") for i in range(3)]

    assert _build(scene.user, django_capture_on_commit_callbacks) is None
    assert _fresh(scene.row).digest_due_at is None   # доп. 14: срок очищается и без `Digest`

    assert not model("notify.Digest").objects.exists()
    assert not model("mail.MailMessage").objects.filter(to=scene.user.email).exists()
    assert not model("notify.Delivery").objects.filter(digest__isnull=False).exists()
    for pair in rows:
        assert [(row.state, row.reason) for row in map(_fresh, pair.values())] == [("skipped", "read")] * 2


def test_zero_accumulated_gives_nothing(clock, django_capture_on_commit_callbacks):
    """FR-330: срок сводки наступил, а накопленного нет, — сводка ничего не создаёт."""
    clock.set(at(TUE, 9, 0))
    scene = _scene(digest_due_at=at(TUE, 8, 0))
    _note(scene, "Только на портале")   # непрочитанное есть, но доставок `held` у него нет

    assert _build(scene.user, django_capture_on_commit_callbacks) is None
    assert _fresh(scene.row).digest_due_at is None   # доп. 14: срок очищается и без `Digest`

    assert not model("notify.Digest").objects.exists()
    assert not model("notify.Delivery").objects.exists()
    assert not model("mail.MailMessage").objects.filter(to=scene.user.email).exists()
    assert notify.queued() == []


# --- сборка: сообщение -------------------------------------------------------------------------------------

def test_n_counts_only_notifications_with_chosen_channel_on(clock, django_capture_on_commit_callbacks):
    """FR-330: N в сообщении — число накопленных, у которых включён выбранный канал (там нет `held`, где канал выключен
    у вида); N письма — число накопленных с почтой; у пяти уведомлений Telegram включён у трёх."""
    from apps.notify.services import delivery as dlv
    clock.set(at(TUE, 9, 0))
    scene = _scene(digest_due_at=at(TUE, 9, 0))
    for i in range(3):
        _held(_note(scene, f"С Telegram {i}"), "email", "telegram")
    for i in range(2):
        _held(_note(scene, f"Без Telegram {i}"), "email")

    digest = _build(scene.user, django_capture_on_commit_callbacks)

    rows = _rows(digest)
    assert (digest.count_email, digest.count_message) == (5, 3)
    assert set(rows) == {"email", "telegram"}
    assert dlv.external_text(rows["telegram"]) == "У вас 3 новых уведомления"


def test_channel_order_telegram_before_max_before_webpush(clock, django_capture_on_commit_callbacks):
    """FR-330: при `held` во всех трёх каналах выбирается Telegram, хотя Web Push и MAX накопили больше: порядок
    важнее числа; N — число `held` Telegram."""
    from apps.notify.services import delivery as dlv
    clock.set(at(TUE, 9, 0))
    scene = _scene(digest_due_at=at(TUE, 9, 0))
    first = _held(_note(scene, "Все каналы"), "telegram", "max", "webpush")
    rest = [_held(_note(scene, f"MAX и Web Push {i}"), "max", "webpush") for i in range(2)]

    digest = _build(scene.user, django_capture_on_commit_callbacks)

    rows = _rows(digest)
    assert set(rows) == {"telegram"} and digest.count_message == 1 and digest.count_email == 0
    # доп. 14: доставки невыбранных каналов тоже заменены сводкой
    assert all(_fresh(row).state == "digested" for pair in [first, *rest] for row in pair.values())
    assert dlv.external_text(rows["telegram"]) == "У вас 1 новое уведомление"


def test_max_chosen_when_telegram_not_held(clock, django_capture_on_commit_callbacks):
    """FR-330: нет `held` в Telegram — сообщение в MAX (хотя у Web Push их больше); N — число `held` MAX."""
    from apps.notify.services import delivery as dlv
    clock.set(at(TUE, 9, 0))
    scene = _scene(digest_due_at=at(TUE, 9, 0))
    first = _held(_note(scene, "MAX и Web Push"), "max", "webpush")
    rest = [_held(_note(scene, f"Только Web Push {i}"), "webpush") for i in range(2)]

    digest = _build(scene.user, django_capture_on_commit_callbacks)

    rows = _rows(digest)
    assert set(rows) == {"max"} and digest.count_message == 1
    # доп. 14: доставки Web Push (невыбранный канал) заменены сводкой
    assert all(_fresh(row).state == "digested" for pair in [first, *rest] for row in pair.values())
    assert (rows["max"].state, rows["max"].due_at) == ("waiting", timezone.now())
    assert dlv.external_text(rows["max"]) == "У вас 1 новое уведомление"


def test_webpush_chosen_when_no_telegram_and_max(clock, django_capture_on_commit_callbacks):
    """FR-330: `held` только у Web Push — сообщение в Web Push, N — их число; доставка поставлена в очередь после
    фиксации одним заданием."""
    from apps.notify.services import delivery as dlv
    clock.set(at(TUE, 9, 0))
    scene = _scene(digest_due_at=at(TUE, 9, 0))
    for i in range(2):
        _held(_note(scene, f"Web Push {i}"), "webpush")

    digest = _build(scene.user, django_capture_on_commit_callbacks)

    rows = _rows(digest)
    assert set(rows) == {"webpush"} and digest.count_message == 2
    assert rows["webpush"].state == "waiting" and rows["webpush"].enqueued_at == timezone.now()
    assert [job.args for job in notify.queued()] == [(rows["webpush"].pk,)]
    assert dlv.external_text(rows["webpush"]) == "У вас 2 новых уведомления"


def test_digest_message_failure_is_not_moved_to_other_channel(clock, bots_on, django_capture_on_commit_callbacks):
    """FR-330: сообщение сводки в Telegram не удалось — повтор по расписанию (`waiting`, срок впереди) в том же канале;
    в MAX сводка не переносится: доставки сводки MAX нет, бот MAX не вызывался."""
    from apps.integrations.telegram import client as telegram_client
    clock.set(at(TUE, 9, 0))
    scene = _scene(digest_due_at=at(TUE, 9, 0))
    for channel in ("telegram", "max"):
        _bind(scene.user, channel)
    held = [_held(_note(scene, f"Заявка {i}"), "telegram", "max") for i in range(2)]
    digest = _build(scene.user, django_capture_on_commit_callbacks)
    sent = _rows(digest)["telegram"]
    assert [_fresh(pair["max"]).state for pair in held] == ["digested"] * 2   # доп. 14: MAX не получает отдельного сообщения

    with notify.fake_bot_send("telegram", raises=telegram_client.RetryLater) as telegram, \
            notify.fake_bot_send("max") as max_bot:
        notify.run_jobs()

    sent = _fresh(sent)
    assert len(telegram.calls) == 1 and max_bot.calls == []
    assert (sent.state, sent.attempts) == ("waiting", 1) and sent.due_at > timezone.now()
    assert [entry["outcome"] for entry in sent.log] == ["retry"]
    assert set(_rows(digest)) == {"telegram"}


def test_no_digest_email_when_email_off_for_all_accumulated(clock, django_capture_on_commit_callbacks):
    """FR-330: у накопленного нет `held` почты (она выключена у видов) — письма сводки нет, сообщение есть."""
    clock.set(at(TUE, 9, 0))
    scene = _scene(digest_due_at=at(TUE, 9, 0))
    for i in range(2):
        _held(_note(scene, f"Заявка {i}"), "telegram")

    digest = _build(scene.user, django_capture_on_commit_callbacks)

    assert set(_rows(digest)) == {"telegram"} and digest.count_email == 0
    assert not _digest_letters(scene.user).exists()


# --- тихие часы и срок сводки ------------------------------------------------------------------------------

def test_none_mode_new_events_give_no_digest(clock, bots_on, django_capture_on_commit_callbacks):
    """FR-330: у сотрудника «Без тихих часов» новые события не копятся: доставка идёт сразу (`waiting`), срока
    сводки нет, обход сводку не собирает."""
    from apps.core.extensions import Draft
    from apps.notify.services import dispatch
    clock.set(at(MON, 22, 0))   # по календарю и по часам 09-18 это были бы тихие часы
    scene = _scene(mode="none")
    _bind(scene.user, "telegram")
    ticket = _ticket(scene)
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            ids = dispatch.create(NEW, [Draft(user_id=scene.user.pk, text="Ночное событие", url=f"/tickets/{ticket.number}/",
                                              object_ref=f"servicedesk.ticket:{ticket.pk}")])
    chat = model("notify.Delivery").objects.get(notification_id=ids[0], channel="telegram")
    assert (chat.state, chat.due_at) == ("waiting", timezone.now())
    assert not model("notify.Delivery").objects.filter(state="held").exists()
    assert _fresh(scene.row).digest_due_at is None

    with notify.fake_bot_send("telegram") as telegram:
        tick = notify.run_tick()

    assert tick["digests"] == 0 and len(telegram.calls) == 1
    assert not model("notify.Digest").objects.exists()


def test_quiet_hours_change_digest_sent_at_new_working_start(clock):
    """FR-330: сотрудник сменил тихие часы, пока копилось, — накопленное уходит сводкой с началом ближайшего рабочего
    времени по новым часам, не по прежним."""
    from apps.notify.services import prefs
    clock.set(at(MON, 20, 0))
    scene = _scene()
    notes = [_note(scene, f"Заявка {i}") for i in range(2)]
    held = [_held(note, "email", "telegram") for note in notes]
    scene.row.digest_due_at = at(TUE, 9, 0)   # прежний срок — начало рабочего дня 09:00
    scene.row.save()

    assert prefs.save(scene.user, quiet_mode="own", own_days=EVERY_DAY, own_start=time(10, 0), own_end=time(19, 0)) is True

    assert _fresh(scene.row).digest_due_at == at(TUE, 10, 0)
    clock.set(at(TUE, 9, 30))
    tick = notify.run_tick()
    assert tick["digests"] == 0 and not model("notify.Digest").objects.exists()
    assert all(_fresh(row).state == "held" for pair in held for row in pair.values())
    clock.set(at(TUE, 10, 0))
    tick = notify.run_tick()
    assert tick["digests"] == 1
    digest = model("notify.Digest").objects.get(user=scene.user)
    assert sorted(digest.notification_ids) == sorted(note.pk for note in notes)
    assert all(_fresh(row).state == "digested" for pair in held for row in pair.values())


def test_switch_to_none_digest_sent_immediately(clock):
    """FR-330: переход на «Без тихих часов» — накопленное уходит сводкой сразу, не дожидаясь утра."""
    from apps.notify.services import prefs
    clock.set(at(MON, 22, 0))
    scene = _scene(digest_due_at=at(TUE, 9, 0))
    note = _note(scene, "Накопленное")
    pair = _held(note, "email", "telegram")

    assert prefs.save(scene.user, quiet_mode="none") is True
    assert _fresh(scene.row).digest_due_at == timezone.now()
    tick = notify.run_tick()

    assert tick["digests"] == 1
    digest = model("notify.Digest").objects.get(user=scene.user)
    assert digest.notification_ids == [note.pk] and (digest.count_email, digest.count_message) == (1, 1)
    assert _fresh(pair["email"]).state == "digested" and _fresh(pair["telegram"]).state == "digested"


# --- перепроверка при сборке -------------------------------------------------------------------------------

def test_digest_drops_notification_read_before_build(clock, django_capture_on_commit_callbacks):
    """FR-330: уведомление прочитали на портале после накопления, до сборки, — в сводке строки нет, доставки `skipped`
    `read`; непрочитанное остаётся."""
    from apps.notify.services import reading
    clock.set(at(TUE, 9, 0))
    scene = _scene(digest_due_at=at(TUE, 9, 0))
    gone, kept = _note(scene, "Прочитаю заранее"), _note(scene, "Останется")
    gone_rows, kept_rows = _held(gone, "email", "telegram"), _held(kept, "email", "telegram")
    with django_capture_on_commit_callbacks(execute=True):
        assert reading.read(scene.user, gone.pk) is True

    digest = _build(scene.user, django_capture_on_commit_callbacks)

    assert digest.notification_ids == [kept.pk] and (digest.count_email, digest.count_message) == (1, 1)
    assert [(row.state, row.reason) for row in map(_fresh, gone_rows.values())] == [("skipped", "read")] * 2
    assert [row.state for row in map(_fresh, kept_rows.values())] == ["digested"] * 2
    assert "Прочитаю заранее" not in "\n".join(_body(_rows(digest)["email"]))


def test_digest_drops_notification_after_access_lost(clock, django_capture_on_commit_callbacks):
    """FR-330: сотрудник перестал видеть заявку (вышел из очереди) — строки в сводке нет, доставки `skipped`
    `not_relevant`; заявка другой очереди, которую он ещё видит, остаётся."""
    clock.set(at(TUE, 9, 0))
    scene = _scene(digest_due_at=at(TUE, 9, 0))
    other = _scene(scene.user, mode=None)
    lost, kept = _note(scene, "Очередь покинута"), _note(other, "Очередь осталась")
    lost_rows, kept_rows = _held(lost, "email", "telegram"), _held(kept, "email", "telegram")
    scene.member.delete()

    digest = _build(scene.user, django_capture_on_commit_callbacks)

    assert digest.notification_ids == [kept.pk]
    assert [(row.state, row.reason) for row in map(_fresh, lost_rows.values())] == [("skipped", "not_relevant")] * 2
    assert [row.state for row in map(_fresh, kept_rows.values())] == ["digested"] * 2
    assert "Очередь покинута" not in "\n".join(_body(_rows(digest)["email"]))


def test_digest_drops_new_ticket_that_got_assignee(clock, django_capture_on_commit_callbacks):
    """FR-330: «Новая заявка в моей очереди», у заявки за ночь появился ответственный, — строки в сводке нет
    (`skipped` `not_relevant`); заявка без ответственного остаётся."""
    clock.set(at(TUE, 9, 0))
    scene = _scene(digest_due_at=at(TUE, 9, 0))
    taken_ticket = _ticket(scene)
    free, taken = _note(scene, "Заявка свободна"), _note(scene, "Заявку взяли", ticket=taken_ticket)
    free_rows, taken_rows = _held(free, "email", "telegram"), _held(taken, "email", "telegram")
    other = support.make_employee()
    org.make_member(other, scene.unit)
    type(taken_ticket).objects.filter(pk=taken_ticket.pk).update(assignee=other, kind="in_progress", assigned_once=True)

    digest = _build(scene.user, django_capture_on_commit_callbacks)

    assert digest.notification_ids == [free.pk]
    assert [(row.state, row.reason) for row in map(_fresh, taken_rows.values())] == [("skipped", "not_relevant")] * 2
    assert [row.state for row in map(_fresh, free_rows.values())] == ["digested"] * 2


def test_not_working_time_at_build_recalculates_due_at(clock, django_capture_on_commit_callbacks):
    """FR-330: к моменту сборки сотрудник снова в тихих часах (сменил часы, календарь) — сводка не собирается, срок
    пересчитан на начало ближайшего рабочего времени, накопленное остаётся `held`."""
    clock.set(at(MON, 22, 0))
    scene = _scene(digest_due_at=at(MON, 21, 0))
    pair = _held(_note(scene, "Накоплено"), "email", "telegram")

    assert _build(scene.user, django_capture_on_commit_callbacks) is None

    assert _fresh(scene.row).digest_due_at == at(TUE, 9, 0)
    assert [row.state for row in map(_fresh, pair.values())] == ["held"] * 2
    assert not model("notify.Digest").objects.exists()


def test_mandatory_kinds_not_in_digest(clock, django_capture_on_commit_callbacks):
    """FR-330: виды безопасности (`mandatory`) доставок не имеют и в сводку не попадают; если накоплены только они, сводки
    нет."""
    from apps.core.extensions import Draft
    from apps.notify.services import dispatch
    clock.set(at(MON, 22, 0))
    scene = _scene()
    with django_capture_on_commit_callbacks(execute=True):
        ids = dispatch.create(MANDATORY, [Draft(user_id=scene.user.pk, text="Пароль изменён", url="/me/security/")])
    assert not model("notify.Delivery").objects.filter(notification_id=ids[0]).exists()
    assert _fresh(scene.row).digest_due_at is None
    scene.row.digest_due_at = at(TUE, 9, 0)
    scene.row.save()
    clock.set(at(TUE, 9, 0))
    assert _build(scene.user, django_capture_on_commit_callbacks) is None   # только `mandatory` — сводки нет

    regular = _note(scene, "Обычное")
    _held(regular, "email", "telegram")
    digest = _build(scene.user, django_capture_on_commit_callbacks)

    assert digest.notification_ids == [regular.pk]
    assert "Пароль изменён" not in "\n".join(_body(_rows(digest)["email"]))


def test_blocked_user_gets_no_digest_and_held_skipped(clock, django_capture_on_commit_callbacks):
    """FR-345: пока учётная запись заблокирована, сводка не уходит: накопленное `held` — `skipped` `user_blocked`,
    срок сводки очищен, ни письма, ни сообщения."""
    clock.set(at(TUE, 9, 0))
    scene = _scene(state="blocked", digest_due_at=at(TUE, 9, 0))
    rows = [_held(_note(scene, f"Заявка {i}"), "email", "telegram") for i in range(2)]

    assert _build(scene.user, django_capture_on_commit_callbacks) is None

    assert all((row.state, row.reason) == ("skipped", "user_blocked")
               for pair in rows for row in map(_fresh, pair.values()))
    assert _fresh(scene.row).digest_due_at is None
    assert not model("notify.Digest").objects.exists()
    assert not model("mail.MailMessage").objects.filter(to=scene.user.email).exists()


# --- Web Push, итог по доставкам ---------------------------------------------------------------------------

def test_webpush_digest_skipped_when_tab_open(clock, webpush_on, django_capture_on_commit_callbacks):
    """FR-330, FR-331: сводка в Web Push при открытой вкладке (`notify:online:<id>` свежее 60 с) не отправляется:
    доставка `skipped` `tab_open`, запросов к push-сервису нет; у сотрудника без вкладки сводка уходит с тегом `digest`."""
    from apps.core.services.valkey import conn
    clock.set(at(TUE, 9, 0))
    watching, away = _scene(digest_due_at=at(TUE, 9, 0)), _scene(digest_due_at=at(TUE, 9, 0))
    pair = notify.browser_keys()
    for scene in (watching, away):
        notify.subscribe(scene.user, keys=pair if scene is away else None)
        for i in range(2):
            _held(_note(scene, f"Заявка {i}"), "webpush")
    conn().zadd(f"notify:online:{watching.user.pk}", {"c1": timezone.now().timestamp()})

    tab = _rows(_build(watching.user, django_capture_on_commit_callbacks))["webpush"]
    with notify.webpush_capture() as capture:
        notify.run_jobs()
    assert capture.requests == []
    tab = _fresh(tab)
    assert (tab.state, tab.reason) == ("skipped", "tab_open")

    own = _rows(_build(away.user, django_capture_on_commit_callbacks))["webpush"]
    with notify.webpush_capture() as capture:
        notify.run_jobs()
    assert _fresh(own).state == "sent" and len(capture.requests) == 1
    assert capture.decrypt(capture.requests[0], pair) == {"title": MESSAGE_TEXT[2], "url": "/notifications/", "tag": "digest"}


def test_used_deliveries_become_digested_and_digest_due_at_cleared(clock, django_capture_on_commit_callbacks):
    """FR-330: все вошедшие в сводку `held` — `digested` (причина пустая), срок сводки очищен; доставки другого сотрудника
    не тронуты."""
    clock.set(at(TUE, 9, 0))
    scene = _scene(digest_due_at=at(TUE, 9, 0))
    neighbour = _scene(digest_due_at=at(TUE, 18, 0))
    mine = [_held(_note(scene, f"Заявка {i}"), "email", "telegram") for i in range(2)]
    foreign = _held(_note(neighbour, "Чужая"), "email", "telegram")

    digest = _build(scene.user, django_capture_on_commit_callbacks)

    assert digest is not None
    assert all((row.state, row.reason) == ("digested", "") for pair in mine for row in map(_fresh, pair.values()))
    assert _fresh(scene.row).digest_due_at is None
    assert [row.state for row in map(_fresh, foreign.values())] == ["held"] * 2
    assert _fresh(neighbour.row).digest_due_at == at(TUE, 18, 0)


def test_digest_email_lists_only_notifications_of_kinds_with_email_on(clock, django_capture_on_commit_callbacks):
    """FR-330: в письме сводки — только уведомления, у вида которых включена «Почта» (есть `held` почты); уведомление
    без почты (только Telegram) в список не входит, но входит в сообщение; N письма и N сообщения считаются отдельно."""
    clock.set(at(TUE, 9, 0))
    scene = _scene(digest_due_at=at(TUE, 9, 0))
    with_mail = _note(scene, "Вид с почтой", age=20)
    without_mail = _note(scene, "Вид без почты", age=10)
    _held(with_mail, "email")
    _held(without_mail, "telegram")

    digest = _build(scene.user, django_capture_on_commit_callbacks)

    rows = _rows(digest)
    assert (digest.count_email, digest.count_message) == (1, 1) and set(rows) == {"email", "telegram"}
    assert sorted(digest.notification_ids) == sorted([with_mail.pk, without_mail.pk])
    text = "\n".join(_body(rows["email"]))
    assert "Вид с почтой" in text and "Вид без почты" not in text
    assert model("mail.MailMessage").objects.get(pk=rows["email"].mail_id).subject == "За нерабочее время: 1 уведомление"
