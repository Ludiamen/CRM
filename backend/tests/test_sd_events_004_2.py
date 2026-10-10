"""T-4104: новые события сервис-деска на шине — перенос, открытие заново, ответ не отправлен, недоставка письма,
просмотр заявки (FR-313). Сценарии 1-3 спеки SPEC-004.

Правила — tests/CONTRACT-004.md (§ 4.2, решения 20 и 24 задач, E8, E9). Имена кода
среза 004 на уровне модуля не импортируются; службы сервис-деска берутся внутри тестов. События ловит `bus_spy`:
подписчики вызываются после фиксации (`django_capture_on_commit_callbacks(execute=True)`), порядок вызовов — порядок
публикации. Почта и очередь — настоящие (Mailpit, Valkey); проверка файла на вирусы подменена помощником среза 003.
"""
import importlib
import secrets

import pytest
from django.utils import timezone

from tests import support, support_org as org, support_servicedesk as sd
from tests.support import HX, model
from tests.support_mail import break_smtp, deliver

pytestmark = pytest.mark.django_db

DOMAIN = "corp.test"
MAILBOX = "tickets@stand.test"
SMTP_FROM = "portal@corp.test"

TRANSFERRED = "servicedesk.ticket_transferred"
REOPENED = "servicedesk.ticket_reopened"
ASSIGNEE_CHANGED = "servicedesk.assignee_changed"
REPLY_RECEIVED = "servicedesk.reply_received"
REPLY_NOT_SENT = "servicedesk.reply_not_sent"
MAIL_FAILED = "servicedesk.mail_failed"
OBJECT_VIEWED = "object.viewed"


# --- помощники только этого файла ------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.servicedesk.services.{name}")


def _queue():
    return sd.make_queue(org.make_unit(f"Очередь {secrets.token_hex(3)}"))


def _member(unit, name: str | None = None):
    user = support.make_employee(full_name=name) if name else support.make_employee()
    org.make_member(user, unit)
    return user


def _actor():
    """Сотрудник с правом `servicedesk.all`: видит все заявки и участник любой очереди."""
    return support.make_with_permissions("servicedesk.all")


def _fresh(obj):
    obj.refresh_from_db()
    return obj


def _worked(queue, assignee, **over):
    return sd.make_ticket(queue=queue, kind="in_progress", assignee=assignee, assigned_once=True, **over)


def _of(spy, name: str, ticket) -> list[dict]:
    """Данные событий `name` по заявке (по номеру) в порядке публикации."""
    return [d for d in spy.calls(name) if d.get("number") == ticket.number]


def _order(spy, ticket, *names: str) -> list[str]:
    """Имена событий из `names` по этой заявке в порядке вызовов шины."""
    return [n for n, d in spy.all() if n in names and d.get("number") == ticket.number]


def _has(data: dict, **expected) -> None:
    """Каждый названный ключ данных события равен ожидаемому (прочие ключи не сверяются)."""
    for key, value in expected.items():
        assert key in data, f"в данных события нет ключа {key}: {sorted(data)}"
        assert data[key] == value, f"{key}: ждали {value!r}, получили {data[key]!r}"


def _prepare(settings):
    """Ящик, адрес отправки портала, домен и очередь по умолчанию; возвращает её `Queue`."""
    settings.SERVICEDESK_MAILBOX = MAILBOX
    settings.DEFAULT_FROM_EMAIL = SMTP_FROM
    default = sd.make_queue()
    sd.configure_servicedesk(domains=[DOMAIN], default_queue=default)
    return default


def _closed(queue_row, *, assignee=None, days: int = 3):
    """Закрытая `days` суток назад заявка с первым письмом заявителя."""
    requester = sd.make_requester(f"req-{secrets.token_hex(3)}@{DOMAIN}")
    ticket = sd.make_ticket(queue=queue_row, requester=requester, kind="closed", closed_at=timezone.now(),
                            resolution="Готово", assignee=assignee, assigned_once=assignee is not None)
    sd.make_entry(ticket, "incoming", text="Первое письмо")
    if days:
        sd.backdate(ticket, "closed_at", days=days)
    return _fresh(ticket)


