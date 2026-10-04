"""T-106: права и роли (FR-014…020, FR-050). Сценарии 12, 15 спеки."""
import re

import pytest

from tests import factories, support
from tests.support import PERMISSIONS, make_with_permissions, model

pytestmark = pytest.mark.django_db

SECTION_LINKS = {
    "accounts.manage": "/staff/", "roles.manage": "/roles/", "audit.view": "/audit/",
    "settings.portal": "/settings/portal/", "settings.security": "/settings/security/",
}


def test_seven_permissions_created_by_migration():
    """FR-014, FR-118: семь прав среза 001 созданы миграцией данных с русскими названиями (полный набор из десяти прав — T-2104)."""
    rows = list(model("core.Permission").objects.filter(code__in=PERMISSIONS).values_list("code", "title"))
    assert sorted(code for code, _ in rows) == sorted(PERMISSIONS)
    assert all(re.search("[а-яА-Я]", title) for _, title in rows)


def test_three_builtin_roles_with_initial_permissions():
    """FR-015, FR-020, FR-118: три начальные роли; у администратора все десять прав, у «Руководителя» и «Сотрудника ИТ» ровно `staff.view`."""
    Role = model("core.Role")
    builtin = {r.name: r for r in Role.objects.filter(is_builtin=True)}
    assert set(builtin) == {support.ADMIN_ROLE, support.MANAGER_ROLE, support.STAFF_ROLE}
    assert set(builtin[support.ADMIN_ROLE].permissions.values_list("code", flat=True)) == set(PERMISSIONS + support.PERMISSIONS_002)
    assert set(builtin[support.MANAGER_ROLE].permissions.values_list("code", flat=True)) == {"staff.view"}
    assert set(builtin[support.STAFF_ROLE].permissions.values_list("code", flat=True)) == {"staff.view"}
    employee = support.logged_in(support.make_employee(roles=[builtin[support.STAFF_ROLE]]))
    assert employee.get("/me/").status_code == 200 and employee.get("/me/security/").status_code == 200
    assert employee.get("/staff/").status_code == 200, "сотрудник со `staff.view` открывает список"
    assert employee.get("/staff/new/").status_code == 403, "создание записи — только `accounts.manage`"


def test_custom_role_create_edit_delete_when_unassigned():
    """FR-015, FR-016 (сценарий 12): своя роль создаётся, правится и удаляется без кода и перезапуска; всё — в журнале «было / стало»."""
    Role = model("core.Role")
    admin = support.logged_in(support.make_admin())
    created = admin.post("/roles/new/", {"name": "Аудитор", "permissions": ["audit.view"]})
    assert created.status_code == 302
    role = Role.objects.get(name="Аудитор")
    assert not role.is_builtin and list(role.permissions.values_list("code", flat=True)) == ["audit.view"]
    assert "Аудитор" in admin.get("/roles/").content.decode()
    assert "Аудитор" in admin.get("/staff/new/").content.decode(), "роль сразу доступна для назначения"
    edited = admin.post(f"/roles/{role.pk}/", {"name": "Аудитор журнала", "permissions": ["audit.view", "accounts.manage"]})
    assert edited.status_code == 302
    role.refresh_from_db()
    assert role.name == "Аудитор журнала" and set(role.permissions.values_list("code", flat=True)) == {"audit.view", "accounts.manage"}
    updated = model("core.AuditEvent").objects.get(action="role.updated", object_id=str(role.pk))
    assert "audit.view" in str(updated.before) and "accounts.manage" in str(updated.after) and updated.actor_id
    assert admin.post(f"/roles/{role.pk}/delete/").status_code == 302
    assert not Role.objects.filter(pk=role.pk).exists()
    assert {"role.created", "role.updated", "role.deleted"} <= set(support.audit_actions())


def test_builtin_and_assigned_role_cannot_be_deleted():
    """FR-016 (сценарий 12.6): начальную роль и роль, назначенную хоть кому-то, удалить нельзя."""
    Role = model("core.Role")
    admin = support.logged_in(support.make_admin())
    for role in Role.objects.filter(is_builtin=True):
        admin.post(f"/roles/{role.pk}/delete/")
        assert Role.objects.filter(pk=role.pk).exists(), f"встроенную роль {role.name} удалили"
    mine = factories.make_role(name="Занятая роль")
    holder = support.make_employee(roles=[mine])
    admin.post(f"/roles/{mine.pk}/delete/")
    assert Role.objects.filter(pk=mine.pk).exists()
    holder.roles.clear()
    admin.post(f"/roles/{mine.pk}/delete/")
    assert not Role.objects.filter(pk=mine.pk).exists()


