"""Создание личного диалога, поиск людей и страница «Написать» (срез 008, T-8203).

CONTRACT-008 § 10.2 (адреса, поля и ответы), 12.1 (`[data-messenger-page="write"]`), 12.6
(`[data-person-id]`); PLAN-008 «Виды чатов и создание», «Список чатов и порядок», «Написать из
карточки сотрудника». Личный диалог один на пару — `chats.personal`; с уволенным не создаётся,
существующий остаётся в списке и читается (FR-645). `GET /messenger/?to=<id>` ничего не пишет в
базу: диалог появляется с первым сообщением, пустых чатов не остаётся. Поиск людей — до 20
действующих сотрудников с подразделением, уволенных в выдаче нет.

Первое сообщение со страницы «Написать» приходит в `POST /messenger/chats/` полем `text` (форма
`_form.html`); саму отправку делает `services.messages.send` (T-8209). Групповой чат, состав,
выход и удаление — T-8204.
"""
from django.apps import apps
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db.models import CharField, Value
from django.db.models.functions import Lower, Replace
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_GET, require_POST

from apps.core.models import User, UserState
from apps.core.services import permissions
from apps.core.views.common import is_fragment, render_page
from apps.messenger.models import Chat
from apps.messenger.services import chats, department, members, read, unread
from apps.messenger.services.errors import MessengerError

PEOPLE_LIMIT = 20
# Кому мессенджер закрыт: приглашённый ещё не сотрудник, уволенному портал закрыт (FR-643).
HIDDEN_STATES = (UserState.DISMISSED, UserState.INVITED)


def _fold(expression):
    """Сравнение ФИО без различия регистра и «ё/е» — как подсказки ленты (`feed.views.pickers`)."""
    return Replace(Lower(expression), Value("ё"), Value("е"), output_field=CharField())


def _person(value):
    """Сотрудник по номеру из формы или строки запроса; нет/не число — `None` (страница без адресата)."""
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    if number <= 0:
        return None
    return User.objects.filter(pk=number).first()


def _write_context(person=None, *, errors=None, text: str = "") -> dict:
    """Контекст страницы «Написать»: адресат, ошибки полей (10.1) и сохранённый ввод."""
    return {"mode": "write", "addressee": person, "errors": dict(errors or {}), "form_text": text}


@login_required
@require_GET
def write(request):
    """`GET /messenger/?to=<id>` — поле ввода с адресатом; в базу не пишет (FR-645).

    Несуществующий и уволенный адресат — та же страница без адресата (10.2). Без `to` страница
    открывается списком чатов (список — T-8207).
    """
    raw = request.GET.get("to")
    person = _person(raw)
    if person is not None and person.state in HIDDEN_STATES:
        person = None
    if raw is None:
        return render_page(request, "messenger/page.html", {"mode": "list", "errors": {}})
    return render_page(request, "messenger/page.html", _write_context(person))


@login_required
@require_POST
def create(request):
    """`POST /messenger/chats/` — личный диалог по `kind=personal&user=<id>` (FR-645).

    Диалог пары создаёт `chats.personal` (второй строки не появляется). Несуществующий адресат —
    404, уволенный — 200 с причиной у поля `user` (10.1, 10.2). Поле `text` приходит со страницы
    «Написать»: пустое не создаёт пустого чата, непустое уходит в `services.messages.send`.
    """
    kind = (request.POST.get("kind") or "personal").strip()
    if kind == "group":
        return _create_group(request)
    if kind != "personal":
        raise Http404

    text = request.POST.get("text")
    person = _person(request.POST.get("user"))
    if person is None:
        raise Http404
    if text is not None and not text.strip():
        error = MessengerError("empty_text", field="text")
        return render_page(request, "messenger/page.html",
                           _write_context(person, errors={error.field: error}, text=text))

    try:
        chat = chats.personal(request.user, person)
    except MessengerError as exc:
        return render_page(request, "messenger/page.html",
                           _write_context(person, errors={exc.field or "user": exc}, text=text or ""))

    if text is not None and text.strip():
        from apps.messenger.services import messages

        try:
            messages.send(chat, request.user, text)
        except MessengerError as exc:
            return render_page(request, "messenger/page.html",
                               _write_context(person, errors={exc.field or "text": exc}, text=text))
    return redirect(f"/messenger/chats/{chat.pk}/")


def _create_group(request):
    """Групповой чат: название 1–200 после среза, участники — действующие, создатель входит сам (FR-646)."""
    try:
        chat = chats.create_group(request.user, request.POST.get("title", ""),
                                  request.POST.getlist("members"))
    except MessengerError as exc:
        field = exc.field or "title"
        return render_page(request, "messenger/page.html",
                           {"mode": "list", "errors": {field: exc}, "form_text": ""})
    return redirect(f"/messenger/chats/{chat.pk}/")


