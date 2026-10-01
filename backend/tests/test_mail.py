"""T-115: исходящая почта на RQ и Mailpit (FR-044, FR-052…055, NFR-003, NFR-010). Сценарии 2, 5, 7, 9, 16, 18.

Доставку выполняет `SimpleWorker` (tests/support_mail.py): в процессе теста и в его транзакции, на
настоящем Valkey и настоящем SMTP Mailpit. Сбой SMTP — адрес без слушателя.
"""
import re
from unittest import mock

import pytest
from django.utils.html import escape

from tests import factories, support
from tests.support import model
from tests.support_mail import break_smtp, deliver, mail_jobs, mail_queue

pytestmark = pytest.mark.django_db

PORTAL_NAME = "Портал для писем"


def six_letters(capture, mailpit):
    """Запускает по настоящему сценарию все шесть писем и доставляет их; возвращает {шаблон: (письмо Mailpit, данные)}."""
    model("core.PortalSettings").objects.update(name=PORTAL_NAME)
    admin_user = support.make_admin()
    admin = support.logged_in(admin_user, ip="198.51.100.130")
    staff_role = support.role_by_name(support.STAFF_ROLE)
    data = {}
    with capture(execute=True):
        email = factories.new_email("invitee")
        admin.post("/staff/new/", {"email": email, "full_name": "Письмов Пётр", "position": "Инженер", "roles": [staff_role.pk]})
        invitee = model("core.User").objects.get(email=email)
        data["invitation"] = (invitee, support.link_code(model("core.OneTimeLink").objects.get(user=invitee, purpose="activation")))
        forgetful = support.make_employee()
        support.make_client(ip="198.51.100.131").post("/password/forgot/", {"email": forgetful.email})
        data["password_reset"] = (forgetful, support.link_code(model("core.OneTimeLink").objects.get(user=forgetful, purpose="reset")))
        locked = support.make_employee()
        for _ in range(5):
            support.make_client(ip="198.51.100.132").post("/login/", {"email": locked.email, "password": factories.new_password()})
        data["account_locked"] = (locked, None)
        roamer = support.make_employee()
        support.logged_in(roamer, ip="198.51.100.133")
        support.logged_in(roamer, ip="198.51.100.134", ua=support.CHROME_UA)
        data["new_device"] = (roamer, None)
        from apps.core.services.second_factor import issue_backup_codes

        lost = support.make_employee()
        lost_codes = issue_backup_codes(lost)
        admin.post(f"/staff/{lost.pk}/reset-2fa/")
        data["second_factor_reset"] = (lost, lost_codes)
        changer = support.make_employee()
        old = changer.test_password
        new = factories.new_password()
        client = support.logged_in(changer, ip="198.51.100.135")
        client.post("/me/security/password/", {"current_password": old, "password1": new, "password2": new})
        data["password_changed"] = (changer, (old, new))
    deliver()
    return {template: (mailpit.wait_for(user.email), user, extra) for template, (user, extra) in data.items()}


def test_six_letter_templates_in_russian_with_portal_name(mailpit, django_capture_on_commit_callbacks):
    """FR-052, FR-054, NFR-010: шесть писем среза, все по-русски, с названием портала из настроек."""
    letters = six_letters(django_capture_on_commit_callbacks, mailpit)
    assert set(letters) == {"invitation", "password_reset", "account_locked", "new_device", "second_factor_reset", "password_changed"}
    for template, (letter, user, _) in letters.items():
        text = letter["Text"]
        assert letter["Subject"].strip() and re.search("[а-яА-Я]{4,}", letter["Subject"] + text), template
        assert PORTAL_NAME in text or PORTAL_NAME in letter["Subject"], f"{template}: нет названия портала"
        assert not re.search(r"\b(Hello|Dear|Your account)\b", text), f"{template}: английский текст"
        assert support.mails(to=user.email, template=template, status="sent").count() == 1


def test_send_creates_message_and_enqueues_after_commit_with_id_only(django_capture_on_commit_callbacks):
    """FR-052, FR-053: письмо создаётся до очереди, задание ставится по фиксации транзакции, в него уходит один номер."""
    user = support.make_employee()
    client = support.logged_in(user, ip="198.51.100.136")
    new = factories.new_password()
    before = mail_queue().count
    with django_capture_on_commit_callbacks(execute=False) as callbacks:
        done = client.post("/me/security/password/", {"current_password": user.test_password, "password1": new, "password2": new})
    assert done.status_code == 302
    message = support.mails(to=user.email, template="password_changed").get()
    assert message.status == "queued" and mail_queue().count == before, "до фиксации транзакции очередь пуста"
    for callback in callbacks:
        callback()
    jobs = mail_jobs()
    assert [(j.args, j.kwargs) for j in jobs] == [((message.pk,), {})]
    assert new not in repr(jobs[0].__dict__) and user.email not in repr((jobs[0].args, jobs[0].kwargs))


