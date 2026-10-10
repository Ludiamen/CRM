"""T-4101: каталог видов уведомлений и пять каналов (FR-301…FR-306, FR-321, FR-344). Сценарии 1, 3 и 4 спеки среза 004.

Восемь видов трёх модулей (таблица контракта § 3.2), сборка каталога из точки `notification_kinds` при каждом вызове,
повтор кода как отказ запуска, пять каналов и один столбец push, портал всегда включён, обязательные виды, запись
`Notification`. Код среза на уровне модуля не импортируется: имена берутся внутри тестов (CONTRACT-004, шапка).
"""
import dataclasses
import datetime
import importlib
import secrets

import pytest

from tests import support, support_notify
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

# Таблица контракта § 3.2: код, название, модуль, order, mandatory, default_channels, events, external_text.
ALL_CHANNELS = ("portal", "email", "push", "telegram", "max")
TABLE = [
    ("servicedesk.new_in_queue", "Новая заявка в моей очереди", "Сервис-деск", 10, False, ALL_CHANNELS,
     ("servicedesk.ticket_created", "servicedesk.ticket_transferred", "servicedesk.ticket_reopened"),
     "Новая заявка в вашей очереди"),
    ("servicedesk.assigned", "Мне назначили заявку", "Сервис-деск", 20, False, ALL_CHANNELS,
     ("servicedesk.ticket_created", "servicedesk.assignee_changed"), "Вам назначена заявка"),
    ("servicedesk.requester_replied", "Заявитель ответил", "Сервис-деск", 30, False, ALL_CHANNELS,
     ("servicedesk.reply_received",), "Заявитель ответил по вашей заявке"),
    ("servicedesk.reply_failed", "Ответ заявителю не ушёл", "Сервис-деск", 40, False, ALL_CHANNELS,
     ("servicedesk.reply_not_sent", "servicedesk.mail_failed"), "Ответ заявителю не ушёл"),
    ("core.new_device", "Вход с нового устройства", "Ядро", 110, True, ("portal",), ("core.new_device",), ""),
    ("core.password_changed", "Пароль изменён", "Ядро", 120, True, ("portal",), ("core.password_changed",), ""),
    ("core.second_factor_reset", "Второй фактор сброшен", "Ядро", 130, True, ("portal",),
     ("core.second_factor_reset",), ""),
    ("notify.channel_unbound", "Канал отвязан", "Уведомления", 200, True, ("portal",), (), ""),
]
MANDATORY_CODES = {row[0] for row in TABLE if row[4]}


# --- помощники только этого файла -------------------------------------------------------------------

def _mod(name: str):
    return importlib.import_module(name)


def _kinds():
    return _mod("apps.notify.services.kinds")


def _prefs():
    return _mod("apps.notify.services.prefs")


def _dispatch():
    return _mod("apps.notify.services.dispatch")


def _ext():
    return _mod("apps.core.extensions")


def _kind(**over):
    """Тестовый вид с уникальным кодом; все пять каналов по умолчанию."""
    NotificationKind = _ext().NotificationKind
    fields = {"code": "test." + secrets.token_hex(4), "title": "Тестовый вид", "module": "Тест",
              "default_channels": ALL_CHANNELS}
    fields.update(over)
    return NotificationKind(**fields)


def _by_code(kinds_list) -> dict:
    return {kind.code: kind for kind in kinds_list}


def _queue_member():
    """Сотрудник, прямой участник узла-очереди: ему доступны все виды сервис-деска."""
    queue = sd.make_queue(org.make_unit(f"Очередь {secrets.token_hex(3)}"))
    user = support.make_employee()
    org.make_member(user, queue.unit)
    return user


def _register_core_and_notify():
    """Решение E12: регистрации ядра и `notify` без сервис-деска (вызывать внутри `extensions.empty()`)."""
    extensions = _ext()
    extensions.register("notification_kinds", _mod("apps.core.notify_kinds").notification_kinds)
    extensions.register("notification_kinds", _mod("apps.notify.extensions").notification_kinds)


# --- каталог: состав ---------------------------------------------------------------------------------

