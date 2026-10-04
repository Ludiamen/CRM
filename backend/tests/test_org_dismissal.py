"""T-2105: увольнение и возврат на работу (FR-123…129, FR-150). Сценарии 7 и 8 спеки SPEC-002.

Имена кода среза 002 (`apps.org…`, `accounts.dismiss`, `accounts.rehire`, …) импортируются внутри
тестов: сбор проходит до появления кода. Правила — tests/CONTRACT-002.md (§ 3, 4.3, 6, 8.3, 9.3, 9.8).
"""
import re
from datetime import timedelta
from html.parser import HTMLParser

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from tests import factories, support, support_mail, support_org
from tests.support import HX, model

pytestmark = pytest.mark.django_db


# --- разбор разметки без внешних пакетов ---------------------------------------------------------

_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


class _Node:
    def __init__(self, tag, attrs, parent):
        self.tag, self.attrs, self.parent, self.children = tag, attrs, parent, []

    @property
    def text(self) -> str:
        parts = [c if isinstance(c, str) else c.text for c in self.children]
        return " ".join(" ".join(parts).split())

    def walk(self):
        for child in self.children:
            if not isinstance(child, str):
                yield child
                yield from child.walk()


class _Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {}, None)
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur)
        self.cur.children.append(node)
        if tag not in _VOID:
            self.cur = node

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(_Node(tag, {k: (v if v is not None else "") for k, v in attrs}, self.cur))

    def handle_endtag(self, tag):
        node = self.cur
        while node is not None and node.tag != tag:
            node = node.parent
        if node is not None and node.parent is not None:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def page(response) -> str:
    return response.content.decode()


def select(html: str, attrs: dict, tag: str | None = None) -> list:
    """Элементы разметки по атрибутам: значение `True` — достаточно, чтобы атрибут был."""
    tree = _Tree()
    tree.feed(html)
    found = []
    for node in tree.root.walk():
        if tag and node.tag != tag:
            continue
        if all(key in node.attrs and (want is True or node.attrs[key] == str(want)) for key, want in attrs.items()):
            found.append(node)
    return found


def alert_text(response) -> str:
    nodes = select(page(response), {"role": "alert"})
    assert nodes, "в ответе нет [role=alert]"
    return " ".join(n.text for n in nodes).lower()


def row_ids(html: str) -> set[int]:
    return {int(n.attrs["data-user-id"]) for n in select(html, {"data-user-id": True}, tag="tr")}


# --- помощники файла -------------------------------------------------------------------------------

def org_manager(*extra):
    """Сотрудник с правами `org.manage`, `staff.view` (и `extra`); права среза 002 заводит миграция T-2200: пока их нет, роль выходит пустой, и тест падает на отказе доступа."""
    codes = ("org.manage", "staff.view", *extra)
    return support.make_with_permissions(*codes)


def client_of(user, n: int = 40):
    return support.logged_in(user, ip=f"198.51.100.{n}")


def audit_of(user, *actions):
    qs = model("core.AuditEvent").objects.filter(object_id=str(user.pk)).order_by("id")
    return list(qs.filter(action__in=actions) if actions else qs)


def staff_role():
    return support.role_by_name(support.STAFF_ROLE)


def dismiss_url(user) -> str:
    return f"/structure/people/{getattr(user, 'pk', user)}/dismiss/"


def rehire_url(user) -> str:
    return f"/structure/people/{getattr(user, 'pk', user)}/rehire/"


def core_dismiss(user, actor):
    from apps.core.services import accounts

    accounts.dismiss(user, actor=actor)
    user.refresh_from_db()
    return user


def org_dismiss(user, actor, callbacks):
    from apps.org.services import people

    with callbacks(execute=True):
        people.dismiss(user, actor=actor)
    user.refresh_from_db()
    return user


def worker_with_units(*, head_in_first: bool = True, **extra):
    """Сотрудник — участник двух отделов («Сеть» и «Поддержка»), руководитель первого; личная роль у него есть."""
    role = factories.make_role(permissions=("staff.view",))
    user = support.make_employee(roles=[role], **extra)
    net, desk = support_org.make_unit("Сеть"), support_org.make_unit("Поддержка")
    support_org.make_member(user, net, mark="head" if head_in_first else "")
    support_org.make_member(user, desk)
    return user, net, desk, role


# --- FR-124: «уволен» — отдельное состояние -----------------------------------------------------------

def test_dismissed_state_separate_from_blocked():
    """FR-124: «уволен» — четвёртое состояние, не блокировка: `is_active` ложно у обоих, но блокировка
    чистится и не возвращается, `unblock` над уволенным ничего не делает, дата и автор сохранены."""
    from apps.core.models import UserState
    from apps.core.services import accounts

    User = model("core.User")
    assert UserState.DISMISSED == "dismissed"
    assert {value for value, _ in User._meta.get_field("state").choices} == {"invited", "active", "blocked", "dismissed"}
    manager = org_manager()
    active, invited = support.make_employee(), support.make_employee(state="invited", totp=False)
    blocked = support.make_employee(state="blocked", blocked_from="active", blocked_reason="проверка")
    assert active.is_active and invited.is_active and not blocked.is_active
    started = timezone.now()
    accounts.dismiss(blocked, actor=manager)
    blocked.refresh_from_db()
    assert blocked.state == "dismissed" and blocked.state != "blocked"
    assert not blocked.is_active
    assert (blocked.blocked_from, blocked.blocked_reason) == ("", "")
    assert blocked.dismissed_by == manager and abs(blocked.dismissed_at - started) < timedelta(minutes=5)
    assert list(manager.dismissed_users.all()) == [blocked]
    accounts.unblock(blocked, actor=manager)
    blocked.refresh_from_db()
    assert blocked.state == "dismissed", "разблокировка не возвращает уволенного"
    assert not User.objects.filter(state="blocked", pk=blocked.pk).exists()
    assert User.objects.get(pk=active.pk).dismissed_at is None


