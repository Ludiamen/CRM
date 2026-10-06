"""T-3129: обезличивание закрытых заявок (FR-290, FR-291, NFR-211). Сценарии хранения спеки SPEC-003.

Отбор по `closed_at` и `retention_years`, порции по 50 и предел ночи 2000, что остаётся и что стирается
(CONTRACT-003 § 6.24), запись заявителя (FR-291), журнал `ticket.anonymized`. Код среза на уровне модуля не
импортируется: имена берутся внутри тестов (CONTRACT-003, шапка). Файлы — настоящий том `protected_root`.
"""
import json
import re
import secrets
from datetime import datetime, timezone as dt_timezone

import pytest
from django.utils import timezone

from tests import factories, support, support_org as org, support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

ANON = "обезличено"  # CONTRACT-003 § 2.2, строка `ANONYMIZED`: тест сравнивает со строкой-литералом


# --- помощники только этого файла ------------------------------------------------------------------

def _boundary(years: int = 3, now=None):
    """Граница отбора по § 6.24: `now.replace(year=now.year - years)`; 29 февраля без такой даты — 28 февраля."""
    now = now or timezone.now()
    try:
        return now.replace(year=now.year - years)
    except ValueError:
        return now.replace(year=now.year - years, day=28)


def _closed(*, past_days: int = 2, years: int = 3, queue=None, requester=None, **over):
    """Закрытая заявка с `closed_at` на `past_days` дней раньше границы (отрицательное — позже: срок не вышел)."""
    ticket = sd.make_ticket(kind="closed", queue=queue, requester=requester, closed_at=timezone.now(), **over)
    sd.backdate(ticket, "closed_at", days=(timezone.now() - _boundary(years)).days + past_days)
    return ticket


def _retention():
    from apps.servicedesk.services import retention

    return retention


def _run(capture, ticket) -> bool:
    """`anonymize_one` с выполнением обработчиков «после фиксации»."""
    with capture(execute=True):
        return _retention().anonymize_one(ticket.pk)


def _fresh(obj):
    return type(obj).objects.get(pk=obj.pk)


def _token() -> str:
    return secrets.token_hex(6)


def _put(path, data: bytes = b"data") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _attach(ticket, entry, root, *, name="счёт.pdf", status="clean", write=True):
    """Вложение: `StoredFile(attachment)` и `Attachment`; файл — в `attachments/` или `incoming/` настоящего тома."""
    stored = model("core.StoredFile").objects.create(
        purpose="attachment", owner=None, size=4, sha256="0" * 64, content_type="application/pdf", status=status)
    folder = "attachments" if status == "clean" else "incoming"
    path = root / folder / str(stored.pk)
    if write:
        _put(path)
    att = model("servicedesk.Attachment").objects.create(ticket=ticket, entry=entry, file=stored, name=name, size=4)
    return stored, att, path


def _eml(inbound, root):
    path = root / "inbound" / f"{inbound.pk}.eml"
    _put(path, b"From: a@client.test\r\n\r\nraw")
    return path


def _mail(ticket, **over):
    fields = {"to": "client@client.test", "template": "ticket.reply", "subject": f"[#{ticket.number}] {ticket.subject}",
              "status": "sent", "related_ref": f"ticket:{ticket.pk}"}
    fields.update(over)
    return model("mail.MailMessage").objects.create(**fields)


def _audit(action, **filters):
    return list(model("core.AuditEvent").objects.filter(action=action, **filters).order_by("id"))


def _in_column(ticket, tsquery: str, *, plain: bool = False) -> bool:
    """Совпадает ли столбец `search` заявки с запросом `to_tsquery('russian', …)` (или `plainto_tsquery`)."""
    from django.contrib.postgres.search import SearchQuery

    query = SearchQuery(tsquery, config="russian", search_type="plain" if plain else "raw")
    return model("servicedesk.Ticket").objects.filter(pk=ticket.pk, search=query).exists()


def _staff(queue=None):
    queue = queue or sd.make_queue()
    user = support.make_employee()
    org.make_member(user, queue.unit)
    return user, queue


# --- отбор -------------------------------------------------------------------------------------------

