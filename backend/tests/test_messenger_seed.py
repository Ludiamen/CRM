"""T-8122: данные установки мессенджера (FR-651, 670).

План: «Модель данных» (строка `MessengerSettings`, «Общий чат», создание чатов) и «Риски» — миграция данных
установки. CONTRACT-008: 2.3 (миграция `messenger 0002_initial_data`, данные установки, `messenger_settings.get()`),
5.4, 5.7. Миграция данных выполняется на тестовой базе при её создании, поэтому каждый тест сначала возвращает базу
к виду «до миграции данных» своим `_clear()` (как `test_feed_seed.py`), а затем зовёт
`support_messenger.run_seed(using="default")`: строки создаются и читаются на соединении `default`, где работает тест.
`run_seed` передаёт `seed` объект `SimpleNamespace(connection=…)`, поэтому `schema_editor` читается только как
`.connection.alias` — любое другое обращение к нему упало бы. Код среза импортируется внутри функций: сбор
(`pytest --collect-only`) проходит до появления миграций и служб Этапа 3.
"""
import importlib
import inspect

import pytest
from django.db import migrations

from tests import support
from tests import support_messenger as sm

pytestmark = pytest.mark.django_db

GENERAL_TITLE = "Общий чат"


# --- помощники только этого файла -------------------------------------------------------------------------------

def _settings():
    return support.model("messenger.MessengerSettings")


def _chat():
    return support.model("messenger.Chat")


def _seed_module():
    """Модуль миграции данных `messenger 0002_initial_data` (имя начинается с цифры — через `importlib`)."""
    return importlib.import_module("apps.messenger.migrations.0002_initial_data")


def _clear() -> None:
    """«До миграции данных»: строки настройки и «Общего чата» нет (как `_clear()` в `test_feed_seed.py`).

    Строки удаляются в транзакции теста и возвращаются откатом, поэтому соседние тесты файла видят обычную базу
    после установки. Каскад чата (участники, отметки, сообщения, вложения) в тестовой базе пуст."""
    settings, chat = _settings(), _chat()
    settings.objects.all().delete()
    chat.objects.filter(kind="general").delete()
    assert not settings.objects.exists()
    assert not chat.objects.filter(kind="general").exists()


def _row_state():
    """Снимок данных установки: строка настройки и «Общий чат» (номера строк, значения)."""
    settings_rows = list(_settings().objects.order_by("pk").values_list(
        "pk", "retention_years", "general_chat_enabled", "updated_at", "updated_by_id"))
    general_rows = list(_chat().objects.filter(kind="general").order_by("pk").values_list(
        "pk", "title", "created_by_id", "unit_id", "pair_key"))
    return settings_rows, general_rows


# --- FR-651, 670: миграция данных создаёт строку настройки и «Общий чат» ----------------------------------------

def test_migration_creates_settings_three_years_and_general_on():
    """FR-651, 670 (CONTRACT-008, 2.3): миграция данных `messenger 0002_initial_data` — один `RunPython(seed, noop)`
    (решение К7: обратного хода нет); `seed(apps, schema_editor, *, stand=False)` создаёт ровно одну строку
    `MessengerSettings(pk=1, retention_years=3, general_chat_enabled=True)` — без «кто и когда менял» — и один
    «Общий чат»; `schema_editor` читается только как `.connection.alias`."""
    _clear()
    data = _seed_module()
    operations = [operation for operation in data.operations if isinstance(operation, migrations.RunPython)]
    assert len(operations) == 1, f"в миграции данных не один RunPython: {len(operations)}"
    assert operations[0].code is data.seed, "данные установки вносит функция seed модуля миграции"
    assert operations[0].reverse_code is migrations.RunPython.noop, "обратная функция — noop (решение К7)"

    signature = inspect.signature(data.seed)
    assert list(signature.parameters) == ["apps", "schema_editor", "stand"]
    assert signature.parameters["stand"].kind is inspect.Parameter.KEYWORD_ONLY
    assert signature.parameters["stand"].default is False

    sm.run_seed(using="default")

    settings_rows, general_rows = _row_state()
    assert settings_rows == [(1, 3, True, None, None)], \
        "строка настройки одна: pk=1, три года, «Общий чат» включён, менявшего нет"
    assert len(general_rows) == 1, f"«Общий чат» не один: {len(general_rows)}"
    assert general_rows[0][1] == GENERAL_TITLE
    assert _chat().objects.count() == 1, "других чатов миграция данных не создаёт"


