"""T-5130: границы модулей среза 005 (FR-426, FR-432, FR-433, FR-445). Сценарии спеки — «Комментарий к объекту любого
модуля», «Карточка заявки», «Модуль выключен», «Сквозной поиск».

`knowledge` и `search` подключаются к ядру и прежним модулям только точками расширения, шиной и публичными службами
(CONTRACT-005, 1.1, 3.1, 4.2, 4.3, 9.2, 16); без регистраций `knowledge` (`support_kb.without_knowledge`) карточка
заявки, каталог уведомлений, поиск и меню работают как после среза 004. Имена кода среза импортируются внутри тестов."""
import ast
import re

import pytest
from django.db.models import CharField

from tests import support, support_kb
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import model

pytestmark = pytest.mark.django_db

POINTS_15 = ("menu_items", "role_sources", "role_usage", "audit_labels", "staff_directory", "card_sections",
             "day_marks", "home_notices", "stand_reset", "unit_usage", "file_purposes", "mail_renderers", "login_links",
             "notification_kinds", "top_bar_items")
POINTS_17 = POINTS_15 + ("search_providers", "ticket_card_parts")
MODULE_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]*(\.[A-Za-z_][A-Za-z0-9_]*)+")
PUBLIC = "apps.servicedesk.services.public"
KB_MODELS = ("Article", "ArticleVersion", "Rubric", "Tag", "ArticleFile", "TicketLink", "RubricSubscription",
             "KnowledgeSettings")
KB_PARTS = ("kb-articles", "kb-from-ticket", "kb-link-tool")
WORD = "поддержка"


# --- разбор импортов (как в test_notify_boundaries.py) ----------------------------------------------------------

def _targets(source: str, package: list[str], *, with_strings: bool = True) -> set[str]:
    """Абсолютные имена, от которых зависит файл (`ast`): `import a.b`; `from a.b import c` — имя `a.b.c`; относительные
    импорты; `import_module("…")`/`__import__("…")`; при `with_strings` — ещё строка-путь модуля целиком вне докстрингов."""
    tree = ast.parse(source)
    docstrings = set()
    for parent in ast.walk(tree):
        if isinstance(parent, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and parent.body:
            first = parent.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstrings.add(id(first.value))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package[: len(package) - (node.level - 1)]
                module = ".".join(base + (node.module.split(".") if node.module else []))
            else:
                module = node.module or ""
            for alias in node.names:
                found.add(module if alias.name == "*" else f"{module}.{alias.name}")
        elif isinstance(node, ast.Call):
            func = node.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name in ("import_module", "__import__") and node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str):
                found.add(node.args[0].value)
        elif with_strings and isinstance(node, ast.Constant) and isinstance(node.value, str) \
                and id(node) not in docstrings and MODULE_PATH.fullmatch(node.value):
            found.add(node.value)
    return found


def _under(name: str, root: str) -> bool:
    return name == root or name.startswith(root + ".")


def _scan(*parts: str, bad, with_strings: bool = True) -> list[str]:
    root = support.BACKEND_DIR.joinpath(*parts)
    files = sorted(root.rglob("*.py"))
    assert files, f"нет исходников в {root}"
    offenders = []
    for path in files:
        rel = path.relative_to(support.BACKEND_DIR).with_suffix("")
        hits = sorted(n for n in _targets(path.read_text(encoding="utf-8"), list(rel.parts[:-1]),
                                          with_strings=with_strings) if bad(n))
        if hits:
            offenders.append(f"{path.relative_to(support.BACKEND_DIR)}: {hits}")
    return offenders


def _check_scanner(bad, package: list[str], found: tuple[str, ...], clean: tuple[str, ...], *, with_strings=True) -> None:
    """Сам разбор находит нарушения на образцах и не срабатывает на чистых (иначе пустой список ничего не доказывает)."""
    for sample in found:
        assert any(bad(n) for n in _targets(sample, package, with_strings=with_strings)), f"разбор не нашёл: {sample}"
    for sample in clean:
        assert not any(bad(n) for n in _targets(sample, package, with_strings=with_strings)), f"ложное срабатывание: {sample}"


