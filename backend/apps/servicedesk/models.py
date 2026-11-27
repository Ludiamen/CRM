"""Модели сервис-деска: Ticket, TicketEntry, TicketParticipant, Attachment, Queue, Category, Priority, Complexity, Status, Source, ClientUnit, Requester, RequesterImport, InboundMail, MailboxState, ServiceDeskSettings (PLAN-003, «Где живёт код»).

Модели `org` не импортируются: связи с узлом и пользователем заданы строками.
"""
from datetime import time

from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import Q
from django.utils import timezone


def now():
    """Время по умолчанию берётся при каждом обращении (подмена времени в тестах)."""
    return timezone.now()


def default_sla_workdays():
    """Рабочие дни SLA по умолчанию: понедельник — пятница."""
    return [0, 1, 2, 3, 4]


def name_key(text: str) -> str:
    """Ключ названия: без лишних пробелов, строчными, «ё» как «е» (как у узла структуры)."""
    return " ".join(text.split()).lower().replace("ё", "е")


class NamedModel(models.Model):
    """Общая часть справочников: название, ключ названия (уникален), строка — название."""

    name = models.CharField("название", max_length=100)
    name_key = models.CharField("ключ названия", max_length=100, unique=True)

    class Meta:
        abstract = True
        default_permissions = ()

    def save(self, *args, **kwargs):
        if not self.name_key:
            self.name_key = name_key(self.name)
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.name


class OrderedDictionary(NamedModel):
    """Справочник с порядком показа и архивом."""

    order = models.IntegerField("порядок", default=0)
    archived = models.BooleanField("в архиве", default=False)

    class Meta:
        abstract = True
        default_permissions = ()


class Priority(OrderedDictionary):
    """Критичность заявки."""

    class Meta:
        default_permissions = ()
        verbose_name = "критичность"
        verbose_name_plural = "критичности"


class Complexity(OrderedDictionary):
    """Сложность заявки."""

    class Meta:
        default_permissions = ()
        verbose_name = "сложность"
        verbose_name_plural = "уровни сложности"


class Status(OrderedDictionary):
    """Статус заявки; вид (`kind`) после создания не меняется."""

    class Kind(models.TextChoices):
        NEW = "new", "новая"
        IN_PROGRESS = "in_progress", "в работе"
        WAITING = "waiting", "ждёт ответа заявителя"
        CLOSED = "closed", "закрыта"

    kind = models.CharField("вид", max_length=16, choices=Kind.choices)
    is_default = models.BooleanField("по умолчанию", default=False)
    system_code = models.CharField("системный код", max_length=16, blank=True, default="")  # "" или "autoclosed"

    class Meta:
        default_permissions = ()
        verbose_name = "статус"
        verbose_name_plural = "статусы"
        constraints = [
            models.UniqueConstraint(fields=["kind"], condition=Q(is_default=True),
                                    name="servicedesk_status_one_default_per_kind"),
        ]


class Source(OrderedDictionary):
    """Источник заявки; `system_code` — `mail`, `form` или пусто (ручной источник)."""

    system_code = models.CharField("системный код", max_length=16, blank=True, default="")

    class Meta:
        default_permissions = ()
        verbose_name = "источник"
        verbose_name_plural = "источники"


class Category(OrderedDictionary):
    """Категория заявки; очередь пуста только у системной «Другое»."""

    queue = models.ForeignKey("org.Unit", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                              verbose_name="очередь")
    default_assignee = models.ForeignKey("core.User", on_delete=models.PROTECT, null=True, blank=True,
                                         related_name="+", verbose_name="ответственный по умолчанию")
    on_form = models.BooleanField("на форме", default=False)
    is_system = models.BooleanField("системная", default=False)

    class Meta:
        default_permissions = ()
        verbose_name = "категория"
        verbose_name_plural = "категории"


class ClientUnit(NamedModel):
    """Подразделение-клиент (плоский список); поля `order` нет."""

    name = models.CharField("название", max_length=150)
    name_key = models.CharField("ключ названия", max_length=150, unique=True)
    archived = models.BooleanField("в архиве", default=False)

    class Meta:
        default_permissions = ()
        verbose_name = "подразделение-клиент"
        verbose_name_plural = "подразделения-клиенты"


