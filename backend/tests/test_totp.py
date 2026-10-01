"""T-107: второй фактор — TOTP и резервные коды (FR-021…025, NFR-004, NFR-011). Сценарии 3, 4, 6, 7."""
import base64
import hmac
import time

import pytest
from django.conf import settings
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tests import factories, support
from tests.support import enroll_totp, model

pytestmark = pytest.mark.django_db


def away_from_step_boundary():
    """Коды TOTP меняются каждые 30 с: не стартуем на границе шага, чтобы тест не мигал."""
    if not 3 < time.time() % 30 < 26:
        time.sleep(5)


def fresh_device(user):
    device = model("core.EncryptedTOTPDevice").objects.get(user=user, confirmed=True)
    device.last_t = -1
    device.save()
    return device


def test_totp_accepts_tolerance_one_step_rejects_replay():
    """FR-021: допуск ±1 шаг (30 с); код вне допуска и повторный код отклоняются."""
    away_from_step_boundary()
    user = support.make_employee()
    key, now = user.test_totp_key, time.time()
    code = lambda shift: factories.totp_code(key, at=now + 30 * shift)  # noqa: E731
    assert fresh_device(user).verify_token(code(0)) is True
    assert fresh_device(user).verify_token(code(-1)) is True
    assert fresh_device(user).verify_token(code(1)) is True
    assert fresh_device(user).verify_token(code(-2)) is False
    assert fresh_device(user).verify_token(code(2)) is False
    device = fresh_device(user)
    assert device.verify_token(code(0)) is True
    assert device.verify_token(code(0)) is False, "тот же код второй раз — повтор"
    assert fresh_device(user).verify_token("12345") is False and fresh_device(user).verify_token("abcdef") is False
    device = fresh_device(user)
    assert device.verify_token(code(1)) is True
    assert device.verify_token(code(0)) is False, "код более раннего шага после более позднего — тоже повтор"


def test_totp_key_stored_encrypted_not_readable_in_database():
    """NFR-011: ключ TOTP в базе только зашифрованным (Fernet, ключ из окружения), в открытом виде не читается."""
    user = support.make_employee(state="active", totp=False)
    client = support.make_client(ip="198.51.100.170")
    assert support.post_password(client, user)["Location"].endswith("/me/security/totp/")
    key, _ = enroll_totp(client, user, totp_url="/me/security/totp/", codes_url="/me/security/backup-codes/")
    with connection.cursor() as cur:
        cur.execute("SELECT * FROM core_encryptedtotpdevice WHERE user_id = %s", [user.pk])
        rows = cur.fetchall()
    stored = " ".join(str(value) for row in rows for value in row)
    for plain in (key.hex(), base64.b32encode(key).decode().rstrip("="), base64.b64encode(key).decode(), repr(key)):
        assert plain not in stored, "ключ TOTP читается из строки базы"
    device = model("core.EncryptedTOTPDevice").objects.get(user=user, confirmed=True)
    assert support.device_key(device) == key, "ключ расшифровывается ключом Fernet из окружения"
    assert device.key_encrypted != key and (device.step, device.digits, device.tolerance) == (30, 6, 1)


def test_login_requires_second_factor_every_time():
    """FR-021, NFR-004: код нужен при каждом входе, в том числе с уже известного устройства."""
    user = support.make_employee()
    client = support.make_client(ip="198.51.100.171")
    support.login(client, user)
    assert client.get("/me/").status_code == 200
    assert client.post("/logout/").status_code == 302
    again = support.post_password(client, user)
    assert again.status_code == 302 and again["Location"].endswith("/login/code/"), "известное устройство не отменяет код"
    assert client.get("/me/").status_code == 302, "после пароля, до кода, портал закрыт"
    bare = support.make_client(ip="198.51.100.172").post("/login/code/", {"code": support.current_code(user)})
    assert bare.status_code == 302 and "/login/" in bare["Location"] and "/code/" not in bare["Location"]
    done = client.post("/login/code/", {"code": support.current_code(user)})
    assert done.status_code == 302 and client.get("/me/").status_code == 200