def test_selects_closed_by_closed_at_and_retention_years(clock, django_capture_on_commit_callbacks):
    """FR-290: выбираются закрытые заявки с `closed_at` раньше границы «N лет назад»; `retention_years` читается при
    каждом вызове; 29 февраля — граница 28 февраля. Фикстура `clock` — исключение A1 (CONTRACT-003 § 6.24, строка
    `anonymize_batch`: заданий RQ в вызове нет)."""
    retention = _retention()
    queue = sd.make_queue()
    old = _closed(past_days=2, queue=queue)
    young = _closed(past_days=-2, queue=queue)
    recent = sd.make_ticket(kind="closed", queue=queue, closed_at=timezone.now())
    sd.backdate(recent, "closed_at", days=180)  # полгода назад: моложе года (R-6-a-1)
    with django_capture_on_commit_callbacks(execute=True):
        batch = retention.anonymize_batch()
    assert batch.done == 1
    assert _fresh(old).anonymized_at is not None
    assert _fresh(young).anonymized_at is None and _fresh(recent).anonymized_at is None
    assert _fresh(old).kind == "closed"

    sd.configure_servicedesk(retention_years=1)  # срок читается из настроек при каждом вызове
    with django_capture_on_commit_callbacks(execute=True):
        batch = retention.anonymize_batch()
    assert batch.done == 1  # young закрыта ~3 года назад, recent — полгода назад (моложе года)
    assert _fresh(young).anonymized_at is not None and _fresh(recent).anonymized_at is None
    sd.configure_servicedesk(retention_years=3)

    # 29.02.2028: три года назад — 29.02.2025, такой даты нет, граница — 28.02.2025
    clock.set(datetime(2028, 2, 29, 12, 0, tzinfo=dt_timezone.utc))
    before = _closed_at_explicit(datetime(2025, 2, 26, 12, 0, tzinfo=dt_timezone.utc), queue)
    after = _closed_at_explicit(datetime(2025, 3, 2, 12, 0, tzinfo=dt_timezone.utc), queue)
    with django_capture_on_commit_callbacks(execute=True):
        batch = retention.anonymize_batch()
    assert batch.done == 1
    assert _fresh(before).anonymized_at is not None
    assert _fresh(after).anonymized_at is None


def _closed_at_explicit(moment, queue):
    ticket = sd.make_ticket(kind="closed", queue=queue)
    model("servicedesk.Ticket").objects.filter(pk=ticket.pk).update(closed_at=moment)
    return _fresh(ticket)


def test_open_tickets_not_touched(django_capture_on_commit_callbacks):
    """FR-290: открытые заявки (новая, в работе, ждёт ответа) не обезличиваются, даже со старыми датами."""
    queue = sd.make_queue()
    requester = sd.make_requester(full_name="Открытый Заявитель")
    opened = []
    for kind in ("new", "in_progress", "waiting"):
        ticket = sd.make_ticket(kind=kind, queue=queue, requester=requester)
        sd.make_entry(ticket, "incoming", text="текст открытой заявки")
        sd.backdate(ticket, "created_at", days=2000)
        model("servicedesk.Ticket").objects.filter(pk=ticket.pk).update(closed_at=timezone.now())
        sd.backdate(_fresh(ticket), "closed_at", days=2000)  # остаток старого закрытия не делает заявку выбираемой
        opened.append(ticket)
    closed = _closed(queue=queue)
    with django_capture_on_commit_callbacks(execute=True):
        batch = _retention().anonymize_batch()
    assert batch.done == 1 and _fresh(closed).anonymized_at is not None
    for ticket in opened:
        fresh = _fresh(ticket)
        assert fresh.anonymized_at is None
        assert fresh.requester_email == requester.email and fresh.requester_id == requester.pk
        assert fresh.entries.get().text == "текст открытой заявки"
    assert _retention().anonymize_one(opened[0].pk) is False


def test_reopened_ticket_counts_from_new_close(django_capture_on_commit_callbacks):
    """FR-290: отсчёт — от последнего закрытия: открытая заново заявка не выбирается, после нового закрытия срок идёт заново."""
    retention = _retention()
    ticket = _closed(past_days=30)
    # открыта заново: `closed_at` очищено, вид не «закрыта»
    model("servicedesk.Ticket").objects.filter(pk=ticket.pk).update(
        kind="new", status=model("servicedesk.Status").objects.get(kind="new", is_default=True), closed_at=None)
    with django_capture_on_commit_callbacks(execute=True):
        assert retention.anonymize_batch().done == 0
    assert _fresh(ticket).anonymized_at is None
    # закрыта снова только что: старое закрытие значения не имеет
    model("servicedesk.Ticket").objects.filter(pk=ticket.pk).update(
        kind="closed", status=model("servicedesk.Status").objects.get(kind="closed", is_default=True),
        closed_at=timezone.now())
    with django_capture_on_commit_callbacks(execute=True):
        assert retention.anonymize_batch().done == 0
    assert _fresh(ticket).anonymized_at is None
    # новое закрытие давно вышло за срок: заявка выбирается
    sd.backdate(_fresh(ticket), "closed_at", days=(timezone.now() - _boundary()).days + 2)
    with django_capture_on_commit_callbacks(execute=True):
        assert retention.anonymize_batch().done == 1
    assert _fresh(ticket).anonymized_at is not None


# --- что стирается и что остаётся ----------------------------------------------------------------------