def _read(*parts: str) -> str:
    path = support.BACKEND_DIR.joinpath(*parts)
    assert path.is_file(), f"нет файла {path.relative_to(support.BACKEND_DIR)}"
    return path.read_text(encoding="utf-8")


# --- помощники данных ---------------------------------------------------------------------------------------

def _reader_in_queue(*codes: str):
    """Участник очереди (видит её заявки); `codes` — права базы знаний или прочие. Возвращает (пользователь, очередь)."""
    queue = sd.make_queue()
    user = support.make_with_permissions(*[c for c in codes if not c.startswith("knowledge.")])
    org.make_member(user, queue.unit)
    kb_codes = [c for c in codes if c.startswith("knowledge.")]
    if kb_codes:
        support_kb.grant(user, *kb_codes)
    return user, queue


def _two_tickets(queue):
    """Открытая заявка и закрытая заявка с решением."""
    from django.utils import timezone

    opened = sd.make_ticket(queue=queue)
    closed = sd.make_ticket(queue=queue, kind="closed", closed_at=timezone.now(), resolution="Заменили кабель питания")
    return opened, closed


def _card_html(user, ticket) -> str:
    response = support.logged_in(user).get(f"/tickets/{ticket.number}/")
    assert response.status_code == 200, f"карточка #{ticket.number}: {response.status_code}"
    return response.content.decode()


# --- FR-426, FR-432, FR-445: границы импортов (план «Сверка с конституцией», «Проверка») ------------------------------

def test_knowledge_does_not_import_models_of_servicedesk_org_notify():
    """FR-426, FR-432, FR-445: в `apps/knowledge/**` нет импорта моделей `servicedesk`, `org`, `notify`; связь со
    статьёй у заявки — число (`TicketLink.ticket_number`), а ни одно поле связи моделей `knowledge` не ведёт в другое
    приложение, кроме `core`; сам разбор находит нарушения на образцах."""
    from django.apps import apps

    def bad(name):
        return any(_under(name, f"apps.{app}.models") for app in ("servicedesk", "org", "notify"))

    _check_scanner(bad, ["apps", "knowledge", "services"],
                   ("from apps.org.models import Unit", "import apps.notify.models", "from apps.servicedesk import models",
                    "from ...org.models import Unit", "x = 'apps.servicedesk.models.Ticket'"),
                   ('"""apps.org.models в докстринге"""\nimport os', "from apps.org.services import calendar",
                    "from apps.core.models import User", "from ..models import Article"))
    assert _scan("apps", "knowledge", bad=bad) == []
    config = apps.get_app_config("knowledge")
    models = {m.__name__: m for m in config.get_models()}
    assert set(KB_MODELS) <= set(models), f"в приложении нет моделей: {sorted(set(KB_MODELS) - set(models))}"
    for name, kb_model in models.items():
        for field in kb_model._meta.get_fields():
            if field.is_relation and not field.auto_created:
                assert field.related_model._meta.app_label in ("core", "knowledge"), \
                    f"{name}.{field.name} ведёт в приложение {field.related_model._meta.app_label}"
    ticket_number = models["TicketLink"]._meta.get_field("ticket_number")
    assert not ticket_number.is_relation, "номер заявки в связи — число, а не внешний ключ"


