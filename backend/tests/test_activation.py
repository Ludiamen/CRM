"""T-105: мастер активации и ограниченная сессия (FR-011, FR-013, FR-021, FR-024, FR-026, NFR-004). Сценарии 1, 3, 7."""
import pytest

from tests import factories, support
from tests.support import enroll_totp, model

pytestmark = pytest.mark.django_db

PROFILE = {"phone": "+7 900 111-22-33", "contacts": "telegram: @newcomer"}


def begin(**extra):
    """Приглашённый сотрудник открыл ссылку: возвращает (сотрудник, клиент, код)."""
    user = support.make_employee(state="invited", totp=False, roles=[support.role_by_name(support.STAFF_ROLE)], **extra)
    link, code = factories.make_link(user, "activation")
    client = support.make_client(ip="198.51.100.101")
    done = client.post("/activate/exchange/", {"code": code})
    assert done.status_code == 302 and done["Location"].endswith("/activate/profile/")
    return user, client, code


def set_password_step(client, password=None):
    password = password or factories.new_password()
    done = client.post("/activate/password/", {"password1": password, "password2": password})
    return password, done


def test_wizard_order_profile_password_totp_backup_codes():
    """FR-013 (сценарий 3): профиль → пароль → TOTP → резервные коды; в конце сотрудник внутри, запись активна."""
    user, client, _ = begin()
    assert client.get("/activate/profile/").status_code == 200
    done = client.post("/activate/profile/", PROFILE)
    assert done.status_code == 302 and done["Location"].endswith("/activate/password/")
    password, done = set_password_step(client)
    assert done.status_code == 302 and done["Location"].endswith("/activate/totp/")
    key, codes = enroll_totp(client, user, totp_url="/activate/totp/", codes_url="/activate/codes/", finish=False)
    assert len(codes) == 10 and len(set(codes)) == 10 and all(len(c) >= 10 for c in codes)
    user.refresh_from_db()
    assert user.state == "invited", "до подтверждения «я сохранил коды» запись не активна"
    done = client.post("/activate/codes/", {"confirm": "1"})
    assert done.status_code == 302 and done["Location"].endswith("/")
    user.refresh_from_db()
    assert user.state == "active" and user.activated_at is not None
    assert user.check_password(password) and user.phone == PROFILE["phone"]
    assert model("core.PasswordHistory").objects.filter(user=user).count() == 1
    assert client.get("/me/").status_code == 200, "после последнего шага сотрудник внутри портала"
    assert model("core.EncryptedTOTPDevice").objects.filter(user=user, confirmed=True).count() == 1
    assert model("core.BackupCode").objects.filter(used_at__isnull=True).count() == 10
    actions = support.audit_actions(object_id=str(user.pk))
    assert {"user.activated", "totp.enrolled"} <= set(actions)
    dumped = " ".join(str(e.before) + str(e.after) for e in model("core.AuditEvent").objects.all())
    for secret in (password, *codes, key.hex(), factories.totp_code(key)):
        assert secret not in dumped


def test_cannot_skip_steps_or_reach_portal_before_finish():
    """FR-013, FR-021: шаги нельзя пропустить, в портал до конца не попасть."""
    ghost = support.make_client()
    assert ghost.get("/activate/profile/").status_code in (302, 403), "без обмена кода мастер закрыт"
    user, client, _ = begin()
    for step in ("password", "totp", "codes"):
        done = client.get(f"/activate/{step}/")
        assert done.status_code == 302 and done["Location"].endswith("/activate/profile/"), f"{step} до профиля"
    client.post("/activate/profile/", PROFILE)
    for step in ("totp", "codes"):
        done = client.get(f"/activate/{step}/")
        assert done.status_code == 302 and done["Location"].endswith("/activate/password/"), f"{step} до пароля"
    set_password_step(client)
    assert client.get("/activate/codes/").status_code == 302
    assert client.post("/activate/codes/", {"confirm": "1"}).status_code == 302
    user.refresh_from_db()
    assert user.state == "invited", "без подключённого фактора запись не активируется"
    for path in ("/", "/me/", "/me/security/", "/staff/"):
        done = client.get(path)
        assert done.status_code == 302 and "/login/" in done["Location"], path
    assert not model("core.UserSession").objects.filter(user=user).exists()


def test_link_dies_after_last_step():
    """FR-011, FR-013: ссылка работает до завершения активации и гаснет после последнего шага."""
    user, client, code = begin()
    client.post("/activate/profile/", PROFILE)
    set_password_step(client)
    other = support.make_client(ip="198.51.100.102")
    assert other.post("/activate/exchange/", {"code": code}).status_code == 302, "до конца активации ссылка жива"
    enroll_totp(client, user, totp_url="/activate/totp/", codes_url="/activate/codes/")
    link = model("core.OneTimeLink").objects.get(user=user, purpose="activation")
    assert link.used_at is not None and not link.code_encrypted
    late = support.make_client(ip="198.51.100.103").post("/activate/exchange/", {"code": code})
    assert late.status_code != 302
    unknown = support.make_client(ip="198.51.100.104").post("/activate/exchange/", {"code": factories.new_password()})
    assert support.same_failure(late, unknown)


