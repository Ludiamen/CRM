"""T-8126a: изменения ядра среза 008 (FR-649, FR-653, FR-662).

План: «Изменения кода прежних срезов» — строки `core/extensions.py` (точка `unit_form_parts`, датакласс
`UnitFormPart`), `core/models/files.py` и миграция `core/0011_storedfile_messenger_purpose.py`, новые
`core/services/text.py` (`render_plain`, `snippet`) и `core/services/thumbs.py` (`build`, `MAX_SIDE`),
`feed/services/text.py` и `feed/services/thumbs.py` — обёртки над ядром; «Модель данных» — «Ядро и прежние модули».
Контракт: CONTRACT-008, 1.4 (девятнадцатая точка), 2.1 (`Purpose.MESSENGER`, `core.services.text`,
`core.services.thumbs`, обёртки ленты), 3.1 (`UnitFormPart`).

Шесть тестов T-8126a, других нет. Код среза на уровне модуля не импортируется (правила для всех тестов среза):
`apps.core.*` и `apps.feed.*` берутся ленивыми импортами внутри тестов, модель — `support.model("core.StoredFile")`.
Сверка ядра с лентой идёт на одном входе: части `pieces` для ядра собраны в этом файле по контракту (группа 1 —
номер маркера, обработчик возвращает готовый экранированный HTML и повторяет разметку ленты), поэтому вывод ядра и
вывод обёртки ленты сравниваются дословно, включая экранирование, ссылки, абзацы и переносы. Секретов и ПДн нет:
адресов и телефонов в данных нет, в тексте — только `***`.
"""
import ast
import collections.abc
import dataclasses
import html
import inspect
import re
from typing import get_origin

import pytest
from django.utils.safestring import SafeString

from tests import support
from tests import support_feed as feed
from tests import support_org as org

pytestmark = pytest.mark.django_db

# восемнадцать точек прежних срезов, до точки мессенджера (CONTRACT-008, 1.4, 3.1)
POINTS_18 = ("menu_items", "role_sources", "role_usage", "audit_labels", "staff_directory", "card_sections",
             "day_marks", "home_notices", "stand_reset", "unit_usage", "file_purposes", "mail_renderers",
             "login_links", "notification_kinds", "top_bar_items", "search_providers",
             "ticket_card_parts", "home_body")
# шаблон маркера ленты `@[id]` (факт `feed/services/text.py`) и маркер «чат» для проверки частей `pieces`
MARKER = r"@\[([1-9]\d{0,8})\]"
CHAT_MARKER = r"@\[c([1-9]\d{0,8})\]"
P = inspect.Parameter


# --- помощники только этого файла ----------------------------------------------------------------------------------

def _params(func):
    """Имя, вид и значение по умолчанию каждого параметра подписи (как в `test_feed_core_changes.py`)."""
    return [(parameter.name, parameter.kind, parameter.default)
            for parameter in inspect.signature(func).parameters.values()]


def _pieces(people: dict[int, str]):
    """Части `pieces` для ядра: маркер чата остаётся текстом, маркер человека — разметка ленты (CONTRACT-008, 2.1).

    Обработчик читает свой номер как `group(1)`: группы считаются от шаблона самой части, поэтому маркер чата стоит
    первым и сдвигает группы маркера человека. Имя человека очищается `core.services.text.clean` — так же, как имя
    в обработчике ленты; без этого сверка разошлась бы на имени с невидимыми символами.
    """
    def escaped(match, link_staff):
        return html.escape(match.group(0), quote=True)

    def mention(match, link_staff):
        from apps.core.services import text as core_text

        person_id = int(match.group(1))
        name = people.get(person_id)
        if not name:
            return html.escape(match.group(0), quote=True)
        safe_name = html.escape(core_text.clean(str(name)), quote=True)
        if link_staff:
            return f'<a href="/staff/{person_id}/" data-mention="{person_id}">{safe_name}</a>'
        return f'<span data-mention="{person_id}">{safe_name}</span>'

    return [(re.compile(CHAT_MARKER), escaped), (re.compile(MARKER), mention)]


def _build(protected_root, module, data: bytes, stored_id: int) -> str:
    """Исходник в `incoming/<id>` и эскиз службой `module` (как `_build` в `test_feed_files_2.py`)."""
    source = protected_root / "incoming" / str(stored_id)
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(data)
    return module.build(source, stored_id)