class Queue(models.Model):
    """Очередь — отметка узла: строка есть, значит узел принимает заявки."""

    unit = models.OneToOneField("org.Unit", on_delete=models.PROTECT, related_name="+", verbose_name="узел")
    created_at = models.DateTimeField("создана", default=now)
    created_by = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+",
                                   verbose_name="кто создал")

    class Meta:
        default_permissions = ()
        verbose_name = "очередь"
        verbose_name_plural = "очереди"


class QueueRule(models.Model):
    """Правило автораспределения заявок очереди (SPEC-012, FR-759…763)."""

    class Mode(models.TextChoices):
        OFF = "off", "выключен"
        EVENLY = "evenly", "равномерно"
        STRICTLY = "strictly", "строго по очереди"
        ALL = "all", "одновременно всем"

    queue = models.OneToOneField(Queue, on_delete=models.CASCADE, related_name="rule", verbose_name="очередь")
    mode = models.CharField("режим", max_length=16, choices=Mode.choices, default=Mode.OFF)
    last_assignee = models.ForeignKey("core.User", on_delete=models.SET_NULL, null=True, blank=True,
                                      related_name="+", verbose_name="последний назначенный")
    updated_by = models.ForeignKey("core.User", on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name="кто изменил")
    created_at = models.DateTimeField("создано", default=now)
    updated_at = models.DateTimeField("изменено", auto_now=True)

    class Meta:
        default_permissions = ()
        verbose_name = "правило очереди"
        verbose_name_plural = "правила очередей"

    def __str__(self) -> str:
        return f"{self.queue_id}: {self.mode}"


class QueueObserver(models.Model):
    """Наблюдатель очереди: читает её заявки, но не работает с ними (SPEC-012, FR-766…768)."""

    queue = models.ForeignKey(Queue, on_delete=models.CASCADE, related_name="observers", verbose_name="очередь")
    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="+", verbose_name="сотрудник")
    added_by = models.ForeignKey("core.User", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="+", verbose_name="кто добавил")
    added_at = models.DateTimeField("добавлен", default=now)
    removed_at = models.DateTimeField("снят", null=True, blank=True)
    removed_by = models.ForeignKey("core.User", on_delete=models.SET_NULL, null=True, blank=True,
                                   related_name="+", verbose_name="кто снял")

    class Meta:
        default_permissions = ()
        verbose_name = "наблюдатель очереди"
        verbose_name_plural = "наблюдатели очередей"
        constraints = [
            models.UniqueConstraint(fields=["queue", "user"], condition=Q(removed_at__isnull=True),
                                    name="servicedesk_observer_active_uniq"),
        ]
        indexes = [
            models.Index(fields=["queue", "removed_at"], name="sd_observer_queue_active"),
            models.Index(fields=["user", "removed_at"], name="sd_observer_user_active"),
        ]

    def __str__(self) -> str:
        return f"{self.queue_id}: {self.user_id}"


class ServiceDeskSettings(models.Model):
    """Настройки сервис-деска: одна строка, `pk=1`. Границы значений проверяет служба настроек."""

    domains = models.JSONField("домены", default=list)
    default_queue = models.ForeignKey("org.Unit", on_delete=models.PROTECT, null=True, blank=True,
                                      related_name="+", verbose_name="очередь по умолчанию")
    default_priority = models.ForeignKey(Priority, on_delete=models.PROTECT, related_name="+",
                                         verbose_name="критичность по умолчанию")
    autoclose_days = models.PositiveIntegerField("автозакрытие, дней", default=7)
    reopen_days = models.PositiveIntegerField("повторное открытие, дней", default=7)
    form_hourly_limit = models.PositiveIntegerField("писем с формы в час", default=10)
    retention_years = models.PositiveIntegerField("срок хранения, лет", default=3)
    inbound_retention_days = models.PositiveIntegerField("хранение входящих писем, дней", default=30)
    sla_reminder_hours = models.PositiveIntegerField("часы напоминания SLA", default=1)
    updated_at = models.DateTimeField("изменены", auto_now=True)

    class Meta:
        default_permissions = ()
        verbose_name = "настройки сервис-деска"
        verbose_name_plural = "настройки сервис-деска"
        constraints = [
            models.CheckConstraint(condition=Q(sla_reminder_hours__gte=1, sla_reminder_hours__lte=24),
                                   name="servicedesk_settings_sla_reminder_hours_1_24"),
        ]


