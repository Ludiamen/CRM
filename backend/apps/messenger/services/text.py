"""Вывод текста мессенджера: шаблоны `@[u<id>]` и `@[c<id>]` (срез 008, T-8209; CONTRACT-008, 5.2).

Обёртка над `apps.core.services.text` по образцу ленты: ядро — единственное место `mark_safe`, а мессенджер
передаёт два своих шаблона. Маркер человека `@[u<id>]` выводится ФИО со ссылкой на карточку (`data-mention="<id>"`),
маркер чата `@[c<id>]` — названием со ссылкой на беседу (`data-mention="c<id>"`). Известность маркера проверяется
по базе; неизвестный номер и неверная форма остаются текстом. `snippet` — отрывок без разметки, `expand`
превращает маркеры в имена до обрезки.
"""
import html
import re

from apps.core.services import text as core_text

__all__ = ["render_plain", "snippet"]

PERSON = re.compile(r"@\[u([1-9]\d{0,8})\]")
CHAT = re.compile(r"@\[c([1-9]\d{0,8})\]")


def _name(marker_number: int) -> str | None:
    """ФИО действующего сотрудника для маркера; нет строки — `None` (маркер останется текстом)."""
    from apps.core.models import User, UserState

    name = (User.objects.filter(pk=marker_number, state=UserState.ACTIVE)
            .values_list("full_name", flat=True).first())
    return core_text.clean(str(name)) if name else None


def _chat_title(chat_id: int) -> str | None:
    """Название чата для маркера; нет строки — `None`."""
    from apps.messenger.models import Chat
    from apps.messenger.services import page

    chat = Chat.objects.filter(pk=chat_id).first()
    if chat is None:
        return None
    return core_text.clean(str(page.chat_title(chat)))


def _person_html(match, link_staff: bool) -> str:
    token = match.group(0)
    number = int(match.group(1))
    name = _name(number)
    if name is None:
        return html.escape(token, quote=True)
    safe_name = html.escape(name, quote=True)
    if link_staff:
        return f'<a href="/staff/{number}/" data-mention="{number}">{safe_name}</a>'
    return f'<span data-mention="{number}">{safe_name}</span>'


def _chat_html(match, link_staff: bool) -> str:
    token = match.group(0)
    number = int(match.group(1))
    title = _chat_title(number)
    if title is None:
        return html.escape(token, quote=True)
    safe_title = html.escape(title, quote=True)
    if link_staff:
        return f'<a href="/messenger/chats/{number}/" data-mention="c{number}">«{safe_title}»</a>'
    return f'<span data-mention="c{number}">«{safe_title}»</span>'


def render_plain(text: str, *, link_staff: bool):
    """Безопасный HTML: экранирование, ссылки `http`/`https`/`mailto`, абзацы, упоминания людей и чатов."""
    return core_text.render_plain(text, [(PERSON, _person_html), (CHAT, _chat_html)], link_staff=link_staff)


def snippet(text: str, limit: int, *, expand=None) -> str:
    """Отрывок без разметки; `expand(cleaned)` — преобразователь маркеров, получает уже очищенный текст."""
    return core_text.snippet(text, limit, expand=expand)