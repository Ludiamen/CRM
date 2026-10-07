"""T-3131: журнал среза 003 — коды, поля «было / стало», русские названия, отсутствие ПДн (FR-288, FR-289, NFR-212).

Сценарии 1–10 спеки среза 003 (по следам заявки, справочников, очередей, заявителей, ящика). Каждый код § 9.2
контракта получает одно настоящее действие службы; события читаются из `core.AuditEvent`. Код среза на уровне
модуля не импортируется: имена берутся внутри функций (CONTRACT-003, шапка). Образец — `test_org_audit.py`.
Время сдвигается `backdate`, подмены — только точки § 3.5 (`scan_found`, `fake_mailbox`).
"""
import importlib
import json
import re
import secrets
from html import unescape
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.db import connection, transaction
from django.db.utils import ProgrammingError
from django.utils import timezone

from tests import support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db(databases=["default", "migrate"])

IP = "198.51.100.77"
CORP = "corp.test"

# Все тридцать четыре кода § 9.2 и вид объекта каждого.
CODE_TYPES = {
    "ticket.created": "ticket", "ticket.assigned": "ticket", "ticket.assignee_removed": "ticket",
    "ticket.transferred": "ticket", "ticket.updated": "ticket", "ticket.closed": "ticket",
    "ticket.autoclosed": "ticket", "ticket.reopened": "ticket", "ticket.reply_sent": "ticket",
    "ticket.comment_added": "ticket", "ticket.attachment_quarantined": "ticket", "ticket.mail_failed": "ticket",
    "ticket.participant_removed": "ticket", "ticket.anonymized": "ticket",
    "requester.created": "requester", "requester.updated": "requester", "requester.deleted": "requester",
    "requester_import.completed": "requester_import",
    "queue.marked": "queue", "queue.unmarked": "queue", "queue.default_changed": "queue",
    "sd_dictionary.created": "sd_dictionary", "sd_dictionary.updated": "sd_dictionary",
    "sd_dictionary.archived": "sd_dictionary", "sd_dictionary.restored": "sd_dictionary",
    "sd_dictionary.deleted": "sd_dictionary",
    "client_unit.created": "sd_dictionary", "client_unit.updated": "sd_dictionary",
    "client_unit.archived": "sd_dictionary", "client_unit.restored": "sd_dictionary",
    "client_unit.deleted": "sd_dictionary",
    "servicedesk.settings_changed": "servicedesk",
    "mailbox.connected": "mailbox", "mailbox.recreated": "mailbox",
}
SLICE_CODES = tuple(CODE_TYPES)

# Русские названия событий — § 9.2 контракта (колонка «Код»).
TITLES = {
    "ticket.created": "Заявка создана", "ticket.assigned": "Назначен ответственный",
    "ticket.assignee_removed": "Ответственный снят", "ticket.transferred": "Заявка передана в другую очередь",
    "ticket.updated": "Заявка изменена", "ticket.closed": "Заявка закрыта",
    "ticket.autoclosed": "Заявка закрыта автоматически", "ticket.reopened": "Заявка открыта заново",
    "ticket.reply_sent": "Ответ отправлен", "ticket.comment_added": "Комментарий добавлен",
    "ticket.attachment_quarantined": "Вложение в карантине", "ticket.mail_failed": "Письмо не доставлено",
    "ticket.participant_removed": "Участник снят", "ticket.anonymized": "Заявка обезличена",
    "requester.created": "Заявитель добавлен", "requester.updated": "Заявитель изменён",
    "requester.deleted": "Заявитель удалён", "requester_import.completed": "Загрузка заявителей выполнена",
    "queue.marked": "Очередь отмечена", "queue.unmarked": "Отметка очереди снята",
    "queue.default_changed": "Очередь по умолчанию изменена",
    "sd_dictionary.created": "Значение справочника добавлено", "sd_dictionary.updated": "Значение справочника изменено",
    "sd_dictionary.archived": "Значение справочника в архиве",
    "sd_dictionary.restored": "Значение справочника возвращено из архива",
    "sd_dictionary.deleted": "Значение справочника удалено",
    "client_unit.created": "Подразделение-клиент добавлено", "client_unit.updated": "Подразделение-клиент изменено",
    "client_unit.archived": "Подразделение-клиент в архиве",
    "client_unit.restored": "Подразделение-клиент возвращено из архива",
    "client_unit.deleted": "Подразделение-клиент удалено",
    "servicedesk.settings_changed": "Настройки сервис-деска изменены",
    "mailbox.connected": "Ящик заявок подключён", "mailbox.recreated": "Ящик заявок пересоздан",
}
OBJECT_TITLES = {
    "ticket": "заявка", "requester": "заявитель", "requester_import": "загрузка", "queue": "очередь",
    "sd_dictionary": "справочник", "servicedesk": "сервис-деск", "mailbox": "ящик заявок",
}
# Русские названия полей — § 9.2.
FIELD_TITLES = {
    "number": "номер", "channel": "канал", "queue": "очередь", "category": "категория", "priority": "критичность",
    "complexity": "сложность", "source": "источник", "status": "статус", "assignee": "ответственный",
    "created_by": "кто создал", "client_unit": "подразделение", "reason_given": "указана причина",
    "requester_name_changed": "ФИО заявителя изменено", "name_changed": "ФИО изменено",
    "entry_id": "номер элемента ленты", "participant_id": "номер участника", "mail_kind": "вид письма",
    "via": "способ", "origin": "отметка записи", "delete_missing": "удалять отсутствующих", "domains": "домены",
    "default_priority": "критичность по умолчанию", "autoclose_days": "срок автозакрытия, дней",
    "reopen_days": "срок открытия заново, дней", "form_hourly_limit": "порог формы в час",
    "retention_years": "срок хранения заявок, лет", "inbound_retention_days": "срок хранения писем без заявки, дней",
    "dictionary": "справочник", "name": "название", "order": "порядок",
    "default_assignee": "ответственный по умолчанию", "on_form": "на форме", "status_kind": "вид статуса",
    "is_default": "по умолчанию", "uidvalidity": "номер версии ящика (UIDVALIDITY)", "last_uid": "последний UID",
    "added": "добавлено", "updated": "обновлено", "unchanged": "без изменений", "deleted": "удалено",
    "reason": "причина", "queue_id": "номер очереди", "assignee_id": "номер ответственного",
    "created_by_id": "номер создавшего",
}
# Русские названия значений — § 9.2 («Значения VALUES»).
VALUE_TITLES = {
    ("channel", "mail"): "письмо", ("channel", "form"): "форма", ("channel", "staff"): "исполнитель",
    ("via", "manual"): "вручную", ("via", "mail"): "письмом заявителя",
    ("reason", "manual"): "вручную", ("reason", "queue_changed"): "смена очереди",
    ("reason", "not_participant"): "больше не участник очереди",
    ("origin", "table"): "таблица", ("origin", "ticket"): "заявка",
    ("dictionary", "category"): "категория", ("dictionary", "priority"): "критичность",
    ("dictionary", "complexity"): "сложность", ("dictionary", "status"): "статус",
    ("dictionary", "source"): "источник",
    ("status_kind", "new"): "новая", ("status_kind", "in_progress"): "в работе",
    ("status_kind", "waiting"): "ждёт ответа заявителя", ("status_kind", "closed"): "закрыта",
    ("mail_kind", "confirmation"): "подтверждение заявки", ("mail_kind", "assigned"): "взята в работу",
    ("mail_kind", "closed"): "закрыта с решением", ("mail_kind", "autoclosed"): "закрыта автоматически",
    ("mail_kind", "reopened"): "открыта заново", ("mail_kind", "reply"): "ответ исполнителя",
}
# Ключи `before` / `after` по таблице § 9.2 (`None` — сторона не читается тестом).
KEYS = {
    "ticket.created": (set(), {"number", "channel", "queue", "queue_id", "category", "priority", "source"}),
    "ticket.assigned": ({"assignee", "assignee_id"}, {"assignee", "assignee_id"}),
    "ticket.assignee_removed": ({"assignee", "assignee_id"}, {"assignee", "assignee_id", "reason"}),
    "ticket.transferred": ({"queue", "queue_id"}, {"queue", "queue_id", "reason_given"}),
    "ticket.closed": ({"status"}, {"status"}),
    "ticket.autoclosed": ({"status"}, {"status"}),
    "ticket.reopened": ({"status"}, {"status", "via"}),
    "ticket.reply_sent": (set(), {"entry_id"}),
    "ticket.comment_added": (set(), {"entry_id"}),
    "ticket.attachment_quarantined": (set(), {"file_id", "signature"}),
    "ticket.mail_failed": (set(), {"mail_kind"}),
    "ticket.participant_removed": (set(), {"participant_id"}),
    "ticket.anonymized": (set(), {"number"}),
    "requester.created": (set(), {"origin", "client_unit"}),
    "requester_import.completed": (set(), {"file_name", "delete_missing", "totals"}),
    "queue.marked": (set(), {"unit", "unit_id"}),
    "queue.unmarked": ({"unit", "unit_id"}, set()),
    "queue.default_changed": ({"unit", "unit_id"}, {"unit", "unit_id"}),
    "sd_dictionary.archived": (set(), {"dictionary", "name"}),
    "sd_dictionary.restored": (set(), {"dictionary", "name"}),
    "sd_dictionary.deleted": ({"dictionary", "name"}, set()),
    "client_unit.created": (set(), {"name"}),
    "client_unit.updated": ({"name"}, {"name"}),
    "client_unit.archived": (set(), {"name"}),
    "client_unit.restored": (set(), {"name"}),
    "client_unit.deleted": ({"name"}, set()),
    "mailbox.connected": (set(), {"uidvalidity", "last_uid"}),
    "mailbox.recreated": ({"uidvalidity"}, {"uidvalidity", "skipped"}),
}
# Целые значения (а не строки и не `bool`): § 9.1 «у ключей с суффиксом `_id` — целые».
INT_KEYS = ("queue_id", "unit_id", "assignee_id", "created_by_id", "entry_id", "participant_id", "number",
            "uidvalidity", "last_uid", "skipped", "autoclose_days", "reopen_days", "form_hourly_limit",
            "retention_years", "inbound_retention_days")