def test_retry_intervals_1_5_15_60_minutes_then_7_times_3_hours(django_capture_on_commit_callbacks):
    """FR-053, NFR-003: Retry(max=11) с паузами 1, 5, 15, 60 минут, затем 7 раз по 3 часа."""
    support.make_employee()
    user = support.make_employee()
    with django_capture_on_commit_callbacks(execute=True):
        support.logged_in(user, ip="198.51.100.137")
        support.logged_in(user, ip="198.51.100.138", ua=support.CHROME_UA)
    job = mail_jobs()[0]
    assert job.retries_left == 11
    assert list(job.retry_intervals) == [60, 300, 900, 3600] + [10800] * 7
    assert job.failure_callback is not None, "после последней неудачи — обработчик on_failure"


def test_on_failure_not_called_after_intermediate_failures(settings, django_capture_on_commit_callbacks):
    """FR-053: промежуточная неудача оставляет письмо в очереди (повтор отложен); `failed` — только после последней попытки."""
    from rq.job import Job

    break_smtp(settings)
    user = support.make_employee()
    with django_capture_on_commit_callbacks(execute=True):
        support.logged_in(user, ip="198.51.100.139")
        support.logged_in(user, ip="198.51.100.140", ua=support.CHROME_UA)
    message = support.mails(to=user.email, template="new_device").get()
    job = mail_jobs()[0]
    deliver()
    message.refresh_from_db()
    assert message.status == "queued" and message.attempts == 1 and message.last_error
    job = Job.fetch(job.id, connection=mail_queue().connection)
    assert job.get_status() == "scheduled", "повтор ждёт паузу в планировщике"
    job.retries_left = 0
    job.save()
    mail_queue().enqueue_job(job)
    deliver()
    message.refresh_from_db()
    assert message.status == "failed" and message.attempts == 2


def test_each_attempt_writes_mailattempt_visible_in_mail_log(settings, django_capture_on_commit_callbacks):
    """FR-053: каждая попытка — запись MailAttempt (результат, ошибка без секретов); журнал доставки виден администратору с settings.portal."""
    Attempt = model("mail.MailAttempt")
    user = support.make_employee()
    break_smtp(settings)
    settings.EMAIL_HOST_PASSWORD = factories.new_password()
    with django_capture_on_commit_callbacks(execute=True):
        support.logged_in(user, ip="198.51.100.141")
        support.logged_in(user, ip="198.51.100.142", ua=support.CHROME_UA)
    deliver()
    failed = Attempt.objects.get()
    assert failed.ok is False and failed.error and settings.EMAIL_HOST_PASSWORD not in failed.error
    viewer = support.logged_in(support.make_with_permissions("settings.portal"), ip="198.51.100.143")
    page = viewer.get("/settings/mail-log/").content.decode()
    assert user.email in page and "new_device" in page or "устройств" in page.lower()
    assert escape(failed.error) in page and settings.EMAIL_HOST_PASSWORD not in page
    assert support.logged_in(support.make_employee(), ip="198.51.100.144").get("/settings/mail-log/").status_code == 403


def test_mail_body_not_stored_in_database(mailpit, django_capture_on_commit_callbacks):
    """FR-054: тело письма в базе не хранится: у MailMessage и MailAttempt нет полей тела, значений-фрагментов письма нет в таблицах почты."""
    letters = six_letters(django_capture_on_commit_callbacks, mailpit)
    for label in ("mail.MailMessage", "mail.MailAttempt"):
        names = {f.name for f in model(label)._meta.get_fields()}
        assert not names & {"body", "text", "html", "content", "message_body", "payload"}, f"{label}: {names}"
    stored = " ".join(str(v) for m in model("mail.MailMessage").objects.all() for v in (m.to, m.template, m.subject, m.last_error))
    stored += " ".join(a.error for a in model("mail.MailAttempt").objects.all())
    for template, (letter, user, extra) in letters.items():
        for line in (l.strip() for l in letter["Text"].splitlines() if len(l.strip()) > 40):
            assert line not in stored, f"{template}: строка письма лежит в базе"
    assert letters["invitation"][2] not in stored


def test_no_passwords_or_codes_in_any_letter(mailpit, django_capture_on_commit_callbacks):
    """FR-054: в письмах нет паролей, кодов второго фактора и резервных кодов."""
    letters = six_letters(django_capture_on_commit_callbacks, mailpit)
    old, new = letters["password_changed"][2]
    user = letters["second_factor_reset"][1]
    forbidden = [old, new, user.test_password, factories.totp_code(user.test_totp_key), *letters["second_factor_reset"][2]]
    for template, (letter, _, _) in letters.items():
        body = letter["Text"] + letter.get("HTML", "")
        for secret in forbidden:
            assert secret not in body, f"{template}: секрет в письме"
        assert not re.search(r"(?i)резервн\w+ код\w*\s*[:：]\s*[A-Za-z0-9-]{10,}", body)