def _letter(ticket, protected_root, capture):
    """Письмо заявителя с `[#N]` в теме разбирается настоящим `intake.process`; возвращает итог."""
    intake = _svc("intake")
    raw = sd.build_mail(from_addr=ticket.requester_email, to=[MAILBOX], subject=f"[#{ticket.number}] Ответ",
                        text="Не помогло")
    inbound = sd.make_inbound(size=len(raw), from_email=ticket.requester_email)
    folder = protected_root / "inbound"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{inbound.pk}.eml").write_bytes(raw)
    with capture(execute=True):
        return intake.process(inbound.pk)


# --- ticket_transferred (FR-313) -------------------------------------------------------------------

def test_ticket_transferred_on_transfer_has_from_to_actor_and_assignee_after(bus_spy, django_capture_on_commit_callbacks):
    """FR-313: `transfer.transfer` публикует `ticket_transferred` с номером, очередями «из» и «в», действующим
    сотрудником и ответственным, оставшимся после переноса (участник обеих очередей остаётся)."""
    bus_spy.listen(TRANSFERRED, ASSIGNEE_CHANGED)
    current, target = _queue(), _queue()
    actor = _actor()
    keeper = _member(current.unit)
    org.make_member(keeper, target.unit)
    ticket = _worked(current, keeper)

    with django_capture_on_commit_callbacks(execute=True):
        _svc("transfer").transfer(ticket, target.unit_id, reason="Не наш профиль", actor=actor)

    (data,) = _of(bus_spy, TRANSFERRED, ticket)
    _has(data, number=ticket.number, from_queue_id=current.unit_id, to_queue_id=target.unit_id,
         actor_id=actor.pk, assignee_after_id=keeper.pk)
    assert _fresh(ticket).queue_id == target.unit_id and ticket.assignee_id == keeper.pk
    assert _of(bus_spy, ASSIGNEE_CHANGED, ticket) == [], "ответственный остался: смены нет"


def test_ticket_transferred_on_category_change_has_from_to_and_assignee_after(
        bus_spy, django_capture_on_commit_callbacks):
    """FR-313, решение E9: `change_category` с переходом в другую очередь публикует `ticket_transferred`; при
    ответственном по умолчанию новой категории в данных `assignee_after_id=None`, затем отдельное `assignee_changed`
    с действующим сотрудником."""
    bus_spy.listen(TRANSFERRED, ASSIGNEE_CHANGED)
    first, second = _queue(), _queue()
    actor = _actor()
    default = _member(second.unit)
    old = sd.make_category(queue=first)
    new_plain = sd.make_category(queue=second)
    new_default = sd.make_category(queue=second, default_assignee=default)
    keeper = _member(first.unit)
    org.make_member(keeper, second.unit)
    kept = _worked(first, keeper, category=old)
    unassigned = sd.make_ticket(queue=first, category=old)
    same_cat = sd.make_category(queue=first)
    same = sd.make_ticket(queue=first, category=old)

    with django_capture_on_commit_callbacks(execute=True):
        _svc("transfer").change_category(kept, new_plain, confirmed=True, actor=actor)
    with django_capture_on_commit_callbacks(execute=True):
        _svc("transfer").change_category(unassigned, new_default, confirmed=True, actor=actor)
    with django_capture_on_commit_callbacks(execute=True):
        _svc("transfer").change_category(same, same_cat, confirmed=True, actor=actor)

    (data,) = _of(bus_spy, TRANSFERRED, kept)
    _has(data, number=kept.number, from_queue_id=first.unit_id, to_queue_id=second.unit_id, actor_id=actor.pk,
         assignee_after_id=keeper.pk)
    assert _of(bus_spy, ASSIGNEE_CHANGED, kept) == [], "ответственный остался: смены нет"
    (data,) = _of(bus_spy, TRANSFERRED, unassigned)
    _has(data, number=unassigned.number, from_queue_id=first.unit_id, to_queue_id=second.unit_id,
         actor_id=actor.pk, assignee_after_id=None)
    assert _fresh(unassigned).assignee_id == default.pk
    (changed,) = _of(bus_spy, ASSIGNEE_CHANGED, unassigned)
    _has(changed, assignee_before_id=None, assignee_after_id=default.pk, actor_id=actor.pk)
    assert _order(bus_spy, unassigned, TRANSFERRED, ASSIGNEE_CHANGED) == [TRANSFERRED, ASSIGNEE_CHANGED]
    assert _fresh(same).category_id == same_cat.pk and _fresh(same).queue_id == first.unit_id
    assert _of(bus_spy, TRANSFERRED, same) == [], "очередь не менялась: переноса нет"


