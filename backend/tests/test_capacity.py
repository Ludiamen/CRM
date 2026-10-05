"""T-117, T-2120: ёмкость и скорость (NFR-001, NFR-002, NFR-101, NFR-102).

Проверка p95 ≤ 500 мс на 100 пользователях — нагрузочный прогон `tests/load/locustfile.py` (Этап 4, T-304),
здесь — то, что видно в тестах: 100 сессий держатся, а число запросов к базе у списков не растёт с выборкой.
Срез 002: то же для структуры (до 200 узлов) и страниц среза; нагрузочный прогон — класс `OrgUser` в locustfile.py.
"""
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests import factories, support, support_org
from tests.support import model

pytestmark = pytest.mark.django_db


def test_hundred_users_hold_hundred_sessions():
    """NFR-001: 100 учётных записей входят одновременно, 100 сессий живут рядом и каждая работает."""
    users = [support.make_employee() for _ in range(100)]
    clients = [support.logged_in(u, ip=f"203.0.{i // 200}.{i % 200 + 1}") for i, u in enumerate(users)]
    assert model("core.UserSession").objects.count() == 100
    assert len({s.session_key for s in model("core.UserSession").objects.all()}) == 100
    for _ in range(2):
        assert all(c.get("/me/").status_code == 200 for c in clients)
    assert model("core.UserSession").objects.count() == 100, "запросы не плодят и не теряют сессии"
    assert model("core.LoginAttempt").objects.filter(result="success").count() == 100


def queries(client, path) -> int:
    client.get(path)  # прогрев: кэш прав, статика
    with CaptureQueriesContext(connection) as captured:
        got = client.get(path)
    assert got.status_code == 200, path
    return len(captured)


def test_list_pages_query_count_constant_for_staff_audit_and_history():
    """NFR-002: число запросов к базе у списка сотрудников, журнала и истории входов не зависит от размера выборки (нет N+1)."""
    from apps.core.services.audit import record

    Attempt = model("core.LoginAttempt")
    role = factories.make_role(name="Нагрузочная", permissions=("audit.view",))
    admin_user = support.make_admin()
    admin = support.logged_in(admin_user, ip="198.51.100.190")
    target = support.make_employee(roles=[role])
    paths = ("/staff/", "/audit/", f"/staff/{target.pk}/logins/", "/me/security/history/")

    def add_attempts(n):
        Attempt.objects.bulk_create([Attempt(user=admin_user, ip=f"192.0.2.{i % 250}", browser="Firefox", platform="Linux",
                                             result="bad_password", at=timezone.now() - timedelta(minutes=i))
                                     for i in range(n)] +
                                    [Attempt(user=target, ip=f"192.0.2.{i % 250}", browser="Firefox", platform="Linux",
                                             result="bad_password", at=timezone.now() - timedelta(minutes=i))
                                     for i in range(n)])

    for i in range(2):
        support.make_employee(roles=[role])
        record("probe.small", actor=admin_user, object_type="probe", object_id=str(i))
    add_attempts(3)
    small = {path: queries(admin, path) for path in paths}
    for i in range(30):
        support.make_employee(roles=[role])
    for i in range(300):
        record("probe.large", actor=admin_user, object_type="probe", object_id=str(i))
    add_attempts(120)
    large = {path: queries(admin, path) for path in paths}
    assert large == small, f"число запросов растёт с выборкой: было {small}, стало {large}"
    assert all(n <= 25 for n in large.values()), f"слишком много запросов на страницу: {large}"


# --- срез 002 (T-2120): структура до 200 узлов и страницы среза ----------------------------------

def count_queries(client, path, **headers) -> int:
    """Число запросов к базе за один GET (после прогрева). `execute_wrapper`, а не `CaptureQueriesContext`:
    последний сбрасывается сигналом `request_started` и теряет запросы запроса клиента."""
    client.get(path, **headers)  # прогрев: кэш прав, статика
    counter = []

    def wrapper(execute, sql, params, many, context):
        counter.append(sql)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(wrapper):
        got = client.get(path, **headers)
    assert got.status_code == 200, path
    return len(counter)


def staff_viewer():
    """Смотрящий со всеми правами среза: страницы отдают всю разметку (действия, поле поиска, правка дней)."""
    return support.make_with_permissions("staff.view", "accounts.manage", "org.manage", "roles.manage", "calendar.manage")


