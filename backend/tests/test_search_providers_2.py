"""T-5127: поставщики сквозного поиска «Сотрудники» (ядро) и «Подразделения» (`org`), отключение базы знаний
(FR-441, FR-443, FR-444, FR-445). Сценарии 10 и 4 спеки (поиск; справочник сотрудников)."""
import itertools
import re

import pytest

from tests import support, support_kb, support_org
from tests.support_kb import email_of, phone_of

pytestmark = pytest.mark.django_db


# --- помощники файла ---------------------------------------------------------------------------------

def _parsed(q: str):
    """Запрос в виде `ParsedQuery` по правилам разбора плана (слова `\\w+`, короче 2 знаков отбрасываются, до 8)."""
    from apps.core.extensions import ParsedQuery

    words = [w for w in re.findall(r"\w+", q.strip().lower()) if len(w) >= 2][:8]
    return ParsedQuery(words=words, number=None, raw=" & ".join(f"{w}:*" for w in words), hint="")


def _provider(key: str):
    """Запись поставщика с этим ключом из точки `search_providers` (как собирает `search.services`)."""
    from apps.core import extensions

    for func in extensions.registered("search_providers"):
        for record in func():
            if record.key == key:
                return record
    pytest.fail(f"поставщик {key!r} не зарегистрирован в точке search_providers")


_VIEWER_NUMBERS = itertools.count(1)


def _viewer():
    """Сотрудник с правом `staff.view` и больше ни с какими; почта фиксированная (без случайной части и без слова
    «example»), чтобы смотрящий не попадал в выдачу по словам и цифрам запросов."""
    local = "viewer" + "x" * next(_VIEWER_NUMBERS)
    return support.make_with_permissions("staff.view", totp=False, email=email_of(local, "viewer.test"))


def _person(**fields):
    fields.setdefault("full_name", "Тестов Тест Тестович")
    return support.make_employee(totp=False, **fields)


def _rows(key: str, viewer, q: str, limit: int = 100, offset: int = 0):
    return _provider(key).search(viewer, _parsed(q), limit, offset)


def _titles(key: str, viewer, q: str) -> list[str]:
    return [row.title for row in _rows(key, viewer, q)]


def _group_keys(viewer, q: str) -> list[str]:
    from apps.search import services

    return [group.key for group in services.page(viewer, _parsed(q))]


# --- право на группу «Сотрудники» (FR-444) -----------------------------------------------------------

def test_staff_group_requires_staff_view():
    """FR-444: группа «Сотрудники» доступна только с правом `staff.view`; без права выдачи нет, как будто
    сотрудников не существует."""
    _person(full_name="Кузнецов Артём", position="Кладовщик")
    provider = _provider("staff")
    no_rights = support.make_with_permissions(totp=False)
    viewer = _viewer()
    assert provider.available(no_rights) is False
    assert provider.available(viewer) is True
    assert "staff" not in _group_keys(no_rights, "кузнецов")
    assert "staff" in _group_keys(viewer, "кузнецов")


def test_accounts_manage_alone_does_not_give_staff_group():
    """FR-444: право `accounts.manage` одно группу «Сотрудники» не даёт (оно открывает справочник, но не выдачу)."""
    _person(full_name="Кузнецов Артём", position="Кладовщик")
    manager = support.make_with_permissions("accounts.manage", totp=False)
    assert _provider("staff").available(manager) is False
    assert "staff" not in _group_keys(manager, "кузнецов")


def test_staff_only_active_accounts_invited_blocked_dismissed_hidden():
    """FR-444: в группе только действующие учётные записи; приглашённые, заблокированные и уволенные не видны."""
    for state, name in (("active", "Действующий"), ("invited", "Приглашённый"), ("blocked", "Заблокированный"),
                        ("dismissed", "Уволенный")):
        _person(full_name=f"{name} Складов", position="Кладовщик", state=state)
    found = _titles("staff", _viewer(), "кладовщик")
    assert found == ["Действующий Складов"]
    assert _provider("staff").count(_viewer(), _parsed("кладовщик")) == (1, False)


# --- совпадение: поля справочника, почта, телефон, подразделение (FR-443) ----------------------------------

