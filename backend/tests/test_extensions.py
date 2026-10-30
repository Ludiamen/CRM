"""T-2116: границы модулей и точки расширения ядра (FR-120, FR-122, FR-123, FR-149; инвариант «модуль-приложение»).
Сценарии 3, 4, 13 спеки (роли по источникам, меню, календарь) — через точки расширения; CONTRACT-002 § 5."""
import datetime
import functools
import re

import pytest

from tests import support, support_org

pytestmark = pytest.mark.django_db

POINTS = ("menu_items", "role_sources", "role_usage", "audit_labels", "staff_directory",
          "card_sections", "day_marks", "home_notices", "stand_reset")
# четыре точки среза 003 (CONTRACT-003 § 3.2): в них `org` не регистрируется, их проверяет T-3132
POINTS_003 = ("unit_usage", "file_purposes", "mail_renderers", "login_links")
CORE_MENU_TITLES = ["Сотрудники", "Роли и права", "Журнал событий", "Настройки портала", "Безопасность и политика"]
ORG_IMPORT = re.compile(r"\bapps\.org\b|^\s*from\s+apps\s+import\s+[^#\n]*\borg\b", re.M)


def test_core_does_not_import_org():
    """Инвариант «модуль-приложение»: ни один файл `apps/core/**/*.py` не содержит `apps.org` и `from apps import org`; зависимость идёт только от `org` к ядру."""
    files = sorted((support.BACKEND_DIR / "apps" / "core").rglob("*.py"))
    assert files, "каталог apps/core не найден"
    offenders = [str(path.relative_to(support.BACKEND_DIR)) for path in files if ORG_IMPORT.search(path.read_text(encoding="utf-8"))]
    assert offenders == [], f"ядро ссылается на org: {offenders}"


def test_core_without_registered_extensions_behaves_as_slice_001(no_extensions):
    """Инвариант «модуль-приложение» (FR-120, FR-122): при пустых реестрах меню — только пункты ядра, роли узлов не действуют, `/staff/` и карточка без возможностей `org`."""
    from apps.core import extensions
    from apps.core.services import permissions

    assert all(extensions.registered(point) == [] for point in POINTS)
    role = support.factories.make_role(permissions=("audit.view", "roles.manage"))
    unit = support_org.make_unit()
    member = support.make_employee(full_name="Участник Узла")
    support_org.make_member(member, unit)
    support_org.make_unit_role(unit, role)
    assert permissions.permissions_of(member) == frozenset(), "роль узла без role_sources не действует"
    assert [item["title"] for item in permissions.menu_for(member)] == []

    admin = support.make_admin(full_name="Админ Админов")
    menu = permissions.menu_for(admin)
    assert [item["title"] for item in menu] == CORE_MENU_TITLES
    assert all(set(item) == {"url", "title", "icon", "order"} for item in menu), "menu_for отдаёт ровно url, title, icon, order"
    assert not [item for item in menu if item["url"].startswith(("/structure/", "/calendar/"))]

    client = support.logged_in(admin)
    listing = client.get("/staff/")
    assert listing.status_code == 200
    html = listing.content.decode()
    assert "Участник Узла" in html, "без уволенных видны все записи, как в срезе 001"
    presets = re.findall(r'<a\b[^>]*\bdata-preset="([^"]*)"', html)
    assert sorted(presets) == sorted(["", "dismissed", "all", "invited", "active", "blocked"]), (
        f"пресеты ядра без расширений (доп. 48): {presets}")
    assert 'name="unit"' not in html and 'data-preset="no_unit"' not in html and "Загрузить из таблицы" not in html

    card = client.get(f"/staff/{member.pk}/")
    assert card.status_code == 200
    body = card.content.decode()
    assert "data-card" in body and 'data-roles-group="unit"' not in body
    for name in ("units", "head", "subordinates"):
        assert f'data-field="{name}"' not in body, f"раздел карточки {name} принадлежит org"
    assert "Роль назначена узлу" not in body


