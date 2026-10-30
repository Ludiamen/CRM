"""T-7152: сценарий 13 — права «Писать всем» и «Модерировать ленту» (FR-608, FR-610, FR-620, FR-621, FR-639, FR-640).

Общее для файла (шаблон задания e2e/template.md, CONTRACT-007.md разделы 2, 10.1, 10.2, 12, 13, решение 57 задач):
- управляющий — администратор круга `admin_page` (роль «Администратор портала»: страница ролей, журнал); права ролей
  меняются на странице роли `/roles/<id>/` флажками `input[name=permissions]` (как в `test_d08_heads`), без кода;
- «Писать всем» — `feed.post_all`, «Модерировать ленту» — `feed.moderate` (`helpers_feed.POST_ALL`, `MODERATE`); роли
  теста создаёт `helpers_feed.make_role`: пустая — «роль, созданная после установки» и «сотрудник без права»;
- роль, созданная до установки модуля администратором, на сброшенном стенде не воспроизводится — её проверяет серверный
  тест данных установки T-7133; здесь — три начальные роли (решение 57 задач);
- начальная роль «Сотрудник ИТ» общая для всех кругов: тест, снявший с неё «Писать всем», возвращает право в `finally`;
- запрос в обход формы — прямой POST той же формы с токеном CSRF страницы сотрудника (`helpers_org.direct_post`; для
  нескольких значений `to` — тот же запрос с телом, собранным из пар); отказ службы — 200 с `[data-code]`, текст из
  раздела 13 контракта («Писать всем вам не разрешено»), записи нет;
- «пункта «Всем» в «Кому» нет» — в форме записи нет таблетки `[data-to-pill="all"]` (у держателя права она стоит при
  открытии формы, кнопки «Всем» в форме нет) и подсказка не предлагает `all`;
- сброса стенда в файле нет.
"""
import secrets
from urllib.parse import urlencode, urlsplit

from playwright.sync_api import expect

from tests.e2e import helpers, helpers_feed as feed, helpers_org
from tests.e2e.conftest import PORTAL_URL

POST_ALL_TITLE = "Писать всем"
MODERATE_TITLE = "Модерировать ленту"
DENIED_TEXT = "Писать всем вам не разрешено"
ALL_PILL = '[data-to-pill="all"]'
FORM = "form#feed-form"
DELETE = 'button[data-action="post-delete"]'
IT_STAFF = helpers.STAFF_ROLE  # «Сотрудник ИТ»


# --- Общие помощники файла ------------------------------------------------------------------------------------

def _marker() -> str:
    return f"Права{secrets.token_hex(4)}"


def _token() -> str:
    return secrets.token_hex(3)


def _person(employee, token: str, surname: str, **kwargs):
    """Сотрудник с ФИО `<Фамилия><token> Иван Иванович`: общий `token` находит всех одним запросом `add_members`."""
    return employee(full_name=f"{surname}{token} Иван Иванович", **kwargs)


def _unit_with(page, members, token: str) -> tuple:
    """Отдел под корнем с участниками `members`; возвращает `(номер, название)`."""
    helpers_org.open_structure(page)
    name = helpers_org.unique_name("Отдел")
    unit_id = helpers_org.create_unit(page, name, kind="department", parent_id=helpers_org.root_id(page))
    helpers_org.add_members(page, unit_id, [m.id for m in members], q=token, mode="concurrent")
    return unit_id, name


def _set_permission(page, role_id, code: str, *, on: bool) -> None:
    """Включает или снимает право роли на `/roles/<id>/` и сохраняет."""
    page.goto(f"/roles/{role_id}/")
    box = page.locator(f'input[name=permissions][value="{code}"]')
    expect(box).to_have_count(1)
    box.set_checked(on)
    with page.expect_navigation():
        page.locator("form:has(input[name=permissions]) button[type=submit]").first.click()
    page.wait_for_load_state()


def _permission_checked(page, role_id, code: str) -> bool:
    page.goto(f"/roles/{role_id}/")
    box = page.locator(f'input[name=permissions][value="{code}"]')
    expect(box).to_have_count(1)
    return box.is_checked()


