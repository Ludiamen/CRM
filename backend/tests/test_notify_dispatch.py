"""T-4109: создание уведомления и раскладка по каналам (FR-305, FR-306, FR-327…FR-331, FR-345, NFR-304).

Сценарии 1-4 спеки среза 004. Событие — тестовый вид, который тест регистрирует внутри `extensions.empty()`
помощником `support_notify.register_kind` (фикстура `env` вместе с `bus`); обёртка — `dispatch.handler_for(name)`.
Время раскладки ставит фикстура `clock` (рабочее время — среда 14.10.2026 12:00 по Москве, тихие часы — тот же
день 22:00, календарь по умолчанию пн-пт 09:00-18:00). Всё, что идёт после фиксации (раскладка, число и системное
уведомление в группе, постановка заданий), — внутри `django_capture_on_commit_callbacks(execute=True)`. Кадры группы —
`ws_run` и `ws_fragments` (CONTRACT-004 § 11.3-11.4). Имена кода среза 004 — внутри тестов или через `support.model`.
"""
import datetime
import logging
import uuid
from zoneinfo import ZoneInfo

import pytest
from django.db import transaction

from tests import support
from tests import support_notify as notify
from tests.support import model

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
WORK = datetime.datetime(2026, 10, 14, 12, 0, tzinfo=MSK)         # среда, рабочее время
QUIET = datetime.datetime(2026, 10, 14, 22, 0, tzinfo=MSK)        # среда, после конца рабочего дня
NEXT_START = datetime.datetime(2026, 10, 15, 9, 0, tzinfo=MSK)    # четверг, начало рабочего дня
FRIDAY_EVENING = datetime.datetime(2026, 10, 16, 20, 0, tzinfo=MSK)
MONDAY_START = datetime.datetime(2026, 10, 19, 9, 0, tzinfo=MSK)

EVENT = "test.happened"
KIND = "test.thing"
ALL_CHANNELS = ("portal", "email", "push", "telegram", "max")


# --- помощники только этого файла ------------------------------------------------------------------------

@pytest.fixture
def env(bus, clock):
    """Каталог видов и подписки шины пусты, часы стоят в рабочем времени; тестовый вид — `_register`."""
    from apps.core import extensions

    with extensions.empty():
        clock.set(WORK)
        yield bus


def _register(*, code=KIND, channels=ALL_CHANNELS, mandatory=False, build=None, events=(EVENT,)):
    """Тестовый вид: по одному `Draft` на номер из `data["user_ids"]`."""
    from apps.core.extensions import Draft, NotificationKind

    def default_build(event, data):
        return [Draft(user_id=uid, text=f"Событие для {uid}", url="/test/", object_ref=f"test:{uid}")
                for uid in data["user_ids"]]

    kind = NotificationKind(code=code, title="Тестовый вид", module="test", events=tuple(events),
                            build=build or default_build, external_text="Есть новое",
                            default_channels=tuple(channels), mandatory=mandatory)
    notify.register_kind(kind)
    return kind


def _draft(user, text: str = "Событие"):
    from apps.core.extensions import Draft

    return Draft(user_id=user.pk, text=text, url="/test/", object_ref=f"test:{user.pk}")


def _fire(capture, *users, name: str = EVENT) -> None:
    """Публикует событие шины внутри `capture(execute=True)`: обработчики и рассылка идут после фиксации."""
    from apps.core import events

    with capture(execute=True):
        events.publish(name, user_ids=[user.pk for user in users])


def _bind(user, *channels: str) -> None:
    for channel in channels:
        model("notify.ChatBinding").objects.create(user=user, channel=channel,
                                                   chat_id=f"{channel}-{uuid.uuid4().hex[:8]}")


def _notes(user=None):
    notes = model("notify.Notification").objects.all()
    return notes.filter(user=user) if user is not None else notes


def _deliveries(user=None):
    rows = model("notify.Delivery").objects.all()
    return rows.filter(notification__user=user) if user is not None else rows


def _by_channel(user) -> dict:
    return {row.channel: row for row in _deliveries(user)}


def _prefs_row(user):
    return model("notify.UserNotifySettings").objects.filter(user=user).first()


