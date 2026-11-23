"""Срез 010 «Поручения»: файлы (T-10116; NFR-722).

`apps.instructions.services.files`, `views.files` и назначение `instruction` — CONTRACT-010, 5.1, 6.2, 12.2.
Код среза импортируется внутри тестов: сбор проходит до появления моделей и служб.
"""
import datetime

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile

from tests import support, support_org
from tests import support_instructions as ins

pytestmark = pytest.mark.django_db

MAX_BYTES = 20 * 1024 * 1024
PENDING_TEXT = "Файл ещё проверяется"
QUARANTINE_TEXT = "Файл в карантине"


def files():
    from apps.instructions.services import files as module
    return module


def _err(call):
    from apps.instructions.texts import InstructionsError

    with pytest.raises(InstructionsError) as caught:
        call()
    return caught.value


def _setup():
    row = ins.make_instruction()
    report = support.model("instructions.InstructionReport").objects.create(
        instruction=row, date=None, author=row.assignee, text="Итог")
    return row, report


def _upload(name="основание.pdf", data=b"%PDF-1.4 test"):
    return SimpleUploadedFile(name, data)


def _store(row, *, kind="basis", report=None, part=None, name="основание.pdf", data=b"%PDF-1.4 test"):
    return files().store(row.author, row, _upload(name, data), kind=kind, report=report, part=part)


def _scan(stored, capture):
    from apps.core import tasks as core_tasks

    with capture(execute=True):
        core_tasks.scan_file(str(stored.pk))


def test_store_checks_size_and_type(protected_root):
    """NFR-722: файл до 20 МБ принимается; больше — `file_too_big`; исполняемый — `file_type`."""
    row, report = _setup()
    entry = _store(row)
    assert entry.kind == "basis" and entry.file.status == "pending"
    assert entry.uploaded_by_id == row.author_id and entry.name == "основание.pdf"

    err = _err(lambda: _store(row, name="большой.bin", data=b"x" * (MAX_BYTES + 1)))
    assert (err.code, err.field) == ("file_too_big", "file")
    err = _err(lambda: _store(row, name="вирус.exe", data=b"MZ...."))
    assert (err.code, err.field) == ("file_type", "file")


def test_clean_scan_makes_file_downloadable_via_x_accel(protected_root, django_capture_on_commit_callbacks,
                                                        monkeypatch):
    """NFR-722: до проверки файл недоступен; «чисто» — скачивание через X-Accel с `nosniff` и `no-store`."""
    row, report = _setup()
    entry = _store(row)
    client = support.logged_in(row.author)
    assert client.get(f"/instructions/files/{entry.pk}/").status_code == 404

    support_org.scan_clean(monkeypatch)
    _scan(entry.file, django_capture_on_commit_callbacks)
    entry.refresh_from_db()
    assert entry.file.status == "clean"

    response = client.get(f"/instructions/files/{entry.pk}/")
    assert response.status_code == 200 and response.content == b""
    assert response["X-Accel-Redirect"].startswith("/protected/attachments/")
    assert response["X-Content-Type-Options"] == "nosniff"
    assert response["Cache-Control"] == "no-store"


def test_found_scan_quarantines_and_hides_file(protected_root, django_capture_on_commit_callbacks, monkeypatch):
    """NFR-722: заражённый файл — карантин и текст «Файл в карантине»; ссылки нет."""
    row, report = _setup()
    entry = _store(row)
    support_org.scan_found(monkeypatch)
    _scan(entry.file, django_capture_on_commit_callbacks)
    entry.refresh_from_db()
    assert entry.file.status == "quarantine"

    response = support.logged_in(row.author).get(f"/instructions/files/{entry.pk}/")
    assert response.status_code == 404
    assert QUARANTINE_TEXT in response.content.decode()
    assert response.get("X-Accel-Redirect") is None


def test_pending_and_unavailable_scan_keep_file_hidden(protected_root, monkeypatch):
    """NFR-722: недоступный ClamAV не делает файл «чистым»; он остаётся «проверяется» и скрыт."""
    row, report = _setup()
    entry = _store(row)
    support_org.scan_unavailable(monkeypatch)
    from apps.core import tasks as core_tasks

    with pytest.raises(support_org.ScanUnavailable):
        core_tasks.scan_file(str(entry.file.pk))
    entry.refresh_from_db()
    assert entry.file.status == "pending"

    response = support.logged_in(row.author).get(f"/instructions/files/{entry.pk}/")
    assert response.status_code == 404
    assert PENDING_TEXT in response.content.decode()
    assert response.get("X-Accel-Redirect") is None


def test_ten_files_per_report_and_eleventh_refused(protected_root):
    """NFR-722: не больше 10 файлов на отчёт или часть; одиннадцатый — `report_limit` у поля `file`."""
    row, report = _setup()
    for index in range(10):
        _store(row, kind="report", report=report, name=f"отчёт-{index}.txt", data=b"data")
    err = _err(lambda: _store(row, kind="report", report=report, name="лишний.txt", data=b"data"))
    assert (err.code, err.field) == ("report_limit", "file")


def test_foreign_instruction_file_is_404(protected_root):
    """FR-719: файл чужого поручения — 404 как несуществующий."""
    first, _ = _setup()
    second, _ = _setup()
    entry = _store(first)
    assert support.logged_in(second.author).get(f"/instructions/files/{entry.pk}/").status_code == 404


def test_file_purposes_registered_for_instruction():
    """NFR-722: назначение `instruction` зарегистрировано в точке `file_purposes` и обрабатывает ожидание,
    чистый и карантин."""
    purposes = files().file_purposes()
    assert [item.purpose for item in purposes] == ["instruction"]
    assert all(callable(getattr(purposes[0], name)) for name in ("still_waiting", "clean", "found"))
    from apps.core import extensions

    registered = extensions.registered("file_purposes")
    assert any(func.__module__ == "apps.instructions.services.files" for func in registered)


def test_bind_files_to_report_and_part(protected_root):
    """FR-706, NFR-722: загруженные файлы привязываются к отчёту и к части отчётной даты."""
    row, report = _setup()
    due = ins.add_report_date(row, ins._today() + datetime.timedelta(days=3))
    part = support.model("instructions.InstructionReportPart").objects.create(
        date=due, author=row.assignee, text="Часть")
    report_file = _store(row, kind="report", report=None, name="отчёт.txt", data=b"report")
    part_file = _store(row, kind="part", part=None, name="часть.txt", data=b"part")

    files().bind(report=report, file_ids=[report_file.pk])
    files().bind(part=part, file_ids=[part_file.pk])
    report_file.refresh_from_db()
    part_file.refresh_from_db()
    assert report_file.report_id == report.pk and report_file.part_id is None
    assert part_file.part_id == part.pk and part_file.report_id is None