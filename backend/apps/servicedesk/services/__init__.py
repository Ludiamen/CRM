"""Службы сервис-деска. Пакет отдаёт только ошибку и порцию; подмодули служб берут по имени."""
from .errors import Batch, ServiceDeskError

__all__ = ["Batch", "ServiceDeskError"]
