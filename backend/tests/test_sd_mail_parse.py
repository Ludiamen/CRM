"""T-3108: разбор письма — текст, части, имена вложений, отправитель, очистка (FR-217, FR-218, FR-219,
FR-286, NFR-214). Сценарии 1 и 12 спеки.

Чистые функции `apps.servicedesk.services.mail_parse` (контракт § 6.14) работают над байтами письма,
базы не нужно. Письма — `support_servicedesk.build_mail` (CRLF); варианты, которых `build_mail` не
даёт (сырые 8-битные заголовки, вложенное письмо, имена вложений), собираются здесь из `email`
и из байтов.
"""
import base64
import email
import email.policy
from email.message import EmailMessage

from tests.support_servicedesk import MailPart, build_mail, sample

_CRLF = email.policy.default.clone(linesep="\r\n")


# --- помощники файла ------------------------------------------------------------------------------

def _mp():
    """Модуль разбора: имя кода среза 003 импортируется внутри теста (контракт, шапка)."""
    from apps.servicedesk.services import mail_parse
    return mail_parse


def _b64(text: str | bytes) -> str:
    data = text.encode("utf-8") if isinstance(text, str) else text
    return base64.b64encode(data).decode("ascii")


def _raw(headers: list[str], body: bytes = b"") -> bytes:
    """Письмо из строк заголовков и тела, переводы строк CRLF."""
    return "\r\n".join(headers).encode("utf-8") + b"\r\n\r\n" + body


def _mixed(attachments: list[tuple[list[str], bytes]], *, text: str = "Текст письма") -> bytes:
    """`multipart/mixed`: основной `text/plain` и вложения; у вложения свои строки заголовков части."""
    chunks = [b"--bnd\r\nContent-Type: text/plain; charset=utf-8\r\nContent-Transfer-Encoding: base64\r\n\r\n"
              + _b64(text).encode("ascii") + b"\r\n"]
    for lines, data in attachments:
        chunks.append(b"--bnd\r\n" + "\r\n".join(lines).encode("utf-8") + b"\r\n\r\n"
                      + _b64(data).encode("ascii") + b"\r\n")
    head = ["From: sender@client.test", "To: tickets@stand.test", "Subject: Вложения",
            "Message-ID: <att@client.test>", "MIME-Version: 1.0",
            'Content-Type: multipart/mixed; boundary="bnd"']
    return _raw(head, b"".join(chunks) + b"--bnd--\r\n")


def _attach_lines(disposition: str, content_type: str = "application/octet-stream") -> list[str]:
    return [f"Content-Type: {content_type}", "Content-Transfer-Encoding: base64", disposition]


def _names(parsed) -> list[str]:
    return [part.name for part in parsed.parts]


# --- текст (FR-218) -------------------------------------------------------------------------------

def test_plain_only_text_taken_as_is():
    """FR-218: письмо только с `text/plain` — текст берётся как есть: без завершающего перевода строки
    (его добавляет `set_content`), начало и середина — без изменений, вложений нет."""
    text = "Здравствуйте!\nНе работает принтер.\n\nКабинет 12."
    parsed = _mp().parse(build_mail(from_addr="user@client.test", subject="Принтер", text=text))
    assert parsed.text == text
    assert parsed.parts == []


def test_cc_addresses_collected_from_all_cc_headers():
    """FR-217: копии собираются из всех заголовков `Cc` (а не только из первого): адреса строчными, имена
    раскрыты (RFC 2047), повторы одного адреса склеены, адрес без `@` пропущен."""
    name = "Иван Петров"
    raw = _raw([
        "From: sender@client.test", "To: tickets@stand.test", "Subject: Копии",
        "Message-ID: <cc@client.test>",
        f"Cc: =?utf-8?B?{_b64(name)}?= <Ivan@Corp.Test>, localuser",
        "Cc: Petr <petr@corp.test>, " f"=?utf-8?B?{_b64(name)}?= <ivan@corp.test>",
        "Cc: Petr <PETR@corp.test>",
        "Content-Type: text/plain; charset=utf-8",
    ], b"text\r\n")
    cc = _mp().parse(raw).cc
    assert sorted(cc) == [("ivan@corp.test", name), ("petr@corp.test", "Petr")]
    assert all(isinstance(pair, tuple) for pair in cc)
    # та же функция над разобранным письмом даёт тот же список
    mail_parse = _mp()
    assert sorted(mail_parse.cc_pairs(mail_parse.load(raw))) == sorted(cc)