def test_backup_codes_ten_hashed_with_hmac_shown_once():
    """FR-022, NFR-011: 10 кодов, показаны один раз; в базе — только HMAC-SHA256 с секретом из окружения."""
    user = support.make_employee(totp=False)
    client = support.make_client(ip="198.51.100.173")
    support.post_password(client, user)
    _, codes = enroll_totp(client, user, totp_url="/me/security/totp/", codes_url="/me/security/backup-codes/")
    assert len(codes) == 10 and len(set(codes)) == 10 and all(len(c) >= 10 for c in codes)
    rows = list(model("core.BackupCode").objects.filter(device__user=user))
    assert len(rows) == 10
    pepper = settings.BACKUP_CODE_PEPPER.encode()
    expected = {hmac.new(pepper, c.encode(), "sha256").hexdigest() for c in codes}
    assert {r.code_hash for r in rows} == expected
    with connection.cursor() as cur:
        cur.execute("SELECT * FROM core_backupcode")
        stored = " ".join(str(v) for row in cur.fetchall() for v in row)
    assert not any(c in stored for c in codes), "резервный код читается из базы"
    again = client.get("/me/security/backup-codes/")
    assert not any(c in again.content.decode() for c in codes), "повторно коды не показываются"


def issue_codes(user):
    from apps.core.services import second_factor

    return second_factor.issue_backup_codes(user)


def test_backup_code_single_use_and_concurrent_use_only_once():
    """FR-022: резервный код срабатывает один раз — и при повторе, и при гонке двух проверок (select_for_update)."""
    user = support.make_employee()
    codes = issue_codes(user)
    Device = model("core.BackupCodeDevice")
    first, second = Device.objects.get(user=user), Device.objects.get(user=user)
    with CaptureQueriesContext(connection) as queries:
        assert first.verify_token(codes[0]) is True
    assert any("FOR UPDATE" in q["sql"].upper() for q in queries), "проверка кода идёт под select_for_update"
    assert second.verify_token(codes[0]) is False, "второй объект устройства, загруженный раньше, код повторно не примет"
    assert Device.objects.get(user=user).verify_token(codes[0]) is False
    client = support.make_client(ip="198.51.100.174")
    support.post_password(client, user)
    done = client.post("/login/code/", {"backup_code": codes[1]})
    assert done.status_code == 302 and client.get("/me/").status_code == 200
    assert model("core.BackupCode").objects.filter(device__user=user, used_at__isnull=False).count() == 2
    assert "backup_code.used" in support.audit_actions(object_id=str(user.pk))
    late = support.make_client(ip="198.51.100.175")
    support.post_password(late, user)
    refused = late.post("/login/code/", {"backup_code": codes[1]})
    assert refused.status_code == 200 and late.get("/me/").status_code == 302
    assert model("core.LoginAttempt").objects.filter(user=user, result="bad_code").exists()


def test_new_backup_set_revokes_previous_and_shows_remaining():
    """FR-023: новый набор из 10 кодов гасит прежний; на странице безопасности видно, сколько кодов осталось."""
    user = support.make_employee()
    old = issue_codes(user)
    Device = model("core.BackupCodeDevice")
    for code in old[:3]:
        assert Device.objects.get(user=user).verify_token(code) is True
    client = support.logged_in(user)
    page = client.get("/me/security/").content.decode()
    assert 'data-backup-remaining="7"' in page
    done = client.post("/me/security/backup-codes/new/")
    assert done.status_code == 200
    fresh = support.backup_code_values(done.content.decode())
    assert len(fresh) == 10 and not set(fresh) & set(old)
    for code in old[3:]:
        assert not any(d.verify_token(code) for d in Device.objects.filter(user=user)), "прежний набор перестал действовать"
    assert 'data-backup-remaining="10"' in client.get("/me/security/").content.decode()
    assert Device.objects.get(user=user).verify_token(fresh[0]) is True
    assert "backup_codes.issued" in support.audit_actions(object_id=str(user.pk))