def test_staff_found_by_each_directory_field():
    """FR-443: сотрудник находится по каждому из шести полей справочника: ФИО, должность, почта, телефон,
    внутренний телефон, место работы — и только по своему полю."""
    viewer = _viewer()
    by_name = _person(full_name="Зайцев Мирон")
    by_position = _person(full_name="Белов Олег", position="Метролог")
    by_email = _person(full_name="Орлов Лев", email=email_of("orlovlev"))
    by_phone = _person(full_name="Волков Ян", phone=phone_of("+7", "913", "555", "01", "02"))
    by_internal = _person(full_name="Лисин Макар", internal_phone="7351")
    by_workplace = _person(full_name="Мышкин Глеб", workplace="Мансарда")
    cases = [("зайцев", by_name), ("метролог", by_position), ("orlovlev", by_email), ("79135550102", by_phone),
             ("7351", by_internal), ("мансарда", by_workplace)]
    for query, person in cases:
        assert _titles("staff", viewer, query) == [person.full_name], query


def test_staff_found_by_full_email_and_by_part():
    """FR-443: адрес почты находится целиком и по частям (до и после `@`, части через `.`, `_`, `-`)."""
    viewer = _viewer()
    owner = _person(full_name="Громов Тимур", email=email_of("petr.gromov-ml", "mail.example.test"))
    _person(full_name="Другой Человек", email=email_of("other", "mail.example.test"))
    for query in (email_of("petr.gromov-ml", "mail.example.test"), "petr.gromov-ml", "gromov", "petr gromov"):
        assert _titles("staff", viewer, query) == [owner.full_name], query
    assert len(_titles("staff", viewer, "example")) == 2


def test_staff_found_by_phone_digits_and_with_plus7_or_8():
    """FR-443: телефон находится как есть и только цифрами — целиком и по началу номера; номер, записанный с `+7`
    и с `8`, находится по цифрам."""
    viewer = _viewer()
    plus7 = _person(full_name="Соколов Ян", phone="+7 912 345-67-89")
    eight = _person(full_name="Дроздов Ян", phone="8 (913) 111-22-33")
    assert _titles("staff", viewer, "79123456789") == [plus7.full_name]
    assert _titles("staff", viewer, "7912") == [plus7.full_name]
    assert _titles("staff", viewer, "89131112233") == [eight.full_name]
    assert _titles("staff", viewer, "8913") == [eight.full_name]
    # п. 17.47: номер, записанный с +7, находится и по цифрам с ведущей 8 (вариант в векторе)
    assert _titles("staff", viewer, "89123456789") == [plus7.full_name]
    assert _titles("staff", viewer, "8912") == [plus7.full_name]
    assert _titles("staff", viewer, "+79123456789") == [plus7.full_name]
    assert _titles("staff", viewer, "70000000000") == []


def test_staff_found_by_unit_name_via_staff_directory():
    """FR-443 (план «Сотрудники», условие записи `staff_directory.search`): сотрудник находится по названию своего
    подразделения; без членства в нём он по этому слову не находится."""
    viewer = _viewer()
    unit = support_org.make_unit("Склад Гамма")
    member = _person(full_name="Ершов Павел")
    support_org.make_member(member, unit)
    _person(full_name="Жданов Игорь")
    assert _titles("staff", viewer, "гамма") == [member.full_name]
    assert _titles("staff", viewer, "склад гамма") == [member.full_name]


def test_staff_stop_word_does_not_empty_results():
    """FR-443: слово запроса, дающее пустой `tsquery` (стоп-слово «на»), отбрасывается, а не обнуляет выдачу."""
    viewer = _viewer()
    person = _person(full_name="Иванов Пётр")
    assert _titles("staff", viewer, "иванов") == [person.full_name]
    assert _titles("staff", viewer, "на иванов") == [person.full_name]
    assert _titles("staff", viewer, "иванов на") == [person.full_name]


def test_staff_matches_by_word_start_all_words_required():
    """FR-443: каждое слово ищется по началу слова, все слова должны совпасть (И); середина слова не совпадает."""
    viewer = _viewer()
    person = _person(full_name="Кузнецов Артём Игоревич", position="Монтажник")
    other = _person(full_name="Кузьмин Борис Петрович", position="Электрик")
    assert _titles("staff", viewer, "кузн арт") == [person.full_name]
    assert _titles("staff", viewer, "артём монтажник") == [person.full_name]
    assert _titles("staff", viewer, "кузн электрик") == []
    assert _titles("staff", viewer, "нецов") == []
    assert sorted(_titles("staff", viewer, "куз")) == sorted([person.full_name, other.full_name])


