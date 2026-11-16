"""T-8127: тесты галочки формы узла — чат отдела (FR-649, FR-643).

План: «Точки расширения ядра и шина событий» (запись точки `unit_form_parts`), «Виды чатов и создание» — чат
отдела. Контракт: CONTRACT-008, 3.1–3.2 (`UnitFormPart`, `render`, `on_saved`, свой savepoint и журнал
`apps.messenger.unit_form`), 3.4 (запись `messenger_chat` порядка 10), 4.4 (`without_messenger`), 5.7 (помощники),
12.6 (`[data-messenger-unit-field]`, `input[name="messenger_chat"]`, «Чат отдела создан»).

Шесть тестов T-8127, других нет. Код среза на уровне модуля не импортируется: модель — `support.model`, реестр
точек и службы — ленивыми импортами внутри тестов, поэтому `pytest --collect-only` проходит до появления кода
T-8205. Проверки идут через HTTP-форму узла (`/structure/new/`, `/structure/<id>/edit/`): так тест не зависит от
того, как запись точки хранит разметку. Секретов и ПДн нет: ФИО, адреса и телефоны не создаются.
"""
import contextlib
import logging
import re

import pytest

from tests import support
from tests import support_messenger as sm
from tests import support_org as org

pytestmark = pytest.mark.django_db

# поле галочки и её подписи (CONTRACT-008, 3.4, 12.6)
CHECKBOX = "messenger_chat"
LABEL = "Создадим чат для всего отдела"
CREATED = "Чат отдела создан"
# журнал сбоев полей формы узла — имя из плана среза 008 (CONTRACT-008, 3.2)
LOG = "apps.messenger.unit_form"
INPUT = re.compile(r'<input[^>]*name="messenger_chat"[^>]*>')


# --- помощники только этого файла ----------------------------------------------------------------------------------

def _Chat():
    return support.model("messenger.Chat")


def _Unit():
    return support.model("org.Unit")


def _field(html: str):
    """Тег галочки из HTML формы (`None` — поля нет); `name` в теге сверяется дословно."""
    match = INPUT.search(html)
    return match.group(0) if match else None


def _has_field(html: str) -> bool:
    return _field(html) is not None


def _part_div(html: str, key: str) -> bool:
    """Обёртка поля точки `unit_form_parts` в шаблоне `org/_slider.html`."""
    return f'data-unit-form-part="{key}"' in html


def _edit_html(client, unit) -> str:
    response = client.get(f"/structure/{unit.pk}/edit/")
    assert response.status_code == 200, f"форма узла {unit.pk}: статус {response.status_code}"
    return response.content.decode()


def _new_html(client, parent=None) -> str:
    response = client.get("/structure/new/", {"parent": (parent or org.root_unit()).pk})
    assert response.status_code == 200, f"форма нового узла: статус {response.status_code}"
    return response.content.decode()


def _post_new(client, name: str, *, checkbox: bool, parent=None):
    """`POST /structure/new/` с галочкой или без неё; узел из базы — по имени."""
    data = {"kind": "department", "name": name, "description": "",
            "parent": (parent if parent is not None else org.root_unit()).pk}
    if checkbox:
        data[CHECKBOX] = "on"
    response = client.post("/structure/new/", data)
    assert response.status_code == 302, f"создание узла: статус {response.status_code}"
    return _Unit().objects.get(name=name)


def _post_edit(client, unit, *, checkbox: bool):
    """`POST /structure/<id>/edit/` без переноса узла (ключа `parent` нет), с галочкой или без неё."""
    data = {"name": unit.name, "description": unit.description}
    if checkbox:
        data[CHECKBOX] = "on"
    return client.post(f"/structure/{unit.pk}/edit/", data)


def _chats(unit) -> list:
    """Чаты отдела этого узла (строки `kind="department"`)."""
    return list(_Chat().objects.filter(kind="department", unit_id=unit.pk))


def _part(key: str, order: int, html):
    """Запись точки со своим HTML: проверки порядка и пустой строки не зависят от мессенджера."""
    from apps.core import extensions

    return extensions.UnitFormPart(key=key, order=order, render=lambda request, unit, _html=html: _html,
                                   on_saved=lambda unit, post, actor, ip=None: None)


def _direct_parts(items: list) -> bool:
    """Точка хранит записи `UnitFormPart` (а не функции, возвращающие их): сверяется по самим записям."""
    return all(hasattr(item, "key") and hasattr(item, "render") for item in items)


def _all_parts(items: list) -> list:
    """Все записи точки, как их видит `org`: и части в реестре, и части из зарегистрированных функций."""
    return [item for item in items] if _direct_parts(items) else [part for item in items for part in item()]


def _registry_function(parts: list):
    """Замена регистрации для реестра, который хранит функции: тот же модуль, что и настоящая запись."""
    def registered_parts():
        return list(parts)

    registered_parts.__module__ = "apps.messenger.unit_form"
    return registered_parts


