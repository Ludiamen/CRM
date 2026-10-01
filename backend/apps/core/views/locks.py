"""Блокировки входа `/staff/locks/` (T-246, FR-038, FR-044): заблокированные записи и адреса, «Снять блокировку входа»."""
from django.http import HttpResponseRedirect
from django.views.decorators.http import require_http_methods

from apps.core.models import User
from apps.core.services import accounts
from apps.core.services.permissions import require_permission

from .common import flash, render_page

URL = "/staff/locks/"


def _minutes(seconds: int) -> int:
    return max((seconds + 59) // 60, 1)


@require_permission("accounts.manage")
@require_http_methods(["GET", "POST"])
def locks(request):
    if request.method == "POST":
        kind, target = request.POST.get("kind", ""), request.POST.get("target", "").strip()
        ip = request.client_ip
        if kind == "account":
            user = User.objects.filter(pk=int(target)).first() if target.isdigit() else None
            if user is None:
                flash(request, "Такой записи нет.", error=True)
            elif accounts.unlock_login(user, actor=request.user, ip=ip):
                flash(request, f"Блокировка входа снята: {user.email}.")
            else:
                flash(request, "Блокировка уже снята или истекла.")
        elif kind == "ip" and target:
            if accounts.unlock_ip(target, actor=request.user, ip=ip):
                flash(request, f"Блокировка адреса снята: {target}.")
            else:
                flash(request, "Блокировка уже снята или истекла.")
        else:
            flash(request, "Не указано, что разблокировать.", error=True)
        return HttpResponseRedirect(URL)
    overview = accounts.lock_overview()
    context = {
        "accounts": [{"user": user, "minutes": _minutes(left)} for user, left in overview["accounts"]],
        "ips": [{"address": address, "minutes": _minutes(left)} for address, left in overview["ips"]],
    }
    return render_page(request, "staff/locks.html", context)
