"""Карточка заявки и действия над ней (CONTRACT-003, 12.4, 13.3, 13.4, 14.1, 14.2, 14.5).

Каждое представление начинается с `tickets.get_for`: невидимая и несуществующая заявка дают одно и то же 404 до любой
другой проверки (дополнение 2). Закрытая заявка: всё, кроме комментария и открытия заново, отвечает 200 с карточкой и
одним `[role=alert]` «Заявка закрыта: сначала откройте её». Отказ службы — 200 с тем же шаблоном и одним
`[role=alert][data-code]`; отказ диалога — тот же диалог (НХ: с заголовками `HX-Retarget: #dialog-root`).
Раскладка карточки (`slider` или `page`) приходит скрытым полем `layout` формы и параметром `?layout=` ссылки диалога:
по заголовкам НХ её не отличить (решение Opus волны (в), п. 3 «Особо» T-3231).
Число запросов карточки не зависит от длины ленты: лента — `replies.feed` (не больше двух запросов), вложения — один
запрос на заявку и раскладка по элементам в Python.
"""
import re

from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.core.models import StoredFile
from apps.core.views.common import flash, is_fragment, render_page

from ..audit_labels import VALUES
from ..models import (Attachment, Category, ClientUnit, Complexity, InboundMail, Priority, Status, Ticket, TicketEntry,
                      TicketParticipant)
from ..services import (access, assignment, attachments, closing, dictionaries, events, queues, replies, tickets,
                        transfer)
from ..services.errors import ServiceDeskError
from ..services.letters import short_name

LAYOUTS = ("slider", "page")
CLOSED_TEXT = "Заявка закрыта: сначала откройте её"
CONFIRM_TEXT = "Подтвердите действие"
SEND_LABELS = dict(TicketEntry.SendState.choices)
MAIL_LABELS = {"queued": "в очереди", "sent": "отправлено", "failed": "не доставлено"}
NONE_TEXT = "не задано"
_DIGITS = re.compile(r"[0-9]{1,18}")

get_user = get_user_model


# --- общие помощники ----------------------------------------------------------------------------------------

def _error(code: str, message: str) -> ServiceDeskError:
    return ServiceDeskError(code, message)


def _number(value) -> int | None:
    """Целое из строки только из цифр (до 18 знаков), иначе `None`."""
    text = (value or "").strip()
    return int(text) if _DIGITS.fullmatch(text) else None


def _layout(request) -> str:
    """Раскладка из поля `layout` или параметра `?layout=`; вне НХ и при неизвестном значении — `page`."""
    value = request.POST.get("layout") or request.GET.get("layout")
    return value if value in LAYOUTS and is_fragment(request) else "page"


def _closed(ticket) -> bool:
    return ticket.kind == Status.Kind.CLOSED


def _fragment(request, template: str, context: dict, *, status: int = 200):
    response = render(request, template, context, status=status)
    response["Vary"] = "HX-Request"
    return response


def _val(data: dict, key: str, empty: str = NONE_TEXT) -> str:
    return str(data.get(key) or "") or empty


