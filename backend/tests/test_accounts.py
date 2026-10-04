"""T-103: учётные записи (FR-001…008, FR-044). Сценарии 1, 2, 15 спеки."""
import re
from datetime import timedelta
from io import StringIO

import pytest
from django.conf import settings
from django.core.management import CommandError, call_command
from django.db import IntegrityError, transaction

from tests import factories, support
from tests.support import HX, model

pytestmark = pytest.mark.django_db

NEW_STAFF = {"full_name": "Пётр Сидоров", "position": "Инженер", "phone": ""}


def staff_form(role, **over):
    return {**NEW_STAFF, "email": factories.new_email("new"), "roles": [role.pk], **over}


def test_create_user_needs_permission_and_required_fields():
    """FR-001: запись создаёт только администратор; ФИО, почта, должность и роль обязательны, телефон — нет."""
    User = model("core.User")
    admin, role = support.make_admin(), support.role_by_name(support.STAFF_ROLE)
    client = support.logged_in(admin)
    data = staff_form(role, phone="+7 900 000-00-00")
    done = client.post("/staff/new/", data)
    assert done.status_code == 302
    created = User.objects.get(email=data["email"])
    assert (created.full_name, created.position, created.phone, created.state) == (
        "Пётр Сидоров", "Инженер", "+7 900 000-00-00", "invited")
    assert list(created.roles.all()) == [role]
    assert done["Location"].endswith(f"/staff/{created.pk}/")
    # телефон необязателен, остальное — обязательно
    assert client.post("/staff/new/", {k: v for k, v in staff_form(role).items() if k != "phone"}).status_code == 302
    before = User.objects.count()
    for missing in ("email", "full_name", "position", "roles"):
        broken = staff_form(role)
        broken.pop(missing)
        assert client.post("/staff/new/", broken).status_code == 200, f"без поля {missing} форма должна вернуться с ошибкой"
    assert User.objects.count() == before
    # без права и без входа
    plain = support.logged_in(support.make_employee(roles=[role]))
    assert plain.get("/staff/new/").status_code == 403
    assert plain.post("/staff/new/", staff_form(role)).status_code == 403
    assert support.make_client().get("/staff/new/").status_code == 302
    assert User.objects.count() == before + 1, "новая запись — только plain, созданная тестом"


def test_email_unique_case_insensitive_and_is_login():
    """FR-002: рабочая почта уникальна без учёта регистра и служит именем входа."""
    User = model("core.User")
    existing = support.make_employee(email="Ivanov.Test@Example.com")
    with pytest.raises(IntegrityError), transaction.atomic():
        factories.make_user(email="ivanov.test@example.com")
    admin, role = support.make_admin(), support.role_by_name(support.STAFF_ROLE)
    done = support.logged_in(admin).post("/staff/new/", staff_form(role, email="IVANOV.TEST@example.COM"))
    assert done.status_code == 200 and "уже" in done.content.decode().lower()
    assert User.objects.filter(email__iexact="ivanov.test@example.com").count() == 1
    client = support.make_client()
    again = support.post_password(client, existing.email.upper(), existing.test_password)
    assert again.status_code == 302 and again["Location"].endswith("/login/code/")


def test_user_states_invited_active_blocked_only():
    """FR-003, FR-124: у записи четыре состояния, в том числе «уволен»."""
    User = model("core.User")
    assert {value for value, _ in User._meta.get_field("state").choices} == {"invited", "active", "blocked", "dismissed"}
    admin, role = support.make_admin(), support.role_by_name(support.STAFF_ROLE)
    client = support.logged_in(admin)
    data = staff_form(role)
    client.post("/staff/new/", data)
    target = User.objects.get(email=data["email"])
    assert target.state == "invited"
    client.post(f"/staff/{target.pk}/block/", {"reason": "проверка"})
    target.refresh_from_db()
    assert target.state == "blocked"
    assert {"user.created", "user.blocked"} <= set(support.audit_actions(object_id=str(target.pk)))