def test_org_registers_all_nine_extension_points():
    """FR-120, FR-122, FR-123: `POINTS` — девять имён среза 002, четыре среза 003, два среза 004, два среза 005 и `home_body` среза 007 (всего восемнадцать); `org` при запуске регистрирует по функции в каждой из девяти точек среза 002, в `search_providers` («Подразделения») и не регистрируется в двух точках среза 004 и в `ticket_card_parts`; неизвестная точка — `ValueError`, повтор той же функции не дублируется, `empty()` очищает и возвращает прежнее, `clear()` очищает все точки."""
    from apps.core import extensions
    from tests.support_kb import POINTS_005
    from tests.support_feed import POINTS_007
    from tests.support_notify import POINTS_004

    assert tuple(extensions.POINTS) == POINTS + POINTS_003 + POINTS_004 + POINTS_005 + POINTS_007
    all_points = POINTS + POINTS_003 + POINTS_004 + POINTS_005 + POINTS_007
    for point in POINTS:
        funcs = extensions.registered(point)
        # в реестре могут быть и функции ядра; от `org` нужна хотя бы одна обычная функция модуля apps.org (доп. 39)
        org_funcs = [f for f in funcs
                     if getattr(f, "__module__", "").startswith("apps.org") and not isinstance(f, functools.partial)]
        assert org_funcs, f"org не зарегистрировал обычную функцию модуля apps.org в точке {point} (доп. 39)"
    for point in POINTS_004 + ("ticket_card_parts",):
        org_funcs = [f for f in extensions.registered(point) if getattr(f, "__module__", "").startswith("apps.org")]
        assert not org_funcs, f"org не должен регистрироваться в точке {point} среза 004 и в ticket_card_parts"
    org_search = [f for f in extensions.registered("search_providers")
                  if getattr(f, "__module__", "").startswith("apps.org") and not isinstance(f, functools.partial)]
    assert len(org_search) == 1, "org регистрирует ровно одну обычную функцию в search_providers («Подразделения»)"
    with pytest.raises(ValueError):
        extensions.register("no_such_point", lambda: None)
    with pytest.raises(ValueError):
        extensions.registered("no_such_point")
    before = {point: extensions.registered(point) for point in all_points}
    extensions.register("stand_reset", before["stand_reset"][0])
    assert extensions.registered("stand_reset") == before["stand_reset"], "повторная регистрация игнорируется"
    extensions.registered("stand_reset").clear()
    assert extensions.registered("stand_reset") == before["stand_reset"], "registered отдаёт копию"
    with extensions.empty():
        assert all(extensions.registered(point) == [] for point in all_points)
        for point in POINTS:
            extensions.register(point, before[point][0])
        assert all(extensions.registered(point) for point in POINTS)
        extensions.clear()
        assert all(extensions.registered(point) == [] for point in all_points), "clear() очищает все восемнадцать точек"
    # `stand_reset`: здесь проверяется только регистрация; очистку данных модуля проверяет стенд (T-2242)
    assert {point: extensions.registered(point) for point in all_points} == before


def test_org_public_interface_is_services_package():
    """FR-149: публичный интерфейс `org` — пакет `apps/org/services/` (`calendar.is_working_time`, `next_working_start`, `day_kind`, `structure.units_of`, `heads_of`); другие приложения модели `org` не импортируют."""
    import importlib
    import zoneinfo

    package = importlib.import_module("apps.org.services")
    assert hasattr(package, "__path__"), "services — пакет"
    calendar = importlib.import_module("apps.org.services.calendar")
    structure = importlib.import_module("apps.org.services.structure")
    for module, names in ((calendar, ("is_working_time", "next_working_start", "day_kind")), (structure, ("units_of", "heads_of"))):
        for name in names:
            assert callable(getattr(module, name)), f"{module.__name__}.{name}"

    moment = datetime.datetime(2026, 10, 7, 12, 0, tzinfo=zoneinfo.ZoneInfo("Europe/Moscow"))
    # по умолчанию (CONTRACT-002 § 2, § 4.5): пн–пт, 09:00–18:00 по Москве; 7 октября 2026 — среда, 10 октября — суббота
    assert datetime.date(2026, 10, 7).weekday() == 2 and datetime.date(2026, 10, 10).weekday() == 5
    assert calendar.is_working_time(moment) is True
    assert calendar.next_working_start(moment) == moment
    assert calendar.day_kind(datetime.date(2026, 10, 7)) == "work"
    saturday = datetime.datetime(2026, 10, 10, 12, 0, tzinfo=zoneinfo.ZoneInfo("Europe/Moscow"))
    assert calendar.is_working_time(saturday) is False
    assert calendar.day_kind(datetime.date(2026, 10, 10)) == "off"
    assert calendar.next_working_start(saturday) == datetime.datetime(2026, 10, 12, 9, 0, tzinfo=zoneinfo.ZoneInfo("Europe/Moscow"))
    with pytest.raises(ValueError):
        calendar.is_working_time(moment.replace(tzinfo=None))
    with pytest.raises(ValueError):
        calendar.next_working_start(moment.replace(tzinfo=None))

    unit = support_org.make_unit()
    person, outsider = support.make_employee(), support.make_employee()
    support_org.make_member(person, unit)
    assert len(structure.units_of(person)) == 1 and structure.units_of(outsider) == []
    assert len(structure.heads_of(person)) == 1 and structure.heads_of(outsider) == []

    others = [p for app in ("integrations",) for p in (support.BACKEND_DIR / "apps" / app).rglob("*.py")]
    offenders = [str(p) for p in others if re.search(r"apps\.org\.models|from\s+apps\.org\s+import\s+models", p.read_text(encoding="utf-8"))]
    assert offenders == [], "другие приложения не импортируют модели org"
