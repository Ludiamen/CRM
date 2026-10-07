"""T-3136: команды восстановления из копии и сброса стенда (FR-201, FR-211, NFR-210). Сценарии — «Восстановление из копии».

Контракт: CONTRACT-003 § 8 (команды `e2e_*`, `servicedesk_after_restore`, точка `stand_reset`), 2.2 (последовательность
номеров), 3.4 (`sequence_state`, `set_sequence`, `using="migrate"`), 3.5 (соединение `migrate`).

Тесты `servicedesk_after_restore` и `e2e_reset_stand` идут с соединением `migrate`; данные, которые команда должна
увидеть, создаются тем же соединением (`using="migrate"`) и читаются через него; соединения `default` тест не трогает:
его блокировка читателя мешала бы очистке таблиц. Тесты `e2e_poll_mailbox`, `e2e_backdate`, `e2e_run_job` идут с
обычным `django_db` (§ 8.2, последний абзац). Стенд и `e2e_reset_stand` против стенда не запускаются.
"""
import re
import secrets
from datetime import datetime, timedelta, timezone as dt_timezone
from io import StringIO

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections
from django.utils import timezone

from tests import factories, support, support_org
from tests.support_servicedesk import (
    backdate, build_mail, configure_servicedesk, make_category, make_entry, make_inbound, make_participant, make_queue,
    make_requester, make_ticket, sequence_state, set_sequence)

MIGRATE = pytest.mark.django_db(databases=["default", "migrate"])
PLAIN = pytest.mark.django_db

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."
NEED_MIGRATE = "Нужен DATABASE_MIGRATE_URL: команда работает под владельцем схемы."
PROCESS_JOB = "apps.servicedesk.tasks.process_inbound"


# --- общие помощники файла ------------------------------------------------------------------------------------

@pytest.fixture
def keep_sequence():
    """Последовательность номеров не откатывается с транзакцией теста: возвращаем прежнее состояние сами."""
    saved = sequence_state()
    yield saved
    set_sequence(saved[0], is_called=saved[1])


@pytest.fixture
def reset_env(monkeypatch, settings, protected_root):
    """Окружение сброса стенда: флаг `E2E_STAND=1`, ящик не задан (без соединений с настоящим Dovecot), том во временной папке."""
    monkeypatch.setenv("E2E_STAND", "1")
    settings.IMAP_HOST = ""
    return protected_root


def _owner():
    """Сотрудник, созданный через соединение `migrate` (`created_by` очередей и справочников)."""
    User = support.model("core.User")
    user = User(email=factories.new_email(), full_name="Тест Тестов", state="active")
    user.set_password(factories.new_password())
    user.save(using="migrate")
    return user


def _ticket_on_migrate(**over):
    """Заявка со всем нужным, созданная через `migrate`."""
    queue = make_queue(created_by=_owner(), using="migrate")
    return make_ticket(queue=queue, using="migrate", **over), queue


def _all(model_name: str):
    return support.model(model_name).objects.using("migrate")


def _run(command: str, *args) -> str:
    out = StringIO()
    call_command(command, *args, stdout=out)
    return out.getvalue()


def _inbox_job_ids() -> list:
    import django_rq

    return [job.args[0] for job in django_rq.get_queue("inbox").jobs if job.func_name == PROCESS_JOB]


def _put_mailbox_state(**over):
    values = {"uidvalidity": 1, "last_uid": 0, "last_error": "старая ошибка"}
    stale = timezone.now() - timedelta(days=30)
    values.update({"connected_at": stale, "last_poll_at": stale, "last_ok_at": stale})
    values.update(over)
    _all("servicedesk.MailboxState").all().delete()
    return _all("servicedesk.MailboxState").create(pk=1, **values)


def _years_ago(moment: datetime, years: int) -> datetime:
    """Та же дата и время `years` лет назад (29 февраля — 28-е), как граница обезличивания (6.24)."""
    try:
        return moment.replace(year=moment.year - years)
    except ValueError:
        return moment.replace(year=moment.year - years, day=28)


