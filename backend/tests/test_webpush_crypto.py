"""T-4114: шифрование aes128gcm (RFC 8291) и подпись VAPID Web Push (FR-324, NFR-312). Сценарий 5 спеки SPEC-004.

Правила — tests/CONTRACT-004.md § 5.3 (`crypto.encrypt`, `encrypt_detail`, `vapid`, `CryptoError`, константы
`RFC8291_*`), шапка (решение 23 задач: секреты только сгенерированные на месте, значения не печатаются). Имена кода
среза 004 импортируются внутри тестов: сбор проходит до появления кода. Базы и сети тесты не трогают.
Ключи браузера — `support_notify.browser_keys()`; подпись VAPID проверяется библиотекой `cryptography`.
Допущение: JWT без знаков `=` (RFC 7515) — тест проверяет это для всех трёх частей, хотя контракт требует «без дополнения» только для `k`.
"""
import base64
import json
import re
from datetime import datetime, timezone as dt_timezone

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from tests import support_notify as sn

ENDPOINT = "https://fcm.googleapis.com/fcm/send/abc123-device"
SUBJECT = "mailto:it@portal.example.test"
MOMENT = datetime(2026, 10, 12, 9, 0, 0, 600000, tzinfo=dt_timezone.utc)
FIXED_VAPID_ERROR = "неверный ключ VAPID"
FIXED_SUBSCRIPTION_ERROR = "неверные ключи подписки"
FIXED_LENGTH_ERROR = "нагрузка слишком длинная"


# --- помощники файла ----------------------------------------------------------------------------------

def _crypto():
    from apps.integrations.webpush import crypto
    return crypto


def _text(raw: bytes) -> str:
    """base64url без дополнения."""
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _raw(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _vapid_pair():
    """Новая пара VAPID: (закрытый — base64url 32 байта, открытый — 65 байт)."""
    pair = ec.generate_private_key(ec.SECP256R1())
    priv = pair.private_numbers().private_value.to_bytes(32, "big")
    pub = pair.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    return _text(priv), pub


def _split_header(header: str):
    """`vapid t=<JWT>, k=<открытый>` → (три части JWT, открытый ключ текстом)."""
    found = re.fullmatch(r"vapid t=([^,\s]+), k=(\S+)", header)
    assert found, "значение Authorization не по форме «vapid t=…, k=…»"
    parts = found.group(1).split(".")
    assert len(parts) == 3
    return parts, found.group(2)


def _claims(header: str) -> dict:
    parts, _ = _split_header(header)
    return json.loads(_raw(parts[1]))


def _decrypt(body: bytes, browser) -> bytes:
    """Открытый текст из тела aes128gcm одной записью вместе с разделителем (RFC 8188/8291), без обрезки нулей."""
    salt, id_len = body[:16], body[20]
    sender_point = body[21:21 + id_len]
    receiver_point = _raw(browser.p256dh)
    receiver = ec.derive_private_key(int.from_bytes(browser.private, "big"), ec.SECP256R1())
    sender = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), sender_point)
    shared = receiver.exchange(ec.ECDH(), sender)
    ikm = HKDF(hashes.SHA256(), 32, browser.auth_raw, b"WebPush: info\x00" + receiver_point + sender_point).derive(shared)
    cek = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
    nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    return AESGCM(cek).decrypt(nonce, body[21 + id_len:], None)


def _rfc_args():
    return sn.RFC8291_PLAINTEXT, _text(sn.RFC8291_RECEIVER_PUB), _text(sn.RFC8291_AUTH)


def _rfc_detail():
    payload, p256dh, auth = _rfc_args()
    return _crypto().encrypt_detail(payload, p256dh, auth, salt=sn.RFC8291_SALT,
                                    sender_private_key=sn.RFC8291_SENDER_PRIV)


def _leaks(message: str, *values) -> list[str]:
    """Какие из значений (текст, байты, их base64url и hex) встречаются в сообщении."""
    found = []
    for value in values:
        forms = [value] if isinstance(value, str) else [_text(value), base64.urlsafe_b64encode(value).decode(),
                                                          base64.b64encode(value).decode(), value.hex()]
        found += [form for form in forms if form and form in message]
    return found