def test_feed_texts_emptied_and_authors_anonymized(django_capture_on_commit_callbacks):
    """FR-290: тексты `incoming`, `reply`, `comment` пусты; `author_email` и `author_name` письма заявителя — «обезличено»; элементы остаются."""
    staff, queue = _staff()
    requester = sd.make_requester(full_name="Фролов Игорь")
    ticket = _closed(queue=queue, requester=requester)
    incoming = sd.make_entry(ticket, "incoming", text="Секретный текст письма", author_email=requester.email,
                             author_name="Фролов Игорь")
    reply = sd.make_entry(ticket, "reply", author=staff, text="Ответ исполнителя с подробностями")
    comment = sd.make_entry(ticket, "comment", author=staff, text="Внутренний комментарий")
    count = ticket.entries.count()
    assert _run(django_capture_on_commit_callbacks, ticket) is True
    assert ticket.entries.count() == count
    for entry in (incoming, reply, comment):
        assert _fresh(entry).text == ""
    assert _fresh(incoming).author_email == ANON and _fresh(incoming).author_name == ANON
    assert _fresh(reply).author_id == staff.pk and _fresh(comment).author_id == staff.pk


def test_event_data_texts_and_attachment_names_removed(django_capture_on_commit_callbacks):
    """FR-290: из `data` событий удаляются `reason_text` (передача) и `name` (отказ вложения, карантин, неотправленный ответ); остальные ключи остаются."""
    ticket = _closed()
    cases = {
        "transferred": {"from": "Очередь А", "to": "Очередь Б", "from_id": 1, "to_id": 2,
                        "reason_text": "Клиент Иванов просил передать", "reason": "queue_changed"},
        "attachment_rejected": {"name": "пароль.zip", "reason": "encrypted"},
        "attachment_quarantined": {"name": "вирус.exe"},
        "reply_not_sent": {"name": "архив.zip", "reason": "encrypted", "entry_id": 7},
    }
    removed = {"transferred": "reason_text", "attachment_rejected": "name", "attachment_quarantined": "name",
               "reply_not_sent": "name"}
    entries = {code: sd.make_entry(ticket, "event", event=code, data=dict(data)) for code, data in cases.items()}
    assert _run(django_capture_on_commit_callbacks, ticket) is True
    for code, entry in entries.items():
        expected = {k: v for k, v in cases[code].items() if k != removed[code]}
        assert _fresh(entry).data == expected, code


def test_close_event_keeps_status_and_resolution_text(django_capture_on_commit_callbacks):
    """FR-290: событие закрытия сохраняет статус и текст решения; текст решения остаётся и в заявке."""
    data = {"status": "Решена", "status_id": 4, "resolution": "Заменили картридж и перезагрузили принтер"}
    ticket = _closed(resolution=data["resolution"])
    closed = sd.make_entry(ticket, "event", event="closed", data=dict(data))
    status_changed = sd.make_entry(ticket, "event", event="status_changed",
                                   data={"before": "Новая", "after": "Решена", "before_id": 1, "after_id": 4,
                                         "reason": "close"})
    assert _run(django_capture_on_commit_callbacks, ticket) is True
    assert _fresh(closed).data == data
    assert _fresh(status_changed).data["after"] == "Решена"
    assert _fresh(ticket).resolution == data["resolution"]


def test_kept_fields_number_subject_category_queue_unit_criticality_status_dates(django_capture_on_commit_callbacks):
    """FR-290: остаются номер, тема, категория, очередь, подразделение, критичность, статус, даты."""
    queue = sd.make_queue()
    category = sd.make_category(queue=queue)
    unit_name = f"Отдел {_token()}"
    unit = model("servicedesk.ClientUnit").objects.create(name=unit_name, name_key=org.name_key(unit_name))
    priority = model("servicedesk.Priority").objects.get(name_key="высокая")
    ticket = _closed(queue=queue, category=category, client_unit=unit, priority=priority, subject="Не печатает принтер",
                     resolution="Готово")
    names = ("number", "subject", "category_id", "queue_id", "client_unit_id", "priority_id", "status_id", "kind",
             "created_at", "closed_at", "last_message_at", "resolution", "source_id")
    before = {n: getattr(_fresh(ticket), n) for n in names}
    assert _run(django_capture_on_commit_callbacks, ticket) is True
    fresh = _fresh(ticket)
    assert {n: getattr(fresh, n) for n in names} == before
    assert fresh.anonymized_at is not None and fresh.kind == "closed"
    assert before["client_unit_id"] == unit.pk and before["category_id"] == category.pk