def test_html_only_converted_to_text_without_markup():
    """FR-218, NFR-214: письмо только с HTML — в тексте нет тегов, слова на месте, абзацы на разных строках."""
    html = "<html><body><p>Привет, <b>мир</b></p><div>Вторая строка</div></body></html>"
    parsed = _mp().parse(build_mail(from_addr="user@client.test", subject="HTML", text=None, html=html))
    assert "<" not in parsed.text and ">" not in parsed.text
    assert "Привет, мир" in parsed.text
    lines = parsed.text.splitlines()
    first = [line for line in lines if "Привет" in line]
    second = [line for line in lines if "Вторая" in line]
    assert first and second and first[0] != second[0]
    assert parsed.parts == []


def test_html_script_and_style_dropped_entities_expanded_line_breaks_kept():
    """FR-218, NFR-214: `script` и `style` пропущены вместе с содержимым, сущности раскрыты, переводы строк
    дают `br`, `p`, `div`, `li`, `tr`, теги не остаются."""
    html = ("<html><head><style>p { color: redred; }</style></head><body>"
            "<script>var scriptmark = 1;</script>"
            "<p>Абзац</p><div>Блок</div>Раз<br>Два"
            "<ul><li>Пункт1</li><li>Пункт2</li></ul>"
            "<table><tr><td>Строка1</td></tr><tr><td>Строка2</td></tr></table>"
            "<p>Том &amp; Джерри &lt;b&gt; &copy; &#1081;</p></body></html>")
    text = _mp().html_to_text(html)
    assert "redred" not in text and "scriptmark" not in text
    assert "Том & Джерри <b> © й" in text
    assert "</" not in text and "<p" not in text and "<li" not in text and "<td" not in text
    lines = text.splitlines()
    for first, second in [("Абзац", "Блок"), ("Раз", "Два"), ("Пункт1", "Пункт2"), ("Строка1", "Строка2")]:
        line_first = [i for i, line in enumerate(lines) if first in line]
        line_second = [i for i, line in enumerate(lines) if second in line]
        assert line_first and line_second and line_first[0] != line_second[0], (first, second, text)
    # то же через разбор целого письма
    parsed = _mp().parse(build_mail(from_addr="user@client.test", text=None, html=html))
    assert "scriptmark" not in parsed.text and "Том & Джерри" in parsed.text


def test_alternative_prefers_plain_part():
    """FR-218: в `multipart/alternative` берётся `text/plain`, а не HTML; HTML-пара не становится вложением."""
    parsed = _mp().parse(build_mail(from_addr="user@client.test", subject="Оба", text="Простой текст",
                                    html="<p>Разметка HTMLONLY</p>"))
    assert parsed.text == "Простой текст"
    assert "HTMLONLY" not in parsed.text
    assert parsed.parts == []


def test_windows_1251_body_decoded():
    """FR-218: тело в `windows-1251` декодируется по объявленной кодировке, без U+FFFD."""
    text = "Привет, не открывается почта."
    raw = build_mail(from_addr="user@client.test", subject="1251", text=text, charset="windows-1251")
    assert b"windows-1251" in raw.lower()
    parsed = _mp().parse(raw)
    assert parsed.text == text
    assert "�" not in parsed.text