def test_staff_list_filters_search_sort_pagination():
    """FR-004: фильтр по состоянию и роли, поиск по ФИО и почте, сортировка, 25 строк на страницу."""
    manager_role = factories.make_role(name="Аудитор-тест")
    anna = support.make_employee(full_name="Анна Алфавитова", email="anna-search@example.com")
    boris = support.make_employee(full_name="Борис Бетов", email="boris-search@example.com", roles=[manager_role])
    vera = support.make_employee(full_name="Вера Вётова", email="vera-search@example.com", state="blocked")
    ivan = support.make_employee(full_name="Иван Приглашённый", email="ivan-search@example.com", state="invited", totp=False)
    client = support.logged_in(support.make_admin())
    emails = {u: u.email for u in (anna, boris, vera, ivan)}

    def present(html):
        return {u for u, e in emails.items() if e in html}

    page = lambda query: client.get("/staff/" + query).content.decode()  # noqa: E731
    assert present(page("?state=blocked")) == {vera}
    assert present(page("?state=invited")) == {ivan}
    assert present(page(f"?role={manager_role.pk}")) == {boris}
    assert present(page("?q=алфавит")) == {anna}
    assert present(page("?q=BORIS-SEARCH")) == {boris}
    ordered = page("?q=search&sort=full_name")
    assert ordered.index(anna.email) < ordered.index(boris.email) < ordered.index(vera.email) < ordered.index(ivan.email)
    reverse = page("?q=search&sort=-full_name")
    assert reverse.index(ivan.email) < reverse.index(vera.email) < reverse.index(boris.email) < reverse.index(anna.email)
    for n in range(30):
        factories.make_user(email=f"bulk{n:02d}-page@example.com", full_name=f"Массовый {n:02d}")
    found = lambda html: set(re.findall(r"bulk\d\d-page@example\.com", html))  # noqa: E731
    first, second = found(page("?q=bulk&sort=email")), found(page("?q=bulk&sort=email&page=2"))
    assert len(first) == 25 and len(second) == 5 and not first & second


def test_staff_card_has_own_url_and_htmx_fragment():
    """FR-004: у карточки свой адрес /staff/<id>/; HTMX получает фрагмент, обычный запрос — страницу целиком."""
    target = support.make_employee(full_name="Карточкин Кирилл")
    client = support.logged_in(support.make_admin())
    full = client.get(f"/staff/{target.pk}/")
    fragment = client.get(f"/staff/{target.pk}/", **HX)
    assert full.status_code == fragment.status_code == 200
    assert "<html" in full.content.decode() and target.email in full.content.decode()
    body = fragment.content.decode()
    assert "<html" not in body and "<body" not in body and target.email in body and "Карточкин" in body
    listing = client.get("/staff/", **HX).content.decode()
    assert "<html" not in listing and target.email in listing


def test_admin_edits_profile_and_blocks_user_closes_sessions():
    """FR-005 (сценарий 15): правка профиля, блокировка закрывает все сессии сразу, разблокировка возвращает вход."""
    User, Session = model("core.User"), model("core.UserSession")
    admin = support.make_admin()
    worker = support.make_employee(full_name="Старое Имя", position="Старая должность")
    admin_client, worker_client = support.logged_in(admin), support.logged_in(worker, ip="198.51.100.20")
    assert worker_client.get("/me/").status_code == 200
    done = admin_client.post(f"/staff/{worker.pk}/edit/", {
        "full_name": "Новое Имя", "position": "Новая должность", "phone": "+7 111", "email": worker.email,
        "contacts": "telegram: @worker"})
    assert done.status_code == 302
    worker.refresh_from_db()
    assert (worker.full_name, worker.position, worker.phone) == ("Новое Имя", "Новая должность", "+7 111")
    edited = model("core.AuditEvent").objects.filter(action="user.updated", object_id=str(worker.pk)).get()
    assert edited.actor_id == admin.pk and edited.before["full_name"] == "Старое Имя" and edited.after["full_name"] == "Новое Имя"
    admin_client.post(f"/staff/{worker.pk}/block/", {"reason": "подозрение на компрометацию"})
    worker.refresh_from_db()
    assert worker.state == "blocked" and "компрометац" in worker.blocked_reason
    assert not Session.objects.filter(user=worker).exists()
    after = worker_client.get("/me/")
    assert after.status_code == 302 and "/login/" in after["Location"]
    blocked_event = model("core.AuditEvent").objects.get(action="user.blocked", object_id=str(worker.pk))
    assert blocked_event.actor_id == admin.pk and "компрометац" in str(blocked_event.after)
    admin_client.post(f"/staff/{worker.pk}/unblock/")
    worker.refresh_from_db()
    assert worker.state == "active"
    support.login(support.make_client(ip="198.51.100.21"), worker)  # прежним паролем и тем же фактором
    assert "user.unblocked" in support.audit_actions(object_id=str(worker.pk))
    assert User.objects.filter(pk=worker.pk).exists()


