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
from django.db import connection
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
    fresh = client.post("/me/security/backup-codes/new/")
    codes = support.backup_code_values(fresh.content.decode())  # прежний набор погашен — входим кодом из нового
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
    clock.advance(minutes=30)  # меньше порога бездействия (60 мин): сессия жива, время события — сдвинутое
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
    # код использованной ссылки по контракту стёрт (его и нечего расшифровывать) — проверяем исходный
    # код активации и коды ссылок, которые ещё живы
    live = model("core.OneTimeLink").objects.filter(user=user, used_at__isnull=True, revoked_at__isnull=True).exclude(code_encrypted="")
    secrets_ = [password, newer, wrong, code, key.hex(), factories.totp_code(key), *codes,
                *[support.link_code(l) for l in live]]
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


HX_RESULTS = {**HX, "HTTP_HX_TARGET": "audit-results"}


def sql_of(client, path, **headers) -> list[str]:
    """Тексты SQL, ушедшие в базу за один запрос страницы."""
    seen = []

    def spy(execute, sql, params, many, context):
        seen.append(sql)
        return execute(sql, params, many, context)

    with connection.execute_wrapper(spy):
        got = client.get(path, **headers)
    assert got.status_code == 200, path
    return seen


def pager(html: str) -> str:
    """Нижняя панель журнала: количество, номер страницы, «Назад» и «Вперёд»."""
    return html.split('aria-label="Страницы журнала"', 1)[1].split("</nav>", 1)[0]


def test_audit_counts_selection_only_on_request():
    """FR-047, NFR-002 (UX-04, п. 6; PLAN-001 «Уточнения версии 4»): показ журнала не считает выборку —
    внизу «Всего: показать количество»; ссылка с текущими условиями и `count=1` показывает точное число."""
    from apps.core.services.audit import record

    admin_user = support.make_admin()
    client = support.logged_in(admin_user, ip="198.51.100.108")
    for i in range(3):
        record("role.updated", actor=admin_user, object_type="role", object_id=str(i))
    for path, headers in (("/audit/", {}), ("/audit/?preset=access", {}), ("/audit/?preset=roles&sort=at", HX_RESULTS)):
        counted = [sql for sql in sql_of(client, path, **headers) if "COUNT(" in sql.upper() and "core_auditevent" in sql]
        assert not counted, f"{path}: журнал считает выборку на каждый показ: {counted}"
    html = client.get("/audit/?preset=roles&sort=at").content.decode()
    link = re.search(r'<a [^>]*href="([^"]*count=1[^"]*)"[^>]*>показать количество</a>', pager(html))
    assert link, "внизу журнала нет ссылки «показать количество»"
    href = link.group(1).replace("&amp;", "&")
    assert "preset=roles" in href and "sort=at" in href, f"ссылка теряет условия выборки: {href}"
    roles_total = model("core.AuditEvent").objects.filter(action__startswith="role.").count()
    assert roles_total >= 3
    for headers in ({}, HX_RESULTS):
        shown = client.get(href, **headers).content.decode()
        assert f"Всего: {roles_total}." in pager(shown) and "показать количество" not in shown
    assert "<html" not in client.get(href, **HX_RESULTS).content.decode(), "по HTMX обновляется только таблица"


def test_audit_pages_forward_and_back_without_total():
    """FR-047 (PLAN-001 «Уточнения версии 4»): по 50 строк, «Страница N» без «из M»; «Вперёд» — пока за
    страницей есть строки, «Назад» — со второй; страницы не пересекаются и вместе дают всю выборку;
    номер за концом выборки и неверный номер — первая страница."""
    from apps.core.services.audit import record

    admin_user = support.make_admin()
    client = support.logged_in(admin_user, ip="198.51.100.109")
    for i in range(105):
        record("probe.page", actor=admin_user, object_type="probe", object_id=str(i))
    for i in range(50):
        record("probe.exact", actor=admin_user, object_type="probe", object_id=str(i))

    def page(action, number):
        html = client.get(f"/audit/?action={action}&page={number}").content.decode()
        return pager(html), event_ids(html)

    (nav1, ids1), (nav2, ids2), (nav3, ids3) = (page("probe.page", n) for n in (1, 2, 3))
    assert (len(ids1), len(ids2), len(ids3)) == (50, 50, 5)
    every = set(model("core.AuditEvent").objects.filter(action="probe.page").values_list("pk", flat=True))
    assert not ids1 & ids2 and not ids2 & ids3 and ids1 | ids2 | ids3 == every
    for nav, number, back, forward in ((nav1, 1, False, True), (nav2, 2, True, True), (nav3, 3, True, False)):
        assert f"Страница {number}." in nav and " из " not in nav, nav
        assert (">Назад</a>" in nav, ">Вперёд</a>" in nav) == (back, forward), f"страница {number}: {nav}"
    forward_href = re.search(r'href="([^"]+)"[^>]*>Вперёд</a>', nav1).group(1).replace("&amp;", "&")
    assert "page=2" in forward_href and "action=probe.page" in forward_href
    exact_nav, exact_ids = page("probe.exact", 1)
    assert len(exact_ids) == 50 and ">Вперёд</a>" not in exact_nav, "ровно 50 строк — следующей страницы нет"
    for wrong in ("99", "abc", "0", "-3", "1" + "0" * 30):
        nav, ids = page("probe.page", wrong)
        assert ids == ids1 and "Страница 1." in nav, f"page={wrong}"