# --- приложение A RFC 8291 -----------------------------------------------------------------------------

def test_rfc8291_appendix_a_ciphertext_matches_byte_for_byte():
    """FR-324: с солью и ключом отправителя из приложения A RFC 8291 тело совпадает с вектором побайтно; `encrypt` — то же."""
    payload, p256dh, auth = _rfc_args()
    body = _crypto().encrypt(payload, p256dh, auth, salt=sn.RFC8291_SALT, sender_private_key=sn.RFC8291_SENDER_PRIV)
    assert body == sn.RFC8291_BODY
    assert _rfc_detail().body == sn.RFC8291_BODY
    padded = _crypto().encrypt(payload, p256dh + "=" * (-len(p256dh) % 4), auth + "=" * (-len(auth) % 4),
                               salt=sn.RFC8291_SALT, sender_private_key=sn.RFC8291_SENDER_PRIV)
    assert padded == sn.RFC8291_BODY


def test_rfc8291_appendix_a_ecdh_secret_and_ikm_match():
    """FR-324: общий секрет ECDH и IKM из `encrypt_detail` совпадают с приложением A."""
    detail = _rfc_detail()
    assert detail.ecdh_secret == sn.RFC8291_ECDH
    assert detail.ikm == sn.RFC8291_IKM


def test_rfc8291_appendix_a_content_key_and_nonce_match():
    """FR-324: ключ содержимого (16 байт) и nonce (12 байт) совпадают с приложением A."""
    detail = _rfc_detail()
    assert len(detail.content_key) == 16 and len(detail.nonce) == 12
    assert detail.content_key == sn.RFC8291_CEK
    assert detail.nonce == sn.RFC8291_NONCE


def test_rfc8291_appendix_a_header_is_salt_rs_idlen_and_sender_key():
    """FR-324: заголовок тела — соль (16) ‖ rs=4096 (4 байта) ‖ idlen=65 (1 байт) ‖ открытый ключ отправителя (65)."""
    detail = _rfc_detail()
    body = detail.body
    assert body[:16] == sn.RFC8291_SALT
    assert body[16:20] == (4096).to_bytes(4, "big")
    assert body[20] == 65
    assert body[21:86] == sn.RFC8291_SENDER_PUB
    assert detail.salt == sn.RFC8291_SALT
    assert detail.sender_public == sn.RFC8291_SENDER_PUB


# --- форма записи ---------------------------------------------------------------------------------------

def test_encrypt_makes_single_record_with_rs_4096():
    """FR-324: одна запись, rs = 4096; шифртекст = открытый текст + разделитель 0x02 + тег 16 байт, без добавки нулей."""
    browser = sn.browser_keys()
    payload = '{"title":"Новое уведомление","url":"/notifications/","tag":"n-1"}'.encode("utf-8")
    body = _crypto().encrypt(payload, browser.p256dh, browser.auth)
    assert body[16:20] == (4096).to_bytes(4, "big")
    assert body[20] == 65
    assert len(body) == 86 + len(payload) + 1 + 16
    assert _decrypt(body, browser) == payload + b"\x02"


def test_encrypt_accepts_plaintext_of_3993_bytes():
    """FR-324: открытый текст в 3993 байта принимается; тело ровно 4096 байт и расшифровывается."""
    browser = sn.browser_keys()
    payload = bytes(range(256)) * 15 + bytes(153)
    assert len(payload) == 3993
    body = _crypto().encrypt(payload, browser.p256dh, browser.auth)
    assert len(body) == 4096
    assert _decrypt(body, browser) == payload + b"\x02"


def test_encrypt_rejects_plaintext_of_3994_bytes():
    """FR-324: 3994 байта — `CryptoError` с фиксированным текстом «нагрузка слишком длинная»; это `ValueError`."""
    crypto = _crypto()
    browser = sn.browser_keys()
    assert issubclass(crypto.CryptoError, ValueError)
    with pytest.raises(crypto.CryptoError) as caught:
        crypto.encrypt(b"x" * 3994, browser.p256dh, browser.auth)
    assert str(caught.value) == FIXED_LENGTH_ERROR


