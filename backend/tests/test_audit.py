"""T-112: журнал событий (FR-018, FR-044…047, NFR-008). Сценарии 13 и 17.4.

Параметры списка `/audit/` и `/audit/export.csv` (tests/CONTRACT.md): `date_from`, `date_to`
(ГГГГ-ММ-ДД, по Москве), `user` (номер действующего лица), `action` (код события),
`object_type`, `object_id`, `preset` (`today`, `access`, `roles`, `settings`),
`sort` (`at`, `-at`, `action`, `-action`; по умолчанию `-at`). Строка таблицы несёт `data-event-id="<номер>"`.
"""
import ast
import csv
import io
import re
import sys
from datetime import datetime, timedelta, timezone as tz

import pytest
from django.db.models.signals import pre_save

from tests import factories, support
from tests.support import HX, model

pytestmark = pytest.mark.django_db

FR044_ACTIONS = {
    "login.success", "login.failed", "logout", "account.locked", "account.unlocked", "ip.locked", "ip.unlocked",
    "password.reset_requested", "user.created", "user.updated", "user.blocked", "user.unblocked", "invitation.sent",
    "user.activated", "totp.enrolled", "totp.reset", "backup_code.used", "backup_codes.issued", "password.changed",
    "sessions.logout_everywhere", "role.created", "role.updated", "role.deleted", "role.assigned",
    "security_settings.updated", "portal_settings.updated", "mail.status_changed",
}


def event_ids(html: str) -> set[int]:
    return {int(n) for n in re.findall(r'data-event-id="(\d+)"', html)}


def staff_edit(user, **over):
    data = {"full_name": user.full_name, "position": user.position, "phone": user.phone,
            "email": user.email, "contacts": ""}
    data.update(over)
    return data


def test_audit_event_for_each_action_in_fr044_list(django_capture_on_commit_callbacks, mailpit):
    """FR-044: каждое действие из перечня оставляет событие с нужным кодом (проходим настоящие сценарии)."""
    from tests.support_mail import deliver

    admin_user = support.make_admin()
    admin = support.logged_in(admin_user, ip="198.51.100.90")
    support.make_client(ip="198.51.100.91").post("/login/", {"email": admin_user.email, "password": factories.new_password()})
    support.make_client(ip="198.51.100.92").post("/password/forgot/", {"email": admin_user.email})
    # учётная запись: создание (+приглашение, письмо и его доставка), правка, блокировка, роли
    email = factories.new_email("audit")
    role = support.role_by_name(support.STAFF_ROLE)
    with django_capture_on_commit_callbacks(execute=True):
        assert admin.post("/staff/new/", {"email": email, "full_name": "Журналов Жан", "position": "Инженер",
                                          "roles": [role.pk]}).status_code == 302
    deliver()
    target = model("core.User").objects.get(email=email)
    admin.post(f"/staff/{target.pk}/edit/", staff_edit(target, position="Старший инженер"))
    admin.post(f"/staff/{target.pk}/block/", {"reason": "проверка журнала"})
    admin.post(f"/staff/{target.pk}/unblock/")
    # роли и настройки
    admin.post("/roles/new/", {"name": "Журнальная", "permissions": ["audit.view"]})
    made = model("core.Role").objects.get(name="Журнальная")
    admin.post(f"/roles/{made.pk}/", {"name": "Журнальная 2", "permissions": ["audit.view", "roles.manage"]})
    admin.post(f"/staff/{target.pk}/roles/", {"roles": [made.pk]})
    admin.post(f"/roles/{made.pk}/delete/")
    target.roles.clear()
    admin.post(f"/roles/{made.pk}/delete/")
    support.post_security_settings(admin, password_min_length=14)
    admin.post("/settings/portal/", {"name": "Портал для журнала"})
    # блокировки записи и адреса
    victim = support.make_employee()
    for _ in range(5):
        support.make_client(ip="198.51.100.93").post("/login/", {"email": victim.email, "password": factories.new_password()})
    admin.post(f"/staff/{victim.pk}/unlock/")
    support.set_security(account_lock_limit=100, ip_lock_limit=5, ip_lock_min_accounts=2)
    for i in range(6):
        support.make_client(ip="198.51.100.94").post(
            "/login/", {"email": [support.make_employee, support.make_employee][0]().email, "password": factories.new_password()})
    admin.post("/staff/locks/", {"kind": "ip", "target": "198.51.100.94"})
    # активация, резервный код, смена пароля, выход со всех, сброс второго фактора, выход
    user = support.make_employee(state="invited", totp=False, roles=[role])
    link, code = factories.make_link(user, "activation")
    client = support.make_client(ip="198.51.100.95")
    client.post("/activate/exchange/", {"code": code})
    client.post("/activate/profile/", {"phone": "+7 900 000-00-01", "contacts": ""})
    password = factories.new_password()
    client.post("/activate/password/", {"password1": password, "password2": password})
    _, codes = support.enroll_totp(client, user, totp_url="/activate/totp/", codes_url="/activate/codes/")
    user.test_password = password
    client.post("/me/security/backup-codes/new/")
    client.post("/logout/")
    client.post("/login/", {"email": user.email, "password": password})
    client.post("/login/code/", {"backup_code": codes[0]})
    new_password = factories.new_password()
    client.post("/me/security/password/", {"current_password": password, "password1": new_password, "password2": new_password})
    client.post("/me/security/logout-everywhere/")
    admin.post(f"/staff/{user.pk}/reset-2fa/")
    admin.post("/logout/")
    missing = FR044_ACTIONS - set(support.audit_actions())
    assert not missing, f"нет событий: {sorted(missing)}"