def test_block_keeps_memberships_marks_and_unit_roles():
    """FR-124 (сценарий 7, п. 12): блокировка структуру не меняет — членства, отметка руководителя и роли узла
    остаются; заблокированный руководитель виден в узле и в `heads_of` коллег."""
    from apps.org.services import structure

    Membership, UnitRole = support.model("org.Membership"), support.model("org.UnitRole")
    head = support.make_employee(full_name="Руководитель Блокируемый")
    colleague = support.make_employee(full_name="Коллега Рядовой")
    unit = support_org.make_unit("Сеть")
    support_org.make_member(head, unit, mark="head")
    support_org.make_member(colleague, unit)
    support_org.make_unit_role(unit, factories.make_role(permissions=("staff.view",)))
    admin = client_of(support.make_admin())
    done = admin.post(f"/staff/{head.pk}/block/", {"reason": "проверка"})
    assert done.status_code == 302
    head.refresh_from_db()
    assert head.state == "blocked"
    assert Membership.objects.get(user=head, unit=unit).mark == "head"
    assert Membership.objects.filter(unit=unit).count() == 2 and UnitRole.objects.filter(unit=unit).count() == 1
    assert [u.id for u in structure.units_of(head)] == [unit.pk]
    assert head.pk in [p.id for entry in structure.heads_of(colleague) for p in entry.heads]
    viewer = client_of(org_manager(), 41)
    rows = select(page(viewer.get(f"/structure/{unit.pk}/")), {"data-member": True, "data-user-id": head.pk})
    assert len(rows) == 1 and rows[0].attrs.get("data-mark") == "head"


# --- FR-125: последствия увольнения -----------------------------------------------------------------

def test_dismiss_closes_all_sessions_next_request_of_each_kind_refused():
    """FR-125 (сценарий 7, п. 1): обе сессии (два устройства) закрыты сразу; следующий запрос из каждой отклонён."""
    UserSession = model("core.UserSession")
    manager = org_manager()
    user = support.make_employee(roles=[staff_role()])
    first = support.logged_in(user, ip="198.51.100.31")
    second = support.logged_in(user, ip="198.51.100.32", ua=support.CHROME_UA)
    assert UserSession.objects.filter(user=user).count() == 2
    assert first.get("/me/").status_code == 200 and second.get("/me/").status_code == 200
    core_dismiss(user, manager)
    assert not UserSession.objects.filter(user=user).exists()
    for client in (first, second):
        for refused in (client.get("/me/"), client.get("/me/", **HX), client.get("/staff/"),
                        client.post("/me/", {"phone": "", "contacts": ""})):
            assert refused.status_code == 302 and "/login/" in refused["Location"]


def test_dismiss_revokes_activation_and_reset_links():
    """FR-125 (сценарий 7, п. 1): ссылки активации и восстановления погашены и не меняются на сессию; у живых то же работает."""
    Link = model("core.OneTimeLink")
    manager = org_manager()
    invited = support.make_employee(state="invited", totp=False)
    active = support.make_employee()
    live_invited, live_active = support.make_employee(state="invited", totp=False), support.make_employee()
    _, activation = factories.make_link(invited, "activation", created_by=manager)
    _, reset = factories.make_link(active, "reset")
    _, control_activation = factories.make_link(live_invited, "activation")
    _, control_reset = factories.make_link(live_active, "reset")
    assert support.make_client(ip="198.51.100.51").post("/activate/exchange/", {"code": control_activation}).status_code == 302
    assert support.make_client(ip="198.51.100.52").post("/password/reset/exchange/", {"code": control_reset}).status_code == 302
    core_dismiss(invited, manager)
    core_dismiss(active, manager)
    for user, purpose in ((invited, "activation"), (active, "reset")):
        link = Link.objects.get(user=user, purpose=purpose)
        assert link.revoked_at is not None and not link.code_encrypted
    unknown = support.make_client(ip="198.51.100.53").post("/activate/exchange/", {"code": factories.new_password()})
    late_activation = support.make_client(ip="198.51.100.54").post("/activate/exchange/", {"code": activation})
    late_reset = support.make_client(ip="198.51.100.55").post("/password/reset/exchange/", {"code": reset})
    assert late_activation.status_code != 302 and late_reset.status_code != 302
    assert support.same_failure(late_activation, unknown)


def test_dismissed_login_refused_at_password_and_code_with_common_message():
    """FR-125 (сценарий 7, п. 1): уволенный не входит ни на шаге пароля, ни на шаге кода; отказ тот же общий (FR-034),
    что у неизвестной почты и заблокированной записи."""
    Attempt, Session = model("core.LoginAttempt"), model("core.UserSession")
    manager = org_manager()
    dismissed, blocked = support.make_employee(), support.make_employee(state="blocked")
    core_dismiss(dismissed, manager)
    ghost = support.make_client(ip="198.51.100.61").post(
        "/login/", {"email": factories.new_email("ghost"), "password": factories.new_password()})
    by_blocked = support.make_client(ip="198.51.100.62").post(
        "/login/", {"email": blocked.email, "password": blocked.test_password})
    by_dismissed = support.make_client(ip="198.51.100.63").post(
        "/login/", {"email": dismissed.email, "password": dismissed.test_password})
    assert by_dismissed.status_code == 200 and support.same_failure(ghost, by_blocked, by_dismissed)
    assert not Attempt.objects.filter(user=dismissed, result="success").exists()
    # шаг кода: пароль принят, пока запись жива; затем запись блокируют или увольняют
    pending_block, pending_dismiss = support.make_employee(), support.make_employee()
    c_block = support.make_client(ip="198.51.100.64")
    c_dismiss = support.make_client(ip="198.51.100.65")
    for client, user in ((c_block, pending_block), (c_dismiss, pending_dismiss)):
        first = support.post_password(client, user)
        assert first.status_code == 302 and first["Location"].endswith("/login/code/")
    from apps.core.services import accounts

    accounts.block(pending_block, "проверка", actor=manager)
    accounts.dismiss(pending_dismiss, actor=manager)
    refused_block = c_block.post("/login/code/", {"code": support.current_code(pending_block)})
    refused_dismiss = c_dismiss.post("/login/code/", {"code": support.current_code(pending_dismiss)})
    assert refused_dismiss.status_code != 302 or "/login/" in refused_dismiss["Location"]
    assert support.same_failure(refused_block, refused_dismiss)
    assert not Attempt.objects.filter(user=pending_dismiss, result="success").exists()
    assert not Session.objects.filter(user=pending_dismiss).exists()
    after = c_dismiss.get("/me/")
    assert after.status_code == 302 and "/login/" in after["Location"]


