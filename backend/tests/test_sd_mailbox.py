"""T-3106: опрос ящика заявок на фальшивом адаптере IMAP (FR-210, FR-211, FR-212, FR-220, FR-275, NFR-201,
NFR-206, NFR-209). Сценарии 1 и 11 спеки среза 003.

Служба `apps.servicedesk.services.mailbox` и адаптер `apps.integrations.mail.imap` вызываются настоящими
функциями (CONTRACT-003 §§ 5.1, 5.2, 6.15, 6.16, 7); подменяются только точки § 3.5: `imap.connect` (фикстура
`fake_mailbox`), классы `imaplib`/`ssl` адаптера (двойник `FakeImap`), `mailbox.write_raw` и
`mailbox.mail_parse.sender_of`. Замок — настоящий Valkey, очереди — настоящие RQ. Имена кода среза 003
импортируются внутри тестов: сбор проходит до появления кода.
"""
import re
from datetime import timedelta
from html import unescape

import pytest

from tests import support
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

LOCK_KEY = "servicedesk:poll"
MAILBOX = "tickets@stand.test"
CORP = "corp.test"
RETRY_INTERVALS = [60, 300, 900, 3600, 10800]


# --- помощники файла --------------------------------------------------------------------------------

def _svc():
    """(mailbox, intake, tasks) — имена среза 003, импорт ленивый."""
    from apps.servicedesk import tasks
    from apps.servicedesk.services import intake, mailbox

    return mailbox, intake, tasks


def _poll(capture):
    """Один запуск опроса вместе с обработчиками «после фиксации» (постановка разбора)."""
    mailbox, _, _ = _svc()
    with capture(execute=True):
        return mailbox.poll()


def _state():
    return model("servicedesk.MailboxState").objects.get(pk=1)


def _rows(**filters) -> list:
    return list(model("servicedesk.InboundMail").objects.filter(**filters).order_by("uid"))


def _events(action: str) -> list:
    return list(model("core.AuditEvent").objects.filter(action=action).order_by("id"))


def _jobs(name: str = "process_inbound", queue: str = "inbox") -> list:
    import django_rq

    return [j for j in django_rq.get_queue(queue).jobs if j.func_name == f"apps.servicedesk.tasks.{name}"]


def _jobs_of(inbound_id: int) -> list:
    return [j for j in _jobs() if j.args == (inbound_id,)]


def _text(value):
    return value.decode() if isinstance(value, bytes) else value


def _lock():
    from apps.core.services import valkey

    return valkey.conn()


def _raw(n: int = 0, *, sender: str | None = None, **kw) -> bytes:
    kw.setdefault("subject", f"Тема {n}")
    kw.setdefault("text", f"Текст письма {n}")
    return sd.build_mail(from_addr=sender or f"user{n}@{CORP}", to=[MAILBOX], **kw)


def _connect_first(fake, capture):
    """Первое подключение к пустому ящику: `last_uid = uidnext − 1`, писем нет."""
    result = _poll(capture)
    assert result.state == "ok"
    return result


def _inbound_dir(protected_root):
    """Каталог писем тома `protected` (на стенде он есть; во временном каталоге теста создаём сами)."""
    path = protected_root / "inbound"
    path.mkdir(exist_ok=True)
    return path


def _imap_settings(settings, password: str, security: str = "ssl") -> None:
    settings.IMAP_HOST = "imap.test"
    settings.IMAP_PORT = 993
    settings.IMAP_SECURITY = security
    settings.IMAP_USER = "tickets"
    settings.IMAP_PASSWORD = password
    settings.IMAP_FOLDER = "INBOX"
    settings.IMAP_TIMEOUT = 17


def _use_fake_imap(monkeypatch, imap, **kwargs):
    """Двойник `imaplib` на оба класса адаптера (`IMAP4_SSL` и `IMAP4`)."""
    factory = sd.FakeImap.factory(**kwargs)
    monkeypatch.setattr(imap.imaplib, "IMAP4_SSL", factory)
    monkeypatch.setattr(imap.imaplib, "IMAP4", factory)
    return factory


def _manager_client(ip: str = "198.51.100.61"):
    return support.logged_in(support.make_with_permissions("servicedesk.manage"), ip=ip)


def _tag(html: str, attr: str) -> str:
    found = re.search(rf"<\w+\b[^>]*{re.escape(attr)}[^>]*>", html)
    return found.group(0) if found else ""


def _all_inner(html: str, attr: str) -> list[str]:
    """Тексты всех элементов с атрибутом `attr` (без вложенных одноимённых тегов)."""
    found = re.finditer(rf"<(\w+)\b[^>]*{re.escape(attr)}[^>]*>(.*?)</\1>", html, re.S)
    return [" ".join(unescape(re.sub("<[^>]+>", " ", m.group(2))).split()) for m in found]


def _mailbox_state_attr(html: str) -> str | None:
    tag = _tag(html, "data-mailbox-status")
    found = re.search(r'data-mailbox-state="([^"]*)"', tag)
    return found.group(1) if found else None


def _configure_corp():
    queue = sd.make_queue()
    sd.configure_servicedesk(domains=[CORP], default_queue=queue)
    return queue


# --- 1. включение, замок --------------------------------------------------------------------------------

