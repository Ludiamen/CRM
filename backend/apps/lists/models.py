"""Модели списков, полей, записей, значений и истории (PLAN-006, «Модель данных» → «Приложение `lists`»).

Внешние ключи на модели ядра заданы строками, с `related_name="+"`: обратных связей к ядру нет.
Номер заявки в `TicketLink` и узел структуры в `Access.unit_id` — числа без внешнего ключа (инвариант «модуль-приложение»).
"""
import re

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.utils import timezone

RESERVED_FIELD_CODES = frozenset({"title", "number", "new", "order"})


def now():
    """Время по умолчанию берётся при каждом обращении (подмена времени в тестах)."""
    return timezone.now()


def empty_list():
    """Пустой список по умолчанию для JSON (имя `list` в телах моделей занято полем)."""
    return []


def validate_field_code_not_reserved(value):
    """Код поля не может совпасть с системным полем или литеральным адресом настройки полей."""
    if value in RESERVED_FIELD_CODES:
        raise ValidationError("Этот код зарезервирован.", code="reserved")


class List(models.Model):
    """Список: пользовательская таблица записей; стартовые списки имеют устойчивый `code`."""

    code = models.CharField("код", max_length=40, blank=True, default="")
    name = models.CharField("название", max_length=100)
    description = models.CharField("описание", max_length=500, blank=True)
    next_number = models.PositiveIntegerField("следующий номер записи", default=1)
    next_field_no = models.PositiveIntegerField("следующий номер для кода поля", default=1)
    vectors_stale_since = models.DateTimeField("векторы поиска устарели с", null=True, blank=True)
    created_at = models.DateTimeField("создан", default=now)
    created_by = models.ForeignKey("core.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    updated_at = models.DateTimeField("изменён", default=now)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(Lower("name"), name="lists_list_name_ci_uniq"),
            models.UniqueConstraint(fields=["code"], condition=~Q(code=""), name="lists_list_code_uniq"),
        ]


class Field(models.Model):
    """Поле списка; «Название» записи строкой `Field` не хранится."""

    class Type(models.TextChoices):
        STRING = "string", "Строка"
        TEXT = "text", "Многострочный текст"
        NUMBER = "number", "Число"
        MONEY = "money", "Деньги"
        DATE = "date", "Дата"
        DATETIME = "datetime", "Дата и время"
        BOOL = "bool", "Да/нет"
        CHOICE = "choice", "Список значений"
        PERSON = "person", "Сотрудник"
        UNIT = "unit", "Подразделение"
        RECORD = "record", "Запись другого списка"
        FILE = "file", "Файл"

    list = models.ForeignKey(List, on_delete=models.CASCADE, related_name="fields")
    code = models.CharField(
        "код", max_length=40,
        validators=[RegexValidator(re.compile(r"^[a-z][a-z0-9_]*$"), "Код: латиница, цифры и «_», первая буква."),
                    validate_field_code_not_reserved])
    name = models.CharField("название", max_length=100)
    hint = models.CharField("подсказка", max_length=200, blank=True)
    type = models.CharField("тип", max_length=16, choices=Type.choices)
    required = models.BooleanField("обязательное", default=False)
    multiple = models.BooleanField("несколько значений", default=False)
    unique = models.BooleanField("уникальное", default=False)
    show_in_table = models.BooleanField("показывать в таблице", default=False)
    hidden = models.BooleanField("скрыто", default=False)
    default = models.JSONField("значение по умолчанию", null=True, blank=True)
    order = models.PositiveIntegerField("порядок")
    target = models.ForeignKey(
        List, on_delete=models.RESTRICT, null=True, blank=True, related_name="referring_fields")
    settings = models.JSONField("свойства типа", default=dict)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["list", "code"], name="lists_field_list_code_uniq"),
            models.UniqueConstraint("list", Lower("name"), name="lists_field_list_name_ci_uniq"),
            models.CheckConstraint(
                condition=Q(type="record", target__isnull=False) | (~Q(type="record") & Q(target__isnull=True)),
                name="lists_field_target_iff_record"),
        ]
        indexes = [models.Index(fields=["list", "order"], name="lists_field_list_order")]


