"""T-2104: права среза и роли узлов (FR-118…123, FR-150). Сценарий 9 спеки (роли узлов) и сквозная проверка прав.

Имена кода среза 002 импортируются внутри тестов, коды трёх новых прав — строками (`staff.view`,
`org.manage`, `calendar.manage`): `support.PERMISSIONS_002` пока нет. Помощники, нужные только этому файлу
(разбор разметки, клиенты с набором прав, прогрев ключей `perms:<id>`), лежат здесь.
"""
import re
import secrets
from html.parser import HTMLParser

import pytest

from tests import factories, support, support_org
from tests import support_servicedesk as sd
from tests.support import HX, model

pytestmark = pytest.mark.django_db

NEW_PERMISSIONS = {
    "staff.view": "Просмотр сотрудников и структуры",
    "org.manage": "Управление структурой",
    "calendar.manage": "Рабочий календарь",
}
ALL_PERMISSIONS = tuple(support.PERMISSIONS) + tuple(NEW_PERMISSIONS)
# права среза 003 (CONTRACT-003 § 3.3); `ALL_PERMISSIONS` остаётся правами срезов 001–002 для остальных тестов файла
TITLES_003 = {"servicedesk.all": "Все заявки", "servicedesk.manage": "Настройка сервис-деска"}
VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


# --- помощники файла -------------------------------------------------------------------------

class Node:
    def __init__(self, tag, attrs, parent=None):
        self.tag, self.attrs, self.parent, self.children, self.chunks = tag, dict(attrs), parent, [], []

    def walk(self):
        for child in self.children:
            yield child
            yield from child.walk()

    def find_all(self, **attrs):
        """Потомки с заданными атрибутами (`True` — атрибут есть, строка — равен ей); дефисы пишутся как `_`."""
        wanted = {key.replace("_", "-"): value for key, value in attrs.items()}
        return [n for n in self.walk()
                if all((k in n.attrs) if v is True else n.attrs.get(k) == v for k, v in wanted.items())]

    def text(self) -> str:
        return " ".join(("".join(self.chunks) + " " + " ".join(c.text() for c in self.children)).split())


class _Builder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root", {})
        self.current = self.root

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.current)
        self.current.children.append(node)
        if tag not in VOID_TAGS:
            self.current = node

    def handle_startendtag(self, tag, attrs):
        self.current.children.append(Node(tag, {k: (v or "") for k, v in attrs}, self.current))

    def handle_endtag(self, tag):
        node = self.current
        while node is not self.root and node.tag != tag:
            node = node.parent
        if node is not self.root:
            self.current = node.parent

    def handle_data(self, data):
        self.current.chunks.append(data)


def dom(response_or_html) -> Node:
    html = response_or_html if isinstance(response_or_html, str) else response_or_html.content.decode()
    builder = _Builder()
    builder.feed(html)
    return builder.root


def form_actions(node: Node) -> set[str]:
    return {n.attrs.get("action", "") for n in node.walk() if n.tag == "form"}


def has_alert(response) -> bool:
    return bool(dom(response).find_all(role="alert"))


def alert_text(response) -> str:
    return " ".join(n.text() for n in dom(response).find_all(role="alert")).lower()


def user_with(*codes, **extra):
    """Сотрудник с ровно этими правами (через свою роль)."""
    return support.make_with_permissions(*codes, **extra)


def all_but(*codes):
    return tuple(c for c in ALL_PERMISSIONS if c not in codes)


def permission_cache_key(user):
    return support.valkey_key(f"perms:{user.pk}")


def warm(*users) -> None:
    """Заполняет кэш прав `perms:<id>` (как первый запрос человека после входа)."""
    from apps.core.services import permissions

    for user in users:
        permissions.permissions_of(user)
        assert permission_cache_key(user), f"кэш прав {user.pk} не заполнился"


def role_names(*roles):
    return sorted(r.name for r in roles)


def unit_role_event(unit):
    return model("core.AuditEvent").objects.filter(action="unit.roles_changed", object_id=str(unit.pk)).order_by("id")


# --- FR-118: права и их начальное распределение ----------------------------------------------