class Requester(models.Model):
    """Заявитель: адрес хранится строчными и уникален."""

    class Origin(models.TextChoices):
        TABLE = "table", "таблица"
        TICKET = "ticket", "заявка"

    email = models.EmailField("адрес", max_length=254, unique=True)
    full_name = models.CharField("имя", max_length=255, blank=True, default="")
    client_unit = models.ForeignKey(ClientUnit, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                    verbose_name="подразделение-клиент")
    origin = models.CharField("происхождение", max_length=8, choices=Origin.choices, default=Origin.TICKET)
    created_at = models.DateTimeField("создан", default=now)
    updated_at = models.DateTimeField("изменён", auto_now=True)

    class Meta:
        default_permissions = ()
        verbose_name = "заявитель"
        verbose_name_plural = "заявители"

    def save(self, *args, **kwargs):
        self.email = self.email.strip().lower()
        super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.email


class RequesterImport(models.Model):
    """Загрузка заявителей из файла: предпросмотр и выполнение."""

    class FileFormat(models.TextChoices):
        CSV = "csv", "CSV"
        XLSX = "xlsx", "XLSX"

    class State(models.TextChoices):
        PREVIEW = "preview", "предпросмотр"
        DONE = "done", "выполнена"

    created_by = models.ForeignKey("core.User", on_delete=models.PROTECT, related_name="+", verbose_name="кто загрузил")
    created_at = models.DateTimeField("создана", default=now)
    file_name = models.CharField("имя файла", max_length=255)
    file_format = models.CharField("формат", max_length=8, choices=FileFormat.choices)
    state = models.CharField("состояние", max_length=8, choices=State.choices, default=State.PREVIEW)
    delete_missing = models.BooleanField("удалить отсутствующих", default=False)
    rows = models.JSONField("строки", default=list)
    summary = models.JSONField("итог", default=dict)
    new_units = models.JSONField("новые подразделения", default=list)

    class Meta:
        default_permissions = ()
        verbose_name = "загрузка заявителей"
        verbose_name_plural = "загрузки заявителей"


class InboundMail(models.Model):
    """Входящее письмо: основа «ровно один раз» — пара `(uidvalidity, uid)`."""

    class Status(models.TextChoices):
        RECEIVED = "received", "получено"
        PROCESSED = "processed", "обработано"
        WAITING_SETUP = "waiting_setup", "ждёт настройки"
        ERROR = "error", "ошибка"

    class Outcome(models.TextChoices):
        CREATED = "created", "создана заявка"
        APPENDED = "appended", "добавлено в заявку"
        REOPENED = "reopened", "открыта заново"
        REJECTED_DOMAIN = "rejected_domain", "отклонено: чужой домен"
        REJECTED_SELF = "rejected_self", "отклонено: письмо с адреса ящика заявок"
        AUTO = "auto", "автоматическое письмо"
        WAITING_SETUP = "waiting_setup", "ждёт настройки очереди по умолчанию"
        PARSE_ERROR = "parse_error", "ошибка разбора"

    uidvalidity = models.BigIntegerField("UIDVALIDITY")
    uid = models.BigIntegerField("UID")
    message_id = models.CharField("Message-ID", max_length=255, blank=True, default="", db_index=True)
    internal_date = models.DateTimeField("время в ящике")
    received_at = models.DateTimeField("забрано", default=now)
    size = models.PositiveIntegerField("размер, байт")
    raw_deleted = models.BooleanField("файл письма стёрт", default=False)
    from_email = models.CharField("отправитель", max_length=254, blank=True, default="")
    subject = models.CharField("тема", max_length=255, blank=True, default="")
    status = models.CharField("состояние", max_length=16, choices=Status.choices, default=Status.RECEIVED)
    outcome = models.CharField("итог", max_length=16, choices=Outcome.choices, blank=True, default="")
    ticket = models.ForeignKey("servicedesk.Ticket", on_delete=models.SET_NULL, null=True, blank=True,
                               related_name="inbound_mails", verbose_name="заявка")
    attempts = models.PositiveIntegerField("попыток", default=0)
    last_error = models.TextField("последняя ошибка", blank=True, default="")
    processed_at = models.DateTimeField("обработано", null=True, blank=True)

    class Meta:
        default_permissions = ()
        verbose_name = "входящее письмо"
        verbose_name_plural = "входящие письма"
        constraints = [
            models.UniqueConstraint(fields=["uidvalidity", "uid"], name="servicedesk_inbound_uidvalidity_uid_uniq"),
        ]