def test_no_delete_user_route_or_service():
    """FR-005: удаления записи нет ни в маршрутах, ни в сервисах."""
    from apps.core.services import accounts

    target = support.make_employee()
    client = support.logged_in(support.make_admin())
    for method, path in (("post", f"/staff/{target.pk}/delete/"), ("delete", f"/staff/{target.pk}/"),
                         ("post", f"/staff/{target.pk}/remove/")):
        assert getattr(client, method)(path).status_code in (404, 405), f"{method} {path}"
    assert model("core.User").objects.filter(pk=target.pk).exists()
    routes = [route for route, _ in support.all_routes()]
    assert routes, "в URLconf нет маршрутов"
    assert not [r for r in routes if re.search(r"delete|remove|destroy", r) and r.startswith("staff/")
                and "/photo/" not in r]
    assert not [n for n in dir(accounts) if re.match(r"(delete|remove|destroy)_user", n)]


def test_employee_edits_only_phone_and_contacts():
    """FR-006: сотрудник правит свой телефон и контакты; ФИО, почту, должность и роль — нет."""
    role = support.role_by_name(support.STAFF_ROLE)
    me = support.make_employee(full_name="Свой Профиль", position="Инженер", roles=[role])
    client = support.logged_in(me)
    assert client.get("/me/").status_code == 200
    done = client.post("/me/", {"phone": "+7 222", "contacts": "telegram: @mine", "full_name": "Взломщик",
                                "position": "Директор", "email": "hacker@example.com",
                                "roles": [support.role_by_name(support.ADMIN_ROLE).pk]})
    assert done.status_code in (200, 302)
    me.refresh_from_db()
    assert me.phone == "+7 222" and "@mine" in str(me.contacts)
    assert (me.full_name, me.position) == ("Свой Профиль", "Инженер")
    assert me.email != "hacker@example.com" and list(me.roles.all()) == [role]
    other = support.make_employee()
    assert client.post(f"/staff/{other.pk}/edit/", {"full_name": "X", "position": "Y"}).status_code == 403


def test_no_self_registration_routes():
    """FR-007: самостоятельной регистрации нет, записи заводит только администратор."""
    User = model("core.User")
    before = User.objects.count()
    client = support.make_client()
    for path in ("/register/", "/signup/", "/registration/", "/accounts/signup/", "/accounts/register/", "/join/"):
        assert client.get(path).status_code == 404 and client.post(path, {"email": "x@example.com"}).status_code == 404
    assert client.post("/staff/new/", staff_form(support.role_by_name(support.STAFF_ROLE))).status_code in (302, 403)
    support.post_password(client, factories.new_email("ghost"), factories.new_password())
    assert User.objects.count() == before
    assert not [r for r, _ in support.all_routes() if re.search(r"regist|signup|sign-up", r)]


def test_create_first_admin_refuses_when_users_exist():
    """FR-001, FR-003: команда выдачи первого администратора отказывает, если записи уже есть."""
    User = model("core.User")
    support.make_employee()
    before = User.objects.count()
    with pytest.raises(CommandError):
        call_command("create_first_admin", "--email", factories.new_email("first"), stdout=StringIO())
    assert User.objects.count() == before


def test_create_first_admin_logs_event_and_prints_link(clock):
    """FR-008, FR-044 (сценарий 1): одна запись с ролью администратора, ссылка на 72 часа печатается, событие — от «системы»."""
    User, Link = model("core.User"), model("core.OneTimeLink")
    assert not User.objects.exists()
    assert set(model("core.Role").objects.values_list("name", flat=True)) >= {
        support.ADMIN_ROLE, support.MANAGER_ROLE, support.STAFF_ROLE}
    email, out = factories.new_email("first"), StringIO()
    call_command("create_first_admin", "--email", email, stdout=out)
    printed = re.search(re.escape(settings.PORTAL_URL) + r"/activate/#([A-Za-z0-9_\-]{40,})", out.getvalue())
    assert printed, "команда не напечатала ссылку активации"
    admin = User.objects.get()
    assert (admin.email, admin.state) == (email, "invited")
    assert [r.name for r in admin.roles.all()] == [support.ADMIN_ROLE]
    link = Link.objects.get(user=admin)
    assert link.purpose == "activation" and link.token_hash == support.sha256(printed.group(1))
    assert support.link_code(link) == printed.group(1)
    assert timedelta(hours=71, minutes=59) < link.expires_at - clock._now <= timedelta(hours=72)
    created = model("core.AuditEvent").objects.get(action="user.created", object_id=str(admin.pk))
    assert created.actor_id is None, "действующее лицо — «система»"
    assert not support.mails(), "письмо первому администратору не нужно"
    assert printed.group(1) not in str(created.after) and printed.group(1) not in str(created.before)
