"""T-4128: хранение, увольнение, повторный приём и блокировка (FR-338, FR-339, FR-340, FR-345).

Сценарии 10 (хранение) и 11 (п. 7, увольнение) спеки среза 004; механизм — план «Хранение, увольнение, блокировка», контракт 6.9, 6.11, 6.13, 6.15.
Ночное удаление — `run_retention()` (§ 7.3), возраст записей задаётся прямой записью `created_at`; проходит оно под
ролью `crm_app` (соединение `default` тестов), своих `GRANT` у таблиц среза нет (§ 2.3). Увольнение, возврат на работу,
блокировка и разблокировка — настоящие `accounts.dismiss`, `accounts.rehire`, `accounts.block`, `accounts.unblock`;
подписчики шины идут внутри `django_capture_on_commit_callbacks(execute=True)` (дополнение 7 раздела 17). Telegram и
MAX — учебная служба `fakebots` (`bots_on`), Web Push — `webpush_capture`. Код среза 004 на уровне модуля не
импортируется: имена берутся внутри тестов (CONTRACT-004, шапка).
"""
import datetime
import hashlib
import json
import logging
import re
import secrets
from zoneinfo import ZoneInfo

import pytest
from django.db import connection, transaction
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests import support, support_notify as notify
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
MOMENT = datetime.datetime(2026, 10, 13, 11, 0, 0, tzinfo=MSK)  # вторник
KIND = "servicedesk.new_in_queue"
EXTERNAL = ("email", "webpush", "telegram", "max")


# --- помощники только этого файла -------------------------------------------------------------------------

def _days(value: int) -> datetime.timedelta:
    return datetime.timedelta(days=value)


def _ago(value: int) -> datetime.datetime:
    return timezone.now() - _days(value)


def _set_term(days: int) -> None:
    model("notify.NotifySettings").objects.filter(pk=1).update(retention_days=days)


def _note(user, *, age: int = 0, text: str | None = None, ref: str = "", kind: str = KIND):
    """Уведомление, которому `age` суток (прямая запись `created_at`)."""
    return model("notify.Notification").objects.create(
        user=user, kind=kind, text=text or "Тест " + secrets.token_hex(4), url="/tickets/1/", object_ref=ref,
        created_at=_ago(age))


def _delivery(note, channel: str, state: str = "waiting", *, due_in: int | None = -5, **over):
    """Доставка уведомления; срок — `due_in` секунд от «сейчас» (None — срока нет)."""
    fields = {"notification": note, "channel": channel, "state": state,
              "due_at": None if due_in is None else timezone.now() + datetime.timedelta(seconds=due_in)}
    fields.update(over)
    return model("notify.Delivery").objects.create(**fields)


def _digest(user, *, age: int = 0):
    return model("notify.Digest").objects.create(user=user, created_at=_ago(age), count_email=1, count_message=1)


def _bind(user, channel: str, chat_id: str):
    return model("notify.ChatBinding").objects.create(user=user, channel=channel, chat_id=chat_id)


def _code(user, channel: str = "telegram", *, expires_in_minutes: int = 10, used: bool = False):
    """Код привязки прямой записью (хеш SHA-256 восьми цифр)."""
    digits = "%08d" % secrets.randbelow(10 ** 8)
    now = timezone.now()
    return model("notify.BindCode").objects.create(
        user=user, channel=channel, code_hash=hashlib.sha256(digits.encode()).hexdigest(),
        expires_at=now + datetime.timedelta(minutes=expires_in_minutes), used_at=now if used else None)


def _prefs(user):
    """Все внешние каналы у вида включены, тихих часов нет (доставки создаются сразу)."""
    return model("notify.UserNotifySettings").objects.update_or_create(
        user=user, defaults={"quiet_mode": "none", "matrix": {KIND: ["email", "push", "telegram", "max"]}})[0]


def _staff(*, chats: tuple[str, str] = ("7001991", "8101991")):
    """Сотрудник со всеми каналами: строка настроек, привязки Telegram и MAX, подписка Web Push."""
    user = support.make_employee()
    _prefs(user)
    _bind(user, "telegram", chats[0])
    _bind(user, "max", chats[1])
    notify.subscribe(user)
    return user


