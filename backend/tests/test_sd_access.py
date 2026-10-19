"""T-3101: доступ к заявкам и участники очередей (FR-228, FR-231, FR-232, FR-233, FR-234, FR-236, FR-275).

Сценарии 8 и 15 спеки среза 003. Узлы работы (`structure.work_units_of`, `structure.queue_people`), служба
`access` (`visible_tickets`, `can_work`, `eligible_assignees`, `menu_visible`, `can_create`), 404 на чужую заявку
(одинаковый с несуществующим номером) и права `servicedesk.all`, `servicedesk.manage`. Код среза на уровне модуля
не импортируется: имена берутся внутри тестов (CONTRACT-003, шапка).
"""
import re
from html.parser import HTMLParser

import pytest

from tests import factories, support
from tests import support_org as org
from tests import support_servicedesk as sd
from tests.support import HX, model

pytestmark = pytest.mark.django_db

FOREIGN_NUMBER = 4711
MISSING_NUMBER = 4812


# --- разбор разметки (помощник только этого файла) -------------------------------------------------

class _Page(HTMLParser):
    """Собирает начальные теги (с признаком «внутри nav#main-menu») и текст элементов с зацепкой `data-skipped`."""

    def __init__(self):
        super().__init__()
        self.tags = []          # (тег, словарь атрибутов, внутри_меню)
        self.skipped = []       # тексты элементов li[data-skipped]
        self._in_menu = False
        self._skip = None       # [глубина, части текста]
        self._depth_li = 0

    def handle_starttag(self, tag, attrs):
        a = {k: (v if v is not None else "") for k, v in attrs}
        if tag == "nav" and a.get("id") == "main-menu":
            self._in_menu = True
        self.tags.append((tag, a, self._in_menu))
        if self._skip is not None and tag == "li":
            self._depth_li += 1
        if tag == "li" and "data-skipped" in a and self._skip is None:
            self._skip, self._depth_li = [], 1

    def handle_endtag(self, tag):
        if tag == "nav":
            self._in_menu = False
        if self._skip is not None and tag == "li":
            self._depth_li -= 1
            if self._depth_li == 0:
                self.skipped.append(" ".join(" ".join(self._skip).split()))
                self._skip = None

    def handle_data(self, data):
        if self._skip is not None:
            self._skip.append(data)


def _page(response) -> _Page:
    parser = _Page()
    parser.feed(response.content.decode("utf-8", "replace"))
    return parser


def _menu_has_tickets(response) -> bool:
    """`#main-menu a.menu-item[href="/tickets/"]` (CONTRACT-003 § 13.5)."""
    return any(tag == "a" and a.get("href") == "/tickets/" and "menu-item" in a.get("class", "").split() and inside
               for tag, a, inside in _page(response).tags)


def _has_new_button(response) -> bool:
    """`a[data-action="ticket-new"]` (§ 13)."""
    return any(tag == "a" and a.get("data-action") == "ticket-new" for tag, a, _ in _page(response).tags)


def _shape(response, number) -> tuple:
    """Ответ без токена CSRF и пробелов; номер заявки в теле заменён меткой (общее тело 404)."""
    status, location, body = support.normalized(response)
    return status, location.replace(str(number), "N"), body.replace(str(number), "N")


def _assert_same_as_missing(foreign, missing, number_foreign, number_missing, what):
    assert foreign.status_code == 404, f"{what}: чужая заявка должна дать 404, получили {foreign.status_code}"
    assert missing.status_code == 404, f"{what}: несуществующий номер должен дать 404, получили {missing.status_code}"
    assert _shape(foreign, number_foreign) == _shape(missing, number_missing), (
        f"{what}: ответ для чужой заявки отличается от ответа для несуществующего номера")


# --- данные теста ------------------------------------------------------------------------------------

def _member(unit, *, mark: str = "", name: str | None = None, state: str = "active"):
    """Сотрудник и его членство в узле."""
    user = support.make_employee(full_name=name, state=state) if name else support.make_employee(state=state)
    org.make_member(user, unit, mark=mark)
    return user


def _numbers(queryset) -> set[int]:
    return set(queryset.values_list("number", flat=True))


def _fresh(user):
    """Свежий объект пользователя: результат `access.scope` лежит в атрибуте объекта (контракт 6.3)."""
    return model("core.User").objects.get(pk=user.pk)