def test_catalog_contains_eight_kinds_from_three_modules():
    """FR-301, FR-304, FR-305, FR-344: в каталоге ровно восемь видов, в порядке таблицы, из модулей «Сервис-деск»,
    «Ядро» и «Уведомления»."""
    catalog = _kinds().catalog()
    assert [kind.code for kind in catalog] == [row[0] for row in TABLE]
    assert {kind.module for kind in catalog} == {"Сервис-деск", "Ядро", "Уведомления"}
    assert [kind.module for kind in catalog].count("Сервис-деск") == 4
    assert [kind.module for kind in catalog].count("Ядро") == 3
    assert [kind.module for kind in catalog].count("Уведомления") == 1


def test_catalog_kind_codes_titles_and_modules_match_plan_table():
    """FR-301, FR-304, FR-305, FR-344: код, название, модуль и order каждого вида — буквально как в таблице плана
    (контракт § 3.2)."""
    by_code = _by_code(_kinds().catalog())
    for code, title, module, order, *_rest in TABLE:
        kind = by_code[code]
        assert kind.title == title, code
        assert kind.module == module, code
        assert kind.order == order, code


def test_catalog_default_channels_per_kind():
    """FR-301, FR-304, FR-305, FR-344: каналы по умолчанию, обязательность, события и текст для внешних каналов
    каждого вида совпадают с таблицей (виды сервис-деска — все пять, безопасность и «Канал отвязан» — только портал)."""
    by_code = _by_code(_kinds().catalog())
    for code, _title, _module, _order, mandatory, channels, events, external in TABLE:
        kind = by_code[code]
        assert tuple(kind.default_channels) == channels, code
        assert kind.mandatory is mandatory, code
        assert tuple(kind.events) == events, code
        assert kind.external_text == external, code


def test_kind_has_code_title_module_default_channels_mandatory_and_order():
    """FR-301: у вида есть код, название, модуль, каналы по умолчанию, признак «обязательный» и порядок; поля и значения
    по умолчанию — как в § 3.1; каталог сортирует по `(order, порядок регистрации функций)`."""
    extensions = _ext()
    names = [field.name for field in dataclasses.fields(extensions.NotificationKind)]
    assert names == ["code", "title", "module", "events", "build", "external_text", "default_channels", "mandatory",
                     "available", "still_relevant", "order"]
    bare = extensions.NotificationKind(code="t.bare", title="Голый", module="Тест")
    assert bare.events == ()
    assert bare.build("any.event", {}) == []
    assert bare.external_text == ""
    assert tuple(bare.default_channels) == ("portal",)
    assert bare.mandatory is False
    assert bare.available(object()) is True
    assert bare.still_relevant(1, "x:1") is True
    assert bare.order == 0
    with pytest.raises(dataclasses.FrozenInstanceError):
        bare.code = "t.other"
    with extensions.empty():
        first_a, first_b = _kind(order=30), _kind(order=10)
        second_a, second_b = _kind(order=10), _kind(order=20)
        extensions.register("notification_kinds", lambda: [first_a, first_b])
        extensions.register("notification_kinds", lambda: [second_a, second_b])
        catalog = _kinds().catalog()
    # order 10 у двух видов: сначала вид из функции, зарегистрированной раньше
    assert [kind.code for kind in catalog] == [first_b.code, second_a.code, second_b.code, first_a.code]


# --- каталог: сборка и расширение -------------------------------------------------------------------

def test_duplicate_kind_code_fails_app_startup_instead_of_silent_replace():
    """FR-301: повтор кода вида — `ImproperlyConfigured` и у `catalog()`, и у `kinds.check()`, и у
    `check_kinds()` приложения (останавливает запуск), вид не заменяется молча."""
    from django.apps import apps
    from django.core.exceptions import ImproperlyConfigured
    extensions = _ext()
    kinds = _kinds()
    with extensions.empty():
        _register_core_and_notify()
        clash = _kind(code="core.new_device", title="Подмена")
        extensions.register("notification_kinds", lambda: [clash])
        with pytest.raises(ImproperlyConfigured):
            kinds.catalog()
        with pytest.raises(ImproperlyConfigured):
            kinds.check()
        with pytest.raises(ImproperlyConfigured):
            apps.get_app_config("notify").check_kinds()
    with extensions.empty():
        twin = _kind()
        extensions.register("notification_kinds", lambda: [twin, twin])
        with pytest.raises(ImproperlyConfigured):
            kinds.catalog()
    # обычный каталог после выхода из блока цел
    assert _by_code(kinds.catalog())["core.new_device"].title == "Вход с нового устройства"
    kinds.check()
    apps.get_app_config("notify").check_kinds()