class MailboxState(models.Model):
    """Состояние ящика заявок: одна строка, `pk=1`; на пустой базе строки нет."""

    uidvalidity = models.BigIntegerField("UIDVALIDITY", null=True, blank=True)
    last_uid = models.BigIntegerField("последний UID", null=True, blank=True)
    connected_at = models.DateTimeField("подключение", null=True, blank=True)
    last_poll_at = models.DateTimeField("последний опрос", null=True, blank=True)
    last_ok_at = models.DateTimeField("последний удачный опрос", null=True, blank=True)
    last_error = models.TextField("последняя ошибка", blank=True, default="")

    class Meta:
        default_permissions = ()
        verbose_name = "состояние ящика"
        verbose_name_plural = "состояние ящика"


class Ticket(models.Model):
    """Заявка. Номер выдаёт последовательность базы `servicedesk_ticket_number` (служба заявок)."""

    class MessageFrom(models.TextChoices):
        REQUESTER = "requester", "заявитель"
        STAFF = "staff", "исполнитель"

    number = models.PositiveIntegerField("номер", unique=True)
    subject = models.CharField("тема", max_length=255)
    requester = models.ForeignKey(Requester, on_delete=models.PROTECT, null=True, blank=True,
                                  related_name="tickets", verbose_name="заявитель")
    requester_email = models.CharField("адрес заявителя", max_length=254, default="")
    requester_name = models.CharField("имя заявителя", max_length=255, blank=True, default="")
    client_unit = models.ForeignKey(ClientUnit, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                    verbose_name="подразделение-клиент")
    category = models.ForeignKey(Category, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                 verbose_name="категория")
    queue = models.ForeignKey("org.Unit", on_delete=models.PROTECT, related_name="+", verbose_name="очередь")
    priority = models.ForeignKey(Priority, on_delete=models.PROTECT, related_name="+", verbose_name="критичность")
    priority_order = models.PositiveSmallIntegerField("порядок критичности", default=0)
    complexity = models.ForeignKey(Complexity, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                   verbose_name="сложность")
    status = models.ForeignKey(Status, on_delete=models.PROTECT, related_name="+", verbose_name="статус")
    kind = models.CharField("вид статуса", max_length=16, choices=Status.Kind.choices)
    sla = models.ForeignKey("servicedesk.SlaLevel", on_delete=models.SET_NULL, null=True, blank=True,
                            related_name="tickets", verbose_name="уровень SLA")
    sla_cycle_started_at = models.DateTimeField("начало цикла SLA", null=True, blank=True)
    sla_reaction_due = models.DateTimeField("срок реакции SLA", null=True, blank=True)
    sla_solution_due = models.DateTimeField("срок решения SLA", null=True, blank=True)
    sla_first_response_at = models.DateTimeField("первый ответ SLA", null=True, blank=True)
    source = models.ForeignKey(Source, on_delete=models.PROTECT, related_name="+", verbose_name="источник")
    assignee = models.ForeignKey("core.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                 verbose_name="ответственный")
    assigned_once = models.BooleanField("ответственный уже был", default=False)
    created_at = models.DateTimeField("создана", default=now)
    created_by = models.ForeignKey("core.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                   verbose_name="кто создал")
    closed_at = models.DateTimeField("закрыта", null=True, blank=True)
    closed_by = models.ForeignKey("core.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                  verbose_name="кто закрыл")
    resolution = models.TextField("решение", blank=True, default="")
    previous = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="continuations", verbose_name="предыдущая заявка")
    consent_at = models.DateTimeField("согласие на форме", null=True, blank=True)
    waiting_since = models.DateTimeField("ждёт ответа с", null=True, blank=True)
    last_message_at = models.DateTimeField("последнее сообщение")
    last_message_from = models.CharField("от кого последнее сообщение", max_length=16, choices=MessageFrom.choices,
                                         blank=True, default="")
    search = SearchVectorField("поиск", null=True)
    search_len = models.PositiveIntegerField("знаков в поиске", default=0)
    anonymized_at = models.DateTimeField("обезличена", null=True, blank=True)
    updated_at = models.DateTimeField("изменена", auto_now=True)

    class Meta:
        default_permissions = ()
        verbose_name = "заявка"
        verbose_name_plural = "заявки"
        indexes = [
            models.Index(fields=["queue", "kind"], name="servicedesk_ticket_queue_kind"),
            models.Index(fields=["queue", "kind", "sla_solution_due"], name="servicedesk_ticket_board_sort"),
            models.Index(fields=["status", "sla_solution_due"], name="sd_ticket_board_status"),
            models.Index(fields=["status", "sla_solution_due", "priority_order", "-last_message_at", "number"],
                         name="sd_ticket_board_sort2"),
            models.Index(fields=["assignee", "kind"], name="servicedesk_ticket_asg_kind"),
            models.Index(fields=["queue"], name="servicedesk_ticket_unassigned",
                         condition=Q(assignee__isnull=True) & ~Q(kind="closed")),
            models.Index(fields=["waiting_since"], name="servicedesk_ticket_waiting", condition=Q(kind="waiting")),
            models.Index(fields=["closed_at"], name="servicedesk_ticket_closed",
                         condition=Q(kind="closed") & Q(anonymized_at__isnull=True)),
            models.Index(fields=["created_at"], name="servicedesk_ticket_created"),
            models.Index(fields=["last_message_at"], name="servicedesk_ticket_last_msg"),
            models.Index(fields=["sla_reaction_due"], name="sd_ticket_sla_reaction",
                         condition=~Q(kind="closed")),
            models.Index(fields=["sla_solution_due"], name="sd_ticket_sla_solution",
                         condition=~Q(kind="closed")),
            GinIndex(fields=["search"], name="servicedesk_ticket_search_gin"),
        ]

    def __str__(self) -> str:
        return f"#{self.number}"


class SlaLevel(models.Model):
    """Уровень обслуживания и его рабочее расписание."""

    title = models.CharField("название", max_length=100)
    priority = models.PositiveIntegerField("приоритет", default=0)
    reaction_minutes = models.PositiveIntegerField("реакция, минут")
    solution_minutes = models.PositiveIntegerField("решение, минут")
    workdays = models.JSONField("рабочие дни", default=default_sla_workdays)
    day_start = models.TimeField("начало рабочего дня", default=time(9, 0))
    day_end = models.TimeField("конец рабочего дня", default=time(18, 0))
    all_day = models.BooleanField("круглосуточно", default=False)
    default_assignee = models.ForeignKey("core.User", on_delete=models.PROTECT, null=True, blank=True,
                                         related_name="default_sla_levels", verbose_name="ответственный по умолчанию")
    archived = models.BooleanField("в архиве", default=False)
    created_at = models.DateTimeField("создан", default=now)
    updated_at = models.DateTimeField("изменён", auto_now=True)

    class Meta:
        default_permissions = ()
        verbose_name = "уровень SLA"
        verbose_name_plural = "уровни SLA"
        constraints = [
            models.CheckConstraint(condition=Q(priority__gte=0, priority__lte=99),
                                   name="servicedesk_sla_level_priority_0_99"),
            models.CheckConstraint(condition=Q(reaction_minutes__gte=5, reaction_minutes__lte=43200),
                                   name="servicedesk_sla_level_reaction_5_43200"),
            models.CheckConstraint(condition=Q(solution_minutes__gte=5, solution_minutes__lte=43200),
                                   name="servicedesk_sla_level_solution_5_43200"),
            models.CheckConstraint(condition=Q(reaction_minutes__lte=models.F("solution_minutes")),
                                   name="servicedesk_sla_level_reaction_lte_solution"),
            models.CheckConstraint(condition=Q(workdays__contained_by=[0, 1, 2, 3, 4, 5, 6]),
                                   name="servicedesk_sla_level_workdays_0_6"),
            models.CheckConstraint(condition=Q(all_day=True) | Q(day_start__lt=models.F("day_end")),
                                   name="servicedesk_sla_level_day_interval"),
        ]
        indexes = [
            models.Index(fields=["archived", "priority"], name="sd_sla_level_arch_prio"),
        ]


class SlaBinding(models.Model):
    """Привязка уровня SLA к категории или критичности."""

    class Kind(models.TextChoices):
        CATEGORY = "category", "категория"
        PRIORITY = "priority", "критичность"

    level = models.ForeignKey(SlaLevel, on_delete=models.CASCADE, related_name="bindings", verbose_name="уровень SLA")
    kind = models.CharField("вид", max_length=10, choices=Kind.choices)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="sla_bindings", verbose_name="категория")
    priority = models.ForeignKey(Priority, on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="sla_bindings", verbose_name="критичность")

    class Meta:
        default_permissions = ()
        verbose_name = "привязка уровня SLA"
        verbose_name_plural = "привязки уровней SLA"
        constraints = [
            models.CheckConstraint(
                condition=(Q(kind="category", category__isnull=False, priority__isnull=True)
                           | Q(kind="priority", category__isnull=True, priority__isnull=False)),
                name="servicedesk_sla_binding_kind_one_field"),
            models.UniqueConstraint(fields=["category"], condition=Q(kind="category"),
                                    name="servicedesk_sla_binding_category_uniq"),
            models.UniqueConstraint(fields=["priority"], condition=Q(kind="priority"),
                                    name="servicedesk_sla_binding_priority_uniq"),
        ]


class AnswerTemplate(models.Model):
    """Личный или общий шаблон ответа."""

    owner = models.ForeignKey("core.User", on_delete=models.CASCADE, null=True, blank=True,
                              related_name="answer_templates", verbose_name="владелец")
    title = models.CharField("название", max_length=100)
    text = models.TextField("текст", max_length=10000)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, null=True, blank=True,
                                 related_name="answer_templates", verbose_name="категория")
    archived = models.BooleanField("в архиве", default=False)
    created_at = models.DateTimeField("создан", default=now)
    updated_at = models.DateTimeField("изменён", auto_now=True)

    class Meta:
        default_permissions = ()
        verbose_name = "шаблон ответа"
        verbose_name_plural = "шаблоны ответов"
        constraints = [
            models.CheckConstraint(condition=Q(owner__isnull=True) | Q(category__isnull=True),
                                   name="servicedesk_answer_template_personal_no_category"),
        ]
        indexes = [
            models.Index(fields=["owner", "archived"], name="servicedesk_answer_owner_arch"),
            models.Index(fields=["category"], name="servicedesk_answer_category"),
        ]


