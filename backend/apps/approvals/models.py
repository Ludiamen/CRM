"""Модели среза 014 «Согласования» (PLAN-014, «Модель данных»).

Шаблон маршрута, его этапы и участники — настройка; маршрут, этапы-экземпляры, задания, маркеры
уведомлений и события — данные выполнения. Снимок этапов и участников хранится в экземплярах, поэтому
правка шаблона не меняет идущий маршрут. Имена ограничений и индексов — CONTRACT-014.
"""
from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.core.models._util import now


class ApprovalTemplate(models.Model):
    """Шаблон маршрута: название, субъект, описание, состояние и этапы."""

    class Subject(models.TextChoices):
        TICKET = "ticket", "Заявка"
        TASK = "task", "Задача"

    name = models.CharField("название", max_length=150)
    subject_type = models.CharField("субъект", max_length=16, choices=Subject.choices)
    description = models.TextField("описание", max_length=2000, blank=True, default="")
    enabled = models.BooleanField("включён", default=True)
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                               related_name="approval_templates", verbose_name="автор")
    created_at = models.DateTimeField("создан", default=now)
    updated_at = models.DateTimeField("изменён", auto_now=True)

    class Meta:
        default_permissions = ()
        verbose_name = "шаблон согласования"
        verbose_name_plural = "шаблоны согласования"
        ordering = ["subject_type", "name", "pk"]
        indexes = [models.Index(fields=["subject_type", "enabled"], name="approval_template_lookup")]
        constraints = [
            models.CheckConstraint(condition=Q(subject_type__in=("ticket", "task")),
                                   name="approval_template_subject"),
        ]

    def __str__(self) -> str:
        return self.name


class ApprovalStage(models.Model):
    """Этап шаблона: порядок, режим, правило, срок и участники."""

    class Mode(models.TextChoices):
        SEQUENTIAL = "sequential", "Последовательно"
        PARALLEL = "parallel", "Параллельно"

    class Rule(models.TextChoices):
        ALL = "all", "Ждут всех"
        ANY = "any", "Достаточно одного"

    template = models.ForeignKey(ApprovalTemplate, on_delete=models.CASCADE, related_name="stages",
                                 verbose_name="шаблон")
    order = models.PositiveSmallIntegerField("порядок")
    title = models.CharField("название", max_length=100)
    mode = models.CharField("режим", max_length=16, choices=Mode.choices, default=Mode.SEQUENTIAL)
    rule = models.CharField("правило", max_length=8, choices=Rule.choices, default=Rule.ALL)
    deadline_hours = models.PositiveSmallIntegerField("срок, часов", null=True, blank=True)

    class Meta:
        default_permissions = ()
        verbose_name = "этап шаблона"
        verbose_name_plural = "этапы шаблона"
        ordering = ["template", "order"]
        constraints = [
            models.UniqueConstraint(fields=["template", "order"], name="approval_stage_template_order_uniq"),
            models.CheckConstraint(condition=Q(order__gte=1) & Q(order__lte=20),
                                   name="approval_stage_order_range"),
            models.CheckConstraint(condition=Q(deadline_hours__isnull=True)
                                   | (Q(deadline_hours__gte=1) & Q(deadline_hours__lte=720)),
                                   name="approval_stage_deadline_range"),
            models.CheckConstraint(condition=~Q(mode="sequential") | Q(rule="all"),
                                   name="approval_stage_sequential_rule"),
        ]

    def __str__(self) -> str:
        return f"{self.order}. {self.title}"


class ApprovalStageParticipant(models.Model):
    """Источник участника этапа: сотрудник, руководитель подразделения или руководитель очереди."""

    class Kind(models.TextChoices):
        EMPLOYEE = "employee", "Сотрудник"
        UNIT_HEAD = "unit_head", "Руководитель подразделения"
        QUEUE_HEAD = "queue_head", "Руководитель очереди"

    stage = models.ForeignKey(ApprovalStage, on_delete=models.CASCADE, related_name="participants",
                              verbose_name="этап")
    order = models.PositiveSmallIntegerField("порядок", default=0)
    kind = models.CharField("вид", max_length=16, choices=Kind.choices, default=Kind.EMPLOYEE)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, null=True, blank=True,
                             related_name="approval_participations", verbose_name="сотрудник")
    unit = models.ForeignKey("org.Unit", on_delete=models.PROTECT, null=True, blank=True,
                             related_name="+", verbose_name="подразделение")

    class Meta:
        default_permissions = ()
        verbose_name = "участник этапа"
        verbose_name_plural = "участники этапа"
        ordering = ["stage", "order", "pk"]
        indexes = [models.Index(fields=["stage", "order"], name="approval_participant_order")]
        constraints = [
            models.CheckConstraint(
                condition=Q(kind="employee", user__isnull=False, unit__isnull=True)
                | Q(kind="unit_head", unit__isnull=False, user__isnull=True)
                | Q(kind="queue_head", user__isnull=True, unit__isnull=True),
                name="approval_participant_kind_fields"),
            models.UniqueConstraint(fields=["stage", "user"], condition=Q(kind="employee"),
                                    name="approval_participant_employee_uniq"),
            models.UniqueConstraint(fields=["stage", "unit"], condition=Q(kind="unit_head"),
                                    name="approval_participant_unit_uniq"),
            models.UniqueConstraint(fields=["stage", "kind"], condition=Q(kind="queue_head"),
                                    name="approval_participant_queue_head_uniq"),
        ]

    def __str__(self) -> str:
        return f"{self.stage_id}: {self.get_kind_display()}"


