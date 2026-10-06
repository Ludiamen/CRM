"""T-3120: настоящий clamd службы `clamav` с `AlertEncryptedArchive` — архивы с паролем и без, вложенный архив, 20 МБ (FR-284). Сценарий 12 спеки."""
import time

from django.conf import settings

from tests import support_servicedesk

ENCRYPTED_PREFIX = "Heuristics.Encrypted."


def _scan(tmp_path, data: bytes, name: str = "attachment.bin"):
    """Кладёт байты в файл с нейтральным именем и проверяет его настоящим clamd через клиент среза 002."""
    from apps.integrations.clamav import client, services

    assert client.ping(host=settings.CLAMAV_HOST, port=settings.CLAMAV_PORT, timeout=settings.CLAMAV_TIMEOUT) is True
    path = tmp_path / name
    path.write_bytes(data)
    return services.scan(path)


def _assert_encrypted(result, kind: str | None = None):
    assert result.clean is False
    assert result.signature.startswith(ENCRYPTED_PREFIX), result.signature
    assert "FOUND" not in result.signature and not result.signature.startswith("stream:")
    if kind is not None:
        assert result.signature == ENCRYPTED_PREFIX + kind


def test_live_clamd_encrypted_zip_reports_heuristics_encrypted_zip(tmp_path):
    """FR-284: настоящий clamd со включённой AlertEncryptedArchive отвечает `Heuristics.Encrypted.Zip` на ZIP с паролем (ZipCrypto)."""
    result = _scan(tmp_path, support_servicedesk.sample("enc_zip_zipcrypto.zip"))
    _assert_encrypted(result, "Zip")


def test_live_clamd_plain_zip_is_clean(tmp_path):
    """FR-284: ZIP без пароля настоящий clamd пропускает (ответ OK, пустая сигнатура) — опция не даёт ложных срабатываний."""
    result = _scan(tmp_path, support_servicedesk.sample("plain.zip"))
    assert tuple(result) == (True, "")


def test_live_clamd_encrypted_7z_with_compressed_header_reports_heuristics_encrypted(tmp_path):
    """FR-284: 7z с паролем на данных и сжатым заголовком (своя проверка заголовков его не видит) clamd находит как `Heuristics.Encrypted.*`."""
    result = _scan(tmp_path, support_servicedesk.sample("enc_7z_compressed_header.7z"))
    _assert_encrypted(result)


def test_live_clamd_plain_7z_is_clean(tmp_path):
    """FR-284: 7z без пароля (простой заголовок) настоящий clamd пропускает."""
    result = _scan(tmp_path, support_servicedesk.sample("plain_7z_plain_header.7z"))
    assert tuple(result) == (True, "")


def test_live_clamd_nested_encrypted_zip_reports_heuristics_encrypted(tmp_path):
    """FR-284: обычный ZIP с вложенным `inner.zip` с паролем — своя проверка не видит, второй рубеж (clamd) даёт `Heuristics.Encrypted.Zip`."""
    result = _scan(tmp_path, support_servicedesk.sample("nested_enc_zip.zip"))
    _assert_encrypted(result, "Zip")


def test_live_clamd_scan_of_20mb_zip_faster_than_clamav_timeout(tmp_path):
    """FR-284: ZIP 20 МБ без сжатия проверяется настоящим clamd чисто и быстрее `settings.CLAMAV_TIMEOUT` (без ScanUnavailable)."""
    data = support_servicedesk.big_zip(20)
    assert len(data) >= 20 * 1024 * 1024
    started = time.monotonic()
    result = _scan(tmp_path, data, "big.bin")
    elapsed = time.monotonic() - started
    assert tuple(result) == (True, "")
    assert elapsed < settings.CLAMAV_TIMEOUT, f"проверка заняла {elapsed:.1f} с при CLAMAV_TIMEOUT={settings.CLAMAV_TIMEOUT}"