def _open(new_context, account):
    """Вкладка сотрудника на главной (лента готова, `#feed-live[data-ws="open"]`)."""
    return feed.open_feed(new_context(), account)


def _refusal_response(response, code: str) -> None:
    body = response.text()
    assert response.status == 200, f"отказ службы — 200, получен {response.status}"
    assert f'data-code="{code}"' in body, f"в ответе нет отказа {code}"


def _post_pairs(page, path: str, pairs):
    """Прямой POST формы с несколькими значениями одного поля (`to`): тело собрано из пар; заголовки, токен CSRF и
    запрет переходов — как у `helpers_org.direct_post`."""
    origin = "{0.scheme}://{0.netloc}".format(urlsplit(PORTAL_URL))
    return page.request.post(path, data=urlencode(pairs), max_redirects=0, headers={
        "X-CSRFToken": helpers_org.csrf_token(page), "Referer": origin + "/", "Origin": origin,
        "Content-Type": "application/x-www-form-urlencoded"})


def _clear_roles(page, account) -> None:
    """Снимает у сотрудника все роли карточки `/staff/<id>/` (форма `form[action$="/roles/"]`)."""
    page.goto(f"/staff/{account.id}/")
    form = page.locator('form[action$="/roles/"]')
    for box in form.locator("input[name=roles]").all():
        box.set_checked(False)
    with page.expect_navigation():
        form.locator("button[type=submit]").click()
    page.wait_for_load_state()
    page.goto(f"/staff/{account.id}/")
    assert not any(box.is_checked() for box in page.locator('form[action$="/roles/"] input[name=roles]').all()), \
        "роли сотрудника не сняты"


def _to_pills(page):
    return page.locator(f"{FORM} [data-to-pill]")


def _no_all_option(page) -> None:
    """В форме нет таблетки «Всем», и подсказка «Кому» на слово «Все» не предлагает `all`."""
    expect(page.locator(FORM)).to_be_visible()
    expect(page.locator(f"{FORM} {ALL_PILL}")).to_have_count(0)
    field = page.locator(f'{FORM} input[data-feed-picker="to"]')
    field.fill("")
    field.press_sequentially("Все", delay=30)
    expect(page.locator('[data-feed-pick-list] [data-pick-value="all"]')).to_have_count(0)
    field.fill("")


# --- Права после установки (сценарий 13, п. 1) -----------------------------------------------------------------

def test_f13_roles_page_after_install_shows_post_all_at_three_starter_roles_and_moderate_only_at_portal_admin(
        admin_page):
    """Сценарий 13, п. 1: «Писать всем» отмечено у «Администратора портала», «Руководителя» и «Сотрудника ИТ»;
    «Модерировать ленту» — только у «Администратора портала» (FR-640)."""
    page = admin_page
    for name in helpers.DEFAULT_ROLES:
        role_id = helpers_org.role_id(page, name)
        assert _permission_checked(page, role_id, feed.POST_ALL), f"у роли «{name}» нет «{POST_ALL_TITLE}»"
        expected = name == helpers.ADMIN_ROLE
        assert _permission_checked(page, role_id, feed.MODERATE) is expected, \
            f"«{MODERATE_TITLE}» у роли «{name}»: ожидалось {expected}"


# --- «Писать всем»: форма и обход формы (п. 2) ------------------------------------------------------------------

def test_f13_it_staff_role_without_post_all_has_no_all_option_in_to_but_units_and_people(
        admin_page, employee, new_context):
    """Сценарий 13, п. 2: с роли «Сотрудник ИТ» снято «Писать всем» — у сотрудника с этой ролью в «Кому» пункта «Всем»
    нет, а подразделения и люди доступны (запись отделу и человеку публикуется); запрос с «Всем» в обход формы
    отклонён (FR-610, FR-640)."""
    page = admin_page
    token = _token()
    staff = _person(employee, token, "Итов")
    other = _person(employee, token, "Адресатов")
    _, unit_name = _unit_with(page, [other], token)
    role_id = helpers_org.role_id(page, IT_STAFF)
    _set_permission(page, role_id, feed.POST_ALL, on=False)
    try:
        staff_page = _open(new_context, staff)
        _no_all_option(staff_page)
        marker = _marker()
        post_id = feed.publish(staff_page, f"{marker} отделу и человеку",
                               to=[("unit", unit_name), ("person", other.full_name)])
        expect(staff_page.locator(f"#feed-post-{post_id}")).to_be_visible()

        response = helpers_org.direct_post(staff_page, "/feed/posts/", {"kind": "post", "text": f"{marker} обход", "to": "all"})
        _refusal_response(response, "post_all_denied")
        assert DENIED_TEXT in response.text()
        staff_page.goto("/")
        expect(staff_page.locator("#feed-list")).not_to_contain_text(f"{marker} обход")
    finally:
        _set_permission(page, role_id, feed.POST_ALL, on=True)


