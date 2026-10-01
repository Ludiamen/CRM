"""Первый администратор портала (PLAN-001, «Запуск», сценарий 1).

    python manage.py create_first_admin --email admin@example.org [--full-name "Имя Фамилия"]

Команда отказывает, если в базе уже есть учётные записи; пишет в журнал создание
записи (действующее лицо — «система») и печатает ссылку активации на 72 часа.
Письмо не отправляется.
"""
from django.core.management.base import BaseCommand, CommandError

from apps.core.services import accounts, links


class Command(BaseCommand):
    help = "Создаёт первого администратора и печатает ссылку активации (только в пустой базе)."

    def add_arguments(self, parser):
        parser.add_argument("--email", required=True, help="рабочая почта администратора")
        parser.add_argument("--full-name", default="", help="ФИО (по умолчанию «Администратор портала»)")

    def handle(self, *args, **options):
        try:
            user, code = accounts.create_first_admin(options["email"], options["full_name"])
        except accounts.AccountError as e:
            raise CommandError(str(e)) from None
        self.stdout.write(f"Создан администратор {user.email}.")
        self.stdout.write("Ссылка активации (действует 72 часа, одноразовая):")
        self.stdout.write(links.invitation_url(code))
