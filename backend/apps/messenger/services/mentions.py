"""Маркеры упоминаний `@[u<id>]` и `@[c<id>]`, подсказка «@» (срез 008, T-8209/T-8210; CONTRACT-008, 5.2).

`extract(text)` — два набора номеров по маркерам; повтор не добавляет элемент, маркер вне формы
`@[u|c][1-9]\\d{0,8}` упоминанием не считается. `suggest(user, chat, q)` — до 20 строк: действующие участники
чата (ФИО и подразделение) и свои чаты (название); пустой или односимвольный запрос и личный диалог — пусто.
"""
import re

from django.apps import apps
from django.db.models import CharField, Value
from django.db.models.functions import Lower, Replace

from apps.core.models import User
from apps.messenger.models import Chat
from apps.messenger.services import members

PERSON = re.compile(r"@\[u([1-9]\d{0,8})\]")
CHAT = re.compile(r"@\[c([1-9]\d{0,8})\]")
MENTION_LIMIT = 20
SUGGEST_LIMIT = 20
MIN_QUERY = 2
HIDDEN_STATES = ("dismissed", "invited")


def extract(text: str) -> tuple[frozenset[int], frozenset[int]]:
    """Наборы номеров людей и чатов из маркеров текста (без обращения к базе)."""
    source = text or ""
    people = frozenset(int(match.group(1)) for match in PERSON.finditer(source))
    chats = frozenset(int(match.group(1)) for match in CHAT.finditer(source))
    return people, chats


def over_limit(people) -> bool:
    """Предел — 20 разных людей на сообщение; повторы предела не расходуют (FR-655)."""
    return len(people) > MENTION_LIMIT


def suggest(user, chat, q: str) -> list[dict]:
    """Подсказка «@»: участники текущего чата и свои чаты, до 20 строк (FR-655).

    В личном диалоге подсказка пуста; запрос короче двух знаков — пусто. Уволенные в участники не входят
    (`members.members` уже без них). Строки — словари `{"value": "u<id>"|"c<id>", "label": ..., "unit": ...}`.
    """
    query = (q or "").strip()
    if chat.kind == Chat.Kind.PERSONAL or len(query) < MIN_QUERY:
        return []

    fold = query.lower().replace("ё", "е")
    rows: list[dict] = []
    rows.extend(_people_rows(chat, fold))
    if len(rows) < SUGGEST_LIMIT:
        rows.extend(_chat_rows(user, chat, fold, SUGGEST_LIMIT - len(rows)))
    return rows[:SUGGEST_LIMIT]


def _folded(expression):
    return Replace(Lower(expression), Value("ё"), Value("е"), output_field=CharField())


def _people_rows(chat, fold: str) -> list[dict]:
    ids = members.members(chat)
    if not ids:
        return []
    found = (User.objects.filter(pk__in=ids)
             .exclude(state__in=HIDDEN_STATES)
             .annotate(_folded_name=_folded("full_name"))
             .filter(_folded_name__contains=fold)
             .order_by("_folded_name", "pk")[:SUGGEST_LIMIT])
    structure = None
    if apps.is_installed("apps.org"):
        from apps.org.services import structure as org_structure

        structure = org_structure
    rows = []
    for person in found:
        units = structure.units_of(person) if structure is not None else []
        rows.append({"value": f"u{person.pk}", "label": person.full_name,
                     "unit": ", ".join(unit.name for unit in units)})
    return rows


def _chat_rows(user, current, fold: str, limit: int) -> list[dict]:
    rows = []
    for chat in members.visible_chats(user).order_by("id")[:100]:
        title = _title(chat)
        if title and fold in title.lower().replace("ё", "е"):
            rows.append({"value": f"c{chat.pk}", "label": title, "unit": ""})
            if len(rows) >= limit:
                break
    return rows


def _title(chat) -> str:
    from apps.messenger.services import page

    return page.chat_title(chat, None)