def test_catalog_without_servicedesk_registrations_has_core_and_notify_kinds_only():
    """FR-301: без регистрации сервис-деска (решение E12) в каталоге три вида ядра и «Канал отвязан»; сервис-деск,
    как и пустой реестр (`kinds.catalog() == []`), ничего не меняют в коде `notify`."""
    extensions = _ext()
    kinds = _kinds()
    with extensions.empty():
        assert kinds.catalog() == []
        _register_core_and_notify()
        catalog = kinds.catalog()
    assert [kind.code for kind in catalog] == ["core.new_device", "core.password_changed", "core.second_factor_reset",
                                              "notify.channel_unbound"]
    assert {kind.module for kind in catalog} == {"Ядро", "Уведомления"}
    assert not any(kind.code.startswith("servicedesk.") for kind in catalog)


def test_kind_registered_through_extension_point_appears_without_changing_notify_code(bus):
    """FR-301: вид, зарегистрированный через точку `notification_kinds`, виден в каталоге, находится по коду и по
    событию, его события попадают в `event_names()`, а событие создаёт уведомление — код `notify` не менялся."""
    extensions = _ext()
    kinds = _kinds()
    user = support.make_employee()
    event = "test.thing_happened"
    kind = _kind(events=(event,), build=lambda name, data: [
        _ext().Draft(user_id=data["user_id"], text=f"{name}: {data['what']}", url="/me/", object_ref="thing:1")])
    with extensions.empty():
        support_notify.register_kind(kind)
        assert [item.code for item in kinds.catalog()] == [kind.code]
        assert kinds.get(kind.code).title == kind.title
        assert [item.code for item in kinds.for_event(event)] == [kind.code]
        assert kinds.event_names() == [event]
        created = _dispatch().on_event(event, user_id=user.pk, what="важное")
    notes = model("notify.Notification").objects.filter(user=user, kind=kind.code)
    assert created == list(notes.values_list("pk", flat=True))
    note = notes.get()
    assert (note.text, note.url, note.object_ref) == (f"{event}: важное", "/me/", "thing:1")


def test_catalog_is_reassembled_from_extension_point_on_each_call():
    """FR-301: функция точки зовётся при каждом вызове `catalog()` (кэша нет): изменение, сделанное между вызовами,
    видно сразу."""
    extensions = _ext()
    kinds = _kinds()
    first, second = _kind(order=1), _kind(order=2)
    state = {"kinds": [first], "calls": 0}

    def provide():
        state["calls"] += 1
        return list(state["kinds"])

    with extensions.empty():
        extensions.register("notification_kinds", provide)
        before = state["calls"]
        assert [kind.code for kind in kinds.catalog()] == [first.code]
        assert state["calls"] > before
        state["kinds"] = [first, second]
        before = state["calls"]
        assert [kind.code for kind in kinds.catalog()] == [first.code, second.code]
        assert state["calls"] > before
        state["kinds"] = [second]
        before = state["calls"]
        assert [kind.code for kind in kinds.catalog()] == [second.code]
        assert state["calls"] > before


# --- каналы ------------------------------------------------------------------------------------------

def test_channels_are_exactly_portal_email_push_telegram_max_in_order():
    """FR-302: каналов пять, в порядке «На портале», «Почта», «Push в браузере», «Telegram», «MAX»; внешние — без
    портала; ячейки действующей таблицы идут в том же порядке."""
    kinds = _kinds()
    assert tuple(kinds.CHANNELS) == ALL_CHANNELS
    assert tuple(kinds.EXTERNAL) == ("email", "push", "telegram", "max")
    table = _prefs().effective(_queue_member())
    assert table.rows
    for row in table.rows:
        assert list(row.cells) == list(ALL_CHANNELS)
    assert set(table.channels) == set(ALL_CHANNELS)  # порядок ключей Table.channels не задан (доп. 18 (в))
    for kind in kinds.catalog():
        assert set(kind.default_channels) <= set(ALL_CHANNELS)


