"""T-8117a: тесты загрузки и привязки файлов (FR-662, FR-669, NFR-704).

Источники: PLAN-008 «Файлы и эскизы» (загрузка по одному, `core.uploads.reject_reason`, 10 к сообщению, 30
непривязанных, условная привязка с проверкой числа строк, «убрать» до отправки), TASKS-008 T-8117a; CONTRACT-008:
5.4 (`files.upload`/`bind`/`remove`), 10.1–10.2 (HTMX, отказ 200, 403/404, поля `file`/`files`/`chat`/`have`),
12.5 (`[data-messenger-file]` — таблетка со скрытым `input[name="files"]` и `button[data-action="file-remove"]`),
13.1 (`files_limit`, `file_too_big`, `file_type`), 13.2 (`file_missing`, `too_many_unbound`), 1.4 (десять файлов,
тридцать непривязанных, 20 МБ, 40 Мп).

Код среза на уровне модуля не импортируется (CONTRACT-008, «Правила для всех тестов среза»): модели берутся через
`support.model`, службы — внутри функций теста. Тексты отказов — литералы разделов 13.1/13.2, ищутся подстрокой в
разметке. Секретов и ПДн нет: адреса и телефоны не создаются.

Допущения писателя (см. отчёт T-8117a): 1) пределы и причины проверяются через адрес `POST /messenger/files/`
(раздел 10.2 — там же коды и поля отказа), служба `files.upload` проверяется тем же путём; 2) ранний предел 10
считается как «прикреплённые к сообщению плюс свои непривязанные из `have`» (план), поэтому одиннадцатый файл
проверяется дважды — подсказкой `have` при загрузке и привязкой одиннадцати при отправке; 3) отказы запрашиваются
HTMX-запросом — ответ фрагмент (10.1), обычный POST отдаёт 302 только на успехе; 4) `files.remove` берёт строку
`MessageAttachment` и сотрудника (5.4), чужой и привязанный файл — `Http404`.
"""
import importlib
import re
from html.parser import HTMLParser

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import transaction
from django.http import Http404

from tests import support
from tests import support_messenger as messenger
from tests import support_servicedesk as sd
from tests.support import HX, model

pytestmark = pytest.mark.django_db

MB = 1024 * 1024
MISSING = 999999
TEXT_FILES_LIMIT = "Не больше 10 файлов к сообщению"
TEXT_TOO_BIG = "Файл больше 20 МБ"
TEXT_TYPE = "Файл такого типа не принимается"
TEXT_UNBOUND = "Слишком много файлов без сообщения: отправьте сообщение или уберите лишние"
TEXT_MISSING = "Файл не найден"

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- разбор разметки (помощник только этого файла; образец — test_feed_files.py) -------------------------------

class Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.parent = parent
        self.children = []
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}

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
    wanted = {name.rstrip("_").replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value) for name, value in wanted.items()):
            found.append(node)
    return found


def _refusals(response) -> list[tuple[str, str, str]]:
    """Отказы формы: (поле, код, текст) — `[data-error][data-code]` в ответе."""
    return [(node.attrs["data-error"], node.attrs.get("data-code", ""), node.text())
            for node in _tree(response).walk() if "data-error" in node.attrs]


def _refused(response, field: str, code: str, text: str) -> None:
    assert response.status_code == 200, f"отказ {code}: ждали 200, получили {response.status_code}"
    assert (field, code, text) in _refusals(response), f"нет отказа {field}/{code}/{text!r}: {_refusals(response)}"
    assert text in response.content.decode("utf-8")


# --- помощники файлов сообщения --------------------------------------------------------------------------------

def _svc(name: str):
    return importlib.import_module(f"apps.messenger.services.{name}")


def _upload(session, chat, name: str, data: bytes, have=()):
    fields = {"file": SimpleUploadedFile(name, data), "chat": chat.pk,
              "have": [str(number) for number in have]}
    return session.client.post("/messenger/files/", fields, **HX)


def _send(session, chat, files=(), text: str = "Сообщение с файлами"):
    return session.client.post(f"/messenger/chats/{chat.pk}/messages/",
                               {"text": text, "files": [str(number) for number in files]}, **HX)


def _counts() -> tuple[int, int]:
    """Число строк `MessageAttachment` и `StoredFile` назначения «вложение сообщения чата»."""
    attachments = model("messenger.MessageAttachment").objects.count()
    stored = model("core.StoredFile").objects.filter(purpose="messenger").count()
    return attachments, stored