# Коды, у которых действует система (`actor` пуст всегда), и коды, у которых сотрудник есть всегда.
ACTOR_NONE = {"ticket.autoclosed", "ticket.attachment_quarantined", "ticket.mail_failed", "ticket.anonymized",
              "mailbox.connected", "mailbox.recreated"}
ACTOR_SET = {"ticket.transferred", "ticket.closed", "ticket.reply_sent", "ticket.comment_added",
             "ticket.participant_removed", "requester.updated", "requester_import.completed", "queue.marked",
             "queue.unmarked", "queue.default_changed", "sd_dictionary.created", "sd_dictionary.updated",
             "sd_dictionary.archived", "sd_dictionary.restored", "sd_dictionary.deleted", "client_unit.created",
             "client_unit.updated", "client_unit.archived", "client_unit.restored", "client_unit.deleted",
             "servicedesk.settings_changed"}
PATH_KINDS = {"category": "categories", "priority": "priorities", "complexity": "complexities",
              "status": "statuses", "source": "sources", "client_unit": "client-units"}


# --- помощники только этого файла ---------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.servicedesk.services.{name}")


def _tok() -> str:
    return secrets.token_hex(4)


def has_cyrillic(text: str) -> bool:
    return bool(re.search("[А-Яа-яЁё]", text))


def is_russian(text: str, code: str) -> bool:
    return text != code and has_cyrillic(text)


def event_text(event) -> str:
    return json.dumps([event.action, event.object_type, event.object_id, event.before, event.after],
                      ensure_ascii=False)


def slice_events() -> list:
    return list(model("core.AuditEvent").objects.filter(action__in=SLICE_CODES).order_by("id"))


def _step(ctx, name, call):
    """Выполняет `call` внутри фиксации; события журнала, появившиеся при этом, — в `ctx.by[name]`."""
    Event = model("core.AuditEvent")
    last = Event.objects.order_by("-id").values_list("id", flat=True).first() or 0
    with ctx.capture(execute=True):
        result = call()
    ctx.by[name] = list(Event.objects.filter(id__gt=last).order_by("id"))
    return result


def _of(ctx, name, code) -> list:
    return [e for e in ctx.by[name] if e.action == code]


def _one(ctx, name, code):
    found = _of(ctx, name, code)
    assert len(found) == 1, f"шаг {name}: событий {code} — {len(found)}, ждали одно"
    return found[0]


def _fresh(obj):
    obj.refresh_from_db()
    return obj


def _copy(obj):
    """Свежая отдельная копия строки из базы (исходный объект `delete()` не тронет)."""
    return type(obj).objects.get(pk=obj.pk)


def _desk(capture, settings):
    """Рабочее место: настройки, две очереди, исполнители, подразделение-клиент, категории."""
    settings.SERVICEDESK_MAILBOX = "tickets@stand.test"
    ctx = SimpleNamespace(capture=capture, by={}, tokens={})
    ctx.admin = support.make_admin()
    ctx.boss = support.make_with_permissions("servicedesk.all")
    ctx.q1 = sd.make_queue(org.make_unit(f"Очередь А {_tok()}"))
    ctx.q2 = sd.make_queue(org.make_unit(f"Очередь Б {_tok()}"))
    ctx.e1 = support.make_employee()
    ctx.e2 = support.make_employee()
    ctx.e3 = support.make_employee()
    org.make_member(ctx.e1, ctx.q1.unit)
    org.make_member(ctx.e2, ctx.q1.unit)
    sd.configure_servicedesk(domains=[CORP], default_queue=ctx.q1)
    ctx.cat = sd.make_category(queue=ctx.q1, on_form=True)
    ctx.cat2 = sd.make_category(queue=ctx.q2)
    ctx.cu = _step(ctx, "cu_create", lambda: _svc("dictionaries").create(
        "client_unit", name=f"Отдел клиентов {_tok()}", actor=ctx.admin))
    return ctx


def _addr(local: str) -> str:
    return f"{local}@{CORP}"


# --- сквозной прогон ----------------------------------------------------------------------------------

def _creates(ctx):
    """Заявки трёх каналов: письмо, форма, исполнитель (с ответственным при создании)."""
    tickets, dictionaries = _svc("tickets"), _svc("dictionaries")
    ctx.src = dictionaries.create("source", name=f"Телефон {_tok()}", actor=ctx.admin)
    ctx.tokens.update(mail_email=f"zayavmail{_tok()}", form_email=f"zayavform{_tok()}",
                      staff_email=f"zayavstaff{_tok()}", mail_name=f"ИмяПочта{_tok()}",
                      form_name=f"ИмяФорма{_tok()}", staff_name=f"ИмяИсп{_tok()}",
                      subject=f"ТемаЗаявки{_tok()}", text=f"ТекстПисьма{_tok()}")
    t = ctx.tokens
    ctx.mail_ticket = _step(ctx, "create_mail", lambda: tickets.create(
        channel=tickets.MAIL, subject=t["subject"], text=t["text"], requester_email=_addr(t["mail_email"]),
        requester_name=t["mail_name"]).ticket)
    ctx.form_ticket = _step(ctx, "create_form", lambda: tickets.create(
        channel=tickets.FORM, subject=f"Форма {_tok()}", text=f"ТекстФормы{_tok()}",
        requester_email=_addr(t["form_email"]), requester_name=t["form_name"], category=ctx.cat,
        consent_at=timezone.now(), ip=IP).ticket)
    ctx.staff_ticket = _step(ctx, "create_staff", lambda: tickets.create(
        channel=tickets.STAFF, subject=f"Исп {_tok()}", text=f"ТекстИсп{_tok()}",
        requester_email=_addr(t["staff_email"]), requester_name=t["staff_name"], client_unit_id=ctx.cu.pk,
        queue_id=ctx.q1.unit_id, source=ctx.src, take_by=ctx.e1, created_by=ctx.e1).ticket)