def test_knowledge_calls_servicedesk_only_through_services_public():
    """FR-432: из `apps.servicedesk` пакет `knowledge` импортирует только `apps.servicedesk.services.public`, и только с
    проверкой `apps.is_installed("apps.servicedesk")` (CONTRACT-005, 4.2); любая другая зависимость — нарушение."""

    def bad(name):
        return _under(name, "apps.servicedesk") and not _under(name, PUBLIC)

    _check_scanner(bad, ["apps", "knowledge", "services"],
                   ("from apps.servicedesk.services import tickets", "import apps.servicedesk.models",
                    "from apps.servicedesk import extensions", "from ...servicedesk.services.access import visible_tickets",
                    "import importlib\nimportlib.import_module('apps.servicedesk.views')"),
                   ("from apps.servicedesk.services import public", "from apps.servicedesk.services.public import briefs",
                    "from ...servicedesk.services.public import ticket_brief"), with_strings=False)
    assert _scan("apps", "knowledge", bad=bad, with_strings=False) == []
    guard = re.compile(r"is_installed\(\s*[\"']apps\.servicedesk[\"']\s*\)")
    sources = {p: p.read_text(encoding="utf-8") for p in sorted(support.BACKEND_DIR.joinpath("apps", "knowledge").rglob("*.py"))}
    assert any(guard.search(text) for text in sources.values()), \
        'нигде в `apps/knowledge` нет проверки `apps.is_installed("apps.servicedesk")` перед вызовом `public`'


def test_search_app_does_not_import_any_module_app():
    """FR-445: `apps/search/**` не импортирует приложения-поставщики (`servicedesk`, `org`, `notify`, `knowledge`) и
    собирает группы только из точки `search_providers` (CONTRACT-005, 9.2)."""

    def bad(name):
        return any(_under(name, f"apps.{app}") for app in ("servicedesk", "org", "notify", "knowledge"))

    _check_scanner(bad, ["apps", "search"],
                   ("from apps.knowledge.services import search", "import apps.servicedesk", "from apps import org",
                    "from .. import notify", "x = 'apps.org.services.search_provider'"),
                   ('"""apps.knowledge в докстринге"""\nimport os', "from apps.core import extensions",
                    "from apps.core.extensions import ParsedQuery"))
    assert _scan("apps", "search", bad=bad) == []
    services = _read("apps", "search", "services.py")
    assert re.search(r"registered\(\s*[\"']search_providers[\"']\s*\)", services), \
        "`search.services` не обходит `extensions.registered(\"search_providers\")`"


def test_servicedesk_org_core_do_not_import_knowledge_or_search():
    """FR-432, FR-433, FR-445: ни один файл `apps/servicedesk/**`, `apps/org/**`, `apps/core/**` не импортирует
    `apps.knowledge` и `apps.search` (ни `import`, ни `import_module`, ни строка-путь вне докстрингов)."""

    def bad(name):
        return _under(name, "apps.knowledge") or _under(name, "apps.search")

    _check_scanner(bad, ["apps", "core", "services"],
                   ("from apps.knowledge.services import access", "import apps.search", "from apps import knowledge",
                    "from ...search import services", "import importlib\nimportlib.import_module('apps.knowledge.tasks')",
                    "x = 'apps.search.services'"),
                   ('"""apps.knowledge в докстринге"""\n# apps.search в комментарии\nimport os',
                    "from apps.core import extensions", "event = 'knowledge.article_published'"))
    offenders = []
    for app in ("servicedesk", "org", "core"):
        offenders += _scan("apps", app, bad=bad)
    assert offenders == [], f"модуль знает о knowledge или search: {offenders}"


# --- FR-432, FR-433: карточка заявки без записей knowledge (CONTRACT-005, 4.3) ----------------------------------------

