"""T-4131: границы модулей и сброс стенда среза 004 (FR-301, FR-313). Сценарии спеки — «Каталог видов и колокольчик» и
«Сброс стенда»: `notify` подключается к ядру, `org` и сервис-деску только через шину и точки расширения (CONTRACT-004
§ 6.1 «Границы», § 3.1), без него они ведут себя как после среза 003; сброс стенда очищает данные среза (§ 7.4, § 8.1–8.3).
Имена кода среза 004 импортируются внутри тестов."""
import ast
import hashlib
import importlib
import logging
import os
import re
import secrets
from datetime import timedelta
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.utils import timezone

from tests import factories, support
from tests import support_org
from tests import support_servicedesk as sd
from tests.support_notify import FakeBots
from tests.support import model

MIGRATE = pytest.mark.django_db(databases=["default", "migrate"])
PLAIN = pytest.mark.django_db

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."
CALENDAR = "apps.org.services.calendar"
FOUR = ("servicedesk.ticket_created", "servicedesk.assignee_changed", "servicedesk.reply_received",
        "servicedesk.ticket_closed")
MODULE_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+")


# --- разбор импортов (как в test_sd_boundaries.py) ---------------------------------------------------------------

def _targets(source: str, package: list[str]) -> set[str]:
    """Абсолютные имена, от которых зависит файл (разбор `ast`): `import a.b`; `from a.b import c` — имя `a.b.c`
    (у `from a.b import *` — `a.b`); относительные импорты; `import_module("…")`/`__import__("…")`; строка-путь модуля
    целиком (`"apps.x.y"`) вне докстрингов."""
    tree = ast.parse(source)
    docstrings = set()
    for parent in ast.walk(tree):
        if isinstance(parent, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and parent.body:
            first = parent.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                module = ".".join(base + (node.module.split(".") if node.module else []))
            else:
                module = node.module or ""
            for alias in node.names:
                found.add(module if alias.name == "*" else f"{module}.{alias.name}")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in ("import_module", "__import__") and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                found.add(node.args[0].value)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and id(node) not in docstrings \
                and MODULE_PATH.fullmatch(node.value):
            found.add(node.value)
    return found


def _under(name: str, root: str) -> bool:
    return name == root or name.startswith(root + ".")


def _scan(*parts: str, bad) -> list[str]:
    root = support.BACKEND_DIR.joinpath(*parts)
    files = sorted(root.rglob("*.py"))
    assert files, f"нет исходников в {root}"
    offenders = []
    for path in files:
        rel = path.relative_to(support.BACKEND_DIR).with_suffix("")
        package = list(rel.parts[:-1])
        hits = sorted(n for n in _targets(path.read_text(encoding="utf-8"), package) if bad(n))
        if hits:
            offenders.append(f"{path.relative_to(support.BACKEND_DIR)}: {hits}")
    return offenders


# --- FR-301: границы модулей (CONTRACT-004 § 6.1 «Границы») --------------------------------------------------------

def test_notify_does_not_import_servicedesk():
    """FR-301: в `apps/notify/**` нет импорта `apps.servicedesk` (ни `import`, ни `from … import`, ни `import_module`):
    `notify` узнаёт о заявках только из событий шины и видов точки `notification_kinds`."""
    offenders = _scan("apps", "notify", bad=lambda name: _under(name, "apps.servicedesk"))
    assert offenders == [], f"notify импортирует servicedesk: {offenders}"


def test_notify_does_not_import_org_except_calendar_service():
    """FR-301: из `apps.org` в `apps/notify/**` берётся только сервис рабочего календаря `apps.org.services.calendar`;
    моделей, членства и прочих сервисов `org` в импортах нет."""
    offenders = _scan("apps", "notify", bad=lambda name: _under(name, "apps.org") and not _under(name, CALENDAR))
    assert offenders == [], f"notify импортирует org сверх календаря: {offenders}"


def test_core_org_and_servicedesk_do_not_import_notify():
    """FR-301: в `apps/core/**`, `apps/org/**`, `apps/servicedesk/**` нет импорта `apps.notify`: ядро и модули работают
    без приложения `notify` и подключаются к нему только через шину и точки расширения."""
    offenders = []
    for app in ("core", "org", "servicedesk"):
        offenders += _scan("apps", app, bad=lambda name: _under(name, "apps.notify"))
    assert offenders == [], f"модуль импортирует notify: {offenders}"


# --- FR-301, FR-313: без регистраций notify (CONTRACT-004 § 3.1 «top_bar_items», «Сброс реестров») ----------------------

@PLAIN
def test_without_notify_registrations_header_has_no_bell(no_extensions):
    """FR-301: при пустых реестрах (`extensions.empty()`) `top_bar == []`, а шапка совпадает с шапкой после среза 003:
    ссылки профиля, безопасности и выхода есть, колокольчика, соединения `ws-connect` и адреса `/ws/notify/` нет."""
    from apps.core import extensions

    for point in ("notification_kinds", "top_bar_items"):
        assert extensions.registered(point) == [], f"реестр {point} не пуст внутри extensions.empty()"
    user = support.make_employee()
    client = support.logged_in(user)
    response = client.get("/")
    assert response.status_code == 200
    assert response.context["top_bar"] == [], "без регистраций top_bar пуст"
    html = response.content.decode()
    match = re.search(r'<header\s+id="top-bar".*?</header>', html, re.S)
    assert match, "в странице нет шапки #top-bar"
    header = match.group(0)
    for hook in ("data-bell", "notify-bell", "ws-connect", "/ws/notify/"):
        assert hook not in html, f"в странице без notify есть {hook}"
    for href in ('href="/me/"', 'href="/me/security/"', 'action="/logout/"'):
        assert href in header, f"в шапке пропала прежняя ссылка {href}"


@PLAIN
def test_without_notify_registrations_servicedesk_events_publish_without_subscriber(
        bus, caplog, django_capture_on_commit_callbacks):
    """FR-313: если на шине нет подписчиков `notify`, создание, назначение, письмо заявителя и закрытие публикуют свои
    события без ошибок (в логе `apps.core.events` нет записей уровня ERROR), а уведомлений и доставок не появляется."""
    from apps.core import events
    from apps.servicedesk.services import assignment, closing, tickets

    for name in FOUR:
        assert events.subscribers(name) == [], f"на шине внутри events.empty() есть подписчик {name}"
    bus.listen(*FOUR)
    queue = sd.make_queue()
    sd.configure_servicedesk(domains=["corp.test"], default_queue=queue)
    second = support.make_employee()
    support_org.make_member(second, queue.unit)
    category = sd.make_category(queue=queue)
    email = factories.new_email("req").lower()
    with caplog.at_level(logging.DEBUG, logger="apps.core.events"):
        with django_capture_on_commit_callbacks(execute=True):
            created = tickets.create(channel=tickets.MAIL, subject="Не печатает принтер", text="Принтер не печатает",
                                     requester_email=email, category=category, inbound_id=sd.make_inbound().pk)
        ticket = model("servicedesk.Ticket").objects.get(pk=created.ticket.pk)
        with django_capture_on_commit_callbacks(execute=True):
            assignment.assign(ticket, second, actor=second)
        ticket.refresh_from_db()
        with django_capture_on_commit_callbacks(execute=True):
            tickets.add_incoming(ticket, author_email=email, text="Добавляю подробности")
        ticket.refresh_from_db()
        closed = model("servicedesk.Status").objects.get(kind="closed", is_default=True)
        with django_capture_on_commit_callbacks(execute=True):
            closing.close(ticket, closed, "Заменили картридж", actor=second)
    for name in FOUR:
        assert len(bus.calls(name)) == 1, f"событие {name} опубликовано не один раз"
        assert bus.calls(name)[0]["number"] == ticket.number
    errors = [r for r in caplog.records if r.name == "apps.core.events" and r.levelno >= logging.ERROR]
    assert errors == [], "публикация без подписчика дала ошибку шины"
    assert model("notify.Notification").objects.count() == 0, "без подписчика появились уведомления"
    assert model("notify.Delivery").objects.count() == 0, "без подписчика появились доставки"


# --- помощники сброса стенда ---------------------------------------------------------------------------------------

@pytest.fixture
def reset_env(monkeypatch, settings, protected_root):
    """Окружение сброса стенда: `E2E_STAND=1`, ящик не задан, том во временной папке; адреса ботов — из окружения
    службы `test` (`fakebots`)."""
    monkeypatch.setenv("E2E_STAND", "1")
    settings.IMAP_HOST = ""
    settings.TELEGRAM_API_BASE = os.environ.get("TELEGRAM_API_BASE", settings.TELEGRAM_API_BASE)
    settings.MAX_API_BASE = os.environ.get("MAX_API_BASE", settings.MAX_API_BASE)
    return protected_root


def _on_migrate(model_name: str):
    return model(model_name).objects.using("migrate")


def _owner():
    """Сотрудник, созданный через соединение `migrate` (соединения `default` тест не трогает: его блокировка мешала бы
    очистке таблиц)."""
    user = model("core.User")(email=factories.new_email(), full_name="Тест Тестов", state="active")
    user.set_password(factories.new_password())
    user.save(using="migrate")
    return user


def _run(command: str, *args) -> str:
    out = StringIO()
    call_command(command, *args, stdout=out)
    return out.getvalue()


SLICE_MODELS = ("Delivery", "Notification", "Digest", "PushSubscription", "ChatBinding", "BindCode", "BotChat",
                "UserNotifySettings")


def _fill_slice():
    """Данные среза через `migrate`: по строке в каждой таблице и изменённые настройки."""
    user = _owner()
    now = timezone.now()
    notification = _on_migrate("notify.Notification").create(
        user=user, kind="core.password_changed", text="Тестовое уведомление 1", url="/notifications/")
    digest = _on_migrate("notify.Digest").create(user=user, count_email=1, notification_ids=[notification.pk])
    _on_migrate("notify.Delivery").create(notification=notification, channel="email", state="waiting", due_at=now)
    _on_migrate("notify.Delivery").create(digest=digest, channel="telegram", state="held")
    _on_migrate("notify.PushSubscription").create(
        user=user, endpoint=f"https://fcm.googleapis.com/{secrets.token_hex(8)}", p256dh="p", auth="a")
    _on_migrate("notify.ChatBinding").create(user=user, channel="telegram", chat_id="100")
    _on_migrate("notify.BindCode").create(
        user=user, channel="max", code_hash=hashlib.sha256(b"12345678").hexdigest(), expires_at=now + timedelta(minutes=10))
    _on_migrate("notify.BotChat").create(channel="telegram", chat_id="100")
    _on_migrate("notify.UserNotifySettings").create(
        user=user, matrix={"core.password_changed": ["email"]}, digest_due_at=now)
    _on_migrate("notify.NotifySettings").filter(pk=1).update(
        webpush_enabled=True, telegram_enabled=True, max_enabled=True, email_delay_minutes=30, retention_days=120,
        defaults={"core.password_changed": []}, channel_status={"telegram": {"at": now.isoformat(), "code": "bad_token"}})


def _fill_queues():
    import django_rq
    from tests.support_notify import _commit_callbacks

    with _commit_callbacks():  # django-rq 4.2 ставит задания после фиксации
        django_rq.get_queue("notify").enqueue("time.time")
        django_rq.get_queue("maintenance").enqueue("time.time")


def _assert_slice_cleared(label: str):
    for name in SLICE_MODELS:
        assert _on_migrate(f"notify.{name}").count() == 0, f"{label}: таблица {name} не очищена"
    assert _on_migrate("notify.NotifySettings").count() == 1, f"{label}: строка настроек не одна"
    row = _on_migrate("notify.NotifySettings").get(pk=1)
    assert (row.webpush_enabled, row.telegram_enabled, row.max_enabled, row.email_delay_minutes, row.retention_days,
            row.defaults, row.channel_status) == (False, False, False, 15, 90, {}, {}), \
        f"{label}: настройки не как после миграции данных"


# --- FR-301: сброс стенда (CONTRACT-004 § 8.3) -----------------------------------------------------------------------

@MIGRATE
def test_stand_reset_of_notify_clears_slice_data(reset_env):
    """FR-301: команда `e2e_reset_stand` и прямой вызов `apps.notify.stand.stand_reset()` стирают все строки `Delivery`,
    `Notification`, `Digest`, `PushSubscription`, `ChatBinding`, `BindCode`, `BotChat`, `UserNotifySettings`, пересоздают
    `NotifySettings` (`pk=1`, значения миграции) и очищают очередь `notify`; очередь `maintenance` не трогается."""
    import django_rq
    from apps.notify import stand

    _fill_slice()
    _fill_queues()
    for name in SLICE_MODELS:
        assert _on_migrate(f"notify.{name}").exists(), f"до сброса нет данных {name}"
    assert django_rq.get_queue("notify").count == 1

    _run("e2e_reset_stand")

    _assert_slice_cleared("команда")
    assert django_rq.get_queue("notify").count == 0, "очередь notify не очищена командой"

    _fill_slice()
    _fill_queues()
    stand.stand_reset()

    _assert_slice_cleared("stand_reset()")
    assert django_rq.get_queue("notify").count == 0, "очередь notify не очищена stand_reset()"
    assert django_rq.get_queue("maintenance").count == 1, "stand_reset() тронул очередь maintenance"


@MIGRATE
def test_stand_reset_of_notify_clears_presence_in_valkey_and_polling_cursors(reset_env):
    """FR-301: `stand_reset()` удаляет ключи `notify:online:*` и не трогает прочие ключи Valkey (`crm-asgi:*`, `rq:*`);
    строки `BotState` остаются, у каждой `cursor=""` и `last_error=""`, `bot_username` сохраняется (решение C10)."""
    from apps.core.services import valkey
    from apps.notify import stand

    first, second = _owner(), _owner()
    _on_migrate("notify.BotState").create(channel="telegram", cursor="42", bot_username="stand_notify_bot",
                                          last_error="conflict")
    _on_migrate("notify.BotState").create(channel="max", cursor="17", bot_username="stand_max_bot",
                                          last_error="bad_token")
    conn = valkey.conn()
    stamp = timezone.now().timestamp()
    online = [f"notify:online:{first.pk}", f"notify:online:{second.pk}"]
    others = [f"crm-asgi:probe-{secrets.token_hex(4)}", f"rq:probe-{secrets.token_hex(4)}"]
    conn.zadd(online[0], {"c1": stamp, "c2": stamp})
    conn.zadd(online[1], {"c3": stamp})
    for name in others:
        conn.set(name, "1")

    stand.stand_reset()

    for name in online:
        assert conn.exists(name) == 0, "ключ присутствия не удалён"
    for name in others:
        assert conn.exists(name) == 1, "сброс удалил чужой ключ Valkey"
    states = {row.channel: row for row in _on_migrate("notify.BotState").all()}
    assert set(states) == {"telegram", "max"}, "строки BotState удалены"
    assert (states["telegram"].cursor, states["telegram"].last_error, states["telegram"].bot_username) == \
        ("", "", "stand_notify_bot")
    assert (states["max"].cursor, states["max"].last_error, states["max"].bot_username) == ("", "", "stand_max_bot")


@MIGRATE
def test_stand_reset_of_notify_resets_fakebots(reset_env, settings):
    """FR-301: сброс стенда зовёт `POST /_test/reset` учебной службы по адресу `settings.TELEGRAM_API_BASE`: события,
    отправленные сообщения и счётчик `update_id` очищены (после сброса первое событие снова получает номер 1); если адрес
    равен `https://api.telegram.org`, к `fakebots` сброс не обращается (решение C11): события и сообщения остаются."""
    from apps.notify import stand

    fake = FakeBots()
    fake.reset()
    bot = "t-" + secrets.token_hex(8)
    event = {"message": {"chat": {"id": 100, "type": "private"}, "from": {"id": 100}, "text": "/start"}}

    def fill():
        assert fake.put_telegram(event) == [1], "после сброса номера событий начинаются с 1"
        fake._call("POST", f"/bot{bot}/sendMessage", {"chat_id": 100, "text": "проба"})
        assert len(fake.sent("telegram")) == 1
        assert len(fake._call("GET", f"/bot{bot}/getUpdates?timeout=0&offset=0")["result"]) == 1

    def assert_empty(label):
        assert fake.sent("telegram") == [], f"{label}: отправленные сообщения остались"
        assert fake._call("GET", f"/bot{bot}/getUpdates?timeout=0&offset=0")["result"] == [], \
            f"{label}: события остались"

    fill()
    stand.stand_reset()
    assert_empty("stand_reset()")

    fill()
    _run("e2e_reset_stand")
    assert_empty("команда")

    # адрес настоящего Telegram: `fakebots` не вызывается (C11); клиент создан до подмены адреса и ходит в учебную службу
    fill()
    fakebots_base = settings.TELEGRAM_API_BASE
    settings.TELEGRAM_API_BASE = "https://api.telegram.org"
    try:
        stand.stand_reset()
    finally:
        settings.TELEGRAM_API_BASE = fakebots_base
    assert len(fake.sent("telegram")) == 1, "при адресе api.telegram.org сброс обратился к fakebots (сообщение очищено)"
    assert len(fake._call("GET", f"/bot{bot}/getUpdates?timeout=0&offset=0")["result"]) == 1, \
        "при адресе api.telegram.org сброс обратился к fakebots (событие очищено)"
    fake.reset()


# --- FR-301: команда e2e_notify_tick (CONTRACT-004 § 8.1, § 8.2) ------------------------------------------------------

def _delivery(user, channel, state, due_at, *, enqueued_at=None):
    notification = model("notify.Notification").objects.create(
        user=user, kind="core.password_changed", text="Тестовое уведомление 1", url="/notifications/")
    return model("notify.Delivery").objects.create(
        notification=notification, channel=channel, state=state, due_at=due_at, enqueued_at=enqueued_at)


def _snapshot(user):
    delivery = model("notify.Delivery").objects.order_by("pk").values_list("pk", "state", "due_at", "enqueued_at")
    codes = model("notify.BindCode").objects.order_by("pk").values_list("pk", "expires_at", "used_at")
    notes = model("notify.Notification").objects.order_by("pk").values_list("pk", "created_at", "read_at")
    return list(delivery), list(codes), list(notes)


@PLAIN
def test_e2e_notify_tick_refused_without_e2e_stand(monkeypatch, django_assert_num_queries):
    """FR-301: без `E2E_STAND=1` команда отказывает `CommandError` с текстом защиты раньше любого запроса к базе
    (`django_assert_num_queries(0)`) при любом наборе аргументов, данные не изменены."""
    monkeypatch.delenv("E2E_STAND", raising=False)
    user = support.make_employee()
    now = timezone.now()
    _delivery(user, "telegram", "waiting", now + timedelta(minutes=10), enqueued_at=now)
    model("notify.BindCode").objects.create(
        user=user, channel="max", code_hash=hashlib.sha256(b"12345678").hexdigest(), expires_at=now + timedelta(minutes=5))
    before = _snapshot(user)
    for args in ((), ("--shift", "5"), ("--age-codes", "5"), ("--age-days", "1"), ("--retention",)):
        with django_assert_num_queries(0):
            with pytest.raises(CommandError) as refused:
                call_command("e2e_notify_tick", *args, stdout=StringIO())
        assert str(refused.value) == REFUSAL, f"аргументы {args}"
    assert _snapshot(user) == before, "отказавшая команда изменила данные"


@PLAIN
def test_e2e_notify_tick_shift_moves_waiting_deliveries_back_and_runs_tick_when_e2e_stand(monkeypatch):
    """FR-301: `--shift 5` при `E2E_STAND=1` сдвигает на 5 минут назад `due_at` всех доставок `waiting` с непустым сроком
    (любого канала) и обнуляет их `enqueued_at`; `held` и `sent`, сроки кодов и `digest_due_at` не трогает; затем всегда
    выполняет обход (доставка, ставшая просроченной, ставится в очередь); вывод — одна строка по формату § 8.2."""
    monkeypatch.setenv("E2E_STAND", "1")
    user = support.make_employee()
    now = timezone.now()
    soon = _delivery(user, "telegram", "waiting", now + timedelta(minutes=3), enqueued_at=now)
    later = _delivery(user, "max", "waiting", now + timedelta(minutes=60))
    mail = _delivery(user, "email", "waiting", now + timedelta(minutes=30))
    held = _delivery(user, "webpush", "held", None)
    sent = _delivery(user, "telegram", "sent", now + timedelta(minutes=40), enqueued_at=now)
    code = model("notify.BindCode").objects.create(
        user=user, channel="max", code_hash=hashlib.sha256(b"12345678").hexdigest(), expires_at=now + timedelta(minutes=5))
    prefs = model("notify.UserNotifySettings").objects.create(user=user, digest_due_at=now + timedelta(hours=1))
    for row in (soon, later, mail, held, sent, code, prefs):
        row.refresh_from_db()
    started = timezone.now()

    output = _run("e2e_notify_tick", "--shift", "5")

    assert output.count("\n") == 1 and output.endswith("\n"), "вывод — одна строка"
    assert re.fullmatch(
        r"notify_tick: shifted=3 aged_codes=0 aged_rows=0 emails=0 released=0 requeued=1 digests=0 codes=0\n", output), \
        f"строка вывода не по формату § 8.2: {output!r}"
    assert user.email not in output
    five = timedelta(minutes=5)
    old = {row.pk: row.due_at for row in (soon, later, mail, held, sent)}
    fresh = {row.pk: type(row).objects.get(pk=row.pk) for row in (soon, later, mail, held, sent)}
    assert fresh[soon.pk].due_at == old[soon.pk] - five
    assert fresh[later.pk].due_at == old[later.pk] - five
    assert fresh[mail.pk].due_at == old[mail.pk] - five
    assert fresh[held.pk].due_at is None and fresh[held.pk].state == "held"
    assert fresh[sent.pk].due_at == old[sent.pk] and fresh[sent.pk].enqueued_at == sent.enqueued_at
    assert fresh[later.pk].enqueued_at is None and fresh[mail.pk].enqueued_at is None
    assert fresh[soon.pk].enqueued_at is not None and fresh[soon.pk].enqueued_at >= started, \
        "обход не поставил просроченную доставку в очередь (enqueued_at не обновлён после сдвига)"
    assert type(code).objects.get(pk=code.pk).expires_at == code.expires_at, "без --age-codes срок кода сдвинут"
    assert type(prefs).objects.get(pk=prefs.pk).digest_due_at == prefs.digest_due_at, "digest_due_at сдвинут"
