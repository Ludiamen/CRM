"""Участники узла, руководители, роли узла (FR-110…114, FR-120…121; T-2232).

Пока заглушки (T-2230a): проверка права окончательная, с правом ответ — 404; тело заменяет T-2232.
"""
from django.http import Http404
from django.views.decorators.http import require_GET, require_POST

from apps.core.services.permissions import require_permission


@require_permission("org.manage")
@require_GET
def candidates(request, unit_id: int):
    """`/structure/<id>/candidates/` — подсказки людей для узла."""
    raise Http404


@require_permission("org.manage")
@require_POST
def members_add(request, unit_id: int):
    """`/structure/<id>/members/` — добавить участников."""
    raise Http404


@require_permission("org.manage")
@require_POST
def member_transfer(request, unit_id: int, user_id: int):
    """`/structure/<id>/members/<user_id>/transfer/` — перевести в другой узел того же вида."""
    raise Http404


@require_permission("org.manage")
@require_POST
def member_remove(request, unit_id: int, user_id: int):
    """`/structure/<id>/members/<user_id>/remove/` — удалить из узла."""
    raise Http404


@require_permission("org.manage")
@require_POST
def marks(request, unit_id: int):
    """`/structure/<id>/marks/` — руководители и заместители из участников."""
    raise Http404


@require_permission("roles.manage")
@require_POST
def unit_roles(request, unit_id: int):
    """`/structure/<id>/roles/` — роли узла."""
    raise Http404