def _messages() -> int:
    return model("messenger.Message").objects.count()


def _unbound(user, chat, count: int, prefix: str = "ждёт") -> list:
    return [messenger.attach(chat, f"{prefix}-{number}.txt", uploaded_by=user) for number in range(count)]


def _fresh(item):
    return model("messenger.MessageAttachment").objects.get(pk=item.pk)


def _pill(response, file_id=None) -> Node:
    """Таблетка загруженного файла `[data-messenger-file]` со скрытым `input[name=files]` и крестиком."""
    pills = _find(_tree(response), data_messenger_file=True)
    assert len(pills) == 1, f"ждали одну таблетку, нашли {len(pills)}"
    pill = pills[0]
    if file_id is not None:
        assert pill.attrs["data-messenger-file"] == str(file_id)
    return pill


def _disk(protected_root) -> list:
    return sorted(str(path.relative_to(protected_root)) for path in protected_root.rglob("*") if path.is_file())


def _chat_pair():
    author = messenger.make_user(full_name="Автор Файлов Сообщения")
    friend = messenger.make_user(full_name="Собеседник Файлов Сообщения")
    return author, friend, messenger.group(author, [friend], title="Файлы сообщения")


# --- 1. загрузка: размер и содержимое --------------------------------------------------------------------------

def test_upload_20mb_ok_and_20mb_plus_byte_refused(protected_root):
    """FR-662, NFR-704: ровно 20 МБ принимается — 200, таблетка `[data-messenger-file="<id>"]` со скрытым
    `input[name="files"][value="<id>"]` и крестиком `button[data-action="file-remove"]`; строка `StoredFile`
    назначения `messenger` («проверяется») и непривязанная строка `MessageAttachment`; на байт больше — «Файл
    больше 20 МБ» (`file_too_big`) у поля `file`, ничего не сохранено."""
    author, _, chat = _chat_pair()
    accepted = _upload(author, chat, "ровно.txt", b"a" * (20 * MB))
    assert accepted.status_code == 200
    assert _refusals(accepted) == []
    (made,) = model("messenger.MessageAttachment").objects.filter(uploaded_by=author.user)
    pill = _pill(accepted, made.pk)
    (hidden,) = _find(pill, "input", name="files")
    assert hidden.attrs["value"] == str(made.pk) and hidden.attrs.get("type") == "hidden"
    assert len(_find(pill, "button", data_action="file-remove")) == 1
    assert made.message_id is None and made.name == "ровно.txt"
    assert made.file.purpose == "messenger" and made.file.status == "pending"
    assert made.file.size == 20 * MB
    assert (protected_root / "incoming" / str(made.file_id)).stat().st_size == 20 * MB

    before, disk = _counts(), _disk(protected_root)
    refused = _upload(author, chat, "больше.txt", b"a" * (20 * MB + 1))
    _refused(refused, "file", "file_too_big", TEXT_TOO_BIG)
    assert _find(_tree(refused), data_messenger_file=True) == []
    assert _counts() == before
    assert _disk(protected_root) == disk


def test_executable_and_password_archive_refused_with_reason(protected_root):
    """FR-662: исполняемый файл (расширение, строка `#!`, PE и ELF под именем картинки) и архив с паролем (ZIP
    ZipCrypto и AES, RAR5) — «Файл такого типа не принимается» (`file_type`) у поля `file`, 200; архив без пароля
    принимается таблеткой; отказы ничего не сохраняют."""
    author, _, chat = _chat_pair()
    before = _counts()
    cases = (("программа.exe", b"not really a program"),
             ("запуск.txt", b"#!/bin/sh\necho hello\n"),
             ("photo.png", sd.sample("exe_pe.bin")),
             ("picture.jpg", sd.sample("exe_elf.bin")),
             ("архив.zip", sd.sample("enc_zip_zipcrypto.zip")),
             ("архив-aes.zip", sd.sample("enc_zip_aes.zip")),
             ("архив.rar", sd.sample("enc_rar5_data.rar")))
    for name, data in cases:
        _refused(_upload(author, chat, name, data), "file", "file_type", TEXT_TYPE)
        assert _counts() == before, name
    assert _disk(protected_root) == []

    accepted = _upload(author, chat, "обычный.zip", sd.sample("plain.zip"))
    assert accepted.status_code == 200 and _refusals(accepted) == []
    assert len(_find(_tree(accepted), data_messenger_file=True)) == 1