def test_push_is_single_column_for_tab_notification_and_web_push(webpush_on, django_capture_on_commit_callbacks):
    """FR-302: столбец `push` один; у доставки нет каналов `push` и `portal`; включённая ячейка `push` даёт
    `Delivery(channel="webpush")` и ничего больше, выключенная — не даёт."""
    Delivery = model("notify.Delivery")
    assert {value for value, _label in Delivery.Channel.choices} == {"email", "webpush", "telegram", "max"}
    user = support.make_employee()
    support_notify.subscribe(user)
    prefs = _prefs()
    prefs.save(user, quiet_mode="none")
    extensions = _ext()
    kind = _kind(default_channels=("portal", "push"))
    with extensions.empty():
        support_notify.register_kind(kind)
        assert prefs.channels_for(user.pk, kind) == ["push"]
        assert prefs.effective(user).web_push_available is True
        with django_capture_on_commit_callbacks(execute=True):
            ids = _dispatch().create(kind.code, [_ext().Draft(user_id=user.pk, text="Текст", url="/me/")])
        deliveries = list(Delivery.objects.filter(notification_id__in=ids))
        assert [(item.channel, item.state) for item in deliveries] == [("webpush", "waiting")]
        # ячейка push выключена — доставки Web Push нет, запись на портале остаётся
        prefs.save(user, table={kind.code: ["email"]})
        with django_capture_on_commit_callbacks(execute=True):
            ids = _dispatch().create(kind.code, [_ext().Draft(user_id=user.pk, text="Ещё", url="/me/")])
        assert model("notify.Notification").objects.filter(pk__in=ids).count() == 1
        assert not Delivery.objects.filter(notification_id__in=ids, channel="webpush").exists()


# --- канал «На портале» -----------------------------------------------------------------------------

def test_portal_channel_is_always_on_for_every_kind():
    """FR-303: «На портале» включён у каждого вида каталога и в каждой строке действующей таблицы, даже если
    администратор пустым списком выключил все внешние каналы; канал доступен всегда."""
    extensions, kinds, prefs = _ext(), _kinds(), _prefs()
    for kind in kinds.catalog():
        assert "portal" in kind.default_channels, kind.code
    admin = support.make_admin()
    defaults = {kind.code: [] for kind in kinds.catalog() if not kind.mandatory}
    _mod("apps.notify.services.settings").update(actor=admin, defaults=defaults)
    user = _queue_member()
    table = prefs.effective(user)
    assert [row.kind.code for row in table.rows] == [row[0] for row in TABLE if not row[4]]
    for row in table.rows:
        assert row.cells["portal"] is True, row.kind.code
        assert row.cells["email"] is False, row.kind.code
        assert prefs.channels_for(user.pk, row.kind) == [], row.kind.code
    assert table.channels["portal"].available is True
    assert table.channels["portal"].reason == ""


def test_portal_channel_cannot_be_turned_off_by_employee_or_admin_defaults():
    """FR-303: `prefs.save` и `settings.update` отбрасывают `portal` молча, в `matrix` и `defaults` он не хранится,
    действующая таблица всегда даёт `portal: True`."""
    prefs, settings_service = _prefs(), _mod("apps.notify.services.settings")
    code = "servicedesk.new_in_queue"
    admin = support.make_admin()
    settings_service.update(actor=admin, defaults={code: ["portal", "email"]})
    assert model("notify.NotifySettings").objects.get(pk=1).defaults[code] == ["email"]
    user = _queue_member()
    assert prefs.save(user, table={code: ["portal"]}) is True  # email снят, portal молча отброшен
    stored = model("notify.UserNotifySettings").objects.get(user=user).matrix
    assert all("portal" not in channels for channels in stored.values())
    assert "email" not in stored[code]
    row = {row.kind.code: row for row in prefs.effective(user).rows}[code]
    assert row.cells["portal"] is True
    assert row.cells["email"] is False
    assert "portal" not in prefs.channels_for(user.pk, row.kind)


