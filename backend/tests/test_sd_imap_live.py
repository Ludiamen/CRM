"""T-3109: живые тесты на настоящем Dovecot стенда (FR-210, FR-211, NFR-201). Сценарий 1 спеки среза 003
(пункты 1 и 7), решение 11.12 плана (пересоздание ящика).

Служба `dovecot` — настоящая (CONTRACT-003 § 1, решение 3 задач: без пропуска, ожидание входа до 30 с). Тест
работает в своей папке `live-<токен>` (фикстура `live_mailbox`), `INBOX` стенда не трогает. Параметры входа —
`settings.IMAP_*` и `os.environ["IMAP_PASSWORD"]`; пароль в тексте ошибок не появляется. Имена кода среза 003
импортируются внутри тестов: сбор проходит до появления кода.
"""
import os
import secrets
import socket
import time
from email.utils import make_msgid

import pytest

from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

CORP = "corp.test"
REQUESTER = "ivanov@corp.test"
MAILBOX = "tickets@stand.test"
NFR_201_SECONDS = 120


# --- помощники файла --------------------------------------------------------------------------------

def _portal(settings):
    """Адрес ящика заявок, корпоративный домен и очередь по умолчанию (через ORM, без журнала)."""
    settings.SERVICEDESK_MAILBOX = MAILBOX
    queue = sd.make_queue()
    sd.configure_servicedesk(domains=[CORP], default_queue=queue)
    return queue


def _mail(subject: str, message_id: str | None = None, text: str = "Не печатает принтер.") -> tuple[bytes, str]:
    message_id = message_id or make_msgid(domain="client.test")
    raw = sd.build_mail(from_addr=REQUESTER, to=[MAILBOX], subject=subject, text=text, message_id=message_id)
    return raw, message_id


def _poll(capture):
    """Один запуск `poll()`; задания после фиксации исполняются (ставятся в настоящую очередь `inbox`)."""
    from apps.servicedesk.services import mailbox

    with capture(execute=True):
        return mailbox.poll()


def _state():
    return model("servicedesk.MailboxState").objects.get(pk=1)


def _journal(action: str) -> list:
    return list(model("core.AuditEvent").objects.filter(action=action).order_by("id"))


def _flags_of(folder: str, uid: int) -> bytes:
    """Флаги письма по `UID FETCH (FLAGS)` (папка открыта только для чтения); пустая строка — письма нет."""
    conn = sd._imap_login()
    try:
        status, _ = conn.select(folder, readonly=True)
        assert status == "OK"
        status, data = conn.uid("FETCH", str(uid), "(FLAGS)")
        assert status == "OK"
        return b" ".join(item for item in data if isinstance(item, bytes))
    finally:
        conn.logout()


# --- тесты ------------------------------------------------------------------------------------------

def test_live_append_then_poll_creates_ticket_in_one_run(live_mailbox, settings, protected_root,
                                                         django_capture_on_commit_callbacks):
    """FR-210, NFR-201: письмо, положенное в настоящий ящик, одним запуском `poll()` забирается, разбор даёт заявку
    не позже 2 минут; байты письма в файле совпадают с ящиком, признак «прочитано» не поставлен."""
    import django_rq

    from apps.servicedesk.services import intake

    _portal(settings)
    first = _poll(django_capture_on_commit_callbacks)
    assert first.state == "ok" and first.fetched == 0
    state = _state()
    assert state.uidvalidity == live_mailbox.uidvalidity() and state.last_uid == 0 and state.last_error == ""

    raw, message_id = _mail("Не печатает принтер")
    started = time.monotonic()
    uid = live_mailbox.append(raw)
    result = _poll(django_capture_on_commit_callbacks)
    assert (result.state, result.fetched, result.known) == ("ok", 1, 0)

    inbound = model("servicedesk.InboundMail").objects.get()
    assert (inbound.uidvalidity, inbound.uid) == (live_mailbox.uidvalidity(), uid)
    assert inbound.status == "received" and inbound.message_id == message_id
    assert inbound.from_email == REQUESTER and inbound.subject == "Не печатает принтер"
    assert (protected_root / "inbound" / f"{inbound.pk}.eml").read_bytes() == raw
    assert _state().last_uid == uid and _state().last_error == ""
    jobs = [j for j in django_rq.get_queue("inbox").jobs if j.func_name == "apps.servicedesk.tasks.process_inbound"]
    assert [j.args[0] for j in jobs] == [inbound.pk]

    with django_capture_on_commit_callbacks(execute=True):
        assert intake.process(inbound.pk) == "created"
    assert time.monotonic() - started < NFR_201_SECONDS
    inbound.refresh_from_db()
    assert inbound.status == "processed" and inbound.outcome == "created" and inbound.ticket_id is not None
    ticket = inbound.ticket
    assert ticket.requester_email == REQUESTER and ticket.subject == "Не печатает принтер"
    # портал письмо не помечает и не удаляет (EXAMINE)
    flags = _flags_of(live_mailbox.folder, uid)
    assert b"FLAGS" in flags and b"\\Seen" not in flags and b"\\Deleted" not in flags


