"""T-104: одноразовые ссылки активации и восстановления (FR-008…012, FR-031…034). Сценарии 2, 8, 15, 18."""
from datetime import timedelta

import django_rq
import pytest
from django.conf import settings

from tests import factories, support
from tests.support import model

pytestmark = pytest.mark.django_db

EXCHANGE = {"activation": "/activate/exchange/", "reset": "/password/reset/exchange/"}


def exchange(client, code, purpose="activation", **extra):
    return client.post(EXCHANGE[purpose], {"code": code}, **extra)


def exchange_ok(response, purpose="activation") -> bool:
    return response.status_code == 302 and response["Location"].endswith(
        "/activate/profile/" if purpose == "activation" else "/password/reset/")


def invited(**extra):
    return support.make_employee(state="invited", totp=False, **extra)


def create_invited_via_admin(capture):
    """Администратор заводит сотрудника через форму; возвращает (сотрудник, ссылка, код)."""
    admin = support.make_admin()
    client = support.logged_in(admin)
    email = factories.new_email("invitee")
    with capture(execute=True):
        done = client.post("/staff/new/", {"email": email, "full_name": "Приглашённый Пётр", "position": "Инженер",
                                           "roles": [support.role_by_name(support.STAFF_ROLE).pk]})
    assert done.status_code == 302
    user = model("core.User").objects.get(email=email)
    link = model("core.OneTimeLink").objects.get(user=user, purpose="activation")
    return user, link, support.link_code(link), client


def test_activation_link_72h_created_and_mail_queued(clock, django_capture_on_commit_callbacks):
    """FR-008: создание записи выпускает ссылку на 72 часа и ставит письмо-приглашение в очередь RQ."""
    user, link, code, _ = create_invited_via_admin(django_capture_on_commit_callbacks)
    assert user.state == "invited"
    assert timedelta(hours=71, minutes=59) < link.expires_at - clock._now <= timedelta(hours=72)
    assert link.used_at is None and link.revoked_at is None and link.token_hash == support.sha256(code)
    message = support.mails(to=user.email, template="invitation").get()
    assert message.status == "queued" and message.related_user_id == user.pk
    jobs = django_rq.get_queue("mail").jobs
    assert [job.args for job in jobs] == [(message.pk,)], "в очереди — одно задание с номером письма"
    assert "invitation.sent" in support.audit_actions(object_id=str(user.pk))


def test_admin_sees_active_link_and_mail_state_decrypt_audited(django_capture_on_commit_callbacks):
    """FR-009: в карточке неактивированной записи — действующая ссылка и состояние письма; показ ссылки пишется в журнал."""
    user, link, code, admin_client = create_invited_via_admin(django_capture_on_commit_callbacks)
    page = admin_client.get(f"/staff/{user.pk}/").content.decode()
    assert f"{settings.PORTAL_URL}/activate/#{code}" in page
    assert "очеред" in page.lower()
    revealed = model("core.AuditEvent").objects.get(action="link.revealed", object_id=str(link.pk))
    assert code not in str(revealed.before) + str(revealed.after) and revealed.actor is not None
    message = support.mails(to=user.email).get()
    for status, word in (("sent", "отправлен"), ("failed", "не доставлен")):
        message.status = status
        message.save()
        assert word in admin_client.get(f"/staff/{user.pk}/").content.decode().lower()
    reader = support.logged_in(support.make_with_permissions("audit.view"))
    assert reader.get(f"/staff/{user.pk}/").status_code == 403


def test_resend_invitation_revokes_previous_link(django_capture_on_commit_callbacks):
    """FR-010: «Отправить приглашение заново» гасит прежнюю ссылку, выпускает новую и шлёт новое письмо."""
    user, first, first_code, admin_client = create_invited_via_admin(django_capture_on_commit_callbacks)
    with django_capture_on_commit_callbacks(execute=True):
        assert admin_client.post(f"/staff/{user.pk}/invite/").status_code == 302
    first.refresh_from_db()
    assert first.revoked_at is not None and not first.code_encrypted, "код погашенной ссылки стирается"
    Link = model("core.OneTimeLink")
    live = Link.objects.filter(user=user, purpose="activation", revoked_at__isnull=True, used_at__isnull=True)
    assert live.count() == 1 and live.get().pk != first.pk
    assert not exchange_ok(exchange(support.make_client(), first_code))
    assert exchange_ok(exchange(support.make_client(), support.link_code(live.get())))
    assert support.mails(to=user.email, template="invitation").count() == 2
    assert support.audit_actions(object_id=str(user.pk)).count("invitation.sent") == 2