def test_employee_switches_email_push_and_messengers_per_kind_without_admin_pinning(bots_on):
    """FR-303, FR-321: сотрудник сам включает и выключает почту, push, Telegram и MAX по видам; значения
    администратора ничего не закрепляют; недоступные каналы без привязки не меняются."""
    prefs, settings_service = _prefs(), _mod("apps.notify.services.settings")
    ChatBinding = model("notify.ChatBinding")
    first, second = "servicedesk.new_in_queue", "servicedesk.assigned"
    settings_service.update(actor=support.make_admin(), defaults={first: ["email"], second: ["telegram"]})
    user = _queue_member()
    channels = prefs.effective(user).channels
    assert channels["telegram"].available is False and channels["telegram"].reason == "not_bound"
    assert channels["max"].available is False and channels["max"].reason == "not_bound"
    # без привязки ячейка telegram не меняется (решение B1): у третьего вида она включена по умолчанию, сотрудник
    # выключает все каналы вида — доступные (почта, push) выключаются, недоступный telegram остаётся включённым.
    # Снимок `matrix` зафиксирует и значение администратора у `first` (["email"]) — ниже проверяется то же значение.
    third = "servicedesk.requester_replied"
    cell_before = {row.kind.code: row for row in prefs.effective(user).rows}[third].cells["telegram"]
    assert cell_before is True
    prefs.save(user, table={third: []})
    third_cells = {row.kind.code: row for row in prefs.effective(user).rows}[third].cells
    assert third_cells["email"] is False and third_cells["push"] is False
    assert third_cells["telegram"] is True
    ChatBinding.objects.create(user=user, channel="telegram", chat_id=str(secrets.randbelow(10 ** 9)))
    ChatBinding.objects.create(user=user, channel="max", chat_id=str(secrets.randbelow(10 ** 9)))
    channels = prefs.effective(user).channels
    assert channels["telegram"].available is True and channels["max"].available is True
    by_code = lambda: {row.kind.code: row for row in prefs.effective(user).rows}  # noqa: E731
    assert prefs.channels_for(user.pk, by_code()[first].kind) == ["email"]  # пока действует значение администратора
    assert prefs.save(user, table={first: ["email", "push", "telegram", "max"], second: []}) is True
    assert prefs.channels_for(user.pk, by_code()[first].kind) == ["email", "push", "telegram", "max"]
    assert prefs.channels_for(user.pk, by_code()[second].kind) == []
    assert [name for name, on in by_code()[first].cells.items() if on] == ["portal", "email", "push", "telegram", "max"]
    assert [name for name, on in by_code()[second].cells.items() if on] == ["portal"]
    # потом сотрудник выключает часть каналов первого вида; администратор уже ничего не диктует
    prefs.save(user, table={first: ["push", "max"], second: ["telegram"]})
    assert prefs.channels_for(user.pk, by_code()[first].kind) == ["push", "max"]
    assert prefs.channels_for(user.pk, by_code()[second].kind) == ["telegram"]


# --- обязательные виды -------------------------------------------------------------------------------

def test_mandatory_flag_only_on_security_kinds_and_channel_unbound():
    """FR-305, FR-344: `mandatory` стоит у трёх видов безопасности и «Канал отвязан», у видов сервис-деска нет; у
    обязательных нет текста для внешних каналов; в таблице сотрудника они не строки, а `fixed`; «Канал отвязан» не
    привязан к событиям шины."""
    kinds, prefs = _kinds(), _prefs()
    catalog = kinds.catalog()
    assert {kind.code for kind in catalog if kind.mandatory} == MANDATORY_CODES
    assert not any(kind.mandatory for kind in catalog if kind.module == "Сервис-деск")
    assert all(kind.external_text == "" for kind in catalog if kind.mandatory)
    assert _by_code(catalog)["notify.channel_unbound"].events == ()
    table = prefs.effective(_queue_member())
    assert {kind.code for kind in table.fixed} == MANDATORY_CODES
    assert not MANDATORY_CODES & {row.kind.code for row in table.rows}
    for event_name in kinds.event_names():
        assert all(not kind.mandatory or kind.module == "Ядро" for kind in kinds.for_event(event_name))