def _image_size(path):
    """Размер картинки эскиза; файл обязан быть."""
    from PIL import Image

    assert path.is_file(), f"нет файла эскиза {path.name}"
    with Image.open(path) as image:
        image.load()
        return image.size


# --- core/extensions.py: девятнадцатая точка и датакласс UnitFormPart ----------------------------------------------

def test_point_unit_form_parts_is_nineteenth_and_dataclass_fields():
    """FR-649: `POINTS` ядра — девятнадцать имён, `unit_form_parts` последней, прежние восемнадцать в прежнем порядке,
    `_registry` содержит ключ на каждое имя; `UnitFormPart` — датакласс с полями `key`, `order`, `render`,
    `on_saved` без значений по умолчанию: `render(request, unit)` отдаёт HTML поля, `on_saved(unit, post, actor,
    ip=None)` вызывается после сохранения узла (CONTRACT-008, 3.1)."""
    from apps.core import extensions
    from tests.support_messenger import POINTS_008

    assert len(extensions.POINTS) == 19
    assert extensions.POINTS[-1] == "unit_form_parts"
    assert tuple(extensions.POINTS[18:]) == POINTS_008
    assert tuple(extensions.POINTS[:18]) == POINTS_18
    assert set(extensions._registry) == set(extensions.POINTS)

    part_type = extensions.UnitFormPart
    assert dataclasses.is_dataclass(part_type)
    assert [field.name for field in dataclasses.fields(part_type)] == ["key", "order", "render", "on_saved"]
    assert all(field.default is dataclasses.MISSING for field in dataclasses.fields(part_type))
    annotations = part_type.__annotations__
    assert annotations["key"] is str and annotations["order"] is int
    for name in ("render", "on_saved"):
        assert get_origin(annotations[name]) is collections.abc.Callable, f"{name}: {annotations[name]!r}"

    calls = []

    def render(request, unit):
        calls.append(("render", request, unit))
        return '<label class="form-check" for="unit-chat">Создадим чат для всего отдела</label>'

    def on_saved(unit, post, actor, ip=None):
        calls.append(("on_saved", unit, post, actor, ip))

    part = part_type(key="messenger_chat", order=10, render=render, on_saved=on_saved)
    assert (part.key, part.order, part.render, part.on_saved) == ("messenger_chat", 10, render, on_saved)
    request, unit, actor = object(), object(), object()
    assert part.render(request, unit) == \
        '<label class="form-check" for="unit-chat">Создадим чат для всего отдела</label>'
    assert calls == [("render", request, unit)]
    part.on_saved(unit, {"messenger_chat": "on"}, actor, ip="10.0.0.1")
    part.on_saved(unit, {}, actor)
    assert calls[-2:] == [("on_saved", unit, {"messenger_chat": "on"}, actor, "10.0.0.1"),
                          ("on_saved", unit, {}, actor, None)]


# --- core/models/files.py и миграция 0011 --------------------------------------------------------------------------