def test_admin_resets_second_factor_revokes_secret_and_codes_mails_user():
    """FR-024 (сценарий 7): сброс гасит ключ и резервные коды, письмо уходит сотруднику, событие — в журнале."""
    user = support.make_employee()
    codes = issue_codes(user)
    admin = support.make_admin()
    client = support.logged_in(admin)
    done = client.post(f"/staff/{user.pk}/reset-2fa/")
    assert done.status_code == 302
    assert not model("core.EncryptedTOTPDevice").objects.filter(user=user, confirmed=True).exists()
    assert not any(d.verify_token(c) for d in model("core.BackupCodeDevice").objects.filter(user=user) for c in codes)
    assert support.mails(to=user.email, template="second_factor_reset").count() == 1
    event = model("core.AuditEvent").objects.get(action="totp.reset", object_id=str(user.pk))
    assert event.actor_id == admin.pk
    assert user.test_totp_key.hex() not in str(event.before) + str(event.after)
    nobody = support.logged_in(support.make_with_permissions("accounts.manage"), ip="198.51.100.176")
    assert nobody.post(f"/staff/{support.make_employee().pk}/reset-2fa/").status_code == 403
    assert f"/staff/{user.pk}/reset-2fa/" not in nobody.get(f"/staff/{user.pk}/").content.decode(), "кнопки сброса без права нет"


def test_admin_cannot_reset_own_second_factor():
    """FR-024 (сценарий 7.5): свой второй фактор администратор не сбрасывает — это делает другой администратор."""
    admin = support.make_admin()
    client = support.logged_in(admin)
    done = client.post(f"/staff/{admin.pk}/reset-2fa/", follow=True)
    assert done.status_code in (200, 400, 403)
    assert model("core.EncryptedTOTPDevice").objects.filter(user=admin, confirmed=True).count() == 1
    assert not support.mails(to=admin.email, template="second_factor_reset")
    assert f"/staff/{admin.pk}/reset-2fa/" not in client.get(f"/staff/{admin.pk}/").content.decode()
    other = support.make_employee()
    assert f"/staff/{other.pk}/reset-2fa/" in client.get(f"/staff/{other.pk}/").content.decode()


def test_bad_totp_and_backup_codes_count_as_failed_attempts():
    """FR-025: неверный код приложения и неверный резервный код — такие же неудачи, как неверный пароль; на пятой запись блокируется."""
    user = support.make_employee()
    wrong_code = lambda: "".join(str((int(c) + 3) % 10) for c in support.current_code(user))  # noqa: E731
    for attempt in range(5):
        client = support.make_client(ip=f"198.51.100.{180 + attempt}")
        assert support.post_password(client, user).status_code == 302
        if attempt % 2:
            done = client.post("/login/code/", {"backup_code": factories.new_password()})
        else:
            done = client.post("/login/code/", {"code": wrong_code()})
        assert done.status_code == 200 and client.get("/me/").status_code == 302
        if attempt < 4:
            assert support.valkey_int(f"fail:acct:{user.pk}") == attempt + 1
    assert model("core.LoginAttempt").objects.filter(user=user, result="bad_code").count() == 5
    assert support.valkey_key(f"lock:acct:{user.pk}"), "пять неверных кодов блокируют запись"
    good = support.make_client(ip="198.51.100.190")
    support.post_password(good, user)
    good.post("/login/code/", {"code": support.current_code(user)})
    assert good.get("/me/").status_code == 302, "заблокированная запись не входит и с верным кодом"


def test_bad_code_at_totp_setup_and_bad_current_password_count_as_failures():
    """FR-025 (сценарии 3.4, 16.4): неверный код при подключении фактора и неверный текущий пароль при смене — неудачи."""
    newcomer = support.make_employee(totp=False)
    client = support.make_client(ip="198.51.100.191")
    support.post_password(client, newcomer)
    client.get("/me/security/totp/")
    for _ in range(3):
        done = client.post("/me/security/totp/", {"code": "000000"})
        assert done.status_code == 200
    assert support.valkey_int(f"fail:acct:{newcomer.pk}") == 3
    assert not model("core.EncryptedTOTPDevice").objects.filter(user=newcomer, confirmed=True).exists()
    owner = support.make_employee()
    session = support.logged_in(owner, ip="198.51.100.192")
    new = factories.new_password()
    for n in range(1, 6):
        done = session.post("/me/security/password/", {"current_password": factories.new_password(),
                                                       "password1": new, "password2": new})
        assert done.status_code in (200, 403)
        if n < 5:
            assert support.valkey_int(f"fail:acct:{owner.pk}") == n
    owner.refresh_from_db()
    assert owner.check_password(owner.test_password), "пароль не сменился"
    assert support.valkey_key(f"lock:acct:{owner.pk}"), "пять неверных текущих паролей блокируют запись"