# --- servicedesk_after_restore (8.4) --------------------------------------------------------------------------

@MIGRATE
def test_after_restore_shifts_sequence_1000_past_max_of_sequence_and_number(keep_sequence, monkeypatch):
    """FR-201, NFR-210: new = max(значение последовательности, наибольший номер) + 1000; вывод по формату 8.4.
    Команда не защищена `E2E_STAND` (8.4): флаг снят, команда работает."""
    monkeypatch.delenv("E2E_STAND", raising=False)
    ticket, queue = _ticket_on_migrate(number=5)
    make_ticket(queue=queue, using="migrate", number=25)
    set_sequence(40)

    output = _run("servicedesk_after_restore")

    assert output == "after_restore: sequence=1040 max_number=25 requeued=0\n"
    assert sequence_state() == (1040, True)


@MIGRATE
def test_after_restore_uses_max_ticket_number_when_greater_than_sequence(keep_sequence):
    """FR-201: если номер в базе больше последовательности (копия базы свежее счётчика), берётся номер заявки."""
    _ticket_on_migrate(number=500)
    set_sequence(10)

    output = _run("servicedesk_after_restore")

    assert output == "after_restore: sequence=1500 max_number=500 requeued=0\n"
    assert sequence_state() == (1500, True)


@MIGRATE
def test_after_restore_twice_never_lowers_sequence_and_never_repeats_a_number(keep_sequence):
    """FR-201, NFR-210: повторный запуск даёт ещё +1000; `is_called=False` читается как `last_value - 1`; номера не повторяются."""
    from apps.servicedesk.services import tickets

    set_sequence(7, is_called=False)  # следующий номер 7, то есть «текущее» значение 6; заявок нет

    first = _run("servicedesk_after_restore")
    after_first = sequence_state()
    second = _run("servicedesk_after_restore")
    after_second = sequence_state()

    assert first == "after_restore: sequence=1006 max_number=0 requeued=0\n"
    assert second == "after_restore: sequence=2006 max_number=0 requeued=0\n"
    assert after_first == (1006, True)
    assert after_second == (2006, True)
    assert tickets.next_number() == 2007, "номер после повторного запуска не меньше и не равен ни одному выданному"


@MIGRATE
def test_after_restore_uses_migrate_connection(monkeypatch, keep_sequence):
    """NFR-210: без соединения `migrate` команда отказывает и ничего не меняет; записи идут через `migrate`."""
    set_sequence(40)
    before = sequence_state()
    with monkeypatch.context() as patch:
        patch.delitem(connections.databases, "migrate")
        with pytest.raises(CommandError) as refused:
            call_command("servicedesk_after_restore", stdout=StringIO())
    assert str(refused.value) == NEED_MIGRATE
    assert sequence_state() == before, "последовательность не тронута"

    # заявка видна команде только через соединение `migrate` (в `default` её нет): иначе max_number был бы 0
    _ticket_on_migrate(number=300)
    assert _run("servicedesk_after_restore") == "after_restore: sequence=1300 max_number=300 requeued=0\n"


@MIGRATE
def test_after_restore_queues_parsing_for_received_inbound_mails(keep_sequence, django_capture_on_commit_callbacks):
    """FR-211, NFR-210: каждому письму в `received` ставится разбор (`process_inbound`), по возрастанию номера строки."""
    first = make_inbound(using="migrate")
    second = make_inbound(using="migrate")
    assert first.status == "received" and second.status == "received"

    with django_capture_on_commit_callbacks(execute=True), django_capture_on_commit_callbacks(using="migrate", execute=True):
        output = _run("servicedesk_after_restore")

    assert output.endswith(" requeued=2\n")
    assert output.startswith("after_restore: sequence=")
    assert _inbox_job_ids() == [first.id, second.id]