def test_koi8_r_body_decoded():
    """FR-218: тело в `koi8-r` декодируется по объявленной кодировке, без U+FFFD."""
    text = "Привет, не открывается почта."
    raw = build_mail(from_addr="user@client.test", subject="koi8", text=text, charset="koi8-r")
    assert b"koi8-r" in raw.lower()
    parsed = _mp().parse(raw)
    assert parsed.text == text
    assert "�" not in parsed.text


def test_unknown_charset_and_replacement_char_use_fallback_path():
    """FR-218: неизвестная кодировка части (`LookupError`) и текст с U+FFFD идут запасным путём: байты части,
    `utf-8`, затем `cp1251`; `fallback_decode` берёт первую кодировку, которая подошла."""
    text = "Привет, мир"
    head = ["From: user@client.test", "To: tickets@stand.test", "Subject: Кодировка",
            "Message-ID: <cs@client.test>", "MIME-Version: 1.0"]
    cp1251 = text.encode("cp1251")
    # 1) неизвестная кодировка, 8-битные байты cp1251
    raw_unknown = _raw(head + ["Content-Type: text/plain; charset=x-no-such-charset-zz",
                               "Content-Transfer-Encoding: 8bit"], cp1251 + b"\r\n")
    assert _mp().parse(raw_unknown).text == text
    # 2) кодировка названа верно как utf-8, но байты — cp1251: при декодировании появляется U+FFFD
    raw_wrong = _raw(head + ["Content-Type: text/plain; charset=utf-8",
                             "Content-Transfer-Encoding: 8bit"], cp1251 + b"\r\n")
    parsed = _mp().parse(raw_wrong)
    assert parsed.text == text
    assert "�" not in parsed.text
    # 3) сама функция запасного пути: сначала utf-8
    message = email.message_from_bytes(raw_wrong, policy=email.policy.default)
    assert _mp().fallback_decode(message).rstrip() == text
    message_utf8 = email.message_from_bytes(
        _raw(head + ["Content-Type: text/plain; charset=x-no-such-charset-zz",
                     "Content-Transfer-Encoding: 8bit"], text.encode("utf-8") + b"\r\n"),
        policy=email.policy.default)
    assert _mp().fallback_decode(message_utf8).rstrip() == text


def test_mail_without_body_gives_empty_text():
    """FR-218: письмо без тела — пустой текст (не `None`, не ошибка); у письма только с вложением текст тоже пуст."""
    no_body = _mp().parse(build_mail(from_addr="user@client.test", subject="Без тела", text=None, html=None))
    assert no_body.text == ""
    assert no_body.parts == []
    only_file = _mp().parse(build_mail(
        from_addr="user@client.test", subject="Файл", text=None,
        attachments=[MailPart("note.txt", b"data", "text/plain")]))
    assert only_file.text == ""
    assert _names(only_file) == ["note.txt"]


# --- части письма (FR-286) ------------------------------------------------------------------------

def test_attachments_found_by_walk_including_inline_picture_in_nested_related():
    """FR-286: вложения ищутся обходом `walk()`: картинка внутри вложенного `multipart/related` найдена
    (в `iter_attachments()` её нет), выбранный текст и HTML-пара вложениями не считаются, порядок обхода."""
    png = sample("image.png")
    msg = EmailMessage()
    msg["From"] = "sender@client.test"
    msg["To"] = "tickets@stand.test"
    msg["Subject"] = "Связанные"
    msg["Message-ID"] = "<rel@client.test>"
    msg.set_content("Простая часть")
    msg.add_alternative('<p>Картинка <img src="cid:img1@client.test"></p>', subtype="html")
    msg.get_body(("html",)).add_related(png, "image", "png", cid="<img1@client.test>",
                                        disposition="inline", filename="pic.png")
    msg.add_attachment(b"%PDF-1.4 test", maintype="application", subtype="pdf", filename="report.pdf")
    raw = msg.as_bytes(policy=_CRLF)
    parsed = _mp().parse(raw)
    assert parsed.text == "Простая часть"
    assert _names(parsed) == ["pic.png", "report.pdf"]
    picture, report = parsed.parts
    assert picture.inline is True and picture.data == png and picture.content_type == "image/png"
    assert report.inline is False and report.data == b"%PDF-1.4 test"
    assert report.content_type == "application/pdf"


