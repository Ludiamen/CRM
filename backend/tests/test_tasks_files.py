"""T-9116: файлы задачи — 20 МБ, ClamAV, карантин, типы, недоступность до проверки, имя, 10 на комментарий,
непривязанные, чужая ссылка, выдача (FR-693, NFR-713).

Источники: PLAN-009 «Комментарии, файлы и лента» (файлы через `core.services.uploads.store(data, name, "task")`,
ClamAV через `file_purposes`; до проверки недоступны, исполняемые и архивы с паролем отклоняются; имя — в
`TaskFile.name`, до 20 МБ, до 10 на комментарий; непривязанные старше 24 часов чистит `tasks_retention`); CONTRACT-009:
1.2 (25m nginx), 2.1 (`TaskFile`), 3 (`file_purposes` — `pending`/`clean`/`quarantine`), 5.1 (`files.store/bind/content`),
5.3 (подмена `apps.integrations.clamav.services.scan`), 6.2 (`POST /tasks/files/`, `GET /tasks/files/<uuid>/`),
6.3 (`[data-task-file]`), 12.1 (`files_limit`, `file_too_big`, `file_type`, `file_missing`), 12.2 («Файл ещё
проверяется», «Файл в карантине»).

Код среза импортируется внутри тестов, модели — через `support.model`; сбор проходит до появления кода. Строка
EICAR в тестах не используется (настоящий ClamAV — только в приёмке): подменяются `support_org.scan_*`.
"""
import hashlib
import mimetypes
import uuid
from datetime import timedelta
from html.parser import HTMLParser

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from tests import support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests import support_tasks as tasks_helpers

pytestmark = pytest.mark.django_db

MB = 1024 * 1024
TOO_BIG = "Файл больше 20 МБ"
TYPE_REFUSED = "Файл такого типа не принимается"
FILES_LIMIT = "Не больше 10 файлов к комментарию"
PENDING_TEXT = "Файл ещё проверяется"
QUARANTINE_TEXT = "Файл в карантине"

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- разбор разметки ---------------------------------------------------------------------------------------------