@MIGRATE
def test_after_restore_does_not_requeue_already_parsed_mails(keep_sequence, django_capture_on_commit_callbacks):
    """FR-211: обработанные, ждущие настройки и письма с ошибкой повторно не ставятся; разбирается только `received`."""
    make_inbound(using="migrate", status="processed", outcome="created")
    make_inbound(using="migrate", status="error", outcome="parse_error", last_error="parse: ValueError")
    make_inbound(using="migrate", status="waiting_setup", outcome="waiting_setup")
    fresh = make_inbound(using="migrate")

    with django_capture_on_commit_callbacks(execute=True), django_capture_on_commit_callbacks(using="migrate", execute=True):
        output = _run("servicedesk_after_restore")

    assert output.endswith(" requeued=1\n")
    assert _inbox_job_ids() == [fresh.id]


@MIGRATE
def test_next_ticket_after_restore_gets_number_beyond_lost_range(keep_sequence):
    """FR-201: следующая заявка получает new + 1: номера, выданные после копии и потерянные, не выдаются снова."""
    from apps.servicedesk.services import tickets

    _ticket_on_migrate(number=30)
    set_sequence(30)

    _run("servicedesk_after_restore")

    assert tickets.next_number() == 1031


# --- e2e_reset_stand и точка stand_reset (8.3) ----------------------------------------------------------------

@MIGRATE
def test_reset_stand_calls_stand_reset_points_in_reverse_registration_order(reset_env, no_extensions):
    """NFR-210: функции точки `stand_reset` зовутся в обратном порядке регистрации."""
    from apps.core import extensions

    calls = []

    def first():
        calls.append("first")

    def second():
        calls.append("second")

    def third():
        calls.append("third")

    for func in (first, second, third):
        extensions.register("stand_reset", func)

    output = _run("e2e_reset_stand")

    assert output  # команда отработала и что-то сообщила
    assert calls == ["third", "second", "first"]


@MIGRATE
def test_reset_stand_clears_servicedesk_data_before_org_units(reset_env):
    """NFR-210: данные среза стёрты раньше узлов `org` (ссылки `PROTECT`): ни ошибки, ни остатков."""
    ticket, queue = _ticket_on_migrate()
    make_inbound(using="migrate", ticket=ticket)
    category = make_category(queue=queue, using="migrate")
    configure_servicedesk(using="migrate", default_queue=queue)
    owner = _owner()
    client_unit = _all("servicedesk.ClientUnit").create(name="Отдел клиента", name_key=support_org.name_key("Отдел клиента"))
    requester = make_requester(using="migrate", client_unit=client_unit)
    entry = make_entry(ticket, using="migrate")
    make_participant(ticket, using="migrate")
    _all("servicedesk.Attachment").create(ticket=ticket, entry=entry, name="a.txt", size=5, created_at=timezone.now())
    _all("servicedesk.RequesterImport").create(
        created_by=owner, created_at=timezone.now(), file_name="r.csv", file_format="csv", state="preview",
        delete_missing=False, rows=[], summary={}, new_units=[])
    assert _all("org.Unit").filter(is_root=False).exists()
    for name in ("TicketEntry", "Attachment", "TicketParticipant", "Requester", "RequesterImport", "ClientUnit"):
        assert _all(f"servicedesk.{name}").exists(), name  # данные есть до сброса (заявитель — и у заявки, и явный)

    _run("e2e_reset_stand")  # ProtectedError здесь — узел удалён раньше данных среза

    for name in ("Ticket", "TicketEntry", "Attachment", "TicketParticipant", "Requester", "RequesterImport", "InboundMail",
                 "Queue", "ClientUnit"):
        assert _all(f"servicedesk.{name}").count() == 0, name
    assert not _all("servicedesk.Category").filter(pk=category.pk).exists()
    assert not _all("org.Unit").filter(is_root=False).exists(), "узлы работы стёрты"
    assert _all("org.Unit").filter(is_root=True).count() == 1


