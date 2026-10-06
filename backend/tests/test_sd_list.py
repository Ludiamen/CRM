"""T-3123: список заявок — пресеты, фильтр, сортировка, страницы, счётчик (FR-276, FR-278, FR-279).
Сценарии 4, 8 и 14 спеки среза 003."""
import re
from datetime import datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

import pytest

from tests import support, support_org as org
from tests import support_servicedesk as sd
from tests.support import HX, model

pytestmark = pytest.mark.django_db

MSK = ZoneInfo("Europe/Moscow")
GRID = {"HTTP_HX_REQUEST": "true", "HTTP_HX_TARGET": "tickets-grid"}
_VOID = {"input", "br", "img", "hr", "meta", "link", "area", "base", "col", "source", "wbr"}
PRESET_CODES = ("mine", "unassigned", "my_queues", "waiting", "closed", "all")


# --- разбор разметки (помощник только этого файла) ---------------------------------------------

class _El:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.kids = tag, attrs, parent, []

    def walk(self):
        yield self
        for kid in self.kids:
            if isinstance(kid, _El):
                yield from kid.walk()

    def text(self) -> str:
        parts = [kid if isinstance(kid, str) else kid.text() for kid in self.kids]
        return " ".join(" ".join(parts).split())

    def find_all(self, tag=None, **want):
        """Элементы с тегом `tag` и атрибутами `want` (`data_x` -> `data-x`; True — любое значение)."""
        wanted = {key.replace("_", "-"): value for key, value in want.items()}
        return [el for el in self.walk()
                if (tag is None or el.tag == tag)
                and all(name in el.attrs and (value is True or el.attrs[name] == str(value))
                        for name, value in wanted.items())]

    def inside(self, **want) -> bool:
        """Сам элемент или кто-то из предков несёт все атрибуты `want`."""
        wanted = {key.replace("_", "-"): value for key, value in want.items()}
        node = self
        while node is not None:
            if all(name in node.attrs and (value is True or node.attrs[name] == str(value))
                   for name, value in wanted.items()):
                return True
            node = node.parent
        return False


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _El("#root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        el = _El(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.kids.append(el)
        if tag not in _VOID:
            self.cur = el

    def handle_startendtag(self, tag, attrs):
        self.cur.kids.append(_El(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.kids.append(data)


def dom(response) -> _El:
    builder = _Builder()
    builder.feed(response.content.decode("utf-8", "replace"))
    return builder.root


def numbers(response) -> list[int]:
    """Номера заявок в строках сетки `tr[data-ticket]` в порядке разметки."""
    return [int(el.attrs["data-ticket"]) for el in dom(response).find_all("tr", data_ticket=True)]


def preset_links(response) -> dict:
    return {el.attrs["data-preset"]: el
            for nav in dom(response).find_all("nav", data_presets=True)
            for el in nav.find_all("a", data_preset=True)}


# --- данные ---------------------------------------------------------------------------------------

def make_marked_unit():
    """Узел, отмеченный очередью."""
    unit = org.make_unit()
    sd.make_queue(unit)
    return unit


def member_of(*units):
    """Сотрудник, состоящий в узлах (узлы работы — они сами)."""
    user = support.make_employee()
    for unit in units:
        org.make_member(user, unit)
    return user


def holder_of_all():
    return support.make_with_permissions("servicedesk.all")


def status_named(name: str):
    return model("servicedesk.Status").objects.get(name=name)


def priority_named(name: str):
    return model("servicedesk.Priority").objects.get(name=name)


def get(user, params=None, *, grid=False, path="/tickets/"):
    client = support.logged_in(user)
    extra = GRID if grid else {}
    return client.get(path, params or {}, **extra)


def open_numbers(*tickets) -> set[int]:
    return {t.number for t in tickets}


# --- пресеты ---------------------------------------------------------------------------------------

def test_preset_mine_own_open_tickets_only():
    """FR-276: «Мои» — ответственный смотрящий и заявка открыта; чужие, закрытые и без ответственного не входят."""
    unit, foreign = make_marked_unit(), make_marked_unit()
    me, other = member_of(unit), member_of(unit)
    mine_new = sd.make_ticket(queue=unit, kind="new", assignee=me)
    mine_progress = sd.make_ticket(queue=unit, kind="in_progress", assignee=me)
    mine_waiting = sd.make_ticket(queue=unit, kind="waiting", assignee=me)
    mine_foreign_queue = sd.make_ticket(queue=foreign, kind="in_progress", assignee=me)
    sd.make_ticket(queue=unit, kind="closed", assignee=me)
    sd.make_ticket(queue=unit, kind="in_progress", assignee=other)
    sd.make_ticket(queue=unit, kind="new")
    response = get(me, {"preset": "mine"})
    assert response.status_code == 200
    assert set(numbers(response)) == open_numbers(mine_new, mine_progress, mine_waiting, mine_foreign_queue)
    assert len(numbers(response)) == 4


def test_preset_unassigned_in_my_queues_open_only():
    """FR-276: «Без ответственного» — открытые заявки без ответственного в моих очередях."""
    unit, foreign = make_marked_unit(), make_marked_unit()
    me, other = member_of(unit), member_of(unit)
    free_new = sd.make_ticket(queue=unit, kind="new")
    free_waiting = sd.make_ticket(queue=unit, kind="waiting")
    sd.make_ticket(queue=unit, kind="closed")
    sd.make_ticket(queue=unit, kind="in_progress", assignee=other)
    sd.make_ticket(queue=unit, kind="in_progress", assignee=me)
    sd.make_ticket(queue=foreign, kind="new")
    response = get(me, {"preset": "unassigned"})
    assert response.status_code == 200
    assert sorted(numbers(response)) == sorted(open_numbers(free_new, free_waiting))


def test_preset_my_queues_open_tickets_of_marked_work_nodes():
    """FR-276: «Мои очереди» — открытые заявки отмеченных узлов среди моих узлов работы; неотмеченный узел,
    чужая очередь и заявка, видимая только как ответственному, не входят."""
    from apps.servicedesk.services import listing

    marked_a, marked_b = make_marked_unit(), make_marked_unit()
    unmarked = org.make_unit()
    foreign = make_marked_unit()
    me, other = member_of(marked_a, marked_b, unmarked), member_of(foreign)
    in_a = sd.make_ticket(queue=marked_a, kind="new")
    in_a_assigned = sd.make_ticket(queue=marked_a, kind="in_progress", assignee=other)
    in_b = sd.make_ticket(queue=marked_b, kind="waiting")
    sd.make_ticket(queue=marked_a, kind="closed")
    sd.make_ticket(queue=unmarked, kind="new")
    sd.make_ticket(queue=foreign, kind="new")
    sd.make_ticket(queue=foreign, kind="in_progress", assignee=me)
    assert listing.my_queue_ids(me) == frozenset({marked_a.pk, marked_b.pk})
    response = get(me, {"preset": "my_queues"})
    assert sorted(numbers(response)) == sorted(open_numbers(in_a, in_a_assigned, in_b))


def test_preset_my_queues_all_marked_nodes_for_all_tickets_holder():
    """FR-276: у держателя «Все заявки» «Мои очереди» — все отмеченные узлы, без неотмеченных."""
    from apps.servicedesk.services import listing

    queue_a, queue_b = make_marked_unit(), make_marked_unit()
    unmarked = org.make_unit()
    holder = holder_of_all()
    in_a = sd.make_ticket(queue=queue_a, kind="new")
    in_b = sd.make_ticket(queue=queue_b, kind="in_progress", assignee=member_of(queue_b))
    sd.make_ticket(queue=queue_a, kind="closed")
    sd.make_ticket(queue=unmarked, kind="new")
    assert listing.my_queue_ids(holder) == frozenset({queue_a.pk, queue_b.pk})
    response = get(holder, {"preset": "my_queues"})
    assert sorted(numbers(response)) == sorted(open_numbers(in_a, in_b))


def test_preset_waiting_requester_kind_only():
    """FR-276: «Ждут ответа заявителя» — только вид «ждёт ответа заявителя», любой ответственный."""
    unit = make_marked_unit()
    me, other = member_of(unit), member_of(unit)
    waiting_free = sd.make_ticket(queue=unit, kind="waiting")
    waiting_other = sd.make_ticket(queue=unit, kind="waiting", assignee=other)
    sd.make_ticket(queue=unit, kind="new")
    sd.make_ticket(queue=unit, kind="in_progress", assignee=me)
    sd.make_ticket(queue=unit, kind="closed")
    response = get(me, {"preset": "waiting"})
    assert sorted(numbers(response)) == sorted(open_numbers(waiting_free, waiting_other))


def test_preset_closed_kind_only():
    """FR-276: «Закрытые» — только вид «закрыта», включая статусы «Решена» и «Не может быть решена»."""
    unit = make_marked_unit()
    me = member_of(unit)
    closed_done = sd.make_ticket(queue=unit, status=status_named("Решена"))
    closed_failed = sd.make_ticket(queue=unit, status=status_named("Не может быть решена"), assignee=me)
    sd.make_ticket(queue=unit, kind="new")
    sd.make_ticket(queue=unit, kind="waiting")
    sd.make_ticket(queue=unit, kind="in_progress", assignee=me)
    response = get(me, {"preset": "closed"})
    assert sorted(numbers(response)) == sorted(open_numbers(closed_done, closed_failed))


def test_preset_all_shows_only_visible_tickets():
    """FR-276: «Все» — всё видимое (очередь смотрящего и свои как ответственного), чужих очередей нет."""
    unit, foreign = make_marked_unit(), make_marked_unit()
    me = member_of(unit)
    own_queue = [sd.make_ticket(queue=unit, kind=kind) for kind in ("new", "in_progress", "waiting", "closed")]
    assigned_abroad = sd.make_ticket(queue=foreign, kind="in_progress", assignee=me)
    hidden = [sd.make_ticket(queue=foreign, kind="new"), sd.make_ticket(queue=foreign, kind="closed")]
    response = get(me, {"preset": "all"})
    assert sorted(numbers(response)) == sorted(open_numbers(*own_queue, assigned_abroad))
    assert not set(numbers(response)) & open_numbers(*hidden)


def test_open_means_new_in_progress_waiting_requester():
    """FR-276: «открытые» — виды «новая», «в работе», «ждёт ответа заявителя»; закрытые виды любого статуса — нет."""
    from apps.servicedesk.services import listing

    assert tuple(listing.OPEN_KINDS) == ("new", "in_progress", "waiting")
    unit = make_marked_unit()
    me = member_of(unit)
    open_tickets = [sd.make_ticket(queue=unit, kind=kind, assignee=me) for kind in listing.OPEN_KINDS]
    sd.make_ticket(queue=unit, status=status_named("Решена"), assignee=me)
    sd.make_ticket(queue=unit, status=status_named("Закрыта автоматически"), assignee=me)
    for preset in ("mine", "my_queues"):
        assert sorted(numbers(get(me, {"preset": preset}))) == sorted(open_numbers(*open_tickets)), preset


def test_default_preset_my_queues_for_queue_member():
    """FR-276: без параметра у участника очереди (и у держателя «Все заявки») — «Мои очереди»."""
    from apps.servicedesk.services import listing

    unit = make_marked_unit()
    member, holder = member_of(unit), holder_of_all()
    in_queue = sd.make_ticket(queue=unit, kind="new")
    sd.make_ticket(queue=unit, kind="closed")
    sd.make_ticket(queue=unit, kind="in_progress", assignee=member_of(unit))
    assert listing.default_preset(member) == "my_queues"
    assert listing.default_preset(holder) == "my_queues"
    response = get(member)
    assert response.status_code == 200
    links = preset_links(response)
    assert set(links) == set(PRESET_CODES)
    assert [code for code, el in links.items() if el.attrs.get("aria-current") == "true"] == ["my_queues"]
    assert len(numbers(response)) == 2
    assert in_queue.number in numbers(response)
    assert preset_links(get(holder))["my_queues"].attrs.get("aria-current") == "true"


def test_default_preset_mine_for_user_without_queues():
    """FR-276: у того, кто ни в одной очереди не состоит, пресет по умолчанию — «Мои»; неизвестный пресет — он же."""
    from apps.servicedesk.services import listing

    foreign = make_marked_unit()
    me = support.make_employee()
    mine = sd.make_ticket(queue=foreign, kind="in_progress", assignee=me)
    sd.make_ticket(queue=foreign, kind="new")
    assert listing.default_preset(me) == "mine"
    for params in ({}, {"preset": "no-such-preset"}):
        response = get(me, params)
        assert response.status_code == 200
        assert numbers(response) == [mine.number]
        assert [code for code, el in preset_links(response).items()
                if el.attrs.get("aria-current") == "true"] == ["mine"]


def test_htmx_grid_target_returns_grid_only_panel_and_presets_stay():
    """FR-276: запрос HTMX с целью сетки получает только сетку (без панели фильтра и пресетов), обычный запрос —
    страницу целиком; ссылки пресетов ведут в сетку с `hx-push-url`."""
    unit = make_marked_unit()
    me = member_of(unit)
    ticket = sd.make_ticket(queue=unit, kind="new")
    client = support.logged_in(me)
    full = client.get("/tickets/", {"preset": "my_queues"})
    assert full.status_code == 200
    page = dom(full)
    assert page.find_all(None, data_tickets_list=True)
    assert page.find_all("nav", data_presets=True)
    assert page.find_all("form", id="tickets-filter")
    assert page.find_all(None, id="tickets-grid")
    for code in PRESET_CODES:
        link = preset_links(full)[code]
        assert link.attrs.get("hx-target") == "#tickets-grid"
        assert link.attrs.get("hx-push-url") == "true"
        assert f"preset={code}" in (link.attrs.get("href", "") + link.attrs.get("hx-get", ""))
    only_grid = client.get("/tickets/", {"preset": "my_queues"}, **GRID)
    assert only_grid.status_code == 200
    part = dom(only_grid)
    assert numbers(only_grid) == [ticket.number]
    assert not part.find_all("nav", data_presets=True)
    assert not part.find_all("form", id="tickets-filter")
    assert not part.find_all(None, data_tickets_list=True)
    other = client.get("/tickets/", {"preset": "my_queues"}, **HX)
    assert other.status_code == 200
    assert dom(other).find_all("form", id="tickets-filter")


def test_filter_params_in_url_for_back_and_push_url():
    """FR-276, FR-278: адрес с параметрами — прежний для «Назад»: форма, пресеты, заголовки, страницы несут
    `hx-get`, `hx-target`, `hx-push-url`; значения фильтра выбраны и скрытые поля несут пресет и сортировку."""
    unit = make_marked_unit()
    holder = holder_of_all()
    for _ in range(51):
        sd.make_ticket(queue=unit, kind="new")
    params = {"preset": "all", "queue": str(unit.pk), "kind": "new", "sort": "created", "dir": "asc",
              "q": "принтер"}
    response = get(holder, params)
    assert response.status_code == 200
    page = dom(response)
    form = page.find_all("form", id="tickets-filter")[0]
    assert form.attrs.get("method", "get").lower() == "get"
    assert form.attrs.get("hx-get") == "/tickets/"
    assert form.attrs.get("hx-target") == "#tickets-grid"
    assert form.attrs.get("hx-push-url") == "true"
    assert any("selected" in o.attrs for o in form.find_all("select", name="queue")[0].find_all("option", value=unit.pk))
    assert any("selected" in o.attrs for o in form.find_all("select", name="kind")[0].find_all("option", value="new"))
    assert form.find_all("input", name="q")[0].attrs.get("value") == "принтер"
    for name, value in (("preset", "all"), ("sort", "created"), ("dir", "asc")):
        assert form.find_all("input", name=name)[0].attrs.get("value") == value
    for link in preset_links(response).values():
        assert link.attrs.get("hx-get") and link.attrs.get("hx-target") == "#tickets-grid"
        assert link.attrs.get("hx-push-url") == "true"
    sort_links = [a for th in page.find_all("th", data_sort=True) for a in th.find_all("a", href=True)]
    assert sort_links
    for link in sort_links:
        assert link.attrs.get("hx-get") and link.attrs.get("hx-target") == "#tickets-grid"
        assert link.attrs.get("hx-push-url") == "true"
        assert "sort=" in link.attrs["href"] and "dir=" in link.attrs["href"]
    # q не нашёл ничего в заявках без вектора поиска; страница 2 для «Назад» — тот же адрес с параметрами
    plain = {"preset": "all", "queue": str(unit.pk), "kind": "new", "sort": "created", "dir": "asc"}
    first = get(holder, plain)
    nxt = dom(first).find_all("a", data_action="page-next")[0]
    assert nxt.attrs.get("hx-get") and nxt.attrs.get("hx-target") == "#tickets-grid"
    assert nxt.attrs.get("hx-push-url") == "true"
    assert "page=2" in nxt.attrs["href"] and f"queue={unit.pk}" in nxt.attrs["href"]
    assert "kind=new" in nxt.attrs["href"] and "sort=created" in nxt.attrs["href"]
    direct = get(holder, plain)
    assert numbers(direct) == numbers(get(holder, plain, grid=True))


# --- фильтр -----------------------------------------------------------------------------------------

def test_filter_by_queue_category_criticality():
    """FR-278: фильтры по очереди, категории и критичности; неверное значение (не число) — как пустое."""
    holder = holder_of_all()
    queue_a, queue_b = make_marked_unit(), make_marked_unit()
    cat_a, cat_b = sd.make_category(queue=queue_a), sd.make_category(queue=queue_b)
    high, low = priority_named("Высокая"), priority_named("Низкая")
    t1 = sd.make_ticket(queue=queue_a, category=cat_a, priority=high)
    t2 = sd.make_ticket(queue=queue_a, category=cat_b, priority=low)
    t3 = sd.make_ticket(queue=queue_b, category=cat_b, priority=high)
    t4 = sd.make_ticket(queue=queue_b, category=cat_a, priority=low)
    base = {"preset": "all"}
    assert sorted(numbers(get(holder, {**base, "queue": queue_a.pk}))) == sorted(open_numbers(t1, t2))
    assert sorted(numbers(get(holder, {**base, "category": cat_b.pk}))) == sorted(open_numbers(t2, t3))
    assert sorted(numbers(get(holder, {**base, "priority": high.pk}))) == sorted(open_numbers(t1, t3))
    assert sorted(numbers(get(holder, {**base, "priority": low.pk, "queue": queue_b.pk}))) == [t4.number]
    assert sorted(numbers(get(holder, {**base, "queue": "abc"}))) == sorted(open_numbers(t1, t2, t3, t4))


def test_filter_by_status_and_status_kind():
    """FR-278: фильтр по статусу (точно) и по виду статуса (все статусы вида)."""
    holder = holder_of_all()
    unit = make_marked_unit()
    solved = sd.make_ticket(queue=unit, status=status_named("Решена"))
    failed = sd.make_ticket(queue=unit, status=status_named("Не может быть решена"))
    auto = sd.make_ticket(queue=unit, status=status_named("Закрыта автоматически"))
    waiting = sd.make_ticket(queue=unit, kind="waiting")
    fresh = sd.make_ticket(queue=unit, kind="new")
    base = {"preset": "all"}
    assert numbers(get(holder, {**base, "status": status_named("Не может быть решена").pk})) == [failed.number]
    assert sorted(numbers(get(holder, {**base, "kind": "closed"}))) == sorted(open_numbers(solved, failed, auto))
    assert numbers(get(holder, {**base, "kind": "waiting"})) == [waiting.number]
    assert numbers(get(holder, {**base, "kind": "new"})) == [fresh.number]


def test_filter_by_assignee_and_without_assignee():
    """FR-278: фильтр по ответственному (id) и «без ответственного» (`assignee=none`), закрытые без ответственного
    тоже."""
    holder = holder_of_all()
    unit = make_marked_unit()
    ann, bob = member_of(unit), member_of(unit)
    t_ann = sd.make_ticket(queue=unit, kind="in_progress", assignee=ann)
    t_bob = sd.make_ticket(queue=unit, kind="in_progress", assignee=bob)
    t_free = sd.make_ticket(queue=unit, kind="new")
    t_free_closed = sd.make_ticket(queue=unit, kind="closed")
    base = {"preset": "all"}
    assert numbers(get(holder, {**base, "assignee": ann.pk})) == [t_ann.number]
    assert numbers(get(holder, {**base, "assignee": bob.pk})) == [t_bob.number]
    assert sorted(numbers(get(holder, {**base, "assignee": "none"}))) == sorted(open_numbers(t_free, t_free_closed))
    page = dom(get(holder, base))
    select = page.find_all("select", name="assignee")[0]
    assert any(o.attrs.get("value") == "" for o in select.find_all("option"))
    assert any(o.attrs.get("value") == "none" for o in select.find_all("option"))


def test_filter_by_client_unit_and_source():
    """FR-278: фильтры по подразделению заказчика и по источнику."""
    holder = holder_of_all()
    unit = make_marked_unit()
    ClientUnit = model("servicedesk.ClientUnit")
    dept_a = ClientUnit.objects.create(name="Бухгалтерия фильтр")
    dept_b = ClientUnit.objects.create(name="Склад фильтр")
    Source = model("servicedesk.Source")
    form, mail, phone = (Source.objects.get(system_code="form"), Source.objects.get(system_code="mail"),
                         Source.objects.get(name="Телефон"))
    t1 = sd.make_ticket(queue=unit, client_unit=dept_a, source=mail)
    t2 = sd.make_ticket(queue=unit, client_unit=dept_b, source=form)
    t3 = sd.make_ticket(queue=unit, client_unit=dept_a, source=phone)
    sd.make_ticket(queue=unit, source=mail)
    base = {"preset": "all"}
    assert sorted(numbers(get(holder, {**base, "client_unit": dept_a.pk}))) == sorted(open_numbers(t1, t3))
    assert numbers(get(holder, {**base, "client_unit": dept_b.pk})) == [t2.number]
    assert numbers(get(holder, {**base, "source": form.pk})) == [t2.number]
    assert numbers(get(holder, {**base, "source": phone.pk})) == [t3.number]
    assert numbers(get(holder, {**base, "source": phone.pk, "client_unit": dept_a.pk})) == [t3.number]


def test_filter_by_created_period_portal_date_field():
    """FR-278: период создания — поле даты портала, обе границы включительны, день — по Москве, два формата даты."""
    holder = holder_of_all()
    unit = make_marked_unit()
    before = sd.make_ticket(queue=unit, created_at=datetime(2026, 3, 9, 23, 59, 59, tzinfo=MSK))
    first = sd.make_ticket(queue=unit, created_at=datetime(2026, 3, 10, 0, 0, 0, tzinfo=MSK))
    last = sd.make_ticket(queue=unit, created_at=datetime(2026, 3, 11, 23, 59, 59, tzinfo=MSK))
    after = sd.make_ticket(queue=unit, created_at=datetime(2026, 3, 12, 0, 0, 0, tzinfo=MSK))
    base = {"preset": "all"}
    expected = sorted(open_numbers(first, last))
    assert sorted(numbers(get(holder, {**base, "created_from": "10.03.2026", "created_to": "11.03.2026"}))) == expected
    assert sorted(numbers(get(holder, {**base, "created_from": "2026-03-10", "created_to": "2026-03-11"}))) == expected
    assert sorted(numbers(get(holder, {**base, "created_from": "11.03.2026"}))) == sorted(open_numbers(last, after))
    assert sorted(numbers(get(holder, {**base, "created_to": "10.03.2026"}))) == sorted(open_numbers(before, first))
    page = dom(get(holder, {**base, "created_from": "10.03.2026"}))
    for name in ("created_from", "created_to"):
        field = page.find_all("input", name=name)[0]
        assert field.inside(data_datefield=True), name


def test_filters_combine_with_and():
    """FR-278: условия фильтра сочетаются через «и» (очередь, вид, ответственный, поиск вместе)."""
    from apps.servicedesk.services import search

    holder = holder_of_all()
    queue_a, queue_b = make_marked_unit(), make_marked_unit()
    ann = member_of(queue_a)
    spec = [
        (queue_a, "in_progress", ann, "Принтер не печатает"),   # подходит всем условиям
        (queue_b, "in_progress", ann, "Принтер не печатает"),   # чужая очередь
        (queue_a, "new", ann, "Принтер не печатает"),           # другой вид
        (queue_a, "in_progress", None, "Принтер не печатает"),  # другой ответственный
        (queue_a, "in_progress", ann, "Монитор мигает"),        # не находится поиском
    ]
    tickets = [sd.make_ticket(queue=q, kind=k, assignee=a, subject=s) for q, k, a, s in spec]
    for ticket in tickets:
        search.rebuild(ticket)
    params = {"preset": "all", "queue": queue_a.pk, "kind": "in_progress", "assignee": ann.pk, "q": "принтер"}
    assert numbers(get(holder, params)) == [tickets[0].number]
    assert sorted(numbers(get(holder, {"preset": "all", "queue": queue_a.pk, "q": "принтер"}))) == sorted(
        open_numbers(tickets[0], tickets[2], tickets[3]))


# --- сортировка -------------------------------------------------------------------------------------

def test_sort_default_new_on_top_by_number():
    """FR-279: по умолчанию — по номеру, новые сверху; `dir=asc` переворачивает; заголовок отмечен `aria-sort`."""
    holder = holder_of_all()
    unit = make_marked_unit()
    # номера не совпадают с порядком создания: сортировка именно по номеру
    for number in (7, 12, 5, 9):
        sd.make_ticket(queue=unit, number=number)
    response = get(holder, {"preset": "all"})
    assert numbers(response) == [12, 9, 7, 5]
    assert numbers(get(holder, {"preset": "all", "sort": "number", "dir": "asc"})) == [5, 7, 9, 12]
    assert numbers(get(holder, {"preset": "all", "sort": "unknown-column"})) == [12, 9, 7, 5]
    th = dom(response).find_all("th", data_sort="number")[0]
    assert th.attrs.get("aria-sort") == "descending"
    th_asc = dom(get(holder, {"preset": "all", "sort": "number", "dir": "asc"})).find_all("th", data_sort="number")[0]
    assert th_asc.attrs.get("aria-sort") == "ascending"


def test_sort_by_created_at_and_last_message():
    """FR-279: сортировка по дате создания и по последнему сообщению, в обе стороны."""
    holder = holder_of_all()
    unit = make_marked_unit()
    base = datetime(2026, 5, 1, 12, 0, tzinfo=MSK)
    day = lambda n: base.replace(day=n)  # noqa: E731
    # создана: №1 — 3-го, №2 — 1-го, №3 — 2-го; последнее сообщение: №1 — 2-го, №2 — 3-го, №3 — 1-го
    sd.make_ticket(queue=unit, number=1, created_at=day(3), last_message_at=day(2))
    sd.make_ticket(queue=unit, number=2, created_at=day(1), last_message_at=day(3))
    sd.make_ticket(queue=unit, number=3, created_at=day(2), last_message_at=day(1))
    base_params = {"preset": "all"}
    assert numbers(get(holder, {**base_params, "sort": "created", "dir": "desc"})) == [1, 3, 2]
    assert numbers(get(holder, {**base_params, "sort": "created", "dir": "asc"})) == [2, 3, 1]
    assert numbers(get(holder, {**base_params, "sort": "last_message", "dir": "desc"})) == [2, 1, 3]
    assert numbers(get(holder, {**base_params, "sort": "last_message", "dir": "asc"})) == [3, 1, 2]
    th = dom(get(holder, {**base_params, "sort": "last_message", "dir": "asc"})).find_all("th", data_sort="last_message")[0]
    assert th.attrs.get("aria-sort") == "ascending"
    assert th.find_all("a", href=True)


def test_sort_by_criticality_dictionary_order_then_number():
    """FR-279: критичность — по порядку справочника (`order`), затем по номеру; направление общее."""
    holder = holder_of_all()
    unit = make_marked_unit()
    Priority = model("servicedesk.Priority")
    # порядок справочника не совпадает ни с алфавитом, ни с номером строки
    urgent = Priority.objects.create(name="Б-срочная", order=25)
    low, medium, high = priority_named("Низкая"), priority_named("Средняя"), priority_named("Высокая")
    plan = [(1, high), (2, medium), (3, low), (4, high), (5, urgent), (6, medium), (7, low)]
    for number, priority in plan:
        sd.make_ticket(queue=unit, number=number, priority=priority)
    assert numbers(get(holder, {"preset": "all", "sort": "priority", "dir": "desc"})) == [4, 1, 5, 6, 2, 7, 3]
    assert numbers(get(holder, {"preset": "all", "sort": "priority", "dir": "asc"})) == [3, 7, 2, 6, 5, 1, 4]


# --- страницы и счётчик -----------------------------------------------------------------------------

def test_page_has_50_rows_and_next_page_by_51st_row():
    """FR-276, FR-279: страница — 50 строк; «следующая» есть, только если найдена 51-я строка; «Страница N»."""
    holder = holder_of_all()
    unit = make_marked_unit()
    for number in range(1, 52):
        sd.make_ticket(queue=unit, number=number)
    client = support.logged_in(holder)
    first = client.get("/tickets/", {"preset": "all"})
    assert numbers(first) == list(range(51, 1, -1))
    page = dom(first)
    assert page.find_all("a", data_action="page-next")
    assert not page.find_all("a", data_action="page-prev")
    assert "Страница 1" in page.find_all(None, data_page=True)[0].text()
    second = client.get("/tickets/", {"preset": "all", "page": "2"})
    assert numbers(second) == [1]
    page2 = dom(second)
    assert not page2.find_all("a", data_action="page-next")
    assert page2.find_all("a", data_action="page-prev")
    assert "Страница 2" in page2.find_all(None, data_page=True)[0].text()
    assert numbers(client.get("/tickets/", {"preset": "all", "page": "abc"})) == numbers(first)
    assert numbers(client.get("/tickets/", {"preset": "all", "page": "0"})) == numbers(first)
    beyond = client.get("/tickets/", {"preset": "all", "page": "3"})
    assert beyond.status_code == 200
    assert numbers(beyond) == []
    # ровно 50 строк: 51-й нет — «следующей» страницы нет
    model("servicedesk.Ticket").objects.filter(number=1).delete()
    exact = client.get("/tickets/", {"preset": "all"})
    assert len(numbers(exact)) == 50
    assert not dom(exact).find_all("a", data_action="page-next")


def test_total_count_only_on_show_count_button():
    """FR-276: общего числа в сетке нет; кнопка «показать количество» ведёт на `/tickets/count/` с теми же
    параметрами, ответ — `[data-total]` с числом по фильтру и только видимые."""
    from apps.servicedesk.services import listing

    unit, foreign = make_marked_unit(), make_marked_unit()
    me = member_of(unit)
    for kind in ("new", "new", "in_progress", "waiting", "closed"):
        sd.make_ticket(queue=unit, kind=kind)
    sd.make_ticket(queue=foreign, kind="new")
    client = support.logged_in(me)
    params = {"preset": "all", "kind": "new"}
    grid = client.get("/tickets/", params)
    assert not dom(grid).find_all(None, data_total=True)
    button = dom(grid).find_all("a", data_action="show-count")[0]
    assert button.attrs["hx-get"].startswith("/tickets/count/")
    assert "preset=all" in button.attrs["hx-get"] and "kind=new" in button.attrs["hx-get"]
    counted = client.get("/tickets/count/", params)
    assert counted.status_code == 200
    totals = dom(counted).find_all(None, data_total=True)
    assert len(totals) == 1
    assert re.findall(r"\d+", totals[0].text()) == ["2"]
    whole = client.get("/tickets/count/", {"preset": "all"})
    assert re.findall(r"\d+", dom(whole).find_all(None, data_total=True)[0].text()) == ["5"]
    assert listing.count(me, preset="all") == 5
    outsider = support.make_employee()
    assert get(outsider, {"preset": "all"}, path="/tickets/count/").status_code == 403