def test_f13_new_post_to_all_sent_bypassing_form_without_post_all_is_refused(admin_page, employee, new_context):
    """Сценарий 13, п. 2: новая запись «Всем», отправленная в обход формы сотрудником без «Писать всем», отклонена —
    «Писать всем вам не разрешено» у поля «Кому», записи нет ни у автора, ни у администратора (FR-610)."""
    page = admin_page
    role = feed.make_role(page)
    staff = employee(role=role)
    staff_page = _open(new_context, staff)
    marker = _marker()
    response = helpers_org.direct_post(staff_page, "/feed/posts/", {"kind": "post", "text": f"{marker} всем", "to": "all"})
    _refusal_response(response, "post_all_denied")
    body = response.text()
    assert DENIED_TEXT in body
    assert 'data-error="to"' in body, "отказ не у поля «Кому»"
    staff_page.goto("/")
    expect(staff_page.locator("#feed-list")).not_to_contain_text(marker)
    page.goto("/")
    expect(page.locator("#feed-list")).not_to_contain_text(marker)


# --- Журнал ролей (п. 3) ------------------------------------------------------------------------------------------

def test_f13_role_rights_change_appears_in_roles_journal_as_before_after(admin_page):
    """Сценарий 13, п. 3: изменение прав роли — в журнале ролей `role.updated` с «было / стало»: выдача «Писать всем»,
    затем «Модерировать ленту» (FR-639)."""
    page = admin_page
    name = feed.make_role(page)
    role_id = helpers_org.role_id(page, name)
    _set_permission(page, role_id, feed.POST_ALL, on=True)
    was, became = helpers_org.audit_sides(page, "role.updated", object_id=role_id)[0]
    assert POST_ALL_TITLE not in was, f"«было»: {was!r}"
    assert POST_ALL_TITLE in became, f"«стало»: {became!r}"

    _set_permission(page, role_id, feed.MODERATE, on=True)
    was, became = helpers_org.audit_sides(page, "role.updated", object_id=role_id)[0]
    assert POST_ALL_TITLE in was and MODERATE_TITLE not in was, f"«было»: {was!r}"
    assert POST_ALL_TITLE in became and MODERATE_TITLE in became, f"«стало»: {became!r}"

    _set_permission(page, role_id, feed.POST_ALL, on=False)
    was, became = helpers_org.audit_sides(page, "role.updated", object_id=role_id)[0]
    assert POST_ALL_TITLE in was and POST_ALL_TITLE not in became, f"снятие: {was!r} → {became!r}"


# --- «Модерировать ленту» (п. 4) ------------------------------------------------------------------------------

def test_f13_employee_without_moderate_right_sees_no_delete_on_others_post(admin_page, employee, new_context):
    """Сценарий 13, п. 4: сотрудник без «Модерировать ленту» открывает чужую запись — «Удалить» ему не показано, а
    прямой запрос удаления — 403 и запись остаётся; у автора «Удалить» есть (контроль) (FR-621, FR-640)."""
    page = admin_page
    writer = employee(role=feed.make_role(page, [feed.POST_ALL]))
    reader = employee(role=feed.make_role(page))
    writer_page = _open(new_context, writer)
    post_id = feed.publish(writer_page, f"{_marker()} чужая запись")
    expect(writer_page.locator(f"#feed-post-{post_id} {DELETE}")).to_have_count(1)  # контроль: у автора есть

    reader_page = _open(new_context, reader)
    expect(reader_page.locator(f"#feed-post-{post_id}")).to_be_visible()
    expect(reader_page.locator(f"#feed-post-{post_id} {DELETE}")).to_have_count(0)
    reader_page.goto(f"/feed/{post_id}/")
    expect(reader_page.locator(f"#feed-post-{post_id}")).to_be_visible()
    expect(reader_page.locator(f"#feed-post-{post_id} {DELETE}")).to_have_count(0)
    response = helpers_org.direct_post(reader_page, f"/feed/{post_id}/delete/")
    assert response.status == 403, f"удаление чужой записи без права: ожидался 403, получен {response.status}"
    assert helpers_org.direct_get(writer_page, f"/feed/{post_id}/").status == 200