class SlaCycle(models.Model):
    """Исторический цикл SLA заявки со снимками уровня и расписания."""

    class ClosedKind(models.TextChoices):
        MANUAL = "manual", "вручную"
        AUTOCLOSED = "autoclosed", "автоматически"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="sla_cycles", verbose_name="заявка")
    number = models.PositiveIntegerField("номер цикла")
    is_current = models.BooleanField("текущий", default=True)
    level = models.ForeignKey(SlaLevel, on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="sla_cycles", verbose_name="уровень SLA")
    level_title = models.CharField("название уровня", max_length=100)
    queue = models.ForeignKey("org.Unit", on_delete=models.SET_NULL, null=True, blank=True,
                              related_name="sla_cycles", verbose_name="очередь")
    queue_name = models.CharField("название очереди", max_length=255)
    category = models.ForeignKey(Category, on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="sla_cycles", verbose_name="категория")
    category_name = models.CharField("название категории", max_length=255)
    assignee = models.ForeignKey("core.User", on_delete=models.SET_NULL, null=True, blank=True,
                                 related_name="sla_cycles", verbose_name="ответственный")
    assignee_name = models.CharField("имя ответственного", max_length=255)
    schedule = models.JSONField("расписание", default=dict)
    cycle_started_at = models.DateTimeField("начало цикла")
    reaction_due = models.DateTimeField("срок реакции")
    solution_due = models.DateTimeField("срок решения")
    first_response_at = models.DateTimeField("первый ответ", null=True, blank=True)
    reaction_minutes = models.PositiveIntegerField("реакция, минут", null=True, blank=True)
    closed_at = models.DateTimeField("закрыт", null=True, blank=True)
    solution_minutes = models.PositiveIntegerField("решение, минут", null=True, blank=True)
    closed_kind = models.CharField("вид закрытия", max_length=10, choices=ClosedKind.choices, null=True, blank=True)
    reaction_met = models.BooleanField("реакция в срок", null=True, blank=True)
    solution_met = models.BooleanField("решение в срок", null=True, blank=True)
    created_at = models.DateTimeField("создан", default=now)

    class Meta:
        default_permissions = ()
        verbose_name = "цикл SLA"
        verbose_name_plural = "циклы SLA"
        constraints = [
            models.UniqueConstraint(fields=["ticket", "number"], name="servicedesk_sla_cycle_ticket_number_uniq"),
            models.UniqueConstraint(fields=["ticket", "cycle_started_at"],
                                    name="servicedesk_sla_cycle_ticket_started_uniq"),
            models.UniqueConstraint(fields=["ticket"], condition=Q(is_current=True),
                                    name="servicedesk_sla_cycle_current_uniq"),
        ]
        indexes = [
            models.Index(fields=["closed_at"], name="servicedesk_sla_cycle_closed"),
            models.Index(fields=["cycle_started_at"], name="servicedesk_sla_cycle_started"),
            models.Index(fields=["level"], name="servicedesk_sla_cycle_level"),
            models.Index(fields=["queue"], name="servicedesk_sla_cycle_queue"),
            models.Index(fields=["category"], name="servicedesk_sla_cycle_category"),
            models.Index(fields=["ticket"], name="servicedesk_sla_cycle_open",
                         condition=Q(is_current=True, solution_met=False)),
        ]


