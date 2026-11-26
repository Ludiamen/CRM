"""Администратор для браузерного круга на непустом стенде (только E2E_STAND=1).

Печатает ссылку активации, как `create_first_admin`, но не требует пустой базы: стенд приёмки
обновляется без сброса и уже содержит сотрудников. Письмо не отправляется.
"""
import os

from django.core.management.base import BaseCommand, CommandError

from apps.core.models import Role, User
from apps.core.services import accounts, links, roles


class Command(BaseCommand):
    help = "Создаёт приглашённого администратора стенда и печатает ссылку активации."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True)
        parser.add_argument("--full-name", default="Администратор Стенда")

    def handle(self, *args, **options):
        if os.environ.get("E2E_STAND") != "1":
            raise CommandError("Команда работает только на стенде (E2E_STAND=1).")
        admin_role = roles.admin_role()
        if admin_role is None:
            raise CommandError("Нет роли администратора: примените миграции.")
        actor = User.objects.order_by("pk").first()
        if actor is None:
            user, code = accounts.create_first_admin(options["email"], options["full_name"])
        else:
            user = accounts.create_user(
                email=options["email"], full_name=options["full_name"], position="Администратор портала",
                role_ids=[admin_role.pk], actor=actor, invite=False)
            _, code = links.issue(user, "activation")
        self.stdout.write(links.invitation_url(code))