def test_three_new_permissions_and_initial_distribution():
    """FR-118, FR-275: всего шестнадцать прав срезов 001–006 с русскими названиями; «Администратор портала» имеет все; «Руководитель» —
    только `staff.view`; «Сотрудник ИТ» — `staff.view` и `knowledge.edit`; `org.manage`, `calendar.manage`, `knowledge.manage` и
    `lists.manage` (срез 006) — только у администратора, `knowledge.edit` — у администратора и «Сотрудника ИТ»; набор меняется в интерфейсе без кода."""
    from tests.support_kb import PERMISSIONS_005, TITLES_005
    from tests.support_lists import PERMISSIONS_006, TITLES_006
    from tests.support_notify import PERMISSIONS_004, TITLES_004

    Permission, Role = model("core.Permission"), model("core.Role")
    titles = dict(Permission.objects.values_list("code", "title"))
    assert set(titles) == (set(ALL_PERMISSIONS) | set(sd.PERMISSIONS_003) | set(PERMISSIONS_004) | set(PERMISSIONS_005)
                           | set(PERMISSIONS_006)), (
        "ожидалось семь прав среза 001, три среза 002, два среза 003, одно среза 004, два среза 005 и одно среза 006")
    for code, title in {**NEW_PERMISSIONS, **TITLES_003, **TITLES_004, **TITLES_005, **TITLES_006}.items():
        assert titles[code] == title, code
    assert all(re.search("[а-яА-Я]", title) for title in titles.values())
    builtin = {r.name: set(r.permissions.values_list("code", flat=True)) for r in Role.objects.filter(is_builtin=True)}
    assert builtin[support.ADMIN_ROLE] == (
        set(ALL_PERMISSIONS) | set(sd.PERMISSIONS_003) | set(PERMISSIONS_004) | set(PERMISSIONS_005)
        | set(PERMISSIONS_006))
    assert builtin[support.MANAGER_ROLE] == {"staff.view"}
    assert builtin[support.STAFF_ROLE] == {"staff.view", "knowledge.edit"}
    holders = {code: sorted(name for name, codes in builtin.items() if code in codes)
               for code in tuple(NEW_PERMISSIONS) + PERMISSIONS_005 + PERMISSIONS_006}
    assert holders["org.manage"] == [support.ADMIN_ROLE] and holders["calendar.manage"] == [support.ADMIN_ROLE]
    assert holders["knowledge.manage"] == [support.ADMIN_ROLE]
    assert holders["lists.manage"] == [support.ADMIN_ROLE]
    assert holders["knowledge.edit"] == sorted([support.ADMIN_ROLE, support.STAFF_ROLE])
    assert len(holders["staff.view"]) == 3
    admin = support.logged_in(support.make_admin())
    created = admin.post("/roles/new/", {"name": "Организатор", "permissions": [
        "org.manage", "calendar.manage", "knowledge.edit", "knowledge.manage"]})
    assert created.status_code == 302
    assert set(Role.objects.get(name="Организатор").permissions.values_list("code", flat=True)) == {
        "org.manage", "calendar.manage", "knowledge.edit", "knowledge.manage"}


def test_staff_list_and_card_open_with_staff_view_or_accounts_manage():
    """FR-118: список «Сотрудники» и карточка коллеги открываются по `staff.view` или `accounts.manage`; без обоих — 403,
    без входа — на вход."""
    target = support.make_employee()
    for codes in (("staff.view",), ("accounts.manage",), ("staff.view", "accounts.manage")):
        client = support.logged_in(user_with(*codes))
        assert client.get("/staff/").status_code == 200, codes
        assert client.get(f"/staff/{target.pk}/").status_code == 200, codes
    outsider = support.logged_in(user_with(*all_but("staff.view", "accounts.manage")))
    assert outsider.get("/staff/").status_code == 403
    assert outsider.get(f"/staff/{target.pk}/").status_code == 403
    anonymous = support.make_client(ip="198.51.100.120")
    for path in ("/staff/", f"/staff/{target.pk}/"):
        got = anonymous.get(path)
        assert got.status_code == 302 and "/login/" in got["Location"], path


# --- FR-119: служебные поля карточки остаются под правами среза 001 -----------------------------

def test_colleague_sees_no_service_fields_security_tab_absent_and_403():
    """FR-119: коллега по `staff.view` не видит ролей, состояния, приглашения и форм карточки; вкладки «Безопасность»
    нет ни в полной странице, ни во фрагменте HTMX; её адреса и действия карточки отвечают 403 и ничего не меняют."""
    secret_role = factories.make_role(name=f"Служебная роль {secrets.token_hex(3)}")
    target = support.make_employee(roles=[secret_role])
    viewer = user_with("staff.view")
    client = support.logged_in(viewer)
    for extra in ({}, HX):
        response = client.get(f"/staff/{target.pk}/", **extra)
        assert response.status_code == 200
        html, page = response.content.decode(), dom(response)
        assert not page.find_all(data_tab_button="security") and not page.find_all(data_tab_panel="security")
        assert not page.find_all(data_field="state") and not page.find_all(data_invitation_link=True)
        assert not page.find_all(data_roles_group=True) and not page.find_all(data_role_name=True)
        assert secret_role.name not in html, "название роли видно коллеге"
        forbidden_actions = {f"/staff/{target.pk}/{part}/" for part in
                             ("edit", "roles", "block", "unblock", "invite", "unlock", "reset-2fa")}
        assert not (form_actions(page) & forbidden_actions)
        assert f"/staff/{target.pk}/logins/" not in html
    before = (target.state, list(target.roles.all()), target.full_name)
    assert client.get(f"/staff/{target.pk}/logins/").status_code == 403
    for action in ("edit", "roles", "block", "unblock", "invite", "unlock", "reset-2fa"):
        got = client.post(f"/staff/{target.pk}/{action}/", {"roles": [], "full_name": "Взлом", "reason": "x",
                                                            "confirm": "1"})
        assert got.status_code == 403, action
    target.refresh_from_db()
    assert (target.state, list(target.roles.all()), target.full_name) == before