def test_image_over_40_megapixels_refused_as_type(protected_root):
    """FR-662, NFR-704: картинка больше 40 млн точек при малом размере файла (`ImageTooLarge`) — тот же отказ типа
    «Файл такого типа не принимается» (`file_type`), 200, не 500; строк и файлов не прибавилось."""
    author, _, chat = _chat_pair()
    before = _counts()
    huge = messenger.images()["huge"]
    assert len(huge) < 5 * MB
    _refused(_upload(author, chat, "огромная.png", huge), "file", "file_type", TEXT_TYPE)
    assert _counts() == before
    assert _disk(protected_root) == []


# --- 2. пределы: десять к сообщению и тридцать непривязанных ----------------------------------------------------

def test_eleventh_file_refused_including_already_attached(protected_root):
    """FR-662: одиннадцатый файл — «Не больше 10 файлов к сообщению» (`files_limit`), считая уже прикреплённые:
    загрузка при десяти своих непривязанных в `have` (поле `file`) и отправка одиннадцати файлов (поле `files`);
    отказанный файл не сохранён, сообщения нет, присланные файлы остались непривязанными."""
    author, _, chat = _chat_pair()
    waiting = _unbound(author.user, chat, 10, "в форме")
    before = _counts()
    _refused(_upload(author, chat, "одиннадцатый.txt", b"data", have=[item.pk for item in waiting]),
             "file", "files_limit", TEXT_FILES_LIMIT)
    assert _counts() == before

    eleven = _unbound(author.user, chat, 11, "пачка")
    messages = _messages()
    _refused(_send(author, chat, [item.pk for item in eleven]), "files", "files_limit", TEXT_FILES_LIMIT)
    assert _messages() == messages
    assert all(_fresh(item).message_id is None for item in eleven)


def test_31st_unbound_upload_refused(protected_root):
    """FR-662: у сотрудника не больше 30 непривязанных файлов: тридцатый принимается, тридцать первый — «Слишком
    много файлов без сообщения: отправьте сообщение или уберите лишние» (`too_many_unbound`) у поля `file`; строк
    не прибавилось; у другого сотрудника счёт свой."""
    author, _, chat = _chat_pair()
    other = messenger.make_user(full_name="Другой Счёт Файлов")
    other_chat = messenger.personal(author, other)
    _unbound(author.user, chat, 29)
    thirtieth = _upload(author, chat, "тридцатый.txt", b"data")
    assert thirtieth.status_code == 200 and _refusals(thirtieth) == []
    before = _counts()
    _refused(_upload(author, chat, "тридцать-первый.txt", b"data"), "file", "too_many_unbound", TEXT_UNBOUND)
    assert _counts() == before
    elsewhere = _upload(other, other_chat, "чужой-счёт.txt", b"data")
    assert elsewhere.status_code == 200 and _refusals(elsewhere) == []


# --- 3. привязка при отправке ----------------------------------------------------------------------------------

def test_foreign_unbound_file_id_refused_on_send(protected_root):
    """FR-662, FR-669: чужой непривязанный номер в `files` при отправке — тот же отказ «Файл не найден»
    (`file_missing`) у поля `files`, что у несуществующего; сообщения нет, ничего не привязано, в том числе свой
    файл из того же запроса; чужой файл остался непривязанным у своего хозяина."""
    author, friend, chat = _chat_pair()
    own = messenger.attach(chat, "свой.txt", uploaded_by=author.user)
    foreign = messenger.attach(chat, "чужой.txt", uploaded_by=friend.user)
    messages = _messages()
    response = _send(author, chat, [own.pk, foreign.pk])
    _refused(response, "files", "file_missing", TEXT_MISSING)
    missing = _send(author, chat, [own.pk, MISSING])
    assert [item[1:] for item in _refusals(response)] == [item[1:] for item in _refusals(missing)]
    assert _messages() == messages
    assert (_fresh(own).message_id, _fresh(own).uploaded_by_id) == (None, author.user.pk)
    assert (_fresh(foreign).message_id, _fresh(foreign).uploaded_by_id) == (None, friend.user.pk)