def test_ticket_transferred_assignee_after_is_none_when_assignee_cleared(bus_spy, django_capture_on_commit_callbacks):
    """FR-313, решение E9: ответственный не участник новой очереди — снят; `ticket_transferred` публикуется после
    `assignee_changed(after=None)` и несёт `assignee_after_id=None`."""
    bus_spy.listen(TRANSFERRED, ASSIGNEE_CHANGED)
    current, target = _queue(), _queue()
    actor = _actor()
    only_old = _member(current.unit)
    ticket = _worked(current, only_old)

    with django_capture_on_commit_callbacks(execute=True):
        result = _svc("transfer").transfer(ticket, target.unit_id, actor=actor)

    assert result.assignee_removed is True and _fresh(ticket).assignee_id is None
    (data,) = _of(bus_spy, TRANSFERRED, ticket)
    _has(data, from_queue_id=current.unit_id, to_queue_id=target.unit_id, actor_id=actor.pk, assignee_after_id=None)
    (changed,) = _of(bus_spy, ASSIGNEE_CHANGED, ticket)
    _has(changed, assignee_before_id=only_old.pk, assignee_after_id=None)
    assert _order(bus_spy, ticket, TRANSFERRED, ASSIGNEE_CHANGED) == [ASSIGNEE_CHANGED, TRANSFERRED]


# --- ticket_reopened (FR-313) ----------------------------------------------------------------------

def test_ticket_reopened_by_mail_has_via_mail_and_queue_and_assignee(
        settings, protected_root, bus_spy, django_capture_on_commit_callbacks):
    """FR-313: открытие письмом заявителя — `ticket_reopened` с `via="mail"`, `actor_id=None`, очередью заявки и
    прежним ответственным (участник очереди)."""
    _prepare(settings)
    bus_spy.listen(REOPENED)
    queue_row = sd.make_queue()
    assignee = _member(queue_row.unit)
    ticket = _closed(queue_row, assignee=assignee)

    result = _letter(ticket, protected_root, django_capture_on_commit_callbacks)

    assert result == "reopened" and _fresh(ticket).kind == "in_progress"
    (data,) = _of(bus_spy, REOPENED, ticket)
    _has(data, number=ticket.number, queue_id=queue_row.unit_id, via="mail", actor_id=None,
         assignee_id=assignee.pk)


def test_ticket_reopened_manually_has_via_manual_and_actor(settings, bus_spy, django_capture_on_commit_callbacks):
    """FR-313: ручное открытие — `via="manual"`, `actor_id` — номер сотрудника, `assignee_id` — ответственный."""
    _prepare(settings)
    bus_spy.listen(REOPENED)
    queue_row = sd.make_queue()
    member = _member(queue_row.unit)
    ticket = _closed(queue_row, assignee=member, days=40)

    with django_capture_on_commit_callbacks(execute=True):
        _svc("closing").reopen(ticket, actor=member)

    (data,) = _of(bus_spy, REOPENED, ticket)
    _has(data, number=ticket.number, queue_id=queue_row.unit_id, via="manual", actor_id=member.pk,
         assignee_id=member.pk)


