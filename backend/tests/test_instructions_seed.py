"""Срез 010 «Поручения»: данные установки (T-10120; FR-701, 709, NFR-729).

Миграция `instructions 0002_initial_data` — CONTRACT-010, 2.2. Модуль миграции импортируется внутри тестов: сбор
проходит до появления кода.
"""
import importlib
from types import SimpleNamespace

import pytest
from django.apps import apps as django_apps
from django.db import connections

from tests import support

pytestmark = pytest.mark.django_db

BASIS = ("Приказ", "Протокол совещания", "Письмо", "Устное указание")
DEFAULT_LADDER = {"offsets": [30, 14, 7, 3, 1], "due": True, "overdue": True}


def _module():
    return importlib.import_module("apps.instructions.migrations.0002_initial_data")


def _seed(using="default"):
    module = _module()
    module.seed(django_apps, SimpleNamespace(connection=connections[using]))


def _settings():
    return support.model("instructions.InstructionSettings")


def _basis():
    return support.model("instructions.InstructionBasisKind")


def test_migration_is_one_runpython_step_after_initial():
    """Данные установки — `0002_initial_data` от `0001_initial`, одна операция `RunPython(seed, noop)`."""
    module = _module()
    assert module.dependencies == [("instructions", "0001_initial")]
    assert len(module.operations) == 1
    import ast
    import pathlib

    path = support.BACKEND_DIR / "apps" / "instructions" / "migrations" / "0002_initial_data.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    assert any(isinstance(node, ast.FunctionDef) and node.name == "seed" for node in tree.body)


def test_seed_creates_settings_and_four_basis_kinds():
    """FR-701, NFR-729: установка создаёт `InstructionSettings(pk=1, 3 года, лестница)` и четыре вида основания с
    порядком 0–3."""
    _settings().objects.all().delete()
    _basis().objects.all().delete()
    _seed()

    row = _settings().objects.get(pk=1)
    assert row.retention_years == 3 and row.default_ladder == DEFAULT_LADDER
    kinds = list(_basis().objects.order_by("position"))
    assert [item.title for item in kinds] == list(BASIS)
    assert [item.position for item in kinds] == [0, 1, 2, 3]
    assert all(item.active for item in kinds)


def test_seed_is_idempotent_and_does_not_overwrite():
    """FR-701, NFR-729: повторный запуск не дублирует виды и не перезаписывает изменённые настройки."""
    _settings().objects.all().delete()
    _basis().objects.all().delete()
    _seed()
    _settings().objects.filter(pk=1).update(retention_years=7)
    _seed()

    assert _settings().objects.count() == 1
    assert _settings().objects.get(pk=1).retention_years == 7
    assert _basis().objects.count() == 4
    assert sorted(_basis().objects.values_list("title", flat=True)) == sorted(BASIS)


def test_settings_service_uses_seeded_defaults():
    """FR-709: служба настроек отдаёт умолчание лестницы из данных установки."""
    _settings().objects.all().delete()
    _seed()
    from apps.instructions.services import settings as service

    row = service.get()
    assert row.retention_years == 3 and row.default_ladder == DEFAULT_LADDER