def test_dismissed_forgot_password_sends_no_mail(django_capture_on_commit_callbacks):
    """FR-125: запрос восстановления для уволенного отвечает как для чужого адреса; письма и ссылки нет."""
    Link = model("core.OneTimeLink")
    manager = org_manager()
    dismissed, active = support.make_employee(), support.make_employee()
    core_dismiss(dismissed, manager)
    with django_capture_on_commit_callbacks(execute=True):
        stranger = support.make_client(ip="198.51.100.71").post("/password/forgot/", {"email": factories.new_email("nobody")})
        answer = support.make_client(ip="198.51.100.72").post("/password/forgot/", {"email": dismissed.email})
        control = support.make_client(ip="198.51.100.73").post("/password/forgot/", {"email": active.email})
    assert answer.status_code in (200, 302) and support.same_failure(stranger, answer, control)
    assert not support.mails(to=dismissed.email).exists() and not support.mails(related_user=dismissed).exists()
    assert not Link.objects.filter(user=dismissed, purpose="reset").exists()
    assert [m.to for m in support.mails(template="password_reset")] == [active.email], "у активной записи письмо уходит"


def test_dismiss_removes_memberships_marks_personal_roles_keeps_date_and_actor(django_capture_on_commit_callbacks):
    """FR-125 (сценарий 7, п. 2): человек ушёл из всех узлов вместе с отметками, узел остался без руководителя, личные
    роли сняты, дата и имя уволившего сохранены, ключ прав сброшен; чужие членства целы."""
    from apps.core.services import permissions

    Membership = support.model("org.Membership")
    manager = org_manager()
    user, net, desk, role = worker_with_units()
    other = support.make_employee()
    support_org.make_member(other, net)
    permissions.permissions_of(user)
    assert support.valkey_keys(f"perms:{user.pk}"), "до увольнения права записаны в кэш"
    started = timezone.now()
    org_dismiss(user, manager, django_capture_on_commit_callbacks)
    assert user.state == "dismissed"
    assert not Membership.objects.filter(user=user).exists()
    assert not Membership.objects.filter(unit=net, mark="head").exists(), "узел остался без руководителя"
    assert list(Membership.objects.filter(unit=net).values_list("user_id", flat=True)) == [other.pk]
    assert Membership.objects.filter(unit__in=(net, desk)).count() == 1
    assert user.roles.count() == 0 and role.pk is not None
    assert user.dismissed_by == manager and abs(user.dismissed_at - started) < timedelta(minutes=5)
    assert support.valkey_keys(f"perms:{user.pk}") == [], "ключ прав уволенного сброшен на фиксации"


def test_dismiss_sends_no_mail_and_clears_block_fields(django_capture_on_commit_callbacks):
    """FR-125 (сценарий 7, п. 9, 11): письма уволенному нет ни в базе, ни в очереди; поля блокировки очищены."""
    manager = org_manager()
    blocked = support.make_employee(state="blocked", blocked_from="active", blocked_reason="причина блокировки")
    mails_before, jobs_before = support.mails().count(), len(support_mail.mail_jobs())
    with django_capture_on_commit_callbacks(execute=True):
        core_dismiss(blocked, manager)
    assert blocked.state == "dismissed" and (blocked.blocked_from, blocked.blocked_reason) == ("", "")
    assert support.mails().count() == mails_before and len(support_mail.mail_jobs()) == jobs_before
    assert not support.mails(to=blocked.email).exists() and not support.mails(related_user=blocked).exists()


def test_dismiss_dialog_get_shows_consequences_and_changes_nothing():
    """FR-125 (сценарий 7, п. 10): GET диалога — фрагмент с последствиями, формой и «Отменой»; запись, членства и журнал не меняются."""
    Audit = model("core.AuditEvent")
    manager = org_manager()
    user, net, desk, role = worker_with_units()
    client = client_of(manager)
    events_before = Audit.objects.count()
    response = client.get(dismiss_url(user), **HX)
    assert response.status_code == 200
    html = page(response)
    assert "<html" not in html
    dialogs = select(html, {"data-dialog": "dismiss", "role": "dialog", "aria-modal": "true"})
    assert len(dialogs) == 1
    consequences = select(html, {"data-consequence": True})
    assert len(consequences) >= 3
    text = " ".join(n.text for n in consequences).lower()
    for phrase in ("вход закрыт", "уйдёт из всех подразделений", "личные роли будут сняты"):
        assert phrase in text, phrase
    forms = [f for f in select(html, {"data-form": "dismiss"}, tag="form")]
    assert forms and select(html, {"type": "submit"}, tag="button")
    cancel = select(html, {"data-dialog-cancel": True}, tag="button")
    assert len(cancel) == 1 and "отмена" in cancel[0].text.lower()
    user.refresh_from_db()
    assert user.state == "active" and user.roles.count() == 1
    assert support.model("org.Membership").objects.filter(user=user).count() == 2
    assert Audit.objects.count() == events_before, "диалог — не действие: журнал не пополняется"


