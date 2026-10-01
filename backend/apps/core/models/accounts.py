"""Учётные записи, права и роли (PLAN-001, «Модель данных»).

Прав и групп Django у пользователя нет: права даются только через роли
(FR-017), поэтому модель не наследует PermissionsMixin.
"""
from django.contrib.auth.base_user import AbstractBaseUser, BaseUserManager
from django.db import models
from django.db.models.functions import Lower

from ._util import now


class UserState(models.TextChoices):
    INVITED = "invited", "приглашён"
    ACTIVE = "active", "активен"
    BLOCKED = "blocked", "заблокирован"


class UserManager(BaseUserManager):
    use_in_migrations = False

    def get_by_natural_key(self, email):
        """Почта — имя входа, регистр не важен."""
        return self.get(email__iexact=email)


class User(AbstractBaseUser):
    email = models.EmailField("рабочая почта", max_length=254, unique=True)
    full_name = models.CharField("ФИО", max_length=255)
    position = models.CharField("должность", max_length=255, blank=True)
    phone = models.CharField("телефон", max_length=64, blank=True)
    contacts = models.JSONField("контакты", default=list, blank=True)
    state = models.CharField("состояние", max_length=16, choices=UserState.choices, default=UserState.INVITED)
    # состояние, из которого запись заблокировали: разблокировка возвращает его
    blocked_from = models.CharField(max_length=16, blank=True)
    blocked_reason = models.TextField("причина блокировки", blank=True)
    created_at = models.DateTimeField(default=now)
    activated_at = models.DateTimeField(null=True, blank=True)
    roles = models.ManyToManyField("core.Role", related_name="users", blank=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["full_name"]

    objects = UserManager()

    class Meta:
        default_permissions = ()
        constraints = [
            # почта уникальна без учёта регистра (FR-002)
            models.UniqueConstraint(Lower("email"), name="core_user_email_lower_uniq"),
        ]

    def __str__(self):
        return self.email

    @property
    def is_active(self):
        """Заблокированная запись не проходит проверку сессии Django."""
        return self.state != UserState.BLOCKED


class Permission(models.Model):
    code = models.CharField(max_length=64, unique=True)
    title = models.CharField(max_length=255)

    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.code


class Role(models.Model):
    name = models.CharField("название", max_length=100, unique=True)
    is_builtin = models.BooleanField(default=False)
    permissions = models.ManyToManyField(Permission, related_name="roles", blank=True)

    class Meta:
        default_permissions = ()

    def __str__(self):
        return self.name