@contextlib.contextmanager
def _extra_parts(entries: list):
    """Дополнительные записи точки `unit_form_parts` на время блока; прежние возвращаются при выходе.

    Записи дописываются после настоящих: если форма соблюдает `order`, они всё равно встают по нему
    (CONTRACT-008, 3.2). Форма хранения точки (части или функции) видна по реестру.
    """
    from apps.core import extensions

    saved = extensions.registered("unit_form_parts")
    added = [*saved, *entries] if _direct_parts(saved) else [*saved, _registry_function(entries)]
    extensions._registry["unit_form_parts"][:] = added
    try:
        yield _all_parts(extensions.registered("unit_form_parts"))
    finally:
        extensions._registry["unit_form_parts"][:] = saved


@contextlib.contextmanager
def _broken_handler(error: str):
    """Запись `messenger_chat` с падающим `on_saved` на время блока (CONTRACT-008, 3.2).

    Подменяется только обработчик: ключ, порядок и `render` остаются настоящими, поэтому форма и галочка прежние.
    """
    from apps.core import extensions

    saved = extensions.registered("unit_form_parts")
    parts = _all_parts(saved)
    found = [part for part in parts if part.key == CHECKBOX]
    assert len(found) == 1, f"в точке `unit_form_parts` нет одной записи {CHECKBOX}: {parts!r}"
    real = found[0]

    def fail(unit, post, actor, ip=None):
        raise RuntimeError(error)

    broken = extensions.UnitFormPart(key=real.key, order=real.order, render=real.render, on_saved=fail)
    replaced = [broken if part is real else part for part in parts]
    extensions._registry["unit_form_parts"][:] = replaced if _direct_parts(saved) else [_registry_function(replaced)]
    try:
        yield
    finally:
        extensions._registry["unit_form_parts"][:] = saved


# --- FR-649: где галочка, порядок и пустая строка -----------------------------------------------------------------

def test_checkbox_only_for_department_not_team_or_root():
    """FR-649 (CONTRACT-008, 3.2, 3.4, 12.6): `render` записи `messenger_chat` рисует для отдела галочку
    `input[name="messenger_chat"][type="checkbox"]` с подписью «Создадим чат для всего отдела» и зацепкой
    `[data-messenger-unit-field]`; у команды и корневого узла поля нет. На создании узла, где `unit` ещё нет,
    `render` отдаёт пустую строку. Поля точки идут в порядке `order` (запись порядка 5 раньше `messenger_chat`
    порядка 10, хотя зарегистрирована позже), а пустая строка записи в разметку не попадает (порядок 20)."""
    admin = sm.as_admin()
    department = sm.unit("Отдел с галочкой")
    team = org.make_unit("Команда без галочки", kind="team")
    root = org.root_unit()

    html = _edit_html(admin.client, department)
    tag = _field(html)
    assert tag is not None, "у отдела нет поля messenger_chat"
    assert 'type="checkbox"' in tag, f"поле отдела — не галочка: {tag}"
    assert "data-messenger-unit-field" in html, "у галочки нет зацепки [data-messenger-unit-field]"
    assert LABEL in html, "у галочки нет подписи «Создадим чат для всего отдела»"
    assert _part_div(html, CHECKBOX), "поле чата не выведено как часть точки unit_form_parts"

    for unit in (team, root):
        page = _edit_html(admin.client, unit)
        assert not _has_field(page), f"галочка нарисована у узла kind={unit.kind} (root={unit.is_root})"
        assert "data-messenger-unit-field" not in page, "у команды или корня есть зацепка поля чата"

    new_form = _new_html(admin.client)
    assert not _has_field(new_form), "галочка нарисована при создании узла, где узла ещё нет"

    with _extra_parts([_part("early_part", 5, "<i>Раннее поле</i>"), _part("late_part", 20, "")]) as parts:
        assert len(parts) >= 3
        ordered = _edit_html(admin.client, department)
    assert _part_div(ordered, "early_part") and _part_div(ordered, CHECKBOX), "поля точки не выведены"
    assert ordered.index('data-unit-form-part="early_part"') < ordered.index(f'data-unit-form-part="{CHECKBOX}"'), \
        "поля точки выведены не в порядке order"
    assert not _part_div(ordered, "late_part"), "пустая строка записи выведена в форму"


def test_checkbox_checked_creates_chat_after_save():
    """FR-649 (CONTRACT-008, 3.2, 3.4, 5.4): галочка на создании узла зовёт `on_saved` после сохранения — у отдела
    появляется ровно один чат `kind="department"` с его номером и пустым `title` (название даёт `page.chat_title`
    через `unit_refs`); до сохранения, на GET формы, чата нет."""
    admin = sm.as_admin()
    unit = _post_new(admin.client, "Отдел в чате", checkbox=True)

    chats = _chats(unit)
    assert len(chats) == 1, f"чатов отдела после сохранения с галочкой: {len(chats)}"
    chat = chats[0]
    assert chat.kind == "department"
    assert chat.unit_id == unit.pk
    assert chat.title == "", "название отдела скопировано в Chat.title вместо unit_refs"


