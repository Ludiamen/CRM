"""T-230, T-231: письма среза через сервисы ядра, без страниц администратора (FR-044, FR-052…055, NFR-010).

Те же шесть писем, что и в test_mail.py, но поводы создаются сервисами и страницами входа, поэтому тесты не
ждут `/staff/…`. Доставляет настоящий `SimpleWorker` в процессе теста, принимает настоящий Mailpit.
"""
import re

import pytest
from django.conf import settings

from tests import factories, support
from tests.support import model
from tests.support_mail import deliver

pytestmark = pytest.mark.django_db

PORTAL_NAME = "Портал-проверка писем"
TEMPLATES = {"invitation", "password_reset", "account_locked", "new_device", "second_factor_reset", "password_changed"}


def make_all(capture, mailpit):
    """Шесть писем через сервисы; возвращает {шаблон: (письмо Mailpit, пользователь, секреты)}."""
    from apps.core.services import accounts, links
    from apps.core.services.second_factor import issue_backup_codes

    model("core.PortalSettings").objects.update(name=PORTAL_NAME)
    admin = support.make_admin()
    made = {}
    with capture(execute=True):
        invitee = support.make_employee(state="invited", totp=False)
        links.send_invitation(invitee, created_by=admin)
        made["invitation"] = (invitee, support.link_code(model("core.OneTimeLink").objects.get(user=invitee, purpose="activation")))
        forgetful = support.make_employee()
        links.request_password_reset(forgetful.email, ip="198.51.100.131")
        made["password_reset"] = (forgetful, support.link_code(model("core.OneTimeLink").objects.get(user=forgetful, purpose="reset")))
        locked = support.make_employee()
        for _ in range(5):
            support.make_client(ip="198.51.100.132").post("/login/", {"email": locked.email, "password": factories.new_password()})
        made["account_locked"] = (locked, None)
        roamer = support.make_employee()
        support.logged_in(roamer, ip="198.51.100.133")
        support.logged_in(roamer, ip="198.51.100.134", ua=support.CHROME_UA)
        made["new_device"] = (roamer, None)
        lost = support.make_employee()
        lost_codes = issue_backup_codes(lost)
        accounts.reset_second_factor(lost, actor=admin)
        made["second_factor_reset"] = (lost, lost_codes)
        changer = support.make_employee()
        new = factories.new_password()
        client = support.logged_in(changer, ip="198.51.100.135")
        client.post("/me/security/password/", {"current_password": changer.test_password, "password1": new, "password2": new})
        made["password_changed"] = (changer, (changer.test_password, new))
    deliver()
    return {t: (mailpit.wait_for(user.email), user, extra) for t, (user, extra) in made.items()}


def header(mailpit, letter, name):
    import json
    import urllib.request

    with urllib.request.urlopen(f"{mailpit.base_url}/api/v1/message/{letter['ID']}/headers", timeout=10) as r:
        headers = json.loads(r.read())
    return next((v[0] for k, v in headers.items() if k.lower() == name.lower()), "")


def test_six_letters_russian_named_with_template_header(mailpit, django_capture_on_commit_callbacks):
    """Шесть шаблонов: по-русски, название портала, заголовок X-Portal-Template, статус sent, без паролей и кодов."""
    letters = make_all(django_capture_on_commit_callbacks, mailpit)
    assert set(letters) == TEMPLATES
    forbidden = []
    old, new = letters["password_changed"][2]
    forbidden += [old, new, *letters["second_factor_reset"][2]]
    for template, (letter, user, _) in letters.items():
        text = letter["Text"]
        assert header(mailpit, letter, "X-Portal-Template") == template
        assert re.search("[а-яА-Я]{4,}", letter["Subject"]) and re.search("[а-яА-Я]{4,}", text)
        assert PORTAL_NAME in letter["Subject"] and PORTAL_NAME in text
        assert not re.search(r"\b(Hello|Dear)\b", text)
        assert support.mails(to=user.email, template=template, status="sent").count() == 1
        assert user.full_name in text
        for secret in forbidden:
            assert secret not in text + letter["Subject"], template


def test_links_only_in_invitation_and_reset(mailpit, django_capture_on_commit_callbacks):
    """Ссылка активации — только в приглашении, ссылка восстановления — только в восстановлении; в очереди кода не было."""
    letters = make_all(django_capture_on_commit_callbacks, mailpit)
    invitation, reset = letters["invitation"], letters["password_reset"]
    assert f"{settings.PORTAL_URL}/activate/#{invitation[2]}" in invitation[0]["Text"]
    assert f"{settings.PORTAL_URL}/password/reset/#{reset[2]}" in reset[0]["Text"]
    for template, (letter, _, _) in letters.items():
        if template != "invitation":
            assert "/activate/" not in letter["Text"], template
        if template != "password_reset":
            assert "/password/reset/" not in letter["Text"], template
        if template not in ("invitation", "password_reset"):
            assert not re.search(r"https?://", letter["Text"]), f"{template}: ссылка в письме"


