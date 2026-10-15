"""Модели уведомлений: Notification, Delivery, Digest, NotifySettings, UserNotifySettings, PushSubscription, ChatBinding, BindCode, BotChat, BotState (PLAN-004, «Где живёт код»).

Внешние ключи на модели ядра заданы строками, с `related_name="+"`: обратных связей к ядру нет.
"""
from django.db import models
from django.db.models import Q
from django.utils import timezone


def now():
    """Время по умолчанию берётся при каждом обращении (подмена времени в тестах)."""
    return timezone.now()


class MessengerChannel(models.TextChoices):
    """Каналы-мессенджеры: привязки, коды, диалоги, состояние опроса."""

    TELEGRAM = "telegram", "Telegram"
    MAX = "max", "MAX"


class NotifySettings(models.Model):
    """Настройки уведомлений портала: одна строка, pk=1 (создаёт миграция данных)."""

    webpush_enabled = models.BooleanField("Web Push включён", default=False)
    telegram_enabled = models.BooleanField("Telegram включён", default=False)
    max_enabled = models.BooleanField("MAX включён", default=False)
    email_delay_minutes = models.PositiveSmallIntegerField("задержка письма, минут", default=15)
    retention_days = models.PositiveSmallIntegerField("срок хранения, дней", default=90)
    defaults = models.JSONField("каналы по умолчанию", default=dict, blank=True)
    channel_status = models.JSONField("состояние каналов", default=dict, blank=True)
    updated_at = models.DateTimeField("изменено", auto_now=True)

    class Meta:
        default_permissions = ()
        verbose_name = "настройки уведомлений"
        verbose_name_plural = "настройки уведомлений"


class UserNotifySettings(models.Model):
    """Настройки уведомлений сотрудника: таблица каналов, тихие часы, время ближайшей сводки."""

    class QuietMode(models.TextChoices):
        CALENDAR = "calendar", "По рабочему календарю компании"
        OWN = "own", "Свои часы"
        NONE = "none", "Без тихих часов"

    user = models.OneToOneField("core.User", on_delete=models.CASCADE, related_name="+")
    matrix = models.JSONField("таблица каналов", default=dict, blank=True)
    quiet_mode = models.CharField("тихие часы", max_length=16, choices=QuietMode.choices,
                                  default=QuietMode.CALENDAR)
    own_days = models.JSONField("свои дни (0 — понедельник)", default=list, blank=True)
    own_start = models.TimeField("свои часы, начало", null=True, blank=True)
    own_end = models.TimeField("свои часы, конец", null=True, blank=True)
    digest_due_at = models.DateTimeField("ближайшая сводка", null=True, blank=True)

    class Meta:
        default_permissions = ()
        verbose_name = "настройки уведомлений сотрудника"
        verbose_name_plural = "настройки уведомлений сотрудников"
        indexes = [
            models.Index(fields=["digest_due_at"], name="notify_usettings_digest_due",
                         condition=Q(digest_due_at__isnull=False)),
        ]


class Notification(models.Model):
    """Уведомление сотрудника (запись в портале)."""

    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="+")
    kind = models.CharField("вид", max_length=64)
    text = models.CharField("текст", max_length=300)
    url = models.CharField("адрес", max_length=300)
    object_ref = models.CharField("объект", max_length=64, blank=True, default="")
    created_at = models.DateTimeField("создано", default=now)
    read_at = models.DateTimeField("прочитано", null=True, blank=True)

    class Meta:
        default_permissions = ()
        verbose_name = "уведомление"
        verbose_name_plural = "уведомления"
        indexes = [
            models.Index(fields=["user", "-created_at"], name="notify_notif_user_created"),
            models.Index(fields=["user"], name="notify_notif_unread", condition=Q(read_at__isnull=True)),
            models.Index(fields=["user", "object_ref"], name="notify_notif_obj_unread",
                         condition=Q(read_at__isnull=True)),
            models.Index(fields=["created_at"], name="notify_notif_created"),
        ]


class Digest(models.Model):
    """Сводка отложенных уведомлений, отправленная одним сообщением."""

    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField("создана", default=now)
    count_email = models.PositiveIntegerField("писем в сводке", default=0)
    count_message = models.PositiveIntegerField("сообщений в сводке", default=0)
    notification_ids = models.JSONField("номера уведомлений", default=list, blank=True)

    class Meta:
        default_permissions = ()
        verbose_name = "сводка"
        verbose_name_plural = "сводки"
        indexes = [models.Index(fields=["user", "created_at"], name="notify_digest_user_created")]