def _ticket_ref(user) -> str:
    """Заявка без ответственного в очереди, где сотрудник — прямой участник: уведомление по ней актуально (письмо уйдёт)."""
    queue = sd.make_queue(org.make_unit("Очередь " + secrets.token_hex(3)))
    org.make_member(user, queue.unit)
    return f"servicedesk.ticket:{sd.make_ticket(queue=queue).pk}"


def _create(capture, user, text: str | None = None, ref: str = ""):
    """`dispatch.create` внутри транзакции и «после фиксации» (§ 7.3); возвращает уведомление."""
    from apps.core.extensions import Draft
    from apps.notify.services import dispatch

    draft = Draft(user_id=user.pk, text=text or "Назначена заявка " + secrets.token_hex(3), url="/tickets/1/",
                  object_ref=ref)
    with capture(execute=True):
        with transaction.atomic():
            ids = dispatch.create(KIND, [draft])
    return model("notify.Notification").objects.get(pk=ids[0])


def _rows(note) -> dict:
    return {row.channel: row for row in model("notify.Delivery").objects.filter(notification=note)}


def _fresh(row):
    return type(row).objects.get(pk=row.pk)


def _exists(row) -> bool:
    return type(row).objects.filter(pk=row.pk).exists()


def _admin():
    return support.make_admin()


def _dismiss(capture, user, admin) -> None:
    from apps.core.services import accounts

    with capture(execute=True):
        accounts.dismiss(user, actor=admin)


def _block(user, admin) -> None:
    from apps.core.services import accounts

    accounts.block(user, "тест", actor=admin)


def _letters(user):
    """Письма уведомлений (`notify.item`, `notify.digest`) этому сотруднику."""
    return model("mail.MailMessage").objects.filter(to=user.email, template__in=["notify.item", "notify.digest"])


def _nothing_left_the_portal(bots, push, user) -> bool:
    return bots.sent("telegram") == [] and bots.sent("max") == [] and push.requests == [] and not _letters(user).exists()


def _audit(action: str, user):
    return list(model("core.AuditEvent").objects.filter(action=action, object_id=str(user.pk)).order_by("id"))


# --- 1. ночное удаление уведомлений (FR-338) ---------------------------------------------------------------

def test_nightly_retention_deletes_notifications_older_than_term_with_their_deliveries():
    """FR-338: уведомления старше 90 суток удаляются ночным заданием вместе со своими доставками (каскад); число
    удалённых — в `notifications`; свежее уведомление и его доставки остаются."""
    user = support.make_employee()
    old = _note(user, age=91)
    old_rows = [_delivery(old, "email", "sent", due_in=None), _delivery(old, "telegram", "failed", due_in=None)]
    fresh = _note(user, age=10)
    fresh_row = _delivery(fresh, "email", "sent", due_in=None)

    result = notify.run_retention()

    assert result["notifications"] == 1
    assert not _exists(old)
    assert not model("notify.Delivery").objects.filter(pk__in=[row.pk for row in old_rows]).exists()
    assert _exists(fresh) and _exists(fresh_row)


def test_nightly_retention_keeps_notifications_within_term():
    """FR-338: уведомления в пределах срока (89 и 10 суток, только что) ночное задание не трогает, доставки остаются."""
    user = support.make_employee()
    notes = [_note(user, age=age) for age in (0, 10, 89)]
    rows = [_delivery(note, "telegram", "sent", due_in=None) for note in notes]

    result = notify.run_retention()

    assert result["notifications"] == 0
    assert all(_exists(note) for note in notes) and all(_exists(row) for row in rows)


def test_nightly_retention_takes_term_180_days_from_settings():
    """FR-338: срок хранения берётся из настроек: при 180 сутках запись в 100 суток остаётся (при 90 ушла бы), в 200 —
    удаляется."""
    _set_term(180)
    user = support.make_employee()
    middle, old = _note(user, age=100), _note(user, age=200)
    middle_row = _delivery(middle, "email", "sent", due_in=None)

    result = notify.run_retention()

    assert result["notifications"] == 1
    assert _exists(middle) and _exists(middle_row)
    assert not _exists(old)


