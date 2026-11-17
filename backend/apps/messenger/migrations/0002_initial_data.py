"""Данные установки мессенджера (срез 008, T-8201; PLAN-008, «Модель данных»; CONTRACT-008, 2.3).

Строка `MessengerSettings(pk=1, retention_years=3, general_chat_enabled=True)` — без «кто и когда менял» — и
«Общий чат» (`kind="general"`) создаются `get_or_create`, поэтому повторный запуск (в том числе со стенда) ничего
не дублирует и не перезаписывает уже стоящие значения: это данные установки, а не сброс настроек. «Общий чат»
держится уникальным индексом `messenger_chat_general_uniq`; создателя, узла и `pair_key` у него нет.
Обратная функция — `RunPython.noop`: обратного хода план не задаёт (решение контракта К7).
"""
from django.db import migrations
from django.utils import timezone

GENERAL_TITLE = "Общий чат"

# Списки зависимостей и операций — на уровне модуля: класс `Migration` берёт их как есть, а тесты среза сверяют
# состав по модулю (CONTRACT-008, 2.3).
dependencies = [
    ("core", "0002_initial_data"),      # роли установки
    ("messenger", "0001_initial"),      # таблицы мессенджера
]


def seed(apps, schema_editor, *, stand=False):
    """Вносит данные установки; `schema_editor` читается только как `.connection.alias`."""
    db = schema_editor.connection.alias
    MessengerSettings = apps.get_model("messenger", "MessengerSettings")
    Chat = apps.get_model("messenger", "Chat")
    MessengerSettings.objects.using(db).get_or_create(
        pk=1, defaults={"retention_years": 3, "general_chat_enabled": True})
    Chat.objects.using(db).get_or_create(
        kind="general", defaults={"title": GENERAL_TITLE, "created_at": timezone.now()})


operations = [
    migrations.RunPython(seed, migrations.RunPython.noop),
]


class Migration(migrations.Migration):

    dependencies = dependencies
    operations = operations