def test_permissions_only_through_roles_union_of_several():
    """FR-017: права только через роли; у нескольких ролей действует объединение; отдельных прав и суперпользователя нет."""
    User = model("core.User")
    names = {f.name for f in User._meta.get_fields()}
    assert not names & {"is_superuser", "is_staff", "user_permissions", "groups"}
    both = support.make_employee(roles=[factories.make_role(permissions=("audit.view",)),
                                        factories.make_role(permissions=("roles.manage",))])
    client = support.logged_in(both)
    assert client.get("/audit/").status_code == 200 and client.get("/roles/").status_code == 200
    assert client.get("/staff/").status_code == 403 and client.get("/settings/security/").status_code == 403
    target = support.make_employee()
    admin = support.logged_in(support.make_admin())
    role = factories.make_role(permissions=("accounts.manage",))
    admin.post(f"/staff/{target.pk}/roles/", {"roles": [role.pk]})
    assert list(target.roles.all()) == [role]
    assert "role.assigned" in support.audit_actions(object_id=str(target.pk))
    assert support.logged_in(target, ip="198.51.100.31").get("/staff/").status_code == 200


def protected_table(victim, role):
    """Защищённые представления среза: (метод, путь, право)."""
    s = f"/staff/{victim.pk}"
    r = f"/roles/{role.pk}"
    return [
        ("get", "/staff/", "accounts.manage"), ("get", "/staff/new/", "accounts.manage"),
        ("post", "/staff/new/", "accounts.manage"), ("get", f"{s}/", "accounts.manage"),
        ("post", f"{s}/edit/", "accounts.manage"), ("post", f"{s}/roles/", "accounts.manage"),
        ("post", f"{s}/block/", "accounts.manage"), ("post", f"{s}/unblock/", "accounts.manage"),
        ("post", f"{s}/invite/", "accounts.manage"), ("post", f"{s}/unlock/", "accounts.manage"),
        ("get", "/staff/locks/", "accounts.manage"), ("post", "/staff/locks/", "accounts.manage"),
        ("post", f"{s}/reset-2fa/", "accounts.reset_2fa"), ("get", f"{s}/logins/", "accounts.view_logins"),
        ("get", "/roles/", "roles.manage"), ("get", "/roles/new/", "roles.manage"), ("post", "/roles/new/", "roles.manage"),
        ("get", f"{r}/", "roles.manage"), ("post", f"{r}/", "roles.manage"), ("post", f"{r}/delete/", "roles.manage"),
        ("get", "/audit/", "audit.view"), ("get", "/audit/export.csv", "audit.view"),
        ("get", "/settings/portal/", "settings.portal"), ("post", "/settings/portal/", "settings.portal"),
        ("get", "/settings/mail-log/", "settings.portal"),
        ("get", "/settings/security/", "settings.security"), ("post", "/settings/security/", "settings.security"),
    ]


def test_every_protected_view_requires_permission_403():
    """FR-018: право проверяется на каждом представлении независимо от меню; без входа — на вход, без права — 403."""
    victim, spare_role = support.make_employee(), factories.make_role(name="Запасная")
    table = protected_table(victim, spare_role)
    anonymous = support.make_client(ip="198.51.100.140")
    rest = {p: support.logged_in(make_with_permissions(*[q for q in PERMISSIONS if q != p]), ip="198.51.100.141")
            for p in PERMISSIONS}
    only = {p: support.logged_in(make_with_permissions(p), ip="198.51.100.142") for p in PERMISSIONS}
    for method, path, permission in table:
        label = f"{method.upper()} {path}"
        got = getattr(anonymous, method)(path)
        assert got.status_code == 302 and "/login/" in got["Location"], f"{label}: без входа"
        assert getattr(rest[permission], method)(path).status_code == 403, f"{label}: без права {permission}"
        got = getattr(only[permission], method)(path)
        assert got.status_code != 403 and not (got.status_code == 302 and "/login/" in got["Location"]), (
            f"{label}: с правом {permission} получили {got.status_code}")
    # таблица обязана покрывать все маршруты разделов, а неизвестных разделов быть не должно
    from tests.support_org import SLICE_002_STAFF_ROUTES, route_path

    known = ("login/", "logout/", "password/", "activate/", "me/", "staff/", "structure/", "calendar/", "ui/",
             "roles/", "audit/", "settings/", "health/", "media/", "static/", "")
    paths = [path for _, path, _ in table] + [route_path(t, 1) for _, t, _ in SLICE_002_STAFF_ROUTES]
    for route, _ in support.all_routes():
        assert route.startswith(known), f"маршрут {route!r} не относится ни к одному разделу плана"
        if route.startswith(("staff/", "roles/", "audit/", "settings/")):
            pattern = re.compile("^/" + re.sub(r"<[^>]+>", "[^/]+", route).replace(".", r"\.") + "$")
            assert any(pattern.match(p) for p in paths), f"маршрут {route} не покрыт проверкой прав"


