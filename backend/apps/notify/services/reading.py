"""Публичный интерфейс уведомлений: «прочитано» (PLAN-004, «Колокольчик…» → «Прочитано»; CONTRACT-004, 6.8).

После каждой отметки, если число изменилось, новое число уходит в группу сотрудника.
"""
from django.http import Http404
from django.utils import timezone

from ..models import Notification
from . import live


def unread_count(user_id: int) -> int:
    """Число непрочитанных уведомлений сотрудника."""
    return Notification.objects.filter(user_id=user_id, read_at__isnull=True).count()


def _own(user, notification_id) -> Notification:
    try:
        return Notification.objects.get(pk=notification_id, user_id=user.pk)
    except (Notification.DoesNotExist, ValueError, TypeError):
        raise Http404("Уведомление не найдено") from None


def _mark(user, notification_id) -> tuple[Notification, bool]:
    """Отмечает своё уведомление одним `UPDATE` по непрочитанной записи; `True`, если запись изменилась."""
    note = _own(user, notification_id)
    changed = Notification.objects.filter(pk=note.pk, user_id=user.pk, read_at__isnull=True).update(
        read_at=timezone.now()) > 0
    return note, changed


def open(user, notification_id) -> str:  # noqa: A001 — имя из контракта
    """Адрес уведомления; своё непрочитанное отмечается. Чужое или несуществующее — `Http404`."""
    note, changed = _mark(user, notification_id)
    if changed:
        live.push([user.pk])
    return note.url


def read(user, notification_id) -> bool:
    """Отмечает своё уведомление прочитанным; `False` — уже было прочитано (рассылки нет)."""
    _, changed = _mark(user, notification_id)
    if changed:
        live.push([user.pk])
    return changed


def read_all(user) -> int:
    """Отмечает все свои непрочитанные одним `UPDATE`; возвращает их число."""
    marked = Notification.objects.filter(user_id=user.pk, read_at__isnull=True).update(read_at=timezone.now())
    if marked:
        live.push([user.pk])
    return marked


def mark_object(user_id: int, object_ref: str) -> int:
    """Отмечает непрочитанные сотрудника по объекту (публичная функция для других срезов); пустая ссылка — `0`."""
    if not object_ref:
        return 0
    marked = Notification.objects.filter(user_id=user_id, object_ref=object_ref, read_at__isnull=True).update(
        read_at=timezone.now())
    if marked:
        live.push([user_id])
    return marked


def on_object_viewed(*, object_ref: str, user_id: int) -> None:
    """Подписчик `object.viewed`: открытие объекта отмечает его уведомления."""
    mark_object(user_id, object_ref)
