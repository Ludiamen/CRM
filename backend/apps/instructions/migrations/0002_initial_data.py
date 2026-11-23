"""Данные установки поручений (срез 010, T-10201; PLAN-010, «Данные установки `instructions 0002`»).

`InstructionSettings(pk=1, retention_years=3, default_ladder=…)` и четыре вида основания создаются
`get_or_create`, поэтому повторный запуск (в том числе со стенда) ничего не дублирует и не перезаписывает уже
стоящие значения. Обратная функция — `RunPython.noop`: обратного хода план не задаёт.
"""
from django.db import migrations

BASIS_KINDS = ("Приказ", "Протокол совещания", "Письмо", "Устное указание")
DEFAULT_LADDER = {"offsets": [30, 14, 7, 3, 1], "due": True, "overdue": True}

dependencies = [("instructions", "0001_initial")]


def seed(apps, schema_editor, *, stand=False):
    """Внести данные установки; `schema_editor` читается только как `.connection.alias`."""
    db = schema_editor.connection.alias
    Settings = apps.get_model("instructions", "InstructionSettings")
    BasisKind = apps.get_model("instructions", "InstructionBasisKind")
    Settings.objects.using(db).get_or_create(
        pk=1, defaults={"retention_years": 3, "default_ladder": dict(DEFAULT_LADDER)})
    for position, title in enumerate(BASIS_KINDS):
        BasisKind.objects.using(db).get_or_create(title=title, defaults={"position": position})


operations = [migrations.RunPython(seed, migrations.RunPython.noop)]


class Migration(migrations.Migration):

    dependencies = dependencies
    operations = operations