def test_ticket_card_without_knowledge_has_no_parts_and_renders(caplog):
    """FR-432, FR-433: пока `knowledge` включён, закрытая заявка с решением несёт три части (`kb-articles`,
    `kb-from-ticket`, `kb-link-tool`); без его регистраций точка `ticket_card_parts` пуста, карточки открытой и закрытой
    заявок рисуются (200, поля, форма комментария, «Открыть заново»), оболочек `data-card-part` нет, ошибок в журнале нет."""
    from apps.core import extensions

    user, queue = _reader_in_queue("servicedesk.all", "knowledge.edit")
    opened, closed = _two_tickets(queue)
    with_kb = _card_html(user, closed)
    for part in KB_PARTS:
        assert f'data-card-part="{part}"' in with_kb, f"при включённом модуле нет части {part}"
    with caplog.at_level("DEBUG"):
        with support_kb.without_knowledge():
            assert extensions.registered("ticket_card_parts") == [], "точка не пуста без knowledge"
            html_open = _card_html(user, opened)
            html_closed = _card_html(user, closed)
    for html in (html_open, html_closed):
        assert "data-card-part" not in html and "data-part-kind" not in html, "оболочка части без записей точки"
        assert "data-card-fields" in html and "data-card-feed" in html, "карточка потеряла поля или ленту"
        assert 'data-form="ticket-comment"' in html, "пропала форма внутреннего комментария"
    assert 'data-action="ticket-reopen"' in html_closed, "у закрытой заявки пропала кнопка «Открыть заново»"
    assert [r for r in caplog.records if r.name.startswith("apps.servicedesk") and r.levelno >= 40] == []


def test_ticket_card_without_knowledge_has_no_article_button_section_or_link_tool():
    """FR-432, FR-433: без регистраций `knowledge` в карточке нет кнопки «Статья из решения», раздела «Статьи» (с формой
    привязки) и кнопки «Ссылка на статью»; при включённом модуле у сотрудника с правом «Редактирование» они есть."""
    user, queue = _reader_in_queue("servicedesk.all", "knowledge.edit")
    opened, closed = _two_tickets(queue)
    with_kb = _card_html(user, closed)
    for hook in ('data-action="kb-from-ticket"', 'data-section="kb-articles"', 'data-form="kb-link"',
                 'data-action="kb-link-tool"'):
        assert hook in with_kb, f"при включённом модуле нет {hook}"
    with support_kb.without_knowledge():
        pages = (_card_html(user, opened), _card_html(user, closed))
    for html in pages:
        for hook in ('data-action="kb-from-ticket"', 'data-form="kb-from-ticket"', 'data-section="kb-articles"',
                     'data-form="kb-link"', 'data-action="kb-link-tool"', 'data-kb-pick-results'):
            assert hook not in html, f"без knowledge в карточке есть {hook}"
        for text in ("Статья из решения", "Ссылка на статью", "Привязать статью"):
            assert text not in html, f"без knowledge в карточке есть надпись «{text}»"


# --- FR-433: каталог уведомлений, поиск, меню без knowledge ---------------------------------------------------------

def test_notification_catalog_without_knowledge_has_no_knowledge_kinds():
    """FR-433: без регистраций `knowledge` каталог видов уведомлений — прежние восемь видов трёх модулей, видов с кодом
    `knowledge.*` и модулем «База знаний» нет, проверка каталога проходит; с включённым модулем добавляются ровно три."""
    from apps.notify.services import kinds

    full = {kind.code: kind for kind in kinds.catalog()}
    added = {"knowledge.comment_on_my_article", "knowledge.my_article_changed", "knowledge.rubric_subscription"}
    assert added <= set(full), "при включённом модуле в каталоге нет видов knowledge"
    with support_kb.without_knowledge():
        kinds.check()
        rest = kinds.catalog()
    assert [k.code for k in rest if k.code.startswith("knowledge.") or k.module == "База знаний"] == []
    assert {k.code for k in rest} == set(full) - added
    assert len(rest) == 8, "прежних видов срезов 003 и 004 — восемь"


