"""T-3134: число запросов к базе у страниц среза и индекс поиска (NFR-203). Сценарии 4, 8, 14 спеки.

Нагрузочный прогон p95 ≤ 500 мс — отдельно (Этап 4); здесь — то, что видно в тесте: число запросов списка, поиска,
счётчика, карточки, меню и открытой формы не растёт с размером выборки (нет N+1), а у столбца `Ticket.search` есть
GIN-индекс. Число запросов считается через `connection.execute_wrapper` (сигнал `request_started` сбрасывает журнал
`CaptureQueriesContext`), сравнивается на двух размерах выборки с запасом: разница меньше `SLACK`. Точное число задано
контрактом только у `menu_visible` (не больше двух запросов) и `badge` (два `COUNT`, 6.21). Код среза на уровне
модуля не импортируется (CONTRACT-003, шапка).
"""
import importlib
import re

import pytest
from django.contrib.postgres.search import SearchVector
from django.db import connection
from django.db.models import Value
from django.test.utils import CaptureQueriesContext

from tests import support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import HX, model

pytestmark = pytest.mark.django_db

GRID = {**HX, "HTTP_HX_TARGET": "tickets-grid"}
PRESETS = ("mine", "unassigned", "my_queues", "waiting", "closed", "all")
SMALL, LARGE = 3, 40          # размеры выборки: разница 37 строк — N+1 дал бы запас намного больше SLACK
SLACK = 10                    # «не растёт»: разница меньше 10 запросов (урок проверки волны 3)
_ROW = re.compile(r"<tr\b[^>]*\bdata-ticket\b")


def _svc(name: str):
    return importlib.import_module(f"apps.servicedesk.services.{name}")


def _member(**extra):
    """Участник новой очереди. Возвращает (пользователь, очередь)."""
    queue = sd.make_queue()
    user = support.make_employee(**extra)
    org.make_member(user, queue.unit)
    return user, queue


def count_queries(client, path, **headers) -> tuple[int, str]:
    """(число запросов к базе за один GET после прогрева, тело ответа). `execute_wrapper`, а не `CaptureQueriesContext`:
    последний сбрасывается сигналом `request_started` и теряет запросы запроса клиента."""
    client.get(path, **headers)  # прогрев: сессия, кэш прав, статика
    seen = []

    def wrapper(execute, sql, params, many, context):
        seen.append(sql)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(wrapper):
        got = client.get(path, **headers)
    assert got.status_code == 200, f"{path}: {got.status_code}"
    return len(seen), got.content.decode("utf-8")


def rows_of(html: str) -> int:
    return len(_ROW.findall(html))


def _grow_dictionary_rows():
    """Справочники, на которые смотрят строки сетки: по несколько значений, чтобы чередовать их в заявках."""
    Priority, Source = model("servicedesk.Priority"), model("servicedesk.Source")
    return list(Priority.objects.all()[:3]), list(Source.objects.all()[:2])


def _add_tickets(count, *, queue, user, category=None, client_unit=None, **over):
    """`count` заявок с заполненными связями (справочники, узел, ответственный, подразделение, заявитель)."""
    priorities, sources = _grow_dictionary_rows()
    made = []
    for index in range(count):
        fields = {"queue": queue, "requester": sd.make_requester(full_name=f"Заявитель {index}"),
                  "priority": priorities[index % len(priorities)], "source": sources[index % len(sources)]}
        if category is not None:
            fields["category"] = category
        if client_unit is not None:
            fields["client_unit"] = client_unit
        fields.update(over)
        made.append(sd.make_ticket(**fields))
    return made


def test_list_each_preset_query_count_independent_of_ticket_count():
    """NFR-203: у каждого из шести пресетов `/tickets/` число запросов не растёт с числом заявок (3 → 40 каждого
    вида: свои открытые, без ответственного, ждущие, закрытые); число строк сетки при этом растёт."""
    user, queue = _member()
    other = support.make_employee()
    client = support.logged_in(user)
    category = sd.make_category(queue=queue)
    unit_row = model("servicedesk.ClientUnit").objects.create(name="Склад")

    def add(count):
        _add_tickets(count, queue=queue, user=user, category=category, client_unit=unit_row, kind="in_progress",
                     assignee=user)
        _add_tickets(count, queue=queue, user=user, category=category, client_unit=unit_row, kind="new")
        _add_tickets(count, queue=queue, user=user, category=category, client_unit=unit_row, kind="waiting",
                     assignee=other)
        _add_tickets(count, queue=queue, user=user, category=category, client_unit=unit_row, kind="closed",
                     assignee=other)

    add(SMALL)
    small = {preset: count_queries(client, f"/tickets/?preset={preset}") for preset in PRESETS}
    add(LARGE - SMALL)
    large = {preset: count_queries(client, f"/tickets/?preset={preset}") for preset in PRESETS}
    for preset in PRESETS:
        assert rows_of(large[preset][1]) > rows_of(small[preset][1]), f"{preset}: строк не прибавилось"
        assert large[preset][0] - small[preset][0] < SLACK, (
            f"{preset}: число запросов растёт с числом заявок: {small[preset][0]} → {large[preset][0]}")