def test_empty_imap_host_poll_exits_without_connecting(fake_mailbox, settings, django_capture_on_commit_callbacks):
    """FR-210: `IMAP_HOST` пуст — `poll` и задание `poll_mailbox` выходят без подключения (`connects == 0`), письма
    не берутся, разбор не ставится; страница «Входящие письма» пишет «ящик не подключён» (единственное условие)."""
    mailbox, _, tasks = _svc()
    fake_mailbox.append(_raw(1))
    settings.IMAP_HOST = ""

    result = _poll(django_capture_on_commit_callbacks)
    with django_capture_on_commit_callbacks(execute=True):
        tasks.poll_mailbox()

    assert result.state == "disabled"
    assert fake_mailbox.connects == 0 and fake_mailbox.fetched == [] and fake_mailbox.searches == []
    assert _rows() == [] and _jobs() == []
    assert not _text(_lock().get(LOCK_KEY) or b"")
    html = _manager_client().get("/servicedesk/inbound/").content.decode()
    assert _mailbox_state_attr(html) == "not-connected"
    assert "ящик не подключён" in html.lower()


def test_second_poll_exits_when_lock_held(fake_mailbox, django_capture_on_commit_callbacks):
    """NFR-209, FR-210: замок `servicedesk:poll` занят чужим значением — `poll` выходит с `locked` без подключения,
    чужой ключ не удаляет и не продлевает, письма не берёт."""
    mailbox, _, tasks = _svc()
    fake_mailbox.append(_raw(1))
    conn = _lock()
    assert conn.set(LOCK_KEY, "other", nx=True, ex=120)

    result = _poll(django_capture_on_commit_callbacks)
    with django_capture_on_commit_callbacks(execute=True):
        tasks.poll_mailbox()

    assert result.state == "locked"
    assert fake_mailbox.connects == 0 and fake_mailbox.fetched == []
    assert _text(conn.get(LOCK_KEY)) == "other"
    assert 0 < conn.ttl(LOCK_KEY) <= 120
    assert _rows() == [] and _jobs() == []


def test_lock_released_only_by_own_value_in_finally(fake_mailbox, protected_root, django_capture_on_commit_callbacks):
    """NFR-209: замок снимается в `finally` только своим значением: после обычного запуска ключа нет; если во время
    запуска значение подменили, `poll` его не удаляет и не продлевает."""
    _inbound_dir(protected_root)
    conn = _lock()
    _connect_first(fake_mailbox, django_capture_on_commit_callbacks)
    assert conn.exists(LOCK_KEY) == 0, "после запуска без писем замок снят"
    fake_mailbox.append(_raw(1))
    assert _poll(django_capture_on_commit_callbacks).state == "ok"
    assert conn.exists(LOCK_KEY) == 0, "после запуска с письмом замок снят"

    fake_mailbox.append(_raw(2))
    fake_mailbox.on_fetch = lambda uid: conn.set(LOCK_KEY, "other", ex=60)
    result = _poll(django_capture_on_commit_callbacks)

    assert result.state == "ok"
    assert fake_mailbox.fetched[-1] == 2 and len(_rows()) == 2, "письмо забрано, ошибки замка нет"
    assert _text(conn.get(LOCK_KEY)) == "other", "чужое значение в finally не удалено"
    assert 0 < conn.ttl(LOCK_KEY) <= 60, "чужое значение не продлено"


def test_lock_extended_after_each_fetched_mail(fake_mailbox, protected_root, django_capture_on_commit_callbacks):
    """NFR-209: срок замка продлевается после каждого забранного письма (`EX 120`): хук `on_fetch` сокращает срок до
    5 с, а перед следующим скачиванием он снова близок к 120 с."""
    _inbound_dir(protected_root)
    conn = _lock()
    _connect_first(fake_mailbox, django_capture_on_commit_callbacks)
    for n in (1, 2, 3):
        fake_mailbox.append(_raw(n))
    seen_ttl = []

    def shorten(uid):
        seen_ttl.append(conn.ttl(LOCK_KEY))
        conn.expire(LOCK_KEY, 5)

    fake_mailbox.on_fetch = shorten
    result = _poll(django_capture_on_commit_callbacks)

    assert result.state == "ok" and fake_mailbox.fetched == [1, 2, 3]
    assert len(seen_ttl) == 3 and 100 < seen_ttl[0] <= 120, seen_ttl
    assert all(100 < ttl <= 120 for ttl in seen_ttl[1:]), f"срок не продлён после письма: {seen_ttl}"
    assert conn.exists(LOCK_KEY) == 0


# --- 2. первое подключение -------------------------------------------------------------------------------

def test_first_connect_sets_last_uid_to_uidnext_minus_one_and_parses_nothing(
        fake_mailbox, protected_root, settings, django_capture_on_commit_callbacks):
    """FR-211: первое подключение к ящику с тремя письмами — `uidvalidity` записан, `last_uid = UIDNEXT − 1`, письма
    не скачиваются и не разбираются; `connected` ложно до подключения и истинно после, страница при заданном
    `IMAP_HOST` не пишет «ящик не подключён»; следующий опрос берёт только новые письма."""
    mailbox, _, _ = _svc()
    _inbound_dir(protected_root)
    for n in (1, 2, 3):
        fake_mailbox.append(_raw(n))
    assert fake_mailbox.uidnext == 4
    client = _manager_client()

    before = mailbox.status()
    assert before.configured is True and before.connected is False
    html = client.get("/servicedesk/inbound/").content.decode()
    assert _mailbox_state_attr(html) == "connected" and "ящик не подключён" not in html.lower()

    result = _poll(django_capture_on_commit_callbacks)

    assert result.state == "ok" and result.fetched == 0 and result.known == 0
    state = _state()
    assert state.uidvalidity == 1000 and state.last_uid == 3
    assert state.last_ok_at is not None and state.last_poll_at is not None and state.last_error == ""
    assert fake_mailbox.fetched == [] and _rows() == [] and _jobs() == []
    assert model("servicedesk.Ticket").objects.count() == 0
    assert mailbox.status().connected is True

    fake_mailbox.append(_raw(4))
    assert _poll(django_capture_on_commit_callbacks).fetched == 1
    assert fake_mailbox.fetched == [4] and [r.uid for r in _rows()] == [4] and _state().last_uid == 4


