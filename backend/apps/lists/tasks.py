"""Фоновые задачи списков: пересчёт векторов, напоминания, загрузка (срез 006)."""
from django.db import transaction

from apps.lists.models import Field, List, Record
from apps.lists.services import access, vectors

CHUNK = 500


def refresh_vectors(list_id: int, field_id: int) -> None:
    """Пересчитывает вектор поиска записей списка, у которых заполнено поле (скрытие и показ поля — И2).

    Порциями по 500 по возрастанию `id`, каждая — в своей транзакции под разделяемым замком списка. В конце снимает
    `List.vectors_stale_since`, только если признак не менялся с начала задания: второе скрытие во время пересчёта
    оставит признак своему заданию (К20). Нет списка — выход без ошибки; нет поля (пустое поле успели удалить) —
    пересчитывать нечего, признак снимается так же."""
    started = List.objects.filter(pk=list_id).values_list("vectors_stale_since", flat=True).first()
    if not List.objects.filter(pk=list_id).exists():
        return
    field = Field.objects.filter(pk=field_id, list_id=list_id).first()
    if field is not None:
        last = 0
        while True:
            with transaction.atomic():
                access.lock_list(list_id, shared=True)
                ids = list(Record.objects.filter(list_id=list_id, values__has_key=field.code, pk__gt=last)
                           .order_by("pk").values_list("pk", flat=True)[:CHUNK])
                vectors.refresh(ids)
            if len(ids) < CHUNK:
                break
            last = ids[-1]
    List.objects.filter(pk=list_id, vectors_stale_since=started).update(vectors_stale_since=None)


def remind_deadlines() -> None:
    """Ночное задание сроков (cron `lists_reminders`, 05:00 UTC = 08:00 по Москве): обход, уведомления, уборка.

    Сбой одной записи обход не прерывает; если сбои были, задание после обхода завершается ошибкой с номерами записей
    (`Record.pk`) — так сбой виден в очереди (FR-530, NFR-511)."""
    from apps.core.widgets import moscow_today
    from apps.lists.services import reminders

    result = reminders.run(moscow_today())
    if result.failed:
        raise RuntimeError("Напоминания о сроках: сбой по записям " + ", ".join(str(pk) for pk in result.failed))
