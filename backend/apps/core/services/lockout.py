"""Защита от перебора на Valkey (T-212, ADR-0006, FR-025, FR-035…038).

Ключи (без приставки, на соединении очереди RQ):
- `fail:acct:<ключ>` — неудачи записи подряд; сутки от последней неудачи;
- `lock:acct:<ключ>` — запись заблокирована на `account_lock_minutes`;
- `fail:ip:<ip>` — неудачи с адреса в окне `ip_lock_window_minutes` (от первой неудачи);
- `accts:ip:<ip>` — множество хешей логинов, которые перебирали с адреса;
- `lock:ip:<ip>` — адрес заблокирован на `ip_lock_minutes`.

`ключ` записи — `str(user.pk)` для существующей и хеш логина для несуществующей.
Счётчики меняются одним скриптом Lua, то есть атомарно. К базе сервис не
обращается: журнал и письмо пишет вызывающий по исходу (`Outcome`).
Потеря Valkey обнуляет счётчики; события блокировок остаются в журнале.
"""
from dataclasses import dataclass

from . import crypto, valkey

FAIL_ACCOUNT_TTL = 24 * 3600

_REGISTER_FAILURE = """
-- KEYS: fail_acct, lock_acct, fail_ip, accts_ip, lock_ip
-- ARGV: member, account_limit, account_lock_s, fail_ttl_s, ip_limit, ip_min_accounts, window_s, ip_lock_s
if redis.call('EXISTS', KEYS[2]) == 1 then
  return {0, 0, 0}
end
local account_locked = 0
local fails = redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], tonumber(ARGV[4]))
if fails >= tonumber(ARGV[2]) then
  redis.call('DEL', KEYS[1])
  redis.call('SET', KEYS[2], '1', 'EX', tonumber(ARGV[3]))
  account_locked = 1
end
local ip_fails = redis.call('INCR', KEYS[3])
if ip_fails == 1 then
  redis.call('EXPIRE', KEYS[3], tonumber(ARGV[7]))
end
redis.call('SADD', KEYS[4], ARGV[1])
if redis.call('TTL', KEYS[4]) < 0 then
  redis.call('EXPIRE', KEYS[4], tonumber(ARGV[7]))
end
local ip_locked = 0
if ip_fails >= tonumber(ARGV[5]) and redis.call('SCARD', KEYS[4]) >= tonumber(ARGV[6])
   and redis.call('EXISTS', KEYS[5]) == 0 then
  redis.call('SET', KEYS[5], '1', 'EX', tonumber(ARGV[8]))
  ip_locked = 1
end
return {1, account_locked, ip_locked}
"""


@dataclass(frozen=True)
class Limits:
    account_lock_limit: int = 5
    account_lock_minutes: int = 15
    ip_lock_limit: int = 20
    ip_lock_min_accounts: int = 3
    ip_lock_window_minutes: int = 15
    ip_lock_minutes: int = 15

    @classmethod
    def from_settings(cls) -> "Limits":
        """Пороги из настроек безопасности (читаются из базы при каждом вызове)."""
        from apps.core.services import security_settings

        row = security_settings.get()
        return cls(**{name: getattr(row, name) for name in cls.__dataclass_fields__})


@dataclass(frozen=True)
class Outcome:
    counted: bool          # неудача засчитана (False, если запись уже заблокирована)
    account_locked_now: bool
    ip_locked_now: bool


_conn = valkey.conn


def account_key_for_login(login: str) -> str:
    """Ключ несуществующей записи — хеш логина (адрес почты в Valkey не лежит)."""
    return crypto.keyed_hash(login)


def register_failure(*, account_key: str, ip: str, limits: Limits) -> Outcome:
    conn = _conn()
    script = conn.register_script(_REGISTER_FAILURE)
    counted, account_locked, ip_locked = script(
        keys=[f"fail:acct:{account_key}", f"lock:acct:{account_key}", f"fail:ip:{ip}", f"accts:ip:{ip}",
              f"lock:ip:{ip}"],
        args=[crypto.keyed_hash(account_key), limits.account_lock_limit, limits.account_lock_minutes * 60,
              FAIL_ACCOUNT_TTL, limits.ip_lock_limit, limits.ip_lock_min_accounts,
              limits.ip_lock_window_minutes * 60, limits.ip_lock_minutes * 60],
    )
    return Outcome(bool(counted), bool(account_locked), bool(ip_locked))


def is_account_locked(account_key: str) -> bool:
    return bool(_conn().exists(f"lock:acct:{account_key}"))


def is_ip_locked(ip: str) -> bool:
    return bool(ip) and bool(_conn().exists(f"lock:ip:{ip}"))


def register_success(account_key: str) -> None:
    """Успешный вход обнуляет серию неудач записи."""
    _conn().delete(f"fail:acct:{account_key}")


def unlock_account(account_key: str) -> bool:
    """Снимает блокировку записи и серию неудач; True, если что-то было."""
    return bool(_conn().delete(f"lock:acct:{account_key}", f"fail:acct:{account_key}"))


def unlock_ip(ip: str) -> bool:
    return bool(_conn().delete(f"lock:ip:{ip}", f"fail:ip:{ip}", f"accts:ip:{ip}"))


def _scan(prefix: str) -> list[str]:
    conn = _conn()
    return sorted(key.decode()[len(prefix):] for key in conn.scan_iter(match=f"{prefix}*", count=200))


def locked_account_keys() -> list[str]:
    """Ключи заблокированных записей (для страницы блокировок)."""
    return _scan("lock:acct:")


def locked_ips() -> list[str]:
    return _scan("lock:ip:")


def lock_ttl(kind: str, target: str) -> int:
    """Сколько секунд осталось до конца блокировки (0, если её нет)."""
    ttl = _conn().ttl(f"lock:{'acct' if kind == 'account' else 'ip'}:{target}")
    return max(int(ttl), 0)