def test_requester_fields_anonymized_requester_link_cleared_search_rebuilt(django_capture_on_commit_callbacks):
    """FR-290: `requester_email` и `requester_name` — «обезличено», связь с записью заявителя пуста, поиск собран из номера и темы."""
    from apps.servicedesk.services import search

    email = f"frolov.{_token()}@corp.test"
    requester = sd.make_requester(email, full_name="Фролов Игорь")
    ticket = _closed(requester=requester, subject="Сломался сканер бухгалтерии")
    sd.make_entry(ticket, "incoming", text="Уникальнаяфраза в письме")
    search.rebuild(_fresh(ticket))
    assert _in_column(ticket, "фролов:*") and _in_column(ticket, email, plain=True)
    assert _run(django_capture_on_commit_callbacks, ticket) is True
    fresh = _fresh(ticket)
    assert fresh.requester_email == ANON and fresh.requester_name == ANON
    assert fresh.requester_id is None and fresh.anonymized_at is not None
    assert _in_column(ticket, f"{ticket.number}:*") and _in_column(ticket, "сканер:*")
    assert not _in_column(ticket, "фролов:*") and not _in_column(ticket, "игорь:*")
    assert not _in_column(ticket, email, plain=True) and not _in_column(ticket, "уникальнаяфраза:*")


def test_attachments_rows_deleted_files_erased_after_commit(django_capture_on_commit_callbacks, protected_root):
    """FR-290: строки `StoredFile` и `Attachment` удаляются в транзакции, файлы — только после её фиксации; чужие вложения целы."""
    StoredFile, Attachment = model("core.StoredFile"), model("servicedesk.Attachment")
    ticket = _closed()
    entry = sd.make_entry(ticket, "incoming", text="с вложениями")
    clean = _attach(ticket, entry, protected_root, name="счёт.pdf", status="clean")
    pending = _attach(ticket, entry, protected_root, name="акт.pdf", status="pending")
    rejected = Attachment.objects.create(ticket=ticket, entry=entry, file=None, name="большой.iso", size=99,
                                         rejected="too_big")
    other_ticket = _closed(past_days=-5)
    other = _attach(other_ticket, sd.make_entry(other_ticket, "incoming", text="чужое"), protected_root, name="чужой.pdf")
    assert clean[2].exists() and pending[2].exists()
    with django_capture_on_commit_callbacks(execute=True):
        assert _retention().anonymize_one(ticket.pk) is True
        assert not Attachment.objects.filter(ticket=ticket).exists()
        assert not StoredFile.objects.filter(pk__in=[clean[0].pk, pending[0].pk]).exists()
        assert not Attachment.objects.filter(pk=rejected.pk).exists()
        assert clean[2].exists() and pending[2].exists(), "файлы стираются только после фиксации"
    assert not clean[2].exists() and not pending[2].exists()
    assert StoredFile.objects.filter(pk=other[0].pk).exists() and other[2].exists()
    assert Attachment.objects.filter(pk=other[1].pk).exists()


def test_missing_file_on_repeat_is_not_error(django_capture_on_commit_callbacks, protected_root):
    """FR-290: отсутствующий на диске файл (вложения и письма) — не ошибка; повторный вызов ничего не меняет и отвечает `False`."""
    StoredFile = model("core.StoredFile")
    ticket = _closed()
    entry = sd.make_entry(ticket, "incoming", text="текст")
    stored, _, path = _attach(ticket, entry, protected_root, write=False)
    inbound = sd.make_inbound(ticket=ticket, from_email=factories.new_email("from"), subject="тема", outcome="created",
                              status="processed")
    assert not path.exists() and not (protected_root / "inbound" / f"{inbound.pk}.eml").exists()
    assert _run(django_capture_on_commit_callbacks, ticket) is True
    assert not StoredFile.objects.filter(pk=stored.pk).exists()
    assert _fresh(inbound).raw_deleted is True
    stamp = _fresh(ticket).anonymized_at
    assert _run(django_capture_on_commit_callbacks, ticket) is False
    assert _fresh(ticket).anonymized_at == stamp
    assert len(_audit("ticket.anonymized", object_id=str(ticket.number))) == 1


def test_inbound_mail_fields_cleared_and_raw_file_erased_after_commit(django_capture_on_commit_callbacks, protected_root):
    """FR-290: у входящих писем заявки `raw_deleted`, `from_email`, `subject`, `message_id` очищены, файл `.eml` стёрт после фиксации; итог остаётся."""
    ticket = _closed()
    other_ticket = _closed(past_days=-5)
    mail = sd.make_inbound(ticket=ticket, from_email=factories.new_email("from"), subject="Тема письма клиента",
                           outcome="created", status="processed")
    other = sd.make_inbound(ticket=other_ticket, from_email=factories.new_email("from"), subject="Чужая тема",
                            outcome="created", status="processed")
    path, other_path = _eml(mail, protected_root), _eml(other, protected_root)
    other_values = (other.from_email, other.subject, other.message_id)
    with django_capture_on_commit_callbacks(execute=True):
        assert _retention().anonymize_one(ticket.pk) is True
        fresh = _fresh(mail)
        assert fresh.raw_deleted is True
        assert fresh.from_email == "" and fresh.subject == "" and fresh.message_id == ""
        assert path.exists(), "файл письма стирается только после фиксации"
    assert not path.exists()
    fresh = _fresh(mail)
    assert fresh.outcome == "created" and fresh.ticket_id == ticket.pk
    kept = _fresh(other)
    assert kept.raw_deleted is False and (kept.from_email, kept.subject, kept.message_id) == other_values
    assert other_path.exists()