def attach_clean_photo(user):
    stored = model("core.StoredFile").objects.create(
        owner=user, purpose="photo", status="clean", content_type="image/png", size=100, sha256="0" * 64)
    user.photo = stored
    user.save(update_fields=["photo"])


def grow_units(parent, count, *, prefix="Узел"):
    """`count` узлов под `parent`: ветви по пять детей, чтобы дерево было и широким, и глубоким."""
    made, queue = [], [parent]
    while len(made) < count:
        head = queue.pop(0)
        for _ in range(5):
            if len(made) == count:
                break
            unit = support_org.make_unit(f"{prefix} {len(made) + 1}-{head.pk}", parent=head)
            made.append(unit)
            queue.append(unit)
    return made


def test_tree_page_with_200_units_query_count_constant():
    """NFR-101, NFR-102: в структуре 200 узлов (с корнем); число запросов к дереву и к карточке узла не растёт с числом
    узлов и участников, а все 200 узлов видны в дереве."""
    viewer = staff_viewer()
    client = support.logged_in(viewer, ip="198.51.100.191")
    root = support_org.root_unit()
    dept = support_org.make_unit("Карточка")
    grow_units(root, 2, prefix="Малый")
    for i in range(2):
        support_org.make_member(support.make_employee(full_name=f"Участник {i}"), dept)
    paths = ("/structure/", f"/structure/{dept.pk}/")
    small = {path: count_queries(client, path) for path in paths}
    small["HX card"] = count_queries(client, f"/structure/{dept.pk}/", HTTP_HX_REQUEST="true")

    Unit = model("org.Unit")
    grow_units(dept, 200 - Unit.objects.count(), prefix="Большой")
    assert Unit.objects.count() == 200
    for i in range(2, 30):
        support_org.make_member(support.make_employee(full_name=f"Участник {i}"), dept, mark="head" if i == 2 else "")
    large = {path: count_queries(client, path) for path in paths}
    large["HX card"] = count_queries(client, f"/structure/{dept.pk}/", HTTP_HX_REQUEST="true")
    assert large == small, f"число запросов растёт с размером структуры: было {small}, стало {large}"
    html = client.get("/structure/").content.decode()
    assert len(re.findall(r'<li\b[^>]*\bdata-unit-id="', html)) == 200, "в дереве должны быть все 200 узлов"