def test_purpose_messenger_choice_last_and_migration_0011_depends_on_0010():
    """FR-662, FR-693: `StoredFile.Purpose` — восемь значений, последнее `instruction` среза 010 (T-10111); `MESSENGER`
    («вложение сообщения чата») на прежнем месте, подписи прежние; `max_length` 16 и значение по умолчанию `photo`
    не менялись; миграция `core 0011_storedfile_messenger_purpose` — одна операция `AlterField` поля `purpose`,
    зависит от `0010`; строку с назначением `messenger` можно создать (CONTRACT-008, 2.1)."""
    from tests.support_messenger import PURPOSES_008

    StoredFile = support.model("core.StoredFile")
    assert StoredFile.Purpose.choices == [
        ("photo", "фото"), ("attachment", "вложение"), ("knowledge", "файл статьи"),
        ("lists", "файл записи списка"), ("feed", "вложение ленты"), ("messenger", "вложение сообщения чата"),
        ("task", "вложение задачи"), ("instruction", "вложение поручения")]
    assert tuple(StoredFile.Purpose.values) == PURPOSES_008
    assert StoredFile.Purpose.MESSENGER == "messenger" and list(StoredFile.Purpose.values)[-1] == "instruction"
    field = StoredFile._meta.get_field("purpose")
    assert field.max_length == 16 and field.default == "photo"
    assert len(StoredFile.Purpose.MESSENGER) <= field.max_length

    path = support.BACKEND_DIR / "apps" / "core" / "migrations" / "0011_storedfile_messenger_purpose.py"
    assert path.is_file(), "нет миграции core/0011_storedfile_messenger_purpose.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "Migration")
    assigned = {t.id: node.value for node in cls.body if isinstance(node, ast.Assign) for t in node.targets
                if isinstance(t, ast.Name)}
    assert ast.literal_eval(assigned["dependencies"]) == [("core", "0010_storedfile_feed_purpose")]
    operations = assigned["operations"].elts
    assert len(operations) == 1 and isinstance(operations[0], ast.Call) and operations[0].func.attr == "AlterField"
    keywords = {kw.arg: ast.literal_eval(kw.value) for kw in operations[0].keywords
                if kw.arg in ("model_name", "name")}
    assert keywords == {"model_name": "storedfile", "name": "purpose"}

    row = StoredFile.objects.create(purpose="messenger", owner=None, size=1, sha256="0" * 64,
                                    content_type="application/octet-stream", status="pending")
    row.refresh_from_db()
    assert row.purpose == "messenger"


# --- core/services/text.py: вывод и отрывок ------------------------------------------------------------------------

def test_core_render_plain_matches_feed_output_for_same_input():
    """FR-653 (NFR-703): `core.services.text.render_plain(text, pieces, *, link_staff)` на одном входе даёт
    дословно тот же HTML, что `feed.services.text.render_plain(text, people, link_staff)`: экранирование, ссылки
    `http`/`https`/`mailto`, абзацы и переносы, маркеры частей `pieces` (обработчик читает свой номер как
    `group(1)`); `mark_safe` — только в ядре (CONTRACT-008, 2.1)."""
    from apps.core.services import text as core_text
    from apps.feed.services import text as feed_text

    # у частей `pieces` контракт значение по умолчанию не задаёт: сверяются имена и вид параметров
    assert [(parameter.name, parameter.kind) for parameter in
            inspect.signature(core_text.render_plain).parameters.values()] == [
        ("text", P.POSITIONAL_OR_KEYWORD), ("pieces", P.POSITIONAL_OR_KEYWORD), ("link_staff", P.KEYWORD_ONLY)]
    people = {7: "Иванов Иван", 8: '<b>Иван</b> "x" & <script>alert(1)</script>', 9: "\u202aИван\u2069"}
    texts = (
        "Просто текст",
        "",
        "  пробелы  и\tтабуляция\r\nи перенос ",
        "один\nдва\n\nтри\n  \n\nчетыре",
        '<b>жирный</b> & "кавычки" \'апостроф\'',
        "javascript:alert(1) и ftp://example.test/file и www.example.test",
        "Смотри https://example.test/a?x=1&b=2. Дальше",
        "(см. https://example.test/wiki/Тест_(слово)).",
        "Почта mailto:ivanov@example.test, точка.",
        "до https://example.test/" + "a" * 2030 + " после",
        "Привет @[7] и ещё раз @[7]!",
        "Неизвестный @[99] и кривой @[0] @[01] @[1234567890] @[-5] @[abc] @[]",
        "Смесь @[c4] @[7] https://example.test/a <i>x</i>",
        "Имя с разметкой @[8] и с невидимыми @[9]",
        "\u202aдо\u2066 @[9] после\x00\x07",
        '<script>alert(1)</script> @[7] \'"><img src=x onerror=alert(1)>',
    )
    for text in texts:
        for link_staff in (False, True):
            mine = core_text.render_plain(text, _pieces(people), link_staff=link_staff)
            theirs = feed_text.render_plain(text, people, link_staff)
            assert isinstance(mine, SafeString) and isinstance(theirs, SafeString)
            assert str(mine) == str(theirs), (repr(text), link_staff)

    quiet = ('<b>жирный</b> & https://example.test/a?x=1&b=2\n\nвторой', "а\nб", "")
    for text in quiet:
        assert str(core_text.render_plain(text, (), link_staff=False)) == str(
            feed_text.render_plain(text, {}, False)), repr(text)

    core_source = (support.BACKEND_DIR / "apps" / "core" / "services" / "text.py").read_text(encoding="utf-8")
    assert core_source.count("mark_safe(") == 1, "mark_safe в ядре не один раз"


