"""Учётные записи для нагрузочного прогона T-304 (NFR-001, NFR-002).

Создаёт на стенде N администраторов с паролем и подтверждённым TOTP и печатает строки
`почта,пароль,ключ_TOTP_hex` — это файл LOAD_CREDENTIALS для locustfile.py. Файл вне git.
Работает ТОЛЬКО при E2E_STAND=1 (как e2e_reset_stand); данные стенда убирает следующий
сброс приёмки. Каталог tests в образ не входит, поэтому скрипт подаётся на вход shell:

    docker compose -f deploy/docker-compose.yml --profile dev exec -T -e LOAD_USERS=100 standtools \
        python manage.py shell --no-imports < backend/tests/load/prepare_users.py > creds.csv
"""
import os
import secrets
import sys

from django.db import transaction
from django.utils import timezone

from apps.core.models import EncryptedTOTPDevice, Role, User
from apps.core.services import crypto

ADMIN_ROLE = "Администратор портала"

if os.environ.get("E2E_STAND") != "1":
    sys.exit("Скрипт работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено.")

count = int(os.environ.get("LOAD_USERS", "100"))
role = Role.objects.get(name=ADMIN_ROLE)
run = secrets.token_hex(3)
rows = []
with transaction.atomic():
    for i in range(count):
        password = secrets.token_urlsafe(18)
        key = os.urandom(20)
        user = User(email=f"load-{run}-{i:03d}@example.org", full_name=f"Нагрузка {i:03d}",
                    state="active", activated_at=timezone.now())
        user.set_password(password)
        user.save()
        user.roles.set([role])
        EncryptedTOTPDevice.objects.create(user=user, name="default", confirmed=True,
                                           key_encrypted=crypto.encrypt(key), step=30, digits=6,
                                           tolerance=1, last_t=-1)
        rows.append(f"{user.email},{password},{key.hex()}")
print("\n".join(rows))
