"""T-110: защита от перебора на настоящем Valkey (FR-027, FR-035…038, FR-044, NFR-006, NFR-007). Сценарий 9 спеки.

Ключи Valkey — по PLAN-001: fail:acct:<id>, lock:acct:<id>, fail:ip:<ip>, accts:ip:<ip>, lock:ip:<ip>.
Потеря срока жизни ключа имитируется его удалением: Valkey и RQ живут по настоящему времени.
"""
import pytest

from tests import factories, support
from tests.support import model, valkey, valkey_int, valkey_key

pytestmark = pytest.mark.django_db

IP = "198.51.100.30"


def fail(email, ip=IP, password=None):
    return support.make_client(ip=ip).post("/login/", {"email": email, "password": password or factories.new_password()})


def fail_n(user_or_email, n, ip=IP):
    email = getattr(user_or_email, "email", user_or_email)
    return [fail(email, ip) for _ in range(n)]


def ttl(suffix):
    key = valkey_key(suffix)
    assert key, f"ключа …{suffix} в Valkey нет"
    client = valkey()
    try:
        return client.ttl(key)
    finally:
        client.close()


def can_log_in(user, ip) -> bool:
    client = support.make_client(ip=ip)
    first = support.post_password(client, user)
    if first.status_code != 302 or not first["Location"].endswith("/login/code/"):
        return False
    client.post("/login/code/", {"code": support.current_code(user)})
    return client.get("/me/").status_code == 200


def test_account_locked_after_5_failures_for_15_minutes():
    """FR-035, NFR-006 (сценарий 9.1): на пятой неудаче запись блокируется на 15 минут; шестая попытка — прежний ответ."""
    user = support.make_employee()
    generic = fail(support.make_employee().email, "198.51.100.31")
    fail_n(user, 4)
    assert not valkey_key(f"lock:acct:{user.pk}"), "четыре неудачи ещё не блокируют"
    assert support.valkey_int(f"fail:acct:{user.pk}") == 4
    fail(user.email)
    assert 14 * 60 < ttl(f"lock:acct:{user.pk}") <= 15 * 60
    sixth = support.make_client(ip=IP).post("/login/", {"email": user.email, "password": user.test_password})
    assert support.same_failure(sixth, generic), "шестая попытка с верным паролем неотличима от неверной"
    results = list(model("core.LoginAttempt").objects.filter(user=user).order_by("id").values_list("result", flat=True))
    assert results == ["bad_password"] * 5 + ["locked"]
    event = model("core.AuditEvent").objects.get(action="account.locked", object_id=str(user.pk))
    assert event.ip == IP and event.actor_id is None


def test_lock_expires_after_account_lock_minutes():
    """FR-035 (сценарий 9.2): срок блокировки — account_lock_minutes; после него вход возможен и счётчик обнулён."""
    user = support.make_employee()
    support.set_security(account_lock_minutes=3)
    fail_n(user, 5)
    assert 2 * 60 < ttl(f"lock:acct:{user.pk}") <= 3 * 60, "срок берётся из настройки, а не из кода"
    assert valkey_int(f"fail:acct:{user.pk}") == 0, "счётчик обнуляется при блокировке"
    client = valkey()
    client.delete(valkey_key(f"lock:acct:{user.pk}"))  # так срок жизни ключа и заканчивается
    client.close()
    fail(user.email)
    assert not valkey_key(f"lock:acct:{user.pk}"), "после истечения серия начинается заново"
    assert can_log_in(user, IP)


def test_20_failures_on_one_account_do_not_lock_ip():
    """FR-036 (сценарий 9.6): сколько бы раз ни ошибались в одной записи, адрес не блокируется."""
    support.set_security(account_lock_limit=100)
    victim, other = support.make_employee(), support.make_employee()
    fail_n(victim, 25)
    assert valkey_int(f"fail:ip:{IP}") == 25
    assert not valkey_key(f"lock:ip:{IP}")
    assert can_log_in(other, IP)


def test_20_failures_across_3_accounts_lock_ip_for_15_minutes():
    """FR-036, NFR-006 (сценарий 9.6): 20 неудач по трём и более разным записям блокируют адрес на 15 минут для всех."""
    support.set_security(account_lock_limit=100)
    accounts = [support.make_employee() for _ in range(3)]
    bystander = support.make_employee()
    for i in range(19):
        fail(accounts[i % 3].email)
    assert not valkey_key(f"lock:ip:{IP}")
    fail(accounts[0].email)
    assert 14 * 60 < ttl(f"lock:ip:{IP}") <= 15 * 60
    refused = support.make_client(ip=IP).post("/login/", {"email": bystander.email, "password": bystander.test_password})
    generic = fail(bystander.email, "198.51.100.32")
    assert support.same_failure(refused, generic), "ответ для заблокированного адреса не раскрывает причину"
    assert not any(a.email in refused.content.decode() for a in accounts)
    assert model("core.LoginAttempt").objects.filter(user=bystander, result="ip_locked").exists()
    event = model("core.AuditEvent").objects.get(action="ip.locked")
    assert event.object_id == IP and event.actor_id is None
    assert can_log_in(bystander, "198.51.100.33"), "другой адрес не затронут"


