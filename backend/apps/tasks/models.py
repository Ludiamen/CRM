"""Модели среза 009 «Задачи» (PLAN-009, «Модель данных» → «Приложение `tasks`»).

Восемь таблиц: задача, участник, категория, колонка личного плана, напоминание, комментарий, файл, настройки.
Внешние ключи — только на `core.User` и `core.StoredFile`; узлы структуры и уведомления приходят службами.
Имена ограничений и индексов — CONTRACT-009, 2.1. Номер задачи — `pk`.
"""
import uuid

from django.db import models
from django.db.models import Q

from apps.core.models._util import now


class Task(models.Model):
    """Задача: название, описание, срок-дата, постановщик и исполнитель, статус, категория, колонка плана."""

    class Status(models.TextChoices):
        NEW = "new", "Новая"
        IN_PROGRESS = "in_progress", "В работе"
        WAITING = "waiting", "Ждёт"
        DONE = "done", "Готово"

    title = models.CharField("название", max_length=300)
    description = models.TextField("описание", max_length=10_000, blank=True, default="")
    deadline = models.DateField("срок", null=True, blank=True)
    author = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="authored_tasks")
    assignee = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="assigned_tasks")
    status = models.CharField("статус", max_length=16, choices=Status.choices, default=Status.NEW)
    category = models.ForeignKey("tasks.TaskCategory", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="tasks")
    plan_column = models.ForeignKey("tasks.PlanColumn", on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="tasks")
    created_at = models.DateTimeField(default=now)
    updated_at = models.DateTimeField(default=now)
    completed_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    # Связь с заявкой сервис-деска — номером без внешнего ключа (SPEC-012, FR-776).
    ticket_number = models.PositiveIntegerField("номер заявки", null=True, blank=True)

    class Meta:
        default_permissions = ()
        indexes = [
            models.Index(fields=["assignee", "status"], name="tasks_task_assignee_status"),
            models.Index(fields=["deadline"], name="tasks_task_deadline"),
            models.Index(fields=["author"], name="tasks_task_author"),
            models.Index(fields=["plan_column"], name="tasks_task_plan_column"),
            models.Index(fields=["category"], name="tasks_task_category"),
            models.Index(fields=["deleted_at"], name="tasks_task_deleted_at"),
            models.Index(fields=["ticket_number", "deleted_at"], name="tasks_task_ticket_number"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(ticket_number__isnull=True) | Q(ticket_number__gt=0),
                                   name="tasks_task_ticket_number_positive"),
        ]

    def __str__(self):
        return f"#{self.pk} {self.title}"


class TaskMember(models.Model):
    """Соисполнитель или наблюдатель задачи; исполнитель хранится в `Task.assignee`."""

    class Role(models.TextChoices):
        COEXECUTOR = "coexecutor", "соисполнитель"
        OBSERVER = "observer", "наблюдатель"

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="task_memberships")
    role = models.CharField("роль", max_length=16, choices=Role.choices, default=Role.COEXECUTOR)

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["task", "user"], name="tasks_member_task_user_uniq")]
        indexes = [models.Index(fields=["user"], name="tasks_member_user")]


class TaskCategory(models.Model):
    """Категория задач — справочник администратора."""

    title = models.CharField("название", max_length=100, unique=True)
    position = models.PositiveIntegerField("порядок", default=0)

    class Meta:
        default_permissions = ()
        ordering = ["position", "pk"]
        indexes = [models.Index(fields=["position"], name="tasks_category_position")]

    def __str__(self):
        return self.title


class PlanColumn(models.Model):
    """Личная колонка «Моего плана» сотрудника."""

    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="task_plan_columns")
    title = models.CharField("название", max_length=100)
    position = models.PositiveIntegerField("порядок", default=0)

    class Meta:
        default_permissions = ()
        ordering = ["position", "pk"]
        constraints = [models.UniqueConstraint(fields=["user", "title"], name="tasks_plan_user_title_uniq")]
        indexes = [models.Index(fields=["user", "position"], name="tasks_plan_user_position")]

    def __str__(self):
        return f"{self.user_id}: {self.title}"


class TaskReminder(models.Model):
    """Напоминание о задаче: автоматическое (`auto*`) или ручное, со своим моментом."""

    class Kind(models.TextChoices):
        AUTO_SOON = "auto_soon", "скоро просрочена"
        AUTO_DUE = "auto_due", "срок наступил"
        AUTO_OVERDUE = "auto_overdue", "просрочена"
        MANUAL = "manual", "ручное"

    class State(models.TextChoices):
        PENDING = "pending", "ждёт"
        SENT = "sent", "отправлено"
        CANCELLED = "cancelled", "отменено"

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="reminders")
    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="task_reminders")
    kind = models.CharField("вид", max_length=16, choices=Kind.choices)
    moment = models.DateTimeField("момент")
    days = models.PositiveSmallIntegerField("за N рабочих дней", null=True, blank=True)
    state = models.CharField("состояние", max_length=16, choices=State.choices, default=State.PENDING)
    postponed_to = models.DateTimeField("отложено до", null=True, blank=True)
    created_at = models.DateTimeField(default=now)

    class Meta:
        default_permissions = ()
        indexes = [models.Index(fields=["state", "moment"], name="tasks_reminder_state_moment")]
        constraints = [
            models.UniqueConstraint(
                fields=["task", "user", "kind"],
                condition=Q(kind__startswith="auto") & ~Q(state="cancelled"),
                name="tasks_reminder_auto_uniq",
            ),
        ]


class TaskComment(models.Model):
    """Комментарий карточки: своя модель (правка и мягкое удаление), не `core.Comment`."""

    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="comments")
    author = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="task_comments")
    text = models.TextField("текст", max_length=10_000)
    created_at = models.DateTimeField(default=now)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        default_permissions = ()
        ordering = ["created_at", "pk"]
        indexes = [models.Index(fields=["task", "created_at"], name="tasks_comment_task_created")]


class TaskFile(models.Model):
    """Вложение задачи или комментария; строка `core.StoredFile` — назначение `task`. Номер — UUID."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="files")
    comment = models.ForeignKey(TaskComment, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="files")
    file = models.OneToOneField("core.StoredFile", on_delete=models.PROTECT, related_name="task_file")
    name = models.CharField("имя", max_length=255)
    uploaded_by = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="task_files")
    created_at = models.DateTimeField(default=now)

    class Meta:
        default_permissions = ()
        indexes = [
            models.Index(fields=["task"], name="tasks_file_task"),
            models.Index(fields=["comment"], name="tasks_file_comment"),
        ]


class TaskSettings(models.Model):
    """Настройки задач: срок хранения (одна строка `pk=1`)."""

    retention_years = models.PositiveSmallIntegerField("срок хранения, лет", default=3)
    updated_at = models.DateTimeField(null=True, blank=True)
    updated_by = models.ForeignKey("core.User", on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+")

    class Meta:
        default_permissions = ()