"""T-2109: настоящий clamd тестовой службы (FR-132, NFR-105). Сценарии про фото сотрудника спеки 002."""
from django.conf import settings

from tests import support_org


def test_real_clamd_finds_eicar_and_passes_clean_file(tmp_path):
    """FR-132, NFR-105: настоящий clamd по settings.CLAMAV_HOST/PORT отвечает на ping, находит EICAR и пропускает чистый файл."""
    from apps.integrations.clamav import client, services

    assert client.ping(host=settings.CLAMAV_HOST, port=settings.CLAMAV_PORT, timeout=settings.CLAMAV_TIMEOUT) is True
    bad = tmp_path / "eicar.bin"
    bad.write_bytes(support_org.eicar_bytes())
    found = services.scan(bad)
    assert found.clean is False
    assert "Eicar" in found.signature
    assert "FOUND" not in found.signature and not found.signature.startswith("stream:")
    good = tmp_path / "clean.bin"
    good.write_bytes(b"ordinary harmless content\n" * 1000)
    ok = services.scan(good)
    assert tuple(ok) == (True, "")