def _setup_queue_with_ticket(**ticket_over):
    """Очередь, её узел и заявка в ней."""
    queue = sd.make_queue()
    return queue, sd.make_ticket(queue=queue, **ticket_over)


def _outsider_with_own_queue():
    """Участник другой очереди: меню «Заявки» у него есть, чужие заявки — нет. Возвращает (пользователь, очередь)."""
    queue = sd.make_queue()
    user = _member(queue.unit)
    return user, queue


def _stored_attachment(ticket, root):
    """Принятое вложение (файл `clean`, `owner=None`) со строкой `Attachment` и файлом в `attachments/<id>`."""
    StoredFile, Attachment = model("core.StoredFile"), model("servicedesk.Attachment")
    stored = StoredFile.objects.create(
        purpose="attachment", owner=None, size=5, sha256="0" * 64, content_type="text/plain", status="clean")
    folder = root / "attachments"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / str(stored.id)).write_bytes(b"hello")
    entry = sd.make_entry(ticket, "comment", text="с файлом")
    Attachment.objects.create(ticket=ticket, entry=entry, file=stored, name="a.txt", size=5,
                              created_at=stored.created_at)
    return stored


def _source_mail(ticket, root):
    """Входящее письмо заявки с файлом `inbound/<id>.eml`."""
    inbound = sd.make_inbound(ticket=ticket, status="processed", outcome="created")
    folder = root / "inbound"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{inbound.pk}.eml").write_bytes(b"From: a@example.com\r\n\r\ntext\r\n")
    return inbound


# --- структура: узлы работы и участники очереди ---------------------------------------------------

def test_work_units_of_direct_member_and_concurrent_member_get_all_their_units():
    """FR-231, FR-232: узлы человека — все, где он состоит, в том числе совместителем; чужих и корня нет."""
    from apps.org.services import membership, structure

    tree = org.make_tree({"Сеть": {}, "Поддержка": {}, "Чужой": {}})
    team = org.make_unit("Дежурные", kind="team", parent=tree["Сеть"])
    user = support.make_employee()
    admin = support.make_admin()
    org.make_member(user, tree["Сеть"])
    membership.add_members(tree["Поддержка"], [user], mode=membership.CONCURRENT, actor=admin)
    org.make_member(user, team)
    assert structure.work_units_of(_fresh(user)) == frozenset({tree["Сеть"].pk, tree["Поддержка"].pk, team.pk})


def test_work_units_of_head_and_deputy_include_all_nested_units():
    """FR-232: руководитель и заместитель получают свой узел и все вложенные (на любую глубину, команды тоже)."""
    from apps.org.services import structure

    tree = org.make_tree({"Сеть": {"Серверы": {"team:Дежурные": {}}, "Связь": {}}, "Поддержка": {"Линия": {}},
                          "Чужой": {"Вложенный": {}}})
    head = _member(tree["Сеть"], mark="head")
    deputy = _member(tree["Поддержка"], mark="deputy")
    assert structure.work_units_of(_fresh(head)) == frozenset(
        {tree["Сеть"].pk, tree["Серверы"].pk, tree["Дежурные"].pk, tree["Связь"].pk})
    assert structure.work_units_of(_fresh(deputy)) == frozenset({tree["Поддержка"].pk, tree["Линия"].pk})


def test_work_units_of_nested_member_does_not_include_parent_unit():
    """FR-232: участник вложенного узла вышестоящего узла не получает; рядовой участник не получает и вложенные."""
    from apps.org.services import structure

    tree = org.make_tree({"Сеть": {"Серверы": {"Стойки": {}}}})
    nested = _member(tree["Серверы"])
    units = structure.work_units_of(_fresh(nested))
    assert units == frozenset({tree["Серверы"].pk})
    assert tree["Сеть"].pk not in units and tree["Стойки"].pk not in units


def test_work_units_of_dismissed_employee_is_empty():
    """FR-232: уволенный (и тот, кто нигде не состоит) — пустой набор, даже если запись членства осталась."""
    from apps.org.services import structure

    tree = org.make_tree({"Сеть": {"Серверы": {}}})
    gone = _member(tree["Сеть"], mark="head")
    model("core.User").objects.filter(pk=gone.pk).update(state="dismissed")
    assert structure.work_units_of(_fresh(gone)) == frozenset()
    assert structure.work_units_of(_fresh(support.make_employee())) == frozenset()