def test_inline_without_content_id_is_attachment():
    """FR-286: часть с `Content-Disposition: inline`, но без `Content-ID` — обычное вложение (`inline=False`)."""
    png = sample("image.png")
    msg = EmailMessage()
    msg["From"] = "sender@client.test"
    msg["Subject"] = "Без cid"
    msg["Message-ID"] = "<nocid@client.test>"
    msg.set_content("Текст")
    msg.add_attachment(png, maintype="image", subtype="png", filename="plain-inline.png", disposition="inline")
    parsed = _mp().parse(msg.as_bytes(policy=_CRLF))
    assert _names(parsed) == ["plain-inline.png"]
    assert parsed.parts[0].inline is False
    assert parsed.parts[0].data == png
    assert parsed.text == "Текст"


def test_inline_picture_with_content_id_marked_inline_attachment():
    """FR-286: картинка с `Content-ID` и `inline` — вложение с отметкой `inline=True`: имя, тип и байты на месте."""
    png = sample("image.png")
    raw = build_mail(from_addr="user@client.test", subject="Логотип", text="Текст",
                     html='<p>Логотип <img src="cid:logo@client.test"></p>',
                     attachments=[MailPart("logo.png", png, "image/png", "logo@client.test"),
                                  MailPart("doc.txt", b"doc", "text/plain")])
    parsed = _mp().parse(raw)
    assert parsed.text == "Текст"
    by_name = {part.name: part for part in parsed.parts}
    assert set(by_name) == {"logo.png", "doc.txt"}
    assert by_name["logo.png"].inline is True
    assert by_name["logo.png"].data == png and by_name["logo.png"].content_type == "image/png"
    assert by_name["doc.txt"].inline is False


def test_nested_mail_is_single_eml_attachment_children_not_entered():
    """FR-286: вложенное письмо (`message/rfc822`) — одна часть `.eml`; его текст, вложения и картинки
    в список не попадают; без имени — «вложение-N.eml»."""
    inner = EmailMessage()
    inner["From"] = "inner@client.test"
    inner["Subject"] = "Inner subject"
    inner.set_content("Внутренний текст")
    inner.add_attachment(b"inner-data", maintype="application", subtype="pdf", filename="inner.pdf")

    def outer(filename: str | None) -> bytes:
        msg = EmailMessage()
        msg["From"] = "sender@client.test"
        msg["Subject"] = "Пересылка"
        msg["Message-ID"] = "<fwd@client.test>"
        msg.set_content("Внешний текст")
        if filename:
            msg.add_attachment(inner, filename=filename)
        else:
            msg.add_attachment(inner)
        return msg.as_bytes(policy=_CRLF)

    named = _mp().parse(outer("forward.eml"))
    assert named.text == "Внешний текст"
    assert _names(named) == ["forward.eml"]
    assert named.parts[0].content_type == "message/rfc822"
    assert named.parts[0].inline is False
    assert b"Inner subject" in named.parts[0].data

    nameless = _mp().parse(outer(None))
    assert _names(nameless) == ["вложение-1.eml"]
    assert nameless.parts[0].content_type == "message/rfc822"
    assert b"Inner subject" in nameless.parts[0].data


def test_attachment_name_rfc2231_and_rfc2047_decoded():
    """FR-286: имя вложения раскрыто и из RFC 2231 (`filename*=utf-8''…`), и из RFC 2047 (`=?utf-8?B?…?=`)."""
    name_2231 = "Отчёт за июнь.pdf"
    encoded_2231 = "".join(f"%{b:02X}" for b in name_2231.encode("utf-8"))
    name_2047 = "Счёт №5.xlsx"
    raw = _mixed([
        (_attach_lines(f"Content-Disposition: attachment; filename*=utf-8''{encoded_2231}"), b"one"),
        (_attach_lines(f'Content-Disposition: attachment; filename="=?utf-8?B?{_b64(name_2047)}?="'), b"two"),
    ])
    parsed = _mp().parse(raw)
    assert _names(parsed) == [name_2231, name_2047]
    assert [part.data for part in parsed.parts] == [b"one", b"two"]
    # то же через `build_mail`: библиотека пишет имя с не-ASCII по RFC 2231
    built = _mp().parse(build_mail(from_addr="user@client.test", text="t",
                                   attachments=[MailPart(name_2231, b"three")]))
    assert _names(built) == [name_2231]


