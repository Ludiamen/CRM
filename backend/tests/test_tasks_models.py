"""Срез 009 «Задачи»: модель данных и изменения ядра (FR-674…FR-699).

T-9002: назначение файла `task` в конце перечня и миграция `core 0012` (FR-693). Остальные тесты моделей
добавляет T-9101.
"""
import ast

import pytest

from tests import support

pytestmark = pytest.mark.django_db


# --- core/models/files.py и миграция 0012 --------------------------------------------------------------------------

def test_purpose_task_is_last():
    """FR-693: `StoredFile.Purpose.TASK = "task"` («вложение задачи») — последним; прежние шесть значений и
    подписи те же, `max_length` 16 и значение по умолчанию `photo` не менялись; миграция
    `core 0012_storedfile_task_purpose` — одна операция `AlterField` поля `purpose`, зависит от `0011`; строку
    с назначением `task` можно создать (CONTRACT-009, 2.1)."""
    StoredFile = support.model("core.StoredFile")
    assert StoredFile.Purpose.choices == [
        ("photo", "фото"), ("attachment", "вложение"), ("knowledge", "файл статьи"),
        ("lists", "файл записи списка"), ("feed", "вложение ленты"), ("messenger", "вложение сообщения чата"),
        ("task", "вложение задачи")]
    assert tuple(StoredFile.Purpose.values) == (
        "photo", "attachment", "knowledge", "lists", "feed", "messenger", "task")
    assert StoredFile.Purpose.TASK == "task" and list(StoredFile.Purpose.values)[-1] == "task"
    field = StoredFile._meta.get_field("purpose")
    assert field.max_length == 16 and field.default == "photo"
    assert len(StoredFile.Purpose.TASK) <= field.max_length

    path = support.BACKEND_DIR / "apps" / "core" / "migrations" / "0012_storedfile_task_purpose.py"
    assert path.is_file(), "нет миграции core/0012_storedfile_task_purpose.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Migration")
    assigned = {t.id: node.value for node in cls.body if isinstance(node, ast.Assign) for t in node.targets
                if isinstance(t, ast.Name)}
    assert ast.literal_eval(assigned["dependencies"]) == [("core", "0011_storedfile_messenger_purpose")]
    operations = assigned["operations"].elts
    assert len(operations) == 1 and isinstance(operations[0], ast.Call) and operations[0].func.attr == "AlterField"
    keywords = {kw.arg: ast.literal_eval(kw.value) for kw in operations[0].keywords
                if kw.arg in ("model_name", "name")}
    assert keywords == {"model_name": "storedfile", "name": "purpose"}

    row = StoredFile.objects.create(purpose="task", owner=None, size=1, sha256="0" * 64,
                                    content_type="application/octet-stream", status="pending")
    row.refresh_from_db()
    assert row.purpose == "task"