def test_security_tab_parts_by_accounts_manage_and_view_logins():
    """FR-119: вкладка «Безопасность» чужой карточки есть у `accounts.manage` и у `accounts.view_logins`; её части зависят
    от прав: состояние и блокировка — у `accounts.manage`, устройства и входы — у `accounts.view_logins`."""
    target = support.make_employee()
    logins_url = f"/staff/{target.pk}/logins/"
    block_action = f"/staff/{target.pk}/block/"
    reset_action = f"/staff/{target.pk}/reset-2fa/"

    def security(codes):
        client = support.logged_in(user_with(*codes))
        response = client.get(f"/staff/{target.pk}/")
        assert response.status_code == 200, codes
        page = dom(response)
        buttons, panels = page.find_all(data_tab_button="security"), page.find_all(data_tab_panel="security")
        assert len(buttons) == 1 and len(panels) == 1, f"{codes}: вкладка «Безопасность» должна быть"
        assert "hidden" in panels[0].attrs, "по умолчанию открыт «Профиль»"
        account = panels[0].find_all(data_security_part="account")
        logins = panels[0].find_all(data_security_part="logins")
        assert len(account) <= 1 and len(logins) <= 1, codes
        # состояние лежит только в части «account»; сброс второго фактора — тоже там
        state_in_account = bool(account) and bool(account[0].find_all(data_field="state"))
        assert bool(page.find_all(data_field="state")) == state_in_account, codes
        account_forms = form_actions(account[0]) if account else set()
        all_forms = form_actions(panels[0])
        links = {n.attrs.get("href") for n in logins[0].walk() if n.tag == "a"} if logins else set()
        assert logins_url not in {n.attrs.get("href") for n in panels[0].walk() if n.tag == "a"} - links, codes
        return (bool(account), state_in_account, block_action in account_forms, reset_action in account_forms,
                (block_action in all_forms) == (block_action in account_forms) and
                (reset_action in all_forms) == (reset_action in account_forms),
                bool(logins), logins_url in links, client.get(logins_url).status_code)

    # сброс второго фактора — по праву своего маршрута `accounts.reset_2fa` (срез 001, test_totp; дополнение 66)
    assert security(("accounts.manage",)) == (True, True, True, False, True, False, False, 403)
    assert security(("accounts.manage", "accounts.reset_2fa")) == (True, True, True, True, True, False, False, 403)
    assert security(("staff.view", "accounts.view_logins")) == (False, False, False, False, True, True, True, 200)
    assert security(("accounts.manage", "accounts.view_logins")) == (True, True, True, False, True, True, True, 200)

    # приглашение — тоже часть «account»: у записи в состоянии `invited` есть форма `…/invite/` (дополнение 4)
    invited = support.make_employee(state="invited", totp=False)
    invite_action = f"/staff/{invited.pk}/invite/"
    for codes, expected in ((("accounts.manage",), True), (("accounts.manage", "accounts.view_logins"), True),
                            (("staff.view", "accounts.view_logins"), False)):
        page = dom(support.logged_in(user_with(*codes)).get(f"/staff/{invited.pk}/"))
        panel, = page.find_all(data_tab_panel="security")
        account = panel.find_all(data_security_part="account")
        assert (invite_action in (form_actions(account[0]) if account else set())) is expected, codes
        assert (invite_action in form_actions(panel)) is expected, codes


# --- FR-120, сценарий 9: роли узлов ------------------------------------------------------------

def test_unit_role_applies_to_members_of_unit_and_nested_units():
    """FR-120 (сценарий 9.1): роль отдела действует на участников отдела и вложенных узлов, объединяется с личными ролями
    и ролями другого узла (совместитель), не действует на соседние узлы и на вышестоящих; право открывает страницу."""
    from apps.core.services import permissions

    tree = support_org.make_tree({"Сеть": {"Группа филиала": {}, "team:Дежурные": {}}, "Поддержка": {}})
    net, branch, support_dept = tree["Сеть"], tree["Группа филиала"], tree["Поддержка"]
    role_audit = factories.make_role(name="Аудитор узла", permissions=("audit.view",))
    role_settings = factories.make_role(name="Настройщик узла", permissions=("settings.portal",))
    personal = factories.make_role(name="Личная", permissions=("roles.manage",))
    support_org.make_unit_role(net, role_audit)
    support_org.make_unit_role(support_dept, role_settings)

    in_branch, in_net = support.make_employee(), support.make_employee()
    in_support, in_none = support.make_employee(), support.make_employee()
    concurrent = support.make_employee(roles=[personal])
    support_org.make_member(in_branch, branch)
    support_org.make_member(in_net, net)
    support_org.make_member(in_support, support_dept)
    support_org.make_member(concurrent, tree["Дежурные"])
    support_org.make_member(concurrent, support_dept)

    assert "audit.view" in permissions.permissions_of(in_branch), "вложенный узел получает роль отдела"
    assert "audit.view" in permissions.permissions_of(in_net)
    assert "audit.view" not in permissions.permissions_of(in_support)
    assert permissions.permissions_of(in_none) == frozenset()
    assert {"audit.view", "settings.portal", "roles.manage"} <= permissions.permissions_of(concurrent)
    assert support.logged_in(in_branch).get("/audit/").status_code == 200
    assert support.logged_in(in_support).get("/audit/").status_code == 403
    assert support.logged_in(in_support).get("/settings/portal/").status_code == 200
    # роль команды не поднимается вверх
    team_role = factories.make_role(name="Роль команды", permissions=("audit.view",))
    support_org.make_unit_role(tree["Дежурные"], team_role)
    lone = support.make_employee()
    support_org.make_member(lone, tree["Дежурные"])
    assert "audit.view" in permissions.permissions_of(lone)
    assert "audit.view" not in permissions.permissions_of(support.make_employee())
    parent_member = support.make_employee()
    other = support_org.make_tree({"Отдел без ролей": {"team:Своя команда": {}}})
    support_org.make_unit_role(other["Своя команда"], team_role)
    support_org.make_member(parent_member, other["Отдел без ролей"])
    assert "audit.view" not in permissions.permissions_of(parent_member), "роль команды не действует на отдел выше"