def test_slice_pages_query_count_constant(django_capture_on_commit_callbacks):
    """NFR-102: число запросов у структуры, карточки узла, списка сотрудников (поиск, подразделение, фото), карточки
    сотрудника, календаря и сетки поля даты не зависит от числа людей, узлов, фото и особых дней."""
    viewer = staff_viewer()
    client = support.logged_in(viewer, ip="198.51.100.192")
    root = support_org.root_unit()
    dept = support_org.make_unit("Подразделение нагрузки")
    card = support_org.make_unit("Карточка нагрузки", parent=dept)
    today = datetime.now(ZoneInfo("Europe/Moscow")).date()
    year = today.year
    model("org.CalendarYear").objects.create(
        year=year, loaded_by=viewer, file_name="calendar.csv",
        totals={"holidays_on_weekdays": 0, "moved_days_off": 0, "moved_workdays": 0, "short_days": 0, "work_days": 0})
    SpecialDay = model("org.SpecialDay")

    def add_special_days(first, last):
        for n in range(first, last):
            SpecialDay.objects.create(date=date(year, 1 + n // 28, 1 + n % 28), kind="holiday" if n % 2 else "short",
                                      origin="file", changed_by=viewer)

    def add_people(first, last, units, with_photo):
        people = []
        for n in range(first, last):
            user = support.make_employee(full_name=f"Сотрудник нагрузки {n}", position="Инженер")
            support_org.make_member(user, units[n % len(units)])
            if with_photo and n % 2:
                attach_clean_photo(user)
            people.append(user)
        return people

    add_special_days(0, 2)
    people = add_people(0, 3, [card], with_photo=True)
    # руководитель есть в обеих выборках: одна ветвь кода; people[0] уже участник card — меняется только отметка
    model("org.Membership").objects.filter(user=people[0], unit=card).update(mark="head")
    target = people[1]
    def paths():
        return {
            "structure": "/structure/",
            "card": f"/structure/{card.pk}/",
            "card search": f"/structure/{card.pk}/?q=сотрудник",
            "staff list": f"/staff/?q=сотрудник&unit={dept.pk}",
            "staff card": f"/staff/{target.pk}/",
            "calendar": f"/calendar/?year={year}",
            "date picker": f"/ui/date-picker/?month={today.year}-{today.month:02d}",
        }

    def measure():
        result = {name: count_queries(client, path) for name, path in paths().items()}
        result["card (HX)"] = count_queries(client, f"/structure/{card.pk}/", HTTP_HX_REQUEST="true")
        result["staff list (HX)"] = count_queries(client, f"/staff/?q=сотрудник&unit={dept.pk}", HTTP_HX_REQUEST="true")
        return result

    small = measure()
    branches = grow_units(dept, 60, prefix="Ветвь нагрузки") + grow_units(root, 40, prefix="Другая ветвь")
    add_people(3, 66, [card] + branches[:60], with_photo=True)
    add_special_days(2, 40)
    # дни добавлены мимо служб: версию кэша отметок поднимаем, как делают службы (план, «Рабочий календарь»);
    # служба поднимает её после фиксации, а транзакция теста не фиксируется (решение 11 задач)
    from apps.org.services import calendar as calendar_service
    with django_capture_on_commit_callbacks(execute=True):
        calendar_service.bump_version()
    large = measure()
    assert large == small, f"число запросов растёт с выборкой: было {small}, стало {large}"
    assert model("core.StoredFile").objects.filter(status="clean").count() >= 30, "в большой выборке есть фото"
    assert_pages_have_content(client, viewer, card, dept, target, people[0], today, year)


def assert_pages_have_content(client, viewer, card, dept, target, head, today, year):
    """Постоянное число запросов не значит пустую страницу: на большой выборке страницы несут зацепки контракта
    (CONTRACT-002.md, 9.1, 9.3, 9.4, 9.5, 9.6)."""
    def page(path, **headers):
        got = client.get(path, **headers)
        assert got.status_code == 200, path
        return got.content.decode()

    member_re = r'<[^>]*\bdata-member(?=[\s>=])'
    expected_members = model("org.Membership").objects.filter(unit=card).count()
    assert expected_members >= 4
    for html in (page(f"/structure/{card.pk}/"), page(f"/structure/{card.pk}/", HTTP_HX_REQUEST="true")):
        assert len(re.findall(member_re, html)) == expected_members, "в карточке узла все участники [data-member]"
        assert head.full_name in html

    html = page(f"/staff/?q=сотрудник&unit={dept.pk}")
    assert len(re.findall(r'<[^>]*\bdata-user-id="', html)) > 3, "в списке строки сотрудников"
    # страница списка — 25 строк (срез 001); «…10» из большой выборки на первой странице и при порядке по ФИО, и по id
    assert "Сотрудник нагрузки 10" in html, "в списке есть ФИО из большой выборки"
    assert "<img" in html, "в списке есть фото"

    html = page(f"/staff/{target.pk}/")
    at = html.find('data-field="head"')
    assert at >= 0, "в карточке сотрудника есть [data-field=head]"
    assert head.full_name in html[at:at + 400] and "не назначен" not in html[at:at + 400], "назван руководитель"

    html = page(f"/calendar/?year={year}")
    assert len(re.findall(r'<[^>]*\bdata-month="(?:[1-9]|1[0-2])"', html)) == 12, "в календаре 12 месяцев"
    SpecialDay = model("org.SpecialDay")
    for kind in ("holiday", "short"):
        marked = len(re.findall(rf'<td\b[^>]*\bdata-day-kind="{kind}"', html))
        assert marked == SpecialDay.objects.filter(kind=kind).count() >= 19, f"в календаре отмечены особые дни: {kind}"

    html = page(f"/ui/date-picker/?month={today.year}-{today.month:02d}")
    assert "data-datefield-grid" in html and f'data-month="{today.year}-{today.month:02d}"' in html
    assert len(re.findall(r'<button\b[^>]*\bdata-date="', html)) >= 28, "в сетке есть дни месяца"