# --- FR-126: кого можно уволить ----------------------------------------------------------------------

def test_cannot_dismiss_self_or_last_admin():
    """FR-126 (сценарий 7, п. 6, 7): себя и последнего администратора уволить нельзя (отказ службы и 200 с [role=alert]);
    порядок: себя раньше последнего администратора; при двух администраторах одного уволить можно."""
    from apps.core.services import accounts, roles

    Audit = model("core.AuditEvent")
    manager = org_manager()
    sole = support.make_admin()
    # служба: себя
    with pytest.raises(accounts.AccountError):
        accounts.dismiss(manager, actor=manager)
    # служба: последний администратор — своим отказом ролей, а если он же actor, раньше срабатывает «себя»
    with pytest.raises(roles.RoleError):
        accounts.dismiss(sole, actor=manager)
    with pytest.raises(accounts.AccountError):
        accounts.dismiss(sole, actor=sole)
    already = core_dismiss(support.make_employee(), manager)
    stamp = already.dismissed_at
    with pytest.raises(accounts.AccountError):
        accounts.dismiss(already, actor=manager)
    already.refresh_from_db()
    assert already.dismissed_at == stamp and already.state == "dismissed"
    client = client_of(manager)
    events_before = Audit.objects.count()
    own = client.post(dismiss_url(manager))
    assert own.status_code == 200 and alert_text(own)
    last = client.post(dismiss_url(sole))
    assert last.status_code == 200 and "последн" in alert_text(last)
    for user in (manager, sole):
        user.refresh_from_db()
        assert user.state == "active" and user.dismissed_at is None and user.dismissed_by is None
    assert not Audit.objects.filter(action="user.dismissed", object_id__in=(manager.pk, sole.pk)).exists()
    assert Audit.objects.count() == events_before, "отказ не пишет ни user.dismissed, ни membership.removed"
    second_admin = support.make_admin()
    done = client.post(dismiss_url(sole))
    assert done.status_code == 302
    sole.refresh_from_db()
    assert sole.state == "dismissed" and second_admin.state == "active"


def test_guard_last_admin_locks_active_admin_rows():
    """FR-126: `guard_last_admin` берёт `select_for_update` строк действующих администраторов (в запросе есть FOR UPDATE)."""
    from apps.core.services import roles

    one, two = support.make_admin(), support.make_admin()
    with CaptureQueriesContext(connection) as captured:
        roles.guard_last_admin(one, action="уволить его")
    # Условие роли может идти через таблицу связи `core_user_roles` без `core_role`: требовать её в SQL нельзя.
    locking = [q["sql"] for q in captured if "FOR UPDATE" in q["sql"].upper() and '"core_user"' in q["sql"]]
    assert locking, "блокирующего запроса по строкам записей (core_user, FOR UPDATE) нет"
    roles.guard_last_admin(one, action="уволить его")  # второй администратор есть — отказа нет
    two.state = "dismissed"
    two.save(update_fields=["state"])
    with pytest.raises(roles.RoleError):
        roles.guard_last_admin(one, action="уволить его")


def test_dismiss_allowed_from_invited_active_and_blocked():
    """FR-126 (сценарий 7, п. 11): уволить можно приглашённую, активную и заблокированную запись; безопасный `next` учитывается,
    чужой хост — нет."""
    manager = org_manager()
    invited = support.make_employee(state="invited", totp=False)
    active = support.make_employee()
    blocked = support.make_employee(state="blocked", blocked_from="active", blocked_reason="причина")
    client = client_of(manager)
    assert client.post(dismiss_url(invited)).status_code == 302
    done = client.post(dismiss_url(active), {"next": "/structure/"})
    assert done.status_code == 302 and done["Location"] == "/structure/"
    done = client.post(dismiss_url(blocked), {"next": "https://evil.example/"})
    assert done.status_code == 302 and "evil.example" not in done["Location"]
    assert done["Location"].endswith(f"/staff/{blocked.pk}/")
    for user in (invited, active, blocked):
        user.refresh_from_db()
        assert user.state == "dismissed" and user.dismissed_by == manager and user.dismissed_at is not None
    again = client.post(dismiss_url(active))
    assert again.status_code == 200 and alert_text(again), "уже уволенного уволить нельзя"


# --- FR-127: уволенный в интерфейсе --------------------------------------------------------------------