def test_audit_csv_export_applies_filter_and_escapes_formulas(clock):
    """FR-047 (сценарий 13.6): выгрузка CSV — текущая выборка; ячейки на `=`, `+`, `-`, `@`, табуляция, возврат каретки получают апостроф."""
    from apps.core.services.audit import record

    admin_user = support.make_admin(full_name="=HYPERLINK(1)")
    client = support.logged_in(admin_user, ip="198.51.100.104")
    record("probe.formula", actor=admin_user, object_type="+SUM", object_id="=1+1", before={"a": "-2"}, after={"b": "@x"})
    tab_actor = support.make_admin(full_name="\tТабов")
    record("probe.formula", actor=tab_actor, object_type="\tВид", object_id="\rНомер", before={"a": "\t1"}, after={"b": "\r2"})
    record("probe.other", object_type="plain", object_id="2")
    done = client.get("/audit/export.csv?action=probe.formula")
    assert done.status_code == 200 and done["Content-Type"].startswith("text/csv")
    assert "attachment" in done.get("Content-Disposition", "")
    rows = list(csv.reader(io.StringIO(done.content.decode("utf-8-sig"))))
    assert len(rows) == 3, "заголовок и две строки выборки"
    cells = [c for row in rows[1:] for c in row]
    assert "'=1+1" in cells and "'+SUM" in cells
    assert "'\tВид" in cells and "'\rНомер" in cells and any(c.startswith("'\tТабов") for c in cells), cells
    assert not [c for c in cells if c.startswith(("=", "+", "-", "@"))], cells
    assert not [c for c in cells if c.startswith(("\t", "\r"))], cells
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


# --- T-301 F3: журнал по-русски ---------------------------------------------------------------

def _written_keys() -> set[str]:
    """Все ключи «было/стало», которые пишет код среза: разбор вызовов `audit.record` в исходниках."""
    import re
    from pathlib import Path

    from apps.core.services import security_settings

    root = Path(__file__).resolve().parent.parent / "apps"
    keys = {"email", "full_name", "position", "phone", "contacts"}  # accounts._snapshot
    keys |= set(security_settings.BOUNDS)
    for path in root.rglob("*.py"):
        if "migrations" in path.parts or path.name == "audit.py":
            continue
        text = path.read_text(encoding="utf-8")
        for block in re.findall(r"audit\.record\((.*?)\n\s*\n|audit\.record\((.*?)\)\n", text, flags=re.S):
            for part in re.findall(r"(?:before|after)=\{(.*?)\}", "".join(block), flags=re.S):
                keys |= set(re.findall(r'"(\w+)":', part))
    return keys


def test_audit_every_written_key_has_russian_label():
    from apps.core.templatetags.portal import pairs

    keys = _written_keys()
    assert {"via", "count", "confirmed", "remaining", "result", "step", "attempts", "minutes", "closed", "changed",
            "expires_at", "status", "permissions"} <= keys, keys
    for key in sorted(keys):
        label, _ = pairs({key: 1})[0]
        assert label != key and not label.isascii(), f"ключ {key} не переведён"


def test_audit_value_codes_are_russian():
    from apps.core.templatetags.portal import pairs

    def shown(key, value):
        return pairs({key: value})[0][1]

    for key, values in {
        "via": ["activation", "password", "backup", "totp", "reset"],
        "result": ["success", "bad_password", "bad_code", "locked", "ip_locked", "backup_code"],
        "step": ["password", "code", "totp_setup", "change_password"],
        "status": ["queued", "sent", "failed"],
    }.items():
        for value in values:
            assert not shown(key, value).isascii() and shown(key, value) != value, (key, value)