def test_nightly_retention_default_term_is_90_days():
    """FR-338, § 2.3: после установки прочие таблицы среза пусты, срок по умолчанию — 90 суток: запись в 89 суток
    остаётся, в 91 — удаляется."""
    for name in ("Notification", "Delivery", "PushSubscription", "ChatBinding", "BindCode", "Digest",
                 "UserNotifySettings", "BotChat", "BotState"):
        assert not model(f"notify.{name}").objects.exists(), name
    assert model("notify.NotifySettings").objects.get(pk=1).retention_days == 90
    user = support.make_employee()
    kept, gone = _note(user, age=89), _note(user, age=91)

    notify.run_retention()

    assert _exists(kept)
    assert not _exists(gone)


def test_nightly_retention_deletes_in_batches_of_1000(monkeypatch):
    """FR-338: удаление идёт порциями по `BATCH` (1000), порция — своя транзакция, цикл до порции короче `BATCH`:
    при `BATCH = 3` семь старых записей уходят тремя порциями (3, 3, 1), свежая остаётся."""
    from apps.notify.services import retention

    assert retention.BATCH == 1000
    monkeypatch.setattr(retention, "BATCH", 3)
    user = support.make_employee()
    old = [_note(user, age=100 + i) for i in range(7)]
    rows = [_delivery(note, "email", "sent", due_in=None) for note in old]
    fresh = _note(user, age=1)

    with CaptureQueriesContext(connection) as queries:
        result = notify.run_retention()

    sql = [item["sql"] for item in queries.captured_queries]
    table = model("notify.Notification")._meta.db_table
    deletes = [text for text in sql if re.search(rf'\bDELETE\s+FROM\s+"?{table}"?(\s|$)', text)]
    assert result["notifications"] == 7
    assert len(deletes) == 3
    assert not model("notify.Notification").objects.filter(pk__in=[note.pk for note in old]).exists()
    assert not model("notify.Delivery").objects.filter(pk__in=[row.pk for row in rows]).exists()
    assert _exists(fresh)


def test_nightly_retention_deletes_digests_older_than_same_term():
    """FR-338: сводки старше того же срока удаляются вместе со своими доставками; свежая сводка остаётся; срок —
    из настроек."""
    user = support.make_employee()
    old, fresh = _digest(user, age=95), _digest(user, age=40)
    old_row = model("notify.Delivery").objects.create(digest=old, channel="email", state="sent")
    fresh_row = model("notify.Delivery").objects.create(digest=fresh, channel="email", state="sent")

    result = notify.run_retention()

    assert result["digests"] == 1
    assert not _exists(old) and not _exists(old_row)
    assert _exists(fresh) and _exists(fresh_row)

    _set_term(30)
    gone, kept = _digest(user, age=31), _digest(user, age=20)
    result = notify.run_retention()
    assert result["digests"] == 2
    assert _exists(kept) and not _exists(gone) and not _exists(fresh)  # при сроке 30 суток уходит и сводка в 40 суток


def test_ticket_history_stays_in_ticket_after_notification_is_deleted():
    """FR-338: когда ночное задание удалило уведомление о заявке, сама заявка и её лента остаются неизменными."""
    user = support.make_employee()
    queue = sd.make_queue(org.make_unit("Очередь " + secrets.token_hex(3)))
    ticket = sd.make_ticket(queue=queue)
    entries = [sd.make_entry(ticket, "comment", author=user, text="Комментарий " + secrets.token_hex(3)),
               sd.make_entry(ticket, "event", event="assignee_changed", text="Назначена")]
    note = _note(user, age=120, ref=f"servicedesk.ticket:{ticket.pk}")
    _delivery(note, "telegram", "sent", due_in=None)
    before = sorted(model("servicedesk.TicketEntry").objects.filter(ticket=ticket).values_list("pk", "kind", "text"))

    result = notify.run_retention()

    assert result["notifications"] == 1 and not _exists(note)
    assert _exists(ticket)
    after = sorted(model("servicedesk.TicketEntry").objects.filter(ticket=ticket).values_list("pk", "kind", "text"))
    assert after == before and len(after) == len(entries)