def test_password_step_applies_policy():
    """FR-026: при задании пароля — политика: длина, совпадение, настройка администратора; объяснение — на месте."""
    user, client, _ = begin()
    client.post("/activate/profile/", PROFILE)
    short = "Aa1-" + "x" * 7  # 11 знаков
    done = client.post("/activate/password/", {"password1": short, "password2": short})
    assert done.status_code == 200 and "12" in done.content.decode() and "символ" in done.content.decode()
    good = factories.new_password() + "Zz"
    mismatch = client.post("/activate/password/", {"password1": good, "password2": good + "x"})
    assert mismatch.status_code == 200
    user.refresh_from_db()
    assert not user.check_password(short) and not user.check_password(good)
    support.set_security(password_min_length=30)
    long_enough = client.post("/activate/password/", {"password1": good, "password2": good})
    assert long_enough.status_code == 200 and "30" in long_enough.content.decode(), "политика берётся из настроек"
    support.set_security(password_min_length=12)
    password, done = set_password_step(client, good)
    assert done.status_code == 302 and done["Location"].endswith("/activate/totp/")
    user.refresh_from_db()
    assert user.check_password(good)


def test_limited_session_reaches_only_totp_setup_pages():
    """FR-021, NFR-004: без подтверждённого фактора после верного пароля доступны только подключение и показ резервных кодов."""
    admin_role = support.role_by_name(support.ADMIN_ROLE)
    user = support.make_employee(state="invited", totp=False, roles=[admin_role])
    client = support.make_client(ip="198.51.100.110")
    done = support.post_password(client, user)
    assert done.status_code == 302 and done["Location"].endswith("/me/security/totp/")
    assert client.get("/me/security/totp/").status_code == 200
    for path in ("/", "/me/", "/me/security/", "/staff/", "/roles/", "/audit/", "/settings/security/",
                 "/me/security/password/", "/me/security/devices/"):
        got = client.get(path)
        assert got.status_code == 302 and got["Location"].endswith("/me/security/totp/"), f"{path}: {got.status_code}"
    assert client.post("/staff/new/", {"email": factories.new_email()}).status_code in (302, 403)
    enroll_totp(client, user, totp_url="/me/security/totp/", codes_url="/me/security/backup-codes/", finish=False)
    assert client.get("/me/security/backup-codes/").status_code == 200
    assert client.get("/staff/").status_code == 302, "пока коды не подтверждены, портал закрыт"
    assert client.post("/me/security/backup-codes/", {"confirm": "1"}).status_code == 302
    assert client.get("/staff/").status_code == 200 and client.get("/me/").status_code == 200


def test_user_without_confirmed_device_after_reset_gets_limited_session():
    """FR-021, FR-024, NFR-004 (сценарий 7): после сброса фактора вход по паролю ведёт только к его подключению."""
    user = support.make_employee()
    old_key = user.test_totp_key
    employee = support.logged_in(user, ip="198.51.100.120")
    admin = support.logged_in(support.make_admin(), ip="198.51.100.121")
    assert employee.get("/me/").status_code == 200
    assert admin.post(f"/staff/{user.pk}/reset-2fa/").status_code == 302
    assert employee.get("/me/").status_code == 302, "сброс закрывает сессии сотрудника"
    assert not model("core.EncryptedTOTPDevice").objects.filter(user=user, confirmed=True).exists()
    client = support.make_client(ip="198.51.100.122")
    done = support.post_password(client, user)
    assert done.status_code == 302 and done["Location"].endswith("/me/security/totp/")
    assert client.get("/me/").status_code == 302
    key, codes = enroll_totp(client, user, totp_url="/me/security/totp/", codes_url="/me/security/backup-codes/")
    assert key != old_key and len(codes) == 10
    assert client.get("/me/").status_code == 200
    again = support.make_client(ip="198.51.100.123")
    assert support.post_password(again, user)["Location"].endswith("/login/code/"), "теперь фактор подключён"


def test_profile_step_change_written_to_audit_unchanged_not():
    """FR-044 (этап 4, T-305): шаг «профиль» меняет телефон и контакты записи — это изменение учётной записи,
    в журнал «user.updated» с «было» и «стало»; тот же профиль без изменений журнал не засоряет."""
    user, client, _ = begin(phone="+7 900 000-00-07", contacts=[])
    client.post("/activate/profile/", PROFILE)
    events = model("core.AuditEvent").objects.filter(action="user.updated", object_id=str(user.pk))
    assert events.count() == 1
    event = events.get()
    assert event.actor_id == user.pk and event.ip == "198.51.100.101"
    assert event.before == {"phone": "+7 900 000-00-07", "contacts": []}
    assert event.after == {"phone": PROFILE["phone"], "contacts": ["telegram: @newcomer"]}
    client.post("/activate/profile/", PROFILE)
    assert events.count() == 1, "повтор того же профиля — не изменение"
