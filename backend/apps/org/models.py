"""Модели оргструктуры: Unit, Membership, UnitRole, WorkCalendar, CalendarYear, SpecialDay, CalendarUpload, StaffImport (PLAN-002, «Где живёт код»)."""
from datetime import time

from django.db import models
from django.db.models import Q, Value

from apps.core.models._util import now


def default_work_weekdays():
    """Рабочие дни по умолчанию: понедельник — пятница (0 — понедельник)."""
    return [0, 1, 2, 3, 4]


class Unit(models.Model):
    """Узел структуры: отдел или команда; дерево на материализованном пути (FR-101…107)."""

    class Kind(models.TextChoices):
        DEPARTMENT = "department", "отдел"
        TEAM = "team", "команда"

    kind = models.CharField("вид", max_length=20, choices=Kind.choices)
    name = models.CharField("название", max_length=150)
    name_key = models.CharField("название для сравнения", max_length=150)
    description = models.TextField("описание", blank=True)
    parent = models.ForeignKey(
        "self", verbose_name="родитель", on_delete=models.PROTECT, null=True, blank=True, related_name="children")
    is_root = models.BooleanField("корень", default=False)
    path = models.TextField("путь", db_collation="C")
    depth = models.PositiveIntegerField("глубина")
    created_at = models.DateTimeField("создан", default=now)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["parent", "name_key"], name="org_unit_parent_name_key_uniq"),
            models.UniqueConstraint(fields=["is_root"], condition=Q(is_root=True), name="org_unit_single_root"),
            models.CheckConstraint(
                condition=Q(is_root=True, parent__isnull=True) | Q(is_root=False, parent__isnull=False),
                name="org_unit_root_has_no_parent"),
        ]
        indexes = [models.Index(fields=["path"], name="org_unit_path_like", opclasses=["text_pattern_ops"])]


class Membership(models.Model):
    """Членство сотрудника в узле с пометкой руководителя или заместителя (FR-110…114)."""

    class Mark(models.TextChoices):
        NONE = "", "нет"
        HEAD = "head", "руководитель"
        DEPUTY = "deputy", "заместитель"

    user = models.ForeignKey("core.User", verbose_name="сотрудник", on_delete=models.PROTECT, related_name="memberships")
    unit = models.ForeignKey(Unit, verbose_name="узел", on_delete=models.PROTECT, related_name="memberships")
    mark = models.CharField("пометка", max_length=10, choices=Mark.choices, blank=True, default="")
    created_at = models.DateTimeField("создано", default=now)
    created_by = models.ForeignKey("core.User", verbose_name="кем создано", on_delete=models.PROTECT, related_name="+")

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["user", "unit"], name="org_membership_user_unit_uniq")]


class UnitRole(models.Model):
    """Роль узла: даётся всем участникам узла (FR-120, FR-121)."""

    unit = models.ForeignKey(Unit, verbose_name="узел", on_delete=models.CASCADE, related_name="unit_roles")
    role = models.ForeignKey("core.Role", verbose_name="роль", on_delete=models.PROTECT, related_name="unit_roles")

    class Meta:
        default_permissions = ()
        constraints = [models.UniqueConstraint(fields=["unit", "role"], name="org_unitrole_unit_role_uniq")]


class WorkCalendar(models.Model):
    """Одна строка: рабочие дни недели и границы рабочего дня (FR-143)."""

    work_weekdays = models.JSONField("рабочие дни недели", default=default_work_weekdays)
    day_start = models.TimeField("начало рабочего дня", default=time(9, 0))
    day_end = models.TimeField("конец рабочего дня", default=time(18, 0))
    updated_at = models.DateTimeField("изменён", default=now)

    class Meta:
        default_permissions = ()
        # вторую строку не даёт уникальный индекс по константе (дополнение 28)
        constraints = [models.UniqueConstraint(Value(1), name="org_workcalendar_single_row")]


class CalendarYear(models.Model):
    """Год, для которого загружен производственный календарь (FR-145, FR-146)."""

    year = models.PositiveIntegerField("год", unique=True)
    loaded_at = models.DateTimeField("загружен", default=now)
    loaded_by = models.ForeignKey("core.User", verbose_name="кем загружен", on_delete=models.PROTECT, related_name="+")
    file_name = models.CharField("имя файла", max_length=255)
    totals = models.JSONField("итоги", default=dict)

    class Meta:
        default_permissions = ()


class SpecialDay(models.Model):
    """Особый день календаря: праздник, перенос, сокращённый день (FR-144, FR-145)."""

    class Kind(models.TextChoices):
        HOLIDAY = "holiday", "праздник"
        DAY_OFF = "day_off", "перенесённый выходной"
        WORKDAY = "workday", "перенесённый рабочий день"
        SHORT = "short", "сокращённый"

    class Origin(models.TextChoices):
        FILE = "file", "из файла"
        MANUAL = "manual", "вручную"

    date = models.DateField("дата", unique=True)
    kind = models.CharField("вид", max_length=20, choices=Kind.choices)
    origin = models.CharField("происхождение", max_length=20, choices=Origin.choices)
    changed_by = models.ForeignKey("core.User", verbose_name="кем изменён", on_delete=models.PROTECT, related_name="+")
    changed_at = models.DateTimeField("изменён", default=now)

    class Meta:
        default_permissions = ()


class CalendarUpload(models.Model):
    """Предпросмотр загрузки календаря; неподтверждённый стирается через сутки (FR-145)."""

    class State(models.TextChoices):
        PREVIEW = "preview", "предпросмотр"
        APPLIED = "applied", "применён"

    year = models.PositiveIntegerField("год")
    file_name = models.CharField("имя файла", max_length=255)
    days = models.JSONField("дни", default=list)
    totals = models.JSONField("итоги", default=dict)
    created_by = models.ForeignKey("core.User", verbose_name="кем создан", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField("создан", default=now)
    state = models.CharField("состояние", max_length=20, choices=State.choices, default=State.PREVIEW)

    class Meta:
        default_permissions = ()


class StaffImport(models.Model):
    """Загрузка сотрудников из файла: предпросмотр и итог (FR-136…142)."""

    class FileFormat(models.TextChoices):
        CSV = "csv", "CSV"
        XLSX = "xlsx", "XLSX"

    class State(models.TextChoices):
        PREVIEW = "preview", "предпросмотр"
        DONE = "done", "выполнена"

    created_by = models.ForeignKey("core.User", verbose_name="кем создана", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField("создана", default=now)
    file_name = models.CharField("имя файла", max_length=255)
    file_format = models.CharField("формат файла", max_length=10, choices=FileFormat.choices)
    state = models.CharField("состояние", max_length=20, choices=State.choices, default=State.PREVIEW)
    send_invites = models.BooleanField("отправить приглашения", default=False)
    rows = models.JSONField("строки", default=list)
    summary = models.JSONField("итоги", default=dict)

    class Meta:
        default_permissions = ()