def test_botchat_without_binding_older_than_30_days_deleted_bound_or_newer_kept():
    """FR-338, § 6.15: `BotChat` старше 30 суток без привязки того же канала и чата удаляется; с такой привязкой, а
    также младше 30 суток — остаётся; привязка другого канала или другого чата чат не защищает."""
    BotChat = model("notify.BotChat")
    user = support.make_employee()
    _bind(user, "telegram", "5001")
    _bind(user, "max", "5003")
    started = _ago(31)
    unbound = BotChat.objects.create(channel="telegram", chat_id="5002", started_at=started)
    bound = BotChat.objects.create(channel="telegram", chat_id="5001", started_at=started)
    recent = BotChat.objects.create(channel="telegram", chat_id="5004", started_at=_ago(29))
    other_channel = BotChat.objects.create(channel="max", chat_id="5001", started_at=started)
    bound_max = BotChat.objects.create(channel="max", chat_id="5003", started_at=started)

    result = notify.run_retention()

    assert result["botchats"] == 2
    assert not _exists(unbound) and not _exists(other_channel)
    assert _exists(bound) and _exists(recent) and _exists(bound_max)


# --- 2. коды привязки (FR-339) -----------------------------------------------------------------------------

def test_binding_code_deleted_by_sweep_after_10_minutes(bots_on, clock):
    """FR-339: код привязки живёт 10 минут: обход через 9 минут его оставляет, после 10 минут — удаляет."""
    from apps.notify.services import binding

    clock.set(MOMENT)
    user = support.make_employee()
    other = support.make_employee()
    binding.new_code(user, "telegram")
    assert model("notify.BindCode").objects.get(user=user).expires_at == MOMENT + datetime.timedelta(minutes=10)

    clock.advance(minutes=9)
    notify.run_tick()
    assert model("notify.BindCode").objects.filter(user=user).count() == 1

    clock.advance(minutes=1, seconds=1)
    binding.new_code(other, "max")  # новый код не должен пострадать от обхода
    tick = notify.run_tick()
    assert tick["codes"] == 1
    assert not model("notify.BindCode").objects.filter(user=user).exists()
    assert model("notify.BindCode").objects.filter(user=other).count() == 1


def test_binding_code_deleted_after_use(clock):
    """FR-339: использованный код (`used_at` не пусто) удаляет ближайший обход, хотя срок кода не вышел; неиспользованный
    действующий код другого сотрудника остаётся."""
    clock.set(MOMENT)
    user, other = support.make_employee(), support.make_employee()
    used = _code(user, used=True)
    active = _code(other)

    tick = notify.run_tick()

    assert tick["codes"] == 1
    assert not _exists(used)
    assert _exists(active)


def test_nightly_retention_deletes_expired_binding_codes():
    """FR-339: ночное удаление убирает коды с истёкшим сроком и использованные; действующий остаётся; `codes` — их число."""
    first, second, third = (support.make_employee() for _ in range(3))
    expired = _code(first, expires_in_minutes=-1)
    used = _code(second, "max", used=True)
    active = _code(third)

    result = notify.run_retention()

    assert result["codes"] == 2
    assert not _exists(expired) and not _exists(used)
    assert _exists(active)


# --- 3. увольнение (FR-340) --------------------------------------------------------------------------------



def test_dismissal_deletes_push_subscriptions_telegram_max_bindings_codes_and_user_settings(
        bots_on, webpush_on, caplog, django_capture_on_commit_callbacks):
    """FR-340: увольнение удаляет все подписки Web Push, привязки Telegram и MAX, коды привязки и строку
    `UserNotifySettings`; ошибок подписчиков в журнале приложения нет."""
    from apps.notify.services import binding

    user, admin = _staff(), _admin()
    notify.subscribe(user)
    binding.new_code(user, "telegram")
    binding.new_code(user, "max")
    assert model("notify.PushSubscription").objects.filter(user=user).count() == 2
    assert model("notify.BindCode").objects.filter(user=user).count() == 2

    caplog.set_level(logging.ERROR, logger="apps.core.events")
    _dismiss(django_capture_on_commit_callbacks, user, admin)

    assert not model("notify.PushSubscription").objects.filter(user=user).exists()
    assert not model("notify.ChatBinding").objects.filter(user=user).exists()
    assert not model("notify.BindCode").objects.filter(user=user).exists()
    assert not model("notify.UserNotifySettings").objects.filter(user=user).exists()
    assert not [r for r in caplog.records if r.name == "apps.core.events" and r.levelno >= logging.ERROR]


