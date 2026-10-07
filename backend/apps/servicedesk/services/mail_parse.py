"""Разбор письма: текст, части, отправитель, копии, признаки автоматического письма (чистые функции).

Модуль без моделей и без базы: работает над байтами письма и `email.message.EmailMessage`.
Весь разбор для службы `intake` берётся отсюда (план, раздел «Разбор», п. 2–8; контракт 6.14).
Исключение разбора идёт наружу: его ловит шаг `parse` службы `intake`.
"""
import email
import email.errors
import email.header
import email.message
import email.policy
import email.utils
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser

_SUBJECT_MAX = 255
_FILENAME_MAX = 255
_NUMBER_MAX = 2147483647
_ID_RE = re.compile(r"<[^<>\s]+>")
_NUMBER_RE = re.compile(r"\[#(\d+)\]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f-\x9f]")
_AUTOMATIC_PRECEDENCE = {"bulk", "junk", "list"}
_BLOCK_TAGS = {"br", "p", "div", "li", "tr"}
_SKIP_TAGS = {"script", "style"}


@dataclass(frozen=True)
class Part:
    """Вложение письма: имя (уже очищенное), байты, тип и отметка «встроенная картинка»."""

    name: str
    data: bytes
    content_type: str = "application/octet-stream"
    inline: bool = False


@dataclass(frozen=True)
class ParsedMail:
    """Результат разбора письма."""

    sender: str
    sender_name: str
    subject: str
    text: str
    parts: list = field(default_factory=list)
    cc: list = field(default_factory=list)
    message_id: str = ""
    link_ids: list = field(default_factory=list)
    subject_number: int | None = None
    automatic: bool = False


def load(raw):
    """Письмо из байтов; исключение разбора идёт наружу."""
    return email.message_from_bytes(raw, policy=email.policy.default)


def parse(raw):
    """Собирает `ParsedMail` из функций модуля."""
    message = load(raw)
    sender, sender_name = sender_of(message)
    subject = clean_subject(str(message.get("Subject", "") or ""))
    return ParsedMail(
        sender=sender,
        sender_name=sender_name,
        subject=subject,
        text=body_text(message),
        parts=attachment_parts(message),
        cc=cc_pairs(message),
        message_id=str(message.get("Message-ID", "") or ""),
        link_ids=link_ids(message),
        subject_number=subject_number(subject),
        automatic=is_automatic(message),
    )


def clean_text(value):
    """Убирает суррогаты (сырые 8-битные байты) и заменяет NUL пробелом."""
    value = value.encode("utf-8", "surrogateescape").decode("utf-8", "replace")
    return value.replace("\x00", " ")


def clean_subject(value):
    """Тема без переводов строк и управляющих знаков, пробелы сжаты, не длиннее 255 знаков."""
    value = _CONTROL_RE.sub(" ", clean_text(value))
    value = re.sub(r" {2,}", " ", value).strip()
    return value[:_SUBJECT_MAX].strip()


def _raw_names(message, header_name):
    """Имена из исходных (не разобранных политикой) заголовков: адрес строчными -> имя.

    Политика `default` склеивает смежные слова RFC 2047 пробелом и рвёт длинные имена («Серг еевич»);
    `make_header(decode_header(...))` склеивает их без пробела.
    """
    names = {}
    for key, raw in message.raw_items():
        if key.lower() != header_name.lower():
            continue
        try:
            pairs = email.utils.getaddresses([str(raw)])
        except (TypeError, ValueError, IndexError, email.errors.MessageError):  # останется имя политики
            continue
        for name, addr in pairs:
            if "=?" in name:
                try:
                    name = str(email.header.make_header(email.header.decode_header(name)))
                except (UnicodeError, LookupError, ValueError, email.errors.MessageError):  # имя возьмёт политика
                    continue
                names.setdefault(addr.lower(), name)
    return names


def _display_name(address, raw_names):
    """Имя адреса: из исходного заголовка, если оно закодировано RFC 2047, иначе из разбора политики."""
    policy_name = address.display_name or ""
    raw_name = raw_names.get((address.addr_spec or "").lower())
    if not raw_name:
        return policy_name
    if "\ufffd" in raw_name and "\ufffd" not in policy_name:
        return policy_name
    return raw_name


def sender_of(message):
    """Пара (адрес строчными, имя) первого адреса `From`; нет адреса или домена — адрес пуст."""
    header = message.get("From")
    addresses = getattr(header, "addresses", None) if header is not None else None
    if not addresses:
        return "", ""
    first = addresses[0]
    name = clean_text(_display_name(first, _raw_names(message, "From")))
    address = clean_text(first.addr_spec or "").lower()
    if "@" not in address or not address.rpartition("@")[2] or not address.rpartition("@")[0]:
        return "", name
    return address, name