def test_delivery_log_to_cc_attachments_and_attempt_errors_cleared(django_capture_on_commit_callbacks):
    """FR-290, NFR-211: письма заявки в журнале доставки — `to` «обезличено», `cc`, `attachments`, `last_error` и ошибки попыток пусты; письма другой заявки целы."""
    MailAttempt = model("mail.MailAttempt")
    ticket = _closed()
    other_ticket = _closed(past_days=-5)
    msg = _mail(ticket, to="client@client.test", cc="a@client.test, b@client.test", attachments=["00000000-0000-0000-0000-000000000001"],
                last_error="550 client@client.test rejected", status="failed")
    attempt = MailAttempt.objects.create(message=msg, ok=False, error="smtp: client@client.test refused")
    foreign = _mail(other_ticket, to="other@client.test", cc="c@client.test", last_error="ошибка")
    foreign_attempt = MailAttempt.objects.create(message=foreign, ok=False, error="чужая ошибка")
    assert _run(django_capture_on_commit_callbacks, ticket) is True
    fresh = _fresh(msg)
    assert fresh.to == ANON and fresh.cc == "" and fresh.attachments == [] and fresh.last_error == ""
    assert _fresh(attempt).error == ""
    kept = _fresh(foreign)
    assert (kept.to, kept.cc, kept.last_error) == ("other@client.test", "c@client.test", "ошибка")
    assert _fresh(foreign_attempt).error == "чужая ошибка"


def test_delivery_log_subject_reply_to_message_id_references_kept(django_capture_on_commit_callbacks):
    """FR-290: у писем заявки остаются тема, `reply_to`, `message_id`, `references` (служебные идентификаторы), а также шаблон и статус."""
    ticket = _closed(subject="Тема заявки")
    msg = _mail(ticket, reply_to="tickets@portal.test", message_id="<abc123@portal.test>",
                references="<root@portal.test> <abc122@portal.test>", cc="x@client.test", status="sent")
    snapshot = {n: getattr(_fresh(msg), n) for n in ("subject", "reply_to", "message_id", "references", "template",
                                                      "status", "related_ref")}
    assert snapshot["subject"] == f"[#{ticket.number}] Тема заявки"
    assert _run(django_capture_on_commit_callbacks, ticket) is True
    fresh = _fresh(msg)
    assert {n: getattr(fresh, n) for n in snapshot} == snapshot
    assert fresh.to == ANON


def test_participants_deleted_and_events_show_anonymized_participant(django_capture_on_commit_callbacks):
    """FR-290: участники из копии удаляются; событие «участник снят» в карточке показывает «участник (обезличено)», адресов нет."""
    staff, queue = _staff()
    ticket = _closed(queue=queue)
    active_mail, removed_mail = factories.new_email("cc"), factories.new_email("gone")
    sd.make_participant(ticket, active_mail, name="Копия Активная")
    removed = sd.make_participant(ticket, removed_mail, name="Копия Снятая", removed_by=staff)
    event = sd.make_entry(ticket, "event", event="participant_removed", data={"participant_id": removed.pk})
    participants = model("servicedesk.TicketParticipant").objects
    assert participants.filter(ticket=ticket).count() == 2
    assert _run(django_capture_on_commit_callbacks, ticket) is True
    assert not participants.filter(ticket=ticket).exists()
    assert _fresh(event).kind == "event"
    response = support.logged_in(staff).get(f"/tickets/{ticket.number}/")
    assert response.status_code == 200
    html = response.content.decode()
    match = re.search(r'<li\b[^>]*data-event="participant_removed"[^>]*>(.*?)</li>', html, re.S)
    assert match is not None, "нет события participant_removed в ленте"
    text = " ".join(re.sub(r"<[^>]+>", " ", match.group(1)).split())
    assert "участник (обезличено)" in text
    for address in (active_mail, removed_mail):
        assert address not in html