def test_queue_people_members_plus_upper_heads_and_deputies_unique_sorted_without_dismissed():
    """FR-232: участники узла и руководители, заместители вышестоящих; без повторов и уволенных; по ФИО, затем id."""
    from apps.org.services import structure

    tree = org.make_tree({"Верх": {"Середина": {"Очередь": {}}, "Рядом": {}}})
    queue_unit, middle, top, near = tree["Очередь"], tree["Середина"], tree["Верх"], tree["Рядом"]
    yakovlev = _member(queue_unit, name="Яковлев Яков")
    andreev = _member(queue_unit, name="Андреев Андрей")
    borisov = _member(middle, mark="head", name="Борисов Борис")
    vasilev = _member(top, mark="deputy", name="Васильев Василий")
    grigorev = _member(queue_unit, name="Григорьев Георгий")
    org.make_member(grigorev, top, mark="head")  # и участник узла, и руководитель вышестоящего: один раз
    twin1 = _member(queue_unit, name="Зайцев Захар")
    twin2 = _member(queue_unit, name="Зайцев Захар")
    _member(queue_unit, name="Дмитриев Дмитрий", state="dismissed")
    _member(top, name="Егоров Егор")            # рядовой участник вышестоящего узла — не входит
    _member(near, mark="head", name="Жуков Жук")  # руководитель соседнего узла — не входит
    people = structure.queue_people(queue_unit.pk)
    first, second = sorted([twin1.pk, twin2.pk])
    assert [p.id for p in people] == [andreev.pk, borisov.pk, vasilev.pk, grigorev.pk, first, second, yakovlev.pk]
    assert len({p.id for p in people}) == len(people)
    assert structure.queue_people(10 ** 9) == []


# --- права «Все заявки» -----------------------------------------------------------------------------

def test_all_tickets_right_makes_employee_participant_of_every_queue():
    """FR-233: держатель `servicedesk.all` — участник любой очереди и узла, без членства; другие — нет."""
    from apps.core.services import permissions
    from apps.servicedesk.services import access

    queue = sd.make_queue()
    plain_unit = org.make_unit()
    holder = support.make_with_permissions("servicedesk.all")
    other = support.make_employee()
    assert access.is_participant(_fresh(holder), queue.unit_id) is True
    assert access.is_participant(_fresh(holder), plain_unit.pk) is True
    assert access.scope(_fresh(holder)).has_all is True
    assert access.is_participant(_fresh(other), queue.unit_id) is False
    assert holder.pk in [u.pk for u in permissions.users_with("servicedesk.all")]
    assert other.pk not in [u.pk for u in permissions.users_with("servicedesk.all")]


# --- видимость заявок -------------------------------------------------------------------------------

def test_visible_tickets_only_own_queues_and_own_assigned():
    """FR-234: видны заявки очередей человека и заявки, где он ответственный; больше ничьи; держатель «Все» видит всё."""
    from apps.servicedesk.services import access

    queue_a, queue_b, queue_c = sd.make_queue(), sd.make_queue(), sd.make_queue()
    user = _member(queue_a.unit)
    a1, a2 = sd.make_ticket(queue=queue_a), sd.make_ticket(queue=queue_a)
    b_foreign = sd.make_ticket(queue=queue_b)
    b_mine = sd.make_ticket(queue=queue_b, assignee=user)
    c_foreign = sd.make_ticket(queue=queue_c)
    assert _numbers(access.visible_tickets(_fresh(user))) == {a1.number, a2.number, b_mine.number}
    assert not _numbers(access.visible_tickets(_fresh(support.make_employee())))
    holder = support.make_with_permissions("servicedesk.all")
    assert _numbers(access.visible_tickets(_fresh(holder))) == {
        t.number for t in (a1, a2, b_foreign, b_mine, c_foreign)}


def test_assignee_sees_ticket_of_foreign_queue():
    """FR-234: ответственный видит заявку чужой очереди и может с ней работать; остальные заявки той очереди — нет."""
    from apps.servicedesk.services import access

    queue = sd.make_queue()
    user = support.make_employee()
    mine = sd.make_ticket(queue=queue, assignee=user)
    other = sd.make_ticket(queue=queue)
    me = _fresh(user)
    assert _numbers(access.visible_tickets(me)) == {mine.number}
    assert access.can_work(me, mine) is True
    assert access.can_work(me, other) is False
    client = support.logged_in(user)
    assert client.get(f"/tickets/{mine.number}/").status_code == 200
    assert client.get(f"/tickets/{other.number}/").status_code == 404


