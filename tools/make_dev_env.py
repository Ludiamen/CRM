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
недостающие имена из СТЕНД и генерируемых секретов образца; пустые строки имён СТЕНД
заполняются на месте, остальные строки — без изменений; права 0600 сохраняются, печатаются только имена
дописанных переменных или «нечего дописывать», значения — никогда. Если файла
нет, режим работает как обычный. Вместе с --force он отклоняется (код 1).
Имя с пустым значением (`IMAP_PASSWORD=`) считается заданным и не дописывается:
прежние строки режим не меняет, такое значение вписывают руками. Исключение — имена
из таблицы СТЕНД (например, `TELEGRAM_BOT_TOKEN=` из образца): для них пустое значение
считается незаданным и заменяется на месте, в той же строке; второй строки с этим
именем в файле не появляется. Пара VAPID сюда не входит: её создаёт команда
`manage.py notify_vapid_keys`, `VAPID_PRIVATE_KEY=` остаётся пустым.

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


def токен_стенда() -> str:
    """Токен бота для стенда: не по форме токена Telegram (`<цифры>:<35 знаков>`), без двоеточия."""
    return "t-" + secrets.token_hex(8)


# значения стенда (тестовый ящик Dovecot, PLAN-003 «Запуск» → «Переменные окружения»);
# одна таблица служит и созданию файла, и режиму --add-missing
СТЕНД = {
    "IMAP_HOST": "dovecot",
    "IMAP_PORT": "31143",
    "IMAP_SECURITY": "none",
    "IMAP_USER": "tickets",
    "IMAP_FOLDER": "INBOX",
    "SERVICEDESK_MAILBOX": "tickets@stand.test",
    # срез 004: учебная служба ботов `fakebots` и токены ботов стенда (решение 21 задач);
    # токены создаются при запуске скрипта и в отчёты не попадают
    "TELEGRAM_API_BASE": "http://fakebots:8099",
    "MAX_API_BASE": "http://fakebots:8099/max",
    "TELEGRAM_BOT_TOKEN": токен_стенда(),
    "MAX_BOT_TOKEN": токен_стенда(),
}
ПАРОЛЬ_В_АДРЕСЕ = {"DATABASE_URL": "CRM_APP_PASSWORD", "DATABASE_MIGRATE_URL": "CRM_OWNER_PASSWORD"}


def пусто(значение: str) -> bool:
    """Пустое значение переменной: ничего, пробелы или пустые кавычки."""
    return not значение.strip().strip("\"'").strip()


def действующие_имена(текст: str) -> set:
    """Имена переменных из действующих строк `ИМЯ=...` (закомментированные не в счёт).

    Для имён из СТЕНД пустое значение считается незаданным: имя в результат не входит,
    пока где-нибудь в тексте нет строки с этим именем и непустым значением.
    """
    имена = set()
    for м in re.finditer(r"^([A-Za-z_][A-Za-z0-9_]*)=(.*)$", текст, re.M):
        if м.group(1) not in СТЕНД or not пусто(м.group(2)):
            имена.add(м.group(1))
    return имена


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
        elif м and м.group(1) in СТЕНД and пусто(м.group(2)):
            строка = f"{м.group(1)}={СТЕНД[м.group(1)]}"  # пустое значение стенда — заполняем на месте
        строки.append(строка)
    есть = действующие_имена("\n".join(строки))
    for имя, значение in СТЕНД.items():
        if имя not in есть:
            строки.append(f"{имя}={значение}")
    ЦЕЛЬ.write_text("\n".join(строки) + "\n", encoding="utf-8")
    ЦЕЛЬ.chmod(0o600)
    print(f"создан {ЦЕЛЬ.relative_to(КОРЕНЬ)} (значения не показаны)")
    return 0


def заполнить_пустую(текст: str, имя: str, значение: str):
    """Заменяет на месте первую строку `ИМЯ=` с пустым значением; возвращает (текст, заменена ли)."""
    for м in re.finditer(rf"^{re.escape(имя)}=([^\r\n]*)", текст, re.M):
        if пусто(м.group(1)):
            return текст[: м.start()] + f"{имя}={значение}" + текст[м.end():], True
    return текст, False


def дописать_недостающее() -> int:
    """--add-missing: недостающие имена дописываются в конец; пустое `ИМЯ=` из СТЕНД заменяется на месте."""
    текст = ЦЕЛЬ.read_bytes().decode("utf-8")
    есть = действующие_имена(текст)
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
    в_конец = {}
    for имя, знач in новые.items():
        if имя in СТЕНД:
            текст, заменена = заполнить_пустую(текст, имя, знач)
            if заменена:
                continue
        в_конец[имя] = знач
    if в_конец:
        вставка = ("" if текст.endswith("\n") or not текст else "\n") + "\n"
        вставка += "# Дописано tools/make_dev_env.py --add-missing (тестовый ящик сервис-деска, стенд)\n"
        вставка += "".join(f"{имя}={знач}\n" for имя, знач in в_конец.items())
        текст += вставка
    ЦЕЛЬ.write_bytes(текст.encode("utf-8"))  # остальные строки — те же байты
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