def test_dismissed_card_read_only_except_rehire_and_photo_delete(django_capture_on_commit_callbacks, protected_root):
    """FR-127 (сценарий 7, п. 3): карточка уволенного только для чтения — правка профиля, блокировка, роли, сброс второго
    фактора, членства и отметки отказывают и ничего не меняют; остаются «Вернуть на работу» и удаление фото; поля на месте."""
    from apps.core.services import accounts, files, roles
    from apps.org.services import OrgError, membership, structure

    Membership, Audit = support.model("org.Membership"), model("core.AuditEvent")
    manager = org_manager("accounts.manage", "accounts.reset_2fa", "roles.manage")
    user, net, desk, role = worker_with_units(position="Сетевой инженер")
    upload = SimpleUploadedFile("p.jpg", support_org.jpeg_bytes(), content_type="image/jpeg")
    files.upload_photo(user, upload, actor=user)
    user.refresh_from_db()
    assert user.photo_pending is not None
    org_dismiss(user, manager, django_capture_on_commit_callbacks)
    snapshot = (user.full_name, user.position, user.email, user.phone, user.state)
    events_before = Audit.objects.count()
    for call, error in (
        (lambda: accounts.update_profile(user, actor=manager, position="Другая должность"), accounts.AccountError),
        (lambda: accounts.block(user, "причина", actor=manager), accounts.AccountError),
        (lambda: accounts.reset_second_factor(user, actor=manager), accounts.AccountError),
        (lambda: roles.set_user_roles(user, [role.pk], actor=manager), roles.RoleError),
    ):
        with pytest.raises(error):
            call()
    assert structure.units_of(user) == []
    with pytest.raises(OrgError) as refused:
        membership.add_members(net, [user], mode=membership.CONCURRENT, actor=manager)
    assert refused.value.code == "dismissed_user"
    with pytest.raises(OrgError) as refused:
        membership.set_marks(net, heads=[user], actor=manager)
    assert refused.value.code == "dismissed_user"
    user.refresh_from_db()
    assert (user.full_name, user.position, user.email, user.phone, user.state) == snapshot
    assert user.roles.count() == 0 and not Membership.objects.filter(user=user).exists()
    assert Audit.objects.count() == events_before, "отказы ничего не пишут в журнал"
    # через страницы
    client = client_of(manager)
    edit = client.post(f"/staff/{user.pk}/edit/", {
        "full_name": user.full_name, "position": "Новая должность", "phone": "", "email": user.email, "contacts": ""})
    assert edit.status_code == 200 and alert_text(edit)
    for url, data in (
        (f"/staff/{user.pk}/block/", {"reason": "причина"}),
        (f"/staff/{user.pk}/roles/", {"roles": [role.pk]}),
        (f"/staff/{user.pk}/reset-2fa/", {}),
        (f"/staff/{user.pk}/invite/", {}),
        (f"/structure/{net.pk}/marks/", {"part": "heads", "users": [user.pk]}),
        (f"/structure/{net.pk}/members/", {"users": [user.pk], "mode": "concurrent"}),
    ):
        refused_page = client.post(url, data)
        assert refused_page.status_code == 200 and alert_text(refused_page), f"{url}: отказ — 200 с [role=alert]"
    unblocked = client.post(f"/staff/{user.pk}/unblock/")
    assert unblocked.status_code == 200, "unblock над уволенным — 200 без изменений"
    user.refresh_from_db()
    assert user.position == "Сетевой инженер" and user.state == "dismissed"
    assert user.roles.count() == 0 and not Membership.objects.filter(user=user).exists()
    assert (user.full_name, user.position, user.email, user.phone) == snapshot[:4]
    assert Audit.objects.count() == events_before, "отказы страниц ничего не пишут в журнал"
    # карточка: все прежние поля, отметка «уволен», вернуть можно, уволить нельзя
    card = page(client.get(f"/staff/{user.pk}/"))
    assert user.email in card and "Сетевой инженер" in card
    badges = select(card, {"data-dismissed-badge": True})
    assert badges and "уволен" in badges[0].text.lower()
    assert select(card, {"data-action": "rehire"}) and not select(card, {"data-action": "dismiss"})
    units = select(card, {"data-field": "units"})
    assert len(units) == 1 and units[0].attrs["data-empty"] == "true" and "не заполнено" in units[0].text.lower()
    assert not select(card, {"data-role-name": True}), "у уволенного ролей на карточке нет"
    # удаление фото остаётся (ПДн)
    stored = user.photo_pending
    gone = client.post(f"/staff/{user.pk}/photo/delete/")
    assert gone.status_code == 302 and gone["Location"].endswith(f"/staff/{user.pk}/")
    user.refresh_from_db()
    assert user.photo_pending is None and user.photo is None
    assert not support.model("core.StoredFile").objects.filter(pk=stored.pk).exists()


def test_dismissed_in_dismissed_and_all_presets_not_in_company():
    """FR-127 (сценарий 7, п. 3): уволенный есть в «Уволены» и «Все», его нет в «В компании» (по умолчанию) и «Без подразделения»;
    у строки `data-state="dismissed"`; коллега видит пресет «Уволены»."""
    manager = org_manager()
    dismissed = support.make_employee(full_name="Уволенный Список")
    plain = support.make_employee(full_name="Свободный Список")
    member = support.make_employee(full_name="Участник Список")
    support_org.make_member(member, support_org.make_unit("Сеть"))
    core_dismiss(dismissed, manager)
    admin = client_of(support.make_admin(), 42)

    def ids(query):
        return row_ids(page(admin.get("/staff/" + query)))

    assert dismissed.pk not in ids("") and {plain.pk, member.pk} <= ids("")
    assert dismissed.pk in ids("?state=dismissed") and plain.pk not in ids("?state=dismissed")
    assert dismissed.pk in ids("?state=all") and {plain.pk, member.pk} <= ids("?state=all")
    assert plain.pk in ids("?state=no_unit") and member.pk not in ids("?state=no_unit")
    assert dismissed.pk not in ids("?state=no_unit")
    rows = select(page(admin.get("/staff/?state=dismissed")), {"data-user-id": dismissed.pk}, tag="tr")
    assert len(rows) == 1 and rows[0].attrs.get("data-state") == "dismissed"
    colleague = client_of(support.make_with_permissions("staff.view"), 43)
    listing = page(colleague.get("/staff/?state=dismissed"))
    assert dismissed.pk in row_ids(listing) and select(listing, {"data-preset": "dismissed"}, tag="a")
    colleague_rows = select(listing, {"data-user-id": dismissed.pk}, tag="tr")
    assert len(colleague_rows) == 1 and "data-state" not in colleague_rows[0].attrs
    assert colleague_rows[0].attrs.get("data-dismissed") == "true"
    plain_rows = select(page(colleague.get("/staff/")), {"data-user-id": plain.pk}, tag="tr")
    assert len(plain_rows) == 1 and "data-state" not in plain_rows[0].attrs
    assert "data-dismissed" not in plain_rows[0].attrs
    assert dismissed.pk not in row_ids(page(colleague.get("/staff/")))