def _no_bus_errors(caplog) -> None:
    """Решение 24 задач: сбоев подписчиков шины в журнале приложения нет."""
    bad = [r.getMessage() for r in caplog.records if r.name == "apps.core.events" and r.levelno >= logging.ERROR]
    assert not bad, bad


def _check_immediate(channel: str, kind_code: str, capture, caplog, *, bind: str = "", subscribe: bool = False):
    """Раздел FR-328: доставка канала в рабочее время — `waiting`, срок и отметка постановки — «сейчас»."""
    _register(channels=("portal", kind_code))
    user = support.make_employee()
    if bind:
        _bind(user, bind)
    if subscribe:
        notify.subscribe(user)
    _fire(capture, user)
    row = _by_channel(user)[channel]
    assert row.state == "waiting"
    assert row.due_at == WORK
    assert row.enqueued_at == WORK
    assert row.attempts == 0 and row.reason == "" and row.log == []
    assert set(_by_channel(user)) == {channel}
    assert [job.args for job in notify.queued()] == [(row.pk,)]
    _no_bus_errors(caplog)


def _check_held(channel: str, kind_code: str, capture, caplog, *, bind: str = "", subscribe: bool = False):
    """FR-329: в тихие часы доставка канала — `held`, без срока и без задания."""
    _register(channels=("portal", kind_code))
    user = support.make_employee()
    if bind:
        _bind(user, bind)
    if subscribe:
        notify.subscribe(user)
    _fire(capture, user)
    row = _by_channel(user)[channel]
    assert row.state == "held"
    assert row.due_at is None and row.enqueued_at is None
    assert row.attempts == 0 and row.reason == ""
    assert set(_by_channel(user)) == {channel}
    assert _notes(user).count() == 1                      # на портале уведомление видно сразу
    assert notify.queued() == []
    _no_bus_errors(caplog)


# --- одна запись на получателя ---------------------------------------------------------------------------

def test_event_creates_one_notification_per_recipient(env, django_capture_on_commit_callbacks, caplog):
    """FR-306: одно событие — одна запись у каждого получателя (вид, кому, время, текст, ссылка, не прочитана);
    человек вне списка записи не получает."""
    _register(channels=("portal",))
    first, second, third, outsider = (support.make_employee() for _ in range(4))
    _fire(django_capture_on_commit_callbacks, first, second, third)
    assert _notes().count() == 3
    for user in (first, second, third):
        rows = list(_notes(user))
        assert len(rows) == 1, user.pk
        note = rows[0]
        assert note.kind == KIND
        assert note.text == f"Событие для {user.pk}"
        assert note.url == "/test/"
        assert note.object_ref == f"test:{user.pk}"
        assert note.created_at == WORK
        assert note.read_at is None
    assert _notes(outsider).count() == 0
    _no_bus_errors(caplog)


def test_notification_and_deliveries_created_in_one_transaction(env, bots_on, django_capture_on_commit_callbacks):
    """FR-306: записи и доставки пишутся в транзакции вызывающего: откат действия убирает и их, а действия «после
    фиксации» (постановка заданий) не выполняются."""
    from apps.notify.services import dispatch

    class Rollback(Exception):
        pass

    _register()
    user = support.make_employee()
    _bind(user, "telegram")
    with django_capture_on_commit_callbacks(execute=True):
        with pytest.raises(Rollback):
            with transaction.atomic():
                dispatch.create(KIND, [_draft(user)])
                assert _notes(user).count() == 1
                assert set(_by_channel(user)) == {"email", "telegram"}
                raise Rollback
    assert _notes().count() == 0
    assert _deliveries().count() == 0
    assert notify.queued() == []


def test_event_wrapper_passes_event_name_to_handler(env, django_capture_on_commit_callbacks):
    """FR-306: `handler_for(name)` — функция `handler(**data)`, она зовёт `on_event(name, **data)`: вид получает имя
    именно того события, на которое подписана обёртка; обёртка для одного имени — один и тот же объект."""
    from apps.core.extensions import Draft
    from apps.notify.services import dispatch

    seen = []

    def build(event, data):
        seen.append((event, dict(data)))
        return [Draft(user_id=uid, text=f"Из {event}", url="/test/") for uid in data["user_ids"]]

    _register(channels=("portal",), events=("test.first", "test.second"), build=build)
    user = support.make_employee()
    first, second = dispatch.handler_for("test.first"), dispatch.handler_for("test.second")
    assert first is dispatch.handler_for("test.first")
    assert first is not second
    with django_capture_on_commit_callbacks(execute=True):
        first(user_ids=[user.pk])
        second(user_ids=[user.pk])
    assert seen == [("test.first", {"user_ids": [user.pk]}), ("test.second", {"user_ids": [user.pk]})]
    assert sorted(_notes(user).values_list("text", flat=True)) == ["Из test.first", "Из test.second"]