def test_audit_event_has_actor_time_object_before_after_ip(clock):
    """FR-044: событие хранит кто, когда, что, над чем, было, стало, IP."""
    admin_user = support.make_admin()
    admin = support.logged_in(admin_user, ip="198.51.100.96")
    target = support.make_employee(position="Инженер")
    clock.advance(hours=3)
    admin.post(f"/staff/{target.pk}/edit/", staff_edit(target, position="Главный инженер"), REMOTE_ADDR="198.51.100.96")
    event = model("core.AuditEvent").objects.get(action="user.updated", object_id=str(target.pk))
    assert event.actor_id == admin_user.pk and event.at == clock._now and event.ip == "198.51.100.96"
    assert event.object_type and isinstance(event.object_id, str)
    assert event.before["position"] == "Инженер" and event.after["position"] == "Главный инженер"
    system = model("core.AuditEvent").objects.filter(action="login.success", actor=admin_user).first()
    assert system is not None and system.ip == "198.51.100.96"


def test_audit_recorded_by_services_not_views():
    """FR-044: события пишут сервисы, а не представления: ни один модуль представлений не зовёт запись журнала."""
    from apps.core.models import AuditEvent


    callers: list[set[str]] = []

    def spy(sender, instance, **kwargs):
        frames, f = set(), sys._getframe(1)
        while f:
            frames.add(f.f_globals.get("__name__", ""))
            f = f.f_back
        callers.append(frames)

    pre_save.connect(spy, sender=AuditEvent, weak=False, dispatch_uid="audit-spy")
    try:
        admin = support.logged_in(support.make_admin(), ip="198.51.100.97")
        target = support.make_employee()
        admin.post(f"/staff/{target.pk}/block/", {"reason": "проверка слоя"})
        admin.post("/roles/new/", {"name": "Слойная", "permissions": []})
    finally:
        pre_save.disconnect(sender=AuditEvent, dispatch_uid="audit-spy")
    assert callers, "событий не записано"
    for frames in callers:
        assert any(".services" in name for name in frames), f"запись журнала не из сервиса: {sorted(frames)[:6]}"
    for path in (support.BACKEND_DIR / "apps").rglob("*.py"):
        if path.name == "views.py" or "views" in path.parts:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                names = [a.name for a in getattr(node, "names", [])] + [getattr(node, "module", "") or ""]
                assert not any("audit" in n and "services" in n or n == "record" for n in names if n), (
                    f"{path}: представление подключает запись журнала")


def test_no_audit_edit_or_delete_routes_even_for_admin():
    """FR-045 (сценарий 13.4): ни изменения, ни удаления записи журнала нет, в том числе у администратора."""
    admin = support.logged_in(support.make_admin(), ip="198.51.100.98")
    Event = model("core.AuditEvent")
    count, some = Event.objects.count(), Event.objects.first()
    for route, _ in support.all_routes():
        if route.startswith("audit/"):
            assert route in ("audit/", "audit/export.csv"), f"лишний маршрут журнала: {route}"
    for method in ("post", "put", "patch", "delete"):
        for path in ("/audit/", "/audit/export.csv", f"/audit/{some.pk}/", f"/audit/{some.pk}/delete/", f"/audit/{some.pk}/edit/"):
            assert getattr(admin, method)(path).status_code in (404, 405), f"{method.upper()} {path}"
    assert Event.objects.count() >= count and Event.objects.filter(pk=some.pk).exists()
    assert "django.contrib.admin" not in __import__("django.conf").conf.settings.INSTALLED_APPS


