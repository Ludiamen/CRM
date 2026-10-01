"""Шифрование полей, хеши и случайные коды (T-211, NFR-011).

Ключи читаются из `settings` при каждом вызове, а не при импорте: смена ключей
(команда `rotate_field_keys`) и тесты подменяют их на лету. Секреты — только из
окружения: `FIELD_ENCRYPTION_KEYS`, `BACKUP_CODE_PEPPER`, `SECRET_KEY`.
"""
import hashlib
import hmac
import re
import secrets

from cryptography.fernet import Fernet, MultiFernet
from django.conf import settings

# Алфавит резервных кодов без похожих знаков (0/O, 1/I/L)
BACKUP_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"
BACKUP_CODE_LENGTH = 12


def fernet() -> MultiFernet:
    """Первый ключ шифрует, остальные только расшифровывают."""
    return MultiFernet([Fernet(key) for key in settings.FIELD_ENCRYPTION_KEYS])


def encrypt(value: bytes | str) -> str:
    data = value.encode() if isinstance(value, str) else bytes(value)
    return fernet().encrypt(data).decode()


def decrypt(token: str | bytes) -> bytes:
    data = token.encode() if isinstance(token, str) else bytes(token)
    return fernet().decrypt(data)


def new_link_code() -> str:
    """Код ссылки: 256 бит случайности."""
    return secrets.token_urlsafe(32)


def sha256_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def link_token_hash(code: str) -> str:
    return sha256_hex(code)


def new_backup_code() -> str:
    return "".join(secrets.choice(BACKUP_ALPHABET) for _ in range(BACKUP_CODE_LENGTH))


def normalize_backup_code(value: str) -> str:
    """Дефисы и пробелы отбрасываются, регистр не важен (решение Opus, CONTRACT.md)."""
    return re.sub(r"[\s\-]+", "", str(value or "")).upper()


def backup_code_hash(code: str) -> str:
    """HMAC-SHA256 с секретом из окружения; код хешируется в том виде, в каком показан."""
    if not code:
        return ""
    return hmac.new(settings.BACKUP_CODE_PEPPER.encode(), code.encode(), hashlib.sha256).hexdigest()


def keyed_hash(value: str) -> str:
    """Хеш с ключом SECRET_KEY: логины и адреса почты в Valkey лежат только так."""
    return hmac.new(settings.SECRET_KEY.encode(), value.strip().lower().encode(), hashlib.sha256).hexdigest()


def new_device_key() -> str:
    """Значение долгоживущей куки устройства; в базе лежит только его SHA-256."""
    return secrets.token_urlsafe(32)