def _event_text(entry, known_participants: set) -> str:
    """Текст события ленты по коду и `data` (CONTRACT-003, 9.3 и 14.5); ключи и коды причин наружу не выводятся."""
    code, data = entry.event, entry.data or {}
    if code == "assignee_changed":
        return f"ответственный: {_val(data, 'before', 'не назначен')} → {_val(data, 'after', 'не назначен')}"
    if code == "assignee_reconciled":
        return "ответственный снят: больше не участник очереди"
    if code == "transferred":
        text = f"передана в очередь: {_val(data, 'from')} → {_val(data, 'to')}"
        return text + (f"; причина: {data['reason_text']}" if data.get("reason_text") else "")
    if code == "queue_changed":
        text = f"очередь: {_val(data, 'from')} → {_val(data, 'to')}"
        return text + (", причина — очередь снята" if data.get("reason") == "queue_unmarked" else "")
    titles = {"category_changed": "категория", "priority_changed": "критичность",
              "complexity_changed": "сложность", "client_unit_changed": "подразделение",
              "status_changed": "статус"}
    if code in titles:
        return f"{titles[code]}: {_val(data, 'before')} → {_val(data, 'after')}"
    if code == "requester_name_changed":
        return "ФИО заявителя изменено"
    if code == "closed":
        return f"заявка закрыта: {_val(data, 'status')}; решение: {data.get('resolution', '')}"
    if code == "autoclosed":
        return f"заявка закрыта автоматически: {_val(data, 'status')}"
    if code == "reopened":
        via = VALUES["via"].get(data.get("via"), "")
        return "заявка открыта заново" + (f" ({via})" if via else "")
    if code == "continued":
        return f"продолжение — заявка #{data.get('number', '')}"
    if code == "participant_removed":
        return "участник снят" if data.get("participant_id") in known_participants else "участник (обезличено)"
    if code == "reply_not_sent":
        reason, name = data.get("reason"), data.get("name")
        if reason == "ticket_closed":
            return "ответ не отправлен: заявка закрыта"
        who = f"вложение «{name}»" if name else "вложение"
        return f"ответ не отправлен: {who} — архив с паролем" if reason == "encrypted" else (
            f"ответ не отправлен: {who} в карантине")
    if code == "mail_failed":
        return f"письмо не доставлено: {VALUES['mail_kind'].get(data.get('mail_kind'), '')}".rstrip(": ")
    if code == "attachment_rejected":
        name = data.get("name")
        return (f"вложение «{name}» не принято" if name else "вложение не принято") + ": архив с паролем"
    if code == "attachment_quarantined":
        name = data.get("name")
        return f"вложение в карантине: «{name}»" if name else "вложение в карантине"
    return "событие"


def _attachment_item(item, ticket) -> dict:
    """Принятое вложение для карточки: состояние и ссылка (только у чистого)."""
    status = item.file.status
    state = "clean" if status == StoredFile.Status.CLEAN else (
        "pending" if status == StoredFile.Status.PENDING else "quarantine")
    url = f"/tickets/{ticket.number}/files/{item.file_id}/" if state == "clean" else ""
    return {"name": item.name, "state": state, "url": url}


def _rejected_item(item) -> dict:
    return {"code": item.rejected, "name": item.name, "title": Attachment.REJECT_TITLES.get(item.rejected, "")}


