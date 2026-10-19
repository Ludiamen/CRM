"""Комментарий к объекту любого модуля (PLAN-005, «Модель данных» → «Ядро и прежние модули»).

Объект назван строкой `object_ref` вида `<приложение>.<объект>:<pk>` (как `notify.Notification.object_ref`);
внешнего ключа на объект нет: модуль сам удаляет комментарии своего объекта (`comments.delete_for`).
"""
from django.db import models

from ._util import now


class Comment(models.Model):
    object_ref = models.CharField("объект", max_length=64)
    author = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    text = models.TextField("текст")  # длину до 4000 знаков проверяет служба
    created_at = models.DateTimeField("создан", default=now)

    class Meta:
        default_permissions = ()
        indexes = [models.Index(fields=["object_ref", "created_at", "id"], name="core_comment_object_idx")]