class SlaNotice(models.Model):
    """Идемпотентная запись напоминания по сроку цикла."""

    class Deadline(models.TextChoices):
        REACTION = "reaction", "реакция"
        SOLUTION = "solution", "решение"

    class Kind(models.TextChoices):
        DUE_SOON = "due_soon", "скоро срок"
        OVERDUE = "overdue", "просрочено"

    cycle = models.ForeignKey(SlaCycle, on_delete=models.CASCADE, related_name="notices", verbose_name="цикл SLA")
    deadline = models.CharField("срок", max_length=8, choices=Deadline.choices)
    kind = models.CharField("вид", max_length=8, choices=Kind.choices)
    due_at = models.DateTimeField("срок",)
    recipient = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="sla_notices",
                                  verbose_name="получатель")
    sent_at = models.DateTimeField("отправлено", null=True, blank=True)

    class Meta:
        default_permissions = ()
        verbose_name = "уведомление SLA"
        verbose_name_plural = "уведомления SLA"
        constraints = [
            models.UniqueConstraint(fields=["cycle", "deadline", "kind", "due_at", "recipient"],
                                    name="servicedesk_sla_notice_key_uniq"),
        ]


class SlaDigest(models.Model):
    """Ежедневная сводка SLA для получателя."""

    recipient = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="sla_digests",
                                  verbose_name="получатель")
    day = models.DateField("день")
    units = models.JSONField("очереди", default=list)
    sent_at = models.DateTimeField("отправлено", null=True, blank=True)

    class Meta:
        default_permissions = ()
        verbose_name = "сводка SLA"
        verbose_name_plural = "сводки SLA"
        constraints = [
            models.UniqueConstraint(fields=["recipient", "day"], name="servicedesk_sla_digest_recipient_day_uniq"),
        ]