def _feed(ticket, user, participants: list) -> dict:
    """Лента, вложения и раздел вложений: запросов столько же при любой длине ленты."""
    items = replies.feed(ticket)
    by_entry: dict = {}
    for row in Attachment.objects.filter(ticket=ticket).select_related("file").order_by("id"):
        by_entry.setdefault(row.entry_id, []).append(row)
    inbound_ids = {item.entry.inbound_id for item in items if item.entry.inbound_id}
    raw_gone = dict(InboundMail.objects.filter(pk__in=inbound_ids).values_list("pk", "raw_deleted"))
    clean_inbound = {pk: True for pk in raw_gone if not raw_gone[pk]}
    entry_inbound = {item.entry.pk: item.entry.inbound_id for item in items}
    for entry_id, rows in by_entry.items():
        pk = entry_inbound.get(entry_id)
        if pk in clean_inbound and any(r.rejected or r.file is None or r.file.status != StoredFile.Status.CLEAN
                                       for r in rows):
            clean_inbound[pk] = False
    known = {p["id"] for p in participants}
    open_ticket = not _closed(ticket)
    feed = []
    for item in items:
        entry = item.entry
        rows = by_entry.get(entry.pk, [])
        accepted = [_attachment_item(r, ticket) for r in rows if not r.rejected and r.file is not None]
        entry_data = {
            "id": entry.pk, "kind": entry.kind, "at": entry.at, "event": entry.event, "text": entry.text,
            "event_text": _event_text(entry, known) if entry.kind == TicketEntry.Kind.EVENT else "",
            "attachments": accepted, "rejected": [_rejected_item(r) for r in rows if r.rejected],
            "author": None, "send_state": "", "send_label": "", "mail_status": "", "mail_label": "",
            "resend": False, "source_mail": "",
        }
        if item.author_kind != "system":
            if item.author_kind == "staff":
                label = item.author_name + (" (уволен)" if item.author_dismissed else "")
            elif item.author_kind == "participant":
                label = f"участник {item.author_address}"
            else:
                label = f"заявитель {item.author_address}"
            entry_data["author"] = {"kind": item.author_kind, "label": label, "dismissed": item.author_dismissed}
        if entry.kind == TicketEntry.Kind.REPLY:
            entry_data["send_state"] = entry.send_state
            entry_data["send_label"] = SEND_LABELS.get(entry.send_state, "")
            entry_data["mail_status"] = item.mail_status
            entry_data["mail_label"] = MAIL_LABELS.get(item.mail_status, item.mail_status)
            entry_data["resend"] = open_ticket and not item.resent and entry.send_state == TicketEntry.SendState.NOT_SENT
        if entry.kind == TicketEntry.Kind.INCOMING and clean_inbound.get(entry.inbound_id):
            entry_data["source_mail"] = f"/tickets/{ticket.number}/mail/{entry.inbound_id}.eml"
        feed.append(entry_data)
    every = [_attachment_item(r, ticket) for rows in by_entry.values() for r in rows
             if not r.rejected and r.file is not None]
    every_rejected = [_rejected_item(r) for rows in by_entry.values() for r in rows if r.rejected]
    return {"feed": feed, "all_attachments": every, "all_rejected": every_rejected}


def _participants(ticket) -> list:
    rows = TicketParticipant.objects.filter(ticket=ticket).order_by("id")
    return [{"id": p.pk, "email": p.email, "name": p.name, "removed": p.removed_at is not None} for p in rows]


def _choices(kind: str, current, extra_empty: bool = False) -> list:
    """Выбор справочника: неархивные значения; текущее архивное показано, но недоступно для выбора."""
    result = [{"id": obj.pk, "name": obj.name, "selected": current is not None and obj.pk == current.pk,
               "disabled": False} for obj in dictionaries.offered(kind)]
    if current is not None and current.archived:
        result.insert(0, {"id": current.pk, "name": f"{current.name} (в архиве)", "selected": True,
                          "disabled": True})
    return result


def _link_to(user, other) -> dict | None:
    """Связанная заявка: ссылкой только если видна смотрящему, иначе текстом."""
    if other is None:
        return None
    return {"number": other.number, "visible": access.can_work(user, other)}


def _queue_name(ticket) -> str:
    for unit in queues.marked_units():
        if unit.id == ticket.queue_id:
            return unit.name
    return Ticket.objects.select_related("queue").get(pk=ticket.pk).queue.name


def _context(request, ticket, layout: str, *, alert=None, dialog=None, reply_text: str = "") -> dict:
    """Всё, что нужно разметке карточки; заявка перечитывается одним запросом со связями."""
    user = request.user
    ticket = (Ticket.objects.select_related("queue", "status", "priority", "category", "complexity", "client_unit",
                                            "source", "requester", "assignee", "closed_by", "previous")
              .get(pk=ticket.pk))
    participants = _participants(ticket)
    context = _feed(ticket, user, participants)
    open_ticket = not _closed(ticket)
    continuation = Ticket.objects.filter(previous=ticket).order_by("id").first()
    context.update({
        "ticket": ticket, "card_layout": layout, "alert": alert, "dialog": dialog, "reply_text": reply_text,
        "open": open_ticket, "participants": participants,
        "can_take": open_ticket and access.is_participant(user, ticket.queue_id) and ticket.assignee_id != user.pk,
        "closed_by_name": short_name(ticket.closed_by.full_name) if ticket.closed_by_id else "",
        "closed_by_dismissed": bool(ticket.closed_by_id) and ticket.closed_by.state == "dismissed",
        "assignee_dismissed": bool(ticket.assignee_id) and ticket.assignee.state == "dismissed",
        "previous_link": _link_to(user, ticket.previous), "continuation_link": _link_to(user, continuation),
        "priorities": _choices("priority", ticket.priority), "complexities": _choices("complexity", ticket.complexity),
        "client_units": _choices("client_unit", ticket.client_unit),
        "categories": _choices("category", ticket.category),
        "statuses": [{"id": s.pk, "name": s.name, "selected": s.pk == ticket.status_id}
                     for s in dictionaries.manual_statuses()] if open_ticket else [],
        "consent": ticket.consent_at,
    })
    return context


