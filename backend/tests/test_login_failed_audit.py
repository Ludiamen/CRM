"""FR-044 (поправка прохода 3б): отказы входа по блокировке пишутся не только в историю входов, но и в журнал событий.

Спека требует журналировать неудачные попытки входа. Отказы с результатом `locked` и `ip_locked`
раньше шли только в `LoginAttempt`; теперь у каждого есть событие `login.failed` с результатом в «стало».
Пароля, кода, почты введённого логина и их производных в событии нет.
"""
import json

import pytest

from tests import factories, support
from tests.support import model

pytestmark = pytest.mark.django_db

IP = "198.51.100.200"


def failed_events(**filters):
    return list(model("core.AuditEvent").objects.filter(action="login.failed", **filters).order_by("id"))


def dump(events) -> str:
    return json.dumps([[e.object_type, e.object_id, e.before, e.after, str(e.ip)] for e in events], ensure_ascii=False)


def test_account_locked_refusals_written_to_audit_without_secrets():
    """Пять неверных паролей, затем отказ по блокировке записи: у каждой неудачи своё событие, у отказа — результат `locked`."""
    user = support.make_employee()
    wrong = [factories.new_password() for _ in range(5)]
    for password in wrong:
        support.make_client(ip=IP).post("/login/", {"email": user.email, "password": password})
    refused = factories.new_password()
    support.make_client(ip=IP).post("/login/", {"email": user.email, "password": refused})
    support.make_client(ip=IP).post("/login/", {"email": user.email, "password": user.test_password})
    events = failed_events(object_id=str(user.pk))
    assert [e.after["result"] for e in events] == ["bad_password"] * 5 + ["locked", "locked"]
    assert all(e.actor_id is None and e.ip == IP and e.object_type == "user" for e in events)
    text = dump(events)
    for secret in (*wrong, refused, user.test_password, user.email, user.email.split("@")[0]):
        assert secret not in text, "секрет или почта в событии неудачного входа"
    history = list(model("core.LoginAttempt").objects.filter(user=user).order_by("id").values_list("result", flat=True))
    assert history == ["bad_password"] * 5 + ["locked", "locked"], "история входов и журнал совпадают"


def test_ip_locked_refusal_written_to_audit():
    """Отказ по блокировке адреса — тоже событие с результатом `ip_locked`; для чужой почты объект пуст."""
    support.set_security(account_lock_limit=100)
    accounts = [support.make_employee() for _ in range(3)]
    for i in range(20):
        support.make_client(ip=IP).post("/login/", {"email": accounts[i % 3].email, "password": factories.new_password()})
    assert support.valkey_key(f"lock:ip:{IP}")
    bystander = support.make_employee()
    typed = factories.new_password()
    support.make_client(ip=IP).post("/login/", {"email": bystander.email, "password": typed})
    ghost = factories.new_email("ghost")
    support.make_client(ip=IP).post("/login/", {"email": ghost, "password": typed})
    refused = [e for e in failed_events() if e.after.get("result") == "ip_locked"]
    assert [e.object_id for e in refused] == [str(bystander.pk), ""], "для несуществующей записи объект пуст"
    text = dump(refused)
    for secret in (typed, bystander.email, ghost, ghost.split("@")[0]):
        assert secret not in text


def test_refusals_at_code_step_written_to_audit():
    """На шаге кода отказ по блокировке записи тоже в журнале: результат `locked`, сам код не сохраняется."""
    user = support.make_employee()
    client = support.make_client(ip=IP)
    assert support.post_password(client, user).status_code == 302
    for n in range(5):
        support.make_client(ip=f"198.51.100.{210 + n}").post(
            "/login/", {"email": user.email, "password": factories.new_password()})
    guess = "123456"
    client.post("/login/code/", {"code": guess})
    locked = [e for e in failed_events(object_id=str(user.pk)) if e.after.get("result") == "locked"]
    assert len(locked) == 1 and guess not in dump(locked)
