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
from django.db.models import CharField, Value
from django.db.models.functions import Lower, Replace
from django.http import Http404
from django.shortcuts import redirect
from django.views.decorators.http import require_GET, require_POST

from apps.core.models import User, UserState
from apps.core.views.common import render_page
from apps.messenger.services import chats
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
    if kind != "personal":
        # Групповой чат — T-8204; до неё адрес других видов не принимает.
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