def test_core_snippet_matches_feed_snippet_and_expand_hook():
    """FR-653 (NFR-703): `core.services.text.snippet(text, limit, *, expand=None)` даёт тот же отрывок, что
    `feed.services.text.snippet(text, limit, people)`, на всех пределах; `expand` получает уже очищенный текст и
    раскрывает имена упоминаний; без `expand` маркеры остаются текстом, разметки нет (CONTRACT-008, 2.1)."""
    from apps.core.services import text as core_text
    from apps.feed.services import text as feed_text

    assert _params(core_text.snippet) == [
        ("text", P.POSITIONAL_OR_KEYWORD, P.empty), ("limit", P.POSITIONAL_OR_KEYWORD, P.empty),
        ("expand", P.KEYWORD_ONLY, None)]
    people = {7: "Иванов Иван", 9: "Пётр Петров"}
    marker = re.compile(MARKER)

    def expand(cleaned: str) -> str:
        def replace(match):
            name = people.get(int(match.group(1)))
            return "@" + name if name is not None else match.group(0)

        return marker.sub(replace, cleaned)

    texts = (
        "Привет  @[7]   вот\n\nтекст\tдальше",
        "Ссылка https://example.test/a тут и @[9].",
        "Неизвестный @[99] и @[0] остаются",
        " ".join(["слово", "длинноеслово", "а", "ещё", "пятнадцатибуквенное"] * 80),
        "<b>текст</b> @[7]",
        "",
    )
    for text in texts:
        for limit in (0, 1, 6, 60, 100, 300, 4000):
            assert core_text.snippet(text, limit, expand=expand) == feed_text.snippet(text, limit, people), (
                repr(text), limit)

    assert core_text.snippet("Привет @[7]  вот", 100) == "Привет @[7] вот"
    assert core_text.snippet("<a>текст</a>", 100) == "<a>текст</a>"
    assert "<a" not in core_text.snippet("Привет @[7]  вот", 100, expand=expand)

    seen = []

    def recording(cleaned: str) -> str:
        seen.append(cleaned)
        return expand(cleaned)

    core_text.snippet("до\u202a @[7] после\x00", 100, expand=recording)
    assert seen == ["до @[7] после"]


# --- core/services/thumbs.py: путь и размер эскиза -----------------------------------------------------------------

def test_core_thumbs_build_matches_feed_path_and_size(protected_root):
    """FR-662: `core.services.thumbs.build(source_path, stored_id)` и обёртка ленты дают один и тот же путь
    `attachments/thumbs/<id>.jpg` (WebP — у картинки с прозрачностью) и один и тот же размер картинки, не больше
    `MAX_SIDE` = 1280 px по большей стороне; не картинка — пустая строка и файла нет (CONTRACT-008, 2.1)."""
    from apps.core.services import thumbs as core_thumbs
    from apps.feed.services import thumbs as feed_thumbs

    assert core_thumbs.MAX_SIDE == feed_thumbs.MAX_SIDE == 1280
    samples = (
        ("jpeg", org.jpeg_bytes(3000, 2000), "jpg"),
        ("png_alpha", feed.images()["png_alpha"], "webp"),
        ("gif", feed.images()["gif_frames"], "jpg"),
        ("small", org.jpeg_bytes(400, 300), "jpg"),
        ("text", b"just text, not an image", ""),
    )
    for shift, (label, data, suffix) in enumerate(samples):
        core_id, feed_id = 9500 + shift, 9600 + shift
        core_path = _build(protected_root, core_thumbs, data, core_id)
        feed_path = _build(protected_root, feed_thumbs, data, feed_id)
        assert core_path == (f"attachments/thumbs/{core_id}.{suffix}" if suffix else ""), label
        assert feed_path == (f"attachments/thumbs/{feed_id}.{suffix}" if suffix else ""), label
        if not suffix:
            assert not list((protected_root / "attachments" / "thumbs").glob(f"{core_id}.*")), label
            continue
        core_size = _image_size(protected_root / core_path)
        feed_size = _image_size(protected_root / feed_path)
        assert core_size == feed_size, label
        assert max(core_size) <= core_thumbs.MAX_SIDE, label
    assert _image_size(protected_root / "attachments/thumbs/9500.jpg") == (1280, 853)
    assert _image_size(protected_root / "attachments/thumbs/9503.jpg") == (400, 300)