def test_dismissal_sets_waiting_held_sending_deliveries_to_skipped(bots_on, webpush_on,
                                                                   django_capture_on_commit_callbacks):
    """FR-340: доставки уволенного в состояниях `waiting`, `held`, `sending` (по уведомлению и по сводке) становятся
    `skipped` с причиной `user_dismissed`, аренда снята; `sent`, `failed`, `digested` не меняются."""
    user, admin = _staff(), _admin()
    lease = timezone.now() + datetime.timedelta(minutes=3)
    waiting = _delivery(_note(user), "telegram")
    waiting_mail = _delivery(_note(user), "email", due_in=900)
    held = _delivery(_note(user), "webpush", "held", due_in=None)
    sending = _delivery(_note(user), "max", "sending", lease_until=lease)
    digest = _digest(user)
    digest_waiting = model("notify.Delivery").objects.create(digest=digest, channel="telegram", state="waiting",
                                                             due_at=timezone.now())
    kept = {"sent": _delivery(_note(user), "telegram", "sent", due_in=None),
            "failed": _delivery(_note(user), "max", "failed", due_in=None, reason="expired"),
            "digested": _delivery(_note(user), "email", "digested", due_in=None)}

    _dismiss(django_capture_on_commit_callbacks, user, admin)

    for row in (waiting, waiting_mail, held, sending, digest_waiting):
        row = _fresh(row)
        assert (row.state, row.reason, row.lease_until) == ("skipped", "user_dismissed", None), row.channel
    for state, row in kept.items():
        row = _fresh(row)
        assert row.state == state
    assert _fresh(kept["failed"]).reason == "expired"


def test_dismissal_keeps_notifications_until_retention_term(bots_on, webpush_on, django_capture_on_commit_callbacks):
    """FR-340: уведомления и сводки уволенного остаются до общего срока хранения: после увольнения и после ночного
    задания живут записи младше срока, старше срока — уходят."""
    user, admin = _staff(), _admin()
    recent, old = _note(user, age=10), _note(user, age=100)
    recent_row = _delivery(recent, "email", "sent", due_in=None)
    recent_digest, old_digest = _digest(user, age=5), _digest(user, age=100)

    _dismiss(django_capture_on_commit_callbacks, user, admin)

    assert all(_exists(row) for row in (recent, old, recent_row, recent_digest, old_digest))
    result = notify.run_retention()
    assert (result["notifications"], result["digests"]) == (1, 1)
    assert _exists(recent) and _exists(recent_row) and _exists(recent_digest)
    assert not _exists(old) and not _exists(old_digest)


def test_dismissal_audit_was_became_has_no_chat_identifiers(bots_on, webpush_on, django_capture_on_commit_callbacks):
    """FR-340, § 9.2: увольнение пишет от системы `notify.channel_unbound` по каждой привязке и `notify.push_removed`
    по каждой подписке с причиной `dismissed`; в «было / стало» нет номеров чатов и адресов подписок."""
    user, admin = _staff(chats=("7001991", "8101991")), _admin()
    notify.subscribe(user)
    model("notify.PushSubscription").objects.filter(user=user).update(browser="Chrome 126", platform="Windows")
    endpoints = list(model("notify.PushSubscription").objects.filter(user=user).values_list("endpoint", flat=True))

    _dismiss(django_capture_on_commit_callbacks, user, admin)

    unbound = _audit("notify.channel_unbound", user)
    removed = _audit("notify.push_removed", user)
    assert len(unbound) == 2 and len(removed) == 2
    assert all(event.actor_id is None for event in unbound + removed)
    assert sorted(event.before["channel"] for event in unbound) == ["max", "telegram"]
    for event in unbound:
        assert event.before == {"channel": event.before["channel"], "bound": True}
        assert event.after == {"bound": False, "reason": "dismissed"}
    for event in removed:
        assert event.before == {"browser": "Chrome 126", "platform": "Windows"}
        assert event.after == {"reason": "dismissed"}
    dumped = json.dumps([[event.before, event.after] for event in unbound + removed], ensure_ascii=False)
    assert "7001991" not in dumped and "8101991" not in dumped
    assert not any(endpoint.rsplit("/", 1)[-1] in dumped for endpoint in endpoints)


