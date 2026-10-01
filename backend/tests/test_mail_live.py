"""T-115 (живые): письмо доходит до настоящего Mailpit через настоящую очередь на Valkey (FR-008, FR-052, FR-053, NFR-003).

Отдельный процесс рабочего не увидел бы данных теста (транзакция теста откатывается, у crm_app нет
TRUNCATE), поэтому доставляет `SimpleWorker` в процессе теста; процесс рабочего и планировщика
проверяет проход Playwright и T-304. Пауза повтора не ждётся: срок сдвигается в реестре отложенных.
"""
import time

import pytest

from tests import factories, support
from tests.support import model
from tests.support_mail import break_smtp, deliver, make_due, mail_jobs, run_scheduler_step

pytestmark = pytest.mark.django_db


def invite(capture):
    admin = support.logged_in(support.make_admin(), ip="198.51.100.160")
    email = factories.new_email("live")
    with capture(execute=True):
        done = admin.post("/staff/new/", {"email": email, "full_name": "Живой Лев", "position": "Инженер",
                                          "roles": [support.role_by_name(support.STAFF_ROLE).pk]})
    assert done.status_code == 302
    return model("core.User").objects.get(email=email)


def test_invitation_reaches_mailpit_within_one_minute_with_real_worker(mailpit, django_capture_on_commit_callbacks):
    """FR-008, FR-052, NFR-003: приглашение уходит сразу (без паузы) и лежит в Mailpit быстрее минуты; в письме рабочая ссылка активации."""
    started = time.monotonic()
    user = invite(django_capture_on_commit_callbacks)
    job = mail_jobs()[0]
    assert job.get_status() == "queued", "первая попытка без отложенного срока"
    deliver()
    letter = mailpit.wait_for(user.email, timeout=20)
    assert time.monotonic() - started < 60
    code = support.link_code(model("core.OneTimeLink").objects.get(user=user, purpose="activation"))
    assert f"/activate/#{code}" in letter["Text"]
    assert support.mails(to=user.email).get().status == "sent"
    exchange = support.make_client().post("/activate/exchange/", {"code": code})
    assert exchange.status_code == 302, "ссылка из письма работает"


def test_mail_delivered_after_smtp_outage_via_scheduler_retry(settings, mailpit, django_capture_on_commit_callbacks):
    """FR-053, NFR-003: сервер почты недоступен — письмо не теряется, повтор ждёт в планировщике ~1 минуту и доставляется, когда сервер вернулся."""
    from datetime import datetime, timezone

    from rq.job import Job

    from tests.support_mail import mail_queue

    good = (settings.EMAIL_HOST, settings.EMAIL_PORT)
    break_smtp(settings)
    user = invite(django_capture_on_commit_callbacks)
    job_id = mail_jobs()[0].id
    deliver()
    message = support.mails(to=user.email).get()
    assert message.status == "queued" and message.attempts == 1
    job = Job.fetch(job_id, connection=mail_queue().connection)
    due = mail_queue().scheduled_job_registry.get_scheduled_time(job)
    assert 30 < (due - datetime.now(timezone.utc)).total_seconds() <= 65, "первая пауза — около минуты"
    assert not mailpit.messages()
    settings.EMAIL_HOST, settings.EMAIL_PORT = good
    make_due(job)
    run_scheduler_step()
    deliver()
    letter = mailpit.wait_for(user.email, timeout=20)
    assert "Живой" in letter["Text"] or letter["Subject"]
    message.refresh_from_db()
    assert message.status == "sent" and message.attempts == 2
    assert [a.ok for a in model("mail.MailAttempt").objects.filter(message=message).order_by("id")] == [False, True]