def test_list_with_filters_query_count_independent_of_ticket_count():
    """NFR-203: при всех фильтрах разом (очередь, категория, критичность, статус, вид, ответственный, подразделение,
    источник, период — 12.2) число запросов списка не растёт с числом подходящих заявок."""
    user, queue = _member()
    assignee = support.make_employee()
    client = support.logged_in(user)
    category = sd.make_category(queue=queue)
    unit_row = model("servicedesk.ClientUnit").objects.create(name="Цех")
    priority = model("servicedesk.Priority").objects.first()
    source = model("servicedesk.Source").objects.get(system_code="mail")
    status = model("servicedesk.Status").objects.get(kind="in_progress", is_default=True)

    def add(count):
        for index in range(count):
            sd.make_ticket(queue=queue, requester=sd.make_requester(full_name=f"Заявитель {index}"),
                           category=category, client_unit=unit_row, priority=priority, source=source, status=status,
                           kind="in_progress", assignee=assignee)

    path = (f"/tickets/?preset=all&queue={queue.unit_id}&category={category.pk}&priority={priority.pk}"
            f"&status={status.pk}&kind=in_progress&assignee={assignee.pk}&client_unit={unit_row.pk}"
            f"&source={source.pk}&created_from=01.01.2000&created_to=31.12.2099")
    add(SMALL)
    small, small_html = count_queries(client, path)
    add(LARGE - SMALL)
    large, large_html = count_queries(client, path)
    assert (rows_of(small_html), rows_of(large_html)) == (SMALL, LARGE)
    assert large - small < SLACK, f"число запросов растёт с числом заявок: {small} → {large}"


def test_list_search_query_count_independent_of_ticket_count():
    """NFR-203: поиск `q=…` в списке — число запросов не растёт с числом найденных заявок (столбец `search` заполнен
    обычным ORM-обновлением, находятся все)."""
    user, queue = _member()
    client = support.logged_in(user)
    Ticket = model("servicedesk.Ticket")
    created = []

    def add(count):
        created.extend(t.pk for t in _add_tickets(count, queue=queue, user=user, assignee=user, kind="in_progress"))
        Ticket.objects.filter(pk__in=created).update(search=SearchVector(Value("принтер сломался"), config="russian"))

    path = "/tickets/?preset=all&q=%D0%BF%D1%80%D0%B8%D0%BD%D1%82%D0%B5%D1%80"
    add(SMALL)
    small, small_html = count_queries(client, path)
    add(LARGE - SMALL)
    large, large_html = count_queries(client, path)
    assert (rows_of(small_html), rows_of(large_html)) == (SMALL, LARGE), "поиск должен находить все заявки"
    assert large - small < SLACK, f"число запросов поиска растёт с числом найденных заявок: {small} → {large}"


def test_list_reads_grid_without_per_row_queries():
    """NFR-203, FR-277: сетка (запрос НХ с целью `tickets-grid`) читается одной выборкой со справочниками, узлом и
    ответственным: у 40 строк со всеми заполненными связями запросов не больше, чем у 3 (разница меньше 10); строки
    сетки — все заявки."""
    user, queue = _member()
    client = support.logged_in(user)
    category = sd.make_category(queue=queue)
    unit_row = model("servicedesk.ClientUnit").objects.create(name="Склад")

    def add(count):
        for index in range(count):
            _add_tickets(1, queue=queue, user=user, category=category, client_unit=unit_row, kind="in_progress",
                         assignee=support.make_employee(full_name=f"Ответственный {index}"))

    path = "/tickets/?preset=all"
    add(SMALL)
    small, small_html = count_queries(client, path, **GRID)
    add(LARGE - SMALL)
    large, large_html = count_queries(client, path, **GRID)
    assert (rows_of(small_html), rows_of(large_html)) == (SMALL, LARGE)
    assert large - small < SLACK, f"сетка читается построчно: {small} → {large} запросов"

    listing = _svc("listing")
    with CaptureQueriesContext(connection) as ctx:
        page = listing.build(user, preset="all")
        for row in page.rows:
            for name in ("status", "priority", "category", "assignee", "client_unit", "queue"):
                str(getattr(row, name))
    assert len(page.rows) == LARGE
    assert len(ctx) < SLACK, f"`listing.build` и чтение связей строк: {len(ctx)} запросов на {LARGE} строк"


def test_card_query_count_independent_of_feed_items():
    """NFR-203: карточка заявки `/tickets/<номер>/` — число запросов не растёт с числом элементов ленты (5 → 50,
    у каждого свой автор из пула сотрудников)."""
    user, queue = _member()
    client = support.logged_in(user)
    ticket = sd.make_ticket(queue=queue, kind="in_progress", assignee=user)
    authors = [support.make_employee(full_name=f"Автор {i}") for i in range(6)]
    sd.make_entry(ticket, "incoming", text="Первое сообщение")

    def add(count):
        for index in range(count):
            sd.make_entry(ticket, "comment", author=authors[index % len(authors)], text=f"Комментарий {index}")

    path = f"/tickets/{ticket.number}/"
    add(5)
    small, small_html = count_queries(client, path)
    add(45)
    large, large_html = count_queries(client, path)
    assert "Комментарий 44" in large_html and "Комментарий 44" not in small_html
    assert large - small < SLACK, f"число запросов карточки растёт с лентой: {small} → {large}"