def _flow(ctx, monkeypatch):
    """Действия над заявками: назначение, правка, передача, закрытие, ответ, вложение, обезличивание."""
    assignment, transfer, tickets = _svc("assignment"), _svc("transfer"), _svc("tickets")
    replies, closing, reconcile = _svc("replies"), _svc("closing"), _svc("reconcile")
    attachments, retention = _svc("attachments"), _svc("retention")
    boss, t, tok = ctx.boss, ctx.mail_ticket, ctx.tokens
    Priority, Status = model("servicedesk.Priority"), model("servicedesk.Status")

    _step(ctx, "assign1", lambda: assignment.assign(_fresh(t), ctx.e1, actor=boss))
    _step(ctx, "assign2", lambda: assignment.assign(_fresh(t), ctx.e2, actor=boss))
    ctx.old_priority = _fresh(t).priority
    ctx.new_priority = Priority.objects.exclude(pk=ctx.old_priority.pk).filter(archived=False).order_by("id").first()
    _step(ctx, "update_priority", lambda: tickets.update_fields(_fresh(t), actor=boss, priority=ctx.new_priority))
    tok["new_name"] = f"НовоеИмя{_tok()}"
    _step(ctx, "update_name", lambda: tickets.update_fields(_fresh(t), actor=boss, requester_name=tok["new_name"]))
    _step(ctx, "update_unit", lambda: tickets.update_fields(_fresh(t), actor=boss, client_unit_id=ctx.cu.pk))
    _step(ctx, "update_two", lambda: tickets.update_fields(
        _fresh(t), actor=boss, priority=ctx.old_priority, requester_name=f"ЕщёИмя{_tok()}"))
    _step(ctx, "category", lambda: transfer.change_category(_fresh(t), ctx.cat2, confirmed=True, actor=boss))
    tok["reason"] = f"ПричинаПередачи{_tok()}"
    _step(ctx, "transfer_back", lambda: transfer.transfer(_fresh(t), ctx.q1.unit_id, reason="", actor=boss))
    _step(ctx, "assign3", lambda: assignment.assign(_fresh(t), ctx.e1, actor=boss))
    _step(ctx, "transfer_q2", lambda: transfer.transfer(
        _fresh(t), ctx.q2.unit_id, reason=tok["reason"], actor=boss))

    # сверка: ответственный не участник ни одной очереди
    ctx.orphan = sd.make_ticket(queue=ctx.q1, kind="in_progress", assignee=ctx.e3, assigned_once=True)
    _step(ctx, "reconcile", lambda: reconcile.for_users([ctx.e3.pk]))

    s = ctx.staff_ticket
    _step(ctx, "unassign", lambda: assignment.unassign(_fresh(s), actor=boss))
    tok.update(reply=f"ТекстОтвета{_tok()}", comment=f"ТекстКомментария{_tok()}", resolution=f"Решение{_tok()}",
               part_email=f"copy{_tok()}", part_name=f"ИмяКопии{_tok()}", file_name=f"файл{_tok()}.txt")
    ctx.reply = _step(ctx, "reply", lambda: replies.reply(_fresh(s), text=tok["reply"], actor=boss))
    model("servicedesk.TicketEntry").objects.filter(pk=ctx.reply.pk).update(send_state="not_sent")
    ctx.resent = _step(ctx, "resend", lambda: replies.resend(_fresh(ctx.reply), actor=boss))
    _step(ctx, "comment", lambda: replies.comment(_fresh(s), text=tok["comment"], actor=boss))
    ctx.participant = sd.make_participant(s, _addr(tok["part_email"]), name=tok["part_name"])
    _step(ctx, "participant", lambda: tickets.remove_participant(_fresh(s), ctx.participant.pk, actor=boss))
    message = _fresh(ctx.reply).mail  # письмо ответа, а не подтверждения заявки
    _step(ctx, "mail_failed", lambda: replies.on_mail_failed(mail_id=message.pk, related_ref=message.related_ref))
    closed = Status.objects.get(kind="closed", is_default=True)
    _step(ctx, "close", lambda: closing.close(_fresh(s), closed, tok["resolution"], actor=boss))
    _step(ctx, "reopen_manual", lambda: closing.reopen(_fresh(s), actor=boss))
    _step(ctx, "close2", lambda: closing.close(_fresh(s), closed, tok["resolution"], actor=boss))
    _step(ctx, "reopen_mail", lambda: closing.reopen(_fresh(s), actor=None, via="mail"))

    waiting = sd.make_ticket(queue=ctx.q1, kind="waiting", waiting_since=timezone.now())
    sd.backdate(waiting, "waiting_since", days=8)
    ctx.waiting = waiting
    _step(ctx, "autoclose", lambda: closing.autoclose_one(waiting.pk))

    old = sd.make_ticket(queue=ctx.q1, kind="closed", closed_at=timezone.now())
    sd.backdate(old, "closed_at", days=366 * 4)
    ctx.old = old
    _step(ctx, "anonymize", lambda: retention.anonymize_one(old.pk))

    host = sd.make_ticket(queue=ctx.q1)
    entry = sd.make_entry(host, "incoming")
    ctx.host = host
    accepted = _step(ctx, "accept", lambda: attachments.accept(
        entry, [attachments.Part(name=tok["file_name"], data=org.eicar_bytes())], strict=False))
    ctx.stored = accepted[0].file
    sd.scan_found(monkeypatch, "Eicar-Signature")
    from apps.core import tasks
    _step(ctx, "quarantine", lambda: tasks.scan_file(str(ctx.stored.pk)))


def _admin_part(ctx):
    """Справочники, подразделения-клиенты, очереди, настройки."""
    dictionaries, queues, settings_svc = _svc("dictionaries"), _svc("queues"), _svc("settings")
    admin, tok = ctx.admin, ctx.tokens
    Priority = model("servicedesk.Priority")

    tok["cat_name"] = f"Категория {_tok()}"
    tok["cat_name2"] = f"Категория {_tok()}"
    ctx.dcat = _step(ctx, "cat_create", lambda: dictionaries.create(
        "category", name=tok["cat_name"], order=5, queue_id=ctx.q2.unit_id, on_form=True, actor=admin))
    ctx.dcat = _step(ctx, "cat_rename", lambda: dictionaries.update(_fresh(ctx.dcat), name=tok["cat_name2"], actor=admin))
    _step(ctx, "cat_on_form", lambda: dictionaries.update(
        _fresh(ctx.dcat), name=tok["cat_name2"], on_form=False, actor=admin))
    ctx.prio = _step(ctx, "prio_create", lambda: dictionaries.create(
        "priority", name=f"Срочная {_tok()}", order=40, actor=admin))
    ctx.compl = _step(ctx, "compl_create", lambda: dictionaries.create(
        "complexity", name=f"Сложная {_tok()}", order=40, actor=admin))
    ctx.status_new = _step(ctx, "status_create", lambda: dictionaries.create(
        "status", name=f"Согласование {_tok()}", kind="in_progress", actor=admin))
    _step(ctx, "status_default", lambda: dictionaries.update(
        _fresh(ctx.status_new), name=ctx.status_new.name, is_default=True, actor=admin))
    ctx.status_extra = dictionaries.create("status", name=f"Ожидание {_tok()}", kind="waiting", actor=admin)
    _step(ctx, "status_archive", lambda: dictionaries.archive(_fresh(ctx.status_extra), actor=admin))
    _step(ctx, "status_restore", lambda: dictionaries.restore(_fresh(ctx.status_extra), actor=admin))
    # удаляется отдельная копия: `delete()` обнуляет `pk` у переданного объекта, а `ctx.status_extra.pk` нужен проверкам
    _step(ctx, "status_delete", lambda: dictionaries.delete(_copy(ctx.status_extra), actor=admin))

    ctx.cu2 = dictionaries.create("client_unit", name=f"Клиент {_tok()}", actor=admin)
    tok["cu_name1"] = ctx.cu2.name  # «было» до `update`: объект меняется на месте
    tok["cu_name2"] = f"Клиент {_tok()}"
    _step(ctx, "cu_update", lambda: dictionaries.update(_fresh(ctx.cu2), name=tok["cu_name2"], actor=admin))
    _step(ctx, "cu_archive", lambda: dictionaries.archive(_fresh(ctx.cu2), actor=admin))
    _step(ctx, "cu_restore", lambda: dictionaries.restore(_fresh(ctx.cu2), actor=admin))
    _step(ctx, "cu_delete", lambda: dictionaries.delete(_copy(ctx.cu2), actor=admin))

    ctx.q3 = org.make_unit(f"Очередь В {_tok()}")
    _step(ctx, "q_mark", lambda: queues.mark(ctx.q3.pk, actor=admin))
    _step(ctx, "q_default", lambda: queues.set_default(ctx.q3.pk, actor=admin))
    _step(ctx, "q_default_back", lambda: queues.set_default(ctx.q1.unit_id, actor=admin))
    _step(ctx, "q_unmark", lambda: queues.unmark(ctx.q3.pk, actor=admin))

    current = model("servicedesk.ServiceDeskSettings").objects.get(pk=1)
    ctx.settings_before = {
        "domains": list(current.domains), "default_priority": current.default_priority.name,
        "autoclose_days": current.autoclose_days, "reopen_days": current.reopen_days,
        "form_hourly_limit": current.form_hourly_limit, "retention_years": current.retention_years,
        "inbound_retention_days": current.inbound_retention_days}
    high = Priority.objects.get(name="Высокая")
    ctx.settings_after = {
        "domains": [CORP, "two.test"], "default_priority": high.name, "autoclose_days": 5, "reopen_days": 3,
        "form_hourly_limit": 20, "retention_years": 4, "inbound_retention_days": 60}
    _step(ctx, "settings", lambda: settings_svc.update(
        actor=admin, domains=f"{CORP}, two.test", default_priority=high, autoclose_days=5, reopen_days=3,
        form_hourly_limit=20, retention_years=4, inbound_retention_days=60))