def test_unit_role_permissions_gone_next_request_after_removal(django_capture_on_commit_callbacks):
    """FR-120 (сценарий 9.2): права от узла пропадают со следующего запроса при удалении из узла и при снятии роли узла,
    появляются при добавлении."""
    from apps.org.services import membership

    unit = support_org.make_unit("Сеть")
    role = factories.make_role(name="Аудитор узла", permissions=("audit.view",))
    support_org.make_unit_role(unit, role)
    member = support.make_employee()
    support_org.make_member(member, unit)
    admin = support.logged_in(support.make_admin(), ip="198.51.100.171")
    client = support.logged_in(member)
    assert client.get("/audit/").status_code == 200
    assert permission_cache_key(member), "права закэшированы"

    with django_capture_on_commit_callbacks(execute=True):
        assert admin.post(f"/structure/{unit.pk}/members/{member.pk}/remove/").status_code == 302
    assert client.get("/audit/").status_code == 403, "права от узла остались после удаления из узла"

    with django_capture_on_commit_callbacks(execute=True):
        membership.add_members(unit, [member], mode=membership.TRANSFER, actor=support.make_admin())
    assert client.get("/audit/").status_code == 200, "права появляются со следующего запроса"

    with django_capture_on_commit_callbacks(execute=True):
        assert admin.post(f"/structure/{unit.pk}/roles/", {"roles": []}).status_code == 302
    assert client.get("/audit/").status_code == 403, "права остались после снятия роли с узла"


def test_permission_keys_dropped_on_commit_for_membership_move_delete_and_unit_roles(django_capture_on_commit_callbacks):
    """FR-120 (решение 11): ключи `perms:<id>` сбрасываются после фиксации: у человека — при добавлении, переводе,
    удалении из узла и увольнении; у участников поддерева — при переносе узла и смене ролей узла; посторонние не страдают."""
    from apps.org.services import membership, people, structure, unit_roles

    admin = support.make_admin()
    role = factories.make_role(name="Роль узла", permissions=("audit.view",))
    tree = support_org.make_tree({"Сеть": {"Серверы": {"team:Дежурные": {}}}, "Поддержка": {}, "Склад": {}})
    net, servers, duty = tree["Сеть"], tree["Серверы"], tree["Дежурные"]
    support_dept, store = tree["Поддержка"], tree["Склад"]

    def person(unit=None):
        user = support.make_employee()
        if unit is not None:
            support_org.make_member(user, unit)
        return user

    def dropped_on_commit(users, kept, action):
        warm(*users, *kept)
        with django_capture_on_commit_callbacks(execute=True):
            action()
            assert all(permission_cache_key(u) for u in users), "ключи сброшены до фиксации транзакции"
        for user in users:
            assert not permission_cache_key(user), f"ключ perms:{user.pk} не сброшен после фиксации"
        for user in kept:
            assert permission_cache_key(user), f"ключ посторонней записи perms:{user.pk} сброшен"

    bystander = person(store)
    newcomer = person()
    dropped_on_commit([newcomer], [bystander],
                      lambda: membership.add_members(net, [newcomer], mode=membership.CONCURRENT, actor=admin))
    mover = person(support_dept)
    dropped_on_commit([mover], [bystander],
                      lambda: membership.transfer_member(mover, support_dept, store, actor=admin))
    leaver = person(store)
    dropped_on_commit([leaver], [bystander], lambda: membership.remove_member(leaver, store, actor=admin))
    fired = person(net)
    dropped_on_commit([fired], [bystander], lambda: people.dismiss(fired, actor=admin))

    in_servers, in_duty, in_net, in_support = person(servers), person(duty), person(net), person(support_dept)
    dropped_on_commit([in_servers, in_duty], [in_net, in_support, bystander],
                      lambda: structure.move_unit(servers, support_dept, actor=admin))
    in_servers2, in_duty2, in_support2 = person(servers), person(duty), person(support_dept)
    dropped_on_commit([in_servers2, in_duty2], [in_support2, bystander],
                      lambda: unit_roles.set_unit_roles(servers, [role], actor=admin))


