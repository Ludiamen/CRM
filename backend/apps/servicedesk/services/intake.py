"""Публичный интерфейс сервис-деска: разбор входящего письма (PLAN-003, «Где живёт код»; CONTRACT-003, 6.16 и 7.2).

`process` — одна транзакция под блокировкой строки письма: шаги из словаря `STEPS` идут по порядку, ошибка любого шага
откатывает разбор, затем отдельной транзакцией строка получает `status="error"`, итог «ошибка разбора» и шаг с классом
исключения (текста исключения там нет, FR-289), и исходное исключение поднимается наружу (повтор делает RQ).

Службы `tickets`, `closing`, `attachments`, `queues` подключаются внутри функций: `queues` сама зовёт `intake.enqueue`,
`tickets` зовёт `queues` — на уровне модуля вышел бы цикл импорта.
"""
import pathlib
from email.utils import parseaddr

import django_rq
from django.conf import settings as dj_settings
from django.db import transaction
from django.utils import timezone

from ..models import InboundMail, Ticket, TicketParticipant
from . import mail_parse
from . import settings as sd_settings

TASK = "apps.servicedesk.tasks.process_inbound"
QUEUE = "inbox"
JOB_TIMEOUT = 300
RETRY_INTERVALS = [60, 300, 900, 3600, 10800]

Outcome = InboundMail.Outcome


class _Run:
    """Состояние одного разбора: письмо, его байты и то, что нашли шаги."""

    def __init__(self, inbound):
        self.inbound = inbound
        self.raw = b""
        self.parsed = None
        self.rejected = None      # итог проверок FR-214 или None
        self.waiting = False      # нет очереди по умолчанию
        self.linked = None        # заявка, с которой связано письмо
        self.ticket = None
        self.outcome = ""
        self.entry = None


def enqueue(inbound_id) -> None:
    """Ставит разбор письма в очередь `inbox`: внутри транзакции — после фиксации, вне её — сразу.

    Функция задания названа строкой пути: её определяет `apps.servicedesk.tasks`, а у `intake` импорта нет.
    """
    from rq import Retry

    def put():
        django_rq.get_queue(QUEUE).enqueue(TASK, inbound_id, job_timeout=JOB_TIMEOUT,
                                           retry=Retry(max=len(RETRY_INTERVALS), interval=RETRY_INTERVALS))

    transaction.on_commit(put)


def has_job(inbound_id) -> bool:
    """В очереди `inbox`, среди ждущих повтора или выполняемых есть задание разбора этого письма."""
    from rq.job import Job

    queue = django_rq.get_queue(QUEUE)
    for job in queue.jobs:
        if job.func_name == TASK and job.args and job.args[0] == inbound_id:
            return True
    for registry in (queue.scheduled_job_registry, queue.started_job_registry):
        for job_id in registry.get_job_ids():
            job = Job.fetch(job_id, connection=queue.connection)
            if job.func_name == TASK and job.args and job.args[0] == inbound_id:
                return True
    return False


def _domain(address: str) -> str:
    return address.rpartition("@")[2]


def classify(message, sender):
    """Первая сработавшая проверка FR-214: `rejected_self`, `auto`, `rejected_domain` или `None`.

    `message` — `ParsedMail` (признак автоматического письма он уже несёт); `sender` — адрес строчными, пустой — нет адреса.
    """
    own = {sd_settings.mailbox_address().strip().lower(),
           parseaddr(dj_settings.DEFAULT_FROM_EMAIL or "")[1].strip().lower()} - {""}
    if sender and sender in own:
        return Outcome.REJECTED_SELF.value
    if message.automatic:
        return Outcome.AUTO.value
    if not sender or not sd_settings.accepts_domain(_domain(sender)):
        return Outcome.REJECTED_DOMAIN.value
    return None


def _allowed(ticket, sender: str) -> bool:
    """Отправитель — заявитель заявки или неснятый участник."""
    if ticket.requester_email.lower() == sender:
        return True
    return TicketParticipant.objects.filter(ticket=ticket, email__iexact=sender, removed_at__isnull=True).exists()


def find_ticket(parsed):
    """Заявка письма: по `[#N]` темы (главнее заголовков), иначе по `In-Reply-To`/`References`; чужому отправителю — `None`."""
    from apps.integrations.mail.models import MailMessage

    ticket = None
    if parsed.subject_number is not None:
        ticket = Ticket.objects.filter(number=parsed.subject_number).first()
    else:
        for message_id in parsed.link_ids:
            mail = (MailMessage.objects.filter(message_id=message_id, related_ref__startswith="ticket:")
                    .order_by("-id").first())
            if mail is not None:
                number = mail.related_ref.partition(":")[2]
                ticket = Ticket.objects.filter(pk=int(number)).first() if number.isdigit() else None
            else:
                inbound = (InboundMail.objects.filter(message_id=message_id, ticket__isnull=False)
                           .select_related("ticket").order_by("-id").first())
                ticket = inbound.ticket if inbound is not None else None
            if ticket is not None:
                break
    if ticket is None or not _allowed(ticket, parsed.sender):
        return None
    return ticket