def test_first_connect_writes_mailbox_connected_journal(fake_mailbox, django_capture_on_commit_callbacks):
    """FR-211: первое подключение пишет в журнал `mailbox.connected` (вид `mailbox`, объект `"1"`, без автора,
    `before` пуст, `after` — `uidvalidity` и `last_uid`); второй опрос события не добавляет."""
    for n in (1, 2, 3):
        fake_mailbox.append(_raw(n))

    _poll(django_capture_on_commit_callbacks)

    (event,) = _events("mailbox.connected")
    assert (event.object_type, event.object_id, event.actor) == ("mailbox", "1", None)
    assert event.before == {}
    assert event.after == {"uidvalidity": 1000, "last_uid": 3}
    _poll(django_capture_on_commit_callbacks)
    assert len(_events("mailbox.connected")) == 1 and _events("mailbox.recreated") == []


# --- 3. адаптер на двойнике imaplib --------------------------------------------------------------------

def test_uidvalidity_taken_from_select_not_status(monkeypatch, settings, password):
    """FR-211: адаптер берёт UIDVALIDITY и UIDNEXT из ответа на выбор папки (`response`), а не из `STATUS`
    (у `STATUS` в двойнике другое значение)."""
    from apps.integrations.mail import imap

    _imap_settings(settings, password)
    _use_fake_imap(monkeypatch, imap, uidvalidity=777, uidnext=12, status_uidvalidity=999)

    with imap.connect() as conn:
        assert conn.uidvalidity == 777
        assert conn.uidnext == 12

    names = [name for name, _ in sd.FakeImap.calls]
    assert "status" not in names, "STATUS не нужен: значения в ответе на выбор папки"
    assert ("response", ("UIDVALIDITY",)) in sd.FakeImap.calls
    assert ("login", ("tickets", "***")) in sd.FakeImap.calls
    assert names.index("login") < names.index("select")


def test_mailbox_opened_read_only_examine_nothing_flagged_or_deleted(
        monkeypatch, settings, password, protected_root, django_capture_on_commit_callbacks):
    """FR-210, FR-211: папка выбирается только для чтения (`select(folder, readonly=True)`, команда EXAMINE); ответ
    не `OK` — `MailboxUnavailable` без пароля; адаптер не шлёт команд, меняющих ящик; после опроса ни одно письмо
    фальшивого ящика не помечено и не удалено."""
    from apps.integrations.mail import imap

    _imap_settings(settings, password)
    _use_fake_imap(monkeypatch, imap, uidvalidity=5, uidnext=9, status_uidvalidity=1)
    with imap.connect():
        pass
    assert sd.FakeImap.readonly is True
    assert ("select", ("INBOX", True)) in sd.FakeImap.calls
    changing = [c for c in sd.FakeImap.calls
                if c[0] in ("store", "copy", "expunge", "append", "delete")
                or (c[0] == "uid" and str(c[1][0]).upper() in ("STORE", "COPY", "EXPUNGE"))]
    assert changing == []

    _use_fake_imap(monkeypatch, imap, uidvalidity=5, uidnext=9, status_uidvalidity=1, select_result="NO")
    with pytest.raises(imap.MailboxUnavailable) as caught:
        imap.connect()
    assert password not in str(caught.value)

    # служба опроса на фальшивом ящике: письма не помечаются и не удаляются
    fake = sd.install_fake_mailbox(monkeypatch, settings)
    _inbound_dir(protected_root)
    _connect_first(fake, django_capture_on_commit_callbacks)
    for n in (1, 2, 3):
        fake.append(_raw(n))
    _poll(django_capture_on_commit_callbacks)
    assert fake.fetched == [1, 2, 3] and sorted(fake.messages) == [1, 2, 3]
    assert [fake.seen(uid) for uid in (1, 2, 3)] == [False, False, False]


def test_adapter_security_modes_ssl_starttls_with_verifying_context_and_none(monkeypatch, settings, password):
    """FR-210: `ssl` — `IMAP4_SSL(host, port, ssl_context=<проверяющий контекст>, timeout=IMAP_TIMEOUT)`; `starttls` —
    `IMAP4` и `starttls(ssl_context=…)` до входа; `none` — `IMAP4` без шифрования, контекст не создаётся; иной режим —
    `MailboxUnavailable`."""
    from apps.integrations.mail import imap

    made = []
    contexts = []

    def fake_context(*args, **kwargs):
        context = object()
        made.append((args, kwargs))
        contexts.append(context)
        return context

    monkeypatch.setattr(imap.ssl, "create_default_context", fake_context)
    _use_fake_imap(monkeypatch, imap, uidvalidity=1, uidnext=2, status_uidvalidity=9)

    def reset():
        made.clear()
        contexts.clear()
        sd.FakeImap.ctor.clear()
        sd.FakeImap.calls.clear()
        sd.FakeImap.instances.clear()
        sd.FakeImap.ssl_context = None

    # ssl
    _imap_settings(settings, password, "ssl")
    reset()
    imap.connect().close()
    (name, positional, kwargs), = sd.FakeImap.ctor
    assert (name, positional) == ("IMAP4_SSL", ("imap.test", 993))
    assert len(contexts) == 1 and kwargs["ssl_context"] is contexts[0]
    assert kwargs["timeout"] == 17
    assert "starttls" not in [c[0] for c in sd.FakeImap.calls]

    # starttls
    _imap_settings(settings, password, "starttls")
    reset()
    imap.connect().close()
    (name, positional, kwargs), = sd.FakeImap.ctor
    assert (name, positional) == ("IMAP4", ("imap.test", 993))
    assert "ssl_context" not in kwargs and kwargs["timeout"] == 17
    assert len(contexts) == 1 and sd.FakeImap.ssl_context is contexts[0]
    names = [c[0] for c in sd.FakeImap.calls]
    assert names.index("starttls") < names.index("login")

    # none
    _imap_settings(settings, password, "none")
    reset()
    imap.connect().close()
    (name, positional, kwargs), = sd.FakeImap.ctor
    assert (name, positional) == ("IMAP4", ("imap.test", 993))
    assert "ssl_context" not in kwargs and kwargs["timeout"] == 17
    assert made == [] and sd.FakeImap.ssl_context is None
    assert "starttls" not in [c[0] for c in sd.FakeImap.calls]

    # другое значение
    _imap_settings(settings, password, "plain")
    reset()
    with pytest.raises(imap.MailboxUnavailable):
        imap.connect()


