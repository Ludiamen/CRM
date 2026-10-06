"""T-3119: вложения заявок (FR-212, FR-283…FR-287, NFR-206, NFR-213). Сценарий 12 спеки.

Приём (размеры, исполняемые файлы, архивы с паролем, число и сумма), хранение до проверки, итог проверки
антивирусом (чисто, карантин, архив с паролем, ClamAV недоступен), выдача файла и исходного письма. Антивирус
подменяется только помощниками `scan_clean`/`scan_found`/`scan_unavailable`; файловый том — настоящий
(`protected_root`). Код среза на уровне модуля не импортируется: имена берутся внутри тестов (CONTRACT-003, шапка).
"""
import hashlib
import importlib
import json
import zipfile
from html.parser import HTMLParser
from io import BytesIO
from urllib.parse import unquote

import pytest
from django.utils import timezone

from tests import factories, support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

SCAN = "apps.core.tasks.scan_file"
MB = 1024 * 1024
TITLES = {"too_big": "больше 20 МБ", "mail_too_big": "письмо больше 50 МБ", "executable": "исполняемый файл",
          "encrypted": "архив с паролем"}


# --- помощники файла ------------------------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.servicedesk.services.{name}")


def _att():
    return _svc("attachments")


def _errors():
    return importlib.import_module("apps.servicedesk.services").ServiceDeskError


def _part(name: str = "справка.txt", data: bytes = b"clean data", *, inline: bool = False,
          content_type: str = "text/plain"):
    return _att().Part(name=name, data=data, content_type=content_type, inline=inline)


def _refuse(code: str, call):
    with pytest.raises(_errors()) as caught:
        call()
    assert caught.value.code == code, f"ждали {code}, получили {caught.value.code}: {caught.value}"
    return caught.value


def _staff():
    """Сотрудник с правом «Все заявки»: видит любую заявку."""
    return support.make_with_permissions("servicedesk.all")


def _mail_ticket(capture, parts=(), *, strict=False, mail_size=None):
    """Заявка из письма (`tickets.create`, канал `mail`) и приём вложений первого элемента, как делает `intake`."""
    tickets = _svc("tickets")
    queue = sd.make_queue()
    category = sd.make_category(queue=queue)
    with capture(execute=True):
        created = tickets.create(channel=tickets.MAIL, subject="Вложения", text="Письмо с файлами",
                                 requester_email=factories.new_email("req").lower(), category=category,
                                 inbound_id=sd.make_inbound().pk)
        accepted = _att().accept(created.entry, list(parts), strict=strict, mail_size=mail_size)
    return created, accepted


def _entry_ticket(parts=(), *, strict=False, capture=None, mail_size=None):
    """Заявка и элемент `incoming` через ORM (без `tickets.create`); вложения — через `accept`."""
    ticket = sd.make_ticket(queue=sd.make_queue())
    entry = sd.make_entry(ticket, "incoming")
    with capture(execute=True):
        accepted = _att().accept(entry, list(parts), strict=strict, mail_size=mail_size)
    return ticket, entry, accepted


def _fresh(obj):
    obj.refresh_from_db()
    return obj


def _scan(stored, capture):
    """Исполняет проверку файла диспетчером ядра внутри фиксации (стирание файлов — после неё)."""
    from apps.core import tasks

    with capture(execute=True):
        tasks.scan_file(str(stored.pk))


def _journal(action: str, ticket) -> list:
    return list(model("core.AuditEvent").objects.filter(
        action=action, object_type="ticket", object_id=str(ticket.number)).order_by("id"))


def _feed_events(ticket, code: str) -> list:
    return list(ticket.entries.filter(kind="event", event=code).order_by("id"))


def _scan_jobs(stored) -> list:
    return [job for job in org.files_jobs() if job.func_name == SCAN and tuple(job.args) == (str(stored.pk),)]


def _put_eml(inbound, protected_root) -> None:
    path = protected_root / "inbound" / f"{inbound.pk}.eml"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"From: a@client.test\r\n\r\nraw")


# --- разбор разметки (помощник только этого файла) ------------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.parent, self.children = tag, parent, []
        self.attrs = {k: (v if v is not None else "") for k, v in attrs}

    def walk(self):
        for child in self.children:
            if isinstance(child, Node):
                yield child
                yield from child.walk()

    def text(self) -> str:
        parts = []

        def collect(node):
            for child in node.children:
                collect(child) if isinstance(child, Node) else parts.append(child)

        collect(self)
        return " ".join("".join(parts).split())


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in _VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not self.root:
            if node.tag == tag:
                self.cur = node.parent
                return
            node = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def _tree(response) -> Node:
    parser = _Tree()
    parser.feed(response.content.decode("utf-8"))
    return parser.root


def _find(scope, tag=None, **attrs) -> list:
    wanted = {k.rstrip("_").replace("_", "-"): v for k, v in attrs.items()}
    result = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            result.append(node)
    return result


def _card(user, ticket):
    response = support.logged_in(user).get(f"/tickets/{ticket.number}/")
    assert response.status_code == 200
    (card,) = _find(_tree(response), data_ticket_card=True)
    return card


def _attachment_nodes(card) -> list:
    """Вложения заявки — только внутри `[data-section="attachments"]` (контракт 13.3)."""
    (section,) = _find(card, data_section="attachments")
    return _find(section, data_attachment=True)


