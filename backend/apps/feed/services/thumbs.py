"""Обёртка над `apps.core.services.thumbs` (срез 008, T-8004): эскизы ленты.

Публичные имена и поведение прежние: `MAX_SIDE` и `build(source_path, stored_id) -> str`;
построение эскиза живёт в ядре, чтобы модуль мессенджера не импортировал ленту.
"""

from apps.core.services.thumbs import MAX_SIDE, build

__all__ = ["MAX_SIDE", "build"]