def test_nothing_is_sent_to_dismissed_employee_after_dismissal(bots_on, webpush_on, clock,
                                                                django_capture_on_commit_callbacks):
    """FR-340: после увольнения ни письмо, ни Telegram, ни MAX, ни Web Push не уходят — ни из очереди, ни из обхода;
    все доставки пропущены с причиной `user_dismissed`."""
    clock.set(MOMENT)
    user, admin = _staff(), _admin()
    note = _create(django_capture_on_commit_callbacks, user)
    rows = _rows(note)
    assert set(rows) == set(EXTERNAL) and len(notify.queued()) == 3
    sd.backdate(rows["email"], "due_at", minutes=16)

    _dismiss(django_capture_on_commit_callbacks, user, admin)
    with notify.webpush_capture() as push:
        notify.run_jobs()
        clock.advance(minutes=20)
        notify.run_tick()

    assert {name: (row.state, row.reason) for name, row in ((n, _fresh(r)) for n, r in rows.items())} == {
        name: ("skipped", "user_dismissed") for name in EXTERNAL}
    assert _nothing_left_the_portal(bots_on, push, user)


def test_dismissal_does_not_touch_data_of_other_employees(bots_on, webpush_on, django_capture_on_commit_callbacks):
    """FR-340: подписки, привязки, коды, настройки и доставки других сотрудников после увольнения остаются как были."""
    from apps.notify.services import binding

    user, other, admin = _staff(), _staff(chats=("7002992", "8102992")), _admin()
    binding.new_code(user, "telegram")
    binding.new_code(other, "telegram")
    waiting = _delivery(_note(other), "telegram")
    held = _delivery(_note(other), "webpush", "held", due_in=None)
    mine = _delivery(_note(user), "telegram")

    def snapshot():
        return {name: model(f"notify.{name}").objects.filter(user=other).count()
                for name in ("PushSubscription", "ChatBinding", "BindCode", "UserNotifySettings", "Notification")}

    before = snapshot()
    assert before == {"PushSubscription": 1, "ChatBinding": 2, "BindCode": 1, "UserNotifySettings": 1,
                      "Notification": 2}

    _dismiss(django_capture_on_commit_callbacks, user, admin)

    assert snapshot() == before
    assert (_fresh(waiting).state, _fresh(waiting).reason) == ("waiting", "")
    assert (_fresh(held).state, _fresh(held).reason) == ("held", "")
    assert _fresh(mine).state == "skipped"


def test_dismissal_signal_is_core_user_dismissed_and_access_changed_does_not_purge(
        bots_on, webpush_on, bus_spy, django_capture_on_commit_callbacks):
    """FR-340: сигнал увольнения — событие `core.user_dismissed` (`user_id`, `actor_id`), на него подписан `cleanup`;
    `access.changed` подписчиков `notify` не зовёт и ничего не стирает."""
    from apps.core import events
    from apps.notify.services import cleanup

    user, admin = _staff(), _admin()
    waiting = _delivery(_note(user), "telegram")
    assert cleanup.on_dismissed in events.subscribers("core.user_dismissed")
    assert not [h for h in events.subscribers("access.changed") if getattr(h, "__module__", "").startswith("apps.notify")]

    with django_capture_on_commit_callbacks(execute=True):
        events.publish("access.changed", user_ids=[user.pk])
        events.publish("access.changed", user_ids=None)
    assert model("notify.PushSubscription").objects.filter(user=user).exists()
    assert model("notify.ChatBinding").objects.filter(user=user).count() == 2
    assert model("notify.UserNotifySettings").objects.filter(user=user).exists()
    assert (_fresh(waiting).state, _fresh(waiting).reason) == ("waiting", "")

    bus_spy.listen("core.user_dismissed")
    _dismiss(django_capture_on_commit_callbacks, user, admin)
    assert bus_spy.calls("core.user_dismissed") == [{"user_id": user.pk, "actor_id": admin.pk}]
    assert not model("notify.ChatBinding").objects.filter(user=user).exists()
    assert _fresh(waiting).state == "skipped"