class ApprovalRoute(models.Model):
    """Экземпляр маршрута: субъект, снимок названия шаблона, инициатор и состояние."""

    class Status(models.TextChoices):
        RUNNING = "running", "Идёт"
        APPROVED = "approved", "Согласовано"
        REJECTED = "rejected", "Отклонено"
        RETURNED = "returned", "Возвращено"
        CANCELLED = "cancelled", "Отменено"

    template = models.ForeignKey(ApprovalTemplate, on_delete=models.PROTECT, related_name="routes",
                                 verbose_name="шаблон")
    template_name = models.CharField("название шаблона", max_length=150)
    subject_type = models.CharField("субъект", max_length=16, choices=ApprovalTemplate.Subject.choices)
    subject_id = models.PositiveBigIntegerField("номер субъекта")
    subject_number = models.PositiveIntegerField("номер для показа")
    initiator = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                                  related_name="approval_routes", verbose_name="инициатор")
    status = models.CharField("состояние", max_length=16, choices=Status.choices, default=Status.RUNNING)
    started_at = models.DateTimeField("запущен", default=now)
    finished_at = models.DateTimeField("завершён", null=True, blank=True)
    cancelled_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                                     related_name="+", verbose_name="отменил")

    class Meta:
        default_permissions = ()
        verbose_name = "маршрут согласования"
        verbose_name_plural = "маршруты согласования"
        ordering = ["-started_at", "-pk"]
        indexes = [
            models.Index(fields=["subject_type", "subject_id", "started_at"],
                         name="approval_route_subject"),
            models.Index(fields=["subject_type", "subject_number", "started_at"],
                         name="approval_route_number"),
            models.Index(fields=["status", "finished_at"], name="approval_route_status"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["subject_type", "subject_id"], condition=Q(status="running"),
                                    name="approval_route_one_running"),
            models.CheckConstraint(condition=Q(subject_type__in=("ticket", "task")),
                                   name="approval_route_subject_type"),
            models.CheckConstraint(condition=Q(subject_id__gt=0) & Q(subject_number__gt=0),
                                   name="approval_route_numbers_positive"),
        ]

    def __str__(self) -> str:
        return f"Маршрут {self.pk}: {self.template_name}"


class ApprovalStageRun(models.Model):
    """Снимок этапа в маршруте."""

    class Status(models.TextChoices):
        WAITING = "waiting", "Ждёт"
        RUNNING = "running", "Идёт"
        DONE = "done", "Завершён"
        CANCELLED = "cancelled", "Отменён"

    route = models.ForeignKey(ApprovalRoute, on_delete=models.CASCADE, related_name="stages",
                              verbose_name="маршрут")
    order = models.PositiveSmallIntegerField("порядок")
    title = models.CharField("название", max_length=100)
    mode = models.CharField("режим", max_length=16, choices=ApprovalStage.Mode.choices)
    rule = models.CharField("правило", max_length=8, choices=ApprovalStage.Rule.choices)
    deadline_hours = models.PositiveSmallIntegerField("срок, часов", null=True, blank=True)
    status = models.CharField("состояние", max_length=16, choices=Status.choices, default=Status.WAITING)
    started_at = models.DateTimeField("начат", null=True, blank=True)
    finished_at = models.DateTimeField("завершён", null=True, blank=True)
    due_at = models.DateTimeField("срок", null=True, blank=True)

    class Meta:
        default_permissions = ()
        verbose_name = "этап маршрута"
        verbose_name_plural = "этапы маршрута"
        ordering = ["route", "order"]
        indexes = [models.Index(fields=["route", "status"], name="approval_stage_run_status")]
        constraints = [
            models.UniqueConstraint(fields=["route", "order"], name="approval_stage_run_route_order_uniq"),
            models.CheckConstraint(condition=Q(order__gte=1) & Q(order__lte=20),
                                   name="approval_stage_run_order_range"),
        ]

    def __str__(self) -> str:
        return f"{self.order}. {self.title}"


