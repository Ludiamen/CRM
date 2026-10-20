"""Подписки на рубрики (PLAN-005, «Уведомления базы знаний» → «Подписка»; FR-437).

Подписку видит и меняет только сам сотрудник: функции принимают одного пользователя и только на себя.
"""
from django.db import transaction
from django.http import Http404

from ..models import Rubric, RubricSubscription


def toggle(user, rubric_id: int) -> bool:
    """Подписывает на рубрику или снимает подписку; `True` — теперь подписан. Рубрики нет — `Http404`. Журнала нет."""
    with transaction.atomic():
        # Строка рубрики под замком: параллельное удаление рубрики не оставит подписку без рубрики.
        if not Rubric.objects.select_for_update().filter(pk=rubric_id).exists():
            raise Http404("Рубрики нет")
        deleted, _ = RubricSubscription.objects.filter(user=user, rubric_id=rubric_id).delete()
        if deleted:
            return False
        RubricSubscription.objects.get_or_create(user=user, rubric_id=rubric_id)
        return True


def on_user_dismissed(*, user_id: int, actor_id: int | None = None) -> None:
    """Подписчик события ядра `core.user_dismissed`: удаляет подписки уволенного (FR-437)."""
    RubricSubscription.objects.filter(user_id=user_id).delete()
