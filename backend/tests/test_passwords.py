"""T-108: политика паролей, сессии, смена пароля (FR-026…030, NFR-005, NFR-011). Сценарии 10, 16, 17."""
from datetime import timedelta

import pytest
from django.db import connection
from django.utils import timezone

from tests import factories, support
from tests.support import model

pytestmark = pytest.mark.django_db

CHANGE = "/me/security/password/"


def change(client, current, new, new2=None):
    return client.post(CHANGE, {"current_password": current, "password1": new, "password2": new2 or new})


def test_policy_min_length_and_history_with_messages():
    """FR-026: длина и запрет повтора последних паролей; сообщение называет невыполненное требование."""
    History = model("core.PasswordHistory")
    user = support.make_employee()
    passwords = [factories.new_password() for _ in range(5)]
    support.set_password_history(user, passwords)
    client = support.logged_in(user)
    short = change(client, user.test_password, "Aa1-" + "x" * 7)
    body = short.content.decode()
    assert short.status_code == 200 and "12" in body and "символ" in body
    oldest = change(client, user.test_password, passwords[0])
    assert oldest.status_code == 200 and "последн" in oldest.content.decode() and "5" in oldest.content.decode()
    assert change(client, user.test_password, passwords[4]).status_code == 200, "текущий пароль тоже среди последних"
    user.refresh_from_db()
    assert user.check_password(passwords[4])
    sixth = factories.new_password()
    assert change(client, user.test_password, sixth).status_code == 302
    assert History.objects.filter(user=user).count() == 5, "хранятся последние password_history паролей"
    user.refresh_from_db()
    user.test_password = sixth
    assert change(client, user.test_password, passwords[0]).status_code == 302, "шестой назад уже можно"


def test_policy_defaults_12_chars_history_5_no_expiry_60_min():
    """NFR-005 (сценарий 17.1): значения по умолчанию — длина 12, 5 паролей, срока нет, выход через 60 минут."""
    row = model("core.SecuritySettings").objects.get()
    assert (row.password_min_length, row.password_history, row.password_max_age_days, row.idle_timeout_minutes) == (12, 5, None, 60)
    assert (row.account_lock_limit, row.account_lock_minutes, row.ip_lock_limit, row.ip_lock_min_accounts) == (5, 15, 20, 3)
    assert (row.ip_lock_window_minutes, row.ip_lock_minutes, row.login_history_days) == (15, 15, 365)
    page = support.logged_in(support.make_admin()).get("/settings/security/").content.decode()
    for name, value in (("password_min_length", "12"), ("password_history", "5"), ("idle_timeout_minutes", "60")):
        assert f'name="{name}"' in page and f'value="{value}"' in page


def test_policy_change_not_retroactive():
    """FR-027 (сценарий 17.3, 17.4): новая политика действует на новые пароли; прежние не сбрасываются; изменение — в журнале."""
    user = support.make_employee()
    old_hash = user.password
    admin = support.logged_in(support.make_admin())
    done = support.post_security_settings(admin, password_min_length=20)
    assert done.status_code == 302
    event = model("core.AuditEvent").objects.get(action="security_settings.updated")
    assert event.before["password_min_length"] == 12 and event.after["password_min_length"] == 20
    client = support.logged_in(user, ip="198.51.100.200")
    user.refresh_from_db()
    assert user.password == old_hash, "прежний пароль не сброшен задним числом"
    weak = "Aa1-" + "x" * 11  # 15 знаков
    rejected = change(client, user.test_password, weak)
    assert rejected.status_code == 200 and "20" in rejected.content.decode()
    strong = factories.new_password() + "-" + factories.new_password()
    assert len(strong) >= 20 and change(client, user.test_password, strong).status_code == 302


def test_password_max_age_forces_change_when_enabled():
    """FR-027 (сценарий 4.5): при включённом сроке пароль старше срока меняют до работы; по умолчанию срока нет."""
    History = model("core.PasswordHistory")
    user = support.make_employee()
    support.set_password_history(user, [user.test_password])
    History.objects.filter(user=user).update(created_at=timezone.now() - timedelta(days=400))
    assert support.logged_in(user, ip="198.51.100.201").get("/me/").status_code == 200, "срока по умолчанию нет"
    support.set_security(password_max_age_days=30)
    client = support.make_client(ip="198.51.100.202")
    done = support.login(client, user)
    assert done["Location"].endswith(CHANGE), "после входа — смена пароля"
    for path in ("/me/", "/me/security/"):
        assert client.get(path)["Location"].endswith(CHANGE)
    assert client.get(CHANGE).status_code == 200
    new = factories.new_password()
    assert change(client, user.test_password, new).status_code == 302
    assert client.get("/me/").status_code == 200
    support.set_security(password_max_age_days=None)