@MIGRATE
def test_reset_stand_recreates_initial_dictionaries_and_settings(reset_env):
    """NFR-210: после сброса справочники и настройки как после миграций (2.2), правки и добавления стёрты."""
    queue = make_queue(created_by=_owner(), using="migrate")
    make_category(queue=queue, using="migrate")
    configure_servicedesk(using="migrate", default_queue=queue, domains=["stand-reset.test"], autoclose_days=30,
                          reopen_days=2, form_hourly_limit=500, retention_years=9, inbound_retention_days=90)
    _all("servicedesk.Status").filter(name_key=support_org.name_key("Новая")).update(name="Переименована")
    _all("servicedesk.Priority").filter(name_key=support_org.name_key("Высокая")).update(order=99)
    _all("servicedesk.Source").filter(system_code="").filter(name_key=support_org.name_key("Телефон")).delete()
    _all("servicedesk.ClientUnit").create(name="Отдел клиента", name_key=support_org.name_key("Отдел клиента"))

    _run("e2e_reset_stand")

    def rows(model, *fields):
        return [tuple(row) for row in _all(f"servicedesk.{model}").order_by("order", "id").values_list(*fields)]

    assert rows("Status", "name", "kind", "is_default", "system_code", "order") == [
        ("Новая", "new", True, "", 10), ("В работе", "in_progress", True, "", 20),
        ("Ждёт ответа заявителя", "waiting", True, "", 30), ("Решена", "closed", True, "", 40),
        ("Не может быть решена", "closed", False, "", 50), ("Закрыта автоматически", "closed", False, "autoclosed", 60)]
    assert rows("Priority", "name", "order") == [("Низкая", 10), ("Средняя", 20), ("Высокая", 30)]
    assert rows("Complexity", "name", "order", "name_key") == [
        ("Лёгкий", 10, "легкий"), ("Средний", 20, "средний"), ("Высокий", 30, "высокий")]
    assert rows("Source", "name", "system_code", "order") == [
        ("Почта", "mail", 10), ("Форма", "form", 20), ("Телефон", "", 30), ("Лично", "", 40)]
    categories = list(_all("servicedesk.Category").all())
    assert [(c.name, c.is_system, c.on_form, c.queue_id, c.order) for c in categories] == [("Другое", True, True, None, 100)]
    assert _all("servicedesk.ClientUnit").count() == 0
    settings_row = _all("servicedesk.ServiceDeskSettings").get(pk=1)
    assert (settings_row.autoclose_days, settings_row.reopen_days, settings_row.form_hourly_limit,
            settings_row.retention_years, settings_row.inbound_retention_days) == (7, 7, 10, 3, 30)
    assert settings_row.domains == []
    assert settings_row.default_queue_id is None
    priority = settings_row.default_priority
    assert getattr(priority, "name", priority) == "Средняя"
    assert _all("servicedesk.ServiceDeskSettings").count() == 1


@MIGRATE
def test_reset_stand_resets_ticket_number_sequence_via_migrate_connection(reset_env, keep_sequence):
    """FR-201: после сброса `sequence_state() == (1, False)`: следующая заявка получает номер 1."""
    _ticket_on_migrate(number=77)
    set_sequence(777)
    assert sequence_state() == (777, True)

    _run("e2e_reset_stand")

    assert sequence_state() == (1, False)


@MIGRATE
def test_reset_stand_clears_attachments_and_inbound_files(reset_env):
    """NFR-210: содержимое `protected/attachments` и `protected/inbound` стёрто, сами каталоги остаются."""
    root = reset_env
    for name in ("attachments", "inbound"):
        (root / name / "ab").mkdir(parents=True)
        (root / name / "ab" / "file.bin").write_bytes(secrets.token_bytes(16))
        (root / name / "7.eml").write_bytes(secrets.token_bytes(16))

    _run("e2e_reset_stand")

    for name in ("attachments", "inbound"):
        assert (root / name).is_dir(), f"каталог {name} остаётся"
        assert list((root / name).iterdir()) == [], f"содержимое {name} стёрто"