def test_audit_actor_protected_users_not_deletable():
    """FR-045, NFR-008: действующее лицо журнала — PROTECT: пользователь с событиями не удаляется, SET_NULL (UPDATE журнала) не применяется."""
    from django.db import models
    from django.db.models import ProtectedError

    assert model("core.AuditEvent")._meta.get_field("actor").remote_field.on_delete is models.PROTECT
    user = support.make_employee()
    support.logged_in(user, ip="198.51.100.99")
    assert model("core.AuditEvent").objects.filter(actor=user).exists()
    with pytest.raises(ProtectedError):
        user.delete()


def test_no_automatic_audit_deletion_retention_3_years(clock):
    """FR-045, NFR-008: журнал хранится без срока (не меньше 3 лет): ночные задания его не трогают, настройки срока для журнала нет."""
    from apps.core.services import retention
    from apps.core.services.audit import record

    Event = model("core.AuditEvent")
    now = clock._now
    clock.set(now - timedelta(days=4 * 365))
    record("probe.old", object_type="probe", object_id="1")
    clock.set(now - timedelta(days=3 * 365 + 10))
    record("probe.older_than_3y", object_type="probe", object_id="2")
    clock.set(now)
    for name in ("purge_login_history", "purge_expired_links", "purge_expired_sessions"):
        getattr(retention, name)()
    assert set(Event.objects.filter(object_type="probe").values_list("action", flat=True)) == {"probe.old", "probe.older_than_3y"}
    fields = {f.name for f in model("core.SecuritySettings")._meta.get_fields()}
    assert not [n for n in fields if "audit" in n]

    for path in (support.BACKEND_DIR / "apps").rglob("*.py"):
        for line in path.read_text(encoding="utf-8").splitlines():
            assert not (re.search(r"auditevent", line, re.I) and re.search(r"\.delete\(|_raw_delete|truncate", line, re.I)), (
                f"{path}: удаление журнала: {line.strip()}")


def test_audit_never_contains_passwords_keys_codes_link_codes():
    """FR-046: пароли, ключи TOTP, резервные коды и коды ссылок не попадают в журнал ни в каком виде (ни в таблицу, ни на страницу, ни в CSV)."""
    user = support.make_employee(state="invited", totp=False, roles=[support.role_by_name(support.STAFF_ROLE)])
    link, code = factories.make_link(user, "activation")
    client = support.make_client(ip="198.51.100.100")
    client.post("/activate/exchange/", {"code": code})
    client.post("/activate/profile/", {"phone": "+7 900 000-00-02", "contacts": ""})
    password = factories.new_password()
    client.post("/activate/password/", {"password1": password, "password2": password})
    key, codes = support.enroll_totp(client, user, totp_url="/activate/totp/", codes_url="/activate/codes/")
    newer = factories.new_password()
    client.post("/me/security/password/", {"current_password": password, "password1": newer, "password2": newer})
    wrong = factories.new_password()
    support.make_client(ip="198.51.100.101").post("/login/", {"email": user.email, "password": wrong})
    admin = support.logged_in(support.make_admin(), ip="198.51.100.102")
    admin.post(f"/staff/{user.pk}/invite/")
    admin.get(f"/staff/{user.pk}/")
    secrets_ = [password, newer, wrong, code, key.hex(), factories.totp_code(key), *codes,
                support.link_code(model("core.OneTimeLink").objects.filter(user=user, revoked_at__isnull=True).first() or link)
                if model("core.OneTimeLink").objects.filter(user=user, revoked_at__isnull=True).exists() else code]
    dump = " ".join(
        " ".join(str(getattr(e, f.name)) for f in e._meta.concrete_fields) for e in model("core.AuditEvent").objects.all())
    page = admin.get("/audit/").content.decode() + admin.get("/audit/export.csv").content.decode()
    for secret in secrets_:
        assert secret not in dump and secret not in page, "секрет попал в журнал"


def make_events(clock):
    """Набор событий в разные дни; возвращает (администратор, словарь имя → номер события)."""
    admin_user = support.make_admin()
    other = support.make_employee()
    Event = model("core.AuditEvent")
    from apps.core.services.audit import record

    base = datetime(2026, 9, 1, 9, 0, tzinfo=tz.utc)
    plan = (("old.access", "login.success", admin_user, "user", "1", 0), ("old.roles", "role.updated", admin_user, "role", "7", 1),
            ("mid.settings", "security_settings.updated", other, "settings", "1", 10),
            ("today.access", "login.failed", other, "user", "9", 30), ("today.roles", "role.assigned", admin_user, "user", "9", 30))
    ids = {}
    for name, action, actor, otype, oid, day in plan:
        clock.set(base + timedelta(days=day))
        record(action, actor=actor, object_type=otype, object_id=oid)
        ids[name] = Event.objects.filter(action=action).order_by("-id").first().pk
    clock.set(base + timedelta(days=30, hours=2))
    return admin_user, other, ids


