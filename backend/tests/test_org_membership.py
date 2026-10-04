"""T-2102: членство и отметки (FR-110…114, FR-123, FR-127, FR-150). Сценарии 2 и 3 спеки среза 002."""
import re
from html.parser import HTMLParser

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from tests import factories, support
from tests import support_org as org
from tests.support import HX, model

pytestmark = pytest.mark.django_db

IP = "198.51.100.9"
_VOID = {"input", "br", "img", "hr", "meta", "link", "area", "base", "col", "source", "wbr"}


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
        """Элементы (в том числе сам) с тегом `tag` и атрибутами `want` (`data_x` -> `data-x`; True — любое значение)."""
        wanted = {key.replace("_", "-"): value for key, value in want.items()}
        found = []
        for el in self.walk():
            if tag is not None and el.tag != tag:
                continue
            if all(name in el.attrs and (value is True or el.attrs[name] == str(value)) for name, value in wanted.items()):
                found.append(el)
        return found


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
    builder.feed(response.content.decode("utf-8", "replace") if hasattr(response, "content") else response)
    return builder.root


def alert_text(response) -> str:
    return " ".join(el.text() for el in dom(response).find_all(None, role="alert")).lower()


def status_text(response) -> str:
    return " ".join(el.text() for el in dom(response).find_all(None, role="status")).lower()


# --- данные -------------------------------------------------------------------------------------

def manager():
    """Сотрудник с правами на структуру: просмотр и управление."""
    return support.make_with_permissions("staff.view", "org.manage", full_name="Управляющий Структурой")


def person(name: str, **extra):
    return support.make_employee(full_name=name, **extra)


def unit_names(user) -> list[str]:
    return sorted(model("org.Membership").objects.filter(user=user).values_list("unit__name", flat=True))


def mark_of(user, unit) -> str | None:
    found = model("org.Membership").objects.filter(user=user, unit=unit).first()
    return None if found is None else found.mark


def by_path(*units) -> list[str]:
    return [u.name for u in sorted(units, key=lambda u: u.path)]


def user_events(user, prefix: str = "membership.") -> list:
    return list(model("core.AuditEvent").objects.filter(
        object_type="user", object_id=str(user.pk), action__startswith=prefix).order_by("id"))


def all_events() -> int:
    return model("core.AuditEvent").objects.count()


def events_except_logins() -> int:
    """События журнала без входов: `support.logged_in` сам пишет `login.success` (срез 001, login.py)."""
    return model("core.AuditEvent").objects.exclude(action="login.success").count()


def warm_permission_cache(user) -> None:
    from apps.core.services import permissions

    permissions.permissions_of(user)
    assert support.valkey_key(f"perms:{user.pk}"), "кэш прав не наполнился"


def card(client, unit, **extra):
    return client.get(f"/structure/{unit.pk}/", **HX, **extra)


def member_row(root: _El, user):
    rows = root.find_all(None, data_member=True, data_user_id=user.pk)
    assert len(rows) == 1, f"в карточке нет строки участника {user.pk}"
    return rows[0]


# --- тесты --------------------------------------------------------------------------------------

def test_add_to_department_transfer_mode_leaves_teams(django_capture_on_commit_callbacks):
    """FR-110 (сц. 2, п. 1): режим «перевести» снимает членства во всех других отделах, команды остаются;
    события — removed (по path), added, один transferred; ключ прав добавленного сброшен на фиксации."""
    from apps.org.services import membership

    t = org.make_tree({"Сеть": {"team:Дежурные": {}}, "Отдел Б": {}, "Поддержка": {}})
    admin, user = manager(), person("Анна Первая")
    for name in ("Сеть", "Отдел Б", "Дежурные"):
        org.make_member(user, t[name])
    warm_permission_cache(user)
    with django_capture_on_commit_callbacks(execute=True):
        result = membership.add_members(t["Поддержка"], [user], mode=membership.TRANSFER, actor=admin, ip=IP)
    assert result.added == [user] and result.already == []
    assert unit_names(user) == ["Дежурные", "Поддержка"], "отделы сняты, команда осталась, новый отдел добавлен"
    assert not support.valkey_key(f"perms:{user.pk}"), "ключ perms:<id> после добавления не сброшен"
    events = user_events(user)
    assert [e.action for e in events] == [
        "membership.removed", "membership.removed", "membership.added", "membership.transferred"]
    removed = events[:2]
    assert [e.before["unit"] for e in removed] == by_path(t["Сеть"], t["Отдел Б"])
    assert all(e.before["reason"] == "transfer" and e.actor_id == admin.pk and e.ip == IP for e in removed)
    assert events[2].after["unit"] == "Поддержка" and events[2].after["mode"] == "transfer"
    assert events[2].after["unit_id"] == t["Поддержка"].pk
    assert events[3].before["units"] == by_path(t["Сеть"], t["Дежурные"], t["Отдел Б"])
    assert events[3].after["units"] == by_path(t["Дежурные"], t["Поддержка"])
    # тот же режим со страницы: форма «Добавить сотрудников»
    other = person("Борис Второй")
    org.make_member(other, t["Сеть"])
    client = support.logged_in(admin)
    with django_capture_on_commit_callbacks(execute=True):
        done = client.post(f"/structure/{t['Поддержка'].pk}/members/", {"users": [other.pk], "mode": "transfer"})
    assert done.status_code == 302 and done["Location"].endswith(f"/structure/{t['Поддержка'].pk}/")
    assert unit_names(other) == ["Поддержка"]
    assert [e.action for e in user_events(other)] == [
        "membership.removed", "membership.added", "membership.transferred"]
    # смешанный набор: один уже участник, другой новый
    fresh = person("Виктор Третий")
    with django_capture_on_commit_callbacks(execute=True):
        mixed = membership.add_members(t["Поддержка"], [other, fresh], mode=membership.CONCURRENT, actor=admin)
    assert mixed.added == [fresh] and mixed.already == [other]