class TicketParticipant(models.Model):
    """Участник из копии письма; снятый остаётся строкой с `removed_at`."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="participants", verbose_name="заявка")
    email = models.CharField("адрес", max_length=254)
    name = models.CharField("имя", max_length=255, blank=True, default="")
    added_at = models.DateTimeField("добавлен", default=now)
    removed_at = models.DateTimeField("снят", null=True, blank=True)
    removed_by = models.ForeignKey("core.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                   verbose_name="кто снял")

    class Meta:
        default_permissions = ()
        verbose_name = "участник заявки"
        verbose_name_plural = "участники заявки"
        constraints = [
            models.UniqueConstraint(fields=["ticket", "email"], name="servicedesk_participant_ticket_email_uniq"),
        ]


class TicketEntry(models.Model):
    """Элемент ленты заявки: письмо, ответ, комментарий или событие."""

    class Kind(models.TextChoices):
        INCOMING = "incoming", "письмо"
        REPLY = "reply", "ответ"
        COMMENT = "comment", "комментарий"
        EVENT = "event", "событие"

    class SendState(models.TextChoices):
        WAITING_FILES = "waiting_files", "ждёт проверки файлов"
        QUEUED = "queued", "поставлен в очередь"
        NOT_SENT = "not_sent", "не отправлен"

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="entries", verbose_name="заявка")
    kind = models.CharField("вид", max_length=16, choices=Kind.choices)
    at = models.DateTimeField("время", default=now)
    author = models.ForeignKey("core.User", on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                               verbose_name="автор")
    author_email = models.CharField("адрес автора", max_length=254, blank=True, default="")
    author_name = models.CharField("имя автора", max_length=255, blank=True, default="")
    text = models.TextField("текст", blank=True, default="")
    event = models.CharField("код события", max_length=48, blank=True, default="")
    data = models.JSONField("данные", default=dict)
    inbound = models.ForeignKey(InboundMail, on_delete=models.SET_NULL, null=True, blank=True,
                                related_name="entries", verbose_name="входящее письмо")
    wait_flag = models.BooleanField("ждём ответа заявителя", default=False)
    send_state = models.CharField("отправка", max_length=16, choices=SendState.choices, blank=True, default="")
    mail = models.ForeignKey("mail.MailMessage", on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="+", verbose_name="письмо")
    resent_from = models.ForeignKey("self", on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="resends", verbose_name="повтор отправки")

    class Meta:
        default_permissions = ()
        verbose_name = "элемент ленты"
        verbose_name_plural = "лента заявки"
        indexes = [models.Index(fields=["ticket", "at", "id"], name="servicedesk_entry_ticket_at_id")]


class Attachment(models.Model):
    """Вложение: принятое (есть `file`) или не принятое (остаются имя, размер и причина)."""

    class Rejected(models.TextChoices):
        NONE = "", "принято"
        TOO_BIG = "too_big", "больше 20 МБ"
        MAIL_TOO_BIG = "mail_too_big", "письмо больше 50 МБ"
        EXECUTABLE = "executable", "исполняемый файл"
        ENCRYPTED = "encrypted", "архив с паролем"

    REJECT_TITLES = {code: title for code, title in Rejected.choices if code}

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="attachments", verbose_name="заявка")
    entry = models.ForeignKey(TicketEntry, on_delete=models.CASCADE, related_name="attachments",
                              verbose_name="элемент ленты")
    file = models.ForeignKey("core.StoredFile", on_delete=models.SET_NULL, null=True, blank=True,
                             related_name="+", verbose_name="файл")
    name = models.CharField("имя", max_length=255)
    size = models.PositiveBigIntegerField("размер, байт")
    inline = models.BooleanField("встроенная картинка", default=False)
    rejected = models.CharField("причина отказа", max_length=16, choices=Rejected.choices, blank=True, default="")
    created_at = models.DateTimeField("создано", default=now)

    class Meta:
        default_permissions = ()
        verbose_name = "вложение"
        verbose_name_plural = "вложения"


class TicketRating(models.Model):
    """Оценка заявителя за цикл заявки и ссылка без входа (SPEC-012, FR-769…772)."""

    ticket = models.ForeignKey(Ticket, on_delete=models.CASCADE, related_name="ratings", verbose_name="заявка")
    cycle_number = models.PositiveIntegerField("номер закрытия")
    closed_at_snapshot = models.DateTimeField("закрыта")
    token_hash = models.CharField("хеш кода", max_length=64, unique=True, null=True, blank=True)
    score = models.PositiveSmallIntegerField("оценка", null=True, blank=True)
    expires_at = models.DateTimeField("ссылка действует до")
    is_current = models.BooleanField("текущая", default=True)
    rated_at = models.DateTimeField("оценена", null=True, blank=True)
    created_at = models.DateTimeField("создана", default=now)
    updated_at = models.DateTimeField("изменена", auto_now=True)
    # Снимки для отчёта: передача заявки и архивирование справочников не меняют историю.
    queue_id = models.PositiveIntegerField("очередь, id", null=True, blank=True)
    queue_name = models.CharField("очередь", max_length=255, blank=True, default="")
    category_id = models.PositiveIntegerField("категория, id", null=True, blank=True)
    category_name = models.CharField("категория", max_length=255, blank=True, default="")
    assignee_id = models.PositiveIntegerField("исполнитель, id", null=True, blank=True)
    assignee_name = models.CharField("исполнитель", max_length=255, blank=True, default="")
    level_id = models.PositiveIntegerField("уровень, id", null=True, blank=True)
    level_title = models.CharField("уровень", max_length=100, blank=True, default="")

    class Meta:
        default_permissions = ()
        verbose_name = "оценка заявки"
        verbose_name_plural = "оценки заявок"
        constraints = [
            models.UniqueConstraint(fields=["ticket", "cycle_number"], name="servicedesk_rating_ticket_cycle_uniq"),
            models.UniqueConstraint(fields=["ticket"], condition=Q(is_current=True),
                                    name="servicedesk_rating_current_uniq"),
            models.CheckConstraint(condition=Q(score__isnull=True) | Q(score__gte=1, score__lte=5),
                                   name="servicedesk_rating_score_1_5"),
        ]
        indexes = [
            models.Index(fields=["is_current", "closed_at_snapshot"], name="sd_rating_current_closed"),
            models.Index(fields=["queue_id", "closed_at_snapshot"], name="sd_rating_queue_closed"),
        ]

    def __str__(self) -> str:
        return f"#{self.ticket_id}: {self.score or '—'}"