def _render_card(request, ticket, layout: str, *, alert=None, dialog=None, reply_text: str = "", panel=False,
                 headers=None):
    """Карточка: НХ — одна карточка (или слайдер целиком при первом открытии), обычный запрос — страница."""
    context = _context(request, ticket, layout, alert=alert, dialog=dialog, reply_text=reply_text)
    if is_fragment(request):
        response = _fragment(request, "servicedesk/card/_slider.html" if panel else "servicedesk/card/_card.html",
                             context)
    else:
        response = render_page(request, "servicedesk/card/page.html", context)
    for name, value in (headers or {}).items():
        response[name] = value
    return response


def _closed_refusal(request, ticket, layout: str):
    """200 с карточкой и одним алертом `ticket_closed`; НХ-ответ подменяет саму карточку, откуда бы ни пришёл запрос."""
    headers = {"HX-Retarget": "[data-ticket-card]", "HX-Reswap": "outerHTML"} if is_fragment(request) else None
    return _render_card(request, ticket, layout, alert={"code": "ticket_closed", "text": CLOSED_TEXT}, headers=headers)


def _prepare(request, number, *, closed_ok: bool = False):
    """`get_for` и закрытость: (заявка, раскладка, готовый ответ-отказ или `None`)."""
    ticket = tickets.get_for(request.user, number)
    layout = _layout(request)
    if not closed_ok and _closed(ticket):
        return ticket, layout, _closed_refusal(request, ticket, layout)
    return ticket, layout, None


def _refuse(request, ticket, layout: str, error: ServiceDeskError, **context):
    """Отказ службы действия карточки: 200, карточка с одним алертом `[data-code]`; база не меняется."""
    return _render_card(request, ticket, layout, alert={"code": error.code, "text": error.message}, **context)


def _dialog_context(request, ticket, layout: str, name: str, *, error=None, **extra) -> dict:
    form = {"layout": layout, **extra}
    return {"name": name, "ticket": ticket, "form": form, "error": error}


def _dialog_response(request, ticket, layout: str, name: str, *, error=None, **extra):
    """Диалог: НХ — только диалог (в `#dialog-root`), обычный запрос — страница карточки с диалогом."""
    if error is not None and error.code == "ticket_closed":
        return _closed_refusal(request, ticket, layout)
    dialog = _dialog_context(request, ticket, layout, name, error=error, **extra)
    dialog.update(_dialog_lists(ticket, name))
    if is_fragment(request):
        response = _fragment(request, "servicedesk/card/_dialog.html", {"dialog": dialog})
        response["HX-Retarget"] = "#dialog-root"
        response["HX-Reswap"] = "innerHTML"
        return response
    return _render_card(request, ticket, "page", dialog=dialog)


def _dialog_lists(ticket, name: str) -> dict:
    if name == "ticket-transfer":
        return {"queues": transfer.target_queues(ticket)}
    if name == "ticket-close":
        return {"statuses": dictionaries.closing_statuses()}
    return {}


def _done(request, ticket, layout: str):
    """Успех действия: НХ — карточка, обычный запрос — переход на карточку."""
    if is_fragment(request):
        return _render_card(request, ticket, layout)
    return redirect(f"/tickets/{ticket.number}/")