# --- 4. выбор писем и запись ------------------------------------------------------------------------------

def test_new_mail_found_by_uid_range_filtered_on_client_for_empty_range(
        fake_mailbox, protected_root, django_capture_on_commit_callbacks):
    """FR-211: поиск идёт по диапазону `UID last_uid+1:*`; на пустой диапазон сервер отдаёт последнее письмо ящика, и
    `poll` отфильтровывает `uid <= last_uid` сам: ничего не скачано; новое письмо найдено по `("uid", last_uid+1)`."""
    _inbound_dir(protected_root)
    fake_mailbox.append(_raw(1))
    fake_mailbox.append(_raw(2))
    _connect_first(fake_mailbox, django_capture_on_commit_callbacks)
    assert _state().last_uid == 2

    result = _poll(django_capture_on_commit_callbacks)

    assert result.state == "ok" and result.fetched == 0 and result.known == 0
    assert fake_mailbox.searches[-1] == ("uid", 3), "сервер на пустой диапазон отдал письмо 2"
    assert fake_mailbox.fetched == [] and _rows() == [] and _jobs() == []

    uid = fake_mailbox.append(_raw(3))
    result = _poll(django_capture_on_commit_callbacks)

    assert uid == 3 and result.fetched == 1
    assert fake_mailbox.searches[-1] == ("uid", 3)
    assert fake_mailbox.fetched == [3] and [r.uid for r in _rows()] == [3]
    assert _state().last_uid == 3
    _poll(django_capture_on_commit_callbacks)
    assert fake_mailbox.fetched == [3], "письмо 3 повторно не скачивается"


def test_mail_read_by_other_client_still_fetched(fake_mailbox, protected_root, django_capture_on_commit_callbacks):
    """FR-211: письмо, которое другой клиент уже пометил прочитанным, не теряется (отбор по UID, а не по «непрочитанным»);
    портал признак «прочитано» не меняет ни у этого, ни у соседнего письма."""
    _inbound_dir(protected_root)
    _connect_first(fake_mailbox, django_capture_on_commit_callbacks)
    read = fake_mailbox.append(_raw(1), seen=True)
    other = fake_mailbox.append(_raw(2))
    fake_mailbox.mark_seen(read)

    result = _poll(django_capture_on_commit_callbacks)

    assert result.fetched == 2 and fake_mailbox.fetched == [read, other]
    assert [r.uid for r in _rows()] == [read, other]
    assert fake_mailbox.seen(read) is True and fake_mailbox.seen(other) is False


def test_at_most_20_mails_per_run_rest_next_run_in_uid_order(
        fake_mailbox, protected_root, django_capture_on_commit_callbacks):
    """NFR-201: за запуск скачивается не больше 20 писем, по возрастанию UID; остаток берёт следующий запуск, письма
    не теряются и не повторяются."""
    _inbound_dir(protected_root)
    _connect_first(fake_mailbox, django_capture_on_commit_callbacks)
    for n in range(1, 26):
        fake_mailbox.append(_raw(n))

    first = _poll(django_capture_on_commit_callbacks)

    assert first.state == "ok" and first.fetched == 20
    assert fake_mailbox.fetched == list(range(1, 21))
    assert [r.uid for r in _rows()] == list(range(1, 21)) and _state().last_uid == 20

    second = _poll(django_capture_on_commit_callbacks)

    assert second.fetched == 5
    assert fake_mailbox.fetched == list(range(1, 26))
    assert [r.uid for r in _rows()] == list(range(1, 26)) and _state().last_uid == 25
    assert len(_jobs()) == 25


def test_inbound_row_and_last_uid_saved_in_one_transaction(
        fake_mailbox, protected_root, monkeypatch, settings, django_capture_on_commit_callbacks):
    """FR-211, NFR-209: строка письма, файл и `last_uid` пишутся одной транзакцией: в момент записи файла строка уже
    есть, а `last_uid` ещё прежний; сбой на третьем письме оставляет строки 1 и 2 и `last_uid == 2`, строки 3 нет."""
    mailbox, _, _ = _svc()
    inbound = _inbound_dir(protected_root)
    _connect_first(fake_mailbox, django_capture_on_commit_callbacks)
    for n in (1, 2, 3, 4):
        fake_mailbox.append(_raw(n))
    last_ok_before = _state().last_ok_at
    real = mailbox.write_raw
    snapshots = []

    def watched(path, data):
        if len(snapshots) == 2:
            raise OSError("диск недоступен")
        row_id = int(path.name.split(".")[0])
        snapshots.append((model("servicedesk.InboundMail").objects.filter(pk=row_id).exists(), _state().last_uid))
        real(path, data)

    monkeypatch.setattr(mailbox, "write_raw", watched)
    result = _poll(django_capture_on_commit_callbacks)

    assert result.state == "unavailable" and result.fetched == 2, "OSError не поднимается, сохранены письма 1 и 2"
    assert _state().last_error and settings.IMAP_PASSWORD not in _state().last_error
    assert _state().last_ok_at == last_ok_before, "last_ok_at при ошибке не тронут"
    assert fake_mailbox.fetched == [1, 2, 3], "после сбоя на письме 3 письмо 4 в этот запуск не берётся"
    assert _lock().exists(LOCK_KEY) == 0, "замок снят"
    assert snapshots == [(True, 0), (True, 1)], "до записи файла строка есть, last_uid ещё прежний"
    assert [r.uid for r in _rows()] == [1, 2] and _state().last_uid == 2
    assert sorted(p.name for p in inbound.iterdir()) == sorted(f"{r.id}.eml" for r in _rows())