@login_required
@require_POST
def members_change(request, chat_id: int):
    """`POST /messenger/chats/<id>/members/` — `add` и `remove`; ведёт создатель, пока в чате (FR-646)."""
    try:
        chat = members.get_chat(request.user, chat_id)
    except Http404:
        # Создатель после выхода чат уже не видит, но состав заморожен: ему 403, а не 404 (FR-646, 10.2).
        chat = Chat.objects.filter(pk=chat_id, kind=Chat.Kind.GROUP).first()
        if chat is None:
            raise
        if chat.created_by_id == request.user.pk:
            raise PermissionDenied
        raise
    try:
        if request.POST.getlist("add"):
            chats.add_members(chat, request.user, request.POST.getlist("add"))
        if request.POST.getlist("remove"):
            chats.remove_members(chat, request.user, request.POST.getlist("remove"))
    except MessengerError as exc:
        field = exc.field or "members"
        return render_page(request, "messenger/page.html",
                           {"mode": "list", "errors": {field: exc}, "form_text": ""})
    return redirect(f"/messenger/chats/{chat.pk}/")


@login_required
@require_POST
def leave(request, chat_id: int):
    """`POST /messenger/chats/<id>/leave/` — выход с `confirm=1`; последний участник удаляет чат (FR-647)."""
    chat = members.get_chat(request.user, chat_id)
    if chat.kind != chats.Chat.Kind.GROUP:
        raise PermissionDenied
    if chats.remaining_members(chat) == 1:
        if request.POST.get("confirm") != "1":
            return _confirm_page(request, chat, "leave")
        chats.delete(chat, request.user)
    else:
        chats.leave(chat, request.user)
    return redirect("/messenger/")


@login_required
@require_POST
def delete(request, chat_id: int):
    """`POST /messenger/chats/<id>/delete/` — создатель группового чата или администратор портала для отдела.

    Групповой чат удаляет создатель-участник (FR-648), чат отдела — `settings.portal` с подтверждением
    (FR-672); невидимый чужой чат — 404, действие без права — 403 (10.1). «Общий чат» не удаляется.
    """
    try:
        chat = members.get_chat(request.user, chat_id)
    except Http404:
        # Администратор портала не входит в состав чата отдела, но удаляет его со страницы настроек.
        if not permissions.has_permission(request.user, "settings.portal"):
            raise
        chat = Chat.objects.filter(pk=chat_id, kind=Chat.Kind.DEPARTMENT).first()
        if chat is None:
            raise

    if chat.kind == Chat.Kind.DEPARTMENT:
        if not permissions.has_permission(request.user, "settings.portal"):
            raise PermissionDenied
        if request.POST.get("confirm") != "1":
            return _confirm_page(request, chat, "delete")
        department.delete(chat, request.user)
        return redirect("/messenger/")

    if chat.kind != chats.Chat.Kind.GROUP:
        raise PermissionDenied
    if chat.created_by_id != request.user.pk or not members.is_member(request.user, chat):
        raise PermissionDenied
    if request.POST.get("confirm") != "1":
        return _confirm_page(request, chat, "delete")
    chats.delete(chat, request.user)
    return redirect("/messenger/")


@login_required
@require_POST
def mark_read(request, chat_id: int):
    """`POST /messenger/chats/<id>/read/` — отметка прочтения; HTMX получает OOB-узлы числа чата, меню и строки.

    `at` неверный или отсутствующий читается как теперь, будущий обрезается (FR-659, 10.1). Обычный POST — 302 в
    беседу; после отметки — `object.viewed` для уведомлений чата (FR-666).
    """
    chat = members.get_chat(request.user, chat_id)
    read.mark(chat, request.user, read.parse_at(request.POST.get("at")))
    if not is_fragment(request):
        return redirect(f"/messenger/chats/{chat.pk}/")
    last_own = read.last_own(chat, request.user)
    readers, audience = read.line(chat, last_own)
    return render_page(request, "messenger/_read_answer.html", {
        "chat": chat, "chat_count": unread.counts(request.user).get(chat.pk, 0),
        "total": unread.total(request.user), "readers": readers, "audience": audience,
        "line_message": last_own})


def _confirm_page(request, chat, action: str):
    """Второй шаг подтверждения `[data-messenger-confirm]` (CONTRACT-008, 12.6)."""
    return render_page(request, "messenger/_confirm.html",
                       {"action": f"/messenger/chats/{chat.pk}/{action}/"})


@login_required
@require_GET
def people(request):
    """`GET /messenger/people/?q=` — до 20 действующих сотрудников с действием «Написать» (FR-645).

    Пустой запрос — подсказка «начните вводить имя», уволенные и приглашённые в выдаче не
    появляются. Строка несёт `[data-person-id]` и подразделение (10.2, 12.6).
    """
    query = (request.GET.get("q") or "").strip()
    rows = _people_rows(query) if query else []
    return render_page(request, "messenger/_people.html", {"q": query, "rows": rows})


def _people_rows(query: str) -> list[dict]:
    """До 20 сотрудников по ФИО одним запросом; подразделения — `org.services.structure`."""
    folded = query.lower().replace("ё", "е")
    found = (User.objects.exclude(state__in=HIDDEN_STATES)
             .annotate(_folded_name=_fold("full_name"))
             .filter(_folded_name__contains=folded)
             .order_by("_folded_name", "pk")[:PEOPLE_LIMIT])
    structure = None
    if apps.is_installed("apps.org"):
        from apps.org.services import structure as org_structure

        structure = org_structure
    rows = []
    for person in found:
        units = structure.units_of(person) if structure is not None else []
        rows.append({"person": person, "unit": ", ".join(unit.name for unit in units)})
    return rows