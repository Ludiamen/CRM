"""Проверка файла антивирусом: scan(path), ScanUnavailable (PLAN-002, «Интеграции»)."""
import logging
from typing import NamedTuple

from apps.integrations.clamav import client
from apps.integrations.clamav.client import ScanUnavailable  # noqa: F401

logger = logging.getLogger(__name__)


class ScanResult(NamedTuple):
    clean: bool
    signature: str


def scan(path) -> ScanResult:
    """Проверяет файл: ScanResult(True, "") или ScanResult(False, "<сигнатура>").

    При сбое связи, тайм-ауте, ответе «… ERROR» и неожиданном ответе — ScanUnavailable.
    В логи попадает только имя сигнатуры.
    """
    answer = client.instream(path)
    if answer.endswith(" ERROR"):
        raise ScanUnavailable("clamd ответил ошибкой")
    if answer.endswith(" FOUND"):
        signature = answer[: -len(" FOUND")]
        if signature.startswith("stream:"):
            signature = signature[len("stream:"):]
        signature = signature.strip()
        logger.info("clamav: найдена сигнатура %s", signature)
        return ScanResult(False, signature)
    if answer == "stream: OK":
        return ScanResult(True, "")
    raise ScanUnavailable("неожиданный ответ clamd")