def test_head_and_deputy_see_and_work_with_nested_queue_tickets():
    """FR-232, FR-234: руководитель и заместитель видят и ведут заявки вложенных очередей (в том числе глубже)."""
    from apps.servicedesk.services import access

    tree = org.make_tree({"Сеть": {"Серверы": {"Стойки": {}}}, "Чужой": {}})
    queue_child = sd.make_queue(tree["Серверы"])
    queue_deep = sd.make_queue(tree["Стойки"])
    queue_alien = sd.make_queue(tree["Чужой"])
    child_ticket = sd.make_ticket(queue=queue_child)
    deep_ticket = sd.make_ticket(queue=queue_deep)
    alien_ticket = sd.make_ticket(queue=queue_alien)
    head = _member(tree["Сеть"], mark="head")
    deputy = _member(tree["Сеть"], mark="deputy")
    for person in (head, deputy):
        me = _fresh(person)
        assert _numbers(access.visible_tickets(me)) == {child_ticket.number, deep_ticket.number}
        assert access.can_work(me, child_ticket) is True and access.can_work(me, alien_ticket) is False
        assert access.is_participant(me, queue_deep.unit_id) is True
    client = support.logged_in(head)
    assert client.get(f"/tickets/{deep_ticket.number}/").status_code == 200
    assert client.get(f"/tickets/{alien_ticket.number}/").status_code == 404


def test_rank_and_file_of_parent_unit_does_not_see_nested_queue_tickets():
    """FR-232, FR-234: рядовой участник вышестоящего узла заявок вложенной очереди не видит, своей очереди — видит."""
    from apps.servicedesk.services import access

    tree = org.make_tree({"Сеть": {"Серверы": {}}})
    queue_parent = sd.make_queue(tree["Сеть"])
    queue_child = sd.make_queue(tree["Серверы"])
    parent_ticket = sd.make_ticket(queue=queue_parent)
    child_ticket = sd.make_ticket(queue=queue_child)
    user = _member(tree["Сеть"])
    me = _fresh(user)
    assert _numbers(access.visible_tickets(me)) == {parent_ticket.number}
    assert access.can_work(me, child_ticket) is False
    assert access.is_participant(me, queue_child.unit_id) is False
    assert support.logged_in(user).get(f"/tickets/{child_ticket.number}/").status_code == 404


def test_nested_team_member_does_not_see_parent_queue_tickets():
    """FR-232, FR-234: участник вложенной команды заявок очереди вышестоящего узла не видит; своей команды — видит."""
    from apps.servicedesk.services import access

    tree = org.make_tree({"Сеть": {"team:Дежурные": {}}})
    queue_parent = sd.make_queue(tree["Сеть"])
    queue_team = sd.make_queue(tree["Дежурные"])
    parent_ticket = sd.make_ticket(queue=queue_parent)
    team_ticket = sd.make_ticket(queue=queue_team)
    user = _member(tree["Дежурные"])
    me = _fresh(user)
    assert _numbers(access.visible_tickets(me)) == {team_ticket.number}
    assert access.can_work(me, parent_ticket) is False
    assert support.logged_in(user).get(f"/tickets/{parent_ticket.number}/").status_code == 404


# --- 404 на чужую заявку (FR-236) --------------------------------------------------------------------

def test_foreign_ticket_page_404_same_as_missing_number():
    """FR-236: карточка чужой заявки — 404 с тем же телом, что у несуществующего номера; своя открывается."""
    outsider, own_queue = _outsider_with_own_queue()
    foreign = sd.make_ticket(queue=sd.make_queue(), number=FOREIGN_NUMBER)
    mine = sd.make_ticket(queue=own_queue)
    client = support.logged_in(outsider)
    assert client.get(f"/tickets/{mine.number}/").status_code == 200
    for extra in ({}, HX):
        _assert_same_as_missing(client.get(f"/tickets/{foreign.number}/", **extra),
                                client.get(f"/tickets/{MISSING_NUMBER}/", **extra),
                                foreign.number, MISSING_NUMBER, "карточка")