@MIGRATE
def test_reset_stand_clears_inbox_and_maintenance_queues(reset_env, django_capture_on_commit_callbacks):
    """NFR-210: очереди `inbox` и `maintenance` после сброса пусты."""
    import django_rq

    for name in ("inbox", "maintenance"):
        queue = django_rq.get_queue(name)
        with django_capture_on_commit_callbacks(execute=True):  # django-rq 4.x ставит задание по фиксации
            queue.enqueue("tests.test_sd_stand_restore.not_run_job")
        assert queue.count == 1, name

    _run("e2e_reset_stand")

    for name in ("inbox", "maintenance"):
        queue = django_rq.get_queue(name)
        assert queue.count == 0, name


@MIGRATE
def test_reset_stand_clears_form_threshold_keys_only(reset_env):
    """NFR-210: ключи `servicedesk:form:*` (порог формы, в том числе IPv6) удалены, остальные ключи на месте."""
    from apps.core.services import valkey

    conn = valkey.conn()
    forms = ["servicedesk:form:203.0.113.5", "servicedesk:form:2001:db8::1"]
    kept = ["servicedesk:poll", "servicedesk:formal", "standcheck:keep"]
    for key in forms:
        conn.zadd(key, {"1760000000.5:abc": 1760000000.5})
    for key in kept:
        conn.set(key, "value")

    _run("e2e_reset_stand")

    assert [conn.exists(key) for key in forms] == [0, 0]
    assert [conn.exists(key) for key in kept] == [1, 1, 1]


@MIGRATE
def test_reset_stand_sets_mailbox_state_to_current_mailbox_end(monkeypatch, settings, protected_root, fake_mailbox):
    """FR-211, NFR-210: `MailboxState` — на текущий конец ящика; ящик не отвечает или `IMAP_HOST` пуст — строки нет."""
    monkeypatch.setenv("E2E_STAND", "1")
    mailbox = fake_mailbox
    mailbox.recreate(uidvalidity=2000)
    for number in range(3):
        mailbox.append(build_mail(from_addr="someone@client.test", subject=f"Письмо {number}", text="Текст"))
    assert (mailbox.uidvalidity, mailbox.uidnext) == (2000, 4)
    _put_mailbox_state()

    started = timezone.now()
    _run("e2e_reset_stand")

    state = _all("servicedesk.MailboxState").get(pk=1)
    assert (state.uidvalidity, state.last_uid) == (2000, 3), "last_uid = uidnext - 1: письма прежних кругов не разбираются"
    assert state.last_error == ""
    for field in ("connected_at", "last_poll_at", "last_ok_at"):
        value = getattr(state, field)
        assert value is not None and started - timedelta(seconds=5) <= value <= timezone.now() + timedelta(seconds=5), field
    assert mailbox.connects >= 1
    assert mailbox.fetched == [], "письма не скачиваются"

    # ящик не отвечает: строка удалена, первое подключение создаст её само
    _put_mailbox_state()
    mailbox.set_unavailable("ящик не отвечает")
    _run("e2e_reset_stand")
    assert not _all("servicedesk.MailboxState").exists()

    # IMAP_HOST пуст: строки тоже нет
    mailbox.set_unavailable(None)
    settings.IMAP_HOST = ""
    _put_mailbox_state()
    _run("e2e_reset_stand")
    assert not _all("servicedesk.MailboxState").exists()


@MIGRATE
def test_reset_stand_with_only_org_keeps_slice_002_order(reset_env, no_extensions):
    """NFR-210: при единственной точке `org` порядок и результат как в срезе 002: листья вперёд, остаётся один корень."""
    from apps.core import extensions
    from apps.org.stand import stand_reset

    extensions.register("stand_reset", stand_reset)
    Unit = support.model("org.Unit")
    root = _all("org.Unit").get(is_root=True)

    def add(parent, name):
        unit = Unit.objects.using("migrate").create(name=name, name_key=support_org.name_key(name), kind="department",
                                                    parent=parent, depth=parent.depth + 1, path="")
        unit.path = f"{parent.path}{unit.pk}/"
        unit.save(using="migrate", update_fields=["path"])
        return unit

    child = add(root, f"Узел {secrets.token_hex(3)}")
    add(child, f"Подузел {secrets.token_hex(3)}")
    assert _all("org.Unit").count() == 3

    _run("e2e_reset_stand")

    units = list(_all("org.Unit").all())
    assert [(u.is_root, u.name) for u in units] == [(True, "ИТ-отдел")]