def test_f13_moderate_right_given_to_role_in_interface_shows_delete_on_others_post(admin_page, employee, new_context):
    """Сценарий 13: администратор отмечает «Модерировать ленту» у роли на странице ролей — у сотрудника с этой ролью
    на чужой записи появляется «Удалить» (до выдачи его не было) (FR-621, FR-640)."""
    page = admin_page
    writer = employee(role=feed.make_role(page, [feed.POST_ALL]))
    role = feed.make_role(page)
    role_id = helpers_org.role_id(page, role)
    moderator = employee(role=role)
    writer_page = _open(new_context, writer)
    post_id = feed.publish(writer_page, f"{_marker()} запись для модератора")

    mod_page = _open(new_context, moderator)
    expect(mod_page.locator(f"#feed-post-{post_id}")).to_be_visible()
    expect(mod_page.locator(f"#feed-post-{post_id} {DELETE}")).to_have_count(0)

    _set_permission(page, role_id, feed.MODERATE, on=True)
    mod_page.goto("/")
    expect(mod_page.locator(f"#feed-post-{post_id}")).to_be_visible()
    expect(mod_page.locator(f"#feed-post-{post_id} {DELETE}")).to_have_count(1)


# --- Роль после установки и сотрудник без ролей (п. 5) -----------------------------------------------------------

def test_f13_role_created_after_install_has_no_post_all_until_it_is_checked(admin_page, employee, new_context):
    """Сценарий 13, п. 5: роль, созданная после установки модуля, права «Писать всем» не имеет — на странице роли
    флажок не отмечен, в «Кому» сотрудника «Всем» нет; после отметки галочкой «Всем» в форме появляется (FR-640)."""
    page = admin_page
    role = feed.make_role(page)
    role_id = helpers_org.role_id(page, role)
    assert not _permission_checked(page, role_id, feed.POST_ALL), "новая роль получила «Писать всем» сама"
    staff = employee(role=role)
    staff_page = _open(new_context, staff)
    _no_all_option(staff_page)

    _set_permission(page, role_id, feed.POST_ALL, on=True)
    assert _permission_checked(page, role_id, feed.POST_ALL)
    staff_page.goto("/")
    expect(staff_page.locator(f"{FORM} {ALL_PILL}")).to_have_count(1)


def test_f13_employee_without_roles_has_no_all_option_but_publishes_to_unit_and_people(
        admin_page, employee, new_context):
    """Сценарий 13, п. 5: у сотрудника без ролей пункта «Всем» в «Кому» нет, но запись подразделению и человеку он
    публикует (FR-608, FR-610, FR-640)."""
    page = admin_page
    token = _token()
    loner = _person(employee, token, "Безролев")
    other = _person(employee, token, "Получателев")
    _, unit_name = _unit_with(page, [other], token)
    _clear_roles(page, loner)
    loner_page = _open(new_context, loner)
    _no_all_option(loner_page)
    marker = _marker()
    unit_post = feed.publish(loner_page, f"{marker} отделу", to=[("unit", unit_name)])
    person_post = feed.publish(loner_page, f"{marker} человеку", to=[("person", other.full_name)])
    expect(loner_page.locator(f"#feed-post-{unit_post}")).to_be_visible()
    expect(loner_page.locator(f"#feed-post-{person_post}")).to_be_visible()
    other_page = _open(new_context, other)
    expect(other_page.locator(f"#feed-post-{unit_post}")).to_be_visible()
    expect(other_page.locator(f"#feed-post-{person_post}")).to_be_visible()


# --- Правка (п. 6) и снятие права с опубликованным «Всем» ------------------------------------------------------

