"""Справочник видов основания поручений (срез 010, T-10201; FR-701; CONTRACT-010, 5.1, 6.2).

Ведёт администратор; удаление использованного вида не удаляет поручения — вид выключается (`active=False`).
"""
from django.db import transaction
from django.db.models import Max

from apps.instructions.models import Instruction, InstructionBasisKind
from apps.instructions.texts import InstructionsError

TITLE_MAX = 100


def all():
    """Все виды по порядку."""
    return InstructionBasisKind.objects.order_by("position", "pk")


def active():
    """Только действующие виды."""
    return all().filter(active=True)


def _clean(title) -> str:
    text = (title or "").strip()
    if not 1 <= len(text) <= TITLE_MAX:
        raise InstructionsError("basis_title_range", "title")
    return text


@transaction.atomic
def add(actor, title) -> InstructionBasisKind:
    """Добавить вид в конец справочника."""
    text = _clean(title)
    if InstructionBasisKind.objects.filter(title=text).exists():
        raise InstructionsError("basis_title_taken", "title")
    top = InstructionBasisKind.objects.aggregate(top=Max("position"))["top"]
    position = 0 if top is None else top + 1
    return InstructionBasisKind.objects.create(title=text, position=position)


@transaction.atomic
def rename(actor, kind, title) -> InstructionBasisKind:
    """Переименовать вид."""
    text = _clean(title)
    if InstructionBasisKind.objects.filter(title=text).exclude(pk=kind.pk).exists():
        raise InstructionsError("basis_title_taken", "title")
    kind.title = text
    kind.save(update_fields=["title"])
    return kind


@transaction.atomic
def delete(actor, kind) -> bool:
    """Удалить неиспользованный вид; использованный — выключить. Возвращает `True`, если строка удалена."""
    if Instruction.objects.filter(basis_kind=kind).exists():
        if kind.active:
            kind.active = False
            kind.save(update_fields=["active"])
        return False
    kind.delete()
    return True