class _Node:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = {name: (value if value is not None else "") for name, value in attrs}
        self.parent = parent
        self.children = []

    def walk(self):
        for child in self.children:
            if isinstance(child, _Node):
                yield child
                yield from child.walk()

    def text(self) -> str:
        parts = []
        for child in self.children:
            parts.append(child.text() if isinstance(child, _Node) else child)
        return " ".join("".join(parts).split())


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", [], None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, attrs, self.cur)
        self.cur.children.append(node)
        if tag not in _VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(_Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def _tree(response) -> _Node:
    parser = _Parser()
    parser.feed(response.content.decode("utf-8", "replace"))
    return parser.root


def _find(scope, tag=None, **attrs) -> list:
    wanted = {name.rstrip("_").replace("_", "-"): value for name, value in attrs.items()}
    found = []
    for node in scope.walk():
        if tag is not None and node.tag != tag:
            continue
        if all(name in node.attrs and (value is True or node.attrs[name] == value)
               for name, value in wanted.items()):
            found.append(node)
    return found


def _refusals(response) -> list[tuple[str, str, str]]:
    return [(node.attrs["data-error"], node.attrs.get("data-code", ""), node.text())
            for node in _tree(response).walk() if "data-error" in node.attrs]


def _refused(response, field: str, code: str, text: str) -> None:
    assert response.status_code == 200, f"отказ {code}: ждали 200, получили {response.status_code}"
    found = _refusals(response)
    assert (field, code, text) in found, f"нет отказа {field}/{code}/{text!r}: {found}"


# --- помощники файлов -------------------------------------------------------------------------------------------

def _attach(task, name: str = "схема.png", data: bytes | None = None, *, status: str = "clean",
            uploaded_by=None, comment=None, write: bool = False):
    """Строки `StoredFile(purpose="task")` и `TaskFile`; `write=True` пишет байты по `attachment_path`."""
    if data is None:
        data = b"file body"
    now = timezone.now()
    stored = support.model("core.StoredFile").objects.create(
        purpose="task", owner=None, size=len(data), sha256=hashlib.sha256(data).hexdigest(),
        content_type=mimetypes.guess_type(name)[0] or "application/octet-stream", status=status,
        scanned_at=now if status != "pending" else None)
    if write:
        from apps.core.services import files as core_files

        path = core_files.attachment_path(stored)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
    return support.model("tasks.TaskFile").objects.create(
        task=task, comment=comment, file=stored, name=name, uploaded_by=uploaded_by or task.author)


def _upload(client, task, name: str, data: bytes):
    """`POST /tasks/files/` (multipart) с HTMX: таблетка `[data-task-file]` или отказ формы."""
    return client.post("/tasks/files/", {"file": SimpleUploadedFile(name, data), "task": task.pk}, **support.HX)


def _pill(response) -> _Node:
    pills = _find(_tree(response), data_task_file=True)
    assert len(pills) == 1, f"ждали одну таблетку файла, нашли {len(pills)}"
    return pills[0]


def _fetched(client, item):
    return client.get(f"/tasks/files/{item.pk}/")


def _path(stored):
    from apps.core.services import files as core_files

    return core_files.attachment_path(stored)


def _scan(stored, capture):
    """Проверка файла диспетчером ядра внутри фиксации (как у вложений ленты и мессенджера)."""
    from apps.core import tasks as core_tasks

    with capture(execute=True):
        core_tasks.scan_file(str(stored.pk))


def _world():
    author = tasks_helpers.staff_user(full_name="Автор Файлов Задачи")
    assignee = tasks_helpers.staff_user(full_name="Исполнитель Файлов Задачи")
    task = tasks_helpers.make_task(author=author, assignee=assignee, deadline=None, title="Задача файлов")
    return {"task": task, "author": author, "assignee": assignee}


# --- NFR-713: размер и тип -------------------------------------------------------------------------------------

def test_twenty_megabytes_accepted_byte_more_refused_and_name_kept(protected_root):
    """FR-693, NFR-713 (CONTRACT-009, 6.2, 12.1): ровно 20 МБ принимается — таблетка `[data-task-file="<uuid>"]`
    со скрытым `input[name="files"]`, строка `TaskFile` с именем файла и `StoredFile` назначения `task` в состоянии
    «проверяется»; на байт больше — «Файл больше 20 МБ» (`file_too_big`) у поля `file`, ничего не сохранено."""
    world = _world()
    client = support.logged_in(world["assignee"])

    accepted = _upload(client, world["task"], "схема отчёта.txt", b"a" * (20 * MB))
    assert accepted.status_code == 200 and _refusals(accepted) == []
    made = support.model("tasks.TaskFile").objects.get(task=world["task"])
    pill = _pill(accepted)
    assert pill.attrs["data-task-file"] == str(made.pk)
    (hidden,) = _find(pill, "input", name="files")
    assert hidden.attrs.get("value") == str(made.pk) and hidden.attrs.get("type") == "hidden"
    assert made.name == "схема отчёта.txt"
    assert made.file.purpose == "task" and made.file.status == "pending" and made.file.size == 20 * MB
    assert made.uploaded_by_id == world["assignee"].pk

    refused = _upload(client, world["task"], "больше.txt", b"a" * (20 * MB + 1))
    _refused(refused, "file", "file_too_big", TOO_BIG)
    assert support.model("tasks.TaskFile").objects.filter(task=world["task"]).count() == 1


def test_executable_and_password_archive_refused_plain_archive_accepted(protected_root):
    """FR-693 (CONTRACT-009, 12.1): исполняемые файлы (PE, ELF, расширение `.exe`) и архивы с паролем (ZIP ZipCrypto
    и AES, RAR5) — «Файл такого типа не принимается» (`file_type`) у поля `file`, 200; архив без пароля принимается."""
    world = _world()
    client = support.logged_in(world["assignee"])
    cases = (("программа.exe", b"not a program"),
             ("photo.png", sd.sample("exe_pe.bin")),
             ("picture.jpg", sd.sample("exe_elf.bin")),
             ("архив.zip", sd.sample("enc_zip_zipcrypto.zip")),
             ("архив-aes.zip", sd.sample("enc_zip_aes.zip")),
             ("архив.rar", sd.sample("enc_rar5_data.rar")))
    for name, data in cases:
        _refused(_upload(client, world["task"], name, data), "file", "file_type", TYPE_REFUSED)
    assert not support.model("tasks.TaskFile").objects.filter(task=world["task"]).exists()

    accepted = _upload(client, world["task"], "обычный.zip", sd.sample("plain.zip"))
    assert accepted.status_code == 200 and _refusals(accepted) == []


# --- ClamAV и состояния файла ----------------------------------------------------------------------------------

def test_clean_scan_makes_file_downloadable_via_x_accel(protected_root, django_capture_on_commit_callbacks,
                                                        monkeypatch):
    """FR-693, NFR-713 (CONTRACT-009, 6.2): файл загружается «проверяется» и недоступен; `scan` ответил «чисто» —
    состояние `clean`, файл переехал в `attachments/`, 200 с пустым телом и `X-Accel-Redirect:
    /protected/attachments/<номер StoredFile>`, `nosniff`, `no-store`."""
    world = _world()
    item = _attach(world["task"], "чистый.txt", b"clean", status="pending", write=True)
    client = support.logged_in(world["assignee"])
    assert _fetched(client, item).status_code == 404, "файл до проверки доступен"

    org.scan_clean(monkeypatch)
    _scan(item.file, django_capture_on_commit_callbacks)

    item.refresh_from_db()
    assert item.file.status == "clean"
    assert _path(item.file).is_file() and str(item.file.pk) in str(_path(item.file))
    response = _fetched(client, item)
    assert response.status_code == 200 and response.content == b""
    assert response["X-Accel-Redirect"] == f"/protected/attachments/{item.file_id}"
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Cache-Control"] == "no-store"


def test_found_scan_quarantines_file_and_hides_it(protected_root, django_capture_on_commit_callbacks, monkeypatch):
    """FR-693, NFR-713 (CONTRACT-009, 6.2, 12.2): `scan` нашёл сигнатуру — состояние `quarantine`, по прямой ссылке
    404 с текстом «Файл в карантине», без `X-Accel-Redirect`, даже автору задачи."""
    world = _world()
    item = _attach(world["task"], "заражён.txt", b"bad", status="pending", write=True)
    monkeypatch.setattr("apps.integrations.clamav.services.scan", lambda path: _scan_result(False, "Test-Signature"))
    _scan(item.file, django_capture_on_commit_callbacks)

    item.refresh_from_db()
    assert item.file.status == "quarantine"
    for user in (world["author"], world["assignee"]):
        response = _fetched(support.logged_in(user), item)
        assert response.status_code == 404
        assert QUARANTINE_TEXT in response.content.decode("utf-8")
        assert response.get("X-Accel-Redirect") is None


def _scan_result(clean: bool, signature: str):
    """Форма `ScanResult` интеграции ClamAV (поля `clean` и `signature`)."""
    return org.ScanResult(clean, signature)


def test_unavailable_scan_keeps_file_pending_and_hidden(protected_root, monkeypatch):
    """FR-693, NFR-713 (CONTRACT-009, 6.2, 12.2): недоступный ClamAV не делает файл «чистым» и не роняет запрос —
    файл остаётся «проверяется», по прямой ссылке 404 с текстом «Файл ещё проверяется»."""
    world = _world()
    item = _attach(world["task"], "проверка-недоступна.txt", b"data", status="pending", write=True)
    org.scan_unavailable(monkeypatch)
    from apps.core import tasks as core_tasks

    with pytest.raises(org.ScanUnavailable):
        core_tasks.scan_file(str(item.file.pk))

    item.refresh_from_db()
    assert item.file.status == "pending", f"недоступный ClamAV перевёл файл в {item.file.status!r}"
    response = _fetched(support.logged_in(world["assignee"]), item)
    assert response.status_code == 404
    assert PENDING_TEXT in response.content.decode("utf-8")
    assert response.get("X-Accel-Redirect") is None


# --- 10 файлов на комментарий и привязка -----------------------------------------------------------------------

def test_eleventh_file_in_comment_refused_with_reason(protected_root):
    """FR-693 (CONTRACT-009, 6.2, 12.1): к комментарию не больше 10 файлов — отправка одиннадцати непривязанных
    файлов отвечает «Не больше 10 файлов к комментарию» (`files_limit`) у поля `file`, комментарий не создан,
    файлы остались непривязанными."""
    world = _world()
    client = support.logged_in(world["assignee"])
    items = [_attach(world["task"], f"ждёт-{number}.txt", b"data", status="clean",
                     uploaded_by=world["assignee"]) for number in range(11)]
    before = support.model("tasks.TaskComment").objects.filter(task=world["task"]).count()

    response = client.post(f"/tasks/{world['task'].pk}/comments/",
                           {"text": "Комментарий с одиннадцатью", "files": [str(item.pk) for item in items]},
                           **support.HX)

    _refused(response, "file", "files_limit", FILES_LIMIT)
    assert support.model("tasks.TaskComment").objects.filter(task=world["task"]).count() == before
    assert all(support.model("tasks.TaskFile").objects.get(pk=item.pk).comment_id is None for item in items)


def test_unbound_file_older_than_24h_removed_by_retention(protected_root, django_capture_on_commit_callbacks):
    """FR-693 (CONTRACT-009, 6.2, 5.1): непривязанный файл старше 24 часов чистит `tasks_retention` — строки
    `TaskFile` и `StoredFile` в транзакции, файл с диска после фиксации; свежий и привязанный остаются."""
    world = _world()
    support.model("tasks.TaskSettings").objects.update_or_create(pk=1, defaults={"retention_years": 3})
    stale = _attach(world["task"], "старый.txt", b"stale", status="clean", write=True)
    fresh = _attach(world["task"], "свежий.txt", b"fresh", status="clean", write=True)
    comment = tasks_helpers.make_task(author=world["author"], assignee=world["assignee"], deadline=None,
                                      title="Задача с привязанным")
    bound = _attach(comment, "привязанный.txt", b"bound", status="clean", write=True)
    from apps.tasks.services import comments as comments_service

    made = comments_service.add(world["author"], comment, "С файлом")
    support.model("tasks.TaskFile").objects.filter(pk=bound.pk).update(comment=made)

    now = timezone.now()
    support.model("tasks.TaskFile").objects.filter(pk=stale.pk).update(created_at=now - timedelta(hours=25))
    support.model("tasks.TaskFile").objects.filter(pk=fresh.pk).update(created_at=now - timedelta(hours=23))

    stale_path = _path(stale.file)
    from apps.tasks.tasks import tasks_retention

    with django_capture_on_commit_callbacks(execute=True):
        tasks_retention(now=now)

    assert not support.model("tasks.TaskFile").objects.filter(pk=stale.pk).exists()
    assert not support.model("core.StoredFile").objects.filter(pk=stale.file_id).exists()
    assert not stale_path.exists(), "файл не стёрт с диска"
    assert support.model("tasks.TaskFile").objects.filter(pk__in=[fresh.pk, bound.pk]).count() == 2


# --- выдача и чужая ссылка -------------------------------------------------------------------------------------

def test_foreign_task_file_link_is_404_like_missing(protected_root):
    """FR-693 (CONTRACT-009, 6.1, 11): файл задачи, которую сотрудник не видит, и несуществующий файл отвечают
    одинаково — 404 «Не найдено» без `X-Accel-Redirect»; видимый файл отдаётся."""
    world = _world()
    item = _attach(world["task"], "схема.txt", b"body", status="clean", write=True)
    outsider = support.logged_in(tasks_helpers.staff_user(full_name="Посторонний Файлов"))
    hidden = outsider.get(f"/tasks/files/{item.pk}/")
    missing = outsider.get(f"/tasks/files/{uuid.uuid4()}/")
    assert hidden.status_code == 404 and missing.status_code == 404
    assert support.same_failure(hidden, missing)
    assert hidden.get("X-Accel-Redirect") is None
    assert _fetched(support.logged_in(world["assignee"]), item).status_code == 200