def test_body_not_stored_and_audit_has_status_change(mailpit, django_capture_on_commit_callbacks):
    """Тела письма в базе нет; смена статуса queued → sent каждого письма записана в журнал."""
    letters = make_all(django_capture_on_commit_callbacks, mailpit)
    stored = " ".join(f"{m.to} {m.template} {m.subject} {m.last_error}" for m in model("mail.MailMessage").objects.all())
    for template, (letter, _, _) in letters.items():
        for line in (l.strip() for l in letter["Text"].splitlines() if len(l.strip()) > 40):
            assert line not in stored, template
    events = model("core.AuditEvent").objects.filter(action="mail.status_changed")
    assert events.count() == len(TEMPLATES)
    assert {(e.before["status"], e.after["status"]) for e in events} == {("queued", "sent")}


def test_letter_dies_quietly_when_link_gone(mailpit, django_capture_on_commit_callbacks):
    """Ссылка погашена до отправки: письмо с мёртвой ссылкой не уходит, статус failed, повторов нет."""
    from apps.core.services import links

    user = support.make_employee(state="invited", totp=False)
    with django_capture_on_commit_callbacks(execute=True):
        links.send_invitation(user)
    links.revoke(user)
    deliver()
    message = support.mails(to=user.email).get()
    assert message.status == "failed" and "недействительна" in message.last_error
    assert not mailpit.messages()


def test_delivery_after_smtp_outage_via_scheduler_retry(settings, mailpit, django_capture_on_commit_callbacks):
    """FR-053, NFR-003: сервер почты недоступен — письмо не теряется, повтор ждёт около минуты и доходит после возвращения сервера."""
    from datetime import datetime, timezone

    from rq.job import Job

    from apps.core.services import links
    from tests.support_mail import break_smtp, make_due, mail_jobs, mail_queue, run_scheduler_step

    good = (settings.EMAIL_HOST, settings.EMAIL_PORT)
    break_smtp(settings)
    user = support.make_employee(state="invited", totp=False)
    with django_capture_on_commit_callbacks(execute=True):
        links.send_invitation(user)
    job_id = mail_jobs()[0].id
    deliver()
    message = support.mails(to=user.email).get()
    assert message.status == "queued" and message.attempts == 1 and message.last_error
    job = Job.fetch(job_id, connection=mail_queue().connection)
    due = mail_queue().scheduled_job_registry.get_scheduled_time(job)
    assert 30 < (due - datetime.now(timezone.utc)).total_seconds() <= 65, "первая пауза — около минуты"
    assert not mailpit.messages()
    settings.EMAIL_HOST, settings.EMAIL_PORT = good
    make_due(job)
    run_scheduler_step()
    deliver()
    letter = mailpit.wait_for(user.email, timeout=20)
    assert "/activate/#" in letter["Text"]
    message.refresh_from_db()
    assert message.status == "sent" and message.attempts == 2 and not message.last_error
    assert [a.ok for a in model("mail.MailAttempt").objects.filter(message=message).order_by("id")] == [False, True]
    events = model("core.AuditEvent").objects.filter(action="mail.status_changed", object_id=str(message.pk))
    assert [(e.before["status"], e.after["status"]) for e in events] == [("queued", "sent")], "промежуточная неудача статус не меняет"


def test_job_shape_retry_plan_and_no_secrets_in_queue(django_capture_on_commit_callbacks):
    """Задание: один позиционный аргумент, пустые kwargs, план повторов, on_failure; ни кода ссылки, ни адреса в очереди."""
    from apps.core.services import links
    from tests.support_mail import mail_jobs

    user = support.make_employee(state="invited", totp=False)
    with django_capture_on_commit_callbacks(execute=True):
        links.send_invitation(user)
    code = support.link_code(model("core.OneTimeLink").objects.get(user=user, purpose="activation"))
    job = mail_jobs()[0]
    message = support.mails(to=user.email).get()
    assert (job.args, job.kwargs) == ((message.pk,), {})
    assert job.retries_left == 11 and list(job.retry_intervals) == [60, 300, 900, 3600] + [10800] * 7
    assert job.failure_callback is not None and job.get_status() == "queued"
    assert code not in repr(job.__dict__) and user.email not in repr(job.__dict__)
    r = support.valkey()
    for key in r.keys("*"):
        for value in (r.hgetall(key).values() if r.type(key) == b"hash" else [r.get(key)] if r.type(key) == b"string" else []):
            assert code.encode() not in (value or b""), f"код ссылки в Valkey: {key!r}"
    r.close()