def test_portal_channel_creates_no_delivery(env, django_capture_on_commit_callbacks):
    """FR-306: канал «портал» доставки не создаёт — запись и есть канал; у доставки нет каналов `portal` и `push`."""
    from apps.notify.services import prefs

    Delivery = model("notify.Delivery")
    assert {value for value, _ in Delivery.Channel.choices} == {"email", "webpush", "telegram", "max"}
    kind = _register(channels=("portal",))
    user = support.make_employee()
    assert prefs.channels_for(user.pk, kind) == []
    _fire(django_capture_on_commit_callbacks, user)
    assert _notes(user).count() == 1
    assert _deliveries().count() == 0
    assert notify.queued() == []


# --- почта (FR-327) --------------------------------------------------------------------------------------

def test_email_delivery_waiting_with_due_at_plus_delay_minutes(env, django_capture_on_commit_callbacks, caplog):
    """FR-327: письмо — доставка `waiting` со сроком «создано + N минут» (по умолчанию 15, потом настройка 45)."""
    _register(channels=("portal", "email"))
    user = support.make_employee()
    _fire(django_capture_on_commit_callbacks, user)
    note = _notes(user).get()
    row = _deliveries(user).get()
    assert row.channel == "email" and row.state == "waiting" and row.reason == ""
    assert row.due_at == note.created_at + datetime.timedelta(minutes=15)
    model("notify.NotifySettings").objects.filter(pk=1).update(email_delay_minutes=45)
    other = support.make_employee()
    _fire(django_capture_on_commit_callbacks, other)
    later = _deliveries(other).get()
    assert later.due_at == _notes(other).get().created_at + datetime.timedelta(minutes=45)
    _no_bus_errors(caplog)


def test_email_not_enqueued_at_creation(env, django_capture_on_commit_callbacks):
    """FR-327: письмо при создании в очередь не ставится (ни `notify`, ни `mail`); его берёт обход по сроку."""
    import django_rq

    _register(channels=("portal", "email"))
    user = support.make_employee()
    _fire(django_capture_on_commit_callbacks, user)
    row = _deliveries(user).get()
    assert row.channel == "email" and row.state == "waiting"
    assert row.enqueued_at is None and row.mail_id is None
    assert notify.queued() == []
    assert list(django_rq.get_queue("notify").jobs) == []
    assert list(django_rq.get_queue("mail").jobs) == []


def test_no_email_delivery_when_email_off_for_kind(env, bots_on, django_capture_on_commit_callbacks):
    """FR-327: если «Почта» у вида выключена (по умолчанию вида или в таблице сотрудника), доставки `email` нет;
    остальные включённые каналы работают."""
    _register(channels=("portal", "email", "telegram"))
    by_default, by_matrix = support.make_employee(), support.make_employee()
    model("notify.UserNotifySettings").objects.create(user=by_matrix, matrix={KIND: ["telegram"]})
    _bind(by_default, "telegram")
    _bind(by_matrix, "telegram")
    _fire(django_capture_on_commit_callbacks, by_default, by_matrix)
    assert set(_by_channel(by_default)) == {"email", "telegram"}
    assert set(_by_channel(by_matrix)) == {"telegram"}
    _register(code="test.no_mail", events=("test.other",), channels=("portal", "telegram"))
    lone = support.make_employee()
    _bind(lone, "telegram")
    _fire(django_capture_on_commit_callbacks, lone, name="test.other")
    assert set(_by_channel(lone)) == {"telegram"}


# --- мгновенные каналы в рабочее время (FR-328) ----------------------------------------------------------

def test_webpush_waiting_due_now_in_working_hours(env, webpush_on, django_capture_on_commit_callbacks, caplog):
    """FR-328: ячейка `push` вида даёт доставку `webpush` — `waiting`, срок и постановка «сейчас»."""
    _check_immediate("webpush", "push", django_capture_on_commit_callbacks, caplog, subscribe=True)


