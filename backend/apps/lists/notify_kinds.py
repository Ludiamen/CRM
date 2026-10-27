"""Виды уведомлений `lists.*` (срез 006; PLAN-006, «Сроки и напоминания»; CONTRACT-006, раздел 7).

Один вид — `lists.deadline`: уведомления создаёт не событие шины, а ночное задание `tasks.remind_deadlines` прямым
`dispatch.create`. Получателем бывает любой сотрудник, в том числе без права на список, поэтому вид виден всем, а
`still_relevant` доступ к списку не проверяет (FR-531). Названия записи и списка во внешние каналы не попадают.
"""
import re

from django.contrib.auth import get_user_model

from apps.core.extensions import NotificationKind

from .models import Record

DEADLINE = "lists.deadline"
OBJECT_PREFIX = "lists.record:"
_REF = re.compile(r"lists\.record:([0-9]{1,18}):([0-9]{1,18}):([0-9]{1,5})")
EXPIRING_TEXT = "Истекает срок в записи списка"
REACHED_TEXT = "Срок в записи списка наступил"


def make_ref(record_id: int, field_id: int, threshold: int) -> str:
    """`object_ref` напоминания: запись, поле-срок и порог; даты срока в нём нет (перенос срока даёт новое уведомление)."""
    return f"{OBJECT_PREFIX}{record_id}:{field_id}:{threshold}"


def deadline_external_text(object_ref: str) -> str:
    """Внешний текст по порогу из ссылки: порог 0 — «Срок … наступил», иначе — «Истекает срок …»."""
    match = _REF.fullmatch(object_ref or "")
    if match is not None and int(match.group(3)) == 0:
        return REACHED_TEXT
    return EXPIRING_TEXT


def deadline_still_relevant(user_id: int, object_ref: str) -> bool:
    """Получатель не уволен и запись существует; доступ к списку и архив не проверяются (FR-531)."""
    match = _REF.fullmatch(object_ref or "")
    if match is None:
        return False
    user = get_user_model().objects.filter(pk=user_id).first()
    if user is None or user.state == "dismissed":
        return False
    return Record.objects.filter(pk=int(match.group(1))).exists()


def _available(user) -> bool:
    return True


def notification_kinds() -> list[NotificationKind]:
    """Функция точки `notification_kinds`: один вид, свежий объект при каждом вызове."""
    return [
        NotificationKind(
            code=DEADLINE, title="Срок в записи списка", module="Списки", external_text=EXPIRING_TEXT,
            default_channels=("portal", "email"), available=_available, still_relevant=deadline_still_relevant,
            order=60, coalesce=False, external_text_of=deadline_external_text),
    ]