def test_dismissed_marked_in_audit_and_login_history():
    """FR-127 (сценарий 7, п. 5): действия уволенного в журнале и в истории входов подписаны его именем с пометкой «(уволен)»;
    у действующего пометки нет; прежние события на месте."""
    from apps.core.services import audit_search

    Audit = model("core.AuditEvent")
    manager = org_manager()
    gone = support.make_employee(full_name="Прежний Работник")
    stays = support.make_employee(full_name="Действующий Работник")
    support.logged_in(gone, ip="198.51.100.81")
    support.logged_in(stays, ip="198.51.100.82")
    login_event = Audit.objects.filter(action="login.success", actor=gone).get()
    core_dismiss(gone, manager)
    assert audit_search.actor_text(Audit.objects.get(pk=login_event.pk)) == f"{gone.full_name} (уволен) <{gone.email}>"
    stays_event = Audit.objects.filter(action="login.success", actor=stays).get()
    assert "(уволен)" not in audit_search.actor_text(stays_event)
    admin = client_of(support.make_admin(), 83)
    text = " ".join(re.sub(r"<[^>]+>", " ", page(admin.get("/audit/"))).split())
    assert f"{gone.full_name} (уволен)" in text and f"{stays.full_name} (уволен)" not in text
    export = page(admin.get("/audit/export.csv"))
    assert f"{gone.full_name} (уволен)" in export and f"{stays.full_name} (уволен)" not in export
    history = admin.get(f"/staff/{gone.pk}/logins/")
    assert history.status_code == 200 and "198.51.100.81" in page(history), "прежние входы видны"
    names = select(page(history), {"data-person-name": True})
    assert len(names) == 1 and names[0].text == f"{gone.full_name} (уволен)"
    kept = admin.get(f"/staff/{stays.pk}/logins/")
    kept_names = select(page(kept), {"data-person-name": True})
    assert kept.status_code == 200 and len(kept_names) == 1 and kept_names[0].text == stays.full_name


def test_dismissed_not_offered_in_any_person_picker():
    """FR-127 (сценарий 7, п. 4): `accounts.pickable` и подсказки кандидатов узла не предлагают уволенного (заблокированных и
    приглашённых — предлагают); добавление уволенного в узел отказано целиком."""
    from apps.core.services import accounts

    manager = org_manager()
    gone = support.make_employee(full_name="Тёмный Уволенный")
    active = support.make_employee(full_name="Тёмный Активный")
    blocked = support.make_employee(full_name="Тёмный Заблокированный", state="blocked")
    invited = support.make_employee(full_name="Тёмный Приглашённый", state="invited", totp=False)
    core_dismiss(gone, manager)
    offered = list(accounts.pickable(""))
    assert gone not in offered and {active, blocked, invited} <= set(offered)
    found = list(accounts.pickable("темный"))
    assert found == sorted(found, key=lambda u: (u.full_name, u.id)) and gone not in found
    assert {active, blocked, invited} <= set(found)
    unit = support_org.make_unit("Сеть")
    client = client_of(manager)
    candidates = client.get(f"/structure/{unit.pk}/candidates/?q=Тёмный", **HX)
    assert candidates.status_code == 200
    ids = {int(n.attrs["data-user-id"]) for n in select(page(candidates), {"data-candidate": True, "data-user-id": True})}
    assert active.pk in ids and gone.pk not in ids
    refused = client.post(f"/structure/{unit.pk}/members/", {"users": [active.pk, gone.pk], "mode": "concurrent"})
    assert refused.status_code == 200 and alert_text(refused)
    assert not support.model("org.Membership").objects.filter(unit=unit).exists(), "пачка отклонена целиком"


# --- FR-128: возврат -------------------------------------------------------------------------------------

def test_rehire_makes_invited_sends_72h_invitation_staff_role_no_units(django_capture_on_commit_callbacks):
    """FR-128 (сценарий 8, п. 1): «Вернуть на работу» — запись «приглашён», приглашение на 72 часа, роль только «Сотрудник ИТ»,
    подразделений нет, дата и автор увольнения очищены."""
    from apps.core.services import roles

    Link, Membership = model("core.OneTimeLink"), support.model("org.Membership")
    manager = org_manager()
    user, net, desk, role = worker_with_units()
    org_dismiss(user, manager, django_capture_on_commit_callbacks)
    assert roles.STAFF_ROLE_NAME == "Сотрудник ИТ" and roles.staff_role().name == "Сотрудник ИТ"
    client = client_of(manager)
    started = timezone.now()
    with django_capture_on_commit_callbacks(execute=True):
        done = client.post(rehire_url(user))
    assert done.status_code == 302 and done["Location"].endswith(f"/staff/{user.pk}/")
    user.refresh_from_db()
    assert user.state == "invited" and user.is_active
    assert (user.dismissed_at, user.dismissed_by) == (None, None)
    assert list(user.roles.all()) == [roles.staff_role()]
    assert not Membership.objects.filter(user=user).exists()
    link = Link.objects.get(user=user, purpose="activation", revoked_at=None, used_at=None)
    assert abs((link.expires_at - started) - timedelta(hours=72)) < timedelta(minutes=5)
    sent = support.mails(to=user.email, template="invitation")
    assert sent.count() == 1 and sent.get().related_user_id == user.pk
    assert [j for j in support_mail.mail_jobs()], "письмо приглашения поставлено в очередь после фиксации"