def _gone(request, ticket, text: str):
    """Заявка перестала быть видна актёру: переход на список (нет пункта меню — на главную) с сообщением."""
    target = "/tickets/" if access.menu_visible(request.user) else "/"
    if text:
        flash(request, text)
    if is_fragment(request):
        response = HttpResponse(status=200)
        response["HX-Redirect"] = target
        return response
    return redirect(target)


def _after(request, ticket, layout: str, moved_text: str | None):
    """Результат действия, после которого заявка могла стать невидимой (`access.can_work` на том же объекте).

    `moved_text=None` — видимость не проверяется; пустая строка — проверяется, сообщения нет (назначение).
    """
    if moved_text is not None and not access.can_work(request.user, ticket):
        text = moved_text.format(number=ticket.number, queue=_queue_name(ticket)) if moved_text else ""
        return _gone(request, ticket, text)
    return _done(request, ticket, layout)


def _post_guard(view):
    """Вход обязателен, метод — только POST."""
    return login_required(require_http_methods(["POST"])(view))


# --- карточка -----------------------------------------------------------------------------------------------

@login_required
@require_http_methods(["GET"])
def ticket_card(request, number):
    """Карточка: НХ — слайдер, прямой адрес — страница; нет заявки или она не видна — 404."""
    ticket = tickets.get_for(request.user, number)
    layout = "slider" if is_fragment(request) else "page"
    events.object_viewed(request.user, ticket)
    return _render_card(request, ticket, layout, panel=True)


@_post_guard
def ticket_take(request, number):
    """«Взять себе»: `assignment.take`."""
    ticket, layout, refused = _prepare(request, number)
    if refused:
        return refused
    try:
        assignment.take(ticket, actor=request.user, ip=request.client_ip)
    except ServiceDeskError as error:
        return _refuse(request, ticket, layout, error)
    return _done(request, ticket, layout)


@login_required
@require_http_methods(["GET"])
def ticket_assignees(request, number):
    """Подсказка ответственных: кандидаты по началу имени (пустой запрос — без кандидатов)."""
    ticket, layout, refused = _prepare(request, number)
    if refused:
        return refused
    prefix = (request.GET.get("q") or "").strip()
    people = access.suggest_assignees(ticket.queue_id, prefix) if prefix else []
    return _fragment(request, "servicedesk/card/_candidates.html", {"people": people})


@_post_guard
def ticket_assign(request, number):
    """Назначить ответственного (`assignee` — номер сотрудника) или снять (пустое значение)."""
    ticket, layout, refused = _prepare(request, number)
    if refused:
        return refused
    raw = request.POST.get("assignee")
    try:
        if raw is not None and not raw.strip():
            assignment.unassign(ticket, actor=request.user, ip=request.client_ip)
        else:
            number_ = _number(raw)
            user = get_user().objects.filter(pk=number_).first() if number_ is not None else None
            if user is None:
                raise _error("not_participant", "Ответственным может быть только участник очереди заявки")
            assignment.assign(ticket, user, actor=request.user, ip=request.client_ip)
    except ServiceDeskError as error:
        return _refuse(request, ticket, layout, error)
    return _after(request, ticket, layout, "")


@login_required
@require_http_methods(["GET", "POST"])
def ticket_transfer(request, number):
    """Передача в другую очередь: GET — диалог, POST — `transfer.transfer`."""
    ticket, layout, refused = _prepare(request, number)
    if refused:
        return refused
    if request.method == "GET":
        return _dialog_response(request, ticket, layout, "ticket-transfer", queue="", reason="")
    queue_raw = request.POST.get("queue", "")
    reason = request.POST.get("reason", "")
    try:
        queue_id = _number(queue_raw)
        if queue_id is None and queue_raw.strip():
            queue_id = -1   # не число: служба ответит `not_queue`
        result = transfer.transfer(ticket, queue_id, reason=reason, actor=request.user, ip=request.client_ip)
    except ServiceDeskError as error:
        return _dialog_response(request, ticket, layout, "ticket-transfer", error=error, queue=queue_raw,
                                reason=reason)
    if not result.visible_after:
        return _gone(request, ticket, f"Заявка #{ticket.number} передана в очередь «{_queue_name(ticket)}»")
    return _done(request, ticket, layout)