def test_link_dead_after_use_expiry_block_or_new_link(clock):
    """FR-011: ссылка не работает после использования, 72 часов, блокировки записи и выпуска новой."""
    def make(purpose="activation"):
        user = invited()
        return (user, *factories.make_link(user, purpose))

    fresh_user, fresh, fresh_code = make()
    assert exchange_ok(exchange(support.make_client(), fresh_code)), "действующая ссылка обязана работать"
    used_user, used, used_code = make()
    used.used_at = clock._now
    used.save()
    assert not exchange_ok(exchange(support.make_client(), used_code))
    old_user, old, old_code = make()
    support.logged_in(support.make_admin()).post(f"/staff/{old_user.pk}/invite/")
    assert not exchange_ok(exchange(support.make_client(), old_code)), "новая ссылка гасит прежнюю"
    blocked_user, blocked, blocked_code = make()
    support.logged_in(support.make_admin()).post(f"/staff/{blocked_user.pk}/block/", {"reason": "проверка"})
    assert not exchange_ok(exchange(support.make_client(), blocked_code)), "блокировка гасит ссылку активации"
    late_user, late, late_code = make()
    clock.advance(hours=72, minutes=1)
    assert not exchange_ok(exchange(support.make_client(), late_code))


@pytest.mark.parametrize("purpose", ["activation", "reset"])
def test_invalid_expired_used_links_give_identical_response(purpose, clock):
    """FR-011, FR-032, FR-034: неверная, просроченная, использованная и погашенная ссылки дают один ответ, без подсказок о записи."""
    user = support.make_employee(state="invited" if purpose == "activation" else "active", totp=purpose == "reset")
    link_expired, code_expired = factories.make_link(user, purpose, ttl=timedelta(minutes=-1))
    link_used, code_used = factories.make_link(user, purpose)
    link_used.used_at = clock._now
    link_used.save()
    link_revoked, code_revoked = factories.make_link(user, purpose)
    link_revoked.revoked_at = clock._now
    link_revoked.save()
    wrong = factories.new_password()
    responses = [exchange(support.make_client(ip=f"198.51.100.{i}"), c, purpose)
                 for i, c in enumerate((wrong, code_expired, code_used, code_revoked), start=30)]
    assert all(r.status_code != 302 for r in responses)
    assert support.same_failure(*responses)
    body = responses[0].content.decode()
    assert user.email not in body and user.full_name not in body
    assert support.same_failure(responses[0], exchange(support.make_client(), "", purpose))


def test_get_with_code_not_accepted_exchange_is_post_only():
    """FR-012, FR-032: код принимается только телом POST; GET и параметр адреса его не обменивают."""
    user = invited()
    link, code = factories.make_link(user, "activation")
    reset_user = support.make_employee()
    reset_link, reset_code = factories.make_link(reset_user, "reset")
    client = support.make_client()
    assert client.get("/activate/exchange/").status_code == 405
    assert client.get("/password/reset/exchange/").status_code == 405
    client.get(f"/activate/?code={code}")
    client.get(f"/activate/{code}/")
    assert client.get("/activate/profile/").status_code in (302, 403), "GET с кодом не должен открывать мастер"
    assert not exchange_ok(client.post(f"/activate/exchange/?code={code}"))
    assert not exchange_ok(client.post(f"/password/reset/exchange/?code={reset_code}"), "reset")
    client.get(f"/password/reset/?code={reset_code}")
    attempt = factories.new_password()
    done = client.post("/password/reset/", {"password1": attempt, "password2": attempt})
    assert not (done.status_code == 302 and done["Location"].endswith("/login/")), "без обмена кода пароль не меняется"
    reset_user.refresh_from_db()
    assert not reset_user.check_password(attempt)
    assert exchange_ok(exchange(client, code)), "ссылка не должна сгорать от GET"
    assert exchange_ok(exchange(support.make_client(), reset_code, "reset"), "reset")


def test_code_not_in_url_after_exchange_nor_in_queue_payload(django_capture_on_commit_callbacks):
    """FR-012: после обмена адрес без кода; в очереди RQ и в письме-записи кода нет."""
    user, link, code, _ = create_invited_via_admin(django_capture_on_commit_callbacks)
    client = support.make_client()
    done = exchange(client, code)
    assert exchange_ok(done) and code not in done["Location"]
    page = client.get(done["Location"], follow=True)
    assert code not in page.request["PATH_INFO"] and code not in page.request["QUERY_STRING"]
    assert code not in page.content.decode()
    for job in django_rq.get_queue("mail").jobs:
        assert code not in repr((job.args, job.kwargs, job.description, job.func_name, job.meta))
    message = support.mails(to=user.email).get()
    assert code not in " ".join(str(getattr(message, f)) for f in ("to", "template", "subject", "last_error"))
    r = support.valkey()
    for key in r.keys("*"):
        raw = r.get(key) if r.type(key) == b"string" else b""
        assert code.encode() not in (raw or b""), f"код ссылки в Valkey: {key!r}"
    r.close()


def forgot(email, ip="198.51.100.40"):
    return support.make_client(ip=ip).post("/password/forgot/", {"email": email})


def test_forgot_answer_same_for_unknown_blocked_invited_and_active():
    """FR-031: ответ на запрос восстановления одинаков для чужого адреса, заблокированной, приглашённой и активной записи."""
    active, blocked = support.make_employee(), support.make_employee(state="blocked")
    pending = invited()
    responses = [forgot(e, f"198.51.100.{50 + i}") for i, e in enumerate(
        (factories.new_email("nobody"), blocked.email, pending.email, active.email))]
    assert all(r.status_code in (200, 302) for r in responses)
    assert support.same_failure(*responses)
    assert active.email not in responses[3].content.decode()