def test_add_as_concurrent_keeps_all_units(django_capture_on_commit_callbacks):
    """FR-110 (сц. 2, п. 2): режим «совместитель» ничего не снимает и пишет только added; режим обязателен для отдела."""
    from apps.org.services import OrgError, membership

    t = org.make_tree({"Сеть": {"team:Дежурные": {}}, "Поддержка": {}})
    admin, user = manager(), person("Анна Первая")
    org.make_member(user, t["Сеть"])
    org.make_member(user, t["Дежурные"])
    with django_capture_on_commit_callbacks(execute=True):
        result = membership.add_members(t["Поддержка"], [user], mode=membership.CONCURRENT, actor=admin, ip=IP)
    assert result.added == [user] and result.already == []
    assert unit_names(user) == ["Дежурные", "Поддержка", "Сеть"]
    events = user_events(user)
    assert [e.action for e in events] == ["membership.added"], "совместительство не пишет removed и transferred"
    assert events[0].after["mode"] == "concurrent" and events[0].after["unit"] == "Поддержка"
    assert events[0].after["mark"] == ""
    # режим — только transfer или concurrent: None и чужое значение отказывают, ничего не добавляя
    newcomer = person("Вера Новая")
    before = all_events()
    for bad in (None, "both", ""):
        with pytest.raises(OrgError) as refused:
            membership.add_members(t["Поддержка"], [newcomer], mode=bad, actor=admin)
        assert refused.value.code == "bad_mode", f"mode={bad!r}"
    assert unit_names(newcomer) == [] and all_events() == before
    client = support.logged_in(admin)
    wrong = client.post(f"/structure/{t['Поддержка'].pk}/members/", {"users": [newcomer.pk]})
    assert wrong.status_code == 200 and alert_text(wrong), "отдел без режима: 200 с [role=alert]"
    assert unit_names(newcomer) == []
    with django_capture_on_commit_callbacks(execute=True):
        done = client.post(f"/structure/{t['Поддержка'].pk}/members/", {"users": [newcomer.pk], "mode": "concurrent"})
    assert done.status_code == 302 and unit_names(newcomer) == ["Поддержка"]


def test_add_to_team_has_no_mode(django_capture_on_commit_callbacks):
    """FR-110 (сц. 2): в команду добавляют без режима; режим игнорируется; в карточке команды поля режима нет."""
    from apps.org.services import membership

    t = org.make_tree({"Сеть": {"team:Дежурные": {}}, "Поддержка": {}})
    admin = manager()
    first, second = person("Анна Первая"), person("Борис Второй")
    org.make_member(first, t["Сеть"])
    org.make_member(second, t["Сеть"])
    with django_capture_on_commit_callbacks(execute=True):
        membership.add_members(t["Дежурные"], [first], actor=admin, ip=IP)
        membership.add_members(t["Дежурные"], [second], mode=membership.TRANSFER, actor=admin, ip=IP)
    for user in (first, second):
        assert unit_names(user) == ["Дежурные", "Сеть"], "в команду человек добавляется, из отдела не уходит"
        events = user_events(user)
        assert [e.action for e in events] == ["membership.added"]
        assert events[0].after["mode"] == "" and events[0].after["unit"] == "Дежурные"
    client = support.logged_in(admin)
    team_card = dom(card(client, t["Дежурные"]))
    team_form = team_card.find_all("form", data_form="members-add")
    assert len(team_form) == 1 and not team_form[0].find_all("select", name="mode"), "у команды выбора режима нет"
    dept_form = dom(card(client, t["Поддержка"])).find_all("form", data_form="members-add")
    modes = dept_form[0].find_all("select", name="mode")
    assert len(modes) == 1
    assert {o.attrs.get("value") for o in modes[0].find_all("option")} >= {"transfer", "concurrent"}
    third = person("Галина Третья")
    with django_capture_on_commit_callbacks(execute=True):
        done = client.post(f"/structure/{t['Дежурные'].pk}/members/", {"users": [third.pk]})
    assert done.status_code == 302 and unit_names(third) == ["Дежурные"]


def test_repeated_add_creates_no_second_membership_and_says_already_member(django_capture_on_commit_callbacks):
    """FR-110 (сц. 2, п. 7): повторное добавление в любом режиме не создаёт второго членства и не пишет событий; страница говорит «уже участник»."""
    from apps.org.services import membership

    t = org.make_tree({"Сеть": {"team:Дежурные": {}}})
    admin, user = manager(), person("Анна Первая")
    Membership = model("org.Membership")
    with django_capture_on_commit_callbacks(execute=True):
        membership.add_members(t["Сеть"], [user], mode=membership.CONCURRENT, actor=admin)
        membership.add_members(t["Дежурные"], [user], actor=admin)
    events_before = events_except_logins()
    for mode in (membership.CONCURRENT, membership.TRANSFER):
        with django_capture_on_commit_callbacks(execute=True):
            again = membership.add_members(t["Сеть"], [user], mode=mode, actor=admin)
        assert again.added == [] and again.already == [user], f"режим {mode}"
    with django_capture_on_commit_callbacks(execute=True):
        again = membership.add_members(t["Дежурные"], [user], actor=admin)
    assert again.added == [] and again.already == [user]
    assert Membership.objects.filter(user=user, unit=t["Сеть"]).count() == 1
    assert unit_names(user) == ["Дежурные", "Сеть"], "режим «перевести» при повторе не снимает прочих членств"
    assert events_except_logins() == events_before, "повторное добавление ничего не пишет в журнал"
    # страница: 302 и сообщение «уже участник» в [role=status] следующей страницы
    client = support.logged_in(admin)
    done = client.post(f"/structure/{t['Сеть'].pk}/members/", {"users": [user.pk], "mode": "concurrent"})
    assert done.status_code == 302 and done["Location"].endswith(f"/structure/{t['Сеть'].pk}/")
    assert "уже участник" in status_text(client.get(done["Location"]))
    assert Membership.objects.filter(user=user, unit=t["Сеть"]).count() == 1 and events_except_logins() == events_before