def test_encrypted_payload_of_about_100_bytes_decrypts_with_browser_keys():
    """FR-324: нагрузка около 100 байт расшифровывается ключами браузера (адреса с дополнением и без); текст тот же."""
    crypto = _crypto()
    browser = sn.browser_keys()
    payload = json.dumps({"title": "У вас 3 новых уведомления", "url": "/notifications/", "tag": "digest"},
                         ensure_ascii=False).encode("utf-8")
    assert 80 <= len(payload) <= 120
    for p256dh, auth in ((browser.p256dh, browser.auth),
                         (browser.p256dh + "=" * (-len(browser.p256dh) % 4), browser.auth + "=" * (-len(browser.auth) % 4))):
        body = crypto.encrypt(payload, p256dh, auth)
        assert _decrypt(body, browser) == payload + b"\x02"
    other = sn.browser_keys()
    with pytest.raises(Exception):
        _decrypt(crypto.encrypt(payload, browser.p256dh, browser.auth), other)


def test_encrypt_uses_new_salt_and_new_sender_key_on_each_call():
    """FR-324: без `salt` и `sender_private_key` каждый вызов берёт новую соль и новый ключ отправителя."""
    crypto = _crypto()
    browser = sn.browser_keys()
    payload = b'{"title":"t","url":"/notifications/","tag":"n-2"}'
    first = crypto.encrypt_detail(payload, browser.p256dh, browser.auth)
    second = crypto.encrypt_detail(payload, browser.p256dh, browser.auth)
    assert len(first.salt) == 16 and len(first.sender_public) == 65
    assert first.salt != second.salt
    assert first.sender_public != second.sender_public
    assert first.body[:16] == first.salt and first.body[21:86] == first.sender_public
    assert first.body != second.body
    assert _decrypt(first.body, browser) == payload + b"\x02"
    assert _decrypt(second.body, browser) == payload + b"\x02"


# --- VAPID ---------------------------------------------------------------------------------------------

def test_vapid_signature_verifies_with_public_key():
    """FR-324: подпись JWT проверяется открытым ключом `k` и ключом, вычисленным из закрытого; чужая нагрузка — нет."""
    priv, pub = _vapid_pair()
    header = _crypto().vapid(ENDPOINT, priv, SUBJECT)
    parts, pub_text = _split_header(header)
    assert _raw(pub_text) == pub
    point = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), pub)
    signature = _raw(parts[2])
    assert len(signature) == 64
    der = encode_dss_signature(int.from_bytes(signature[:32], "big"), int.from_bytes(signature[32:], "big"))
    signing_input = f"{parts[0]}.{parts[1]}".encode("ascii")
    point.verify(der, signing_input, ec.ECDSA(hashes.SHA256()))
    forged = _text(json.dumps({**json.loads(_raw(parts[1])), "sub": "mailto:other@portal.example.test"}).encode())
    with pytest.raises(InvalidSignature):
        point.verify(der, f"{parts[0]}.{forged}".encode("ascii"), ec.ECDSA(hashes.SHA256()))


def test_vapid_signature_is_es256_raw_64_bytes_and_header_alg():
    """FR-324: заголовок JWT — {"typ": "JWT", "alg": "ES256"}; подпись — 64 байта `r ‖ s`, не DER."""
    priv, _ = _vapid_pair()
    parts, _ = _split_header(_crypto().vapid(ENDPOINT, priv, SUBJECT))
    assert json.loads(_raw(parts[0])) == {"typ": "JWT", "alg": "ES256"}
    signature = _raw(parts[2])
    assert len(signature) == 64
    assert all("=" not in part for part in parts)


def test_vapid_aud_is_origin_of_subscription_endpoint_without_path():
    """FR-324: `aud` — схема и хост адреса подписки (с портом, если он есть) без пути и запроса."""
    priv, _ = _vapid_pair()
    crypto = _crypto()
    assert _claims(crypto.vapid(ENDPOINT, priv, SUBJECT))["aud"] == "https://fcm.googleapis.com"
    assert _claims(crypto.vapid("https://push.portal.example.test:8443/wpush/v2/abc?x=1", priv, SUBJECT))["aud"] \
        == "https://push.portal.example.test:8443"
    assert _claims(crypto.vapid("https://updates.push.services.mozilla.com/wpush/v2/Zm9v", priv, SUBJECT))["aud"] \
        == "https://updates.push.services.mozilla.com"