def test_foreign_ticket_attachment_download_404_same_as_missing(protected_root):
    """FR-236: файл чужой заявки (принятый) не выдаётся — 404, как у несуществующего номера; члену очереди выдаётся."""
    outsider, own_queue = _outsider_with_own_queue()
    foreign_queue = sd.make_queue()
    foreign = sd.make_ticket(queue=foreign_queue, number=FOREIGN_NUMBER)
    stored = _stored_attachment(foreign, protected_root)
    member = _member(foreign_queue.unit)
    granted = support.logged_in(member).get(f"/tickets/{foreign.number}/files/{stored.id}/")
    assert granted.status_code == 200 and granted["X-Accel-Redirect"] == f"/protected/attachments/{stored.id}"
    client = support.logged_in(outsider)
    _assert_same_as_missing(client.get(f"/tickets/{foreign.number}/files/{stored.id}/"),
                            client.get(f"/tickets/{MISSING_NUMBER}/files/{stored.id}/"),
                            foreign.number, MISSING_NUMBER, "вложение")


def test_foreign_ticket_source_email_404_same_as_missing(protected_root):
    """FR-236: исходное письмо чужой заявки не выдаётся — 404, как у несуществующего номера; члену очереди выдаётся."""
    outsider, own_queue = _outsider_with_own_queue()
    foreign_queue = sd.make_queue()
    foreign = sd.make_ticket(queue=foreign_queue, number=FOREIGN_NUMBER)
    inbound = _source_mail(foreign, protected_root)
    member = _member(foreign_queue.unit)
    granted = support.logged_in(member).get(f"/tickets/{foreign.number}/mail/{inbound.pk}.eml")
    assert granted.status_code == 200 and granted["X-Accel-Redirect"] == f"/protected/inbound/{inbound.pk}.eml"
    client = support.logged_in(outsider)
    _assert_same_as_missing(client.get(f"/tickets/{foreign.number}/mail/{inbound.pk}.eml"),
                            client.get(f"/tickets/{MISSING_NUMBER}/mail/{inbound.pk}.eml"),
                            foreign.number, MISSING_NUMBER, "исходное письмо")


def _snapshot(foreign):
    """Состояние всех заявок и число всех элементов ленты чужой заявки — для сравнения «до/после» (FR-236)."""
    tickets = sorted(model("servicedesk.Ticket").objects.values_list(
        "number", "assignee_id", "queue_id", "kind", "priority_id", "status_id", "requester_name"))
    return tickets, model("servicedesk.TicketEntry").objects.filter(ticket=foreign).count()


def test_every_ticket_action_route_404_for_foreign_ticket_same_as_missing():
    """FR-236: каждый маршрут действия над чужой заявкой даёт тот же 404, что и несуществующий номер; свой — не 404."""
    outsider, own_queue = _outsider_with_own_queue()
    foreign_queue = sd.make_queue()
    foreign = sd.make_ticket(queue=foreign_queue, number=FOREIGN_NUMBER)
    own = sd.make_ticket(queue=own_queue)
    entry = sd.make_entry(foreign, "reply", text="ответ")
    participant = sd.make_participant(foreign)
    other_queue = sd.make_queue()
    priority = model("servicedesk.Priority").objects.first()
    status = model("servicedesk.Status").objects.filter(kind="in_progress").first()
    closing = model("servicedesk.Status").objects.filter(kind="closed").first()
    routes = [
        ("get", "/", {}),
        ("post", "take/", {}),
        ("get", "assignees/", {"q": "а"}),
        ("post", "assign/", {"assignee": str(outsider.pk)}),
        ("get", "transfer/", {}),
        ("post", "transfer/", {"queue": str(other_queue.unit_id), "reason": "r"}),
        ("post", "category/", {"category": "1", "confirm": "1"}),
        ("post", "fields/", {"priority": str(priority.pk)}),
        ("post", "status/", {"status": str(status.pk)}),
        ("post", "reply/", {"text": "текст"}),
        ("post", f"reply/{entry.pk}/resend/", {}),
        ("post", "comment/", {"text": "заметка"}),
        ("get", "close/", {}),
        ("post", "close/", {"status": str(closing.pk), "resolution": "готово"}),
        ("post", "reopen/", {}),
        ("get", f"participants/{participant.pk}/remove/", {}),
        ("post", f"participants/{participant.pk}/remove/", {"confirm": "1"}),
    ]
    client = support.logged_in(outsider)
    # свою заявку действия не отвергают как «нет такой»: проверяем на чтении карточки и на диалоге передачи
    assert client.get(f"/tickets/{own.number}/").status_code == 200
    assert client.get(f"/tickets/{own.number}/transfer/").status_code == 200
    for method, tail, data in routes:
        suffix = "" if tail == "/" else tail
        call = getattr(client, method)
        before = _snapshot(foreign)
        responses = []
        for number in (foreign.number, MISSING_NUMBER):
            path = f"/tickets/{number}/{suffix}"
            responses.append(call(path, data))
        _assert_same_as_missing(responses[0], responses[1], foreign.number, MISSING_NUMBER, f"{method.upper()} {tail}")
        assert before == _snapshot(foreign), f"{method.upper()} {tail}: заявки изменились"
    assert not model("servicedesk.TicketEntry").objects.filter(ticket=foreign, kind="comment").exists()


