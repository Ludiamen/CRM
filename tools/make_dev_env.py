#!/usr/bin/env python3
"""Создаёт deploy/.env для стенда из deploy/.env.example со свежими секретами.

Каждое `***` заменяется случайным значением нужного вида; пароль роли базы,
стоящий в DATABASE_URL / DATABASE_MIGRATE_URL, берётся тот же, что в
CRM_APP_PASSWORD / CRM_OWNER_PASSWORD. Значения не печатаются. Существующий
deploy/.env не затирается (нужен --force). Файл в .gitignore, права 0600.

    python3 tools/make_dev_env.py [--force]
"""
import base64
import os
import re
import secrets
import sys
from pathlib import Path

КОРЕНЬ = Path(__file__).resolve().parent.parent
ОБРАЗЕЦ = КОРЕНЬ / "deploy" / ".env.example"
ЦЕЛЬ = КОРЕНЬ / "deploy" / ".env"


def ключ_fernet() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode()


ГЕНЕРАТОРЫ = {
    "DJANGO_SECRET_KEY": lambda: secrets.token_urlsafe(64),
    "FIELD_ENCRYPTION_KEYS": ключ_fernet,
    "BACKUP_CODE_PEPPER": lambda: secrets.token_urlsafe(48),
    "POSTGRES_PASSWORD": lambda: secrets.token_urlsafe(24),
    "CRM_OWNER_PASSWORD": lambda: secrets.token_urlsafe(24),
    "CRM_APP_PASSWORD": lambda: secrets.token_urlsafe(24),
}
ПАРОЛЬ_В_АДРЕСЕ = {"DATABASE_URL": "CRM_APP_PASSWORD", "DATABASE_MIGRATE_URL": "CRM_OWNER_PASSWORD"}


def main(арг) -> int:
    if ЦЕЛЬ.exists() and "--force" not in арг:
        print(f"{ЦЕЛЬ.relative_to(КОРЕНЬ)} уже есть, не трогаю (--force — пересоздать)")
        return 0
    значения = {имя: г() for имя, г in ГЕНЕРАТОРЫ.items()}
    строки = []
    for строка in ОБРАЗЕЦ.read_text(encoding="utf-8").splitlines():
        м = re.match(r"^([A-Z_]+)=(.*)$", строка)
        if м and "***" in м.group(2):
            имя = м.group(1)
            if имя in ПАРОЛЬ_В_АДРЕСЕ:
                строка = f"{имя}={м.group(2).replace('***', значения[ПАРОЛЬ_В_АДРЕСЕ[имя]])}"
            elif имя in значения:
                строка = f"{имя}={значения[имя]}"
            else:
                print(f"нет генератора для {имя}", file=sys.stderr)
                return 1
        строки.append(строка)
    ЦЕЛЬ.write_text("\n".join(строки) + "\n", encoding="utf-8")
    ЦЕЛЬ.chmod(0o600)
    print(f"создан {ЦЕЛЬ.relative_to(КОРЕНЬ)} (значения не показаны)")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