def test_member_menu_transfer_same_kind_remove_and_dismiss_items(django_capture_on_commit_callbacks):
    """FR-111 (сц. 2, п. 5): меню «…» участника — перевести (в узел того же вида), удалить, уволить; подписи отдела и команды; перевод в узел другого вида отказан."""
    from apps.org.services import OrgError, membership

    t = org.make_tree({"Сеть": {"team:Дежурные": {}, "team:Резерв": {}}, "Поддержка": {}, "Эксплуатация": {}})
    admin, user = manager(), person("Анна Первая")
    org.make_member(user, t["Сеть"])
    org.make_member(user, t["Дежурные"])
    client = support.logged_in(admin)

    def menu_of(unit):
        row = member_row(dom(card(client, unit)), user)
        menus = row.find_all("details", data_member_menu=True)
        assert len(menus) == 1, "в строке участника нет меню «…»"
        assert menus[0].find_all("summary", data_member_menu_button=True, aria_label="Действия")
        items = {}
        for name in ("transfer", "remove", "dismiss"):
            found = menus[0].find_all(None, data_menu_item=name)
            assert len(found) == 1, f"нет пункта {name}"
            items[name] = found[0]
        return items

    dept = menu_of(t["Сеть"])
    assert "перевести в другой отдел" in dept["transfer"].text().lower()
    assert "удалить из отдела" in dept["remove"].text().lower()
    assert "уволить" in dept["dismiss"].text().lower()
    transfer_form = dept["transfer"].find_all("form", action=f"/structure/{t['Сеть'].pk}/members/{user.pk}/transfer/")
    assert len(transfer_form) == 1 and transfer_form[0].attrs.get("method", "post").lower() == "post"
    targets = {o.attrs.get("value") for o in transfer_form[0].find_all("select", name="target")[0].find_all("option")}
    assert {str(t["Поддержка"].pk), str(t["Эксплуатация"].pk)} <= targets, "цели — другие отделы"
    assert not targets & {str(t["Дежурные"].pk), str(t["Резерв"].pk)}, "команд среди целей отдела нет"
    assert dept["remove"].find_all("form", action=f"/structure/{t['Сеть'].pk}/members/{user.pk}/remove/")
    assert dept["dismiss"].find_all("a", hx_get=f"/structure/people/{user.pk}/dismiss/")

    team = menu_of(t["Дежурные"])
    assert "перевести в другую команду" in team["transfer"].text().lower()
    assert "удалить из команды" in team["remove"].text().lower()
    assert "уволить" in team["dismiss"].text().lower()
    team_form = team["transfer"].find_all("form", action=f"/structure/{t['Дежурные'].pk}/members/{user.pk}/transfer/")
    team_targets = {o.attrs.get("value") for o in team_form[0].find_all("select", name="target")[0].find_all("option")}
    assert str(t["Резерв"].pk) in team_targets
    assert not team_targets & {str(t["Поддержка"].pk), str(t["Эксплуатация"].pk), str(t["Сеть"].pk)}

    # другой вид — отказ службы и страницы, ничего не меняется
    before = all_events()
    with pytest.raises(OrgError) as refused:
        membership.transfer_member(user, t["Сеть"], t["Резерв"], actor=admin)
    assert refused.value.code == "kind_mismatch"
    with pytest.raises(OrgError) as refused:
        membership.transfer_member(user, t["Дежурные"], t["Поддержка"], actor=admin)
    assert refused.value.code == "kind_mismatch"
    wrong = client.post(f"/structure/{t['Сеть'].pk}/members/{user.pk}/transfer/", {"target": t["Резерв"].pk})
    assert wrong.status_code == 200 and alert_text(wrong)
    assert unit_names(user) == ["Дежурные", "Сеть"] and all_events() == before
    # тот же вид — перевод; удаление — только это членство
    with django_capture_on_commit_callbacks(execute=True):
        moved = client.post(f"/structure/{t['Сеть'].pk}/members/{user.pk}/transfer/", {"target": t["Поддержка"].pk})
    assert moved["Location"].endswith(f"/structure/{t['Сеть'].pk}/") and moved.status_code == 302
    assert unit_names(user) == ["Дежурные", "Поддержка"]
    with django_capture_on_commit_callbacks(execute=True):
        removed = client.post(f"/structure/{t['Дежурные'].pk}/members/{user.pk}/remove/")
    assert removed.status_code == 302 and removed["Location"].endswith(f"/structure/{t['Дежурные'].pk}/")
    assert unit_names(user) == ["Поддержка"]


