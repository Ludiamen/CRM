"""Маркеры упоминаний `@[u<id>]` и `@[c<id>]` (срез 008, T-8209/T-8210; CONTRACT-008, 5.2).

`extract(text)` — два набора номеров по маркерам; повтор не добавляет элемент, маркер вне формы
`@[u|c][1-9]\\d{0,8}` упоминанием не считается. Проверка участия и подсказка «@» — T-8210.
"""
import re

PERSON = re.compile(r"@\[u([1-9]\d{0,8})\]")
CHAT = re.compile(r"@\[c([1-9]\d{0,8})\]")
MENTION_LIMIT = 20


def extract(text: str) -> tuple[frozenset[int], frozenset[int]]:
    """Наборы номеров людей и чатов из маркеров текста (без обращения к базе)."""
    source = text or ""
    people = frozenset(int(match.group(1)) for match in PERSON.finditer(source))
    chats = frozenset(int(match.group(1)) for match in CHAT.finditer(source))
    return people, chats


def over_limit(people) -> bool:
    """Предел — 20 разных людей на сообщение; повторы предела не расходуют (FR-655)."""
    return len(people) > MENTION_LIMIT