"""Вход в два шага на уровне сервиса (T-220, FR-021, FR-025, FR-034, FR-035, FR-039…041).

Шаг 1 — почта и пароль (`check_password`), шаг 2 — код TOTP или резервный код
(`check_code`), затем `complete` открывает сессию. Блокировки записи и адреса
проверяются до проверки пароля; для несуществующей и недоступной записи
выполняется холостая проверка хеша, чтобы по времени ответа их нельзя было
отличить. Причина отказа наружу не раскрывается: вызывающий показывает одно общее
сообщение (FR-034), а настоящая причина остаётся в истории входов и журнале.
"""
from dataclasses import dataclass

from django.contrib.auth import hashers
from django.db import transaction
from django.utils import timezone

from apps.core.models import LoginAttempt, LoginResult, User, UserSession, UserState
from apps.integrations.mail import services as mail

from . import audit, backup_codes, crypto, devices, lockout, sessions, totp

_dummy_hash: str | None = None

REASON_BAD = "bad"            # неверный пароль или код (или записи нет)
REASON_LOCKED = "locked"      # запись заблокирована по перебору или администратором
REASON_IP_LOCKED = "ip_locked"


@dataclass(frozen=True)
class PasswordStep:
    ok: bool
    user: User | None = None
    limited: bool = False       # у записи нет подтверждённого второго фактора
    reason: str = ""


@dataclass(frozen=True)
class CodeStep:
    ok: bool
    via: str = ""               # "totp" или "backup"
    reason: str = ""


@dataclass(frozen=True)
class Completed:
    device_key: str             # значение куки устройства для клиента
    new_device: bool


def _dummy_check(password: str) -> None:
    """Холостая проверка хеша: время ответа не выдаёт, что записи нет."""
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hashers.make_password(crypto.new_link_code())
    hashers.check_password(password or "", _dummy_hash)


def _attempt(user, ip, user_agent, result, device=None) -> LoginAttempt:
    browser, platform = devices.parse_user_agent(user_agent)
    return LoginAttempt.objects.create(user=user, at=timezone.now(), ip=ip or None, browser=browser,
                                       platform=platform, device=device, result=result)


def _refuse(user, ip, user_agent, result: str) -> None:
    """Отказ по блокировке (запись или адрес): история входов и журнал событий (FR-044).

    В «стало» — только результат: ни пароля, ни кода, ни почты введённого логина.
    """
    with transaction.atomic():
        _attempt(user, ip, user_agent, result)
        audit.record("login.failed", object_type="user", object_id=user.pk if user else "",
                     after={"result": result}, ip=ip)


def _account_key(user, login_name: str) -> str:
    return str(user.pk) if user is not None else lockout.account_key_for_login(login_name)


def _count_failure(user, account_key: str, ip: str, *, step: str) -> lockout.Outcome:
    """Засчитывает неудачу в счётчиках; блокировки и письмо о блокировке — по исходу."""
    limits = lockout.Limits.from_settings()
    outcome = lockout.register_failure(account_key=account_key, ip=ip or "", limits=limits)
    if outcome.account_locked_now and user is not None:
        audit.record("account.locked", object_type="user", object_id=user.pk,
                     after={"minutes": limits.account_lock_minutes, "step": step}, ip=ip)
        mail.send("account_locked", user.email, {"full_name": user.full_name, "minutes": limits.account_lock_minutes},
                  related_user=user)
    if outcome.ip_locked_now:
        audit.record("ip.locked", object_type="ip", object_id=ip, ip=ip)
    return outcome


def register_other_failure(user, *, ip, step: str) -> None:
    """Неудача вне входа (неверный код при подключении фактора, неверный текущий пароль при смене): FR-025."""
    key = str(user.pk)
    if lockout.is_account_locked(key):
        return
    if _count_failure(user, key, ip, step=step).counted:
        audit.record("login.failed", object_type="user", object_id=user.pk, after={"step": step}, ip=ip)