def _requesters_part(ctx):
    """Записи заявителей: правка, удаление, загрузка таблицей."""
    requesters, requester_import = _svc("requesters"), _svc("requester_import")
    admin, tok = ctx.admin, ctx.tokens
    ctx.requester = _fresh(ctx.mail_ticket).requester
    tok["upd_name"] = f"НовоеФИО{_tok()}"
    ctx.cu_name = ctx.cu.name
    _step(ctx, "req_update", lambda: requesters.update(
        _fresh(ctx.requester), name=tok["upd_name"], client_unit_id=None, actor=admin))
    ctx.r2 = sd.make_requester(_addr(f"table{_tok()}"), full_name=f"Табличный{_tok()}", origin="table")
    _step(ctx, "req_set_unit", lambda: requesters.update(
        _fresh(ctx.r2), name=ctx.r2.full_name, client_unit_id=ctx.cu.pk, actor=admin))
    ctx.r3 = sd.make_requester(_addr(f"del{_tok()}"), full_name=f"Удаляемый{_tok()}", origin="table")
    _step(ctx, "req_delete", lambda: requesters.delete(_fresh(ctx.r3), actor=admin))
    ctx.gone = sd.make_requester(_addr(f"gone{_tok()}"), full_name=f"Уйдущий{_tok()}", origin="table")
    tok["unit_new"] = f"НоваяЕдиница{_tok()}"
    tok["import_email"] = _addr(f"imp{_tok()}")
    body = ("﻿Почта;Фамилия;Имя;Отчество;Подразделение\n"
            f"{tok['import_email']};Импортов;Иван;Иванович;{tok['unit_new']}\n").encode("utf-8")
    item = _step(ctx, "import_preview", lambda: requester_import.make_preview(
        body, file_name="people.csv", actor=admin))
    _step(ctx, "import_confirm", lambda: requester_import.confirm(item, delete_missing=True, actor=admin))
    ctx.import_item = item


def _mailbox_part(ctx, fake, protected_root):
    """Первое подключение ящика и его пересоздание."""
    mailbox = _svc("mailbox")
    (protected_root / "inbound").mkdir(exist_ok=True)
    _step(ctx, "mb_connect", lambda: mailbox.poll())
    state = model("servicedesk.MailboxState").objects.get(pk=1)
    sd.backdate(state, "last_ok_at", hours=1)
    fake.recreate(uidvalidity=2000)
    _step(ctx, "mb_recreate", lambda: mailbox.poll())


def _everything(capture, settings, monkeypatch, fake, protected_root):
    ctx = _desk(capture, settings)
    _creates(ctx)
    _flow(ctx, monkeypatch)
    _admin_part(ctx)
    _requesters_part(ctx)
    _mailbox_part(ctx, fake, protected_root)
    return ctx


def _check_keys(code, event, side, required, allowed=None):
    data = getattr(event, side)
    assert isinstance(data, dict), (code, side)
    if required is not None:
        assert required <= set(data) <= (allowed or required), (code, side, sorted(data))
    for key in INT_KEYS:
        if key in data and data[key] is not None:
            assert isinstance(data[key], int) and not isinstance(data[key], bool), (code, side, key, data[key])


def _audit_page_texts(admin) -> dict:
    """Страница журнала по каждому виду объекта среза (отфильтрована, чтобы события не ушли на вторую страницу)."""
    client = support.logged_in(admin, ip=IP)
    pages = {}
    for kind in OBJECT_TITLES:
        response = client.get(f"/audit/?object_type={kind}")
        assert response.status_code == 200, kind
        html, seen = response.content.decode(), set(re.findall(r'data-event-id="(\d+)"', response.content.decode()))
        for number in range(2, 40):  # следующие страницы, пока на них появляются новые события
            more = client.get(f"/audit/?object_type={kind}&page={number}")
            ids = set(re.findall(r'data-event-id="(\d+)"', more.content.decode())) if more.status_code == 200 else set()
            if not ids - seen:
                break
            seen |= ids
            html += more.content.decode()
        pages[kind] = html
    return pages


# --- 1. каждое действие среза пишет событие ---------------------------------------------------------------

def test_every_slice_action_writes_event_with_code_from_plan_table(
        django_capture_on_commit_callbacks, settings, monkeypatch, fake_mailbox, protected_root):
    """FR-288: каждое из 34 действий среза (заявки, заявители, загрузка, очереди, справочники, подразделения,
    настройки, ящик) пишет событие с кодом таблицы плана, видом и номером объекта и ключами § 9.2; у действий системы
    автора нет, у действий сотрудника есть."""
    ctx = _everything(django_capture_on_commit_callbacks, settings, monkeypatch, fake_mailbox, protected_root)
    events = slice_events()
    by_code = {}
    for event in events:
        by_code.setdefault(event.action, []).append(event)
    assert set(by_code) == set(SLICE_CODES), sorted(set(SLICE_CODES) ^ set(by_code))
    for code, kind in CODE_TYPES.items():
        for event in by_code[code]:
            assert event.object_type == kind and isinstance(event.object_id, str) and event.object_id, code
            assert isinstance(event.before, dict) and isinstance(event.after, dict), code
            if code in KEYS:
                for side, required in zip(("before", "after"), KEYS[code]):
                    optional = {"created_by", "created_by_id"} if (code, side) == ("ticket.created", "after") else set()
                    _check_keys(code, event, side, required, required | optional)
            if code.startswith("sd_dictionary"):
                assert re.fullmatch(r"(categories|priorities|complexities|statuses|sources):\d+", event.object_id), (
                    code, event.object_id)
            if code.startswith("client_unit"):
                assert re.fullmatch(r"client-units:\d+", event.object_id), (code, event.object_id)
            if code in ACTOR_NONE:
                assert event.actor_id is None, code
            if code in ACTOR_SET:
                assert event.actor_id is not None, code
    assert {e.object_id for e in by_code["queue.marked"]} >= {str(ctx.q3.pk)}
    assert {e.object_id for e in by_code["servicedesk.settings_changed"]} == {"1"}
    assert {e.object_id for e in by_code["mailbox.connected"] + by_code["mailbox.recreated"]} == {"1"}
    assert by_code["requester_import.completed"][0].object_id == str(ctx.import_item.pk)
    assert by_code["ticket.created"][0].object_id.isdigit()


# --- 2. русские названия ------------------------------------------------------------------------------

def test_event_codes_have_russian_labels_registered(
        django_capture_on_commit_callbacks, settings, monkeypatch, fake_mailbox, protected_root):
    """FR-288: названия событий, видов объекта, полей и значений — по-русски и именно такие, как в § 9.1–9.2:
    через точку `audit_labels` они попадают в общий словарь ядра (страница журнала и выгрузка)."""
    from apps.core.services import audit_labels, audit_search
    from apps.servicedesk import audit_labels as own

    _everything(django_capture_on_commit_callbacks, settings, monkeypatch, fake_mailbox, protected_root)
    titles = dict(audit_search.known_actions())
    for code, title in TITLES.items():
        assert titles.get(code) == title, (code, titles.get(code))
        assert own.ACTIONS[code] == title, code
    for kind, title in OBJECT_TITLES.items():
        assert audit_labels.object_title(kind) == title, kind
        assert own.OBJECT_TYPES[kind] == title, kind
    keys = set(FIELD_TITLES)
    for event in slice_events():
        for side in (event.before, event.after):
            keys |= set(side)
            for value in side.values():
                if isinstance(value, dict):
                    keys |= set(value)
    for key in sorted(keys):  # все подписи по-русски, как требует тест журнала среза 001 (дополнение 51)
        assert is_russian(audit_labels.label(key), key), f"поле {key} не переведено: {audit_labels.label(key)!r}"
    for key, title in FIELD_TITLES.items():
        assert audit_labels.label(key) == title, key
    for (field, value), title in VALUE_TITLES.items():
        assert audit_labels.text(field, value) == title, (field, value)
    assert audit_labels.text("reason", "manual") == "вручную"  # согласовано с `org`


# --- 3. создание заявки ----------------------------------------------------------------------------------