def test_group_action_checks_access_of_each_ticket_separately():
    """FR-236: групповое действие применяется к видимым заявкам, чужие и несуществующие пропускаются как «нет доступа»
    без номера в ответе."""
    user, own_queue = _outsider_with_own_queue()
    mine = sd.make_ticket(queue=own_queue)
    foreign = sd.make_ticket(queue=sd.make_queue(), number=FOREIGN_NUMBER)
    high = model("servicedesk.Priority").objects.get(name_key=org.name_key("Высокая"))
    before_foreign = foreign.priority_id
    client = support.logged_in(user)
    response = client.post("/tickets/bulk/", {"action": "priority", "numbers": [mine.number, foreign.number,
                                                                                 MISSING_NUMBER],
                                              "priority": str(high.pk)}, **HX)
    assert response.status_code == 200
    mine.refresh_from_db()
    foreign.refresh_from_db()
    assert mine.priority_id == high.pk
    assert foreign.priority_id == before_foreign
    html = response.content.decode()
    assert "data-bulk-result" in html
    assert re.search(r"Выполнено:\s*1;\s*пропущено:\s*2", html)
    skipped = _page(response).skipped
    assert len(skipped) == 2 and all("нет доступа" in text for text in skipped)
    for number in (FOREIGN_NUMBER, MISSING_NUMBER):
        assert not re.search(rf"(?<!\w){number}(?!\w)", html), f"номер {number} недоступной заявки раскрыт"


# --- меню, заявитель, ответственные -------------------------------------------------------------------

def test_menu_item_tickets_visible_to_participant_all_holder_or_assignee_only():
    """FR-234: пункт «Заявки» (и `/tickets/`) — у участника очереди, держателя «Все» и ответственного; у остальных нет."""
    from apps.servicedesk.services import access

    queue = sd.make_queue()
    plain_unit = org.make_unit()  # узел без отметки очереди
    tree = org.make_tree({"Верх": {"Низ": {}}})
    sd.make_queue(tree["Низ"])
    participant = _member(queue.unit)
    holder = support.make_with_permissions("servicedesk.all")
    assignee = support.make_employee()
    sd.make_ticket(queue=sd.make_queue(), assignee=assignee)
    head_above_queue = _member(tree["Верх"], mark="head")
    member_without_queue = _member(plain_unit)
    nobody = support.make_employee()
    for user in (participant, holder, assignee, head_above_queue):
        client = support.logged_in(user)
        page = client.get("/me/")
        assert page.status_code == 200 and _menu_has_tickets(page), f"{user.full_name}: пункта «Заявки» нет"
        assert client.get("/tickets/").status_code == 200
        assert access.menu_visible(_fresh(user)) is True
    for user in (member_without_queue, nobody):
        client = support.logged_in(user)
        page = client.get("/me/")
        assert page.status_code == 200 and not _menu_has_tickets(page), "пункт «Заявки» виден без доступа"
        assert client.get("/tickets/").status_code == 403
        assert access.menu_visible(_fresh(user)) is False