def test_live_first_poll_skips_mail_present_before_connection(live_mailbox, settings, protected_root,
                                                              django_capture_on_commit_callbacks):
    """FR-211: письма, лежавшие в ящике до первого подключения, не разбираются; `last_uid` — конец ящика
    (`UIDNEXT − 1` из ответа на выбор папки); письмо, пришедшее после, забирается."""
    _portal(settings)
    old_uids = [live_mailbox.append(_mail(f"Старое {n}")[0]) for n in (1, 2)]
    assert model("servicedesk.MailboxState").objects.count() == 0

    first = _poll(django_capture_on_commit_callbacks)
    assert (first.state, first.fetched) == ("ok", 0)
    assert model("servicedesk.InboundMail").objects.count() == 0
    state = _state()
    assert state.uidvalidity == live_mailbox.uidvalidity() and state.last_uid == max(old_uids)
    connected = _journal("mailbox.connected")
    assert len(connected) == 1
    assert int(connected[0].after["uidvalidity"]) == state.uidvalidity
    assert int(connected[0].after["last_uid"]) == max(old_uids)

    raw, _ = _mail("Новое после подключения")
    new_uid = live_mailbox.append(raw)
    second = _poll(django_capture_on_commit_callbacks)
    assert (second.state, second.fetched) == ("ok", 1)
    assert [m.uid for m in model("servicedesk.InboundMail").objects.all()] == [new_uid]
    assert _state().last_uid == new_uid and len(_journal("mailbox.connected")) == 1


def test_live_non_inbox_folder_deleted_and_created_after_close_changes_uidvalidity_and_poll_follows_plan(
        live_mailbox, settings, protected_root, django_capture_on_commit_callbacks):
    """FR-211: папка (не `INBOX`) удалена и создана заново после закрытия соединения — UIDVALIDITY другой; опрос
    по плану: пишет новый UIDVALIDITY и журнал `mailbox.recreated`, забирает новое письмо, не берёт повторно письмо
    с уже известным `Message-ID`, дальше идёт обычным порядком."""
    _portal(settings)
    assert settings.IMAP_FOLDER == live_mailbox.folder and live_mailbox.folder != "INBOX"
    assert _poll(django_capture_on_commit_callbacks).state == "ok"
    known_raw, known_id = _mail("Письмо до пересоздания")
    live_mailbox.append(known_raw)
    assert _poll(django_capture_on_commit_callbacks).fetched == 1
    assert _state().last_ok_at is not None
    old_validity = _state().uidvalidity
    assert old_validity == live_mailbox.uidvalidity()

    # Dovecot берёт UIDVALIDITY из времени создания папки (секунды): без паузы значение может совпасть
    time.sleep(1.5)
    live_mailbox.recreate()
    new_validity = live_mailbox.uidvalidity()
    assert new_validity != old_validity
    copy_uid = live_mailbox.append(known_raw)  # перенесённая из старого ящика копия: Message-ID известен
    fresh_raw, fresh_id = _mail("Письмо в новом ящике")
    fresh_uid = live_mailbox.append(fresh_raw)
    assert copy_uid < fresh_uid

    result = _poll(django_capture_on_commit_callbacks)
    assert result.state == "ok"
    state = _state()
    assert state.uidvalidity == new_validity and state.last_uid == fresh_uid and state.last_error == ""
    taken = list(model("servicedesk.InboundMail").objects.filter(uidvalidity=new_validity))
    assert [(m.uid, m.message_id) for m in taken] == [(fresh_uid, fresh_id)]
    assert model("servicedesk.InboundMail").objects.filter(message_id=known_id).count() == 1
    recreated = _journal("mailbox.recreated")
    assert len(recreated) == 1
    assert int(recreated[0].before["uidvalidity"]) == old_validity
    assert int(recreated[0].after["uidvalidity"]) == new_validity and isinstance(recreated[0].after["skipped"], int)

    again = _poll(django_capture_on_commit_callbacks)
    assert (again.state, again.fetched) == ("ok", 0) and len(_journal("mailbox.recreated")) == 1


