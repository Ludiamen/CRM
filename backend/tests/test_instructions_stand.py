"""T-10008: сброс стенда поручений и проверка стенда (CONTRACT-010, 1.3).

Каркас Этапа 1: точка `stand_reset` регистрируется последней (и идёт первой при общем сбросе), `require_stand`
отказывает без `E2E_STAND=1`, `stand_reset()` до моделей T-10201 не падает. Полные проверки очистки, файлов и
данных установки добавляет T-10123 (Этап 2).
"""
import io

import pytest
from django.core.management.base import CommandError

REFUSAL = "Команда работает только на стенде приёмочных проходов (E2E_STAND=1); ничего не изменено."


@pytest.mark.django_db
def test_instructions_stand_reset_is_registered_last_after_tasks():
    """Решение 12 задач: `apps.instructions.stand.stand_reset` — последняя регистрация точки, сразу после задач;
    общий сброс (`e2e_reset_stand`) вызывает функции в обратном порядке, значит поручения идут первыми."""
    from apps.core import extensions
    from apps.instructions import stand as instructions_stand
    from apps.tasks import stand as tasks_stand

    funcs = extensions.registered("stand_reset")
    assert funcs, "нет зарегистрированных функций сброса стенда"
    assert funcs[-1] is instructions_stand.stand_reset
    assert funcs[-2] is tasks_stand.stand_reset


@pytest.mark.django_db
def test_stand_command_refused_without_e2e_stand(monkeypatch, django_assert_num_queries):
    """`require_stand()` без `E2E_STAND=1` (нет переменной, «0», пусто) бросает `CommandError(REFUSAL)` раньше
    любого запроса к базе; `REFUSAL` — текст контракта, своя копия; с `E2E_STAND=1` отказа нет."""
    from apps.instructions import stand

    assert stand.REFUSAL == REFUSAL
    for value in (None, "0", ""):
        if value is None:
            monkeypatch.delenv("E2E_STAND", raising=False)
        else:
            monkeypatch.setenv("E2E_STAND", value)
        with django_assert_num_queries(0):
            with pytest.raises(CommandError) as refused:
                stand.require_stand()
        assert str(refused.value) == REFUSAL, repr(value)
    monkeypatch.setenv("E2E_STAND", "1")
    assert stand.require_stand() is None


@pytest.mark.django_db
def test_seed_command_refused_without_e2e_stand(monkeypatch):
    """Команда `e2e_instructions_seed` проверяет стенд первой строкой: без `E2E_STAND=1` — отказ, вывод пуст."""
    from django.core.management import call_command

    monkeypatch.delenv("E2E_STAND", raising=False)
    out = io.StringIO()
    with pytest.raises(CommandError) as refused:
        call_command("e2e_instructions_seed", stdout=out)
    assert str(refused.value) == REFUSAL
    assert out.getvalue() == ""


@pytest.mark.django_db(databases=["default", "migrate"])
def test_stand_reset_is_safe_before_models():
    """Каркас T-10008 живёт до моделей T-10201: `stand_reset()` без таблиц поручений не падает и ничего не меняет."""
    from apps.instructions.stand import stand_reset

    assert stand_reset() is None