def test_requester_and_copy_participant_have_no_portal_access():
    """FR-234: заявитель и участник из копии учётных записей не имеют: вход — общий отказ, `/tickets/` — на вход."""
    queue = sd.make_queue()
    requester = sd.make_requester()
    ticket = sd.make_ticket(queue=queue, requester=requester)
    copy = sd.make_participant(ticket)
    User = model("core.User")
    assert not User.objects.filter(email__in=[requester.email, copy.email]).exists()
    password = factories.new_password()
    unknown = support.make_client().post("/login/", {"email": factories.new_email("none"), "password": password})
    for address in (requester.email, copy.email):
        response = support.make_client().post("/login/", {"email": address, "password": password})
        assert response.status_code == 200, "вход заявителя должен дать общий отказ"
        assert support.same_failure(response, unknown), "отказ для заявителя отличается от отказа неизвестному адресу"
    anonymous = support.make_client().get("/tickets/")
    assert anonymous.status_code == 302 and anonymous["Location"].startswith("/login/")


def test_eligible_assignees_queue_people_plus_all_holders_without_dismissed():
    """FR-232, FR-233: кандидаты в ответственные — участники очереди и держатели «Все» без уволенных и повторов."""
    from apps.servicedesk.services import access

    tree = org.make_tree({"Верх": {"Очередь": {}}, "Чужой": {}})
    queue = sd.make_queue(tree["Очередь"])
    member = _member(tree["Очередь"], name="Яковлев Яков")
    head_above = _member(tree["Верх"], mark="head", name="Борисов Борис")
    holder_member = support.make_with_permissions("servicedesk.all", full_name="Андреев Андрей")
    org.make_member(holder_member, tree["Очередь"])  # и участник, и держатель: один раз
    holder = support.make_with_permissions("servicedesk.all", full_name="Васильев Василий")
    _member(tree["Очередь"], name="Дмитриев Дмитрий", state="dismissed")
    support.make_with_permissions("servicedesk.all", full_name="Егоров Егор", state="dismissed")
    _member(tree["Чужой"], name="Жуков Жук")
    people = access.eligible_assignees(queue.unit_id)
    assert [p.id for p in people] == [holder_member.pk, head_above.pk, holder.pk, member.pk]


# --- права ---------------------------------------------------------------------------------------------

def test_all_tickets_and_manage_rights_only_for_portal_admin_after_install():
    """FR-233, FR-275: после установки оба права есть у «Администратора портала» (пятнадцать кодов), у остальных нет."""
    from apps.core.services import roles
    from tests.support_kb import PERMISSIONS_005
    from tests.support_notify import PERMISSIONS_004

    Permission, Role = model("core.Permission"), model("core.Role")
    assert Permission.objects.get(code="servicedesk.all").title == "Все заявки"
    assert Permission.objects.get(code="servicedesk.manage").title == "Настройка сервис-деска"
    admin = support.role_by_name(support.ADMIN_ROLE)
    assert set(roles.permission_codes(admin)) == set(
        support.PERMISSIONS + support.PERMISSIONS_002 + sd.PERMISSIONS_003 + PERMISSIONS_004 + PERMISSIONS_005)
    assert len(roles.permission_codes(admin)) == 15
    for name in (support.MANAGER_ROLE, support.STAFF_ROLE):
        assert not set(roles.permission_codes(support.role_by_name(name))) & set(sd.PERMISSIONS_003), name
    holders = Role.objects.filter(permissions__code__in=sd.PERMISSIONS_003).distinct()
    assert [r.name for r in holders] == [support.ADMIN_ROLE]


def test_all_tickets_right_granted_to_new_role_and_revoked_without_code(django_capture_on_commit_callbacks):
    """FR-233: право «Все заявки» выдаётся новой роли и снимается правкой роли, без изменения кода; доступ — со
    следующего запроса."""
    from apps.core.services import roles

    admin = support.make_admin()
    ticket = sd.make_ticket(queue=sd.make_queue())
    employee = support.make_employee()
    client = support.logged_in(employee)
    assert client.get(f"/tickets/{ticket.number}/").status_code == 404
    with django_capture_on_commit_callbacks(execute=True):
        role = roles.create_role("Диспетчер заявок", ["servicedesk.all"], actor=admin)
        roles.set_user_roles(employee, [role], actor=admin)
    assert client.get(f"/tickets/{ticket.number}/").status_code == 200
    assert client.get("/tickets/").status_code == 200
    with django_capture_on_commit_callbacks(execute=True):
        roles.update_role(role, role.name, [], actor=admin)
    assert client.get(f"/tickets/{ticket.number}/").status_code == 404
    assert client.get("/tickets/").status_code == 403


# --- доступ меняется со следующего запроса ----------------------------------------------------------