# --- 1. размеры -----------------------------------------------------------------------------------------

def test_letter_over_50mb_rejects_all_attachments_but_ticket_created(
        django_capture_on_commit_callbacks, protected_root):
    """FR-285, FR-284, NFR-206: письмо больше 50 МБ — все вложения `mail_too_big` (имя, размер, причина), заявка создана."""
    att = _att()
    parts = [_part("первый.txt", b"one"), _part("второй.txt", b"two!!")]
    created, accepted = _mail_ticket(django_capture_on_commit_callbacks, parts, mail_size=att.MAX_MAIL + 1)
    assert model("servicedesk.Ticket").objects.filter(pk=created.ticket.pk).exists()
    assert [a.name for a in accepted] == ["первый.txt", "второй.txt"]
    assert [a.size for a in accepted] == [3, 5]
    assert {a.rejected for a in accepted} == {"mail_too_big"}
    assert all(a.file_id is None for a in accepted)
    assert model("core.StoredFile").objects.filter(purpose="attachment").count() == 0
    assert not (protected_root / "incoming").exists() or not list((protected_root / "incoming").iterdir())
    assert org.files_jobs() == [], "на не принятые файлы проверка не ставится"
    stored_rows = list(created.entry.attachments.order_by("id"))
    assert [a.rejected for a in stored_rows] == ["mail_too_big", "mail_too_big"]
    assert [(a.name, a.size, a.rejected) for a in stored_rows] == [
        ("первый.txt", 3, "mail_too_big"), ("второй.txt", 5, "mail_too_big")], "имя, размер, причина — в базе"
    # граница: ровно 50 МБ — письмо ещё принимается
    created2, accepted2 = _mail_ticket(django_capture_on_commit_callbacks, [_part("граница.txt", b"x")],
                                       mail_size=att.MAX_MAIL)
    assert accepted2[0].rejected == "" and accepted2[0].file_id is not None
    assert model("servicedesk.Ticket").objects.filter(pk=created2.ticket.pk).exists()


def test_attachment_over_20mb_rejected_with_reason(django_capture_on_commit_callbacks, protected_root):
    """FR-284: файл больше 20 МБ — `too_big`, остальные файлы письма принимаются; ровно 20 МБ принимается."""
    att = _att()
    big = b"\0" * (att.MAX_FILE + 1)
    edge = b"\1" * att.MAX_FILE
    ticket, entry, accepted = _entry_ticket([_part("большой.dat", big), _part("граница.dat", edge),
                                             _part("малый.txt", b"small")],
                                            capture=django_capture_on_commit_callbacks)
    assert [a.rejected for a in accepted] == ["too_big", "", ""]
    assert accepted[0].size == len(big) and accepted[0].file_id is None
    assert accepted[1].file_id is not None and accepted[2].file_id is not None
    assert model("core.StoredFile").objects.filter(purpose="attachment").count() == 2
    Attachment = model("servicedesk.Attachment")
    assert [(a.name, a.size, a.rejected) for a in Attachment.objects.filter(entry=entry).order_by("id")] == [
        ("большой.dat", len(big), "too_big"), ("граница.dat", len(edge), ""), ("малый.txt", 5, "")], "из базы"
    assert Attachment.REJECT_TITLES["too_big"] == TITLES["too_big"]
    # форма, ответ, заявка от исполнителя (`strict=True`): отказ с названием файла и причиной, ничего не записано
    error = _refuse("file_rejected", lambda: att.precheck([_part("большой.dat", big)]))
    assert "большой.dat" in str(error) and TITLES["too_big"] in str(error)


# --- 2. исполняемые файлы -------------------------------------------------------------------------------

def test_executable_signatures_and_type_by_content_rejected():
    """FR-284, NFR-213: PE, ELF, Mach-O (64 и 32 бита), скрипт `#!` — исполняемые по содержимому при любом имени."""
    att = _att()
    for name in ("exe_pe.bin", "exe_elf.bin", "exe_macho64_le.bin", "exe_macho32_be.bin", "exe_script.bin"):
        data = sd.sample(name)
        for file_name in ("отчёт.txt", "картинка.png", "noext"):
            assert att.is_executable(file_name, data) is True, (name, file_name)
            assert att.reason_of(file_name, data) == "executable", (name, file_name)
    assert att.reason_of("отчёт.txt", b"just plain text") == ""
    assert att.is_executable("отчёт.txt", sd.sample("image.png")) is False


def test_signature_edge_cases_mz_without_pe_cafebabe_ole_doc_and_jar():
    """FR-284, NFR-213: `MZ` без `PE`, текст «MZ», класс Java, OLE `.doc` и ZIP документа ODF — не исполняемые; fat Mach-O, MSI и JAR — исполняемые."""
    att = _att()
    for name in ("not_exe_dos_mz.bin", "not_exe_mz_text.txt", "not_exe_java_class.bin", "not_exe_ole_doc.bin",
                 "not_exe_odf_manifest.zip"):
        assert att.is_executable("файл.dat", sd.sample(name)) is False, name
        assert att.reason_of("файл.dat", sd.sample(name)) == "", name
    for name in ("exe_macho_fat.bin", "exe_msi.bin", "exe_jar.zip"):
        assert att.is_executable("файл.dat", sd.sample(name)) is True, name
        assert att.reason_of("файл.dat", sd.sample(name)) == "executable", name