# --- команды e2e_poll_mailbox, e2e_backdate, e2e_run_job (8.1, 8.2) -------------------------------------------

@PLAIN
def test_stand_commands_poll_mailbox_backdate_run_job_refused_without_e2e_stand(monkeypatch, fake_mailbox):
    """NFR-210: без `E2E_STAND=1` три команды отказывают тем же текстом, что `e2e_reset_stand`: ящик не тронут, база не изменена."""
    old = timezone.now() - timedelta(days=30)
    ticket = make_ticket(kind="waiting", waiting_since=old)
    created_at = ticket.created_at
    fake_mailbox.append(build_mail(from_addr="someone@client.test", subject="Письмо", text="Текст"))
    commands = [("e2e_poll_mailbox",), ("e2e_backdate", "ticket", str(ticket.number), "waiting_since", "3"),
                ("e2e_run_job", "autoclose")]

    for value in (None, "0", ""):
        if value is None:
            monkeypatch.delenv("E2E_STAND", raising=False)
        else:
            monkeypatch.setenv("E2E_STAND", value)
        for command in commands:
            with pytest.raises(CommandError) as refused:
                call_command(*command, stdout=StringIO())
            assert str(refused.value) == REFUSAL, command

    assert fake_mailbox.connects == 0
    ticket.refresh_from_db()
    assert (ticket.kind, ticket.waiting_since, ticket.created_at) == ("waiting", old, created_at)
    assert not support.model("servicedesk.InboundMail").objects.exists()
    assert not support.model("servicedesk.MailboxState").objects.exists()


@PLAIN
def test_stand_poll_mailbox_polls_and_parses_at_once(monkeypatch, fake_mailbox, django_capture_on_commit_callbacks,
                                                     protected_root, settings):
    """FR-211, NFR-210: `e2e_poll_mailbox` забирает письма и разбирает их сразу, без рабочего процесса; вывод по формату 8.2."""
    monkeypatch.setenv("E2E_STAND", "1")
    queue = make_queue()
    configure_servicedesk(domains=["client.test"], default_queue=queue)
    # ящик уже подключали раньше: первое подключение писем не забирает (FR-211, 6.15 `poll`)
    support.model("servicedesk.MailboxState").objects.create(pk=1, uidvalidity=fake_mailbox.uidvalidity, last_uid=0)
    senders = ["first@client.test", "second@client.test"]
    for sender in senders:
        fake_mailbox.append(build_mail(from_addr=sender, to=["tickets@stand.test"], subject=f"Тема от {sender}", text="Текст"))

    with django_capture_on_commit_callbacks(execute=True):
        output = _run("e2e_poll_mailbox")

    assert output == "poll_mailbox: state=ok fetched=2 parsed=2 errors=0\n"
    Inbound = support.model("servicedesk.InboundMail")
    Ticket = support.model("servicedesk.Ticket")
    mails = list(Inbound.objects.order_by("id"))
    assert [(m.status, m.outcome) for m in mails] == [("processed", "created")] * 2
    assert sorted(Ticket.objects.values_list("requester_email", flat=True)) == senders
    assert all(m.ticket_id is not None for m in mails)
    assert fake_mailbox.fetched == [1, 2]

    # ветви 8.2: ящик не задан — отказ; ящик недоступен — отказ без пароля в тексте
    settings.IMAP_HOST = ""
    with pytest.raises(CommandError):
        _run("e2e_poll_mailbox")
    settings.IMAP_HOST = "imap.test"
    fake_mailbox.set_unavailable("соединение отклонено")
    with pytest.raises(CommandError) as unavailable:
        _run("e2e_poll_mailbox")
    assert settings.IMAP_PASSWORD not in str(unavailable.value)


