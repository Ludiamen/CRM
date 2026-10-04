"""T-140: сценарий 2 — администратор заводит сотрудника и отправляет приглашение
(FR-001, FR-002, FR-004, FR-008, FR-009, FR-010, FR-052).

П. 3 приёмки (почтовый сервер недоступен, письмо ждёт в очереди) здесь не проходится:
для этого пришлось бы останавливать контейнер Mailpit; его проверяют test_mail и
test_mail_live на уровне сервера.
"""
import re
import time

from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers


def test_s02_admin_creates_employee_and_invitation_arrives(admin_page, mailpit, employee, new_context):
    """Сценарий 2, п. 1, 2, 4, 5: запись в списке со статусом «приглашён», письмо за минуту;
    повторная почта отклонена; в журнале создание и приглашение; рядовой сотрудник форму не открывает
    и кнопки создания не видит (раздел «Сотрудники» в меню у него есть)."""
    email = factories.new_email("emp")
    seen = helpers.mail_ids(mailpit, email)
    started = time.monotonic()
    user_id = helpers.create_employee(admin_page, email, full_name="Петров Пётр Петрович",
                                      position="Системный администратор", phone="+7 900 111-22-33")
    mail = helpers.wait_mail(mailpit, email, "invitation", seen=seen, timeout=60)
    assert time.monotonic() - started < 60, "письмо-приглашение пришло позже минуты"
    assert re.search(r"[А-Яа-я]", mail["Subject"] + mail["Text"])
    mail_link = helpers.link_in(mail, "/activate/")

    # п. 1: в списке со статусом «приглашён»
    admin_page.goto("/staff/")
    row = helpers.staff_row(admin_page, email)
    expect(row).to_have_count(1)
    assert row.get_attribute("data-state") == "invited"

    # карточка показывает ту же ссылку и состояние письма
    admin_page.goto(f"/staff/{user_id}/")
    helpers.open_security_tab(admin_page)
    card_link = admin_page.locator("[data-invitation-link]").first.inner_text().strip()
    assert helpers.code_of(card_link) == helpers.code_of(mail_link), "ссылка в карточке не та, что в письме"
    expect(admin_page.locator("[data-mail-status]").first).to_be_visible()

    # п. 2: повторная почта — отказ, запись не создаётся
    admin_page.goto("/staff/new/")
    form = admin_page.locator('form[action="/staff/new/"]')
    form.locator("[name=email]").fill(email)
    form.locator("[name=full_name]").fill("Двойник Двойников")
    form.locator("[name=position]").fill("Инженер")
    form.get_by_label(helpers.STAFF_ROLE, exact=True).check()
    form.locator("button[type=submit]").click()
    expect(admin_page.locator("[role=alert]").first).to_be_visible()
    assert "/staff/new/" in admin_page.url
    admin_page.goto("/staff/")
    expect(helpers.staff_row(admin_page, email)).to_have_count(1)

    # п. 4: в журнале — создание записи и отправка приглашения
    actions = helpers.audit_actions(admin_page)
    assert "user.created" in actions and "invitation.sent" in actions

    # п. 5: сотрудник без права управления учётными записями: «Сотрудники» в меню есть (FR-118),
    # кнопки создания нет, а форма создания закрыта
    plain = employee()
    page = plain.page
    response = page.goto("/staff/new/")
    assert response is not None and response.status == 403
    page.goto("/me/")
    expect(page.locator('#main-menu a[href="/staff/"]')).to_have_count(1)
    response = page.goto("/staff/")
    assert response is not None and response.status == 200, "список сотрудников должен открыться (не 403/500)"
    expect(page.locator('a[href="/staff/new/"]')).to_have_count(0)


def test_s02_resend_invitation_old_link_dead_and_form_ux11(admin_page, mailpit, new_context):
    """Сценарий 8, п. 4 и UX-11: форма короткая (телефон не обязателен), «Отправить приглашение заново»
    выдаёт новую ссылку и письмо, прежняя ссылка не работает, в журнале — повторная отправка (FR-010)."""
    admin_page.goto("/staff/new/")
    form = admin_page.locator('form[action="/staff/new/"]')
    for name in ("email", "full_name", "position", "phone"):
        expect(form.locator(f"[name={name}]")).to_have_count(1)
    assert form.locator("[name=phone]").get_attribute("required") is None, "телефон должен быть по желанию"
    expect(form.locator("button[type=submit]")).to_contain_text("Создать и пригласить")
    assert form.locator("input:not([type=hidden]):not([type=checkbox]), textarea, select").count() <= 6, \
        "форма не короткая"

    email = factories.new_email("emp")
    user_id = helpers.create_employee(admin_page, email)
    first = helpers.wait_mail(mailpit, email, "invitation")
    first_link = helpers.link_in(first, "/activate/")
    seen = helpers.mail_ids(mailpit, email)

    admin_page.goto(f"/staff/{user_id}/")
    helpers.open_security_tab(admin_page)
    helpers.submit(admin_page.locator('form[action$="/invite/"]'))
    second = helpers.wait_mail(mailpit, email, "invitation", seen=seen)
    second_link = helpers.link_in(second, "/activate/")
    assert helpers.code_of(first_link) != helpers.code_of(second_link)

    context = new_context()
    page = context.new_page()
    page.goto(first_link)
    page.wait_for_load_state("networkidle")
    assert "/activate/profile/" not in page.url, "прежняя ссылка после повторной отправки ещё работает"
    expect(page.locator("[role=alert]")).to_be_visible()
    helpers.open_activation_link(page, second_link)

    actions = helpers.audit_actions(admin_page, f"object_id={user_id}")
    assert actions.count("invitation.sent") == 2, "в журнале нет повторной отправки приглашения"