def test_every_executable_extension_rejected_by_last_extension_case_insensitive():
    """FR-284: каждое из 21 расширений ловится по последнему расширению без учёта регистра (`счёт.pdf.exe`); `exe.pdf` не ловится."""
    att = _att()
    expected = ("exe", "com", "scr", "pif", "bat", "cmd", "msi", "msp", "vbs", "vbe", "js", "jse", "wsf", "wsh",
                "ps1", "hta", "cpl", "jar", "lnk", "reg", "sh")
    assert set(att.EXECUTABLE_EXTENSIONS) == set(expected) and len(att.EXECUTABLE_EXTENSIONS) == 21
    for ext in expected:
        for name in (f"файл.{ext}", f"ФАЙЛ.{ext.upper()}", f"счёт.pdf.{ext}", f"Mixed.{ext.capitalize()}"):
            assert att.is_executable(name, b"plain text") is True, name
            assert att.reason_of(name, b"plain text") == "executable", name
        assert att.is_executable(f"{ext}.pdf", b"plain text") is False, f"{ext}.pdf"
        assert att.reason_of(f"{ext}.txt", b"plain text") == ""


def test_docm_and_xlsm_not_executable():
    """FR-284: `docm` и `xlsm` не исполняемые (их проверяет ClamAV): ни по имени, ни по содержимому, в любом регистре."""
    att = _att()
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("word/document.xml", "<doc/>")
    data = buffer.getvalue()
    assert "docm" not in att.EXECUTABLE_EXTENSIONS and "xlsm" not in att.EXECUTABLE_EXTENSIONS
    for name in ("макрос.docm", "макрос.DOCM", "таблица.xlsm", "Таблица.XlSm"):
        assert att.is_executable(name, data) is False, name
        assert att.reason_of(name, data) == "", name


# --- 3. архивы с паролем --------------------------------------------------------------------------------

def test_password_protected_zip_flag_bit_and_aes_rejected():
    """FR-284: ZIP с паролем (ZipCrypto, WinZip AES, шифрование у второго элемента) — «архив с паролем»; ZIP без пароля — нет."""
    att = _att()
    for name in ("enc_zip_zipcrypto.zip", "enc_zip_aes.zip", "enc_zip_second_entry.zip"):
        data = sd.sample(name)
        assert att.is_encrypted_archive(data) is True, name
        assert att.reason_of("архив.dat", data) == "encrypted", name
    assert att.is_encrypted_archive(sd.sample("plain.zip")) is False
    assert att.reason_of("архив.dat", sd.sample("plain.zip")) == ""


def test_password_protected_rar4_rar5_and_7z_rejected():
    """FR-284: RAR4, RAR5 (данные и заголовки) и 7z с AES в простом или зашифрованном заголовке — «архив с паролем»."""
    att = _att()
    for name in ("enc_rar5_data.rar", "enc_rar5_headers.rar", "enc_rar4_data.rar", "enc_rar4_headers.rar",
                 "enc_7z_plain_header.7z", "enc_7z_encrypted_header.7z"):
        data = sd.sample(name)
        assert att.is_encrypted_archive(data) is True, name
        assert att.reason_of("архив.dat", data) == "encrypted", name


def test_archives_without_password_accepted(django_capture_on_commit_callbacks, protected_root):
    """FR-284: архивы без пароля (ZIP, RAR4, RAR5, 7z с простым и со сжатым заголовком) принимаются; вложенный ZIP с паролем своя проверка не видит."""
    att = _att()
    names = ("plain.zip", "plain_rar4.rar", "plain_rar5.rar", "plain_7z_plain_header.7z",
             "plain_7z_compressed_header.7z", "nested_enc_zip.zip")
    for name in names:
        assert att.is_encrypted_archive(sd.sample(name)) is False, name
        assert att.reason_of("архив.dat", sd.sample(name)) == "", name
    ticket, entry, accepted = _entry_ticket([_part(f"a{i}.bin", sd.sample(n)) for i, n in enumerate(names)],
                                            capture=django_capture_on_commit_callbacks)
    assert [a.rejected for a in accepted] == [""] * len(names)
    assert all(a.file_id is not None and _fresh(a.file).status == "pending" for a in accepted)


# --- 4. форма и ответ -----------------------------------------------------------------------------------

def test_form_over_10_files_or_over_50mb_total_refused(django_capture_on_commit_callbacks, protected_root):
    """FR-284: больше 10 файлов или сумма больше 50 МБ — отказ целиком (`too_many_files`, `total_too_big`), ничего не записано."""
    att = _att()
    ten = [_part(f"f{i}.txt", b"x") for i in range(10)]
    assert att.precheck(ten) is None, "ровно 10 файлов допустимо"
    eleven = ten + [_part("f10.txt", b"x")]
    _refuse("too_many_files", lambda: att.precheck(eleven))
    five = [_part(f"p{i}.dat", b"\0" * (10 * MB)) for i in range(5)]
    assert att.precheck(five) is None, "ровно 50 МБ допустимо"
    over = five + [_part("лишний.dat", b"\0")]
    _refuse("total_too_big", lambda: att.precheck(over))
    # число проверяется раньше суммы
    many_big = [_part(f"m{i}.dat", b"\0" * (5 * MB)) for i in range(11)]
    _refuse("too_many_files", lambda: att.precheck(many_big))
    # единая функция приёма при `strict=True`: тот же отказ, в базе и на диске ничего
    ticket = sd.make_ticket(queue=sd.make_queue())
    entry = sd.make_entry(ticket, "reply")
    with django_capture_on_commit_callbacks(execute=True):
        _refuse("too_many_files", lambda: att.accept(entry, eleven, strict=True))
        _refuse("total_too_big", lambda: att.accept(entry, over, strict=True))
    assert model("servicedesk.Attachment").objects.count() == 0
    assert model("core.StoredFile").objects.filter(purpose="attachment").count() == 0
    assert org.files_jobs() == []