def test_staff_e_yo_equivalence():
    """FR-443: «е» и «ё» равны в запросе и в данных."""
    viewer = _viewer()
    with_yo = _person(full_name="Пётр Алёхин")
    with_ye = _person(full_name="Семен Лебедев")
    assert _titles("staff", viewer, "петр алехин") == [with_yo.full_name]
    assert _titles("staff", viewer, "пётр") == [with_yo.full_name]
    assert _titles("staff", viewer, "семён") == [with_ye.full_name]
    assert _titles("staff", viewer, "семен") == [with_ye.full_name]


def test_staff_ordered_by_full_name():
    """FR-443: порядок строк — по ФИО, при равных ФИО — по номеру записи; число группы точное и не «больше
    потолка»."""
    viewer = _viewer()
    yablokov = _person(full_name="Яблоков Антон", position="Грузчик")
    abramov = _person(full_name="Абрамов Борис", position="Грузчик")
    twin_first = _person(full_name="Мышкин Глеб", position="Грузчик")
    twin_second = _person(full_name="Мышкин Глеб", position="Грузчик")
    rows = _rows("staff", viewer, "грузчик")
    assert [r.title for r in rows] == ["Абрамов Борис", "Мышкин Глеб", "Мышкин Глеб", "Яблоков Антон"]
    assert [r.url for r in rows] == [f"/staff/{p.pk}/" for p in (abramov, twin_first, twin_second, yablokov)]
    assert _provider("staff").count(viewer, _parsed("грузчик")) == (4, False)
    assert [r.title for r in _provider("staff").search(viewer, _parsed("грузчик"), 2, 1)] == [
        "Мышкин Глеб", "Мышкин Глеб"]


def test_staff_without_org_uses_core_fields_only():
    """FR-443, FR-445: без записи `staff_directory` (модуль `org` не поставил поиск по подразделениям) ищутся только
    поля ядра; по названию подразделения сотрудник не находится, по полям — находится."""
    viewer = _viewer()
    unit = support_org.make_unit("Склад Гамма")
    member = _person(full_name="Ершов Павел", position="Кладовщик")
    support_org.make_member(member, unit)
    assert _titles("staff", viewer, "гамма") == [member.full_name]
    with support_kb.without_registrations("staff_directory"):
        assert _titles("staff", viewer, "гамма") == []
        assert _titles("staff", viewer, "кладовщик") == [member.full_name]
        assert _provider("staff").count(viewer, _parsed("гамма")) == (0, False)


def test_staff_row_has_name_position_unit_photo_and_card_url():
    """FR-441: строка сотрудника — ФИО, должность, подразделение, фото, адрес карточки `/staff/<id>/`; шаблон строки
    `search/rows/_staff.html`, в контексте ключи `unit` и `photo` (`files.photo_url(user, 96)`)."""
    from apps.core.services import files

    viewer = _viewer()
    unit = support_org.make_unit("Склад Гамма")
    person = _person(full_name="Ершов Павел", position="Кладовщик")
    support_org.make_member(person, unit)
    (row,) = _rows("staff", viewer, "ершов")
    assert row.title == "Ершов Павел"
    assert row.subtitle == "Кладовщик"
    assert row.url == f"/staff/{person.pk}/"
    assert row.template == "search/rows/_staff.html"
    assert "unit" in row.context and "photo" in row.context
    assert row.context["unit"] == "Склад Гамма"
    assert row.context["photo"] == files.photo_url(type(person).objects.get(pk=person.pk), 96)


# --- «Подразделения» (FR-441, FR-443, FR-444) --------------------------------------------------------------

def test_units_group_requires_staff_view():
    """FR-444: группа «Подразделения» доступна только с правом `staff.view`; `accounts.manage` одно её не даёт."""
    support_org.make_unit("Снабжение")
    provider = _provider("units")
    no_rights = support.make_with_permissions(totp=False)
    manager = support.make_with_permissions("accounts.manage", totp=False)
    viewer = _viewer()
    assert provider.available(no_rights) is False
    assert provider.available(manager) is False
    assert provider.available(viewer) is True
    assert "units" not in _group_keys(no_rights, "снабжение")
    assert "units" in _group_keys(viewer, "снабжение")