def test_ticket_created_event_fields_number_channel_queue_category_criticality(
        django_capture_on_commit_callbacks, settings):
    """FR-288: `ticket.created` по письму и по форме: номер, канал (код), очередь (название и номер), категория
    (название или пусто), критичность и источник — названия; `before` пуст; ничего сверх таблицы."""
    ctx = _desk(django_capture_on_commit_callbacks, settings)
    _creates(ctx)
    Source, current = model("servicedesk.Source"), model("servicedesk.ServiceDeskSettings").objects.get(pk=1)
    mail = _one(ctx, "create_mail", "ticket.created")
    ticket = _fresh(ctx.mail_ticket)
    assert (mail.object_type, mail.object_id, mail.actor_id) == ("ticket", str(ticket.number), None)
    assert mail.before == {}
    assert mail.after == {
        "number": ticket.number, "channel": "mail", "queue": ctx.q1.unit.name, "queue_id": ctx.q1.unit_id,
        "category": "", "priority": current.default_priority.name,
        "source": Source.objects.get(system_code="mail").name}
    form = _one(ctx, "create_form", "ticket.created")
    ticket = _fresh(ctx.form_ticket)
    assert (form.object_type, form.object_id, form.actor_id) == ("ticket", str(ticket.number), None)
    assert form.before == {}
    assert form.after == {
        "number": ticket.number, "channel": "form", "queue": ctx.q1.unit.name, "queue_id": ctx.q1.unit_id,
        "category": ctx.cat.name, "priority": current.default_priority.name,
        "source": Source.objects.get(system_code="form").name}


def test_executor_ticket_created_event_has_creator(django_capture_on_commit_callbacks, settings):
    """FR-288: у заявки от исполнителя автор события — исполнитель, в `after` ещё `created_by` (имя сотрудника
    целиком, § 9.2, дополнение 10) и `created_by_id`; источник — выбранный; адреса клиента нет (`ip` пуст)."""
    ctx = _desk(django_capture_on_commit_callbacks, settings)
    _creates(ctx)
    event = _one(ctx, "create_staff", "ticket.created")
    ticket = _fresh(ctx.staff_ticket)
    assert (event.object_type, event.object_id) == ("ticket", str(ticket.number))
    assert event.actor_id == ctx.e1.pk and event.ip is None
    assert event.before == {}
    assert set(event.after) == {"number", "channel", "queue", "queue_id", "category", "priority", "source",
                                "created_by", "created_by_id"}
    assert event.after["channel"] == "staff" and event.after["source"] == ctx.src.name
    assert event.after["created_by"] == ctx.e1.full_name and event.after["created_by_id"] == ctx.e1.pk


# --- 4. назначение, передача, правка ----------------------------------------------------------------------

def test_assign_transfer_update_events_were_became(django_capture_on_commit_callbacks, settings, monkeypatch, protected_root):
    """FR-288: назначение (при создании с `take_by` — от пустого, дополнение 7), смена ответственного, снятие
    (вручную, передачей, сверкой), передача, правка критичности и смена категории пишут «было / стало» по § 9.2
    (имена и названия, не номера; снятие сверкой — без автора, причина `not_participant`)."""
    ctx = _desk(django_capture_on_commit_callbacks, settings)
    _creates(ctx)
    _flow(ctx, monkeypatch)
    # назначение при создании с `take_by`: автор — он же, прежний ответственный пуст
    created = _one(ctx, "create_staff", "ticket.assigned")
    assert created.actor_id == ctx.e1.pk and created.object_id == str(_fresh(ctx.staff_ticket).number)
    assert created.before == {"assignee": "", "assignee_id": None}
    assert created.after == {"assignee": ctx.e1.full_name, "assignee_id": ctx.e1.pk}
    # смена ответственного
    Status = model("servicedesk.Status")
    status_edit = _one(ctx, "assign1", "ticket.updated")  # первое назначение переводит новую заявку в работу
    assert status_edit.before == {"status": Status.objects.get(kind="new", is_default=True).name}
    assert status_edit.after == {"status": Status.objects.get(kind="in_progress", is_default=True).name}
    first = _one(ctx, "assign1", "ticket.assigned")
    assert first.actor_id == ctx.boss.pk
    assert first.before == {"assignee": "", "assignee_id": None}
    assert first.after == {"assignee": ctx.e1.full_name, "assignee_id": ctx.e1.pk}
    second = _one(ctx, "assign2", "ticket.assigned")
    assert second.before == {"assignee": ctx.e1.full_name, "assignee_id": ctx.e1.pk}
    assert second.after == {"assignee": ctx.e2.full_name, "assignee_id": ctx.e2.pk}
    # снятие вручную
    manual = _one(ctx, "unassign", "ticket.assignee_removed")
    assert manual.actor_id == ctx.boss.pk
    assert manual.before == {"assignee": ctx.e1.full_name, "assignee_id": ctx.e1.pk}
    assert manual.after == {"assignee": "", "assignee_id": None, "reason": "manual"}
    # снятие передачей и сменой категории: очередь сменилась
    for step, who in (("transfer_q2", ctx.e1), ("category", ctx.e2)):
        removed = _one(ctx, step, "ticket.assignee_removed")
        assert removed.actor_id == ctx.boss.pk
        assert removed.before == {"assignee": who.full_name, "assignee_id": who.pk}
        assert removed.after == {"assignee": "", "assignee_id": None, "reason": "queue_changed"}
    # снятие сверкой: без автора
    swept = _one(ctx, "reconcile", "ticket.assignee_removed")
    assert swept.actor_id is None and swept.object_id == str(ctx.orphan.number)
    assert swept.before == {"assignee": ctx.e3.full_name, "assignee_id": ctx.e3.pk}
    assert swept.after == {"assignee": "", "assignee_id": None, "reason": "not_participant"}
    # передача
    moved = _one(ctx, "transfer_q2", "ticket.transferred")
    assert moved.actor_id == ctx.boss.pk and moved.object_id == str(ctx.mail_ticket.number)
    assert moved.before == {"queue": ctx.q1.unit.name, "queue_id": ctx.q1.unit_id}
    assert moved.after == {"queue": ctx.q2.unit.name, "queue_id": ctx.q2.unit_id, "reason_given": True}
    # правка критичности: названия
    edit = _one(ctx, "update_priority", "ticket.updated")
    assert edit.actor_id == ctx.boss.pk
    assert edit.before == {"priority": ctx.old_priority.name} and edit.after == {"priority": ctx.new_priority.name}
    # смена категории: категория было «пусто» → стало название, и передача в очередь новой категории
    cat = _one(ctx, "category", "ticket.updated")
    assert cat.before == {"category": ""} and cat.after == {"category": ctx.cat2.name}
    swap = _one(ctx, "category", "ticket.transferred")
    assert swap.before == {"queue": ctx.q1.unit.name, "queue_id": ctx.q1.unit_id}
    assert swap.after == {"queue": ctx.q2.unit.name, "queue_id": ctx.q2.unit_id, "reason_given": False}


def test_transfer_event_says_reason_given_without_text(django_capture_on_commit_callbacks, settings, monkeypatch, protected_root):
    """FR-288, FR-289: `ticket.transferred` хранит только факт «причина указана» (`True` при непустой, `False` при
    пустой); текста причины нет ни в `before`, ни в `after`."""
    ctx = _desk(django_capture_on_commit_callbacks, settings)
    _creates(ctx)
    _flow(ctx, monkeypatch)
    with_reason = _one(ctx, "transfer_q2", "ticket.transferred")
    assert with_reason.after["reason_given"] is True
    assert set(with_reason.after) == {"queue", "queue_id", "reason_given"} and set(with_reason.before) == {"queue", "queue_id"}
    without = _one(ctx, "transfer_back", "ticket.transferred")
    assert without.after["reason_given"] is False
    for event in (with_reason, without):
        assert ctx.tokens["reason"] not in event_text(event)


# --- 5. закрытие и открытие ---------------------------------------------------------------------------

def test_close_autoclose_reopen_events_status_before_after_and_reopen_way(
        django_capture_on_commit_callbacks, settings, monkeypatch, protected_root):
    """FR-288: закрытие и автозакрытие пишут статус «было / стало» (названия; автозакрытие — без автора, закрытие —
    с автором), открытие заново — статус и способ `manual` (с автором) или `mail` (без автора); текста решения нет."""
    ctx = _desk(django_capture_on_commit_callbacks, settings)
    _creates(ctx)
    _flow(ctx, monkeypatch)
    Status = model("servicedesk.Status")
    closed = Status.objects.get(kind="closed", is_default=True)
    in_work = Status.objects.get(kind="in_progress", is_default=True)
    number = str(ctx.staff_ticket.number)

    shut = _one(ctx, "close", "ticket.closed")
    assert (shut.object_type, shut.object_id, shut.actor_id) == ("ticket", number, ctx.boss.pk)
    assert shut.before == {"status": in_work.name} and shut.after == {"status": closed.name}
    assert ctx.tokens["resolution"] not in event_text(shut)

    manual = _one(ctx, "reopen_manual", "ticket.reopened")
    assert manual.actor_id == ctx.boss.pk and manual.object_id == number
    assert manual.before == {"status": closed.name} and manual.after == {"status": in_work.name, "via": "manual"}

    by_mail = _one(ctx, "reopen_mail", "ticket.reopened")
    assert by_mail.actor_id is None and by_mail.object_id == number
    assert by_mail.before == {"status": closed.name} and by_mail.after == {"status": in_work.name, "via": "mail"}

    auto = _one(ctx, "autoclose", "ticket.autoclosed")
    waiting_status = Status.objects.get(kind="waiting", is_default=True)
    after_status = _fresh(ctx.waiting).status
    assert (auto.object_type, auto.object_id, auto.actor_id) == ("ticket", str(ctx.waiting.number), None)
    assert auto.before == {"status": waiting_status.name} and auto.after == {"status": after_status.name}
    assert _fresh(ctx.waiting).kind == "closed"