def test_file_write_error_rolls_back_and_same_uid_retried(
        fake_mailbox, protected_root, monkeypatch, settings, django_capture_on_commit_callbacks):
    """FR-211, NFR-209: ошибка записи файла (`OSError` из `write_raw`) откатывает строку письма и `last_uid`, разбор не
    ставится; на следующем запуске тот же UID скачивается снова и сохраняется."""
    mailbox, _, _ = _svc()
    inbound = _inbound_dir(protected_root)
    real = mailbox.write_raw
    _connect_first(fake_mailbox, django_capture_on_commit_callbacks)
    uid = fake_mailbox.append(_raw(1))

    def broken(path, data):
        raise OSError("диск недоступен")

    monkeypatch.setattr(mailbox, "write_raw", broken)
    last_ok_before = _state().last_ok_at
    failed = _poll(django_capture_on_commit_callbacks)

    assert failed.state == "unavailable" and failed.fetched == 0, "OSError не поднимается наружу"
    assert _state().last_error and settings.IMAP_PASSWORD not in _state().last_error
    assert _state().last_ok_at == last_ok_before
    assert _lock().exists(LOCK_KEY) == 0, "замок снят"
    assert _rows() == [] and _state().last_uid == uid - 1
    assert _jobs() == [] and list(inbound.iterdir()) == []
    assert fake_mailbox.fetched == [uid]

    monkeypatch.setattr(mailbox, "write_raw", real)
    result = _poll(django_capture_on_commit_callbacks)

    assert result.state == "ok" and result.fetched == 1
    assert fake_mailbox.fetched == [uid, uid], "тот же UID скачан повторно"
    (row,) = _rows()
    assert row.uid == uid and _state().last_uid == uid
    assert (inbound / f"{row.id}.eml").exists() and len(_jobs_of(row.id)) == 1


def test_raw_mail_saved_whole_byte_for_byte_before_parsing(
        fake_mailbox, protected_root, django_capture_on_commit_callbacks):
    """FR-212: письмо с вложением и «сырыми» байтами сохраняется целиком, байт в байт, в `protected/inbound/<id>.eml`
    до разбора (заявок нет, итога нет, строка в `received`); временного файла не остаётся."""
    inbound = _inbound_dir(protected_root)
    _connect_first(fake_mailbox, django_capture_on_commit_callbacks)
    part = sd.MailPart("data.bin", bytes(range(256)) * 40, "application/octet-stream")
    raw = _raw(1, attachments=[part]) + "\r\n хвост без разбора\r\n".encode() + b"\xff\xfe\x00\r\n"
    uid = fake_mailbox.append(raw)

    _poll(django_capture_on_commit_callbacks)

    (row,) = _rows()
    path = inbound / f"{row.id}.eml"
    assert path.read_bytes() == raw
    assert row.size == len(raw) and row.uid == uid and row.uidvalidity == 1000
    assert row.internal_date == fake_mailbox.messages[uid].internal_date
    assert row.status == "received" and row.outcome == "" and row.ticket_id is None
    assert row.received_at is not None
    assert not list(inbound.glob("*.tmp"))
    assert model("servicedesk.Ticket").objects.count() == 0


# --- 5. восстановление базы ----------------------------------------------------------------------------

def _restored_setup(fake_mailbox, protected_root):
    """Копия базы: последнее известное `last_uid = 0`, в ящике четыре письма, пары 1 и 3 уже во входящих копии."""
    _inbound_dir(protected_root)
    queue = _configure_corp()
    state = model("servicedesk.MailboxState")
    state.objects.create(pk=1, uidvalidity=1000, last_uid=0, last_ok_at=None)
    raws = {n: _raw(n, sender=f"person{n}@{CORP}") for n in (1, 2, 3, 4)}
    for n in (1, 2, 3, 4):
        fake_mailbox.append(raws[n])
    known = {}
    for n in (1, 3):
        requester = sd.make_requester(f"person{n}@{CORP}")
        ticket = sd.make_ticket(queue=queue, requester=requester)
        known[n] = sd.make_inbound(uidvalidity=1000, uid=n, from_email=f"person{n}@{CORP}", status="processed",
                                   outcome="created", ticket=ticket)
    return queue, known


def test_restored_database_known_pairs_not_downloaded_last_uid_advances(
        fake_mailbox, protected_root, django_capture_on_commit_callbacks):
    """FR-211, NFR-209: после восстановления базы пары `(uidvalidity, uid)`, которые уже есть во входящих, не скачиваются
    и лишь двигают `last_uid`; новые письма между ними и после них скачаны по порядку."""
    _restored_setup(fake_mailbox, protected_root)

    result = _poll(django_capture_on_commit_callbacks)

    assert result.state == "ok" and result.known == 2 and result.fetched == 2
    assert fake_mailbox.fetched == [2, 4], "известные пары 1 и 3 не скачивались"
    assert _state().last_uid == 4
    assert [r.uid for r in _rows(uidvalidity=1000)] == [1, 2, 3, 4]
    assert [j.args[0] for j in _jobs()] == [r.id for r in _rows(uid__in=[2, 4])]


