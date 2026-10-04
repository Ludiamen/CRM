"""T-2109: адаптер ClamAV (FR-132, FR-151, NFR-105). Сценарии про фото сотрудника спеки 002."""
import logging
import socket
import struct

import pytest

from tests import support  # noqa: F401
from tests.support import model

SOCKET_TARGET = "apps.integrations.clamav.client.socket.create_connection"


class FakeSocket:
    """Поддельный сокет: записывает отправленное и отдаёт заданный ответ."""

    def __init__(self, reply: bytes = b""):
        self.sent = bytearray()
        self.reply = reply
        self.closed = False
        self.timeout = None

    def sendall(self, data, *args):
        self.sent += bytes(data)

    def send(self, data, *args):
        self.sent += bytes(data)
        return len(data)

    def recv(self, size=4096, *args):
        data, self.reply = self.reply[:size], self.reply[size:]
        return data

    def settimeout(self, value):
        self.timeout = value

    def shutdown(self, *args):
        pass

    def close(self):
        self.closed = True

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()
        return False


@pytest.fixture
def fake_net(monkeypatch):
    """Подменяет socket.create_connection; возвращает список вызовов и поддельных сокетов."""
    state = {"calls": [], "socks": [], "reply": b"", "raises": None}

    def create_connection(address, timeout=None, *args, **kwargs):
        state["calls"].append((address, timeout))
        if state["raises"] is not None:
            raise state["raises"]
        sock = FakeSocket(state["reply"])
        state["socks"].append(sock)
        return sock

    monkeypatch.setattr(SOCKET_TARGET, create_connection)
    return state


def parse_instream(sent: bytes):
    """Разбирает отправленное: (команда, список частей, остаток после нулевой части)."""
    assert sent.startswith(b"zINSTREAM\0")
    pos, chunks = len(b"zINSTREAM\0"), []
    while True:
        (length,) = struct.unpack(">I", sent[pos:pos + 4])
        pos += 4
        if length == 0:
            return chunks, sent[pos:]
        chunks.append(sent[pos:pos + length])
        pos += length


def test_instream_sends_64k_chunks_with_length_and_zero_terminator(fake_net, tmp_path):
    """NFR-105: INSTREAM — команда, части не более 64 КБ с длиной 4 байта big-endian, в конце нулевая часть."""
    from apps.integrations.clamav import client

    assert client.CHUNK_SIZE == 65536
    data = bytes(range(256)) * 600  # 153600 байт = 2 * 65536 + 22528
    path = tmp_path / "payload.bin"
    path.write_bytes(data)
    fake_net["reply"] = b"stream: OK\0"
    answer = client.instream(str(path), host="clamd.test", port=3999, timeout=7)
    assert answer == "stream: OK"
    assert fake_net["calls"] == [(("clamd.test", 3999), 7)]
    chunks, rest = parse_instream(bytes(fake_net["socks"][0].sent))
    assert all(0 < len(c) <= client.CHUNK_SIZE for c in chunks)
    assert b"".join(chunks) == data
    assert rest == b""
    # пустой файл: сразу нулевая часть
    empty = tmp_path / "empty.bin"
    empty.write_bytes(b"")
    fake_net["reply"] = b"stream: OK\0"
    client.instream(empty)
    assert fake_net["socks"][1].sent == b"zINSTREAM\0" + b"\0\0\0\0"


def test_ping(fake_net):
    """NFR-105: ping шлёт zPING\\0; ответ PONG — True; иной ответ — ScanUnavailable."""
    from apps.integrations.clamav import client

    fake_net["reply"] = b"PONG\0"
    assert client.ping(host="h", port=1, timeout=2) is True
    assert bytes(fake_net["socks"][0].sent) == b"zPING\0"
    fake_net["reply"] = b"WHAT\0"
    with pytest.raises(client.ScanUnavailable):
        client.ping(host="h", port=1, timeout=2)


def test_ok_is_clean_found_returns_signature(fake_net, tmp_path):
    """FR-132: «OK» — ScanResult(True, ""); «<сигнатура> FOUND» — ScanResult(False, сигнатура) без FOUND и stream:."""
    from apps.integrations.clamav import services

    path = tmp_path / "f.bin"
    path.write_bytes(b"content")
    fake_net["reply"] = b"stream: OK\0"
    result = services.scan(path)
    assert tuple(result) == (True, "")
    assert result.clean is True and result.signature == ""
    fake_net["reply"] = b"stream: Eicar-Signature FOUND\0"
    result = services.scan(str(path))
    assert tuple(result) == (False, "Eicar-Signature")
    assert result.clean is False and result.signature == "Eicar-Signature"