def test_units_found_by_name_and_ordered_by_name():
    """FR-443: подразделения находятся по названию (начало слова, все слова) и идут по названию; число точное."""
    viewer = _viewer()
    south = support_org.make_unit("Снабжение юг")
    east = support_org.make_unit("Снабжение восток")
    procurement = support_org.make_unit("Закупки и снабжение")
    support_org.make_unit("Бухгалтерия")
    rows = _rows("units", viewer, "снабжен")
    assert [r.title for r in rows] == ["Закупки и снабжение", "Снабжение восток", "Снабжение юг"]
    assert [r.url for r in rows] == [f"/structure/{u.pk}/" for u in (procurement, east, south)]
    assert _titles("units", viewer, "снабжен юг") == ["Снабжение юг"]
    assert _provider("units").count(viewer, _parsed("снабжен")) == (3, False)


def test_unit_row_has_name_ancestor_path_and_structure_url():
    """FR-441: строка подразделения — название, путь (названия предков через « / », у корня пусто), адрес узла
    `/structure/<id>/`."""
    viewer = _viewer()
    root = support_org.root_unit()
    department = support_org.make_unit("Снабжение", parent=root)
    store = support_org.make_unit("Склады юг", parent=department)
    (dep_row,) = _rows("units", viewer, "снабжение")
    assert (dep_row.title, dep_row.subtitle, dep_row.url) == ("Снабжение", root.name, f"/structure/{department.pk}/")
    (store_row,) = _rows("units", viewer, "склады")
    assert store_row.title == "Склады юг"
    assert store_row.subtitle == f"{root.name} / Снабжение"
    assert store_row.url == f"/structure/{store.pk}/"
    root_rows = [r for r in _rows("units", viewer, "отдел") if r.url == f"/structure/{root.pk}/"]
    assert len(root_rows) == 1
    assert root_rows[0].subtitle == ""


def test_unit_e_yo_equivalence():
    """FR-443: «е» и «ё» равны и в названии подразделения, и в запросе."""
    viewer = _viewer()
    with_yo = support_org.make_unit("Объект Чёрный")
    with_ye = support_org.make_unit("Склад Зеленый")
    assert _titles("units", viewer, "черный") == [with_yo.name]
    assert _titles("units", viewer, "чёрный") == [with_yo.name]
    assert _titles("units", viewer, "зелёный") == [with_ye.name]
    assert _titles("units", viewer, "зеленый") == [with_ye.name]


# --- выключенная база знаний и недоступная группа (FR-444, FR-445) -----------------------------------------

def test_knowledge_disabled_has_no_articles_group_others_work():
    """FR-445: при выключенном модуле «База знаний» группы «Статьи» нет, остальные группы работают, поиск не падает."""
    from apps.search import services

    viewer = _viewer()
    unit = support_org.make_unit("Мониторинг")
    person = _person(full_name="Мельников Глеб", position="Мониторинг")
    support_org.make_member(person, unit)
    support_kb.make_published(title="Мониторинг сети", text="Текст про мониторинг")
    assert [p.key for p in services.providers(viewer)] == ["articles", "staff", "units"]
    assert _group_keys(viewer, "мониторинг") == ["articles", "staff", "units"]
    with support_kb.without_knowledge():
        assert [p.key for p in services.providers(viewer)] == ["staff", "units"]
        groups = services.page(viewer, _parsed("мониторинг"))
        assert [g.key for g in groups] == ["staff", "units"]
        by_group = {g.key: g for g in groups}
        assert [r.title for r in by_group["staff"].rows] == [person.full_name]
        assert [r.title for r in by_group["units"].rows] == ["Мониторинг"]


def test_provider_available_false_hides_group():
    """FR-444, FR-445: группа, у которой `available(user)` ложно, пользователю не показывается: сборщик её не
    вызывает, недоступное не отличается от несуществующего; доступные группы остаются."""
    from apps.search import services

    unit = support_org.make_unit("Мониторинг")
    person = _person(full_name="Мельников Глеб", position="Мониторинг")
    support_org.make_member(person, unit)
    support_kb.make_published(title="Мониторинг сети")
    no_rights = support.make_with_permissions(totp=False)
    viewer = _viewer()
    assert [p.key for p in services.providers(no_rights)] == ["articles"]
    assert [p.key for p in services.providers(viewer)] == ["articles", "staff", "units"]
    assert _group_keys(no_rights, "мониторинг") == ["articles"]
    assert _provider("tickets").available(no_rights) is False
    assert "tickets" not in [p.key for p in services.providers(viewer)]