def test_restored_database_new_mails_parsed_without_duplicate_tickets(
        fake_mailbox, protected_root, django_capture_on_commit_callbacks):
    """FR-211, NFR-209: новые письма после восстановления становятся заявками, а письма, уже разобранные в копии, второй
    заявки не создают: у каждого отправителя ровно одна заявка."""
    _, intake, _ = _svc()
    _restored_setup(fake_mailbox, protected_root)
    Ticket = model("servicedesk.Ticket")
    assert Ticket.objects.count() == 2

    _poll(django_capture_on_commit_callbacks)
    for row in _rows(uid__in=[2, 4]):
        with django_capture_on_commit_callbacks(execute=True):
            assert intake.process(row.pk) == "created"

    assert Ticket.objects.count() == 4
    for n in (1, 2, 3, 4):
        assert Ticket.objects.filter(requester_email=f"person{n}@{CORP}").count() == 1, f"заявок от person{n}"
    assert sorted(r.outcome for r in _rows(uidvalidity=1000)) == ["created"] * 4
    assert all(r.ticket_id for r in _rows(uidvalidity=1000))


# --- 6. ящик пересоздан -----------------------------------------------------------------------------------

def _connected_at(fake_mailbox, capture, *, hours: int = 1):
    """Ящик подключён, `last_ok_at` отодвинут на `hours` часов назад; возвращает это время."""
    _connect_first(fake_mailbox, capture)
    state = _state()
    sd.backdate(state, "last_ok_at", hours=hours)
    return state.last_ok_at


def test_recreated_mailbox_takes_mails_within_10_minutes_before_last_ok_at(
        fake_mailbox, protected_root, django_capture_on_commit_callbacks):
    """FR-211: ящик пересоздан (UIDVALIDITY другой) — выбирается `search_since` с датой на сутки раньше `last_ok_at`;
    письма с `INTERNALDATE` раньше `last_ok_at − 10 мин` не забираются, остальные забираются; новый UIDVALIDITY записан."""
    _inbound_dir(protected_root)
    last_ok = _connected_at(fake_mailbox, django_capture_on_commit_callbacks)
    fake_mailbox.recreate(uidvalidity=2000)
    fake_mailbox.append(_raw(1), internal_date=last_ok - timedelta(minutes=30))
    fake_mailbox.append(_raw(2), internal_date=last_ok - timedelta(minutes=9))
    fake_mailbox.append(_raw(3), internal_date=last_ok + timedelta(minutes=2))

    result = _poll(django_capture_on_commit_callbacks)

    assert result.state == "ok" and result.fetched == 2
    since = [day for kind, day in fake_mailbox.searches if kind == "since"]
    assert len(since) == 1
    from django.utils import timezone

    expected = {(last_ok - timedelta(days=1)).date(), timezone.localtime(last_ok - timedelta(days=1)).date()}
    assert since[0] in expected, f"дата отбора {since[0]}, ждали одну из {expected}"
    assert set(fake_mailbox.peeked) == {1, 2, 3}, "отбор по дате и Message-ID — по заголовкам, тело не скачивается"
    assert fake_mailbox.fetched == [2, 3]
    assert [(r.uidvalidity, r.uid) for r in _rows(uidvalidity=2000)] == [(2000, 2), (2000, 3)]
    state = _state()
    assert state.uidvalidity == 2000 and state.last_uid == 3


def test_recreated_mailbox_skips_repeated_message_id(
        fake_mailbox, protected_root, django_capture_on_commit_callbacks):
    """FR-211: из нового ящика не берётся письмо, чей `Message-ID` уже есть во входящих (перенесённое из старого ящика;
    оно лежит раньше новых); письмо без `Message-ID` и письмо с новым берутся."""
    _inbound_dir(protected_root)
    last_ok = _connected_at(fake_mailbox, django_capture_on_commit_callbacks)
    known_id = "<moved-from-old@client.test>"
    sd.make_inbound(uidvalidity=1000, uid=1, message_id=known_id, status="processed", outcome="created")
    fake_mailbox.recreate(uidvalidity=2000)
    fake_mailbox.append(_raw(1, message_id=known_id), internal_date=last_ok - timedelta(minutes=5))
    fake_mailbox.append(_raw(2, message_id="<fresh-2@client.test>"), internal_date=last_ok + timedelta(minutes=1))
    fake_mailbox.append(_raw(3, message_id=""), internal_date=last_ok + timedelta(minutes=2))

    _poll(django_capture_on_commit_callbacks)

    assert fake_mailbox.fetched == [2, 3], "письмо 1 с известным Message-ID не скачано"
    assert [r.uid for r in _rows(uidvalidity=2000)] == [2, 3]
    assert [r.message_id for r in _rows(uidvalidity=2000)] == ["<fresh-2@client.test>", ""]
    assert _state().last_uid == 3


def test_recreated_mailbox_last_uid_by_smallest_selected_uid_or_uidnext_minus_one(
        fake_mailbox, protected_root, django_capture_on_commit_callbacks):
    """FR-211: `last_uid` после пересоздания — наименьший UID отобранных минус 1 (обычный поиск начинается с него), а
    если отобранных нет — `UIDNEXT − 1`; вызовы `head` в предел 20 писем не входят."""
    _inbound_dir(protected_root)
    last_ok = _connected_at(fake_mailbox, django_capture_on_commit_callbacks)

    # есть отобранные: письмо 1 раньше окна, письма 2 и 3 внутри окна
    fake_mailbox.recreate(uidvalidity=2000)
    fake_mailbox.append(_raw(1), internal_date=last_ok - timedelta(minutes=40))
    fake_mailbox.append(_raw(2), internal_date=last_ok - timedelta(minutes=3))
    fake_mailbox.append(_raw(3), internal_date=last_ok)
    _poll(django_capture_on_commit_callbacks)
    assert fake_mailbox.searches[-1] == ("uid", 2), "last_uid = 2 − 1"
    assert fake_mailbox.fetched == [2, 3] and _state().last_uid == 3

    # отобранных нет: оба письма раньше окна, UIDNEXT = 3
    fake_mailbox.recreate(uidvalidity=3000)
    state = _state()
    for n in (1, 2):
        fake_mailbox.append(_raw(10 + n), internal_date=state.last_ok_at - timedelta(minutes=50))
    fake_mailbox.fetched.clear()
    _poll(django_capture_on_commit_callbacks)
    assert fake_mailbox.uidnext == 3
    assert fake_mailbox.searches[-1] == ("uid", 3), "last_uid = UIDNEXT − 1 = 2"
    assert fake_mailbox.fetched == [] and _state().last_uid == 2 and _state().uidvalidity == 3000

    uid = fake_mailbox.append(_raw(20))
    _poll(django_capture_on_commit_callbacks)
    assert fake_mailbox.fetched == [uid] and _state().last_uid == uid