def test_attachment_name_path_and_control_chars_cleaned_cut_to_255():
    """FR-286: из имени берётся последняя часть пути (`/` и `\\`), управляющие знаки убраны, длина не больше 255."""
    def rfc2231(value: str) -> str:
        return "".join(f"%{b:02X}" for b in value.encode("utf-8"))

    long_name = "а" * 300 + ".txt"
    raw = _mixed([
        (_attach_lines(f"Content-Disposition: attachment; filename*=utf-8''{rfc2231('../../etc/passwd')}"), b"1"),
        (_attach_lines(f"Content-Disposition: attachment; filename*=utf-8''{rfc2231('C:' + chr(92) + 'Users' + chr(92) + 'x' + chr(92) + 'evil.exe')}"), b"2"),
        (_attach_lines(f"Content-Disposition: attachment; filename*=utf-8''{rfc2231('bad' + chr(1) + 'na' + chr(7) + 'me.txt')}"), b"3"),
        (_attach_lines(f"Content-Disposition: attachment; filename*=utf-8''{rfc2231(long_name)}"), b"4"),
    ])
    parsed = _mp().parse(raw)
    names = _names(parsed)
    assert names[0] == "passwd"
    assert names[1] == "evil.exe"
    assert names[2] == "badname.txt"
    assert 0 < len(names[3]) <= 255
    assert names[3].startswith("а" * 100)
    # сама функция: те же правила, номер вложения — только для пустого имени
    clean = _mp().clean_filename
    assert clean("a/b/c.txt", 1) == "c.txt"
    assert clean("a" + chr(92) + "b" + chr(92) + "c.txt", 1) == "c.txt"
    assert len(clean("б" * 400, 1)) <= 255


def test_nameless_attachment_gets_attachment_n_name():
    """FR-286: вложение без имени получает «вложение-N», где N — номер среди всех найденных вложений
    (именованные тоже считаются, счёт с 1); имя из одних управляющих знаков тоже пустое."""
    raw = _mixed([
        (_attach_lines('Content-Disposition: attachment; filename="named.txt"'), b"a"),
        (_attach_lines("Content-Disposition: attachment"), b"b"),
        (_attach_lines("Content-Disposition: attachment"), b"c"),
    ])
    parsed = _mp().parse(raw)
    assert _names(parsed) == ["named.txt", "вложение-2", "вложение-3"]
    assert [part.data for part in parsed.parts] == [b"a", b"b", b"c"]
    clean = _mp().clean_filename
    assert clean("", 1) == "вложение-1"
    assert clean("", 7) == "вложение-7"
    assert clean(chr(1) + chr(2), 4) == "вложение-4"


# --- отправитель, очистка (FR-219, NFR-214, FR-218) ----------------------------------------------

def test_requester_name_from_from_header_rfc2047():
    """FR-219: имя заявителя — из `From` (RFC 2047 раскрыт), адрес строчными; без домена адрес пуст, имя остаётся."""
    name = "Иван Петров"
    raw = build_mail(from_addr=f"{name} <Ivan.Petrov@Corp.Test>", subject="Имя", text="t")
    assert b"=?utf-8?" in raw.lower()
    parsed = _mp().parse(raw)
    assert parsed.sender == "ivan.petrov@corp.test"
    assert parsed.sender_name == name
    mail_parse = _mp()
    assert mail_parse.sender_of(mail_parse.load(raw)) == ("ivan.petrov@corp.test", name)
    # адрес без домена: адреса нет, имя осталось
    no_domain = _raw([f"From: =?utf-8?B?{_b64(name)}?= <ivan>", "Subject: x", "Message-ID: <nd@client.test>"], b"t\r\n")
    assert mail_parse.sender_of(mail_parse.load(no_domain)) == ("", name)
    assert mail_parse.parse(no_domain).sender == ""