def test_rehire_deletes_previous_notifications_of_employee(bots_on, webpush_on, bus_spy,
                                                           django_capture_on_commit_callbacks):
    """FR-340: возврат на работу (`accounts.rehire`, событие `core.user_rehired`) удаляет прежние уведомления и сводки
    сотрудника вместе с доставками; записи других сотрудников остаются."""
    from apps.core.services import accounts

    user, other, admin = _staff(), support.make_employee(), _admin()
    old, recent = _note(user, age=100), _note(user, age=3)
    rows = [_delivery(old, "email", "sent", due_in=None), _delivery(recent, "telegram", "sent", due_in=None)]
    digest = _digest(user, age=2)
    digest_row = model("notify.Delivery").objects.create(digest=digest, channel="email", state="sent")
    others = _note(other, age=3)
    others_row = _delivery(others, "email", "sent", due_in=None)
    _dismiss(django_capture_on_commit_callbacks, user, admin)
    assert _exists(old) and _exists(recent) and _exists(digest)

    bus_spy.listen("core.user_rehired")
    with django_capture_on_commit_callbacks(execute=True):
        accounts.rehire(user, actor=admin)

    assert bus_spy.calls("core.user_rehired") == [{"user_id": user.pk, "actor_id": admin.pk}]
    assert not model("notify.Notification").objects.filter(user=user).exists()
    assert not model("notify.Digest").objects.filter(user=user).exists()
    assert not model("notify.Delivery").objects.filter(pk__in=[row.pk for row in rows + [digest_row]]).exists()
    assert _exists(others) and _exists(others_row)


# --- 4. блокировка (FR-345) --------------------------------------------------------------------------------

def test_blocked_employee_gets_no_external_deliveries_created(bots_on, webpush_on, django_capture_on_commit_callbacks):
    """FR-345: диспетчер заблокированному внешних доставок не создаёт и в очередь ничего не ставит; такому же активному
    сотруднику создаёт по всем четырём каналам."""
    active, blocked, admin = _staff(), _staff(chats=("7002992", "8102992")), _admin()
    _block(blocked, admin)

    control = _create(django_capture_on_commit_callbacks, active)
    assert set(_rows(control)) == set(EXTERNAL)
    queued_before = len(notify.queued())
    note = _create(django_capture_on_commit_callbacks, blocked)

    assert note.user_id == blocked.pk
    assert not model("notify.Delivery").objects.filter(notification=note).exists()
    assert len(notify.queued()) == queued_before


def test_blocked_employee_existing_delivery_skipped_with_reason_by_send_job(bots_on, webpush_on,
                                                                             django_capture_on_commit_callbacks):
    """FR-345: доставки Telegram, MAX и Web Push, созданные до блокировки, задание `send_delivery` пропускает:
    `skipped`, причина `user_blocked`, аренды нет, ничего не уходит."""
    from apps.notify.services import delivery

    user, admin = _staff(), _admin()
    note = _create(django_capture_on_commit_callbacks, user)
    rows = _rows(note)
    assert len(notify.queued()) == 3
    _block(user, admin)

    with notify.webpush_capture() as push:
        assert notify.run_jobs() == 3
        assert delivery.send_delivery(rows["telegram"].pk) == "noop"  # уже пропущена

    for channel in ("telegram", "max", "webpush"):
        row = _fresh(rows[channel])
        assert (row.state, row.reason, row.lease_until) == ("skipped", "user_blocked", None), channel
    assert bots_on.sent("telegram") == [] and bots_on.sent("max") == [] and push.requests == []


