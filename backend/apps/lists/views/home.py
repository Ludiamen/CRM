"""Главная раздела «Списки», общие помощники страниц и заглушка адресов следующих задач (T-6214a; PLAN-006, «Раздел и
настройка списка», «Контракты»; CONTRACT-006, 10.1, 11.2).

Главная — только для тех, кому раздел открыт (`access.sees_section`): иначе 404 (FR-501, FR-514).
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import redirect
from django.views.decorators.http import require_GET

from apps.core.views.common import is_fragment, render_page
from apps.lists.models import List
from apps.lists.services import access
from apps.lists.texts import TEXTS


def done(request, url: str):
    """Успех POST (10.1): обычный запрос — 302 на адрес; запрос HTMX — пустой ответ 200 с `HX-Redirect` на тот же адрес."""
    if is_fragment(request):
        response = HttpResponse("")
        response["HX-Redirect"] = url
        response["Vary"] = "HX-Request"
        return response
    return redirect(url)


@login_required
def pending(request, task: str, **kwargs):
    """Заглушка адреса, который ещё не написан (решение 60): 404; `task` в `urls.py` называет задачу-владельца."""
    raise Http404("Страница не написана")


@login_required
@require_GET
def home(request):
    """Читаемые списки по названию; у каждого название, описание и число записей не в архиве (один запрос)."""
    user = request.user
    if not access.sees_section(user):
        raise Http404("Раздел не найден")
    scope = access.scope(user)
    lists = List.objects.all() if scope.manage else List.objects.filter(pk__in=scope.readable)
    rows = lists.annotate(live_count=Count("records", filter=Q(records__archived=False))).order_by("name", "pk")
    return render_page(request, "lists/home.html", {"rows": list(rows), "can_manage": scope.manage,
                                                    "empty_text": TEXTS["home_empty"]})