def test_menu_hides_sections_without_permission():
    """FR-018, FR-050: пункт меню виден только с правом; без пункта прямой адрес всё равно закрыт."""
    def menu(user):
        html = support.logged_in(user).get("/me/").content.decode()
        return {perm for perm, link in SECTION_LINKS.items() if f'href="{link}"' in html}

    staff_html = support.logged_in(support.make_employee(roles=[support.role_by_name(support.STAFF_ROLE)])).get(
        "/me/").content.decode()
    for link in ("/staff/", "/structure/", "/calendar/"):
        assert f'href="{link}"' in staff_html, f"у «Сотрудника ИТ» в меню должен быть {link}"
    assert not [link for link in SECTION_LINKS.values() if link != "/staff/" and f'href="{link}"' in staff_html], (
        "разделов администрирования у «Сотрудника ИТ» в меню нет")
    assert menu(support.make_admin()) == set(SECTION_LINKS)
    for permission, link in SECTION_LINKS.items():
        user = make_with_permissions(permission)
        assert menu(user) == {permission}, f"с правом {permission} в меню должен быть только {link}"
    plain = support.logged_in(support.make_employee())
    assert all(plain.get(link).status_code == 403 for link in SECTION_LINKS.values())


def test_permission_cache_dropped_on_role_change_effect_next_request(django_capture_on_commit_callbacks):
    """FR-015, FR-017 (сценарий 12.2): объединение прав кэшируется в Valkey (perms:<id>); изменение роли сбрасывает кэш держателей."""
    role = factories.make_role(name="Меняемая", permissions=("audit.view",))
    holders = [support.make_employee(roles=[role]) for _ in range(2)]
    clients = [support.logged_in(h, ip=f"198.51.100.{150 + i}") for i, h in enumerate(holders)]
    assert all(c.get("/audit/").status_code == 200 for c in clients)
    assert all(support.valkey_key(f"perms:{h.pk}") for h in holders), "объединение прав не закэшировано"
    admin = support.logged_in(support.make_admin())
    with django_capture_on_commit_callbacks(execute=True):
        admin.post(f"/roles/{role.pk}/", {"name": "Меняемая", "permissions": ["roles.manage"]})
    assert not any(support.valkey_key(f"perms:{h.pk}") for h in holders), "кэш держателей роли не сброшен"
    for client in clients:
        assert client.get("/audit/").status_code == 403 and client.get("/roles/").status_code == 200
    extra = factories.make_role(name="Добавочная", permissions=("settings.security",))
    assert clients[0].get("/settings/security/").status_code == 403
    with django_capture_on_commit_callbacks(execute=True):
        admin.post(f"/staff/{holders[0].pk}/roles/", {"roles": [role.pk, extra.pk]})
    assert clients[0].get("/settings/security/").status_code == 200, "назначение роли действует со следующего запроса"
    assert clients[1].get("/settings/security/").status_code == 403


def test_permission_cache_loss_recomputes_from_database():
    """FR-017: потеря Valkey ведёт только к пересчёту прав из базы."""
    user = make_with_permissions("audit.view")
    client = support.logged_in(user)
    assert client.get("/audit/").status_code == 200
    r = support.valkey()
    r.flushdb()
    r.close()
    assert client.get("/audit/").status_code == 200, "после потери кэша права берутся из базы"
    assert client.get("/staff/").status_code == 403
    assert support.valkey_key(f"perms:{user.pk}"), "кэш наполняется заново"


def test_last_admin_cannot_lose_role_or_be_blocked():
    """FR-019 (сценарий 12.5): последнему администратору нельзя снять роль и нельзя его заблокировать."""
    User = model("core.User")
    helper = support.make_with_permissions("accounts.manage", "roles.manage")
    first, second = support.make_admin(), support.make_admin()
    client = support.logged_in(helper)
    admin_role = support.role_by_name(support.ADMIN_ROLE)
    client.post(f"/staff/{second.pk}/block/", {"reason": "лишний администратор"})
    second.refresh_from_db()
    assert second.state == "blocked", "пока есть другой администратор, блокировка допустима"
    refused = client.post(f"/staff/{first.pk}/block/", {"reason": "проверка"}, follow=True)
    first.refresh_from_db()
    assert first.state == "active" and "последн" in refused.content.decode().lower()
    refused = client.post(f"/staff/{first.pk}/roles/", {"roles": []}, follow=True)
    assert list(first.roles.all()) == [admin_role] and "последн" in refused.content.decode().lower()
    own = support.logged_in(first, ip="198.51.100.160")
    own.post(f"/staff/{first.pk}/block/", {"reason": "себя"})
    assert User.objects.get(pk=first.pk).state == "active"
    second.state = "active"
    second.save()
    client.post(f"/staff/{second.pk}/roles/", {"roles": []})
    assert not second.roles.exists(), "при двух администраторах роль снять можно"