def test_second_save_shows_chat_created_instead_of_checkbox():
    """FR-649 (CONTRACT-008, 3.4, 5.4, 12.6): на правке отдела с чатом вместо галочки — «Чат отдела создан»;
    повторное сохранение с галочкой второго чата не создаёт (`department.create` идемпотентен по номеру узла), и
    надпись остаётся на месте."""
    admin = sm.as_admin()
    unit = _post_new(admin.client, "Отдел с чатом", checkbox=True)
    first = _chats(unit)
    assert len(first) == 1, f"чатов отдела: {len(first)}"

    html = _edit_html(admin.client, unit)
    assert CREATED in html, "на правке отдела с чатом нет надписи «Чат отдела создан»"
    assert not _has_field(html), "на правке отдела с чатом осталась галочка"
    assert LABEL not in html, "на правке отдела с чатом осталась подпись галочки"

    response = _post_edit(admin.client, unit, checkbox=True)
    assert response.status_code == 302, f"правка узла: статус {response.status_code}"
    chats = _chats(unit)
    assert len(chats) == 1, f"после повторного сохранения с галочкой чатов: {len(chats)}"
    assert chats[0].pk == first[0].pk, "второй чат отдела создан вместо прежнего"
    assert CREATED in _edit_html(admin.client, unit)


def test_unchecked_keeps_no_chat():
    """FR-649 (CONTRACT-008, 3.2): без галочки `on_saved` чат не создаёт ни на создании, ни на правке; пока чата
    нет, галочка остаётся в форме — её можно поставить следующим сохранением."""
    admin = sm.as_admin()
    unit = _post_new(admin.client, "Отдел без чата", checkbox=False)
    assert _chats(unit) == [], "чат создан без галочки"

    response = _post_edit(admin.client, unit, checkbox=False)
    assert response.status_code == 302, f"правка узла: статус {response.status_code}"
    assert _chats(unit) == [], "чат создан правкой узла без галочки"

    html = _edit_html(admin.client, unit)
    assert _has_field(html), "без чата галочки в форме нет — поставить нечем"
    assert CREATED not in html


# --- FR-649: сбой обработчика и выключенный мессенджер -------------------------------------------------------------

def test_handler_error_logged_and_unit_saved(caplog):
    """FR-649 (CONTRACT-008, 3.2): сбой `on_saved` идёт в собственный savepoint — узел сохраняется, форма цела и
    по-прежнему предлагает галочку, чата нет; предупреждение с ключом записи и текстом ошибки пишется в журнал
    `apps.messenger.unit_form`. После сбоя чат создаётся повторным сохранением с галочкой."""
    admin = sm.as_admin()
    error = "Сбой создания чата отдела"
    caplog.set_level(logging.WARNING, logger=LOG)

    with _broken_handler(error):
        unit = _post_new(admin.client, "Отдел со сбоем", checkbox=True)
        assert _chats(unit) == [], "чат создан, хотя обработчик упал"
        assert _has_field(_edit_html(admin.client, unit)), "после сбоя форма узла не предлагает галочку"

    records = [record for record in caplog.records if record.name == LOG and record.levelno == logging.WARNING]
    assert len(records) == 1, f"предупреждений в {LOG}: {len(records)}"
    message = records[0].getMessage()
    assert CHECKBOX in message, f"в предупреждении нет ключа записи: {message}"
    assert error in message, f"в предупреждении нет текста ошибки: {message}"

    response = _post_edit(admin.client, unit, checkbox=True)
    assert response.status_code == 302, f"повторная правка узла: статус {response.status_code}"
    chats = _chats(unit)
    assert len(chats) == 1, f"повторное сохранение с галочкой чат не создало: чатов {len(chats)}"


def test_without_messenger_form_has_no_field():
    """FR-643, FR-649 (CONTRACT-008, 3.2, 4.4): без регистраций мессенджера форма узла прежняя — ни на правке
    отдела, ни на создании узла нет галочки, обёртки части точки и зацепки `[data-messenger-unit-field]`; POST с
    полем `messenger_chat` узел сохраняет, но чата не делает."""
    admin = sm.as_admin()
    department = sm.unit("Отдел без мессенджера")

    with sm.without_messenger():
        html = _edit_html(admin.client, department)
        assert not _has_field(html), "без мессенджера в форме узла осталась галочка"
        assert "data-messenger-unit-field" not in html
        assert not _part_div(html, CHECKBOX)
        assert not _has_field(_new_html(admin.client)), "без мессенджера галочка есть на создании узла"

        unit = _post_new(admin.client, "Отдел без мессенджера 2", checkbox=True)
        assert _chats(unit) == [], "без мессенджера POST с полем messenger_chat создал чат"