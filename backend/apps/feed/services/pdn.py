"""Поиск открытых адресов почты и телефонов в тексте ленты."""

from apps.core.services.pdn_patterns import EMAIL, PHONE


def find_plain(*texts) -> list[str]:
    """Найти уникальные совпадения EMAIL/PHONE в порядке появления, максимум 20."""
    found = []
    seen = set()
    for text in texts:
        if not text:
            continue
        for pattern in (EMAIL, PHONE):
            for match in pattern.finditer(str(text)):
                value = match.group(0)
                if value not in seen:
                    seen.add(value)
                    found.append(value)
                    if len(found) == 20:
                        return found
    return found