def test_audit_ticket_anonymized_written(django_capture_on_commit_callbacks):
    """FR-290, FR-289: одно событие журнала `ticket.anonymized`: заявка, номер, без исполнителя, `after = {number}`, ни адресов, ни темы."""
    requester = sd.make_requester(full_name="Журнал Тестов")
    ticket = _closed(requester=requester, subject="Уникальная тема журнала")
    assert _run(django_capture_on_commit_callbacks, ticket) is True
    events = _audit("ticket.anonymized", object_id=str(ticket.number))
    assert len(events) == 1
    event = events[0]
    assert event.object_type == "ticket" and event.actor_id is None
    assert event.before == {} and event.after == {"number": ticket.number}
    dump = json.dumps([event.before, event.after], ensure_ascii=False)
    assert requester.email not in dump and "Журнал Тестов" not in dump and "Уникальная тема" not in dump


# --- порции и предел ночи --------------------------------------------------------------------------------

def _maintenance_jobs():
    import django_rq

    return [j for j in django_rq.get_queue("maintenance").jobs if j.func_name == "apps.servicedesk.tasks.anonymize_tickets"]


def test_batch_of_50_and_next_batch_queued_in_maintenance(django_capture_on_commit_callbacks):
    """FR-290: задание берёт 50 самых давних заявок по (`closed_at`, `id`) и ставит следующую порцию в `maintenance`
    с `done_total`, курсором `after` и сроком 600 с; последняя порция следующей не ставит."""
    from apps.servicedesk import tasks

    queue = sd.make_queue()
    requester = sd.make_requester()
    tickets = [_closed(past_days=60 - i, queue=queue, requester=requester) for i in range(51)]  # [0] — самая давняя
    assert _maintenance_jobs() == []
    with django_capture_on_commit_callbacks(execute=True):
        tasks.anonymize_tickets()
    done = [_fresh(t).anonymized_at is not None for t in tickets]
    assert done == [True] * 50 + [False]
    last = _fresh(tickets[49])
    jobs = _maintenance_jobs()
    assert len(jobs) == 1
    assert jobs[0].kwargs == {"done_total": 50, "after": (last.closed_at, last.pk)}
    assert jobs[0].timeout == 600
    with django_capture_on_commit_callbacks(execute=True):
        jobs[0].perform()
    assert _fresh(tickets[50]).anonymized_at is not None
    assert len(_maintenance_jobs()) == 1, "после последней порции новой не ставится"


def test_nightly_limit_2000_rest_next_night(django_capture_on_commit_callbacks):
    """FR-290: за ночь не больше 2000 заявок: `more` истинно, пока `done_total + done < 2000`; остаток уходит на следующую ночь."""
    from apps.servicedesk import tasks

    retention = _retention()
    queue = sd.make_queue()
    first, second, third = (_closed(past_days=10 - i, queue=queue) for i in range(3))
    with django_capture_on_commit_callbacks(execute=True):
        batch = retention.anonymize_batch(size=1, done_total=1998)
    first = _fresh(first)
    assert batch.done == 1 and batch.more is True and batch.last == (first.closed_at, first.pk)
    with django_capture_on_commit_callbacks(execute=True):
        batch = retention.anonymize_batch(size=1, done_total=1999, after=batch.last)
    assert batch.done == 1 and batch.more is False  # 1999 + 1 уже не меньше 2000
    assert _fresh(first).anonymized_at is not None and _fresh(second).anonymized_at is not None
    assert _fresh(third).anonymized_at is None
    # следующая ночь: счёт с нуля
    with django_capture_on_commit_callbacks(execute=True):
        tasks.anonymize_tickets()
    assert _fresh(third).anonymized_at is not None

    # задание передаёт предел 2000 (§ 7.1, R-6-a-2): при done_total 1960 порция из 50 исчерпывает ночь — следующей нет
    for n in range(51):
        _closed(past_days=100 - n, queue=queue)
    before = len(_maintenance_jobs())
    with django_capture_on_commit_callbacks(execute=True):
        tasks.anonymize_tickets(done_total=1960)
    assert len(_maintenance_jobs()) == before, "1960 + 50 не меньше 2000: следующая порция не ставится"
    # при done_total 1900 остаток ставится дальше: done_total = 1950
    for n in range(50):
        _closed(past_days=200 - n, queue=queue)
    with django_capture_on_commit_callbacks(execute=True):
        tasks.anonymize_tickets(done_total=1900)
    jobs = _maintenance_jobs()
    assert len(jobs) == before + 1 and jobs[-1].kwargs["done_total"] == 1950