def test_vapid_exp_is_12_hours_after_now(clock):
    """FR-324: `exp` = целые секунды `timezone.now()` + 43200; сдвиг часов сдвигает `exp`."""
    priv, _ = _vapid_pair()
    crypto = _crypto()
    clock.set(MOMENT)
    assert _claims(crypto.vapid(ENDPOINT, priv, SUBJECT))["exp"] == int(MOMENT.timestamp()) + 43200
    clock.advance(hours=5, minutes=30)
    later = MOMENT.timestamp() + 5.5 * 3600
    assert _claims(crypto.vapid(ENDPOINT, priv, SUBJECT))["exp"] == int(later) + 43200


def test_vapid_sub_equals_given_subject():
    """FR-324: `sub` — переданная строка subject дословно; в полезной части ровно три поля aud, exp, sub."""
    priv, _ = _vapid_pair()
    crypto = _crypto()
    for subject in (SUBJECT, "https://portal.example.test/contact"):
        claims = _claims(crypto.vapid(ENDPOINT, priv, subject))
        assert claims["sub"] == subject
        assert set(claims) == {"aud", "exp", "sub"}


def test_vapid_authorization_header_has_vapid_t_and_k_parts():
    """FR-324: значение — `vapid t=<JWT>, k=<65 байт base64url без дополнения, 0x04…>`; JWT из трёх частей."""
    priv, pub = _vapid_pair()
    header = _crypto().vapid(ENDPOINT, priv, SUBJECT)
    assert header.startswith("vapid t=")
    parts, pub_text = _split_header(header)
    assert len(parts) == 3 and all(parts)
    assert "=" not in pub_text
    decoded = _raw(pub_text)
    assert len(decoded) == 65 and decoded[0] == 4
    assert decoded == pub


# --- ошибки без утечки ключей (NFR-312) -------------------------------------------------------------------

def test_private_key_not_in_exception_on_bad_key_material():
    """NFR-312: плохой закрытый ключ VAPID — `CryptoError` с фиксированным текстом; ни текста, ни байтов ключа в нём нет."""
    crypto = _crypto()
    short = bytes(range(1, 32))
    zero = bytes(32)
    too_big = b"\xff" * 32
    for bad in ("@@@@не-base64@@@@", _text(short), _text(zero), _text(too_big), _text(bytes(range(1, 34))), "AAAAA", ""):
        with pytest.raises(crypto.CryptoError) as caught:
            crypto.vapid(ENDPOINT, bad, SUBJECT)
        message = str(caught.value)
        assert message == FIXED_VAPID_ERROR
        assert not _leaks(message, bad, short, zero, too_big)
        assert not _leaks(repr(caught.value), bad, short, zero, too_big)


def test_private_key_not_in_exception_on_bad_subscription_keys():
    """NFR-312: плохие ключи подписки — `CryptoError` «неверные ключи подписки»; в тексте нет ни ключей подписки, ни ключа отправителя."""
    crypto = _crypto()
    browser = sn.browser_keys()
    off_curve = b"\x04" + bytes(range(1, 65))
    truncated = _raw(browser.p256dh)[:33]
    bad_values = ["@@@@не-base64@@@@", "AAAAA", _text(off_curve), _text(truncated), ""]
    for bad in bad_values:
        with pytest.raises(crypto.CryptoError) as caught:
            crypto.encrypt(b'{"title":"t"}', bad, browser.auth, sender_private_key=sn.RFC8291_SENDER_PRIV)
        message = str(caught.value)
        assert message == FIXED_SUBSCRIPTION_ERROR
        assert not _leaks(message, bad, off_curve, truncated, browser.auth, browser.auth_raw, sn.RFC8291_SENDER_PRIV)
        assert not _leaks(repr(caught.value), bad, off_curve, truncated, browser.auth, browser.auth_raw,
                          sn.RFC8291_SENDER_PRIV)