def test_access_changes_with_next_request_after_transfer(django_capture_on_commit_callbacks):
    """FR-232: после перевода сотрудника в другой отдел очереди доступ меняется со следующего запроса того же клиента."""
    from apps.org.services import membership, structure

    tree = org.make_tree({"Сеть": {}, "Поддержка": {}})
    queue_a, queue_b = sd.make_queue(tree["Сеть"]), sd.make_queue(tree["Поддержка"])
    ticket_a, ticket_b = sd.make_ticket(queue=queue_a), sd.make_ticket(queue=queue_b)
    user = _member(tree["Сеть"])
    client = support.logged_in(user)
    assert client.get(f"/tickets/{ticket_a.number}/").status_code == 200
    assert client.get(f"/tickets/{ticket_b.number}/").status_code == 404
    assert structure.work_units_of(_fresh(user)) == frozenset({tree["Сеть"].pk})
    with django_capture_on_commit_callbacks(execute=True):
        assert membership.transfer_member(user, tree["Сеть"], tree["Поддержка"], actor=support.make_admin()) is True
    assert structure.work_units_of(_fresh(user)) == frozenset({tree["Поддержка"].pk})
    assert client.get(f"/tickets/{ticket_a.number}/").status_code == 404
    assert client.get(f"/tickets/{ticket_b.number}/").status_code == 200


def test_access_changes_with_next_request_after_unit_move_and_marks_change(django_capture_on_commit_callbacks):
    """FR-232: снятие и возвращение отметки руководителя, затем перенос узла-очереди — доступ меняется со следующего
    запроса того же клиента."""
    from apps.org.services import membership, structure

    tree = org.make_tree({"Сеть": {"Серверы": {}}, "Другой": {}})
    queue = sd.make_queue(tree["Серверы"])
    ticket = sd.make_ticket(queue=queue)
    admin = support.make_admin()
    head = _member(tree["Сеть"], mark="head")
    client = support.logged_in(head)
    assert client.get(f"/tickets/{ticket.number}/").status_code == 200
    with django_capture_on_commit_callbacks(execute=True):
        membership.set_marks(tree["Сеть"], heads=[], actor=admin)
    assert client.get(f"/tickets/{ticket.number}/").status_code == 404, "отметка снята, а заявка ещё видна"
    with django_capture_on_commit_callbacks(execute=True):
        membership.set_marks(tree["Сеть"], heads=[head], actor=admin)
    assert client.get(f"/tickets/{ticket.number}/").status_code == 200, "отметка возвращена, а заявки нет"
    with django_capture_on_commit_callbacks(execute=True):
        structure.move_unit(tree["Серверы"], tree["Другой"], actor=admin)
    assert client.get(f"/tickets/{ticket.number}/").status_code == 404, "очередь перенесена, а заявка ещё видна"
    with django_capture_on_commit_callbacks(execute=True):
        structure.move_unit(tree["Серверы"], tree["Сеть"], actor=admin)
    assert client.get(f"/tickets/{ticket.number}/").status_code == 200


def test_non_participant_has_no_new_ticket_button_and_direct_request_refused():
    """FR-228, FR-234, FR-236: ответственный по заявке чужой очереди видит пункт меню, но кнопки «Новая заявка» нет, а
    `/tickets/new/` — 403 (и на GET, и на POST); участнику очереди — кнопка и форма."""
    from apps.servicedesk.services import access

    foreign_queue = sd.make_queue()
    user = support.make_employee()
    sd.make_ticket(queue=foreign_queue, assignee=user)
    client = support.logged_in(user)
    listing = client.get("/tickets/")
    assert listing.status_code == 200 and not _has_new_button(listing)
    assert client.get("/tickets/new/").status_code == 403
    tickets_before = model("servicedesk.Ticket").objects.count()
    assert client.post("/tickets/new/", {"email": factories.new_email("req"), "name": "Имя", "subject": "Тема",
                                         "text": "Текст", "queue": str(foreign_queue.unit_id)}).status_code == 403
    assert model("servicedesk.Ticket").objects.count() == tickets_before
    assert access.can_create(_fresh(user)) is False
    member = _member(foreign_queue.unit)
    member_client = support.logged_in(member)
    assert _has_new_button(member_client.get("/tickets/"))
    assert member_client.get("/tickets/new/").status_code == 200
    assert access.can_create(_fresh(member)) is True