def test_role_permission_change_drops_all_permission_keys(django_capture_on_commit_callbacks):
    """FR-120: смена набора прав роли сбрасывает ключи `perms:<id>` ВСЕХ записей (держатели через узлы ядру не видны),
    и новые права действуют со следующего запроса; `forget_all()` тоже отложен до фиксации."""
    from apps.core.services import permissions

    role = factories.make_role(name="Меняемая", permissions=("audit.view",))
    unit = support_org.make_unit("Сеть")
    support_org.make_unit_role(unit, role)
    personal_holder, via_unit, outsider = support.make_employee(roles=[role]), support.make_employee(), support.make_employee()
    support_org.make_member(via_unit, unit)
    admin_user = support.make_admin()
    admin = support.logged_in(admin_user)
    unit_client = support.logged_in(via_unit, ip="198.51.100.172")
    assert unit_client.get("/audit/").status_code == 200
    warm(personal_holder, outsider, admin_user)

    with django_capture_on_commit_callbacks(execute=True):
        got = admin.post(f"/roles/{role.pk}/", {"name": "Меняемая", "permissions": ["roles.manage"]})
        assert got.status_code == 302
    for user in (personal_holder, via_unit, outsider, admin_user):
        assert not permission_cache_key(user), f"ключ perms:{user.pk} не сброшен при смене прав роли"
    assert unit_client.get("/audit/").status_code == 403 and unit_client.get("/roles/").status_code == 200

    warm(outsider, via_unit)
    with django_capture_on_commit_callbacks(execute=True):
        permissions.forget_all()
        assert permission_cache_key(outsider), "forget_all сбросил ключи до фиксации"
    assert not permission_cache_key(outsider) and not permission_cache_key(via_unit)


def test_role_assigned_to_unit_cannot_be_deleted():
    """FR-120 (сценарий 9.7): роль, назначенная узлу, не удаляется ни из интерфейса, ни из сервиса (текст «Роль назначена
    узлу…»); база — второй рубеж (`PROTECT`); после снятия с узла удаляется."""
    from django.db import IntegrityError, transaction
    from django.db.models import ProtectedError

    from apps.core.services import roles
    from apps.org.services import unit_roles

    Role = model("core.Role")
    unit = support_org.make_unit("Сеть")
    role = factories.make_role(name="Роль узла", permissions=("audit.view",))
    support_org.make_unit_role(unit, role)
    admin_user = support.make_admin()
    admin = support.logged_in(admin_user)

    shown = admin.post(f"/roles/{role.pk}/delete/", follow=True)
    assert Role.objects.filter(pk=role.pk).exists()
    assert "Роль назначена узлу" in shown.content.decode()
    with pytest.raises(roles.RoleError) as refused:
        roles.delete_role(role, actor=admin_user)
    assert "Роль назначена узлу" in str(refused.value)
    with pytest.raises((ProtectedError, IntegrityError)), transaction.atomic():
        role.delete()
    assert Role.objects.filter(pk=role.pk).exists()

    unit_roles.set_unit_roles(unit, [], actor=admin_user)
    assert admin.post(f"/roles/{role.pk}/delete/").status_code == 302
    assert not Role.objects.filter(pk=role.pk).exists()


# --- FR-121 -----------------------------------------------------------------------------------

def test_admin_role_cannot_be_assigned_to_unit():
    """FR-121 (сценарий 9.4): роль «Администратор портала» узлу не назначается — сервис отказывает кодом
    `admin_role_forbidden`, форма даёт `[role=alert]`; отказ целиком (прочие роли того же набора не применяются), журнала нет."""
    from apps.org.services import OrgError, unit_roles

    unit = support_org.make_unit("Сеть")
    admin_role = support.role_by_name(support.ADMIN_ROLE)
    ordinary = factories.make_role(name="Обычная роль", permissions=("audit.view",))
    admin_user = support.make_admin()
    UnitRole = model("org.UnitRole")

    with pytest.raises(OrgError) as refused:
        unit_roles.set_unit_roles(unit, [ordinary, admin_role], actor=admin_user)
    assert refused.value.code == "admin_role_forbidden"
    assert "администратор выдаётся только лично" in str(refused.value).lower()
    assert not UnitRole.objects.filter(unit=unit).exists(), "отказ должен быть целиком"
    assert not unit_role_event(unit).exists()

    client = support.logged_in(admin_user)
    got = client.post(f"/structure/{unit.pk}/roles/", {"roles": [ordinary.pk, admin_role.pk]})
    assert got.status_code == 200 and has_alert(got)
    assert "администратор выдаётся только лично" in alert_text(got)
    assert not UnitRole.objects.filter(unit=unit).exists() and not unit_role_event(unit).exists()
    # несуществующая роль: role_missing, ничего не меняется
    with pytest.raises(OrgError) as missing:
        unit_roles.set_unit_roles(unit, [999999], actor=admin_user)
    assert missing.value.code == "role_missing"
    assert not UnitRole.objects.filter(unit=unit).exists() and not unit_role_event(unit).exists()

    unit_roles.set_unit_roles(unit, [ordinary], actor=admin_user)
    got = client.post(f"/structure/{unit.pk}/roles/", {"roles": [ordinary.pk, admin_role.pk]})
    assert got.status_code == 200 and has_alert(got)
    assert "администратор выдаётся только лично" in alert_text(got)
    assert list(UnitRole.objects.filter(unit=unit).values_list("role_id", flat=True)) == [ordinary.pk]


