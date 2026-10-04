"""T-2144: сценарий 7 — увольнение сотрудника (FR-123, FR-124, FR-125, FR-126, FR-127)."""
import re
import secrets

from playwright.sync_api import expect

from tests import factories
from tests.e2e import helpers, helpers_org
from tests.e2e.helpers_org import (add_members, create_unit, direct_post, member_menu, member_row, open_structure,
                                   root_id, set_marks, unique_name)


def _card(page, user_id):
    """Карточка сотрудника `[data-card][data-user-id]` (§ 9.3)."""
    return page.locator(f'[data-card][data-user-id="{user_id}"]')


def _open_dismiss_dialog(page, user_id):
    """Открывает `/staff/<id>/`, нажимает `[data-action="dismiss"]` карточки; возвращает диалог в `#dialog-root`."""
    page.goto(f"/staff/{user_id}/")
    _card(page, user_id).locator('[data-action="dismiss"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    return dialog


def _dismiss(page, user_id) -> None:
    """Увольняет из карточки: диалог → подтверждение; ждёт отметку `[data-dismissed-badge]` рядом с ФИО."""
    dialog = _open_dismiss_dialog(page, user_id)
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    expect(_card(page, user_id).locator("[data-dismissed-badge]")).to_be_visible()


def _try_dismiss(page, user_id) -> str:
    """Увольнение, которое должно быть отклонено: возвращает текст `[role=alert]` (ответ 200, § 8)."""
    dialog = _open_dismiss_dialog(page, user_id)
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    # `.first`: напоминание календаря размечено role="status" (доп. 56), ложного [role=alert] на странице нет
    expect(page.locator("[role=alert]").first).to_be_visible()
    return helpers.alert_text(page)


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


def _user_id(page, email) -> str:
    """Номер записи по почте: строка `tr[data-user-email][data-user-id]` списка с поиском `q`."""
    page.goto(f"/staff/?q={email}")
    row = helpers.staff_row(page, email)
    expect(row).to_have_count(1)
    return row.get_attribute("data-user-id")


def _forgot(page, email: str) -> None:
    """Запрос ссылки восстановления пароля (`/password/forgot/`, срез 001); ждёт ответ портала."""
    page.goto("/password/forgot/")
    page.fill("input[name=email]", email)
    page.click("button[type=submit]")
    page.locator("[role=status], [role=alert]").first.wait_for()


def _create_role(page, name: str, permissions) -> None:
    """Новая роль формой `/roles/new/` (срез 001)."""
    page.goto("/roles/new/")
    form = page.locator('form[action="/roles/new/"]')
    form.locator("[name=name]").fill(name)
    for code in permissions:
        form.locator(f'input[name=permissions][value="{code}"]').check()
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()


def test_o07_two_sessions_closed_login_and_links_refused(admin_page, employee, mailpit, new_context):
    """Сценарий 7, п. 1: у активного сотрудника две открытые сессии; после увольнения обе закрыты сразу, вход
    с верными данными отклонён тем же сообщением, что и неверный пароль, ссылка активации приглашённого и ссылка
    восстановления пароля, выданная до увольнения, не работают (FR-125)."""
    acc = employee()
    invited = employee(activate=False)
    first = acc.page
    second = new_context().new_page()
    helpers.sign_in(second, acc)
    for session in (first, second):
        session.goto("/me/")
        expect(session.locator("#top-bar")).to_be_visible()

    # ссылка восстановления запрошена до увольнения
    asker = new_context().new_page()
    _forgot(asker, acc.email)
    recovery_link = helpers.link_in(helpers.wait_mail(mailpit, acc.email, "password_reset", timeout=60),
                                    "/password/reset/")
    seen = helpers.mail_ids(mailpit, acc.email)

    _dismiss(admin_page, acc.id)
    _dismiss(admin_page, invited.id)

    # п. 1: обе сессии закрыты сразу
    for session in (first, second):
        session.goto("/me/")
        assert "/login/" in session.url, "сессия уволенного жива"
        expect(session.locator("#top-bar")).to_have_count(0)

    # п. 1: вход невозможен; сообщение неотличимо от неверного пароля, на второй шаг не пускает
    page = new_context().new_page()
    helpers.fill_login(page, acc.email, factories.new_password())
    page.wait_for_load_state("networkidle")
    generic = helpers.alert_text(page)
    helpers.fill_login(page, acc.email, acc.password)
    page.wait_for_load_state("networkidle")
    assert generic, "при неверном пароле нет сообщения"
    assert page.locator("input[name=code]").count() == 0, "уволенного пустило на ввод кода"
    assert helpers.alert_text(page) == generic
    expect(page.locator("#top-bar")).to_have_count(0)

    # п. 1: ссылка активации уволенного приглашённого не открывает мастер
    dead = new_context().new_page()
    dead.goto(invited.link)
    dead.wait_for_load_state("networkidle")
    assert "/activate/profile/" not in dead.url, "ссылка активации уволенного открыла мастер"

    # п. 1: ссылка восстановления, выданная до увольнения, пароль задать не даёт
    reset = new_context().new_page()
    reset.goto(recovery_link)
    reset.wait_for_load_state("networkidle")
    expect(reset.locator("input[name=password1]")).to_have_count(0)

    # новый запрос восстановления для уволенного письма не рождает
    _forgot(asker, acc.email)
    assert helpers.no_mail(mailpit, acc.email, "password_reset", seen=seen, wait=4.0), \
        "уволенному ушла ссылка восстановления"


def test_o07_units_marks_roles_removed_dismissed_preset_and_marked_journal(admin_page, employee, stand_admin):
    """Сценарий 7, п. 2-5: участник двух узлов и руководитель одного, увольняемый из меню «…» в карточке узла, ушёл
    из обоих узлов, узел остался без руководителя, личные роли сняты; в «Уволены» он виден, карточка со всеми
    прежними полями, подразделения и роли пусты, состояние показывает отметка «уволен»; в предложениях людей его
    нет; журнал подписывает его прежние действия «(уволен)», в истории входов то же, у события увольнения —
    кто уволил (FR-125, FR-127)."""
    page = admin_page
    token = secrets.token_hex(3)
    person = employee(full_name=f"Увол{token} Пётр Петрович")
    candidate = employee(activate=False, full_name=f"Канд{token} Анна Андреевна")
    colleague = employee()
    open_structure(page)
    rid = root_id(page)
    unit_a = create_unit(page, unique_name("Сеть"), kind="department", parent_id=rid)
    unit_b = create_unit(page, unique_name("Поддержка"), kind="department", parent_id=rid)
    add_members(page, unit_a, [person.id], q=token, mode="concurrent")
    add_members(page, unit_b, [person.id], q=token, mode="concurrent")
    set_marks(page, unit_a, "heads", [person.id])
    _grant_role(page, person.id, "Руководитель")
    assert _personal_roles(page, person.id) == sorted(["Руководитель", helpers.STAFF_ROLE])

    # п. 2: увольнение из меню «…» в карточке узла; в форме диалога — путь страницы, откуда он открыт
    open_structure(page, unit_a)
    expect(member_row(page, person.id, "heads")).to_have_count(1)
    member_menu(page, person.id).locator('[data-menu-item="dismiss"]').click()
    dialog = page.locator('#dialog-root [data-dialog="dismiss"]')
    expect(dialog).to_be_visible()
    assert f"/structure/{unit_a}/" in dialog.locator("input[name=next]").input_value()
    helpers.submit(dialog.locator('form[data-form="dismiss"]'))
    # страница остаётся на том же адресе: ответ ждёт следующая проверка (to_have_count(0) повторяется до срока)

    # п. 2: ушёл из обоих узлов, узел остался без руководителя
    expect(member_row(page, person.id)).to_have_count(0)
    expect(page.locator('[data-unit-card] [data-section="heads"] [data-member]')).to_have_count(0)
    open_structure(page, unit_b)
    expect(member_row(page, person.id)).to_have_count(0)

    # п. 2-3: карточка открывается со всеми прежними полями; подразделения и личные роли пусты
    page.goto(f"/staff/{person.id}/")
    card = _card(page, person.id)
    expect(card.locator("[data-dismissed-badge]")).to_contain_text("уволен")
    expect(card.locator('[data-field="state"]')).to_have_count(0)
    expect(card.locator('[data-field="full_name"]')).to_contain_text(f"Увол{token}")
    expect(card.locator('[data-field="position"]')).to_contain_text("Инженер")
    expect(card.locator('[data-field="email"]')).to_contain_text(person.email)
    expect(card.locator('[data-field="phone"]')).to_contain_text("900")
    units = card.locator('[data-field="units"]')
    expect(units).to_have_attribute("data-empty", "true")
    expect(units).to_contain_text("не заполнено")
    assert _personal_roles(page, person.id) == [], "личные роли уволенного не сняты"

    # п. 3: в списке «В компании» его нет, пресет «Уволены» его показывает
    page.goto(f"/staff/?q={person.email}")
    expect(helpers.staff_row(page, person.email)).to_have_count(0)
    page.goto("/staff/")
    page.locator('a[data-preset="dismissed"]').click()
    expect(page.locator('a[data-preset="dismissed"]')).to_have_attribute("aria-current", "true")
    page.goto(f"/staff/?state=dismissed&q={person.email}")
    row = helpers.staff_row(page, person.email)
    expect(row).to_have_count(1)
    assert row.get_attribute("data-state") == "dismissed"
    row.locator('[data-cell="name"] a').click()
    page.wait_for_url(re.compile(rf"/staff/{person.id}/"))
    expect(_card(page, person.id).locator("[data-dismissed-badge]")).to_be_visible()

    # п. 3 (FR-127): коллеге уволенный виден в «Уволены»; служебного состояния нет, есть пометка строки
    colleague.page.goto(f"/staff/?state=dismissed&q={person.email}")
    crow = helpers.staff_row(colleague.page, person.email)
    expect(crow).to_have_count(1)
    assert crow.get_attribute("data-dismissed") == "true"
    assert crow.get_attribute("data-state") is None, "коллега видит служебное состояние"

    # п. 4: уволенного нет в подсказках людей (добавление в узел), живой кандидат с тем же запросом есть
    page.goto(f"/structure/{unit_a}/")
    details = page.locator('#unit-card details[data-action="members-add"]')
    expect(details).to_have_count(1)
    details.locator("summary").first.click()
    form = details.locator('form[data-form="members-add"]')
    with page.expect_response(lambda r: "/candidates/" in r.url and r.status == 200):
        form.locator("input[name=q]").fill(token)
    expect(form.locator(f'label[data-candidate][data-user-id="{candidate.id}"]')).to_have_count(1)
    expect(form.locator(f'label[data-candidate][data-user-id="{person.id}"]')).to_have_count(0)

    # п. 5: журнал подписывает прежние действия уволенного «(уволен)»
    page.goto(f"/audit/?user={person.id}")
    rows = page.locator("tr[data-event-id]")
    assert rows.count() >= 1, "у активированного сотрудника нет событий в журнале"
    for text in rows.all_inner_texts():
        assert "(уволен)" in text, "действие уволенного в журнале без пометки"
    # п. 5: и история входов (`[data-person-name]`, доп. 12)
    page.goto(f"/staff/{person.id}/logins/")
    name = " ".join(page.locator("[data-person-name]").first.inner_text().split())
    assert name == f"{person.full_name} (уволен)"

    # п. 2: журнал — кто уволил и вынос из каждого узла
    dismissed = helpers_org.audit_rows(page, "user.dismissed", person.id)
    assert len(dismissed) == 1
    assert stand_admin.email in dismissed[0] or stand_admin.full_name in dismissed[0], "не указан, кто уволил"
    assert len(helpers_org.audit_rows(page, "membership.removed", person.id)) == 2


def test_o07_cancel_self_last_admin_and_no_right_refused(admin_page, employee, stand_admin):
    """Сценарий 7, п. 6-8, 10: «Отмена» в диалоге ничего не меняет и запросов не шлёт; администратор не может
    уволить себя; единственного администратора не может уволить даже обладатель права «Управление структурой»;
    сотрудник без этого права получает отказ (403), кнопок у него нет (FR-123, FR-125, FR-126).
    Условие на входе: первый круг после сброса; роль администратора в круге раньше o07 никто не назначает (RE-1d)."""
    page = admin_page
    target = employee()
    plain = employee()
    admin_id = _user_id(page, stand_admin.email)

    # п. 10: диалог называет последствия; «Отмена» закрывает его без запросов, состояние и журнал прежние
    dialog = _open_dismiss_dialog(page, target.id)
    consequences = " ".join(dialog.locator("[data-consequence]").all_inner_texts()).lower()
    for phrase in ("вход закрыт", "уйдёт из всех подразделений", "личные роли будут сняты"):
        assert phrase in consequences, f"в диалоге нет последствия «{phrase}»"
    posts = []
    page.on("request", lambda r: posts.append(r) if r.method == "POST" else None)
    cancel = dialog.locator("button[data-dialog-cancel]")
    expect(cancel).to_contain_text("Отмена")
    cancel.click()
    expect(page.locator('#dialog-root [data-dialog="dismiss"]')).to_have_count(0)
    assert not posts, "«Отмена» отправила запрос"
    page.goto(f"/staff/{target.id}/")
    expect(_card(page, target.id).locator("[data-dismissed-badge]")).to_have_count(0)
    page.goto(f"/staff/?q={target.email}")
    assert helpers.staff_row(page, target.email).get_attribute("data-state") == "active"
    assert helpers_org.audit_rows(page, "user.dismissed", target.id) == []

    # п. 6: администратор жмёт «Уволить» у себя — отказ
    assert _try_dismiss(page, admin_id)
    page.goto(f"/staff/?q={stand_admin.email}")
    assert helpers.staff_row(page, stand_admin.email).get_attribute("data-state") == "active"

    # п. 7: единственный администратор; уволить его пытается другой обладатель права «Управление структурой»
    admin_role = helpers_org.role_id(page, helpers.ADMIN_ROLE)
    page.goto(f"/staff/?role={admin_role}")
    expect(page.locator("tr[data-user-email]")).to_have_count(1)  # в круге администратор один
    role_name = unique_name("Кадры")
    _create_role(page, role_name, ("staff.view", "org.manage"))
    hr = employee()
    _grant_role(page, hr.id, role_name)
    assert _try_dismiss(hr.page, admin_id), "единственного администратора уволили"
    page.goto(f"/staff/{admin_id}/")
    expect(_card(page, admin_id).locator("[data-dismissed-badge]")).to_have_count(0)
    page.goto(f"/staff/?q={stand_admin.email}")
    assert helpers.staff_row(page, stand_admin.email).get_attribute("data-state") == "active"
    assert helpers_org.audit_rows(page, "user.dismissed", admin_id) == []

    # п. 8: сотрудник без права — кнопки нет, диалог и увольнение закрыты (403), запись цела
    plain.page.goto(f"/staff/{target.id}/")
    expect(_card(plain.page, target.id)).to_be_visible()
    expect(plain.page.locator('[data-action="dismiss"]')).to_have_count(0)
    assert helpers_org.direct_get(plain.page, f"/structure/people/{target.id}/dismiss/").status == 403
    assert direct_post(plain.page, f"/structure/people/{target.id}/dismiss/").status == 403
    page.goto(f"/staff/?q={target.email}")
    assert helpers.staff_row(page, target.email).get_attribute("data-state") == "active"
    assert helpers_org.audit_rows(page, "user.dismissed", target.id) == []


def test_o07_blocked_dismissed_and_blocked_head_keeps_structure(admin_page, employee):
    """Сценарий 7, п. 11-12: заблокированную запись можно уволить, она становится «уволен»; заблокированный
    руководитель отдела остаётся участником и руководителем узла, его подчинённый по-прежнему видит его как
    руководителя (FR-124, FR-126)."""
    page = admin_page
    token = secrets.token_hex(3)
    blocked_head = employee(activate=False, full_name=f"Блок{token} Игорь Игоревич")
    member = employee(activate=False, full_name=f"Подчин{token} Анна Андреевна")
    victim = employee(activate=False, full_name=f"Блокуволен{token} Олег Олегович")
    open_structure(page)
    rid = root_id(page)
    unit = create_unit(page, unique_name("Отдел"), kind="department", parent_id=rid)
    add_members(page, unit, [blocked_head.id, member.id], q=token, mode="concurrent")
    set_marks(page, unit, "heads", [blocked_head.id])

    for target in (blocked_head, victim):
        page.goto(f"/staff/{target.id}/")
        helpers.open_security_tab(page)
        form = page.locator('form[action$="/block/"]')
        form.locator("[name=reason]").fill("проверка " + token)
        helpers.submit(form)
        page.goto(f"/staff/?state=blocked&q={target.email}")
        expect(helpers.staff_row(page, target.email)).to_have_count(1)

    # п. 12: блокировка структуру не меняет
    open_structure(page, unit)
    head_row = member_row(page, blocked_head.id, "heads")
    expect(head_row).to_have_count(1)
    expect(head_row).to_have_attribute("data-mark", "head")
    expect(head_row.locator("[data-mark-label]")).to_contain_text("Руководитель")
    page.goto(f"/staff/{blocked_head.id}/")
    expect(_card(page, blocked_head.id).locator('[data-field="units"]')).to_have_attribute("data-empty", "false")
    page.goto(f"/staff/{member.id}/")
    expect(_card(page, member.id).locator('[data-field="head"]')).to_contain_text(f"Блок{token}")

    # п. 11: заблокированную запись увольняют
    _dismiss(page, victim.id)
    page.goto(f"/staff/?state=dismissed&q={victim.email}")
    row = helpers.staff_row(page, victim.email)
    expect(row).to_have_count(1)
    assert row.get_attribute("data-state") == "dismissed"
    page.goto(f"/staff/?state=blocked&q={victim.email}")
    expect(helpers.staff_row(page, victim.email)).to_have_count(0)


def test_o07_no_mail_to_dismissed(admin_page, employee, mailpit):
    """Сценарий 7, п. 9: при увольнении активного сотрудника письмо ему не уходит; почта работает — следующее
    письмо другому адресу доставлено после увольнения (FR-125)."""
    acc = employee()
    before = employee(activate=False)  # письмо-«промывка»: всё, что поставлено в очередь раньше, ушло
    helpers.wait_mail(mailpit, before.email, "invitation", timeout=60)
    seen = helpers.mail_ids(mailpit, acc.email)

    _dismiss(admin_page, acc.id)

    after = employee(activate=False)  # очередь живая: это письмо стоит после возможного письма уволенному
    helpers.wait_mail(mailpit, after.email, "invitation", timeout=60)
    admin_page.wait_for_timeout(3000)
    assert helpers.mail_ids(mailpit, acc.email) == seen, "уволенному ушло письмо"