def test_selection_rechecked_under_lock(django_capture_on_commit_callbacks):
    """FR-290: перед обезличиванием отбор проверяется заново: открытая заново, уже обезличенная, ещё не вышедшая за срок и несуществующая заявки дают `False` и не меняются."""
    retention = _retention()
    reopened = _closed()
    model("servicedesk.Ticket").objects.filter(pk=reopened.pk).update(
        kind="new", status=model("servicedesk.Status").objects.get(kind="new", is_default=True), closed_at=None)
    sd.make_entry(reopened, "incoming", text="текст остаётся")
    young = _closed(past_days=-2)
    done = _closed()
    assert _run(django_capture_on_commit_callbacks, done) is True
    stamp = _fresh(done).anonymized_at
    for ticket in (reopened, young):
        assert _run(django_capture_on_commit_callbacks, ticket) is False
        assert _fresh(ticket).anonymized_at is None and _fresh(ticket).requester_email != ANON
    assert _run(django_capture_on_commit_callbacks, done) is False
    assert _fresh(done).anonymized_at == stamp
    assert reopened.entries.get().text == "текст остаётся"
    with django_capture_on_commit_callbacks(execute=True):
        assert retention.anonymize_one(10 ** 9) is False
    assert len(_audit("ticket.anonymized")) == 1


def test_failure_of_one_ticket_does_not_roll_back_others(monkeypatch, django_capture_on_commit_callbacks):
    """FR-290: сбой одной заявки не откатывает остальные; сбойная в эту ночь больше не выбирается (курсор идёт дальше), в следующую — снова."""
    retention = _retention()
    queue = sd.make_queue()
    first, bad, last = (_closed(past_days=10 - i, queue=queue) for i in range(3))
    real = retention.anonymize_one

    def fails_for_one_id(ticket_id):
        if ticket_id == bad.pk:
            raise RuntimeError("сбой обезличивания")
        return real(ticket_id)

    monkeypatch.setattr(retention, "anonymize_one", fails_for_one_id)
    with django_capture_on_commit_callbacks(execute=True):
        batch = retention.anonymize_batch(size=2)
    bad_fresh = _fresh(bad)
    assert batch.done == 1 and batch.more is True and batch.last == (bad_fresh.closed_at, bad_fresh.pk)
    assert _fresh(first).anonymized_at is not None and bad_fresh.anonymized_at is None
    with django_capture_on_commit_callbacks(execute=True):
        batch = retention.anonymize_batch(size=2, after=batch.last)
    assert batch.done == 1 and batch.more is False
    assert _fresh(last).anonymized_at is not None and _fresh(bad).anonymized_at is None
    assert _fresh(bad).requester_email != ANON
    monkeypatch.setattr(retention, "anonymize_one", real)  # следующая ночь: сбойная выбирается снова
    with django_capture_on_commit_callbacks(execute=True):
        assert retention.anonymize_batch().done == 1
    assert _fresh(bad).anonymized_at is not None


# --- запись заявителя (FR-291) ---------------------------------------------------------------------------

def test_requester_record_from_ticket_without_other_tickets_deleted_with_audit_reason(django_capture_on_commit_callbacks):
    """FR-291: запись «заявка» без других заявок удаляется вместе с обезличиванием; журнал `requester.deleted` с причиной «срок хранения»."""
    Requester = model("servicedesk.Requester")
    requester = sd.make_requester(full_name="Одноразовый Заявитель", origin="ticket")
    ticket = _closed(requester=requester)
    assert _run(django_capture_on_commit_callbacks, ticket) is True
    assert not Requester.objects.filter(pk=requester.pk).exists()
    assert _fresh(ticket).requester_id is None
    events = _audit("requester.deleted", object_id=str(requester.pk))
    assert len(events) == 1
    event = events[0]
    assert event.object_type == "requester" and event.actor_id is None
    assert event.before == {"origin": "ticket"} and event.after == {"reason": "срок хранения"}
    assert requester.email not in json.dumps([event.before, event.after], ensure_ascii=False)


def test_requester_record_kept_when_other_tickets_exist(django_capture_on_commit_callbacks):
    """FR-291: пока у записи есть другие заявки (открытая или закрытая, но не вышедшая за срок), запись не меняется и не удаляется."""
    Requester = model("servicedesk.Requester")
    requester = sd.make_requester(full_name="Постоянный Заявитель", origin="ticket")
    old = _closed(requester=requester)
    other_open = sd.make_ticket(kind="new", requester=requester)
    other_young = _closed(past_days=-30, requester=requester)
    assert _run(django_capture_on_commit_callbacks, old) is True
    kept = Requester.objects.get(pk=requester.pk)
    assert (kept.email, kept.full_name, kept.origin) == (requester.email, "Постоянный Заявитель", "ticket")
    assert _fresh(other_open).requester_id == requester.pk and _fresh(other_young).requester_id == requester.pk
    assert _fresh(old).requester_id is None and _fresh(old).requester_email == ANON
    assert _audit("requester.deleted", object_id=str(requester.pk)) == []