def test_unit_roles_need_roles_manage_not_org_manage():
    """FR-120 (сценарий 9.5): роли узла назначает обладатель `roles.manage`, а не `org.manage`: без `roles.manage` — 403 и
    ничего не меняется; кнопка `unit-roles` в карточке узла — только с `roles.manage`."""
    unit = support_org.make_unit("Сеть")
    role = factories.make_role(name="Роль узла", permissions=("audit.view",))
    UnitRole = model("org.UnitRole")

    org_only = support.logged_in(user_with("staff.view", "org.manage"), ip="198.51.100.173")
    assert org_only.post(f"/structure/{unit.pk}/roles/", {"roles": [role.pk]}).status_code == 403
    assert not UnitRole.objects.filter(unit=unit).exists()
    roles_only = support.logged_in(user_with("staff.view", "roles.manage"), ip="198.51.100.174")
    got = roles_only.post(f"/structure/{unit.pk}/roles/", {"roles": [role.pk]})
    assert got.status_code == 302 and got["Location"] == f"/structure/{unit.pk}/"
    assert list(UnitRole.objects.filter(unit=unit).values_list("role_id", flat=True)) == [role.pk]
    anonymous = support.make_client(ip="198.51.100.175").post(f"/structure/{unit.pk}/roles/", {"roles": []})
    assert anonymous.status_code == 302 and "/login/" in anonymous["Location"]

    with_org = dom(org_only.get(f"/structure/{unit.pk}/"))
    with_roles = dom(roles_only.get(f"/structure/{unit.pk}/"))
    assert not with_org.find_all(data_action="unit-roles") and with_org.find_all(data_action="unit-edit")
    assert with_roles.find_all(data_action="unit-roles") and not with_roles.find_all(data_action="unit-edit")


# --- FR-122 -----------------------------------------------------------------------------------

def test_card_roles_grouped_personal_and_by_unit_source():
    """FR-122 (сценарий 9.3): в карточке роли сгруппированы: «лично» и «от подразделения <узел, которому назначена роль>»;
    то же даёт `permissions.roles_by_source` (группы по названию узла, пустых нет)."""
    from apps.core.services import permissions

    tree = support_org.make_tree({"Сеть": {"Группа филиала": {}}, "Поддержка": {}})
    personal = factories.make_role(name="Личная роль", permissions=("roles.manage",))
    net_role = factories.make_role(name="Роль Сети", permissions=("audit.view",))
    support_role = factories.make_role(name="Роль Поддержки", permissions=("settings.portal",))
    support_org.make_unit_role(tree["Сеть"], net_role)
    support_org.make_unit_role(tree["Поддержка"], support_role)
    person = support.make_employee(roles=[personal])
    support_org.make_member(person, tree["Группа филиала"])
    support_org.make_member(person, tree["Поддержка"])
    lone = support.make_employee(roles=[personal])

    assert permissions.roles_by_source(person) == [
        ("лично", [personal]), ("от подразделения Поддержка", [support_role]), ("от подразделения Сеть", [net_role])]
    assert permissions.roles_by_source(lone) == [("лично", [personal])], "пустые группы не возвращаются"
    assert permissions.roles_by_source(support.make_employee()) == []

    client = support.logged_in(support.make_admin())
    page = dom(client.get(f"/staff/{person.pk}/"))

    def names(group):
        return [n.text() for n in group.find_all(data_role_name=True)]

    personal_groups = page.find_all(data_roles_group="personal")
    assert len(personal_groups) == 1 and names(personal_groups[0]) == [personal.name]
    assert "лично" in personal_groups[0].text()
    unit_groups = {g.attrs["data-source-unit"]: g for g in page.find_all(data_roles_group="unit")}
    assert set(unit_groups) == {"Сеть", "Поддержка"}, "источник — узел, которому назначена роль, а не узел членства"
    assert names(unit_groups["Сеть"]) == [net_role.name] and names(unit_groups["Поддержка"]) == [support_role.name]
    assert "от подразделения Сеть" in unit_groups["Сеть"].text()
    assert not dom(client.get(f"/staff/{lone.pk}/")).find_all(data_roles_group="unit")


# --- FR-123 -----------------------------------------------------------------------------------

BOTH = "оба"  # в кортеже прав: нужны ВСЕ перечисленные права (маршруты загрузки сотрудников)


def _slice_routes():
    """(метод, шаблон пути, права): права — «любое из» (кортеж кодов) или `(BOTH, a, b)` — оба. Маршруты под `staff/`
    берутся из `support_org.SLICE_002_STAFF_ROUTES`, остальные — из § 8 контракта."""
    routes = list(support_org.SLICE_002_STAFF_ROUTES)
    routes += [
        ("get", "/structure/", ("staff.view",)),
        ("get", "/structure/{unit_id}/", ("staff.view",)),
        ("get", "/structure/new/", ("org.manage",)), ("post", "/structure/new/", ("org.manage",)),
        ("get", "/structure/{unit_id}/edit/", ("org.manage",)), ("post", "/structure/{unit_id}/edit/", ("org.manage",)),
        ("get", "/structure/{unit_id}/delete/", ("org.manage",)),
        ("post", "/structure/{unit_id}/delete/", ("org.manage",)),
        ("get", "/structure/{unit_id}/candidates/", ("org.manage",)),
        ("post", "/structure/{unit_id}/members/", ("org.manage",)),
        ("post", "/structure/{unit_id}/members/{user_id}/transfer/", ("org.manage",)),
        ("post", "/structure/{unit_id}/members/{user_id}/remove/", ("org.manage",)),
        ("post", "/structure/{unit_id}/marks/", ("org.manage",)),
        ("post", "/structure/{unit_id}/roles/", ("roles.manage",)),
        ("get", "/structure/people/{user_id}/dismiss/", ("org.manage",)),
        ("post", "/structure/people/{user_id}/dismiss/", ("org.manage",)),
        ("get", "/structure/people/{user_id}/rehire/", ("org.manage",)),
        ("post", "/structure/people/{user_id}/rehire/", ("org.manage",)),
        ("get", "/structure/import/", (BOTH, "accounts.manage", "org.manage")),
        ("post", "/structure/import/", (BOTH, "accounts.manage", "org.manage")),
        ("get", "/structure/import/{import_id}/", (BOTH, "accounts.manage", "org.manage")),
        ("post", "/structure/import/{import_id}/", (BOTH, "accounts.manage", "org.manage")),
        ("get", "/structure/import/sample.csv", (BOTH, "accounts.manage", "org.manage")),
        ("get", "/structure/import/sample.xlsx", (BOTH, "accounts.manage", "org.manage")),
        ("get", "/calendar/", ("staff.view", "calendar.manage")),
        ("post", "/calendar/settings/", ("calendar.manage",)),
        ("get", "/calendar/upload/", ("calendar.manage",)), ("post", "/calendar/upload/", ("calendar.manage",)),
        ("get", "/calendar/upload/{upload_id}/", ("calendar.manage",)),
        ("post", "/calendar/upload/{upload_id}/", ("calendar.manage",)),
        ("get", "/calendar/days/{day}/", ("calendar.manage",)),
        ("post", "/calendar/days/{day}/", ("calendar.manage",)),
    ]
    return routes


