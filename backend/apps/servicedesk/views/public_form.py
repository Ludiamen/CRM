"""Открытая форма заявки: `/request/` и `/request/done/` (CONTRACT-003, 12.1, 13.6).

Страница — всегда `base_public.html` без меню, и для вошедшего, и для запроса НХ (поэтому `render`, а не
`render_page`). Решения принимает служба `form`; здесь — разбор полей, сессия и показ.
"""
from django.http import HttpResponseRedirect
from django.shortcuts import render
from django.views.decorators.http import require_http_methods

from ..services import attachments, form
from ..services.errors import ServiceDeskError

FIELDS = ("email", "name", "client_unit", "category", "subject", "text")
DONE_URL = "/request/done/"
_MAX_ID = 2**31 - 1


def _id(value):
    """Номер из поля выбора: пусто — `None`; не число и вне границ базы — 0 (такой записи нет, служба откажет)."""
    value = (value or "").strip()
    if not value:
        return None
    if not value.isascii() or not value.isdigit() or int(value) > _MAX_ID:
        return 0
    return int(value)


def _page(request, *, values=None, errors=None, alert=None, status=200):
    """Страница формы; закрытое состояние — плашка вместо формы."""
    opened = form.is_open()
    context = {"is_open": opened, "values": values or {}, "errors": errors or {}, "alert": alert,
               "closed_text": "" if opened else form.closed_text(), "choices": form.choices() if opened else None}
    return render(request, "servicedesk/form/request.html", context, status=status)


@require_http_methods(["GET", "HEAD", "POST"])
def request_form(request):
    """Форма заявки без входа; отказ службы — 200 с той же страницей (поля — у полей, прочее — одно сообщение)."""
    if request.method != "POST":
        return _page(request)
    post = request.POST
    values = {field: post.get(field, "") for field in FIELDS}
    values["consent"] = bool(post.get("consent"))
    try:
        parts = [attachments.from_upload(item) for item in request.FILES.getlist("files")]
        created = form.submit(
            email=values["email"], name=values["name"], client_unit_id=_id(values["client_unit"]),
            category_id=_id(values["category"]), subject=values["subject"], text=values["text"],
            consent=values["consent"], parts=parts, ip=request.client_ip)
    except form.FormInvalid as error:
        errors = {field: {"code": code, "text": form.FIELD_TEXTS[code]} for field, code in error.errors.items()}
        return _page(request, values=values, errors=errors)
    except ServiceDeskError as error:
        return _page(request, values=values, alert={"code": error.code, "text": error.message})
    form.remember_done(request.session, created.ticket.requester_email)
    return HttpResponseRedirect(DONE_URL)


@require_http_methods(["GET", "HEAD"])
def request_done(request):
    """«Заявка принята»: адрес из сессии показывается один раз; без адреса — на форму."""
    email = form.pop_done(request.session)
    if not email:
        return HttpResponseRedirect("/request/")
    return render(request, "servicedesk/form/done.html", {"email": email})