def test_ticket_reopened_published_after_assignee_cleared_and_move_to_default_queue(
        settings, bus_spy, django_capture_on_commit_callbacks):
    """FR-313: узел закрытой заявки перестал быть очередью — заявка уходит в очередь по умолчанию, ответственный
    (не участник её) снимается; `ticket_reopened` публикуется последним и несёт новую очередь и `assignee_id=None`."""
    default = _prepare(settings)
    bus_spy.listen(REOPENED, ASSIGNEE_CHANGED)
    gone = sd.make_queue()
    admin = support.make_admin()
    former = _member(gone.unit)
    ticket = _closed(gone, assignee=former, days=3)
    _svc("queues").unmark(gone.unit_id, actor=admin)

    with django_capture_on_commit_callbacks(execute=True):
        _svc("closing").reopen(ticket, actor=admin)

    assert _fresh(ticket).queue_id == default.unit_id and ticket.assignee_id is None
    (data,) = _of(bus_spy, REOPENED, ticket)
    _has(data, queue_id=default.unit_id, assignee_id=None, via="manual", actor_id=admin.pk)
    (changed,) = _of(bus_spy, ASSIGNEE_CHANGED, ticket)
    _has(changed, assignee_before_id=former.pk, assignee_after_id=None)
    assert _order(bus_spy, ticket, ASSIGNEE_CHANGED, REOPENED) == [ASSIGNEE_CHANGED, REOPENED]


# --- reply_not_sent (FR-313) -----------------------------------------------------------------------

def _not_sent(monkeypatch, bus_spy, capture, *, scan, data: bytes, name: str, close: bool = False):
    """Ответ с файлом; проверка файла даёт `scan`; возвращает (заявка, элемент ответа, автор, данные события)."""
    bus_spy.listen(REPLY_NOT_SENT)
    actor = _actor()
    ticket = sd.make_ticket(queue=sd.make_queue(), kind="in_progress")
    scan(monkeypatch)
    part = _svc("attachments").Part(name=name, data=data)
    with capture(execute=True):
        entry = _svc("replies").reply(ticket, text="Ответ исполнителя", wait_flag=False, parts=[part], actor=actor)
    if close:
        status = model("servicedesk.Status").objects.get(kind="closed", is_default=True)
        model("servicedesk.Ticket").objects.filter(pk=ticket.pk).update(
            status=status, kind="closed", closed_at=timezone.now())
    with capture(execute=True):
        org.run_files_worker()
    assert _fresh(entry).send_state == "not_sent"
    (event,) = _of(bus_spy, REPLY_NOT_SENT, ticket)
    return ticket, entry, actor, event


def test_reply_not_sent_for_quarantine_has_reason_author_entry_and_no_actor(
        monkeypatch, protected_root, bus_spy, django_capture_on_commit_callbacks):
    """FR-313: файл ответа в карантине — `reply_not_sent` с `reason="quarantine"`, автором ответа, номером элемента
    ленты и `actor_id=None`."""
    ticket, entry, author, event = _not_sent(
        monkeypatch, bus_spy, django_capture_on_commit_callbacks,
        scan=lambda mp: sd.scan_found(mp, "Eicar-Signature"), data=org.eicar_bytes(), name="заметка.txt")
    _has(event, number=ticket.number, entry_id=entry.pk, reason="quarantine", author_id=author.pk, actor_id=None)


def test_reply_not_sent_for_encrypted_archive_has_reason_encrypted_and_no_actor(
        monkeypatch, protected_root, bus_spy, django_capture_on_commit_callbacks):
    """FR-313: архив с паролем — `reason="encrypted"`, автор ответа, элемент ленты, `actor_id=None`."""
    ticket, entry, author, event = _not_sent(
        monkeypatch, bus_spy, django_capture_on_commit_callbacks,
        scan=lambda mp: sd.scan_found(mp, "Heuristics.Encrypted.Zip"), data=b"plain bytes", name="архив.zip")
    _has(event, number=ticket.number, entry_id=entry.pk, reason="encrypted", author_id=author.pk, actor_id=None)