def test_transfer_from_one_of_two_departments_keeps_other(django_capture_on_commit_callbacks):
    """FR-111 (сц. 2, п. 4): перевод из первого отдела в третий оставляет второй; цель, где человек уже состоит, — False и тишина."""
    from apps.org.services import membership

    t = org.make_tree({"Первый": {}, "Второй": {}, "Третий": {}})
    admin, user = manager(), person("Анна Первая")
    org.make_member(user, t["Первый"])
    org.make_member(user, t["Второй"])
    warm_permission_cache(user)
    with django_capture_on_commit_callbacks(execute=True):
        done = membership.transfer_member(user, t["Первый"], t["Третий"], actor=admin, ip=IP)
    assert done is True
    assert unit_names(user) == ["Второй", "Третий"]
    assert not support.valkey_key(f"perms:{user.pk}"), "ключ прав переведённого не сброшен на фиксации"
    events = user_events(user)
    assert [e.action for e in events] == ["membership.removed", "membership.added", "membership.transferred"]
    assert events[0].before["unit"] == "Первый" and events[0].before["reason"] == "transfer"
    assert events[1].after["unit"] == "Третий" and events[1].after["mode"] == "transfer"
    assert events[2].before["units"] == by_path(t["Первый"], t["Второй"])
    assert events[2].after["units"] == by_path(t["Второй"], t["Третий"])
    # цель, где человек уже состоит: ничего не меняется, событий нет
    before = events_except_logins()
    with django_capture_on_commit_callbacks(execute=True):
        again = membership.transfer_member(user, t["Второй"], t["Третий"], actor=admin)
    assert again is False
    assert unit_names(user) == ["Второй", "Третий"] and events_except_logins() == before
    # узел, где человека нет: not_member, ничего не меняется и не пишется
    from apps.org.services import OrgError
    stranger = person("Игорь Посторонний")
    for run in (lambda: membership.remove_member(stranger, t["Первый"], actor=admin),
                lambda: membership.transfer_member(stranger, t["Первый"], t["Третий"], actor=admin)):
        with django_capture_on_commit_callbacks(execute=True), pytest.raises(OrgError) as absent:
            run()
        assert absent.value.code == "not_member"
    assert unit_names(user) == ["Второй", "Третий"] and unit_names(stranger) == [] and events_except_logins() == before
    # страница: 302 и «уже участник», членства прежние
    client = support.logged_in(admin)
    done = client.post(f"/structure/{t['Второй'].pk}/members/{user.pk}/transfer/", {"target": t["Третий"].pk})
    assert done.status_code == 302
    assert "уже участник" in status_text(client.get(done["Location"]))
    assert unit_names(user) == ["Второй", "Третий"] and events_except_logins() == before


def test_member_without_unit_allowed_found_by_preset(django_capture_on_commit_callbacks):
    """FR-112 (сц. 2, п. 3): сотрудник без подразделения допустим и находится пресетом «Без подразделения»; уволенные в него не попадают."""
    from apps.org.services import membership

    t = org.make_tree({"Сеть": {}})
    admin, viewer = manager(), support.make_with_permissions("staff.view")
    lone, kept = person("Анна Одинокая"), person("Борис Состоящий")
    fresh = person("Вера Новая")
    gone = person("Глеб Уволенный", state="dismissed")
    org.make_member(lone, t["Сеть"])
    org.make_member(kept, t["Сеть"])
    with django_capture_on_commit_callbacks(execute=True):
        membership.remove_member(lone, t["Сеть"], actor=admin, ip=IP)
    lone.refresh_from_db()
    assert lone.state == "active" and unit_names(lone) == [], "после удаления из узла сотрудник остаётся в портале"
    event = user_events(lone)[0]
    assert event.action == "membership.removed" and event.before["reason"] == "manual"
    assert event.before["unit"] == "Сеть" and event.before["unit_id"] == t["Сеть"].pk
    client = support.logged_in(viewer)
    listed = client.get("/staff/", {"state": "no_unit"})
    assert listed.status_code == 200
    ids = {int(r.attrs["data-user-id"]) for r in dom(listed).find_all("tr", data_user_id=True)}
    assert lone.pk in ids and fresh.pk in ids, "без подразделения: и удалённый из узла, и никогда не состоявший"
    assert kept.pk not in ids and gone.pk not in ids
    preset = dom(listed).find_all("a", data_preset="no_unit")
    assert preset and preset[0].attrs.get("aria-current") == "true"


def test_one_position_many_units_listed_by_comma():
    """FR-113 (сц. 2, п. 2): должность одна, подразделений несколько; в карточке они через запятую по path."""
    t = org.make_tree({"Сеть": {}, "Поддержка": {}})
    viewer = support.make_with_permissions("staff.view")
    user = person("Анна Первая", position="Инженер")
    org.make_member(user, t["Сеть"])
    org.make_member(user, t["Поддержка"])
    page = support.logged_in(viewer).get(f"/staff/{user.pk}/")
    assert page.status_code == 200
    root = dom(page)
    units = root.find_all(None, data_field="units")
    assert len(units) == 1 and units[0].text() == ", ".join(by_path(t["Сеть"], t["Поддержка"]))
    assert units[0].attrs.get("data-empty") == "false"
    position = root.find_all(None, data_field="position")
    assert len(position) == 1 and "Инженер" in position[0].text()
    user.refresh_from_db()
    assert user.position == "Инженер"


