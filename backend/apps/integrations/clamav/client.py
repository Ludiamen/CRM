"""Клиент clamd: команды zPING и zINSTREAM, файл частями (PLAN-002, «Интеграции»).

Адрес и тайм-аут берутся из `settings.CLAMAV_*` при каждом вызове. Ни содержимое файла,
ни путь на диске в логи и тексты ошибок не попадают.
"""
import socket
import struct

from django.conf import settings

CHUNK_SIZE = 65536


class ScanUnavailable(Exception):
    """Проверка невозможна: сбой связи, тайм-аут, ответ «… ERROR» или неожиданный ответ."""


def _params(host, port, timeout):
    return (
        settings.CLAMAV_HOST if host is None else host,
        settings.CLAMAV_PORT if port is None else port,
        settings.CLAMAV_TIMEOUT if timeout is None else timeout,
    )


def _read_reply(sock) -> str:
    """Читает ответ до завершающего нулевого байта или закрытия соединения."""
    data = b""
    while b"\0" not in data:
        part = sock.recv(4096)
        if not part:
            break
        data += part
    return data.split(b"\0", 1)[0].decode("utf-8", "replace").strip()


def ping(*, host=None, port=None, timeout=None) -> bool:
    """Спрашивает clamd `zPING`; ответ PONG — True, иначе ScanUnavailable."""
    host, port, timeout = _params(host, port, timeout)
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(b"zPING\0")
            answer = _read_reply(sock)
    except OSError as exc:  # включает ConnectionError и socket.timeout
        raise ScanUnavailable(f"clamd недоступен ({type(exc).__name__})") from None
    if answer != "PONG":
        raise ScanUnavailable("неожиданный ответ clamd на PING")
    return True


def instream(path, *, host=None, port=None, timeout=None) -> str:
    """Отправляет файл командой `zINSTREAM` и возвращает ответ clamd без `\\0` и пробелов."""
    host, port, timeout = _params(host, port, timeout)
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(b"zINSTREAM\0")
            with open(path, "rb") as source:
                while True:
                    chunk = source.read(CHUNK_SIZE)
                    if not chunk:
                        break
                    sock.sendall(struct.pack(">I", len(chunk)) + chunk)
            sock.sendall(struct.pack(">I", 0))
            return _read_reply(sock)
    except OSError as exc:  # включает ConnectionError и socket.timeout
        raise ScanUnavailable(f"clamd недоступен ({type(exc).__name__})") from None