def test_idle_timeout_ends_session_and_offers_login(clock):
    """FR-028 (сценарий 10.1): каждый запрос продлевает сессию; после периода бездействия — страница входа с пояснением."""
    user = support.make_employee()
    client = support.logged_in(user)
    clock.advance(minutes=59)
    assert client.get("/me/").status_code == 200
    clock.advance(minutes=59)
    assert client.get("/me/").status_code == 200, "активность продлевает сессию"
    clock.advance(minutes=61)
    done = client.get("/me/")
    assert done.status_code == 302 and "/login/" in done["Location"]
    page = client.get(done["Location"])
    assert "бездейств" in page.content.decode().lower()
    assert client.get("/me/").status_code == 302
    assert not model("core.UserSession").objects.filter(user=user).exists()


def test_idle_timeout_snapshot_taken_at_session_creation(clock):
    """FR-028, FR-027 (сценарий 10.2): время бездействия запоминается при создании сессии; новое значение — для новых сессий."""
    user, admin = support.make_employee(), support.logged_in(support.make_admin())
    before = support.logged_in(user, ip="198.51.100.203")
    assert support.post_security_settings(admin, idle_timeout_minutes=10).status_code == 302
    after = support.logged_in(user, ip="198.51.100.204")
    clock.advance(minutes=30)
    assert before.get("/me/").status_code == 200, "прежняя сессия живёт по прежним 60 минутам"
    assert after.get("/me/").status_code == 302, "новая сессия — по новым 10 минутам"
    event = model("core.AuditEvent").objects.get(action="security_settings.updated")
    assert event.before["idle_timeout_minutes"] == 60 and event.after["idle_timeout_minutes"] == 10


def test_change_password_needs_current_mails_and_closes_other_sessions():
    """FR-029 (сценарий 16): смена требует текущий пароль, шлёт письмо, закрывает остальные сессии и пишется в журнал без паролей."""
    user = support.make_employee()
    here, elsewhere = support.logged_in(user, ip="198.51.100.205"), support.logged_in(user, ip="198.51.100.206")
    new = factories.new_password()
    wrong = change(here, factories.new_password(), new)
    assert wrong.status_code == 200
    user.refresh_from_db()
    assert user.check_password(user.test_password) and not support.mails(template="password_changed")
    done = change(here, user.test_password, new)
    assert done.status_code == 302
    user.refresh_from_db()
    assert user.check_password(new)
    assert support.mails(to=user.email, template="password_changed").count() == 1
    assert here.get("/me/").status_code == 200, "текущая сессия остаётся"
    assert elsewhere.get("/me/").status_code == 302, "остальные закрыты"
    event = model("core.AuditEvent").objects.get(action="password.changed", object_id=str(user.pk))
    assert new not in str(event.before) + str(event.after) and user.test_password not in str(event.before) + str(event.after)


def test_logout_everywhere_keeps_current_session():
    """FR-030 (сценарий 10.3, 10.4): «Выйти со всех устройств» закрывает остальные сессии, текущая остаётся."""
    user, other = support.make_employee(), support.make_employee()
    clients = [support.logged_in(user, ip=f"198.51.100.{210 + i}", ua=ua)
               for i, ua in enumerate((support.FIREFOX_UA, support.CHROME_UA, "Mozilla/5.0 (X11; Linux) Edg/129"))]
    bystander = support.logged_in(other, ip="198.51.100.220")
    done = clients[0].post("/me/security/logout-everywhere/")
    assert done.status_code == 302
    assert clients[0].get("/me/").status_code == 200
    for closed in clients[1:]:
        got = closed.get("/me/")
        assert got.status_code == 302 and "/login/" in got["Location"]
    assert model("core.UserSession").objects.filter(user=user).count() == 1
    assert bystander.get("/me/").status_code == 200
    assert "sessions.logout_everywhere" in support.audit_actions(object_id=str(user.pk))


def test_password_hash_is_argon2_and_irreversible():
    """NFR-011: пароли только argon2-хешем; открытого вида нет ни в таблицах, ни в страницах, ни в журнале."""
    user = support.make_employee()
    client = support.logged_in(user)
    new = factories.new_password()
    assert change(client, user.test_password, new).status_code == 302
    user.refresh_from_db()
    assert user.password.startswith("argon2$") and user.check_password(new)
    hashes = list(model("core.PasswordHistory").objects.filter(user=user).values_list("password_hash", flat=True))
    assert hashes and all(h.startswith("argon2$") for h in hashes)
    stored = ""
    with connection.cursor() as cur:
        for query in ("SELECT * FROM core_user", "SELECT * FROM core_passwordhistory",
                      "SELECT * FROM core_auditevent", "SELECT * FROM core_loginattempt"):
            cur.execute(query)
            stored += " ".join(str(v) for row in cur.fetchall() for v in row)
    assert new not in stored and user.test_password not in stored
    admin = support.logged_in(support.make_admin(), ip="198.51.100.221")
    card = admin.get(f"/staff/{user.pk}/").content.decode()
    assert "argon2" not in card and new not in card