def test_marks_only_for_members_head_or_deputy_any_number_removing_one_keeps_other(django_capture_on_commit_callbacks):
    """FR-114, FR-150 (сц. 3, пп. 1, 6, 7): отметки — только участникам, любое число; снятие одной оставляет другую; событие «было / стало»; None набор не трогает."""
    from apps.org.services import OrgError, membership

    t = org.make_tree({"Сеть": {}})
    unit = t["Сеть"]
    admin = manager()
    a, b, c, d = (person(n) for n in ("Аркадий", "Борис", "Виктор", "Дмитрий"))
    outsider = person("Ярослав Посторонний")
    for user in (a, b, c, d):
        org.make_member(user, unit)
    Event = model("core.AuditEvent")

    def marks_events():
        return list(Event.objects.filter(action="unit.marks_changed", object_id=str(unit.pk)).order_by("id"))

    with django_capture_on_commit_callbacks(execute=True):
        membership.set_marks(unit, heads=[a, b], deputies=[c, d], actor=admin, ip=IP)
    assert [mark_of(u, unit) for u in (a, b, c, d)] == ["head", "head", "deputy", "deputy"], "число отметок не ограничено"
    first = marks_events()
    assert len(first) == 1 and first[0].before.get("heads", []) == [] and first[0].before.get("deputies", []) == []
    assert first[0].after["heads"] == ["Аркадий", "Борис"] and first[0].after["deputies"] == ["Виктор", "Дмитрий"]
    # снять одного заместителя: второй остаётся, руководители не тронуты (None), в журнале «было / стало»
    with django_capture_on_commit_callbacks(execute=True):
        membership.set_marks(unit, deputies=[d], actor=admin, ip=IP)
    assert [mark_of(u, unit) for u in (a, b, c, d)] == ["head", "head", "", "deputy"]
    second = marks_events()[-1]
    assert second.before["deputies"] == ["Виктор", "Дмитрий"] and second.after["deputies"] == ["Дмитрий"]
    assert second.after["heads"] == ["Аркадий", "Борис"], "ключи before/after содержат оба набора"
    # то же значение — ничего не пишется
    count = len(marks_events())
    with django_capture_on_commit_callbacks(execute=True):
        membership.set_marks(unit, heads=[a, b], deputies=[d], actor=admin)
        membership.set_marks(unit, actor=admin)
    assert len(marks_events()) == count
    # не участник — отказ без изменений
    with pytest.raises(OrgError) as refused:
        membership.set_marks(unit, heads=[outsider], actor=admin)
    assert refused.value.code == "not_member"
    assert [mark_of(u, unit) for u in (a, b, c, d)] == ["head", "head", "", "deputy"]
    assert mark_of(outsider, unit) is None and len(marks_events()) == count
    # пустой набор снимает всех руководителей
    with django_capture_on_commit_callbacks(execute=True):
        membership.set_marks(unit, heads=[], actor=admin)
    assert [mark_of(u, unit) for u in (a, b, c, d)] == ["", "", "", "deputy"]

    # страница: формы шлют part и users; метка в строке участника; отказ — [role=alert]
    client = support.logged_in(admin)
    with django_capture_on_commit_callbacks(execute=True):
        done = client.post(f"/structure/{unit.pk}/marks/", {"part": "heads", "users": [a.pk]})
    assert done.status_code == 302 and done["Location"].endswith(f"/structure/{unit.pk}/")
    assert mark_of(a, unit) == "head" and mark_of(d, unit) == "deputy", "другой набор не меняется"
    with django_capture_on_commit_callbacks(execute=True):
        client.post(f"/structure/{unit.pk}/marks/", {"part": "deputies"})
    assert mark_of(d, unit) == "", "ни одного users — набор пуст"
    count = len(marks_events())
    wrong = client.post(f"/structure/{unit.pk}/marks/", {"part": "heads", "users": [outsider.pk]})
    assert wrong.status_code == 200
    assert "руководителем и заместителем может быть только участник узла" in alert_text(wrong)
    assert mark_of(a, unit) == "head" and len(marks_events()) == count
    root = dom(card(client, unit))
    labels = member_row(root, a).find_all(None, data_mark_label=True)
    assert len(labels) == 1 and labels[0].text().lower() == "руководитель"
    assert member_row(root, a).attrs.get("data-mark") == "head" and member_row(root, b).attrs.get("data-mark") == ""
    assert not member_row(root, b).find_all(None, data_mark_label=True)
    for name, part in (("marks-heads", "heads"), ("marks-deputies", "deputies")):
        forms = root.find_all("form", data_form=name)
        assert len(forms) == 1, f"нет формы {name}"
        parts = forms[0].find_all("input", name="part")
        assert parts and parts[0].attrs.get("value") == part and parts[0].attrs.get("type") == "hidden"


def test_head_then_deputy_in_same_unit_refused_not_replaced(django_capture_on_commit_callbacks):
    """FR-114 (сц. 3, п. 10): руководитель не становится заместителем молча; отказ и по сохранённому состоянию; сменить можно двумя вызовами."""
    from apps.org.services import OrgError, membership

    unit = org.make_tree({"Сеть": {}})["Сеть"]
    admin, a, b = manager(), person("Аркадий"), person("Борис")
    org.make_member(a, unit)
    org.make_member(b, unit)
    with django_capture_on_commit_callbacks(execute=True):
        membership.set_marks(unit, heads=[a], actor=admin)
    Event = model("core.AuditEvent")
    events_before = Event.objects.filter(action="unit.marks_changed").count()
    # заместителем тот, кто руководитель
    with pytest.raises(OrgError) as refused:
        membership.set_marks(unit, deputies=[a], actor=admin)
    assert refused.value.code == "head_and_deputy"
    # даже если тот же вызов снимает прежнюю отметку
    with pytest.raises(OrgError) as refused:
        membership.set_marks(unit, heads=[], deputies=[a], actor=admin)
    assert refused.value.code == "head_and_deputy"
    # итоговые наборы пересекаются
    with pytest.raises(OrgError) as refused:
        membership.set_marks(unit, heads=[b], deputies=[b], actor=admin)
    assert refused.value.code == "head_and_deputy"
    assert mark_of(a, unit) == "head" and mark_of(b, unit) == ""
    assert Event.objects.filter(action="unit.marks_changed").count() == events_before, "отказ ничего не пишет"
    # страница
    client = support.logged_in(admin)
    wrong = client.post(f"/structure/{unit.pk}/marks/", {"part": "deputies", "users": [a.pk]})
    assert wrong.status_code == 200
    assert "в одном узле человек либо руководитель, либо заместитель" in alert_text(wrong)
    assert mark_of(a, unit) == "head"
    # сменить можно только двумя действиями: снять, затем поставить
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(f"/structure/{unit.pk}/marks/", {"part": "heads"}).status_code == 302
        assert client.post(f"/structure/{unit.pk}/marks/", {"part": "deputies", "users": [a.pk]}).status_code == 302
    assert mark_of(a, unit) == "deputy"


