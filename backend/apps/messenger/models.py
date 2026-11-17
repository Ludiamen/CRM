"""Модели мессенджера (срез 008, PLAN-008, «Модель данных» → «Приложение `messenger`»).

Шесть таблиц: чат, участник, отметка прочтения, сообщение, вложение, настройки. Внешние ключи на модели `org`,
`notify` и `feed` не ставятся: узел структуры в `Chat.unit_id` — число (FR-650), а файл вложения — строка
`core.StoredFile` назначения `messenger`. Имена ограничений и индексов заданы CONTRACT-008 (2.2) и не длиннее
30 знаков (решение К5); на них опираются тесты среза и SQL помощников.
"""
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import Q


class Chat(models.Model):
    """Беседа: личный диалог, группа, чат отдела или «Общий чат» (FR-643, 645, 649…651).

    Строк `ChatMember` у чата отдела и «Общего чата» нет — состав считается на момент просмотра; название чата
    отдела хранится не здесь, его даёт узел (`page.chat_title`). `pair_key` — «<меньший id>:<больший id>» личного
    диалога, `unit_id` — номер узла отдела.
    """

    class Kind(models.TextChoices):
        PERSONAL = "personal", "Личный"
        GROUP = "group", "Групповой"
        DEPARTMENT = "department", "Чат отдела"
        GENERAL = "general", "Общий чат"

    kind = models.CharField(max_length=16, choices=Kind.choices)
    title = models.CharField(max_length=200, blank=True, default="")
    unit_id = models.PositiveIntegerField(null=True, blank=True)
    pair_key = models.CharField(max_length=32, blank=True, default="")
    created_by = models.ForeignKey("core.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField()
    last_message_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        default_permissions = ()
        constraints = [
            models.CheckConstraint(
                condition=(
                    (Q(kind="group") | Q(kind="general")) & ~Q(title="")
                    | Q(kind__in=["personal", "department"]) & Q(title="")
                ),
                name="messenger_chat_title_chk",
            ),
            models.CheckConstraint(
                condition=(
                    Q(kind="department", unit_id__isnull=False)
                    | (~Q(kind="department") & Q(unit_id__isnull=True))
                ),
                name="messenger_chat_unit_chk",
            ),
            models.CheckConstraint(
                condition=(Q(kind="personal") & ~Q(pair_key="")) | (~Q(kind="personal") & Q(pair_key="")),
                name="messenger_chat_pair_chk",
            ),
            models.UniqueConstraint(
                fields=["pair_key"],
                condition=Q(kind="personal"),
                name="messenger_chat_pair_uniq",
            ),
            models.UniqueConstraint(
                fields=["unit_id"],
                condition=Q(kind="department"),
                name="messenger_chat_unit_uniq",
            ),
            models.UniqueConstraint(
                fields=["kind"],
                condition=Q(kind="general"),
                name="messenger_chat_general_uniq",
            ),
        ]
        indexes = [
            models.Index(fields=["-last_message_at", "-id"], name="messenger_chat_last_msg_idx"),
            models.Index(fields=["created_by"], name="messenger_chat_created_by_idx"),
        ]


class ChatMember(models.Model):
    """Участник личного или группового чата (FR-646, 647).

    Строка одна на пару «чат, сотрудник» и после выхода: вышедший помечается `left_at`, новой строки не появляется.
    """

    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    is_creator = models.BooleanField(default=False)
    joined_at = models.DateTimeField()
    left_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["chat", "user"], name="messenger_chatmember_uniq"),
        ]
        indexes = [
            models.Index(
                fields=["user", "chat"],
                condition=Q(left_at__isnull=True),
                name="messenger_chatmember_user_idx",
            ),
        ]


class ChatRead(models.Model):
    """Отметка прочтения беседы сотрудником (FR-659, 660).

    Отдельная таблица, а не поле `ChatMember.last_read_at`: у чата отдела и «Общего чата» строк участников нет.
    """

    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="reads")
    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="+")
    last_read_at = models.DateTimeField()

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["chat", "user"], name="messenger_chatread_uniq"),
        ]
        indexes = [
            models.Index(fields=["user", "chat"], name="messenger_chatread_user_idx"),
        ]


class Message(models.Model):
    """Сообщение беседы или системная запись (FR-649, 652, 654, 657, 658, 668).

    Текст хранится как есть (до 4 000 знаков проверяет служба); у системной записи автора нет, у удалённой текст
    пуст. `search` заполняет служба, индекс `GIN` — для сквозного поиска.
    """

    chat = models.ForeignKey(Chat, on_delete=models.CASCADE, related_name="messages")
    author = models.ForeignKey("core.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    is_system = models.BooleanField(default=False)
    text = models.TextField(blank=True, default="")
    quote = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    created_at = models.DateTimeField()
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    search = SearchVectorField(null=True)

    class Meta:
        default_permissions = ()
        constraints = [
            models.CheckConstraint(
                condition=Q(is_system=True, author__isnull=True) | Q(is_system=False, author__isnull=False),
                name="messenger_message_system_chk",
            ),
            models.CheckConstraint(
                condition=Q(deleted_at__isnull=True) | Q(text=""),
                name="messenger_message_deleted_chk",
            ),
        ]
        indexes = [
            models.Index(fields=["chat", "-created_at", "-id"], name="messenger_message_chat_idx"),
            models.Index(fields=["created_at"], name="messenger_message_created_idx"),
            GinIndex(fields=["search"], name="messenger_message_search_gin"),
        ]


class MessageAttachment(models.Model):
    """Вложение сообщения: строка файла ядра назначения `messenger` (FR-662).

    Пока файл не привязан к сообщению, `message` пусто; один файл — одно вложение.
    """

    message = models.ForeignKey(Message, on_delete=models.CASCADE, null=True, blank=True, related_name="files")
    file = models.OneToOneField("core.StoredFile", on_delete=models.PROTECT, related_name="+")
    name = models.CharField(max_length=255)
    thumb = models.CharField(max_length=255, blank=True, default="")
    uploaded_by = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField()

    class Meta:
        default_permissions = ()
        indexes = [
            models.Index(fields=["message"], name="messenger_attach_message_idx"),
            models.Index(
                fields=["uploaded_by", "uploaded_at"],
                condition=Q(message__isnull=True),
                name="messenger_attach_unbound_idx",
            ),
        ]


class MessengerSettings(models.Model):
    """Настройки мессенджера: одна строка `pk=1` (FR-651, 670).

    Срок хранения — 1…10 лет (по умолчанию 3), «Общий чат» по умолчанию включён; строку создаёт миграция `0002`.
    """

    retention_years = models.PositiveSmallIntegerField(default=3)
    general_chat_enabled = models.BooleanField(default=True)
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey("core.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")

    class Meta:
        default_permissions = ()
        constraints = [
            models.CheckConstraint(
                condition=Q(retention_years__gte=1, retention_years__lte=10),
                name="messenger_settings_years_chk",
            ),
        ]