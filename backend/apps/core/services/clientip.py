"""Адрес клиента за прокси (решение Opus 2026-10-01, CONTRACT.md).

Цепочка: прокси администратора → nginx портала → Django. Если `REMOTE_ADDR` входит
в `TRUSTED_PROXIES` (адреса и сети CIDR), адрес клиента — последний недоверенный
адрес из `X-Forwarded-For`; иначе — `REMOTE_ADDR`. Заголовок от недоверенного
источника игнорируется. Список читается при запросе, а не при импорте.
"""
import ipaddress
from functools import lru_cache

from django.conf import settings


@lru_cache(maxsize=32)
def _networks(entries: tuple[str, ...]):
    networks = []
    for entry in entries:
        entry = entry.strip()
        if entry:
            networks.append(ipaddress.ip_network(entry, strict=False))
    return tuple(networks)


def _parse(value: str):
    try:
        return ipaddress.ip_address(value.strip())
    except ValueError:
        return None


def client_ip(meta) -> str:
    """Адрес клиента по `request.META`."""
    remote = (meta.get("REMOTE_ADDR") or "").strip()
    trusted = _networks(tuple(settings.TRUSTED_PROXIES))
    remote_ip = _parse(remote)
    if remote_ip is None or not any(remote_ip in net for net in trusted):
        return remote
    forwarded = meta.get("HTTP_X_FORWARDED_FOR", "")
    for item in reversed([part for part in forwarded.split(",") if part.strip()]):
        address = _parse(item)
        if address is None:
            return remote  # мусор в заголовке от доверенного прокси: ему не верим
        if not any(address in net for net in trusted):
            return str(address)
    return remote