def test_links_only_in_invitation_and_reset_letters(mailpit, django_capture_on_commit_callbacks):
    """FR-054, секреты-в-url: ссылка активации — только в приглашении, ссылка восстановления — только в письме восстановления."""
    from django.conf import settings

    letters = six_letters(django_capture_on_commit_callbacks, mailpit)
    invitation, reset = letters["invitation"], letters["password_reset"]
    assert f"{settings.PORTAL_URL}/activate/#{invitation[2]}" in invitation[0]["Text"]
    assert f"{settings.PORTAL_URL}/password/reset/#{reset[2]}" in reset[0]["Text"]
    for template, (letter, _, extra) in letters.items():
        body = letter["Text"] + letter.get("HTML", "")
        if template != "invitation":
            assert "/activate/" not in body, f"{template}: ссылка активации"
        if template != "password_reset":
            assert "/password/reset/" not in body, f"{template}: ссылка восстановления"
        if template not in ("invitation", "password_reset"):
            assert not re.search(r"#[A-Za-z0-9_-]{30,}", body), f"{template}: код в адресе"


def test_smtp_failure_does_not_break_user_create_login_or_password_change(settings, django_capture_on_commit_callbacks):
    """FR-053, NFR-003: при недоступном SMTP создание записи, вход и смена пароля работают, письма ждут в очереди."""
    break_smtp(settings)
    admin_user = support.make_admin()
    admin = support.logged_in(admin_user, ip="198.51.100.145")
    with django_capture_on_commit_callbacks(execute=True):
        email = factories.new_email("outage")
        done = admin.post("/staff/new/", {"email": email, "full_name": "Сбойный Сергей", "position": "Инженер",
                                          "roles": [support.role_by_name(support.STAFF_ROLE).pk]})
        user = support.make_employee()
        support.logged_in(user, ip="198.51.100.146")
        other = support.logged_in(user, ip="198.51.100.147", ua=support.CHROME_UA)
        new = factories.new_password()
        changed = other.post("/me/security/password/", {"current_password": user.test_password, "password1": new, "password2": new})
    assert done.status_code == 302 and model("core.User").objects.filter(email=email).exists()
    assert changed.status_code == 302 and other.get("/me/").status_code == 200
    deliver()
    assert not support.mails(status="sent").exists() and support.mails(status="queued").count() >= 3
    assert other.get("/me/").status_code == 200


def test_delivery_status_changes_written_to_audit(settings, mailpit, django_capture_on_commit_callbacks):
    """FR-044, FR-053: смена статуса письма (queued → sent и queued → failed) пишется в журнал."""
    user = support.make_employee()
    with django_capture_on_commit_callbacks(execute=True):
        support.logged_in(user, ip="198.51.100.148")
        support.logged_in(user, ip="198.51.100.149", ua=support.CHROME_UA)
    message = support.mails(to=user.email).get()
    deliver()
    events = model("core.AuditEvent").objects.filter(action="mail.status_changed", object_id=str(message.pk))
    assert [(e.before["status"], e.after["status"]) for e in events] == [("queued", "sent")]
    break_smtp(settings)
    other = support.make_employee()
    with django_capture_on_commit_callbacks(execute=True):
        support.logged_in(other, ip="198.51.100.150")
        support.logged_in(other, ip="198.51.100.151", ua=support.CHROME_UA)
    failing = support.mails(to=other.email).get()
    job = mail_jobs()[0]
    job.retries_left = 0
    job.save()
    deliver()
    failed = model("core.AuditEvent").objects.get(action="mail.status_changed", object_id=str(failing.pk))
    assert failed.before["status"] == "queued" and failed.after["status"] == "failed"


@pytest.mark.parametrize("mode,tls,ssl", [("starttls", True, False), ("ssl", False, True), ("none", False, False)])
def test_smtp_security_modes_starttls_ssl_none(mode, tls, ssl, settings, django_capture_on_commit_callbacks):
    """FR-055: режимы SMTP starttls / ssl / none выбирают соединение: STARTTLS, SMTP_SSL или обычное."""
    settings.EMAIL_USE_TLS, settings.EMAIL_USE_SSL = tls, ssl
    settings.EMAIL_HOST, settings.EMAIL_PORT = "smtp.example.invalid", 2525
    user = support.make_employee()
    with django_capture_on_commit_callbacks(execute=True):
        support.logged_in(user, ip="198.51.100.152")
        support.logged_in(user, ip="198.51.100.153", ua=support.CHROME_UA)
    with mock.patch("smtplib.SMTP") as plain, mock.patch("smtplib.SMTP_SSL") as secure:
        deliver()
    if ssl:
        assert secure.called and not plain.called
        assert secure.call_args.args[:2] == ("smtp.example.invalid", 2525)
    else:
        assert plain.called and not secure.called
        assert plain.return_value.starttls.called is tls
    assert support.mails(to=user.email).get().status == "sent"