def test_blocked_employee_skipped_by_tick_and_digest_and_mail_letter(bots_on, webpush_on, clock,
                                                                      django_capture_on_commit_callbacks):
    """FR-345: заблокированному не уходят письмо (обход), сообщение (обход ставит задание — оно пропускает) и сводка
    (`digest.build`: накопленное `held` — `skipped`, срок сводки очищен, ни письма, ни сообщения)."""
    clock.set(MOMENT)
    user, admin = _staff(), _admin()
    note = _create(django_capture_on_commit_callbacks, user)
    mail_row = _rows(note)["email"]
    sd.backdate(mail_row, "due_at", minutes=16)
    direct = _note(user)  # доставки созданы «до блокировки», но задание в очередь не ставилось: обход поставит
    direct_rows = [_delivery(direct, "telegram"), _delivery(direct, "webpush")]
    held_note = _note(user)
    held_rows = [_delivery(held_note, "email", "held", due_in=None), _delivery(held_note, "telegram", "held", due_in=None)]
    due = timezone.now() - datetime.timedelta(minutes=1)
    model("notify.UserNotifySettings").objects.filter(user=user).update(digest_due_at=due)
    _block(user, admin)

    with notify.webpush_capture() as push:
        notify.run_tick()

    assert (_fresh(mail_row).state, _fresh(mail_row).reason) == ("skipped", "user_blocked")
    assert [(_fresh(row).state, _fresh(row).reason) for row in direct_rows] == [("skipped", "user_blocked")] * 2
    assert [(_fresh(row).state, _fresh(row).reason) for row in held_rows] == [("skipped", "user_blocked")] * 2
    assert model("notify.UserNotifySettings").objects.get(user=user).digest_due_at is None
    assert not model("notify.Digest").objects.filter(user=user).exists()
    assert _nothing_left_the_portal(bots_on, push, user)


def test_skipped_deliveries_are_not_sent_after_unblock(bots_on, webpush_on, clock, django_capture_on_commit_callbacks):
    """FR-345: пропущенные при блокировке доставки после разблокировки не досылаются (остаются `skipped` с
    `user_blocked`); новое уведомление после разблокировки получает доставки и уходит."""
    from apps.core.services import accounts

    clock.set(MOMENT)
    user, admin = _staff(), _admin()
    old_note = _create(django_capture_on_commit_callbacks, user)
    old_rows = _rows(old_note)
    sd.backdate(old_rows["email"], "due_at", minutes=16)
    _block(user, admin)
    with notify.webpush_capture() as push_blocked:
        notify.run_jobs()
        notify.run_tick()
    assert {_fresh(row).state for row in old_rows.values()} == {"skipped"}
    assert push_blocked.requests == []

    accounts.unblock(user, actor=admin)
    new_note = _create(django_capture_on_commit_callbacks, user, ref=_ticket_ref(user))
    with notify.webpush_capture() as push:
        notify.run_jobs()
        clock.advance(minutes=20)
        notify.run_tick()

    assert {(_fresh(row).state, _fresh(row).reason) for row in old_rows.values()} == {("skipped", "user_blocked")}
    new_rows = _rows(new_note)
    assert {name: _fresh(row).state for name, row in new_rows.items()} == {name: "sent" for name in EXTERNAL}
    assert len(bots_on.sent("telegram")) == 1 and len(bots_on.sent("max")) == 1  # только новое
    assert len(push.requests) == 1


def test_blocked_employee_portal_notifications_accumulate(bots_on, webpush_on, django_capture_on_commit_callbacks):
    """FR-345: пока учётная запись заблокирована, уведомления на портале копятся непрочитанными и остаются после
    разблокировки; доставок нет."""
    from apps.core.services import accounts

    user, admin = _staff(), _admin()
    _block(user, admin)
    notes = [_create(django_capture_on_commit_callbacks, user, f"Заявка {i}") for i in range(3)]

    assert model("notify.Notification").objects.filter(user=user).count() == 3
    assert all(_fresh(note).read_at is None for note in notes)
    assert not model("notify.Delivery").objects.filter(notification__user=user).exists()

    accounts.unblock(user, actor=admin)
    assert sorted(model("notify.Notification").objects.filter(user=user, read_at__isnull=True)
                  .values_list("text", flat=True)) == ["Заявка 0", "Заявка 1", "Заявка 2"]


def test_blocked_employee_still_gets_core_security_letters_as_in_slice_001(django_capture_on_commit_callbacks):
    """FR-345: письма безопасности ядра заблокированному идут как в срезе 001 (письмо «second_factor_reset»), запись на
    портале создаётся (вид `mandatory`, доставок нет); писем уведомлений нет."""
    from apps.core.services import accounts

    user, admin = support.make_employee(), _admin()
    _block(user, admin)

    with django_capture_on_commit_callbacks(execute=True):
        accounts.reset_second_factor(user, actor=admin)

    assert support.mails(to=user.email, template="second_factor_reset").count() == 1
    note = model("notify.Notification").objects.get(user=user, kind="core.second_factor_reset")
    assert not model("notify.Delivery").objects.filter(notification=note).exists()
    assert not _letters(user).exists()