def test_form_and_reply_with_rejected_file_refused_entirely_with_message(
        django_capture_on_commit_callbacks, protected_root):
    """FR-284, FR-285: форма и ответ исполнителя с не принятым файлом отказывают целиком: «файл «…» не принят: <причина>», ничего не создано."""
    att = _att()
    good = _part("хороший.txt", b"good")
    bad = _part("вирус.exe", b"MZ not really")
    error = _refuse("file_rejected", lambda: att.precheck([good, bad]))
    assert str(error) == "файл «вирус.exe» не принят: исполняемый файл"
    encrypted = _part("секрет.dat", sd.sample("enc_zip_zipcrypto.zip"))
    error = _refuse("file_rejected", lambda: att.precheck([good, encrypted]))
    assert str(error) == "файл «секрет.dat» не принят: архив с паролем"
    # форма: заявка не создаётся
    form = _svc("form")
    queue = sd.make_queue()
    category = sd.make_category(queue=queue, on_form=True)
    sd.configure_servicedesk(domains=["example.test"], default_queue=queue)
    tickets_before = model("servicedesk.Ticket").objects.count()
    with django_capture_on_commit_callbacks(execute=True):
        _refuse("file_rejected", lambda: form.submit(
            email="client@example.test", name="Клиент", client_unit_id=None, category_id=category.pk,
            subject="Тема", text="Текст", consent=True, parts=[good, bad], ip="203.0.113.5"))
    assert model("servicedesk.Ticket").objects.count() == tickets_before
    # ответ исполнителя: элемента ответа нет, файлов нет
    actor = _staff()
    ticket = sd.make_ticket(queue=sd.make_queue(), kind="in_progress")
    entries_before = ticket.entries.count()
    with django_capture_on_commit_callbacks(execute=True):
        _refuse("file_rejected", lambda: _svc("replies").reply(
            ticket, text="Ответ", wait_flag=False, parts=[good, bad], actor=actor))
    assert ticket.entries.count() == entries_before
    assert model("servicedesk.Attachment").objects.count() == 0
    assert model("core.StoredFile").objects.filter(purpose="attachment").count() == 0
    # маршрут ответа: страница с сообщением, ответ не создан
    from django.core.files.uploadedfile import SimpleUploadedFile

    response = support.logged_in(actor).post(
        f"/tickets/{ticket.number}/reply/",
        {"text": "Ответ по маршруту", "files": [SimpleUploadedFile("хороший.txt", b"good"),
                                                SimpleUploadedFile("вирус.exe", b"MZ not really")]})
    assert response.status_code == 200
    alerts = _find(_tree(response), role="alert")
    assert alerts and any("файл «вирус.exe» не принят: исполняемый файл" in node.text() for node in alerts)
    assert ticket.entries.count() == entries_before


# --- 5. не принятые вложения в карточке и подтверждении -------------------------------------------------

def test_rejected_attachment_keeps_only_name_size_reason_and_is_listed_in_card_and_confirmation(
        django_capture_on_commit_callbacks, protected_root):
    """FR-285, NFR-213: от не принятого остаются имя, размер, причина; список — в карточке (`data-rejected`) и в письме-подтверждении."""
    att = _att()
    exe = b"MZ\x90\x00" + b"\0" * 1230
    created, accepted = _mail_ticket(django_capture_on_commit_callbacks,
                                     [_part("вирус.exe", exe), _part("справка.txt", b"ok")])
    bad, good = accepted
    assert (bad.name, bad.size, bad.rejected, bad.file_id) == ("вирус.exe", len(exe), "executable", None)
    assert good.rejected == "" and good.file_id is not None
    assert model("core.StoredFile").objects.filter(purpose="attachment").count() == 1
    stored_files = [p for p in protected_root.rglob("*") if p.is_file()]
    assert len(stored_files) == 1 and stored_files[0].read_bytes() == b"ok", "тело не принятого файла не хранится"
    assert [a.pk for a in att.rejected_of(created.entry)] == [bad.pk]
    assert [a.pk for a in att.rejected_of(created.ticket)] == [bad.pk]
    # карточка
    card = _card(_staff(), created.ticket)
    items = _find(card, "li", data_rejected="executable")
    assert items and any("вирус.exe — исполняемый файл" in item.text() for item in items)
    assert _find(card, data_rejected_attachments=True)
    # подтверждение заявителю
    (message,) = [m for m in sd.ticket_mails(created.ticket) if m.template == "ticket.confirmation"]
    text = " ".join(sd.mail_text(message, {"ticket_id": created.ticket.pk, "entry_id": created.entry.pk,
                                           "after_hours": None}).split())
    assert "Вложения, которые не приняты" in text
    assert "вирус.exe — исполняемый файл" in text
    # имя, размер, причина — и в базе
    stored_bad = model("servicedesk.Attachment").objects.get(pk=bad.pk)
    assert (stored_bad.name, stored_bad.size, stored_bad.rejected, stored_bad.file_id) == (
        "вирус.exe", len(exe), "executable", None)