def test_requester_record_from_table_kept(django_capture_on_commit_callbacks):
    """FR-291: запись из таблицы без других заявок остаётся, пока её не удалят вручную; журнал удаления не пишется."""
    Requester = model("servicedesk.Requester")
    requester = sd.make_requester(full_name="Из Таблицы", origin="table")
    ticket = _closed(requester=requester)
    assert _run(django_capture_on_commit_callbacks, ticket) is True
    kept = Requester.objects.get(pk=requester.pk)
    assert (kept.email, kept.full_name, kept.origin) == (requester.email, "Из Таблицы", "table")
    assert _fresh(ticket).requester_id is None and _fresh(ticket).requester_email == ANON
    assert _audit("requester.deleted", object_id=str(requester.pk)) == []


# --- нет адресов и ФИО ни в одном текстовом поле -----------------------------------------------------

def test_all_text_fields_of_slice_models_free_of_address_and_name_after_job(
        django_capture_on_commit_callbacks, protected_root):
    """FR-290, NFR-211: после ночного задания ни в одном текстовом, символьном и JSON-поле моделей среза, журнала
    доставки и журнала действий нет адресов, ФИО и текстов закрытой заявки."""
    from django.db import models as dj
    from django.apps import apps
    from apps.servicedesk import tasks

    tok = _token()
    needles = {
        "req_email": f"req.{tok}@corp.test", "req_name": f"Заявителев{tok} Пётр", "cc_email": f"cc.{tok}@corp.test",
        "cc_name": f"Копиев{tok} Иван", "gone_email": f"gone.{tok}@corp.test", "in_text": f"ТекстПисьма{tok}",
        "reply_text": f"ТекстОтвета{tok}", "comment_text": f"Комментарий{tok}", "reason": f"ПричинаПередачи{tok}",
        "att_name": f"вложение{tok}.pdf", "att_event": f"карантин{tok}.exe", "from": f"from.{tok}@sender.test",
        "in_subject": f"ТемаВходящего{tok}", "mail_cc": f"mailcc.{tok}@corp.test", "err": f"ошибка{tok}",
    }
    staff, queue = _staff()
    requester = sd.make_requester(needles["req_email"], full_name=needles["req_name"])
    ticket = _closed(requester=requester, queue=queue, subject="Тема остаётся", resolution="Решено")
    incoming = sd.make_entry(ticket, "incoming", text=needles["in_text"], author_email=needles["req_email"],
                             author_name=needles["req_name"])
    sd.make_entry(ticket, "reply", author=staff, text=needles["reply_text"])
    sd.make_entry(ticket, "comment", author=staff, text=needles["comment_text"])
    sd.make_entry(ticket, "event", event="transferred",
                  data={"from": "А", "to": "Б", "from_id": 1, "to_id": 2, "reason_text": needles["reason"]})
    sd.make_entry(ticket, "event", event="attachment_quarantined", data={"name": needles["att_event"]})
    sd.make_entry(ticket, "event", event="closed", data={"status": "Решена", "status_id": 4, "resolution": "Решено"})
    _attach(ticket, incoming, protected_root, name=needles["att_name"])
    sd.make_participant(ticket, needles["cc_email"], name=needles["cc_name"])
    removed = sd.make_participant(ticket, needles["gone_email"], removed_by=staff)
    sd.make_entry(ticket, "event", event="participant_removed", data={"participant_id": removed.pk})
    inbound = sd.make_inbound(ticket=ticket, from_email=needles["from"], subject=needles["in_subject"],
                              outcome="created", status="processed")
    _eml(inbound, protected_root)
    msg = _mail(ticket, to=needles["req_email"], cc=needles["mail_cc"], last_error=needles["err"])
    model("mail.MailAttempt").objects.create(message=msg, ok=False, error=needles["err"])
    model("core.AuditEvent").objects.create(action="ticket.created", object_type="ticket", object_id=str(ticket.number),
                                            before={}, after={"number": ticket.number})
    with django_capture_on_commit_callbacks(execute=True):
        tasks.anonymize_tickets()
    assert _fresh(ticket).anonymized_at is not None

    scanned = [m for m in apps.get_models() if m._meta.app_label == "servicedesk"]
    scanned += [model("mail.MailMessage"), model("mail.MailAttempt"), model("core.AuditEvent")]
    text_types = (dj.CharField, dj.TextField, dj.JSONField, dj.EmailField)
    found = []
    for mdl in scanned:
        names = [f.name for f in mdl._meta.concrete_fields if isinstance(f, text_types)]
        for row in mdl.objects.all().values_list(*names):
            for name, value in zip(names, row):
                blob = json.dumps(value, ensure_ascii=False) if not isinstance(value, str) else value
                found += [f"{mdl.__name__}.{name}: {key}" for key, needle in needles.items() if needle in blob]
    assert found == []