def test_mark_removed_with_membership_on_transfer_remove_and_dismiss(django_capture_on_commit_callbacks):
    """FR-114 (сц. 3, п. 9): отметка уходит с членством при переводе, удалении, режиме «перевести» и увольнении и не возвращается; unit.marks_changed не пишется."""
    from apps.org.services import membership, people

    t = org.make_tree({"Отдел А": {}, "Отдел Б": {}, "Отдел В": {}, "Отдел Г": {}, "Отдел Д": {}})
    admin = manager()
    Event = model("core.AuditEvent")
    heads = {}
    for key in ("transfer", "remove", "mode", "dismiss"):
        heads[key] = person(f"Руководитель {key}")
    deputy = person("Заместитель remove")
    unit = t["Отдел А"]
    for user in (*heads.values(), deputy):
        org.make_member(user, unit)
    with django_capture_on_commit_callbacks(execute=True):
        membership.set_marks(unit, heads=list(heads.values()), deputies=[deputy], actor=admin)
    marks_changed = Event.objects.filter(action="unit.marks_changed").count()

    def removed_event(user):
        found = [e for e in user_events(user) if e.action == "membership.removed"]
        assert len(found) == 1
        return found[0]

    with django_capture_on_commit_callbacks(execute=True):
        membership.transfer_member(heads["transfer"], unit, t["Отдел Б"], actor=admin)
        membership.remove_member(heads["remove"], unit, actor=admin)
        membership.remove_member(deputy, unit, actor=admin)
        membership.add_members(t["Отдел В"], [heads["mode"]], mode=membership.TRANSFER, actor=admin)
        people.dismiss(heads["dismiss"], actor=admin)
    assert mark_of(heads["transfer"], unit) is None and mark_of(heads["transfer"], t["Отдел Б"]) == ""
    assert unit_names(heads["transfer"]) == ["Отдел Б"]
    assert unit_names(heads["remove"]) == [] and unit_names(deputy) == []
    assert unit_names(heads["mode"]) == ["Отдел В"] and mark_of(heads["mode"], t["Отдел В"]) == ""
    assert unit_names(heads["dismiss"]) == []
    assert model("org.Membership").objects.filter(unit=unit).count() == 0, "в узле не осталось ни участников, ни отметок"
    expected = {"transfer": ("head", "transfer"), "remove": ("head", "manual"), "mode": ("head", "transfer"),
                "dismiss": ("head", "dismissal")}
    for key, (mark, reason) in expected.items():
        event = removed_event(heads[key])
        assert event.before["mark"] == mark and event.before["reason"] == reason, key
        assert event.before["unit"] == "Отдел А"
    assert removed_event(deputy).before["mark"] == "deputy"
    assert Event.objects.filter(action="unit.marks_changed").count() == marks_changed, (
        "снятие отметки вместе с членством unit.marks_changed не пишет")
    # вернулся в тот же узел — прежняя отметка не восстанавливается
    with django_capture_on_commit_callbacks(execute=True):
        membership.add_members(unit, [heads["remove"]], mode=membership.CONCURRENT, actor=admin)
    assert mark_of(heads["remove"], unit) == ""