def test_search_without_knowledge_has_no_articles_group():
    """FR-433, FR-445: без регистраций `knowledge` поиск не знает группы «Статьи»: среди поставщиков и групп её нет, на
    странице `/search/` нет `section[data-search-group="articles"]`, подсчёт группы — пустой ответ; с модулем группа
    с опубликованной статьёй есть."""
    from apps.core import extensions
    from apps.search import parse, services

    user = support.make_with_permissions("staff.view")
    article = support_kb.make_published(title=f"{WORD.capitalize()} и сеть")
    parsed = parse.parse(WORD)
    group_codes = [g.key for g in services.page(user, parsed)]
    assert "articles" in group_codes, "при включённом модуле нет группы «Статьи»"
    client = support.logged_in(user)
    assert 'data-search-group="articles"' in client.get(f"/search/?q={WORD}").content.decode()
    with support_kb.without_knowledge():
        assert "articles" not in [p.key for f in extensions.registered("search_providers") for p in f()]
        assert "articles" not in [g.key for g in services.page(user, parsed)]
        assert services.more(user, parsed, "articles", 0) == []
        assert services.count(user, parsed, "articles") is None
        response = client.get(f"/search/?q={WORD}")
        counted = client.get(f"/search/count/?q={WORD}&group=articles")
    assert response.status_code == 200 and 'data-search-group="articles"' not in response.content.decode()
    assert f"/kb/{article.pk}/" not in response.content.decode()
    assert counted.status_code == 200 and counted.content.decode().strip() == "", "подсчёт неизвестной группы — пустой ответ"


def test_search_without_knowledge_still_returns_tickets_staff_units():
    """FR-433, FR-445: без регистраций `knowledge` поиск по слову отдаёт остальные три группы в порядке `order`
    (заявки, сотрудники, подразделения) со строками `/tickets/<n>/`, `/staff/<id>/`, `/structure/<id>/`."""
    from apps.search import parse, services
    from apps.servicedesk.services import tickets
    from tests import factories

    queue = sd.make_queue()
    sd.configure_servicedesk(domains=["corp.test"], default_queue=queue)
    user = support.make_with_permissions("staff.view")
    org.make_member(user, queue.unit)
    created = tickets.create(channel=tickets.MAIL, subject=f"{WORD.capitalize()} принтера", text="Принтер не печатает",
                             requester_email=factories.new_email("req"), inbound_id=sd.make_inbound().pk)
    colleague = support.make_employee(full_name="Иванова Ольга Петровна", position=WORD.capitalize())
    unit = org.make_unit(WORD.capitalize())
    support_kb.make_published(title=f"{WORD.capitalize()} и сеть")
    with support_kb.without_knowledge():
        groups = services.page(user, parse.parse(WORD))
    assert [g.key for g in groups] == ["tickets", "staff", "units"]
    by_group = {g.key: [row.url for row in g.rows] for g in groups}
    assert f"/tickets/{created.ticket.number}/" in by_group["tickets"]
    assert f"/staff/{colleague.pk}/" in by_group["staff"]
    assert f"/structure/{unit.pk}/" in by_group["units"]


def test_menu_without_knowledge_has_no_knowledge_item():
    """FR-433: без регистраций `knowledge` в меню нет пункта «База знаний» (`/kb/`) ни в `menu_for`, ни в разметке
    страницы; прежние пункты остаются; с включённым модулем пункт есть у любого сотрудника (порядок 7)."""
    from apps.core.services import permissions

    admin = support.make_admin()
    item = [m for m in permissions.menu_for(admin) if m["title"] == "База знаний"]
    assert item and item[0]["url"] == "/kb/" and item[0]["order"] == 7, "при включённом модуле нет пункта «База знаний»"
    client = support.logged_in(admin)
    assert 'href="/kb/"' in client.get("/").content.decode()
    with support_kb.without_knowledge():
        menu = permissions.menu_for(admin)
        html = client.get("/").content.decode()
    assert [m for m in menu if m["title"] == "База знаний" or m["url"].startswith("/kb/")] == []
    assert any(m["url"] == "/staff/" for m in menu), "пропали прежние пункты меню"
    assert 'href="/kb/"' not in html and "База знаний" not in html.split('id="main-menu"', 1)[-1].split("</nav>", 1)[0]


# --- FR-432, FR-445: точки расширения (CONTRACT-005, 3.1) -----------------------------------------------------------