class Delivery(models.Model):
    """Доставка уведомления или сводки по внешнему каналу."""

    class Channel(models.TextChoices):
        EMAIL = "email", "Почта"
        WEBPUSH = "webpush", "Web Push"
        TELEGRAM = "telegram", "Telegram"
        MAX = "max", "MAX"

    class State(models.TextChoices):
        WAITING = "waiting", "Ждёт отправки"
        SENDING = "sending", "Отправляется"
        HELD = "held", "Отложена"
        SENT = "sent", "Отправлена"
        FAILED = "failed", "Не доставлена"
        SKIPPED = "skipped", "Пропущена"
        DIGESTED = "digested", "Вошла в сводку"

    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, null=True, blank=True,
                                     related_name="deliveries")
    digest = models.ForeignKey(Digest, on_delete=models.CASCADE, null=True, blank=True,
                               related_name="deliveries")
    channel = models.CharField("канал", max_length=16, choices=Channel.choices)
    state = models.CharField("состояние", max_length=16, choices=State.choices, default=State.WAITING)
    due_at = models.DateTimeField("отправить в", null=True, blank=True)
    enqueued_at = models.DateTimeField("поставлено в очередь", null=True, blank=True)
    lease_until = models.DateTimeField("удерживается до", null=True, blank=True)
    attempts = models.PositiveSmallIntegerField("попыток", default=0)
    log = models.JSONField("журнал попыток", default=list, blank=True)
    mail_id = models.PositiveIntegerField("номер письма", null=True, blank=True)
    reason = models.CharField("причина", max_length=32, blank=True, default="")

    class Meta:
        default_permissions = ()
        verbose_name = "доставка"
        verbose_name_plural = "доставки"
        constraints = [
            models.UniqueConstraint(fields=["notification", "channel"], name="notify_delivery_notif_channel"),
            models.UniqueConstraint(fields=["digest", "channel"], name="notify_delivery_digest_channel"),
            models.CheckConstraint(
                condition=(Q(notification__isnull=False, digest__isnull=True)
                           | Q(notification__isnull=True, digest__isnull=False)),
                name="notify_delivery_one_target"),
        ]
        indexes = [
            models.Index(fields=["due_at"], name="notify_delivery_waiting_due", condition=Q(state="waiting")),
            models.Index(fields=["lease_until"], name="notify_delivery_sending_lease",
                         condition=Q(state="sending")),
        ]


class PushSubscription(models.Model):
    """Подписка браузера на Web Push."""

    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="+")
    endpoint = models.CharField("адрес push-сервиса", max_length=1000)
    p256dh = models.CharField("ключ p256dh", max_length=128)
    auth = models.CharField("ключ auth", max_length=64)
    device = models.ForeignKey("core.KnownDevice", on_delete=models.CASCADE, null=True, blank=True,
                               related_name="+")
    browser = models.CharField("браузер", max_length=128, blank=True)
    platform = models.CharField("платформа", max_length=128, blank=True)
    created_at = models.DateTimeField("создана", default=now)
    last_ok_at = models.DateTimeField("последняя удачная отправка", null=True, blank=True)

    class Meta:
        default_permissions = ()
        verbose_name = "подписка Web Push"
        verbose_name_plural = "подписки Web Push"
        constraints = [models.UniqueConstraint(fields=["endpoint"], name="notify_push_endpoint_unique")]


class ChatBinding(models.Model):
    """Привязка учётной записи к чату Telegram или MAX."""

    Channel = MessengerChannel

    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="+")
    channel = models.CharField("канал", max_length=16, choices=MessengerChannel.choices)
    chat_id = models.CharField("номер чата", max_length=64)
    bound_at = models.DateTimeField("привязано", default=now)

    class Meta:
        default_permissions = ()
        verbose_name = "привязка чата"
        verbose_name_plural = "привязки чатов"
        constraints = [
            models.UniqueConstraint(fields=["channel", "chat_id"], name="notify_binding_chat_unique"),
            models.UniqueConstraint(fields=["user", "channel"], name="notify_binding_user_channel_unique"),
        ]


class BindCode(models.Model):
    """Одноразовый код привязки чата (хранится только хеш)."""

    Channel = MessengerChannel

    user = models.ForeignKey("core.User", on_delete=models.CASCADE, related_name="+")
    channel = models.CharField("канал", max_length=16, choices=MessengerChannel.choices)
    code_hash = models.CharField("хеш кода", max_length=64)
    expires_at = models.DateTimeField("действует до")
    used_at = models.DateTimeField("использован", null=True, blank=True)

    class Meta:
        default_permissions = ()
        verbose_name = "код привязки"
        verbose_name_plural = "коды привязки"
        constraints = [
            models.UniqueConstraint(fields=["user", "channel"], condition=Q(used_at__isnull=True),
                                    name="notify_bindcode_one_active"),
        ]
        indexes = [models.Index(fields=["channel", "code_hash"], name="notify_bindcode_channel_hash")]


class BotChat(models.Model):
    """Чат, в котором начат диалог с ботом."""

    Channel = MessengerChannel

    channel = models.CharField("канал", max_length=16, choices=MessengerChannel.choices)
    chat_id = models.CharField("номер чата", max_length=64)
    started_at = models.DateTimeField("диалог начат", default=now)
    bad_attempts = models.PositiveSmallIntegerField("неверных кодов за окно", default=0)
    window_started_at = models.DateTimeField("окно началось", null=True, blank=True)

    class Meta:
        default_permissions = ()
        verbose_name = "чат бота"
        verbose_name_plural = "чаты ботов"
        constraints = [models.UniqueConstraint(fields=["channel", "chat_id"], name="notify_botchat_unique")]


class BotState(models.Model):
    """Состояние опроса бота: курсор, имя бота, код последней ошибки."""

    Channel = MessengerChannel

    channel = models.CharField("канал", max_length=16, choices=MessengerChannel.choices, primary_key=True)
    cursor = models.CharField("курсор", max_length=64, blank=True)
    bot_username = models.CharField("имя бота", max_length=64, blank=True)
    updated_at = models.DateTimeField("обновлено", auto_now=True)
    last_error = models.CharField("код последней ошибки", max_length=32, blank=True)

    class Meta:
        default_permissions = ()
        verbose_name = "состояние бота"
        verbose_name_plural = "состояние ботов"