def test_candidates_exclude_dismissed():
    """FR-110, FR-127 (сц. 2, п. 8): подсказки идут из accounts.pickable и не содержат уволенных; не больше 20; заблокированные и приглашённые есть."""
    from apps.core.services import accounts
    from apps.org.services import OrgError, membership

    t = org.make_tree({"Сеть": {}})
    unit = t["Сеть"]
    admin = manager()
    active = person("Алексей Активный")
    invited = person("Алла Приглашённая", state="invited", totp=False)
    blocked = person("Анатолий Блокированный", state="blocked")
    gone = person("Андрей Уволенный", state="dismissed")
    yo = person("Артём Ёлкин", position="Тестировщик")
    ids = {u.pk for u in (active, invited, blocked, yo)}
    picked = list(accounts.pickable(""))
    assert gone not in picked and ids <= {u.pk for u in picked}
    mine = [u.full_name for u in picked if u.pk in ids]
    assert mine == ["Алексей Активный", "Алла Приглашённая", "Анатолий Блокированный", "Артём Ёлкин"], "порядок по full_name"
    assert gone not in accounts.pickable("Андрей") and active in accounts.pickable("активн")
    assert yo in accounts.pickable("артем") and yo in accounts.pickable("тестировщик")
    assert yo in accounts.pickable(yo.email.upper())
    # уволенный в пачке — отказ всей пачки, никто не добавлен
    with pytest.raises(OrgError) as refused:
        membership.add_members(unit, [active, gone], mode=membership.CONCURRENT, actor=admin)
    assert refused.value.code == "dismissed_user" and unit_names(active) == []

    client = support.logged_in(admin)
    found = client.get(f"/structure/{unit.pk}/candidates/", {"q": "Ан"})
    assert found.status_code == 200 and b"<html" not in found.content.lower(), "подсказки — всегда фрагмент"
    shown = {int(e.attrs["data-user-id"]) for e in dom(found).find_all(None, data_candidate=True, data_user_id=True)}
    assert blocked.pk in shown and gone.pk not in shown
    shown_all = {int(e.attrs["data-user-id"]) for e in dom(
        client.get(f"/structure/{unit.pk}/candidates/")).find_all(None, data_candidate=True, data_user_id=True)}
    assert {active.pk, invited.pk, blocked.pk, yo.pk} <= shown_all and gone.pk not in shown_all
    yo_found = dom(client.get(f"/structure/{unit.pk}/candidates/", {"q": "ЕЛКИН"})).find_all(None, data_candidate=True)
    assert yo_found, "поиск без учёта регистра и «е/ё»"
    # не больше 20 подсказок
    User = model("core.User")
    User.objects.bulk_create([
        User(email=factories.new_email("many"), full_name=f"Массовый {i:02d}", state="active") for i in range(25)])
    capped = dom(client.get(f"/structure/{unit.pk}/candidates/", {"q": "Массовый"})).find_all(None, data_candidate=True)
    assert len(capped) == 20
    expected = [u.pk for u in sorted(User.objects.filter(full_name__startswith="Массовый"),
                                     key=lambda u: (u.full_name, u.pk))][:20]
    assert [int(e.attrs["data-user-id"]) for e in capped] == expected, "первые 20 по (full_name, id)"
    # страница: добавление уволенного отказано целиком
    refused = client.post(f"/structure/{unit.pk}/members/", {"users": [active.pk, gone.pk], "mode": "concurrent"})
    assert refused.status_code == 200 and alert_text(refused)
    assert unit_names(active) == [] and unit_names(gone) == []
    # в форме добавления есть поле поиска с запросом подсказок
    form = dom(card(client, unit)).find_all("form", data_form="members-add")[0]
    search = form.find_all("input", name="q")
    assert search and search[0].attrs.get("hx-get") == f"/structure/{unit.pk}/candidates/"
    assert form.find_all(None, data_candidates=True)


def test_membership_changes_lock_root_row(django_capture_on_commit_callbacks):
    """FR-110: добавление, перевод, удаление и отметки берут `FOR UPDATE` строки корня org_unit — прямым вызовом и через страницу."""
    from apps.org.services import membership

    def locks(sqls) -> int:
        return sum(1 for q in sqls if 'FROM "org_unit"' in q and "FOR UPDATE" in q.upper()
                   and re.search(r'WHERE\s+"org_unit"\."is_root"', q))

    t = org.make_tree({"Первый": {}, "Второй": {}, "Третий": {}})
    admin = manager()
    a, b, c = person("Аркадий"), person("Борис"), person("Виктор")
    for user in (a, b, c):
        org.make_member(user, t["Первый"])
    operations = {
        "add_members": lambda: membership.add_members(t["Второй"], [a], mode=membership.CONCURRENT, actor=admin),
        "transfer_member": lambda: membership.transfer_member(b, t["Первый"], t["Третий"], actor=admin),
        "remove_member": lambda: membership.remove_member(c, t["Первый"], actor=admin),
        "set_marks": lambda: membership.set_marks(t["Второй"], heads=[a], actor=admin),
    }
    for name, run in operations.items():
        with django_capture_on_commit_callbacks(execute=True), CaptureQueriesContext(connection) as captured:
            run()
        assert locks([q["sql"] for q in captured.captured_queries]), f"{name}: нет FOR UPDATE по корню org_unit"

    # через страницу: перехватчик запросов
    seen: list[str] = []

    def spy(execute, sql, params, many, context):
        seen.append(str(sql))
        return execute(sql, params, many, context)

    d, e, f, g = person("Дмитрий"), person("Елена"), person("Фёдор"), person("Галина")
    for user in (d, e, f):
        org.make_member(user, t["Первый"])
    client = support.logged_in(admin)
    posts = {
        "members": (f"/structure/{t['Второй'].pk}/members/", {"users": [g.pk], "mode": "concurrent"}),
        "transfer": (f"/structure/{t['Первый'].pk}/members/{d.pk}/transfer/", {"target": t["Третий"].pk}),
        "remove": (f"/structure/{t['Первый'].pk}/members/{e.pk}/remove/", {}),
        "marks": (f"/structure/{t['Первый'].pk}/marks/", {"part": "heads", "users": [f.pk]}),
    }
    for name, (path, data) in posts.items():
        seen.clear()
        with django_capture_on_commit_callbacks(execute=True), connection.execute_wrapper(spy):
            response = client.post(path, data)
        assert response.status_code == 302, name
        assert locks(seen), f"{name}: страница не берёт FOR UPDATE по корню org_unit"


