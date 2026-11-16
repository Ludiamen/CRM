"""Обёртка над `apps.core.services.text` (срез 008, T-8004): шаблон упоминаний ленты `@[id]`.

Публичные имена и сигнатуры прежние: `render_plain(text, people, link_staff) -> SafeString` и
`snippet(text, limit, people=None) -> str`. Лента передаёт ядру свой шаблон маркера и обработчик;
ядро остаётся единственным местом `mark_safe` для пользовательского текста.
"""

import html
import re

from django.utils.safestring import SafeString

from apps.core.services import text as core_text

__all__ = ["render_plain", "snippet"]

_MARKER = re.compile(r"@\[([1-9]\d{0,8})\]")


def _mention_name(person_id: int, people: dict[int, str]) -> str | None:
    """ФИО для маркера, очищенное от управляющих и двунаправленных символов; нет имени — `None`."""
    name = people.get(person_id)
    if not name:
        return None
    return core_text.clean(str(name))


def _mention_html(match, link_staff: bool, people: dict[int, str]) -> str:
    """Готовый экранированный HTML маркера: ссылка на карточку, `span` или текст без известного имени."""
    token = match.group(0)
    person_id = int(match.group(1))
    name = _mention_name(person_id, people)
    if name is None:
        return html.escape(token, quote=True)
    safe_name = html.escape(name, quote=True)
    if link_staff:
        return f'<a href="/staff/{person_id}/" data-mention="{person_id}">{safe_name}</a>'
    return f'<span data-mention="{person_id}">{safe_name}</span>'


def render_plain(text: str, people: dict[int, str], link_staff: bool) -> SafeString:
    """Безопасно вывести простой текст ленты с экранированием и разрешёнными ссылками/упоминаниями."""

    def mention(match, link_staff: bool) -> str:
        return _mention_html(match, link_staff, people)

    return core_text.render_plain(text, [(_MARKER, mention)], link_staff=link_staff)


def snippet(text: str, limit: int, people: dict[int, str] | None = None) -> str:
    """Expand known mention names, collapse whitespace, and truncate on a word boundary."""
    known = people

    def expand(cleaned: str) -> str:
        nonlocal known
        if known is None:
            ids = list(dict.fromkeys(int(match.group(1)) for match in _MARKER.finditer(cleaned)))
            known = {}
            if ids:
                from apps.core.models import User, UserState

                known = dict(User.objects.filter(pk__in=ids, state=UserState.ACTIVE).values_list("pk", "full_name"))

        def replace(match):
            name = _mention_name(int(match.group(1)), known)
            return "@" + name if name is not None else match.group(0)

        return _MARKER.sub(replace, cleaned)

    return core_text.snippet(text, limit, expand=expand)
