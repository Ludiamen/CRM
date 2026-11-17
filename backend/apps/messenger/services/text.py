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


def _person_html(match, link_staff: bool, allowed=None) -> str:
    token = match.group(0)
    number = int(match.group(1))
    if allowed is not None and number not in allowed:
        return html.escape(token, quote=True)
    name = _name(number)
    if name is None:
        return html.escape(token, quote=True)
    safe_name = html.escape(name, quote=True)
    if link_staff:
        return f'<a href="/staff/{number}/" data-mention="{number}">{safe_name}</a>'
    return f'<span data-mention="{number}">{safe_name}</span>'


def _chat_html(match, link_staff: bool, viewer=None) -> str:
    token = match.group(0)
    number = int(match.group(1))
    if not _chat_visible(number, viewer):
        return html.escape(token, quote=True)
    title = _chat_title(number)
    if title is None:
        return html.escape(token, quote=True)
    safe_title = html.escape(title, quote=True)
    if link_staff:
        return f'<a href="/messenger/chats/{number}/" data-mention="c{number}">«{safe_title}»</a>'
    return f'<span data-mention="c{number}">«{safe_title}»</span>'


def _chat_visible(number: int, viewer) -> bool:
    """Упоминание чата раскрывается, если чат виден смотрящему; без смотрящего — любой существующий (общая обёртка)."""
    if viewer is None:
        return True
    from apps.messenger.services import members

    return members.visible_chats(viewer).filter(pk=number).exists()


def render_plain(text: str, *, link_staff: bool, chat=None, viewer=None):
    """Безопасный HTML: экранирование, ссылки, абзацы, упоминания людей и чатов.

    С `chat` раскрываются только участники этого чата (маркер постороннего остаётся текстом, FR-655); с
    `viewer` упоминание чата раскрывается, только если чат ему виден. Без `chat` (общая обёртка) раскрывается
    любой известный номер — так её проверяет `test_messenger_text.py`.
    """
    allowed_people = None
    if chat is not None:
        from apps.messenger.services import members

        allowed_people = members.members(chat)

    def person(match, link_staff: bool) -> str:
        return _person_html(match, link_staff, allowed_people)

    def chat_link(match, link_staff: bool) -> str:
        return _chat_html(match, link_staff, viewer)

    return core_text.render_plain(text, [(PERSON, person), (CHAT, chat_link)], link_staff=link_staff)


def snippet(text: str, limit: int, *, expand=None) -> str:
    """Отрывок без разметки; `expand(cleaned)` — преобразователь маркеров, получает уже очищенный текст."""
    return core_text.snippet(text, limit, expand=expand)