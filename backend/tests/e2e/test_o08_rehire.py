"""T-2144: сценарий 8 — возврат уволенного на работу (FR-123, FR-128)."""
import secrets

from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers, helpers_org
from tests.e2e.helpers_org import (add_members, create_unit, direct_get, direct_post, has_alert, open_structure,
                                   root_id, unique_name)


def _card(page, user_id):
    """Карточка сотрудника `[data-card][data-user-id]` (§ 9.3)."""
    return page.locator(f'[data-card][data-user-id="{user_id}"]')


def _dismiss(page, user_id) -> None:
    """Увольняет из карточки (диалог `dismiss` → подтверждение); ждёт отметку `[data-dismissed-badge]`."""
    page.goto(f"/staff/{user_id}/")
    _card(page, user_id).locator('[data-action="dismiss"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(_card(page, user_id).locator("[data-dismissed-badge]")).to_be_visible()


def _grant_role(page, user_id, role_name) -> None:
    """Личная роль из формы `form[action$="/roles/"]` карточки (срез 001); ждёт ответ POST."""
    page.goto(f"/staff/{user_id}/")
    form = page.locator('form[action$="/roles/"]')
    form.get_by_label(role_name, exact=True).check()
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()


def _personal_roles(page, user_id) -> list:
    """Названия личных ролей в «Профиле» карточки: `[data-roles-group="personal"] [data-role-name]` (§ 9.3)."""
    page.goto(f"/staff/{user_id}/")
    expect(_card(page, user_id)).to_be_visible()
    texts = _card(page, user_id).locator('[data-roles-group="personal"] [data-role-name]').all_inner_texts()
    return sorted(t.strip() for t in texts)


def test_o08_rehire_invitation_new_password_and_second_factor(admin_page, employee, mailpit, new_context):
    """Сценарий 8, п. 1-3: «Вернуть на работу» с подтверждением делает запись «приглашён», отправляет новое
    приглашение, оставляет только роль «Сотрудник ИТ» и ни одного подразделения; возвращённый при активации
    задаёт новый пароль и подключает второй фактор заново — прежние пароль, ключ, резервные коды и устройство
    недействительны; в журнале возврат и отправка приглашения, прежние события сохранены (FR-128)."""
    page = admin_page
    token = secrets.token_hex(3)
    acc = employee(full_name=f"Возврат{token} Пётр Петрович")
    old_password, old_secret, old_codes = acc.password, acc.totp_secret, list(acc.backup_codes)
    open_structure(page)
    unit = create_unit(page, unique_name("Сеть"), kind="department", parent_id=root_id(page))
    add_members(page, unit, [acc.id], q=token, mode="concurrent")
    _grant_role(page, acc.id, "Руководитель")
    _dismiss(page, acc.id)

    # у уволенного — «Вернуть на работу» есть, «Уволить» нет
    card = _card(page, acc.id)
    expect(card.locator('[data-action="rehire"]')).to_have_count(1)
    expect(card.locator('[data-action="dismiss"]')).to_have_count(0)

    # п. 1: диалог называет последствия; подтверждение
    seen = helpers.mail_ids(mailpit, acc.email)
    card.locator('[data-action="rehire"]').click()
    dialog = page.locator('#dialog-root [data-dialog="rehire"]')
    expect(dialog).to_be_visible()
    # перечень последствий обязателен и для `rehire`: CONTRACT-002, доп. 55 (FR-128)
    assert dialog.locator("[data-consequence]").count() >= 1, "диалог возврата не называет последствий"
    helpers.submit(dialog.locator('form[data-form="rehire"]'))
    expect(_card(page, acc.id).locator("[data-dismissed-badge]")).to_have_count(0)

    # п. 1: запись «приглашён», новое приглашение, роль «Сотрудник ИТ», подразделений нет
    page.goto(f"/staff/?q={acc.email}")
    assert helpers.staff_row(page, acc.email).get_attribute("data-state") == "invited"
    invitation = helpers.wait_mail(mailpit, acc.email, "invitation", seen=seen, timeout=60)
    link = helpers.link_in(invitation, "/activate/")
    assert _personal_roles(page, acc.id) == [helpers.STAFF_ROLE]
    expect(_card(page, acc.id).locator('[data-field="units"]')).to_have_attribute("data-empty", "true")

    # п. 2: прежний пароль не пускает (запись снова «приглашён»)
    stale = new_context().new_page()
    helpers.fill_login(stale, acc.email, old_password)
    stale.wait_for_load_state("networkidle")
    assert stale.locator("input[name=code]").count() == 0
    expect(stale.locator("#top-bar")).to_have_count(0)

    # п. 2: активация заново — новый пароль и новый второй фактор
    new_password = factories.new_password()
    secret, codes = helpers.walk_activation(new_context().new_page(), link, new_password)
    assert secret.replace(" ", "") != old_secret.replace(" ", ""), "после возврата показан прежний ключ"
    assert not set(codes) & set(old_codes), "после возврата выданы прежние резервные коды"
    acc.password, acc.totp_secret, acc.backup_codes = new_password, secret, codes

    # п. 2: прежний код из старого приложения и прежний резервный код входа не дают; новые данные входят
    old_login = new_context().new_page()
    helpers.fill_login(old_login, acc.email, new_password)
    old_login.wait_for_url(lambda url: "/login/code/" in url)
    old_login.fill("input[name=code]", helpers.totp_for(old_secret))
    old_login.click("button[type=submit]")
    old_login.wait_for_load_state("networkidle")
    expect(old_login.locator("#top-bar")).to_have_count(0)
    helpers.use_backup_code(old_login, old_codes[0])
    old_login.wait_for_load_state("networkidle")
    expect(old_login.locator("#top-bar")).to_have_count(0)

    # п. 2: прежнее устройство забыто — вход из прежнего контекста снова «новое устройство» (письмо)
    seen = helpers.mail_ids(mailpit, acc.email)
    helpers.sign_in(acc.page, acc)
    helpers.wait_mail(mailpit, acc.email, "new_device", seen=seen, timeout=60)

    # п. 3: журнал — возврат и отправка приглашения, прежние события сохранены
    actions = helpers.audit_actions(page, f"object_id={acc.id}")
    assert actions.count("user.rehired") == 1
    assert actions.count("invitation.sent") == 2, "нет приглашения при возврате"
    for kept in ("user.created", "user.dismissed"):
        assert kept in actions, f"прежнее событие {kept} пропало из журнала"


def test_o08_rehire_not_offered_for_active_and_refused_without_right(admin_page, employee):
    """Сценарий 8, п. 4-5: у неуволенного «Вернуть на работу» не предлагается, прямой запрос отклоняется (200 с
    `[role=alert]`), запись не меняется; сотрудник без права «Управление структурой» не может вернуть уволенного
    (403), уволенный остаётся уволенным (FR-123, FR-128)."""
    page = admin_page
    active = employee()
    dismissed = employee(activate=False)
    plain = employee()
    _dismiss(page, dismissed.id)

    # п. 4: у активного кнопки нет; прямой POST отклонён, состояние прежнее, события возврата нет
    page.goto(f"/staff/{active.id}/")
    expect(_card(page, active.id)).to_be_visible()
    expect(_card(page, active.id).locator('[data-action="rehire"]')).to_have_count(0)
    response = direct_post(page, f"/structure/people/{active.id}/rehire/")
    assert response.status == 200 and has_alert(response), response.status
    page.goto(f"/staff/?q={active.email}")
    assert helpers.staff_row(page, active.email).get_attribute("data-state") == "active"
    assert helpers_org.audit_rows(page, "user.rehired", active.id) == []

    # п. 5: без права — кнопки нет, диалог и возврат закрыты (403), уволенный остался уволенным
    plain.page.goto(f"/staff/{dismissed.id}/")
    expect(_card(plain.page, dismissed.id)).to_be_visible()
    expect(plain.page.locator('[data-action="rehire"]')).to_have_count(0)
    assert direct_get(plain.page, f"/structure/people/{dismissed.id}/rehire/").status == 403
    assert direct_post(plain.page, f"/structure/people/{dismissed.id}/rehire/").status == 403
    page.goto(f"/staff/?state=dismissed&q={dismissed.email}")
    assert helpers.staff_row(page, dismissed.email).get_attribute("data-state") == "dismissed"
    assert helpers_org.audit_rows(page, "user.rehired", dismissed.id) == []