def test_locked_results_not_counted_towards_ip_threshold():
    """FR-036: отказы по уже заблокированной записи в счёт адреса не идут."""
    a, b, c, d = (support.make_employee() for _ in range(4))
    fail_n(a, 5)
    assert valkey_int(f"fail:ip:{IP}") == 5
    for _ in range(40):
        support.make_client(ip=IP).post("/login/", {"email": a.email, "password": a.test_password})
    assert valkey_int(f"fail:ip:{IP}") == 5, "повторы по заблокированной записи набирают порог адреса"
    fail_n(b, 2)
    fail_n(c, 2)
    assert valkey_int(f"fail:ip:{IP}") == 9 and not valkey_key(f"lock:ip:{IP}")
    assert can_log_in(d, IP)


def test_nonexistent_accounts_counted_by_login_hash():
    """FR-036: попытки в несуществующие записи тоже считаются, по хешу логина; сам адрес почты в Valkey не попадает."""
    ghosts = [factories.new_email("ghost") for _ in range(4)]
    for ghost in ghosts[:3]:
        fail_n(ghost, 5)
    assert valkey_int(f"fail:ip:{IP}") == 15 and not valkey_key(f"lock:ip:{IP}")
    r = valkey()
    members = r.smembers(valkey_key(f"accts:ip:{IP}"))
    assert len(members) == 3, "в множестве адреса — по одному хешу на каждый логин"
    fail_n(ghosts[3], 5)
    assert valkey_key(f"lock:ip:{IP}"), "20 неудач по четырём несуществующим записям блокируют адрес"
    dump = b" ".join([k for k in r.keys("*")] + [m for k in r.keys("accts:*") for m in r.smembers(k)])
    r.close()
    assert not any(g.encode() in dump or g.split("@")[0].encode() in dump for g in ghosts), "логин лежит в Valkey открытым"


def test_other_user_logs_in_from_same_ip_without_delay():
    """FR-036, NFR-006 (сценарий 9.5): запись одного сотрудника заблокирована, другой с того же адреса входит сразу."""
    blocked, colleague = support.make_employee(), support.make_employee()
    fail_n(blocked, 5)
    assert valkey_key(f"lock:acct:{blocked.pk}")
    assert can_log_in(colleague, IP)
    assert not valkey_key(f"lock:ip:{IP}")


def test_ip_thresholds_editable_in_settings():
    """FR-036, FR-027: порог, минимум записей, окно и срок блокировки адреса меняются в настройках безопасности."""
    admin = support.logged_in(support.make_admin(), ip="198.51.100.34")
    done = support.post_security_settings(admin, ip_lock_limit=6, ip_lock_min_accounts=2, ip_lock_window_minutes=5,
                                          ip_lock_minutes=7, account_lock_limit=100)
    assert done.status_code == 302
    one, two = support.make_employee(), support.make_employee()
    for i in range(5):
        fail((one, two)[i % 2].email)
    assert not valkey_key(f"lock:ip:{IP}")
    assert 4 * 60 < ttl(f"fail:ip:{IP}") <= 5 * 60, "окно счёта — ip_lock_window_minutes"
    fail(two.email)
    assert 6 * 60 < ttl(f"lock:ip:{IP}") <= 7 * 60, "срок блокировки адреса — ip_lock_minutes"
    changed = model("core.AuditEvent").objects.get(action="security_settings.updated")
    assert changed.before["ip_lock_limit"] == 20 and changed.after["ip_lock_limit"] == 6


def test_lock_mail_sent_once_per_lock():
    """FR-037 (сценарий 9.4): письмо о блокировке записи — одно на блокировку, повторные отказы его не плодят."""
    user = support.make_employee()
    fail_n(user, 5)
    for _ in range(10):
        support.make_client(ip=IP).post("/login/", {"email": user.email, "password": user.test_password})
    assert support.mails(to=user.email, template="account_locked").count() == 1
    ghost = factories.new_email("ghost")
    fail_n(ghost, 6)
    assert not support.mails(to=ghost)
    admin = support.logged_in(support.make_admin(), ip="198.51.100.35")
    assert admin.post(f"/staff/{user.pk}/unlock/").status_code == 302
    fail_n(user, 5, ip="198.51.100.36")
    assert support.mails(to=user.email, template="account_locked").count() == 2


