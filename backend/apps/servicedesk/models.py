"""Модели сервис-деска: Ticket, TicketEntry, TicketParticipant, Attachment, Queue, Category, Priority, Complexity, Status, Source, ClientUnit, Requester, RequesterImport, InboundMail, MailboxState, ServiceDeskSettings (PLAN-003, «Где живёт код»).

Модели `org` не импортируются: связи с узлом и пользователем заданы строками.
"""
from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVectorField
from django.db import models
from django.db.models import Q
from django.utils import timezone


def now():
    """Время по умолчанию берётся при каждом обращении (подмена времени в тестах)."""
    return timezone.now()


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
    updated_at = models.DateTimeField("изменены", auto_now=True)

    class Meta:
        default_permissions = ()
        verbose_name = "настройки сервис-деска"
        verbose_name_plural = "настройки сервис-деска"


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
    complexity = models.ForeignKey(Complexity, on_delete=models.PROTECT, null=True, blank=True, related_name="+",
                                   verbose_name="сложность")
    status = models.ForeignKey(Status, on_delete=models.PROTECT, related_name="+", verbose_name="статус")
    kind = models.CharField("вид статуса", max_length=16, choices=Status.Kind.choices)
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
            models.Index(fields=["assignee", "kind"], name="servicedesk_ticket_asg_kind"),
            models.Index(fields=["queue"], name="servicedesk_ticket_unassigned",
                         condition=Q(assignee__isnull=True) & ~Q(kind="closed")),
            models.Index(fields=["waiting_since"], name="servicedesk_ticket_waiting", condition=Q(kind="waiting")),
            models.Index(fields=["closed_at"], name="servicedesk_ticket_closed",
                         condition=Q(kind="closed") & Q(anonymized_at__isnull=True)),
            models.Index(fields=["created_at"], name="servicedesk_ticket_created"),
            models.Index(fields=["last_message_at"], name="servicedesk_ticket_last_msg"),
            GinIndex(fields=["search"], name="servicedesk_ticket_search_gin"),
        ]

    def __str__(self) -> str:
        return f"#{self.number}"


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
