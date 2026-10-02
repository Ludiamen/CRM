"""T-149: сценарий 18 — восстановление пароля по ссылке из письма (FR-031, FR-032, FR-033, FR-052)."""
import re
import secrets
import time


from tests import factories
from tests.e2e import helpers


def _forgot(page, email: str) -> str:
    """Запрашивает ссылку; возвращает текст ответа портала (одинаковый для любого адреса)."""
    page.goto("/login/")
    page.get_by_text("Забыли пароль?").first.click()
    page.wait_for_url(re.compile(r"/password/forgot/"))
    page.fill("input[name=email]", email)
    page.click("button[type=submit]")
    # ответ — новая страница на том же адресе: ждём его текст, а не загрузку прежней формы
    page.locator("[role=status], [role=alert]").first.wait_for()
    return (helpers.status_text(page) + " " + helpers.alert_text(page)).strip()


def test_s18_forgot_reset_second_factor_still_required_and_mail(admin_page, employee, mailpit, new_context):
    """Сценарий 18, п. 1-8: один и тот же ответ для известного и неизвестного адреса, письмо только
    активной записи (не неактивированной); ссылка меняется на сессию восстановления — адрес без кода;
    слабый пароль отклонён; после смены второй фактор по-прежнему нужен; сессии на других устройствах закрыты,
    письмо о смене ушло, ссылка больше не работает, более ранняя ссылка мертва; в журнале запрос, смена и
    закрытие сессий без кода и паролей (FR-031, FR-032, FR-033, FR-052)."""
    acc = employee()
    invited = employee(activate=False)
    other_session = acc.page
    page = new_context().new_page()

    # п. 1 и 7: ответ одинаков; письмо — только активной записи
    known = _forgot(page, acc.email)
    unknown = _forgot(page, factories.new_email("nobody"))
    not_active = _forgot(page, invited.email)
    assert known and known == unknown == not_active, "ответ различает адреса"
    first = helpers.wait_mail(mailpit, acc.email, "password_reset", timeout=60)
    first_link = helpers.link_in(first, "/password/reset/")
    assert helpers.no_mail(mailpit, invited.email, "password_reset", wait=2.0), "письмо ушло неактивной записи"
    assert re.search(r"[А-Яа-я]", first["Subject"] + first["Text"])

    # п. 6: новый запрос — прежняя ссылка недействительна
    seen = helpers.mail_ids(mailpit, acc.email)
    _forgot(page, acc.email)
    second = helpers.wait_mail(mailpit, acc.email, "password_reset", seen=seen, timeout=60)
    second_link = helpers.link_in(second, "/password/reset/")
    old = new_context().new_page()
    old.goto(first_link)
    old.wait_for_load_state("networkidle")
    assert re.search(r"недействит", helpers.alert_text(old), re.I)
    assert old.locator("input[name=password1]").count() == 0

    # п. 2-3: ссылка → страница нового пароля без кода в адресе; слабый пароль отклонён
    page.goto(second_link)
    page.wait_for_url(re.compile(r"/password/reset/"))
    assert "#" not in page.url and helpers.code_of(second_link) not in page.url
    weak = "Aa1!" + secrets.token_hex(2)
    page.fill("input[name=password1]", weak)
    page.fill("input[name=password2]", weak)
    page.click("button[type=submit]")
    assert "символ" in helpers.alert_text(page)
    seen = helpers.mail_ids(mailpit, acc.email)
    new_password = factories.new_password()
    page.fill("input[name=password1]", new_password)
    page.fill("input[name=password2]", new_password)
    page.click("button[type=submit]")
    page.wait_for_url(re.compile(r"/login/"))

    # п. 5: письмо о смене, другие сессии закрыты, ссылка использована
    helpers.wait_mail(mailpit, acc.email, "password_changed", seen=seen, timeout=60)
    other_session.goto("/me/security/")
    assert "/login/" in other_session.url, "сессия на другом устройстве осталась"
    again = new_context().new_page()
    again.goto(second_link)
    again.wait_for_load_state("networkidle")
    assert again.locator("input[name=password1]").count() == 0

    # п. 4: только паролем войти нельзя — нужен второй фактор
    helpers.fill_login(page, acc.email, new_password)
    page.wait_for_url(re.compile(r"/login/code/"))
    assert page.locator("#top-bar").count() == 0
    page.goto("/me/")
    assert "/login/" in page.url
    acc.password = new_password
    helpers.sign_in(new_context().new_page(), acc)

    # п. 8: журнал
    actions = helpers.audit_actions(admin_page, f"object_id={acc.id}")
    for needed in ("password.reset_requested", "password.changed", "sessions.closed"):
        assert needed in actions, f"в журнале нет {needed}"
    journal = helpers.audit_text(admin_page)
    secrets_ = (helpers.code_of(first_link), helpers.code_of(second_link), new_password, weak)
    assert not [s for s in secrets_ if s in journal], "в журнале код ссылки или пароль"


def test_s18_rate_limited_requests_create_no_extra_mail(employee, mailpit, new_context):
    """Сценарий 18, п. 9 (FR-031): серия запросов на один адрес — писем не больше предела (3 в час), ответ
    остаётся прежним."""
    acc = employee()
    page = new_context().new_page()
    seen = helpers.mail_ids(mailpit, acc.email)
    answers = {_forgot(page, acc.email) for _ in range(6)}
    assert len(answers) == 1 and "" not in answers, "ответ портала меняется при превышении предела"
    helpers.wait_mail(mailpit, acc.email, "password_reset", seen=seen, timeout=60)
    time.sleep(5)  # лишние письма, если они есть, успели бы прийти
    sent = [m for m in mailpit.messages()
            if m["ID"] not in seen and any(a["Address"].lower() == acc.email.lower() for a in m["To"])
            and helpers.template_of(mailpit, m["ID"]) == "password_reset"]
    assert 1 <= len(sent) <= 3, f"писем восстановления {len(sent)}: предел 3 в час"