def test_points_has_seventeen_names():
    """FR-445: `POINTS` ядра — ровно семнадцать имён в порядке контракта (пятнадцать прежних и две новые); `_registry`
    содержит ключ на каждое имя."""
    from apps.core import extensions

    assert tuple(extensions.POINTS) == POINTS_17
    assert len(extensions.POINTS) == 17
    assert set(extensions._registry) == set(POINTS_17)


def test_points_new_names_search_providers_and_ticket_card_parts_are_last_two():
    """FR-432, FR-445: прежние пятнадцать имён и их порядок не изменились, новые `search_providers` и `ticket_card_parts`
    стоят последними (в таком порядке); в `ticket_card_parts` регистрируется только `knowledge`, `servicedesk` её
    не регистрирует; неизвестная точка отказывает `ValueError`."""
    from apps.core import extensions

    assert tuple(extensions.POINTS[:15]) == POINTS_15
    assert tuple(extensions.POINTS[-2:]) == ("search_providers", "ticket_card_parts") == support_kb.POINTS_005
    parts = extensions.registered("ticket_card_parts")
    assert parts, "knowledge не зарегистрировал части карточки"
    assert all(getattr(f, "__module__", "").startswith("apps.knowledge") for f in parts), \
        f"в ticket_card_parts регистрируется не только knowledge: {[f.__module__ for f in parts]}"
    with pytest.raises(ValueError):
        extensions.register("no_such_point", lambda: [])
    with pytest.raises(ValueError):
        extensions.registered("no_such_point")


# --- FR-426: комментарий ядра (CONTRACT-005, 2.1, 3.4) ----------------------------------------------------------

def test_core_comment_has_no_foreign_key_to_module_objects():
    """FR-426: у `core.Comment` один внешний ключ — автор (`core.User`); связей с объектами модулей нет (ни внешнего
    ключа, ни `ContentType`), поля — `object_ref`, `author`, `text`, `created_at`, пометки «удалён» нет."""
    comment = model("core.Comment")
    meta = comment._meta
    names = {f.name for f in meta.get_fields() if not f.auto_created or f.concrete}
    assert names == {"id", "object_ref", "author", "text", "created_at"}, f"поля комментария: {sorted(names)}"
    relations = [f for f in meta.get_fields() if f.is_relation]
    assert [f.name for f in relations] == ["author"], f"связи комментария: {[f.name for f in relations]}"
    assert relations[0].related_model._meta.label == "core.User"
    assert meta.default_permissions == ()


def test_core_comment_object_ref_is_string_in_app_object_pk_format():
    """FR-426: `object_ref` — `CharField(64)` вида `<приложение>.<объект>:<pk>`; комментарий статьи, созданный службой
    `knowledge`, хранит `knowledge.article:<id>`."""
    from apps.knowledge.services import articles

    field = model("core.Comment")._meta.get_field("object_ref")
    assert isinstance(field, CharField) and field.max_length == 64
    article = support_kb.make_published()
    reader = support_kb.as_reader().user
    created = articles.add_comment(reader, article.pk, "Спасибо, помогло")
    stored = model("core.Comment").objects.get(pk=created.pk)
    assert stored.object_ref == f"knowledge.article:{article.pk}"
    assert re.fullmatch(r"[a-z_]+\.[a-z_]+:\d+", stored.object_ref)


def test_comment_attaches_to_object_of_any_module_by_ref():
    """FR-426: `core.comments.add` крепит комментарий к любой непустой ссылке (статья, заявка, подразделение, объект
    будущего модуля) без проверки существования; `list_for` каждой ссылки отдаёт только её комментарии, старые первыми."""
    from apps.core.services import comments

    author = support.make_employee()
    refs = ("knowledge.article:15", "servicedesk.ticket:7", "org.unit:3", "future.thing:99")
    for ref in refs:
        comments.add(author, ref, f"Первый для {ref}")
        comments.add(author, ref, f"Второй для {ref}")
    for ref in refs:
        found = comments.list_for(ref)
        assert [c.text for c in found] == [f"Первый для {ref}", f"Второй для {ref}"]
        assert {c.object_ref for c in found} == {ref}
        assert {c.author_id for c in found} == {author.pk}
    assert model("core.Comment").objects.count() == 2 * len(refs)