def test_rehire_drops_password_totp_backup_codes_devices_keeps_password_history():
    """FR-128 (сценарий 8, п. 2): пароль непригоден, ключ TOTP, резервные коды и запомненные устройства удалены, история паролей
    остаётся и не даёт повторить старый пароль при новой активации."""
    from apps.core.services import accounts, links, second_factor

    Totp, BackupDevice, BackupCode = model("core.EncryptedTOTPDevice"), model("core.BackupCodeDevice"), model("core.BackupCode")
    Known, History = model("core.KnownDevice"), model("core.PasswordHistory")
    manager = org_manager()
    user = support.make_employee(roles=[staff_role()])
    first, second = factories.new_password(), factories.new_password()
    support.set_password_history(user, [first, second])
    support.logged_in(user, ip="198.51.100.91")
    second_factor.issue_backup_codes(user)
    history_before = History.objects.filter(user=user).count()
    assert Totp.objects.filter(user=user).exists() and BackupDevice.objects.filter(user=user).exists()
    assert BackupCode.objects.filter(device__user=user).exists() and Known.objects.filter(user=user).exists()
    assert history_before >= 2
    accounts.dismiss(user, actor=manager)
    user.refresh_from_db()
    accounts.rehire(user, actor=manager)
    user.refresh_from_db()
    assert user.state == "invited" and not user.has_usable_password()
    assert not user.check_password(second) and not user.check_password(first)
    assert not Totp.objects.filter(user=user).exists() and not BackupDevice.objects.filter(user=user).exists()
    assert not BackupCode.objects.filter(device__user=user).exists() and not Known.objects.filter(user=user).exists()
    assert History.objects.filter(user=user).count() == history_before
    # новая активация: старый пароль повторить нельзя
    code = support.link_code(links.current_activation_link(user))
    client = support.make_client(ip="198.51.100.92")
    assert client.post("/activate/exchange/", {"code": code}).status_code == 302
    assert client.post("/activate/profile/", {"phone": "", "contacts": ""}).status_code == 302
    for old in (second, first):
        refused = client.post("/activate/password/", {"password1": old, "password2": old})
        assert refused.status_code == 200 and "последн" in page(refused).lower()


def test_rehire_only_for_dismissed_and_needs_org_manage():
    """FR-128 (сценарий 8, п. 4, 5): вернуть можно только уволенного (иначе отказ службы и 200 с [role=alert]); без `org.manage`
    диалог и действие — 403, без входа — на вход; диалог — `[data-dialog="rehire"]` и ничего не меняет."""
    from apps.core.services import accounts

    Audit = model("core.AuditEvent")
    manager = org_manager()
    active, gone = support.make_employee(), support.make_employee()
    core_dismiss(gone, manager)
    with pytest.raises(accounts.AccountError):
        accounts.rehire(active, actor=manager)
    active.refresh_from_db()
    assert active.state == "active"
    client = client_of(manager)
    refused = client.post(rehire_url(active))
    assert refused.status_code == 200 and alert_text(refused)
    events_before = Audit.objects.count()
    dialog = client.get(rehire_url(gone), **HX)
    assert dialog.status_code == 200 and "<html" not in page(dialog)
    assert select(page(dialog), {"data-dialog": "rehire", "role": "dialog"})
    cancel = select(page(dialog), {"data-dialog-cancel": True}, tag="button")
    assert cancel and "отмена" in cancel[0].text.lower() and select(page(dialog), {"type": "submit"}, tag="button")
    gone.refresh_from_db()
    assert gone.state == "dismissed" and Audit.objects.count() == events_before
    for plain in (support.make_with_permissions("accounts.manage", "staff.view"), support.make_employee()):
        other = client_of(plain, 44)
        assert other.get(rehire_url(gone), **HX).status_code == 403
        assert other.post(rehire_url(gone)).status_code == 403
        assert other.post(rehire_url(active)).status_code == 403
    anonymous = support.make_client().post(rehire_url(gone))
    assert anonymous.status_code == 302 and "/login/" in anonymous["Location"]
    gone.refresh_from_db()
    assert gone.state == "dismissed" and support.mails(to=gone.email, template="invitation").count() == 0


# --- FR-129: данные уволенного хранятся ----------------------------------------------------------------

def test_dismissed_email_stays_taken():
    """FR-129: почта уволенного остаётся занятой — ни новая запись, ни правка чужой, ни прямая вставка её не берут."""
    from django.db import IntegrityError, transaction

    from apps.core.services import accounts

    User = model("core.User")
    manager = org_manager()
    gone = support.make_employee(email="Gone.Person@Example.com")
    core_dismiss(gone, manager)
    admin = support.make_admin()
    total = User.objects.count()
    with pytest.raises(accounts.AccountError):
        accounts.create_user(email="GONE.person@example.COM", full_name="Новый", position="Инженер",
                             role_ids=[staff_role().pk], actor=admin)
    other = support.make_employee()
    with pytest.raises(accounts.AccountError):
        accounts.update_profile(other, actor=admin, email="gone.person@example.com")
    client = client_of(admin)
    done = client.post("/staff/new/", {"email": "gone.person@EXAMPLE.com", "full_name": "Пётр Новый",
                                       "position": "Инженер", "phone": "", "roles": [staff_role().pk]})
    assert done.status_code == 200 and "уже" in page(done).lower()
    with pytest.raises(IntegrityError), transaction.atomic():
        factories.make_user(email="gone.person@example.com")
    assert User.objects.count() == total + 1, "прибавилась только запись `other`"
    assert User.objects.filter(email__iexact="gone.person@example.com").count() == 1


