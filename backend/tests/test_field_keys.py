"""T-119: смена ключей шифрования полей (NFR-011, FR-009, FR-021, FR-046).

`python manage.py rotate_field_keys` перешифровывает `EncryptedTOTPDevice.key_encrypted` и
`OneTimeLink.code_encrypted` первым ключом `settings.FIELD_ENCRYPTION_KEYS` через `MultiFernet.rotate()`.
Ключи подменяются через `settings` (приложение обязано читать их при вызове, а не при импорте).
"""
from io import StringIO

import pytest
from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.core.management import CommandError, call_command

from tests import factories, support
from tests.support import model

pytestmark = pytest.mark.django_db


def new_key() -> str:
    return Fernet.generate_key().decode()


def opens_with(token: str, *keys: str) -> bytes:
    return MultiFernet([Fernet(k) for k in keys]).decrypt(token.encode())


def cannot_open(token: str, key: str) -> bool:
    try:
        Fernet(key).decrypt(token.encode())
    except InvalidToken:
        return True
    return False


def prepare(settings, old: str):
    """Сотрудник с устройством TOTP и ссылкой активации, зашифрованными старым ключом."""
    settings.FIELD_ENCRYPTION_KEYS = [old]
    user = support.make_employee()
    invited = support.make_employee(state="invited", totp=False)
    link, code = factories.make_link(invited, "activation")
    return user, support.model("core.EncryptedTOTPDevice").objects.get(user=user), invited, link, code


def run() -> str:
    out = StringIO()
    call_command("rotate_field_keys", stdout=out, stderr=out)
    return out.getvalue()


def test_rotate_field_keys_reencrypts_totp_keys_and_link_codes_with_new_first_key(settings):
    """NFR-011: после команды оба поля открываются новым первым ключом; прежний шифротекст — другой, открытые значения те же."""
    old, new = new_key(), new_key()
    user, device, invited, link, code = prepare(settings, old)
    before_device, before_link = device.key_encrypted, link.code_encrypted
    settings.FIELD_ENCRYPTION_KEYS = [new, old]
    run()
    device.refresh_from_db()
    link.refresh_from_db()
    assert device.key_encrypted != before_device and link.code_encrypted != before_link
    assert cannot_open(device.key_encrypted, old) and cannot_open(link.code_encrypted, old), "теперь шифрует первый ключ"
    assert opens_with(device.key_encrypted, new) == user.test_totp_key
    assert opens_with(link.code_encrypted, new).decode() == code


def test_after_rotation_old_key_removed_totp_login_and_admin_link_view_still_work(settings):
    """NFR-011, FR-009, FR-021: старый ключ убран из списка — вход с кодом TOTP и показ ссылки активации администратору работают."""
    old, new = new_key(), new_key()
    user, device, invited, link, code = prepare(settings, old)
    admin_user = support.make_admin()
    settings.FIELD_ENCRYPTION_KEYS = [new, old]
    run()
    settings.FIELD_ENCRYPTION_KEYS = [new]
    support.login(support.make_client(ip="198.51.100.200"), user)
    admin = support.logged_in(admin_user, ip="198.51.100.201")
    card = admin.get(f"/staff/{invited.pk}/").content.decode()
    assert f"{settings.PORTAL_URL}/activate/#{code}" in card
    exchange = support.make_client(ip="198.51.100.202").post("/activate/exchange/", {"code": code})
    assert exchange.status_code == 302, "ссылка активации продолжает работать"


def test_rotate_field_keys_is_idempotent_and_does_not_log_key_material(settings, caplog):
    """NFR-011, FR-046: повторный запуск безопасен; ни вывод команды, ни журнал приложения, ни события не содержат ключей и секретов."""
    old, new = new_key(), new_key()
    user, device, invited, link, code = prepare(settings, old)
    settings.FIELD_ENCRYPTION_KEYS = [new, old]
    with caplog.at_level("DEBUG"):
        first, second = run(), run()
    device.refresh_from_db()
    link.refresh_from_db()
    assert opens_with(device.key_encrypted, new) == user.test_totp_key and opens_with(link.code_encrypted, new).decode() == code
    assert model("core.EncryptedTOTPDevice").objects.filter(confirmed=True).count() == 1
    audit = " ".join(str(e.before) + str(e.after) for e in model("core.AuditEvent").objects.all())
    for secret in (old, new, user.test_totp_key.hex(), code, device.key_encrypted, link.code_encrypted):
        for where, text in (("вывод", first + second), ("журнал", caplog.text), ("аудит", audit)):
            assert secret not in text, f"{where}: ключевой материал"
    support.login(support.make_client(ip="198.51.100.203"), user)


def test_rotation_without_old_key_in_list_fails_loudly_and_changes_nothing(settings):
    """NFR-011: если шифротекст не открывается ни одним ключом списка (старый ключ убрали рано), команда падает с ошибкой и не меняет ни одной строки."""
    old, new, lost = new_key(), new_key(), new_key()
    user, device, invited, link, code = prepare(settings, old)
    settings.FIELD_ENCRYPTION_KEYS = [lost]
    stranger = support.make_employee(state="invited", totp=False)
    stranger_link, _ = factories.make_link(stranger, "activation")
    settings.FIELD_ENCRYPTION_KEYS = [new, old]
    before = {
        "device": model("core.EncryptedTOTPDevice").objects.get(pk=device.pk).key_encrypted,
        "link": model("core.OneTimeLink").objects.get(pk=link.pk).code_encrypted,
        "stranger": model("core.OneTimeLink").objects.get(pk=stranger_link.pk).code_encrypted,
    }
    with pytest.raises(CommandError):
        call_command("rotate_field_keys", stdout=StringIO(), stderr=StringIO())
    after = {
        "device": model("core.EncryptedTOTPDevice").objects.get(pk=device.pk).key_encrypted,
        "link": model("core.OneTimeLink").objects.get(pk=link.pk).code_encrypted,
        "stranger": model("core.OneTimeLink").objects.get(pk=stranger_link.pk).code_encrypted,
    }
    assert after == before, "частичная смена ключей недопустима"