def test_connection_error_timeout_and_error_reply_raise_scan_unavailable(fake_net, tmp_path, monkeypatch):
    """NFR-105: отказ соединения, тайм-аут, ответ «… ERROR» и неожиданный ответ — ScanUnavailable."""
    from apps.integrations.clamav import services
    from apps.integrations.clamav.client import ScanUnavailable

    assert services.ScanUnavailable is ScanUnavailable
    path = tmp_path / "f.bin"
    path.write_bytes(b"content")
    for failure in (ConnectionRefusedError("refused"), socket.timeout("timed out"), OSError("down")):
        fake_net["raises"] = failure
        with pytest.raises(ScanUnavailable):
            services.scan(path)
    fake_net["raises"] = None
    for reply in (b"INSTREAM size limit exceeded. ERROR\0", b"stream: Can't open file ERROR\0", b"garbage\0"):
        fake_net["reply"] = reply
        with pytest.raises(ScanUnavailable):
            services.scan(path)
    # тайм-аут во время чтения ответа
    fake_net["reply"] = b"stream: OK\0"

    def slow_recv(self, *args):
        raise socket.timeout("timed out")

    monkeypatch.setattr(FakeSocket, "recv", slow_recv)
    with pytest.raises(ScanUnavailable):
        services.scan(path)


def test_host_port_timeout_from_environment_with_defaults(fake_net, settings, tmp_path):
    """NFR-105: незаданные аргументы берутся из settings.CLAMAV_* при каждом вызове; значения по умолчанию — clamav, 3310, 30."""
    from apps.integrations.clamav import client

    path = tmp_path / "f.bin"
    path.write_bytes(b"x")
    settings.CLAMAV_HOST, settings.CLAMAV_PORT, settings.CLAMAV_TIMEOUT = "clamd-one", 4001, 11
    fake_net["reply"] = b"PONG\0"
    client.ping()
    settings.CLAMAV_HOST, settings.CLAMAV_PORT, settings.CLAMAV_TIMEOUT = "clamd-two", 4002, 12
    fake_net["reply"] = b"stream: OK\0"
    client.instream(path)
    assert fake_net["calls"] == [(("clamd-one", 4001), 11), (("clamd-two", 4002), 12)]
    # значения по умолчанию — в подпроцессе с окружением без CLAMAV_* (настройки читают только окружение)
    import json
    import os
    import subprocess
    import sys
    from pathlib import Path

    backend = Path(__file__).resolve().parents[1]
    code = ("import json, config.settings as s; "
            "print(json.dumps([s.CLAMAV_HOST, s.CLAMAV_PORT, s.CLAMAV_TIMEOUT]))")

    def read(extra):
        env = {k: v for k, v in os.environ.items() if not k.startswith("CLAMAV_")}
        env.update(extra)
        out = subprocess.run([sys.executable, "-c", code], cwd=backend, env=env,
                             capture_output=True, text=True, timeout=60, check=True)
        return json.loads(out.stdout.strip().splitlines()[-1])

    assert read({}) == ["clamav", 3310, 30]  # json различает 3310 и "3310"
    assert read({"CLAMAV_HOST": "h9", "CLAMAV_PORT": "4999", "CLAMAV_TIMEOUT": "5"}) == ["h9", 4999, 5]


@pytest.mark.django_db
def test_adapter_logs_no_content_or_path(fake_net, tmp_path, caplog):
    """FR-151: ни содержимое файла, ни путь на диске не попадают ни в логи, ни в журнал событий."""
    from apps.integrations.clamav import services
    from apps.integrations.clamav.client import ScanUnavailable

    marker = "SECRET-MARKER-7f3a9c"
    folder = tmp_path / "unique-dir-8d21"
    folder.mkdir()
    path = folder / "unique-name-5b40.bin"
    path.write_bytes(marker.encode() + support_org_eicar())
    audit = model("core.AuditEvent")
    before = audit.objects.count()
    with caplog.at_level(logging.DEBUG):
        fake_net["reply"] = b"stream: Eicar-Signature FOUND\0"
        services.scan(path)
        fake_net["reply"] = b"stream: OK\0"
        services.scan(path)
        fake_net["reply"] = b"stream: Something ERROR\0"
        with pytest.raises(ScanUnavailable) as err:
            services.scan(path)
        fake_net["raises"] = ConnectionRefusedError("refused")
        with pytest.raises(ScanUnavailable) as refused:
            services.scan(path)
    text = caplog.text + "".join(r.getMessage() + repr(r.args) for r in caplog.records)
    for secret in (marker, str(path), "unique-dir-8d21", "unique-name-5b40"):
        assert secret not in text
        assert secret not in str(err.value)
        assert secret not in str(refused.value)
    assert audit.objects.count() == before


def support_org_eicar() -> bytes:
    from tests import support_org

    return support_org.eicar_bytes()