class ApprovalAssignment(models.Model):
    """Задание участнику: одна строка на этап-экземпляр и сотрудника."""

    class Status(models.TextChoices):
        PENDING = "pending", "Ждёт решения"
        APPROVED = "approved", "Согласовано"
        REJECTED = "rejected", "Отклонено"
        RETURNED = "returned", "На доработку"
        CANCELLED = "cancelled", "Отменено"

    class Decision(models.TextChoices):
        APPROVED = "approved", "Согласовано"
        REJECTED = "rejected", "Отклонено"
        RETURNED = "returned", "На доработку"

    stage_run = models.ForeignKey(ApprovalStageRun, on_delete=models.CASCADE, related_name="assignments",
                                  verbose_name="этап")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
                             related_name="approval_assignments", verbose_name="участник")
    order = models.PositiveSmallIntegerField("порядок", default=0)
    status = models.CharField("состояние", max_length=16, choices=Status.choices, default=Status.PENDING)
    decision = models.CharField("решение", max_length=16, choices=Decision.choices, null=True, blank=True)
    comment = models.TextField("комментарий", max_length=4000, blank=True, default="")
    created_at = models.DateTimeField("создано", default=now)
    due_at = models.DateTimeField("срок", null=True, blank=True)
    decided_at = models.DateTimeField("решено", null=True, blank=True)

    class Meta:
        default_permissions = ()
        verbose_name = "задание согласования"
        verbose_name_plural = "задания согласования"
        ordering = ["stage_run", "order", "pk"]
        indexes = [
            models.Index(fields=["user", "status", "due_at"], name="approval_assignment_queue"),
            models.Index(fields=["stage_run", "status"], name="approval_assignment_stage"),
        ]
        constraints = [
            models.UniqueConstraint(fields=["stage_run", "user"], name="approval_assignment_stage_user_uniq"),
            models.CheckConstraint(condition=~Q(status="pending") | Q(decision__isnull=True),
                                   name="approval_assignment_pending_decision"),
            models.CheckConstraint(
                condition=~Q(status__in=("approved", "rejected", "returned"))
                | (Q(decision=F("status")) & Q(decided_at__isnull=False)),
                name="approval_assignment_decided"),
            models.CheckConstraint(condition=~Q(status="cancelled") | Q(decision__isnull=True),
                                   name="approval_assignment_cancelled"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id}: {self.get_status_display()}"


class ApprovalNotice(models.Model):
    """Маркер отправленного напоминания или уведомления о сроке."""

    class Kind(models.TextChoices):
        REMINDER = "reminder", "Напоминание за 24 часа"
        OVERDUE = "overdue", "Срок наступил"

    assignment = models.ForeignKey(ApprovalAssignment, on_delete=models.CASCADE, related_name="notices",
                                   verbose_name="задание")
    kind = models.CharField("вид", max_length=16, choices=Kind.choices)
    sent_at = models.DateTimeField("отправлено", default=now)

    class Meta:
        default_permissions = ()
        verbose_name = "маркер уведомления"
        verbose_name_plural = "маркеры уведомлений"
        indexes = [models.Index(fields=["kind", "sent_at"], name="approval_notice_kind")]
        constraints = [
            models.UniqueConstraint(fields=["assignment", "kind"], name="approval_notice_assignment_kind_uniq"),
        ]


class ApprovalEvent(models.Model):
    """Событие маршрута; только дописывается."""

    class Kind(models.TextChoices):
        STARTED = "started", "Запуск"
        STAGE_COMPLETED = "stage_completed", "Этап завершён"
        DECISION = "decision", "Решение"
        REJECTED = "rejected", "Отклонено"
        RETURNED = "returned", "Возвращено"
        CANCELLED = "cancelled", "Отменено"
        ASSIGNMENT_CANCELLED = "assignment_cancelled", "Задание отменено"

    route = models.ForeignKey(ApprovalRoute, on_delete=models.CASCADE, related_name="events",
                              verbose_name="маршрут")
    kind = models.CharField("вид", max_length=24, choices=Kind.choices)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="+", verbose_name="автор")
    data = models.JSONField("данные", default=dict, blank=True)
    at = models.DateTimeField("когда", default=now)

    class Meta:
        default_permissions = ()
        verbose_name = "событие согласования"
        verbose_name_plural = "события согласования"
        ordering = ["route", "at", "pk"]
        indexes = [
            models.Index(fields=["route", "at"], name="approval_event_route"),
            models.Index(fields=["kind", "at"], name="approval_event_kind"),
        ]
