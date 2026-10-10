"""T-4121: доверие TLS к корню Минцифры у адаптера MAX (FR-325). Сценарии привязки бота спеки 004.

Файл корня «Russian Trusted Root CA» лежит рядом с адаптером MAX (расширение `.crt`, решение владельца), контекст
TLS адаптера MAX содержит только его, контекст адаптера Telegram — системное хранилище без этого корня. Два живых
теста пропускаются без выхода в интернет (решение 8 задач) и выполняются на стенде. Код среза на уровне модуля не
импортируется (CONTRACT-004, шапка).
"""
import datetime
import hashlib
import pathlib
import socket
import ssl

import pytest

# Отпечаток SHA-256 корня в DER-форме (CONTRACT-004 § 1.3, «Корень MAX»): без двоеточий, в нижнем регистре.
ROOT_CA_SHA256 = "D2:6D:2D:02:31:B7:C3:9F:92:CC:73:85:12:BA:54:10:35:19:E4:40:5D:68:B5:BD:70:3E:97:88:CA:8E:CF:31"
ROOT_FINGERPRINT = ROOT_CA_SHA256.replace(":", "").lower()
ROOT_FILE_NAME = "russian_trusted_root_ca.crt"


# --- помощники только этого файла -------------------------------------------------------------------

def _root_path() -> pathlib.Path:
    """Путь файла корня: `<каталог адаптера MAX>/certs/russian_trusted_root_ca.crt` (§ 1.3)."""
    import apps.integrations.max as max_package

    return pathlib.Path(max_package.__file__).parent / "certs" / ROOT_FILE_NAME


def _root_text() -> str:
    return _root_path().read_text(encoding="ascii")


def _root_der() -> bytes:
    return ssl.PEM_cert_to_DER_cert(_root_text())


def _fingerprint(der: bytes) -> str:
    return hashlib.sha256(der).hexdigest()


def _max_client():
    from apps.integrations.max import client

    return client


def _telegram_client():
    from apps.integrations.telegram import client

    return client


def _connect_or_skip(host: str) -> socket.socket:
    """TCP-соединение с узлом; нет выхода в интернет — пропуск с причиной (решение 8 задач)."""
    try:
        return socket.create_connection((host, 443), timeout=8)
    except OSError as error:
        pytest.skip(f"нет выхода в интернет к {host}:443 ({type(error).__name__}); тест выполняется на стенде")


# --- файл корня -------------------------------------------------------------------------------------

def test_root_file_sha256_equals_pinned_value():
    """FR-325: SHA-256 DER-формы сертификата из файла корня равен закреплённому отпечатку контракта (не хеш файла)."""
    assert _fingerprint(_root_der()) == ROOT_FINGERPRINT


def test_root_file_is_single_certificate_valid_until_2032_02_27():
    """FR-325: в файле один сертификат PEM, срок действия (`notAfter`, UTC) — 2032-02-27 21:04:15."""
    from cryptography import x509

    text = _root_text()
    assert text.count("-----BEGIN CERTIFICATE-----") == 1
    assert text.count("-----END CERTIFICATE-----") == 1
    assert "PRIVATE KEY" not in text
    cert = x509.load_pem_x509_certificate(text.encode("ascii"))
    assert cert.not_valid_after_utc == datetime.datetime(2032, 2, 27, 21, 4, 15, tzinfo=datetime.timezone.utc)
    assert cert.not_valid_before_utc < datetime.datetime.now(datetime.timezone.utc)


def test_root_file_lies_in_max_adapter_certs_directory():
    """FR-325: файл `russian_trusted_root_ca.crt` лежит в `apps/integrations/max/certs/` (расширение `.crt`, не `.pem`)."""
    path = _root_path()
    assert path.is_file()
    assert path.parent.name == "certs"
    assert path.parent.parent.name == "max"
    assert path.parent.parent.parent.name == "integrations"
    assert path.suffix == ".crt"
    assert not list(path.parent.glob("*.pem"))


# --- построители контекста TLS ----------------------------------------------------------------------

def test_max_adapter_context_is_built_with_cafile_and_holds_only_that_root():
    """FR-325: `max.client.ssl_context()` — проверяющий контекст с `cafile=CA_FILE`; в нём ровно корень Минцифры."""
    client = _max_client()
    assert pathlib.Path(client.CA_FILE) == _root_path()
    ctx = client.ssl_context()
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    assert ctx.get_ca_certs(binary_form=True) == [_root_der()]
    subject = dict(item[0] for item in ctx.get_ca_certs()[0]["subject"])
    assert subject.get("commonName") == "Russian Trusted Root CA"


def test_max_adapter_does_not_load_system_trust_store():
    """FR-325: системное хранилище в контекст MAX не загружено: `get_ca_certs()` — ровно один сертификат."""
    ctx = _max_client().ssl_context()
    loaded = ctx.get_ca_certs(binary_form=True)
    assert len(loaded) == 1
    assert _fingerprint(loaded[0]) == ROOT_FINGERPRINT


def test_telegram_adapter_uses_system_trust_store_and_not_the_ministry_root():
    """FR-325: `telegram.client.ssl_context()` — обычный проверяющий контекст без корня Минцифры (решение E13)."""
    ctx = _telegram_client().ssl_context()
    assert isinstance(ctx, ssl.SSLContext)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    prints = {_fingerprint(der) for der in ctx.get_ca_certs(binary_form=True)}
    assert ROOT_FINGERPRINT not in prints
    assert ctx.get_ca_certs(binary_form=True) != _max_client().ssl_context().get_ca_certs(binary_form=True)


# --- живые проверки (пропуск без выхода в интернет) ---------------------------------------------------

def test_live_tls_to_platform_api2_max_ru_passes_with_ministry_root():
    """FR-325: рукопожатие TLS с `platform-api2.max.ru` проходит с контекстом адаптера MAX (корень Минцифры)."""
    host = "platform-api2.max.ru"
    ctx = _max_client().ssl_context()
    raw = _connect_or_skip(host)
    with raw:
        with ctx.wrap_socket(raw, server_hostname=host) as tls:
            assert tls.version() is not None
            assert tls.getpeercert()


def test_live_tls_to_api_telegram_org_is_rejected_with_ministry_root():
    """FR-325: с контекстом адаптера MAX рукопожатие с `api.telegram.org` отвергнуто ошибкой проверки сертификата."""
    host = "api.telegram.org"
    ctx = _max_client().ssl_context()
    raw = _connect_or_skip(host)
    with raw:
        with pytest.raises(ssl.SSLCertVerificationError):
            ctx.wrap_socket(raw, server_hostname=host)