def corporate_cc(parsed, requester_email):
    """Пары (адрес, имя) из копии: домены из списка, без ящика, адреса отправки портала, заявителя и повторов."""
    skip = {sd_settings.mailbox_address().strip().lower(),
            parseaddr(dj_settings.DEFAULT_FROM_EMAIL or "")[1].strip().lower(),
            (requester_email or "").strip().lower()} - {""}
    pairs = {}
    for address, name in parsed.cc:
        address = address.strip().lower()
        if address in skip:
            continue
        if not sd_settings.accepts_domain(_domain(address)):
            continue
        if address not in pairs or (not pairs[address] and name):
            pairs[address] = name
    return list(pairs.items())


def add_participants(ticket, pairs) -> list:
    """Участники заявки из пар (адрес, имя); существующий не меняется, снятый не восстанавливается."""
    result = []
    for address, name in pairs:
        row, _created = TicketParticipant.objects.get_or_create(
            ticket=ticket, email=address.strip().lower(), defaults={"name": name})
        result.append(row)
    return result


# --- шаги разбора; `process` зовёт их через `STEPS` ---------------------------------------------------

def _step_parse(run):
    """Читает файл письма и разбирает его."""
    path = pathlib.Path(dj_settings.PROTECTED_ROOT) / "inbound" / f"{run.inbound.pk}.eml"
    run.raw = path.read_bytes()
    run.parsed = mail_parse.parse(run.raw)


def _step_checks(run):
    """Проверки FR-214; очередь по умолчанию проверяет сам `process` сразу после этого шага."""
    run.rejected = classify(run.parsed, run.parsed.sender)


def _step_link(run):
    """Связь письма с заявкой."""
    run.linked = find_ticket(run.parsed)


def _step_ticket(run):
    """Новая заявка, дописывание в открытую или открытие закрытой заново (FR-214, FR-251)."""
    from . import closing, tickets

    parsed, inbound, linked = run.parsed, run.inbound, run.linked
    at = inbound.received_at
    if linked is not None and linked.kind != "closed":
        run.entry = tickets.add_incoming(
            linked, author_email=parsed.sender, author_name=parsed.sender_name, text=parsed.text, at=at,
            inbound_id=inbound.pk, cc=corporate_cc(parsed, linked.requester_email))
        run.ticket, run.outcome = linked, Outcome.APPENDED.value
    elif linked is not None and closing.within_reopen_term(linked):
        closing.reopen(linked, actor=None, via="mail")
        linked.refresh_from_db()
        run.entry = tickets.add_incoming(
            linked, author_email=parsed.sender, author_name=parsed.sender_name, text=parsed.text, at=at,
            inbound_id=inbound.pk, cc=corporate_cc(parsed, linked.requester_email))
        run.ticket, run.outcome = linked, Outcome.REOPENED.value
    else:
        created = tickets.create(
            channel=tickets.MAIL, subject=parsed.subject, text=parsed.text, requester_email=parsed.sender,
            requester_name=parsed.sender_name, inbound_id=inbound.pk, at=at, previous=linked)
        add_participants(created.ticket, corporate_cc(parsed, parsed.sender))
        run.ticket, run.entry, run.outcome = created.ticket, created.entry, Outcome.CREATED.value


def _step_attachments(run):
    """Вложения письма — в той же транзакции; принятые уйдут на проверку после фиксации."""
    from . import attachments

    if run.entry is not None:
        attachments.accept(run.entry, run.parsed.parts, strict=False, mail_size=len(run.raw))


def _step_finish(run):
    """Итог письма: связь с заявкой, состояние и время разбора."""
    inbound = run.inbound
    if run.waiting:
        inbound.status, inbound.outcome = InboundMail.Status.WAITING_SETUP, Outcome.WAITING_SETUP.value
        inbound.save(update_fields=["status", "outcome"])
        return
    inbound.status = InboundMail.Status.PROCESSED
    inbound.outcome = run.rejected or run.outcome
    inbound.ticket = run.ticket
    inbound.processed_at = timezone.now()
    inbound.last_error = ""
    inbound.save(update_fields=["status", "outcome", "ticket", "processed_at", "last_error"])


STEPS = {
    "parse": _step_parse,
    "checks": _step_checks,
    "link": _step_link,
    "ticket": _step_ticket,
    "attachments": _step_attachments,
    "finish": _step_finish,
}


def _run_steps(run, current):
    """Идёт по шагам; `current` — список с именем шага, на котором сейчас работа (для `last_error`)."""
    from . import queues

    def call(name):
        current[0] = name
        STEPS[name](run)

    call("parse")
    call("checks")
    if run.rejected is None and queues.default_unit_id() is None:
        run.waiting = True
    if run.rejected is None and not run.waiting:
        call("link")
        call("ticket")
        call("attachments")
    call("finish")


def process(inbound_id):
    """Разбирает письмо; возвращает итог (`InboundMail.Outcome`) или `None`, если разбирать нечего."""
    current = ["parse"]
    try:
        with transaction.atomic():
            inbound = InboundMail.objects.select_for_update().filter(pk=inbound_id).first()
            if inbound is None or inbound.raw_deleted or inbound.status == InboundMail.Status.PROCESSED:
                return None
            run = _Run(inbound)
            _run_steps(run, current)
            return inbound.outcome
    except Exception as exc:
        with transaction.atomic():
            row = InboundMail.objects.select_for_update().filter(pk=inbound_id).first()
            if row is not None:
                row.status = InboundMail.Status.ERROR
                row.outcome = Outcome.PARSE_ERROR.value
                row.attempts += 1
                row.last_error = f"{current[0]}: {type(exc).__name__}"
                row.save(update_fields=["status", "outcome", "attempts", "last_error"])
        raise