def test_live_login_with_env_password_error_text_has_no_password(settings, django_capture_on_commit_callbacks):
    """FR-210, NFR-201: отказ входа на настоящем Dovecot — `MailboxUnavailable` с текстом без пароля из окружения
    (неверный пароль — пароль окружения с лишним хвостом: Dovecot стенда пускает любое имя с паролем `USER_PASSWORD`,
    факт F1 PLAN-003, поэтому отказ даёт только пароль);
    `poll()` не поднимает ошибку и пишет в `last_error` текст без пароля; `safe_error` заменяет пароль на `***`."""
    from apps.integrations.mail import imap, tasks

    sd.live_mailbox_ready()
    real = os.environ["IMAP_PASSWORD"]
    assert real
    password = real + "-x" + secrets.token_urlsafe(6)
    settings.IMAP_PASSWORD = password

    with pytest.raises(imap.MailboxUnavailable) as caught:
        imap.connect()
    text = str(caught.value)
    assert text and password not in text and real not in text

    result = _poll(django_capture_on_commit_callbacks)
    assert result.state == "unavailable"
    state = _state()
    assert state.last_error and password not in state.last_error and real not in state.last_error
    assert state.last_poll_at is not None
    assert state.uidvalidity is None and state.last_uid is None

    leaked = tasks.safe_error(RuntimeError(f"LOGIN failed for password {password}"))
    assert "***" in leaked and password not in leaked


def test_live_mailbox_readiness_waits_by_login_retry_up_to_30_seconds(settings):
    """FR-210: готовность ящика ждётся повтором входа до 30 с (по умолчанию `timeout=30.0`); живой ящик отвечает
    сразу, адаптер открывает папку только для чтения и берёт UIDVALIDITY и UIDNEXT из ответа; недоступный порт —
    `AssertionError` не раньше срока и без пароля."""
    import inspect

    from apps.integrations.mail import imap

    assert inspect.signature(sd.live_mailbox_ready).parameters["timeout"].default == 30.0
    started = time.monotonic()
    assert sd.live_mailbox_ready() is None
    assert time.monotonic() - started < 30

    settings.IMAP_FOLDER = "INBOX"
    with imap.connect() as conn:
        assert isinstance(conn.uidvalidity, int) and conn.uidvalidity > 0
        assert isinstance(conn.uidnext, int) and conn.uidnext > 0

    password = os.environ["IMAP_PASSWORD"]
    with socket.socket() as probe:
        probe.bind(("", 0))
        free_port = probe.getsockname()[1]
    settings.IMAP_PORT = free_port
    started = time.monotonic()
    with pytest.raises(AssertionError) as caught:
        sd.live_mailbox_ready(timeout=3.0)
    waited = time.monotonic() - started
    assert 2.5 <= waited < 15
    assert password not in str(caught.value)
