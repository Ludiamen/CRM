"""Печать новой пары ключей VAPID для `.env` (PLAN-004, «Запуск»; CONTRACT-004, 8.2).

Без аргументов, не защищена флагом стенда. Базу, Valkey и журнал не трогает; значения идут только в `stdout`.
"""
from django.core.management.base import BaseCommand

from apps.integrations.webpush import crypto


class Command(BaseCommand):
    help = "Печатает новую пару VAPID_PRIVATE_KEY и VAPID_PUBLIC_KEY (base64url) для файла .env."

    def handle(self, *args, **options):
        private, public = crypto.generate_vapid_keys()
        self.stdout.write(f"VAPID_PRIVATE_KEY={private}\nVAPID_PUBLIC_KEY={public}")
