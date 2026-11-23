"""Модели среза 010 «Поручения» (PLAN-010, «Модель данных»; CONTRACT-010, 2.1).

Номер поручения — `pk`; `__str__` — `#<pk> <title>` (К3). Статус поручения не хранится: вычисляется службой
реестра (К4). Периодичность отчётных дат не поле модели — приходит из формы в `services.dates` (К21).
"""
import uuid

from django.db import models
from django.db.models import Q
from django.utils import timezone


class InstructionBasisKind(models.Model):
    """Вид документа-основания: справочник администратора."""

    title = models.CharField("название", max_length=100, unique=True)
    position = models.PositiveIntegerField("порядок", default=0)
    active = models.BooleanField("действует", default=True)

    class Meta:
        default_permissions = ()
        ordering = ("position", "pk")
        indexes = [models.Index(fields=["position"], name="instr_basis_position")]

    def __str__(self) -> str:
        return self.title


class Instruction(models.Model):
    """Поручение с основанием, сроком, контролёром и исполнителями."""

    title = models.CharField("название", max_length=300)
    text = models.TextField("текст", max_length=10_000, blank=True)
    basis_kind = models.ForeignKey(InstructionBasisKind, verbose_name="вид основания", on_delete=models.PROTECT,
                                   related_name="instructions")
    basis_number = models.CharField("номер основания", max_length=100)
    basis_date = models.DateField("дата основания")
    author = models.ForeignKey("core.User", verbose_name="постановщик", on_delete=models.PROTECT,
                               related_name="authored_instructions")
    controller = models.ForeignKey("core.User", verbose_name="контролёр", on_delete=models.PROTECT,
                                   related_name="controlled_instructions")
    assignee = models.ForeignKey("core.User", verbose_name="исполнитель", on_delete=models.PROTECT,
                                 related_name="assigned_instructions")
    deadline = models.DateField("срок")
    original_deadline = models.DateField("исходный срок")
    ladder = models.JSONField("лестница", default=dict, blank=True)
    created_at = models.DateTimeField("создано", default=timezone.now)
    updated_at = models.DateTimeField("изменено", default=timezone.now)
    closed_at = models.DateTimeField("снято с контроля", null=True, blank=True)
    deleted_at = models.DateTimeField("удалено по сроку", null=True, blank=True)

    class Meta:
        default_permissions = ()
        indexes = [
            models.Index(fields=["assignee", "deadline"], name="instr_assignee_deadline"),
            models.Index(fields=["controller"], name="instr_controller"),
            models.Index(fields=["author"], name="instr_author"),
            models.Index(fields=["deadline"], name="instr_deadline"),
            models.Index(fields=["closed_at"], name="instr_closed_at"),
            models.Index(fields=["basis_kind"], name="instr_basis_kind"),
        ]

    def __str__(self) -> str:
        return f"#{self.pk} {self.title}"


class InstructionMember(models.Model):
    """Соисполнитель поручения."""

    class Role(models.TextChoices):
        COEXECUTOR = "coexecutor", "соисполнитель"

    instruction = models.ForeignKey(Instruction, verbose_name="поручение", on_delete=models.CASCADE,
                                    related_name="members")
    user = models.ForeignKey("core.User", verbose_name="сотрудник", on_delete=models.PROTECT,
                             related_name="instruction_memberships")
    role = models.CharField("роль", max_length=16, choices=Role.choices, default=Role.COEXECUTOR)

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["instruction", "user"], name="instr_member_uniq")]
        indexes = [models.Index(fields=["user"], name="instr_member_user")]

    def __str__(self) -> str:
        return f"{self.instruction_id}: {self.user_id}"


class InstructionReportDate(models.Model):
    """Отчётная дата поручения: отчёт к дате и её решение контролёра."""

    class State(models.TextChoices):
        WAITING = "waiting", "ждёт отчёта"
        REVIEW = "review", "отчёт на проверке"
        RETURNED = "returned", "возвращено"
        ACCEPTED = "accepted", "принято"

    instruction = models.ForeignKey(Instruction, verbose_name="поручение", on_delete=models.CASCADE,
                                    related_name="report_dates")
    due_date = models.DateField("дата")
    position = models.PositiveIntegerField("порядок", default=0)
    state = models.CharField("состояние", max_length=16, choices=State.choices, default=State.WAITING)
    closed_at = models.DateTimeField("закрыта", null=True, blank=True)

    class Meta:
        default_permissions = ()
        ordering = ("due_date", "pk")
        constraints = [models.UniqueConstraint(fields=["instruction", "due_date"], name="instr_date_uniq")]
        indexes = [models.Index(fields=["instruction", "position"], name="instr_date_position")]

    def __str__(self) -> str:
        return f"{self.instruction_id}: {self.due_date}"