def test_telegram_waiting_due_now_in_working_hours(env, bots_on, django_capture_on_commit_callbacks, caplog):
    """FR-328: доставка `telegram` при привязке — `waiting`, срок и постановка «сейчас»."""
    _check_immediate("telegram", "telegram", django_capture_on_commit_callbacks, caplog, bind="telegram")


def test_max_waiting_due_now_in_working_hours(env, bots_on, django_capture_on_commit_callbacks, caplog):
    """FR-328: доставка `max` при привязке — `waiting`, срок и постановка «сейчас»."""
    _check_immediate("max", "max", django_capture_on_commit_callbacks, caplog, bind="max")


# --- тихие часы (FR-329) ---------------------------------------------------------------------------------

def test_webpush_held_in_quiet_hours(env, clock, webpush_on, django_capture_on_commit_callbacks, caplog):
    """FR-329: в тихие часы доставка `webpush` — `held`, срока нет, в очередь не ставится."""
    clock.set(QUIET)
    _check_held("webpush", "push", django_capture_on_commit_callbacks, caplog, subscribe=True)


def test_telegram_held_in_quiet_hours(env, clock, bots_on, django_capture_on_commit_callbacks, caplog):
    """FR-329: в тихие часы доставка `telegram` — `held`, срока нет, в очередь не ставится."""
    clock.set(QUIET)
    _check_held("telegram", "telegram", django_capture_on_commit_callbacks, caplog, bind="telegram")


def test_max_held_in_quiet_hours(env, clock, bots_on, django_capture_on_commit_callbacks, caplog):
    """FR-329: в тихие часы доставка `max` — `held`, срока нет, в очередь не ставится."""
    clock.set(QUIET)
    _check_held("max", "max", django_capture_on_commit_callbacks, caplog, bind="max")


def test_email_delivery_waiting_even_in_quiet_hours_with_delay_due(env, clock, django_capture_on_commit_callbacks):
    """FR-327, FR-329: письмо и в тихие часы при создании — `waiting` со сроком «создано + N минут» (тихие часы
    проверит обход в момент отправки); сводка для него не планируется."""
    clock.set(QUIET)
    _register(channels=("portal", "email"))
    user = support.make_employee()
    _fire(django_capture_on_commit_callbacks, user)
    row = _deliveries(user).get()
    assert row.channel == "email" and row.state == "waiting"
    assert row.due_at == QUIET + datetime.timedelta(minutes=15)
    assert not _deliveries(user).filter(state="held").exists()
    prefs_row = _prefs_row(user)
    assert prefs_row is None or prefs_row.digest_due_at is None


def test_held_delivery_sets_digest_due_at_to_next_working_start(env, clock, bots_on,
                                                               django_capture_on_commit_callbacks):
    """FR-329: у сотрудника с новой `held` `digest_due_at` — ближайшее начало рабочего времени по календарю
    (среда вечером — четверг 09:00; пятница вечером — понедельник 09:00)."""
    _register(channels=("portal", "telegram"))
    wednesday, friday = support.make_employee(), support.make_employee()
    _bind(wednesday, "telegram")
    _bind(friday, "telegram")
    clock.set(QUIET)
    _fire(django_capture_on_commit_callbacks, wednesday)
    assert _prefs_row(wednesday).digest_due_at == NEXT_START
    clock.set(FRIDAY_EVENING)
    _fire(django_capture_on_commit_callbacks, friday)
    assert _prefs_row(friday).digest_due_at == MONDAY_START
    assert _by_channel(wednesday)["telegram"].state == "held"