def test_raw_8bit_name_surrogates_cleaned_before_saving():
    """FR-219: имя и тема, пришедшие сырыми 8-битными байтами, не содержат суррогатов и кодируются в UTF-8
    без ошибки (иначе запись в PostgreSQL падает): верный UTF-8 восстановлен, чужая кодировка — заменой."""
    head = b"To: tickets@stand.test\r\nMessage-ID: <raw8@client.test>\r\n"
    utf8 = b"From: " + "Иван".encode("utf-8") + b" <ivan@corp.test>\r\nSubject: x\r\n" + head + b"\r\nt\r\n"
    parsed = _mp().parse(utf8)
    assert parsed.sender == "ivan@corp.test"
    assert parsed.sender_name == "Иван"
    cp1251 = (b"From: " + "Иван".encode("cp1251") + b" <ivan@corp.test>\r\nSubject: "
              + "Тема".encode("cp1251") + b"\r\n" + head + b"\r\nt\r\n")
    parsed = _mp().parse(cp1251)
    assert parsed.sender == "ivan@corp.test"
    for value in (parsed.sender_name, parsed.subject):
        value.encode("utf-8")  # не поднимает UnicodeEncodeError
        assert not any("\ud800" <= ch <= "\udfff" for ch in value)
    # сама функция очистки
    assert _mp().clean_text("Иван".encode("cp1251").decode("utf-8", "surrogateescape")).encode("utf-8")
    assert _mp().clean_text("Иван".encode("utf-8").decode("utf-8", "surrogateescape")) == "Иван"


def test_nul_replaced_in_text_and_subject():
    """NFR-214: символ NUL в тексте и в теме заменён пробелом (не удалён и не U+FFFD): PostgreSQL его не принимает."""
    raw = _raw(["From: user@client.test", "To: tickets@stand.test", "Message-ID: <nul@client.test>",
                f"Subject: =?utf-8?B?{_b64(b'one' + bytes([0]) + b'two')}?=", "MIME-Version: 1.0",
                "Content-Type: text/plain; charset=utf-8", "Content-Transfer-Encoding: base64"],
               _b64(b"before" + bytes([0]) + b"after").encode("ascii") + b"\r\n")
    parsed = _mp().parse(raw)
    assert parsed.text == "before after"
    assert parsed.subject == "one two"
    assert "\x00" not in parsed.text and "\x00" not in parsed.subject
    assert _mp().clean_text("a" + chr(0) + "b") == "a b"


def test_subject_cleaned_of_line_breaks_and_control_chars():
    """FR-218: тема очищена: переводы строк, табуляции и управляющие знаки — пробелы, подряд идущие пробелы
    сжаты, края обрезаны, длина не больше 255 (та же функция даёт тему заявки)."""
    clean = _mp().clean_subject
    assert clean("  Тема" + chr(13) + chr(10) + chr(9) + "продолжение" + chr(7) + chr(31) + "знаки   конец  ") \
        == "Тема продолжение знаки конец"
    assert clean("Обычная тема") == "Обычная тема"
    assert clean(chr(10) + chr(10)) == ""
    assert len(clean("я" * 400)) == 255
    # свёрнутый заголовок из письма: перенос внутри темы не остаётся
    raw = _raw(["From: user@client.test", "Message-ID: <subj@client.test>",
                "Subject: Часть один", "\tчасть два", "Content-Type: text/plain; charset=utf-8"], b"t\r\n")
    parsed = _mp().parse(raw)
    assert parsed.subject == "Часть один часть два"