class InstructionReport(models.Model):
    """Сводный отчёт ответственного: к отчётной дате или к сроку (`date` пусто)."""

    class Decision(models.TextChoices):
        PENDING = "pending", "ждёт решения"
        ACCEPTED = "accepted", "принят"
        RETURNED = "returned", "возвращён"

    instruction = models.ForeignKey(Instruction, verbose_name="поручение", on_delete=models.CASCADE,
                                    related_name="reports")
    date = models.ForeignKey(InstructionReportDate, verbose_name="отчётная дата", on_delete=models.CASCADE,
                             null=True, blank=True, related_name="reports")
    author = models.ForeignKey("core.User", verbose_name="автор", on_delete=models.PROTECT,
                               related_name="instruction_reports")
    text = models.TextField("текст", max_length=10_000)
    submitted_at = models.DateTimeField("отправлен", default=timezone.now)
    decision = models.CharField("решение", max_length=16, choices=Decision.choices, default=Decision.PENDING)
    decided_by = models.ForeignKey("core.User", verbose_name="решил", on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name="decided_instruction_reports")
    decided_at = models.DateTimeField("решено", null=True, blank=True)
    comment = models.CharField("комментарий", max_length=2_000, blank=True)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["instruction", "author"], condition=Q(date__isnull=True),
                                    name="instr_final_report_uniq"),
        ]
        indexes = [models.Index(fields=["instruction", "submitted_at"], name="instr_report_submitted")]

    def __str__(self) -> str:
        return f"{self.instruction_id}: {'к сроку' if self.date_id is None else self.date_id}"


class InstructionReportPart(models.Model):
    """Часть отчёта соисполнителя к отчётной дате; переживает возврат сводного отчёта."""

    date = models.ForeignKey(InstructionReportDate, verbose_name="отчётная дата", on_delete=models.CASCADE,
                             related_name="parts")
    author = models.ForeignKey("core.User", verbose_name="автор", on_delete=models.PROTECT,
                               related_name="instruction_report_parts")
    text = models.TextField("текст", max_length=10_000)
    created_at = models.DateTimeField("создано", default=timezone.now)

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["date", "author"], name="instr_part_uniq")]
        indexes = [models.Index(fields=["date"], name="instr_part_date")]

    def __str__(self) -> str:
        return f"{self.date_id}: {self.author_id}"


class InstructionFile(models.Model):
    """Файл основания, отчёта или части; номер — UUID."""

    class Kind(models.TextChoices):
        BASIS = "basis", "основание"
        REPORT = "report", "отчёт"
        PART = "part", "часть отчёта"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instruction = models.ForeignKey(Instruction, verbose_name="поручение", on_delete=models.CASCADE,
                                    related_name="files")
    kind = models.CharField("вид", max_length=16, choices=Kind.choices)
    report = models.ForeignKey(InstructionReport, verbose_name="отчёт", on_delete=models.SET_NULL, null=True,
                               blank=True, related_name="files")
    part = models.ForeignKey(InstructionReportPart, verbose_name="часть", on_delete=models.SET_NULL, null=True,
                             blank=True, related_name="files")
    file = models.OneToOneField("core.StoredFile", verbose_name="файл", on_delete=models.PROTECT,
                                related_name="instruction_file")
    name = models.CharField("имя", max_length=255)
    uploaded_by = models.ForeignKey("core.User", verbose_name="загрузил", on_delete=models.PROTECT,
                                    related_name="instruction_files")
    created_at = models.DateTimeField("создано", default=timezone.now)

    class Meta:
        default_permissions = ()
        indexes = [
            models.Index(fields=["instruction"], name="instr_file_instruction"),
            models.Index(fields=["report"], name="instr_file_report"),
            models.Index(fields=["part"], name="instr_file_part"),
        ]

    def __str__(self) -> str:
        return self.name