def test_no_job_purges_dismissed_data(clock):
    """FR-129: никакое задание не стирает данные уволенного: ночные очистки через пять лет оставляют запись, поля, историю
    паролей и журнал; в `config/cron.py` нет задания, связанного с сотрудниками."""
    from apps.core.services import retention

    User, Audit, History = model("core.User"), model("core.AuditEvent"), model("core.PasswordHistory")
    manager = org_manager()
    user = support.make_employee(full_name="Давний Уволенный", position="Инженер", phone="+7 900 111-22-33")
    support.set_password_history(user, [factories.new_password(), factories.new_password()])
    core_dismiss(user, manager)
    snapshot = {f: getattr(User.objects.get(pk=user.pk), f) for f in (
        "email", "full_name", "position", "phone", "state", "dismissed_at", "dismissed_by_id")}
    history, events = History.objects.filter(user=user).count(), Audit.objects.filter(object_id=str(user.pk)).count()
    clock.advance(days=5 * 365)
    retention.purge_login_history()
    retention.purge_expired_links()
    retention.purge_expired_sessions()
    from apps.core import tasks as core_tasks
    from apps.org import tasks as org_tasks

    core_tasks.purge_quarantine()
    core_tasks.requeue_pending_scans()
    org_tasks.purge_previews()
    after = User.objects.get(pk=user.pk)
    assert {f: getattr(after, f) for f in snapshot} == snapshot
    assert History.objects.filter(user=user).count() == history
    assert Audit.objects.filter(object_id=str(user.pk)).count() == events
    cron = (support.BACKEND_DIR / "config" / "cron.py").read_text(encoding="utf-8")
    names = re.findall(r'name="([a-z_]+)"', cron)
    assert names and not [n for n in names if re.search(r"dismiss|user|staff|account|employee|personal", n)]


# --- FR-123: права на кнопки и маршруты ---------------------------------------------------------------------

def test_dismiss_and_rehire_need_org_manage_buttons_only_with_it():
    """FR-123 (сценарий 7, п. 8; сценарий 8, п. 5): «Уволить» и «Вернуть на работу» видит и выполняет только обладатель
    `org.manage`; «Уволить» видна и у себя, и у последнего администратора (отказ даёт POST); без права маршруты — 403, без входа — на вход."""
    manager = org_manager()
    sole = support.make_admin()
    target = support.make_employee()
    gone = support.make_employee()
    core_dismiss(gone, manager)
    with_right = client_of(manager)

    def action(client, user, name):
        return select(page(client.get(f"/staff/{user.pk}/")), {"data-action": name})

    links = action(with_right, target, "dismiss")
    assert len(links) == 1 and links[0].attrs.get("hx-get") == dismiss_url(target)
    assert not action(with_right, target, "rehire")
    rehire = action(with_right, gone, "rehire")
    assert len(rehire) == 1 and rehire[0].attrs.get("hx-get") == rehire_url(gone)
    assert not action(with_right, gone, "dismiss")
    assert action(with_right, manager, "dismiss") and action(with_right, sole, "dismiss")
    plain_users = (support.make_with_permissions("staff.view"), support.make_with_permissions("staff.view", "accounts.manage"))
    for n, plain in enumerate(plain_users):
        client = client_of(plain, 45 + n)
        for user in (target, gone):
            assert not action(client, user, "dismiss") and not action(client, user, "rehire")
        assert client.get(dismiss_url(target), **HX).status_code == 403
        assert client.post(dismiss_url(target)).status_code == 403
        assert client.get(rehire_url(gone), **HX).status_code == 403
        assert client.post(rehire_url(gone)).status_code == 403
        assert client.post(dismiss_url(support.make_employee().pk + 100000)).status_code == 403, "право проверяется раньше объекта"
    assert with_right.post(dismiss_url(target.pk + 100000)).status_code == 404
    anonymous = support.make_client()
    for method, url in (("get", dismiss_url(target)), ("post", dismiss_url(target)), ("post", rehire_url(gone))):
        answer = getattr(anonymous, method)(url)
        assert answer.status_code == 302 and "/login/" in answer["Location"]
    target.refresh_from_db()
    gone.refresh_from_db()
    assert target.state == "active" and gone.state == "dismissed"


# --- FR-150: события журнала -----------------------------------------------------------------------------------

def test_dismiss_and_rehire_events(django_capture_on_commit_callbacks):
    """FR-150: увольнение пишет `user.dismissed` (до/после состояние и личные роли) и по `membership.removed` на узел с причиной
    `dismissal` (по возрастанию пути, с отметкой); возврат — `user.rehired` и `invitation.sent`; прежние события остаются."""
    Audit = model("core.AuditEvent")
    manager = org_manager()
    user, net, desk, role = worker_with_units()
    expected_units = sorted((net, desk), key=lambda u: u.path)
    org_dismiss(user, manager, django_capture_on_commit_callbacks)
    events = audit_of(user, "user.dismissed", "membership.removed")
    assert [e.action for e in events] == ["user.dismissed", "membership.removed", "membership.removed"]
    dismissed, removed = events[0], events[1:]
    assert dismissed.actor_id == manager.pk and (dismissed.object_type, dismissed.object_id) == ("user", str(user.pk))
    assert dismissed.before["state"] == "active" and dismissed.before["roles"] == [role.name]
    assert dismissed.after["state"] == "dismissed"
    assert [e.before["unit_id"] for e in removed] == [u.pk for u in expected_units]
    for event, unit in zip(removed, expected_units):
        assert event.actor_id == manager.pk and (event.object_type, event.object_id) == ("user", str(user.pk))
        assert event.before["unit"] == unit.name and event.before["reason"] == "dismissal"
        assert event.before["mark"] == ("head" if unit == net else "")
    with django_capture_on_commit_callbacks(execute=True):
        from apps.org.services import people

        people.rehire(user, actor=manager)
    after = audit_of(user, "user.dismissed", "user.rehired", "invitation.sent")
    assert [e.action for e in after] == ["user.dismissed", "user.rehired", "invitation.sent"], "прежнее событие осталось"
    rehired = after[1]
    assert rehired.actor_id == manager.pk and (rehired.object_type, rehired.object_id) == ("user", str(user.pk))
    assert rehired.before["state"] == "dismissed"
    assert rehired.after["state"] == "invited" and rehired.after["roles"] == ["Сотрудник ИТ"]
    assert Audit.objects.filter(action="membership.removed", object_id=str(user.pk)).count() == 2
