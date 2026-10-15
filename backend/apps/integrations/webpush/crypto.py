"""Шифрование Web Push (aes128gcm) и подпись VAPID (PLAN-004, «Где живёт код»).

Шифрование — RFC 8291 поверх RFC 8188: ECDH P-256, HKDF-SHA256, AES-128-GCM, одна запись `rs=4096`. Подпись VAPID —
RFC 8292: JWT ES256. Тексты `CryptoError` фиксированные и без ключей, солей и подписей (NFR-312): внутренние
исключения библиотеки в цепочку не попадают (`from None`).
"""
import base64
import json
import os
from typing import NamedTuple
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.asymmetric.utils import decode_dss_signature
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.utils import timezone

RECORD_SIZE = 4096
MAX_PLAINTEXT = 3993          # 4096 - 86 (заголовок) - 1 (разделитель 0x02) - 16 (тег GCM)
VAPID_LIFETIME = 43200        # 12 часов

ERROR_SUBSCRIPTION = "неверные ключи подписки"
ERROR_VAPID = "неверный ключ VAPID"
ERROR_LENGTH = "нагрузка слишком длинная"


class CryptoError(ValueError):
    """Ошибка шифрования или подписи; текст фиксированный, без ключей (NFR-312)."""


class Encrypted(NamedTuple):
    """Тело aes128gcm и промежуточные значения RFC 8291 (для побайтной сверки в тестах)."""
    body: bytes
    ecdh_secret: bytes
    ikm: bytes
    content_key: bytes
    nonce: bytes
    salt: bytes
    sender_public: bytes


def _b64decode(text: str) -> bytes:
    """base64url с дополнением или без; ошибка — `ValueError` без значения."""
    if not isinstance(text, str) or not text or not text.isascii():
        raise ValueError
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _private_key(raw: bytes) -> ec.EllipticCurvePrivateKey:
    """Закрытый ключ P-256 из 32 байт скаляра; иной размер или скаляр вне диапазона — `ValueError`."""
    if len(raw) != 32:
        raise ValueError
    return ec.derive_private_key(int.from_bytes(raw, "big"), ec.SECP256R1())


def _public_bytes(key: ec.EllipticCurvePublicKey) -> bytes:
    return key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)


def encrypt_detail(payload: bytes, p256dh: str, auth: str, *, salt: bytes | None = None,
                   sender_private_key: bytes | None = None) -> Encrypted:
    """Зашифровать `payload` для подписки (RFC 8291) и вернуть тело вместе с промежуточными значениями."""
    if len(payload) > MAX_PLAINTEXT:
        raise CryptoError(ERROR_LENGTH)
    try:
        receiver_point = _b64decode(p256dh)
        auth_secret = _b64decode(auth)
        if len(receiver_point) != 65 or receiver_point[0] != 4:
            raise ValueError
        receiver = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), receiver_point)
        sender = _private_key(sender_private_key) if sender_private_key is not None \
            else ec.generate_private_key(ec.SECP256R1())
        salt = os.urandom(16) if salt is None else salt
        if len(salt) != 16:
            raise ValueError
        sender_public = _public_bytes(sender.public_key())
        ecdh_secret = sender.exchange(ec.ECDH(), receiver)
        ikm = HKDF(hashes.SHA256(), 32, auth_secret,
                   b"WebPush: info\x00" + receiver_point + sender_public).derive(ecdh_secret)
        content_key = HKDF(hashes.SHA256(), 16, salt, b"Content-Encoding: aes128gcm\x00").derive(ikm)
        nonce = HKDF(hashes.SHA256(), 12, salt, b"Content-Encoding: nonce\x00").derive(ikm)
    except Exception:  # любые сбои разбора ключей: детали (и сами ключи) в текст не попадают
        raise CryptoError(ERROR_SUBSCRIPTION) from None
    ciphertext = AESGCM(content_key).encrypt(nonce, payload + b"\x02", None)
    body = salt + RECORD_SIZE.to_bytes(4, "big") + bytes([len(sender_public)]) + sender_public + ciphertext
    return Encrypted(body, ecdh_secret, ikm, content_key, nonce, salt, sender_public)


def encrypt(payload: bytes, p256dh: str, auth: str, *, salt: bytes | None = None,
            sender_private_key: bytes | None = None) -> bytes:
    """Полное тело aes128gcm одной записью: `salt ‖ rs ‖ idlen ‖ ключ отправителя ‖ шифртекст`."""
    return encrypt_detail(payload, p256dh, auth, salt=salt, sender_private_key=sender_private_key).body


def vapid(endpoint: str, private_key: str, subject: str) -> str:
    """Значение заголовка `Authorization` для адреса подписки: `vapid t=<JWT ES256>, k=<открытый ключ>`."""
    try:
        key = _private_key(_b64decode(private_key))
    except Exception:
        raise CryptoError(ERROR_VAPID) from None
    parts = urlsplit(endpoint)
    claims = {"aud": f"{parts.scheme}://{parts.netloc}",
              "exp": int(timezone.now().timestamp()) + VAPID_LIFETIME, "sub": subject}
    header = {"typ": "JWT", "alg": "ES256"}
    signing_input = ".".join(
        _b64encode(json.dumps(part, separators=(",", ":"), ensure_ascii=False).encode("utf-8"))
        for part in (header, claims))
    r, s = decode_dss_signature(key.sign(signing_input.encode("ascii"), ec.ECDSA(hashes.SHA256())))
    signature = r.to_bytes(32, "big") + s.to_bytes(32, "big")
    public = _b64encode(_public_bytes(key.public_key()))
    return f"vapid t={signing_input}.{_b64encode(signature)}, k={public}"


def generate_vapid_keys() -> tuple[str, str]:
    """Новая пара VAPID: (закрытый 32 байта, открытый 65 байт), оба base64url без дополнения."""
    key = ec.generate_private_key(ec.SECP256R1())
    private = key.private_numbers().private_value.to_bytes(32, "big")
    return _b64encode(private), _b64encode(_public_bytes(key.public_key()))