def test_comment_is_deleted_with_object_by_delete_for_ref():
    """FR-426: при удалении статьи навсегда (`articles.purge`) исчезают её комментарии и только они — комментарии другой
    статьи и объектов других модулей остаются; `comments.delete_for(ref)` возвращает число удалённых."""
    from apps.core.services import comments
    from apps.knowledge.services import articles

    manager = support_kb.as_manager().user
    doomed = support_kb.make_trashed()
    other = support_kb.make_published()
    author = support.make_employee()
    support_kb.make_comment(doomed, author, "К удаляемой 1")
    support_kb.make_comment(doomed, author, "К удаляемой 2")
    kept = support_kb.make_comment(other, author, "К другой статье")
    foreign = comments.add(author, "servicedesk.ticket:1", "К заявке")
    ref = f"knowledge.article:{doomed.pk}"
    assert model("core.Comment").objects.filter(object_ref=ref).count() == 2
    articles.purge(doomed, manager)
    left = set(model("core.Comment").objects.values_list("pk", flat=True))
    assert left == {kept.pk, foreign.pk}, "вместе со статьёй должны уйти ровно её комментарии"
    assert not model("knowledge.Article").objects.filter(pk=doomed.pk).exists()
    comments.add(author, "future.thing:5", "Один")
    comments.add(author, "future.thing:5", "Два")
    assert comments.delete_for("future.thing:5") == 2
    assert model("core.Comment").objects.filter(object_ref="future.thing:5").count() == 0
    assert model("core.Comment").objects.filter(pk=foreign.pk).exists()


# --- FR-445: поставщики поиска (CONTRACT-005, 3.3, 4.4, 4.5, 9.3) ------------------------------------------------------

def test_search_providers_registered_by_servicedesk_knowledge_core_org_in_order():
    """FR-445: в `search_providers` по одной функции от `servicedesk`, `knowledge`, ядра и `org`; записи — `SearchProvider`
    с ключами, названиями и `order` из 9.3 (заявки 10, статьи 20, сотрудники 30, подразделения 40); `search.services.providers`
    отдаёт группы в этом порядке."""
    from apps.core import extensions
    from apps.search import services

    functions = extensions.registered("search_providers")
    owners = {"servicedesk": "tickets", "knowledge": "articles", "core": "staff", "org": "units"}
    expected = {"tickets": ("Заявки", 10), "articles": ("Статьи", 20), "staff": ("Сотрудники", 30),
                "units": ("Подразделения", 40)}
    records = {}
    for app, group in owners.items():
        mine = [f for f in functions if getattr(f, "__module__", "").startswith(f"apps.{app}")]
        assert len(mine) == 1, f"у {app} в search_providers {len(mine)} регистраций, ждали одну"
        listed = mine[0]()
        assert len(listed) == 1 and isinstance(listed[0], extensions.SearchProvider)
        records[listed[0].key] = listed[0]
        assert listed[0].key == group, f"ключ группы {app}: {listed[0].key}"
    for group, (title, order) in expected.items():
        assert (records[group].title, records[group].order) == (title, order), f"группа {group}"
        assert callable(records[group].search) and callable(records[group].count) and callable(records[group].available)
    user = support.make_with_permissions("staff.view", "servicedesk.all")
    support_kb.grant(user, "knowledge.edit")
    assert [p.key for p in services.providers(user)] == ["tickets", "articles", "staff", "units"]
    assert [p.title for p in services.providers(user)] == ["Заявки", "Статьи", "Сотрудники", "Подразделения"]
