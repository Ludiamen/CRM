"""Поиск и скрытие персональных данных в тексте статьи (план 005, «Защита от ПДн», FR-428, FR-431).

Шаблоны — почта и телефон. `find` — предупреждение по статье в Markdown; `mask_plain` и `mask_resolution` — «Статья
из решения заявки». Ложные срабатывания допустимы: это только предупреждение.
"""
import re
from urllib.parse import unquote

from apps.knowledge.services import render

EMAIL = re.compile(r"(?<![\w.+-])[\w.+-]+@[\w-]+(?:\.[\w-]+)*\.[^\W\d_]{2,}(?![\w-])")
PHONE = re.compile(r"(?<![\d+])(?:\+7|8)[ \t\-()]*(?:\d[ \t\-()]*){9}\d(?!\d)")
HIDDEN = "[скрыто]"
LIMIT = 20

_FENCE = re.compile(r"^ {0,3}(`{3,}|~{3,})")
_SPAN = re.compile(r"(?<!`)(`+)(?!`)(.+?)(?<!`)\1(?!`)")


def _visible_text(title: str, text: str) -> str:
    """Склейка заголовка и видимого текста статьи; код пропущен, блоки и ячейки разделены переводом строки."""
    parts = [title, "\n"]
    for token in render.parse(text):
        if token.type == "inline":
            for child in token.children or ():
                if child.type == "text":
                    parts.append(child.content)
                elif child.type in ("softbreak", "hardbreak", "code_inline"):
                    parts.append("\n")
                elif child.type == "image":
                    parts.append(" ".join(c.content for c in child.children or () if c.type == "text"))
                elif child.type == "link_open":
                    href = child.attrGet("href") or ""
                    if href.lower().startswith("mailto:"):
                        parts.append("\n" + unquote(href[7:].split("?", 1)[0]) + "\n")
        else:
            parts.append("\n")
    return "".join(parts)


def find(title: str, text: str) -> list[str]:
    """Найденные в статье подстроки с почтой и телефонами: без повторов, по порядку первого вхождения, до 20."""
    joined = _visible_text(title, text)
    hits = sorted((m.start(), m.group(0)) for pattern in (EMAIL, PHONE) for m in pattern.finditer(joined))
    found: list[str] = []
    for _, value in hits:
        if value not in found:
            found.append(value)
        if len(found) == LIMIT:
            break
    return found


def _mask(text: str) -> str:
    return PHONE.sub(HIDDEN, EMAIL.sub(HIDDEN, text))


def mask_plain(text: str) -> str:
    """Тема заявки — простой текст: скрывает всё найденное."""
    return _mask(text.replace("\r\n", "\n"))


def _mask_line(line: str) -> str:
    """Скрывает найденное вне участков в обратных кавычках."""
    out, last = [], 0
    for span in _SPAN.finditer(line):
        out.append(_mask(line[last:span.start()]))
        out.append(span.group(0))
        last = span.end()
    out.append(_mask(line[last:]))
    return "".join(out)


def mask_resolution(text: str) -> str:
    """Решение заявки — будущий текст статьи: строки внутри ограждений и участки в обратных кавычках не меняются."""
    lines = []
    fence = None
    for line in text.replace("\r\n", "\n").split("\n"):
        found = _FENCE.match(line)
        if fence is not None:
            lines.append(line)
            if found and found.group(1)[0] == fence[0] and len(found.group(1)) >= len(fence) \
                    and not line.strip().strip(fence[0]):
                fence = None
        elif found:
            fence = found.group(1)
            lines.append(line)
        else:
            lines.append(_mask_line(line))
    return "\n".join(lines)