def check_password(email: str, password: str, *, ip: str, user_agent: str = "") -> PasswordStep:
    """Шаг 1: почта и пароль. Все отказы для вызывающего одинаковы (`ok=False`)."""
    login_name = (email or "").strip()
    user = User.objects.filter(email__iexact=login_name).first() if login_name else None
    key = _account_key(user, login_name)

    if lockout.is_ip_locked(ip):
        _dummy_check(password)
        _refuse(user, ip, user_agent, LoginResult.IP_LOCKED)
        return PasswordStep(False, reason=REASON_IP_LOCKED)
    if lockout.is_account_locked(key) or (user is not None and user.state == UserState.BLOCKED):
        _dummy_check(password)
        _refuse(user, ip, user_agent, LoginResult.LOCKED)
        return PasswordStep(False, reason=REASON_LOCKED)

    if user is None or not user.check_password(password or ""):
        if user is None:
            _dummy_check(password)
        with transaction.atomic():
            _count_failure(user, key, ip, step="password")
            _attempt(user, ip, user_agent, LoginResult.BAD_PASSWORD)
            audit.record("login.failed", object_type="user", object_id=user.pk if user else "",
                         after={"result": LoginResult.BAD_PASSWORD}, ip=ip)
        return PasswordStep(False, reason=REASON_BAD)
    return PasswordStep(True, user=user, limited=not totp.has_confirmed(user))


def check_code(user, *, code: str = "", backup_code: str = "", ip: str, user_agent: str = "") -> CodeStep:
    """Шаг 2: код приложения или резервный код. Неверный код — такая же неудача, как неверный пароль."""
    key = str(user.pk)
    if lockout.is_ip_locked(ip):
        _refuse(user, ip, user_agent, LoginResult.IP_LOCKED)
        return CodeStep(False, reason=REASON_IP_LOCKED)
    if lockout.is_account_locked(key) or user.state == UserState.BLOCKED:
        _refuse(user, ip, user_agent, LoginResult.LOCKED)
        return CodeStep(False, reason=REASON_LOCKED)

    if backup_code:
        ok, via = backup_codes.verify(user, backup_code), "backup"
    else:
        ok, via = totp.verify(user, code), "totp"
    if ok:
        return CodeStep(True, via=via)
    with transaction.atomic():
        _count_failure(user, key, ip, step="code")
        _attempt(user, ip, user_agent, LoginResult.BAD_CODE)
        audit.record("login.failed", object_type="user", object_id=user.pk,
                     after={"result": LoginResult.BAD_CODE}, ip=ip)
    return CodeStep(False, reason=REASON_BAD)


def complete(request, user, *, ip: str, user_agent: str = "", device_key: str | None = None,
             via: str = "totp", limited: bool = False) -> Completed:
    """Открывает сессию: устройство, история, журнал, письмо о новом устройстве, обнуление счётчика.

    `via`: `totp`, `backup` (резервный код) или `activation` (последний шаг мастера активации).
    Ограниченная сессия (`limited=True`, нет второго фактора) устройство не запоминает: оно ещё
    не подтверждено вторым фактором; запоминание — в `finish_limited`.
    """
    with transaction.atomic():
        known_before = devices.has_history(user)
        touched = None if limited else devices.touch(user, device_key, user_agent)
        result = LoginResult.BACKUP_CODE if via == "backup" else LoginResult.SUCCESS
        _attempt(user, ip, user_agent, result, device=touched.device if touched else None)
        lockout.register_success(str(user.pk))
        sessions.start(request, user, device=touched.device if touched else None, ip=ip, limited=limited)
        audit.record("login.success", actor=user, object_type="user", object_id=user.pk,
                     after={"via": "password" if limited else via}, ip=ip)
        if touched is not None and touched.is_new and known_before:
            _mail_new_device(user, ip, user_agent)
    return Completed(touched.raw_key if touched else (device_key or ""), bool(touched and touched.is_new))


def _mail_new_device(user, ip, user_agent) -> None:
    browser, platform = devices.parse_user_agent(user_agent)
    mail.send("new_device", user.email, {"full_name": user.full_name, "at": timezone.now(), "browser": browser,
                                         "platform": platform, "ip": ip}, related_user=user)


def finish_limited(request, user, *, ip: str, user_agent: str = "", device_key: str | None = None) -> Completed:
    """Второй фактор подключён, коды подтверждены: ограничение снимается, устройство запоминается."""
    with transaction.atomic():
        touched = devices.touch(user, device_key, user_agent)
        sessions.finish_limited(request)
        UserSession.objects.filter(session_key=request.session.session_key).update(device=touched.device)
    return Completed(touched.raw_key, touched.is_new)


def logout(request, *, ip: str | None = None) -> None:
    """Выход: событие в журнале, сессия закрыта."""
    user = request.user if request.user.is_authenticated else None
    sessions.end(request)
    if user is not None:
        audit.record("logout", actor=user, object_type="user", object_id=user.pk, ip=ip)