def test_digest_due_at_keeps_earlier_value(env, clock, bots_on, django_capture_on_commit_callbacks):
    """FR-329: `digest_due_at` — меньшее из прежнего и нового: более поздний расчёт прежнее значение не двигает,
    более ранний — заменяет."""
    UserNotifySettings = model("notify.UserNotifySettings")
    _register(channels=("portal", "telegram"))
    user, other = support.make_employee(), support.make_employee()
    _bind(user, "telegram")
    _bind(other, "telegram")
    clock.set(QUIET)
    _fire(django_capture_on_commit_callbacks, user)
    assert _prefs_row(user).digest_due_at == NEXT_START
    clock.set(datetime.datetime(2026, 10, 15, 19, 0, tzinfo=MSK))   # четверг вечером: новое начало — пятница 09:00
    _fire(django_capture_on_commit_callbacks, user)
    assert _by_channel(user)["telegram"].state == "held" and _deliveries(user).count() == 2
    assert _prefs_row(user).digest_due_at == NEXT_START
    later = datetime.datetime(2026, 10, 26, 9, 0, tzinfo=MSK)
    UserNotifySettings.objects.create(user=other, digest_due_at=later)
    clock.set(QUIET)
    _fire(django_capture_on_commit_callbacks, other)
    assert UserNotifySettings.objects.get(user=other).digest_due_at == NEXT_START


# --- какие каналы создаются (FR-328, FR-329, FR-305, FR-345) ---------------------------------------------

def test_no_external_delivery_when_kind_channel_off(env, bots_on, webpush_on, django_capture_on_commit_callbacks):
    """FR-328: канал, выключенный у вида (по умолчанию вида или в таблице сотрудника), доставки не создаёт, хотя
    сам канал включён и доступен."""
    _register(channels=("portal", "telegram"))
    default_user, cleared_user = support.make_employee(), support.make_employee()
    for user in (default_user, cleared_user):
        _bind(user, "telegram", "max")
        notify.subscribe(user)
    model("notify.UserNotifySettings").objects.create(user=cleared_user, matrix={KIND: []})
    _fire(django_capture_on_commit_callbacks, default_user, cleared_user)
    assert set(_by_channel(default_user)) == {"telegram"}
    assert _deliveries(cleared_user).count() == 0
    assert _notes(cleared_user).count() == 1


def test_no_external_delivery_when_channel_unavailable(env, clock, bots_on, webpush_on,
                                                       django_capture_on_commit_callbacks):
    """FR-328, FR-329: канал без привязки, без подписки или выключенный администратором доставки не создаёт; в тихие
    часы недоступный канал не даёт и `held`."""
    NotifySettings = model("notify.NotifySettings")
    _register()
    bare, only_push, only_bots = (support.make_employee() for _ in range(3))
    notify.subscribe(only_push)
    _bind(only_bots, "telegram", "max")
    _fire(django_capture_on_commit_callbacks, bare, only_push, only_bots)
    assert set(_by_channel(bare)) == {"email"}
    assert set(_by_channel(only_push)) == {"email", "webpush"}
    assert set(_by_channel(only_bots)) == {"email", "telegram", "max"}
    # администратор выключил Telegram: привязка есть, канал не доступен
    NotifySettings.objects.filter(pk=1).update(telegram_enabled=False)
    full = support.make_employee()
    _bind(full, "telegram", "max")
    notify.subscribe(full)
    _fire(django_capture_on_commit_callbacks, full)
    assert set(_by_channel(full)) == {"email", "webpush", "max"}
    # и Web Push: подписка есть, канал выключен
    NotifySettings.objects.filter(pk=1).update(webpush_enabled=False)
    no_push = support.make_employee()
    _bind(no_push, "telegram", "max")
    notify.subscribe(no_push)
    _fire(django_capture_on_commit_callbacks, no_push)
    assert set(_by_channel(no_push)) == {"email", "max"}
    # тихие часы: недоступный канал не копится
    clock.set(QUIET)
    quiet_bare = support.make_employee()
    _fire(django_capture_on_commit_callbacks, quiet_bare)
    assert set(_by_channel(quiet_bare)) == {"email"}
    assert not _deliveries(quiet_bare).filter(state="held").exists()
    row = _prefs_row(quiet_bare)
    assert row is None or row.digest_due_at is None


def test_mandatory_kind_creates_no_deliveries(env, clock, bots_on, webpush_on, django_capture_on_commit_callbacks):
    """FR-305, FR-306: у вида `mandatory` внешних доставок нет (письмо — у ядра), тихие часы его не задерживают и
    сводку не планируют, запись на портале есть."""
    _register(channels=("portal", "email", "push", "telegram", "max"), mandatory=True)
    day_user, night_user = support.make_employee(), support.make_employee()
    for user in (day_user, night_user):
        _bind(user, "telegram", "max")
        notify.subscribe(user)
    _fire(django_capture_on_commit_callbacks, day_user)
    clock.set(QUIET)
    _fire(django_capture_on_commit_callbacks, night_user)
    assert _notes(day_user).count() == 1 and _notes(night_user).count() == 1
    assert _deliveries().count() == 0
    assert notify.queued() == []
    row = _prefs_row(night_user)
    assert row is None or row.digest_due_at is None