def test_audit_datetime_shown_in_moscow_time_and_permissions_by_title():
    from apps.core.templatetags.portal import pairs

    assert pairs({"expires_at": "2026-10-06T20:09:45.369087+00:00"})[0][1] == "06.10.2026 23:09"
    perm = model("core.Permission").objects.get(code="audit.view")
    assert pairs({"permissions": ["audit.view"]})[0][1] == perm.title


def test_audit_object_kind_in_russian_and_filter_is_dropdown_with_old_param_values():
    from apps.core.templatetags.portal import object_label

    assert object_label("user", 1) == "сотрудник № 1" and object_label("link", 3) == "ссылка № 3"
    assert object_label("mail", 2) == "письмо № 2" and object_label("role", 5) == "роль № 5"
    admin = support.logged_in(support.make_admin(), ip="198.51.100.201")
    page = admin.get("/audit/?object_type=user").content.decode()
    assert '<select class="form-select" id="id_object_type"' in page and 'value="user" selected' in page
    assert "сотрудник" in page and "user, role" not in page
    assert admin.get("/audit/?object_type=user").status_code == 200


def test_audit_changed_fields_only_for_settings_events():
    from apps.core.templatetags.portal import side_pairs

    event = model("core.AuditEvent")(action="security_settings.updated",
                                     before={"password_min_length": 12, "idle_timeout_minutes": 60},
                                     after={"password_min_length": 14, "idle_timeout_minutes": 60})
    assert [label for label, _ in side_pairs(event, "before")] == [label for label, _ in side_pairs(event, "after")]
    assert len(side_pairs(event, "before")) == 1 and side_pairs(event, "after")[0][1] == "14"
    same = model("core.AuditEvent")(action="portal_settings.updated", before={"name": "A"}, after={"name": "A"})
    assert len(side_pairs(same, "after")) == 1, "ничего не изменилось — как сейчас"


def test_audit_csv_is_russian_like_the_page_with_event_code_column(clock):
    """FR-047, NFR-010, PLAN-001 версия 4 «Выгрузка журнала — как экран»: CSV по-русски, плюс колонка «Код события»."""
    from apps.core.services import audit_search
    from apps.core.services.audit import record

    admin_user = support.make_admin()
    client = support.logged_in(admin_user, ip="198.51.100.105")
    clock.set(datetime(2026, 9, 1, 9, 5, 7, tzinfo=tz.utc))
    record("security_settings.updated", actor=admin_user, object_type="security_settings", object_id="1",
           before={"password_min_length": 12, "idle_timeout_minutes": 60},
           after={"password_min_length": 14, "idle_timeout_minutes": 60})
    record("login.failed", object_type="user", object_id="9", before={}, after={"result": "bad_password"})
    record("role.created", actor=admin_user, object_type="role", object_id="7",
           after={"name": "Проверяющий", "permissions": ["audit.view"]})
    perm_title = model("core.Permission").objects.get(code="audit.view").title

    rows = list(csv.reader(io.StringIO(client.get("/audit/export.csv?sort=at").content.decode("utf-8-sig"))))
    assert rows[0] == ["Номер", "Время (Москва)", "Кто", "Событие", "Код события", "Вид объекта", "Номер объекта",
                       "Было", "Стало", "Адрес"]
    by_code = {row[4]: row for row in rows[1:]}

    def has_no_ascii_key(cell, keys):
        return not any(re.search(rf"\b{key}\b", cell) for key in keys)

    settings_row = by_code["security_settings.updated"]
    assert settings_row[3] == audit_search.ACTION_TITLES["security_settings.updated"]
    assert settings_row[5] == "настройки безопасности" and settings_row[6] == "1"
    assert settings_row[1] == "2026-09-01 12:05:07", "время по Москве, ГГГГ-ММ-ДД ЧЧ:ММ:СС"
    assert settings_row[7].endswith(": 12") and settings_row[8].endswith(": 14"), (settings_row[7], settings_row[8])
    assert "; " not in settings_row[8], "изменилось одно поле — одна пара"
    assert has_no_ascii_key(settings_row[7] + settings_row[8], ("password_min_length", "idle_timeout_minutes"))
    assert "{" not in settings_row[7] + settings_row[8]

    failed = by_code["login.failed"]
    assert failed[3] == audit_search.ACTION_TITLES["login.failed"] and failed[5] == "сотрудник" and failed[6] == "9"
    assert failed[8] == "итог: неверный пароль" and failed[7] == ""

    role = by_code["role.created"]
    assert role[5] == "роль" and role[6] == "7"
    assert role[8] == f"название: Проверяющий; права: {perm_title}", role[8]
    assert has_no_ascii_key(role[8], ("name", "permissions", "audit.view"))