@PLAIN
def test_stand_backdate_shifts_ticket_and_mail_timestamps_back(monkeypatch):
    """NFR-210: `e2e_backdate` сдвигает отметки заявки, письма и ящика назад на сутки, вывод — по формату; отказы по 8.2."""
    monkeypatch.setenv("E2E_STAND", "1")
    stamp = timezone.now() - timedelta(days=5)
    ticket = make_ticket(kind="waiting", waiting_since=stamp)
    mail = make_inbound(message_id=f"<{secrets.token_hex(6)}@client.test>")
    state = support.model("servicedesk.MailboxState").objects.create(pk=1, last_ok_at=stamp)
    before_mail = mail.received_at

    def moved(output: str, prefix: str):
        match = re.fullmatch(rf"{re.escape(prefix)} (\S+) -> (\S+)\n", output)
        assert match, output
        return tuple(_parse_iso(text) for text in match.groups())

    old, new = moved(_run("e2e_backdate", "ticket", str(ticket.number), "waiting_since", "3"),
                     f"backdate: ticket {ticket.number} waiting_since -3d")
    ticket.refresh_from_db()
    assert abs(old - stamp) < timedelta(seconds=1) and abs(new - (stamp - timedelta(days=3))) < timedelta(seconds=1)
    assert ticket.waiting_since == stamp - timedelta(days=3)

    for field in ("created_at", "last_message_at"):
        was = getattr(ticket, field)
        _run("e2e_backdate", "ticket", str(ticket.number), field, "2")
        ticket.refresh_from_db()
        assert getattr(ticket, field) == was - timedelta(days=2), field

    assert ticket.closed_at is None
    started = timezone.now()
    _run("e2e_backdate", "ticket", str(ticket.number), "closed_at", "1")
    ticket.refresh_from_db()
    assert abs(ticket.closed_at - (started - timedelta(days=1))) < timedelta(minutes=2), "пустая отметка — от «сейчас»"

    output = _run("e2e_backdate", "mail", mail.message_id, "received_at", "2")
    assert output.startswith(f"backdate: mail {mail.message_id} received_at -2d ")
    mail.refresh_from_db()
    assert mail.received_at == before_mail - timedelta(days=2)

    output = _run("e2e_backdate", "mailbox", "-", "last_ok_at", "1")
    assert output.startswith("backdate: mailbox - last_ok_at -1d ")
    state.refresh_from_db()
    assert state.last_ok_at == stamp - timedelta(days=1)

    ticket.refresh_from_db()
    frozen = (ticket.created_at, ticket.waiting_since)
    for args in (("bogus", str(ticket.number), "created_at", "1"), ("ticket", str(ticket.number), "received_at", "1"),
                 ("mail", mail.message_id, "created_at", "1"), ("ticket", str(ticket.number), "created_at", "0"),
                 ("ticket", str(ticket.number), "created_at", "x"), ("ticket", str(ticket.number + 1000), "created_at", "1"),
                 ("mail", "<absent@client.test>", "received_at", "1")):
        with pytest.raises(CommandError):
            call_command("e2e_backdate", *args, stdout=StringIO())
    ticket.refresh_from_db()
    assert (ticket.created_at, ticket.waiting_since) == frozen, "отказы ничего не меняют"


