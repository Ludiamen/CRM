#!/usr/bin/env python3
"""Создаёт deploy/.env для стенда из deploy/.env.example со свежими секретами.

Каждое `***` заменяется случайным значением нужного вида; пароль роли базы,
стоящий в DATABASE_URL / DATABASE_MIGRATE_URL, берётся тот же, что в
CRM_APP_PASSWORD / CRM_OWNER_PASSWORD. Значения не печатаются. Существующий
deploy/.env не затирается (нужен --force). Файл в .gitignore, права 0600.

Значения стенда (таблица СТЕНД: тестовый ящик Dovecot, PLAN-003) дописываются в
конец созданного файла для имён, которых в нём нет действующей строкой.

Режим --add-missing не пересоздаёт секреты: если deploy/.env уже есть, в его
конец (после пустой строки и комментария-заголовка) дописываются только
недостающие имена из СТЕНД и генерируемых секретов образца; прежние строки не
меняются ни на байт, права 0600 сохраняются, печатаются только имена
дописанных переменных или «нечего дописывать», значения — никогда. Если файла
нет, режим работает как обычный. Вместе с --force он отклоняется (код 1).
Имя с пустым значением (`IMAP_PASSWORD=`) считается заданным и не дописывается:
прежние строки режим не меняет, такое значение вписывают руками.

    python3 tools/make_dev_env.py [--force | --add-missing]
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
ГЕНЕРАТОРЫ["IMAP_PASSWORD"] = lambda: secrets.token_urlsafe(24)
# значения стенда (тестовый ящик Dovecot, PLAN-003 «Запуск» → «Переменные окружения»);
# одна таблица служит и созданию файла, и режиму --add-missing
СТЕНД = {
    "IMAP_HOST": "dovecot",
    "IMAP_PORT": "31143",
    "IMAP_SECURITY": "none",
    "IMAP_USER": "tickets",
    "IMAP_FOLDER": "INBOX",
    "SERVICEDESK_MAILBOX": "tickets@stand.test",
}
ПАРОЛЬ_В_АДРЕСЕ = {"DATABASE_URL": "CRM_APP_PASSWORD", "DATABASE_MIGRATE_URL": "CRM_OWNER_PASSWORD"}


def действующие_имена(текст: str) -> set:
    """Имена переменных из действующих строк `ИМЯ=...` (закомментированные не в счёт)."""
    return {м.group(1) for м in re.finditer(r"^([A-Za-z_][A-Za-z0-9_]*)=", текст, re.M)}


def создать(значения: dict) -> int:
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
    есть = действующие_имена("\n".join(строки))
    for имя, значение in СТЕНД.items():
        if имя not in есть:
            строки.append(f"{имя}={значение}")
    ЦЕЛЬ.write_text("\n".join(строки) + "\n", encoding="utf-8")
    ЦЕЛЬ.chmod(0o600)
    print(f"создан {ЦЕЛЬ.relative_to(КОРЕНЬ)} (значения не показаны)")
    return 0


def дописать_недостающее() -> int:
    """--add-missing: дописывает в конец существующего файла только недостающие имена."""
    есть = действующие_имена(ЦЕЛЬ.read_text(encoding="utf-8"))
    секреты_образца = [
        м.group(1)
        for м in re.finditer(r"^([A-Z_]+)=.*\*\*\*", ОБРАЗЕЦ.read_text(encoding="utf-8"), re.M)
        if м.group(1) in ГЕНЕРАТОРЫ
    ]
    новые = {имя: знач for имя, знач in СТЕНД.items() if имя not in есть}
    for имя in секреты_образца:
        if имя not in есть:
            новые[имя] = ГЕНЕРАТОРЫ[имя]()
    if not новые:
        print("нечего дописывать")
        return 0
    прежнее = ЦЕЛЬ.read_bytes()
    вставка = ("" if прежнее.endswith(b"\n") or not прежнее else "\n") + "\n"
    вставка += "# Дописано tools/make_dev_env.py --add-missing (тестовый ящик сервис-деска, стенд)\n"
    вставка += "".join(f"{имя}={знач}\n" for имя, знач in новые.items())
    with open(ЦЕЛЬ, "ab") as файл:  # дозапись: прежние байты не перезаписываются
        файл.write(вставка.encode("utf-8"))
    ЦЕЛЬ.chmod(0o600)
    print("дописаны: " + ", ".join(новые))
    return 0


def main(арг) -> int:
    if "--force" in арг and "--add-missing" in арг:
        print("--force и --add-missing вместе не допускаются", file=sys.stderr)
        return 1
    if "--add-missing" in арг and ЦЕЛЬ.exists():
        return дописать_недостающее()
    if ЦЕЛЬ.exists() and "--force" not in арг:
        print(f"{ЦЕЛЬ.relative_to(КОРЕНЬ)} уже есть, не трогаю (--force — пересоздать)")
        return 0
    return создать({имя: г() for имя, г in ГЕНЕРАТОРЫ.items()})


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