# --- 6. встроенные картинки -----------------------------------------------------------------------------

def test_inline_image_is_attachment_and_checked(django_capture_on_commit_callbacks, protected_root):
    """FR-286: встроенная картинка (с `Content-ID`) — обычное вложение: `inline=True`, на проверке; исполняемый файл под видом картинки не принят."""
    mail_parse = _svc("mail_parse")
    raw = sd.build_mail(from_addr="client@example.test", to=["help@example.test"], subject="Картинка", text="Текст",
                        attachments=[sd.MailPart("logo.png", sd.sample("image.png"), "image/png",
                                                 content_id="logo@client.test"),
                                     sd.MailPart("fake.png", sd.sample("exe_pe.bin"), "image/png",
                                                 content_id="fake@client.test")])
    parts = mail_parse.parse(raw).parts
    assert [(p.name, p.inline) for p in parts] == [("logo.png", True), ("fake.png", True)]
    ticket, entry, accepted = _entry_ticket(parts, capture=django_capture_on_commit_callbacks)
    logo, fake = accepted
    assert logo.inline is True and logo.rejected == "" and logo.file_id is not None
    stored = _fresh(logo.file)
    assert stored.purpose == "attachment" and stored.status == "pending"
    assert len(_scan_jobs(stored)) == 1, "встроенная картинка проверяется, как любое вложение"
    assert fake.rejected == "executable" and fake.file_id is None


# --- 7. хранение до проверки ----------------------------------------------------------------------------

def test_accepted_file_stored_pending_in_incoming_with_owner_none(
        django_capture_on_commit_callbacks, protected_root):
    """FR-283, NFR-213: годный файл — в `incoming/<id>` тома, `StoredFile(attachment, owner=None, pending)`, проверка ставится после фиксации."""
    from apps.core.services import files

    data = b"hello attachment"
    ticket = sd.make_ticket(queue=sd.make_queue())
    entry = sd.make_entry(ticket, "incoming")
    with django_capture_on_commit_callbacks(execute=False):
        (accepted,) = _att().accept(entry, [_part("письмо.txt", data, content_type="text/plain")])
        assert org.files_jobs() == [], "проверка ставится только после фиксации"
    stored = _fresh(accepted.file)
    assert stored.purpose == "attachment" and stored.owner_id is None and stored.status == "pending"
    assert stored.size == len(data) and stored.sha256 == hashlib.sha256(data).hexdigest()
    assert stored.content_type == "text/plain"
    path = protected_root / "incoming" / str(stored.pk)
    assert path.read_bytes() == data and files.attachment_path(stored) == path
    assert (accepted.ticket_id, accepted.entry_id, accepted.name, accepted.size, accepted.inline) == (
        ticket.pk, entry.pk, "письмо.txt", len(data), False)
    entry2 = sd.make_entry(ticket, "incoming")
    with django_capture_on_commit_callbacks(execute=True):
        (second,) = _att().accept(entry2, [_part("второе.txt", b"two")])
    jobs = _scan_jobs(second.file)
    assert len(jobs) == 1 and jobs[0].timeout == 300, "очередь `files`, срок задания 300 с"


def test_stored_file_content_type_up_to_255_chars(django_capture_on_commit_callbacks, protected_root):
    """FR-283, NFR-213: `content_type` у вложения помещается в 255 знаков: длинный тип не роняет приём, 255 знаков хранятся целиком."""
    exact = "text/" + "a" * 250
    longer = "text/" + "b" * 400
    ticket, entry, accepted = _entry_ticket(
        [_part("a.txt", b"1", content_type=exact), _part("b.txt", b"2", content_type=longer)],
        capture=django_capture_on_commit_callbacks)
    first, second = (_fresh(a.file) for a in accepted)
    assert first.content_type == exact and len(first.content_type) == 255
    assert second.content_type == longer[:255]


# --- 8. итог проверки -----------------------------------------------------------------------------------