def test_audit_filters_by_period_user_action_object_with_presets_and_sort(clock):
    """FR-047 (сценарий 13.1, 13.2): фильтры по периоду, пользователю, виду действия, объекту; пресеты; сортировка; HTMX — только таблица."""
    admin_user, other, ids = make_events(clock)
    client = support.logged_in(admin_user, ip="198.51.100.103")
    clock.set(datetime(2026, 10, 1, 12, 0, tzinfo=tz.utc))

    def found(**params):
        qs = "&".join(f"{k}={v}" for k, v in params.items())
        return event_ids(client.get("/audit/?" + qs).content.decode())

    assert {ids["old.access"], ids["old.roles"]} <= found(date_from="2026-09-01", date_to="2026-09-02")
    assert not {ids["mid.settings"], ids["today.access"]} & found(date_from="2026-09-01", date_to="2026-09-02")
    assert found(user=other.pk, action="login.failed") & {ids["today.access"]} and ids["old.access"] not in found(user=other.pk)
    assert ids["old.roles"] in found(object_type="role", object_id="7") and ids["old.access"] not in found(object_type="role")
    assert ids["old.access"] in found(preset="access") and ids["mid.settings"] not in found(preset="access")
    assert ids["old.roles"] in found(preset="roles") and ids["old.access"] not in found(preset="roles")
    assert ids["mid.settings"] in found(preset="settings") and ids["old.roles"] not in found(preset="settings")
    clock.set(datetime(2026, 10, 1, 12, 0, tzinfo=tz.utc))
    today = found(preset="today")
    assert today and ids["old.access"] not in today
    html = client.get("/audit/?sort=at").content.decode()
    order = [int(n) for n in re.findall(r'data-event-id="(\d+)"', html)]
    assert order == sorted(order), "сортировка по времени по возрастанию"
    desc = [int(n) for n in re.findall(r'data-event-id="(\d+)"', client.get("/audit/?sort=-at").content.decode())]
    assert desc == sorted(desc, reverse=True)
    fragment = client.get("/audit/?preset=access", **HX).content.decode()
    assert "<html" not in fragment and event_ids(fragment)


def test_audit_csv_export_applies_filter_and_escapes_formulas(clock):
    """FR-047 (сценарий 13.6): выгрузка CSV — текущая выборка; ячейки на `=`, `+`, `-`, `@` получают апостроф."""
    from apps.core.services.audit import record

    admin_user = support.make_admin(full_name="=HYPERLINK(1)")
    client = support.logged_in(admin_user, ip="198.51.100.104")
    record("probe.formula", actor=admin_user, object_type="+SUM", object_id="=1+1", before={"a": "-2"}, after={"b": "@x"})
    record("probe.other", object_type="plain", object_id="2")
    done = client.get("/audit/export.csv?action=probe.formula")
    assert done.status_code == 200 and done["Content-Type"].startswith("text/csv")
    assert "attachment" in done.get("Content-Disposition", "")
    rows = list(csv.reader(io.StringIO(done.content.decode("utf-8-sig"))))
    assert len(rows) == 2, "заголовок и одна строка выборки"
    cells = [c for row in rows[1:] for c in row]
    assert "'=1+1" in cells and "'+SUM" in cells
    assert not [c for c in cells if c.startswith(("=", "+", "-", "@"))], cells
    everything = list(csv.reader(io.StringIO(client.get("/audit/export.csv").content.decode("utf-8-sig"))))
    assert len(everything) > 2


def test_audit_view_needs_audit_view_permission():
    """FR-047, FR-018 (сценарий 13.5): без права просмотра журнала и выгрузки — отказ."""
    plain = support.logged_in(support.make_with_permissions("accounts.manage"), ip="198.51.100.105")
    for path in ("/audit/", "/audit/export.csv"):
        assert plain.get(path).status_code == 403
    reader = support.logged_in(support.make_with_permissions("audit.view"), ip="198.51.100.106")
    assert reader.get("/audit/").status_code == 200 and reader.get("/audit/export.csv").status_code == 200
    anonymous = support.make_client(ip="198.51.100.107").get("/audit/")
    assert anonymous.status_code == 302 and "/login/" in anonymous["Location"]