def _parse_iso(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    return value if value.tzinfo else value.replace(tzinfo=dt_timezone.utc)


@PLAIN
def test_stand_run_job_runs_autoclose_anonymize_tickets_purge_inbound_now(protected_root, monkeypatch,
                                                                         django_capture_on_commit_callbacks):
    """NFR-210: `e2e_run_job` выполняет задание целиком сразу, цепочкой порций по 50, без очереди; вывод по формату 8.2."""
    import django_rq

    monkeypatch.setenv("E2E_STAND", "1")
    now = timezone.now()
    queue = make_queue()
    requester = make_requester()
    maintenance = django_rq.get_queue("maintenance")

    # autoclose: 51 заявка «ждёт ответа» дольше срока (7 суток) — две порции; «в работе» не закрывается
    waiting = [make_ticket(queue=queue, requester=requester, kind="waiting",
                           waiting_since=now - timedelta(days=30, minutes=index)) for index in range(51)]
    fresh = make_ticket(queue=queue, requester=requester, kind="waiting", waiting_since=now - timedelta(days=1))
    in_work = make_ticket(queue=queue, requester=requester, kind="in_progress")
    backdate(in_work, "created_at", days=60)
    with django_capture_on_commit_callbacks(execute=True):
        output = _run("e2e_run_job", "autoclose")
    assert output == "run_job: autoclose done=51 batches=2\n"
    Ticket = support.model("servicedesk.Ticket")
    assert Ticket.objects.filter(pk__in=[t.pk for t in waiting], kind="closed", status__system_code="autoclosed").count() == 51
    for untouched in (fresh, in_work):
        untouched.refresh_from_db()
    assert fresh.kind == "waiting" and in_work.kind == "in_progress"
    assert maintenance.count == 0, "следующие порции в очередь не ставятся"

    # anonymize_tickets: закрытые раньше границы «3 года назад» (запас 2 суток); свежее закрытие остаётся
    border = _years_ago(now, 3)
    old_closed = [make_ticket(queue=queue, requester=requester, kind="closed", closed_at=border - timedelta(days=2))
                  for _ in range(2)]
    new_closed = make_ticket(queue=queue, requester=requester, kind="closed", closed_at=border + timedelta(days=2))
    with django_capture_on_commit_callbacks(execute=True):
        output = _run("e2e_run_job", "anonymize_tickets")
    assert output == "run_job: anonymize_tickets done=2 batches=1\n"
    for ticket in old_closed:
        ticket.refresh_from_db()
        assert ticket.anonymized_at is not None and ticket.requester_email == "обезличено"
    new_closed.refresh_from_db()
    assert new_closed.anonymized_at is None and new_closed.requester_email != "обезличено"
    assert maintenance.count == 0

    # purge_inbound: письма без заявки старше срока (30 суток) очищены, файл стёрт; свежее и письмо с заявкой остаются
    (protected_root / "inbound").mkdir(exist_ok=True)
    stale = [make_inbound(status="processed", outcome="rejected_domain", received_at=now - timedelta(days=40),
                          subject="Старое") for _ in range(2)]
    young = make_inbound(status="processed", outcome="rejected_domain", subject="Свежее")
    linked = make_inbound(status="processed", outcome="created", ticket=fresh, received_at=now - timedelta(days=40))
    for mail in (*stale, young, linked):
        (protected_root / "inbound" / f"{mail.id}.eml").write_bytes(b"raw")
    with django_capture_on_commit_callbacks(execute=True):
        output = _run("e2e_run_job", "purge_inbound")
    assert output == "run_job: purge_inbound done=2 batches=1\n"
    for mail in stale:
        mail.refresh_from_db()
        assert mail.raw_deleted is True and (mail.from_email, mail.subject, mail.message_id) == ("", "", "")
        assert mail.outcome == "rejected_domain"
        assert not (protected_root / "inbound" / f"{mail.id}.eml").exists()
    for mail in (young, linked):
        mail.refresh_from_db()
        assert mail.raw_deleted is False
        assert (protected_root / "inbound" / f"{mail.id}.eml").exists()
    assert maintenance.count == 0

    with pytest.raises(CommandError):
        call_command("e2e_run_job", "unknown_job", stdout=StringIO())


def not_run_job():
    """Функция для очередей: задание только ставится, рабочего процесса в тестах нет."""