def test_counter_query_count_independent_of_ticket_count():
    """NFR-203, FR-278: `/tickets/count/` (кнопка «показать количество») — число запросов не растёт с числом заявок;
    `[data-total]` показывает настоящее число строк фильтра."""
    user, queue = _member()
    client = support.logged_in(user)
    category = sd.make_category(queue=queue)

    def add(count):
        _add_tickets(count, queue=queue, user=user, category=category, kind="in_progress", assignee=user)

    def shown(html):
        found = re.search(r"data-total[^>]*>([^<]*)<", html)
        assert found, "нет [data-total]"
        return int("".join(ch for ch in found.group(1) if ch.isdigit()))

    path = f"/tickets/count/?preset=all&category={category.pk}&kind=in_progress"
    add(SMALL)
    small, small_html = count_queries(client, path)
    add(LARGE - SMALL)
    large, large_html = count_queries(client, path)
    assert (shown(small_html), shown(large_html)) == (SMALL, LARGE)
    assert large - small < SLACK, f"число запросов счётчика растёт с числом заявок: {small} → {large}"


def test_menu_query_count_independent_of_ticket_and_queue_count():
    """NFR-203, FR-280, 6.3, 6.21: меню с пунктом «Заявки» — `access.menu_visible` не больше двух запросов, `badge` —
    два `COUNT` по таблице заявок; число запросов страницы (`/me/`) не растёт ни с числом заявок, ни с числом очередей."""
    user, queue = _member()
    access, listing = _svc("access"), _svc("listing")
    client = support.logged_in(user)

    def add(tickets, queues):
        _add_tickets(tickets, queue=queue, user=user, kind="new")
        _add_tickets(tickets, queue=queue, user=user, kind="in_progress", assignee=user, last_message_from="requester")
        for _ in range(queues):
            org.make_member(user, sd.make_queue().unit)

    def cold_menu_queries():
        """Запросы `menu_visible` на свежем объекте пользователя (дополнение 38 б): без кэша прав."""
        fresh = type(user).objects.get(pk=user.pk)
        with CaptureQueriesContext(connection) as ctx:
            assert access.menu_visible(fresh) is True
        return len(ctx)

    add(2, 1)
    small, _ = count_queries(client, "/me/")
    cold_menu_queries()   # прогрев: прочие кэши процесса
    menu_small = cold_menu_queries()
    add(LARGE, 20)
    large, _ = count_queries(client, "/me/")
    assert large - small < SLACK, f"число запросов меню растёт: {small} → {large}"
    menu_large = cold_menu_queries()
    assert menu_small <= 4, f"`menu_visible` на свежем объекте: {menu_small} запросов"
    assert menu_large == menu_small, f"запросы `menu_visible` зависят от данных: {menu_small} → {menu_large}"
    with CaptureQueriesContext(connection) as ctx:
        total = listing.badge(user)
    counts = [item["sql"] for item in ctx.captured_queries
              if "COUNT(" in item["sql"].upper() and "servicedesk_ticket" in item["sql"]
              and "servicedesk_ticketentry" not in item["sql"]]
    assert len(counts) == 2, f"`badge`: ожидалось два COUNT, было {len(counts)}"
    assert total == 2 * (LARGE + 2), "без ответственного в моих очередях + мои от заявителя"


def test_open_form_query_count_constant():
    """NFR-203: открытая форма `/request/` без входа — число запросов не растёт с числом категорий формы и
    подразделений; категории из справочника в форме есть (число `option` растёт)."""
    queue = sd.make_queue()
    sd.configure_servicedesk(domains=["client.test"], default_queue=queue)
    ClientUnit = model("servicedesk.ClientUnit")
    client = support.make_client(ip="198.51.100.77")

    def add(count, start):
        for index in range(start, start + count):
            sd.make_category(f"Категория формы {index}", queue=queue, on_form=True)
            unit_name = f"Подразделение формы {index}"
            ClientUnit.objects.create(name=unit_name, name_key=org.name_key(unit_name))

    add(2, 0)
    small, small_html = count_queries(client, "/request/")
    add(LARGE, 2)
    large, large_html = count_queries(client, "/request/")
    assert 'data-form="request"' in large_html, "приём закрыт: форма не показана"
    assert large_html.count("<option") - small_html.count("<option") >= LARGE
    assert large - small < SLACK, f"число запросов формы растёт со справочниками: {small} → {large}"


def test_ticket_search_column_has_gin_index():
    """NFR-203, 2.2: у столбца `Ticket.search` есть GIN-индекс (имя не сравнивается; план запроса не проверяется)."""
    with connection.cursor() as cur:
        constraints = connection.introspection.get_constraints(cur, "servicedesk_ticket")
    found = [c for c in constraints.values() if c["index"] and c["type"] == "gin" and c["columns"] == ["search"]]
    assert found, f"нет GIN-индекса по столбцу search: {sorted(constraints)}"