@_post_guard
def ticket_category(request, number):
    """Смена категории; очередь другая и подтверждения нет — диалог `ticket-category`."""
    ticket, layout, refused = _prepare(request, number)
    if refused:
        return refused
    confirmed = request.POST.get("confirm") == "1"
    category_id = _number(request.POST.get("category"))
    category = Category.objects.filter(pk=category_id).first() if category_id is not None else None
    try:
        if category is None:
            raise _error("archived_value", "Значение в архиве: выберите другое")
        result = transfer.change_category(ticket, category, confirmed=confirmed, actor=request.user,
                                          ip=request.client_ip)
    except ServiceDeskError as error:
        if confirmed:
            return _dialog_response(request, ticket, layout, "ticket-category", error=error,
                                    category=category_id or "", queue_name="")
        return _refuse(request, ticket, layout, error)
    if result.needs_confirmation:
        names = {unit.id: unit.name for unit in queues.marked_units()}
        return _dialog_response(request, ticket, layout, "ticket-category", category=category.pk,
                                queue_name=names.get(result.new_queue_id, ""))
    return _after(request, ticket, layout, "Заявка #{number} передана в очередь «{queue}»"
                  if result.queue_changed else None)


def _object(model, raw):
    """Объект справочника (с архивными) по номеру или «неизвестное значение»: `archived_value`."""
    number_ = _number(raw)
    found = model.objects.filter(pk=number_).first() if number_ is not None else None
    if found is None:
        raise _error("archived_value", "Значение в архиве: выберите другое")
    return found


@_post_guard
def ticket_fields(request, number):
    """Правка критичности, сложности, подразделения и ФИО заявителя: меняются только поля, чьи имена пришли в теле."""
    ticket, layout, refused = _prepare(request, number)
    if refused:
        return refused
    post = request.POST
    arguments = {}
    try:
        priority = Priority.objects.filter(pk=_number(post.get("priority"))).first() if "priority" in post else None
        if priority is not None:   # пустой и неизвестный — поле игнорируется (правило 12)
            arguments["priority"] = priority
        if "complexity" in post:
            arguments["complexity"] = _object(Complexity, post["complexity"]) if post["complexity"].strip() else None
        if "client_unit" in post:
            raw = post["client_unit"]
            arguments["client_unit_id"] = _object(ClientUnit, raw).pk if raw.strip() else None
        if "requester_name" in post:
            arguments["requester_name"] = post["requester_name"]
        tickets.update_fields(ticket, actor=request.user, ip=request.client_ip,
                              save_name_to_record=bool(post.get("save_to_record")), **arguments)
    except ServiceDeskError as error:
        return _refuse(request, ticket, layout, error)
    return _done(request, ticket, layout)


@_post_guard
def ticket_status(request, number):
    """Ручная смена статуса: `tickets.set_status_manual`."""
    ticket, layout, refused = _prepare(request, number)
    if refused:
        return refused
    number_ = _number(request.POST.get("status"))
    status = Status.objects.filter(pk=number_).first() if number_ is not None else None
    try:
        if status is None:
            raise _error("bad_status", "Этот статус нельзя выбрать здесь")
        tickets.set_status_manual(ticket, status, actor=request.user, ip=request.client_ip)
    except ServiceDeskError as error:
        return _refuse(request, ticket, layout, error)
    return _done(request, ticket, layout)


