"""Срез 010 «Поручения»: справочник видов основания (T-10103; FR-701).

`apps.instructions.services.basis` и страницы `/settings/instructions/basis/…` — CONTRACT-010, 6.2, 12.1.
Код среза импортируется внутри тестов: сбор проходит до появления моделей и служб.
"""
import pytest

from tests import support
from tests import support_instructions as ins

pytestmark = pytest.mark.django_db


def basis():
    from apps.instructions.services import basis as module
    return module


def _clear():
    """Убрать данные установки стенда, чтобы справочник начинался с пустого (тест изолирован)."""
    support.model("instructions.InstructionBasisKind").objects.all().delete()
    support.model("instructions.InstructionSettings").objects.all().delete()


def _err(call):
    from apps.instructions.texts import InstructionsError

    with pytest.raises(InstructionsError) as caught:
        call()
    return caught.value


def test_all_is_ordered_by_position_and_active_excludes_inactive():
    """FR-701: справочник отдаётся по `position`; `active()` не показывает выключенные виды."""
    _clear()
    late = ins.make_basis("Письмо", position=2)
    early = ins.make_basis("Приказ", position=0)
    off = ins.make_basis("Устное указание", position=1, active=False)

    rows = list(basis().all())
    assert [row.pk for row in rows] == [early.pk, off.pk, late.pk]
    assert [row.pk for row in basis().active()] == [early.pk, late.pk]


def test_add_checks_title_length_and_uniqueness():
    """FR-701: название вида 1–100 (`basis_title_range`), повтор — `basis_title_taken`; отказ у поля `title`."""
    _clear()
    for title in ("", "я" * 101):
        err = _err(lambda title=title: basis().add(support.make_admin(), title))
        assert (err.code, err.field) == ("basis_title_range", "title")
    basis().add(support.make_admin(), "Приказ")
    err = _err(lambda: basis().add(support.make_admin(), "Приказ"))
    assert (err.code, err.field) == ("basis_title_taken", "title")


def test_rename_and_delete_unused():
    """FR-701: вид переименовывается; неиспользованный удаляется из справочника."""
    _clear()
    actor = support.make_admin()
    kind = basis().add(actor, "Приказ")
    renamed = basis().rename(actor, kind, "Приказ отдела")
    assert renamed.title == "Приказ отдела"
    basis().delete(actor, renamed)
    assert not support.model("instructions.InstructionBasisKind").objects.filter(pk=kind.pk).exists()


def test_delete_used_deactivates_and_keeps_instructions():
    """FR-701: удаление использованного вида не удаляет поручения — вид выключается (`active=False`), новые
    _clear()
    поручения с ним отклоняются."""
    actor = support.make_admin()
    kind = ins.make_basis("Приказ")
    row = ins.make_instruction(basis=kind)
    basis().delete(actor, kind)
    kind.refresh_from_db()
    assert kind.active is False
    assert support.model("instructions.Instruction").objects.filter(pk=row.pk).exists()
    assert support.model("instructions.Instruction").objects.get(pk=row.pk).basis_kind_id == kind.pk


def test_one_document_can_basis_several_instructions():
    """FR-701: один документ-основание — у нескольких поручений."""
    _clear()
    kind = ins.make_basis("Протокол совещания")
    first = ins.make_instruction(title="Первое", basis=kind, basis_number="7", basis_date=ins._today())
    second = ins.make_instruction(title="Второе", basis=kind, basis_number="7", basis_date=ins._today())
    assert first.basis_kind_id == second.basis_kind_id == kind.pk


def test_settings_pages_are_admin_only_and_create_rename_delete(client):
    """NFR-729, CONTRACT-010, 6.1: справочник под `settings.portal`; рядовому — 403; создание, переименование и
    _clear()
    удаление через страницы."""
    actor = support.make_admin()
    support.login(client, actor)
    page = client.get("/settings/instructions/basis/")
    assert page.status_code == 200 and b'data-instructions-page="settings"' in page.content

    created = client.post("/settings/instructions/basis/", {"title": "Распоряжение"})
    kind = support.model("instructions.InstructionBasisKind").objects.get(title="Распоряжение")
    assert created.status_code == 302

    renamed = client.post(f"/settings/instructions/basis/{kind.pk}/", {"title": "Распоряжение главы"})
    kind.refresh_from_db()
    assert renamed.status_code == 302 and kind.title == "Распоряжение главы"

    second = client.post("/settings/instructions/basis/", {"title": "Письмо"})
    other = support.model("instructions.InstructionBasisKind").objects.get(title="Письмо")
    without = client.post(f"/settings/instructions/basis/{other.pk}/delete/", {})
    assert without.status_code == 200 and b"data-instructions-confirm" in without.content
    deleted = client.post(f"/settings/instructions/basis/{other.pk}/delete/", {"confirm": "1"})
    assert deleted.status_code == 302
    assert not support.model("instructions.InstructionBasisKind").objects.filter(pk=other.pk).exists()

    staff_client = support.logged_in(ins.staff_user())
    assert staff_client.get("/settings/instructions/basis/").status_code == 403
    assert staff_client.post("/settings/instructions/basis/", {"title": "Чужое"}).status_code == 403