# --- 6. ответ и комментарий -------------------------------------------------------------------------------

def test_reply_and_comment_events_fact_and_item_number_only(django_capture_on_commit_callbacks, settings, monkeypatch, protected_root):
    """FR-288, FR-289: ответ и комментарий пишут только факт и номер элемента ленты (`entry_id`, у повторной
    отправки — номер нового элемента); текста нет."""
    ctx = _desk(django_capture_on_commit_callbacks, settings)
    _creates(ctx)
    _flow(ctx, monkeypatch)
    number = str(ctx.staff_ticket.number)
    sent = _one(ctx, "reply", "ticket.reply_sent")
    assert (sent.object_type, sent.object_id, sent.actor_id) == ("ticket", number, ctx.boss.pk)
    assert sent.before == {} and sent.after == {"entry_id": ctx.reply.pk}
    again = _one(ctx, "resend", "ticket.reply_sent")
    assert again.before == {} and again.after == {"entry_id": ctx.resent.pk} and ctx.resent.pk != ctx.reply.pk
    comment = _one(ctx, "comment", "ticket.comment_added")
    entry = model("servicedesk.TicketEntry").objects.get(ticket=ctx.staff_ticket, kind="comment")
    assert (comment.object_type, comment.object_id, comment.actor_id) == ("ticket", number, ctx.boss.pk)
    assert comment.before == {} and comment.after == {"entry_id": entry.pk}
    for event in (sent, again, comment):
        assert ctx.tokens["reply"] not in event_text(event) and ctx.tokens["comment"] not in event_text(event)


# --- 7. вложение, письмо, участник ---------------------------------------------------------------------

def test_attachment_quarantine_mail_failed_participant_removed_events(
        django_capture_on_commit_callbacks, settings, monkeypatch, protected_root):
    """FR-288: карантин вложения (номер файла строкой и сигнатура, без автора и без имени файла), недоставка письма
    (вид письма, без автора), снятие участника (номер участника без адреса и имени, автор — исполнитель)."""
    ctx = _desk(django_capture_on_commit_callbacks, settings)
    _creates(ctx)
    _flow(ctx, monkeypatch)
    quarantined = _one(ctx, "quarantine", "ticket.attachment_quarantined")
    assert (quarantined.object_type, quarantined.object_id, quarantined.actor_id) == (
        "ticket", str(ctx.host.number), None)
    assert quarantined.before == {}
    assert quarantined.after == {"file_id": str(ctx.stored.pk), "signature": "Eicar-Signature"}
    assert ctx.tokens["file_name"] not in event_text(quarantined)
    failed = _one(ctx, "mail_failed", "ticket.mail_failed")
    assert (failed.object_type, failed.object_id, failed.actor_id) == ("ticket", str(ctx.staff_ticket.number), None)
    assert failed.before == {} and failed.after == {"mail_kind": "reply"}
    removed = _one(ctx, "participant", "ticket.participant_removed")
    assert (removed.object_type, removed.object_id, removed.actor_id) == (
        "ticket", str(ctx.staff_ticket.number), ctx.boss.pk)
    assert removed.before == {} and removed.after == {"participant_id": ctx.participant.pk}
    assert ctx.tokens["part_email"] not in event_text(removed) and ctx.tokens["part_name"] not in event_text(removed)
    gone = _one(ctx, "anonymize", "ticket.anonymized")
    purged = _one(ctx, "anonymize", "requester.deleted")  # заявитель стёрт по сроку хранения
    assert purged.before == {"origin": "ticket"} and purged.after == {"reason": "срок хранения"}
    assert (gone.object_type, gone.object_id, gone.actor_id) == ("ticket", str(ctx.old.number), None)
    assert gone.before == {} and gone.after == {"number": ctx.old.number}


# --- 8. справочники, очереди ---------------------------------------------------------------------------

def test_dictionary_queue_settings_events_were_became_in_russian(
        django_capture_on_commit_callbacks, settings, monkeypatch, protected_root):
    """FR-288: события справочников (вид объекта `sd_dictionary`, номер `<вид>:<id>` по пути раздела 12), подразделений
    и очередей — «было / стало» по § 9.2; перенос отметки «по умолчанию» — одно `updated` у выбранного статуса
    (дополнение 4); все названия полей и значений в этих событиях — по-русски."""
    from apps.core.services import audit_labels

    ctx = _desk(django_capture_on_commit_callbacks, settings)
    _creates(ctx)
    _flow(ctx, monkeypatch)
    _admin_part(ctx)
    cat = ctx.dcat
    made = _one(ctx, "cat_create", "sd_dictionary.created")
    assert (made.object_type, made.object_id, made.actor_id) == ("sd_dictionary", f"categories:{cat.pk}", ctx.admin.pk)
    assert made.before == {}
    assert made.after == {"dictionary": "category", "name": ctx.tokens["cat_name"], "order": 5,
                          "queue": ctx.q2.unit.name, "default_assignee": "", "on_form": True}
    renamed = _one(ctx, "cat_rename", "sd_dictionary.updated")
    assert renamed.object_id == f"categories:{cat.pk}"
    assert renamed.before == {"name": ctx.tokens["cat_name"]}
    assert renamed.after == {"dictionary": "category", "name": ctx.tokens["cat_name2"]}
    flag = _one(ctx, "cat_on_form", "sd_dictionary.updated")
    assert flag.before == {"on_form": True}
    assert flag.after == {"dictionary": "category", "name": ctx.tokens["cat_name2"], "on_form": False}
    prio = _one(ctx, "prio_create", "sd_dictionary.created")
    assert prio.object_id == f"priorities:{ctx.prio.pk}" and prio.after["dictionary"] == "priority"
    assert set(prio.after) == {"dictionary", "name", "order"}
    compl = _one(ctx, "compl_create", "sd_dictionary.created")
    assert compl.object_id == f"complexities:{ctx.compl.pk}" and compl.after["dictionary"] == "complexity"
    state = _one(ctx, "status_create", "sd_dictionary.created")
    assert state.object_id == f"statuses:{ctx.status_new.pk}"
    assert state.after == {"dictionary": "status", "name": ctx.status_new.name, "order": 0,
                           "status_kind": "in_progress", "is_default": False}
    # перенос «по умолчанию»: одно событие у выбранного статуса, у прежнего события нет
    moved = ctx.by["status_default"]
    assert [e.action for e in moved] == ["sd_dictionary.updated"]
    assert moved[0].object_id == f"statuses:{ctx.status_new.pk}"
    assert moved[0].before == {"is_default": False}
    assert moved[0].after == {"dictionary": "status", "name": ctx.status_new.name, "is_default": True}
    extra = f"statuses:{ctx.status_extra.pk}"
    arch = _one(ctx, "status_archive", "sd_dictionary.archived")
    assert arch.object_id == extra and arch.before == {}
    assert arch.after == {"dictionary": "status", "name": ctx.status_extra.name}
    rest = _one(ctx, "status_restore", "sd_dictionary.restored")
    assert rest.object_id == extra and rest.before == {} and rest.after == arch.after
    dele = _one(ctx, "status_delete", "sd_dictionary.deleted")
    assert dele.object_id == extra and dele.after == {} and dele.before == arch.after
    # подразделения-клиенты: тот же вид объекта, свои коды
    cu_made = _one(ctx, "cu_create", "client_unit.created")
    assert (cu_made.object_type, cu_made.object_id) == ("sd_dictionary", f"client-units:{ctx.cu.pk}")
    assert cu_made.before == {} and cu_made.after == {"name": ctx.cu.name}
    cu_id = f"client-units:{ctx.cu2.pk}"
    cu_upd = _one(ctx, "cu_update", "client_unit.updated")
    assert cu_upd.object_id == cu_id and cu_upd.before == {"name": ctx.tokens["cu_name1"]} and cu_upd.after == {"name": ctx.tokens["cu_name2"]}
    for step, code in (("cu_archive", "client_unit.archived"), ("cu_restore", "client_unit.restored")):
        event = _one(ctx, step, code)
        assert event.object_id == cu_id and event.before == {} and event.after == {"name": ctx.tokens["cu_name2"]}
    cu_del = _one(ctx, "cu_delete", "client_unit.deleted")
    assert cu_del.object_id == cu_id and cu_del.before == {"name": ctx.tokens["cu_name2"]} and cu_del.after == {}
    # очереди
    mark = _one(ctx, "q_mark", "queue.marked")
    assert (mark.object_type, mark.object_id, mark.actor_id) == ("queue", str(ctx.q3.pk), ctx.admin.pk)
    assert mark.before == {} and mark.after == {"unit": ctx.q3.name, "unit_id": ctx.q3.pk}
    default = _one(ctx, "q_default", "queue.default_changed")
    assert default.object_id == str(ctx.q3.pk)
    assert default.before == {"unit": ctx.q1.unit.name, "unit_id": ctx.q1.unit_id}
    assert default.after == {"unit": ctx.q3.name, "unit_id": ctx.q3.pk}
    back = _one(ctx, "q_default_back", "queue.default_changed")
    assert back.object_id == str(ctx.q1.unit_id)
    unmark = _one(ctx, "q_unmark", "queue.unmarked")
    assert unmark.object_id == str(ctx.q3.pk) and unmark.after == {}
    assert unmark.before == {"unit": ctx.q3.name, "unit_id": ctx.q3.pk}
    # по-русски: поля и значения этих событий
    events = [e for step in ("cat_create", "cat_rename", "status_create", "status_default", "cu_update", "q_mark",
                             "q_default", "q_unmark") for e in ctx.by[step]]
    for event in events:
        for side in (event.before, event.after):
            for key, value in side.items():
                assert is_russian(audit_labels.label(key), key), key
                if key in ("dictionary", "status_kind"):
                    assert is_russian(audit_labels.text(key, value), value), (key, value)