def test_blocked_user_gets_notification_without_external_deliveries(env, clock, bots_on, webpush_on,
                                                                    django_capture_on_commit_callbacks):
    """FR-345: заблокированному запись на портале создаётся, внешних доставок нет (ни в рабочее, ни в тихие
    часы); активный получатель того же события их получает."""
    _register()
    blocked, active = support.make_employee(state="blocked"), support.make_employee()
    for user in (blocked, active):
        _bind(user, "telegram", "max")
        notify.subscribe(user)
    _fire(django_capture_on_commit_callbacks, blocked, active)
    assert _notes(blocked).count() == 1
    assert _deliveries(blocked).count() == 0
    assert set(_by_channel(active)) == {"email", "webpush", "telegram", "max"}
    clock.set(QUIET)
    _fire(django_capture_on_commit_callbacks, blocked)
    assert _notes(blocked).count() == 2
    assert _deliveries(blocked).count() == 0
    row = _prefs_row(blocked)
    assert row is None or row.digest_due_at is None


# --- кадр группы пользователя (FR-331, FR-329) -----------------------------------------------------------

def test_group_fragment_carries_new_count(env, django_capture_on_commit_callbacks):
    """FR-331: после события в группу `notify.u.<id>` уходит один кадр с точным новым числом непрочитанных
    (`#notify-count[data-count]`); при подключении — кадр с прежним числом."""
    _register(channels=("portal",))
    user = support.make_employee()
    Notification = model("notify.Notification")
    for _ in range(2):
        Notification.objects.create(user=user, kind=KIND, text="Старое", url="/test/")
    Notification.objects.create(user=user, kind=KIND, text="Прочитанное", url="/test/", read_at=WORK)
    client = support.logged_in(user)

    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        opening = await conn.receive()
        assert opening is not None, "кадра с числом при подключении нет"
        first = notify.ws_fragments(opening)
        assert first["notify-count"].attrs["data-count"] == "2"
        await hub.do(_fire, django_capture_on_commit_callbacks, user)
        frame = await conn.receive()
        assert frame is not None
        fragment = notify.ws_fragments(frame)["notify-count"]
        assert fragment.attrs["data-count"] == "3"
        assert fragment.text.strip() == "3"
        await hub.do(_fire, django_capture_on_commit_callbacks, user)
        second = await conn.receive()
        assert second is not None, "кадра после второго события нет"
        again = notify.ws_fragments(second)["notify-count"]
        assert again.attrs["data-count"] == "4"

    notify.ws_run(scenario)


def _toast_after_event(capture, user, client):
    """Подключается, делает событие и возвращает фрагменты кадра с новым уведомлением."""
    async def scenario(hub):
        conn = await hub.connect(client)
        assert conn.accepted
        await conn.receive()                                   # кадр с числом при подключении
        await hub.do(_fire, capture, user)
        frame = await conn.receive()
        assert frame is not None, "кадра после события нет"
        return notify.ws_fragments(frame)

    return notify.ws_run(scenario)


def test_group_fragment_data_show_1_with_webpush_kind_in_working_hours(env, django_capture_on_commit_callbacks):
    """FR-331: у вида включена ячейка `push`, рабочее время — `#notify-toast[data-show="1"]` с текстом, ссылкой
    открытия и меткой `n-<id>`; наличие подписки Web Push на признак не влияет."""
    _register(channels=("portal", "push"))
    user = support.make_employee()
    client = support.logged_in(user)
    fragments = _toast_after_event(django_capture_on_commit_callbacks, user, client)
    note = _notes(user).get()
    toast = fragments["notify-toast"]
    assert toast.attrs["data-show"] == "1"
    assert toast.attrs["data-text"] == note.text
    assert toast.attrs["data-url"] == f"/notifications/{note.pk}/open/"
    assert toast.attrs["data-tag"] == f"n-{note.pk}"
    assert fragments["notify-count"].attrs["data-count"] == "1"