def test_reply_not_sent_for_closed_ticket_has_reason_ticket_closed_and_no_actor(
        monkeypatch, protected_root, bus_spy, django_capture_on_commit_callbacks):
    """FR-313: заявку закрыли за время проверки файла — `reason="ticket_closed"`, автор ответа, `actor_id=None`."""
    ticket, entry, author, event = _not_sent(
        monkeypatch, bus_spy, django_capture_on_commit_callbacks, scan=sd.scan_clean, data=b"clean data",
        name="справка.txt", close=True)
    _has(event, number=ticket.number, entry_id=entry.pk, reason="ticket_closed", author_id=author.pk,
         actor_id=None)


# --- mail_failed (FR-313) --------------------------------------------------------------------------

def test_mail_failed_published_for_each_mail_kind_with_no_actor(bus_spy, django_capture_on_commit_callbacks):
    """FR-313, решение E8: событие почтового модуля `mail.failed` письма заявки (`related_ref="ticket:<pk>"`) даёт
    `mail_failed` с видом письма по имени шаблона, для каждого из шести видов; `actor_id=None`; у письма-ответа
    `entry_id` — элемент ленты, у остальных `None`."""
    from apps.core import events

    bus_spy.listen(MAIL_FAILED)
    kinds = ("confirmation", "assigned", "reply", "closed", "reopened", "autoclosed")
    ticket = sd.make_ticket(queue=sd.make_queue(), kind="in_progress")
    staff = _actor()
    expected = {}
    for kind in kinds:
        message = model("mail.MailMessage").objects.create(
            to=ticket.requester_email, template=f"ticket.{kind}", subject="Тема", status="failed", attempts=1,
            related_ref=f"ticket:{ticket.pk}")
        entry = sd.make_entry(ticket, "reply", author=staff, text="Ответ", mail=message) if kind == "reply" else None
        expected[kind] = entry.pk if entry else None
        with django_capture_on_commit_callbacks(execute=True):
            events.publish("mail.failed", mail_id=message.pk, related_ref=message.related_ref)

    got = _of(bus_spy, MAIL_FAILED, ticket)
    assert [d["mail_kind"] for d in got] == list(kinds)
    for data in got:
        _has(data, number=ticket.number, entry_id=expected[data["mail_kind"]], actor_id=None)


def test_mail_failed_has_entry_id_none_when_mail_has_no_timeline_entry(
        settings, bus_spy, django_capture_on_commit_callbacks):
    """FR-313: настоящая недоставка письма-подтверждения после последней попытки — `mail_failed` с `mail_kind=
    "confirmation"`, `entry_id=None` (ключ есть, значение пусто) и `actor_id=None`."""
    import django_rq

    bus_spy.listen(MAIL_FAILED)
    ticket = sd.make_ticket(queue=sd.make_queue(), requester=sd.make_requester(f"req-{secrets.token_hex(3)}@{DOMAIN}"))
    entry = sd.make_entry(ticket, "incoming", text="Не печатает")
    with django_capture_on_commit_callbacks(execute=True):
        _svc("letters").send(ticket, "ticket.confirmation", entry=entry)
    (message,) = sd.ticket_mails(ticket)
    (job,) = [j for j in django_rq.get_queue("mail").jobs if j.args == (message.pk,)]
    job.retries_left = 0
    job.save()
    break_smtp(settings)
    with django_capture_on_commit_callbacks(execute=True):
        deliver()

    assert _fresh(message).status == "failed"
    (data,) = _of(bus_spy, MAIL_FAILED, ticket)
    _has(data, number=ticket.number, mail_kind="confirmation", entry_id=None, actor_id=None)