def test_scan_clean_moves_file_to_attachments_and_makes_it_downloadable(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-283: чисто — файл из `incoming` в `attachments/<id>`, статус `clean`, `scanned_at`; ссылка в карточке и выдача работают."""
    data = b"clean content"
    ticket, entry, (accepted,) = _entry_ticket([_part("отчёт.txt", data)], capture=django_capture_on_commit_callbacks)
    stored = accepted.file
    user = _staff()
    client = support.logged_in(user)
    url = f"/tickets/{ticket.number}/files/{stored.pk}/"
    assert client.get(url).status_code == 404, "до проверки файл не выдаётся"
    (pending,) = _attachment_nodes(_card(user, ticket))
    assert pending.attrs["data-state"] == "pending" and "проверяется" in pending.text()
    calls = sd.scan_clean(monkeypatch)
    _scan(stored, django_capture_on_commit_callbacks)
    assert calls == [str(protected_root / "incoming" / str(stored.pk))]
    _fresh(stored)
    assert stored.status == "clean" and stored.scanned_at is not None
    assert (protected_root / "attachments" / str(stored.pk)).read_bytes() == data
    assert not (protected_root / "incoming" / str(stored.pk)).exists()
    assert client.get(url).status_code == 200
    (clean,) = _attachment_nodes(_card(user, ticket))
    assert clean.attrs["data-state"] == "clean"
    (link,) = _find(clean, "a")
    assert link.attrs["href"] == url and "отчёт.txt" in link.text()


def test_scan_infected_goes_to_quarantine_with_feed_event_and_audit(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-283: найден вирус — файл в `quarantine/<id>`, событие ленты `attachment_quarantined`, журнал `ticket.attachment_quarantined` без имени файла."""
    ticket, entry, (accepted,) = _entry_ticket([_part("заражён.txt", org.eicar_bytes())],
                                               capture=django_capture_on_commit_callbacks)
    stored = accepted.file
    sd.scan_found(monkeypatch, "Eicar-Signature")
    _scan(stored, django_capture_on_commit_callbacks)
    _fresh(stored)
    assert stored.status == "quarantine" and stored.signature == "Eicar-Signature"
    assert (protected_root / "quarantine" / str(stored.pk)).is_file()
    assert not (protected_root / "incoming" / str(stored.pk)).exists()
    assert not (protected_root / "attachments" / str(stored.pk)).exists()
    (event,) = _feed_events(ticket, "attachment_quarantined")
    assert event.data == {"name": "заражён.txt"}
    (audit,) = _journal("ticket.attachment_quarantined", ticket)
    assert audit.actor_id is None and audit.before == {}
    assert audit.after == {"file_id": str(stored.pk), "signature": "Eicar-Signature"}
    assert "заражён.txt" not in json.dumps([audit.before, audit.after], ensure_ascii=False), "имена вложений в журнал не пишутся"
    user = _staff()
    (node,) = _attachment_nodes(_card(user, ticket))
    assert node.attrs["data-state"] == "quarantine" and "в карантине" in node.text()
    assert _find(node, "a") == [], "из карантина ссылки нет"


def test_scan_heuristics_encrypted_rejects_as_password_archive_and_erases_file(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-284, FR-283: `Heuristics.Encrypted.*` — не вирус: файл стёрт, `StoredFile` удалён, `rejected="encrypted"`, событие `attachment_rejected`, карантина и журнала нет."""
    names = ("nested_enc_zip.zip", "enc_7z_compressed_header.7z")
    for name in names:
        assert _att().is_encrypted_archive(sd.sample(name)) is False, "свою проверку образец не проходит"
        ticket, entry, (accepted,) = _entry_ticket([_part("архив.dat", sd.sample(name))],
                                                   capture=django_capture_on_commit_callbacks)
        assert accepted.rejected == "", "до clamd архив принят"
        stored_id = accepted.file_id
        incoming = protected_root / "incoming" / str(stored_id)
        assert incoming.is_file()
        sd.scan_found(monkeypatch, "Heuristics.Encrypted.Zip")
        _scan(accepted.file, django_capture_on_commit_callbacks)
        row = _fresh(accepted)
        assert row.file_id is None and row.rejected == "encrypted" and row.name == "архив.dat"
        assert not model("core.StoredFile").objects.filter(pk=stored_id).exists()
        assert not incoming.exists() and not (protected_root / "quarantine" / str(stored_id)).exists()
        assert not (protected_root / "attachments" / str(stored_id)).exists()
        (event,) = _feed_events(ticket, "attachment_rejected")
        assert event.data == {"name": "архив.dat", "reason": "encrypted"}
        assert _feed_events(ticket, "attachment_quarantined") == []
        assert _journal("ticket.attachment_quarantined", ticket) == []


# --- 9. ClamAV недоступен, повторы ----------------------------------------------------------------------

def test_clamav_unavailable_ticket_created_attachment_waits_and_job_retries(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-287, NFR-206: ClamAV недоступен — заявка создана, вложение «проверяется» и не скачивается, задание уходит на повтор (24 повтора, срок 300 с)."""
    from rq.job import Job

    from apps.core import tasks

    created, (accepted,) = _mail_ticket(django_capture_on_commit_callbacks, [_part("файл.txt", b"data")])
    ticket, stored = created.ticket, accepted.file
    assert model("servicedesk.Ticket").objects.filter(pk=ticket.pk).exists()
    assert [m.template for m in sd.ticket_mails(ticket)] == ["ticket.confirmation"]
    calls = sd.scan_unavailable(monkeypatch)
    org.run_files_worker()
    assert calls, "антивирус должен быть вызван"
    _fresh(stored)
    assert stored.status == "pending" and stored.attempts == 1 and stored.last_error
    assert str(protected_root) not in stored.last_error
    assert (protected_root / "incoming" / str(stored.pk)).is_file()
    queue = org.files_queue()
    ids = queue.scheduled_job_registry.get_job_ids()
    assert len(ids) == 1
    job = Job.fetch(ids[0], connection=queue.connection)
    assert job.func_name == SCAN and job.args == (str(stored.pk),)
    assert len(job.retry_intervals) == 24 and job.timeout == 300
    user = _staff()
    (node,) = _attachment_nodes(_card(user, ticket))
    assert node.attrs["data-state"] == "pending" and "проверяется" in node.text()
    assert support.logged_in(user).get(f"/tickets/{ticket.number}/files/{stored.pk}/").status_code == 404
    # позже проверка проходит
    sd.scan_clean(monkeypatch)
    with django_capture_on_commit_callbacks(execute=True):
        tasks.scan_file(str(stored.pk))
    assert _fresh(stored).status == "clean"
    assert support.logged_in(user).get(f"/tickets/{ticket.number}/files/{stored.pk}/").status_code == 200


def test_pending_and_quarantined_not_downloadable_requeue_picks_pending(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-283, FR-287: ожидающий и карантин не выдаются (404, `download` — `Http404`); часовое задание подбирает только ожидающий файл без задания."""
    from django.http import Http404

    from apps.core import tasks

    ticket = sd.make_ticket(queue=sd.make_queue())
    entry = sd.make_entry(ticket, "incoming")
    with django_capture_on_commit_callbacks(execute=False):      # заданий проверки нет: потеряны
        pending, quarantined, clean = (a.file for a in _att().accept(
            entry, [_part("ждёт.txt", b"1"), _part("вирус.txt", b"2"), _part("чисто.txt", b"3")]))
    sd.scan_found(monkeypatch, "Eicar-Signature")
    _scan(quarantined, django_capture_on_commit_callbacks)
    sd.scan_clean(monkeypatch)
    _scan(clean, django_capture_on_commit_callbacks)
    assert (_fresh(pending).status, _fresh(quarantined).status, _fresh(clean).status) == (
        "pending", "quarantine", "clean")
    user = _staff()
    client = support.logged_in(user)
    for stored in (pending, quarantined):
        assert client.get(f"/tickets/{ticket.number}/files/{stored.pk}/").status_code == 404
        with pytest.raises(Http404):
            _att().download(user, ticket.number, stored.pk)
    assert client.get(f"/tickets/{ticket.number}/files/{clean.pk}/").status_code == 200
    for stored in (pending, quarantined, clean):
        sd.backdate(stored, "created_at", hours=2)
    with django_capture_on_commit_callbacks(execute=True):
        assert tasks.requeue_pending_scans() == 1
    assert len(_scan_jobs(pending)) == 1
    assert _scan_jobs(quarantined) == [] and _scan_jobs(clean) == []


# --- 10. выдача файла -----------------------------------------------------------------------------------

def _clean_attachment(capture, monkeypatch, name="отчёт за июнь.txt", data=b"payload"):
    ticket, entry, (accepted,) = _entry_ticket([_part(name, data)], capture=capture)
    sd.scan_clean(monkeypatch)
    _scan(accepted.file, capture)
    return ticket, _fresh(accepted.file), name


def test_download_of_invisible_ticket_returns_404(django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-283: заявка не видна, чужая заявка или несуществующий номер — одинаковый 404; `download` поднимает `Http404`."""
    from django.http import Http404

    ticket, stored, _ = _clean_attachment(django_capture_on_commit_callbacks, monkeypatch)
    other = sd.make_ticket(queue=sd.make_queue())
    outsider = support.make_employee()
    member = _staff()
    assert support.logged_in(member).get(f"/tickets/{ticket.number}/files/{stored.pk}/").status_code == 200
    client = support.logged_in(outsider)
    missing = client.get(f"/tickets/{ticket.number + 1000}/files/{stored.pk}/")
    invisible = client.get(f"/tickets/{ticket.number}/files/{stored.pk}/")
    assert invisible.status_code == 404 and missing.status_code == 404
    assert "X-Accel-Redirect" not in invisible
    with pytest.raises(Http404):
        _att().download(outsider, ticket.number, stored.pk)
    # видимая заявка, но файл другой заявки
    assert support.logged_in(member).get(f"/tickets/{other.number}/files/{stored.pk}/").status_code == 404
    with pytest.raises(Http404):
        _att().download(member, other.number, stored.pk)


def test_download_response_headers_x_accel_redirect_octet_stream_filename_star(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-283: выдача — `X-Accel-Redirect`, `application/octet-stream`, `attachment; filename*=UTF-8''…`, `nosniff`, `no-store`, тело пустое."""
    ticket, stored, name = _clean_attachment(django_capture_on_commit_callbacks, monkeypatch)
    user = _staff()
    response = support.logged_in(user).get(f"/tickets/{ticket.number}/files/{stored.pk}/")
    assert response.status_code == 200 and response.content == b""
    assert response["X-Accel-Redirect"] == f"/protected/attachments/{stored.pk}"
    assert response["Content-Type"] == "application/octet-stream"
    disposition = response["Content-Disposition"]
    prefix = "attachment; filename*=UTF-8''"
    assert disposition.startswith(prefix) and unquote(disposition[len(prefix):]) == name
    assert disposition.isascii() and " " not in disposition[len(prefix):]
    assert response["X-Content-Type-Options"] == "nosniff"
    assert "no-store" in response["Cache-Control"] and "max-age" not in response["Cache-Control"]
    result = _att().download(user, ticket.number, stored.pk)
    assert (result.accel_path, result.filename, result.content_type) == (
        f"/protected/attachments/{stored.pk}", name, "application/octet-stream")


# --- 11. исходное письмо --------------------------------------------------------------------------------

def _eml_ticket(capture, parts, protected_root, **inbound_over):
    """Заявка с входящим письмом, элементом `incoming` (`inbound`) и вложениями через `accept`."""
    ticket = sd.make_ticket(queue=sd.make_queue())
    inbound = sd.make_inbound(ticket=ticket, status="processed", outcome="created", **inbound_over)
    _put_eml(inbound, protected_root)
    entry = sd.make_entry(ticket, "incoming", inbound=inbound)
    with capture(execute=True):
        accepted = _att().accept(entry, list(parts), strict=False)
    return ticket, inbound, entry, accepted


def _source_links(user, ticket):
    return _find(_card(user, ticket), "a", data_action="source-mail")


def test_source_eml_issued_only_when_all_attachments_clean_and_none_rejected(
        django_capture_on_commit_callbacks, protected_root, monkeypatch):
    """FR-212: `.eml` выдаётся, только если все вложения чистые и ни одно не отклонено; ожидающее, карантин, отклонённое, стёртое письмо — 404, ссылки в карточке нет."""
    from django.http import Http404

    user = _staff()
    client = support.logged_in(user)

    def get(ticket, inbound):
        return client.get(f"/tickets/{ticket.number}/mail/{inbound.pk}.eml")

    # без вложений
    ticket, inbound, entry, _ = _eml_ticket(django_capture_on_commit_callbacks, [], protected_root)
    response = get(ticket, inbound)
    assert response.status_code == 200 and response.content == b""
    assert response["X-Accel-Redirect"] == f"/protected/inbound/{inbound.pk}.eml"
    assert response["Content-Type"] == "application/octet-stream"
    assert response["Content-Disposition"] == f"attachment; filename*=UTF-8''mail-{inbound.pk}.eml"
    assert response["X-Content-Type-Options"] == "nosniff" and "no-store" in response["Cache-Control"]
    (link,) = _source_links(user, ticket)
    assert link.attrs["href"] == f"/tickets/{ticket.number}/mail/{inbound.pk}.eml"
    assert _att().source_mail(user, ticket.number, inbound.pk).accel_path == f"/protected/inbound/{inbound.pk}.eml"
    # два вложения: одно проверено, другое ждёт
    ticket, inbound, entry, (first, second) = _eml_ticket(
        django_capture_on_commit_callbacks, [_part("а.txt", b"1"), _part("б.txt", b"2")], protected_root)
    sd.scan_clean(monkeypatch)
    _scan(first.file, django_capture_on_commit_callbacks)
    assert get(ticket, inbound).status_code == 404 and _source_links(user, ticket) == []
    with pytest.raises(Http404):
        _att().source_mail(user, ticket.number, inbound.pk)
    _scan(second.file, django_capture_on_commit_callbacks)
    assert get(ticket, inbound).status_code == 200 and len(_source_links(user, ticket)) == 1
    # карантин
    ticket, inbound, entry, (clean, infected) = _eml_ticket(
        django_capture_on_commit_callbacks, [_part("а.txt", b"1"), _part("в.txt", b"2")], protected_root)
    _scan(clean.file, django_capture_on_commit_callbacks)
    sd.scan_found(monkeypatch, "Eicar-Signature")
    _scan(infected.file, django_capture_on_commit_callbacks)
    assert get(ticket, inbound).status_code == 404 and _source_links(user, ticket) == []
    # не принятое вложение (исполняемый) при остальных чистых
    ticket, inbound, entry, (clean, bad) = _eml_ticket(
        django_capture_on_commit_callbacks, [_part("а.txt", b"1"), _part("x.exe", b"text")], protected_root)
    sd.scan_clean(monkeypatch)
    _scan(clean.file, django_capture_on_commit_callbacks)
    assert bad.rejected == "executable"
    assert get(ticket, inbound).status_code == 404 and _source_links(user, ticket) == []
    # письмо с стёртым файлом
    ticket, inbound, entry, _ = _eml_ticket(django_capture_on_commit_callbacks, [], protected_root, raw_deleted=True)
    assert get(ticket, inbound).status_code == 404 and _source_links(user, ticket) == []


def test_source_eml_of_invisible_ticket_returns_404(django_capture_on_commit_callbacks, protected_root):
    """FR-212: заявка не видна — 404, как у несуществующей; письмо другой заявки по номеру этой — 404."""
    from django.http import Http404

    ticket, inbound, entry, _ = _eml_ticket(django_capture_on_commit_callbacks, [], protected_root)
    other_ticket, other_inbound, _, _ = _eml_ticket(django_capture_on_commit_callbacks, [], protected_root)
    member = _staff()
    outsider = support.make_employee()
    assert support.logged_in(member).get(f"/tickets/{ticket.number}/mail/{inbound.pk}.eml").status_code == 200
    client = support.logged_in(outsider)
    invisible = client.get(f"/tickets/{ticket.number}/mail/{inbound.pk}.eml")
    missing = client.get(f"/tickets/{ticket.number + 1000}/mail/{inbound.pk}.eml")
    assert invisible.status_code == 404 and missing.status_code == 404
    assert "X-Accel-Redirect" not in invisible
    with pytest.raises(Http404):
        _att().source_mail(outsider, ticket.number, inbound.pk)
    assert support.logged_in(member).get(f"/tickets/{ticket.number}/mail/{other_inbound.pk}.eml").status_code == 404
    with pytest.raises(Http404):
        _att().source_mail(member, ticket.number, other_inbound.pk)