def test_settings_change_event_has_each_changed_field_before_after(
        django_capture_on_commit_callbacks, settings, monkeypatch, protected_root):
    """FR-288: `servicedesk.settings_changed` (вид `servicedesk`, объект `"1"`) хранит каждое изменённое поле до и
    после: домены списком строк, критичность по умолчанию названием, сроки и пороги числами; очереди по умолчанию в
    событии нет."""
    ctx = _desk(django_capture_on_commit_callbacks, settings)
    _admin_part(ctx)
    event = _one(ctx, "settings", "servicedesk.settings_changed")
    assert (event.object_type, event.object_id, event.actor_id) == ("servicedesk", "1", ctx.admin.pk)
    assert event.before == ctx.settings_before and event.after == ctx.settings_after
    assert "default_queue" not in event.before and "default_queue" not in event.after
    for key in ("autoclose_days", "reopen_days", "form_hourly_limit", "retention_years", "inbound_retention_days"):
        assert isinstance(event.after[key], int) and not isinstance(event.after[key], bool), key
    assert isinstance(event.after["domains"], list) and all(isinstance(x, str) for x in event.after["domains"])


# --- 9. заявители ---------------------------------------------------------------------------------------

def test_requester_events_unit_was_became_name_and_address_only_changed(
        django_capture_on_commit_callbacks, settings, monkeypatch, protected_root):
    """FR-288, FR-289: записи заявителей — создание (отметка и подразделение), правка (подразделение «было и стало»
    названиями, очистка — пустая строка; ФИО — только `name_changed`; адреса нет), удаление (отметка), загрузка
    (имя файла, флажок, итоги; создание подразделения; удаление с причиной `загрузка таблицы`)."""
    ctx = _desk(django_capture_on_commit_callbacks, settings)
    _creates(ctx)
    _flow(ctx, monkeypatch)
    _requesters_part(ctx)
    tok = ctx.tokens
    made = _one(ctx, "create_staff", "requester.created")
    requester = model("servicedesk.Requester").objects.get(email=_addr(tok["staff_email"]))
    assert (made.object_type, made.object_id, made.actor_id) == ("requester", str(requester.pk), ctx.e1.pk)
    assert made.before == {} and made.after == {"origin": "ticket", "client_unit": ctx.cu.name}
    from_mail = _one(ctx, "create_mail", "requester.created")
    assert from_mail.actor_id is None and from_mail.after == {"origin": "ticket", "client_unit": ""}
    # подразделение заявки, выбранное исполнителем, попадает и в запись заявителя
    edit = _one(ctx, "update_unit", "requester.updated")
    assert edit.object_id == str(ctx.requester.pk) and edit.actor_id == ctx.boss.pk
    assert edit.before == {"client_unit": ""} and edit.after == {"client_unit": ctx.cu.name}
    ticket_edit = _one(ctx, "update_unit", "ticket.updated")
    assert ticket_edit.before == {"client_unit": ""} and ticket_edit.after == {"client_unit": ctx.cu.name}
    # правка записи: очистка подразделения и смена ФИО
    upd = _one(ctx, "req_update", "requester.updated")
    assert (upd.object_type, upd.object_id, upd.actor_id) == ("requester", str(ctx.requester.pk), ctx.admin.pk)
    assert upd.before == {"client_unit": ctx.cu_name} and upd.after == {"client_unit": "", "name_changed": True}
    assert tok["upd_name"] not in event_text(upd) and tok["mail_email"] not in event_text(upd)
    setting = _one(ctx, "req_set_unit", "requester.updated")
    assert setting.before == {"client_unit": ""} and setting.after == {"client_unit": ctx.cu.name}
    deleted = _one(ctx, "req_delete", "requester.deleted")
    assert (deleted.object_type, deleted.object_id, deleted.actor_id) == ("requester", str(ctx.r3.pk), ctx.admin.pk)
    assert deleted.before == {"origin": "table"} and deleted.after == {}
    # загрузка таблицей
    assert [e for e in ctx.by["import_preview"] if e.action == "requester_import.completed"] == []
    done = _one(ctx, "import_confirm", "requester_import.completed")
    assert (done.object_type, done.object_id, done.actor_id) == (
        "requester_import", str(ctx.import_item.pk), ctx.admin.pk)
    assert done.after["file_name"] == "people.csv" and done.after["delete_missing"] is True
    assert set(done.after["totals"]) == {"added", "updated", "unchanged", "errors", "deleted", "origin_changed"}
    assert done.after["totals"] == {"added": 1, "updated": 0, "unchanged": 0, "errors": 0, "deleted": 2,
                                    "origin_changed": 0}
    removed_ids = {e.object_id for e in ctx.by["import_confirm"] if e.action == "requester.deleted"}
    assert removed_ids == {str(ctx.gone.pk), str(ctx.r2.pk)}
    unit_made = [e for e in ctx.by["import_confirm"] if e.action == "client_unit.created"]
    assert [e.after for e in unit_made] == [{"name": tok["unit_new"]}]
    assert unit_made[0].actor_id == ctx.admin.pk
    gone = [e for e in ctx.by["import_confirm"] if e.action == "requester.deleted" and e.object_id == str(ctx.gone.pk)]
    assert len(gone) == 1 and gone[0].after == {"reason": "загрузка таблицы"} and gone[0].before == {"origin": "table"}
    added = [e for e in ctx.by["import_confirm"] if e.action == "requester.created"]
    assert [e.after for e in added] == [{"origin": "table", "client_unit": tok["unit_new"]}]
    assert added[0].actor_id == ctx.admin.pk
    for event in ctx.by["import_confirm"]:
        assert tok["import_email"] not in event_text(event)


def test_ticket_updated_requester_name_only_marked_changed(django_capture_on_commit_callbacks, settings, monkeypatch, protected_root):
    """FR-289: смена ФИО заявителя в заявке пишет одно `ticket.updated`: в `after` только `requester_name_changed:
    True`, в `before` ничего; значений ФИО нет. Один вызов с двумя полями — одно событие (дополнение 21); без
    изменений события нет."""
    ctx = _desk(django_capture_on_commit_callbacks, settings)
    _creates(ctx)
    _flow(ctx, monkeypatch)
    event = _one(ctx, "update_name", "ticket.updated")
    assert (event.object_type, event.object_id, event.actor_id) == (
        "ticket", str(ctx.mail_ticket.number), ctx.boss.pk)
    assert event.before == {} and event.after == {"requester_name_changed": True}
    assert ctx.tokens["new_name"] not in event_text(event) and ctx.tokens["mail_name"] not in event_text(event)
    both = _one(ctx, "update_two", "ticket.updated")
    assert both.before == {"priority": ctx.new_priority.name}
    assert both.after == {"priority": ctx.old_priority.name, "requester_name_changed": True}
    tickets = _svc("tickets")
    same = _step(ctx, "noop", lambda: tickets.update_fields(
        _fresh(ctx.mail_ticket), actor=ctx.boss, priority=_fresh(ctx.mail_ticket).priority))
    assert same == [] and _of(ctx, "noop", "ticket.updated") == []