@_post_guard
def ticket_reply(request, number):
    """Ответ заявителю: текст, флажок «ждём ответа», файлы."""
    ticket, layout, refused = _prepare(request, number)
    if refused:
        return refused
    text = request.POST.get("text", "")
    try:
        parts = [attachments.from_upload(item) for item in request.FILES.getlist("files")]
        replies.reply(ticket, text=text, parts=parts, wait_flag=bool(request.POST.get("wait")),
                      actor=request.user, ip=request.client_ip)
    except ServiceDeskError as error:
        return _refuse(request, ticket, layout, error, reply_text=text)
    return _done(request, ticket, layout)


@_post_guard
def ticket_resend(request, number, entry_id):
    """«Отправить заново без заражённых вложений»: элемент — этой заявки, иначе 404."""
    ticket, layout, refused = _prepare(request, number)
    if refused:
        return refused
    entry = TicketEntry.objects.filter(pk=entry_id, ticket=ticket).first()
    if entry is None:
        raise Http404
    try:
        replies.resend(entry, actor=request.user, ip=request.client_ip)
    except ServiceDeskError as error:
        return _refuse(request, ticket, layout, error)
    return _done(request, ticket, layout)


@_post_guard
def ticket_comment(request, number):
    """Внутренний комментарий: работает и на закрытой заявке."""
    ticket, layout, refused = _prepare(request, number, closed_ok=True)
    try:
        replies.comment(ticket, text=request.POST.get("text", ""), actor=request.user, ip=request.client_ip)
    except ServiceDeskError as error:
        return _refuse(request, ticket, layout, error)
    return _done(request, ticket, layout)


@login_required
@require_http_methods(["GET", "POST"])
def ticket_close(request, number):
    """Закрытие: GET — диалог, POST — `closing.close`."""
    ticket, layout, refused = _prepare(request, number)
    if refused:
        return refused
    if request.method == "GET":
        return _dialog_response(request, ticket, layout, "ticket-close", status="", resolution="")
    status_raw = request.POST.get("status", "")
    resolution = request.POST.get("resolution", "")
    number_ = _number(status_raw)
    status = Status.objects.filter(pk=number_).first() if number_ is not None else None
    try:
        if status is None:
            raise _error("bad_status", "Этот статус нельзя выбрать здесь")
        closing.close(ticket, status, resolution, actor=request.user, ip=request.client_ip)
    except ServiceDeskError as error:
        return _dialog_response(request, ticket, layout, "ticket-close", error=error, status=status_raw,
                                resolution=resolution)
    return _done(request, ticket, layout)


@_post_guard
def ticket_reopen(request, number):
    """«Открыть заново»: заявка закрыта; после открытия могла стать невидимой (дополнение 27 (г))."""
    ticket, layout, refused = _prepare(request, number, closed_ok=True)
    try:
        closing.reopen(ticket, actor=request.user, ip=request.client_ip, via="manual")
    except ServiceDeskError as error:
        return _refuse(request, ticket, layout, error)
    return _after(request, ticket, layout, "Заявка #{number} открыта заново и передана в очередь «{queue}»")


@login_required
@require_http_methods(["GET", "POST"])
def participant_remove(request, number, participant_id):
    """Снятие участника: GET — диалог, POST с `confirm=1` — `tickets.remove_participant`; чужой участник — 404."""
    ticket, layout, refused = _prepare(request, number)
    if refused:
        return refused
    if request.method == "GET":
        if not TicketParticipant.objects.filter(pk=participant_id, ticket=ticket).exists():
            raise Http404
        return _dialog_response(request, ticket, layout, "participant-remove", participant=participant_id)
    try:
        if request.POST.get("confirm") != "1":
            if not TicketParticipant.objects.filter(pk=participant_id, ticket=ticket).exists():
                raise Http404
            raise _error("confirm_required", CONFIRM_TEXT)
        tickets.remove_participant(ticket, participant_id, actor=request.user, ip=request.client_ip)
    except TicketParticipant.DoesNotExist:
        raise Http404
    except ServiceDeskError as error:
        return _dialog_response(request, ticket, layout, "participant-remove", error=error,
                                participant=participant_id)
    return _done(request, ticket, layout)