def test_admin_unlocks_account_and_ip_early_and_audited():
    """FR-038, FR-044 (сценарий 9.7, 9.8): администратор снимает блокировку записи и адреса, каждое снятие — в журнале."""
    victim = support.make_employee()
    fail_n(victim, 5)
    support.set_security(account_lock_limit=100)
    others = [support.make_employee() for _ in range(3)]
    for i in range(20):
        fail(others[i % 3].email, "198.51.100.37")
    assert valkey_key(f"lock:acct:{victim.pk}") and valkey_key("lock:ip:198.51.100.37")
    admin = support.make_admin()
    client = support.logged_in(admin, ip="198.51.100.38")
    page = client.get("/staff/locks/").content.decode()
    assert victim.email in page and "198.51.100.37" in page, "на странице блокировок — запись и адрес"
    assert client.post("/staff/locks/", {"kind": "account", "target": victim.pk}).status_code == 302
    assert not valkey_key(f"lock:acct:{victim.pk}") and valkey_int(f"fail:acct:{victim.pk}") == 0
    assert can_log_in(victim, "198.51.100.39")
    assert client.post("/staff/locks/", {"kind": "ip", "target": "198.51.100.37"}).status_code == 302
    assert not valkey_key("lock:ip:198.51.100.37") and valkey_int("fail:ip:198.51.100.37") == 0
    assert not valkey_key("accts:ip:198.51.100.37")
    assert can_log_in(others[0], "198.51.100.37")
    unlocked = model("core.AuditEvent").objects.get(action="account.unlocked", object_id=str(victim.pk))
    assert unlocked.actor_id == admin.pk
    ip_unlocked = model("core.AuditEvent").objects.get(action="ip.unlocked", object_id="198.51.100.37")
    assert ip_unlocked.actor_id == admin.pk
    fail_n(victim, 5, ip="198.51.100.40")
    assert client.post(f"/staff/{victim.pk}/unlock/").status_code == 302, "то же действие из карточки сотрудника"
    assert not valkey_key(f"lock:acct:{victim.pk}")


def test_parallel_failures_counted_atomically():
    """FR-035, FR-036: при одновременных неудачах счётчики точны: одна блокировка, пять засчитанных, порог адреса срабатывает один раз.

    Сервис блокировки не обращается к базе (потоки не видят данных теста), поэтому проверяется напрямую.
    """
    from apps.core.services import lockout

    limits = lockout.Limits()
    outcomes = support.run_threads(lambda key, ip: lockout.register_failure(account_key=key, ip=ip, limits=limits),
                                   [("k-one", "203.0.113.10")] * 40)
    assert sum(o.account_locked_now for o in outcomes) == 1
    assert sum(o.counted for o in outcomes) == 5
    assert valkey_int("fail:ip:203.0.113.10") == 5 and valkey_key("lock:acct:k-one")
    args = [(f"k-{n % 4}", "203.0.113.11") for n in range(20)]
    outcomes = support.run_threads(lambda key, ip: lockout.register_failure(account_key=key, ip=ip, limits=limits), args)
    assert sum(o.counted for o in outcomes) == 20
    assert sum(o.ip_locked_now for o in outcomes) == 1, "блокировка адреса объявляется ровно один раз"
    assert valkey_int("fail:ip:203.0.113.11") == 20 and valkey_key("lock:ip:203.0.113.11")
    r = valkey()
    assert r.scard(valkey_key("accts:ip:203.0.113.11")) == 4
    r.close()


def test_valkey_data_loss_resets_counters_events_stay_in_audit():
    """NFR-006: потеря Valkey обнуляет счётчики, а события блокировок остаются в журнале и истории."""
    user = support.make_employee()
    fail_n(user, 5)
    assert valkey_key(f"lock:acct:{user.pk}")
    r = valkey()
    r.flushdb()
    r.close()
    assert can_log_in(user, IP), "после потери Valkey блокировка снята"
    assert valkey_int(f"fail:acct:{user.pk}") == 0
    assert "account.locked" in support.audit_actions(object_id=str(user.pk))
    assert model("core.LoginAttempt").objects.filter(user=user, result="bad_password").count() == 5


def test_real_ip_taken_from_forwarded_header_only_from_trusted_proxy(settings):
    """NFR-006, NFR-007: адрес из X-Forwarded-For берётся только от доверенного прокси; подделка с чужого адреса не действует."""
    settings.TRUSTED_PROXIES = ["10.9.9.9"]
    user = support.make_employee()
    Attempt = model("core.LoginAttempt")

    def attempt(remote, forwarded=None):
        extra = {"HTTP_X_FORWARDED_FOR": forwarded} if forwarded else {}
        support.make_client(ip=remote).post("/login/", {"email": user.email, "password": factories.new_password()}, **extra)
        return Attempt.objects.order_by("-id").first().ip

    assert attempt("198.51.100.77", "203.0.113.99") == "198.51.100.77", "заголовок от чужого адреса игнорируется"
    assert attempt("10.9.9.9", "203.0.113.55") == "203.0.113.55"
    assert attempt("10.9.9.9", "203.0.113.55, 10.9.9.9") == "203.0.113.55"
    assert attempt("10.9.9.9", "1.2.3.4, 203.0.113.56") == "203.0.113.56", "левую часть цепочки задаёт клиент — ей не верим"
    assert attempt("10.9.9.9") == "10.9.9.9"
    assert valkey_int("fail:ip:198.51.100.77") == 1 and valkey_int("fail:ip:203.0.113.99") == 0