def test_bind_uses_conditional_update_and_rolls_back_on_short_count(protected_root):
    """FR-662: привязка — условный `UPDATE … WHERE message_id IS NULL AND uploaded_by_id = <я>` с параметрами
    (номера файлов и автора в тексте SQL нет); привязано строк меньше присланного (несуществующий номер, уже
    привязанный файл) — откат и «Файл не найден» (`file_missing`); сообщения нет, свой свободный файл остался
    непривязанным; служба поднимает `MessengerError` с кодом `file_missing`."""
    author, _, chat = _chat_pair()
    items = [messenger.attach(chat, f"с-{number}.txt", uploaded_by=author.user) for number in range(2)]
    ids = [item.pk for item in items]
    with messenger.queries_with_params() as pairs:
        message = _svc("messages").send(chat, author.user, "Сообщение с файлами", files=ids)
    updates = [(sql, params) for sql, params in pairs
               if sql.lstrip().upper().startswith("UPDATE") and "messenger_messageattachment" in sql]
    assert updates, "привязка файлов должна быть отдельным UPDATE таблицы messenger_messageattachment"
    sql, params = updates[0]
    lowered = " ".join(sql.lower().split())
    assert "message_id" in lowered and "is null" in lowered and "uploaded_by_id" in lowered
    flat = []
    for value in params or ():
        flat.extend(value if isinstance(value, (list, tuple, set)) else [value])
    assert author.user.pk in flat and set(ids) <= set(flat), f"параметры: {params}"
    for number in [author.user.pk, *ids]:
        assert re.search(rf"(?<![\w_]){number}(?![\w_])", sql) is None, f"{number} стоит в тексте SQL"
    assert all(_fresh(item).message_id == message.pk for item in items)

    free = messenger.attach(chat, "свободный.txt", uploaded_by=author.user)
    taken = messenger.attach(chat, "занят.txt", uploaded_by=author.user)
    taken_message = messenger.post(chat, author, "Занятый файл", files=[taken])
    messages = _messages()
    for sent in ([free.pk, MISSING], [free.pk, taken.pk]):
        _refused(_send(author, chat, sent), "files", "file_missing", TEXT_MISSING)
        assert _messages() == messages
        assert _fresh(free).message_id is None
        assert _fresh(taken).message_id == taken_message.pk

    errors = importlib.import_module("apps.messenger.services.errors")
    with pytest.raises(errors.MessengerError) as caught:
        with transaction.atomic():
            _svc("messages").send(chat, author.user, "Текст", files=[free.pk, MISSING])
    assert caught.value.code == "file_missing"
    assert _messages() == messages and _fresh(free).message_id is None


# --- 4. «убрать» до отправки -----------------------------------------------------------------------------------

def test_remove_unbound_file_deletes_row_and_file_after_commit(
        django_capture_on_commit_callbacks, protected_root):
    """FR-662: `POST /messenger/files/<id>/delete/` убирает только свой непривязанный файл — 200 с пустым телом,
    строки `MessageAttachment` и `StoredFile` в транзакции, файл с диска после фиксации; чужой, привязанный и
    несуществующий — 404 одним и тем же ответом, ничего не удалено; служба `files.remove` поднимает `Http404`."""
    author, friend, chat = _chat_pair()
    mine = messenger.attach(chat, "мой.txt", b"my file", uploaded_by=author.user, write=True)
    foreign = messenger.attach(chat, "чужой.txt", b"other file", uploaded_by=friend.user, write=True)
    bound = messenger.attach(chat, "привязан.txt", b"bound file", uploaded_by=author.user, write=True)
    messenger.post(chat, author, "Сообщение с файлом", files=[bound])
    before = _counts()
    answers = []
    for number in (foreign.pk, bound.pk, MISSING):
        answers.append(author.client.post(f"/messenger/files/{number}/delete/", **HX))
    assert [response.status_code for response in answers] == [404, 404, 404]
    assert support.same_failure(*answers)
    assert _counts() == before
    files = _svc("files")
    with pytest.raises(Http404):
        files.remove(_fresh(foreign), author.user)
    with pytest.raises(Http404):
        files.remove(_fresh(bound), author.user)

    stored_id = mine.file_id
    path = protected_root / "attachments" / str(stored_id)
    assert path.is_file()
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        response = author.client.post(f"/messenger/files/{mine.pk}/delete/", **HX)
    assert response.status_code == 200 and response.content.strip() == b""
    assert not model("messenger.MessageAttachment").objects.filter(pk=mine.pk).exists()
    assert not model("core.StoredFile").objects.filter(pk=stored_id).exists()
    assert path.is_file(), "диск стирается после фиксации, а не в транзакции"
    assert callbacks, "стирание файла — transaction.on_commit после фиксации"
    for callback in callbacks:
        callback()
    assert not path.exists()
    assert model("messenger.MessageAttachment").objects.filter(pk__in=[foreign.pk, bound.pk]).count() == 2
    assert model("core.StoredFile").objects.filter(pk__in=[foreign.file_id, bound.file_id]).count() == 2