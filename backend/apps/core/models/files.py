"""Хранимые файлы (PLAN-002, «Ядро (изменения)»): фото сотрудника и вложения заявок.

Сами файлы лежат в томе `protected`; здесь только запись о файле и его проверке.
Связь с `User` — строковая ссылка: `accounts.py` ссылается на `StoredFile` так же.
"""
import uuid

from django.db import models

from ._util import now


class StoredFile(models.Model):
    class Purpose(models.TextChoices):
        PHOTO = "photo", "фото"
        ATTACHMENT = "attachment", "вложение"

    class Status(models.TextChoices):
        PENDING = "pending", "проверяется"
        CLEAN = "clean", "чистый"
        QUARANTINE = "quarantine", "карантин"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    purpose = models.CharField("назначение", max_length=16, choices=Purpose.choices, default=Purpose.PHOTO)
    owner = models.ForeignKey(
        "core.User", null=True, blank=True, on_delete=models.PROTECT, related_name="stored_files"
    )
    size = models.PositiveBigIntegerField("размер, байт")
    sha256 = models.CharField(max_length=64)
    content_type = models.CharField("тип содержимого", max_length=255)
    status = models.CharField("состояние проверки", max_length=16, choices=Status.choices, default=Status.PENDING)
    signature = models.CharField("сигнатура", max_length=255, blank=True)
    attempts = models.PositiveIntegerField("попыток проверки", default=0)
    last_error = models.TextField("последняя ошибка", blank=True)
    created_at = models.DateTimeField(default=now)
    scanned_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        default_permissions = ()

    def __str__(self):
        return str(self.id)