def test_group_fragment_data_show_0_in_quiet_hours(env, clock, django_capture_on_commit_callbacks):
    """FR-329, FR-331: в тихие часы при включённой ячейке `push` фрагмент системного уведомления с `data-show="0"`,
    число на колокольчике обновляется."""
    _register(channels=("portal", "push"))
    user = support.make_employee()
    clock.set(QUIET)
    client = support.logged_in(user)
    fragments = _toast_after_event(django_capture_on_commit_callbacks, user, client)
    note = _notes(user).get()
    assert fragments["notify-toast"].attrs["data-show"] == "0"
    assert fragments["notify-toast"].attrs["data-tag"] == f"n-{note.pk}"
    assert fragments["notify-count"].attrs["data-count"] == "1"


def test_group_fragment_data_show_0_without_webpush_on_kind(env, django_capture_on_commit_callbacks):
    """FR-331: ячейка `push` у вида выключена — `data-show="0"` и в рабочее время; число обновляется."""
    _register(channels=("portal", "email", "telegram"))
    user = support.make_employee()
    client = support.logged_in(user)
    fragments = _toast_after_event(django_capture_on_commit_callbacks, user, client)
    assert fragments["notify-toast"].attrs["data-show"] == "0"
    assert fragments["notify-count"].attrs["data-count"] == "1"


# --- постановка заданий и сбой подписчика ----------------------------------------------------------------

def test_immediate_deliveries_enqueued_after_commit(env, bots_on, webpush_on, django_capture_on_commit_callbacks):
    """FR-328: задания `send_delivery` ставятся после фиксации (до выхода из блока очередь пуста): по одному на
    доставку `waiting` со сроком «сейчас»; письмо и `held` в очередь не попадают."""
    from apps.notify.services import dispatch

    _register()
    ready, quiet = support.make_employee(), support.make_employee()
    for user in (ready, quiet):
        _bind(user, "telegram", "max")
        notify.subscribe(user)
    # у второго «свои часы» не включают среду 12:00: его внешние доставки копятся
    model("notify.UserNotifySettings").objects.create(
        user=quiet, quiet_mode="own", own_days=[0], own_start=datetime.time(9, 0), own_end=datetime.time(10, 0))
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            dispatch.create(KIND, [_draft(ready), _draft(quiet)])
            assert notify.queued() == []
        assert notify.queued() == []
    jobs = notify.queued()
    immediate = _by_channel(ready)
    expected = {immediate[name].pk for name in ("webpush", "telegram", "max")}
    assert sorted(job.args for job in jobs) == sorted((pk,) for pk in expected)
    assert all(job.timeout == 180 for job in jobs)
    for name in ("webpush", "telegram", "max"):
        assert immediate[name].state == "waiting" and immediate[name].enqueued_at == WORK
    assert immediate["email"].enqueued_at is None
    held = _by_channel(quiet)
    assert {row.state for name, row in held.items() if name != "email"} == {"held"}
    assert all(row.enqueued_at is None for row in held.values())


def test_subscriber_error_is_logged_and_does_not_roll_back_publishing_action(env, caplog,
                                                                              django_capture_on_commit_callbacks):
    """FR-306, NFR-304: сбой подписчика `notify` — запись `ERROR` в логгере `apps.core.events`; действие издателя
    сохранено, записей нет, остальные подписчики события отработали."""
    from apps.core import events

    def broken(event, data):
        raise RuntimeError("сбой вида")

    _register(channels=("portal",), build=broken)
    env.listen(EVENT)
    user = support.make_employee()
    with django_capture_on_commit_callbacks(execute=True):
        with transaction.atomic():
            model("core.User").objects.filter(pk=user.pk).update(full_name="Действие издателя")
            events.publish(EVENT, user_ids=[user.pk])
    assert model("core.User").objects.get(pk=user.pk).full_name == "Действие издателя"
    assert _notes().count() == 0
    assert len(env.calls(EVENT)) == 1
    errors = [r for r in caplog.records if r.name == "apps.core.events" and r.levelno >= logging.ERROR]
    assert errors
    assert any(r.exc_info and "сбой вида" in str(r.exc_info[1]) for r in errors)