# --- 10. отсутствие ПДн ----------------------------------------------------------------------------------

def test_no_message_reply_comment_or_transfer_text_in_any_event(
        django_capture_on_commit_callbacks, settings, monkeypatch, fake_mailbox, protected_root):
    """FR-289: ни в `before`, ни в `after`, ни на странице журнала нет текста письма, ответа, комментария, решения,
    причины передачи, темы заявки и имени вложения."""
    ctx = _everything(django_capture_on_commit_callbacks, settings, monkeypatch, fake_mailbox, protected_root)
    tok = ctx.tokens
    secrets_here = [tok["text"], tok["reply"], tok["comment"], tok["resolution"], tok["reason"], tok["subject"],
                    tok["file_name"], f"ТекстФормы", f"ТекстИсп"]
    events = slice_events()
    assert events
    for event in events:
        text = event_text(event)
        for secret in secrets_here:
            assert secret not in text, (event.action, secret)
    for kind, html in _audit_page_texts(ctx.admin).items():
        for secret in secrets_here:
            assert secret not in unescape(html), (kind, secret)


def test_no_requester_or_participant_address_or_name_in_any_event(
        django_capture_on_commit_callbacks, settings, monkeypatch, fake_mailbox, protected_root):
    """FR-289: адресов и ФИО заявителей и участников копии нет ни в событиях, ни на странице журнала (у формы
    адрес клиента — только колонка `ip`); имена сотрудников-исполнителей хранятся."""
    ctx = _everything(django_capture_on_commit_callbacks, settings, monkeypatch, fake_mailbox, protected_root)
    tok = ctx.tokens
    secrets_here = [tok["mail_email"], tok["form_email"], tok["staff_email"], tok["mail_name"], tok["form_name"],
                    tok["staff_name"], tok["new_name"], tok["part_email"], tok["part_name"], tok["upd_name"],
                    tok["import_email"], ctx.r2.full_name, ctx.r2.email, ctx.gone.email, ctx.gone.full_name]
    events = slice_events()
    for event in events:
        text = event_text(event)
        for secret in secrets_here:
            assert secret not in text, (event.action, secret)
    for kind, html in _audit_page_texts(ctx.admin).items():
        for secret in secrets_here:
            assert secret not in unescape(html), (kind, secret)
    stored = [e for e in events if e.action == "ticket.assigned"]
    assert any(e.after.get("assignee") == ctx.e1.full_name for e in stored), "имена исполнителей должны храниться"


# --- 11. адрес клиента формы -----------------------------------------------------------------------------

def test_form_ticket_created_event_has_client_ip(django_capture_on_commit_callbacks, settings):
    """FR-288: у заявки с формы адрес клиента — колонка `ip` события `ticket.created` (в `before` и `after` его
    нет)."""
    ctx = _desk(django_capture_on_commit_callbacks, settings)
    _creates(ctx)
    event = _one(ctx, "create_form", "ticket.created")
    assert event.ip == IP
    assert IP not in json.dumps([event.before, event.after])


def test_mail_ticket_created_event_has_no_client_ip(django_capture_on_commit_callbacks, settings):
    """FR-288: у заявки из письма и от исполнителя `ip` пуст (`None`)."""
    ctx = _desk(django_capture_on_commit_callbacks, settings)
    _creates(ctx)
    assert _one(ctx, "create_mail", "ticket.created").ip is None
    assert _one(ctx, "create_staff", "ticket.created").ip is None


# --- 12. фильтр журнала -----------------------------------------------------------------------------------

def test_audit_filter_has_new_object_kinds():
    """FR-288: в выпадающем списке вида объекта журнала появились все семь видов среза (проверка по кодам: у двух
    видов загрузки подпись «загрузка» общая); фильтр отбирает события нужного вида; прежние виды остались."""
    from apps.core.services import audit_labels
    from apps.core.services.audit import record

    admin = support.make_admin()
    created = {}
    for number, kind in enumerate(OBJECT_TITLES, start=1):
        object_id = {"sd_dictionary": "categories:7", "servicedesk": "1", "mailbox": "1"}.get(kind, str(number))
        created[kind] = record("ticket.updated", actor=admin, object_type=kind, object_id=object_id,
                               before={}, after={"name": "x"}, ip=IP)
    client = support.logged_in(admin, ip=IP)
    html = client.get("/audit/").content.decode()
    select = re.search(r'<select[^>]*id="id_object_type".*?</select>', html, re.S).group(0)
    options = {value: " ".join(unescape(re.sub("<[^>]+>", "", label)).split())
               for value, label in re.findall(r'<option[^>]*value="([^"]*)"[^>]*>(.*?)</option>', select, re.S)}
    for kind in OBJECT_TITLES:
        assert kind in options, kind
    for old in ("unit", "staff_import", "calendar", "user", "link", "mail", "role"):
        assert old in options, old
    for kind in OBJECT_TITLES:
        page = client.get(f"/audit/?object_type={kind}").content.decode()
        ids = {int(n) for n in re.findall(r'data-event-id="(\d+)"', page)}
        assert ids == {created[kind].pk}, kind
        assert audit_labels.object_title(kind) == OBJECT_TITLES[kind], kind


# --- 13. журнал только дописывается -------------------------------------------------------------------------

def test_audit_events_append_only_no_edit_or_delete(
        django_capture_on_commit_callbacks, settings, monkeypatch, fake_mailbox, protected_root):
    """NFR-212: события среза лежат в журнале «только дописывается»: у роли приложения нет UPDATE, DELETE и TRUNCATE;
    код `servicedesk` не правит и не удаляет журнал; ночные и порционные задания среза (автозакрытие,
    обезличивание, очистка писем, файлов и просмотров) не трогают ни одного события."""
    Event = model("core.AuditEvent")
    _everything(django_capture_on_commit_callbacks, settings, monkeypatch, fake_mailbox, protected_root)
    codes = list(SLICE_CODES)
    ids = sorted(Event.objects.filter(action__in=codes).values_list("id", flat=True))
    assert len(ids) >= len(codes)
    columns = ("id", "action", "object_type", "object_id", "before", "after", "actor_id")
    snapshot = list(Event.objects.filter(id__in=ids).order_by("id").values_list(*columns))

    with connection.cursor() as cur:
        cur.execute("SELECT has_table_privilege('crm_app', 'core_auditevent', 'UPDATE'), "
                    "has_table_privilege('crm_app', 'core_auditevent', 'DELETE'), "
                    "has_table_privilege('crm_app', 'core_auditevent', 'TRUNCATE')")
        assert cur.fetchone() == (False, False, False)
    with pytest.raises(ProgrammingError), transaction.atomic():
        Event.objects.filter(action__in=codes).update(action="tampered")
    with pytest.raises(ProgrammingError), transaction.atomic():
        with connection.cursor() as cur:
            cur.execute("DELETE FROM core_auditevent WHERE action = ANY(%s)", [codes])
    with pytest.raises(ProgrammingError), transaction.atomic():
        Event.objects.filter(action__in=codes).delete()
    assert sorted(Event.objects.filter(action__in=codes).values_list("id", flat=True)) == ids
    assert list(Event.objects.filter(id__in=ids).order_by("id").values_list(*columns)) == snapshot

    root = support.BACKEND_DIR / "apps" / "servicedesk"
    sources = [p for p in Path(root).rglob("*.py") if "migrations" not in p.parts]
    assert sources, "нет кода apps/servicedesk"
    for path in sources:
        for line in path.read_text(encoding="utf-8").splitlines():
            assert not (re.search(r"auditevent", line, re.I)
                        and re.search(r"\.delete\(|_raw_delete|truncate|\.update\(", line, re.I)), (
                f"{path}: правка журнала: {line.strip()}")

    retention, closing = _svc("retention"), _svc("closing")
    for call in (lambda: closing.autoclose_batch(), lambda: retention.anonymize_batch(),
                 lambda: retention.purge_inbound(), lambda: retention.purge_orphan_files(),
                 lambda: _svc("retention").purge_requester_previews()):
        with django_capture_on_commit_callbacks(execute=True):
            call()
    # новые события среза задания вправе написать, но прежние остаются как были
    assert list(Event.objects.filter(id__in=ids).order_by("id").values_list(*columns)) == snapshot