class Choice(models.Model):
    """Значение поля «список значений»; архивное не предлагается при вводе."""

    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name="choices")
    title = models.CharField("название", max_length=100)
    order = models.PositiveIntegerField("порядок")
    archived = models.BooleanField("в архиве", default=False)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint("field", Lower("title"), name="lists_choice_field_title_ci_uniq"),
        ]
        indexes = [models.Index(fields=["field", "order"], name="lists_choice_field_order")]


class Record(models.Model):
    """Запись списка: значения в JSON по кодам полей, вектор поиска, версия для проверки одновременной правки."""

    list = models.ForeignKey(List, on_delete=models.PROTECT, related_name="records")
    number = models.PositiveIntegerField("номер")
    title = models.CharField("название", max_length=200)
    values = models.JSONField("значения", default=dict)
    archived = models.BooleanField("в архиве", default=False)
    archived_at = models.DateTimeField("перенесена в архив", null=True, blank=True)
    archived_by = models.ForeignKey("core.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    version = models.PositiveIntegerField("версия", default=1)
    search = SearchVectorField(null=True)
    created_at = models.DateTimeField("создана", default=now)
    created_by = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    updated_at = models.DateTimeField("изменена", default=now)
    updated_by = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["list", "number"], name="lists_record_list_number_uniq"),
            models.CheckConstraint(
                condition=Q(archived=True, archived_at__isnull=False) | Q(archived=False, archived_at__isnull=True),
                name="lists_record_archived_iff_archived_at"),
        ]
        indexes = [
            models.Index(fields=["list", "archived"], name="lists_record_list_archived"),
            GinIndex(fields=["search"], name="lists_record_search_gin"),
        ]


class UniqueValue(models.Model):
    """Нормализованное значение уникального поля: уникальность держит база."""

    list = models.ForeignKey(List, on_delete=models.CASCADE, related_name="+")
    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name="+")
    norm_value = models.CharField("нормализованное значение", max_length=500)
    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name="+")

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["list", "field", "norm_value"], name="lists_uniquevalue_list_field_norm_uniq"),
        ]
        indexes = [models.Index(fields=["record"], name="lists_uniquevalue_record")]


class Change(models.Model):
    """Строка истории записи; не меняется и не удаляется, кроме каскада при удалении записи."""

    class Kind(models.TextChoices):
        CREATED = "created", "создана"
        CHANGED = "changed", "изменена"
        IMPORTED = "imported", "изменена загрузкой"
        ARCHIVED = "archived", "перенесена в архив"
        RESTORED = "restored", "возвращена из архива"
        FILE_ADDED = "file_added", "файл добавлен"
        FILE_REMOVED = "file_removed", "файл удалён"

    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name="changes")
    at = models.DateTimeField("когда", default=now)
    actor = models.ForeignKey("core.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    kind = models.CharField("вид", max_length=16, choices=Kind.choices)
    changes = models.JSONField("изменения", default=list)
    via_import = models.BooleanField("создана загрузкой", default=False)

    class Meta:
        default_permissions = ()
        indexes = [models.Index(fields=["record", "at", "id"], name="lists_change_record_at")]


class Access(models.Model):
    """Право на список: роль или узел структуры (`unit_id` — число без внешнего ключа)."""

    class Level(models.TextChoices):
        READ = "read", "Читают"
        EDIT = "edit", "Правят"

    list = models.ForeignKey(List, on_delete=models.CASCADE, related_name="accesses")
    level = models.CharField("уровень", max_length=8, choices=Level.choices)
    role = models.ForeignKey("core.Role", on_delete=models.PROTECT, null=True, blank=True, related_name="+")
    unit_id = models.PositiveIntegerField("узел структуры", null=True, blank=True)

    class Meta:
        default_permissions = ()
        constraints = [
            models.CheckConstraint(
                condition=Q(role__isnull=False, unit_id__isnull=True) | Q(role__isnull=True, unit_id__isnull=False),
                name="lists_access_one_subject"),
            models.UniqueConstraint(
                fields=["list", "level", "role"], condition=Q(role__isnull=False),
                name="lists_access_list_level_role_uniq"),
            models.UniqueConstraint(
                fields=["list", "level", "unit_id"], condition=Q(unit_id__isnull=False),
                name="lists_access_list_level_unit_uniq"),
        ]
        indexes = [
            models.Index(fields=["role"], name="lists_access_role"),
            models.Index(fields=["unit_id"], name="lists_access_unit"),
        ]


class UserView(models.Model):
    """Личный набор столбцов таблицы списка (`title` — системное поле)."""

    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="+")
    list = models.ForeignKey(List, on_delete=models.CASCADE, related_name="+")
    columns = models.JSONField("столбцы", default=empty_list)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["user", "list"], name="lists_userview_user_list_uniq"),
        ]