def test_every_slice_view_requires_declared_permission_403():
    """FR-123: каждый маршрут среза проверяет заявленное право независимо от меню: без входа — на вход, без права — 403
    (до проверки существования объекта), с правом — не 403; таблица покрывает все маршруты `structure/` и `calendar/`,
    а маршруты `SLICE_002_STAFF_ROUTES` существуют."""
    victim, dismissee = support.make_employee(), support.make_employee()
    unit = support_org.make_unit("Сеть")
    ids = {"unit_id": unit.pk, "user_id": victim.pk, "import_id": 999999, "upload_id": 999999}
    anonymous = support.make_client(ip="198.51.100.180")
    clients: dict = {}

    def client_with(codes):
        key = tuple(sorted(codes))
        if key not in clients:
            clients[key] = support.logged_in(user_with(*codes), ip="198.51.100.181")
        return clients[key]

    # Порядок существенный: «уволить» и «вернуть» одного `dismissee` идут подряд (в порядке таблицы маршрутов).
    def path_of(template):
        user_id = dismissee.pk if "/dismiss/" in template else victim.pk
        return support_org.route_path(template.replace("{unit_id}", str(unit.pk)).replace(
            "{import_id}", "999999").replace("{upload_id}", "999999").replace("{day}", "2027-03-01"), user_id)

    def passed(response):
        return response.status_code != 403 and not (response.status_code == 302 and "/login/" in response["Location"])

    routes = _slice_routes()
    for method, template, rights in routes:
        path, label = path_of(template), f"{method.upper()} {template}"
        got = getattr(anonymous, method)(path)
        assert got.status_code == 302 and "/login/" in got["Location"], f"{label}: без входа"
        if rights[0] == BOTH:
            needed = rights[1:]
            for lacking in needed:
                assert getattr(client_with(all_but(lacking)), method)(path).status_code == 403, f"{label}: без {lacking}"
            assert passed(getattr(client_with(needed), method)(path)), f"{label}: с обоими правами"
            continue
        granting = [r for r in rights if r != support_org.SELF]
        denied_client = client_with(all_but(*granting))
        assert getattr(denied_client, method)(path).status_code == 403, f"{label}: без права {granting}"
        for code in granting:
            got = getattr(client_with((code,)), method)(path)
            assert passed(got), f"{label}: с правом {code} получили {got.status_code}"
    # «сам» в выдаче фото: без прав своё фото не 403 (404: такого фото нет), чужое — 403
    lone = user_with(*all_but("staff.view", "accounts.manage"))
    lone_client = support.logged_in(lone, ip="198.51.100.182")
    own = lone_client.get(support_org.route_path("/staff/{user_id}/photo/{photo_id}/{size}/", lone))
    assert own.status_code == 404
    other = lone_client.get(support_org.route_path("/staff/{user_id}/photo/{photo_id}/{size}/", victim))
    assert other.status_code == 403

    templates = [template for _, template, _ in routes]
    for route, _ in support.all_routes():
        normalized = "/" + re.sub(r"<[^>]+>", "x", route)
        if route.startswith(("structure/", "calendar/")):
            assert any(support_org.route_regex(t).match(normalized) for t in templates), (
                f"маршрут {route} не покрыт проверкой прав")
    known = [route for route, _ in support.all_routes()]
    for method, template, _ in support_org.SLICE_002_STAFF_ROUTES:
        normalized_routes = ["/" + re.sub(r"<[^>]+>", "x", r) for r in known]
        assert any(support_org.route_regex(template).match(r) for r in normalized_routes), (
            f"маршрута {template} из SLICE_002_STAFF_ROUTES нет в проекте")


