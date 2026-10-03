"""Учётные записи для нагрузочного прогона T-304 (NFR-001, NFR-002).

Готовит на стенде N администраторов с паролем и подтверждённым TOTP и печатает строки
`почта,пароль,ключ_TOTP_hex` — это файл LOAD_CREDENTIALS для locustfile.py. Файл вне git.
Записи нагрузки прежних прогонов (`load-…@example.org`) берутся снова — с новым паролем и ключом,
их сессии закрываются; недостающие до N создаются. Так повторные прогоны не раздувают список
сотрудников (PLAN-001 версия 4). Работает ТОЛЬКО при E2E_STAND=1 (как e2e_reset_stand); данные
стенда убирает следующий сброс приёмки. Каталог tests в образ не входит, поэтому скрипт подаётся
на вход shell:

    docker compose -f deploy/docker-compose.yml --profile dev exec -T -e LOAD_USERS=100 standtools \
        python manage.py shell --no-imports < backend/tests/load/prepare_users.py > creds.csv
"""
import os
import secrets
import sys

from django.db import transaction
from django.utils import timezone

from apps.core.models import EncryptedTOTPDevice, Role, User, UserSession
from apps.core.services import crypto, sessions

ADMIN_ROLE = "Администратор портала"

if os.environ.get("E2E_STAND") != "1":
    sys.exit("Скрипт работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено.")

count = int(os.environ.get("LOAD_USERS", "100"))
role = Role.objects.get(name=ADMIN_ROLE)
run = secrets.token_hex(3)
rows = []
with transaction.atomic():
    reused = list(User.objects.filter(email__startswith="load-", email__endswith="@example.org", state="active")
                  .order_by("email")[:count])
    sessions.close(UserSession.objects.filter(user__in=reused))
    for user in reused:
        password = secrets.token_urlsafe(18)
        key = os.urandom(20)
        user.set_password(password)
        user.save(update_fields=["password"])
        EncryptedTOTPDevice.objects.update_or_create(
            user=user, name="default", defaults={"confirmed": True, "key_encrypted": crypto.encrypt(key), "step": 30,
                                                 "digits": 6, "tolerance": 1, "last_t": -1})
        rows.append(f"{user.email},{password},{key.hex()}")
    for i in range(count - len(reused)):
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