def test_f13_adding_all_to_own_unit_post_bypassing_form_without_post_all_is_refused(
        admin_page, employee, new_context):
    """Сценарий 13, п. 6: сотрудник без «Писать всем» правит свою запись отделу и добавляет «Всем» в «Кому» запросом
    в обход формы — правка отклонена (отказ «Писать всем вам не разрешено»), «Кому» остаётся прежним (FR-610, FR-620)."""
    page = admin_page
    token = _token()
    author = _person(employee, token, "Правщиков", role=feed.make_role(page))
    member = _person(employee, token, "Участников")
    _, unit_name = _unit_with(page, [member], token)
    author_page = _open(new_context, author)
    marker = _marker()
    post_id = feed.publish(author_page, f"{marker} отделу", to=[("unit", unit_name)])

    author_page.goto(f"/feed/{post_id}/edit/")
    expect(author_page.locator('[data-feed-page="edit"]')).to_be_visible()
    saved = author_page.locator('[data-feed-page="edit"] input[name="to"]').evaluate_all("els => els.map(e => e.value)")
    assert saved, "в форме правки нет сохранённых адресатов"
    pairs = [("kind", "post"), ("text", f"{marker} с добавленным «Всем»")] + [("to", v) for v in saved] + [("to", "all")]
    response = _post_pairs(author_page, f"/feed/{post_id}/edit/", pairs)
    _refusal_response(response, "post_all_denied")
    assert DENIED_TEXT in response.text()

    author_page.goto(f"/feed/{post_id}/")
    expect(author_page.locator(f"#feed-post-{post_id}-to")).to_contain_text(unit_name)
    expect(author_page.locator(f"#feed-post-{post_id}-to")).not_to_contain_text("Всем")
    expect(author_page.locator(f"#feed-post-{post_id}-body")).not_to_contain_text("с добавленным")


def test_f13_removing_post_all_keeps_earlier_post_to_all_visible_and_author_edits_it_keeping_all(
        admin_page, employee, new_context):
    """Сценарий 13 (FR-640): снятие «Писать всем» опубликованные записи «Всем» не отзывает — запись остаётся видна
    читателю, автор правит её как свою, и «Всем» в её «Кому» остаётся; в новой форме «Всем» у автора уже нет
    (FR-620, FR-640)."""
    page = admin_page
    role = feed.make_role(page, [feed.POST_ALL])
    role_id = helpers_org.role_id(page, role)
    writer = employee(role=role)
    reader = employee(role=feed.make_role(page))
    writer_page = _open(new_context, writer)
    marker = _marker()
    post_id = feed.publish(writer_page, f"{marker} исходная запись")
    expect(writer_page.locator(f"#feed-post-{post_id}-to")).to_contain_text("Всем")

    _set_permission(page, role_id, feed.POST_ALL, on=False)
    reader_page = _open(new_context, reader)
    expect(reader_page.locator(f"#feed-post-{post_id}")).to_be_visible()

    writer_page.goto("/")  # новая форма: «Всем» у автора больше нет
    expect(writer_page.locator(f"{FORM} {ALL_PILL}")).to_have_count(0)
    writer_page.goto(f"/feed/{post_id}/edit/")
    expect(writer_page.locator('[data-feed-page="edit"]')).to_be_visible()
    form = writer_page.locator('[data-feed-page="edit"] form').first
    form.locator('textarea[name="text"]').fill(f"{marker} исправленная запись")
    with writer_page.expect_response(lambda r: r.request.method == "POST" and f"/feed/{post_id}/edit/" in r.url):
        form.locator('button:not([type="button"])').first.click()
    writer_page.wait_for_load_state()

    writer_page.goto(f"/feed/{post_id}/")
    expect(writer_page.locator(f"#feed-post-{post_id}-body")).to_contain_text("исправленная запись")
    expect(writer_page.locator(f"#feed-post-{post_id}-to")).to_contain_text("Всем")
    reader_page.goto(f"/feed/{post_id}/")
    expect(reader_page.locator(f"#feed-post-{post_id}-body")).to_contain_text("исправленная запись")
    expect(reader_page.locator(f"#feed-post-{post_id}-to")).to_contain_text("Всем")