def test_menu_staff_structure_calendar_items_by_permission():
    """FR-123: пункты «Сотрудники», «Структура», «Календарь» — по правам (`staff.view` или `accounts.manage`; `staff.view`;
    `staff.view` или `calendar.manage`); у пункта ключи `url`, `title`, `icon`, `order` (и `badge` только у «Заявок»), порядок 5, 7, 8, 10…60, 62, 65, 70
    (7 — «База знаний», `/kb/`, без прав и без `badge`, срез 005; 8 — «Списки», `/lists/`, без прав и без `badge`,
    видимость по `access.sees_section`, срез 006; 62 — «Уведомления», `notify.manage`, срез 004);
    разметка меню совпадает с `menu_for`; недоступное скрыто."""
    from apps.core.services import permissions

    def urls(user):
        return [item["url"] for item in permissions.menu_for(user)]

    def html_links(user):
        page = dom(support.logged_in(user, ip="198.51.100.190").get("/me/"))
        return {n.attrs["href"] for n in page.walk() if n.tag == "a" and n.attrs.get("href", "").startswith(
            ("/staff/", "/structure/", "/calendar/", "/roles/", "/audit/", "/settings/"))}

    slice_urls = {"/staff/", "/structure/", "/calendar/"}
    cases = [
        ((), set()),
        (("staff.view",), {"/staff/", "/structure/", "/calendar/"}),
        (("accounts.manage",), {"/staff/"}),
        (("calendar.manage",), {"/calendar/"}),
        (("org.manage",), set()),
        (("staff.view", "calendar.manage"), {"/staff/", "/structure/", "/calendar/"}),
    ]
    for codes, expected in cases:
        user = user_with(*codes) if codes else support.make_employee()
        assert set(urls(user)) & slice_urls == expected, f"права {codes}: меню {urls(user)}"
        assert html_links(user) & slice_urls == expected, f"права {codes}: ссылки в разметке {html_links(user)}"
        assert "/roles/" not in urls(user) and "/audit/" not in urls(user)

    items = permissions.menu_for(support.make_admin())
    assert [i["url"] for i in items] == ["/tickets/", "/kb/", "/lists/", "/staff/", "/structure/", "/calendar/", "/roles/",
                                         "/audit/", "/settings/portal/", "/settings/notifications/", "/servicedesk/",
                                         "/settings/security/"]
    assert [i["order"] for i in items] == [5, 7, 8, 10, 20, 30, 40, 50, 60, 62, 65, 70]
    assert [i["title"] for i in items] == ["Заявки", "База знаний", "Списки", "Сотрудники", "Структура", "Календарь",
                                           "Роли и права", "Журнал событий", "Настройки портала", "Уведомления",
                                           "Сервис-деск", "Безопасность и политика"]
    # `badge` есть только у «Заявок» (CONTRACT-003 § 3.2); у остальных ровно четыре ключа
    assert set(items[0]) == {"url", "title", "icon", "order", "badge"}
    assert all(set(i) == {"url", "title", "icon", "order"} for i in items[1:])
    icons = {i["url"]: i["icon"] for i in items}
    assert icons["/structure/"] == "icons/structure.html" and icons["/calendar/"] == "icons/calendar.html"
    assert icons["/lists/"] == "icons/lists.html"
    assert all(re.fullmatch(r"icons/[a-z0-9_-]+\.html", icon) for icon in icons.values())


# --- FR-150 -----------------------------------------------------------------------------------

def test_unit_roles_events_before_after(django_capture_on_commit_callbacks):
    """FR-150 (сценарий 9.6): назначение и снятие ролей узла пишет `unit.roles_changed` с `before` и `after` — списками
    названий ролей по возрастанию, исполнителем и узлом; пустая правка события не даёт; название ролей видно в журнале."""
    from apps.org.services import unit_roles

    unit = support_org.make_unit("Сеть")
    first = factories.make_role(name="Роль Б", permissions=("audit.view",))
    second = factories.make_role(name="Роль А", permissions=("settings.portal",))
    admin_user = support.make_admin()

    with django_capture_on_commit_callbacks(execute=True):
        unit_roles.set_unit_roles(unit, [first, second], actor=admin_user)
    event = unit_role_event(unit).get()
    assert event.object_type == "unit" and event.actor_id == admin_user.pk
    assert event.before.get("roles", []) == [] and event.after == {"roles": ["Роль А", "Роль Б"]}

    with django_capture_on_commit_callbacks(execute=True):
        unit_roles.set_unit_roles(unit, [second.pk, first.pk], actor=admin_user)
    assert unit_role_event(unit).count() == 1, "та же правка не пишет события"

    client = support.logged_in(admin_user, ip="198.51.100.195")
    with django_capture_on_commit_callbacks(execute=True):
        assert client.post(f"/structure/{unit.pk}/roles/", {"roles": [second.pk]}).status_code == 302
    last = unit_role_event(unit).last()
    assert unit_role_event(unit).count() == 2
    assert last.before == {"roles": ["Роль А", "Роль Б"]} and last.after == {"roles": ["Роль А"]}
    assert last.actor_id == admin_user.pk

    with django_capture_on_commit_callbacks(execute=True):
        unit_roles.set_unit_roles(unit, [], actor=admin_user)
    cleared = unit_role_event(unit).last()
    assert cleared.before == {"roles": ["Роль А"]} and cleared.after.get("roles", []) == []
    page = client.get("/audit/").content.decode()
    assert "Роль А" in page, "«было / стало» с названиями ролей видно на странице журнала"