class InstructionTransfer(models.Model):
    """Запрос переноса срока и решение по нему."""

    class State(models.TextChoices):
        PENDING = "pending", "ждёт решения"
        APPROVED = "approved", "согласован"
        REJECTED = "rejected", "отклонён"

    instruction = models.ForeignKey(Instruction, verbose_name="поручение", on_delete=models.CASCADE,
                                    related_name="transfers")
    old_deadline = models.DateField("прежний срок")
    new_deadline = models.DateField("новый срок")
    reason = models.CharField("причина", max_length=1_000)
    requested_by = models.ForeignKey("core.User", verbose_name="запросил", on_delete=models.PROTECT,
                                     related_name="instruction_transfer_requests")
    state = models.CharField("состояние", max_length=16, choices=State.choices, default=State.PENDING)
    decided_by = models.ForeignKey("core.User", verbose_name="решил", on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name="decided_instruction_transfers")
    decided_at = models.DateTimeField("решено", null=True, blank=True)
    comment = models.CharField("комментарий", max_length=1_000, blank=True)
    created_at = models.DateTimeField("создано", default=timezone.now)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["instruction"], condition=Q(state="pending"),
                                    name="instr_transfer_pending_uniq"),
        ]
        indexes = [models.Index(fields=["instruction", "state"], name="instr_transfer_state")]

    def __str__(self) -> str:
        return f"{self.instruction_id}: {self.old_deadline} → {self.new_deadline}"


class InstructionReminder(models.Model):
    """Напоминание лестницы или об отчётной дате."""

    class Kind(models.TextChoices):
        DEADLINE = "deadline", "о сроке"
        REPORT = "report", "об отчёте"

    class State(models.TextChoices):
        PENDING = "pending", "ждёт"
        SENT = "sent", "отправлено"
        CANCELLED = "cancelled", "отменено"

    instruction = models.ForeignKey(Instruction, verbose_name="поручение", on_delete=models.CASCADE,
                                    related_name="reminders")
    date = models.ForeignKey(InstructionReportDate, verbose_name="отчётная дата", on_delete=models.CASCADE,
                             null=True, blank=True, related_name="reminders")
    user = models.ForeignKey("core.User", verbose_name="получатель", on_delete=models.CASCADE,
                             related_name="instruction_reminders")
    kind = models.CharField("вид", max_length=16, choices=Kind.choices)
    stage = models.CharField("порог", max_length=8, choices=(
        ("d30", "30 рабочих дней"), ("d14", "14 рабочих дней"), ("d7", "7 рабочих дней"),
        ("d3", "3 рабочих дня"), ("d1", "1 рабочий день"), ("due", "день срока"),
        ("overdue", "просрочка"), ("r3", "3 дня до отчёта"), ("r1", "1 день до отчёта")))
    moment = models.DateTimeField("момент")
    state = models.CharField("состояние", max_length=16, choices=State.choices, default=State.PENDING)
    created_at = models.DateTimeField("создано", default=timezone.now)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["instruction", "date", "user", "kind", "stage"],
                                    condition=Q(state="pending"), nulls_distinct=False,
                                    name="instr_reminder_pending_uniq"),
        ]
        indexes = [models.Index(fields=["state", "moment"], name="instr_reminder_state_moment")]

    def __str__(self) -> str:
        return f"{self.instruction_id}: {self.stage}"


class InstructionSettings(models.Model):
    """Настройки поручений: одна строка `pk=1`."""

    retention_years = models.PositiveSmallIntegerField("срок хранения, лет", default=3)
    default_ladder = models.JSONField("умолчание лестницы", default=dict, blank=True)
    updated_at = models.DateTimeField("изменено", default=timezone.now)
    updated_by = models.ForeignKey("core.User", verbose_name="изменил", on_delete=models.SET_NULL, null=True,
                                   blank=True, related_name="+")

    class Meta:
        default_permissions = ()
        constraints = [
            models.CheckConstraint(condition=Q(retention_years__gte=1, retention_years__lte=10),
                                   name="instr_settings_retention_range"),
        ]


class InstructionTask(models.Model):
    """Связь поручения с задачей среза 009."""

    instruction = models.ForeignKey(Instruction, verbose_name="поручение", on_delete=models.CASCADE,
                                    related_name="task_links")
    task = models.ForeignKey("tasks.Task", verbose_name="задача", on_delete=models.CASCADE,
                             related_name="instruction_links")
    created_by = models.ForeignKey("core.User", verbose_name="связал", on_delete=models.PROTECT,
                                   related_name="instruction_task_links")
    created_at = models.DateTimeField("создано", default=timezone.now)

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["instruction", "task"], name="instr_task_uniq")]
        indexes = [models.Index(fields=["task"], name="instr_task_task")]