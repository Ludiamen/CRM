"""Срез 010 «Поручения»: модели и изменения ядра (FR-700…723).

T-10002: назначение `instruction` в конце перечня и `core 0014`. Остальные тесты моделей добавляет T-10101.
"""
import ast

import pytest

from tests import support

pytestmark = pytest.mark.django_db


def test_purpose_instruction_is_last():
    """NFR-722: `StoredFile.Purpose.INSTRUCTION = "instruction"` («вложение поручения») — последним; прежние
    семь значений и подписи те же; миграция `core 0014` — один `AlterField`, зависит от `0013`."""
    StoredFile = support.model("core.StoredFile")
    assert tuple(StoredFile.Purpose.values) == (
        "photo", "attachment", "knowledge", "lists", "feed", "messenger", "task", "instruction")
    assert StoredFile.Purpose.INSTRUCTION.label == "вложение поручения"
    field = StoredFile._meta.get_field("purpose")
    assert field.max_length == 16 and field.default == "photo"

    path = support.BACKEND_DIR / "apps" / "core" / "migrations" / "0014_storedfile_instruction_purpose.py"
    assert path.is_file(), "нет миграции core/0014_storedfile_instruction_purpose.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Migration")
    assigned = {t.id: node.value for node in cls.body if isinstance(node, ast.Assign) for t in node.targets
                if isinstance(t, ast.Name)}
    assert ast.literal_eval(assigned["dependencies"]) == [("core", "0013_tasks_permissions")]
    operations = assigned["operations"].elts
    assert len(operations) == 1 and operations[0].func.attr == "AlterField"