def test_recreated_mailbox_writes_mailbox_recreated_journal(
        fake_mailbox, protected_root, django_capture_on_commit_callbacks):
    """FR-211: пересоздание ящика пишет `mailbox.recreated` (вид `mailbox`, объект `"1"`, без автора): `before` — прежний
    `uidvalidity`, `after` — новый и число пропущенных писем; `mailbox.connected` повторно не пишется."""
    _inbound_dir(protected_root)
    last_ok = _connected_at(fake_mailbox, django_capture_on_commit_callbacks)
    known_id = "<moved-from-old@client.test>"
    sd.make_inbound(uidvalidity=1000, uid=1, message_id=known_id, status="processed", outcome="created")
    fake_mailbox.recreate(uidvalidity=2000)
    fake_mailbox.append(_raw(1), internal_date=last_ok - timedelta(minutes=40))
    fake_mailbox.append(_raw(2), internal_date=last_ok + timedelta(minutes=1))
    fake_mailbox.append(_raw(3, message_id=known_id), internal_date=last_ok - timedelta(minutes=5))

    _poll(django_capture_on_commit_callbacks)

    (event,) = _events("mailbox.recreated")
    assert (event.object_type, event.object_id, event.actor) == ("mailbox", "1", None)
    assert event.before == {"uidvalidity": 1000}
    assert event.after == {"uidvalidity": 2000, "skipped": 1}, "письмо 1 старше окна не считается, письмо 3 известно"
    assert len(_events("mailbox.connected")) == 1


# --- 7. ошибки ------------------------------------------------------------------------------------------

def test_header_read_error_does_not_stop_poll_fields_empty(
        fake_mailbox, protected_root, monkeypatch, django_capture_on_commit_callbacks):
    """FR-211: ошибка чтения заголовков (`mail_parse.sender_of` поднимает исключение) опрос не останавливает: письма
    сохранены, `message_id`, `from_email`, `subject` пусты, `last_uid` продвинут, разбор поставлен."""
    mailbox, _, _ = _svc()
    _inbound_dir(protected_root)
    _connect_first(fake_mailbox, django_capture_on_commit_callbacks)

    def raising(*args, **kwargs):
        raise ValueError("заголовок не читается")

    monkeypatch.setattr(mailbox.mail_parse, "sender_of", raising)
    fake_mailbox.append(_raw(1))
    fake_mailbox.append(_raw(2))

    result = _poll(django_capture_on_commit_callbacks)

    assert result.state == "ok" and result.fetched == 2
    rows = _rows()
    assert [r.uid for r in rows] == [1, 2]
    assert [(r.message_id, r.from_email, r.subject) for r in rows] == [("", "", ""), ("", "", "")]
    assert _state().last_uid == 2 and _state().last_error == ""
    assert len(_jobs()) == 2


def test_connection_error_saved_in_last_error_without_password_no_retry(
        fake_mailbox, settings, caplog, django_capture_on_commit_callbacks):
    """FR-210, NFR-206: ошибка подключения не поднимается из `poll`: состояние `unavailable`, повтора нет (одно
    подключение), строка `MailboxState` создана с `last_error` без пароля (`***`) и `last_poll_at`; в логе и на
    странице пароля нет; следующий удачный опрос очищает ошибку."""
    secret = settings.IMAP_PASSWORD
    fake_mailbox.set_unavailable(f"вход отклонён для пароля {secret}")
    assert model("servicedesk.MailboxState").objects.count() == 0

    with caplog.at_level("DEBUG"):
        result = _poll(django_capture_on_commit_callbacks)

    assert result.state == "unavailable" and result.fetched == 0
    assert fake_mailbox.connects == 1, "повтора внутри запуска нет"
    state = _state()
    assert "***" in state.last_error and secret not in state.last_error and len(state.last_error) <= 500
    assert state.last_poll_at is not None and state.last_ok_at is None
    assert state.uidvalidity is None and state.last_uid is None
    assert secret not in caplog.text
    assert _rows() == [] and _lock().exists(LOCK_KEY) == 0
    html = _manager_client().get("/servicedesk/inbound/").content.decode()
    shown = " ".join(_all_inner(html, 'data-field="last-error"'))
    assert "***" in shown and secret not in html
    assert _mailbox_state_attr(html) == "connected"

    assert _poll(django_capture_on_commit_callbacks).state == "unavailable"
    assert fake_mailbox.connects == 2

    fake_mailbox.set_unavailable(None)
    assert _poll(django_capture_on_commit_callbacks).state == "ok"
    state = _state()
    assert state.last_error == "" and state.last_ok_at is not None and state.uidvalidity == 1000


# --- 8. постановка разбора, повторы и страница --------------------------------------------------------