def test_mandatory_kinds_have_only_portal_channel_in_defaults(webpush_on, django_capture_on_commit_callbacks):
    """FR-305: у обязательных видов в каналах по умолчанию только портал: внешних каналов нет, а запись на портале
    создаётся без единой доставки."""
    kinds, prefs, Delivery = _kinds(), _prefs(), model("notify.Delivery")
    user = support.make_employee()
    support_notify.subscribe(user)
    for code in sorted(MANDATORY_CODES):
        kind = kinds.get(code)
        assert tuple(kind.default_channels) == ("portal",), code
        assert prefs.channels_for(user.pk, kind) == [], code
        with django_capture_on_commit_callbacks(execute=True):
            ids = _dispatch().create(code, [_ext().Draft(user_id=user.pk, text="Текст", url="/me/")])
        assert len(ids) == 1, code
        assert not Delivery.objects.filter(notification_id__in=ids).exists(), code


# --- запись уведомления ------------------------------------------------------------------------------

def test_build_returns_drafts_with_recipient_text_url_and_object_ref(bus):
    """FR-306: `build(event, data)` возвращает черновики с получателем, одной строкой текста, ссылкой и объектом;
    одно событие — одна запись на каждый черновик с этими значениями."""
    extensions = _ext()
    first, second = support.make_employee(), support.make_employee()
    seen = []

    def build(name, data):
        seen.append((name, dict(data)))
        return [extensions.Draft(user_id=user.pk, text=f"Заявка {data['number']}", url=f"/t/{data['number']}/",
                                 object_ref=f"ticket:{data['number']}") for user in (first, second)]

    event = "test.drafts"
    kind = _kind(events=(event,), build=build)
    drafts = kind.build(event, {"number": 7})
    assert [(d.user_id, d.text, d.url, d.object_ref) for d in drafts] == [
        (first.pk, "Заявка 7", "/t/7/", "ticket:7"), (second.pk, "Заявка 7", "/t/7/", "ticket:7")]
    assert extensions.Draft(user_id=1, text="a", url="/").object_ref == ""
    with pytest.raises(dataclasses.FrozenInstanceError):
        drafts[0].text = "другое"
    seen.clear()
    with extensions.empty():
        support_notify.register_kind(kind)
        created = _dispatch().on_event(event, number=9)
    assert seen == [(event, {"number": 9})]
    notes = model("notify.Notification").objects.filter(pk__in=created).order_by("pk")
    assert [(n.user_id, n.kind, n.text, n.url, n.object_ref) for n in notes] == [
        (first.pk, kind.code, "Заявка 9", "/t/9/", "ticket:9"), (second.pk, kind.code, "Заявка 9", "/t/9/", "ticket:9")]


def test_notification_record_has_kind_recipient_created_text_url_and_read_at():
    """FR-306: у записи `Notification` есть вид, получатель, время создания, одна строка текста, ссылка и время
    прочтения; время создания задаётся при создании, прочтения по умолчанию нет; индексы — по § 2.2."""
    from django.utils import timezone
    Notification = model("notify.Notification")
    user = support.make_employee()
    created_at = timezone.now().replace(microsecond=0) - datetime.timedelta(days=3)
    note = Notification.objects.create(user=user, kind="core.new_device", text="Вход с нового устройства",
                                       url="/me/", created_at=created_at)
    note.refresh_from_db()
    assert (note.user_id, note.kind, note.text, note.url) == (user.pk, "core.new_device", "Вход с нового устройства",
                                                                "/me/")
    assert note.created_at == created_at  # не auto_now_add: время создания задаёт тест
    assert note.read_at is None
    assert note.object_ref == ""
    meta = Notification._meta
    assert meta.get_field("kind").max_length == 64
    assert meta.get_field("text").max_length == 300
    assert meta.get_field("url").max_length == 300
    assert meta.get_field("object_ref").max_length == 64
    assert meta.get_field("read_at").null is True
    assert not getattr(meta.get_field("created_at"), "auto_now_add", False)
    by_name = {index.name: index for index in meta.indexes}
    assert {"notify_notif_user_created", "notify_notif_unread", "notify_notif_obj_unread",
            "notify_notif_created"} <= set(by_name)
    assert list(by_name["notify_notif_user_created"].fields) == ["user", "-created_at"]
    assert list(by_name["notify_notif_unread"].fields) == ["user"]
    assert by_name["notify_notif_unread"].condition is not None
    assert list(by_name["notify_notif_obj_unread"].fields) == ["user", "object_ref"]
    assert by_name["notify_notif_obj_unread"].condition is not None
    assert list(by_name["notify_notif_created"].fields) == ["created_at"]