# --- FR-651: повторный запуск ничего не дублирует ---------------------------------------------------------------

def test_seed_twice_does_not_duplicate():
    """FR-651 (CONTRACT-008, 2.3): данные установки вносятся `get_or_create` — повторный запуск `seed` (в том числе
    со стенда) не добавляет вторую строку настройки и второй «Общий чат» и не меняет уже стоящие значения
    (срок 7 лет и выключенный «Общий чат» остаются: миграция — данные установки, а не сброс настроек)."""
    _clear()
    sm.run_seed(using="default")
    settings_rows, general_rows = _row_state()
    assert settings_rows == [(1, 3, True, None, None)]
    assert len(general_rows) == 1
    general_pk = general_rows[0][0]

    _settings().objects.filter(pk=1).update(retention_years=7, general_chat_enabled=False)
    sm.run_seed(using="default")
    assert _row_state() == ([(1, 7, False, None, None)], general_rows), "повторный seed перезаписал данные установки"

    sm.run_seed(using="default", stand=True)
    assert _settings().objects.count() == 1, "повторный seed добавил строку настройки"
    assert list(_chat().objects.filter(kind="general").values_list("pk", flat=True)) == [general_pk], \
        "повторный seed добавил второй «Общий чат»"
    assert _row_state() == ([(1, 7, False, None, None)], general_rows)


# --- FR-651: название «Общего чата» и одна строка --------------------------------------------------------------

def test_general_chat_title_and_single_row():
    """FR-651 (план, «Виды чатов и создание»): «Общий чат» — одна строка `kind="general"` с названием «Общий чат»;
    создателя, узла, `pair_key` и последнего сообщения у неё нет, `created_at` заполнен; других чатов установка не
    создаёт, поэтому уникальный индекс по виду держит ровно одну строку."""
    _clear()
    sm.run_seed(using="default")

    chat = _chat()
    generals = list(chat.objects.filter(kind="general"))
    assert len(generals) == 1, f"«Общий чат» не один: {len(generals)}"
    row = generals[0]
    assert row.title == GENERAL_TITLE, f"название «Общего чата»: {row.title!r}"
    assert row.title.strip() == row.title and not row.title.isascii(), "название — русское, без пробелов по краям"
    assert row.created_by_id is None, "у «Общего чата» создателя нет"
    assert row.unit_id is None and row.pair_key == "", "«Общий чат» не отдел и не личный диалог"
    assert row.last_message_at is None, "сообщений в новом «Общем чате» нет"
    assert row.created_at is not None, "created_at обязателен"
    assert _chat().objects.count() == 1, "миграция данных создаёт только «Общий чат»"


# --- FR-670: messenger_settings.get() создаёт строку при отсутствии ---------------------------------------------

def test_settings_get_creates_row_when_missing():
    """FR-670 (CONTRACT-008, 2.3, 5.4): строки настройки нет — `messenger_settings.get()` создаёт её
    (`pk=1`, три года, «Общий чат» включён, менявшего нет) и возвращает; повторный вызов отдаёт ту же строку, а
    стоящие значения (7 лет, «Общий чат» выключен) читаются как есть, без сброса и без второй строки."""
    from apps.messenger.services import messenger_settings

    _clear()
    row = messenger_settings.get()
    assert (row.pk, row.retention_years, row.general_chat_enabled) == (1, 3, True)
    assert (row.updated_at, row.updated_by_id) == (None, None), "новая строка — без «кто и когда менял»"
    assert _settings().objects.count() == 1, "get() создал не одну строку настройки"

    again = messenger_settings.get()
    assert again.pk == row.pk
    assert _settings().objects.count() == 1, "повторный get() добавил строку настройки"

    _settings().objects.filter(pk=1).update(retention_years=7, general_chat_enabled=False)
    kept = messenger_settings.get()
    assert (kept.pk, kept.retention_years, kept.general_chat_enabled) == (1, 7, False), \
        "get() вернул не стоящую строку настройки"
    assert _settings().objects.count() == 1