class TicketLink(models.Model):
    """Связь записи с заявкой по номеру (без внешнего ключа на `servicedesk`)."""

    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name="ticket_links")
    ticket_number = models.PositiveIntegerField("номер заявки")
    linked_by = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    linked_at = models.DateTimeField("привязана", default=now)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["record", "ticket_number"], name="lists_ticketlink_record_ticket_uniq"),
        ]
        indexes = [models.Index(fields=["ticket_number"], name="lists_ticketlink_ticket")]


class ReminderSent(models.Model):
    """Отметка об отправленном (или пропущенном при нагоне) напоминании о сроке."""

    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name="+")
    field = models.ForeignKey(Field, on_delete=models.CASCADE, related_name="+")
    threshold_days = models.PositiveSmallIntegerField("порог, дней")
    due_date = models.DateField("срок на момент отметки")
    notified = models.BooleanField("уведомление отправлено")
    created_at = models.DateTimeField("создана", default=now)

    class Meta:
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["record", "field", "threshold_days", "due_date"], name="lists_remindersent_uniq"),
        ]


class ImportJob(models.Model):
    """Задание загрузки записей из файла; сам файл не хранится."""

    class State(models.TextChoices):
        MAPPING = "mapping", "сопоставление"
        PREVIEW = "preview", "проверка"
        DONE = "done", "готово"

    class Format(models.TextChoices):
        CSV = "csv", "CSV"
        XLSX = "xlsx", "XLSX"

    list = models.ForeignKey(List, on_delete=models.CASCADE, related_name="+")
    created_by = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField("создано", default=now)
    file_name = models.CharField("имя файла", max_length=255)
    file_format = models.CharField("формат файла", max_length=8, choices=Format.choices)
    state = models.CharField("состояние", max_length=8, choices=State.choices, default=State.MAPPING)
    header = models.JSONField("заголовок", default=empty_list)
    mapping = models.JSONField("сопоставление", default=dict)
    rows = models.JSONField("строки и итог проверки", default=empty_list)
    summary = models.JSONField("итог", default=dict)

    class Meta:
        default_permissions = ()
        indexes = [models.Index(fields=["state", "created_at"], name="lists_importjob_state_created")]


class RecordFile(models.Model):
    """Файл записи: файл ядра удаляет служба вместе с диском."""

    record = models.ForeignKey(Record, on_delete=models.CASCADE, related_name="files")
    field = models.ForeignKey(Field, on_delete=models.PROTECT, related_name="+")
    file = models.OneToOneField("core.StoredFile", on_delete=models.PROTECT, related_name="+")
    name = models.CharField("имя при загрузке", max_length=255)
    uploaded_by = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField("загружен", default=now)

    class Meta:
        default_permissions = ()
        indexes = [models.Index(fields=["record", "uploaded_at"], name="lists_recordfile_record_upl")]