# --- object.viewed (FR-313) ------------------------------------------------------------------------

def _views(spy) -> list[dict]:
    return spy.calls(OBJECT_VIEWED)


def test_object_viewed_published_on_get_of_ticket_slider_and_page(bus_spy, django_capture_on_commit_callbacks):
    """FR-313: каждый успешный GET карточки — одно событие `object.viewed` с `object_ref="servicedesk.ticket:<pk>"`
    (первичный ключ, не номер) и `user_id`: и слайдер (`HX-Request: true`), и страница целиком."""
    bus_spy.listen(OBJECT_VIEWED)
    viewer = _actor()
    ticket = sd.make_ticket(queue=sd.make_queue())
    client = support.logged_in(viewer)
    path = f"/tickets/{ticket.number}/"
    expected = {"object_ref": f"servicedesk.ticket:{ticket.pk}", "user_id": viewer.pk}

    with django_capture_on_commit_callbacks(execute=True):
        slider = client.get(path, **HX)
    assert slider.status_code == 200
    assert _views(bus_spy) == [expected]
    with django_capture_on_commit_callbacks(execute=True):
        page = client.get(path)
    assert page.status_code == 200
    assert _views(bus_spy) == [expected, expected]


def test_object_viewed_not_published_on_post_actions_of_ticket(bus_spy, django_capture_on_commit_callbacks):
    """FR-313: действия POST над карточкой (взять, комментарий, комментарий через HX) события `object.viewed` не дают;
    не дают его и GET чужой заявки (404, нет доступа) и несуществующей."""
    bus_spy.listen(OBJECT_VIEWED)
    queue_row = sd.make_queue()
    worker = _member(queue_row.unit)
    ticket = sd.make_ticket(queue=queue_row)
    client = support.logged_in(worker)

    with django_capture_on_commit_callbacks(execute=True):
        took = client.post(f"/tickets/{ticket.number}/take/")
        commented = client.post(f"/tickets/{ticket.number}/comment/", {"text": "Внутренняя заметка"})
        hx_comment = client.post(f"/tickets/{ticket.number}/comment/", {"text": "Ещё заметка"}, **HX)
    assert took.status_code < 500 and commented.status_code < 500 and hx_comment.status_code < 500
    assert _fresh(ticket).assignee_id == worker.pk, "«Взять себе» не выполнилось: проверка пуста"
    assert _views(bus_spy) == []

    outsider = support.logged_in(support.make_employee())
    missing = max(ticket.number, 1) + 10 ** 6
    with django_capture_on_commit_callbacks(execute=True):
        foreign = outsider.get(f"/tickets/{ticket.number}/")
        absent = client.get(f"/tickets/{missing}/")
    assert foreign.status_code == 404 and absent.status_code == 404
    assert _views(bus_spy) == []


# --- порядок при открытии письмом (FR-313) ---------------------------------------------------------

def test_mail_reopen_publishes_ticket_reopened_before_reply_received(
        settings, protected_root, bus_spy, django_capture_on_commit_callbacks):
    """FR-313: письмо к закрытой заявке — `intake` сначала открывает заявку, затем дописывает письмо: подписчики
    вызываются в порядке `ticket_reopened`, затем `reply_received(via="reopened")`."""
    _prepare(settings)
    bus_spy.listen(REOPENED, REPLY_RECEIVED)
    queue_row = sd.make_queue()
    ticket = _closed(queue_row, assignee=_member(queue_row.unit))

    result = _letter(ticket, protected_root, django_capture_on_commit_callbacks)

    assert result == "reopened"
    assert _order(bus_spy, ticket, REOPENED, REPLY_RECEIVED) == [REOPENED, REPLY_RECEIVED]
    (received,) = _of(bus_spy, REPLY_RECEIVED, ticket)
    _has(received, via="reopened", author_kind="requester")