def test_membership_and_marks_need_org_manage(django_capture_on_commit_callbacks):
    """FR-123 (сц. 2, п. 6): без права «Управление структурой» нет меню, «Добавить сотрудников», режимов и отметок, а прямые запросы — 403 (до проверки объекта)."""
    t = org.make_tree({"Сеть": {}, "Поддержка": {}})
    unit, other = t["Сеть"], t["Поддержка"]
    user, newcomer = person("Анна Первая"), person("Борис Второй")
    org.make_member(user, unit)
    viewer = support.make_with_permissions("staff.view")
    accounts_only = support.make_with_permissions("staff.view", "accounts.manage", "roles.manage")
    manager_user = manager()
    Membership = model("org.Membership")
    snapshot = sorted(Membership.objects.values_list("user_id", "unit_id", "mark"))
    events_before = events_except_logins()
    requests = [
        ("get", f"/structure/{unit.pk}/candidates/", {}),
        ("post", f"/structure/{unit.pk}/members/", {"users": [newcomer.pk], "mode": "concurrent"}),
        ("post", f"/structure/{unit.pk}/members/{user.pk}/transfer/", {"target": other.pk}),
        ("post", f"/structure/{unit.pk}/members/{user.pk}/remove/", {}),
        ("post", f"/structure/{unit.pk}/marks/", {"part": "heads", "users": [user.pk]}),
    ]
    anonymous = support.make_client()
    for method, path, data in requests:
        response = getattr(anonymous, method)(path, data)
        assert response.status_code == 302 and "/login/" in response["Location"], f"без входа: {path}"
    for who in (viewer, accounts_only):
        client = support.logged_in(who)
        for method, path, data in requests:
            assert getattr(client, method)(path, data).status_code == 403, f"{path} у {who.email}"
        gone = [("post", f"/structure/999999/members/", {"users": [newcomer.pk], "mode": "concurrent"}),
                ("post", f"/structure/999999/marks/", {"part": "heads"}),
                ("get", f"/structure/999999/candidates/", {})]
        for method, path, data in gone:
            assert getattr(client, method)(path, data).status_code == 403, "право проверяется раньше существования узла"
        root = dom(card(client, unit))
        assert member_row(root, user)
        for hook in ({"data_member_menu": True}, {"data_menu_item": True}, {"data_action": "members-add"},
                     {"data_action": "marks-heads"}, {"data_action": "marks-deputies"},
                     {"data_form": "members-add"}):
            assert not root.find_all(None, **hook), f"без права на странице есть {hook}"
        assert not root.find_all("select", name="mode")
    assert sorted(Membership.objects.values_list("user_id", "unit_id", "mark")) == snapshot
    assert events_except_logins() == events_before, "отказанные запросы ничего не пишут"
    # с правом всё то же работает, а несуществующий узел — 404
    client = support.logged_in(manager_user)
    root = dom(card(client, unit))
    assert member_row(root, user).find_all("details", data_member_menu=True)
    for hook in ({"data_action": "members-add"}, {"data_action": "marks-heads"}, {"data_action": "marks-deputies"}):
        assert root.find_all("details", **hook), f"с правом нет {hook}"
    assert client.get(f"/structure/{unit.pk}/candidates/").status_code == 200
    assert client.post("/structure/999999/marks/", {"part": "heads"}).status_code == 404
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(f"/structure/{unit.pk}/members/", {"users": [newcomer.pk], "mode": "concurrent"}).status_code == 302
        assert client.post(f"/structure/{unit.pk}/marks/", {"part": "heads", "users": [user.pk]}).status_code == 302
    assert mark_of(user, unit) == "head" and unit_names(newcomer) == ["Сеть"]


def test_membership_events_with_mode_reason_and_mark(django_capture_on_commit_callbacks):
    """FR-150: события членства — актор, объект, IP, узел, режим (команда — пустой), причина удаления и отметка «было»."""
    from apps.org.services import membership

    t = org.make_tree({"Сеть": {"team:Дежурные": {}}, "Поддержка": {}})
    admin = manager()
    user = person("Анна Первая")
    Event = model("core.AuditEvent")
    with django_capture_on_commit_callbacks(execute=True):
        membership.add_members(t["Сеть"], [user], mode=membership.CONCURRENT, actor=admin, ip=IP)
        membership.add_members(t["Дежурные"], [user], actor=admin, ip=IP)
        membership.set_marks(t["Сеть"], heads=[user], actor=admin, ip=IP)
        membership.transfer_member(user, t["Сеть"], t["Поддержка"], actor=admin, ip=IP)
        membership.remove_member(user, t["Дежурные"], actor=admin, ip=IP)
    events = user_events(user)
    assert [e.action for e in events] == [
        "membership.added", "membership.added", "membership.removed", "membership.added",
        "membership.transferred", "membership.removed"]
    for event in events:
        assert event.actor_id == admin.pk and event.ip == IP
        assert event.object_type == "user" and event.object_id == str(user.pk)
    concurrent, team, moved_out, moved_in, transferred, manual = events
    assert (concurrent.after["unit"], concurrent.after["unit_id"], concurrent.after["mode"], concurrent.after["mark"]) == (
        "Сеть", t["Сеть"].pk, "concurrent", "")
    assert (team.after["unit"], team.after["unit_id"], team.after["mode"], team.after["mark"]) == (
        "Дежурные", t["Дежурные"].pk, "", "")
    assert (moved_out.before["unit"], moved_out.before["unit_id"], moved_out.before["mark"], moved_out.before["reason"]) == (
        "Сеть", t["Сеть"].pk, "head", "transfer")
    assert (moved_in.after["unit"], moved_in.after["mode"], moved_in.after["mark"]) == ("Поддержка", "transfer", "")
    assert transferred.before["units"] == by_path(t["Сеть"], t["Дежурные"])
    assert transferred.after["units"] == by_path(t["Дежурные"], t["Поддержка"])
    assert (manual.before["unit"], manual.before["unit_id"], manual.before["mark"], manual.before["reason"]) == (
        "Дежурные", t["Дежурные"].pk, "", "manual")
    marks = Event.objects.get(action="unit.marks_changed", object_id=str(t["Сеть"].pk))
    assert marks.object_type == "unit" and marks.actor_id == admin.pk
    assert marks.before["heads"] == [] and marks.after["heads"] == ["Анна Первая"]
