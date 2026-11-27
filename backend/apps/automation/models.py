"""Модели автоматизации (срез 013, PLAN-013).

Четыре таблицы: правило, действие правила, запуск правила и запуск действия.
Правила адресуют субъект парой «тип + идентификатор», без полиморфного внешнего ключа.
Имена ограничений и индексов — CONTRACT-013, раздел 2.
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import Q

from apps.core.models._util import now


class Rule(models.Model):
    """Правило: субъект, событие, условия, действия и область."""

    class Subject(models.TextChoices):
        TICKET = "ticket", "Заявка"
        TASK = "task", "Задача"

    class Scope(models.TextChoices):
        GLOBAL = "global", "Все"
        QUEUE = "queue", "Очередь"
        TASK_AUTHOR = "task_author", "Задачи автора"

    name = models.CharField("название", max_length=150)
    subject_type = models.CharField("субъект", max_length=16, choices=Subject.choices)
    scope = models.CharField("область", max_length=16, choices=Scope.choices, default=Scope.GLOBAL)
    queue = models.ForeignKey("org.Unit", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                              verbose_name="очередь")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="automation_rules",
                               verbose_name="автор")
    trigger = models.CharField("событие", max_length=40)
    conditions = models.JSONField("условия", default=list, blank=True)
    priority = models.PositiveSmallIntegerField("приоритет", default=100)
    enabled = models.BooleanField("включено", default=False)
    created_at = models.DateTimeField("создано", default=now)
    updated_at = models.DateTimeField("изменено", auto_now=True)

    class Meta:
        default_permissions = ()
        verbose_name = "правило автоматизации"
        verbose_name_plural = "правила автоматизации"
        ordering = ["priority", "pk"]
        constraints = [
            models.CheckConstraint(condition=Q(priority__gte=1) & Q(priority__lte=999),
                                   name="automation_rule_priority_range"),
            models.CheckConstraint(
                condition=(Q(scope="queue") & Q(queue__isnull=False)) | (~Q(scope="queue") & Q(queue__isnull=True)),
                name="automation_rule_queue_scope"),
            models.CheckConstraint(
                condition=(Q(subject_type="ticket") & Q(scope__in=("global", "queue")))
                | (Q(subject_type="task") & Q(scope__in=("global", "task_author"))),
                name="automation_rule_subject_scope"),
        ]
        indexes = [
            models.Index(fields=["subject_type", "trigger", "enabled"], name="automation_rule_lookup"),
            models.Index(fields=["scope", "queue"], name="automation_rule_scope"),
        ]

    def __str__(self) -> str:
        return self.name


class RuleAction(models.Model):
    """Действие правила: порядок, код, параметры и задержка."""

    rule = models.ForeignKey(Rule, on_delete=models.CASCADE, related_name="actions")
    order = models.PositiveSmallIntegerField("порядок")
    kind = models.CharField("действие", max_length=24)
    params = models.JSONField("параметры", default=dict, blank=True)
    delay_seconds = models.PositiveIntegerField("задержка, секунд", default=0)

    class Meta:
        default_permissions = ()
        verbose_name = "действие правила"
        verbose_name_plural = "действия правила"
        ordering = ["rule", "order"]
        constraints = [
            models.UniqueConstraint(fields=["rule", "order"], name="automation_action_rule_order_uniq"),
            models.CheckConstraint(condition=Q(order__gte=1), name="automation_action_order_positive"),
            models.CheckConstraint(condition=Q(delay_seconds__lte=2_592_000),
                                   name="automation_action_delay_range"),
        ]

    def __str__(self) -> str:
        return f"{self.rule_id}:{self.order} {self.kind}"


class RuleRun(models.Model):
    """Запуск правила по событию; уникален по `(rule, event_id)`."""

    class Status(models.TextChoices):
        RUNNING = "running", "выполняется"
        DONE = "done", "выполнено"
        SKIPPED = "skipped", "пропущено"
        FAILED = "failed", "ошибка"

    rule = models.ForeignKey(Rule, on_delete=models.PROTECT, related_name="runs")
    subject_type = models.CharField("субъект", max_length=16, choices=Rule.Subject.choices)
    subject_id = models.PositiveBigIntegerField("номер субъекта")
    event = models.CharField("событие", max_length=40)
    event_id = models.CharField("идентификатор события", max_length=120)
    chain_id = models.UUIDField("цепочка", default=uuid.uuid4)
    root_run_id = models.UUIDField("корневой запуск", null=True, blank=True)
    depth = models.PositiveSmallIntegerField("глубина", default=1)
    status = models.CharField("состояние", max_length=16, choices=Status.choices, default=Status.RUNNING)
    reason = models.CharField("причина", max_length=255, blank=True, default="")
    created_at = models.DateTimeField("создан", default=now)
    finished_at = models.DateTimeField("завершён", null=True, blank=True)

    class Meta:
        default_permissions = ()
        verbose_name = "запуск правила"
        verbose_name_plural = "запуски правил"
        ordering = ["-created_at", "-pk"]
        constraints = [
            models.UniqueConstraint(fields=["rule", "event_id"], name="automation_run_rule_event_uniq"),
            models.CheckConstraint(condition=Q(depth__gte=1), name="automation_run_depth_positive"),
        ]
        indexes = [
            models.Index(fields=["subject_type", "subject_id", "created_at"], name="automation_run_subject"),
            models.Index(fields=["status", "created_at"], name="automation_run_status"),
            models.Index(fields=["chain_id"], name="automation_run_chain"),
        ]

    def __str__(self) -> str:
        return f"{self.rule_id} {self.event} {self.event_id}"


class RuleActionRun(models.Model):
    """Запуск действия: журнал и очередь отложенных действий."""

    class Status(models.TextChoices):
        PENDING = "pending", "ждёт срока"
        RUNNING = "running", "выполняется"
        DONE = "done", "выполнено"
        SKIPPED = "skipped", "пропущено"
        FAILED = "failed", "ошибка"

    run = models.ForeignKey(RuleRun, on_delete=models.CASCADE, related_name="actions")
    action = models.ForeignKey(RuleAction, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    order = models.PositiveSmallIntegerField("порядок")
    kind = models.CharField("действие", max_length=24)
    status = models.CharField("состояние", max_length=16, choices=Status.choices, default=Status.PENDING)
    reason = models.CharField("причина", max_length=255, blank=True, default="")
    due_at = models.DateTimeField("срок", null=True, blank=True)
    started_at = models.DateTimeField("начато", null=True, blank=True)
    finished_at = models.DateTimeField("завершено", null=True, blank=True)

    class Meta:
        default_permissions = ()
        verbose_name = "запуск действия"
        verbose_name_plural = "запуски действий"
        ordering = ["run", "order"]
        constraints = [
            models.UniqueConstraint(fields=["run", "order"], name="automation_action_run_order_uniq"),
        ]
        indexes = [
            models.Index(fields=["status", "due_at"], name="automation_action_due"),
        ]

    def __str__(self) -> str:
        return f"{self.run_id}:{self.order} {self.kind}"