def test_parse_job_enqueued_only_after_commit(fake_mailbox, protected_root, django_capture_on_commit_callbacks):
    """NFR-209, NFR-201: задание `process_inbound(id)` ставится в очередь `inbox` только после фиксации: пока обработчики
    не выполнены, очередь пуста; после — по одному заданию на письмо (позиционный аргумент, срок 300 с, пять повторов)."""
    mailbox, intake, _ = _svc()
    _inbound_dir(protected_root)
    _connect_first(fake_mailbox, django_capture_on_commit_callbacks)
    fake_mailbox.append(_raw(1))
    fake_mailbox.append(_raw(2))

    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        result = mailbox.poll()

    assert result.fetched == 2 and len(_rows()) == 2
    assert _jobs() == [], "до фиксации разбор в очередь не ставится"
    assert callbacks, "постановка зарегистрирована на фиксацию"
    for callback in callbacks:
        callback()

    jobs = _jobs()
    assert sorted(j.args for j in jobs) == sorted((r.id,) for r in _rows())
    for job in jobs:
        assert job.timeout == 300 and job.retries_left == 5 and job.retry_intervals == RETRY_INTERVALS
        assert job.kwargs == {}
    assert all(intake.has_job(r.id) for r in _rows())


def test_reparse_button_requeues_error_mail_for_manage_holder_only_403_for_others_and_ignores_processed_mail(
        protected_root, django_capture_on_commit_callbacks):
    """FR-220, FR-275: «Разобрать снова» (POST `/servicedesk/inbound/<id>/retry/`) у письма в `error` ставит разбор и
    показывает «Разбор поставлен в очередь»; обработанное письмо не трогается («Письмо не ждёт повторного разбора»);
    без права «Настройка сервис-деска» — 403; письма нет — 404; журнал не пишется; кнопка есть только у ошибки."""
    broken = sd.make_inbound(status="error", outcome="parse_error", last_error="parse: ValueError", attempts=5)
    done = sd.make_inbound(status="processed", outcome="created")
    manager = _manager_client("198.51.100.62")
    outsider = support.logged_in(support.make_with_permissions("servicedesk.all"), ip="198.51.100.63")
    url = f"/servicedesk/inbound/{broken.pk}/retry/"
    audit_count = model("core.AuditEvent").objects.filter(action__startswith="mailbox.").count()

    page = manager.get("/servicedesk/inbound/").content.decode()
    assert f'action="/servicedesk/inbound/{broken.pk}/retry/"' in page
    assert f'action="/servicedesk/inbound/{done.pk}/retry/"' not in page
    assert page.count('data-action="inbound-retry"') == 1
    assert 'data-form="inbound-retry"' in page
    assert any("parse: ValueError" in text for text in _all_inner(page, "data-error-reason"))

    assert outsider.get("/servicedesk/inbound/").status_code == 403
    assert outsider.post(url).status_code == 403
    assert _jobs() == [] and model("servicedesk.InboundMail").objects.get(pk=broken.pk).status == "error"

    with django_capture_on_commit_callbacks(execute=True):
        response = manager.post(url)
    assert response.status_code == 302 and response["Location"].endswith("/servicedesk/inbound/")
    assert [j.args for j in _jobs()] == [(broken.pk,)]
    shown = manager.get("/servicedesk/inbound/").content.decode()
    assert any("Разбор поставлен в очередь" in text for text in _all_inner(shown, 'role="status"'))

    with django_capture_on_commit_callbacks(execute=True):
        response = manager.post(f"/servicedesk/inbound/{done.pk}/retry/")
    assert response.status_code == 302 and response["Location"].endswith("/servicedesk/inbound/")
    assert [j.args for j in _jobs()] == [(broken.pk,)], "обработанное письмо в очередь не ставится"
    shown = manager.get("/servicedesk/inbound/").content.decode()
    assert any("Письмо не ждёт повторного разбора" in text for text in _all_inner(shown, 'role="status"'))
    assert model("servicedesk.InboundMail").objects.get(pk=done.pk).status == "processed"

    assert manager.post("/servicedesk/inbound/999999/retry/").status_code == 404
    assert model("core.AuditEvent").objects.filter(action__startswith="mailbox.").count() == audit_count


def test_requeue_inbound_enqueues_parsing_of_received_mails_older_than_3_minutes_without_job_and_skips_fresh_and_processed(
        django_capture_on_commit_callbacks):
    """FR-211, NFR-209: `requeue_inbound` ставит разбор письмам в `received`, полученным раньше 3 минут назад и без
    задания; письмо с заданием, свежее, обработанное, с ошибкой и ждущее настройки не трогаются; повторный запуск
    дублей не создаёт."""
    mailbox, intake, tasks = _svc()
    old = sd.make_inbound()
    queued = sd.make_inbound()
    fresh = sd.make_inbound()
    done = sd.make_inbound(status="processed", outcome="created")
    failed = sd.make_inbound(status="error", outcome="parse_error", last_error="parse: ValueError")
    waiting = sd.make_inbound(status="waiting_setup", outcome="waiting_setup")
    for row in (old, queued, done, failed, waiting):
        sd.backdate(row, "received_at", minutes=10)
    sd.backdate(fresh, "received_at", minutes=1)
    with django_capture_on_commit_callbacks(execute=True):
        intake.enqueue(queued.pk)
    assert intake.has_job(queued.pk) and not intake.has_job(old.pk)

    with django_capture_on_commit_callbacks(execute=True):
        count = mailbox.requeue_inbound()

    assert count == 1
    assert sorted(j.args for j in _jobs()) == sorted([(queued.pk,), (old.pk,)])
    for other in (fresh, done, failed, waiting):
        assert _jobs_of(other.pk) == []
    assert len(_jobs_of(old.pk)) == 1 and len(_jobs_of(queued.pk)) == 1

    with django_capture_on_commit_callbacks(execute=True):
        tasks.requeue_inbound()
    assert len(_jobs()) == 2 and intake.has_job(old.pk)