# --- обёртки ленты --------------------------------------------------------------------------------------------------

def test_feed_wrappers_keep_names_signatures_and_behavior():
    """FR-653, FR-662: `feed.services.text.render_plain(text, people, link_staff)`,
    `snippet(text, limit, people=None)`,
    `feed.services.thumbs.build(source_path, stored_id)` и `MAX_SIDE` — прежние имена, подписи и поведение; `build` и
    `MAX_SIDE` берутся из ядра, обёртка текста своего `mark_safe` не держит (CONTRACT-008, 2.1)."""
    from apps.core.services import text as core_text
    from apps.core.services import thumbs as core_thumbs
    from apps.feed.services import text as feed_text
    from apps.feed.services import thumbs as feed_thumbs

    assert _params(feed_text.render_plain) == [
        ("text", P.POSITIONAL_OR_KEYWORD, P.empty), ("people", P.POSITIONAL_OR_KEYWORD, P.empty),
        ("link_staff", P.POSITIONAL_OR_KEYWORD, P.empty)]
    assert _params(feed_text.snippet) == [
        ("text", P.POSITIONAL_OR_KEYWORD, P.empty), ("limit", P.POSITIONAL_OR_KEYWORD, P.empty),
        ("people", P.POSITIONAL_OR_KEYWORD, None)]
    assert _params(feed_thumbs.build) == [
        ("source_path", P.POSITIONAL_OR_KEYWORD, P.empty), ("stored_id", P.POSITIONAL_OR_KEYWORD, P.empty)]
    assert feed_thumbs.MAX_SIDE == core_thumbs.MAX_SIDE == 1280
    assert feed_thumbs.build is core_thumbs.build, "эскизы ленты строит не ядро"
    assert callable(feed_text.render_plain) and callable(feed_text.snippet)
    wrapper = (support.BACKEND_DIR / "apps" / "feed" / "services" / "text.py").read_text(encoding="utf-8")
    assert "mark_safe(" not in wrapper, "обёртка ленты держит свой mark_safe"
    assert not re.search(r"from\s+django\.utils\.safestring\s+import\s+[^\n]*\bmark_safe\b", wrapper)

    staff = "Иванов Иван"
    linked = feed_text.render_plain("Привет @[7]!", {7: staff}, True)
    assert isinstance(linked, SafeString)
    assert '<a href="/staff/7/" data-mention="7">Иванов Иван</a>' in str(linked)
    assert str(linked).startswith("<p>") and str(linked).endswith("</p>")
    span = str(feed_text.render_plain("Привет @[7]!", {7: staff}, False))
    assert '<span data-mention="7">Иванов Иван</span>' in span and "<a " not in span
    unknown = str(feed_text.render_plain("Привет @[99]!", {}, True))
    assert "@[99]" in unknown and "data-mention" not in unknown
    escaped = str(feed_text.render_plain('<b>жирный</b> & "кавычки"', {}, False))
    assert "&lt;b&gt;жирный&lt;/b&gt;" in escaped and "<b>" not in escaped
    url = str(feed_text.render_plain("Смотри https://example.test/a?x=1&b=2 тут", {}, False))
    assert '<a href="https://example.test/a?x=1&amp;b=2" target="_blank" rel="noopener noreferrer">' in url
    paragraphs = str(feed_text.render_plain("один\nдва\n\nтри", {}, False))
    assert paragraphs.count("<p>") == 2 and "<br>" in paragraphs

    assert feed_text.snippet("Привет  @[7]   вот\n\nтекст", 100, {7: staff}) == "Привет @Иванов Иван вот текст"
    assert feed_text.snippet("слово дальше", 6, {}) == "слово…"
    plain = feed_text.snippet("Привет @[7] и @[7]", 100, {7: staff})
    assert plain == "Привет @Иванов Иван и @Иванов Иван"
    assert "<a" not in plain and "@[7]" not in plain