def fallback_decode(part):
    """Запасной путь: байты части пробуются как utf-8, cp1251, koi8-r (последняя — с заменой ошибок)."""
    data = part.get_payload(decode=True) or b""
    for encoding in ("utf-8", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    return data.decode("koi8-r", errors="replace")


class _TextExtractor(HTMLParser):
    """Собирает текст HTML: `script` и `style` пропущены, блочные теги дают перевод строки."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.chunks = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in _SKIP_TAGS:
            self._skip += 1
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_startendtag(self, tag, attrs):
        if tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_endtag(self, tag):
        if tag in _SKIP_TAGS:
            self._skip = max(0, self._skip - 1)
        elif tag in _BLOCK_TAGS:
            self.chunks.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.chunks.append(data)


def html_to_text(html):
    """HTML в текст на `html.parser`."""
    html = html.replace("\r\n", "\n").replace("\r", "\n")
    extractor = _TextExtractor()
    extractor.feed(html)
    extractor.close()
    text = "".join(extractor.chunks)
    text = re.sub(r"[ \t]+\n", "\n", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip("\n")


def _newlines(text):
    return text.replace("\r\n", "\n").replace("\r", "\n")


def body_text(message):
    """Текст письма: текстовая часть, иначе HTML в текст; тела нет — пустая строка."""
    part = message.get_body(preferencelist=("plain", "html"))
    if part is None:
        return ""
    try:
        text = part.get_content()
        broken = "�" in text
    except LookupError:
        text, broken = "", True
    if broken:
        text = fallback_decode(part)
    if part.get_content_subtype() == "html":
        text = html_to_text(text)
    return _newlines(clean_text(text)).rstrip("\n")


def clean_filename(name, index):
    """Имя вложения: последняя часть пути, без управляющих знаков, до 255 знаков; пустое — «вложение-N»."""
    name = clean_text(name or "")
    name = re.split(r"[/\\]", name)[-1]
    name = _CONTROL_RE.sub("", name).strip()[:_FILENAME_MAX]
    return name or f"вложение-{index}"


def attachment_parts(message):
    """Вложения письма обходом `walk()`; вложенное письмо — одна часть `.eml`, внутрь обход не заходит."""
    body = message.get_body(preferencelist=("plain", "html"))
    html = message.get_body(preferencelist=("html",))
    skipped = set()
    result = []
    for part in message.walk():
        if id(part) in skipped or part is body or part is html:
            continue
        nested = part.get_content_type() == "message/rfc822"
        if nested:
            skipped.update(id(child) for child in part.walk() if child is not part)
        elif part.is_multipart():
            continue
        index = len(result) + 1
        raw_name = part.get_filename()
        if nested:
            name = clean_filename(raw_name, index) if raw_name else f"{clean_filename('', index)}.eml"
            data = part.as_bytes()
        else:
            name = clean_filename(raw_name, index)
            data = part.get_payload(decode=True) or b""
        disposition = (part.get_content_disposition() or "").lower()
        inline = bool(part.get("Content-ID")) and disposition == "inline"
        result.append(Part(name=name, data=data, content_type=part.get_content_type(), inline=inline))
    return result


def link_ids(message):
    """Идентификаторы писем из `In-Reply-To`, затем из `References` от последнего к первому, без повторов."""
    found = _ID_RE.findall(str(message.get("In-Reply-To", "") or ""))
    found += reversed(_ID_RE.findall(str(message.get("References", "") or "")))
    return list(dict.fromkeys(found))


def subject_number(subject):
    """Номер из первого `[#N]` темы; слишком большой — `None`."""
    match = _NUMBER_RE.search(subject)
    if not match:
        return None
    number = int(match.group(1))
    return number if number <= _NUMBER_MAX else None


def cc_pairs(message):
    """Пары (адрес строчными, имя) из всех заголовков `Cc`; повтор адреса — одна пара с первым непустым именем."""
    names = {}
    raw_names = _raw_names(message, "Cc")
    for header in message.get_all("Cc", []):
        for address in getattr(header, "addresses", ()):
            addr = clean_text(address.addr_spec or "").lower()
            if "@" not in addr:
                continue
            name = clean_text(_display_name(address, raw_names))
            if addr not in names or (not names[addr] and name):
                names[addr] = name
    return list(names.items())


def is_automatic(message):
    """Признаки автоматического письма: `Auto-Submitted`, `Precedence`, `Return-Path: <>`."""
    auto = str(message.get("Auto-Submitted", "") or "").split(";")[0].strip().lower()
    if auto and auto != "no":
        return True
    if str(message.get("Precedence", "") or "").strip().lower() in _AUTOMATIC_PRECEDENCE:
        return True
    return str(message.get("Return-Path", "") or "").strip() == "<>"
