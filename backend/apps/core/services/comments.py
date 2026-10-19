"""Комментарии к объектам модулей (PLAN-005, «Комментарии»; FR-425, FR-426).

Ядро объект не разбирает: можно ли комментировать и видеть, решает модуль, который хранит `object_ref`.
События шины и журнал служба не пишет.
"""
from django.utils import timezone

from apps.core.models import Comment, User

MAX_LENGTH = 4000


class CommentError(Exception):
    """Отказ комментария: `code` — `empty` или `too_long`, `message` — текст для сотрудника."""

    MESSAGES = {
        "empty": "Введите текст комментария",
        "too_long": f"Комментарий не длиннее {MAX_LENGTH} знаков",
    }

    def __init__(self, code: str):
        self.code = code
        self.message = self.MESSAGES[code]
        super().__init__(self.message)


def add(author: User, object_ref: str, text: str) -> Comment:
    """Сохраняет комментарий: пробелы по краям убираются, длина 1–4000 знаков."""
    text = text.strip()
    if not text:
        raise CommentError("empty")
    if len(text) > MAX_LENGTH:
        raise CommentError("too_long")
    return Comment.objects.create(author=author, object_ref=object_ref, text=text, created_at=timezone.now())


def list_for(object_ref: str) -> list[Comment]:
    """Комментарии объекта: старые первыми; автор и его фото читаются тем же запросом."""
    return list(Comment.objects.filter(object_ref=object_ref).select_related("author", "author__photo")
                .order_by("created_at", "id"))


def delete(comment: Comment) -> None:
    """Удаляет один комментарий физически."""
    comment.delete()


def delete_for(object_ref: str) -> int:
    """Удаляет все комментарии объекта (в той же транзакции, что и сам объект); возвращает их число."""
    return Comment.objects.filter(object_ref=object_ref).delete()[0]