def test_forgot_mail_only_for_active_account():
    """FR-031: письмо и ссылка восстановления — только для активной записи; запрос попадает в журнал."""
    Link = model("core.OneTimeLink")
    active, blocked, pending = support.make_employee(), support.make_employee(state="blocked"), invited()
    for i, email in enumerate((factories.new_email("nobody"), blocked.email, pending.email, active.email)):
        forgot(email, f"198.51.100.{60 + i}")
    sent = support.mails(template="password_reset")
    assert [m.to for m in sent] == [active.email]
    assert list(Link.objects.filter(purpose="reset").values_list("user_id", flat=True)) == [active.pk]
    assert "password.reset_requested" in support.audit_actions()


def test_forgot_rate_limit_3_per_hour_per_email_10_per_ip():
    """FR-031 (сценарий 18, п. 9): не больше 3 писем в час на адрес и 10 с одного IP; ответ прежний."""
    one = support.make_employee()
    answers = [forgot(one.email, f"198.51.100.{70 + i}") for i in range(5)]
    assert support.same_failure(*answers)
    assert support.mails(to=one.email, template="password_reset").count() == 3
    users = [support.make_employee() for _ in range(12)]
    answers = [forgot(u.email, "198.51.100.99") for u in users]
    assert support.same_failure(*answers)
    assert support.mails(template="password_reset", to__in=[u.email for u in users]).count() == 10


def test_reset_link_1h_one_time_revoked_by_new_request_or_block(clock):
    """FR-032: ссылка восстановления живёт час, одноразовая, гаснет от нового запроса и от блокировки записи."""
    Link = model("core.OneTimeLink")
    user = support.make_employee()
    forgot(user.email, "198.51.100.80")
    first = Link.objects.get(user=user, purpose="reset")
    assert timedelta(minutes=59) < first.expires_at - clock._now <= timedelta(hours=1)
    first_code = support.link_code(first)
    forgot(user.email, "198.51.100.81")
    first.refresh_from_db()
    assert first.revoked_at is not None, "новый запрос гасит прежнюю ссылку"
    second = Link.objects.get(user=user, purpose="reset", revoked_at__isnull=True)
    assert not exchange_ok(exchange(support.make_client(), first_code, "reset"), "reset")
    client = support.make_client()
    second_code = support.link_code(second)
    assert exchange_ok(exchange(client, second_code, "reset"), "reset")
    done = client.post("/password/reset/", {"password1": factories.new_password(), "password2": ""})
    assert done.status_code != 500
    clock.advance(minutes=61)
    assert not exchange_ok(exchange(support.make_client(), second_code, "reset"), "reset")
    other = support.make_employee()
    _, other_code = factories.make_link(other, "reset")
    support.logged_in(support.make_admin()).post(f"/staff/{other.pk}/block/", {"reason": "проверка"})
    assert not exchange_ok(exchange(support.make_client(), other_code, "reset"), "reset")


def test_reset_applies_password_policy_closes_sessions_mails_and_keeps_second_factor(django_capture_on_commit_callbacks):
    """FR-033: новый пароль — по политике; сессии закрыты, письмо о смене отправлено, второй фактор по-прежнему нужен."""
    user = support.make_employee()
    old_password = factories.new_password()
    support.set_password_history(user, [factories.new_password(), old_password])
    elsewhere = support.logged_in(user, ip="198.51.100.90")
    assert elsewhere.get("/me/").status_code == 200
    _, code = factories.make_link(user, "reset")
    client = support.make_client(ip="198.51.100.91")
    assert exchange_ok(exchange(client, code, "reset"), "reset")
    short = client.post("/password/reset/", {"password1": "Ab1-xy", "password2": "Ab1-xy"})
    assert short.status_code == 200 and "символ" in short.content.decode()
    repeat = client.post("/password/reset/", {"password1": old_password, "password2": old_password})
    assert repeat.status_code == 200 and "последн" in repeat.content.decode()
    new_password = factories.new_password()
    with django_capture_on_commit_callbacks(execute=True):
        done = client.post("/password/reset/", {"password1": new_password, "password2": new_password})
    assert done.status_code == 302 and "/login/" in done["Location"]
    assert elsewhere.get("/me/").status_code == 302, "сессии на других устройствах закрыты"
    assert not model("core.UserSession").objects.filter(user=user).exists()
    assert support.mails(to=user.email, template="password_changed").count() == 1
    assert {"password.changed", "sessions.closed"} <= set(support.audit_actions(object_id=str(user.pk)))
    assert client.get("/me/").status_code == 302, "после восстановления входа без пароля и кода нет"
    assert not exchange_ok(exchange(support.make_client(), code, "reset"), "reset")
    user.test_password = new_password
    fresh = support.make_client(ip="198.51.100.92")
    step = support.post_password(fresh, user)
    assert step.status_code == 302 and step["Location"].endswith("/login/code/"), "второй фактор по-прежнему нужен"
    assert fresh.get("/me/").status_code == 302
    assert model("core.EncryptedTOTPDevice").objects.filter(user=user, confirmed=True).count() == 1
